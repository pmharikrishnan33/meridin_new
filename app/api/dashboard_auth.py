from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from app.core.dashboard_security import (
    create_access_token,
    get_admin_credentials,
    hash_password,
    verify_password,
)
from app.database.collections import collections
from app.database.mongodb import mongodb


router = APIRouter(
    prefix="/dashboard/auth",
    tags=["Dashboard Authentication"],
)


class ClientLoginRequest(BaseModel):
    email: str = Field(min_length=3)
    password: str = Field(min_length=1)


class AdminLoginRequest(BaseModel):
    email: str = Field(min_length=3)
    password: str = Field(min_length=1)


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    tenant_id: str | None = None
    business_name: str | None = None


@router.post(
    "/client/login",
    response_model=LoginResponse,
)
async def client_login(
    payload: ClientLoginRequest,
) -> LoginResponse:
    if not mongodb.is_connected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database is unavailable.",
        )

    document = await collections.clients.find_one(
        {
            "dashboard_email": payload.email.lower(),
            "is_active": True,
        }
    )

    if not document:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )

    password_hash = document.get(
        "dashboard_password_hash"
    )

    if not password_hash:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Dashboard access has not been configured "
                "for this client."
            ),
        )

    if not verify_password(
        payload.password,
        password_hash,
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )

    tenant_id = document.get("tenant_id")

    if not tenant_id:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Client tenant configuration is invalid.",
        )

    token = create_access_token(
        role="client",
        tenant_id=tenant_id,
        subject=str(document.get("_id")),
    )

    return LoginResponse(
        access_token=token,
        role="client",
        tenant_id=tenant_id,
        business_name=document.get(
            "business_name"
        ),
    )


@router.post(
    "/admin/login",
    response_model=LoginResponse,
)
async def admin_login(
    payload: AdminLoginRequest,
) -> LoginResponse:
    admin_email, admin_password_hash = (
        get_admin_credentials()
    )

    if not admin_email or not admin_password_hash:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=(
                "Admin dashboard credentials "
                "are not configured."
            ),
        )

    if payload.email.lower() != admin_email:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )

    if not verify_password(
        payload.password,
        admin_password_hash,
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )

    token = create_access_token(
        role="admin",
        subject="meridin-admin",
    )

    return LoginResponse(
        access_token=token,
        role="admin",
    )


@router.get("/me")
async def current_session() -> Dict[str, Any]:
    return {
        "authenticated": True,
    }
