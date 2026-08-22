import re
from dataclasses import dataclass


CATALOGUE = "catalogue"
CERTIFICATE = "certificate"
OTHER = "other"
REVIEW = "review"

CERTIFICATE_TERMS = (
    "certificate of analysis",
    "analysis certificate",
    "certificate of quality",
    "certificate of conformance",
    "quality certificate",
    "test certificate",
    "analytical report",
    "guarantee of analysis",
    "certificate",
    "coa",
    "c of a",
    "coc",
    "lab report",
    "laboratory report",
    "test report",
    "quality report",
    "specification sheet",
    "technical data sheet",
    "tds",
    "msds",
    "halal",
    "kosher",
    "organic certificate",
    "gmp",
    "cgmp",
    "iso",
    "assay",
    "purity",
    "batch release",
)
CATALOGUE_TERMS = (
    "catalog",
    "catalogue",
    "price list",
    "pricelist",
    "quotation",
    "quote",
    "offer",
    "inventory",
    "stock list",
    "available stock",
    "rate list",
    "fob",
    "cif",
    "exw",
)
COMMERCIAL_TERMS = (
    "price",
    "rate",
    "usd",
    "inr",
    "rs.",
    "$",
    "moq",
    "quantity",
    "qty",
    "lead time",
    "delivery",
)
CATALOGUE_HEADER_TERMS = (
    "ingredient",
    "ingredient name",
    "product",
    "product name",
    "item",
    "item name",
    "material",
    "material name",
    "raw material",
    "rm",
    "spec",
    "specification",
    "price",
    "price/unit",
    "price per unit",
    "rate",
    "qty",
    "qty avail",
    "quantity",
    "volume",
    "volume kg",
    "stock",
    "lead time",
    "moq",
)
CATALOGUE_TABLE_HEADER_PATTERN = re.compile(
    r"\b(?:product|ingredient|item|material|rm)\s*(?:name)?\b.{0,120}\b(?:specification|spec|price|rate|qty|quantity|volume|stock|moq|lead\s*time)\b"
    r"|\b(?:specification|spec|price|rate|qty|quantity|volume|stock|moq|lead\s*time)\b.{0,120}\b(?:product|ingredient|item|material|rm)\s*(?:name)?\b",
    re.IGNORECASE | re.DOTALL,
)
CATALOGUE_CATEGORY_PATTERN = re.compile(
    r"\b(?:used\s+for|sports\s+nutrition|dietary\s+supplements|oem\s+services|hard\s+capsules|soft\s+gels|tablets)\b",
    re.IGNORECASE,
)
CATALOGUE_PRODUCT_SPEC_ROW_PATTERN = re.compile(
    r"\b[A-Z][A-Za-z0-9][A-Za-z0-9 .,&()/+-]{2,80}\s{2,}"
    r"(?:all\s+grade|usp\s+grade|nf\s*(?:ii)?\s*grade|vegan|"
    r"\d+(?:\.\d+)?\s*%|[A-Za-z]+(?:oids?|in|ins?)\b|based\s+on\s+extract\s+ratio)",
    re.IGNORECASE,
)
CATALOGUE_LINE_ITEM_PATTERN = re.compile(
    r"\b[A-Za-z][A-Za-z0-9][A-Za-z0-9 .,&()/+-]{2,120}\b"
    r".{0,90}?"
    r"(?:\b(?:USD|INR|EUR|GBP|Rs\.?)\b|[$₹€£]|\b\d+(?:\.\d+)?\s*(?:kg|kgs|g|gm|mt|tons?|units?|packs?)\b|@\s*\d)",
    re.IGNORECASE,
)

# These fields commonly appear together on a COA or quality certificate even
# when the scan/OCR misses its heading.  They are intentionally not commercial
# catalogue fields, so the combination is a strong certificate signal.
CERTIFICATE_FIELD_TERMS = (
    "batch no",
    "batch number",
    "lot no",
    "lot number",
    "manufacturing date",
    "expiry date",
    "retest date",
    "appearance",
    "identification",
    "assay",
    "purity",
    "loss on drying",
    "heavy metals",
    "microbial",
    "conforms",
    "complies",
)

PRICE_UPDATE_SENTENCE_PATTERN = re.compile(
    r"\b(?:price|rate)\s+(?:of|for)\s+"
    r"(?P<material>[A-Za-z0-9][A-Za-z0-9 %().,+/'-]{2,120}?)\s+"
    r"(?:is\s+)?(?:updated|revised|changed|set|now|increased|decreased)\s+"
    r"(?:to|at|as)?\s*(?:US\$|\$|USD|INR|Rs\.?|₹|EUR|€|GBP|£)?\s*"
    r"\d[\d,]*(?:\.\d+)?\s*/\s*[A-Za-z]+",
    re.IGNORECASE,
)


DIRECT_PRICE_SENTENCE_PATTERN = re.compile(
    r"\b(?:price|rate)\s+(?:of|for)\s+"
    r"(?P<material>[A-Za-z0-9][A-Za-z0-9 %().,+/'-]{2,120}?)\s+"
    r"(?:is|:|-)\s*"
    r"(?:US\$|\$|USD|INR|Rs\.?|EUR|GBP)?\s*"
    r"\d[\d,]*(?:\.\d+)?\s*/\s*[A-Za-z]+",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class DocumentClassification:
    category: str
    confidence: float
    material_hint: str | None = None


def classify_document(
    filename: str,
    ext: str,
    text: str | None,
    context_text: str | None = None,
) -> DocumentClassification:
    raw_text = text or ""
    combined_source = f"{filename}\n{context_text or ''}\n{raw_text}".lower()
    filename_lower = filename.lower()
    ext_lower = ext.lower()
    extraction_quality = _extraction_quality(raw_text)

    certificate_score = _term_score(combined_source, CERTIFICATE_TERMS)
    catalogue_score = _term_score(combined_source, CATALOGUE_TERMS) + _term_score(combined_source, COMMERCIAL_TERMS)
    other_score = 0.0
    product_spec_rows = _catalogue_product_spec_row_count(raw_text)
    has_catalogue_header = bool(CATALOGUE_TABLE_HEADER_PATTERN.search(raw_text))
    has_catalogue_category = bool(CATALOGUE_CATEGORY_PATTERN.search(raw_text))
    structured_catalogue_rows = _structured_catalogue_row_count(raw_text)
    catalogue_header_score = _term_score(combined_source, CATALOGUE_HEADER_TERMS)
    line_item_rows = _line_item_row_count(raw_text)

    catalogue_score += extraction_quality * 0.8
    certificate_score += extraction_quality * 0.8
    if product_spec_rows >= 3:
        catalogue_score += 5
    if has_catalogue_header:
        catalogue_score += 4
    if has_catalogue_category:
        catalogue_score += 3
    if structured_catalogue_rows >= 2 and catalogue_header_score >= 2:
        catalogue_score += 5
    elif structured_catalogue_rows >= 3:
        catalogue_score += 3
    if line_item_rows >= 2:
        catalogue_score += 5

    certificate_field_score = _term_score(combined_source, CERTIFICATE_FIELD_TERMS)
    if certificate_field_score >= 2 and product_spec_rows < 3:
        # A heading can be lost in a scan, but two or more analytical/batch
        # fields identify the document as a certificate rather than a quote.
        certificate_score += certificate_field_score + 2
    if certificate_field_score >= 4:
        certificate_score += 3

    table_like_rows = len(
        [
            line
            for line in raw_text.splitlines()
            if "|" in line and re.search(r"\b(?:price|qty|quantity|usd|inr|moq|kg)\b|\d", line, re.IGNORECASE)
        ]
    )
    if table_like_rows >= 2:
        catalogue_score += 3

    if PRICE_UPDATE_SENTENCE_PATTERN.search(raw_text) or DIRECT_PRICE_SENTENCE_PATTERN.search(raw_text):
        catalogue_score += 3

    is_cert_file = _is_certificate_filename(filename_lower)
    is_cat_file = any(
        term in filename_lower for term in ("catalog", "catalogue", "price list", "pricelist", "price", "quotation", "quote")
    )

    if is_cert_file:
        certificate_score += 2
    if is_cat_file:
        catalogue_score += 2

    if extraction_quality >= 0.55 and max(catalogue_score, certificate_score) < 3:
        other_score = 2.5 + extraction_quality * 2

    scores = {
        CATALOGUE: float(catalogue_score),
        CERTIFICATE: float(certificate_score),
        OTHER: float(other_score),
    }
    ordered = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    top_category, top_score = ordered[0]
    runner_up_score = ordered[1][1]
    gap = top_score - runner_up_score

    if top_score <= 0 or extraction_quality < 0.25:
        return DocumentClassification(REVIEW, _confidence(top_score, runner_up_score, extraction_quality), None)

    if is_cert_file and certificate_field_score >= 1:
        return DocumentClassification(CERTIFICATE, _confidence(certificate_score, max(catalogue_score, other_score), extraction_quality), _material_hint(filename, text))

    if certificate_score >= 2 and certificate_field_score >= 1 and structured_catalogue_rows < 2:
        return DocumentClassification(CERTIFICATE, _confidence(certificate_score, max(catalogue_score, other_score), extraction_quality), _material_hint(filename, text))

    if (has_catalogue_header and product_spec_rows >= 2) or product_spec_rows >= 5:
        return DocumentClassification(CATALOGUE, _confidence(catalogue_score, max(certificate_score, other_score), extraction_quality), None)

    if (
        ext_lower in {".pdf", ".docx"}
        and structured_catalogue_rows >= 2
        and catalogue_header_score >= 2
        and certificate_field_score < 3
    ):
        return DocumentClassification(CATALOGUE, _confidence(catalogue_score, max(certificate_score, other_score), extraction_quality), None)

    if line_item_rows >= 2 and certificate_field_score < 3:
        return DocumentClassification(CATALOGUE, _confidence(catalogue_score, max(certificate_score, other_score), extraction_quality), None)

    if certificate_field_score >= 1 and catalogue_score >= 3:
        return DocumentClassification(REVIEW, _confidence(max(catalogue_score, certificate_score), min(catalogue_score, certificate_score), extraction_quality), None)

    if is_cert_file and not is_cat_file:
        return DocumentClassification(CERTIFICATE, _confidence(certificate_score, max(catalogue_score, other_score), extraction_quality), _material_hint(filename, text))

    if certificate_score >= 2 and catalogue_score < certificate_score + 3:
        if gap < 1.5 and top_category != CERTIFICATE:
            return DocumentClassification(REVIEW, _confidence(top_score, runner_up_score, extraction_quality), None)
        return DocumentClassification(CERTIFICATE, _confidence(certificate_score, max(catalogue_score, other_score), extraction_quality), _material_hint(filename, text))

    if catalogue_score >= 3:
        if gap < 1.5 and top_category != CATALOGUE:
            return DocumentClassification(REVIEW, _confidence(top_score, runner_up_score, extraction_quality), None)
        return DocumentClassification(CATALOGUE, _confidence(catalogue_score, max(certificate_score, other_score), extraction_quality), None)

    if certificate_score >= 2:
        return DocumentClassification(CERTIFICATE, _confidence(certificate_score, max(catalogue_score, other_score), extraction_quality), _material_hint(filename, text))

    if top_category == OTHER and top_score >= 3 and gap >= 1:
        return DocumentClassification(OTHER, _confidence(top_score, runner_up_score, extraction_quality), None)

    return DocumentClassification(REVIEW, _confidence(top_score, runner_up_score, extraction_quality), None)


def _term_score(text: str, terms: tuple[str, ...]) -> int:
    return sum(1 for term in terms if re.search(rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])", text, re.IGNORECASE))


def _extraction_quality(text: str) -> float:
    cleaned = " ".join(text.split())
    if not cleaned:
        return 0.0
    alnum_count = sum(1 for char in cleaned if char.isalnum())
    printable_count = sum(1 for char in cleaned if char.isprintable())
    replacement_penalty = cleaned.count("\ufffd") / max(1, len(cleaned))
    length_score = min(1.0, len(cleaned) / 400)
    alnum_score = min(1.0, alnum_count / max(1, len(cleaned)) / 0.55)
    printable_score = printable_count / max(1, len(cleaned))
    return max(0.0, min(1.0, (length_score * 0.45) + (alnum_score * 0.35) + (printable_score * 0.20) - replacement_penalty))


def _confidence(top_score: float, runner_up_score: float, extraction_quality: float) -> float:
    gap = max(0.0, top_score - runner_up_score)
    confidence = 0.42 + min(top_score, 12.0) * 0.025 + min(gap, 8.0) * 0.035 + extraction_quality * 0.18
    return max(0.05, min(0.99, confidence))


def _catalogue_product_spec_row_count(text: str) -> int:
    count = 0
    for line in text.splitlines():
        cleaned = " ".join(line.split())
        if not cleaned:
            continue
        if CATALOGUE_PRODUCT_SPEC_ROW_PATTERN.search(line) or CATALOGUE_PRODUCT_SPEC_ROW_PATTERN.search(cleaned):
            count += 1
    return count


def _structured_catalogue_row_count(text: str) -> int:
    count = 0
    for line in text.splitlines():
        cleaned = " ".join(line.split()).strip()
        if not cleaned or re.fullmatch(r"\|?\s*:?-{2,}:?\s*(?:\|\s*:?-{2,}:?\s*)+\|?", cleaned):
            continue
        cells = _table_cells(cleaned)
        if cells:
            first_text_cell = next((cell for cell in cells if re.search(r"[A-Za-z]", cell)), "")
            numeric_or_unit_cells = [
                cell
                for cell in cells[1:]
                if re.search(r"(?:\d|USD|INR|EUR|GBP|Rs\.?|[$₹€£]|\bkg\b|\bgm?\b|\bunit\b|\bweek\b|\bdays?\b)", cell, re.IGNORECASE)
            ]
            if first_text_cell and numeric_or_unit_cells:
                count += 1
            continue
        if CATALOGUE_LINE_ITEM_PATTERN.search(cleaned):
            count += 1
    return count


def _line_item_row_count(text: str) -> int:
    return sum(1 for line in text.splitlines() if CATALOGUE_LINE_ITEM_PATTERN.search(" ".join(line.split())))


def _table_cells(line: str) -> list[str]:
    if "|" not in line:
        return []
    cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
    return [cell for cell in cells if cell]


def _is_certificate_filename(filename: str) -> bool:
    lowered = filename.lower()
    return bool(
        re.search(
            r"\b(?:coa|cert|certificate|analysis|halal|kosher|gmp|iso|msds|tds|coc|spec|specification|quality|report)\b"
            r"|(?<![a-z0-9])(?:coa|cert|certificate)[0-9_\-\.]",
            lowered,
        )
    )


def _material_hint(filename: str, text: str | None) -> str | None:
    candidates: list[str] = []
    source = f"{filename}\n{text or ''}"
    patterns = (
        r"certificate\s+of\s+analysis\s*[-:]\s*(?P<name>[A-Za-z0-9][A-Za-z0-9 %().,+/-]{2,120})",
        r"\bCOA\s*[-:]\s*(?P<name>[A-Za-z0-9][A-Za-z0-9 %().,+/-]{2,120})",
        r"\b(?:product|material|item|sample|chemical|ingredient)\s*(?:name)?\s*[:\-]\s*(?P<name>[A-Za-z0-9][A-Za-z0-9 %().,+/-]{2,120})",
        r"\bCoA\s+for\s+(?P<name>[A-Za-z0-9][A-Za-z0-9 %().,+/-]{2,120})",
        r"\bCertificate\s+for\s+(?P<name>[A-Za-z0-9][A-Za-z0-9 %().,+/-]{2,120})",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, source, flags=re.IGNORECASE):
            candidates.append(match.group("name"))

    stem = re.sub(r"\.[A-Za-z0-9]+$", "", filename)
    stem = re.sub(r"(?i)\b(?:certificate of analysis|certificate|cert|coa|analysis|report|pdf|scan|copy|doc|document)\b", " ", stem)
    stem = re.sub(r"[_-]+", " ", stem)
    if stem.strip():
        candidates.append(stem)

    for candidate in candidates:
        cleaned = _clean_material_hint(candidate)
        if cleaned:
            return cleaned
    return None


def _clean_material_hint(value: str) -> str | None:
    cleaned = re.sub(r"\s+", " ", value).strip(" -_:.,")
    cleaned = re.split(r"\b(?:batch|lot|mfg|manufacturing|expiry|date|page|supplier)\b", cleaned, flags=re.IGNORECASE)[0].strip(" -_:.,")
    if len(cleaned) < 3:
        return None
    if cleaned.lower() in {"certificate", "analysis", "report", "quality"}:
        return None
    return cleaned[:120]
