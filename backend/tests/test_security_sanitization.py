from backend.app.services.sanitizer import (
    redact_pii,
    redact_sensitive_text,
    sanitize_preview_text,
    strip_email_boilerplate,
    wrap_llm_untrusted_content,
)


def test_redact_sensitive_text_masks_api_keys() -> None:
    text = "Here is my key: sk-abcdef1234567890abcdef1234567890 and Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
    redacted = redact_sensitive_text(text)
    assert "sk-" not in redacted
    assert "[REDACTED_API_KEY]" in redacted
    assert "[REDACTED_TOKEN]" in redacted


def test_redact_pii_masks_phone_numbers() -> None:
    text = "Call me at +1 (555) 123-4567 or +91 98765 43210 for catalog inquiries."
    redacted = redact_pii(text)
    assert "+1 (555)" not in redacted
    assert "[PHONE]" in redacted


def test_strip_email_boilerplate_cuts_off_history() -> None:
    email_text = (
        "Price of Paracetamol is $5/kg.\n\n"
        "Thanks and best regards,\n"
        "John Doe\n"
        "On Sun, Aug 15, 2026 at 10:00 AM supplier@example.com wrote:\n"
        "> Old quoted message history that should be discarded"
    )
    stripped = strip_email_boilerplate(email_text)
    assert "Price of Paracetamol is $5/kg." in stripped
    assert "Old quoted message" not in stripped


def test_sanitize_preview_text_bounds_length() -> None:
    long_text = "Catalog item " * 200
    preview = sanitize_preview_text(long_text, max_chars=100)
    assert preview is not None
    assert len(preview) <= 100


def test_wrap_llm_untrusted_content_adds_delimiters() -> None:
    content = "Vitamin C price $12/kg"
    wrapped = wrap_llm_untrusted_content(content)
    assert wrapped.startswith("<untrusted_supplier_data>")
    assert wrapped.endswith("</untrusted_supplier_data>")
    assert "Vitamin C price $12/kg" in wrapped
