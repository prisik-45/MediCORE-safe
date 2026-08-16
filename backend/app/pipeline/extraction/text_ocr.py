"""OCR text extractor using rapidocr-onnxruntime with tiling and tuned box threshold.

Owned by: pipeline/extraction/text_ocr.py
"""

import logging
from typing import Any
import numpy as np
from PIL import Image

from backend.app.pipeline.config import default_config
from backend.app.pipeline.normalization.schema import ExtractedBlock
from backend.app.pipeline.preprocessing.preprocess import create_image_tiles, preprocess_for_ocr

logger = logging.getLogger(__name__)

# Single instance cached ONNX runtime engine
_RAPID_OCR_ENGINE: Any = None


def get_ocr_engine():
    global _RAPID_OCR_ENGINE
    if _RAPID_OCR_ENGINE is None:
        try:
            from rapidocr_onnxruntime import RapidOCR

            try:
                _RAPID_OCR_ENGINE = RapidOCR(
                    box_thresh=default_config.ocr_box_thresh,
                    unclip_ratio=default_config.ocr_unclip_ratio,
                    use_angle_cls=default_config.ocr_use_angle_cls,
                )
            except TypeError:
                _RAPID_OCR_ENGINE = RapidOCR()
        except Exception as e:
            logger.error("Failed to initialize RapidOCR engine: %s", e)
            raise RuntimeError(f"RapidOCR engine initialization failed: {e}") from e
    return _RAPID_OCR_ENGINE


def extract_text_with_ocr(
    image: Image.Image,
    *,
    box_thresh: float | None = None,
    preprocess: bool = True,
    tile: bool = True,
) -> list[ExtractedBlock]:
    """Run OCR on image, handling tiling and bbox coordinate restoration."""
    engine = get_ocr_engine()

    # Preprocess image
    conditioned = preprocess_for_ocr(image) if preprocess else image

    # Tiling for large/high-res images (>3000px)
    raw_tiles = (
        create_image_tiles(conditioned, max_dimension=default_config.tile_max_dimension, overlap_px=default_config.tile_overlap_px)
        if tile
        else []
    )
    tiles = raw_tiles[:default_config.max_ocr_tiles_per_page]

    all_blocks: list[ExtractedBlock] = []

    if not tiles:
        tiles = [
            type(
                "ImageTile",
                (),
                {"sub_image": conditioned, "offset_x": 0, "offset_y": 0, "width": conditioned.width, "height": conditioned.height},
            )()
        ]

    for tile_item in tiles:
        np_img = np.array(tile_item.sub_image)
        try:
            results, _ = engine(np_img)
            if not results:
                continue

            for item in results:
                if not item or len(item) < 3:
                    continue
                box_points, text, conf = item[0], str(item[1] or "").strip(), float(item[2] or 0.0)

                thresh = box_thresh if box_thresh is not None else default_config.ocr_box_thresh
                if not text or conf < thresh:
                    continue

                xs = [float(pt[0]) + tile_item.offset_x for pt in box_points]
                ys = [float(pt[1]) + tile_item.offset_y for pt in box_points]
                left, top, right, bottom = min(xs), min(ys), max(xs), max(ys)

                all_blocks.append(
                    ExtractedBlock(
                        type="text",
                        bbox=[left, top, right, bottom],
                        content=text,
                        confidence=conf,
                        engine="rapidocr",
                    )
                )
        except Exception as err:
            logger.warning("OCR failed on tile offset (%s, %s): %s", tile_item.offset_x, tile_item.offset_y, err)

    return _deduplicate_ocr_blocks(all_blocks)


def _deduplicate_ocr_blocks(blocks: list[ExtractedBlock]) -> list[ExtractedBlock]:
    """Deduplicate overlapping OCR text blocks produced across tile boundaries."""
    if not blocks:
        return []

    sorted_blocks = sorted(blocks, key=lambda b: (b.bbox[1], b.bbox[0]))
    deduped: list[ExtractedBlock] = []

    for block in sorted_blocks:
        duplicate = False
        for existing in deduped:
            if _boxes_overlap(block.bbox, existing.bbox, iou_thresh=0.6):
                if block.content == existing.content or block.content in existing.content:
                    duplicate = True
                    break
                elif existing.content in block.content:
                    deduped.remove(existing)
                    break
        if not duplicate:
            deduped.append(block)

    return deduped


def _boxes_overlap(box1: list[float], box2: list[float], iou_thresh: float = 0.5) -> bool:
    x1_max = max(box1[0], box2[0])
    y1_max = max(box1[1], box2[1])
    x2_min = min(box1[2], box2[2])
    y2_min = min(box1[3], box2[3])

    inter_w = max(0.0, x2_min - x1_max)
    inter_h = max(0.0, y2_min - y1_max)
    inter_area = inter_w * inter_h

    if inter_area <= 0:
        return False

    area1 = (box1[2] - box1[0]) * (box1[3] - box1[1])
    area2 = (box2[2] - box2[0]) * (box2[3] - box2[1])
    union_area = area1 + area2 - inter_area

    return (inter_area / max(1.0, union_area)) >= iou_thresh
