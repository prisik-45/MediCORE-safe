from pathlib import Path

from backend.app.schemas import ExtractedCatalogItem
from backend.app.services.catalog_table_parser import _header_cell_metadata
from backend.app.services.normalizer import clean_specification, normalize_item


def test_header_currency_detection_supports_symbols_and_empty_currency() -> None:
    assert _header_cell_metadata("Price (£/kg)") == {"field": "price", "currency": "GBP", "unit": "kg"}
    assert _header_cell_metadata("Price (€/kg)") == {"field": "price", "currency": "EUR", "unit": "kg"}
    assert _header_cell_metadata("Rate (₹/kg)") == {"field": "price", "currency": "INR", "unit": "kg"}
    assert _header_cell_metadata("FOB (USD/kg)") == {"field": "price", "currency": "USD", "unit": "kg"}
    assert _header_cell_metadata("Price") == {"field": "price", "currency": None, "unit": None}


def test_normalizer_does_not_default_missing_currency_to_inr() -> None:
    item = normalize_item(ExtractedCatalogItem(ingredient_name="Citric Acid", price_per_unit=41.5, unit="kg"))

    assert item.currency == ""


def test_clean_specification_does_not_rewrite_real_66_percent_value() -> None:
    assert clean_specification("66%") == "66%"
    assert clean_specification("% 66") == "66%"
    assert clean_specification("% 99") == "99%"


def test_no_mojibake_in_backend_sources() -> None:
    bad_markers = tuple(chr(codepoint) for codepoint in (0x00E2, 0x00C3, 0x00C2))
    for path in Path("backend").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert not any(marker in text for marker in bad_markers), path
