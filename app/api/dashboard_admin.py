from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from app.core.dashboard_security import get_current_admin
from app.database.collections import collections
from app.database.mongodb import mongodb
from app.services.r2_usage_service import r2_usage_service


router = APIRouter(
    prefix="/dashboard/admin",
    tags=["Admin Dashboard"],
)


def serialize(value: Any) -> Any:
    if isinstance(value, ObjectId):
        return str(value)

    if isinstance(value, datetime):
        return value.isoformat()

    if isinstance(value, dict):
        return {
            key: serialize(item)
            for key, item in value.items()
        }

    if isinstance(value, list):
        return [
            serialize(item)
            for item in value
        ]

    return value


class ClientStatusRequest(BaseModel):
    is_active: bool


@router.get("/overview")
async def overview(
    _: Dict[str, Any] = Depends(
        get_current_admin
    ),
) -> Dict[str, Any]:

    if not mongodb.is_connected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database is unavailable.",
        )

    total_clients = (
        await collections.clients.count_documents({})
    )

    active_clients = (
        await collections.clients.count_documents(
            {
                "is_active": True,
            }
        )
    )

    total_messages = (
        await collections.messages.count_documents({})
    )

    total_customers = (
        await collections.customers.count_documents({})
    )

    total_conversations = (
        await collections.conversations.count_documents({})
    )

    return {
        "metrics": {
            "clients": total_clients,
            "active_clients": active_clients,
            "messages": total_messages,
            "customers": total_customers,
            "conversations": total_conversations,
        }
    }


@router.get("/clients")
async def clients(
    limit: int = Query(
        default=100,
        ge=1,
        le=200,
    ),
    _: Dict[str, Any] = Depends(
        get_current_admin
    ),
) -> Dict[str, Any]:

    cursor = (
        collections.clients.find({})
        .sort("created_at", -1)
        .limit(limit)
    )

    items = []

    async for document in cursor:
        safe_document = dict(document)

        safe_document.pop(
            "access_token",
            None,
        )

        safe_document.pop(
            "webhook_verify_token",
            None,
        )

        safe_document.pop(
            "dashboard_password_hash",
            None,
        )

        items.append(
            serialize(safe_document)
        )

    return {
        "items": items,
    }


@router.patch("/clients/{client_id}/status")
async def update_client_status(
    client_id: str,
    payload: ClientStatusRequest,
    _: Dict[str, Any] = Depends(
        get_current_admin
    ),
) -> Dict[str, Any]:

    if not ObjectId.is_valid(client_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid client ID.",
        )

    result = await collections.clients.update_one(
        {
            "_id": ObjectId(client_id),
        },
        {
            "$set": {
                "is_active": payload.is_active,
                "updated_at": datetime.now(
                    timezone.utc
                ),
            }
        },
    )

    if result.matched_count == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Client not found.",
        )

    return {
        "updated": True,
        "is_active": payload.is_active,
    }


@router.get("/messages")
async def messages(
    limit: int = Query(
        default=100,
        ge=1,
        le=200,
    ),
    _: Dict[str, Any] = Depends(
        get_current_admin
    ),
) -> Dict[str, Any]:

    cursor = (
        collections.messages.find({})
        .sort("created_at", -1)
        .limit(limit)
    )

    items = []

    async for document in cursor:
        items.append(
            serialize(document)
        )

    return {
        "items": items,
    }


@router.get("/r2-usage")
async def r2_usage(
    _: Dict[str, Any] = Depends(
        get_current_admin
    ),
) -> Dict[str, Any]:
    """Return global Cloudflare R2 usage and Meridin safety-guard status."""
    return await r2_usage_service.status()


@router.get("/usage")
async def usage(
    _: Dict[str, Any] = Depends(
        get_current_admin
    ),
) -> Dict[str, Any]:

    ai_usage = []

    cursor = collections.ai_model_usage.find({}).limit(500)

    async for document in cursor:
        ai_usage.append(
            serialize(document)
        )

    meta_usage = []

    cursor = (
        collections.meta_conversation_usage
        .find({})
        .limit(500)
    )

    async for document in cursor:
        meta_usage.append(
            serialize(document)
        )

    return {
        "ai_model_usage": ai_usage,
        "meta_conversation_usage": meta_usage,
    }
