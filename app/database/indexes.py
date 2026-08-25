from pymongo.errors import (
    OperationFailure,
    PyMongoError,
)

from app.database.collections import collections
from app.database.mongodb import mongodb
from app.utils.logger import logger


async def _create_index(
    collection,
    keys,
    *,
    name: str,
    unique: bool = False,
    sparse: bool = False,
    partial_filter_expression=None,
) -> None:
    """
    Create one MongoDB index safely.

    MongoDB remains the authority for uniqueness.

    Index creation is idempotent when the same index already exists
    with the same definition.
    """

    kwargs = {
        "unique": unique,
        "sparse": sparse,
        "name": name,
    }

    if partial_filter_expression is not None:
        kwargs[
            "partialFilterExpression"
        ] = partial_filter_expression

    try:

        await collection.create_index(
            keys,
            **kwargs,
        )

    except OperationFailure as exc:

        # MongoDB can reject an index when an index with the same
        # name already exists but has a different definition.
        #
        # Do NOT silently ignore that situation because it means
        # the database schema does not match the application schema.

        logger.error(
            "MongoDB index '%s' could not be created: %s",
            name,
            exc,
        )

        raise

    except PyMongoError as exc:

        logger.error(
            "MongoDB error while creating index '%s': %s",
            name,
            exc,
        )

        raise


async def ensure_indexes() -> None:
    """
    Create all MongoDB indexes required by Meridin.

    MongoDB is the authority for uniqueness. Application-level
    find-then-insert checks alone are not sufficient under concurrency.

    This function is safe to call during application startup.
    """

    if not mongodb.is_connected:

        logger.warning(
            "MongoDB unavailable. "
            "Index creation skipped."
        )

        return

    # =========================================================
    # CUSTOMERS
    # =========================================================

    await _create_index(
        collections.customers,

        [
            ("tenant_id", 1),
            ("wa_id", 1),
        ],

        unique=True,

        name=(
            "unique_customer_per_tenant_wa_id"
        ),
    )

    # =========================================================
    # CONVERSATIONS
    # =========================================================

    # Only ONE active conversation may exist for a customer
    # inside a tenant.
    #
    # This is a partial unique index, so historical/closed
    # conversations are allowed.

    await _create_index(
        collections.conversations,

        [
            ("tenant_id", 1),
            ("customer_id", 1),
            ("status", 1),
        ],

        unique=True,

        partial_filter_expression={
            "status": "active",
        },

        name=(
            "unique_active_conversation_per_customer"
        ),
    )

    # =========================================================
    # CONVERSATION LOOKUP
    # =========================================================

    await _create_index(
        collections.conversations,

        [
            ("tenant_id", 1),
            ("customer_id", 1),
            ("updated_at", -1),
        ],

        name=(
            "conversation_lookup"
        ),
    )

    # =========================================================
    # MESSAGES
    # =========================================================

    # WhatsApp message IDs are unique PER TENANT.
    #
    # This is the database-level protection required for
    # webhook idempotency.
    #
    # sparse=True allows outbound/system messages that do not
    # have a WhatsApp provider message ID yet.

    await _create_index(
        collections.messages,

        [
            ("tenant_id", 1),
            ("whatsapp_message_id", 1),
        ],

        unique=True,

        sparse=True,

        name=(
            "unique_whatsapp_message_per_tenant"
        ),
    )

    # =========================================================
    # MESSAGE HISTORY
    # =========================================================

    await _create_index(
        collections.messages,

        [
            ("conversation_id", 1),
            ("created_at", -1),
        ],

        name=(
            "conversation_message_history"
        ),
    )

    # =========================================================
    # OUTBOUND DELIVERY LOOKUP
    # =========================================================

    # Used for:
    #
    # - pending outbound-message recovery
    # - failed message inspection
    # - delivery-status queries
    #
    # tenant_id is intentionally included because Meridin
    # is multi-tenant.

    await _create_index(
        collections.messages,

        [
            ("tenant_id", 1),
            ("direction", 1),
            ("delivery_status", 1),
            ("created_at", -1),
        ],

        name=(
            "outbound_delivery_lookup"
        ),
    )

    logger.info(
        "MongoDB indexes verified successfully."
    )