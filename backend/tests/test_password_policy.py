import pytest
from backend.app.schemas import validate_password_strength


def test_password_strength_accepts_strong_password() -> None:
    valid_password = "SecurePassword123!"
    assert validate_password_strength(valid_password) == valid_password


def test_password_strength_rejects_short_passwords() -> None:
    with pytest.raises(ValueError, match="at least 8 characters"):
        validate_password_strength("Short1!")


def test_password_strength_rejects_missing_character_classes() -> None:
    # Missing uppercase
    with pytest.raises(ValueError, match="uppercase letter"):
        validate_password_strength("alllowercase123!")

    # Missing digits
    with pytest.raises(ValueError, match="number"):
        validate_password_strength("NoDigitsHereInPass!")

    # Missing lowercase
    with pytest.raises(ValueError, match="lowercase letter"):
        validate_password_strength("ALLUPPERCASE123!")


def test_password_strength_rejects_common_weak_passwords() -> None:
    with pytest.raises(ValueError, match="too common or easily guessed"):
        validate_password_strength("password123")
