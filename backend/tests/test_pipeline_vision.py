from pathlib import Path

from PIL import Image

from backend.app.pipeline import pipeline
from backend.app.pipeline.normalization.schema import ExtractedBlock


def test_image_pipeline_uses_vision_before_rapidocr(monkeypatch, tmp_path: Path) -> None:
    image_path = tmp_path / "catalogue.png"
    Image.new("RGB", (16, 16), "white").save(image_path)

    monkeypatch.setattr(
        pipeline,
        "extract_image_text_with_openrouter_vision",
        lambda image, source_name: "Vitamin C | USD 5/kg",
    )

    def fail_rapidocr(*args, **kwargs):
        raise AssertionError("RapidOCR should not run when vision extraction succeeds")

    monkeypatch.setattr(pipeline, "extract_text_with_ocr", fail_rapidocr)

    result = pipeline.process_document(image_path)

    assert result.full_text() == "Vitamin C | USD 5/kg"
    assert result.pages[0].blocks[0].engine == "openrouter-vision"


def test_image_pipeline_falls_back_to_rapidocr_when_vision_is_empty(monkeypatch, tmp_path: Path) -> None:
    image_path = tmp_path / "catalogue.png"
    Image.new("RGB", (16, 16), "white").save(image_path)
    ocr_block = ExtractedBlock(
        type="text",
        bbox=[0.0, 0.0, 0.0, 0.0],
        content="Fallback OCR text",
        confidence=0.8,
        engine="rapidocr",
    )

    monkeypatch.setattr(pipeline, "extract_image_text_with_openrouter_vision", lambda image, source_name: "")
    monkeypatch.setattr(pipeline, "extract_text_with_ocr", lambda image: [ocr_block])
    monkeypatch.setattr(pipeline, "validate_and_retry_low_confidence_blocks", lambda image, blocks: blocks)
    monkeypatch.setattr(pipeline, "extract_tables_from_image", lambda image: [])

    result = pipeline.process_document(image_path)

    assert result.full_text() == "Fallback OCR text"
    assert result.pages[0].blocks[0].engine == "rapidocr"
