from backend.app.file_validator import (
    sanitize_filename,
    sniff_magic_type,
    validate_document_bytes,
)


def test_sanitize_filename_prevents_traversal() -> None:
    assert sanitize_filename("../../secret.pdf") == "secret.pdf"
    assert sanitize_filename("..\\..\\secret.pdf") == "secret.pdf"
    assert sanitize_filename("safe_file.pdf") == "safe_file.pdf"
    assert sanitize_filename("file with spaces & symbols!@#.png") == "file_with_spaces___symbols___.png"
    assert sanitize_filename("") == "document.pdf"
    assert sanitize_filename(None) == "document.pdf"


def test_sniff_magic_type_identifies_valid_headers() -> None:
    pdf_bytes = b"%PDF-1.4 header content"
    png_bytes = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
    jpeg_bytes = b"\xff\xd8\xff\xe0\x00\x10JFIF"
    zip_bytes = b"PK\x03\x04\x14\x00\x00\x00"

    assert sniff_magic_type(pdf_bytes) == "application/pdf"
    assert sniff_magic_type(png_bytes) == "image/png"
    assert sniff_magic_type(jpeg_bytes) == "image/jpeg"
    assert sniff_magic_type(zip_bytes) == "application/zip"


def test_validate_document_bytes_accepts_valid_pdf() -> None:
    pdf_data = b"%PDF-1.7 valid pdf stream"
    valid, mime, err = validate_document_bytes(pdf_data, "catalog.pdf")
    assert valid is True
    assert mime == "application/pdf"
    assert err is None


def test_validate_document_bytes_rejects_mismatched_magic_bytes() -> None:
    fake_pdf = b"This is plain text claiming to be a PDF"
    valid, mime, err = validate_document_bytes(fake_pdf, "invoice.pdf")
    assert valid is False
    assert "missing '%PDF-'" in err


def test_validate_document_bytes_rejects_dangerous_executables() -> None:
    exe_data = b"MZ\x90\x00\x03\x00\x00\x00\x04\x00\x00\x00"
    valid, mime, err = validate_document_bytes(exe_data, "payload.pdf")
    assert valid is False
    assert "prohibited signature" in err.lower()

    elf_data = b"\x7fELF\x02\x01\x01\x00"
    valid, mime, err = validate_document_bytes(elf_data, "binary.pdf")
    assert valid is False
    assert "prohibited signature" in err.lower()


def test_validate_document_bytes_enforces_size_limits() -> None:
    large_data = b"%PDF-" + b"0" * 1000
    valid, mime, err = validate_document_bytes(large_data, "test.pdf", max_bytes=500)
    assert valid is False
    assert "exceeds maximum limit" in err


def test_validate_document_bytes_enforces_allowed_extensions() -> None:
    png_data = b"\x89PNG\r\n\x1a\n\x00"
    valid, mime, err = validate_document_bytes(
        png_data,
        "image.png",
        allowed_extensions={".pdf"},
    )
    assert valid is False
    assert "not permitted in this context" in err
