"""Unified extraction budget and resource limits for document parsing and OCR.

Prevents denial-of-service, CPU/memory exhaustion, and unbounded resource consumption across
PDF, image, Office (DOCX/XLSX), CSV, OCR, and LLM extraction pipelines.
"""

from dataclasses import dataclass, field
import logging

logger = logging.getLogger(__name__)


@dataclass
class ExtractionBudget:
    # Page and Image Rendering Limits
    max_pdf_pages: int = 50
    max_pixels_per_page: int = 25_000_000      # ~5000 x 5000 px
    max_total_rendered_pixels: int = 80_000_000
    
    # OCR Tiling and Embedded Image Limits
    max_ocr_tiles_per_page: int = 4
    max_ocr_tiles_per_document: int = 30
    max_embedded_images: int = 15
    
    # Spreadsheet (XLSX / CSV) Limits
    max_sheets: int = 10
    max_rows_per_sheet: int = 5_000
    max_cols_per_sheet: int = 50
    max_total_cells: int = 50_000
    
    # Output and Context Limits
    max_extracted_text_chars: int = 150_000
    max_llm_input_chars: int = 60_000
    
    # Runtime Tracking
    consumed_pages: int = 0
    consumed_pixels: int = 0
    consumed_ocr_tiles: int = 0
    consumed_embedded_images: int = 0
    consumed_cells: int = 0
    consumed_text_chars: int = 0
    
    is_exhausted: bool = False
    exhaustion_reasons: list[str] = field(default_factory=list)

    def can_process_page(self) -> bool:
        if self.consumed_pages >= self.max_pdf_pages:
            self._record_exhaustion(f"Reached maximum page limit ({self.max_pdf_pages} pages)")
            return False
        return True

    def record_page_processed(self) -> None:
        self.consumed_pages += 1

    def can_render_pixels(self, pixel_count: int) -> bool:
        if pixel_count > self.max_pixels_per_page:
            self._record_exhaustion(f"Page image ({pixel_count} pixels) exceeds max per-page pixel limit ({self.max_pixels_per_page})")
            return False
        if self.consumed_pixels + pixel_count > self.max_total_rendered_pixels:
            self._record_exhaustion(f"Total rendered pixels ({self.consumed_pixels + pixel_count}) exceeds max budget ({self.max_total_rendered_pixels})")
            return False
        return True

    def record_pixels_rendered(self, pixel_count: int) -> None:
        self.consumed_pixels += pixel_count

    def can_process_ocr_tile(self) -> bool:
        if self.consumed_ocr_tiles >= self.max_ocr_tiles_per_document:
            self._record_exhaustion(f"Reached max OCR tile budget ({self.max_ocr_tiles_per_document} tiles)")
            return False
        return True

    def record_ocr_tile_processed(self) -> None:
        self.consumed_ocr_tiles += 1

    def can_process_embedded_image(self) -> bool:
        if self.consumed_embedded_images >= self.max_embedded_images:
            self._record_exhaustion(f"Reached max embedded image budget ({self.max_embedded_images} images)")
            return False
        return True

    def record_embedded_image_processed(self) -> None:
        self.consumed_embedded_images += 1

    def can_process_sheet(self, sheet_index_1indexed: int) -> bool:
        if sheet_index_1indexed > self.max_sheets:
            self._record_exhaustion(f"Reached max sheet limit ({self.max_sheets} sheets)")
            return False
        return True

    def can_add_cells(self, count: int) -> bool:
        if self.consumed_cells + count > self.max_total_cells:
            self._record_exhaustion(f"Reached max cell count budget ({self.max_total_cells} cells)")
            return False
        return True

    def record_cells_processed(self, count: int) -> None:
        self.consumed_cells += count

    def append_text(self, current_text: str, new_text: str) -> str:
        available = self.max_extracted_text_chars - len(current_text)
        if available <= 0:
            self._record_exhaustion(f"Reached maximum extracted text character budget ({self.max_extracted_text_chars} chars)")
            return current_text
        if len(new_text) > available:
            self._record_exhaustion(f"Extracted text truncated to budget ({self.max_extracted_text_chars} chars)")
            return current_text + new_text[:available]
        return current_text + new_text

    def _record_exhaustion(self, reason: str) -> None:
        if reason not in self.exhaustion_reasons:
            self.exhaustion_reasons.append(reason)
            logger.warning("Extraction budget exhausted: %s", reason)
        self.is_exhausted = True
