"""
Repository layer for tenant/client data access.

MongoDB collection:
    clients

Application/domain concept:
    Tenant

The MongoDB document uses:
    _id
    tenant_id
    phone_number_id
    access_token
    webhook_verify_token
    feature_flags
    settings
"""

from typing import Optional

from app.database.collections import collections
from app.database.mongodb import mongodb
from app.models.schemas import Tenant
from app.utils.helpers import normalize_mongo_doc
from app.utils.logger import logger


class TenantRepository:
    """MongoDB-backed repository for client/tenant configuration."""

    async def find_by_phone_number_id(
        self,
        phone_number_id: str,
    ) -> Optional[Tenant]:
        """
        Resolve a tenant from the WhatsApp Business phone number ID.
        """

        if not mongodb.is_connected or not phone_number_id:
            return None

        doc = await collections.clients.find_one(
            {
                "phone_number_id": phone_number_id,
                "is_active": True,
            }
        )

        if not doc:
            return None

        try:
            return Tenant(
                **normalize_mongo_doc(doc.copy())
            )
        except Exception:
            logger.exception(
                "Failed to parse tenant document for phone_number_id=%s",
                phone_number_id,
            )
            return None

    async def find_by_tenant_id(
        self,
        tenant_id: str,
    ) -> Optional[Tenant]:
        """
        Resolve an active tenant using the application tenant_id.

        Example:
            meridin_clothing
        """

        if not mongodb.is_connected or not tenant_id:
            return None

        doc = await collections.clients.find_one(
            {
                "tenant_id": tenant_id,
                "is_active": True,
            }
        )

        if not doc:
            return None

        try:
            return Tenant(
                **normalize_mongo_doc(doc.copy())
            )
        except Exception:
            logger.exception(
                "Failed to parse tenant document for tenant_id=%s",
                tenant_id,
            )
            return None

    async def find_by_id(
        self,
        client_id: str,
    ) -> Optional[Tenant]:
        """
        Resolve a tenant by MongoDB _id.

        This is the internal client-document ID and is different
        from tenant_id.
        """

        if not mongodb.is_connected or not client_id:
            return None

        lookup_id = client_id

        try:
            from bson import ObjectId

            if ObjectId.is_valid(client_id):
                lookup_id = ObjectId(client_id)

        except ImportError:
            pass

        doc = await collections.clients.find_one(
            {
                "_id": lookup_id,
                "is_active": True,
            }
        )

        if not doc:
            return None

        try:
            return Tenant(
                **normalize_mongo_doc(doc.copy())
            )
        except Exception:
            logger.exception(
                "Failed to parse tenant document for _id=%s",
                client_id,
            )
            return None

    async def verify_verify_token(
        self,
        verify_token: str,
    ) -> Optional[Tenant]:
        """
        Resolve the tenant during Meta webhook verification.
        """

        if not mongodb.is_connected or not verify_token:
            return None

        doc = await collections.clients.find_one(
            {
                "webhook_verify_token": verify_token,
                "is_active": True,
            }
        )

        if not doc:
            return None

        try:
            return Tenant(
                **normalize_mongo_doc(doc.copy())
            )
        except Exception:
            logger.exception(
                "Failed to parse tenant document during webhook verification"
            )
            return None


tenant_repository = TenantRepository()