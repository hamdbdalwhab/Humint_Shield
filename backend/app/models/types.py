"""Custom SQLAlchemy column types.

``EncryptedString`` transparently encrypts values with AES-256-GCM before they
are written to the database and decrypts them on read, satisfying the
"encryption at rest for sensitive fields" requirement.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import String, TypeDecorator

from app.security import decrypt_value, encrypt_value


class EncryptedString(TypeDecorator):
    """A ``String`` column whose contents are AES-256-GCM encrypted at rest.

    The underlying column always stores a ``TEXT`` payload containing the
    base64 encoded ciphertext (prefixed with ``enc:v1:``), so the database
    never sees the plaintext value for a protected field.
    """

    impl = String
    cache_ok = True

    def __init__(self, length: int | None = None, **kwargs: Any) -> None:
        # Ciphertext is longer than the plaintext; give ample headroom.
        super().__init__(**kwargs)
        self.length = length

    def load_dialect_impl(self, dialect):  # noqa: ANN001, ANN201
        """Use an unbounded ``TEXT`` column on every dialect."""
        return dialect.type_descriptor(String(None))

    def process_bind_param(self, value: Any, dialect) -> str | None:  # noqa: ANN001
        """Encrypt the value on the way into the database."""
        if value is None:
            return None
        return encrypt_value(str(value))

    def process_result_value(self, value: Any, dialect) -> str | None:  # noqa: ANN001
        """Decrypt the value on the way out of the database."""
        if value is None:
            return None
        return decrypt_value(str(value))
