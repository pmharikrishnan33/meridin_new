"""HTTP endpoints for local chat integration and WhatsApp webhook ingestion."""

from typing import Any, Dict, Optional

from fastapi import APIRouter, Header, HTTPException, Query, Request, status
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from app.core.config import settings
from app.services.message_service import message_service
from app.services.whatsapp_service import whatsapp_sender
from app.utils.logger import logger


router = APIRouter(tags=["messages"])


class ChatRequest(BaseModel):
    """A provider-neutral inbound text message."""

    tenant_id: str = Field(min_length=1)
    user_id: str = Field(min_length=1)
    text: str = Field(min_length=1, max_length=4_000)
    tenant_settings: Dict[str, Any] = Field(default_factory=dict)


class ChatResponse(BaseModel):
    conversation_id: str
    intent: str
    confidence: float
    entities: Dict[str, Any]
    response: Dict[str, Any]


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


@router.post("/messages", response_model=ChatResponse)
async def process_message(payload: ChatRequest) -> ChatResponse:
    """Process a text message and return the bot response to the caller."""
    try:
        result = await message_service.process(
            tenant_id=payload.tenant_id,
            user_id=payload.user_id,
            text=payload.text,
            tenant_settings=payload.tenant_settings,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return _to_chat_response(result)


@router.get("/webhook")
async def verify_webhook(
    mode: Optional[str] = Query(default=None, alias="hub.mode"),
    verify_token: Optional[str] = Query(default=None, alias="hub.verify_token"),
    challenge: Optional[str] = Query(default=None, alias="hub.challenge"),
):
    """Perform Meta's WhatsApp webhook verification handshake."""
    if (
        settings.WHATSAPP_VERIFY_TOKEN
        and mode == "subscribe"
        and verify_token == settings.WHATSAPP_VERIFY_TOKEN
        and challenge is not None
    ):
        return PlainTextResponse(challenge)
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Webhook verification failed")


@router.post("/webhook", status_code=status.HTTP_200_OK)
async def receive_whatsapp_webhook(
    request: Request,
    x_tenant_id: Optional[str] = Header(default=None),
    x_whatsapp_phone_number_id: Optional[str] = Header(default=None),
    x_whatsapp_access_token: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    """Accept WhatsApp text notifications and process each message.

    When ``x_whatsapp_phone_number_id`` and ``x_whatsapp_access_token``
    headers are provided (or the tenant has credentials in the app config),
    the generated response is sent back to Meta via the WhatsApp Cloud API.
    Otherwise the response is returned in the HTTP body for the caller to
    handle.
    """
    payload = await request.json()
    processed = []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            metadata = value.get("metadata", {})
            tenant_id = x_tenant_id or metadata.get("phone_number_id")
            for message in value.get("messages", []):
                text = (message.get("text") or {}).get("body")
                sender = message.get("from")
                if not tenant_id or not sender or not text:
                    continue

                result = await message_service.process(
                    tenant_id=str(tenant_id),
                    user_id=str(sender),
                    text=text,
                )

                chat_response = _to_chat_response(result)
                processed.append(chat_response.model_dump())

                # Attempt to send the reply back to WhatsApp
                phone_number_id = x_whatsapp_phone_number_id or settings.WHATSAPP_PHONE_NUMBER_ID
                access_token = x_whatsapp_access_token or settings.WHATSAPP_ACCESS_TOKEN

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
                        processed[-1]["send_error"] = str(exc)

    return {"status": "accepted", "processed": processed}
