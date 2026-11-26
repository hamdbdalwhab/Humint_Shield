"""Security primitives: password hashing, JWT, and AES-256-GCM encryption.

Nothing in this module reads configuration at import time so that tests can
freely monkeypatch :func:`app.config.get_settings`.
"""
from __future__ import annotations

import base64
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

import bcrypt
from jose import JWTError, jwt

from app.config import get_settings
from app.logging_config import get_logger

logger = get_logger(__name__)

# bcrypt has a hard 72-byte input limit; longer passwords are pre-hashed.
_BCRYPT_MAX_BYTES = 72


class TokenError(Exception):
    """Raised when a JWT cannot be created or validated."""


class EncryptionError(Exception):
    """Raised when encryption or decryption fails."""


# --------------------------------------------------------------------------- #
# Passwords
# --------------------------------------------------------------------------- #
def _password_bytes(password: str) -> bytes:
    """Encode and length-limit a password for bcrypt.

    bcrypt silently truncates at 72 bytes.  To keep behaviour explicit (and to
    support arbitrary length passwords safely) we SHA-256 stretch anything
    longer than the limit into a fixed 32-byte digest.

    Args:
        password: The plaintext password.

    Returns:
        Bytes suitable for :mod:`bcrypt`.
    """
    raw = password.encode("utf-8")
    if len(raw) > _BCRYPT_MAX_BYTES:
        import hashlib

        return hashlib.sha256(raw).hexdigest().encode("ascii")
    return raw


def hash_password(password: str) -> str:
    """Hash a plaintext password with bcrypt.

    Args:
        password: The plaintext password.

    Returns:
        The bcrypt hash as a UTF-8 string.

    Raises:
        ValueError: If ``password`` is empty.
    """
    if not password:
        raise ValueError("password must not be empty")
    rounds = max(4, int(get_settings().bcrypt_rounds))
    salt = bcrypt.gensalt(rounds=rounds)
    return bcrypt.hashpw(_password_bytes(password), salt).decode("utf-8")


def verify_password(plain_password: str, password_hash: str) -> bool:
    """Verify a plaintext password against a bcrypt hash.

    Args:
        plain_password: Candidate plaintext password.
        password_hash: Stored bcrypt hash.

    Returns:
        ``True`` when the password matches, ``False`` otherwise.
    """
    if not plain_password or not password_hash:
        return False
    try:
        return bcrypt.checkpw(_password_bytes(plain_password), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


# --------------------------------------------------------------------------- #
# JWT
# --------------------------------------------------------------------------- #
TokenType = Literal["access", "refresh"]


def _create_token(subject: str, token_type: TokenType, expires_delta: timedelta,
                  extra: dict[str, Any] | None = None, version: int = 0) -> str:
    """Create a signed JWT.

    Args:
        subject: The token subject (user id).
        token_type: ``access`` or ``refresh``.
        expires_delta: Lifetime of the token.
        extra: Additional claims to embed.
        version: The account's ``token_version`` at issue time.  A later
            mismatch means the token was revoked (logout / password change).

    Returns:
        The encoded JWT string.
    """
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": str(subject),
        "type": token_type,
        "ver": int(version),
        "iat": int(now.timestamp()),
        "exp": int((now + expires_delta).timestamp()),
        "jti": base64.urlsafe_b64encode(os.urandom(12)).decode().rstrip("="),
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def claim_version(claims: dict[str, Any]) -> int:
    """Return the token's session-generation claim (``0`` for legacy tokens)."""
    try:
        return int(claims.get("ver", 0))
    except (TypeError, ValueError):
        return -1


def create_access_token(
    subject: str, extra: dict[str, Any] | None = None, version: int = 0
) -> str:
    """Create an access token for ``subject``."""
    settings = get_settings()
    return _create_token(
        subject,
        "access",
        timedelta(minutes=settings.access_token_expire_minutes),
        extra,
        version,
    )


def create_refresh_token(
    subject: str, extra: dict[str, Any] | None = None, version: int = 0
) -> str:
    """Create a refresh token for ``subject``."""
    settings = get_settings()
    return _create_token(
        subject,
        "refresh",
        timedelta(days=settings.refresh_token_expire_days),
        extra,
        version,
    )


def decode_token(token: str) -> dict[str, Any]:
    """Decode and validate a JWT.

    Args:
        token: The encoded JWT.

    Returns:
        The decoded claims.

    Raises:
        TokenError: If the token is invalid, expired or malformed.
    """
    settings = get_settings()
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])
    except JWTError as exc:  # pragma: no cover - exercised via API tests
        raise TokenError(str(exc)) from exc


# --------------------------------------------------------------------------- #
# AES-256-GCM encryption at rest
# --------------------------------------------------------------------------- #
_GCM_NONCE_BYTES = 12
_GCM_TAG_BYTES = 16
#: Marker prefixed to every ciphertext so encrypted values are recognisable.
_ENC_PREFIX = "enc:v1:"


def encrypt_value(plaintext: str | None) -> str | None:
    """Encrypt a string with AES-256-GCM.

    The returned token is ``enc:v1:<base64(nonce || ciphertext || tag)>``.

    Args:
        plaintext: Value to encrypt. ``None`` is passed through unchanged.

    Returns:
        The encrypted, prefixed token, or ``None``.
    """
    if plaintext is None:
        return None
    if plaintext.startswith(_ENC_PREFIX):
        # Already encrypted (idempotent).
        return plaintext
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        aes = AESGCM(get_settings().encryption_key_bytes())
        nonce = os.urandom(_GCM_NONCE_BYTES)
        ciphertext = aes.encrypt(nonce, plaintext.encode("utf-8"), None)
        token = base64.b64encode(nonce + ciphertext).decode("ascii")
        return f"{_ENC_PREFIX}{token}"
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("encryption_failed", error=str(exc))
        raise EncryptionError("Failed to encrypt value") from exc


def decrypt_value(token: str | None) -> str | None:
    """Decrypt a value produced by :func:`encrypt_value`.

    Values that do not carry the ``enc:v1:`` prefix are returned unchanged so
    the function is safe to call on legacy plaintext columns.

    Args:
        token: The encrypted token (or plaintext).

    Returns:
        The decrypted plaintext, or ``None``.

    Raises:
        EncryptionError: When the token is corrupt or the key is wrong.
    """
    if token is None:
        return None
    if not token.startswith(_ENC_PREFIX):
        return token
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        raw = base64.b64decode(token[len(_ENC_PREFIX):])
        nonce, ciphertext = raw[:_GCM_NONCE_BYTES], raw[_GCM_NONCE_BYTES:]
        aes = AESGCM(get_settings().encryption_key_bytes())
        return aes.decrypt(nonce, ciphertext, None).decode("utf-8")
    except Exception as exc:
        logger.error("decryption_failed", error=str(exc))
        raise EncryptionError("Failed to decrypt value") from exc


def constant_time_compare(left: str, right: str) -> bool:
    """Constant-time string comparison for secrets."""
    import hmac

    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))
