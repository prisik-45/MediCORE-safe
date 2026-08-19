import re
from typing import Any

# Standard unit and form abbreviations map
UNIT_FORM_ALIASES = {
    "tab": "tablet",
    "tabs": "tablet",
    "tablets": "tablet",
    "cap": "capsule",
    "caps": "capsule",
    "capsules": "capsule",
    "syr": "syrup",
    "syrups": "syrup",
    "inj": "injection",
    "injections": "injection",
    "susp": "suspension",
    "sol": "solution",
    "soln": "solution",
    "mcg": "mcg",
    "mg": "mg",
    "g": "g",
    "gm": "g",
    "kg": "kg",
    "ml": "ml",
    "l": "l",
    "litre": "l",
    "litres": "l",
}

# Known common drug brand / shorthand aliases
PRODUCT_ALIASES = {
    "pcm": "paracetamol",
    "paracetmol": "paracetamol",
    "paracetemol": "paracetamol",
    "paracetomol": "paracetamol",
    "para cetamol": "paracetamol",
    "paracet amol": "paracetamol",
    "acetaminophen": "paracetamol",
    "amox": "amoxicillin",
    "amoxil": "amoxicillin",
    "amoxycillin": "amoxicillin",
    "ibuprafen": "ibuprofen",
    "ibuprofen": "ibuprofen",
    "cipro": "ciprofloxacin",
    "azithro": "azithromycin",
}


def normalize_product_name(text: str) -> str:
    """Normalize a product name string by stripping noise, standardizing whitespace,

    lowercasing, and expanding common abbreviations.
    """
    if not text:
        return ""

    # Convert to lowercase
    normalized = text.strip().lower()

    # Special handling for hyphenated drug names like para-cetamol
    normalized = re.sub(r"(\w+)-(\w+)", r"\1 \2", normalized)

    # Replace remaining punctuation with space
    normalized = re.sub(r"[_\,/.:;\(\)\[\]]", " ", normalized)

    # Collapse multiple spaces
    words = [w.strip() for w in normalized.split() if w.strip()]

    # Check whole normalized phrase alias
    joined_words = " ".join(words)
    if joined_words in PRODUCT_ALIASES:
        return PRODUCT_ALIASES[joined_words]

    # Replace word by word
    cleaned_words = []
    for word in words:
        if word in PRODUCT_ALIASES:
            cleaned_words.append(PRODUCT_ALIASES[word])
        elif word in UNIT_FORM_ALIASES:
            cleaned_words.append(UNIT_FORM_ALIASES[word])
        else:
            cleaned_words.append(word)

    result = " ".join(cleaned_words)
    if result in PRODUCT_ALIASES:
        return PRODUCT_ALIASES[result]

    return result


def extract_product_attributes(text: str) -> dict[str, Any]:
    """Extract structured attributes (base_name, strength, form, pack_size, unit) from a query string.

    Example: "paracetmol 500mg tablet 10s" -> {
        "base_name": "paracetamol",
        "strength": "500 mg",
        "form": "tablet",
        "pack_size": 10,
        "unit": "tablet"
    }
    """
    if not text:
        return {
            "base_name": "",
            "strength": None,
            "form": None,
            "pack_size": None,
            "unit": None,
            "raw": text,
        }

    raw = text.strip()
    norm = normalize_product_name(raw)

    # 1. Extract strength (e.g., 500 mg, 650mg, 10ml, 5g, 0.5%)
    strength_match = re.search(r"(\b\d+(?:\.\d+)?\s*(?:mg|g|mcg|ml|l|%)\b)", norm, re.IGNORECASE)
    strength = None
    raw_strength_str = ""
    if strength_match:
        raw_strength_str = strength_match.group(1).lower()
        strength = re.sub(r"(\d+)(mg|g|mcg|ml|l|%)", r"\1 \2", raw_strength_str)

    # 2. Extract form (tablet, capsule, syrup, injection, etc.)
    form = None
    for form_keyword in ("tablet", "capsule", "syrup", "injection", "suspension", "solution", "cream", "ointment"):
        if re.search(r"\b" + re.escape(form_keyword) + r"\b", norm):
            form = form_keyword
            break

    # 3. Extract pack size (e.g. "10s", "100s", "10 tabs", "pack of 10", "1x10")
    pack_size = None
    pack_match = re.search(r"(\b\d+\s*s\b|\bpack\s*of\s*\d+|\b\d+\s*x\s*\d+)", norm, re.IGNORECASE)
    if pack_match:
        digits = re.findall(r"\d+", pack_match.group(1))
        if len(digits) == 1:
            pack_size = int(digits[0])
        elif len(digits) == 2:
            pack_size = int(digits[0]) * int(digits[1])

    # 4. Extract base product name by removing strength, form, pack size keywords
    name_words = []
    strength_tokens = set(re.findall(r"[a-z0-9.]+", raw_strength_str.lower())) if raw_strength_str else set()
    if strength:
        strength_tokens.update(re.findall(r"[a-z0-9.]+", strength.lower()))

    for word in norm.split():
        if word in strength_tokens or re.match(r"^\d+(?:mg|g|mcg|ml|l|%)$", word):
            continue
        if form and word == form:
            continue
        if word in ("10s", "20s", "30s", "50s", "100s", "pack", "of"):
            continue
        if re.match(r"^\d+s$", word) or re.match(r"^\d+x\d+$", word):
            continue
        name_words.append(word)

    base_name = " ".join(name_words).strip()
    if not base_name:
        base_name = norm

    return {
        "base_name": base_name,
        "strength": strength,
        "form": form,
        "pack_size": pack_size,
        "unit": form or "unit",
        "normalized": norm,
        "raw": raw,
    }


def are_attributes_compatible(attr1: dict[str, Any], attr2: dict[str, Any]) -> bool:
    """Validate whether two sets of product attributes are compatible.

    Prevents comparing 500mg with 650mg, or Tablets with Syrups.
    """
    # Strength mismatch check
    if attr1.get("strength") and attr2.get("strength"):
        if attr1["strength"] != attr2["strength"]:
            return False

    # Form mismatch check
    if attr1.get("form") and attr2.get("form"):
        if attr1["form"] != attr2["form"]:
            return False

    return True
