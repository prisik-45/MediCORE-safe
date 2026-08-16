from types import SimpleNamespace
from cryptography.fernet import Fernet
import pytest

from backend.app.auth import decrypt_password, encrypt_password, get_fernet
from backend.app.config import get_settings


def test_encryption_and_decryption_with_dedicated_fernet_key(monkeypatch) -> None:
    dedicated_key = Fernet.generate_key().decode("utf-8")
    settings = get_settings()
    monkeypatch.setattr(settings, "mailbox_fernet_key", dedicated_key)

    plaintext = "super_secret_imap_password_123"
    ciphertext = encrypt_password(plaintext)
    assert ciphertext != plaintext

    decrypted = decrypt_password(ciphertext)
    assert decrypted == plaintext


def test_dual_read_fallback_decrypts_legacy_service_role_encrypted_passwords(monkeypatch) -> None:
    settings = get_settings()
    # First, encrypt using legacy service-role key
    monkeypatch.setattr(settings, "mailbox_fernet_key", "")
    legacy_ciphertext = encrypt_password("legacy_mailbox_password")

    # Then, switch to a new dedicated key
    new_key = Fernet.generate_key().decode("utf-8")
    monkeypatch.setattr(settings, "mailbox_fernet_key", new_key)

    # Decrypt should successfully fall back and decrypt the legacy ciphertext
    recovered = decrypt_password(legacy_ciphertext)
    assert recovered == "legacy_mailbox_password"
