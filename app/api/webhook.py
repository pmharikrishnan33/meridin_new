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
from app.models.schemas import (
    IncomingWhatsAppWebhook,
    MessageType,
)
from app.services.message_service import (
    DuplicateWhatsAppMessage,
    message_service,
)
from app.services.whatsapp_inbound import (
    normalize_whatsapp_message,
)
from app.services.whatsapp_service import (
    whatsapp_sender,
)
from app.utils.logger import logger


router = APIRouter(tags=["messages"])


class ChatResponse(BaseModel):
    conversation_id: str
    intent: str
    confidence: float
    entities: Dict[str, Any]
    response: Dict[str, Any]


def _tenant_message_settings(tenant) -> Dict[str, Any]:
    """
    Return only non-sensitive tenant settings needed by
    message handlers.
    """

    return {
        "business_name": tenant.business_name,
        "welcome_message": tenant.welcome_message,
        "fallback_message": tenant.fallback_message,
        "feature_flags": tenant.feature_flags.model_dump(),
    }


def _to_chat_response(result) -> ChatResponse:
    """
    Convert MessageService result into the webhook response format.
    """

    entities: Dict[str, Any] = {}

    for entity in result.understanding.entities:

        entities.setdefault(
            entity.entity_type.value,
            entity.normalized_value or entity.value,
        )

    return ChatResponse(
        conversation_id=result.conversation_id,
        intent=result.understanding.intent.value,
        confidence=result.understanding.intent_confidence,
        entities=entities,
        response=result.response.model_dump(),
    )


@router.get("/webhook")
async def verify_webhook(
    mode: Optional[str] = Query(
        default=None,
        alias="hub.mode",
    ),
    verify_token: Optional[str] = Query(
        default=None,
        alias="hub.verify_token",
    ),
    challenge: Optional[str] = Query(
        default=None,
        alias="hub.challenge",
    ),
):
    """
    Perform Meta's WhatsApp webhook verification handshake.
    """

    if not (
        mode == "subscribe"
        and verify_token is not None
        and challenge is not None
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Webhook verification failed",
        )

    # ---------------------------------------------------------
    # 1. Shared environment verify token
    # ---------------------------------------------------------

    if (
        settings.WHATSAPP_VERIFY_TOKEN
        and verify_token
        == settings.WHATSAPP_VERIFY_TOKEN
    ):
        return PlainTextResponse(challenge)

    # ---------------------------------------------------------
    # 2. Tenant-specific verify token
    # ---------------------------------------------------------

    from app.repositories.tenant_repository import (
        tenant_repository,
    )

    tenant = (
        await tenant_repository.verify_verify_token(
            verify_token
        )
    )

    if tenant is not None:
        return PlainTextResponse(challenge)

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=(
            "Webhook verification failed: "
            "verify token mismatch"
        ),
    )


@router.post(
    "/webhook",
    status_code=status.HTTP_200_OK,
)
async def receive_whatsapp_webhook(
    request: Request,
    x_tenant_id: Optional[str] = Header(
        default=None,
        alias="x-tenant-id",
    ),
    x_whatsapp_phone_number_id: Optional[str] = Header(
        default=None,
        alias="x-whatsapp-phone-number-id",
    ),
    x_whatsapp_access_token: Optional[str] = Header(
        default=None,
        alias="x-whatsapp-access-token",
    ),
    x_hub_signature_256: Optional[str] = Header(
        default=None,
        alias="x-hub-signature-256",
    ),
) -> Dict[str, Any]:

    """
    Accept WhatsApp webhook notifications and process
    supported messages.

    Supported inbound message types currently include:

    - text
    - interactive button replies
    - interactive list replies

    The message is normalized before reaching MessageService.

    Important:

    A message is processed exactly ONCE here.
    """

    # =========================================================
    # 1. RATE LIMIT
    # =========================================================

    await rate_limiter.check(request)

    # =========================================================
    # 2. READ RAW BODY
    # =========================================================

    raw_body = await request.body()

    # =========================================================
    # 3. BODY SIZE
    # =========================================================

    check_body_size(raw_body)

    # =========================================================
    # 4. TENANT RESOLUTION
    # =========================================================

    metadata_phone_number_id = (
        _extract_metadata_phone_number_id(
            raw_body
        )
    )

    (
        tenant,
        resolved_phone_number_id,
        resolved_access_token,
    ) = await resolve_tenant_credentials(
        x_whatsapp_phone_number_id,
        metadata_phone_number_id,
    )

    if (
        tenant is None
        or not tenant.tenant_id
    ):

        logger.warning(
            "Rejected webhook because no canonical "
            "tenant could be resolved."
        )

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Unknown or unconfigured "
                "WhatsApp tenant."
            ),
        )

    # =========================================================
    # 5. SIGNATURE VERIFICATION
    # =========================================================

    verify_tenant_signature(
        raw_body,
        x_hub_signature_256,
        tenant,
    )

    # =========================================================
    # 6. PARSE JSON
    # =========================================================

    try:

        payload = await request.json()

    except Exception:

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Request body is not valid JSON."
            ),
        )

    if not isinstance(payload, dict):

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Webhook payload must be "
                "a JSON object."
            ),
        )

    # =========================================================
    # 7. STRUCTURAL VALIDATION
    # =========================================================

    try:

        validated = (
            IncomingWhatsAppWebhook(
                **payload
            )
        )

    except ValidationError as exc:

        logger.info(
            "Rejected malformed webhook payload: %s",
            exc,
        )

        raise HTTPException(
            status_code=(
                status.HTTP_422_UNPROCESSABLE_ENTITY
            ),
            detail=(
                "Malformed webhook payload."
            ),
        )

    # =========================================================
    # 8. PROCESS
    # =========================================================

    processed: list[Dict[str, Any]] = []

    # Use the validated payload instead of
    # going back to the raw dictionary.

    for entry in validated.entry:

        for change in entry.changes:

            value = change.value

            metadata = (
                value.metadata
            )

            message_phone_number_id = (
                metadata.phone_number_id
            )

            # -------------------------------------------------
            # PHONE NUMBER VALIDATION
            # -------------------------------------------------

            if (
                message_phone_number_id
                != tenant.phone_number_id
            ):

                logger.warning(
                    "Rejected webhook change with "
                    "mismatched phone number metadata."
                )

                continue

            resolved_tenant_id = (
                tenant.tenant_id
            )

            # -------------------------------------------------
            # MESSAGES
            # -------------------------------------------------

            for message in (
                value.messages or []
            ):

                # =============================================
                # NORMALIZE
                # =============================================

                # Pydantic model → dictionary
                message_data = (
                    message.model_dump(
                        exclude_none=True
                    )
                    if hasattr(
                        message,
                        "model_dump",
                    )
                    else message
                )

                normalized = (
                    normalize_whatsapp_message(
                        message_data
                    )
                )

                if not normalized:

                    logger.info(
                        "Ignoring unsupported "
                        "WhatsApp message."
                    )

                    continue

                sender = normalized[
                    "user_id"
                ]

                text = normalized[
                    "text"
                ]

                whatsapp_message_id = (
                    normalized[
                        "whatsapp_message_id"
                    ]
                )

                # =============================================
                # PROCESS EXACTLY ONCE
                # =============================================

                try:

                    result = (
                        await message_service.process(
                            tenant_id=str(
                                resolved_tenant_id
                            ),

                            user_id=str(
                                sender
                            ),

                            text=text,

                            tenant_settings=(
                                _tenant_message_settings(
                                    tenant
                                )
                            ),

                            whatsapp_message_id=(
                                whatsapp_message_id
                            ),

                            message_type=MessageType(
                                normalized[
                                    "message_type"
                                ]
                            ),

                            inbound_metadata=(
                                normalized.get(
                                    "metadata",
                                    {},
                                )
                            ),
                        )
                    )

                except DuplicateWhatsAppMessage:

                    logger.info(
                        "Duplicate WhatsApp message "
                        "ignored: %s",
                        whatsapp_message_id,
                    )

                    processed.append(
                        {
                            "status":
                                "duplicate",

                            "whatsapp_message_id":
                                whatsapp_message_id,
                        }
                    )

                    continue

                # =============================================
                # CONVERT RESPONSE
                # =============================================

                chat_response = (
                    _to_chat_response(
                        result
                    )
                )

                response_data = (
                    chat_response.model_dump()
                )

                # =============================================
                # SEND TO WHATSAPP
                # =============================================

                phone_number_id = (
                    resolved_phone_number_id
                )

                access_token = (
                    resolved_access_token
                )

                if (
                    phone_number_id
                    and access_token
                ):

                    try:

                        await (
                            whatsapp_sender
                            .send_bot_response(
                                phone_number_id=(
                                    phone_number_id
                                ),

                                access_token=(
                                    access_token
                                ),

                                to=str(
                                    sender
                                ),

                                response=(
                                    result.response
                                ),
                            )
                        )

                        response_data[
                            "delivery_status"
                        ] = "sent"

                    except Exception as exc:

                        logger.error(
                            "Failed to send "
                            "WhatsApp reply: %s",
                            exc,
                        )

                        response_data[
                            "delivery_status"
                        ] = "failed"

                else:

                    response_data[
                        "delivery_status"
                    ] = "not_sent"

                # =============================================
                # ADD ONCE
                # =============================================

                processed.append(
                    response_data
                )

    return {
        "status": "accepted",
        "processed": processed,
    }


# =====================================================================
# HELPERS
# =====================================================================


def _extract_metadata_phone_number_id(
    raw_body: bytes,
) -> Optional[str]:
    """
    Best-effort extraction of
    metadata.phone_number_id from raw body.

    Used to resolve the tenant before the JSON
    payload is structurally validated.
    """

    try:

        payload = json.loads(
            raw_body
        )

        if not isinstance(
            payload,
            dict,
        ):
            return None

        entries = payload.get(
            "entry",
            [],
        )

        if not entries:
            return None

        changes = entries[0].get(
            "changes",
            [],
        )

        if not changes:
            return None

        value = changes[0].get(
            "value",
            {},
        )

        metadata = value.get(
            "metadata",
            {},
        )

        return metadata.get(
            "phone_number_id"
        )

    except (
        ValueError,
        IndexError,
        TypeError,
        AttributeError,
    ):

        return None