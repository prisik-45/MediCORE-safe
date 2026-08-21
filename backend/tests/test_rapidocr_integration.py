import sys
from pathlib import Path

import numpy as np
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.app.main import app
from backend.app.pipeline.extraction.text_ocr import (
    check_ocr_readiness,
    extract_text_with_ocr,
    get_ocr_engine,
)
from backend.app.services.ocr import recognize_image, recognize_image_to_text


def create_sample_text_image(text: str = "MEDICORE PHARMA") -> Image.Image:
    """Create a deterministic high-contrast sample image with text for OCR tests."""
    image = Image.new("RGB", (600, 150), color="white")
    draw = ImageDraw.Draw(image)
    draw.text((20, 45), text, fill="black")
    return image


def test_rapidocr_imports():
    """Verify that all core OCR and image runtime dependencies import without error."""
    import cv2
    import onnxruntime
    import rapidocr_onnxruntime
    from rapidocr_onnxruntime import RapidOCR

    assert RapidOCR is not None
    assert cv2.__file__ is not None
    assert onnxruntime.__file__ is not None
    assert rapidocr_onnxruntime.__file__ is not None


def test_ocr_engine_initializes():
    """Verify that the RapidOCR engine initializes properly with bundled ONNX models."""
    engine = get_ocr_engine()
    assert engine is not None


def test_ocr_readiness_check():
    """Verify that check_ocr_readiness reports ready status."""
    readiness = check_ocr_readiness()
    assert readiness["status"] == "ready"
    assert readiness["initialized"] is True
    assert readiness["engine"] == "rapidocr_onnxruntime"


def test_ocr_processes_sample_image():
    """Verify that RapidOCR extracts text blocks from a deterministic synthetic image."""
    img = create_sample_text_image("MEDICORE")
    blocks = extract_text_with_ocr(img, preprocess=True)

    assert isinstance(blocks, list)
    assert len(blocks) > 0
    first_block = blocks[0]
    assert first_block.content
    assert first_block.confidence > 0.0
    assert len(first_block.bbox) == 4
    assert first_block.engine == "rapidocr"


def test_ocr_service_recognize_image():
    """Verify that the legacy OCR service wrapper functions correctly."""
    img = create_sample_text_image("AMOXICILLIN 500MG")
    lines = recognize_image(img, "test_item.png")

    assert len(lines) > 0
    assert lines[0].text
    assert lines[0].score > 0.0


def test_ocr_handles_blank_image():
    """Verify that OCR gracefully handles a completely blank image without error."""
    blank_img = Image.new("RGB", (300, 100), color="white")
    blocks = extract_text_with_ocr(blank_img, preprocess=False)
    assert blocks == []


def test_health_ocr_endpoint():
    """Verify that the /health/ocr endpoint returns status ok/ready."""
    client = TestClient(app)
    response = client.get("/health/ocr")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ready"
    assert data["initialized"] is True
