from app.database.collections import collections
from app.database.mongodb import mongodb
from app.utils.logger import logger


async def ensure_indexes() -> None:
    """
    Create MongoDB indexes required by Meridin.

    Safe to call during application startup.
    """

    if not mongodb.is_connected:
        logger.warning(
            "MongoDB unavailable. Index creation skipped."
        )
        return

    # ---------------------------------------------------------
    # CUSTOMERS
    # ---------------------------------------------------------

    await collections.customers.create_index(
        [
            ("tenant_id", 1),
            ("wa_id", 1),
        ],
        unique=True,
        name="unique_customer_per_tenant_wa_id",
    )

    # ---------------------------------------------------------
    # CONVERSATIONS
    # ---------------------------------------------------------

    await collections.conversations.create_index(
        [
            ("tenant_id", 1),
            ("customer_id", 1),
            ("status", 1),
        ],
        name="conversation_lookup",
    )

    # ---------------------------------------------------------
    # MESSAGES
    # ---------------------------------------------------------

    await collections.messages.create_index(
        [
            ("tenant_id", 1),
            ("whatsapp_message_id", 1),
        ],
        unique=True,
        sparse=True,
        name="unique_whatsapp_message_per_tenant",
    )

    await collections.messages.create_index(
        [
            ("conversation_id", 1),
            ("created_at", -1),
        ],
        name="conversation_message_history",
    )

    logger.info(
        "MongoDB indexes verified."
    )