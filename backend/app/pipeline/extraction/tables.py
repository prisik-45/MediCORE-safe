"""Table extractor using img2table without deep learning or Hugging Face dependencies.

Owned by: pipeline/extraction/tables.py
"""

import io
import logging
import fitz
from PIL import Image

from backend.app.pipeline.normalization.schema import ExtractedBlock

logger = logging.getLogger(__name__)


def extract_tables_from_image(image: Image.Image) -> list[ExtractedBlock]:
    """Extract table structures from a PIL Image using img2table."""
    try:
        from img2table.document import Image as Img2TableImage

        buf = io.BytesIO()
        image.save(buf, format="PNG")
        buf.seek(0)

        doc = Img2TableImage(src=buf)
        tables = doc.extract_tables() or []

        blocks: list[ExtractedBlock] = []
        for idx, table in enumerate(tables, start=1):
            bbox = [
                float(getattr(table.bbox, "x1", 0)),
                float(getattr(table.bbox, "y1", 0)),
                float(getattr(table.bbox, "x2", 0)),
                float(getattr(table.bbox, "y2", 0)),
            ]
            df = getattr(table, "df", None)
            if df is not None and not df.empty:
                md_content = df.to_markdown(index=False)
            else:
                md_content = f"[TABLE {idx}]"

            blocks.append(
                ExtractedBlock(
                    type="table",
                    bbox=bbox,
                    content=md_content.strip(),
                    confidence=0.90,
                    engine="img2table",
                )
            )
        return blocks
    except Exception as err:
        logger.warning("img2table image table extraction failed: %s", err, exc_info=True)
        return []


def extract_tables_from_pdf_page(page: fitz.Page) -> list[ExtractedBlock]:
    """Extract tables from a PyMuPDF page object using PyMuPDF native table finder or img2table."""
    blocks: list[ExtractedBlock] = []

    # 1. Try PyMuPDF native tabu/table finder first (fast, exact vector bounding box)
    try:
        tabs = page.find_tables()
        if tabs and tabs.tables:
            for idx, tab in enumerate(tabs.tables, start=1):
                bbox = list(tab.bbox)  # [x0, y0, x1, y1]
                df = tab.to_pandas()
                if df is not None and not df.empty:
                    md_text = df.to_markdown(index=False)
                else:
                    md_text = "\n".join(" | ".join(str(cell or "") for cell in row) for row in tab.extract())

                if md_text.strip():
                    blocks.append(
                        ExtractedBlock(
                            type="table",
                            bbox=bbox,
                            content=md_text.strip(),
                            confidence=0.95,
                            engine="pymupdf",
                        )
                    )
            if blocks:
                return blocks
    except Exception as err:
        logger.debug("PyMuPDF native find_tables failed or unsupported: %s", err)

    # 2. Fall back to img2table raster image extraction
    try:
        pix = page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0), alpha=False)
        img = Image.open(io.BytesIO(pix.tobytes("png")))
        return extract_tables_from_image(img)
    except Exception as err:
        logger.warning("PDF page table extraction failed: %s", err)
        return []
