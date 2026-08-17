import base64
import hashlib
from cryptography.fernet import Fernet
import pytest

from backend.app.auth import decrypt_password, encrypt_password
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
    # First, simulate ciphertext created by the old service-role-derived key.
    monkeypatch.setattr(settings, "mailbox_fernet_key", "")
    legacy_material = settings.supabase_service_role_key.encode("utf-8")
    legacy_key = base64.urlsafe_b64encode(hashlib.sha256(legacy_material).digest())
    legacy_ciphertext = Fernet(legacy_key).encrypt(b"legacy_mailbox_password").decode("utf-8")

    # Then, switch to a new dedicated key
    new_key = Fernet.generate_key().decode("utf-8")
    monkeypatch.setattr(settings, "mailbox_fernet_key", new_key)

    # Decrypt should successfully fall back and decrypt the legacy ciphertext
    recovered = decrypt_password(legacy_ciphertext)
    assert recovered == "legacy_mailbox_password"


def test_encryption_requires_dedicated_mailbox_key(monkeypatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "mailbox_fernet_key", "")

    with pytest.raises(RuntimeError, match="MAILBOX_FERNET_KEY"):
        encrypt_password("new_mailbox_password")
