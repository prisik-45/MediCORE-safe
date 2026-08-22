from backend.app.services.catalog_table_parser import is_valid_ingredient_name


def test_boilerplate_text_is_not_valid_ingredient_name() -> None:
    rejected = [
        "Dear Sir",
        "Best regards",
        "Thank you",
        "Kindly find attached",
        "Page 1 of 3",
        "GST No 27AAACX",
        "Mumbai 400001",
        "Terms and Conditions",
        "Payment 30 days",
        "Delivery within 15 days",
        "Warm Regards",
        "Sincerely",
    ]

    assert all(not is_valid_ingredient_name(value) for value in rejected)


def test_real_ingredient_names_remain_valid() -> None:
    accepted = [
        "Ascorbic Acid",
        "Citric Acid Monohydrate",
        "Thiamine Mononitrate",
        "Riboflavin",
        "Nicotinamide",
        "Methylcobalamin",
        "Biotin",
        "Ashwagandha Extract",
        "Zinc Glycinate",
        "5-Amino-1-methylquinolinium Chloride",
        "3,3'-Diindolylmethane",
    ]

    assert all(is_valid_ingredient_name(value) for value in accepted)
