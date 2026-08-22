import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageOps

from backend.app.services.ocr import OCRTextLine, preprocess_document_image, recognize_image, recognize_image_to_text

logger = logging.getLogger(__name__)

DEFAULT_COLUMNS = ("column_1", "column_2", "product", "quantity_kg", "price", "lead_time", "moq", "unit")
HEADER_ALIASES = {
    "date": ("date",),
    "customer": ("customer", "client", "buyer"),
    "product": ("product", "item", "ingredient", "chemical", "material", "medicine", "api", "name"),
    "specification": ("specification", "spec", "description", "assay", "purity", "grade", "content"),
    "quantity": ("quantity", "qty", "stock", "available"),
    "unit": ("unit", "uom"),
    "price": ("price", "rate", "quote", "cost"),
    "currency": ("currency", "curr"),
    "moq": ("moq", "m.o.q", "minimum", "min order", "min qty", "pack", "packing", "packaging", "package", "pack size", "moq/packing", "packing/moq"),
    "lead_time": ("lead", "delivery", "dispatch"),
    "pack": ("pack", "packing", "packaging", "package", "pack size", "moq", "m.o.q", "minimum", "min order", "min qty"),
}


@dataclass
class GridExtractionResult:
    horizontal_lines: list[int]
    vertical_lines: list[int]
    rows: list[dict[str, Any]]
    table_text: str


def group_positions(indices: np.ndarray, gap: int = 3, min_size: int = 1) -> list[int]:
    if len(indices) == 0:
        return []

    groups: list[list[int]] = [[int(indices[0])]]
    for value in indices[1:]:
        value = int(value)
        if value - groups[-1][-1] <= gap:
            groups[-1].append(value)
        else:
            groups.append([value])
    return [int(round(sum(group) / len(group))) for group in groups if len(group) >= min_size]


def detect_table_grid(image: Image.Image) -> tuple[list[int], list[int]]:
    gray = ImageOps.autocontrast(image.convert("L"))
    arr = np.array(gray)
    dark_pixels = arr < 95
    height, width = dark_pixels.shape

    row_candidates = np.where(dark_pixels.sum(axis=1) > width * 0.45)[0]
    col_candidates = np.where(dark_pixels.sum(axis=0) > height * 0.50)[0]
    horizontal = _filter_line_positions(group_positions(row_candidates, min_size=1), height)
    vertical = _filter_line_positions(group_positions(col_candidates, min_size=1), width)
    return horizontal, vertical


def _filter_line_positions(values: list[int], size: int) -> list[int]:
    filtered = [value for value in values if 0 <= value <= size]
    if not filtered:
        return []
    merged: list[int] = []
    for value in filtered:
        if merged and value - merged[-1] < max(5, int(size * 0.003)):
            merged[-1] = int((merged[-1] + value) / 2)
        else:
            merged.append(value)
    return merged


def extract_grid_table_from_pil_image(image: Image.Image, source_name: str = "image") -> GridExtractionResult | None:
    try:
        image = preprocess_document_image(ImageOps.exif_transpose(image).convert("RGB"))
        lines = recognize_image(image, source_name, preprocess=False)
        if not lines:
            return None

        horizontal, vertical = detect_table_grid(image)
        if len(horizontal) >= 4 and len(vertical) >= 3:
            result = _extract_bordered_table(lines, horizontal, vertical, source_name, image)
            if result:
                return result

        return _extract_unbordered_table(lines, source_name)
    except Exception:
        logger.debug("RapidOCR table extraction not applicable for %s", source_name, exc_info=True)
        return None


def _extract_bordered_table(
    lines: list[OCRTextLine],
    horizontal: list[int],
    vertical: list[int],
    source_name: str,
    image: Image.Image,
) -> GridExtractionResult | None:
    rows: list[dict[str, Any]] = []
    header_cells = _grid_row_cells(lines, horizontal[0], horizontal[1], vertical, image)
    headers = _headers_from_cells(header_cells, len(vertical) - 1)

    for row_index in range(1, len(horizontal) - 1):
        top = horizontal[row_index]
        bottom = horizontal[row_index + 1]
        cell_values = _grid_row_cells(lines, top, bottom, vertical, image, headers)
        if not any(cell_values):
            continue
        rows.append(
            {
                "row_number": row_index,
                "bbox": {"left": vertical[0], "top": top, "right": vertical[-1], "bottom": bottom},
                "cells": {
                    headers[index]: cell_values[index] if index < len(cell_values) else ""
                    for index in range(len(headers))
                },
            }
        )

    product_rows = [row for row in rows if _row_has_catalogue_signal(row["cells"])]
    if len(product_rows) < 1:
        return None

    table_text = rows_to_catalog_table_text(product_rows)
    logger.info(
        "RapidOCR bordered table extraction produced %s row(s) from %s",
        len(product_rows),
        source_name,
    )
    return GridExtractionResult(horizontal, vertical, product_rows, table_text)


def _grid_row_cells(
    lines: list[OCRTextLine],
    top: int,
    bottom: int,
    vertical: list[int],
    image: Image.Image | None = None,
    headers: list[str] | None = None,
) -> list[str]:
    cells: list[str] = []
    for column_index in range(len(vertical) - 1):
        left = vertical[column_index]
        right = vertical[column_index + 1]
        cell_lines = [
            line
            for line in lines
            if left <= line.center_x <= right and top <= line.center_y <= bottom
        ]
        text = " ".join(line.text for line in sorted(cell_lines, key=lambda value: (value.center_y, value.center_x))).strip()
        header = headers[column_index] if headers and column_index < len(headers) else ""
        if image is not None and _needs_cell_ocr(text, header):
            text = _ocr_grid_cell(image, left, top, right, bottom, header) or text
        cells.append(text)
    return cells


def _needs_cell_ocr(text: str, header: str) -> bool:
    cleaned = clean_text(text)
    if not cleaned:
        return header in {"product", "price", "quantity", "quantity_kg", "lead_time"}
    if header == "product" and re.search(r"[\[\]{}*]{2,}|CdSSC|Suess", cleaned, flags=re.IGNORECASE):
        return True
    if header == "lead_time" and cleaned.lower() in {"d", "day", "days"}:
        return True
    if header == "price" and re.search(r"\b(?:CIF|FOB|EXW|CNF|C&F)\b", cleaned, flags=re.IGNORECASE) and not re.search(r"\$|USD|INR|Rs\.?|\d+\s*/\s*[A-Za-z]+", cleaned, flags=re.IGNORECASE):
        return True
    if header == "price" and cleaned and not _ocr_price_text_has_signal(cleaned):
        return True
    return False


def _ocr_grid_cell(image: Image.Image, left: int, top: int, right: int, bottom: int, header: str = "") -> str:
    try:
        pad = 4
        crop = image.crop(
            (
                max(0, left + pad),
                max(0, top + pad),
                min(image.width, right - pad),
                min(image.height, bottom - pad),
            )
        )
        crop = ImageOps.autocontrast(crop.convert("L")).convert("RGB")
        text = recognize_image_to_text(crop, f"grid cell {header or 'unknown'}")
        return clean_text(text)
    except Exception:
        logger.debug("RapidOCR cell OCR failed", exc_info=True)
        return ""


def _ocr_price_text_has_signal(text: str) -> bool:
    return bool(
        re.search(r"\$|USD|INR|Rs\.?|EUR|GBP|\d[\d,]*(?:\.\d+)?\s*/\s*[A-Za-z]+", text, flags=re.IGNORECASE)
        or re.search(r"\b(?:CIF|FOB|EXW|CNF|C&F|on request|upon request|negotiable|market price|quote)\b", text, flags=re.IGNORECASE)
    )


def _extract_unbordered_table(lines: list[OCRTextLine], source_name: str) -> GridExtractionResult | None:
    clustered_rows = _cluster_lines_by_y(lines)
    table_rows = [row for row in clustered_rows if len(row) >= 2]
    if len(table_rows) < 2:
        return None

    product_spec_result = _extract_unbordered_product_spec_blocks(table_rows, lines, source_name)
    if product_spec_result:
        return product_spec_result

    header_index = _best_header_row_index(table_rows)
    if header_index is None:
        return None
    header_row = table_rows[header_index]
    headers = _headers_from_cells([line.text for line in header_row], len(header_row))
    boundaries = _column_boundaries(header_row, lines)
    rows: list[dict[str, Any]] = []
    for row_number, row in enumerate(table_rows[header_index + 1 :], start=1):
        cells = _assign_lines_to_boundaries(row, boundaries)
        if not any(cells):
            continue
        mapped = {
            headers[index]: cells[index] if index < len(cells) else ""
            for index in range(len(headers))
        }
        if _row_has_catalogue_signal(mapped) and not _is_table_noise_text(" ".join(mapped.values())):
            rows.append({"row_number": row_number, "bbox": {}, "cells": mapped})

    if not rows:
        return None

    table_text = rows_to_catalog_table_text(rows)
    logger.info("RapidOCR unbordered table extraction produced %s row(s) from %s", len(rows), source_name)
    return GridExtractionResult([], [int(boundary) for boundary in boundaries], rows, table_text)


def _extract_unbordered_product_spec_blocks(
    table_rows: list[list[OCRTextLine]],
    all_lines: list[OCRTextLine],
    source_name: str,
) -> GridExtractionResult | None:
    header_index = None
    header_pairs: list[tuple[OCRTextLine, OCRTextLine]] = []
    for index, row in enumerate(table_rows[:10]):
        pairs = _product_spec_header_pairs(row)
        if pairs:
            header_index = index
            header_pairs = pairs
            break
    if header_index is None or not header_pairs:
        return None

    rows: list[dict[str, Any]] = []
    header_centers = sorted([line.center_x for pair in header_pairs for line in pair])
    min_left = min(line.box[0] for line in all_lines)
    max_right = max(line.box[2] for line in all_lines)

    for block_index, (product_header, spec_header) in enumerate(header_pairs):
        previous_center = header_centers[header_centers.index(product_header.center_x) - 1] if header_centers.index(product_header.center_x) > 0 else min_left
        next_header_position = header_centers.index(spec_header.center_x) + 1
        next_center = header_centers[next_header_position] if next_header_position < len(header_centers) else max_right
        block_left = (previous_center + product_header.center_x) / 2 if previous_center != min_left else min_left
        split = (product_header.center_x + spec_header.center_x) / 2
        block_right = (spec_header.center_x + next_center) / 2 if next_center != max_right else max_right

        empty_streak = 0
        for row_number, row in enumerate(table_rows[header_index + 1 :], start=1):
            product_parts: list[OCRTextLine] = []
            spec_parts: list[OCRTextLine] = []
            for line in row:
                if not (block_left <= line.center_x <= block_right):
                    continue
                if line.center_x <= split:
                    product_parts.append(line)
                else:
                    spec_parts.append(line)

            product = clean_text(" ".join(line.text for line in product_parts))
            specification = clean_text(" ".join(line.text for line in spec_parts))
            row_text = clean_text(f"{product} {specification}")
            if not row_text:
                empty_streak += 1
                if empty_streak >= 3:
                    break
                continue
            empty_streak = 0
            if _is_table_noise_text(row_text):
                continue

            mapped = {"product": product, "specification": specification}
            if _row_has_catalogue_signal(mapped):
                row_lines = product_parts + spec_parts
                rows.append(
                    {
                        "row_number": len(rows) + 1,
                        "block_number": block_index + 1,
                        "bbox": _bbox_from_lines(row_lines),
                        "cells": mapped,
                    }
                )

    if not rows:
        return None

    table_text = rows_to_catalog_table_text(rows)
    boundaries = sorted({int(value) for pair in header_pairs for value in (pair[0].center_x, pair[1].center_x)})
    logger.info(
        "RapidOCR product/spec table extraction produced %s row(s) from %s",
        len(rows),
        source_name,
    )
    return GridExtractionResult([], boundaries, rows, table_text)


def _product_spec_header_pairs(row: list[OCRTextLine]) -> list[tuple[OCRTextLine, OCRTextLine]]:
    pairs: list[tuple[OCRTextLine, OCRTextLine]] = []
    sorted_row = sorted(row, key=lambda value: value.center_x)
    product_header: OCRTextLine | None = None
    for line in sorted_row:
        column = column_name_from_header(line.text, "")
        if column == "product":
            product_header = line
            continue
        if column == "specification" and product_header is not None:
            pairs.append((product_header, line))
            product_header = None
    return pairs


def _bbox_from_lines(lines: list[OCRTextLine]) -> dict[str, float]:
    if not lines:
        return {}
    return {
        "left": min(line.box[0] for line in lines),
        "top": min(line.box[1] for line in lines),
        "right": max(line.box[2] for line in lines),
        "bottom": max(line.box[3] for line in lines),
    }


def _cluster_lines_by_y(lines: list[OCRTextLine]) -> list[list[OCRTextLine]]:
    rows: list[list[OCRTextLine]] = []
    for line in sorted(lines, key=lambda value: (value.center_y, value.center_x)):
        height = max(10.0, line.box[3] - line.box[1])
        if rows and abs(rows[-1][0].center_y - line.center_y) <= height * 0.75:
            rows[-1].append(line)
        else:
            rows.append([line])
    for row in rows:
        row.sort(key=lambda value: value.center_x)
    return rows


def _best_header_row_index(rows: list[list[OCRTextLine]]) -> int | None:
    best_index = None
    best_score = 0
    for index, row in enumerate(rows[:8]):
        text = " ".join(line.text for line in row).lower()
        score = sum(
            1
            for aliases in HEADER_ALIASES.values()
            if any(alias in text for alias in aliases)
        )
        if score > best_score:
            best_score = score
            best_index = index
    return best_index if best_score >= 2 else None


def _column_boundaries(header_row: list[OCRTextLine], all_lines: list[OCRTextLine]) -> list[float]:
    centers = [line.center_x for line in header_row]
    min_left = min(line.box[0] for line in all_lines)
    max_right = max(line.box[2] for line in all_lines)
    boundaries = [min_left]
    for left, right in zip(centers, centers[1:]):
        boundaries.append((left + right) / 2)
    boundaries.append(max_right)
    return boundaries


def _assign_lines_to_boundaries(row: list[OCRTextLine], boundaries: list[float]) -> list[str]:
    cells = ["" for _ in range(max(0, len(boundaries) - 1))]
    for line in row:
        for index in range(len(boundaries) - 1):
            if boundaries[index] <= line.center_x <= boundaries[index + 1]:
                cells[index] = f"{cells[index]} {line.text}".strip()
                break
    return cells


def _headers_from_cells(cells: list[str], expected_count: int) -> list[str]:
    headers: list[str] = []
    for index in range(expected_count):
        raw = cells[index] if index < len(cells) else ""
        fallback = DEFAULT_COLUMNS[index] if index < len(DEFAULT_COLUMNS) else f"column_{index + 1}"
        headers.append(column_name_from_header(raw, fallback))
    return _dedupe_headers(headers)


def _dedupe_headers(headers: list[str]) -> list[str]:
    seen: dict[str, int] = {}
    deduped: list[str] = []
    for header in headers:
        seen[header] = seen.get(header, 0) + 1
        deduped.append(header if seen[header] == 1 else f"{header}_{seen[header]}")
    return deduped


def column_name_from_header(header: str, fallback: str) -> str:
    lowered = header.lower()
    if "quantity" in lowered and "kg" in lowered:
        return "quantity_kg"
    for column, aliases in HEADER_ALIASES.items():
        if any(alias in lowered for alias in aliases):
            return column
    return fallback


def clean_text(text: str) -> str:
    replacements = {
        "|": " ",
        "\u00e2\u20ac\u201d": "-",
        "\u00e2\u20ac\u201c": "-",
        "\u00c3\u00a2\u00e2\u201a\u00ac\u00e2\u20ac\u009d": "-",
        "\u00c3\u00a2\u00e2\u201a\u00ac\u00e2\u20ac\u0153": "-",
        "\u00c3\u00a2\u00e2\u201a\u00ac\u00c2\u009d": "",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return re.sub(r"\s+", " ", text).strip(" -_.,")


def number_from_text(text: str) -> float | None:
    match = re.search(r"\d[\d,]*(?:\.\d+)?", text or "")
    if not match:
        return None
    token = match.group(0)
    if "," in token and "." not in token and re.search(r",\d{1,2}$", token):
        token = token.replace(",", ".")
    else:
        token = token.replace(",", "")
    return float(token)


def extract_quantity_parts(text: str) -> tuple[str, str, str, str]:
    quantity = ""
    quantity_unit = ""
    moq = ""
    pack_size = ""

    # 1. Look for explicit MOQ / Packing expressions first
    moq_match = re.search(
        r"\b(?:MOQ|M\.?O\.?Q\.?|Packing|Packaging|Pack\s*size|Pack)\s*:?\s*(\d[\d,]*(?:\.\d+)?)\s*(kg|g|mg|l|ml|unit|pack|bag|drum|carton)?\s*(fibre drum|fiber drum|drum|bag|carton|strip|box|bottle|packing|packaging|pack)?",
        text or "",
        flags=re.IGNORECASE,
    )
    if moq_match:
        val = moq_match.group(1)
        unit = moq_match.group(2) or ""
        container = (moq_match.group(3) or "").strip()
        moq = f"{val}{unit}"
        if container and container.lower() not in unit.lower():
            pack_size = f"{val} {unit} {container}".strip() if unit else f"{val} {container}".strip()
        else:
            pack_size = f"{val} {unit}".strip()

    # 2. Look for standalone pack size expressions if pack_size is not set yet
    if not pack_size:
        pack_match = re.search(
            r"(\d[\d,]*(?:\.\d+)?\s*(?:kg|g|mg|l|ml|units?|packs?)\s+(?:fibre drum|fiber drum|drum|bag|carton|strip|box|bottle|packing|packaging|pack))",
            text or "",
            flags=re.IGNORECASE,
        )
        if pack_match:
            pack_size = pack_match.group(1).strip()

    # 3. MOQ and packing are the same thing: sync them
    if not moq and pack_size:
        num_m = re.search(r"(\d[\d,]*(?:\.\d+)?)", pack_size)
        if num_m:
            u_m = re.search(r"(kg|g|mg|l|ml|unit|pack|bag|drum|carton)", pack_size, flags=re.IGNORECASE)
            unit_str = u_m.group(1).lower() if u_m else ""
            moq = f"{num_m.group(1)}{unit_str}"

    if not pack_size and moq:
        pack_size = moq

    # 4. Quantity logic (available stock qty)
    cleaned_text_for_qty = text or ""
    if moq_match:
        cleaned_text_for_qty = cleaned_text_for_qty[:moq_match.start()] + cleaned_text_for_qty[moq_match.end():]

    quantity_value = number_from_text(cleaned_text_for_qty)
    if quantity_value is not None:
        quantity = f"{quantity_value:g}"
        unit_match = re.search(r"\d[\d,]*(?:\.\d+)?\s*(kg|g|mg|l|ml|unit|units|pack|packs|bags?)\b", cleaned_text_for_qty, flags=re.IGNORECASE)
        if unit_match:
            quantity_unit = unit_match.group(1).lower().rstrip("s")
    else:
        quantity_value = number_from_text(text)
        if quantity_value is not None:
            quantity = f"{quantity_value:g}"
        unit_match = re.search(r"\d[\d,]*(?:\.\d+)?\s*(kg|g|mg|l|ml|unit|units|pack|packs|bags?)\b", text or "", flags=re.IGNORECASE)
        if unit_match:
            quantity_unit = unit_match.group(1).lower().rstrip("s")

    return quantity, quantity_unit, moq, pack_size


def extract_price_parts(text: str) -> tuple[str, str]:
    if re.search(r"\bN\s*/?\s*A\b|\bNA\b", text or "", flags=re.IGNORECASE):
        return "", ""
    currency = ""
    if re.search(r"\$|USD", text or "", flags=re.IGNORECASE):
        currency = "USD"
    elif re.search(r"₹|INR|Rs\.?", text or "", flags=re.IGNORECASE):
        currency = "INR"
    elif re.search(r"€|EUR", text or "", flags=re.IGNORECASE):
        currency = "EUR"
    elif re.search(r"£|GBP", text or "", flags=re.IGNORECASE):
        currency = "GBP"
    if (
        re.search(r"\b(?:CIF|FOB|EXW|CNF|C&F)\b", text or "", flags=re.IGNORECASE)
        and not re.search(r"\d[\d,]*(?:\.\d+)?\s*/\s*[A-Za-z]+", text or "", flags=re.IGNORECASE)
    ):
        return "", currency
    match = re.search(
        r"((?:CIF|FOB|EXW|CNF|C&F)?\s*[A-Za-z ./-]*?(?:\$|USD|INR|Rs\.?|₹|EUR|€|GBP|£|CAD|AUD|SGD|CHF|AED|CNY|JPY|¥|₩|A\$|C\$|S\$\s*)?\s*\d[\d,]*(?:\.\d+)?(?:\s*/\s*[A-Za-z]+)?)",
        text or "",
        flags=re.IGNORECASE,
    )
    if match:
        return clean_text(match.group(1)), currency
    cleaned = clean_text(text or "")
    if re.search(
        r"\b(?:on request|upon request|ask|negotiable|market price|current price|quote)\b",
        cleaned,
        flags=re.IGNORECASE,
    ):
        return cleaned, currency
    return "", currency


def normalize_lead_time_text(text: str) -> str:
    cleaned = clean_text(text)
    if not cleaned:
        return ""
    cleaned = re.sub(r"\b(\d+\s*(?:-|to|~)\s*\d+)\s*d\b", r"\1 days", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b(\d+)\s*d\b", r"\1 days", cleaned, flags=re.IGNORECASE)
    if re.search(r"\d+\s*(?:-|to|~)\s*\d+\s*days?\b|\d+\s*days?\b", cleaned, flags=re.IGNORECASE):
        return cleaned
    if re.search(r"\b(?:ready|stock|dispatch|delivery|lead)\b", cleaned, flags=re.IGNORECASE):
        return cleaned
    return ""


def rows_to_catalog_table_text(rows: list[dict[str, Any]]) -> str:
    lines = ["Product | Specification | Qty | Unit | Price | Currency | Lead | MOQ | Pack | Notes"]
    for row in rows:
        cells = row["cells"]
        product = clean_text(cells.get("product", "") or cells.get("product_2", ""))
        if not product:
            continue
        specification = clean_text(cells.get("specification", ""))
        product, specification = split_inline_specification(product, specification)
        quantity_text = clean_text(cells.get("quantity", "") or cells.get("quantity_kg", ""))
        unit_text = clean_text(cells.get("unit", ""))
        price_text = clean_text(cells.get("price", ""))
        currency_text = clean_text(cells.get("currency", ""))
        lead_text = normalize_lead_time_text(cells.get("lead_time", ""))

        # MOQ and packing are the same thing: check moq, pack, packing, packaging cell keys
        moq_cell = clean_text(cells.get("moq", "") or cells.get("pack", "") or cells.get("packing", "") or cells.get("packaging", "") or cells.get("pack_size", ""))
        pack_cell = clean_text(cells.get("pack", "") or cells.get("packing", "") or cells.get("packaging", "") or cells.get("pack_size", "") or cells.get("moq", ""))

        quantity, quantity_unit, moq, pack_size = extract_quantity_parts(" ".join([quantity_text, moq_cell, pack_cell]))
        final_moq = moq or moq_cell or pack_cell or pack_size
        final_pack = pack_size or pack_cell or moq_cell or final_moq

        price, currency = extract_price_parts(" ".join([price_text, currency_text]).strip())
        header_unit = "kg" if clean_text(cells.get("quantity_kg", "")) else ""
        notes = []
        if quantity_text:
            notes.append(f"original_quantity={quantity_text}")
        if specification:
            notes.append(f"specification={specification}")
        if price:
            notes.append(f"original_price={price}")
        if lead_text:
            notes.append(f"lead_time={lead_text}")
        lines.append(
            " | ".join(
                [
                    product,
                    specification,
                    quantity,
                    unit_text or quantity_unit or header_unit,
                    price,
                    currency or currency_text,
                    lead_text,
                    final_moq,
                    final_pack,
                    "; ".join(notes),
                ]
            )
        )
    return "\n".join(lines)


def split_inline_specification(product: str, specification: str) -> tuple[str, str]:
    if specification:
        return product, specification
    match = re.match(r"^(?P<name>.+?)\s+(?P<spec>\d+(?:\.\d+)?\s*%.*)$", product)
    if not match:
        return product, specification
    name = clean_text(match.group("name"))
    spec = clean_text(match.group("spec"))
    if len(name) < 3:
        return product, specification
    return name, spec


def _row_has_catalogue_signal(cells: dict[str, str]) -> bool:
    product = cells.get("product") or cells.get("product_2") or ""
    product = clean_text(product)
    if len(product.strip()) < 3 or _is_table_noise_text(product):
        return False
    commercial = " ".join(str(value) for key, value in cells.items() if key != "product")
    commercial = clean_text(commercial)
    if _is_table_noise_text(commercial):
        return False
    if cells.get("specification") and len(clean_text(cells.get("specification", ""))) >= 2:
        return True
    return bool(
        re.search(r"\d|USD|INR|Rs\.?|\$|MOQ|kg|g\b|price|rate", commercial, flags=re.IGNORECASE)
        or re.search(r"\b(?:grade|hplc|usp|fcc|nf|extract|ratio|vegan|assay|purity|content)\b", commercial, flags=re.IGNORECASE)
    )


def _is_table_noise_text(text: str) -> bool:
    cleaned = clean_text(text).lower()
    if not cleaned:
        return False
    if re.search(r"\bused\s+for\b", cleaned, flags=re.IGNORECASE):
        return True
    if re.search(r"\boem\s+services?\b", cleaned, flags=re.IGNORECASE):
        return True
    if re.search(r"\b(?:hard\s+capsules?|soft\s+gels?|tablets?)\b", cleaned, flags=re.IGNORECASE):
        return True
    if cleaned in {"product name", "specification", "product", "spec"}:
        return True
    return False


def extract_grid_table_from_image(file_path: Path) -> GridExtractionResult | None:
    try:
        image = Image.open(file_path)
    except Exception:
        logger.debug("Unable to open %s for RapidOCR table extraction", file_path, exc_info=True)
        return None
    return extract_grid_table_from_pil_image(image, file_path.name)
