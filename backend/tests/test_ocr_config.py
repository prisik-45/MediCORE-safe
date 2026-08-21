import sys
from pathlib import Path
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from PIL import Image


class RapidOCRConfigTest(unittest.TestCase):
    def test_rapidocr_lines_are_used_for_image_ocr(self) -> None:
        from backend.app.services import ocr

        class FakeRapidOCR:
            def __call__(self, image):
                return (
                    [
                        (
                            [(10, 20), (75, 20), (75, 35), (10, 35)],
                            "Vitamin",
                            0.92,
                        ),
                        (
                            [(82, 20), (100, 20), (100, 35), (82, 35)],
                            "C",
                            0.91,
                        ),
                        (
                            [(180, 20), (222, 20), (222, 35), (180, 35)],
                            "USD",
                            0.90,
                        ),
                        (
                            [(232, 20), (282, 20), (282, 35), (232, 35)],
                            "5/kg",
                            0.89,
                        ),
                    ],
                    None,
                )

        from backend.app.pipeline.extraction import text_ocr

        fake_module = types.SimpleNamespace(RapidOCR=lambda *args, **kwargs: FakeRapidOCR())

        with patch.dict(sys.modules, {"rapidocr_onnxruntime": fake_module}), patch.object(
            text_ocr, "_RAPID_OCR_ENGINE", FakeRapidOCR()
        ):
            lines = ocr.recognize_image(Image.new("RGB", (320, 120), "white"), "sample.png")

        self.assertEqual([line.text for line in lines], ["Vitamin", "C", "USD", "5/kg"])


if __name__ == "__main__":
    unittest.main()
