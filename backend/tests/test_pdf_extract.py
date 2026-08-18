import unittest
from pathlib import Path
from unittest.mock import patch

from backend.app.pipeline.normalization.schema import DocumentPageResult, ExtractedBlock, ExtractionResult
from backend.app.services import pdf_extract


class PdfExtractServiceTest(unittest.TestCase):
    def test_extract_pdf_text_delegates_to_pipeline(self) -> None:
        mock_result = ExtractionResult(
            source="pdf",
            file_path="sample.pdf",
            pages=[
                DocumentPageResult(
                    page=1,
                    source="pdf",
                    blocks=[
                        ExtractedBlock(
                            type="text",
                            bbox=[10.0, 10.0, 100.0, 50.0],
                            content="Ingredient | Price\nVitamin C | USD 5/kg",
                            confidence=0.98,
                            engine="pymupdf",
                        )
                    ],
                )
            ],
        )

        with patch("backend.app.services.pdf_extract.process_document", return_value=mock_result) as mock_proc:
            with patch.object(Path, "is_file", return_value=True):
                text = pdf_extract.extract_pdf_text("sample.pdf")

        mock_proc.assert_called_once_with(Path("sample.pdf"), use_vision_for_pdf_images=False)
        self.assertIn("Vitamin C | USD 5/kg", text)

    def test_extract_pdf_text_nonexistent_file_returns_empty(self) -> None:
        text = pdf_extract.extract_pdf_text("nonexistent_file_path_xyz.pdf")
        self.assertEqual(text, "")


if __name__ == "__main__":
    unittest.main()
