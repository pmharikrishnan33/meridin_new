"""
Conversation manager - orchestrates conversation flow and persistence.
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
    """
    Manages conversation lifecycle:
    - Create/get conversations
    - Manage in-memory session
    - Persist to MongoDB
    - Handle conversation state
    """

    def __init__(self):
        self._sessions: Dict[str, ConversationSession] = {}  # conversation_id -> session

    async def get_or_create_conversation(
        self,
        tenant_id: str,
        customer_id: str,
        customer_phone: str
    ) -> ConversationSession:
        """
        Get existing active conversation or create new one.
        """

        # Try to find existing active conversation
        conversation = await self._find_active_conversation(tenant_id, customer_id)

        if conversation:
            # Load existing session
            session = await self._load_session(conversation.id)
            return session

        # Create new conversation
        session = await self._create_conversation(tenant_id, customer_id, customer_phone)
        return session

    async def _find_active_conversation(
        self,
        tenant_id: str,
        customer_id: str
    ) -> Optional[Conversation]:
        """
        Find active conversation for customer.
        """

        if not mongodb.is_connected:
            logger.debug("Skipping conversation lookup because MongoDB is unavailable.")
            return None

        doc = await collections.conversations.find_one({
            "tenant_id": tenant_id,
            "customer_id": customer_id,
            "status": ConversationStatus.ACTIVE.value
        }, sort=[("updated_at", -1)])

        if doc:
            return Conversation(**doc)

        return None

    async def _create_conversation(
        self,
        tenant_id: str,
        customer_id: str,
        customer_phone: str
    ) -> ConversationSession:
        """
        Create new conversation and session.
        """

        conversation = Conversation(
            id=str(uuid4()),
            tenant_id=tenant_id,
            customer_id=customer_id,
            status=ConversationStatus.ACTIVE,
            context=ConversationContext()
        )

        # Persist to MongoDB when available
        if mongodb.is_connected:
            await collections.conversations.insert_one(
                conversation.model_dump(by_alias=True, exclude_none=True)
            )
        else:
            logger.debug("Skipping conversation persistence because MongoDB is unavailable.")

        # Create in-memory session
        session = ConversationSession(
            conversation_id=conversation.id,
            tenant_id=tenant_id,
            customer_id=customer_id,
            context=conversation.context
        )

        self._sessions[conversation.id] = session
        logger.info(f"Created new conversation: {conversation.id}")

        return session

    async def _load_session(self, conversation_id: str) -> ConversationSession:
        """
        Load session from memory or MongoDB.
        """

        # Check in-memory first
        if conversation_id in self._sessions:
            return self._sessions[conversation_id]

        # Load from MongoDB
        if not mongodb.is_connected:
            logger.debug("Skipping session load from MongoDB because it is unavailable.")
            raise ValueError(f"Conversation not found: {conversation_id}")

        doc = await collections.conversations.find_one({"_id": conversation_id})

        if doc:
            conversation = Conversation(**doc)
            session = ConversationSession(
                conversation_id=conversation.id,
                tenant_id=conversation.tenant_id,
                customer_id=conversation.customer_id,
                context=conversation.context,
                message_history=[],
                is_active=conversation.status == ConversationStatus.ACTIVE
            )
            self._sessions[conversation_id] = session
            return session

        raise ValueError(f"Conversation not found: {conversation_id}")

    async def save_session(self, session: ConversationSession) -> None:
        """
        Persist session to MongoDB.
        """

        if not mongodb.is_connected:
            logger.debug("Skipping session persistence because MongoDB is unavailable.")
            return

        update_data = {
            "context": session.context.model_dump() if hasattr(session.context, 'model_dump') else session.context.__dict__,
            "updated_at": datetime.utcnow(),
            "status": ConversationStatus.ACTIVE.value if session.is_active else ConversationStatus.CLOSED.value
        }

        if not session.is_active:
            update_data["closed_at"] = datetime.utcnow()

        await collections.conversations.update_one(
            {"_id": session.conversation_id},
            {"$set": update_data}
        )

        logger.debug(f"Saved session: {session.conversation_id}")

    async def save_message(self, message: Message) -> None:
        """
        Save message to MongoDB.
        """

        if not mongodb.is_connected:
            logger.debug("Skipping message persistence because MongoDB is unavailable.")
            return

        await collections.messages.insert_one(
            message.model_dump(by_alias=True, exclude_none=True)
        )

        logger.debug(f"Saved message: {message.id}")

    async def end_conversation(self, conversation_id: str) -> None:
        """
        End conversation and persist final state.
        """

        if conversation_id in self._sessions:
            session = self._sessions[conversation_id]
            session.is_active = False
            await self.save_session(session)
            del self._sessions[conversation_id]

        logger.info(f"Ended conversation: {conversation_id}")

    async def get_conversation_history(
        self,
        conversation_id: str,
        limit: int = 20
    ) -> List[Message]:
        """
        Get recent message history for conversation.
        """

        if not mongodb.is_connected:
            logger.debug("Skipping conversation history load because MongoDB is unavailable.")
            return []

        cursor = collections.messages.find(
            {"conversation_id": conversation_id}
        ).sort("created_at", -1).limit(limit)

        messages = []
        async for doc in cursor:
            messages.append(Message(**doc))

        return list(reversed(messages))

    def get_session(self, conversation_id: str) -> Optional[ConversationSession]:
        """
        Get in-memory session.
        """

        return self._sessions.get(conversation_id)

    def register_session(self, session: ConversationSession) -> None:
        """Register an in-memory session created by a transport adapter."""
        self._sessions[session.conversation_id] = session

    async def update_customer_last_interaction(self, customer_id: str) -> None:
        """
        Update customer's last interaction timestamp.
        """

        if not mongodb.is_connected:
            logger.debug("Skipping customer interaction update because MongoDB is unavailable.")
            return

        await collections.customers.update_one(
            {"_id": customer_id},
            {"$set": {"last_interaction_at": datetime.utcnow()}}
        )

    async def get_or_create_customer(
        self,
        tenant_id: str,
        phone_number: str,
        wa_id: str,
        name: Optional[str] = None
    ) -> Customer:
        """
        Get existing customer or create new one.
        """

        if not mongodb.is_connected:
            logger.debug("Skipping customer lookup because MongoDB is unavailable.")
            return Customer(
                id=str(uuid4()),
                tenant_id=tenant_id,
                phone_number=phone_number,
                wa_id=wa_id,
                name=name,
            )

        customer_doc = await collections.customers.find_one({
            "tenant_id": tenant_id,
            "wa_id": wa_id
        })

        if customer_doc:
            customer = Customer(**customer_doc)
            # Update last interaction
            await self.update_customer_last_interaction(customer.id)
            return customer

        # Create new customer
        customer = Customer(
            id=str(uuid4()),
            tenant_id=tenant_id,
            phone_number=phone_number,
            wa_id=wa_id,
            name=name
        )

        await collections.customers.insert_one(
            customer.model_dump(by_alias=True, exclude_none=True)
        )
        logger.info(f"Created new customer: {customer.id}")

        return customer


conversation_manager = ConversationManager()
