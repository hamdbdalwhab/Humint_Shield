"""Application-level encryption for sensitive columns stored as ``BYTEA``.

This is the column-encryption counterpart of :mod:`app.security`'s string
helpers.  Values are sealed with AES-256-GCM using the deployment's
``ENCRYPTION_KEY`` and stored as raw bytes so PostgreSQL can keep them in a
native ``BYTEA`` (``BLOB`` on SQLite).

Wire format::

    b"HS1" || nonce(12 bytes) || ciphertext || GCM tag(16 bytes)

The three-byte magic prefix lets a reader tell an encrypted value from legacy
plaintext without attempting a decryption, and the GCM tag detects any
tampering or a wrong key.

Never log or return the raw bytes: use :func:`decrypt_text`.
"""
from __future__ import annotations

import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config import get_settings
from app.security import EncryptionError

#: Marks a value produced by this service (and distinguishes it from the
#: ``enc:v1:`` string format used by older columns).
MAGIC = b"HS1"
NONCE_BYTES = 12


def encrypt_text(plaintext: str | None) -> bytes | None:
    """Encrypt ``plaintext`` into a self-describing byte string.

    Args:
        plaintext: The value to protect. ``None`` and blank strings are
            returned as ``None`` so "no value" stays distinct from "".

    Returns:
        ``MAGIC || nonce || ciphertext+tag``, or ``None``.

    Raises:
        EncryptionError: When the cipher backend fails.
    """
    if plaintext is None:
        return None
    text = str(plaintext)
    if not text:
        return None
    try:
        nonce = os.urandom(NONCE_BYTES)
        sealed = AESGCM(get_settings().encryption_key_bytes()).encrypt(
            nonce, text.encode("utf-8"), None
        )
        return MAGIC + nonce + sealed
    except Exception as exc:  # pragma: no cover - defensive
        raise EncryptionError("Failed to encrypt column value") from exc


def decrypt_text(blob: bytes | None) -> str | None:
    """Decrypt a value produced by :func:`encrypt_text`.

    Args:
        blob: The stored bytes, or ``None``.

    Returns:
        The plaintext, or ``None`` when nothing is stored.

    Raises:
        EncryptionError: When the value is corrupt, truncated or was sealed
            with a different key.
    """
    if blob is None:
        return None
    if not isinstance(blob, (bytes, bytearray, memoryview)):
        raise EncryptionError("Encrypted column is not bytes")
    raw = bytes(blob)
    if not raw.startswith(MAGIC):
        raise EncryptionError("Encrypted column has an unknown format")
    body = raw[len(MAGIC):]
    if len(body) <= NONCE_BYTES:
        raise EncryptionError("Encrypted column is truncated")
    nonce, sealed = body[:NONCE_BYTES], body[NONCE_BYTES:]
    try:
        return AESGCM(get_settings().encryption_key_bytes()).decrypt(
            nonce, sealed, None
        ).decode("utf-8")
    except (InvalidTag, ValueError, UnicodeDecodeError) as exc:
        raise EncryptionError("Failed to decrypt column value") from exc


def try_decrypt_text(blob: bytes | None) -> str | None:
    """Best-effort decryption used by read paths.

    A key rotation or a corrupt row must not take an entire list endpoint down,
    so failures are swallowed here and callers fall back to the legacy
    plaintext column.
    """
    if blob is None:
        return None
    try:
        return decrypt_text(blob)
    except EncryptionError:
        return None


__all__ = ["MAGIC", "decrypt_text", "encrypt_text", "try_decrypt_text"]
