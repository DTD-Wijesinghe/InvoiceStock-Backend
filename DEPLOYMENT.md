# Backend deployment — Render + Supabase

This repository is self-contained. The migration SQL files are included under `migrations/sql`; no sibling frontend or database directory is required. `start.py` validates production mode, runs all Alembic migrations, then starts FastAPI on `0.0.0.0:$PORT`. Existing local `.env` values are not copied into Docker.

## 1. Commit and push with GitHub Desktop

Review the changed files. Do not commit `.env`, `.venv`, `*.db`, or database credentials. Suggested commit: **fix: make backend standalone for Render and Supabase deployment**. Run `./Prepare-Git.ps1` once in GitHub Desktop → Repository → Open in Terminal before committing. This untracks ignored databases, Python caches and other generated files, keeping local copies; older Git commits still contain the earlier versions. If those earlier databases contained real customer records or reused passwords, remove that history and rotate affected credentials before making the repository public.

## 2. Configure Render

Create a **Web Service**, connect InvoiceStock-Backend, and select **Docker** runtime and **Free** instance. Root Directory: leave empty. Dockerfile Path: `./Dockerfile`. Health Check Path: `/health`. Leave Docker Command empty: the image runs `python start.py`. Do not select Node or run npm for this backend.

Alternatively, for a Python runtime choose Python 3.14, Build Command `pip install -r requirements-lock.txt`, Start Command `python start.py`. The Docker setup is the reproducible default. Existing services can update their settings or be recreated with the correct runtime.

## 3. Backend environment variables

Set these in **Render → Environment**, without wrapping quotes:

| Name | Value |
| --- | --- |
| DATABASE_URL | `postgresql+psycopg://postgres.kxqbblnjuvuvtrdastcx:YOUR_URL_ENCODED_PASSWORD@aws-0-ap-southeast-1.pooler.supabase.com:5432/postgres?sslmode=require` |
| JWT_SECRET | A private random string, at least 48 characters. Keep stable between redeployments. |
| FRONTEND_ORIGIN | Exact frontend HTTPS origin, for example `https://YOUR_SITE.vercel.app`, no trailing slash. |
| PUBLIC_URL | Same frontend HTTPS origin; used for payment return/cancel pages. |
| BACKEND_PUBLIC_URL | Your backend HTTPS origin, for example `https://YOUR_API.onrender.com`; used for payment callbacks. |
| DEMO_MODE | `false` |
| PAYHERE_SANDBOX | `true` until real payment setup is verified. |

Render supplies PORT automatically; do not set DATABASE_URL to localhost. The `postgresql://` and `postgres://` forms are accepted and normalized to the installed psycopg driver. Use Supabase's **Session pooler on port 5432**, as in the URL you provided. Replace the password placeholder with the project's **database password**, not an anon key, service-role key, Supabase login password, or API URL. URL-encode special password characters (for example @ becomes %40, # becomes %23, / becomes %2F). Do not put square brackets around the real password. If forgotten, reset the database password in Supabase yourself.

Generate JWT_SECRET locally in a private terminal with `python -c "import secrets; print(secrets.token_urlsafe(48))"`, then paste it directly into Render. Never put it in frontend variables or Git.

Optional, leave unset until configured: PAYHERE_MERCHANT_ID, PAYHERE_MERCHANT_SECRET, BACKUP_WEBHOOK_SECRET, AI_BASE_URL, AI_API_KEY, AI_MODEL. Inventory/finance rules and product help work without an external model. Optional model-based drafting requires a reachable hosted model endpoint; Render cannot reach Ollama on your laptop's localhost.

## 4. Deployment order and checks

Create the Vercel frontend site first to reserve its actual URL. Set that URL in FRONTEND_ORIGIN/PUBLIC_URL, then deploy the backend. Use your real assigned Render URL for BACKEND_PUBLIC_URL. Open `/health` on the backend: successful deployment returns status ok and database postgresql. The backend root is an API, so `/` returning 404 is expected; `/docs` is disabled. This is not a frontend web page.

Next set Vercel BACKEND_URL to that backend origin and deploy the frontend. Open the frontend `/health` to verify the proxy. Register a disposable business, refresh after login, change language, log out, and check that expired sessions cannot access the account. Production registration does not import the local demo database or its users.

Create your trusted platform administrator by running `python create_admin.py` in an environment connected to this database with the production variables. Public signup creates business owners only. Never run demo.py on the hosted service.

## Troubleshooting

- ModuleNotFoundError psycopg2: old startup/configuration is using the wrong driver. Push the new code and use the provided URL format.
- Missing schema.sql: the migration SQL files must be included in the commit under migrations/sql.
- Startup failed OperationalError: confirm Supabase is active, the database password is correct and encoded, Session pooler port 5432 is selected, and TLS is enabled.
- Startup failed ValidationError: JWT_SECRET must be set and long enough. Do not use the placeholder values.
- DuplicateTable: the database may already have tables without matching Alembic history. Inspect it first; do not drop data or stamp migrations blindly.
- Origin not allowed / login fails: FRONTEND_ORIGIN must exactly match the frontend URL. Redeploy after correcting it.
- Frontend returns HTML for /api: the Vercel build must run the supplied deployment script with BACKEND_URL. Local Vite proxy configuration alone cannot work on a static deployment.
- First request is slow: a Render Free backend can sleep after 15 minutes. Open backend /health, wait for it to wake, and retry the frontend. Do not interpret an initial proxy timeout as deleted data.

## Free hosting limits

Selected combination: Render backend, Vercel frontend, Supabase PostgreSQL. Vercel Hobby permits personal/non-commercial use only; a paid SaaS needs a plan permitting commercial use. These are separate deployments. There is no guarantee of unlimited, always-on, permanently free service: Render Free sleeps and has monthly hour limits, Vercel has plan and usage limits, and Supabase Free can pause inactive projects. Monitor quotas and back up data. A free host does not eliminate payment gateway fees.

Sources checked 2026-09-08:
- https://render.com/docs/free
- https://vercel.com/docs/plans/hobby
- https://supabase.com/docs/guides/database/connecting-to-postgres
- https://supabase.com/docs/guides/platform/free-project-pausing

These changes prepare the repositories for deployment. No live hosting or Supabase connection has been verified by this update; a real database password and provider access were not supplied.
