"""Rendering, branding and sanitisation tests for the visual email editor."""
from __future__ import annotations

from types import SimpleNamespace

from app.schemas.email_design import EmailDesign, TextBlock
from app.services.email_design import (
    BrandingContext,
    apply_branding_placeholders,
    compile_design_html,
    default_design,
    design_for_template,
    legacy_design_payload,
    render_email_design,
)
from app.services.html_sanitizer import sanitize_email_html


def _branding() -> BrandingContext:
    return BrandingContext(
        company_name="شركة الاختبار",
        primary_color="#123456",
        support_email="support@example.test",
        logo_url="https://cdn.example.test/logo.png",
    )


def test_default_design_renders_rtl_branding_and_merge_tags() -> None:
    """The starter design is Arabic-first and uses live branding."""
    html = render_email_design(default_design(_branding()), _branding())

    assert 'dir="rtl"' in html
    assert "شركة الاختبار" in html
    assert "https://cdn.example.test/logo.png" in html
    assert "#123456" in html
    assert "{{first_name}}" in html
    assert "{{tracking_url}}" in html
    assert "<script" not in html.lower()


def test_legacy_design_keeps_original_document_and_injects_branding() -> None:
    """Legacy HTML remains intact while placeholders are resolved."""
    legacy = (
        "<!doctype html><html><body>"
        "<div>[LOGO]</div><h1>[COMPANY_NAME]</h1>"
        '<p><a href="https://portal.example.test">Open</a></p>'
        "</body></html>"
    )
    design = EmailDesign(mode="legacy", legacy_html=legacy)
    html = render_email_design(design, _branding())

    assert "شركة الاختبار" in html
    assert "cdn.example.test/logo.png" in html
    assert "https://portal.example.test" in html
    assert "[LOGO]" not in html
    assert "[COMPANY_NAME]" not in html


def test_sanitizer_removes_active_content_and_keeps_email_layout() -> None:
    """Scripts, event handlers and javascript: URLs are removed."""
    raw = (
        '<html><body><table><tr><td style="background:#fff;">'
        '<p onclick="alert(1)">Hello <strong>world</strong></p>'
        '<script>alert(1)</script>'
        '<a href="javascript:alert(2)">bad</a>'
        '<img src="https://cdn.example.test/a.png" onerror="alert(3)">'
        "</td></tr></table></body></html>"
    )
    safe = sanitize_email_html(raw)

    assert "<script" not in safe.lower()
    assert "onclick" not in safe.lower()
    assert "onerror" not in safe.lower()
    assert "javascript:" not in safe.lower()
    assert "<strong>world</strong>" in safe
    assert "cdn.example.test/a.png" in safe


def test_sanitizer_blocks_data_urls_except_images() -> None:
    """Data URLs are only allowed for image sources."""
    safe = sanitize_email_html(
        '<p><a href="data:text/html;base64,PHNjcmlwdD4=">x</a>'
        '<img src="data:image/png;base64,iVBORw0KGgo=" /></p>'
    )
    assert "data:text/html" not in safe
    assert "data:image/png" in safe


def test_design_for_template_wraps_legacy_html() -> None:
    """A template without design JSON opens as an editable legacy document."""
    template = SimpleNamespace(body_html="<p>Legacy {{first_name}}</p>", design_json=None)
    design = design_for_template(template, primary_color="#0F6CBD")

    assert design.mode == "legacy"
    assert design.legacy_html == template.body_html
    assert design.settings.link_color == "#0F6CBD"


def test_legacy_payload_is_json_safe() -> None:
    """The wrapper round-trips through the API/DB JSON representation."""
    payload = legacy_design_payload("<p>Hello</p>")
    restored = EmailDesign.model_validate(payload)
    assert restored.mode == "legacy"
    assert restored.legacy_html == "<p>Hello</p>"


def test_compile_design_html_sanitizes_user_content() -> None:
    """Design content is sanitised before it is stored as compiled HTML."""
    design = EmailDesign(
        blocks=[
            TextBlock(
                id="block-1",
                content='<p onclick="x">Hello</p><script>alert(1)</script>',
            )
        ]
    )
    html = compile_design_html(design, _branding())
    assert "<script" not in html.lower()
    assert "onclick" not in html.lower()
    assert "Hello" in html


def test_branding_placeholders_are_escaped() -> None:
    """Company names cannot break out of the placeholder replacement."""
    html = apply_branding_placeholders(
        "<p>[COMPANY_NAME]</p>", BrandingContext(company_name="<Acme & Co>")
    )
    assert "&lt;Acme &amp; Co&gt;" in html
    assert "<Acme" not in html
