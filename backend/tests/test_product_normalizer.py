from backend.app.services.product_normalizer import (
    are_attributes_compatible,
    extract_product_attributes,
    normalize_product_name,
)


def test_normalize_product_name_typos_and_abbreviations():
    assert normalize_product_name("PARACETAMOL") == "paracetamol"
    assert normalize_product_name("paracetmol 500mg tab") == "paracetamol 500mg tablet"
    assert normalize_product_name("pcm 650 cap") == "paracetamol 650 capsule"
    assert normalize_product_name("para-cetamol") == "paracetamol"


def test_extract_product_attributes():
    attrs = extract_product_attributes("paracetmol 500mg tablet 10s")
    assert attrs["base_name"] == "paracetamol"
    assert attrs["strength"] == "500 mg"
    assert attrs["form"] == "tablet"
    assert attrs["pack_size"] == 10

    attrs_syrup = extract_product_attributes("amoxicillin 250 mg syrup")
    assert attrs_syrup["base_name"] == "amoxicillin"
    assert attrs_syrup["strength"] == "250 mg"
    assert attrs_syrup["form"] == "syrup"


def test_are_attributes_compatible():
    attr_500 = extract_product_attributes("Paracetamol 500 mg Tablet")
    attr_650 = extract_product_attributes("Paracetamol 650 mg Tablet")
    attr_500_copy = extract_product_attributes("paracetmol 500mg tab")

    # Incompatible strengths (500mg vs 650mg)
    assert not are_attributes_compatible(attr_500, attr_650)

    # Compatible strengths (500mg vs 500mg)
    assert are_attributes_compatible(attr_500, attr_500_copy)

    # Incompatible forms (Tablet vs Syrup)
    attr_syrup = extract_product_attributes("Paracetamol 500 mg Syrup")
    assert not are_attributes_compatible(attr_500, attr_syrup)
