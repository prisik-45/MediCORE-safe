from collections.abc import Iterator
import logging
import urllib.parse

from sqlalchemy import URL, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from supabase import Client, create_client

from backend.app.config import get_settings


settings = get_settings()
DEFAULT_DATABASE_URL = "postgresql+psycopg://postgres:postgres@localhost:5432/postgres"
logger = logging.getLogger(__name__)


def repair_database_url(url: str) -> str:
    url = url.strip()
    if not url:
        return url

    scheme = "postgresql+psycopg"
    if url.startswith("postgresql+psycopg://"):
        url_payload = url[len("postgresql+psycopg://"):]
    elif url.startswith("postgresql://"):
        url_payload = url[len("postgresql://"):]
    elif url.startswith("postgres://"):
        url_payload = url[len("postgres://"):]
    else:
        return url

    if "@" not in url_payload:
        return f"{scheme}://{url_payload}"

    creds, conn = url_payload.rsplit("@", 1)
    if ":" in creds:
        user, password = creds.split(":", 1)
        decoded = urllib.parse.unquote(password)
        password = urllib.parse.quote_plus(decoded)
        creds = f"{user}:{password}"

    return f"{scheme}://{creds}@{conn}"


def build_pooler_url() -> URL | None:
    if (
        not settings.supabase_pooler_host
        or not settings.supabase_db_password
        or not (settings.supabase_pooler_user or settings.supabase_db_user)
    ):
        return None

    return URL.create(
        "postgresql+psycopg",
        username=settings.supabase_pooler_user or settings.supabase_db_user,
        password=settings.supabase_db_password,
        host=settings.supabase_pooler_host,
        port=settings.supabase_pooler_port,
        database=settings.supabase_db_name,
    )


def is_direct_supabase_url(url: str) -> bool:
    return ".supabase.co:5432" in url and "pooler.supabase.com" not in url


def has_explicit_database_url(url: str) -> bool:
    return bool(url.strip()) and repair_database_url(url) != DEFAULT_DATABASE_URL


def build_database_url() -> URL | str:
    raw_url = settings.database_url.strip()
    pooler_url = build_pooler_url()

    # Supabase direct hosts can resolve to IPv6-only addresses inside containers.
    # When the pooler is configured, prefer it over any direct Supabase URL.
    if has_explicit_database_url(raw_url) and not (
        pooler_url is not None and is_direct_supabase_url(raw_url)
    ):
        return repair_database_url(raw_url)

    if pooler_url is not None:
        return pooler_url

    if settings.supabase_db_host and settings.supabase_db_password:
        return URL.create(
            "postgresql+psycopg",
            username=settings.supabase_db_user,
            password=settings.supabase_db_password,
            host=settings.supabase_db_host,
            port=settings.supabase_db_port,
            database=settings.supabase_db_name,
        )

    return repair_database_url(raw_url)


def database_url_summary() -> str:
    url = build_database_url()
    if isinstance(url, URL):
        return f"{url.host}:{url.port or 'default'}/{url.database}"

    parsed = urllib.parse.urlparse(str(url))
    return f"{parsed.hostname}:{parsed.port or 'default'}{parsed.path or ''}"


def is_supabase_transaction_pooler(url: URL | str) -> bool:
    if isinstance(url, URL):
        host = str(url.host or "").lower()
        port = url.port
    else:
        parsed = urllib.parse.urlparse(str(url))
        host = str(parsed.hostname or "").lower()
        port = parsed.port
    return host.endswith(".pooler.supabase.com") and port == 6543


def database_connect_args(url: URL | str) -> dict:
    connect_args: dict = {"sslmode": "require"}
    if is_supabase_transaction_pooler(url):
        # Transaction pooling can route consecutive transactions to different
        # PostgreSQL sessions, where Psycopg's named prepared statement is absent.
        connect_args["prepare_threshold"] = None
    return connect_args



def create_app_engine():
    try:
        database_url = build_database_url()
        logger.info("Using database host: %s", database_url_summary())
        return create_engine(
            database_url,
            pool_pre_ping=True,
            connect_args=database_connect_args(database_url),
        )
    except Exception:
        if settings.environment == "production":
            raise
        return create_engine("sqlite+pysqlite:///:memory:")


_engine = None
_SessionLocal = None
_ai_readonly_engine = None
_AIReadOnlySessionLocal = None
startup_error = None

try:
    _engine = create_app_engine()
    _SessionLocal = sessionmaker(bind=_engine, autocommit=False, autoflush=False)
except Exception as e:
    startup_error = e

engine = _engine


def build_ai_readonly_database_url() -> str:
    return repair_database_url(getattr(settings, "ai_readonly_database_url", "").strip())


def ai_readonly_database_url_configured() -> bool:
    return bool(build_ai_readonly_database_url())


def get_ai_readonly_session() -> Session | None:
    global _ai_readonly_engine, _AIReadOnlySessionLocal

    ai_database_url = build_ai_readonly_database_url()
    if not ai_database_url:
        return None

    if _ai_readonly_engine is None:
        logger.info("Using dedicated AI read-only database connection")
        _ai_readonly_engine = create_engine(
            ai_database_url,
            pool_pre_ping=True,
            connect_args=database_connect_args(ai_database_url),
        )
        _AIReadOnlySessionLocal = sessionmaker(
            bind=_ai_readonly_engine,
            autocommit=False,
            autoflush=False,
        )

    return _AIReadOnlySessionLocal()


def SessionLocal(*args, **kwargs):
    if startup_error:
        raise RuntimeError(
            f"Database initialization failed at startup. Error: {startup_error}"
        ) from startup_error
    return _SessionLocal(*args, **kwargs)


class Base(DeclarativeBase):
    pass


def get_db() -> Iterator[Session]:
    if startup_error:
        raise RuntimeError(
            "Database connection failed due to startup error. "
            f"Please check DATABASE_URL or Supabase pooler variables. Details: {startup_error}"
        ) from startup_error

    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def close_database_engines() -> None:
    global _ai_readonly_engine
    if _engine is not None:
        _engine.dispose()
    if _ai_readonly_engine is not None:
        _ai_readonly_engine.dispose()
        _ai_readonly_engine = None


def get_supabase() -> Client:
    return create_client(str(settings.supabase_url), settings.supabase_service_role_key)


def ensure_supabase_storage_bucket(bucket_name: str | None = None) -> None:
    bucket = (bucket_name or settings.supabase_storage_bucket or "").strip()
    if not bucket:
        return

    supabase = get_supabase()
    try:
        supabase.storage.get_bucket(bucket)
        return
    except Exception as exc:
        message = str(exc).lower()
        if not any(term in message for term in ("not found", "nosuchbucket", "no such bucket", "404")):
            logger.warning("Could not verify Supabase storage bucket %s before upload: %s", bucket, exc)

    try:
        supabase.storage.create_bucket(
            bucket,
            options={
                "public": False,
                "file_size_limit": "52428800",
                "allowed_mime_types": [
                    "application/pdf",
                    "text/plain",
                    "text/csv",
                    "application/vnd.ms-excel",
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    "application/msword",
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    "image/png",
                    "image/jpeg",
                    "image/webp",
                    "image/bmp",
                    "image/tiff",
                ],
            },
        )
        logger.info("Created Supabase storage bucket %s", bucket)
    except Exception as exc:
        message = str(exc).lower()
        if any(term in message for term in ("already exists", "duplicate", "23505")):
            return
        raise
