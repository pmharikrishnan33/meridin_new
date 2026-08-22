"""
Conversation manager.

MongoDB is the source of truth.
The in-memory session is only a short-lived cache.
"""

from datetime import datetime
from typing import Dict, Optional, List
from uuid import uuid4

from app.database.collections import collections
from app.database.mongodb import mongodb
from app.models.schemas import (
    Conversation,
    ConversationContext,
    ConversationStatus,
    Message,
    Customer,
)
from app.conversation.session import ConversationSession
from app.utils.logger import logger


class ConversationManager:

    def __init__(self):
        self._sessions: Dict[str, ConversationSession] = {}

    # =========================================================
    # CUSTOMER
    # =========================================================

    async def get_or_create_customer(
        self,
        tenant_id: str,
        phone_number: str,
        wa_id: str,
        name: Optional[str] = None,
    ) -> Customer:

        if not mongodb.is_connected:
            raise RuntimeError(
                "MongoDB is unavailable. "
                "Customer state cannot be safely persisted."
            )

        collection = collections.customers

        existing = await collection.find_one(
            {
                "tenant_id": tenant_id,
                "wa_id": wa_id,
            }
        )

        if existing:
            customer = Customer(**existing)

            await collection.update_one(
                {"_id": customer.id},
                {
                    "$set": {
                        "last_interaction_at": datetime.utcnow(),
                        "updated_at": datetime.utcnow(),
                    }
                },
            )

            return customer

        customer = Customer(
            id=str(uuid4()),
            tenant_id=tenant_id,
            phone_number=phone_number,
            wa_id=wa_id,
            name=name,
            last_interaction_at=datetime.utcnow(),
        )

        try:
            await collection.insert_one(
                customer.model_dump(
                    by_alias=True,
                    exclude_none=True,
                )
            )
        except Exception:
            # Another concurrent request may have created it.
            existing = await collection.find_one(
                {
                    "tenant_id": tenant_id,
                    "wa_id": wa_id,
                }
            )

            if existing:
                return Customer(**existing)

            raise

        return customer

    # =========================================================
    # CONVERSATION
    # =========================================================

    async def get_or_create_conversation(
        self,
        tenant_id: str,
        customer_id: str,
        customer_phone: str,
    ) -> ConversationSession:

        if not mongodb.is_connected:
            raise RuntimeError(
                "MongoDB is unavailable. "
                "Conversation state cannot be safely persisted."
            )

        collection = collections.conversations

        conversation_doc = await collection.find_one(
            {
                "tenant_id": tenant_id,
                "customer_id": customer_id,
                "status": ConversationStatus.ACTIVE.value,
            },
            sort=[
                ("updated_at", -1)
            ],
        )

        if conversation_doc:
            return await self._load_session(
                conversation_doc["_id"]
            )

        conversation = Conversation(
            id=str(uuid4()),
            tenant_id=tenant_id,
            customer_id=customer_id,
            status=ConversationStatus.ACTIVE,
            context=ConversationContext(),
        )

        try:
            await collection.insert_one(
                conversation.model_dump(
                    by_alias=True,
                    exclude_none=True,
                )
            )
        except Exception:
            # Race protection:
            # another request may have created the active conversation.
            existing = await collection.find_one(
                {
                    "tenant_id": tenant_id,
                    "customer_id": customer_id,
                    "status": ConversationStatus.ACTIVE.value,
                },
                sort=[
                    ("updated_at", -1)
                ],
            )

            if existing:
                return await self._load_session(
                    existing["_id"]
                )

            raise

        session = ConversationSession(
            conversation_id=conversation.id,
            tenant_id=tenant_id,
            customer_id=customer_id,
            context=conversation.context,
        )

        self._sessions[
            conversation.id
        ] = session

        return session

    # =========================================================
    # LOAD SESSION
    # =========================================================

    async def _load_session(
        self,
        conversation_id: str,
    ) -> ConversationSession:

        if not mongodb.is_connected:
            raise RuntimeError(
                "MongoDB is unavailable."
            )

        # RAM is only a cache.
        cached = self._sessions.get(
            conversation_id
        )

        if cached:
            return cached

        document = await collections.conversations.find_one(
            {
                "_id": conversation_id,
                "status": ConversationStatus.ACTIVE.value,
            }
        )

        if not document:
            raise ValueError(
                f"Conversation not found: {conversation_id}"
            )

        conversation = Conversation(
            **document
        )

        session = ConversationSession(
            conversation_id=conversation.id,
            tenant_id=conversation.tenant_id,
            customer_id=conversation.customer_id,
            context=conversation.context,
            message_history=[],
            search_cache={},
            is_active=(
                conversation.status
                == ConversationStatus.ACTIVE
            ),
        )

        self._sessions[
            conversation_id
        ] = session

        return session

    # =========================================================
    # SAVE SESSION
    # =========================================================

    async def save_session(
        self,
        session: ConversationSession,
    ) -> None:

        if not mongodb.is_connected:
            raise RuntimeError(
                "MongoDB is unavailable. "
                "Cannot persist conversation state."
            )

        update_data = {
            "context": session.context.model_dump(),
            "updated_at": datetime.utcnow(),
            "status": (
                ConversationStatus.ACTIVE.value
                if session.is_active
                else ConversationStatus.CLOSED.value
            ),
        }

        if not session.is_active:
            update_data["closed_at"] = datetime.utcnow()

        await collections.conversations.update_one(
            {
                "_id": session.conversation_id
            },
            {
                "$set": update_data
            },
        )

        self._sessions[
            session.conversation_id
        ] = session

    # =========================================================
    # MESSAGE IDEMPOTENCY
    # =========================================================

    async def get_message_by_whatsapp_id(
        self,
        tenant_id: str,
        whatsapp_message_id: str,
    ) -> Optional[Message]:

        if not mongodb.is_connected:
            raise RuntimeError(
                "MongoDB is unavailable."
            )

        document = await collections.messages.find_one(
            {
                "tenant_id": tenant_id,
                "whatsapp_message_id": whatsapp_message_id,
            }
        )

        if not document:
            return None

        return Message(
            **document
        )

    # =========================================================
    # SAVE MESSAGE
    # =========================================================

    async def save_message(
        self,
        message: Message,
    ) -> None:

        if not mongodb.is_connected:
            raise RuntimeError(
                "MongoDB is unavailable."
            )

        await collections.messages.insert_one(
            message.model_dump(
                by_alias=True,
                exclude_none=True,
            )
        )

    # =========================================================
    # UPDATE DELIVERY
    # =========================================================

    async def update_message_delivery(
        self,
        message_id: str,
        *,
        status: str,
        whatsapp_message_id: Optional[str] = None,
        error: Optional[str] = None,
    ) -> None:

        if not mongodb.is_connected:
            return

        update: Dict[str, object] = {
            "delivery_status": status,
        }

        if whatsapp_message_id:
            update[
                "whatsapp_message_id"
            ] = whatsapp_message_id

        if error:
            update[
                "delivery_error"
            ] = error

        if status == "sent":
            update[
                "sent_at"
            ] = datetime.utcnow()

        if status == "failed":
            update[
                "failed_at"
            ] = datetime.utcnow()

        await collections.messages.update_one(
            {
                "_id": message_id
            },
            {
                "$set": update
            },
        )

    # =========================================================
    # HISTORY
    # =========================================================

    async def get_conversation_history(
        self,
        conversation_id: str,
        limit: int = 20,
    ) -> List[Message]:

        if not mongodb.is_connected:
            return []

        cursor = (
            collections.messages
            .find(
                {
                    "conversation_id":
                        conversation_id
                }
            )
            .sort(
                "created_at",
                -1,
            )
            .limit(limit)
        )

        messages = []

        async for document in cursor:
            messages.append(
                Message(**document)
            )

        return list(
            reversed(messages)
        )

    # =========================================================
    # SESSION ACCESS
    # =========================================================

    def get_session(
        self,
        conversation_id: str,
    ) -> Optional[ConversationSession]:

        return self._sessions.get(
            conversation_id
        )

    def register_session(
        self,
        session: ConversationSession,
    ) -> None:

        self._sessions[
            session.conversation_id
        ] = session

    async def end_conversation(
        self,
        conversation_id: str,
    ) -> None:

        session = await self._load_session(
            conversation_id
        )

        session.is_active = False

        await self.save_session(
            session
        )

        self._sessions.pop(
            conversation_id,
            None,
        )


conversation_manager = ConversationManager()