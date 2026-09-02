from __future__ import annotations

import calendar
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import httpx

from app.core.config import settings
from app.database.redis_cache import redis_cache
from app.utils.logger import logger


# Cloudflare R2 Standard free tier (monthly).
R2_FREE_STORAGE_BYTES = 10_000_000_000
R2_FREE_CLASS_A = 1_000_000
R2_FREE_CLASS_B = 10_000_000

# Meridin intentionally stops before the Cloudflare free tier is reached.
R2_GUARD_RATIO = 0.90
R2_WARNING_RATIO = 0.80

R2_GUARD_STORAGE_BYTES = int(R2_FREE_STORAGE_BYTES * R2_GUARD_RATIO)
R2_GUARD_CLASS_A = int(R2_FREE_CLASS_A * R2_GUARD_RATIO)
R2_GUARD_CLASS_B = int(R2_FREE_CLASS_B * R2_GUARD_RATIO)

# Only these object operations are expected from Meridin's media architecture.
# PutObject = upload (Class A); GetObject = image view (Class B).
CLASS_A_ACTIONS = {
    "ListBuckets",
    "PutBucket",
    "ListObjects",
    "PutObject",
    "CopyObject",
    "CompleteMultipartUpload",
    "CreateMultipartUpload",
    "LifecycleStorageTierTransition",
    "ListMultipartUploads",
    "UploadPart",
    "UploadPartCopy",
    "ListParts",
    "PutBucketEncryption",
    "PutBucketCors",
    "PutBucketLifecycleConfiguration",
}

CLASS_B_ACTIONS = {
    "HeadBucket",
    "HeadObject",
    "GetObject",
    "UsageSummary",
    "GetBucketEncryption",
    "GetBucketLocation",
    "GetBucketCors",
    "GetBucketLifecycleConfiguration",
}


class R2UsageService:
    """Global, non-tenant R2 usage guard and Cloudflare usage reporter."""

    @staticmethod
    def month_key() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m")

    @staticmethod
    def _month_ttl() -> int:
        now = datetime.now(timezone.utc)
        last_day = calendar.monthrange(now.year, now.month)[1]
        end = now.replace(
            day=last_day,
            hour=23,
            minute=59,
            second=59,
            microsecond=0,
        )
        return max(3600, int((end - now).total_seconds()) + 86400)

    @classmethod
    def _counter_key(cls, name: str) -> str:
        return f"meridin:r2:{cls.month_key()}:{name}"

    @classmethod
    async def reserve_upload(cls) -> bool:
        value = await redis_cache.reserve_counter(
            cls._counter_key("class_a_reserved"),
            1,
            R2_GUARD_CLASS_A,
            ttl=cls._month_ttl(),
        )
        return value is not None and value >= 0

    @classmethod
    async def reserve_view(cls) -> bool:
        value = await redis_cache.reserve_counter(
            cls._counter_key("class_b_views"),
            1,
            R2_GUARD_CLASS_B,
            ttl=cls._month_ttl(),
        )
        return value is not None and value >= 0

    @classmethod
    async def counters(cls) -> Dict[str, Any]:
        upload_key = cls._counter_key("class_a_reserved")
        view_key = cls._counter_key("class_b_views")

        uploads = await redis_cache.get_int(upload_key)
        views = await redis_cache.get_int(view_key)

        return {
            "month": cls.month_key(),
            "class_a_reserved": uploads or 0,
            "class_b_views": views or 0,
            "redis_available": redis_cache.is_connected,
        }

    @classmethod
    async def cloudflare_metrics(cls) -> Dict[str, Any]:
        account_id = settings.CLOUDFLARE_R2_ACCOUNT_ID.strip()
        api_token = settings.CLOUDFLARE_API_TOKEN.strip()

        if not account_id or not api_token:
            raise RuntimeError("Cloudflare API credentials are not configured.")

        now = datetime.now(timezone.utc)
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        storage_url = (
            f"https://api.cloudflare.com/client/v4/accounts/"
            f"{account_id}/r2/metrics"
        )

        graphql_url = "https://api.cloudflare.com/client/v4/graphql"

        headers = {
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            storage_response = await client.get(
                storage_url,
                headers=headers,
            )
            storage_response.raise_for_status()
            storage_data = storage_response.json()

            query = """
            query R2MonthlyOperations(
                $accountTag: string!
                $startDate: Time
                $endDate: Time
                $bucketName: string
            ) {
                viewer {
                    accounts(filter: { accountTag: $accountTag }) {
                        r2OperationsAdaptiveGroups(
                            limit: 10000
                            filter: {
                                datetime_geq: $startDate
                                datetime_leq: $endDate
                                            }
                        ) {
                            sum {
                                requests
                            }
                            dimensions {
                                actionType
                            }
                        }
                    }
                }
            }
            """

            graphql_response = await client.post(
                graphql_url,
                headers=headers,
                json={
                    "query": query,
                    "variables": {
                        "accountTag": account_id,
                        "startDate": start.isoformat(),
                        "endDate": now.isoformat(),
                    },
                },
            )
            graphql_response.raise_for_status()
            graphql_data = graphql_response.json()

        if graphql_data.get("errors"):
            raise RuntimeError(
                "Cloudflare GraphQL error: "
                + str(graphql_data["errors"])
            )

        accounts = (
            graphql_data.get("data", {})
            .get("viewer", {})
            .get("accounts", [])
        )

        groups = (
            accounts[0].get("r2OperationsAdaptiveGroups", [])
            if accounts
            else []
        )

        class_a = 0
        class_b = 0
        operation_breakdown: Dict[str, int] = {}

        for group in groups:
            action = (
                group.get("dimensions", {}).get("actionType")
                or "unknown"
            )
            requests = int(
                group.get("sum", {}).get("requests") or 0
            )
            operation_breakdown[action] = (
                operation_breakdown.get(action, 0) + requests
            )

            if action in CLASS_A_ACTIONS:
                class_a += requests
            elif action in CLASS_B_ACTIONS:
                class_b += requests

        standard = (
            storage_data.get("result", {})
            .get("standard", {})
            .get("published", {})
        )

        storage_bytes = int(standard.get("payloadSize") or 0)
        metadata_bytes = int(standard.get("metadataSize") or 0)
        objects = int(standard.get("objects") or 0)

        return {
            "month": cls.month_key(),
            "storage_bytes": storage_bytes,
            "metadata_bytes": metadata_bytes,
            "objects": objects,
            "cloudflare_class_a": class_a,
            "cloudflare_class_b": class_b,
            "operation_breakdown": operation_breakdown,
            "source": "cloudflare",
            "retrieved_at": now.isoformat(),
        }

    @classmethod
    async def status(cls) -> Dict[str, Any]:
        counters = await cls.counters()
        cloudflare: Optional[Dict[str, Any]] = None
        cloudflare_error: Optional[str] = None

        try:
            cloudflare = await cls.cloudflare_metrics()
        except Exception as exc:
            cloudflare_error = str(exc)
            logger.warning("R2 Cloudflare metrics unavailable: %s", exc)

        storage_bytes = (
            cloudflare.get("storage_bytes", 0)
            if cloudflare
            else 0
        )

        class_a = max(
            counters["class_a_reserved"],
            cloudflare.get("cloudflare_class_a", 0) if cloudflare else 0,
        )
        class_b = max(
            counters["class_b_views"],
            cloudflare.get("cloudflare_class_b", 0) if cloudflare else 0,
        )

        storage_percent = (
            storage_bytes / R2_FREE_STORAGE_BYTES * 100
        )
        class_a_percent = class_a / R2_FREE_CLASS_A * 100
        class_b_percent = class_b / R2_FREE_CLASS_B * 100

        blocked = (
            storage_bytes >= R2_GUARD_STORAGE_BYTES
            or class_a >= R2_GUARD_CLASS_A
            or class_b >= R2_GUARD_CLASS_B
            or not redis_cache.is_connected
            or cloudflare_error is not None
        )

        warning = (
            storage_percent >= R2_WARNING_RATIO * 100
            or class_a_percent >= R2_WARNING_RATIO * 100
            or class_b_percent >= R2_WARNING_RATIO * 100
        )

        return {
            "month": cls.month_key(),
            "limits": {
                "storage_bytes": R2_FREE_STORAGE_BYTES,
                "class_a": R2_FREE_CLASS_A,
                "class_b": R2_FREE_CLASS_B,
            },
            "guard_limits": {
                "storage_bytes": R2_GUARD_STORAGE_BYTES,
                "class_a": R2_GUARD_CLASS_A,
                "class_b": R2_GUARD_CLASS_B,
                "ratio": R2_GUARD_RATIO,
            },
            "usage": {
                "storage_bytes": storage_bytes,
                "storage_gb": round(storage_bytes / 1_000_000_000, 3),
                "class_a": class_a,
                "class_b": class_b,
                "storage_percent": round(storage_percent, 2),
                "class_a_percent": round(class_a_percent, 2),
                "class_b_percent": round(class_b_percent, 2),
            },
            "warning": warning,
            "blocked": blocked,
            "cloudflare": cloudflare,
            "cloudflare_error": cloudflare_error,
            "guard_counters": counters,
            "policy": {
                "warning_at_percent": R2_WARNING_RATIO * 100,
                "stop_at_percent": R2_GUARD_RATIO * 100,
                "scope": "global",
            },
        }


r2_usage_service = R2UsageService()
