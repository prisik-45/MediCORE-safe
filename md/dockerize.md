# Dockerizing MediCORE

This guide explains how to Dockerize the MediCORE project step by step while keeping previous working versions protected from new development changes.

Project root:

```powershell
cd "C:\Users\prince\Documents\Core Consultancy\Medicore-prev\MediCORE-Admin"
```

## 1. Current Project Services

MediCORE currently has these services:

| Service | Location | Runtime | Purpose |
| --- | --- | --- | --- |
| API backend | `backend/app/main.py` | FastAPI + uvicorn | HTTP API, auth, catalog ingestion endpoints, chat endpoints |
| Worker | `backend/app/tasks.py` | Celery | Background email/catalog processing |
| Broker/cache | Docker image | Valkey | Redis-compatible Celery broker/result backend |
| Frontend | `frontend` | Next.js | Admin, employee, superadmin UI |
| Database/storage/auth | Supabase Cloud | External service | Postgres, auth, storage |

The project is already partially dockerized:

- `backend/Dockerfile` exists.
- `frontend/Dockerfile` exists.
- `docker-compose.yml` already runs `valkey`, `api`, and `worker`.
- `.dockerignore` already excludes `.env`, virtualenvs, node modules, build output, logs, and git metadata.

## 2. Why Docker Helps Your Main Goal

Your concern is:

> If I modify code, it must not affect my previous version features/functionality.

Docker helps by letting you freeze a working version as an image tag. New code can run in a different container/image without replacing the old one.

Recommended version strategy:

```text
medicore-api:v0.1-working
medicore-worker:v0.1-working
medicore-frontend:v0.1-working

medicore-api:dev
medicore-worker:dev
medicore-frontend:dev
```

Use `v0.1-working` when you want the last stable behavior. Use `dev` while changing code.

## 3. Prerequisites

Install Docker Desktop and confirm it is running:

```powershell
docker --version
docker compose version
```

If either command fails, install or start Docker Desktop first.

## 4. Fix Secrets Before Building

Do not bake secrets into Docker images.

Current status:

- `.dockerignore` already excludes `.env`, which is good.
- `.env` contains real credentials and should remain local only.
- If `.env` was ever committed or shared, rotate the affected Supabase, Gmail, SMTP, OpenRouter, and app-password credentials.

Recommended files:

```text
.env                 local development secrets, never committed
.env.example         safe placeholder values, committed
frontend/.env.local  local frontend values, never committed
```

Recommended `.env.example` shape:

```env
ENVIRONMENT=development
APP_NAME=MediCORE
API_BASE_URL=http://localhost:8000
FRONTEND_ORIGIN=http://localhost:3000
DOMAIN=example.com

SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_ROLE_KEY=replace-me
SUPABASE_STORAGE_BUCKET=catalog-pdfs
SUPABASE_DB_HOST=db.your-project.supabase.co
SUPABASE_DB_PORT=5432
SUPABASE_DB_NAME=postgres
SUPABASE_DB_USER=postgres
SUPABASE_DB_PASSWORD=replace-me

VALKEY_PASSWORD=replace-me
VALKEY_URL=redis://:replace-me@valkey:6379/0

EMAIL_MODE=imap
IMAP_HOST=imap.gmail.com
IMAP_PORT=993
IMAP_USERNAME=replace-me
IMAP_PASSWORD=replace-me
IMAP_MAILBOX=INBOX

OPENROUTER_API_KEY=replace-me
OPENROUTER_MODEL=openai/gpt-4o-mini
OPENROUTER_SITE_URL=http://localhost:3000
OPENROUTER_APP_NAME=MediCORE

NEXT_PUBLIC_API_URL=http://127.0.0.1:8000
NEXT_PUBLIC_WS_URL=ws://127.0.0.1:8000/ws/chat
NEXT_PUBLIC_SUPABASE_URL=https://your-project.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=replace-me
```

## 5. Backend Dockerfile Review

Existing file:

```text
backend/Dockerfile
```

Current behavior:

- Uses `python:3.12-slim`.
- Installs `uv`.
- Copies `pyproject.toml`.
- Runs `uv sync`.
- Copies `backend`.
- Starts uvicorn.

Recommended changes:

1. Copy `uv.lock` too, if present, so builds are reproducible.
2. Use `uv sync --frozen` when `uv.lock` exists.
3. Add a healthcheck in compose, because the API already has `/health`.
4. Use the same image for `api` and `worker`, but different commands.

Recommended backend Dockerfile:

```dockerfile
FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock* ./
RUN uv sync --frozen || uv sync

COPY backend ./backend

ENV PYTHONPATH=/app
ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000

CMD ["sh", "-c", "uvicorn backend.app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
```

## 6. Frontend Dockerfile Review

Existing file:

```text
frontend/Dockerfile
```

Current behavior:

- Uses `node:22-alpine`.
- Installs packages with `npm install`.
- Builds Next.js.
- Starts Next.js.

Recommended changes:

1. Use `npm ci` instead of `npm install` because `package-lock.json` exists.
2. Copy `package-lock.json` before installing dependencies.
3. Expose port `3000`.
4. Pass `NEXT_PUBLIC_*` values at build time because Next.js embeds public env variables during build.

Recommended frontend Dockerfile:

```dockerfile
FROM node:22-alpine

WORKDIR /app

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend ./

ARG NEXT_PUBLIC_API_URL
ARG NEXT_PUBLIC_WS_URL
ARG NEXT_PUBLIC_SUPABASE_URL
ARG NEXT_PUBLIC_SUPABASE_ANON_KEY

ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
ENV NEXT_PUBLIC_WS_URL=$NEXT_PUBLIC_WS_URL
ENV NEXT_PUBLIC_SUPABASE_URL=$NEXT_PUBLIC_SUPABASE_URL
ENV NEXT_PUBLIC_SUPABASE_ANON_KEY=$NEXT_PUBLIC_SUPABASE_ANON_KEY

RUN npm run build

EXPOSE 3000

CMD ["npm", "run", "start"]
```

## 7. Recommended Compose File

The current `docker-compose.yml` runs backend API, worker, and Valkey. Add frontend when you want the whole app in Docker.

Recommended `docker-compose.yml`:

```yaml
services:
  valkey:
    image: valkey/valkey:8-alpine
    command:
      - valkey-server
      - --requirepass
      - ${VALKEY_PASSWORD:-medicore-local-valkey-password}
      - --appendonly
      - "yes"
    ports:
      - "127.0.0.1:6379:6379"
    volumes:
      - valkey_data:/data
    healthcheck:
      test:
        - CMD
        - valkey-cli
        - -a
        - ${VALKEY_PASSWORD:-medicore-local-valkey-password}
        - ping
      interval: 10s
      timeout: 3s
      retries: 5

  api:
    build:
      context: .
      dockerfile: backend/Dockerfile
    image: medicore-api:dev
    env_file: .env
    environment:
      VALKEY_URL: ${VALKEY_URL:-redis://:${VALKEY_PASSWORD:-medicore-local-valkey-password}@valkey:6379/0}
    ports:
      - "8000:8000"
    depends_on:
      valkey:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"]
      interval: 15s
      timeout: 5s
      retries: 5

  worker:
    build:
      context: .
      dockerfile: backend/Dockerfile
    image: medicore-worker:dev
    env_file: .env
    environment:
      VALKEY_URL: ${VALKEY_URL:-redis://:${VALKEY_PASSWORD:-medicore-local-valkey-password}@valkey:6379/0}
    command: ["uv", "run", "celery", "-A", "backend.app.tasks", "worker", "--loglevel=info"]
    depends_on:
      valkey:
        condition: service_healthy

  frontend:
    build:
      context: .
      dockerfile: frontend/Dockerfile
      args:
        NEXT_PUBLIC_API_URL: ${NEXT_PUBLIC_API_URL:-http://127.0.0.1:8000}
        NEXT_PUBLIC_WS_URL: ${NEXT_PUBLIC_WS_URL:-ws://127.0.0.1:8000/ws/chat}
        NEXT_PUBLIC_SUPABASE_URL: ${NEXT_PUBLIC_SUPABASE_URL}
        NEXT_PUBLIC_SUPABASE_ANON_KEY: ${NEXT_PUBLIC_SUPABASE_ANON_KEY}
    image: medicore-frontend:dev
    ports:
      - "3000:3000"
    depends_on:
      api:
        condition: service_healthy

volumes:
  valkey_data:
```

## 8. Step-by-Step Dockerization

### Step 1: Create or verify `.env`

Use the existing local `.env`, but ensure these values are Docker-friendly:

```env
VALKEY_URL=redis://:your-password@valkey:6379/0
REDIS_URL=redis://:your-password@valkey:6379/0
FRONTEND_ORIGIN=http://localhost:3000
API_BASE_URL=http://localhost:8000
NEXT_PUBLIC_API_URL=http://127.0.0.1:8000
NEXT_PUBLIC_WS_URL=ws://127.0.0.1:8000/ws/chat
```

Inside Docker, the backend reaches Valkey through hostname `valkey`, not `localhost`.

### Step 2: Build images

```powershell
docker compose build
```

### Step 3: Start all services

```powershell
docker compose up
```

Or run in background:

```powershell
docker compose up -d
```

### Step 4: Check container status

```powershell
docker compose ps
```

Expected:

```text
valkey    healthy/running
api       healthy/running
worker    running
frontend  running
```

### Step 5: Test API health

```powershell
Invoke-RestMethod http://localhost:8000/health
```

Expected:

```json
{
  "status": "ok",
  "environment": "development"
}
```

### Step 6: Open frontend

```text
http://localhost:3000
```

### Step 7: View logs

```powershell
docker compose logs -f api
docker compose logs -f worker
docker compose logs -f frontend
docker compose logs -f valkey
```

### Step 8: Stop services

```powershell
docker compose down
```

Keep Valkey data:

```powershell
docker compose down
```

Delete Valkey data:

```powershell
docker compose down -v
```

Use `-v` carefully because it removes the local Valkey volume.

## 9. Development Workflow Without Breaking Previous Version

### Freeze a stable version

After you confirm the current app works:

```powershell
docker compose build
docker tag medicore-api:dev medicore-api:v0.1-working
docker tag medicore-worker:dev medicore-worker:v0.1-working
docker tag medicore-frontend:dev medicore-frontend:v0.1-working
```

Now `v0.1-working` is your protected known-good version.

### Continue development

Edit code normally, then rebuild only the changed parts:

```powershell
docker compose build api worker
docker compose up -d api worker
```

For frontend changes:

```powershell
docker compose build frontend
docker compose up -d frontend
```

### Run old stable version again

Create `docker-compose.stable.yml`:

```yaml
services:
  api:
    image: medicore-api:v0.1-working
    build: null

  worker:
    image: medicore-worker:v0.1-working
    build: null

  frontend:
    image: medicore-frontend:v0.1-working
    build: null
```

Run the stable stack:

```powershell
docker compose -f docker-compose.yml -f docker-compose.stable.yml up -d
```

Run the development stack:

```powershell
docker compose up -d --build
```

## 10. Stronger Protection: Separate Project Names

Docker Compose groups containers, networks, and volumes by project name. Use separate project names to run old and new versions side by side.

Development:

```powershell
docker compose -p medicore_dev up -d --build
```

Stable:

```powershell
docker compose -p medicore_stable -f docker-compose.yml -f docker-compose.stable.yml up -d
```

If running both at the same time, change ports in one stack:

```yaml
services:
  api:
    ports:
      - "8001:8000"

  frontend:
    ports:
      - "3001:3000"
```

Then access:

```text
Development: http://localhost:3000 and http://localhost:8000
Stable:     http://localhost:3001 and http://localhost:8001
```

## 11. Database Safety

Docker protects service code, but it does not automatically protect your Supabase database from schema or data changes.

To avoid breaking old functionality:

1. Treat every file in `supabase/migrations` as permanent history.
2. Never edit an already-applied migration unless you are resetting a disposable local database.
3. Add a new migration for every schema change.
4. Test migrations against a separate Supabase dev project before applying them to production.
5. Keep separate Supabase projects for development and stable/production.

Recommended environment split:

```text
.env.development     points to Supabase dev project
.env.stable          points to Supabase stable project
.env.production      points to Supabase production project
```

Run dev with:

```powershell
docker compose --env-file .env.development -p medicore_dev up -d --build
```

Run stable with:

```powershell
docker compose --env-file .env.stable -p medicore_stable -f docker-compose.yml -f docker-compose.stable.yml up -d
```

## 12. Backend Tests in Docker

Add this optional service to compose:

```yaml
  backend-tests:
    build:
      context: .
      dockerfile: backend/Dockerfile
    env_file: .env
    environment:
      VALKEY_URL: ${VALKEY_URL:-redis://:${VALKEY_PASSWORD:-medicore-local-valkey-password}@valkey:6379/0}
    command: ["uv", "run", "pytest", "backend/tests"]
    depends_on:
      valkey:
        condition: service_healthy
```

Run:

```powershell
docker compose run --rm backend-tests
```

If `pytest` is missing, add it to the `dev` dependencies in `pyproject.toml`.

## 13. Recommended Files That Need Changes

These are the files worth changing to complete Dockerization:

| File | Change |
| --- | --- |
| `backend/Dockerfile` | Copy `uv.lock*`, use reproducible `uv sync`, expose port `8000` |
| `frontend/Dockerfile` | Use `npm ci`, copy `package-lock.json`, add build args for `NEXT_PUBLIC_*`, expose port `3000` |
| `docker-compose.yml` | Add image tags, API healthcheck, optional frontend service |
| `.env.example` | Add safe placeholder env values |
| `.gitignore` | Ensure `.env`, `.env.*`, `frontend/.env.local`, `.venv`, `.next`, and logs are ignored |
| `pyproject.toml` | Add `pytest` to dev dependencies if Docker test service is used |
| `md/dockerize.md` | Keep this guide updated whenever Docker behavior changes |

## 14. Useful Commands

Build everything:

```powershell
docker compose build
```

Start everything:

```powershell
docker compose up -d
```

Restart only API:

```powershell
docker compose up -d --build api
```

Restart only worker:

```powershell
docker compose up -d --build worker
```

Restart only frontend:

```powershell
docker compose up -d --build frontend
```

Open API shell:

```powershell
docker compose exec api sh
```

Run a backend script:

```powershell
```

Check Valkey:

```powershell
docker compose exec valkey valkey-cli -a your-password ping
```

View images:

```powershell
docker images | Select-String medicore
```

Remove stopped containers:

```powershell
docker container prune
```

## 15. Practical Recommended Flow

Use this daily workflow during development:

1. Confirm the current version works.
2. Tag it as stable:

   ```powershell
   docker tag medicore-api:dev medicore-api:v0.1-working
   docker tag medicore-worker:dev medicore-worker:v0.1-working
   docker tag medicore-frontend:dev medicore-frontend:v0.1-working
   ```

3. Make code changes.
4. Rebuild and run dev:

   ```powershell
   docker compose -p medicore_dev up -d --build
   ```

5. Test API, worker, frontend, and important old workflows.
6. If something breaks, run the stable version:

   ```powershell
   docker compose -p medicore_stable -f docker-compose.yml -f docker-compose.stable.yml up -d
   ```

7. Once the new version is verified, tag a new stable version:

   ```powershell
   docker tag medicore-api:dev medicore-api:v0.2-working
   docker tag medicore-worker:dev medicore-worker:v0.2-working
   docker tag medicore-frontend:dev medicore-frontend:v0.2-working
   ```

## 16. Key Rule

Docker protects old application code only if you tag and preserve the working images. Database changes need separate protection through migrations, backups, and separate Supabase environments.

## 17. Dev and Prod Compose Files

This project now has separate compose files:

```text
docker-compose.dev.yml
docker-compose.prod.yml
```

Startup priority is encoded through `depends_on` health checks:

```text
Valkey
Backend API
Celery Worker
Frontend
```

Run development:

```powershell
docker compose -f docker-compose.dev.yml up -d --build
```

Run production:

```powershell
docker compose --env-file .env.production -f docker-compose.prod.yml up -d --build
```

Production uses `.env.production`. Do not commit that file.

## 18. Production Backups

The production compose file includes backup services under the `backup` profile. They do not start unless you enable that profile.

Run production with backups:

```powershell
docker compose --env-file .env.production -f docker-compose.prod.yml --profile backup up -d --build
```

### Daily Database Backup

Service:

```text
db-backup
```

What it does:

- Uses the official `postgres:16-alpine` image.
- Runs `pg_dump` against the configured Supabase Postgres host.
- Saves compressed custom-format dumps under `backups/database`.
- Runs every 24 hours by default.
- Deletes dumps older than 14 days by default.

Relevant env values:

```env
SUPABASE_DB_HOST=replace-me
SUPABASE_DB_PORT=5432
SUPABASE_DB_NAME=postgres
SUPABASE_DB_USER=postgres
SUPABASE_DB_PASSWORD=replace-me
DB_BACKUP_INTERVAL_SECONDS=86400
DB_BACKUP_RETENTION_DAYS=14
```

Restore example:

```powershell
docker run --rm -v "${PWD}/backups/database:/backups" postgres:16-alpine pg_restore --list /backups/your-backup.dump
```

Do the actual restore only after choosing the correct target database.

### Certificate PDF Backup

Service:

```text
certificate-pdf-backup
```

What it does:

- Uses `rclone`.
- Syncs the Supabase Storage bucket to `backups/certificate-pdfs/<timestamp>`.
- Runs every 24 hours by default.
- Deletes backup folders older than 30 days by default.

Required env values:

```env
SUPABASE_STORAGE_BUCKET=catalog-pdfs
SUPABASE_STORAGE_S3_ACCESS_KEY_ID=replace-me
SUPABASE_STORAGE_S3_SECRET_ACCESS_KEY=replace-me
SUPABASE_STORAGE_S3_ENDPOINT=replace-me
SUPABASE_STORAGE_S3_REGION=auto
CERTIFICATE_BACKUP_INTERVAL_SECONDS=86400
CERTIFICATE_BACKUP_RETENTION_DAYS=30
```

If certificate PDFs are stored somewhere other than the Supabase Storage bucket, change the `certificate-pdf-backup` service to point to that location.

### Environment Secret Handling

There is intentionally no `environment-backup` service in production. Do not copy `.env.production` into `backups/`, Docker images, GitHub, Docker Hub, or any unencrypted archive.

Safe VPS checklist:

- Keep the production env file only on the Hostinger VPS deployment host.
- Store it outside public web paths and restrict it to the deployment user/root, for example `chmod 600 .env.production`.
- Use Docker Compose `--env-file .env.production` or a runtime `env_file`; do not bake secrets into Docker images.
- Confirm Dockerfiles do not use `COPY . .`. The current backend image copies only `pyproject.toml`, `uv.lock`, `backend/`, and `scripts/`; the frontend image copies only `frontend/`.
- Keep `.env`, `.env.*`, `frontend/.env*`, `backend/.env*`, `backups/`, dumps, archives, and key files excluded by `.dockerignore`.

Cleanup checklist for existing VPS plaintext env backups:

- Inspect `./backups/environment/` on the VPS.
- Delete only obsolete plaintext env backup files from that folder after confirming the active runtime `.env.production` is safe.
- Treat any secret previously copied there as exposed. Plan rotation separately for Supabase service role keys, mailbox/AI encryption keys, OAuth secrets, API keys, and Valkey credentials.
- Do not rotate encryption keys until you have a re-encryption plan for existing encrypted mailbox passwords and stored AI settings.

Backup security checklist:

- Database dumps and certificate PDF backups should be encrypted before storage.
- Move encrypted backup copies off the Hostinger VPS to a private backup store.
- Avoid keeping the only backup copy on the same VPS that runs MediCORE.
