from typing import Optional

from motor.motor_asyncio import AsyncIOMotorCollection

from app.database.mongodb import mongodb


class Collections:
    """
    MongoDB collections with tenant-aware access.
    All tenant-specific data is accessed through these collections.
    """

    @property
    def tenants(self) -> AsyncIOMotorCollection:
        """Tenant/client documents are stored in the 'clients' collection."""
        return mongodb.get_database()["clients"]

    @property
    def products(self) -> AsyncIOMotorCollection:
        return mongodb.get_database()["products"]

    @property
    def customers(self) -> AsyncIOMotorCollection:
        return mongodb.get_database()["customers"]

    @property
    def conversations(self) -> AsyncIOMotorCollection:
        return mongodb.get_database()["conversations"]

    @property
    def messages(self) -> AsyncIOMotorCollection:
        return mongodb.get_database()["messages"]

    @property
    def orders(self) -> AsyncIOMotorCollection:
        return mongodb.get_database()["orders"]

    @property
    def analytics(self) -> AsyncIOMotorCollection:
        return mongodb.get_database()["analytics"]

    @property
    def templates(self) -> AsyncIOMotorCollection:
        """Message templates stored per-tenant for response rendering."""
        return mongodb.get_database()["templates"]

    @property
    def inventory_metadata(self) -> AsyncIOMotorCollection:
        """Color / size / attribute name resolution (type-discriminated)."""
        return mongodb.get_database()["inventory_metadata"]

    # --- Inventory (new multi-collection schema) ------------------------------

    @property
    def clothing_attributes(self) -> AsyncIOMotorCollection:
        """Shared attribute/variant lookup collection (all brands)."""
        return mongodb.get_database()["inventory.clothing_attributes"]

    def clothing(self, brand: Optional[str] = None) -> AsyncIOMotorCollection:
        """
        Return the per-brand clothing collection.

        Collection name follows the pattern ``inventory.clothing_{brand}``.
        When ``brand`` is None, falls back to a brand-agnostic collection.
        """
        brand_suffix = brand.lower().replace(" ", "_") if brand else "default"
        return mongodb.get_database()[f"inventory.clothing_{brand_suffix}"]

    def clothing_store(self, store_name: str) -> AsyncIOMotorCollection:
        """
        Return the per-store inventory collection.

        Collection name follows the pattern ``inventory.<store_name>``
        (e.g. ``inventory.nike``, ``inventory.hm``).  When ``store_name``
        is empty or None, falls back to a default collection.
        """
        suffix = store_name.lower().replace(" ", "_") if store_name else "default"
        return mongodb.get_database()[f"inventory.{suffix}"]


collections = Collections()