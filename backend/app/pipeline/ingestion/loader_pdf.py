"""PDF file loader using PyMuPDF (fitz).

Owned by: pipeline/ingestion/loader_pdf.py
"""

import io
import logging
import math
from pathlib import Path
import fitz
from PIL import Image

# Accommodates unusually wide catalog pages while retaining a bounded raster size.
Image.MAX_IMAGE_PIXELS = 30_000_000
MAX_SAFE_PIXELS_PER_PAGE = 30_000_000
# PyMuPDF rounds raster dimensions to whole pixels, so leave headroom when
# converting the continuous PDF page dimensions into a render scale.
RENDER_SCALE_SAFETY_MARGIN = 0.999

logger = logging.getLogger(__name__)


class PDFDocumentWrapper:
    """Wrapper around PyMuPDF Document to keep file opening encapsulated in ingestion/."""

    def __init__(self, doc: fitz.Document, file_path: Path):
        self.doc = doc
        self.file_path = file_path
        self.page_count = len(doc)

    def get_page(self, page_num_1indexed: int) -> fitz.Page:
        return self.doc[page_num_1indexed - 1]

    def render_page_image(self, page_num_1indexed: int, target_dpi: int = 300) -> Image.Image:
        page = self.get_page(page_num_1indexed)
        scale = target_dpi / 72.0
        page_pixels_at_unit_scale = max(1.0, float(page.rect.width * page.rect.height))
        max_safe_scale = math.sqrt(MAX_SAFE_PIXELS_PER_PAGE / page_pixels_at_unit_scale)
        if scale > max_safe_scale:
            logger.warning(
                "PDF page %s render DPI reduced from %s to %.1f to stay under pixel safety limit",
                page_num_1indexed,
                target_dpi,
                max_safe_scale * RENDER_SCALE_SAFETY_MARGIN * 72.0,
            )
            scale = max_safe_scale * RENDER_SCALE_SAFETY_MARGIN

        # The page rectangle can contain fractional points whereas PyMuPDF's
        # output dimensions are integers. Adaptively retry if rounding still
        # places the bitmap over the cap.
        while True:
            matrix = fitz.Matrix(scale, scale)
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            rendered_pixels = pix.width * pix.height
            if rendered_pixels <= MAX_SAFE_PIXELS_PER_PAGE:
                break

            adjusted_scale = scale * math.sqrt(MAX_SAFE_PIXELS_PER_PAGE / rendered_pixels)
            scale = math.nextafter(adjusted_scale * RENDER_SCALE_SAFETY_MARGIN, 0.0)
            logger.warning(
                "PDF page %s render scale reduced further to %.1f DPI after pixel rounding",
                page_num_1indexed,
                scale * 72.0,
            )
        return Image.open(io.BytesIO(pix.tobytes("png")))

    def close(self) -> None:
        self.doc.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


def load_pdf(file_path: Path) -> PDFDocumentWrapper:
    """Open PDF file and return PDFDocumentWrapper."""
    doc = fitz.open(file_path)
    return PDFDocumentWrapper(doc, file_path)
