"""
Repository layer for tenant data access.

Resolves tenant-specific Meta / WhatsApp credentials from MongoDB so that
each client can operate with its own ``phone_number_id``, ``access_token``,
``webhook_verify_token``, and ``webhook_secret`` rather than relying solely
on shared environment-level defaults.
"""

from typing import Optional

from app.database.collections import collections
from app.database.mongodb import mongodb
from app.models.schemas import Tenant
from app.utils.helpers import normalize_mongo_doc
from app.utils.logger import logger


class TenantRepository:
    """
    MongoDB-backed repository for ``Tenant`` documents.

    Every method degrades gracefully when MongoDB is unavailable — the
    application falls back to shared environment-level configuration.
    """

    async def find_by_phone_number_id(
        self,
        phone_number_id: str,
    ) -> Optional[Tenant]:
        """Find an active tenant by the WhatsApp Business phone-number ID."""
        if not mongodb.is_connected or not phone_number_id:
            return None

        doc = await collections.tenants.find_one(
            {
                "phone_number_id": phone_number_id,
                "is_active": True,
            }
        )
        if doc:
            normalized_doc = normalize_mongo_doc(doc.copy())
            return Tenant(**normalized_doc)
        return None

    async def find_by_id(self, tenant_id: str) -> Optional[Tenant]:
        """Find an active tenant by its primary ID."""
        if not mongodb.is_connected or not tenant_id:
            return None

        lookup_id = tenant_id
        try:
            from bson import ObjectId
            if ObjectId.is_valid(tenant_id):
                lookup_id = {"$in": [tenant_id, ObjectId(tenant_id)]}
        except ImportError:
            pass

        doc = await collections.tenants.find_one(
            {
                "_id": lookup_id,
                "is_active": True,
            }
        )
        if doc:
            normalized_doc = normalize_mongo_doc(doc.copy())
            return Tenant(**normalized_doc)
        return None

    async def verify_verify_token(self, verify_token: str) -> Optional[Tenant]:
        """
        Find a tenant whose ``webhook_verify_token`` matches the supplied
        value during the Meta verification handshake.
        """
        if not mongodb.is_connected or not verify_token:
            return None

        doc = await collections.tenants.find_one(
            {
                "webhook_verify_token": verify_token,
                "is_active": True,
            }
        )
        if doc:
            normalized_doc = normalize_mongo_doc(doc.copy())
            return Tenant(**normalized_doc)
        return None


tenant_repository = TenantRepository()
