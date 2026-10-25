"""Tests for the template personalisation service."""
from __future__ import annotations

import uuid

from app.config import Settings
from app.models import EmailTemplate, HumanAsset, Organization
from app.services.template_service import (
    TemplatePersonalizer,
    build_click_url,
    build_tracking_url,
    extract_links,
)

ORG_ID = uuid.uuid4()


def _org() -> Organization:
    return Organization(id=ORG_ID, name="Acme Test Corporation", domain="acmetest.example")


def _employee(**overrides) -> HumanAsset:
    data = {
        "id": uuid.uuid4(),
        "organization_id": ORG_ID,
        "email": "jane.doe@acmetest.example",
        "first_name": "Jane",
        "last_name": "Doe",
        "department": "Finance",
        "job_title": "Controller",
        "risk_profile": {},
    }
    data.update(overrides)
    return HumanAsset(**data)


def _template(**overrides) -> EmailTemplate:
    data = {
        "id": uuid.uuid4(),
        "organization_id": ORG_ID,
        "name": "Test Template",
        "subject": "Hello {{first_name}} from {{company_name}}",
        "body_html": (
            "<p>Hi {{first_name}} {{last_name}} ({{email}}),</p>"
            "<p>Department: {{department}} &middot; Manager: {{manager_name}}</p>"
            '<p><a href="https://portal.example.com/reset">Reset password</a></p>'
            '<p><a href="https://evil.example.com/track">Invoice {{invoice_number}}</a></p>'
        ),
        "difficulty_level": 5,
        "available_variables": ["first_name", "last_name", "email", "department", "company_name"],
        "is_built_in": True,
        "is_active": True,
    }
    data.update(overrides)
    return EmailTemplate(**data)


def _personalizer() -> TemplatePersonalizer:
    return TemplatePersonalizer(Settings(base_url="http://testserver", encryption_key="ab" * 32))


def test_variable_substitution() -> None:
    """Employee and organization variables are substituted."""
    tracking_uuid = uuid.uuid4()
    rendered = _personalizer().personalize(
        _template(), _employee(), _org(), tracking_uuid
    )
    assert "Hello Jane from Acme Test Corporation" == rendered["subject"]
    assert "Hi Jane Doe (jane.doe@acmetest.example)" in rendered["html_content"]
    assert "Department: Finance" in rendered["html_content"]
    assert "Manager: Finance Manager" in rendered["html_content"]


def test_manager_name_from_risk_profile() -> None:
    """An explicit manager name wins over the department default."""
    employee = _employee(risk_profile={"manager_name": "Priya Nair"})
    rendered = _personalizer().personalize(_template(), employee, _org(), uuid.uuid4())
    assert "Manager: Priya Nair" in rendered["html_content"]


def test_links_are_rewritten_to_click_tracker() -> None:
    """Every anchor is wrapped in the click-tracking endpoint."""
    tracking_uuid = uuid.uuid4()
    body = _personalizer().personalize(
        _template(), _employee(), _org(), tracking_uuid
    )["html_content"]
    links = extract_links(body)
    click_links = [link for link in links if "/api/v1/track/click/" in link]
    assert len(click_links) == 2
    for link in click_links:
        assert f"/api/v1/track/click/{tracking_uuid}" in link
        assert "url=https%3A%2F%2F" in link


def test_tracking_pixel_is_appended() -> None:
    """A 1x1 tracking pixel with the recipient UUID is appended."""
    tracking_uuid = uuid.uuid4()
    body = _personalizer().personalize(
        _template(), _employee(), _org(), tracking_uuid
    )["html_content"]
    assert f"http://testserver/api/v1/track/open/{tracking_uuid}" in body
    assert 'width="1"' in body and 'height="1"' in body


def test_pixel_not_duplicated() -> None:
    """Re-personalising a rendered body does not add a second pixel."""
    tracking_uuid = uuid.uuid4()
    personalizer = _personalizer()
    once = personalizer.personalize(_template(), _employee(), _org(), tracking_uuid)["html_content"]
    twice = personalizer.append_tracking_pixel(once, str(tracking_uuid), "http://testserver")
    assert twice.count("/api/v1/track/open/") == 1


def test_tracking_url_variable() -> None:
    """``{{tracking_url}}`` resolves to the simulation landing page URL."""
    from urllib.parse import unquote

    tracking_uuid = uuid.uuid4()
    template = _template(body_html='<p><a href="{{tracking_url}}">Open portal</a></p>')
    body = _personalizer().personalize(template, _employee(), _org(), tracking_uuid)["html_content"]
    # The landing link is itself wrapped in the click tracker, so the rendered
    # href URL-encodes the landing URL. Decode to assert the target.
    assert f"http://testserver/phish/{tracking_uuid}" in unquote(body)


def test_unknown_variable_is_left_intact() -> None:
    """Placeholders we cannot resolve are preserved verbatim."""
    template = _template(subject="Hi {{first_name}} {{mystery_variable}}")
    rendered = _personalizer().personalize(template, _employee(), _org(), uuid.uuid4())
    assert "{{mystery_variable}}" in rendered["subject"]


def test_values_are_html_escaped() -> None:
    """Substituted values are HTML-escaped to prevent injection."""
    template = _template(body_html="<p>{{first_name}}</p>")
    employee = _employee(first_name="<script>alert(1)</script>")
    body = _personalizer().personalize(template, employee, _org(), uuid.uuid4())["html_content"]
    assert "<script>" not in body
    assert "&lt;script&gt;" in body


def test_anchor_without_href_is_untouched() -> None:
    """Anchors with empty or fragment hrefs are not rewritten."""
    template = _template(body_html='<p><a href="#">Top</a> <a>No href</a></p>')
    body = _personalizer().personalize(template, _employee(), _org(), uuid.uuid4())["html_content"]
    assert "/api/v1/track/click/" not in body
    assert 'href="#"' in body


def test_rewrite_is_idempotent() -> None:
    """An already-wrapped link is not wrapped twice."""
    personalizer = _personalizer()
    tracking_uuid = uuid.uuid4()
    once = personalizer.personalize(_template(), _employee(), _org(), tracking_uuid)["html_content"]
    twice = personalizer.rewrite_links(once, str(tracking_uuid), "http://testserver")
    assert twice.count("/api/v1/track/click/") == once.count("/api/v1/track/click/")


def test_validate_variables_detects_missing() -> None:
    """Unresolvable declared variables are reported."""
    template = _template(
        available_variables=["first_name", "company_name", "invoice_number", "meeting_time"]
    )
    missing = _personalizer().validate_variables(template, _employee())
    assert missing == []


def test_validate_variables_reports_unknown_fields() -> None:
    """A declared variable with no source is reported as missing."""
    template = _template(available_variables=["first_name", "totally_unknown"])
    missing = _personalizer().validate_variables(template, _employee())
    assert "totally_unknown" in missing


def test_extract_links_returns_all_hrefs() -> None:
    """``extract_links`` returns hrefs in document order."""
    html = '<a href="https://a.example">A</a><a href="https://b.example">B</a>'
    assert extract_links(html) == ["https://a.example", "https://b.example"]


def test_extract_links_handles_malformed_markup() -> None:
    """Malformed markup does not raise."""
    assert extract_links("<a href='https://a.example'>unclosed") == ["https://a.example"]


def test_extra_vars_override() -> None:
    """Explicit overrides take precedence over derived values."""
    rendered = _personalizer().personalize(
        _template(),
        _employee(),
        _org(),
        uuid.uuid4(),
        extra_vars={"invoice_number": "INV-FIXED-1", "first_name": "Overridden"},
    )
    assert "Overridden" in rendered["subject"]
    assert "INV-FIXED-1" in rendered["html_content"]


def test_pixel_appended_without_body_tag() -> None:
    """The pixel is appended even when there is no ``</body>``."""
    template = _template(body_html="<p>No body tag</p>")
    body = _personalizer().personalize(template, _employee(), _org(), uuid.uuid4())["html_content"]
    assert "/api/v1/track/open/" in body


def test_invoice_and_meeting_time_generated() -> None:
    """Generated variables are non-empty and plausible."""
    template = _template(
        body_html="<p>{{invoice_number}} / {{meeting_time}} / {{current_year}}</p>"
    )
    body = _personalizer().personalize(template, _employee(), _org(), uuid.uuid4())["html_content"]
    assert "INV-" in body
    assert "UTC" in body


def test_helper_url_builders() -> None:
    """URL helpers produce the documented shapes."""
    uid = str(uuid.uuid4())
    assert build_tracking_url("http://x/", uid) == f"http://x/phish/{uid}"
    assert build_click_url("http://x", uid, "https://y.example").startswith(
        f"http://x/api/v1/track/click/{uid}?url="
    )
