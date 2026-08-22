"""Merge module for combining native text, OCR text, and table extractions.

Owned by: pipeline/normalization/merge.py
"""

from backend.app.pipeline.normalization.schema import DocumentPageResult, ExtractedBlock, SourceType


def merge_page_blocks(
    native_blocks: list[ExtractedBlock],
    ocr_blocks: list[ExtractedBlock],
    table_blocks: list[ExtractedBlock],
    is_mixed_page: bool = False,
) -> list[ExtractedBlock]:
    """Merge and deduplicate extracted blocks for a single page in reading order."""
    combined: list[ExtractedBlock] = []

    # 1. Add table blocks first (tables take layout precedence)
    table_bboxes = [b.bbox for b in table_blocks]
    combined.extend(table_blocks)

    # 2. Add native blocks if not inside a table area
    for n_block in native_blocks:
        if not _is_inside_any_bbox(n_block.bbox, table_bboxes, threshold=0.7):
            combined.append(n_block)

    native_bboxes = [b.bbox for b in native_blocks]

    # 3. Add OCR blocks if not overlapping with native text or table regions (for mixed pages)
    for o_block in ocr_blocks:
        if _is_inside_any_bbox(o_block.bbox, table_bboxes, threshold=0.5):
            continue
        if is_mixed_page and _is_inside_any_bbox(o_block.bbox, native_bboxes, threshold=0.4):
            continue
        combined.append(o_block)

    # Sort blocks in visual reading order (y0 first, then x0)
    return sorted(combined, key=lambda b: (round(b.bbox[1], -1), round(b.bbox[0], -1)))


def create_document_page_result(
    page_num: int,
    source: SourceType,
    blocks: list[ExtractedBlock],
) -> DocumentPageResult:
    return DocumentPageResult(page=page_num, source=source, blocks=blocks)


def _is_inside_any_bbox(box: list[float], container_boxes: list[list[float]], threshold: float = 0.5) -> bool:
    if not container_boxes or not box:
        return False

    box_area = max(1.0, (box[2] - box[0]) * (box[3] - box[1]))
    for cb in container_boxes:
        inter_x0 = max(box[0], cb[0])
        inter_y0 = max(box[1], cb[1])
        inter_x1 = min(box[2], cb[2])
        inter_y1 = min(box[3], cb[3])

        if inter_x1 > inter_x0 and inter_y1 > inter_y0:
            inter_area = (inter_x1 - inter_x0) * (inter_y1 - inter_y0)
            if (inter_area / box_area) >= threshold:
                return True
    return False
