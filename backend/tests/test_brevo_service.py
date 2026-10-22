"""Tests for the Brevo email service (SDK is mocked; no real mail is sent)."""
from __future__ import annotations

import smtplib
from types import SimpleNamespace

import pytest

from app.config import Settings
from app.services.brevo_email_service import (
    AUTHORISED_IPS_URL,
    BrevoEmailService,
    BrevoTransientError,
    SendResult,
    _describe_failure,
)


def _settings(**overrides) -> Settings:
    """Build a Settings object tuned for tests."""
    base = {
        "brevo_api_key": "xkeysib-test-key",
        "from_email": "training@acmetest.example",
        "from_name": "Security Training",
        "email_dry_run": False,
        "email_max_retries": 3,
        "email_retry_base_delay": 0.001,
        "email_timeout_seconds": 5.0,
        "base_url": "http://testserver",
    }
    base.update(overrides)
    return Settings(**base)


class _HttpError(Exception):
    """Stand-in for ``sib_api_v3_sdk.rest.ApiException``; carries an HTTP status."""

    def __init__(self, status: int, body: str) -> None:
        super().__init__(body)
        self.status = status
        self.body = body


class FakeApi:
    """Minimal stand-in for ``TransactionalEmailsApi``."""

    def __init__(self, fail_times: int = 0, status: int = 500) -> None:
        self.fail_times = fail_times
        self.status = status
        self.calls = 0
        self.payloads: list = []

    def send_transac_email(self, payload):  # noqa: ANN001, ANN201
        """Record the payload and optionally fail for a number of attempts."""
        self.calls += 1
        self.payloads.append(payload)
        if self.calls <= self.fail_times:
            raise _HttpError(self.status, f"simulated http {self.status}")
        return SimpleNamespace(message_id=f"<msg-{self.calls}@brevo>")


async def test_send_success(monkeypatch) -> None:
    """A successful send returns the Brevo message id."""
    service = BrevoEmailService(_settings())
    fake = FakeApi()
    monkeypatch.setattr(service, "_build_api", lambda: fake)

    result = await service.send_training_email(
        "jane@acmetest.example", "Jane Doe", "Subject", "<p>Body</p>"
    )
    assert result["success"] is True
    assert result["message_id"] == "<msg-1@brevo>"
    assert result["error"] is None
    assert fake.calls == 1
    payload = fake.payloads[0]
    assert "Body" in payload.text_content
    assert payload.reply_to["email"] == "training@acmetest.example"


async def test_send_retries_transient_failures(monkeypatch) -> None:
    """Transient failures are retried and eventually succeed."""
    service = BrevoEmailService(_settings())
    fake = FakeApi(fail_times=2)
    monkeypatch.setattr(service, "_build_api", lambda: fake)

    result = await service.send_training_email(
        "jane@acmetest.example", "Jane Doe", "Subject", "<p>Body</p>"
    )
    assert result["success"] is True
    assert fake.calls == 3


async def test_send_exhausts_retries(monkeypatch) -> None:
    """When every attempt fails the result reports the failure."""
    service = BrevoEmailService(_settings())
    fake = FakeApi(fail_times=99)
    monkeypatch.setattr(service, "_build_api", lambda: fake)

    result = await service.send_training_email(
        "jane@acmetest.example", "Jane Doe", "Subject", "<p>Body</p>"
    )
    assert result["success"] is False
    assert result["error"] is not None
    assert fake.calls == 3


async def test_permanent_error_is_not_retried(monkeypatch) -> None:
    """A 4xx rejection fails fast instead of burning the retry budget."""
    service = BrevoEmailService(_settings())
    fake = FakeApi(fail_times=99, status=401)
    monkeypatch.setattr(service, "_build_api", lambda: fake)

    result = await service.send_training_email(
        "jane@acmetest.example", "Jane Doe", "Subject", "<p>Body</p>"
    )
    assert result["success"] is False
    assert "simulated http 401" in result["error"]
    assert fake.calls == 1, "a permanent rejection must be attempted exactly once"


async def test_dry_run_does_not_call_sdk(monkeypatch) -> None:
    """Dry-run mode short-circuits before the SDK is touched."""
    service = BrevoEmailService(_settings(email_dry_run=True))
    called = {"n": 0}

    def _build():  # pragma: no cover - must not be called
        called["n"] += 1
        raise AssertionError("SDK must not be used in dry-run mode")

    monkeypatch.setattr(service, "_build_api", _build)
    result = await service.send_training_email(
        "jane@acmetest.example", "Jane", "Subject", "<p>Body</p>"
    )
    assert result["success"] is True
    assert result["message_id"].startswith("dry-run-")
    assert called["n"] == 0


async def test_not_configured_returns_error() -> None:
    """A placeholder key produces a clear configuration error."""
    service = BrevoEmailService(_settings(brevo_api_key=""))
    result = await service.send_training_email("a@b.example", "A", "S", "<p>x</p>")
    assert result["success"] is False
    assert "not configured" in (result["error"] or "").lower()


async def test_verify_configuration_not_configured() -> None:
    """``verify_configuration`` reports an invalid key."""
    service = BrevoEmailService(_settings(brevo_api_key="your-key-here"))
    report = await service.verify_configuration()
    assert report["valid"] is False
    assert report["error"]


async def test_verify_configuration_dry_run() -> None:
    """Dry-run mode reports a valid (simulated) configuration."""
    service = BrevoEmailService(_settings(email_dry_run=True))
    report = await service.verify_configuration()
    assert report["valid"] is True
    assert report["detail"]["mode"] == "dry-run"


async def test_send_test_email(monkeypatch) -> None:
    """``send_test_email`` dispatches a diagnostic message."""
    service = BrevoEmailService(_settings())
    captured: dict = {}

    async def _fake_send(to_email, to_name, subject, html_content, correlation_id=None):  # noqa: ANN001
        captured.update(
            {"to": to_email, "subject": subject, "html": html_content, "name": to_name}
        )
        return SendResult(success=True, message_id="<test@brevo>").as_dict()

    monkeypatch.setattr(service, "send_training_email", _fake_send)
    result = await service.send_test_email("me@acmetest.example")
    assert result["success"] is True
    assert captured["to"] == "me@acmetest.example"
    assert "delivery test" in captured["subject"].lower()


def test_transient_error_permanent_flag() -> None:
    """4xx errors are flagged as permanent; 5xx are retryable."""
    assert BrevoTransientError("bad", status=400).is_permanent is True
    assert BrevoTransientError("boom", status=503).is_permanent is False
    assert BrevoTransientError("boom").is_permanent is False


def test_html_to_text_strips_markup_and_keeps_readable_copy() -> None:
    """The plain-text alternative removes tags/styles and decodes entities."""
    service = BrevoEmailService(_settings())
    text = service._html_to_text(
        "<style>.x{color:red}</style><h2>Hello &amp; welcome</h2>"
        "<p>Click <strong>here</strong>.</p><script>alert(1)</script>"
    )
    assert "Hello & welcome" in text
    assert "Click here" in text
    assert "<" not in text
    assert "alert(1)" not in text


def test_send_result_as_dict() -> None:
    """``SendResult`` serialises predictably."""
    assert SendResult(success=True, message_id="x").as_dict() == {
        "success": True,
        "message_id": "x",
        "error": None,
    }


@pytest.mark.parametrize("status", [None, 500])
async def test_unexpected_exception_is_normalised(monkeypatch, status) -> None:
    """Non-retryable surprises still return a structured failure."""
    service = BrevoEmailService(_settings(email_max_retries=1))
    monkeypatch.setattr(
        service,
        "_build_api",
        lambda: (_ for _ in ()).throw(BrevoTransientError("boom", status=status)),
    )
    result = await service.send_training_email("a@b.example", "A", "S", "<p>x</p>")
    assert result["success"] is False

# --------------------------------------------------------------------------- #
# Actionable diagnosis of Brevo rejections
# --------------------------------------------------------------------------- #
def test_ip_allowlist_rejection_names_the_blocked_address() -> None:
    """Brevo's IP message becomes an exact instruction with the address."""
    message = (
        '{"message":"We have detected you are using an unrecognised IP address '
        '80.253.185.154. If you performed this action make sure to add the new IP '
        'address in this link: https://app.brevo.com/security/authorised_ips",'
        '"code":"unauthorized"}'
    )
    described = _describe_failure(message)
    assert described["action_required"] == "ip_allowlist"
    assert described["blocked_ip"] == "80.253.185.154"
    assert described["action_url"] == AUTHORISED_IPS_URL
    assert "80.253.185.154" in described["hint"]


def test_ip_allowlist_rejection_supports_ipv6() -> None:
    """IPv6 addresses are extracted too."""
    described = _describe_failure("unrecognised IP address 2001:db8::1 detected")
    assert described["blocked_ip"] == "2001:db8::1"


def test_unauthorized_without_ip_is_a_credentials_problem() -> None:
    """A plain 401 points at the API key, not the allowlist."""
    described = _describe_failure("(401) Unauthorized - Key not found")
    assert described["action_required"] == "credentials"
    assert "blocked_ip" not in described


def test_unknown_failure_has_no_action() -> None:
    """Unrecognised errors return nothing rather than a guess."""
    assert _describe_failure("connection reset by peer") == {}


async def test_verify_configuration_attaches_the_ip_hint(monkeypatch) -> None:
    """The verify endpoint surfaces the blocked IP to the dashboard."""
    service = BrevoEmailService(_settings())

    def _boom():
        raise RuntimeError(
            "unrecognised IP address 203.0.113.9. Add it in "
            "https://app.brevo.com/security/authorised_ips"
        )

    monkeypatch.setattr(service, "_build_account_api", _boom)
    result = await service.verify_configuration()
    assert result["valid"] is False
    assert result["action_required"] == "ip_allowlist"
    assert result["blocked_ip"] == "203.0.113.9"


# --------------------------------------------------------------------------- #
# SMTP transport (mailbox delivery: envelope sender == From header)
# --------------------------------------------------------------------------- #
class _FakeSmtp:
    """Context-manager stand-in for ``smtplib.SMTP``."""

    def __init__(self, message: dict | None = None) -> None:
        self.sent: list = []
        self.message = message

    def __enter__(self):
        return self

    def __exit__(self, *args) -> None:
        return None

    def send_message(self, message):  # noqa: ANN001
        self.sent.append(message)

    def noop(self):
        return 250, b"OK"


def _smtp_settings(**overrides) -> Settings:
    """Settings that select the SMTP transport."""
    values = {
        "email_transport": "smtp",
        "smtp_host": "smtp.gmail.com",
        "smtp_port": 465,
        "smtp_username": "sender@example.com",
        "smtp_password": "app-password",
        "smtp_use_ssl": True,
    }
    values.update(overrides)
    return _settings(**values)


async def test_smtp_send_builds_a_valid_message(monkeypatch) -> None:
    """SMTP sends carry From/To/Subject/Message-ID and an HTML alternative."""
    service = BrevoEmailService(_smtp_settings())
    fake = _FakeSmtp()
    monkeypatch.setattr(service, "_open_smtp", lambda: fake)

    result = await service.send_training_email(
        "jane@acmetest.example", "Jane Doe", "Subject", "<p>Body</p>"
    )
    assert result["success"] is True
    assert result["message_id"]
    assert len(fake.sent) == 1
    message = fake.sent[0]
    assert message["To"] == "Jane Doe <jane@acmetest.example>"
    assert message["Subject"] == "Subject"
    assert message["Message-ID"]


async def test_smtp_send_requires_credentials() -> None:
    """Selecting SMTP without credentials fails with a clear error."""
    service = BrevoEmailService(
        _smtp_settings(smtp_host="", smtp_username="", smtp_password="")
    )
    result = await service.send_training_email("a@b.example", "A", "S", "<p>x</p>")
    assert result["success"] is False
    assert "not set" in (result["error"] or "").lower()


async def test_smtp_auth_failure_is_not_retried(monkeypatch) -> None:
    """A rejected app password fails fast and names the problem."""
    service = BrevoEmailService(_smtp_settings())

    def _reject():
        raise smtplib.SMTPAuthenticationError(535, b"bad credentials")

    monkeypatch.setattr(service, "_open_smtp", _reject)
    result = await service.send_training_email("a@b.example", "A", "S", "<p>x</p>")
    assert result["success"] is False
    assert "authentication" in (result["error"] or "").lower()


async def test_smtp_verify_configuration(monkeypatch) -> None:
    """The preflight logs into SMTP and reports the mailbox."""
    service = BrevoEmailService(_smtp_settings())
    fake = _FakeSmtp()
    monkeypatch.setattr(service, "_open_smtp", lambda: fake)

    report = await service.verify_configuration()
    assert report["valid"] is True
    assert report["detail"]["transport"] == "smtp"
    assert report["detail"]["host"] == "smtp.gmail.com"
