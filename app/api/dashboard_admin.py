from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.core.dashboard_security import get_current_admin, hash_password
from app.database.collections import collections
from app.database.mongodb import mongodb
from app.services.r2_usage_service import r2_usage_service

router = APIRouter(prefix="/dashboard/admin", tags=["Admin Dashboard"])


def serialize(value: Any) -> Any:
    if isinstance(value, ObjectId): return str(value)
    if isinstance(value, datetime): return value.isoformat()
    if isinstance(value, dict): return {k: serialize(v) for k, v in value.items()}
    if isinstance(value, list): return [serialize(v) for v in value]
    return value


class ClientStatusRequest(BaseModel):
    is_active: bool


class ClientCreateRequest(BaseModel):
    tenant_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    business_name: str = Field(min_length=1, max_length=200)
    dashboard_email: str
    dashboard_password: str = Field(min_length=8, max_length=200)
    phone_number_id: str = Field(min_length=1, max_length=100)
    access_token: str = Field(min_length=1)
    webhook_verify_token: str = Field(min_length=1)
    welcome_message: str | None = None
    fallback_message: str | None = None
    feature_flags: Dict[str, bool] = Field(default_factory=dict)


class ClientUpdateRequest(BaseModel):
    business_name: str | None = Field(default=None, min_length=1, max_length=200)
    dashboard_email: str | None = None
    dashboard_password: str | None = Field(default=None, min_length=8, max_length=200)
    phone_number_id: str | None = None
    access_token: str | None = None
    webhook_verify_token: str | None = None
    welcome_message: str | None = None
    fallback_message: str | None = None


class FeatureFlagRequest(BaseModel):
    enabled: bool


@router.get("/overview")
async def overview(_: Dict[str, Any] = Depends(get_current_admin)) -> Dict[str, Any]:
    if not mongodb.is_connected:
        raise HTTPException(status_code=503, detail="Database is unavailable.")
    return {"metrics": {
        "clients": await collections.clients.count_documents({}),
        "active_clients": await collections.clients.count_documents({"is_active": True}),
        "messages": await collections.messages.count_documents({}),
        "customers": await collections.customers.count_documents({}),
        "conversations": await collections.conversations.count_documents({}),
    }}


def _safe_client(document: Dict[str, Any]) -> Dict[str, Any]:
    safe = dict(document)
    for key in ("access_token", "webhook_verify_token", "dashboard_password_hash"):
        safe.pop(key, None)
    return serialize(safe)


@router.get("/clients")
async def clients(limit: int = Query(default=100, ge=1, le=200), _: Dict[str, Any] = Depends(get_current_admin)) -> Dict[str, Any]:
    cursor = collections.clients.find({}).sort("created_at", -1).limit(limit)
    items = []
    async for document in cursor:
        items.append(_safe_client(document))
    return {"items": items}


@router.post("/clients", status_code=status.HTTP_201_CREATED)
async def create_client(payload: ClientCreateRequest, _: Dict[str, Any] = Depends(get_current_admin)) -> Dict[str, Any]:
    if not mongodb.is_connected:
        raise HTTPException(status_code=503, detail="Database is unavailable.")

    email = payload.dashboard_email.lower().strip()
    if "@" not in email or email.startswith("@") or email.endswith("@"):
        raise HTTPException(status_code=400, detail="Invalid dashboard email.")
    if await collections.clients.find_one({"tenant_id": payload.tenant_id}):
        raise HTTPException(status_code=409, detail="Tenant ID already exists.")
    if await collections.clients.find_one({"dashboard_email": email}):
        raise HTTPException(status_code=409, detail="Dashboard email already exists.")
    if await collections.clients.find_one({"phone_number_id": payload.phone_number_id}):
        raise HTTPException(status_code=409, detail="WhatsApp phone number ID already exists.")

    now = datetime.now(timezone.utc)
    defaults = {
        "enable_ai_responses": True,
        "enable_product_recommendations": True,
        "enable_order_tracking": False,
        "enable_returns": False,
        "enable_cancellation": False,
        "enable_human_handoff": True,
        "enable_analytics": True,
        "use_synonyms": True,
        "auto_reply_outside_hours": False,
    }
    defaults.update(payload.feature_flags)

    document = {
        "tenant_id": payload.tenant_id,
        "business_name": payload.business_name,
        "dashboard_email": email,
        "dashboard_password_hash": hash_password(payload.dashboard_password),
        "phone_number_id": payload.phone_number_id,
        "access_token": payload.access_token,
        "webhook_verify_token": payload.webhook_verify_token,
        "welcome_message": payload.welcome_message,
        "fallback_message": payload.fallback_message,
        "is_active": True,
        "feature_flags": defaults,
        "settings": {},
        "created_at": now,
        "updated_at": now,
    }
    result = await collections.clients.insert_one(document)
    document["_id"] = result.inserted_id
    return {"created": True, "client": _safe_client(document)}


@router.patch("/clients/{client_id}")
async def update_client(client_id: str, payload: ClientUpdateRequest, _: Dict[str, Any] = Depends(get_current_admin)) -> Dict[str, Any]:
    if not ObjectId.is_valid(client_id):
        raise HTTPException(status_code=400, detail="Invalid client ID.")
    data = payload.model_dump(exclude_none=True)
    if "dashboard_email" in data:
        data["dashboard_email"] = str(data["dashboard_email"]).lower().strip()
        duplicate = await collections.clients.find_one({"dashboard_email": data["dashboard_email"], "_id": {"$ne": ObjectId(client_id)}})
        if duplicate:
            raise HTTPException(status_code=409, detail="Dashboard email already exists.")
    if "dashboard_password" in data:
        data["dashboard_password_hash"] = hash_password(data.pop("dashboard_password"))
    data["updated_at"] = datetime.now(timezone.utc)
    result = await collections.clients.update_one({"_id": ObjectId(client_id)}, {"$set": data})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Client not found.")
    document = await collections.clients.find_one({"_id": ObjectId(client_id)})
    return {"updated": True, "client": _safe_client(document)}


@router.patch("/clients/{client_id}/status")
async def update_client_status(client_id: str, payload: ClientStatusRequest, _: Dict[str, Any] = Depends(get_current_admin)) -> Dict[str, Any]:
    if not ObjectId.is_valid(client_id):
        raise HTTPException(status_code=400, detail="Invalid client ID.")
    result = await collections.clients.update_one({"_id": ObjectId(client_id)}, {"$set": {"is_active": payload.is_active, "updated_at": datetime.now(timezone.utc)}})
    if result.matched_count == 0: raise HTTPException(status_code=404, detail="Client not found.")
    return {"updated": True, "is_active": payload.is_active}


@router.get("/clients/{client_id}/feature-flags")
async def get_feature_flags(client_id: str, _: Dict[str, Any] = Depends(get_current_admin)) -> Dict[str, Any]:
    if not ObjectId.is_valid(client_id): raise HTTPException(status_code=400, detail="Invalid client ID.")
    doc = await collections.clients.find_one({"_id": ObjectId(client_id)}, {"feature_flags": 1, "settings": 1})
    if not doc: raise HTTPException(status_code=404, detail="Client not found.")

    flags: Dict[str, bool] = {}
    for key, value in (doc.get("feature_flags") or {}).items():
        if isinstance(value, bool): flags[f"feature_flags.{key}"] = value

    def collect(prefix: str, value: Any) -> None:
        if isinstance(value, dict):
            for key, child in value.items(): collect(f"{prefix}.{key}", child)
        elif isinstance(value, bool):
            flags[prefix] = value
    collect("settings", doc.get("settings") or {})
    return {"items": [{"path": k, "enabled": v} for k, v in sorted(flags.items())]}


@router.patch("/clients/{client_id}/feature-flags")
async def update_feature_flag(client_id: str, path: str = Query(..., min_length=1, max_length=200), payload: FeatureFlagRequest = ..., _: Dict[str, Any] = Depends(get_current_admin)) -> Dict[str, Any]:
    if not ObjectId.is_valid(client_id): raise HTTPException(status_code=400, detail="Invalid client ID.")
    if not (path.startswith("feature_flags.") or path.startswith("settings.")):
        raise HTTPException(status_code=400, detail="Only feature_flags and settings booleans can be changed.")
    parts = path.split(".")
    if any(not part or part.startswith("$") or part in {"_id", "access_token", "dashboard_password_hash", "webhook_verify_token"} for part in parts):
        raise HTTPException(status_code=400, detail="Invalid feature path.")
    result = await collections.clients.update_one({"_id": ObjectId(client_id)}, {"$set": {path: payload.enabled, "updated_at": datetime.now(timezone.utc)}})
    if result.matched_count == 0: raise HTTPException(status_code=404, detail="Client not found.")
    return {"updated": True, "path": path, "enabled": payload.enabled}


@router.get("/messages")
async def messages(limit: int = Query(default=100, ge=1, le=200), _: Dict[str, Any] = Depends(get_current_admin)) -> Dict[str, Any]:
    cursor = collections.messages.find({}).sort("created_at", -1).limit(limit)
    items = []
    async for document in cursor: items.append(serialize(document))
    return {"items": items}


@router.get("/r2-usage")
async def r2_usage(_: Dict[str, Any] = Depends(get_current_admin)) -> Dict[str, Any]:
    return await r2_usage_service.status()


@router.get("/usage")
async def usage(_: Dict[str, Any] = Depends(get_current_admin)) -> Dict[str, Any]:
    ai_usage = []
    async for document in collections.ai_model_usage.find({}).limit(500): ai_usage.append(serialize(document))
    meta_usage = []
    async for document in collections.meta_conversation_usage.find({}).limit(500): meta_usage.append(serialize(document))
    return {"ai_model_usage": ai_usage, "meta_conversation_usage": meta_usage}
