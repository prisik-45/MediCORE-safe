import csv
import io
import logging
import re
from datetime import UTC, datetime

from backend.app.schemas import ExtractedCatalogItem, clean_optional_text
from backend.app.services.country_detection import UNKNOWN_COUNTRY, normalize_country

CATALOG_TABLE_PARSER_VERSION = "2026-07-27.specification-alignment-v1"
logger = logging.getLogger(__name__)

MONTHS = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}

PACK_PATTERN = re.compile(
    r"(?P<pack_size>\d+(?:\.\d+)?\s*(?:kg|g|mg|ml|l)\s+"
    r"(?:fibre drum|fiber drum|drum|bag|carton|strip|box|bottle|packing|packaging|pack))",
    re.IGNORECASE,
)
ROW_PATTERN = re.compile(
    r"^\s*(?P<ingredient>.+?)\s+"
    r"(?P<pack_size>\d+(?:\.\d+)?\s+(?:kg|g|mg|ml|l)\s+(?:fibre drum|fiber drum|drum|bag|carton|strip|box|bottle|pack))\s+"
    r"(?:INR|Rs\.?)\s*(?P<price>\d+(?:\.\d+)?)\s+"
    r"(?P<qty>[\d,]+(?:\.\d+)?)\s+(?P<unit>kg|g|mg|ml|l|units?|tabs?|tablets?|capsules?)\s+"
    r"(?P<day>\d{1,2})\s+(?P<month>[A-Za-z]{3})"
    r"(?:\s+(?P<status>.*))?\s*$",
    re.IGNORECASE,
)
QUOTE_ROW_PATTERN = re.compile(
    r"^\s*(?P<product>.+?)\s+"
    r"(?P<qty>\d[\d,]*(?:\.\d+)?)"
    r"(?P<qty_extra>(?:\s+(?:(?:MOQ|M\.?O\.?Q\.?)\s*:?\s*"
    r"\d[\d,]*(?:\.\d+)?\s*(?:kg|g|mg|ml|l|units?|packs?)\b|"
    r"\d[\d,]*(?:\.\d+)?\s*(?:kg|g|mg|ml|l|units?|packs?)\s*"
    r"(?:packing|packaging|pack)\b))*)"
    r"\s+"
    r"(?P<price_terms>(?:(?:CIF|FOB|EXW|CNF|C&F)\s+[A-Za-z ./-]+?\s+)*)"
    r"(?:(?P<currency>US\$|\$|USD|INR|Rs\.?|₹|EUR|€)\s*)?"
    r"(?P<price>\d[\d,]*(?:\.\d+)?)"
    r"\s*/\s*(?P<price_unit>[A-Za-z]+)"
    r"(?:\s+(?P<lead>\d+\s*(?:-|to)\s*\d+\s*days?|\d+\s*days?))?"
    r"\s*$",
    re.IGNORECASE,
)
HEADER_CURRENCY_PATTERN = re.compile(r"price\s*\(\s*(?P<currency>[A-Z$₹€]+)\s*\)", re.IGNORECASE)
PRICE_UPDATE_SENTENCE_PATTERNS = (
    re.compile(
        r"\b(?:price|rate)\s+(?:of|for)\s+"
        r"(?P<product>[A-Za-z0-9][A-Za-z0-9 %().,+/'-]{2,120}?)\s+"
        r"(?:is\s+)?(?:updated|revised|changed|set|now|increased|decreased)\s+"
        r"(?:to|at|as)?\s*"
        r"(?:(?P<currency>US\$|\$|USD|INR|Rs\.?|₹|EUR|€|GBP|£)\s*)?"
        r"(?P<price>\d[\d,]*(?:\.\d+)?)\s*/\s*(?P<price_unit>[A-Za-z]+)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?P<product>[A-Za-z0-9][A-Za-z0-9 %().,+/'-]{2,120}?)\s+"
        r"(?:price|rate)\s+(?:is\s+)?(?:updated|revised|changed|set|now|increased|decreased)\s+"
        r"(?:to|at|as)?\s*"
        r"(?:(?P<currency>US\$|\$|USD|INR|Rs\.?|₹|EUR|€|GBP|£)\s*)?"
        r"(?P<price>\d[\d,]*(?:\.\d+)?)\s*/\s*(?P<price_unit>[A-Za-z]+)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:price|rate)\s+(?:of|for)\s+"
        r"(?P<product>[A-Za-z0-9][A-Za-z0-9 %().,+/'-]{2,120}?)\s+"
        r"(?:is|:|-)\s*"
        r"(?:(?P<currency>US\$|\$|USD|INR|Rs\.?|â‚¹|EUR|â‚¬|GBP|Â£)\s*)?"
        r"(?P<price>\d[\d,]*(?:\.\d+)?)\s*/\s*(?P<price_unit>[A-Za-z]+)",
        re.IGNORECASE,
    ),
)
HEADER_UNIT_PATTERN = re.compile(r"(?:quantity|qty|stock|available|vol(?:ume|um)?)\s*(?:\(\s*|\bin\s+)?(?P<unit>[A-Za-z]+)\s*\)?", re.IGNORECASE)
HEADER_CURRENCY_PATTERN = re.compile(r"(?:price|rate|quote|cost|unit price)\s*\(\s*(?P<currency>[A-Z$â‚¹â‚¬]+)\s*\)", re.IGNORECASE)
HEADER_MOQ_UNIT_PATTERN = re.compile(r"(?:MOQ|M\.?O\.?Q\.?|minimum order|min qty|minimum quantity|packing|packaging|pack size|pack)\s*(?:\(\s*|\bin\s+)?(?P<unit>[A-Za-z]+)\s*\)?", re.IGNORECASE)
HEADER_LEAD_TIME_UNIT_PATTERN = re.compile(r"(?:lead\s*time|lead|delivery|dispatch|delivery\s*time)\s*(?:\(\s*|\bin\s+)?(?P<unit>days?|weeks?|months?)\s*\)?", re.IGNORECASE)
HEADER_CURRENCY_PATTERN = re.compile(r"(?:price|rate|quote|cost|unit price|fob|cif|exw|cnf|c&f|ddp|dap)?\s*\(\s*(?P<currency>US\$|USD|INR|Rs\.?|\$|â‚¹|EUR|â‚¬|GBP|Â£|CAD|AUD|SGD|CHF|AED|CNY|JPY)(?:\s*/\s*(?P<unit>[A-Za-z]+))?\s*\)", re.IGNORECASE)
MOQ_PATTERN = re.compile(
    r"\b(?:MOQ|M\.?O\.?Q\.?|minimum\s+order|min\s+qty|minimum\s+quantity|packing|packaging|pack\s+size|pack)\s*:?\s*(?P<moq>\d[\d,]*(?:\.\d+)?)\s*(?P<unit>kg|g|mg|ml|l|units?|packs?|bags?|drums?|cartons?)\b"
    r"|\b(?P<moq2>\d[\d,]*(?:\.\d+)?)\s*(?P<unit2>kg|g|mg|ml|l|units?|packs?|bags?|drums?|cartons?)\s*(?:packing|packaging|pack|bag|drum|carton)\b",
    re.IGNORECASE,
)
PRODUCT_CODE_PATTERN = re.compile(r"^[A-Z]{2,}\d{3,}[A-Z0-9-]*$")
PRODUCT_CODE_HEADER_PATTERN = re.compile(
    r"\b(?:product\s*)?(?:code|sku|item\s*code|item\s*no|ref(?:erence)?|part\s*(?:no|number)|catalog(?:ue)?\s*(?:no|number))\b",
    re.IGNORECASE,
)
CHEMICAL_NAME_HINT_PATTERN = re.compile(
    r"[a-z]{3,}|(?:acid|chloride|citrate|extract|powder|vitamin|sodium|magnesium|zinc|amino|methyl|quinolinium|hcl|usp|bp|ip)\b",
    re.IGNORECASE,
)
STANDALONE_PRICE_PATTERN = re.compile(r"^(?:US\$|\$|USD|INR|Rs\.?|₹|EUR|€)?\s*\d[\d,]*(?:\.\d+)?\s*$", re.IGNORECASE)
FOOTER_OR_HEADER_PATTERN = re.compile(
    r"^(?:real-time raw material|sanyuan jinrui|tel:|add:|jinrui product code|product name|"
    r"product specification description|fob\s*\()",
    re.IGNORECASE,
)
NUMBERED_SPEC_QTY_PATTERN = re.compile(
    r"^\s*\d{1,4}\s+(?P<body>.+?)\s+(?P<qty>\d[\d,]*(?:\.\d+)?)\s*(?P<unit>kg|kgs|g|mg|ml|l|units?|packs?)\s*$",
    re.IGNORECASE,
)
POST_TABLE_BOUNDARY_PATTERN = re.compile(
    r"\s+\b(?:Statement|Disclaimer)\s*:\s+|"
    r"\s+\bThis\s+quotation\s+is\s+provided\s+for\s+informational\b",
    re.IGNORECASE,
)


def parse_catalog_table_text(
    text: str,
    reference_date: datetime | None = None,
    dedupe: bool = True,
) -> list[ExtractedCatalogItem]:
    items: list[ExtractedCatalogItem] = []
    seen: set[tuple[str, float, float, str]] = set()
    context = _table_context(text)
    reference_date = reference_date or datetime.now(UTC)
    structured_spreadsheet = _is_structured_spreadsheet_text(text)

    if not structured_spreadsheet:
        for vertical_item in _parse_vertical_catalog_rows(text, context):
            key = _item_key(vertical_item)
            if not dedupe or key not in seen:
                seen.add(key)
                items.append(vertical_item)

    for table_item in _parse_generic_table(text, context):
        key = _item_key(table_item)
        if not dedupe or key not in seen:
            seen.add(key)
            items.append(table_item)

    if structured_spreadsheet:
        return _valid_catalog_items(items)

    for numbered_item in _parse_numbered_spec_quantity_rows(text):
        key = _item_key(numbered_item)
        if not dedupe or key not in seen:
            seen.add(key)
            items.append(numbered_item)

    for line in _candidate_lines(text):
        cleaned = _clean_line(line)
        if not cleaned:
            continue
        match = ROW_PATTERN.match(cleaned)
        if match:
            month = MONTHS.get(match.group("month").lower())
            if not month:
                continue

            ingredient_name = match.group("ingredient").strip(" -")
            row_item = ExtractedCatalogItem(
                ingredient_name=ingredient_name,
                price_per_unit=float(match.group("price")),
                currency="INR",
                available_qty=float(match.group("qty").replace(",", "")),
                unit=_normalize_unit(match.group("unit")),
                valid_until=_infer_valid_until(int(match.group("day")), month, reference_date),
                notes=(match.group("status") or "").strip() or None,
            )
            if not dedupe or _item_key(row_item) not in seen:
                seen.add(_item_key(row_item))
                items.append(row_item)
            continue

        quote_item = _parse_quotation_row(cleaned, context)
        if quote_item and (not dedupe or _item_key(quote_item) not in seen):
            seen.add(_item_key(quote_item))
            items.append(quote_item)
            continue

        update_item = _parse_price_update_sentence(cleaned, context)
        if update_item and (not dedupe or _item_key(update_item) not in seen):
            seen.add(_item_key(update_item))
            items.append(update_item)
    return _valid_catalog_items(items)


def _is_structured_spreadsheet_text(text: str) -> bool:
    return "[XLSX TABLE]" in text or "[CSV TABLE]" in text


def _parse_vertical_catalog_rows(
    text: str,
    context: dict[str, str | None],
) -> list[ExtractedCatalogItem]:
    rows: list[ExtractedCatalogItem] = []
    lines = [_clean_line(line) for line in text.splitlines() if _clean_line(line)]
    price_unit = _price_unit_context(lines) or context.get("quantity_unit") or "kg"
    currency = _vertical_currency_context(lines) or context.get("currency") or "USD"

    index = 0
    while index < len(lines):
        sku = lines[index]
        if not PRODUCT_CODE_PATTERN.match(sku):
            index += 1
            continue

        name_index = index + 1
        if name_index >= len(lines):
            break
        product_name = lines[name_index]
        if _looks_like_header(product_name) or FOOTER_OR_HEADER_PATTERN.search(product_name):
            index += 1
            continue

        spec_parts: list[str] = []
        price_text: str | None = None
        cursor = name_index + 1
        while cursor < len(lines):
            line = lines[cursor]
            if PRODUCT_CODE_PATTERN.match(line):
                break
            if STANDALONE_PRICE_PATTERN.match(line):
                price_text = line
                cursor += 1
                break
            if not FOOTER_OR_HEADER_PATTERN.search(line):
                spec_parts.append(line)
            cursor += 1

        price = _number_from_text(price_text)
        if price is not None:
            raw_price = _format_original_price(price_text or str(price), currency, price_unit)
            source = " ".join([sku, product_name, *spec_parts, price_text or str(price)])
            notes = _notes(
                supplier_sku=sku,
                specification=" ".join(spec_parts).replace(";", ",") if spec_parts else None,
                original_price=raw_price,
                source=source[:500].replace(";", ","),
            )
            rows.append(
                ExtractedCatalogItem(
                    ingredient_name=product_name,
                    specification=" ".join(spec_parts).replace(";", ",") if spec_parts else None,
                    price_per_unit=price,
                    currency=currency,
                    available_qty=None,
                    unit=price_unit,
                    notes=notes,
                )
            )

        index = max(cursor, index + 1)
    return rows


def _parse_numbered_spec_quantity_rows(text: str) -> list[ExtractedCatalogItem]:
    rows: list[ExtractedCatalogItem] = []
    for line in (_clean_line(line) for line in text.splitlines()):
        if not line:
            continue
        if "|" in line or "\t" in line:
            continue
        match = NUMBERED_SPEC_QTY_PATTERN.match(line)
        if not match:
            continue
        product, specification = _split_product_specification(match.group("body"))
        if not product:
            continue
        rows.append(
            ExtractedCatalogItem(
                ingredient_name=product,
                specification=specification,
                available_qty=_number(match.group("qty")),
                unit=_normalize_unit(match.group("unit")),
                notes=_notes(
                    specification=specification.replace(";", ",") if specification else None,
                    original_quantity=f"{match.group('qty')} {match.group('unit')}",
                    source=line[:500].replace(";", ","),
                ),
            )
        )
    return rows


def _split_product_specification(body: str) -> tuple[str, str | None]:
    text = _clean_line(body)
    if not text:
        return "", None

    # Specifications usually begin with assay/purity markers, percentages, metals, ratios, or ppm values.
    marker = re.search(
        r"(?=(?:Pb|Fe|Zn|Mg|Ca|Na|K|N)(?=\b|\d|[+-])|(?:Assay|Purity|Content)\b|\d+(?:\.\d+)?\s*%|\d+\s*:\s*\d+|[<>]=?)",
        text,
        flags=re.IGNORECASE,
    )
    if marker and marker.start() > 0:
        product = text[: marker.start()].strip(" -")
        specification = text[marker.start() :].strip(" -")
        paren_split = _split_spec_after_trailing_parenthetical(product, specification)
        if paren_split:
            return paren_split
        if product and specification:
            return product, specification

    parts = text.split()
    if len(parts) >= 2 and parts[0].lower() == parts[1].lower():
        return parts[0], " ".join(parts[1:])
    return text, None


def _split_spec_after_trailing_parenthetical(product: str, specification: str) -> tuple[str, str] | None:
    if not specification or not re.match(r"^[<>]?\d", specification):
        return None
    close_index = product.rfind(")")
    if close_index < 0 or close_index >= len(product) - 1:
        return None
    product_name = product[: close_index + 1].strip(" -")
    spec_prefix = product[close_index + 1 :].strip(" -")
    if not product_name or not spec_prefix:
        return None
    if not re.search(r"[A-Za-z]", spec_prefix):
        return None
    return product_name, f"{spec_prefix} {specification}".strip()


def extract_pack_size(line: str) -> str | None:
    match = PACK_PATTERN.search(line)
    return match.group("pack_size") if match else None


def _clean_line(line: str) -> str:
    return re.sub(r"\s+", " ", line).strip()


def _normalize_name(name: str) -> str:
    normalized = name.lower().strip()
    normalized = re.sub(r"\s+api$", "", normalized)
    return normalized


def _normalize_unit(unit: str) -> str:
    unit = unit.lower().strip()
    if unit in {"kgs", "kilogram", "kilograms"}:
        return "kg"
    if unit in {"litre", "liter", "litres", "liters"}:
        return "l"
    if unit in {"packs", "pack"}:
        return "pack"
    if unit in {"units", "unit"}:
        return "unit"
    if unit in {"tabs", "tab", "tablets", "tablet"}:
        return "tablet"
    if unit in {"capsules", "capsule"}:
        return "capsule"
    return unit


def _infer_valid_until(day: int, month: int, reference_date: datetime) -> datetime:
    year = reference_date.year
    candidate = datetime(year, month, day, tzinfo=UTC)
    if candidate.date() < reference_date.date():
        candidate = datetime(year + 1, month, day, tzinfo=UTC)
    return candidate


def _table_context(text: str) -> dict[str, str | None]:
    context: dict[str, str | None] = {"currency": None, "quantity_unit": None}
    for line in text.splitlines():
        cleaned = _clean_line(line)
        if not cleaned:
            continue
        currency_match = HEADER_CURRENCY_PATTERN.search(cleaned)
        if currency_match:
            context["currency"] = _currency_code(currency_match.group("currency"))
        unit_match = HEADER_UNIT_PATTERN.search(cleaned)
        if unit_match:
            context["quantity_unit"] = _normalize_unit(unit_match.group("unit"))
        if context["currency"] and context["quantity_unit"]:
            break
    return context


def _parse_quotation_row(line: str, context: dict[str, str | None]) -> ExtractedCatalogItem | None:
    if _price_occurrences(line) > 1:
        return None
    if " NA" in f" {line.upper()} " and "/" not in line:
        return None
    match = QUOTE_ROW_PATTERN.match(line)
    if not match:
        return None

    product = _strip_leading_date_customer(match.group("product"))
    if not product or _looks_like_header(product):
        return None

    qty = _number(match.group("qty"))
    price = _number(match.group("price"))
    if qty is None or price is None:
        return None

    price_unit = _normalize_unit(match.group("price_unit"))
    qty_unit = context.get("quantity_unit") or price_unit
    qty_extra = (match.group("qty_extra") or "").strip()
    price_terms = (match.group("price_terms") or "").strip()
    lead_text = (match.group("lead") or "").strip()
    currency = _currency_code(match.group("currency") or context.get("currency") or "INR")
    moq, moq_unit = _extract_moq(qty_extra)
    notes = _notes(
        original_quantity=f"{match.group('qty')} {qty_unit}".strip(),
        quantity_extra=qty_extra,
        original_price=_original_price(match, currency),
        price_terms=price_terms,
        lead_time=lead_text,
        moq_unit=moq_unit,
    )

    return ExtractedCatalogItem(
        ingredient_name=product,
        price_per_unit=price,
        currency=currency,
        available_qty=qty,
        unit=qty_unit or price_unit,
        lead_time_days=_lead_time_days(lead_text),
        lead_time_text=lead_text or None,
        moq=moq,
        notes=notes,
    )


def _parse_price_update_sentence(line: str, context: dict[str, str | None]) -> ExtractedCatalogItem | None:
    for pattern in PRICE_UPDATE_SENTENCE_PATTERNS:
        match = pattern.search(line)
        if not match:
            continue

        product = _clean_price_update_product(match.group("product"))
        if not product or _looks_like_header(product):
            continue
        product_name, specification = _split_product_specification(product)
        if not product_name:
            continue

        price = _number(match.group("price"))
        if price is None:
            continue

        price_unit = _normalize_unit(match.group("price_unit"))
        currency = _currency_code(match.group("currency") or context.get("currency") or "USD")
        original_price = _display_price_with_header_currency(match.group("price"), currency, price_unit)
        moq, moq_unit = _extract_moq(line)
        return ExtractedCatalogItem(
            ingredient_name=product_name,
            specification=specification,
            price_per_unit=price,
            currency=currency,
            available_qty=None,
            unit=price_unit,
            moq=moq,
            notes=_notes(
                original_price=original_price,
                moq_unit=moq_unit,
                source=line[:500].replace(";", ","),
            ),
        )
    return None


def _parse_generic_table(text: str, context: dict[str, str | None]) -> list[ExtractedCatalogItem]:
    rows: list[ExtractedCatalogItem] = []
    lines = [_clean_line(line) for line in text.splitlines() if _clean_line(line)]
    header: list[str] | None = None
    header_map: dict[str, int] = {}
    header_meta: dict[int, dict[str, str | None]] = {}
    source_sheet: str | None = None
    source_table: str | None = None

    for line in lines:
        source_match = re.match(
            r"^\[XLSX TABLE\]\s+Sheet:\s*(?P<sheet>.*?)\s+Table:\s*(?P<table>\d+)\b",
            line,
            flags=re.IGNORECASE,
        )
        if source_match:
            source_sheet = source_match.group("sheet").strip()
            source_table = source_match.group("table").strip()
            header = None
            header_map = {}
            header_meta = {}
            continue

        parts = _split_table_line(line)
        if len(parts) < 2:
            continue
        if _is_markdown_table_separator(parts):
            continue

        has_numeric_data = any(_number_from_text(p) is not None for p in parts[1:])
        possible_map = _header_map(parts)
        is_header_candidate = (
            _catalogue_header_has_required_shape(parts, possible_map)
            and not has_numeric_data
        )

        if is_header_candidate or not header:
            if is_header_candidate:
                header = parts
                header_map = possible_map
                header_meta = {index: _header_cell_metadata(part) for index, part in enumerate(header)}
                continue

        if not header or not header_map:
            continue

        if len(parts) < len(header):
            parts = parts + [""] * (len(header) - len(parts))
        parts = _trim_post_table_text_from_row(parts, len(header))

        name, name_index = _resolved_name_cell(parts, header, header_map)
        if not name or _looks_like_header(name):
            continue
        supplier_sku = _supplier_sku_from_row(parts, header)

        price_header_text = header[header_map["price"]] if header and "price" in header_map else ""
        price_header_meta = header_meta.get(header_map["price"], {}) if "price" in header_map else {}
        raw_price_cell = _cell(parts, header_map.get("price"))
        price_cell_is_price = _is_price_value(raw_price_cell, price_header_text)
        price = _number_from_text(raw_price_cell) if price_cell_is_price else None
        price_unit = (
            _normalize_unit(str(price_header_meta.get("unit") or ""))
            or _unit_from_text(price_header_text)
            or (_unit_from_text(raw_price_cell) if price_cell_is_price else None)
        )

        raw_qty = _cell(parts, header_map.get("qty"))
        qty = _number_from_text(raw_qty) if "qty" in header_map else None
        header_qty_text = header[header_map["qty"]] if header and "qty" in header_map else ""
        qty_header_meta = header_meta.get(header_map["qty"], {}) if "qty" in header_map else {}
        header_unit = qty_header_meta.get("unit") or _header_unit_from_text(header_qty_text)

        unit = _normalize_unit(
            _cell(parts, header_map.get("unit"))
            or _unit_from_text(raw_qty)
            or (header_unit if header_unit else None)
            or _unit_from_text(header_qty_text)
            or context.get("quantity_unit")
            or ""
        )
        if qty is not None and not unit:
            unit = "unit"
        if not unit and price_unit:
            unit = price_unit

        currency_source = (
            _cell(parts, header_map.get("currency"))
            or _currency_from_text(raw_price_cell)
            or str(price_header_meta.get("currency") or "")
            or _currency_from_text(price_header_text)
            or (context.get("currency") if price is not None else "")
            or ("USD" if price is not None and price_unit else "")
        )
        currency = _currency_code(currency_source) if currency_source else ""
        raw_moq = _cell(parts, header_map.get("moq"))
        moq = _number_from_text(raw_moq) if "moq" in header_map else None
        moq_header_text = header[header_map["moq"]] if header and "moq" in header_map else ""
        moq_header_meta = header_meta.get(header_map["moq"], {}) if "moq" in header_map else {}
        moq_unit = str(moq_header_meta.get("unit") or "") or _header_moq_unit(moq_header_text) or _unit_from_text(raw_moq) or unit
        raw_lead_time = clean_optional_text(_cell(parts, header_map.get("lead_time")))
        lead_time_header_text = header[header_map["lead_time"]] if header and "lead_time" in header_map else ""
        lead_header_meta = header_meta.get(header_map["lead_time"], {}) if "lead_time" in header_map else {}
        lead_time_unit = str(lead_header_meta.get("unit") or "") or _header_lead_time_unit(lead_time_header_text)
        lead_time_text = _display_with_header_unit(raw_lead_time, lead_time_unit)
        lead_time_days = _lead_time_days(lead_time_text or raw_lead_time)
        specification = clean_optional_text(_cell(parts, header_map.get("specification")))
        notes_parts = []
        if source_sheet:
            notes_parts.append(f"source_sheet={source_sheet.replace(';', ',')}")
        if source_table:
            notes_parts.append(f"source_table={source_table}")
        if specification:
            notes_parts.append(f"specification={specification.replace(';', ',')}")
        pack = clean_optional_text(_cell(parts, header_map.get("pack")))
        if pack:
            notes_parts.append(f"packaging={pack}")
        raw_price = clean_optional_text(raw_price_cell)
        if raw_price and price_cell_is_price:
            notes_parts.append(f"original_price={_display_price_with_header_currency(raw_price, currency, price_unit, price_header_text)}")
        elif raw_price and not specification and _looks_like_specification_value(raw_price):
            specification = raw_price
            notes_parts.append(f"specification={raw_price.replace(';', ',')}")
        raw_qty_note = clean_optional_text(raw_qty)
        if raw_qty_note:
            original_quantity = raw_qty_note
            if unit and not _unit_from_text(raw_qty_note):
                original_quantity = f"{raw_qty_note} {unit}"
            notes_parts.append(f"original_quantity={original_quantity}")
        raw_moq_note = clean_optional_text(raw_moq)
        if raw_moq_note:
            notes_parts.append(f"moq={_display_with_header_unit(raw_moq_note, moq_unit)}")
        if lead_time_text:
            notes_parts.append(f"lead_time={lead_time_text}")

        rows.append(
            ExtractedCatalogItem(
                ingredient_name=name,
                specification=specification,
                price_per_unit=price,
                currency=currency,
                available_qty=qty,
                unit=unit,
                lead_time_days=lead_time_days,
                lead_time_text=lead_time_text,
                moq=moq,
                supplier_sku=supplier_sku if name_index != _product_code_column_index(header) else None,
                notes="; ".join(notes_parts) if notes_parts else None,
            )
        )

    return rows


def _split_table_line(line: str) -> list[str]:
    stripped = line.strip().strip("|")
    if not stripped:
        return []
    if "\t" in stripped:
        return [part.strip() for part in stripped.split("\t")]
    if "|" in stripped:
        return [part.strip() for part in stripped.split("|")]
    if "," in stripped or ";" in stripped:
        try:
            dialect = csv.Sniffer().sniff(stripped, delimiters=",;")
            reader = csv.reader(io.StringIO(stripped), dialect=dialect)
            row = next(reader, None)
            if row and len(row) >= 2:
                return [part.strip() for part in row]
        except Exception:
            pass
    return [part.strip() for part in re.split(r"\s{2,}", stripped) if part.strip()]


def _is_markdown_table_separator(parts: list[str]) -> bool:
    return bool(parts) and all(
        re.fullmatch(r":?-{3,}:?", part.strip()) for part in parts if part.strip()
    )


def _resolved_name_cell(
    parts: list[str],
    header: list[str] | None,
    header_map: dict[str, int],
) -> tuple[str, int | None]:
    mapped_index = header_map.get("name")
    mapped_name = _cell(parts, mapped_index)
    if is_valid_ingredient_name(mapped_name):
        return mapped_name, mapped_index

    # Converted/OCR tables sometimes let a product-code column win the generic
    # "product" alias. Recover by scanning non-code columns for a valid product
    # name instead of discarding the whole row.
    candidate_indexes: list[int] = []
    if header:
        for index, header_text in enumerate(header):
            if _is_product_code_header(header_text):
                continue
            if _header_cell_metadata(header_text).get("field") == "name":
                candidate_indexes.append(index)
    candidate_indexes.extend(index for index in range(len(parts)) if index not in candidate_indexes)

    blocked_indexes = {
        index
        for key, index in header_map.items()
        if key in {"price", "qty", "unit", "currency", "moq", "lead_time", "pack", "specification"}
    }
    for index in candidate_indexes:
        if index in blocked_indexes:
            continue
        cell = _cell(parts, index)
        if PRODUCT_CODE_PATTERN.match(cell):
            continue
        if is_valid_ingredient_name(cell):
            return cell, index
    return mapped_name, mapped_index


def _supplier_sku_from_row(parts: list[str], header: list[str] | None) -> str | None:
    code_index = _product_code_column_index(header)
    if code_index is None:
        return None
    value = clean_optional_text(_cell(parts, code_index))
    return value if value and PRODUCT_CODE_PATTERN.match(value) else None


def _product_code_column_index(header: list[str] | None) -> int | None:
    if not header:
        return None
    for index, header_text in enumerate(header):
        if _is_product_code_header(header_text):
            return index
    return None


def _is_product_code_header(header: str | None) -> bool:
    return bool(PRODUCT_CODE_HEADER_PATTERN.search(str(header or "").lower()))


def _trim_post_table_text_from_row(parts: list[str], expected_columns: int) -> list[str]:
    trimmed = list(parts[:expected_columns])
    for index, cell in enumerate(trimmed):
        match = POST_TABLE_BOUNDARY_PATTERN.search(cell)
        if match:
            trimmed[index] = cell[: match.start()].strip()
            for trailing_index in range(index + 1, len(trimmed)):
                trimmed[trailing_index] = ""
            break
    return trimmed


def _header_map(parts: list[str]) -> dict[str, int]:
    aliases = [
        ("price", ("price", "rate", "quote", "cost", "unit price", "price/unit", "rate/unit", "fob", "cif", "exw", "cnf", "c&f", "ddp", "dap", "$/kg", "/kg", "$/g")),
        ("name", ("product name", "item name", "ingredient name", "material name", "chemical name", "raw material", "product", "item", "ingredient", "chemical", "material", "medicine", "api", "name", "rm", "particulars", "details", "title", "drug", "compound", "article")),
        ("qty", ("qty", "quantity", "quantities", "stock", "available", "availability", "balance", "volume", "volum", "vol", "qnty", "q'ty", "count", "batch size", "lot size", "offer qty", "supplied qty", "order qty", "total qty", "stock qty", "avail qty", "qty avail")),
        ("unit", ("unit of measure", "pack unit", "pkg unit", "uom", "unit")),
        ("specification", ("product specification description", "specification description", "specification", "spec", "description", "assay", "purity", "grade", "content", "quality", "standard")),
        ("currency", ("currency", "curr")),
        ("moq", ("moq", "m.o.q", "minimum order", "min order", "min qty", "minimum quantity", "minimum order quantity", "moq (kg)", "pack", "packing", "packaging", "package", "pack size", "packing (moq)", "moq / packing")),
        ("lead_time", ("lead", "delivery", "dispatch", "lead time", "delivery time", "dispatch time", "ship time", "shipping time", "turnaround")),
        ("pack", ("pack", "packing", "packaging", "package", "pack size", "moq", "m.o.q", "minimum order", "min order", "min qty", "minimum quantity", "minimum order quantity", "packing (moq)", "moq / packing")),
    ]
    mapped: dict[str, int] = {}
    for index, part in enumerate(parts):
        lowered = part.lower().strip()
        if _is_product_code_header(lowered):
            continue
        inferred = _header_cell_metadata(part).get("field")
        if inferred and inferred not in mapped:
            mapped[inferred] = index
            continue
        if lowered in {"rate/unit", "price/unit", "price/kg", "rate/kg", "price (usd)", "price (inr)"}:
            if "price" not in mapped:
                mapped["price"] = index
            continue

        for key, names in aliases:
            if key not in mapped and any(name in lowered for name in names):
                mapped[key] = index

    if "name" not in mapped:
        for index, part in enumerate(parts):
            lowered = part.lower().strip()
            if lowered in {"description", "item description", "product description"}:
                mapped["name"] = index
                break

    return mapped


def _catalogue_header_has_required_shape(parts: list[str], mapped: dict[str, int]) -> bool:
    if "name" not in mapped:
        return False
    if any(
        key in mapped
        for key in ("price", "qty", "specification", "unit", "currency", "moq", "lead_time", "pack")
    ):
        return True
    name_index = mapped["name"]
    return any(
        index != name_index and _is_index_header(part)
        for index, part in enumerate(parts)
    )


def _is_index_header(value: str | None) -> bool:
    lowered = re.sub(r"[^a-z0-9#]+", " ", str(value or "").lower()).strip()
    return lowered in {
        "#",
        "no",
        "no.",
        "s no",
        "sr no",
        "sl no",
        "serial no",
        "serial",
        "s n",
        "sn",
        "id",
    }


def _header_cell_metadata(header: str | None) -> dict[str, str | None]:
    cleaned = _clean_header_text(header)
    lowered = cleaned.lower()
    currency = _currency_from_text(cleaned)
    unit = _unit_from_price_header(cleaned) or _header_unit_from_text(cleaned)
    field: str | None = None

    if re.search(r"\b(?:fob|cif|exw|cnf|c&f|ddp|dap|price|rate|quote|cost)\b|[$â‚¹â‚¬Â£]\s*/|(?:usd|inr|eur|gbp|cad|aud|sgd|chf|aed|cny|jpy)\s*/", lowered, re.IGNORECASE):
        field = "price"
    elif re.search(r"\b(?:moq|m\.?\s*o\.?\s*q\.?|minimum\s+order|minimum\s+quantity|min\s+qty|min\s+order|pack|packing|packaging|pack\s*size)\b", lowered):
        field = "moq"
    elif re.search(r"\b(?:lead|delivery|dispatch|shipping|ship\s*time|turnaround)\b", lowered):
        field = "lead_time"
    elif re.search(r"\b(?:qty|quantity|stock|available|availability|balance|vol(?:ume|um)?|offer\s*qty|total\s*qty)\b", lowered):
        field = "qty"
    elif re.search(r"\b(?:specification|spec|description|assay|purity|grade|content|quality|standard)\b", lowered):
        field = "specification"
    elif re.search(r"\b(?:currency|curr)\b", lowered):
        field = "currency"
    elif re.search(r"\b(?:unit|uom)\b", lowered):
        field = "unit"
    elif re.search(r"\b(?:product|item|ingredient|chemical|material|medicine|api|name|particulars|details|title|drug|compound|article)\b", lowered):
        field = "name"

    return {"field": field, "currency": _currency_code(currency) if currency else None, "unit": unit}


def _clean_header_text(header: str | None) -> str:
    text = str(header or "")
    replacements = {
        "（": "(",
        "）": ")",
        "／": "/",
        "Â£": "GBP",
        "â‚¹": "INR",
        "â‚¬": "EUR",
    }
    for source, target in replacements.items():
        text = text.replace(source, target)
    return re.sub(r"\s+", " ", text).strip()


def _unit_from_price_header(header: str | None) -> str | None:
    match = re.search(r"/\s*(kg|kgs|kilogram|kilograms|g|grams|mg|ml|l|litre|liter|units?|packs?|bags?|drums?|mt|tons?)\b", header or "", flags=re.IGNORECASE)
    return _normalize_unit(match.group(1)) if match else None


def _header_unit_from_text(header: str | None) -> str | None:
    if not header:
        return None
    paren_match = re.search(r"\(\s*(?:in\s+)?(?:[A-Z]{2,4}|US\$|Rs\.?|\$|INR|USD|EUR|GBP|CAD|AUD|SGD|CHF|AED|CNY|JPY)?\s*/?\s*(kg|kgs|kilogram|kilograms|g|grams|mg|ml|l|litre|liter|days?|weeks?|months?|units?|packs?|bags?|drums?|mt|tons?)\s*\)", header, flags=re.IGNORECASE)
    if paren_match:
        return _normalize_unit(paren_match.group(1))
    in_match = re.search(r"\bin\s+(kg|kgs|kilogram|kilograms|g|grams|mg|ml|l|litre|liter|days?|weeks?|months?|units?|packs?|bags?|drums?|mt|tons?)\b", header, flags=re.IGNORECASE)
    if in_match:
        return _normalize_unit(in_match.group(1))
    return None


def is_valid_ingredient_name(name: object) -> bool:
    value = clean_optional_text(name)
    if not value:
        return False
    value = value.strip()
    lowered = value.lower()
    if _looks_like_header(value):
        return False
    if re.search(
        r"\b(?:assay|purity|content|grade|standard|specification|description)\s*:",
        value,
        flags=re.IGNORECASE,
    ):
        return False
    if PRODUCT_CODE_PATTERN.match(value):
        return False
    if PRODUCT_CODE_HEADER_PATTERN.search(value):
        return False
    if STANDALONE_PRICE_PATTERN.match(value):
        return False
    if _number_from_text(value) is not None and not re.search(r"[A-Za-z]", value):
        return False
    if lowered in {"product", "product name", "ingredient", "ingredient name", "specification", "description", "quantity", "qty", "price", "moq", "unit"}:
        return False
    # Addresses are commonly present beside product tables in email and PDF
    # extraction.  A standalone country is never a catalogue ingredient, so
    # reject it before it can be written to catalog_items.
    if normalize_country(value) != UNKNOWN_COUNTRY:
        return False
    if lowered in {"address", "country", "origin", "telephone", "phone", "email", "website", "contact", "postal code", "postcode"}:
        return False
    if len(value) < 3:
        return False
    if CHEMICAL_NAME_HINT_PATTERN.search(value):
        return True
    if re.search(r"[A-Za-z]", value) and len(re.findall(r"[A-Za-z]{2,}", value)) >= 2:
        return not re.search(
            r"\b(?:contact|email|phone|tel|website|address|notes?|supplier|company|inventory|catalogue|catalog|"
            r"total|updated|price\s+list|sheet|table|organic botanicals|conventional botanicals|nutraceuticals)\b",
            lowered,
        )
    return False


def _valid_catalog_items(items: list[ExtractedCatalogItem]) -> list[ExtractedCatalogItem]:
    valid: list[ExtractedCatalogItem] = []
    for item in items:
        if is_valid_ingredient_name(item.ingredient_name):
            valid.append(item)
        else:
            logger.info("Skipping extracted row with invalid ingredient name: %r", item.ingredient_name)
    return valid


def _cell(parts: list[str], index: int | None) -> str:
    if index is None or index >= len(parts):
        return ""
    return parts[index].strip()


def _currency_code(raw: str | None) -> str:
    value = (raw or "").strip().upper()
    if value in {"$", "US$", "USD"}:
        return "USD"
    if value in {"₹", "RS", "RS.", "INR"}:
        return "INR"
    if value in {"€", "EUR"}:
        return "EUR"
    return value or ""


def _currency_from_text(raw: str | None) -> str | None:
    if not raw:
        return None
    code_match = re.search(r"(?<![A-Z])(?:USD|INR|EUR|GBP|CAD|AUD|SGD|CHF|AED|CNY|JPY|Rs\.?)(?![A-Z])", raw, flags=re.IGNORECASE)
    if code_match:
        return code_match.group(0)
    match = re.search(r"(US\$|\$|₹|€|(?<![A-Z])(?:USD|INR|EUR|Rs\.?)(?![A-Z]))", raw, flags=re.IGNORECASE)
    return match.group(1) if match else None


def _vertical_currency_context(lines: list[str]) -> str | None:
    for line in lines[:30]:
        detected = _currency_from_text(line)
        if detected:
            return _currency_code(detected)
    return None


def _price_unit_context(lines: list[str]) -> str | None:
    for line in lines[:30]:
        match = re.search(r"/\s*(kg|g|mg|ml|l|litre|liter|units?|tabs?|tablets?|capsules?|packs?)\b", line, flags=re.IGNORECASE)
        if match:
            return _normalize_unit(match.group(1))
    return None


def _format_original_price(price_text: str, currency: str, price_unit: str) -> str:
    cleaned_price = (price_text or "").strip()
    if _currency_from_text(cleaned_price):
        prefix = ""
    elif currency == "USD":
        prefix = "$"
    elif currency == "INR":
        prefix = "INR "
    elif currency == "EUR":
        prefix = "EUR "
    else:
        prefix = f"{currency} "
    return f"{prefix}{cleaned_price}/{price_unit}".strip()


def _number(raw: str | None) -> float | None:
    if raw is None:
        return None
    try:
        return float(raw.replace(",", ""))
    except ValueError:
        return None


def _number_from_text(raw: str | None) -> float | None:
    if not clean_optional_text(raw):
        return None
    match = re.search(r"\d[\d,]*(?:\.\d+)?", raw)
    return _number(match.group(0)) if match else None


def _is_price_value(value: str | None, header: str | None = None) -> bool:
    cleaned = clean_optional_text(value)
    if not cleaned:
        return False
    lowered = cleaned.lower()
    if lowered in {"na", "n/a", "not available", "no quote", "no offer", "tbd", "to be confirmed"}:
        return True
    if _looks_like_specification_value(cleaned):
        return False
    if _looks_like_lead_time_value(cleaned) or _looks_like_moq_value(cleaned):
        return False
    if _currency_from_text(cleaned):
        return _number_from_text(cleaned) is not None or _looks_like_text_price(cleaned)
    if re.search(r"\b(?:fob|cif|exw|cnf|c&f|ddp|dap|price|rate|quote|offer)\b", cleaned, flags=re.IGNORECASE):
        return _number_from_text(cleaned) is not None or _looks_like_text_price(cleaned)
    if re.search(r"\b(?:on request|upon request|ask|negotiable|market price|current price|quote)\b", lowered):
        return True
    if re.search(r"\d[\d,]*(?:\.\d+)?\s*/\s*(?:kg|g|mg|ml|l|unit|pack|bag|drum|mt|ton)\b", cleaned, flags=re.IGNORECASE):
        return True
    if _number_from_text(cleaned) is None:
        return False
    # A numeric-only cell under a price/rate/commercial header is a valid price,
    # including headers such as FOB($/kg) where currency/unit live in the header.
    return bool(
        re.search(
            r"\b(?:price|rate|quote|cost|fob|cif|exw|cnf|c&f|ddp|dap)\b|[$]\s*/|/\s*(?:kg|g|mg|ml|l|unit|pack|bag|drum|mt|ton)",
            header or "",
            flags=re.IGNORECASE,
        )
    )


def _looks_like_text_price(value: str) -> bool:
    return bool(re.search(r"\b(?:on request|upon request|ask|negotiable|market price|quote)\b", value, flags=re.IGNORECASE))


def _looks_like_specification_value(value: str | None) -> bool:
    cleaned = clean_optional_text(value)
    if not cleaned:
        return False
    return bool(
        re.search(
            r"\b(?:assay|purity|content|grade|spec(?:ification)?|standard|complies?|mesh|appearance|moisture|ash|"
            r"acid value|enzyme activity|dry basis|usp|ep|bp|ip|food grade)\b\s*:?",
            cleaned,
            flags=re.IGNORECASE,
        )
    )


def _looks_like_lead_time_value(value: str | None) -> bool:
    cleaned = clean_optional_text(value)
    if not cleaned:
        return False
    return bool(
        re.search(r"\b(?:lead|delivery|dispatch|ship|ready)\b", cleaned, flags=re.IGNORECASE)
        or re.fullmatch(r"\d+\s*(?:-|to|~)\s*\d+\s*days?", cleaned, flags=re.IGNORECASE)
        or re.fullmatch(r"\d+\s*(?:days?|weeks?|months?)", cleaned, flags=re.IGNORECASE)
    )


def _looks_like_moq_value(value: str | None) -> bool:
    cleaned = clean_optional_text(value)
    if not cleaned:
        return False
    return bool(re.search(r"\b(?:moq|m\.?\s*o\.?\s*q\.?|minimum\s+order|min(?:imum)?\s+qty)\b", cleaned, flags=re.IGNORECASE))


def _unit_from_text(raw: str | None) -> str | None:
    if not raw:
        return None
    match = re.search(
        r"(?:(?<=\d)|(?<=\s)|(?<=\b))(kg|kgs|kilogram|kilograms|g|grams|mg|ml|l|litre|liter|litres|liters|units?|tabs?|tablets?|capsules?|packs?|bags?|drums?|cartons?|boxes?|strips?|bottles?|mt|tons?)\b",
        raw,
        flags=re.IGNORECASE,
    )
    return _normalize_unit(match.group(1)) if match else None


def _header_moq_unit(header: str | None) -> str | None:
    match = HEADER_MOQ_UNIT_PATTERN.search(header or "")
    return _normalize_unit(match.group("unit")) if match else None


def _header_lead_time_unit(header: str | None) -> str | None:
    match = HEADER_LEAD_TIME_UNIT_PATTERN.search(header or "")
    if not match:
        return None
    value = match.group("unit").lower().strip()
    if value.startswith("day"):
        return "days"
    if value.startswith("week"):
        return "weeks"
    if value.startswith("month"):
        return "months"
    return value


def _display_with_header_unit(value: str | None, unit: str | None) -> str | None:
    cleaned = clean_optional_text(value)
    if not cleaned:
        return None
    if not unit or re.search(r"[A-Za-z]", cleaned):
        return cleaned
    return f"{cleaned} {unit}"


def _display_price_with_header_currency(value: str, currency: str, unit: str | None = None, header: str | None = None) -> str:
    cleaned = value.strip()
    display = cleaned
    if not _currency_from_text(cleaned):
        if currency == "USD":
            display = f"${cleaned}"
        elif currency == "INR":
            display = f"INR {cleaned}"
        elif currency == "EUR":
            display = f"EUR {cleaned}"
        else:
            display = f"{currency} {cleaned}".strip()
    price_unit = unit or _unit_from_price_header(header)
    if price_unit and "/" not in display:
        display = f"{display}/{price_unit}"
    return display.strip()


def _extract_moq(text: str) -> tuple[float | None, str | None]:
    if not text:
        return None, None
    match = MOQ_PATTERN.search(text)
    if match:
        moq_str = match.group("moq") or match.group("moq2")
        unit_str = match.group("unit") or match.group("unit2")
        return _number(moq_str), _normalize_unit(unit_str) if unit_str else None
    pack_sz = extract_pack_size(text)
    if pack_sz:
        num_m = re.search(r"(\d[\d,]*(?:\.\d+)?)", pack_sz)
        unit_m = re.search(r"(kg|g|mg|ml|l|units?|packs?|bags?|drums?|cartons?)", pack_sz, re.IGNORECASE)
        if num_m:
            return _number(num_m.group(1)), _normalize_unit(unit_m.group(1)) if unit_m else None
    return None, None


def _lead_time_days(text: str) -> int | None:
    if not text:
        return None
    if re.search(r"\d+\s*(?:-|–|to)\s*\d+", text, flags=re.IGNORECASE):
        return None
    match = re.search(r"(\d+)", text)
    return int(match.group(1)) if match else None


def _original_price(match: re.Match[str], currency: str) -> str:
    raw_currency = match.group("currency") or currency
    return f"{raw_currency}{match.group('price')}/{match.group('price_unit')}"


def _notes(**parts: str | None) -> str | None:
    values = [f"{key}={value}" for key, value in parts.items() if value]
    return "; ".join(values) if values else None


def _strip_leading_date_customer(product: str) -> str:
    cleaned = re.sub(r"^\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\s+", "", product).strip()
    return re.sub(
        r"^[A-Za-z0-9&.,' -]{2,}?\b(?:Inc\.?|Ltd\.?|LLC|Corp\.?|Corporation|Pvt\.?\s+Ltd\.?)\s+",
        "",
        cleaned,
        flags=re.IGNORECASE,
    ).strip()


def _clean_price_update_product(product: str) -> str:
    cleaned = _strip_leading_date_customer(product)
    cleaned = re.sub(r"^\s*(?:the|for|item|product|material|ingredient)\s+", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.split(r"\s+(?:is|has been|was)\s*$", cleaned, flags=re.IGNORECASE)[0]
    return cleaned.strip(" -_:.,")


def _looks_like_header(product: str) -> bool:
    lowered = product.lower()
    if re.match(r"^\d+\s*(?:-|to)\s*\d+\s*days?\b", lowered):
        return True
    return any(header in lowered for header in ("product", "customer", "quantity", "price"))


def _candidate_lines(text: str) -> list[str]:
    lines = [_clean_line(line) for line in text.splitlines()]
    lines = [line for line in lines if line]
    candidates: list[str] = []
    for index in range(len(lines)):
        max_end = min(index + 5, len(lines))
        for end in range(max_end, index, -1):
            candidates.append(" ".join(lines[index:end]))
    return candidates


def _item_key(item: ExtractedCatalogItem) -> tuple[str, str, float, float, str]:
    return (
        item.ingredient_name.lower(),
        (item.specification or "").strip().lower(),
        float(item.available_qty or 0),
        float(item.price_per_unit or 0),
        item.currency,
    )


def _price_occurrences(line: str) -> int:
    return len(
        re.findall(
            r"(?:(?:US\$|\$|USD|INR|Rs\.?|₹|EUR|€)\s*)?\d[\d,]*(?:\.\d+)?\s*/\s*[A-Za-z]+",
            line,
            flags=re.IGNORECASE,
        )
    )
