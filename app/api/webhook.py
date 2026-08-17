"""HTTP endpoints for local chat integration and WhatsApp webhook ingestion."""

import json
from typing import Any, Dict, Optional

from fastapi import APIRouter, Header, HTTPException, Query, Request, status
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, ValidationError

from app.api.security import (
    check_body_size,
    rate_limiter,
    resolve_tenant_credentials,
    verify_tenant_signature,
)
from app.core.config import settings
from app.models.schemas import IncomingWhatsAppWebhook
from app.services.message_service import message_service
from app.services.whatsapp_service import whatsapp_sender
from app.utils.logger import logger


router = APIRouter(tags=["messages"])


class ChatResponse(BaseModel):
    conversation_id: str
    intent: str
    confidence: float
    entities: Dict[str, Any]
    response: Dict[str, Any]


def _tenant_message_settings(tenant) -> Dict[str, Any]:
    """Return only non-sensitive tenant settings needed by message handlers."""
    return {
        "business_name": tenant.business_name,
        "welcome_message": tenant.welcome_message,
        "fallback_message": tenant.fallback_message,
        "feature_flags": tenant.feature_flags.model_dump(),
    }


def _to_chat_response(result) -> ChatResponse:
    entities = {}
    for entity in result.understanding.entities:
        entities.setdefault(entity.entity_type.value, entity.normalized_value or entity.value)
    return ChatResponse(
        conversation_id=result.conversation_id,
        intent=result.understanding.intent.value,
        confidence=result.understanding.intent_confidence,
        entities=entities,
        response=result.response.model_dump(),
    )


@router.get("/webhook")
async def verify_webhook(
    mode: Optional[str] = Query(default=None, alias="hub.mode"),
    verify_token: Optional[str] = Query(default=None, alias="hub.verify_token"),
    challenge: Optional[str] = Query(default=None, alias="hub.challenge"),
):
    """Perform Meta's WhatsApp webhook verification handshake.

    Accepts a verify token from the shared environment config **or** from a
    tenant record stored in MongoDB, enabling per-tenant webhook configuration.
    """
    if not (mode == "subscribe" and verify_token is not None and challenge is not None):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Webhook verification failed",
        )

    # 1. Check shared environment config
    if settings.WHATSAPP_VERIFY_TOKEN and verify_token == settings.WHATSAPP_VERIFY_TOKEN:
        return PlainTextResponse(challenge)

    # 2. Check per-tenant config in MongoDB
    from app.repositories.tenant_repository import tenant_repository

    tenant = await tenant_repository.verify_verify_token(verify_token)
    if tenant is not None:
        return PlainTextResponse(challenge)

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Webhook verification failed: verify token mismatch",
    )


@router.post("/webhook", status_code=status.HTTP_200_OK)
async def receive_whatsapp_webhook(
    request: Request,
    x_tenant_id: Optional[str] = Header(default=None, alias="x-tenant-id"),
    x_whatsapp_phone_number_id: Optional[str] = Header(
        default=None, alias="x-whatsapp-phone-number-id"
    ),
    x_whatsapp_access_token: Optional[str] = Header(
        default=None, alias="x-whatsapp-access-token"
    ),
    x_hub_signature_256: Optional[str] = Header(
        default=None, alias="x-hub-signature-256"
    ),
) -> Dict[str, Any]:
    """Accept WhatsApp text notifications and process each message.

    Pipeline order (fail-fast, cheapest checks first):

    1. **Rate limit** – reject callers that exceed the request threshold.
    2. **Read raw body** – drain the body once so the signature covers the
       exact bytes Meta sent.
    3. **Size guard** – reject oversized payloads *before* any verification
       so attackers can't exhaust CPU with huge bodies.
    4. **Tenant resolution** – resolve per-tenant credentials from MongoDB
       so the correct per-tenant secret is used for signing.
    5. **Signature verification** – verify ``X-Hub-Signature-256`` with the
       shared or per-tenant secret.
    6. **Structural validation** – parse JSON and validate against the
       :class:`~app.models.schemas.IncomingWhatsAppWebhook` model so that
       malformed payloads are rejected with a 422.

    When ``x_whatsapp_phone_number_id`` and ``x_whatsapp_access_token``
    headers are provided (or the tenant has credentials in the database),
    the generated response is sent back to Meta via the WhatsApp Cloud API.
    Otherwise the response is returned in the HTTP body for the caller to
    handle.
    """
    # ------------------------------------------------------------------
    # 1. Rate limiting
    # ------------------------------------------------------------------
    await rate_limiter.check(request)

    # ------------------------------------------------------------------
    # 2. Read raw body (must happen before request.json())
    # ------------------------------------------------------------------
    raw_body = await request.body()

    # ------------------------------------------------------------------
    # 3. Body-size guard (before signature — cheapest rejection first)
    # ------------------------------------------------------------------
    check_body_size(raw_body)

    # ------------------------------------------------------------------
    # 4. Tenant resolution (for per-tenant signature secret + credentials)
    # ------------------------------------------------------------------
    # Try to resolve a tenant early using header values so the correct
    # per-tenant secret can be used for signature verification.
    metadata_phone_number_id = _extract_metadata_phone_number_id(raw_body)
    tenant, resolved_phone_number_id, resolved_access_token = await resolve_tenant_credentials(
        x_whatsapp_phone_number_id, metadata_phone_number_id
    )

    if tenant is None or not tenant.tenant_id:
        logger.warning("Rejected webhook because no canonical tenant could be resolved.")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Unknown or unconfigured WhatsApp tenant.",
        )

    # ------------------------------------------------------------------
    # 5. Signature verification (per-tenant when resolvable)
    # ------------------------------------------------------------------
    verify_tenant_signature(raw_body, x_hub_signature_256, tenant)

    # ------------------------------------------------------------------
    # 5. Parse + structural validation
    # ------------------------------------------------------------------
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Request body is not valid JSON.",
        )

    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Webhook payload must be a JSON object.",
        )

    try:
        validated = IncomingWhatsAppWebhook(**payload)
    except ValidationError as exc:
        logger.info(f"Rejected malformed webhook payload: {exc}")
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Malformed webhook payload.",
        )

    # ------------------------------------------------------------------
    # 6. Process messages
    # ------------------------------------------------------------------
    processed: list[Dict[str, Any]] = []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            metadata = value.get("metadata", {})
            message_phone_number_id = metadata.get("phone_number_id")
            if message_phone_number_id != tenant.phone_number_id:
                logger.warning("Rejected webhook change with mismatched phone number metadata.")
                continue
            resolved_tenant_id = tenant.tenant_id
            for message in value.get("messages", []):
                text = (message.get("text") or {}).get("body")
                sender = message.get("from")
                if not resolved_tenant_id or not sender or not text:
                    continue

                result = await message_service.process(
                    tenant_id=str(resolved_tenant_id),
                    user_id=str(sender),
                    text=text,
                    tenant_settings=_tenant_message_settings(tenant),
                )

                chat_response = _to_chat_response(result)
                processed.append(chat_response.model_dump())

                # Attempt to send the reply back to WhatsApp
                phone_number_id = resolved_phone_number_id
                access_token = resolved_access_token

                if phone_number_id and access_token:
                    try:
                        await whatsapp_sender.send_bot_response(
                            phone_number_id=phone_number_id,
                            access_token=access_token,
                            to=str(sender),
                            response=result.response,
                        )
                    except Exception as exc:
                        logger.error(f"Failed to send WhatsApp reply: {exc}")
                        processed[-1]["delivery_status"] = "failed"

    return {"status": "accepted", "processed": processed}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_metadata_phone_number_id(raw_body: bytes) -> Optional[str]:
    """Best-effort extraction of ``metadata.phone_number_id`` from raw body.

    Used to resolve the tenant *before* the JSON is validated, so the correct
    per-tenant signature secret can be used for verification.
    """
    try:
        payload = json.loads(raw_body)
        if isinstance(payload, dict):
            return (
                payload.get("entry", [{}])[0]
                .get("changes", [{}])[0]
                .get("value", {})
                .get("metadata", {})
                .get("phone_number_id")
            )
    except (ValueError, IndexError, TypeError):
        pass
    return None
