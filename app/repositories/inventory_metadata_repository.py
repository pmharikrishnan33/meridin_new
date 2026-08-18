from typing import Any, Dict, Optional

from app.database.collections import collections
from app.database.mongodb import mongodb


class InventoryMetadataRepository:

    async def get(
        self,
        tenant_id: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Return inventory metadata.

        The current metadata document is global/shared.
        Tenant-specific metadata can be introduced later
        if required.
        """

        if not mongodb.is_connected:
            return None

        document = (
            await collections.inventory_metadata.find_one(
                {}
            )
        )

        return document


inventory_metadata_repository = (
    InventoryMetadataRepository()
)