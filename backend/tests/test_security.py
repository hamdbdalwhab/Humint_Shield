"""Tests for password hashing, JWT issuance and AES-256-GCM encryption."""
from __future__ import annotations

import pytest

from app.security import (
    EncryptionError,
    TokenError,
    constant_time_compare,
    create_access_token,
    create_refresh_token,
    decode_token,
    decrypt_value,
    encrypt_value,
    hash_password,
    verify_password,
)


def test_password_hash_is_not_plaintext() -> None:
    """Hashing must never store the plaintext password."""
    hashed = hash_password("CorrectHorseBattery")
    assert hashed != "CorrectHorseBattery"
    assert hashed.startswith("$2")


def test_password_verify_roundtrip() -> None:
    """The correct password verifies and a wrong one does not."""
    hashed = hash_password("CorrectHorseBattery")
    assert verify_password("CorrectHorseBattery", hashed) is True
    assert verify_password("wrong-password", hashed) is False


def test_password_hashes_are_salted() -> None:
    """Two hashes of the same password must differ (random salt)."""
    assert hash_password("same-password") != hash_password("same-password")


def test_long_password_is_supported() -> None:
    """Passwords longer than bcrypt's 72-byte limit still work."""
    long_password = "a" * 300
    hashed = hash_password(long_password)
    assert verify_password(long_password, hashed) is True
    assert verify_password("a" * 299, hashed) is False


def test_empty_password_rejected() -> None:
    """An empty password is rejected."""
    with pytest.raises(ValueError):
        hash_password("")


def test_verify_with_empty_hash_returns_false() -> None:
    """A missing hash never authenticates."""
    assert verify_password("anything", "") is False
    assert verify_password("", "not-a-hash") is False


def test_access_token_roundtrip() -> None:
    """An access token round-trips and carries the expected claims."""
    token = create_access_token("user-123", {"role": "admin"})
    claims = decode_token(token)
    assert claims["sub"] == "user-123"
    assert claims["type"] == "access"
    assert claims["role"] == "admin"


def test_refresh_token_type() -> None:
    """Refresh tokens are marked as such."""
    claims = decode_token(create_refresh_token("user-123"))
    assert claims["type"] == "refresh"


def test_invalid_token_raises() -> None:
    """A malformed token raises ``TokenError``."""
    with pytest.raises(TokenError):
        decode_token("not-a-jwt")


def test_encrypt_decrypt_roundtrip() -> None:
    """Values survive an encrypt/decrypt round trip."""
    plaintext = "+1-555-0100"
    token = encrypt_value(plaintext)
    assert token is not None
    assert token.startswith("enc:v1:")
    assert plaintext not in token
    assert decrypt_value(token) == plaintext


def test_encryption_is_nondeterministic() -> None:
    """A fresh nonce is used for every encryption."""
    assert encrypt_value("secret") != encrypt_value("secret")


def test_encryption_idempotent_for_ciphertext() -> None:
    """Encrypting an already-encrypted value is a no-op."""
    token = encrypt_value("secret")
    assert encrypt_value(token) == token


def test_encrypt_none_passthrough() -> None:
    """``None`` is passed through untouched in both directions."""
    assert encrypt_value(None) is None
    assert decrypt_value(None) is None


def test_decrypt_plaintext_passthrough() -> None:
    """Legacy plaintext columns are returned as-is."""
    assert decrypt_value("plain-value") == "plain-value"


def test_decrypt_tampered_payload_raises() -> None:
    """Tampering with the ciphertext is detected (GCM authentication)."""
    token = encrypt_value("secret")
    assert token is not None
    tampered = token[:-4] + "AAAA"
    with pytest.raises(EncryptionError):
        decrypt_value(tampered)


def test_constant_time_compare() -> None:
    """Constant-time comparison behaves like equality."""
    assert constant_time_compare("abc", "abc") is True
    assert constant_time_compare("abc", "abd") is False
