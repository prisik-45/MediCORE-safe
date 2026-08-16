import logging

logging.basicConfig(level=logging.INFO)

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from backend.app.api import catalogs, chat, health, ingestion, suppliers, webhooks, email_accounts, admin, superadmin
from backend.app.config import get_settings


settings = get_settings()

allowed_origins = {
    settings.frontend_origin,
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

app = FastAPI(title=settings.app_name, version="0.1.0")


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
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

logger = logging.getLogger(__name__)

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error("Unhandled exception occurred during request handling", exc_info=exc)
    return JSONResponse(
        status_code=500,
        content={
            "detail": "Internal Server Error"
        }
    )


app.include_router(health.router)
app.include_router(suppliers.router, prefix="/api/suppliers", tags=["suppliers"])
app.include_router(catalogs.router, prefix="/api/catalogs", tags=["catalogs"])
app.include_router(ingestion.router, prefix="/api/ingestion", tags=["ingestion"])
app.include_router(chat.router)
app.include_router(email_accounts.router, prefix="/api/email-accounts", tags=["email-accounts"])
app.include_router(admin.router, prefix="/api/admin", tags=["admin"])
app.include_router(superadmin.router, prefix="/api/superadmin", tags=["superadmin"])
app.include_router(webhooks.router, prefix="/webhooks", tags=["webhooks"])
