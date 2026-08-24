"""
Security utilities for the Meta / WhatsApp webhook endpoint.

This module centralises three concerns that every production webhook needs:

1. **HMAC signature verification** – validates the ``X-Hub-Signature-256``
   header against the raw request body so that forged payloads are rejected
   before any business logic runs.

2. **Rate limiting** – throttles incoming requests per client/IP to mitigate
   abuse and denial-of-service attacks.  Uses Redis when available, with a
   thread-safe in-memory fallback.

3. **Body size guard** – prevents the application from allocating unbounded
   memory on oversized or malicious payloads.

4. **Tenant credential resolution** – when a tenant is identified by its
   ``phone_number_id`` (sent in the webhook ``metadata``) the matching
   tenant record is fetched from MongoDB so that per-tenant credentials
   (access token, verify token, webhook secret) are used instead of the
   shared environment defaults.
"""

import hashlib
import hmac
import os
import time
from collections import defaultdict
from threading import Lock
from typing import Optional, Tuple

from fastapi import HTTPException, Request, status

from app.core.config import (
    RATE_LIMIT_DEFAULT_MAX_REQUESTS,
    RATE_LIMIT_DEFAULT_WINDOW,
    WEBHOOK_MAX_BODY_BYTES,
    settings,
)
from app.models.schemas import Tenant
from app.repositories.tenant_repository import tenant_repository
from app.utils.logger import logger


# ---------------------------------------------------------------------------
# 1.  HMAC signature verification
# ---------------------------------------------------------------------------


class SignatureVerificationError(HTTPException):
    """Raised when the ``X-Hub-Signature-256`` header is missing or invalid."""


def _resolve_webhook_secret(tenant: Optional[Tenant] = None) -> str:
    """Resolve the verification secret with a clear precedence order.

    1. Tenant-specific ``webhook_secret`` or ``settings.webhook_secret`` when present.
    2. Shared environment ``WHATSAPP_WEBHOOK_SECRET``.
    3. Shared application ``APP_SECRET`` fallback.
    """
    if tenant:
        secret = getattr(tenant, "webhook_secret", None)
        if isinstance(secret, str) and secret:
            return secret
        if hasattr(tenant, "settings") and tenant.settings:
            nested_secret = getattr(tenant.settings, "webhook_secret", None)
            if isinstance(nested_secret, str) and nested_secret:
                return nested_secret
    if settings.WHATSAPP_WEBHOOK_SECRET:
        return settings.WHATSAPP_WEBHOOK_SECRET
    return settings.APP_SECRET


def verify_signature(raw_body: bytes, signature_header: Optional[str]) -> None:
    """
    Verify the Meta ``X-Hub-Signature-256`` header against *raw_body*.

    The header has the form ``sha256=<hex_digest>``.  Verification uses a
    constant-time comparison to prevent timing attacks.

    Raises :class:`SignatureVerificationError` on any mismatch or when the
    shared secret is not configured.
    """
    shared_secret = _resolve_webhook_secret()

    if not shared_secret:
        # When no secret is configured we cannot cryptographically verify the
        # payload.  Fail closed.
        raise SignatureVerificationError(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Webhook signature verification is not configured.",
        )

    if not signature_header:
        raise SignatureVerificationError(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-Hub-Signature-256 header.",
        )

    try:
        algorithm, provided_digest = signature_header.split("=", 1)
    except ValueError:
        raise SignatureVerificationError(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Malformed X-Hub-Signature-256 header.",
        )

    if algorithm.lower() != "sha256":
        raise SignatureVerificationError(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unsupported signature algorithm. Expected sha256.",
        )

    expected_digest = hmac.new(
        key=shared_secret.encode("utf-8"),
        msg=raw_body,
        digestmod=hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected_digest, provided_digest.lower()):
        raise SignatureVerificationError(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid webhook signature.",
        )


def verify_tenant_signature(
    raw_body: bytes,
    signature_header: Optional[str],
    tenant: Optional[Tenant],
) -> None:
    """
    Verify the signature using a per-tenant secret when available, falling
    back to the shared environment secret and then to ``APP_SECRET``.
    """
    secret = _resolve_webhook_secret(tenant)

    if not secret:
        raise SignatureVerificationError(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Webhook signature verification is not configured.",
        )

    if not signature_header:
        raise SignatureVerificationError(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-Hub-Signature-256 header.",
        )

    try:
        algorithm, provided_digest = signature_header.split("=", 1)
    except ValueError:
        raise SignatureVerificationError(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Malformed X-Hub-Signature-256 header.",
        )

    if algorithm.lower() != "sha256":
        raise SignatureVerificationError(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unsupported signature algorithm. Expected sha256.",
        )

    expected_digest = hmac.new(
        key=secret.encode("utf-8"),
        msg=raw_body,
        digestmod=hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(expected_digest, provided_digest.lower()):
        raise SignatureVerificationError(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid webhook signature.",
        )


# ---------------------------------------------------------------------------
# 2.  Rate limiter (Redis-backed with in-memory fallback)
# ---------------------------------------------------------------------------


class RateLimiter:
    """
    Sliding-window rate limiter backed by Redis, with a thread-safe
    in-memory fallback for when Redis is unavailable.

    Usage::

        limiter = RateLimiter()
        await limiter.check(request, tenant_id="tenant-1")
    """

    def __init__(self) -> None:
        self._window = settings.RATE_LIMIT_WINDOW_SECONDS or RATE_LIMIT_DEFAULT_WINDOW
        self._max_requests = settings.RATE_LIMIT_MAX_REQUESTS or RATE_LIMIT_DEFAULT_MAX_REQUESTS
        self._local: dict[str, list[float]] = defaultdict(list)
        self._local_lock = Lock()
        self._enabled = settings.RATE_LIMIT_ENABLED

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    def _client_ip(self, request: Request) -> str:
        """Extract the real client IP from the request, honouring X-Forwarded-For."""
        forwarded_for = request.headers.get("x-forwarded-for")
        if forwarded_for:
            # Use the first hop in the chain
            return forwarded_for.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    def _cache_key(self, request: Request, tenant_id: Optional[str] = None) -> str:
        """Build a composite cache key scoped to IP + tenant."""
        ip = self._client_ip(request)
        scope = tenant_id or "default"
        return f"ratelimit:{scope}:{ip}"

    async def check(self, request: Request, tenant_id: Optional[str] = None) -> None:
        """
        Raise ``HTTPException(429)`` if the caller has exceeded the rate limit.
        """
        if not self._enabled:
            return

        key = self._cache_key(request, tenant_id)

        # --- Redis path ----------------------------------------------------
        if _redis_is_connected():
            current = await _redis_increment(key, self._window)
            if current is not None and current > self._max_requests:
                logger.warning(f"Rate limit exceeded for key {key}: {current} requests")
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Rate limit exceeded. Please try again later.",
                    headers={"Retry-After": str(self._window)},
                )
            return

        # --- In-memory fallback --------------------------------------------
        with self._local_lock:
            now = time.monotonic()
            # Prune timestamps outside the window
            self._local[key] = [ts for ts in self._local[key] if now - ts < self._window]
            self._local[key].append(now)
            if len(self._local[key]) > self._max_requests:
                logger.warning(f"Rate limit exceeded (in-memory) for key {key}")
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Rate limit exceeded. Please try again later.",
                    headers={"Retry-After": str(self._window)},
                )

    async def reset(self, request: Request, tenant_id: Optional[str] = None) -> None:
        """Clear the rate-limit counters for a given key (useful in tests)."""
        key = self._cache_key(request, tenant_id)
        if _redis_is_connected():
            await _redis_delete(key)
        with self._local_lock:
            self._local.pop(key, None)


def _redis_is_connected() -> bool:
    """Check whether Redis is available for rate-limit storage."""
    try:
        from app.database.redis_cache import redis_cache
        return redis_cache.is_connected
    except Exception:
        return False


async def _redis_increment(key: str, ttl: int) -> Optional[int]:
    """Atomically increment *key* in Redis with an expiry of *ttl* seconds."""
    try:
        from app.database.redis_cache import redis_cache
        result = await redis_cache.increment(key, amount=1, ttl=ttl)
        return result
    except Exception as exc:
        logger.debug(f"Redis rate-limit increment failed for {key}: {exc}")
        return None


async def _redis_delete(key: str) -> None:
    """Delete a key from Redis."""
    try:
        from app.database.redis_cache import redis_cache
        await redis_cache.delete(key)
    except Exception:
        pass


# Module-level singleton
rate_limiter = RateLimiter()


# ---------------------------------------------------------------------------
# 3.  Body-size guard
# ---------------------------------------------------------------------------


def check_body_size(body: bytes) -> None:
    """Raise ``HTTPException(413)`` if *body* exceeds the configured maximum."""
    if len(body) > WEBHOOK_MAX_BODY_BYTES:
        logger.warning(
            f"Rejected oversized webhook body: {len(body)} bytes "
            f"(max {WEBHOOK_MAX_BODY_BYTES})"
        )
        raise HTTPException(
            status_code=getattr(status, "HTTP_413_CONTENT_TOO_LARGE", 413),
            detail="Request body too large.",
        )


# ---------------------------------------------------------------------------
# 4.  Tenant credential resolution
# ---------------------------------------------------------------------------


async def resolve_tenant_credentials(
    phone_number_id: Optional[str],
    metadata_phone_number_id: Optional[str],
) -> Tuple[Optional[Tenant], str, str]:
    """
    Resolve tenant-specific credentials from MongoDB.

    Parameters
    ----------
    phone_number_id
        Value supplied via the ``X-Tenant-Id`` or ``X-WhatsApp-Phone-Number-Id``
        header.
    metadata_phone_number_id
        Value found in the webhook payload's ``metadata.phone_number_id``
        field.

    Returns
    -------
    tuple
        ``(tenant_or_none, resolved_phone_number_id, resolved_access_token)``
    """
    # Header ID has precedence over metadata ID for test/routing overrides
    lookup_id = phone_number_id or metadata_phone_number_id

    tenant = None
    if lookup_id:
        tenant = await tenant_repository.find_by_phone_number_id(lookup_id)
        if tenant is None:
            tenant = await tenant_repository.find_by_tenant_id(lookup_id)

    if tenant:
        return (
            tenant,
            tenant.phone_number_id,
            tenant.access_token,
        )

    logger.debug("No active tenant matched in DB; falling back to default settings.")
    return (
        None,
        settings.WHATSAPP_PHONE_NUMBER_ID,
        settings.WHATSAPP_ACCESS_TOKEN,
    )

