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

    # --- Vonage (SMS + WhatsApp) ------------------------------------------
    #: Vonage API credentials.  Create an API key/secret in the Vonage
    #: dashboard.  Missing values disable real SMS/WhatsApp delivery; the email
    #: channel continues to work.
    vonage_api_key: str = ""
    vonage_api_secret: str = ""
    #: Alphanumeric Sender ID (SMS) or WhatsApp Sandbox/business number.
    vonage_sms_from: str = "Vonage APIs"
    vonage_whatsapp_from: str = ""
    #: Optional Vonage Application credentials for JWT-authenticated Messages
    #: API calls.  The private key can be the PEM content itself or a path to
    #: the downloaded ``.key`` file.  When both are set, WhatsApp uses JWT;
    #: otherwise the SDK falls back to API key/secret authentication.
    vonage_application_id: str = ""
    vonage_private_key: str = ""
    #: Optional Messages API host, for example the WhatsApp sandbox endpoint
    #: ``https://messages-sandbox.nexmo.com``.  Empty uses Vonage production.
    vonage_messages_base_url: str = ""
    #: Per-request timeout for the synchronous Vonage SDK calls.
    vonage_timeout_seconds: float = 15.0
    #: Optional shared secret appended to the dashboard webhook URLs as
    #: ``?token=...`` (or sent as ``X-Vonage-Webhook-Token``).  When set, the
    #: webhook endpoints reject callbacks without it.
    vonage_webhook_token: str = ""

    @property
    def vonage_credentials_configured(self) -> bool:
        """Return ``True`` when non-placeholder API credentials are present."""
        key = (self.vonage_api_key or "").strip()
        secret = (self.vonage_api_secret or "").strip()
        placeholders = ("your", "change-me", "example")
        if not key or not secret:
            return False
        if key.lower().startswith(placeholders) or secret.lower().startswith(placeholders):
            return False
        return True

    @property
    def vonage_sms_configured(self) -> bool:
        """Return ``True`` when SMS credentials and a sender are configured."""
        sender = (self.vonage_sms_from or "").strip()
        return bool(self.vonage_credentials_configured and sender)

    @property
    def vonage_whatsapp_configured(self) -> bool:
        """Return ``True`` when WhatsApp credentials and a sender are configured."""
        sender = (self.vonage_whatsapp_from or "").strip()
        app_id = (self.vonage_application_id or "").strip()
        private_key = (self.vonage_private_key or "").strip()
        # Application credentials are optional, but a partial pair is almost
        # always a misconfiguration.  Refuse it instead of silently falling
        # back to API key/secret authentication.
        if bool(app_id) != bool(private_key):
            return False
        return bool(self.vonage_credentials_configured and sender)

    @property
    def vonage_application_configured(self) -> bool:
        """Return ``True`` when both application ID and private key are set."""
        return bool(
            (self.vonage_application_id or "").strip()
            and (self.vonage_private_key or "").strip()
        )

    @property
    def vonage_configured(self) -> bool:
        """Return ``True`` when the API credentials are configured.

        Channel-specific readiness is exposed by :attr:`vonage_sms_configured`
        and :attr:`vonage_whatsapp_configured`; this property is the common
        credential check used by the diagnostics endpoint.
        """
        return self.vonage_credentials_configured

    def vonage_missing_settings(self, channel: str) -> list[str]:
        """Return the environment variable names required for ``channel``.

        Args:
            channel: ``sms`` or ``whatsapp``.

        Returns:
            A sorted list of missing/placeholder environment variable names.
        """
        missing: list[str] = []
        if not self.vonage_credentials_configured:
            missing.extend(["VONAGE_API_KEY", "VONAGE_API_SECRET"])
        if channel == "sms" and not (self.vonage_sms_from or "").strip():
            missing.append("VONAGE_SMS_FROM")
        if channel == "whatsapp":
            if not (self.vonage_whatsapp_from or "").strip():
                missing.append("VONAGE_WHATSAPP_FROM")
            app_id = (self.vonage_application_id or "").strip()
            private_key = (self.vonage_private_key or "").strip()
            if bool(app_id) != bool(private_key):
                missing.extend(["VONAGE_APPLICATION_ID", "VONAGE_PRIVATE_KEY"])
        return missing

    # --- AI template generation -------------------------------------------
    #: OpenAI-compatible chat-completions provider.  ``openai`` and ``groq``
    #: have sensible defaults; ``custom`` requires an explicit base URL and
    #: model.  No provider SDK is required — the service uses ``httpx``.
    llm_provider: str = "openai"
    llm_api_key: str = ""
    llm_model: str = ""
    llm_fallback_models: str = ""
    llm_base_url: str = ""
    #: Timeout for fallback models.  The primary model has a shorter budget so a
    #: slow/queued primary cannot consume the whole Cloudflare request window.
    llm_timeout_seconds: float = 60.0
    llm_primary_timeout_seconds: float = 30.0
    llm_max_tokens: int = 1800

    @property
    def llm_provider_slug(self) -> str:
        """Return the normalized provider name."""
        return (self.llm_provider or "openai").strip().lower()

    @property
    def llm_base_url_resolved(self) -> str:
        """Return the provider base URL, including the ``/v1`` suffix."""
        configured = (self.llm_base_url or "").strip().rstrip("/")
        if configured:
            return configured
        if self.llm_provider_slug == "groq":
            return "https://api.groq.com/openai/v1"
        if self.llm_provider_slug == "openai":
            return "https://api.openai.com/v1"
        return ""

    @property
    def llm_model_resolved(self) -> str:
        """Return the configured model or the provider's default."""
        configured = (self.llm_model or "").strip()
        if configured:
            return configured
        if self.llm_provider_slug == "groq":
            return "llama-3.3-70b-versatile"
        if self.llm_provider_slug == "openai":
            return "gpt-4o-mini"
        return ""

    @property
    def llm_fallback_model_list(self) -> list[str]:
        """Return the optional fallback models in configured order.

        The value is a comma separated list so a deployment can add models
        without changing code.  Blank entries and duplicates are removed.
        """
        raw = (self.llm_fallback_models or "").strip()
        if not raw:
            return []
        models: list[str] = []
        seen: set[str] = set()
        for part in raw.split(","):
            model = part.strip()
            if model and model not in seen:
                seen.add(model)
                models.append(model)
        return models

    @property
    def llm_configured(self) -> bool:
        """Return ``True`` when a key, base URL and model are all available."""
        key = (self.llm_api_key or "").strip()
        placeholders = ("your", "change-me", "example", "sk-your")
        if not key or key.lower().startswith(placeholders):
            return False
        return bool(self.llm_base_url_resolved and self.llm_model_resolved)

    def llm_missing_settings(self) -> list[str]:
        """Return the environment variable names needed for AI generation."""
        missing: list[str] = []
        key = (self.llm_api_key or "").strip()
        placeholders = ("your", "change-me", "example", "sk-your")
        if not key or key.lower().startswith(placeholders):
            missing.append("LLM_API_KEY")
        if not self.llm_base_url_resolved:
            missing.append("LLM_BASE_URL")
        if not self.llm_model_resolved:
            missing.append("LLM_MODEL")
        return missing

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

    # --- Enterprise Directory & SOAR Automated Containment -----------------
    containment_enabled: bool = True
    containment_simulation_mode: bool = False

    # Active Directory (On-Premises)
    ad_enabled: bool = False
    ad_domain_controller: str = ""
    ad_domain: str = ""
    ad_service_account_user: str = ""
    ad_service_account_password: str = ""
    ad_strict_password_group: str = "Enforced_Strict_Password_Group"
    ad_use_powershell_native: bool = True

    # Microsoft Entra ID / Microsoft 365 (Azure AD)
    entra_id_enabled: bool = False
    entra_tenant_id: str = ""
    entra_client_id: str = ""
    entra_client_secret: str = ""
    entra_high_risk_group_id: str = ""

    # SOAR / SIEM Webhook Integration
    soar_webhook_enabled: bool = False
    soar_webhook_url: str = ""
    soar_webhook_secret: str = ""

    @property
    def entra_configured(self) -> bool:
        """Return ``True`` when Microsoft Entra ID API credentials are set."""
        return bool(
            self.entra_id_enabled
            and (self.entra_tenant_id or "").strip()
            and (self.entra_client_id or "").strip()
            and (self.entra_client_secret or "").strip()
        )

    @property
    def ad_configured(self) -> bool:
        """Return ``True`` when Active Directory domain controller is set."""
        return bool(
            self.ad_enabled
            and (self.ad_domain_controller or "").strip()
        )

    @property
    def soar_configured(self) -> bool:
        """Return ``True`` when SOAR / SIEM webhook URL is set."""
        return bool(
            self.soar_webhook_enabled
            and (self.soar_webhook_url or "").strip()
        )

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
