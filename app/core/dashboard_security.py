from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from typing import Any, Dict, Optional

from fastapi import HTTPException, Request, status

from app.core.config import settings


_PASSWORD_ITERATIONS = 600_000
_TOKEN_TTL_SECONDS = 60 * 60 * 8


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("utf-8").rstrip("=")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def hash_password(password: str) -> str:
    if not password:
        raise ValueError("Password cannot be empty.")

    salt = secrets.token_bytes(16)

    derived_key = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        _PASSWORD_ITERATIONS,
    )

    return (
        f"pbkdf2_sha256${_PASSWORD_ITERATIONS}$"
        f"{_b64encode(salt)}$"
        f"{_b64encode(derived_key)}"
    )


def verify_password(
    password: str,
    password_hash: str,
) -> bool:
    if not password or not password_hash:
        return False

    try:
        algorithm, iterations, salt, stored_key = (
            password_hash.split("$", 3)
        )

        if algorithm != "pbkdf2_sha256":
            return False

        iterations_int = int(iterations)

        salt_bytes = _b64decode(salt)
        stored_key_bytes = _b64decode(stored_key)

        derived_key = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt_bytes,
            iterations_int,
        )

        return hmac.compare_digest(
            derived_key,
            stored_key_bytes,
        )

    except (ValueError, TypeError):
        return False


def create_access_token(
    *,
    role: str,
    tenant_id: Optional[str] = None,
    subject: Optional[str] = None,
) -> str:
    now = int(time.time())

    payload: Dict[str, Any] = {
        "sub": subject,
        "role": role,
        "tenant_id": tenant_id,
        "iat": now,
        "exp": now + _TOKEN_TTL_SECONDS,
    }

    payload_bytes = json.dumps(
        payload,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")

    encoded_payload = _b64encode(payload_bytes)

    signature = hmac.new(
        settings.APP_SECRET.encode("utf-8"),
        encoded_payload.encode("utf-8"),
        hashlib.sha256,
    ).digest()

    return (
        f"{encoded_payload}."
        f"{_b64encode(signature)}"
    )


def decode_access_token(token: str) -> Dict[str, Any]:
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required.",
        )

    try:
        encoded_payload, encoded_signature = (
            token.split(".", 1)
        )

        expected_signature = hmac.new(
            settings.APP_SECRET.encode("utf-8"),
            encoded_payload.encode("utf-8"),
            hashlib.sha256,
        ).digest()

        provided_signature = _b64decode(
            encoded_signature
        )

        if not hmac.compare_digest(
            expected_signature,
            provided_signature,
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication token.",
            )

        payload = json.loads(
            _b64decode(encoded_payload).decode("utf-8")
        )

        if not isinstance(payload, dict):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication token.",
            )

        if int(payload.get("exp", 0)) < int(time.time()):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication token expired.",
            )

        return payload

    except HTTPException:
        raise

    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token.",
        ) from exc


def get_bearer_token(request: Request) -> str:
    authorization = request.headers.get(
        "Authorization",
        "",
    )

    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header is required.",
        )

    scheme, _, token = authorization.partition(" ")

    if scheme.lower() != "bearer" or not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Bearer authentication is required.",
        )

    return token.strip()


async def get_current_user(
    request: Request,
) -> Dict[str, Any]:
    token = get_bearer_token(request)

    return decode_access_token(token)


async def get_current_client(
    request: Request,
) -> Dict[str, Any]:
    user = await get_current_user(request)

    if user.get("role") != "client":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Client access required.",
        )

    tenant_id = user.get("tenant_id")

    if not tenant_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Client tenant context is missing.",
        )

    return user


async def get_current_admin(
    request: Request,
) -> Dict[str, Any]:
    user = await get_current_user(request)

    if user.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Administrator access required.",
        )

    return user


def get_admin_credentials() -> tuple[str, str]:
    email = settings.MERIDIN_ADMIN_EMAIL.strip().lower()
    password_hash = settings.MERIDIN_ADMIN_PASSWORD_HASH.strip()
    return email, password_hash
