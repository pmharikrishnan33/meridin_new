"""
Conversation manager.

MongoDB is the source of truth.
The in-memory session is only a short-lived cache.
"""

from datetime import datetime, timezone
from typing import Dict, Optional, List
from pymongo.errors import DuplicateKeyError
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
            customer_id = f"cust_{wa_id}"
            return Customer(
                id=customer_id,
                tenant_id=tenant_id,
                phone_number=phone_number,
                wa_id=wa_id,
                name=name,
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
                        "last_interaction_at": datetime.now(timezone.utc),
                        "updated_at": datetime.now(timezone.utc),
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
            last_interaction_at=datetime.now(timezone.utc),
        )

        try:
            await collection.insert_one(
                customer.model_dump(
                    by_alias=True,
                    exclude_none=True,
                )
            )
        except DuplicateKeyError:
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
            conv_id = f"conv_{tenant_id}_{customer_id}"
            if conv_id in self._sessions:
                return self._sessions[conv_id]
            session = ConversationSession(
                conversation_id=conv_id,
                tenant_id=tenant_id,
                customer_id=customer_id,
                context=ConversationContext(),
            )
            self._sessions[conv_id] = session
            return session

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
        except DuplicateKeyError:
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
        """
        Load the conversation and its recent message history.

        MongoDB is the source of truth.
        RAM is only a cache.
        """

        cached = self._sessions.get(
            conversation_id
        )

        if cached:
            return cached

        if not mongodb.is_connected:
            raise ValueError(
                f"Conversation not found: {conversation_id}"
            )

        document = await collections.conversations.find_one(
            {
                "_id": conversation_id,
            }
        )

        if not document:
            raise ValueError(
                f"Conversation not found: {conversation_id}"
            )

        conversation = Conversation(
            **document
        )

        history = await self.get_conversation_history(
            conversation_id=conversation.id,
            limit=20,
        )

        session = ConversationSession(
            conversation_id=(
                conversation.id
                or conversation_id
            ),
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

        for message in history:
            session.add_message(
                message_id=message.id,
                direction=message.direction,
                text=message.text or "",
                intent=message.intent,
                intent_confidence=(
                    message.intent_confidence
                ),
                entities=[],
                is_from_bot=(
                    message.direction
                    == "outbound"
                    and message.is_from_bot
                ),
                bot_response_type=(
                    message.bot_response_type
                ),
                metadata=message.metadata or {},
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

        self._sessions[
            session.conversation_id
        ] = session

        if not mongodb.is_connected:
            return

        update_data = {
            "context": session.context.model_dump(),
            "updated_at": datetime.now(timezone.utc),
            "status": (
                ConversationStatus.ACTIVE.value
                if session.is_active
                else ConversationStatus.CLOSED.value
            ),
        }

        if not session.is_active:
            update_data["closed_at"] = datetime.now(timezone.utc)

        await collections.conversations.update_one(
            {
                "_id": session.conversation_id
            },
            {
                "$set": update_data
            },
        )

    # =========================================================
    # MESSAGE IDEMPOTENCY
    # =========================================================

    async def get_message_by_whatsapp_id(
        self,
        tenant_id: str,
        whatsapp_message_id: str,
    ) -> Optional[Message]:

        if not mongodb.is_connected:
            return None

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
        """
        Persist a message to MongoDB.
        """

        if not mongodb.is_connected:
            return

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
            ] = datetime.now(timezone.utc)

        if status == "failed":
            update[
                "failed_at"
            ] = datetime.now(timezone.utc)

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