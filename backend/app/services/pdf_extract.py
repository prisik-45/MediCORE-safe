"""PDF text extraction service wrapping the document extraction pipeline.

Owned by: backend/app/services/pdf_extract.py
"""

import logging
from pathlib import Path

from backend.app.pipeline.pipeline import process_document

import tempfile
from types import SimpleNamespace

logger = logging.getLogger(__name__)


def extract_pdf_text(path: str | Path) -> str:
    """Extract text from a PDF file using the unified document extraction pipeline."""
    pdf_path = Path(path)
    if not pdf_path.is_file():
        logger.warning("PDF file not found: %s", pdf_path.name)
        return ""

    try:
        result = process_document(pdf_path)
        return result.full_text()
    except Exception as err:
        logger.error("Failed to extract text from PDF %s: %s", pdf_path.name, err, exc_info=True)
        return ""


def extract_pdf_document(source: bytes | str | Path) -> SimpleNamespace:
    """Extract PDF document from bytes or file path and return an object with full_text."""
    if isinstance(source, bytes):
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            tmp.write(source)
            tmp_path = Path(tmp.name)
        try:
            text = extract_pdf_text(tmp_path)
        finally:
            if tmp_path.exists():
                tmp_path.unlink()
        return SimpleNamespace(full_text=text)
    return SimpleNamespace(full_text=extract_pdf_text(source))
