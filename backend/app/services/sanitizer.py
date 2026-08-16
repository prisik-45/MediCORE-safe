"""Data sanitization and redaction utilities for previews, LLM prompts, and logs.

Protects against PII leakage, credential exposure, and prompt injection.
"""

import re

MAX_BODY_PREVIEW_CHARS = 500
MAX_LLM_INPUT_CHARS = 60_000

# Regex patterns for sensitive tokens and credentials
SECRET_PATTERNS = [
    (re.compile(r"(?i)\b(?:sk-[a-zA-Z0-9_-]{20,}|ghp_[a-zA-Z0-9]{20,}|xox[baprs]-[a-zA-Z0-9_-]{20,})\b"), "[REDACTED_API_KEY]"),
    (re.compile(r"(?i)\bBearer\s+[a-zA-Z0-9_\-\.]{20,}\b"), "Bearer [REDACTED_TOKEN]"),
    (re.compile(r"(?i)(?:password|passwd|secret|api[_-]?key)\s*[:=]\s*['\"]?([^\s'\"]+)['\"]?"), "[REDACTED_CREDENTIAL]"),
    (re.compile(r"\b(?:\d{4}[ -]?){3}\d{4}\b"), "[REDACTED_CARD]"),
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[REDACTED_SSN]"),
]

# Simple phone number pattern
PHONE_PATTERN = re.compile(r"(?:\+?\d{1,3}[-.\s]?)?\(?\d{2,4}\)?[-.\s]?\d{3,4}[-.\s]?\d{3,4}\b")


def redact_sensitive_text(text: str | None) -> str:
    """Mask credentials, API keys, and sensitive tokens in text."""
    if not text:
        return ""
    result = str(text)
    for pattern, replacement in SECRET_PATTERNS:
        result = pattern.sub(replacement, result)
    return result


def redact_pii(text: str | None) -> str:
    """Mask phone numbers and secrets in user-facing previews."""
    if not text:
        return ""
    cleaned = redact_sensitive_text(text)
    cleaned = PHONE_PATTERN.sub("[PHONE]", cleaned)
    return cleaned


def strip_email_boilerplate(text: str | None) -> str:
    """Remove signatures, quoted reply threads, and common disclaimers."""
    if not text:
        return ""
    cleaned = str(text)

    # Cut off quoted reply threads
    cleaned = re.split(
        r"(?im)^\s*(?:On .+ wrote:|From:.+|-----Original Message-----|_{5,}|-{5,}|Forwarded message)\s*$",
        cleaned,
        maxsplit=1,
    )[0]

    # Cut off common email signatures
    cleaned = re.split(
        r"(?im)^\s*(?:(?:thanks|thank you|regards)\s*[,.!]*|(?:best regards|kind regards|warm regards|sent from my)\b.*)$",
        cleaned,
        maxsplit=1,
    )[0]

    return cleaned.strip()


def sanitize_preview_text(text: str | None, max_chars: int = MAX_BODY_PREVIEW_CHARS) -> str | None:
    """Return a compact, redacted email body preview."""
    if not text:
        return None
    cleaned = strip_email_boilerplate(text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if not cleaned:
        return None
    cleaned = redact_pii(cleaned)
    return cleaned[:max_chars].strip() if cleaned else None


def wrap_llm_untrusted_content(text: str | None, max_chars: int = MAX_LLM_INPUT_CHARS) -> str:
    """Sanitize and encapsulate untrusted document text in data isolation boundaries."""
    if not text:
        return "<untrusted_supplier_data>\n(empty)\n</untrusted_supplier_data>"
    sanitized = redact_sensitive_text(text)
    if len(sanitized) > max_chars:
        sanitized = sanitized[:max_chars] + "\n...[truncated for extraction budget]..."
    return f"<untrusted_supplier_data>\n{sanitized}\n</untrusted_supplier_data>"
