import pytest
from backend.app.pipeline.budget import ExtractionBudget
from backend.app.pipeline.pipeline import process_document


def test_extraction_budget_tracks_pages() -> None:
    budget = ExtractionBudget(max_pdf_pages=3)
    assert budget.can_process_page() is True
    budget.record_page_processed()
    budget.record_page_processed()
    budget.record_page_processed()
    assert budget.can_process_page() is False
    assert budget.is_exhausted is True
    assert "page limit" in budget.exhaustion_reasons[0]


def test_extraction_budget_tracks_pixels() -> None:
    budget = ExtractionBudget(max_pixels_per_page=1000, max_total_rendered_pixels=2500)
    assert budget.can_render_pixels(800) is True
    budget.record_pixels_rendered(800)
    
    # Exceeds per-page limit
    assert budget.can_render_pixels(1500) is False
    
    # Exceeds total limit
    assert budget.can_render_pixels(1800) is False


def test_extraction_budget_tracks_ocr_tiles() -> None:
    budget = ExtractionBudget(max_ocr_tiles_per_document=2)
    assert budget.can_process_ocr_tile() is True
    budget.record_ocr_tile_processed()
    budget.record_ocr_tile_processed()
    assert budget.can_process_ocr_tile() is False


def test_pipeline_fails_closed_on_unsupported_extensions(tmp_path) -> None:
    fake_file = tmp_path / "script.py"
    fake_file.write_text("print('hello')", encoding="utf-8")

    with pytest.raises(ValueError, match="Unsupported document format"):
        process_document(fake_file, allow_fallback=False)
