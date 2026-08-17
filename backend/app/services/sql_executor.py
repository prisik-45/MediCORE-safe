import re
import logging
from typing import Any
from uuid import UUID
from sqlalchemy import text
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger(__name__)

FORBIDDEN_SQL_KEYWORDS = {
    "INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "TRUNCATE", "CREATE",
    "GRANT", "REVOKE", "EXEC", "EXECUTE", "PG_SLEEP", "INTO", "COPY",
    "VACUUM", "REINDEX", "COMMENT", "RENAME", "SET", "RESET", "LOCK",
    "UNION", "INTERSECT", "EXCEPT", "MERGE", "CALL", "DO"
}

ALLOWED_SQL_TABLES = {"catalog_items", "catalog_emails", "suppliers"}

DISALLOWED_SQL_IDENTIFIERS = {
    "auth", "users", "profiles", "employee_invitations", "password_resets",
    "email_accounts", "email_filters", "email_sync_settings", "ai_query_logs",
    "pg_catalog", "information_schema", "pg_stat_activity", "pg_shadow",
    "pg_authid", "pg_roles", "storage", "vault"
}

SENSITIVE_SQL_COLUMNS = {
    "token", "password", "encrypted_password", "service_role", "secret",
    "api_key", "access_token", "refresh_token", "query_text"
}

SAFE_SQL_FUNCTIONS = {
    "avg", "coalesce", "count", "date_trunc", "lower", "max", "min",
    "nullif", "round", "sum", "upper"
}

SQL_CLAUSE_KEYWORDS = {
    "where", "join", "left", "right", "inner", "outer", "full", "cross",
    "on", "group", "order", "limit", "offset", "having", "window"
}


def _strip_sql_comments(sql_query: str) -> str:
    no_comments = re.sub(r"--.*$", "", sql_query, flags=re.MULTILINE)
    return re.sub(r"/\*.*?\*/", "", no_comments, flags=re.DOTALL).strip().rstrip(";")


def _normalize_identifier(identifier: str) -> str:
    cleaned = identifier.strip().strip('"').lower()
    if cleaned.startswith("public."):
        cleaned = cleaned.split(".", 1)[1]
    return cleaned.strip('"')


def _table_references(sql_query: str) -> list[tuple[str, str]]:
    references: list[tuple[str, str]] = []
    pattern = re.compile(
        r"\b(?:from|join)\s+((?:public\.)?[a-z_][a-z0-9_]*)(?:\s+(?:as\s+)?([a-z_][a-z0-9_]*))?",
        flags=re.IGNORECASE,
    )
    for match in pattern.finditer(sql_query):
        table = _normalize_identifier(match.group(1))
        alias = (match.group(2) or "").strip().lower()
        if alias in SQL_CLAUSE_KEYWORDS:
            alias = ""
        references.append((table, alias or table))
    return references


def _validate_safe_function_calls(sql_query: str) -> None:
    for function_name in re.findall(r"\b([a-z_][a-z0-9_]*)\s*\(", sql_query, flags=re.IGNORECASE):
        normalized = function_name.lower()
        if normalized in {"select", "from", "where", "and", "or", "case", "when", "then"}:
            continue
        if normalized not in SAFE_SQL_FUNCTIONS:
            raise ValueError(f"SQL function '{normalized}' is not permitted.")


def _validate_allowed_tables(sql_query: str) -> list[tuple[str, str]]:
    from_match = re.search(r"\bfrom\b(.+?)(?:\bwhere\b|\bgroup\b|\border\b|\blimit\b|$)", sql_query, flags=re.IGNORECASE | re.DOTALL)
    if from_match and "," in from_match.group(1):
        raise ValueError("Implicit comma joins are not permitted in AI SQL.")

    references = _table_references(sql_query)
    if not references:
        raise ValueError("Query must read from an allowed catalogue table.")

    for table, _alias in references:
        if table not in ALLOWED_SQL_TABLES:
            raise ValueError(f"Table '{table}' is not permitted for AI SQL.")
    return references


def _validate_tenant_scope(sql_query: str, references: list[tuple[str, str]]) -> None:
    unique_aliases = list(dict.fromkeys(alias for _table, alias in references))
    for alias in unique_aliases:
        escaped_alias = re.escape(alias)
        scoped = re.search(
            rf"\b{escaped_alias}\.tenant_id\b\s*=\s*:tenant_id\b|:tenant_id\b\s*=\s*\b{escaped_alias}\.tenant_id\b",
            sql_query,
            flags=re.IGNORECASE,
        )
        if scoped:
            continue

        if len(unique_aliases) == 1 and re.search(
            r"\btenant_id\b\s*=\s*:tenant_id\b|:tenant_id\b\s*=\s*\btenant_id\b",
            sql_query,
            flags=re.IGNORECASE,
        ):
            continue

        raise ValueError(f"Tenant predicate for table alias '{alias}' is required.")


def _enforce_limit(sql_query: str, max_limit: int = 100) -> str:
    limit_match = re.search(r"\blimit\s+(\d+)\b", sql_query, flags=re.IGNORECASE)
    if not limit_match:
        return f"{sql_query} LIMIT {max_limit}"
    requested_limit = int(limit_match.group(1))
    if requested_limit <= max_limit:
        return sql_query
    return (
        sql_query[: limit_match.start(1)]
        + str(max_limit)
        + sql_query[limit_match.end(1) :]
    )


def validate_readonly_sql(sql_query: str, require_tenant: bool = False) -> str:
    """
    Validates LLM-generated SQL as a single catalogue-only, read-only SELECT.
    Raises ValueError if the query can read outside the allowlist or bypass tenant scope.
    """
    raw = (sql_query or "").strip()
    if not raw:
        raise ValueError("Empty SQL query provided.")

    no_comments = _strip_sql_comments(raw)

    if ";" in no_comments:
        raise ValueError("Multiple SQL statements separated by semicolons are not permitted.")

    first_word = no_comments.split()[0].upper() if no_comments else ""
    if first_word != "SELECT":
        raise ValueError(f"Only SELECT read-only queries are permitted. Query started with '{first_word}'.")

    if re.search(r"\(\s*select\b|\bwith\b", no_comments, flags=re.IGNORECASE):
        raise ValueError("Subqueries and CTEs are not permitted in AI SQL.")

    tokens = set(re.findall(r"\b[A-Za-z_]+\b", no_comments.upper()))
    forbidden_found = tokens.intersection(FORBIDDEN_SQL_KEYWORDS)
    if forbidden_found:
        raise ValueError(f"Forbidden SQL operation detected: {', '.join(sorted(forbidden_found))}.")

    normalized_tokens = {token.lower() for token in tokens}
    identifier_hits = normalized_tokens.intersection(DISALLOWED_SQL_IDENTIFIERS)
    if identifier_hits:
        raise ValueError(f"Disallowed SQL identifier detected: {', '.join(sorted(identifier_hits))}.")

    sensitive_hits = normalized_tokens.intersection(SENSITIVE_SQL_COLUMNS)
    if sensitive_hits:
        raise ValueError(f"Sensitive SQL column detected: {', '.join(sorted(sensitive_hits))}.")

    star_safe_sql = re.sub(r"\bcount\s*\(\s*\*\s*\)", "count(1)", no_comments, flags=re.IGNORECASE)
    if "*" in star_safe_sql:
        raise ValueError("Wildcard SELECT output is not permitted.")

    _validate_safe_function_calls(no_comments)
    references = _validate_allowed_tables(no_comments)
    if require_tenant:
        _validate_tenant_scope(no_comments, references)

    return _enforce_limit(no_comments)


def execute_readonly_sql(
    db: Session,
    sql_query: str,
    tenant_id: UUID | str | None = None
) -> list[dict[str, Any]]:
    """
    Validates and executes a read-only SQL query against Supabase Cloud Postgres.
    Enforces tenant isolation if tenant_id is provided.
    Returns list of dict rows.
    """
    try:
        validated_sql = validate_readonly_sql(sql_query, require_tenant=bool(tenant_id))
    except ValueError as err:
        logger.warning("SQL validation rejected AI-generated query. Error: %s", err)
        return []

    params: dict[str, Any] = {}
    if tenant_id:
        tenant_str = str(tenant_id)
        params["tenant_id"] = tenant_str

    execution_db = db
    readonly_db: Session | None = None
    readonly_db_configured = False
    try:
        try:
            from backend.app.db import ai_readonly_database_url_configured, get_ai_readonly_session

            readonly_db_configured = ai_readonly_database_url_configured()
            readonly_db = get_ai_readonly_session()
            if readonly_db is not None:
                execution_db = readonly_db
        except Exception as err:
            if readonly_db_configured:
                logger.error("AI read-only DB is configured but unavailable; refusing AI SQL: %s", err)
                return []
            logger.warning("AI read-only DB is not configured; using request DB session with SQL allowlist guard.")

        result = execution_db.execute(text(validated_sql), params)
        if result.returns_rows:
            columns = list(result.keys())
            return [dict(zip(columns, row)) for row in result.fetchall()]
        return []
    except SQLAlchemyError as err:
        logger.error("Failed to execute read-only AI SQL. Error: %s", err)
        return []
    finally:
        if readonly_db is not None:
            readonly_db.close()
