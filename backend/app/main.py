import logging
from contextlib import asynccontextmanager
from urllib.parse import urlparse

logging.basicConfig(level=logging.INFO)

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from backend.app.api import (
    admin,
    auth_session,
    catalogs,
    chat,
    email_accounts,
    health,
    ingestion,
    superadmin,
    suppliers,
    webhooks,
)
from backend.app.config import get_settings
from backend.app.db import close_database_engines

settings = get_settings()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("MediCORE API startup complete")
    try:
        yield
    finally:
        logger.info("MediCORE API shutdown started")
        close_database_engines()
        logger.info("MediCORE API shutdown complete")

allowed_origins = {
    settings.frontend_origin.rstrip("/"),
    "https://medi-core2.vercel.app",
}
allow_origin_regex = None

if settings.environment.lower() != "production":
    allowed_origins.update(
        {
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:3001",
            "http://127.0.0.1:3001",
            "http://192.168.29.44:3000",
            "http://192.168.29.215:3000",
        }
    )
    allow_origin_regex = r"^https?://(localhost|127\.0\.0\.1|192\.168\.\d{1,3}\.\d{1,3})(:\d+)?$"

app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)

trusted_proxy_hosts = [
    host.strip()
    for host in settings.trusted_proxy_hosts.split(",")
    if host.strip()
]
if trusted_proxy_hosts:
    app.add_middleware(ProxyHeadersMiddleware, trusted_hosts=trusted_proxy_hosts)


@app.middleware("http")
async def add_security_and_csrf_headers(request: Request, call_next):
    # CSRF check for state-changing HTTP requests when origin is supplied
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        path = request.url.path
        if not path.startswith("/webhooks") and not path.startswith("/api/health"):
            origin = request.headers.get("origin") or request.headers.get("referer")
            if origin and settings.environment.lower() == "production":
                parsed_origin = urlparse(origin)
                origin_str = f"{parsed_origin.scheme}://{parsed_origin.netloc}".rstrip("/")
                if origin_str not in allowed_origins:
                    return JSONResponse(
                        status_code=403,
                        content={"detail": "CSRF verification failed: Invalid request origin."},
                    )

    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if settings.environment.lower() == "production":
        response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains; preload"
    return response


app.add_middleware(
    CORSMiddleware,
    allow_origins=sorted(allowed_origins),
    allow_origin_regex=allow_origin_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error("Unhandled exception occurred during request handling", exc_info=exc)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal Server Error"},
    )


app.include_router(health.router)
app.include_router(auth_session.router, prefix="/api/auth", tags=["auth"])
app.include_router(suppliers.router, prefix="/api/suppliers", tags=["suppliers"])
app.include_router(catalogs.router, prefix="/api/catalogs", tags=["catalogs"])
app.include_router(ingestion.router, prefix="/api/ingestion", tags=["ingestion"])
app.include_router(chat.router)
app.include_router(email_accounts.router, prefix="/api/email-accounts", tags=["email-accounts"])
app.include_router(admin.router, prefix="/api/admin", tags=["admin"])
app.include_router(superadmin.router, prefix="/api/superadmin", tags=["superadmin"])
app.include_router(webhooks.router, prefix="/webhooks", tags=["webhooks"])
