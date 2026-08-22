"""Legacy OCR service wrapper delegating to the extraction pipeline.

Owned by: backend/app/services/ocr.py
"""

import logging
from dataclasses import dataclass
from PIL import Image

from backend.app.pipeline.extraction.text_ocr import extract_text_with_ocr
from backend.app.pipeline.preprocessing.preprocess import preprocess_for_ocr

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OCRTextLine:
    text: str
    score: float
    box: tuple[float, float, float, float]

    @property
    def center_x(self) -> float:
        return (self.box[0] + self.box[2]) / 2

    @property
    def center_y(self) -> float:
        return (self.box[1] + self.box[3]) / 2


def preprocess_document_image(image: Image.Image, *, scale_small_images: bool = True) -> Image.Image:
    return preprocess_for_ocr(image)


def recognize_image(image: Image.Image, source_name: str = "image", *, preprocess: bool = True) -> list[OCRTextLine]:
    blocks = extract_text_with_ocr(image, preprocess=preprocess)
    lines: list[OCRTextLine] = []
    for b in blocks:
        lines.append(OCRTextLine(text=b.content, score=b.confidence, box=(b.bbox[0], b.bbox[1], b.bbox[2], b.bbox[3])))
    return sorted(lines, key=lambda line: (line.center_y, line.center_x))


def recognize_image_to_text(image: Image.Image, source_name: str = "image") -> str:
    lines = recognize_image(image, source_name)
    if lines:
        rows = _cluster_lines_by_y(lines)
        text = "\n".join(" ".join(line.text for line in row).strip() for row in rows if row).strip()
        if text:
            return text

    return ""


def _cluster_lines_by_y(lines: list[OCRTextLine]) -> list[list[OCRTextLine]]:
    rows: list[list[OCRTextLine]] = []
    for line in sorted(lines, key=lambda value: (value.center_y, value.center_x)):
        height = max(8.0, line.box[3] - line.box[1])
        if rows and abs(rows[-1][0].center_y - line.center_y) <= height * 0.65:
            rows[-1].append(line)
        else:
            rows.append([line])
    for row in rows:
        row.sort(key=lambda value: value.center_x)
    return rows
