import re
from backend.app.schemas import ExtractedCatalogItem, clean_optional_text


UNIT_ALIASES = {
    "pcs": "unit",
    "piece": "unit",
    "pieces": "unit",
    "units": "unit",
    "tabs": "tablet",
    "tablet": "tablet",
    "tablets": "tablet",
    "kg": "kg",
    "kilogram": "kg",
    "g": "g",
    "gram": "g",
}

SPEC_REPLACEMENTS = {
    r"\b(?:apeo\s*esn|apepdsn|epeDasn|apDdsn|apeD\s*dsn|apdsn|apuoN|usp\s*crade)\b": "USP Grade",
    r"\baji\s*crade\b": "AJI Grade",
    r"\bfood\s*cradh?\b": "Food Grade",
    r"\bnfi1\s*grade\b": "NF II Grade",
}

COLUMN_PREFIX_PATTERNS = [
    r"^(?:Ai\s+Cade|AJI\s+Grade|USP\s+Grade|USP\s+Crade|AJI\s+Crade|Food\s+Grade|NF\s+II\s+Grade)\s+",
    r"^(?:Vegan\s*:\s*[0-9:a-z;]+|FCC\s*&\s*AJI\s+Grade,\s*USP\s+Grade|apDdsn|apeD\s*dsn|apdsn|apeo\s*esn)\s+",
    r"^(?:ate\s+)?(?:\d+%\s*)+",
]

INGREDIENT_TYPO_REPLACEMENTS = {
    r"\bBlack\s+Cinger\b": "Black Ginger",
    r"\bCreen\s+Tea\b": "Green Tea",
    r"\bLyiozyme\b": "Lysozyme",
    r"\bMicroblal\b": "Microbial",
    r"\bMagneslum\b": "Magnesium",
    r"\bClycinate\b": "Glycinate",
    r"\bMlcrocrystalline\b": "Microcrystalline",
    r"\bManaradeotide\b": "Mononucleotide",
    r"\bg-Nicotinamide\b": "β-Nicotinamide",
}


def _apply_text_replacements(value: str, replacements: dict[str, str]) -> tuple[str, list[dict[str, str]]]:
    cleaned = value
    corrections: list[dict[str, str]] = []
    for pattern, repl in replacements.items():
        next_value, count = re.subn(pattern, repl, cleaned, flags=re.IGNORECASE)
        if count and next_value != cleaned:
            corrections.append({"from": cleaned, "to": next_value, "rule": pattern})
        cleaned = next_value
    return cleaned, corrections


def clean_ingredient_name_with_corrections(name: str) -> tuple[str, list[dict[str, str]]]:
    name = clean_optional_text(name) or ""
    for pattern in COLUMN_PREFIX_PATTERNS:
        name = re.sub(pattern, "", name, flags=re.IGNORECASE).strip()
    name, corrections = _apply_text_replacements(name, INGREDIENT_TYPO_REPLACEMENTS)
    return name.strip(), [{"field": "ingredient_name", **correction} for correction in corrections]


def clean_ingredient_name(name: str) -> str:
    cleaned, _ = clean_ingredient_name_with_corrections(name)
    return cleaned


def clean_specification_with_corrections(spec: str | None) -> tuple[str | None, list[dict[str, str]]]:
    cleaned = clean_optional_text(spec)
    if not cleaned:
        return None, []
    cleaned = re.sub(r"^\s*%\s*(\d+(?:\.\d+)?)\s*$", r"\1%", cleaned)
    cleaned, corrections = _apply_text_replacements(cleaned, SPEC_REPLACEMENTS)
    return cleaned.strip(), [{"field": "specification", **correction} for correction in corrections]


def clean_specification(spec: str | None) -> str | None:
    cleaned, _ = clean_specification_with_corrections(spec)
    return cleaned


def _append_correction_notes(notes: str | None, corrections: list[dict[str, str]]) -> str | None:
    cleaned_notes = clean_optional_text(notes)
    if not corrections:
        return cleaned_notes
    encoded = "|".join(
        f"{correction['field']}:{correction['from']}->{correction['to']}"
        for correction in corrections
    )
    suffix = f"auto_corrections={encoded}"
    return f"{cleaned_notes}; {suffix}" if cleaned_notes else suffix


def normalize_item(item: ExtractedCatalogItem) -> ExtractedCatalogItem:
    unit = None
    cleaned_unit = clean_optional_text(item.unit)
    if cleaned_unit:
        raw_unit = cleaned_unit.strip().lower()
        unit = UNIT_ALIASES.get(raw_unit, raw_unit)

    ingredient_name, ingredient_corrections = clean_ingredient_name_with_corrections(item.ingredient_name)
    ingredient_name = ingredient_name or item.ingredient_name
    specification, specification_corrections = clean_specification_with_corrections(item.specification)
    corrections = [*ingredient_corrections, *specification_corrections]

    return item.model_copy(
        update={
            "ingredient_name": ingredient_name,
            "unit": unit,
            "currency": (clean_optional_text(item.currency) or "").upper(),
            "specification": specification,
            "lead_time_text": clean_optional_text(item.lead_time_text),
            "notes": _append_correction_notes(item.notes, corrections),
        }
    )
