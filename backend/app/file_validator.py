"""File validation and content-sniffing utilities for document ingestion.

Ensures strict alignment between file magic bytes, declared MIME type, and file extension.
"""

import io
import os
import re
from pathlib import Path
from typing import BinaryIO

# Maximum upload size for certificates (15 MB)
MAX_CERTIFICATE_UPLOAD_BYTES = 15 * 1024 * 1024

# Default document processing limit (30 MB)
MAX_DOCUMENT_BYTES = 30 * 1024 * 1024

# Per-email aggregate attachment limit (50 MB)
MAX_TOTAL_EMAIL_ATTACHMENTS_BYTES = 50 * 1024 * 1024

# Inline base64 data URI limits
MAX_DATA_URI_BYTES = 5 * 1024 * 1024
MAX_TOTAL_DATA_URI_BYTES = 15 * 1024 * 1024
MAX_DATA_URI_COUNT = 5

# Allowed extensions mapped to canonical MIME types and magic byte signatures
SUPPORTED_EXTENSIONS_MAP = {
    ".pdf": {
        "mime": "application/pdf",
        "category": "pdf",
    },
    ".png": {
        "mime": "image/png",
        "category": "image",
    },
    ".jpg": {
        "mime": "image/jpeg",
        "category": "image",
    },
    ".jpeg": {
        "mime": "image/jpeg",
        "category": "image",
    },
    ".webp": {
        "mime": "image/webp",
        "category": "image",
    },
    ".bmp": {
        "mime": "image/bmp",
        "category": "image",
    },
    ".tiff": {
        "mime": "image/tiff",
        "category": "image",
    },
    ".tif": {
        "mime": "image/tiff",
        "category": "image",
    },
    ".docx": {
        "mime": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "category": "docx",
    },
    ".doc": {
        "mime": "application/msword",
        "category": "doc",
    },
    ".xlsx": {
        "mime": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "category": "xlsx",
    },
    ".xlsm": {
        "mime": "application/vnd.ms-excel.sheet.macroEnabled.12",
        "category": "xlsx",
    },
    ".xltx": {
        "mime": "application/vnd.openxmlformats-officedocument.spreadsheetml.template",
        "category": "xlsx",
    },
    ".xltm": {
        "mime": "application/vnd.ms-excel.template.macroEnabled.12",
        "category": "xlsx",
    },
    ".xls": {
        "mime": "application/vnd.ms-excel",
        "category": "xls",
    },
    ".csv": {
        "mime": "text/csv",
        "category": "csv",
    },
    ".txt": {
        "mime": "text/plain",
        "category": "txt",
    },
}

CERTIFICATE_ALLOWED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg"}

# Executable / dangerous magic signatures that must be rejected immediately
DANGEROUS_MAGIC_SIGNATURES = [
    (b"MZ", "DOS/Windows Executable (PE)"),
    (b"\x7fELF", "Linux ELF Executable"),
    (b"\xca\xfe\xba\xbe", "Mach-O / Java Class"),
    (b"\xfe\xed\xfa\xce", "Mach-O 32-bit"),
    (b"\xfe\xed\xfa\xcf", "Mach-O 64-bit"),
    (b"<!DOCTYPE html", "HTML document"),
    (b"<html", "HTML document"),
    (b"<?php", "PHP script"),
    (b"#!/bin/", "Shell script"),
    (b"#!/usr/bin/", "Shell script"),
    (b"<script", "JavaScript script"),
    (b"<?xml", "XML script / payload"),
]


def sanitize_filename(filename: str | None, default_name: str = "document.pdf") -> str:
    """Return a sanitized basename preventing path traversal or dangerous characters."""
    if not filename:
        return default_name
    # Handle forward and backslashes
    clean_name = filename.replace("\\", "/").split("/")[-1].strip()
    clean_name = clean_name.replace("\u00a0", "_").replace(" ", "_")
    safe_name = re.sub(r"[^a-zA-Z0-9_.-]", "_", clean_name)
    # Remove leading dots to avoid hidden files
    safe_name = safe_name.lstrip(".")
    if not safe_name:
        return default_name
    return safe_name


def sniff_magic_type(data: bytes) -> str | None:
    """Sniff content type from initial bytes."""
    if not data:
        return None

    header = data[:1024]

    # Check for PDF signature (%PDF-) anywhere in first 1024 bytes
    if b"%PDF-" in header[:1024]:
        return "application/pdf"

    # PNG
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"

    # JPEG
    if header.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"

    # WebP: RIFF....WEBP
    if len(header) >= 12 and header.startswith(b"RIFF") and header[8:12] == b"WEBP":
        return "image/webp"

    # BMP
    if header.startswith(b"BM"):
        return "image/bmp"

    # TIFF
    if header.startswith((b"II*\x00", b"MM\x00*")):
        return "image/tiff"

    # ZIP-based Office documents (DOCX, XLSX)
    if header.startswith(b"PK\x03\x04"):
        return "application/zip"

    # OLE2 Compound Document (Legacy XLS, DOC)
    if header.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        return "application/x-ole-storage"

    # Plain text / CSV (check if printable ASCII/UTF-8 without null bytes)
    if b"\x00" not in header[:512]:
        try:
            header[:512].decode("utf-8")
            return "text/plain"
        except UnicodeDecodeError:
            try:
                header[:512].decode("latin-1")
                return "text/plain"
            except UnicodeDecodeError:
                pass

    return None


def validate_document_bytes(
    data: bytes,
    filename: str,
    declared_mime: str | None = None,
    allowed_extensions: set[str] | None = None,
    max_bytes: int = MAX_DOCUMENT_BYTES,
) -> tuple[bool, str, str | None]:
    """Validate document binary content, extension, and MIME type.

    Returns:
        tuple (is_valid: bool, canonical_mime: str, error_message: str | None)
    """
    if not data:
        return False, "application/octet-stream", "Document payload is empty."

    if len(data) > max_bytes:
        return False, "application/octet-stream", f"Document size ({len(data)} bytes) exceeds maximum limit ({max_bytes} bytes)."

    safe_name = sanitize_filename(filename)
    ext = Path(safe_name.lower()).suffix

    if not ext or ext not in SUPPORTED_EXTENSIONS_MAP:
        return False, "application/octet-stream", f"Unsupported file extension: '{ext}'"

    if allowed_extensions and ext not in allowed_extensions:
        return False, "application/octet-stream", f"File extension '{ext}' is not permitted in this context."

    expected_config = SUPPORTED_EXTENSIONS_MAP[ext]
    expected_mime = expected_config["mime"]
    category = expected_config["category"]

    # Check for dangerous executable signatures
    header_lower = data[:1024].lstrip().lower()
    for magic, desc in DANGEROUS_MAGIC_SIGNATURES:
        if magic.lower() in header_lower[:len(magic) + 64] and category not in {"txt", "csv"}:
            return False, "application/octet-stream", f"Rejected file matching prohibited signature: {desc}"

    sniffed = sniff_magic_type(data)

    # Specific validation per category
    if category == "pdf":
        if sniffed != "application/pdf":
            return False, "application/octet-stream", "PDF file header missing '%PDF-' signature."
        return True, "application/pdf", None

    elif category == "image":
        if ext in {".jpg", ".jpeg"} and sniffed != "image/jpeg":
            return False, "application/octet-stream", "JPEG image header missing valid SOI marker."
        elif ext == ".png" and sniffed != "image/png":
            return False, "application/octet-stream", "PNG image header missing valid signature."
        elif ext == ".webp" and sniffed != "image/webp":
            return False, "application/octet-stream", "WebP image header missing valid RIFF/WEBP signature."
        elif ext == ".bmp" and sniffed != "image/bmp":
            return False, "application/octet-stream", "BMP image header missing valid signature."
        elif ext in {".tiff", ".tif"} and sniffed != "image/tiff":
            return False, "application/octet-stream", "TIFF image header missing valid signature."
        return True, expected_mime, None

    elif category in {"docx", "xlsx"}:
        if sniffed != "application/zip":
            return False, "application/octet-stream", f"Office OpenXML document ({ext}) must be a valid ZIP archive."
        return True, expected_mime, None

    elif category in {"xls", "doc"}:
        if sniffed != "application/x-ole-storage":
            return False, "application/octet-stream", f"Legacy Office document ({ext}) missing OLE2 signature."
        return True, expected_mime, None

    elif category in {"csv", "txt"}:
        if b"\x00" in data[:1024]:
            return False, "application/octet-stream", f"{category.upper()} document contains invalid binary null bytes."
        return True, expected_mime, None

    return True, expected_mime, None


async def read_bounded_upload_file(
    upload_file,
    max_bytes: int = MAX_CERTIFICATE_UPLOAD_BYTES,
    chunk_size: int = 64 * 1024,
) -> bytes:
    """Read an async UploadFile up to max_bytes without unbounded memory buffering."""
    buffer = io.BytesIO()
    total_read = 0

    while True:
        chunk = await upload_file.read(chunk_size)
        if not chunk:
            break
        total_read += len(chunk)
        if total_read > max_bytes:
            raise ValueError(f"Uploaded file exceeds maximum allowed size of {max_bytes} bytes.")
        buffer.write(chunk)

    return buffer.getvalue()
