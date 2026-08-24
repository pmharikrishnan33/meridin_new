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
    Tenant,
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

    Supported inbound message types:

    - text
    - interactive button replies
    - interactive list replies

    Processing flow:

        raw body
            ↓
        body-size validation
            ↓
        extract phone_number_id
            ↓
        resolve tenant
            ↓
        tenant/IP rate limit
            ↓
        HMAC verification
            ↓
        JSON validation
            ↓
        message normalization
            ↓
        MessageService
            ↓
        save outbound message as pending
            ↓
        WhatsAppSender
            ↓
        Meta
            ↓
        mark outbound message sent/failed
    """

    # =========================================================
    # 1. READ RAW BODY
    # =========================================================

    raw_body = await request.body()

    check_body_size(raw_body)

    # =========================================================
    # 2. EXTRACT PHONE NUMBER ID
    # =========================================================

    metadata_phone_number_id = (
        _extract_metadata_phone_number_id(
            raw_body
        )
    )

    # =========================================================
    # 3. RESOLVE TENANT
    # =========================================================

    (
        tenant,
        resolved_phone_number_id,
        resolved_access_token,
    ) = await resolve_tenant_credentials(
        x_whatsapp_phone_number_id,
        metadata_phone_number_id,
    )

    # =========================================================
    # 4. RATE LIMIT
    # =========================================================

    rate_limit_tenant_id = (
        tenant.tenant_id
        if tenant is not None
        else (
            metadata_phone_number_id
            or x_tenant_id
            or "default"
        )
    )

    await rate_limiter.check(
        request,
        tenant_id=str(
            rate_limit_tenant_id
        ),
    )

    # =========================================================
    # 5. VERIFY SIGNATURE
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
        payload = json.loads(
            raw_body
        )

    except (ValueError, TypeError):
        raise HTTPException(
            status_code=(
                status.HTTP_400_BAD_REQUEST
            ),
            detail=(
                "Request body is not valid JSON."
            ),
        )

    if not isinstance(
        payload,
        dict,
    ):
        raise HTTPException(
            status_code=(
                status.HTTP_400_BAD_REQUEST
            ),
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
            "Rejected malformed webhook "
            "payload: %s",
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
    # 8. TENANT FALLBACK
    # =========================================================

    if tenant is None:

        tenant_id = (
            x_tenant_id
            or metadata_phone_number_id
            or "default"
        )

        tenant = Tenant(
            _id=str(tenant_id),

            tenant_id=str(tenant_id),

            business_name=settings.APP_NAME,

            phone_number_id=(
                resolved_phone_number_id
                or metadata_phone_number_id
                or ""
            ),

            access_token=(
                resolved_access_token
                or ""
            ),

            webhook_verify_token=(
                settings.WHATSAPP_VERIFY_TOKEN
            ),
        )

    # =========================================================
    # 9. PROCESS WEBHOOK ENTRIES
    # =========================================================

    processed: list[Dict[str, Any]] = []

    for entry in validated.entry:

        for change in entry.changes:

            value = change.value

            if isinstance(
                value,
                dict,
            ):

                metadata = (
                    value.get("metadata")
                    or {}
                )

                messages = (
                    value.get("messages")
                    or []
                )

                message_phone_number_id = (
                    metadata.get(
                        "phone_number_id"
                    )
                    if isinstance(
                        metadata,
                        dict,
                    )
                    else getattr(
                        metadata,
                        "phone_number_id",
                        None,
                    )
                )

            else:

                metadata = getattr(
                    value,
                    "metadata",
                    None,
                )

                messages = (
                    getattr(
                        value,
                        "messages",
                        [],
                    )
                    or []
                )

                message_phone_number_id = (
                    getattr(
                        metadata,
                        "phone_number_id",
                        None,
                    )
                    if metadata
                    else None
                )

            # =================================================
            # PHONE NUMBER VALIDATION
            # =================================================

            if (
                tenant.phone_number_id
                and message_phone_number_id
                and str(
                    message_phone_number_id
                )
                != str(
                    tenant.phone_number_id
                )
            ):

                logger.warning(
                    "Rejected webhook change "
                    "with mismatched phone "
                    "number metadata."
                )

                continue

            resolved_tenant_id = (
                tenant.tenant_id
            )

            # =================================================
            # PROCESS MESSAGES
            # =================================================

            for message in messages:

                # ---------------------------------------------
                # NORMALIZE
                # ---------------------------------------------

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
                # PROCESS MESSAGE
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
                        "Duplicate WhatsApp "
                        "message ignored: %s",
                        whatsapp_message_id,
                    )

                    processed.append(
                        {
                            "status": (
                                "duplicate"
                            ),

                            "whatsapp_message_id": (
                                whatsapp_message_id
                            ),
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

                outbound_message_id = (
                    result.outbound_message_id
                )

                if (
                    phone_number_id
                    and access_token
                    and outbound_message_id
                ):

                    try:

                        send_result = (
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
                        )

                        # -------------------------------------
                        # UPDATE DATABASE → SENT
                        # -------------------------------------

                        await (
                            message_service
                            .mark_outbound_sent(
                                outbound_message_id=(
                                    outbound_message_id
                                ),

                                whatsapp_message_id=(
                                    send_result
                                    .provider_message_id
                                ),
                            )
                        )

                        response_data[
                            "delivery_status"
                        ] = "sent"

                        response_data[
                            "whatsapp_message_id"
                        ] = (
                            send_result
                            .provider_message_id
                        )

                    except Exception as exc:

                        logger.exception(
                            "Failed to send "
                            "WhatsApp reply."
                        )

                        # -------------------------------------
                        # UPDATE DATABASE → FAILED
                        # -------------------------------------

                        try:

                            await (
                                message_service
                                .mark_outbound_failed(
                                    outbound_message_id=(
                                        outbound_message_id
                                    ),

                                    error=str(
                                        exc
                                    ),
                                )
                            )

                        except Exception:

                            logger.exception(
                                "Failed to update "
                                "outbound message "
                                "delivery status."
                            )

                        response_data[
                            "delivery_status"
                        ] = "failed"

                        response_data[
                            "delivery_error"
                        ] = str(exc)

                elif outbound_message_id:

                    # =========================================
                    # NO WHATSAPP CREDENTIALS
                    # =========================================

                    await (
                        message_service
                        .mark_outbound_failed(
                            outbound_message_id=(
                                outbound_message_id
                            ),

                            error=(
                                "WhatsApp credentials "
                                "are not configured."
                            ),
                        )
                    )

                    response_data[
                        "delivery_status"
                    ] = "failed"

                else:

                    logger.warning(
                        "No outbound message ID "
                        "was returned by "
                        "MessageService."
                    )

                    response_data[
                        "delivery_status"
                    ] = "not_sent"

                # =============================================
                # ADD RESULT
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

        phone_id = metadata.get(
            "phone_number_id"
        )
        return str(phone_id) if phone_id is not None else None

    except (
        ValueError,
        IndexError,
        TypeError,
        AttributeError,
    ):

        return None