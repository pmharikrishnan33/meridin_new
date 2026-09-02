from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import uuid
from urllib.parse import quote
from typing import Any, Dict, List, Optional
from app.core.config import settings
from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field

from app.core.dashboard_security import get_current_client
from app.database.collections import collections
from app.database.mongodb import mongodb
from app.repositories.product_repository import product_repository
from app.services.catalog_metadata_service import CatalogMetadataService
from app.models.schemas import TenantAISettings, TenantBusinessProfile, TenantCustomerSupport
from app.services.r2_usage_service import R2_GUARD_STORAGE_BYTES, r2_usage_service
from app.database.redis_cache import redis_cache
from app.utils.logger import logger


router = APIRouter(
    prefix="/dashboard/client",
    tags=["Client Dashboard"],
)


class ProductCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: Optional[str] = None
    price: float = Field(ge=0)
    department_id: Optional[int] = None
    category_id: Optional[int] = None
    category: Optional[str] = None
    type: Optional[str] = None
    brand: Optional[str] = None
    color_ids: List[int] = Field(default_factory=list)
    color: List[str] = Field(default_factory=list)
    size_group: Optional[str] = None
    size_ids: List[int] = Field(default_factory=list)
    size: List[str] = Field(default_factory=list)
    material: Optional[str] = None
    fit: Optional[str] = None
    gender: Optional[str] = None
    age_group: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    stock: int = Field(default=0, ge=0)
    media: List[str] = Field(default_factory=list)
    variants: List[Dict[str, Any]] = Field(default_factory=list)
    attributes: Dict[str, Any] = Field(default_factory=dict)
    is_featured: bool = False


class CollectionCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    description: Optional[str] = None
    product_ids: List[str] = Field(
        default_factory=list
    )
    is_active: bool = True


class CollectionUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    product_ids: Optional[List[str]] = None
    is_active: Optional[bool] = None


def _serialize(value: Any) -> Any:
    if isinstance(value, ObjectId):
        return str(value)

    if isinstance(value, datetime):
        return value.isoformat()

    if isinstance(value, dict):
        return {
            key: _serialize(item)
            for key, item in value.items()
        }

    if isinstance(value, list):
        return [
            _serialize(item)
            for item in value
        ]

    return value


def _client_id(user: Dict[str, Any]) -> str:
    tenant_id = user.get("tenant_id")

    if not tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tenant context is missing.",
        )

    return tenant_id


@router.get("/overview")
async def overview(
    user: Dict[str, Any] = Depends(get_current_client),
) -> Dict[str, Any]:
    tenant_id = _client_id(user)

    if not mongodb.is_connected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database is unavailable.",
        )

    products_count = await collections.products(
        tenant_id
    ).count_documents({})

    customers_count = await collections.customers.count_documents(
        {"tenant_id": tenant_id}
    )

    conversations_count = (
        await collections.conversations.count_documents(
            {"tenant_id": tenant_id}
        )
    )

    messages_count = await collections.messages.count_documents(
        {"tenant_id": tenant_id}
    )

    inbound_count = await collections.messages.count_documents(
        {
            "tenant_id": tenant_id,
            "direction": "inbound",
        }
    )

    outbound_count = await collections.messages.count_documents(
        {
            "tenant_id": tenant_id,
            "direction": "outbound",
        }
    )

    active_conversations = (
        await collections.conversations.count_documents(
            {
                "tenant_id": tenant_id,
                "status": "active",
            }
        )
    )

    recent_messages_cursor = (
        collections.messages.find(
            {
                "tenant_id": tenant_id,
            }
        )
        .sort("created_at", -1)
        .limit(10)
    )

    recent_messages = []

    async for message in recent_messages_cursor:
        recent_messages.append(
            _serialize(message)
        )

    return {
        "tenant_id": tenant_id,
        "metrics": {
            "products": products_count,
            "customers": customers_count,
            "conversations": conversations_count,
            "messages": messages_count,
            "inbound_messages": inbound_count,
            "outbound_messages": outbound_count,
            "active_conversations": active_conversations,
        },
        "recent_messages": recent_messages,
    }


class AISettingsUpdateRequest(BaseModel):
    business_profile: TenantBusinessProfile = Field(default_factory=TenantBusinessProfile)
    customer_support: TenantCustomerSupport = Field(default_factory=TenantCustomerSupport)
    ai: TenantAISettings = Field(default_factory=TenantAISettings)


@router.get("/settings")
async def get_settings(
    user: Dict[str, Any] = Depends(get_current_client),
) -> Dict[str, Any]:
    tenant_id = _client_id(user)

    if not mongodb.is_connected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database is unavailable.",
        )

    document = await collections.clients.find_one(
        {"tenant_id": tenant_id, "is_active": True},
        {
            "business_name": 1,
            "welcome_message": 1,
            "fallback_message": 1,
            "settings.business_profile": 1,
            "settings.customer_support": 1,
            "settings.ai": 1,
        },
    )

    if not document:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Client settings not found.",
        )

    settings = document.get("settings") or {}
    return {
        "business_name": document.get("business_name", ""),
        "welcome_message": document.get("welcome_message"),
        "fallback_message": document.get("fallback_message"),
        "business_profile": settings.get("business_profile") or {
            "shop_name": document.get("business_name", ""),
        },
        "customer_support": settings.get("customer_support") or {},
        "ai": settings.get("ai") or {},
    }


@router.put("/settings")
async def update_settings(
    payload: AISettingsUpdateRequest,
    user: Dict[str, Any] = Depends(get_current_client),
) -> Dict[str, Any]:
    tenant_id = _client_id(user)

    if not mongodb.is_connected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database is unavailable.",
        )

    profile = payload.business_profile.model_dump(exclude_none=True)
    support = payload.customer_support.model_dump(exclude_none=True)
    ai = payload.ai.model_dump(exclude_none=True)

    if not profile.get("shop_name"):
        current = await collections.clients.find_one(
            {"tenant_id": tenant_id, "is_active": True},
            {"business_name": 1},
        )
        if current and current.get("business_name"):
            profile["shop_name"] = current["business_name"]

    result = await collections.clients.update_one(
        {"tenant_id": tenant_id, "is_active": True},
        {
            "$set": {
                "settings.business_profile": profile,
                "settings.customer_support": support,
                "settings.ai": ai,
                "updated_at": datetime.now(timezone.utc),
                **({"business_name": profile["shop_name"]} if profile.get("shop_name") else {}),
            }
        },
    )

    if result.matched_count == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Client settings not found.",
        )

    return {
        "saved": True,
        "business_profile": profile,
        "customer_support": support,
        "ai": ai,
    }


@router.get("/products")
async def products(
    search: Optional[str] = None,
    category: Optional[str] = None,
    limit: int = Query(
        default=50,
        ge=1,
        le=100,
    ),
    offset: int = Query(
        default=0,
        ge=0,
    ),
    user: Dict[str, Any] = Depends(
        get_current_client
    ),
) -> Dict[str, Any]:
    tenant_id = _client_id(user)

    from app.models.schemas import ProductSearchFilters

    filters = ProductSearchFilters(
        query=search,
        category=category,
        limit=limit,
        offset=offset,
        in_stock_only=False,
    )

    products_result = await product_repository.search(
        tenant_id,
        filters,
    )

    return {
        "items": [
            product.model_dump(
                by_alias=True,
                mode="json",
            )
            for product in products_result
        ],
        "limit": limit,
        "offset": offset,
    }


@router.get("/catalog-metadata")
async def catalog_metadata(
    user: Dict[str, Any] = Depends(get_current_client),
) -> Dict[str, Any]:
    """Return tenant catalog metadata needed by the client product editor."""
    tenant_id = _client_id(user)
    if not mongodb.is_connected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database is unavailable.",
        )

    service = CatalogMetadataService()
    metadata = await service.get_metadata(tenant_id)
    display_maps = await service.get_display_maps(tenant_id)
    return {
        "metadata": {
            **display_maps,
            "raw": _serialize(metadata),
        }
    }


class ImageUploadRequest(BaseModel):
    content_length: int = Field(ge=1, le=5_000_000)


@router.post("/products/image-upload-url")
async def product_image_upload_url(
    payload: ImageUploadRequest,
    user: Dict[str, Any] = Depends(get_current_client),
) -> Dict[str, Any]:
    """Create a short-lived Cloudflare R2 presigned JPG upload URL.

    R2 credentials stay on the server. The upload itself goes directly from
    the browser to R2. The upload URL is issued only while the global Meridin
    R2 safety guard has capacity.
    """
    _client_id(user)  # Authentication is required; usage is global.

    if not redis_cache.is_connected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Image storage is temporarily disabled because the usage guard is unavailable.",
        )

    account_id = settings.CLOUDFLARE_R2_ACCOUNT_ID.strip()
    access_key_id = settings.CLOUDFLARE_R2_ACCESS_KEY_ID.strip()
    secret_access_key = settings.CLOUDFLARE_R2_SECRET_ACCESS_KEY.strip()
    bucket_name = settings.CLOUDFLARE_R2_BUCKET_NAME.strip()
    public_base = settings.MEDIA_PUBLIC_BASE_URL.strip().rstrip("/")

    if not all([account_id, access_key_id, secret_access_key, bucket_name, public_base]):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Cloudflare R2 image storage is not configured.",
        )

    try:
        # Storage is a GB-month metric. We conservatively block at 90% of
        # the monthly free-tier capacity rather than attempting to use all 10 GB.
        metrics = await r2_usage_service.cloudflare_metrics()
        current_storage = int(metrics.get("storage_bytes", 0))

        if current_storage + payload.content_length > R2_GUARD_STORAGE_BYTES:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Global image storage safety limit reached. New uploads are temporarily disabled.",
            )

        if not await r2_usage_service.reserve_upload():
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Global monthly image-upload safety limit reached. New uploads are temporarily disabled.",
            )

        import boto3
        from botocore.client import Config

        s3 = boto3.client(
            "s3",
            endpoint_url=(
                f"https://{account_id}.r2.cloudflarestorage.com"
            ),
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            region_name="auto",
            config=Config(signature_version="s3v4"),
        )

        object_name = f"products/{uuid.uuid4()}.jpg"

        upload_url = s3.generate_presigned_url(
            "put_object",
            Params={
                "Bucket": bucket_name,
                "Key": object_name,
                "ContentType": "image/jpeg",
                "ContentLength": payload.content_length,
            },
            ExpiresIn=900,
        )

        image_url = f"{public_base}/api/dashboard/client/media/{quote(object_name, safe='/')}"

        return {
            "upload_url": upload_url,
            "image_url": image_url,
            "object_name": object_name,
            "content_type": "image/jpeg",
            "expires_in": 900,
        }

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Unable to create R2 image upload URL: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to prepare image storage.",
        ) from exc


@router.get("/media/{object_name:path}")
async def serve_media(object_name: str) -> Response:
    """Serve Meridin media through the API so the global Class B guard can stop views.

    Do not expose the R2 bucket directly in MongoDB. Every image request must
    pass through this endpoint; otherwise Meridin cannot stop Class B reads.
    """
    if not object_name.startswith("products/") or ".." in object_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid media path.",
        )

    if not redis_cache.is_connected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Image service is temporarily disabled.",
        )

    if not await r2_usage_service.reserve_view():
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Global monthly image-view safety limit reached. Image serving is temporarily disabled.",
        )

    account_id = settings.CLOUDFLARE_R2_ACCOUNT_ID.strip()
    access_key_id = settings.CLOUDFLARE_R2_ACCESS_KEY_ID.strip()
    secret_access_key = settings.CLOUDFLARE_R2_SECRET_ACCESS_KEY.strip()
    bucket_name = settings.CLOUDFLARE_R2_BUCKET_NAME.strip()

    if not all([account_id, access_key_id, secret_access_key, bucket_name]):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Cloudflare R2 image storage is not configured.",
        )

    try:
        import boto3
        from botocore.client import Config

        s3 = boto3.client(
            "s3",
            endpoint_url=(
                f"https://{account_id}.r2.cloudflarestorage.com"
            ),
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            region_name="auto",
            config=Config(signature_version="s3v4"),
        )

        result = await asyncio.to_thread(
            s3.get_object,
            Bucket=bucket_name,
            Key=object_name,
        )

        body = await asyncio.to_thread(result["Body"].read)
        content_type = result.get("ContentType") or "image/jpeg"

        return Response(
            content=body,
            media_type=content_type,
            headers={
                "Cache-Control": "public, max-age=86400",
                "ETag": str(result.get("ETag", "")).strip('"'),
            },
        )

    except Exception as exc:
        logger.exception("R2 media read failed for %s: %s", object_name, exc)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Image not found.",
        ) from exc


@router.post("/products")
async def create_product(
    payload: ProductCreateRequest,
    user: Dict[str, Any] = Depends(
        get_current_client
    ),
) -> Dict[str, Any]:
    tenant_id = _client_id(user)

    if not mongodb.is_connected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database is unavailable.",
            )

    now = datetime.now(timezone.utc)

    document = payload.model_dump()

    document.update(
        {
            "tenant_id": tenant_id,
            "created_at": now,
            "updated_at": now,
        }
    )

    result = await collections.products(
        tenant_id
    ).insert_one(document)

    created = await collections.products(
        tenant_id
    ).find_one(
        {
            "_id": result.inserted_id,
            "tenant_id": tenant_id,
        }
    )

    return {
        "item": _serialize(created),
    }


@router.get("/products/{product_id}")
async def product_detail(
    product_id: str,
    user: Dict[str, Any] = Depends(
        get_current_client
    ),
) -> Dict[str, Any]:
    tenant_id = _client_id(user)

    product = await product_repository.find_by_id(
        tenant_id,
        product_id,
    )

    if not product:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found.",
        )

    return {
        "item": product.model_dump(
            by_alias=True,
            mode="json",
        )
    }


@router.patch("/products/{product_id}")
async def update_product(
    product_id: str,
    payload: ProductCreateRequest,
    user: Dict[str, Any] = Depends(get_current_client),
) -> Dict[str, Any]:
    tenant_id = _client_id(user)
    if not mongodb.is_connected:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Database is unavailable.")

    candidates = [product_id]
    if ObjectId.is_valid(product_id):
        candidates.append(ObjectId(product_id))

    document = payload.model_dump()
    document["updated_at"] = datetime.now(timezone.utc)

    result = await collections.products(tenant_id).update_one(
        {"tenant_id": tenant_id, "_id": {"$in": candidates}},
        {"$set": document},
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found.")

    updated = await collections.products(tenant_id).find_one(
        {"tenant_id": tenant_id, "_id": {"$in": candidates}}
    )
    return {"item": _serialize(updated)}


@router.delete("/products/{product_id}")
async def delete_product(
    product_id: str,
    user: Dict[str, Any] = Depends(
        get_current_client
    ),
) -> Dict[str, Any]:
    tenant_id = _client_id(user)

    candidates: List[Any] = [
        product_id,
    ]

    if ObjectId.is_valid(product_id):
        candidates.append(
            ObjectId(product_id)
        )

    result = await collections.products(
        tenant_id
    ).delete_one(
        {
            "tenant_id": tenant_id,
            "_id": {
                "$in": candidates,
            },
        }
    )

    if result.deleted_count == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Product not found.",
        )

    return {
        "deleted": True,
    }


@router.get("/collections")
async def get_collections(
    user: Dict[str, Any] = Depends(
        get_current_client
    ),
) -> Dict[str, Any]:
    tenant_id = _client_id(user)

    cursor = (
        collections.collections.find(
            {
                "tenant_id": tenant_id,
            }
        )
        .sort("created_at", -1)
    )

    items = []

    async for document in cursor:
        items.append(
            _serialize(document)
        )

    return {
        "items": items,
    }


@router.post("/collections")
async def create_collection(
    payload: CollectionCreateRequest,
    user: Dict[str, Any] = Depends(
        get_current_client
    ),
) -> Dict[str, Any]:
    tenant_id = _client_id(user)

    now = datetime.now(timezone.utc)

    document = {
        "tenant_id": tenant_id,
        "name": payload.name.strip(),
        "description": payload.description,
        "product_ids": payload.product_ids,
        "is_active": payload.is_active,
        "created_at": now,
        "updated_at": now,
    }

    result = await collections.collections.insert_one(
        document
    )

    created = await collections.collections.find_one(
        {
            "_id": result.inserted_id,
            "tenant_id": tenant_id,
        }
    )

    return {
        "item": _serialize(created),
    }


@router.put("/collections/{collection_id}")
async def update_collection(
    collection_id: str,
    payload: CollectionUpdateRequest,
    user: Dict[str, Any] = Depends(
        get_current_client
    ),
) -> Dict[str, Any]:
    tenant_id = _client_id(user)

    if not ObjectId.is_valid(collection_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid collection ID.",
        )

    update_data = {
        key: value
        for key, value in payload.model_dump().items()
        if value is not None
    }

    if "name" in update_data:
        update_data["name"] = (
            update_data["name"].strip()
        )

    update_data["updated_at"] = (
        datetime.now(timezone.utc)
    )

    result = await collections.collections.update_one(
        {
            "_id": ObjectId(collection_id),
            "tenant_id": tenant_id,
        },
        {
            "$set": update_data,
        },
    )

    if result.matched_count == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Collection not found.",
        )

    document = await collections.collections.find_one(
        {
            "_id": ObjectId(collection_id),
            "tenant_id": tenant_id,
        }
    )

    return {
        "item": _serialize(document),
    }


@router.delete("/collections/{collection_id}")
async def delete_collection(
    collection_id: str,
    user: Dict[str, Any] = Depends(
        get_current_client
    ),
) -> Dict[str, Any]:
    tenant_id = _client_id(user)

    if not ObjectId.is_valid(collection_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid collection ID.",
        )

    result = await collections.collections.delete_one(
        {
            "_id": ObjectId(collection_id),
            "tenant_id": tenant_id,
        }
    )

    if result.deleted_count == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Collection not found.",
        )

    return {
        "deleted": True,
    }


@router.get("/messages")
async def messages(
    limit: int = Query(
        default=50,
        ge=1,
        le=100,
    ),
    user: Dict[str, Any] = Depends(
        get_current_client
    ),
) -> Dict[str, Any]:
    tenant_id = _client_id(user)

    cursor = (
        collections.messages.find(
            {
                "tenant_id": tenant_id,
            }
        )
        .sort("created_at", -1)
        .limit(limit)
    )

    items = []

    async for document in cursor:
        items.append(
            _serialize(document)
        )

    return {
        "items": items,
    }


@router.get("/leads")
async def leads(
    user: Dict[str, Any] = Depends(
        get_current_client
    ),
) -> Dict[str, Any]:
    tenant_id = _client_id(user)

    cursor = (
        collections.messages.find(
            {
                "tenant_id": tenant_id,
                "direction": "inbound",
                "intent": {
                    "$nin": [
                        "greeting",
                        "thanks",
                    ]
                },
            }
        )
        .sort("created_at", -1)
        .limit(100)
    )

    items = []

    async for document in cursor:
        items.append(
            _serialize(document)
        )

    return {
        "items": items,
    }


@router.get("/analytics")
async def analytics(
    days: int = Query(
        default=7,
        ge=1,
        le=90,
    ),
    user: Dict[str, Any] = Depends(
        get_current_client
    ),
) -> Dict[str, Any]:
    tenant_id = _client_id(user)

    now = datetime.now(timezone.utc)

    start = now - timedelta(
        days=days
    )

    pipeline = [
        {
            "$match": {
                "tenant_id": tenant_id,
                "created_at": {
                    "$gte": start,
                },
            }
        },
        {
            "$group": {
                "_id": {
                    "$dateToString": {
                        "format": "%Y-%m-%d",
                        "date": "$created_at",
                    }
                },
                "messages": {
                    "$sum": 1
                },
                "inbound": {
                    "$sum": {
                        "$cond": [
                            {
                                "$eq": [
                                    "$direction",
                                    "inbound",
                                ]
                            },
                            1,
                            0,
                        ]
                    }
                },
                "outbound": {
                    "$sum": {
                        "$cond": [
                            {
                                "$eq": [
                                    "$direction",
                                    "outbound",
                                ]
                            },
                            1,
                            0,
                        ]
                    }
                },
            }
        },
        {
            "$sort": {
                "_id": 1,
            }
        },
    ]

    daily = []

    async for row in collections.messages.aggregate(
        pipeline
    ):
        daily.append(
            _serialize(row)
        )

    intent_pipeline = [
        {
            "$match": {
                "tenant_id": tenant_id,
                "direction": "inbound",
                "intent": {
                    "$ne": None,
                },
                "created_at": {
                    "$gte": start,
                },
            }
        },
        {
            "$group": {
                "_id": "$intent",
                "count": {
                    "$sum": 1,
                },
            }
        },
        {
            "$sort": {
                "count": -1,
            }
        },
        {
            "$limit": 10,
        },
    ]

    intents = []

    async for row in collections.messages.aggregate(
        intent_pipeline
    ):
        intents.append(
            _serialize(row)
        )

    return {
        "days": days,
        "daily": daily,
        "intents": intents,
    }


