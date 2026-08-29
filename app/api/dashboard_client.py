from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.core.dashboard_security import get_current_client
from app.database.collections import collections
from app.database.mongodb import mongodb
from app.repositories.product_repository import product_repository


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


