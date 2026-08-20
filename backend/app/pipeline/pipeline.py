"""Main orchestrator entry point for the document extraction pipeline.

Owned by: pipeline/pipeline.py
"""

import logging
from pathlib import Path
from typing import Any, Union

from backend.app.pipeline.budget import ExtractionBudget
from backend.app.pipeline.classification.page_classifier import classify_pdf_page
from backend.app.pipeline.config import default_config
from backend.app.pipeline.extraction.tables import extract_tables_from_image, extract_tables_from_pdf_page
from backend.app.pipeline.extraction.text_native import extract_native_text
from backend.app.pipeline.extraction.text_ocr import extract_text_with_ocr
from backend.app.pipeline.ingestion.loader_docx import load_docx
from backend.app.pipeline.ingestion.loader_image import load_image
from backend.app.pipeline.ingestion.loader_pdf import load_pdf
from backend.app.pipeline.ingestion.loader_xlsx import format_df_to_markdown, load_xlsx
from backend.app.pipeline.normalization.merge import create_document_page_result, merge_page_blocks
from backend.app.pipeline.normalization.schema import DocumentPageResult, ExtractedBlock, ExtractionResult, SourceType
from backend.app.pipeline.preprocessing.preprocess import normalize_image_resolution
from backend.app.pipeline.validation.confidence import validate_and_retry_low_confidence_blocks
from backend.app.services.vision_extraction import extract_image_text_with_openrouter_vision

logger = logging.getLogger(__name__)


def process_document(
    file_path: Union[str, Path],
    budget: ExtractionBudget | None = None,
    allow_fallback: bool = False,
    use_vision_for_pdf_images: bool = False,
    use_vision_as_pdf_ocr_fallback: bool = False,
    db: Any | None = None,
    tenant_id: Any | None = None,
) -> ExtractionResult:
    """Single entry point for processing documents (PDF, Image, DOCX, XLSX/XLS/CSV) with resource bounds."""
    path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"Document file not found: {path}")

    effective_budget = budget or ExtractionBudget()
    suffix = path.suffix.lower()

    if suffix == ".pdf":
        return _process_pdf_document(
            path,
            budget=effective_budget,
            use_vision_for_images=use_vision_for_pdf_images,
            use_vision_as_ocr_fallback=use_vision_as_pdf_ocr_fallback,
            db=db,
            tenant_id=tenant_id,
        )
    elif suffix in {".png", ".jpg", ".jpeg", ".tiff", ".bmp", ".webp"}:
        return _process_image_document(path, budget=effective_budget)
    elif suffix == ".docx":
        return _process_docx_document(path, budget=effective_budget)
    elif suffix in {".xlsx", ".xls", ".csv", ".xlsm", ".xltx", ".xltm"}:
        return _process_xlsx_document(path, budget=effective_budget)
    elif allow_fallback:
        try:
            return _process_image_document(path, budget=effective_budget)
        except Exception:
            return _process_text_fallback(path)
    else:
        raise ValueError(f"Unsupported document format: '{suffix}'. Failing closed to protect parser resources.")


def _process_pdf_document(
    path: Path,
    budget: ExtractionBudget | None = None,
    use_vision_for_images: bool = False,
    use_vision_as_ocr_fallback: bool = False,
    db: Any | None = None,
    tenant_id: Any | None = None,
) -> ExtractionResult:
    result = ExtractionResult(source="pdf", file_path=str(path))
    effective_budget = budget or ExtractionBudget()

    with load_pdf(path) as pdf_wrapper:
        max_pages = min(pdf_wrapper.page_count, effective_budget.max_pdf_pages)
        for page_num in range(1, max_pages + 1):
            if not effective_budget.can_process_page():
                logger.warning("PDF page extraction halted at page %s: budget exhausted", page_num)
                break
            fitz_page = pdf_wrapper.get_page(page_num)
            classification = classify_pdf_page(fitz_page, page_number=page_num)

            native_blocks: list[ExtractedBlock] = []
            ocr_blocks: list[ExtractedBlock] = []
            table_blocks: list[ExtractedBlock] = []

            if classification.page_type == "native_text":
                logger.info("PDF page %s: native text found, using PyMuPDF", page_num)
                native_blocks = extract_native_text(fitz_page)
                table_blocks = extract_tables_from_pdf_page(fitz_page)
            elif classification.page_type == "scanned":
                page_img = pdf_wrapper.render_page_image(page_num, target_dpi=default_config.target_dpi)
                norm_img = normalize_image_resolution(page_img)
                vision_block = (
                    _extract_vision_block(norm_img, f"{path.name} page {page_num}", db=db, tenant_id=tenant_id)
                    if use_vision_for_images
                    else None
                )
                if vision_block:
                    logger.info("PDF page %s: image/scanned catalogue page, using OpenRouter vision", page_num)
                    ocr_blocks = [vision_block]
                else:
                    logger.info("PDF page %s: using RapidOCR fallback", page_num)
                    rapidocr_failed = False
                    try:
                        ocr_blocks = extract_text_with_ocr(norm_img)
                        ocr_blocks = validate_and_retry_low_confidence_blocks(norm_img, ocr_blocks)
                        table_blocks = extract_tables_from_image(norm_img)
                    except Exception as exc:
                        if not use_vision_as_ocr_fallback:
                            raise
                        rapidocr_failed = True
                        logger.warning(
                            "PDF page %s: RapidOCR failed, using OpenRouter vision fallback: %s",
                            page_num,
                            exc,
                            exc_info=True,
                        )
                    if use_vision_as_ocr_fallback and (rapidocr_failed or not _blocks_have_text(ocr_blocks + table_blocks)):
                        logger.info("PDF page %s: RapidOCR failed or returned no text, using OpenRouter vision fallback", page_num)
                        vision_block = _extract_vision_block(norm_img, f"{path.name} page {page_num}", db=db, tenant_id=tenant_id)
                        if vision_block:
                            ocr_blocks = [vision_block]
                            table_blocks = []
            else:  # mixed page
                logger.info("PDF page %s: mixed page, extracting native text with PyMuPDF", page_num)
                native_blocks = extract_native_text(fitz_page)
                page_img = pdf_wrapper.render_page_image(page_num, target_dpi=default_config.target_dpi)
                norm_img = normalize_image_resolution(page_img)
                vision_block = (
                    _extract_vision_block(norm_img, f"{path.name} page {page_num}", db=db, tenant_id=tenant_id)
                    if use_vision_for_images
                    else None
                )
                if vision_block:
                    logger.info("PDF page %s: mixed catalogue image content, using OpenRouter vision", page_num)
                    ocr_blocks = [vision_block]
                    table_blocks = extract_tables_from_pdf_page(fitz_page)
                else:
                    logger.info("PDF page %s: using RapidOCR fallback for image content", page_num)
                    rapidocr_failed = False
                    try:
                        ocr_blocks = extract_text_with_ocr(norm_img)
                        ocr_blocks = validate_and_retry_low_confidence_blocks(norm_img, ocr_blocks)
                        table_blocks = extract_tables_from_pdf_page(fitz_page) or extract_tables_from_image(norm_img)
                    except Exception as exc:
                        if not use_vision_as_ocr_fallback:
                            raise
                        rapidocr_failed = True
                        table_blocks = extract_tables_from_pdf_page(fitz_page)
                        logger.warning(
                            "PDF page %s: RapidOCR failed, using OpenRouter vision fallback: %s",
                            page_num,
                            exc,
                            exc_info=True,
                        )
                    if use_vision_as_ocr_fallback and (rapidocr_failed or not _blocks_have_text(native_blocks + ocr_blocks + table_blocks)):
                        logger.info("PDF page %s: RapidOCR failed or returned no text, using OpenRouter vision fallback", page_num)
                        vision_block = _extract_vision_block(norm_img, f"{path.name} page {page_num}", db=db, tenant_id=tenant_id)
                        if vision_block:
                            ocr_blocks = [vision_block]
                            table_blocks = extract_tables_from_pdf_page(fitz_page)

            merged = merge_page_blocks(
                native_blocks=native_blocks,
                ocr_blocks=ocr_blocks,
                table_blocks=table_blocks,
                is_mixed_page=(classification.page_type == "mixed"),
            )

            result.pages.append(create_document_page_result(page_num=page_num, source="pdf", blocks=merged))

    return result


def _blocks_have_text(blocks: list[ExtractedBlock]) -> bool:
    return any((block.content or "").strip() for block in blocks)


def _process_image_document(path: Path, budget: ExtractionBudget | None = None) -> ExtractionResult:
    result = ExtractionResult(source="image", file_path=str(path))
    img_wrapper = load_image(path)
    norm_img = normalize_image_resolution(img_wrapper.image)

    vision_block = _extract_vision_block(norm_img, path.name)
    if vision_block:
        ocr_blocks = [vision_block]
        table_blocks: list[ExtractedBlock] = []
    else:
        ocr_blocks = extract_text_with_ocr(norm_img)
        ocr_blocks = validate_and_retry_low_confidence_blocks(norm_img, ocr_blocks)
        table_blocks = extract_tables_from_image(norm_img)

    merged = merge_page_blocks(
        native_blocks=[],
        ocr_blocks=ocr_blocks,
        table_blocks=table_blocks,
        is_mixed_page=False,
    )

    result.pages.append(create_document_page_result(page_num=1, source="image", blocks=merged))
    return result


def _extract_vision_block(image, source_name: str, db: Any | None = None, tenant_id: Any | None = None) -> ExtractedBlock | None:
    if db is not None or tenant_id is not None:
        text = extract_image_text_with_openrouter_vision(image, source_name=source_name, db=db, tenant_id=tenant_id)
    else:
        text = extract_image_text_with_openrouter_vision(image, source_name=source_name)
    if not text:
        return None
    return ExtractedBlock(
        type="text",
        bbox=[0.0, 0.0, 0.0, 0.0],
        content=text,
        confidence=0.9,
        engine="openrouter-vision",
    )


def _process_docx_document(path: Path, budget: ExtractionBudget | None = None) -> ExtractionResult:
    result = ExtractionResult(source="docx", file_path=str(path))
    docx_wrapper = load_docx(path)

    blocks: list[ExtractedBlock] = []
    parts = docx_wrapper.get_formatted_parts()
    for part in parts:
        block_type = "table" if part.strip().startswith("|") else "text"
        blocks.append(
            ExtractedBlock(
                type=block_type,
                bbox=[0.0, 0.0, 0.0, 0.0],
                content=part.strip(),
                confidence=1.0,
                engine="mammoth",
            )
        )

    result.pages.append(create_document_page_result(page_num=1, source="docx", blocks=blocks))
    return result


def _process_xlsx_document(path: Path, budget: ExtractionBudget | None = None) -> ExtractionResult:
    result = ExtractionResult(source="xlsx", file_path=str(path))
    excel_wrapper = load_xlsx(path)

    engine_name = "xlrd" if path.suffix.lower() == ".xls" else "openpyxl"

    for idx, (sheet_name, df) in enumerate(excel_wrapper.sheets_data.items(), start=1):
        blocks: list[ExtractedBlock] = []
        if not df.empty:
            md_text = format_df_to_markdown(df)
            blocks.append(
                ExtractedBlock(
                    type="table",
                    bbox=[0.0, 0.0, 0.0, 0.0],
                    content=f"### Sheet: {sheet_name}\n{md_text}".strip(),
                    confidence=1.0,
                    engine=engine_name,
                )
            )
        result.pages.append(create_document_page_result(page_num=idx, source="xlsx", blocks=blocks))

    return result


def _process_text_fallback(path: Path) -> ExtractionResult:
    result = ExtractionResult(source="image", file_path=str(path))
    try:
        content = path.read_text(encoding="utf-8", errors="ignore")
        if content.strip():
            blocks = [
                ExtractedBlock(
                    type="text",
                    bbox=[0.0, 0.0, 0.0, 0.0],
                    content=content.strip(),
                    confidence=1.0,
                    engine="pymupdf",
                )
            ]
            result.pages.append(create_document_page_result(page_num=1, source="image", blocks=blocks))
    except Exception as err:
        logger.warning("Text fallback failed for %s: %s", path.name, err)

    return result
