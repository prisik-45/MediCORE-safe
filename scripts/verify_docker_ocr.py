#!/usr/bin/env python3
"""End-to-end verification script for RapidOCR inside Docker & local environments.

Runs tests for:
1. Python runtime dependencies and shared libraries
2. OpenCV contrib ximgproc availability
3. Bundled ONNX model verification
4. RapidOCR initialization and execution
5. OCR readiness health check
6. Full MediCORE extraction pipeline
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image, ImageDraw

def verify_all():
    print("=" * 60)
    print("1. Testing Imports & Runtime Dependencies...")
    print("=" * 60)
    try:
        import onnxruntime
        import cv2
        from rapidocr_onnxruntime import RapidOCR
        from PIL import Image
        import numpy as np
        print(f" [PASS] onnxruntime version: {onnxruntime.__version__}")
        print(f" [PASS] cv2 version: {cv2.__version__}")
        print(f" [PASS] RapidOCR class: {RapidOCR}")
        print(f" [PASS] cv2.ximgproc available: {hasattr(cv2, 'ximgproc')}")
        assert hasattr(cv2, 'ximgproc'), "cv2.ximgproc is missing! opencv-contrib-python-headless is required."
    except Exception as e:
        print(f" [FAIL] Dependency import error: {e}")
        sys.exit(1)

    print("\n" + "=" * 60)
    print("2. Verifying Bundled ONNX Models...")
    print("=" * 60)
    try:
        import rapidocr_onnxruntime, os
        pkg_dir = os.path.dirname(rapidocr_onnxruntime.__file__)
        models_dir = os.path.join(pkg_dir, "models")
        assert os.path.exists(models_dir), f"Models directory not found at {models_dir}"
        models = os.listdir(models_dir)
        print(f" [PASS] Found bundled models ({len(models)}): {models}")
        assert len(models) >= 3, "Expected at least 3 ONNX models (det, cls, rec)"
    except Exception as e:
        print(f" [FAIL] Model verification error: {e}")
        sys.exit(1)

    print("\n" + "=" * 60)
    print("3. Testing OCR Engine Initialization...")
    print("=" * 60)
    try:
        from backend.app.pipeline.extraction.text_ocr import get_ocr_engine, check_ocr_readiness
        engine = get_ocr_engine()
        assert engine is not None, "Failed to instantiate RapidOCR engine"
        readiness = check_ocr_readiness()
        print(f" [PASS] OCR Engine initialized: {engine}")
        print(f" [PASS] OCR Readiness check: {readiness}")
        assert readiness["status"] == "ready", f"Readiness check status not ready: {readiness}"
    except Exception as e:
        print(f" [FAIL] Engine initialization error: {e}")
        sys.exit(1)

    print("\n" + "=" * 60)
    print("4. Testing OCR Extraction on Synthetic Image...")
    print("=" * 60)
    try:
        from backend.app.pipeline.extraction.text_ocr import extract_text_with_ocr
        from backend.app.services.ocr import recognize_image

        test_img = Image.new("RGB", (600, 150), color="white")
        draw = ImageDraw.Draw(test_img)
        draw.text((20, 45), "MEDICORE OCR SUCCESS", fill="black")

        blocks = extract_text_with_ocr(test_img, preprocess=True)
        print(f" [PASS] extract_text_with_ocr returned {len(blocks)} block(s)")
        for b in blocks:
            print(f"        Block: '{b.content}' (confidence: {b.confidence:.2f}, bbox: {b.bbox})")
        assert len(blocks) > 0, "No text blocks extracted from sample image"

        lines = recognize_image(test_img, "test.png")
        print(f" [PASS] recognize_image returned {len(lines)} line(s)")
        assert len(lines) > 0, "No text lines recognized from sample image"
    except Exception as e:
        print(f" [FAIL] OCR extraction error: {e}")
        sys.exit(1)

    print("\n" + "=" * 60)
    print("5. Testing Full MediCORE Extraction Pipeline...")
    print("=" * 60)
    try:
        from backend.app.pipeline.pipeline import process_document

        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            img = Image.new("RGB", (600, 200), color="white")
            draw = ImageDraw.Draw(img)
            draw.text((20, 40), "AMOXICILLIN 500MG CAPSULES", fill="black")
            draw.text((20, 100), "USD 25.00 PER PACK", fill="black")
            img.save(f.name)
            temp_path = f.name

        result = process_document(temp_path)
        print(f" [PASS] Pipeline processed: {result.file_path}")
        print(f" [PASS] Extracted {len(result.pages)} page(s) with {sum(len(p.blocks) for p in result.pages)} total block(s)")
        for p in result.pages:
            for b in p.blocks:
                print(f"        Extracted [{b.engine} / {b.type}]: '{b.content}' (conf: {b.confidence:.2f})")
        assert len(result.pages) > 0, "Pipeline produced 0 pages"
        assert sum(len(p.blocks) for p in result.pages) > 0, "Pipeline produced 0 blocks"
    except Exception as e:
        print(f" [FAIL] Pipeline extraction error: {e}")
        sys.exit(1)

    print("\n" + "=" * 60)
    print(">>> ALL OCR VERIFICATION CHECKS PASSED SUCCESSFULLY! <<<")
    print("=" * 60)

if __name__ == "__main__":
    verify_all()
