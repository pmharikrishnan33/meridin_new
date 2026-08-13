"""
Repository layer for conversation data access.

Encapsulates MongoDB queries behind a clean interface for conversation
and message persistence.
"""

from typing import List, Optional

from app.database.collections import collections
from app.database.mongodb import mongodb
from app.models.schemas import Conversation, ConversationStatus, Message
from app.utils.helpers import normalize_mongo_doc
from app.utils.logger import logger


class ConversationRepository:
    """
    MongoDB-backed repository for Conversation and Message documents.
    """

    async def find_active(
        self,
        tenant_id: str,
        customer_id: str,
    ) -> Optional[Conversation]:
        """Find the most recent active conversation for a customer."""
        if not mongodb.is_connected:
            return None

        doc = await collections.conversations.find_one(
            {
                "tenant_id": tenant_id,
                "customer_id": customer_id,
                "status": ConversationStatus.ACTIVE.value,
            },
            sort=[("updated_at", -1)],
        )
        return Conversation(**normalize_mongo_doc(doc)) if doc else None

    async def find_by_id(self, conversation_id: str) -> Optional[Conversation]:
        """Retrieve a conversation by ID."""
        if not mongodb.is_connected:
            return None

        doc = await collections.conversations.find_one({"_id": conversation_id})
        return Conversation(**normalize_mongo_doc(doc)) if doc else None

    async def insert(self, conversation: Conversation) -> None:
        """Insert a new conversation document."""
        if not mongodb.is_connected:
            logger.debug("Conversation insert skipped — MongoDB unavailable.")
            return

        await collections.conversations.insert_one(
            conversation.model_dump(by_alias=True, exclude_none=True)
        )

    async def update(self, conversation_id: str, update: dict) -> None:
        """Apply a partial update to a conversation document."""
        if not mongodb.is_connected:
            return

        await collections.conversations.update_one(
            {"_id": conversation_id},
            {"$set": update},
        )

    async def insert_message(self, message: Message) -> None:
        """Persist a single message document."""
        if not mongodb.is_connected:
            return

        await collections.messages.insert_one(
            message.model_dump(by_alias=True, exclude_none=True)
        )

    async def find_messages(
        self,
        conversation_id: str,
        limit: int = 50,
    ) -> List[Message]:
        """Retrieve recent messages for a conversation."""
        if not mongodb.is_connected:
            return []

        cursor = (
            collections.messages
            .find({"conversation_id": conversation_id})
            .sort("created_at", -1)
            .limit(limit)
        )

        messages: List[Message] = []
        async for doc in cursor:
            messages.append(Message(**normalize_mongo_doc(doc)))

        return list(reversed(messages))


conversation_repository = ConversationRepository()
