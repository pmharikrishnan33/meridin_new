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


collections = Collections()