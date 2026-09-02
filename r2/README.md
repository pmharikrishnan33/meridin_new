# Meridin R2 safety configuration

Meridin uses one global R2 budget, not a tenant-specific budget.

Cloudflare's current R2 Standard free tier is 10 GB-month storage, 1,000,000 Class A operations, and 10,000,000 Class B operations per month.

Meridin intentionally stops at 90%:
- 9 GB storage
- 900,000 Class A
- 9,000,000 Class B

Warnings begin at 80%.

Image URLs must use the Meridin API media endpoint rather than a direct public R2 URL. This is required if Meridin must be able to stop image views before the safety threshold. A direct R2 URL bypasses the application's guard.

The Cloudflare API token is used only by the admin-side usage monitor. It should have the minimum R2 read permission needed to read account metrics.
