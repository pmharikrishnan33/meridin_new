"""
MongoDB index management for Meridin.

Responsibilities:
- Create and verify application indexes.
- Enforce database-level uniqueness.
- Protect WhatsApp webhook idempotency.
- Protect active conversation uniqueness.
- Create indexes required by tenant inventory searches.
- Keep all tenant-specific inventory indexes isolated
  inside inventory.<tenant_id> collections.

MongoDB is the final authority for uniqueness.
Application-level find-then-insert checks are not sufficient
under concurrent requests.
"""

from __future__ import annotations

from typing import Any, Iterable, Optional

from pymongo.errors import (
    OperationFailure,
    PyMongoError,
)

from app.database.collections import collections
from app.database.mongodb import mongodb
from app.utils.logger import logger


async def _create_index(
    collection: Any,
    keys: Iterable[tuple[str, int]],
    *,
    name: str,
    unique: bool = False,
    sparse: bool = False,
    partial_filter_expression: Optional[dict[str, Any]] = None,
) -> None:
    """
    Create one MongoDB index.

    Index creation is intentionally strict.

    If an index with the same name already exists but has a
    different definition, MongoDB raises an OperationFailure.
    That error is re-raised instead of being silently ignored.

    This is important because silently accepting a schema mismatch
    can leave production running with incorrect uniqueness or
    lookup guarantees.
    """

    kwargs: dict[str, Any] = {
        "name": name,
        "unique": unique,
        "sparse": sparse,
    }

    if partial_filter_expression is not None:
        kwargs["partialFilterExpression"] = (
            partial_filter_expression
        )

    try:
        await collection.create_index(
            list(keys),
            **kwargs,
        )

    except OperationFailure as exc:
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


async def _ensure_customer_indexes() -> None:
    """Create indexes required by the customers collection."""

    await _create_index(
        collections.customers,
        [
            ("tenant_id", 1),
            ("wa_id", 1),
        ],
        unique=True,
        name="unique_customer_per_tenant_wa_id",
    )

    await _create_index(
        collections.customers,
        [
            ("tenant_id", 1),
            ("last_interaction_at", -1),
        ],
        name="customer_last_interaction_lookup",
    )


async def _ensure_conversation_indexes() -> None:
    """
    Create indexes required by the conversations collection.

    Only one active conversation may exist for a customer
    inside a tenant.
    """

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
        name="unique_active_conversation_per_customer",
    )

    await _create_index(
        collections.conversations,
        [
            ("tenant_id", 1),
            ("customer_id", 1),
            ("updated_at", -1),
        ],
        name="conversation_lookup",
    )

    await _create_index(
        collections.conversations,
        [
            ("tenant_id", 1),
            ("updated_at", -1),
        ],
        name="tenant_conversation_updated_lookup",
    )


async def _ensure_message_indexes() -> None:
    """
    Create indexes required by the messages collection.

    WhatsApp provider message IDs must be unique per tenant.

    A partial index is used instead of sparse=True because messages
    can exist before they receive a WhatsApp provider ID.

    Only documents containing an actual string WhatsApp message ID
    participate in the uniqueness constraint.
    """

    await _create_index(
        collections.messages,
        [
            ("tenant_id", 1),
            ("whatsapp_message_id", 1),
        ],
        unique=True,
        partial_filter_expression={
            "whatsapp_message_id": {
                "$type": "string",
            },
        },
        name="unique_whatsapp_message_per_tenant",
    )

    await _create_index(
        collections.messages,
        [
            ("conversation_id", 1),
            ("created_at", -1),
        ],
        name="conversation_message_history",
    )

    await _create_index(
        collections.messages,
        [
            ("tenant_id", 1),
            ("direction", 1),
            ("delivery_status", 1),
            ("created_at", -1),
        ],
        name="outbound_delivery_lookup",
    )

    await _create_index(
        collections.messages,
        [
            ("tenant_id", 1),
            ("created_at", -1),
        ],
        name="tenant_message_created_lookup",
    )

    await _create_index(
        collections.messages,
        [
            ("tenant_id", 1),
            ("direction", 1),
            ("intent", 1),
            ("created_at", -1),
        ],
        name="tenant_message_lead_lookup",
    )



async def _ensure_client_indexes() -> None:
    """Create indexes required by the tenants/clients collection."""

    await _create_index(
        collections.clients,
        [
            ("tenant_id", 1),
        ],
        unique=True,
        name="unique_tenant_id",
    )

    await _create_index(
        collections.clients,
        [
            ("phone_number_id", 1),
        ],
        unique=True,
        name="unique_whatsapp_phone_number_id",
    )

    await _create_index(
        collections.clients,
        [
            ("is_active", 1),
        ],
        name="active_tenant_lookup",
    )

    await _create_index(
        collections.clients,
        [
            ("dashboard_email", 1),
        ],
        unique=True,
        sparse=True,
        name="unique_dashboard_email",
    )


async def _ensure_collection_indexes() -> None:
    """Create indexes required by the collections collection."""

    await _create_index(
        collections.collections,
        [
            ("tenant_id", 1),
            ("created_at", -1),
        ],
        name="tenant_collection_created_lookup",
    )


async def _ensure_order_indexes() -> None:
    """Create indexes required by the orders collection."""

    await _create_index(
        collections.orders,
        [
            ("tenant_id", 1),
            ("order_number", 1),
        ],
        unique=True,
        name="unique_order_number_per_tenant",
    )

    await _create_index(
        collections.orders,
        [
            ("tenant_id", 1),
            ("customer_id", 1),
            ("created_at", -1),
        ],
        name="customer_order_history",
    )


async def _ensure_template_indexes() -> None:
    """Create indexes required by the templates collection."""

    await _create_index(
        collections.templates,
        [
            ("tenant_id", 1),
            ("name", 1),
            ("language", 1),
            ("is_active", 1),
        ],
        name="tenant_template_lookup",
    )


async def _ensure_inventory_metadata_indexes() -> None:
    await _create_index(
        collections.inventory_metadata,
        [("tenant_id", 1)],
        name="inventory_metadata_tenant_lookup",
    )


async def _ensure_inventory_indexes_for_tenant(
    tenant_id: str,
) -> None:
    """
    Create indexes for one tenant's inventory collection.

    Inventory is stored as:

        inventory.<tenant_id>

    Therefore tenant_id must NOT be included in these indexes.
    The collection itself already provides the tenant boundary.
    """

    if not tenant_id:
        return

    tenant_id = tenant_id.strip()

    if not tenant_id:
        return

    collection = collections.products(
        tenant_id
    )

    # ---------------------------------------------------------
    # CATEGORY / TYPE
    # ---------------------------------------------------------

    await _create_index(
        collection,
        [
            ("category", 1),
            ("type", 1),
        ],
        name="product_category_type_lookup",
    )

    # ---------------------------------------------------------
    # BRAND / MATERIAL
    # ---------------------------------------------------------

    await _create_index(
        collection,
        [
            ("brand", 1),
            ("material", 1),
        ],
        name="product_brand_material_lookup",
    )

    # ---------------------------------------------------------
    # PRICE
    # ---------------------------------------------------------

    await _create_index(
        collection,
        [
            ("price", 1),
        ],
        name="product_price_lookup",
    )

    # ---------------------------------------------------------
    # STOCK
    # ---------------------------------------------------------

    await _create_index(
        collection,
        [
            ("stock", 1),
        ],
        name="product_stock_lookup",
    )

    await _create_index(
        collection,
        [
            ("variants.size", 1),
            ("variants.color", 1),
            ("variants.stock", 1),
        ],
        name="product_variant_availability_lookup",
    )

    # ---------------------------------------------------------
    # CREATED AT
    # ---------------------------------------------------------

    await _create_index(
        collection,
        [
            ("created_at", -1),
        ],
        name="product_newest_lookup",
    )

    # ---------------------------------------------------------
    # SIZE
    # ---------------------------------------------------------

    await _create_index(
        collection,
        [
            ("size", 1),
        ],
        name="product_size_lookup",
    )

    # ---------------------------------------------------------
    # COLOR
    # ---------------------------------------------------------

    await _create_index(
        collection,
        [
            ("color", 1),
        ],
        name="product_color_lookup",
    )

    # ---------------------------------------------------------
    # CANONICAL CATALOG IDS
    # ---------------------------------------------------------

    await _create_index(
        collection,
        [("department_id", 1), ("category_id", 1)],
        name="product_department_category_id_lookup",
    )

    await _create_index(
        collection,
        [("category_id", 1), ("price", 1), ("stock", 1)],
        name="product_category_id_price_stock_lookup",
    )

    await _create_index(
        collection,
        [("color_ids", 1)],
        name="product_color_ids_lookup",
    )

    await _create_index(
        collection,
        [("size_ids", 1)],
        name="product_size_ids_lookup",
    )

    await _create_index(
        collection,
        [("attributes.dress_style", 1)],
        name="product_dress_style_lookup",
    )

    # ---------------------------------------------------------
    # COMMON SEARCH COMBINATION
    # ---------------------------------------------------------

    await _create_index(
        collection,
        [
            ("category", 1),
            ("price", 1),
            ("stock", 1),
        ],
        name="product_category_price_stock_lookup",
    )


async def _get_tenant_ids() -> list[str]:
    """
    Retrieve all currently registered tenant IDs.

    Tenant inventory indexes are created for each registered tenant.
    """

    tenant_ids: list[str] = []

    cursor = collections.clients.find(
        {
            "tenant_id": {
                "$type": "string",
            }
        },
        {
            "_id": 0,
            "tenant_id": 1,
        },
    )

    async for document in cursor:

        tenant_id = document.get(
            "tenant_id"
        )

        if not isinstance(
            tenant_id,
            str,
        ):
            continue

        tenant_id = tenant_id.strip()

        if not tenant_id:
            continue

        tenant_ids.append(
            tenant_id
        )

    return list(
        dict.fromkeys(
            tenant_ids
        )
    )


async def _ensure_inventory_indexes() -> None:
    """
    Create indexes for every registered tenant inventory collection.

    Newly created tenants will receive their inventory indexes when
    ensure_indexes() is run again during the next application startup,
    or when this helper is explicitly invoked.
    """

    tenant_ids = await _get_tenant_ids()

    if not tenant_ids:

        logger.info(
            "No registered tenants found. "
            "Tenant inventory indexes skipped."
        )

        return

    for tenant_id in tenant_ids:

        try:

            await _ensure_inventory_indexes_for_tenant(
                tenant_id
            )

            logger.info(
                "Inventory indexes verified for tenant '%s'.",
                tenant_id,
            )

        except PyMongoError:

            logger.exception(
                "Failed to create inventory indexes "
                "for tenant '%s'.",
                tenant_id,
            )

            raise


async def ensure_indexes() -> None:
    """
    Create all MongoDB indexes required by Meridin.

    MongoDB is the authority for uniqueness.

    This function is safe to call during application startup,
    provided MongoDB is already connected.

    Index creation is intentionally fail-fast. If the database
    schema does not match the application schema, application
    startup should expose that problem instead of silently
    continuing.
    """

    if not mongodb.is_connected:

        logger.warning(
            "MongoDB unavailable. "
            "Index creation skipped."
        )

        return

    logger.info(
        "Starting MongoDB index verification..."
    )

    # =========================================================
    # SHARED COLLECTIONS
    # =========================================================

    await _ensure_customer_indexes()

    await _ensure_conversation_indexes()

    await _ensure_message_indexes()

    await _ensure_client_indexes()

    await _ensure_collection_indexes()

    await _ensure_order_indexes()

    await _ensure_template_indexes()
    await _ensure_inventory_metadata_indexes()

    # =========================================================
    # TENANT INVENTORY
    # =========================================================

    await _ensure_inventory_indexes()

    logger.info(
        "MongoDB indexes verified successfully."
    )
