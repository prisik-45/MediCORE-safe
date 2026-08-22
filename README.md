# MediCORE

Ingest supplier emails, extract attached PDF catalogs, normalize item data, rank suppliers, and let employees ask natural-language purchase questions.

## Architecture

```text
                    Internet
                       │
                   HTTPS :443
                       │
                       ▼
                 ┌───────────┐          Certbot
                 │   Nginx   │◄───────── Let's Encrypt
                 │ + TLS     │           ACME Challenge
                 └─────┬─────┘
                       │
              ┌────────┴────────┐
              ▼                 ▼
          Next.js            FastAPI
           :3000              :8000
                                │
                   ┌────────────┼────────────┐
                   ▼            ▼            ▼
               Supabase      Database      Valkey
                                             │
                                             ▼
                                           Celery
```

- **Backend**: Python 3.12, FastAPI, uv
- **Workers**: Celery with Valkey broker and result backend
- **Authentication**: Secure HttpOnly cookies managed via FastAPI & Supabase Auth (Independent of Valkey or Nginx/Certbot)
- **Frontend Isolation**: Next.js frontend never directly accesses the application database; all application data flows through authenticated FastAPI endpoints.
- **TLS / SSL**: Automated Let's Encrypt certificates via Certbot webroot challenge & persistent Docker volumes
- **LLM**: Routed chat completions with Groq primary and OpenRouter fallback
- **PDF Extraction**: PyMuPDF with pdfplumber fallback
- **Database**: Supabase Postgres
- **Storage**: Supabase Storage for source PDFs
- **Cache**: Valkey (for Celery background tasks & approved application query caching)

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

2. Install backend dependencies:

   ```powershell
   uv sync
   ```

3. Seed mock catalogue data while email reading is paused:

   ```powershell
   uv run python -m backend.app.seed_mock_catalogs
   ```

4. Run the API:

   ```powershell
   uv run -- python -m uvicorn backend.app.main:app --host 0.0.0.0 --reload --port 8000
   ```

5. Run the Celery worker for email ingestion/background processing:

   ```powershell
   uv run -- python -m celery -A backend.app.tasks worker --loglevel=info --pool=solo
   ```

6. Run the frontend:

   ```powershell
   cd frontend
   npm install
   npm run dev
   ```

---

## Let's Encrypt HTTPS Setup (Certbot + Nginx)

MediCORE supports automated TLS certificate issuance and renewal via Certbot and Nginx using the ACME webroot challenge (`/.well-known/acme-challenge/`).

### Initial Certificate Issuance (Production)

1. Start Nginx and the stack in production mode:

   ```powershell
   docker compose -f docker-compose.prod.yml up -d --build
   ```

   Set `DOMAIN=example.com` in the production `.env` before starting the stack. Nginx uses that value to render the TLS certificate path and creates a temporary self-signed certificate so HTTP challenge traffic can start before Let's Encrypt issues the real certificate.

2. Request Let's Encrypt SSL certificate for your domain:

   ```bash
   ./scripts/init_certbot.sh example.com admin@example.com
   ```
   *For Windows PowerShell:*
   ```powershell
   .\scripts\init_certbot.ps1 -Domain "example.com" -Email "admin@example.com"
   ```

3. Certbot issues the certificate via the webroot challenge (`/var/www/certbot`), saves it to `/etc/letsencrypt/live/<your-domain>/`, replaces the temporary certificate, and reloads Nginx automatically.

### Automatic Certificate Renewal

The `certbot` container runs a background daemon that checks for renewal every 12 hours. Certificates are renewed automatically when approaching expiration (30 days remaining).

To test renewal manually at any time:

```powershell
docker compose exec certbot certbot renew --dry-run
```

---

## Safety Model & Data Access Rules

- **Zero Direct Frontend DB Access**: The Next.js frontend does not directly access the PostgreSQL database or Supabase PostgREST tables. All database operations are proxied, validated, and executed through authenticated FastAPI backend routes.
- **Valkey & Authentication Separation**: Valkey is used strictly for Celery background job queuing and approved application caching. Authentication sessions, access tokens, and refresh tokens are NOT stored in Valkey or browser local/sessionStorage, but in HttpOnly, Secure cookies managed directly between FastAPI and Supabase Auth.
- **Nginx & Certbot Responsibility**: Certbot ONLY manages TLS certificates. Neither Nginx nor Certbot store, inspect, or manage application sessions or tokens.
