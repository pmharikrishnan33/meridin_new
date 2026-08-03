"""
Tests for webhook security: signature verification, rate limiting,
request validation hardening, and tenant credential resolution.
"""

import hashlib
import hmac
import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
from fastapi import Request

from app.api.security import (
    SignatureVerificationError,
    check_body_size,
    rate_limiter,
    resolve_tenant_credentials,
    verify_signature,
    verify_tenant_signature,
)
from app.core.config import WEBHOOK_MAX_BODY_BYTES, settings
from app.main import app
from app.models.schemas import Tenant


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TEST_SECRET = "test_webhook_secret_abc123"

TEST_PAYLOAD = {
    "object": "whatsapp_business_account",
    "entry": [
        {
            "id": "123456789",
            "changes": [
                {
                    "field": "messages",
                    "value": {
                        "metadata": {"phone_number_id": "tenant-1"},
                        "messages": [
                            {
                                "from": "user-1",
                                "id": "msg-1",
                                "timestamp": "1700000000",
                                "type": "text",
                                "text": {"body": "hello"},
                            }
                        ],
                    },
                }
            ],
        }
    ],
}


def _sign(body: bytes, secret: str) -> str:
    """Return the Meta-style ``sha256=<hex>`` signature header."""
    digest = hmac.new(
        key=secret.encode("utf-8"), msg=body, digestmod=hashlib.sha256
    ).hexdigest()
    return f"sha256={digest}"


def _dumps(payload: dict) -> bytes:
    """Serialise a dict to compact JSON bytes."""
    return json.dumps(payload).encode("utf-8")


def _make_request(host: str = "127.0.0.1", forwarded_for: str | None = None) -> MagicMock:
    """Build a mock FastAPI Request with the given client IP."""
    request = MagicMock(spec=Request)
    request.headers = {}
    if forwarded_for:
        request.headers["x-forwarded-for"] = forwarded_for
    request.client = MagicMock()
    request.client.host = host
    return request


# ---------------------------------------------------------------------------
# Signature verification
# ---------------------------------------------------------------------------


class SignatureVerificationTests(unittest.IsolatedAsyncioTestCase):
    """Unit tests for the standalone signature verification functions."""

    async def test_valid_signature_passes(self):
        body = _dumps(TEST_PAYLOAD)
        header = _sign(body, TEST_SECRET)

        with patch("app.api.security.settings") as mock_settings:
            mock_settings.WHATSAPP_WEBHOOK_SECRET = TEST_SECRET
            verify_signature(body, header)  # should not raise

    async def test_invalid_signature_raises_401(self):
        body = _dumps(TEST_PAYLOAD)
        header = "sha256=" + "0" * 64

        with patch("app.api.security.settings") as mock_settings:
            mock_settings.WHATSAPP_WEBHOOK_SECRET = TEST_SECRET
            with self.assertRaises(SignatureVerificationError) as ctx:
                verify_signature(body, header)
            self.assertEqual(ctx.exception.status_code, 401)

    async def test_missing_signature_header_raises_401(self):
        body = _dumps(TEST_PAYLOAD)
        with patch("app.api.security.settings") as mock_settings:
            mock_settings.WHATSAPP_WEBHOOK_SECRET = TEST_SECRET
            with self.assertRaises(SignatureVerificationError) as ctx:
                verify_signature(body, None)
            self.assertEqual(ctx.exception.status_code, 401)

    async def test_missing_webhook_secret_raises_500(self):
        body = _dumps(TEST_PAYLOAD)
        with patch("app.api.security.settings") as mock_settings:
            mock_settings.WHATSAPP_WEBHOOK_SECRET = ""
            with self.assertRaises(SignatureVerificationError) as ctx:
                verify_signature(body, "sha256=abc")
            self.assertEqual(ctx.exception.status_code, 500)

    async def test_malformed_signature_raises_401(self):
        body = _dumps(TEST_PAYLOAD)
        with patch("app.api.security.settings") as mock_settings:
            mock_settings.WHATSAPP_WEBHOOK_SECRET = TEST_SECRET
            with self.assertRaises(SignatureVerificationError) as ctx:
                verify_signature(body, "invalid_header_no_equals")
            self.assertEqual(ctx.exception.status_code, 401)

    async def test_wrong_algorithm_raises_401(self):
        body = _dumps(TEST_PAYLOAD)
        with patch("app.api.security.settings") as mock_settings:
            mock_settings.WHATSAPP_WEBHOOK_SECRET = TEST_SECRET
            with self.assertRaises(SignatureVerificationError) as ctx:
                verify_signature(body, "md5=abc123")
            self.assertEqual(ctx.exception.status_code, 401)

    async def test_tenant_signature_uses_tenant_secret(self):
        """When a tenant has its own webhook_secret it should be used."""
        body = _dumps(TEST_PAYLOAD)
        tenant = MagicMock()
        tenant.webhook_secret = "tenant_specific_secret"
        header = _sign(body, "tenant_specific_secret")

        with patch("app.api.security.settings") as mock_settings:
            mock_settings.WHATSAPP_WEBHOOK_SECRET = TEST_SECRET
            verify_tenant_signature(body, header, tenant)  # should not raise

    async def test_tenant_signature_falls_back_to_shared(self):
        """When tenant secret is empty, shared secret should be used."""
        body = _dumps(TEST_PAYLOAD)
        tenant = MagicMock()
        tenant.webhook_secret = ""
        header = _sign(body, TEST_SECRET)

        with patch("app.api.security.settings") as mock_settings:
            mock_settings.WHATSAPP_WEBHOOK_SECRET = TEST_SECRET
            verify_tenant_signature(body, header, tenant)  # should not raise


# ---------------------------------------------------------------------------
# Rate limiter
# ---------------------------------------------------------------------------


class RateLimiterTests(unittest.IsolatedAsyncioTestCase):
    """Tests for the rate limiting logic."""

    def setUp(self):
        self._original_local = rate_limiter._local.copy()
        self._original_enabled = rate_limiter._enabled
        rate_limiter._local.clear()
        rate_limiter._enabled = True
        # Use a small limit for deterministic testing
        self._original_max = rate_limiter._max_requests
        rate_limiter._max_requests = 5

    def tearDown(self):
        rate_limiter._local.clear()
        rate_limiter._local.update(self._original_local)
        rate_limiter._enabled = self._original_enabled
        rate_limiter._max_requests = self._original_max

    async def test_allows_requests_under_limit(self):
        request = _make_request(host="192.168.1.1")
        with patch("app.api.security._redis_is_connected", return_value=False):
            for _ in range(rate_limiter._max_requests):
                await rate_limiter.check(request, tenant_id="tenant-1")

    async def test_blocks_requests_over_limit(self):
        from fastapi import HTTPException as StarletteHTTPException

        request = _make_request(host="192.168.1.2")
        with patch("app.api.security._redis_is_connected", return_value=False):
            # Exhaust the limit
            for _ in range(rate_limiter._max_requests):
                await rate_limiter.check(request, tenant_id="tenant-1")

            with self.assertRaises(StarletteHTTPException) as ctx:
                await rate_limiter.check(request, tenant_id="tenant-1")
            self.assertEqual(ctx.exception.status_code, 429)

    async def test_disabled_when_not_enabled(self):
        request = _make_request(host="192.168.1.3")
        with patch.object(rate_limiter, "_enabled", False):
            for _ in range(rate_limiter._max_requests * 3):
                await rate_limiter.check(request, tenant_id="tenant-1")

    async def test_isolates_per_ip(self):
        """Different IPs get separate counters."""
        from fastapi import HTTPException as StarletteHTTPException

        req1 = _make_request(host="10.0.0.1")
        req2 = _make_request(host="10.0.0.2")

        with patch("app.api.security._redis_is_connected", return_value=False):
            for _ in range(rate_limiter._max_requests):
                await rate_limiter.check(req1, tenant_id="tenant-1")

            # req1 is block but req2 should still work
            with self.assertRaises(StarletteHTTPException):
                await rate_limiter.check(req1, tenant_id="tenant-1")

            await rate_limiter.check(req2, tenant_id="tenant-1")

    async def test_respects_x_forwarded_for(self):
        request = _make_request(forwarded_for="203.0.113.50, 70.4.45.67")
        ip = rate_limiter._client_ip(request)
        self.assertEqual(ip, "203.0.113.50")

    async def test_uses_redis_when_available(self):
        """When Redis is connected, the Redis path is used."""
        request = _make_request(host="192.168.1.10")

        # With Redis connected and increment returning a value under the limit
        with patch("app.api.security._redis_is_connected", return_value=True):
            with patch("app.api.security._redis_increment", new_callable=AsyncMock, return_value=1):
                await rate_limiter.check(request, tenant_id="tenant-1")

    async def test_redis_blocks_over_limit(self):
        """When Redis returns a count over the limit, 429 is raised."""
        from fastapi import HTTPException as StarletteHTTPException

        request = _make_request(host="192.168.1.20")

        with patch("app.api.security._redis_is_connected", return_value=True):
            with patch(
                "app.api.security._redis_increment",
                new_callable=AsyncMock,
                return_value=rate_limiter._max_requests + 1,
            ):
                with self.assertRaises(StarletteHTTPException) as ctx:
                    await rate_limiter.check(request, tenant_id="tenant-1")
                self.assertEqual(ctx.exception.status_code, 429)


# ---------------------------------------------------------------------------
# Body size guard
# ---------------------------------------------------------------------------


class BodySizeGuardTests(unittest.TestCase):
    """Tests for the oversized-body guard."""

    def test_allows_body_under_limit(self):
        body = b"x" * (WEBHOOK_MAX_BODY_BYTES - 1)
        check_body_size(body)  # should not raise

    def test_rejects_body_over_limit(self):
        body = b"x" * (WEBHOOK_MAX_BODY_BYTES + 1)
        with self.assertRaises(Exception) as ctx:
            check_body_size(body)
        self.assertEqual(ctx.exception.status_code, 413)

    def test_rejects_body_exactly_at_limit_plus_one(self):
        body = b"x" * (WEBHOOK_MAX_BODY_BYTES + 1)
        with self.assertRaises(Exception) as ctx:
            check_body_size(body)
        self.assertEqual(ctx.exception.status_code, 413)

    def test_allows_empty_body(self):
        check_body_size(b"")


# ---------------------------------------------------------------------------
# Tenant credential resolution
# ---------------------------------------------------------------------------


class TenantResolutionTests(unittest.IsolatedAsyncioTestCase):
    """Tests for tenant credential resolution from MongoDB."""

    async def test_resolves_tenant_from_db(self):
        mock_tenant = MagicMock(spec=Tenant)
        mock_tenant.phone_number_id = "tenant-1"
        mock_tenant.access_token = "tenant_token"

        with patch(
            "app.repositories.tenant_repository.tenant_repository.find_by_phone_number_id",
            new_callable=AsyncMock,
            return_value=mock_tenant,
        ), patch("app.api.security.settings") as mock_settings:
            mock_settings.WHATSAPP_PHONE_NUMBER_ID = "default_phone"
            mock_settings.WHATSAPP_ACCESS_TOKEN = "default_token"

            tenant, phone_id, token = await resolve_tenant_credentials(
                phone_number_id="tenant-1",
                metadata_phone_number_id=None,
            )
            self.assertEqual(tenant, mock_tenant)
            self.assertEqual(phone_id, "tenant-1")
            self.assertEqual(token, "tenant_token")

    async def test_falls_back_to_defaults_when_no_tenant(self):
        with patch(
            "app.repositories.tenant_repository.tenant_repository.find_by_phone_number_id",
            new_callable=AsyncMock,
            return_value=None,
        ), patch("app.api.security.settings") as mock_settings:
            mock_settings.WHATSAPP_PHONE_NUMBER_ID = "default_phone"
            mock_settings.WHATSAPP_ACCESS_TOKEN = "default_token"

            tenant, phone_id, token = await resolve_tenant_credentials(
                phone_number_id="tenant-1",
                metadata_phone_number_id=None,
            )
            self.assertIsNone(tenant)
            self.assertEqual(phone_id, "default_phone")
            self.assertEqual(token, "default_token")

    async def test_falls_back_to_defaults_when_no_id_provided(self):
        with patch("app.api.security.settings") as mock_settings:
            mock_settings.WHATSAPP_PHONE_NUMBER_ID = "default_phone"
            mock_settings.WHATSAPP_ACCESS_TOKEN = "default_token"

            tenant, phone_id, token = await resolve_tenant_credentials(
                phone_number_id=None,
                metadata_phone_number_id=None,
            )
            self.assertIsNone(tenant)
            self.assertEqual(phone_id, "default_phone")
            self.assertEqual(token, "default_token")

    async def test_prefers_header_id_over_metadata(self):
        """When both header and metadata IDs are present, header wins."""
        with patch(
            "app.repositories.tenant_repository.tenant_repository.find_by_phone_number_id",
            new_callable=AsyncMock,
            return_value=None,
        ) as mock_find, patch("app.api.security.settings") as mock_settings:
            mock_settings.WHATSAPP_PHONE_NUMBER_ID = "default_phone"
            mock_settings.WHATSAPP_ACCESS_TOKEN = "default_token"

            await resolve_tenant_credentials(
                phone_number_id="header-id",
                metadata_phone_number_id="metadata-id",
            )
            mock_find.assert_called_once_with("header-id")

    async def test_falls_back_to_metadata_when_no_header(self):
        """When header is missing, metadata phone_number_id is used."""
        with patch(
            "app.repositories.tenant_repository.tenant_repository.find_by_phone_number_id",
            new_callable=AsyncMock,
            return_value=None,
        ) as mock_find, patch("app.api.security.settings") as mock_settings:
            mock_settings.WHATSAPP_PHONE_NUMBER_ID = "default_phone"
            mock_settings.WHATSAPP_ACCESS_TOKEN = "default_token"

            await resolve_tenant_credentials(
                phone_number_id=None,
                metadata_phone_number_id="metadata-id",
            )
            mock_find.assert_called_once_with("metadata-id")


# ---------------------------------------------------------------------------
# End-to-end webhook endpoint tests
# ---------------------------------------------------------------------------


class WebhookEndpointTests(unittest.IsolatedAsyncioTestCase):
    """Integration tests for the /api/webhook endpoint."""

    def setUp(self):
        self._original_local = rate_limiter._local.copy()
        self._original_enabled = rate_limiter._enabled
        rate_limiter._local.clear()
        # Disable rate limiting to isolate the security checks under test
        rate_limiter._enabled = False

    def tearDown(self):
        rate_limiter._local.clear()
        rate_limiter._local.update(self._original_local)
        rate_limiter._enabled = self._original_enabled

    async def test_valid_signed_payload_returns_200(self):
        """A correctly signed payload should be accepted."""
        body = _dumps(TEST_PAYLOAD)
        secret = settings.WHATSAPP_WEBHOOK_SECRET or TEST_SECRET

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/webhook",
                content=body,
                headers={
                    "content-type": "application/json",
                    "x_hub_signature_256": _sign(body, secret),
                },
            )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["status"], "accepted")

    async def test_missing_signature_rejected(self):
        """Requests without a signature header must get 401."""
        body = _dumps(TEST_PAYLOAD)

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/webhook",
                content=body,
                headers={"content-type": "application/json"},
            )

        self.assertEqual(response.status_code, 401)

    async def test_invalid_signature_rejected(self):
        """Requests with a wrong signature must get 401."""
        body = _dumps(TEST_PAYLOAD)

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/webhook",
                content=body,
                headers={
                    "x_hub_signature_256": "sha256=" + "0" * 64,
                    "content-type": "application/json",
                },
            )

        self.assertEqual(response.status_code, 401)

    async def test_malformed_json_rejected(self):
        """Invalid JSON must return 400."""
        body = b"{not valid json"
        secret = settings.WHATSAPP_WEBHOOK_SECRET or TEST_SECRET

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/webhook",
                content=body,
                headers={
                    "x_hub_signature_256": _sign(body, secret),
                    "content-type": "application/json",
                },
            )

        self.assertEqual(response.status_code, 400)

    async def test_oversized_body_rejected(self):
        """Bodies exceeding the max size must return 413."""
        body = b"x" * (WEBHOOK_MAX_BODY_BYTES + 1)
        secret = settings.WHATSAPP_WEBHOOK_SECRET or TEST_SECRET

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/webhook",
                content=body,
                headers={
                    "x_hub_signature_256": _sign(body, secret),
                    "content-type": "application/json",
                },
            )

        self.assertEqual(response.status_code, 413)

    async def test_malformed_payload_rejected(self):
        """A payload that doesn't match IncomingWhatsAppWebhook must return 422."""
        body = _dumps({"unexpected": "structure"})
        secret = settings.WHATSAPP_WEBHOOK_SECRET or TEST_SECRET

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            response = await client.post(
                "/api/webhook",
                content=body,
                headers={
                    "x_hub_signature_256": _sign(body, secret),
                    "content-type": "application/json",
                },
            )

        self.assertEqual(response.status_code, 422)

    async def test_rate_limit_exceeded_returns_429(self):
        """When the rate limit is exceeded, return 429."""
        body = _dumps(TEST_PAYLOAD)
        secret = settings.WHATSAPP_WEBHOOK_SECRET or TEST_SECRET
        signature = _sign(body, secret)

        # Temporarily re-enable rate limiting with a small limit
        rate_limiter._enabled = True
        rate_limiter._max_requests = 2
        rate_limiter._local.clear()

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            # First two should be processed (not rate-limited)
            # We don't care about 200 vs 500 here — just that it's not 429
            await client.post(
                "/api/webhook",
                content=body,
                headers={
                    "x_hub_signature_256": signature,
                    "content-type": "application/json",
                },
            )
            await client.post(
                "/api/webhook",
                content=body,
                headers={
                    "x_hub_signature_256": signature,
                    "content-type": "application/json",
                },
            )

            # Third should be rate-limited
            response = await client.post(
                "/api/webhook",
                content=body,
                headers={
                    "x_hub_signature_256": signature,
                    "content-type": "application/json",
                },
            )

        self.assertEqual(response.status_code, 429)

    async def test_verify_webhook_accepts_valid_token(self):
        """GET /webhook with a matching verify token should return the challenge."""
        verify_token = settings.WHATSAPP_VERIFY_TOKEN or "test_verify_token"

        with patch("app.api.webhook.settings") as mock_settings:
            mock_settings.WHATSAPP_VERIFY_TOKEN = verify_token

            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                response = await client.get(
                    "/api/webhook",
                    params={
                        "hub.mode": "subscribe",
                        "hub.verify_token": verify_token,
                        "hub.challenge": "challenge123",
                    },
                )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.text, "challenge123")

    async def test_verify_webhook_rejects_invalid_token(self):
        """GET /webhook with a wrong verify token should get 403."""
        with patch("app.api.webhook.settings") as mock_settings:
            mock_settings.WHATSAPP_VERIFY_TOKEN = "valid_token"

            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                response = await client.get(
                    "/api/webhook",
                    params={
                        "hub.mode": "subscribe",
                        "hub.verify_token": "wrong_token",
                        "hub.challenge": "challenge123",
                    },
                )

        self.assertEqual(response.status_code, 403)

    async def test_verify_webhook_rejects_missing_params(self):
        """GET /webhook without required params should get 403."""
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            response = await client.get("/api/webhook")

        self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
