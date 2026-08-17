# MediCORE

Ingest supplier emails, extract attached PDF catalogs, normalize item data, rank suppliers, and let employees ask natural-language purchase questions.

## Architecture

- Backend: Python 3.12, FastAPI, uv
- Workers: Celery with Valkey broker
- LLM: routed chat completions with Groq primary and OpenRouter fallback
- PDF extraction: PyMuPDF with pdfplumber fallback
- Database: Supabase Postgres
- Storage: Supabase Storage for source PDFs
- Cache/session: Valkey
- Frontend: Next.js chat and dashboard UI
- Dev email mode: IMAP polling
- Production email mode: Gmail Pub/Sub push webhook

## Quick Start

1. Copy environment defaults:

   ```powershell
   Copy-Item .env.example .env
   ```

   For Supabase, the least error-prone database setup is to use separate fields:

   ```env
   SUPABASE_DB_HOST=db.your-project-ref.supabase.co
   SUPABASE_DB_PORT=5432
   SUPABASE_DB_NAME=postgres
   SUPABASE_DB_USER=postgres
   SUPABASE_DB_PASSWORD=your_database_password
   ```

   If you use `DATABASE_URL` instead, URL-encode special password characters like `@`, `#`, `%`, `/`, `?`, and `&`.

2. Install backend dependencies:

   ```powershell
   uv sync
   ```

3. Apply `supabase/migrations/001_init.sql` in the Supabase SQL editor.

   The migration is safe to rerun; it drops existing tenant policies before recreating them.

4. Seed mock catalogue data while email reading is paused:

   ```powershell
   uv run python -m backend.app.seed_mock_catalogs
   ```

   This creates 10 mock extracted catalogues, 10 suppliers, and 80 catalogue items in Supabase/Postgres.

5. Run the API:

   ```powershell
   uv run -- python -m uvicorn backend.app.main:app --host 0.0.0.0 --reload --port 8000
   ```

6. Run the worker only when you want email ingestion/background processing:

   ```powershell
   uv run -- python -m celery -A backend.app.tasks worker --loglevel=info --pool=solo
   ```



   **Note on Windows:** The `--pool=solo` flag disables multiprocessing and runs a single-process worker. This avoids permission errors from billiard's semaphore locks on Windows. For production on Windows, consider using WSL2 or Docker instead.

7. Run the frontend:

   ```powershell
   cd frontend
   npm install
   npm.cmd run dev -- --hostname 0.0.0.0
   ```
8. Open url : http://192.168.29.44:3000

## Development vs Production Email

Development uses IMAP polling through `POST /api/ingestion/poll-now` or Celery beat.

Production uses Gmail Pub/Sub push notifications at:

```text
POST /webhooks/gmail
```

Set the Gmail push subscription endpoint to the deployed FastAPI URL. The webhook queues the catalog processing job and returns immediately.

## Safety Model

The LLM never talks to the database directly. Natural-language questions are converted into a whitelisted query plan, validated by Python, executed through parameterized Supabase/Postgres calls, and then summarized conversationally.

## Authentication & Registration Flow

MediCORE includes a premium, secure authentication and 3-step registration workflow:
1. **Account Registration (`/register`)**: Collects essential user details (name, organisation, role, email, password) and registers the user in Supabase Auth. Banners explicitly state that this password is for MediCORE access, distinct from email passwords.
2. **Supplier Email Setup (`/register/email-setup`)**: Prompts the user to connect their supplier inbox (e.g., Gmail) using a secure IMAP App Password. Includes custom inline guides, advanced collapsible filters (PDF-only toggle, keyword filters, skip promotions tab), and an interactive "Test Connection" button calling the FastAPI backend.
3. **App Password Encryption**: Credentials are symmetrically encrypted using Fernet (AES-128) with a key derived from the Supabase service role key, ensuring that raw passwords are never stored in the database.
4. **Triggers and Row Level Security (RLS)**: PostgreSQL triggers automatically create a User Profile and default Email Sync Settings in the database upon signup, protected by Row Level Security (RLS) policies.

---

## Deployment & Database Connectivity

### Database Connection and Pooler WARNING

> [!WARNING]
> In production environments like Railway, the Supabase Transaction Pooler (`aws-0-ap-south-1.pooler.supabase.com:6543`) may throw `FATAL: (ENOTFOUND) tenant/user postgres.vyheggbcjojhipqrvdrz not found` errors. MediCORE's backend automatically prioritizes a direct database connection via port `5432` whenever `SUPABASE_DB_HOST` and `SUPABASE_DB_PASSWORD` are configured. This provides a stable, zero-crash database link.

For production, configure the direct connection variables in Railway:

```env
ENVIRONMENT=production
FRONTEND_ORIGIN=https://medi-core-silk.vercel.app
MOCK_DATA_ENABLED=false

SUPABASE_URL=https://vyheggbcjojhipqrvdrz.supabase.co
SUPABASE_SERVICE_ROLE_KEY=your-service-role-key
SUPABASE_STORAGE_BUCKET=catalog-pdfs

SUPABASE_DB_HOST=db.vyheggbcjojhipqrvdrz.supabase.co
SUPABASE_DB_PORT=5432
SUPABASE_DB_NAME=postgres
SUPABASE_DB_USER=postgres
SUPABASE_DB_PASSWORD=your-database-password
```

### Applying Migrations
Apply migrations using the Supabase SQL editor or direct CLI/TCP tools. The migration scripts in `supabase/migrations/` (such as `002_login_register.sql`) are designed to be fully idempotent, dropping old RLS policies automatically before recreating them to prevent conflicts.

### VPS/Docker Valkey Configuration

MediCORE uses Valkey as the Redis-compatible broker/cache for Celery and chat result caching. The Python dependency is still named `redis` because that is the standard Redis-protocol client and works with Valkey.

Set these variables in production:

```env
VALKEY_PASSWORD=generate-a-long-random-secret
VALKEY_URL=redis://:generate-a-long-random-secret@valkey:6379/0
```

If Valkey runs outside Docker, replace `valkey` with the Valkey host name or private IP. The Docker Compose file binds Valkey to `127.0.0.1:6379` for local terminal workers; do not bind it to `0.0.0.0` or expose port `6379` publicly.

### LLM Router Configuration

MediCORE uses Groq as the primary LLM provider and OpenRouter as the secondary fallback for extraction, supplier-email classification, query planning, and ProcuraAI answers.

```env
GROQ_API_KEY=your-groq-api-key
GROQ_MODEL=llama-3.3-70b-versatile
GROQ_BASE_URL=https://api.groq.com/openai/v1

OPENROUTER_API_KEY=your-openrouter-api-key
OPENROUTER_MODEL=openai/gpt-4o-mini
OPENROUTER_SITE_URL=https://your-frontend-domain.com
OPENROUTER_APP_NAME=MediCORE
```

### Railway/Vercel Test Deployment:
- Deploy FastAPI using `backend/Dockerfile`
- Deploy Valkey or use a Redis-compatible managed service
- Use Supabase Cloud Postgres
- Deploy `frontend` to Vercel
- Inject environment variables from `.env.example`

For Railway deployments where SMTP is unavailable, send admin invitation and password-reset emails through Gmail API:

```env
TRANSACTIONAL_EMAIL_PROVIDER=gmail_api
GOOGLE_CLIENT_ID=your-oauth-client-id
GOOGLE_CLIENT_SECRET=your-oauth-client-secret
GOOGLE_REFRESH_TOKEN=your-oauth-refresh-token
GMAIL_API_SENDER=your-gmail-address@gmail.com
GMAIL_USER_ID=me
```

Generate the refresh token locally. For a Desktop app OAuth client, the script uses this loopback redirect URI:

```text
http://127.0.0.1:8765
```

Then run:

```powershell
$env:GOOGLE_CLIENT_ID="your-oauth-client-id"
$env:GOOGLE_CLIENT_SECRET="your-oauth-client-secret"
uv run python scripts/generate_gmail_refresh_token.py
```

The OAuth client must request the `https://www.googleapis.com/auth/gmail.send` scope. Put the printed `GOOGLE_REFRESH_TOKEN` in Railway for both the FastAPI service and any Celery service that sends transactional emails.

### AWS Production Deployment:
- Run API and Celery worker as separate ECS/Fargate services
- Use Valkey, ElastiCache, or another Redis-compatible broker
- Use Supabase Pro, enable RLS policies in `supabase/migrations/`
- Configure Gmail Pub/Sub webhook to `/webhooks/gmail`
## IMAP Email Test

For real Gmail IMAP testing, keep mock fallback disabled:

```env
EMAIL_MODE=imap
MOCK_DATA_ENABLED=false
IMAP_HOST=imap.gmail.com
IMAP_PORT=993
IMAP_USERNAME=your-gmail-address@gmail.com
IMAP_PASSWORD=your-gmail-app-password
IMAP_MAILBOX=INBOX
```

The IMAP poller reads only unread emails with PDF attachments. If you already opened the test email, mark it unread in Gmail before polling.

Quick direct test without Celery:

```powershell
uv run python -c "from backend.app.db import SessionLocal; from backend.app.services.email_ingestion import EmailIngestionService; db=SessionLocal(); print(EmailIngestionService(db).poll_imap_inbox()); db.close()"
```

Full worker test:

```powershell
docker compose exec valkey valkey-cli -a your-valkey-password ping
uv run uvicorn backend.app.main:app --host 0.0.0.0 --reload --port 8000
uv run python -m celery -A backend.app.tasks worker --loglevel=info --pool=solo
```

Trigger a poll from another terminal:

```powershell
Invoke-RestMethod -Method Post http://localhost:8000/api/ingestion/poll-now
```
Fernet key : uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
MAILBOX_FERNET_KEY=