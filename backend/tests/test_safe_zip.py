import io
import zipfile
import pytest

from backend.app.pipeline.ingestion.safe_zip import (
    SafeZipBombError,
    SafeZipTraversalError,
    inspect_and_validate_zip,
)


def test_inspect_and_validate_zip_accepts_valid_archive() -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("word/document.xml", "<w:document></w:document>")
        zf.writestr("word/media/image1.png", b"\x89PNG\r\n\x1a\n")
    
    buf.seek(0)
    # Should not raise
    inspect_and_validate_zip(buf)


def test_inspect_and_validate_zip_rejects_path_traversal() -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("../../etc/passwd", "root:x:0:0")
    
    buf.seek(0)
    with pytest.raises(SafeZipTraversalError, match="path traversal"):
        inspect_and_validate_zip(buf)


def test_inspect_and_validate_zip_rejects_excessive_entries() -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for i in range(15):
            zf.writestr(f"file_{i}.txt", "content")
    
    buf.seek(0)
    with pytest.raises(SafeZipBombError, match="entries, exceeding limit"):
        inspect_and_validate_zip(buf, max_entries=10)


def test_inspect_and_validate_zip_rejects_huge_uncompressed_size() -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("huge.txt", b"A" * (2 * 1024 * 1024))
    
    buf.seek(0)
    with pytest.raises(SafeZipBombError, match="exceeds limit"):
        inspect_and_validate_zip(buf, max_single_bytes=1024 * 1024)
