from typing import Optional

from app.database.collections import collections
from app.database.mongodb import mongodb


class TemplateRepository:

    async def get(
        self,
        tenant_id: str,
        name: str,
    ) -> Optional[str]:

        if not mongodb.is_connected:
            return None

        document = (
            await collections.templates.find_one(
                {
                    "tenant_id": tenant_id,
                    "name": name,
                    "is_active": True,
                }
            )
        )

        if not document:
            return None

        return document.get(
            "body_text"
        )


template_repository = TemplateRepository()