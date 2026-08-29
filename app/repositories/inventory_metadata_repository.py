from typing import Any, Dict, Optional

from app.database.collections import collections
from app.database.mongodb import mongodb


class InventoryMetadataRepository:
    async def get(
        self,
        tenant_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Return the tenant's metadata, with a global fallback."""
        if not tenant_id or not mongodb.is_connected:
            return None

        document = await collections.inventory_metadata.find_one(
            {"tenant_id": tenant_id}
        )
        if document:
            return document

        return await collections.inventory_metadata.find_one(
            {"tenant_id": {"$exists": False}}
        )


inventory_metadata_repository = InventoryMetadataRepository()