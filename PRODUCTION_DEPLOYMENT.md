# Meridin production deployment

## Current architecture

- Client dashboard: `https://app.meridin.in` → Vercel
- Admin dashboard: `https://admin.meridin.in` → Vercel
- API: `https://meridin-new.vercel.app/api` → Vercel

## Future architecture

- Client dashboard stays on Vercel at `app.meridin.in`.
- Admin dashboard stays on Vercel at `admin.meridin.in`.
- API moves to Google Cloud and is exposed as `https://api.meridin.in/api`.

## Production Vercel API variables

Set `APP_ENV=production`, `DEBUG=False`, `MONGODB_REQUIRED=True`, a strong `APP_SECRET`, production MongoDB/Redis credentials, restrictive CORS, and all required Meta/OpenRouter/R2 secrets in the API project's Vercel Environment Variables.

Do not put secrets in the frontend or Git.

## Frontend API migration

The current client and admin API modules default to the current Vercel API. When the backend moves to Google Cloud, change the production fallback in:

- `meridin_FE/client/js/api.js`
- `meridin_FE/admin/js/api.js`

from `https://meridin-new.vercel.app/api` to `https://api.meridin.in/api`, then redeploy both Vercel dashboard projects.

## Health endpoints

- `/health/live` — process liveness
- `/health/ready` — MongoDB, Redis and ML readiness
- `/health` — backward-compatible dependency status

## Cloudflare

Cloudflare is optional. It is not required to place Vercel in production. It can later be added for DNS, WAF, rate limiting and edge security.
