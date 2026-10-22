"""Application configuration for HUMINT Shield.

All settings are sourced from environment variables / a ``.env`` file using
``pydantic-settings``.  Nothing is hard-coded: every value has a safe default
suitable for local development, and production values are injected via the
environment.
"""
from __future__ import annotations

import functools
import json
import secrets
from typing import Annotated, List

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    """Strongly typed application settings.

    Attributes are grouped by concern (database, security, email, ...).  A
    single shared instance is produced by :func:`get_settings` and cached.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- General -----------------------------------------------------------
    app_name: str = "HUMINT Shield"
    app_version: str = "1.0.0"
    environment: str = "development"
    debug: bool = False

    # --- Database ----------------------------------------------------------
    database_url: str = "sqlite+aiosqlite:///./humint_shield.db"
    db_echo: bool = False
    db_pool_size: int = 10
    db_max_overflow: int = 20
    #: Create tables from the ORM metadata on startup.  Production deployments
    #: set this to ``false`` and let Alembic own the schema.
    auto_create_schema: bool = True
    #: Seed the bootstrap org/admin/templates/modules on startup.
    auto_seed: bool = True

    # --- Redis -------------------------------------------------------------
    redis_url: str = "redis://localhost:6379/0"

    # --- Security ----------------------------------------------------------
    secret_key: str = Field(default_factory=lambda: secrets.token_hex(32))
    encryption_key: str = Field(default_factory=lambda: secrets.token_hex(32))
    access_token_expire_minutes: int = 60
    refresh_token_expire_days: int = 7
    jwt_algorithm: str = "HS256"
    bcrypt_rounds: int = 12

    # --- Email delivery ----------------------------------------------------
    #: ``brevo`` uses the Brevo API; ``smtp`` uses a mailbox (e.g. Gmail) so the
    #: envelope sender matches the From header and SPF/DKIM/DMARC all pass.
    email_transport: str = "brevo"
    brevo_api_key: str = ""
    from_email: str = "security-training@example.com"
    from_name: str = "Security Training"
    email_dry_run: bool = False
    email_max_retries: int = 3
    email_timeout_seconds: float = 15.0
    #: Base delay (seconds) before the first email retry; doubles each time.
    email_retry_base_delay: float = 2.0

    # --- SMTP transport (used when ``EMAIL_TRANSPORT=smtp``) --------------
    smtp_host: str = ""
    smtp_port: int = 465
    smtp_username: str = ""
    smtp_password: str = ""
    #: Implicit TLS (port 465). Set to ``false`` for STARTTLS on port 587.
    smtp_use_ssl: bool = True

    @property
    def smtp_configured(self) -> bool:
        """Return ``True`` when host, username and password are all set."""
        return bool(
            (self.smtp_host or "").strip()
            and (self.smtp_username or "").strip()
            and (self.smtp_password or "").strip()
        )

    @property
    def smtp_transport(self) -> bool:
        """Return ``True`` when outbound mail should use SMTP, not Brevo."""
        return (self.email_transport or "").strip().lower() == "smtp"

    # --- Application -------------------------------------------------------
    base_url: str = "http://localhost:8000"
    frontend_url: str = "http://localhost:5173"
    #: Serve the built React dashboard from this process.  When enabled, a single
    #: public URL exposes both the API and the UI (no second tunnel needed).
    serve_frontend: bool = True
    #: Path to the built frontend.  Empty means ``<repo>/frontend/dist``.
    frontend_dist: str = ""
    #: Origins allowed to call the API. Accepts a comma separated string or a
    #: JSON array; ``NoDecode`` keeps the raw value for the validator below.
    cors_origins: Annotated[List[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:5173"]
    )

    # --- Rate limiting -----------------------------------------------------
    rate_limit_enabled: bool = True
    rate_limit_requests: int = 100
    rate_limit_window_seconds: int = 60
    rate_limit_auth_requests: int = 10

    # --- Observability -----------------------------------------------------
    log_level: str = "INFO"
    log_json: bool = True

    # --- Retention ---------------------------------------------------------
    data_retention_days: int = 365

    # --- Bootstrap ---------------------------------------------------------
    bootstrap_admin_username: str = "admin"
    bootstrap_admin_email: str = "admin@example.com"
    bootstrap_admin_password: str = "ChangeMe123!"
    bootstrap_org_name: str = "Acme Corporation"
    bootstrap_org_domain: str = "example.com"
    seed_builtin_templates: bool = True

    # ------------------------------------------------------------------ #
    # Validators
    # ------------------------------------------------------------------ #
    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_cors(cls, value: object) -> object:
        """Accept either a JSON array or a comma separated string.

        The field is annotated with :data:`~pydantic_settings.NoDecode` so the
        raw string reaches this validator: without that, ``pydantic-settings``
        tries to JSON-decode it and the documented
        ``CORS_ORIGINS=http://a,http://b`` form crashes startup.
        """
        if isinstance(value, str):
            text = value.strip()
            if text.startswith("["):
                try:
                    decoded = json.loads(text)
                except json.JSONDecodeError as exc:
                    raise ValueError(
                        f"CORS_ORIGINS must be a JSON array or a comma separated "
                        f"string; got {value!r} ({exc})"
                    ) from exc
                if not isinstance(decoded, list):
                    raise ValueError("CORS_ORIGINS JSON form must be an array")
                return decoded
            return [origin.strip() for origin in text.split(",") if origin.strip()]
        return value

    @field_validator("log_level")
    @classmethod
    def _upper_level(cls, value: str) -> str:
        return value.upper()

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    @property
    def is_production(self) -> bool:
        """Return ``True`` when running in a production environment."""
        return self.environment.lower() in {"production", "prod"}

    @property
    def is_sqlite(self) -> bool:
        """Return ``True`` when the configured database is SQLite."""
        return self.database_url.startswith("sqlite")

    @property
    def brevo_configured(self) -> bool:
        """Return ``True`` when a non-placeholder Brevo API key is present."""
        key = (self.brevo_api_key or "").strip()
        return bool(key) and not key.lower().startswith("your")

    def encryption_key_bytes(self) -> bytes:
        """Return the raw 32-byte AES key derived from ``encryption_key``.

        The value may be supplied either as 64 hex characters (recommended) or
        as an arbitrary passphrase which is stretched with SHA-256.

        Returns:
            A 32-byte key suitable for AES-256-GCM.
        """
        import hashlib

        raw = (self.encryption_key or "").strip()
        try:
            key = bytes.fromhex(raw)
            if len(key) == 32:
                return key
        except ValueError:
            pass
        # Fall back to deterministic stretching of an arbitrary secret.
        return hashlib.sha256(raw.encode("utf-8")).digest()


@functools.lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide cached :class:`Settings` instance."""
    return Settings()
