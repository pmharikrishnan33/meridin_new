"""HTTP endpoints for local chat integration and WhatsApp webhook ingestion."""

import json
from typing import Any, Dict, Optional

from fastapi import (
    APIRouter,
    Header,
    HTTPException,
    Query,
    Request,
    status,
)
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

from app.conversation.manager import conversation_manager
from app.database.collections import collections

from app.services.whatsapp_inbound import (
    normalize_whatsapp_message,
)

from app.services.whatsapp_service import (
    whatsapp_sender,
)

from app.utils.logger import logger


router = APIRouter(
    tags=["messages"]
)


class ChatResponse(BaseModel):
    conversation_id: str
    intent: str
    confidence: float
    entities: Dict[str, Any]
    response: Dict[str, Any]


def _tenant_message_settings(
    tenant,
) -> Dict[str, Any]:
    """
    Return only non-sensitive tenant settings needed by
    message handlers.

    Never expose:
    - access_token
    - webhook secret
    - verification token
    - other credentials
    """

    feature_flags = getattr(
        tenant,
        "feature_flags",
        None,
    )

    if feature_flags is None:
        feature_flags_data: Dict[str, Any] = {}

    elif hasattr(
        feature_flags,
        "model_dump",
    ):
        feature_flags_data = (
            feature_flags.model_dump()
        )

    elif isinstance(
        feature_flags,
        dict,
    ):
        feature_flags_data = dict(
            feature_flags
        )

    else:
        feature_flags_data = {}

    return {
        "business_name": (
            tenant.business_name
        ),

        "welcome_message": (
            tenant.welcome_message
        ),

        "fallback_message": (
            tenant.fallback_message
        ),

        "feature_flags": (
            feature_flags_data
        ),
    }


def _to_chat_response(
    result,
) -> ChatResponse:
    """
    Convert MessageService result into the webhook
    response format.
    """

    entities: Dict[str, Any] = {}

    for entity in (
        result.understanding.entities
    ):

        entities.setdefault(
            entity.entity_type.value,
            (
                entity.normalized_value
                or entity.value
            ),
        )

    return ChatResponse(
        conversation_id=(
            result.conversation_id
        ),

        intent=(
            result.understanding.intent.value
        ),

        confidence=(
            result.understanding.intent_confidence
        ),

        entities=entities,

        response=(
            result.response.model_dump()
        ),
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
    Perform Meta's WhatsApp webhook verification
    handshake.
    """

    if not (
        mode == "subscribe"
        and verify_token is not None
        and challenge is not None
    ):
        raise HTTPException(
            status_code=(
                status.HTTP_403_FORBIDDEN
            ),

            detail=(
                "Webhook verification failed"
            ),
        )

    # =========================================================
    # 1. SHARED ENVIRONMENT VERIFY TOKEN
    # =========================================================

    if (
        settings.WHATSAPP_VERIFY_TOKEN
        and verify_token
        == settings.WHATSAPP_VERIFY_TOKEN
    ):
        return PlainTextResponse(
            challenge
        )

    # =========================================================
    # 2. TENANT-SPECIFIC VERIFY TOKEN
    # =========================================================

    from app.repositories.tenant_repository import (
        tenant_repository,
    )

    tenant = (
        await tenant_repository
        .verify_verify_token(
            verify_token
        )
    )

    if tenant is not None:

        return PlainTextResponse(
            challenge
        )

    raise HTTPException(
        status_code=(
            status.HTTP_403_FORBIDDEN
        ),

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
    
    x_hub_signature_256: Optional[str] = Header(
        default=None,
        alias="x-hub-signature-256",
    ),
) -> Dict[str, Any]:
    """
    Accept WhatsApp webhook notifications.

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
        tenant validation
            ↓
        message normalization
            ↓
        MessageService
            ↓
        outbound message = pending
            ↓
        WhatsAppSender
            ↓
        Meta
            ↓
        mark outbound = sent / failed
    """

    # =========================================================
    # 1. READ RAW BODY
    # =========================================================

    raw_body = await request.body()

    check_body_size(
        raw_body
    )

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
            or "unknown"
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

    except (
        ValueError,
        TypeError,
    ):

        raise HTTPException(
            status_code=(
                status.HTTP_400_BAD_REQUEST
            ),

            detail=(
                "Request body is not "
                "valid JSON."
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
                "Webhook payload must "
                "be a JSON object."
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
    # 8. TENANT VALIDATION
    # =========================================================
    #
    # IMPORTANT:
    #
    # Never create a fake/default Tenant here.
    #
    # A WhatsApp webhook must belong to a registered
    # tenant before any customer/message processing occurs.
    # =========================================================

    if tenant is None:

        logger.warning(
            "Rejected webhook because no registered "
            "tenant matches phone_number_id=%s "
            "or tenant_id=%s.",
            metadata_phone_number_id,
            x_tenant_id,
        )

        raise HTTPException(
            status_code=(
                status.HTTP_404_NOT_FOUND
            ),

            detail=(
                "Unknown WhatsApp tenant."
            ),
        )

    # =========================================================
    # 9. FINAL PHONE NUMBER VALIDATION
    # =========================================================

    if (
        resolved_phone_number_id
        and tenant.phone_number_id
        and str(
            resolved_phone_number_id
        )
        != str(
            tenant.phone_number_id
        )
    ):

        logger.warning(
            "Resolved phone number ID does not "
            "belong to resolved tenant."
        )

        raise HTTPException(
            status_code=(
                status.HTTP_403_FORBIDDEN
            ),

            detail=(
                "WhatsApp tenant credentials "
                "do not match the webhook."
            ),
        )

    # =========================================================
    # 10. CREDENTIAL VALIDATION
    # =========================================================

    phone_number_id = (
        resolved_phone_number_id
        or tenant.phone_number_id
    )

    access_token = (
        resolved_access_token
        or tenant.access_token
    )

    if not phone_number_id:

        logger.error(
            "Tenant %s has no WhatsApp "
            "phone_number_id.",
            tenant.tenant_id,
        )

        raise HTTPException(
            status_code=(
                status.HTTP_500_INTERNAL_SERVER_ERROR
            ),

            detail=(
                "WhatsApp phone number "
                "configuration is missing."
            ),
        )

    if not access_token:

        logger.error(
            "Tenant %s has no WhatsApp "
            "access token.",
            tenant.tenant_id,
        )

        raise HTTPException(
            status_code=(
                status.HTTP_500_INTERNAL_SERVER_ERROR
            ),

            detail=(
                "WhatsApp access token "
                "configuration is missing."
            ),
        )

    # =========================================================
    # 11. PROCESS WEBHOOK ENTRIES
    # =========================================================

    processed: list[
        Dict[str, Any]
    ] = []

    for entry in validated.entry:

        for change in entry.changes:

            value = change.value

            # =================================================
            # EXTRACT VALUE DATA
            # =================================================

            if isinstance(
                value,
                dict,
            ):

                metadata = (
                    value.get(
                        "metadata"
                    )
                    or {}
                )

                messages = (
                    value.get(
                        "messages"
                    )
                    or []
                )

                statuses = (
                    value.get(
                        "statuses"
                    )
                    or []
                )

                if isinstance(
                    metadata,
                    dict,
                ):

                    message_phone_number_id = (
                        metadata.get(
                            "phone_number_id"
                        )
                    )

                else:

                    message_phone_number_id = (
                        getattr(
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

                statuses = []

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
                not message_phone_number_id
            ):

                logger.warning(
                    "Ignoring webhook change "
                    "without phone_number_id."
                )

                continue

            if (
                str(
                    message_phone_number_id
                )
                != str(
                    tenant.phone_number_id
                )
            ):

                logger.warning(
                    "Rejected webhook change "
                    "with mismatched phone "
                    "number metadata. "
                    "tenant=%s expected=%s received=%s",
                    tenant.tenant_id,
                    tenant.phone_number_id,
                    message_phone_number_id,
                )

                continue

            resolved_tenant_id = (
                tenant.tenant_id
            )

            # =================================================
            # PROCESS OUTBOUND DELIVERY STATUSES
            # =================================================

            for delivery in statuses:
                if not isinstance(delivery, dict):
                    continue

                provider_message_id = delivery.get("id")
                delivery_status = str(delivery.get("status", "")).strip().lower()

                if not provider_message_id or delivery_status not in {"sent", "delivered", "read", "failed"}:
                    continue

                outbound = await conversation_manager.get_message_by_whatsapp_id(
                    tenant_id=tenant.tenant_id,
                    whatsapp_message_id=str(provider_message_id),
                )

                # A single logical BotResponse may generate multiple Meta
                # messages (for example, one image per product plus a button
                # message). Only the first provider ID is stored in the
                # unique whatsapp_message_id field; the complete list is kept
                # in metadata for delivery callbacks for the remaining IDs.
                if outbound is None:
                    outbound_document = await collections.messages.find_one(
                        {
                            "tenant_id": tenant.tenant_id,
                            "metadata.provider_message_ids": str(provider_message_id),
                        }
                    )
                    if outbound_document:
                        from app.models.schemas import Message
                        outbound = Message(**outbound_document)

                if outbound is None:
                    logger.info(
                        "Received delivery status for unknown outbound WhatsApp message: %s",
                        provider_message_id,
                    )
                    continue

                error_text = None
                if delivery_status == "failed":
                    errors = delivery.get("errors") or []
                    if errors and isinstance(errors[0], dict):
                        error_text = errors[0].get("message") or errors[0].get("title") or str(errors[0])
                    else:
                        error_text = "WhatsApp delivery failed."

                await conversation_manager.update_message_delivery(
                    outbound.id,
                    status=delivery_status,
                    whatsapp_message_id=str(provider_message_id),
                    error=error_text,
                )

                processed.append({
                    "status": "delivery_update",
                    "delivery_status": delivery_status,
                    "whatsapp_message_id": str(provider_message_id),
                })

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

                # ---------------------------------------------
                # NORMALIZED FIELDS
                # ---------------------------------------------

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

                message_type = (
                    normalized[
                        "message_type"
                    ]
                )

                # =================================================
                # MESSAGE TYPE VALIDATION
                # =================================================

                try:

                    parsed_message_type = (
                        MessageType(
                            message_type
                        )
                    )

                except (
                    ValueError,
                    TypeError,
                ):

                    logger.warning(
                        "Unsupported normalized "
                        "message type: %s",
                        message_type,
                    )

                    continue

                # =================================================
                # PROCESS MESSAGE
                # =================================================

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

                            message_type=(
                                parsed_message_type
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

                except Exception as exc:

                    logger.exception(
                        "Failed to process "
                        "WhatsApp message "
                        "%s for tenant %s.",
                        whatsapp_message_id,
                        tenant.tenant_id,
                    )

                    # Do not silently acknowledge processing failures.
                    # Meta can retry the webhook when a 5xx response is returned.
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail="Webhook message processing failed.",
                    ) from exc

                # =================================================
                # CONVERT RESPONSE
                # =================================================

                chat_response = (
                    _to_chat_response(
                        result
                    )
                )

                response_data = (
                    chat_response.model_dump()
                )

                # =================================================
                # OUTBOUND MESSAGE
                # =================================================

                outbound_message_id = (
                    result.outbound_message_id
                )

                # =================================================
                # SEND TO WHATSAPP
                # =================================================

                if not outbound_message_id:

                    logger.warning(
                        "MessageService returned "
                        "no outbound message ID "
                        "for inbound message %s.",
                        whatsapp_message_id,
                    )

                    response_data[
                        "delivery_status"
                    ] = "not_sent"

                    processed.append(
                        response_data
                    )

                    continue

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

                    # =================================================
                    # VERIFY PROVIDER RESULT
                    # =================================================

                    if not send_result.success:

                        provider_error = (
                            send_result.error_message
                            or
                            "WhatsApp provider "
                            "rejected the message."
                        )

                        raise RuntimeError(
                            provider_error
                        )

                    provider_message_id = (
                        send_result.provider_message_id
                    )
                    provider_message_ids = list(
                        send_result.provider_message_ids or []
                    )
                    if not provider_message_id and provider_message_ids:
                        provider_message_id = provider_message_ids[-1]

                    if not provider_message_id:

                        raise RuntimeError(
                            "WhatsApp API accepted "
                            "the response but did "
                            "not return a provider "
                            "message ID."
                        )

                    # =================================================
                    # MARK OUTBOUND SENT
                    # =================================================

                    await (
                        message_service
                        .mark_outbound_sent(
                            outbound_message_id=(
                                outbound_message_id
                            ),

                            whatsapp_message_id=(
                                provider_message_id
                            ),
                        )
                    )

                    provider_message_ids = provider_message_ids or [provider_message_id]

                    # Persist every provider ID so subsequent Meta delivery
                    # callbacks can resolve the same logical outbound message.
                    await collections.messages.update_one(
                        {
                            "_id": outbound_message_id,
                            "tenant_id": tenant.tenant_id,
                        },
                        {
                            "$set": {
                                "metadata.provider_message_ids": provider_message_ids,
                                "metadata.provider_message_count": len(provider_message_ids),
                            }
                        },
                    )

                    response_data["whatsapp_message_ids"] = provider_message_ids

                    response_data[
                        "delivery_status"
                    ] = "sent"

                    response_data[
                        "whatsapp_message_id"
                    ] = (
                        provider_message_id
                    )

                except Exception as exc:

                    logger.exception(
                        "Failed to send "
                        "WhatsApp reply "
                        "for outbound message %s.",
                        outbound_message_id,
                    )

                    # Preserve any provider IDs returned before a later
                    # product/button send failed. Those messages may still
                    # generate delivery/read callbacks from Meta.
                    partial_provider_ids = list(
                        getattr(send_result, "provider_message_ids", [])
                        if "send_result" in locals()
                        else []
                    )
                    if partial_provider_ids:
                        await collections.messages.update_one(
                            {
                                "_id": outbound_message_id,
                                "tenant_id": tenant.tenant_id,
                            },
                            {
                                "$set": {
                                    "metadata.provider_message_ids": partial_provider_ids,
                                    "metadata.provider_message_count": len(partial_provider_ids),
                                }
                            },
                        )

                    # =================================================
                    # MARK OUTBOUND FAILED
                    # =================================================

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
                            "delivery status "
                            "for %s.",
                            outbound_message_id,
                        )

                    response_data[
                        "delivery_status"
                    ] = "failed"

                    response_data[
                        "delivery_error"
                    ] = str(exc)

                # =================================================
                # ADD RESULT
                # =================================================

                processed.append(
                    response_data
                )

    # =========================================================
    # WEBHOOK ACKNOWLEDGEMENT
    # =========================================================

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

        if not isinstance(
            entries[0],
            dict,
        ):
            return None

        changes = entries[0].get(
            "changes",
            [],
        )

        if not changes:
            return None

        if not isinstance(
            changes[0],
            dict,
        ):
            return None

        value = changes[0].get(
            "value",
            {},
        )

        if not isinstance(
            value,
            dict,
        ):
            return None

        metadata = value.get(
            "metadata",
            {},
        )

        if not isinstance(
            metadata,
            dict,
        ):
            return None

        phone_id = metadata.get(
            "phone_number_id"
        )

        if phone_id is None:
            return None

        return str(
            phone_id
        )

    except (
        ValueError,
        TypeError,
        IndexError,
        AttributeError,
    ):

        return None