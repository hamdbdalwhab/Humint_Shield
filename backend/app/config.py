"""Application configuration for HUMINT Shield.

All settings are sourced from environment variables / a ``.env`` file using
``pydantic-settings``.  Nothing is hard-coded: every value has a safe default
suitable for local development, and production values are injected via the
environment.
"""
from __future__ import annotations

import functools
import json
import os
import secrets
from typing import Annotated, List

from pydantic import AliasChoices, Field, field_validator, model_validator
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

    # --- IllyVoIP (real outbound vishing / Voice API) ---------------------
    #: Real outbound voice calls and native TTS.  Missing values disable the
    #: real vishing channel; no call is ever simulated.
    illyvoip_api_key: str = ""
    #: Accept both the documented ``ILLYVOIP_API_URL`` spelling and the older
    #: ``ILLYVOIP_API_BASE_URL`` name so existing deployments keep working.
    illyvoip_api_base_url: str = Field(
        default="https://api.illyvoip.com",
        validation_alias=AliasChoices(
            "ILLYVOIP_API_URL", "ILLYVOIP_API_BASE_URL"
        ),
    )
    #: SIP identity that places the call.  Found in the IllyVoIP dashboard.
    illyvoip_sip_user_id: str = ""
    #: Verified/owned caller ID presented to the recipient.
    illyvoip_caller_id: str = ""
    illyvoip_timeout_seconds: float = 20.0
    #: How long to wait for the recipient to answer before hanging up.
    illyvoip_answer_timeout_seconds: float = 45.0
    #: An answer faster than this after the destination started ringing is not
    #: a person picking up: it is a voicemail, an IVR or a carrier announcement.
    #: The call is still reported, but never as a verified human answer.
    illyvoip_min_answer_delay_seconds: float = 1.0
    illyvoip_poll_interval_seconds: float = 2.0
    #: Default Voice API TTS language/voice.  The service passes these values
    #: to IllyVoIP; it never falls back to browser TTS.  A script written in
    #: Arabic is spoken with ``ILLYVOIP_TTS_ARABIC_LANGUAGE`` instead, because
    #: an Arabic script read by an ``en-US`` voice is unintelligible.
    illyvoip_tts_language: str = "en-US"
    illyvoip_tts_voice: str = "illyvoip-emma"
    #: Language used when the script itself is Arabic and the caller did not
    #: choose a language explicitly.
    illyvoip_tts_arabic_language: str = "ar-AR"
    #: Used to keep the call open after /speak returns.  The provider's speak
    #: endpoint does not expose a playback-completion flag.
    illyvoip_tts_chars_per_second: float = 12.0
    illyvoip_tts_padding_seconds: float = 2.0
    #: How long to retry a voice_request_pending response with the same key.
    illyvoip_tts_pending_timeout_seconds: float = 30.0
    illyvoip_max_speech_wait_seconds: int = 180
    illyvoip_wait_chunk_seconds: int = 15
    illyvoip_record_calls: bool = False
    #: Optional sandbox scenario header.  Leave blank for production.
    illyvoip_sandbox_scenario: str = ""

    @property
    def illyvoip_api_key_configured(self) -> bool:
        """Return ``True`` when a non-placeholder IllyVoIP API key is set."""
        key = (self.illyvoip_api_key or "").strip()
        if not key:
            return False
        placeholders = (
            "your",
            "change-me",
            "change_me",
            "example",
            "placeholder",
            "todo",
            "<",
        )
        return not key.lower().startswith(placeholders)

    def illyvoip_missing_settings(self) -> list[str]:
        """Return the settings that physically block a real call.

        Only the API key and base URL are required: IllyVoIP treats
        ``sip_user_id`` and ``from`` as optional and falls back to the
        account's main SIP identity and default caller ID.  Missing optional
        identity values are reported by :meth:`illyvoip_identity_warnings`
        instead of blocking the channel.
        """
        missing: list[str] = []
        if not self.illyvoip_api_key_configured:
            missing.append("ILLYVOIP_API_KEY")
        if not (self.illyvoip_api_base_url or "").strip():
            missing.append("ILLYVOIP_API_BASE_URL")
        return missing

    def illyvoip_identity_warnings(self) -> list[str]:
        """Return optional identity settings that are unset or placeholders.

        The provider then uses the account defaults, which may not be the
        caller ID an operator expects to present, so the UI surfaces it.
        """
        placeholders = (
            "your",
            "change-me",
            "change_me",
            "example",
            "placeholder",
            "todo",
            "<",
        )
        warnings: list[str] = []
        sip = (self.illyvoip_sip_user_id or "").strip()
        if not sip or sip.lower().startswith(placeholders):
            warnings.append("ILLYVOIP_SIP_USER_ID")
        caller = (self.illyvoip_caller_id or "").strip()
        if not caller or caller.lower().startswith(placeholders):
            warnings.append("ILLYVOIP_CALLER_ID")
        return warnings

    @property
    def illyvoip_configured(self) -> bool:
        """Return ``True`` when the real vishing channel can place a call."""
        return not self.illyvoip_missing_settings()

    # --- SMS delivery (TextBee Android gateway) ---------------------------
    #: SMS has exactly one transport: the TextBee Android gateway.  Leaving
    #: ``TEXTBEE_API_KEY`` blank disables the SMS channel; nothing else is tried.
    sms_provider: str = "textbee"
    textbee_api_key: str = ""
    #: Device id from ``GET /gateway/devices``.  When blank the account's
    #: default device is resolved at send time.
    textbee_device_id: str = ""
    textbee_base_url: str = "https://api.textbee.dev/api/v1"
    textbee_timeout_seconds: float = 20.0

    @property
    def textbee_api_key_configured(self) -> bool:
        """Return ``True`` when a non-placeholder TextBee API key is set."""
        key = (self.textbee_api_key or "").strip()
        if not key:
            return False
        placeholders = ("your", "change-me", "change_me", "example", "placeholder", "todo", "<")
        return not key.lower().startswith(placeholders)

    def textbee_missing_settings(self) -> list[str]:
        """Return the settings that block a real TextBee SMS.

        The device id is optional: TextBee falls back to the account's default
        phone, and the service resolves it explicitly when possible.
        """
        missing: list[str] = []
        if not self.textbee_api_key_configured:
            missing.append("TEXTBEE_API_KEY")
        if not (self.textbee_base_url or "").strip():
            missing.append("TEXTBEE_BASE_URL")
        return missing

    @property
    def textbee_configured(self) -> bool:
        """Return ``True`` when TextBee can queue an SMS."""
        return not self.textbee_missing_settings()

    @property
    def sms_provider_effective(self) -> str:
        """Return the provider that will send an SMS.

        TextBee is the only SMS transport; ``"none"`` means the channel is
        disabled because the gateway is not configured.
        """
        return "textbee" if self.textbee_configured else "none"

    # --- WhatsApp delivery (WA-AKG gateway) -------------------------------
    #: Self-hosted WA-AKG instance.  ``WA_AKG_API_URL`` is the API root that
    #: already contains ``/api`` (for example ``http://localhost:3000/api``).
    wa_akg_api_url: str = "http://localhost:3000/api"
    wa_akg_api_key: str = ""
    #: Session (device) id created in the WA-AKG dashboard after the QR scan.
    wa_akg_session_id: str = ""
    wa_akg_timeout_seconds: float = 25.0
    #: Anti-ban pacing between two outbound WhatsApp messages.
    wa_akg_min_delay_seconds: float = 10.0
    wa_akg_max_delay_seconds: float = 30.0
    #: Optional shared secret WA-AKG sends back on webhook deliveries.
    wa_akg_webhook_secret: str = ""

    @property
    def wa_akg_api_key_configured(self) -> bool:
        """Return ``True`` when a non-placeholder WA-AKG API key is set."""
        key = (self.wa_akg_api_key or "").strip()
        if not key:
            return False
        placeholders = ("your", "change-me", "change_me", "example", "placeholder", "todo", "<")
        return not key.lower().startswith(placeholders)

    def whatsapp_missing_settings(self) -> list[str]:
        """Return the settings that block a real WhatsApp message."""
        missing: list[str] = []
        if not (self.wa_akg_api_url or "").strip():
            missing.append("WA_AKG_API_URL")
        if not self.wa_akg_api_key_configured:
            missing.append("WA_AKG_API_KEY")
        if not (self.wa_akg_session_id or "").strip():
            missing.append("WA_AKG_SESSION_ID")
        return missing

    @property
    def whatsapp_configured(self) -> bool:
        """Return ``True`` when WA-AKG can send a WhatsApp message."""
        return not self.whatsapp_missing_settings()

    @property
    def whatsapp_provider_effective(self) -> str:
        """Return the provider that will send a WhatsApp message."""
        return "wa-akg" if self.whatsapp_configured else "none"

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
    #: Clean public origin written into SMS bodies, e.g. ``https://hument.link``.
    #: It must serve this application (or redirect to it) for short links to
    #: resolve; when empty, ``BASE_URL`` is used so local development still works.
    short_link_base_url: str | None = None
    #: When no custom short domain is configured, shorten ``BASE_URL/s/{code}``
    #: with the keyless v.gd API so messages never expose the tunnel host.
    #: Set to ``none`` to keep the local URL (offline development).
    short_link_provider: str = "vgd"
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

    # --- Reverse proxy ------------------------------------------------------
    #: Trust ``CF-Connecting-IP`` / ``X-Forwarded-For`` for the client address.
    #: Only enable this when the app is reachable exclusively through a proxy
    #: (nginx, Cloudflare) that overwrites those headers; otherwise a client can
    #: choose its own rate-limit bucket.
    trust_proxy_headers: bool = True

    # --- Observability -----------------------------------------------------
    log_level: str = "INFO"
    log_json: bool = True
    #: Expose Prometheus metrics at ``/metrics``.  Off by default: the endpoint
    #: is unauthenticated at the application layer and must be enabled only on
    #: an internal listener (nginx additionally restricts it by IP + basic auth).
    metrics_enabled: bool = False

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

    @model_validator(mode="after")
    def _enforce_production_secrets(self) -> "Settings":
        """Refuse to start production with generated or default secrets.

        ``secret_key`` and ``encryption_key`` fall back to a fresh random value
        for local development.  In production that default silently invalidates
        every issued token and every encrypted column on each restart, and it
        differs between worker processes, so it is rejected instead.

        Returns:
            The validated settings instance.

        Raises:
            ValueError: When production is started without explicit keys or
                with the shipped bootstrap admin password.
        """
        if not self.is_production:
            return self
        problems: list[str] = []
        for field_name in ("secret_key", "encryption_key"):
            if field_name not in self.model_fields_set:
                problems.append(f"{field_name.upper()} must be set explicitly")
            elif len(getattr(self, field_name).strip()) < 32:
                problems.append(f"{field_name.upper()} must be at least 32 characters")
        if self.bootstrap_admin_password.strip() == "ChangeMe123!":
            problems.append("BOOTSTRAP_ADMIN_PASSWORD must be changed from the shipped default")
        if problems:
            raise ValueError(
                "Unsafe production configuration: " + "; ".join(problems)
            )
        return self

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


def env_files() -> tuple[str, ...]:
    """Return the dotenv files to load, in increasing precedence.

    ``APP_ENV`` (falling back to ``ENVIRONMENT``) selects an environment
    overlay: ``APP_ENV=production`` reads ``.env`` and then ``.env.production``,
    so the base file can hold shared defaults while the overlay carries the
    environment-specific values.  Real process environment variables always
    win over both files.

    Returns:
        A tuple of file names, later files overriding earlier ones.
    """
    overlay = (
        os.environ.get("APP_ENV")
        or os.environ.get("ENVIRONMENT")
        or ""
    ).strip().lower()
    files: list[str] = [".env"]
    if overlay:
        files.append(f".env.{overlay}")
    return tuple(files)


@functools.lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide cached :class:`Settings` instance."""
    return Settings(_env_file=env_files())


# Re-exported for documentation and tests.
__all__ = ["Settings", "env_files", "get_settings"]
