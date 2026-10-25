"""AI-assisted phishing-template generation.

The service talks to any OpenAI-compatible ``/chat/completions`` endpoint using
``httpx``.  It deliberately does not depend on the OpenAI or Groq SDKs, so a
deployment can switch providers by changing environment variables only.

Security properties:

* a missing key/base URL/model raises :class:`AIServiceNotConfigured` — it never
  falls back to a canned template;
* provider failures surface as :class:`AIProviderError`, never as a silent
  success;
* the generated HTML is sanitized before it is returned or persisted;
* the organization industry is supplied by the caller from the authenticated
  user's tenant, not by the request body.
"""
from __future__ import annotations

import json
import re
from typing import Any

import httpx
from pydantic import ValidationError

from app.config import Settings, get_settings
from app.logging_config import get_logger
from app.schemas.ai import AIGeneratedTemplate

logger = get_logger(__name__)

#: HTML fragments that must never reach an email template.
_SCRIPT_RE = re.compile(r"<script\b[^>]*>.*?</script\s*>", re.IGNORECASE | re.DOTALL)
_SCRIPT_SELF_CLOSING_RE = re.compile(r"<script\b[^>]*/\s*>", re.IGNORECASE | re.DOTALL)
_IFRAME_RE = re.compile(r"<iframe\b[^>]*>.*?</iframe\s*>", re.IGNORECASE | re.DOTALL)
_IFRAME_SELF_CLOSING_RE = re.compile(r"<iframe\b[^>]*/\s*>", re.IGNORECASE | re.DOTALL)
_OBJECT_RE = re.compile(r"<object\b[^>]*>.*?</object\s*>", re.IGNORECASE | re.DOTALL)
_EMBED_RE = re.compile(r"<embed\b[^>]*/?>", re.IGNORECASE | re.DOTALL)
#: ``onclick="..."``, ``onerror='...'`` and unquoted variants.
_EVENT_HANDLER_RE = re.compile(
    r"\s+on[a-z]+\s*=\s*(?:\"[^\"]*\"|'[^']*'|[^\s>]+)", re.IGNORECASE
)
#: ``href="javascript:..."`` and the same for ``src``.
_JAVASCRIPT_URL_RE = re.compile(
    r"(\b(?:href|src)\s*=\s*)([\"'])\s*javascript:[^\"']*\2", re.IGNORECASE
)
#: NUL and other control characters that break XML/PDF/email rendering.
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

_JSON_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)


class AIServiceError(RuntimeError):
    """Base class for AI-generation failures."""


class AIServiceNotConfigured(AIServiceError):
    """Raised when the provider credentials/settings are incomplete."""


class AIProviderError(AIServiceError):
    """Raised when the provider rejects a request or returns unusable data."""


def sanitize_generated_html(value: str) -> str:
    """Remove active content from generated HTML.

    Email templates need inline CSS, tables and links, so those are preserved.
    Scripts, iframes, plugins, inline event handlers and ``javascript:`` URLs are
    removed.  This is a defence-in-depth layer: the dashboard also renders the
    preview inside a sandboxed iframe.
    """
    if not isinstance(value, str):
        raise AIProviderError("generated body_html must be a string")
    cleaned = _CONTROL_RE.sub("", value)
    cleaned = _SCRIPT_RE.sub("", cleaned)
    cleaned = _SCRIPT_SELF_CLOSING_RE.sub("", cleaned)
    cleaned = _IFRAME_RE.sub("", cleaned)
    cleaned = _IFRAME_SELF_CLOSING_RE.sub("", cleaned)
    cleaned = _OBJECT_RE.sub("", cleaned)
    cleaned = _EMBED_RE.sub("", cleaned)
    cleaned = _EVENT_HANDLER_RE.sub("", cleaned)
    cleaned = _JAVASCRIPT_URL_RE.sub(lambda match: f'{match.group(1)}"#"', cleaned)
    return cleaned.strip()


def sanitize_subject(value: str) -> str:
    """Trim a generated subject and collapse line breaks."""
    if not isinstance(value, str):
        raise AIProviderError("generated subject must be a string")
    cleaned = _CONTROL_RE.sub("", value).replace("\r", " ").replace("\n", " ")
    return re.sub(r"\s+", " ", cleaned).strip()


def _extract_json(content: str) -> dict[str, Any]:
    """Parse a JSON object from a model response, tolerating Markdown fences."""
    if not isinstance(content, str) or not content.strip():
        raise AIProviderError("LLM returned an empty response")
    text = _JSON_FENCE_RE.sub("", content.strip()).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise AIProviderError("LLM response did not contain a JSON object")
    candidate = text[start : end + 1]
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise AIProviderError(f"LLM returned invalid JSON: {exc.msg}") from exc
    if not isinstance(parsed, dict):
        raise AIProviderError("LLM JSON response must be an object")
    return parsed


def _coerce_difficulty(value: Any) -> int:
    """Coerce a model-provided difficulty into the 1..10 integer contract."""
    if isinstance(value, bool):
        return 5
    if isinstance(value, (int, float)):
        return max(1, min(10, int(round(value))))
    if isinstance(value, str):
        match = re.search(r"\d+", value)
        if match:
            return max(1, min(10, int(match.group())))
    return 5


def _ensure_tracking_link(body_html: str) -> str:
    """Ensure an AI email has a clickable tracked CTA.

    If the model returned no anchor at all, a minimal CTA is appended.  This is
    a structural requirement of the simulation, not generated content: without
    a link the campaign would have no click event and no training path.
    """
    if re.search(r"<a\b", body_html, re.IGNORECASE):
        return body_html
    return (
        body_html
        + '\n<p style="margin:24px 0 0;font-family:Arial,sans-serif;">'
        '<a href="{{tracking_url}}" style="display:inline-block;padding:12px 22px;'
        'background:#0b5fff;color:#ffffff;text-decoration:none;border-radius:6px;'
        'font-weight:700;">Review now</a></p>'
    )


class AIService:
    """Generate one validated template through an OpenAI-compatible provider."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._client = client

    async def generate_template(
        self,
        *,
        organization_industry: str | None,
        target_department: str,
        scenario: str,
        channel: str = "email",
    ) -> AIGeneratedTemplate:
        """Generate, sanitize and validate one template.

        Args:
            organization_industry: Industry loaded from the authenticated
                user's organization.
            target_department: Department the simulation should target.
            scenario: Administrator's description of the desired pretext.
            channel: ``email``, ``sms`` or ``whatsapp``.

        Raises:
            AIServiceNotConfigured: When the provider settings are incomplete.
            AIProviderError: When the provider fails or returns unusable data.
        """
        if not self.settings.llm_configured:
            missing = ", ".join(self.settings.llm_missing_settings())
            raise AIServiceNotConfigured(
                "AI template generation is not configured. Set "
                f"{missing} in the backend environment."
            )

        industry = (organization_industry or "general business").strip()
        prompt = self._build_prompt(
            industry=industry,
            department=target_department.strip(),
            scenario=scenario.strip(),
            channel=channel,
        )
        payload = {
            "model": self.settings.llm_model_resolved,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a senior security-awareness simulation author. "
                        "You write realistic but safe phishing-simulation templates "
                        "for authorized employee training. Return only valid JSON."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.7,
            "max_tokens": self.settings.llm_max_tokens,
        }
        url = f"{self.settings.llm_base_url_resolved.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.settings.llm_api_key.strip()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        try:
            if self._client is not None:
                response = await self._client.post(url, json=payload, headers=headers)
            else:
                async with httpx.AsyncClient(
                    timeout=self.settings.llm_timeout_seconds
                ) as client:
                    response = await client.post(url, json=payload, headers=headers)
        except httpx.TimeoutException as exc:
            raise AIProviderError("LLM provider timed out") from exc
        except httpx.HTTPError as exc:
            raise AIProviderError(f"LLM provider request failed: {exc}") from exc

        if response.status_code >= 400:
            detail = (response.text or "").strip()[:400]
            logger.warning(
                "ai_provider_http_error",
                provider=self.settings.llm_provider_slug,
                status_code=response.status_code,
                detail=detail,
            )
            raise AIProviderError(
                f"LLM provider returned HTTP {response.status_code}"
                + (f": {detail}" if detail else "")
            )

        try:
            data = response.json()
        except ValueError as exc:
            raise AIProviderError("LLM provider returned a non-JSON response") from exc

        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise AIProviderError("LLM response is missing choices[0].message.content") from exc

        parsed = _extract_json(content)
        subject = sanitize_subject(parsed.get("subject", ""))
        body_html = sanitize_generated_html(parsed.get("body_html", ""))
        if not subject:
            raise AIProviderError("LLM response did not include a subject")
        if not body_html:
            raise AIProviderError("LLM response did not include body_html")
        body_html = _ensure_tracking_link(body_html)

        try:
            generated = AIGeneratedTemplate(
                subject=subject,
                body_html=body_html,
                difficulty_level=_coerce_difficulty(parsed.get("difficulty_level")),
                provider=self.settings.llm_provider_slug,
                model=str(data.get("model") or self.settings.llm_model_resolved)[:120],
            )
        except ValidationError as exc:
            raise AIProviderError(f"LLM response failed validation: {exc.errors()[0]['msg']}") from exc

        logger.info(
            "ai_template_generated",
            provider=generated.provider,
            model=generated.model,
            difficulty=generated.difficulty_level,
            channel=channel,
            industry=industry,
            department=target_department,
        )
        return generated

    @staticmethod
    def _build_prompt(*, industry: str, department: str, scenario: str, channel: str) -> str:
        """Build the provider prompt without embedding any secret."""
        return f"""Create one authorized security-awareness simulation template.

Organization industry: {industry}
Target department: {department}
Requested scenario: {scenario}
Delivery channel: {channel}

Return ONLY a JSON object with exactly these keys:
- "subject": a concise subject line (for SMS/WhatsApp, a short message title)
- "body_html": a complete, email-safe HTML fragment using inline CSS and a
  professional visual hierarchy. Use Arabic when the scenario is Arabic;
  otherwise use the scenario's language. Make it look like a plausible internal
  message for the stated industry and department.
- "difficulty_level": an integer from 1 to 10 (1-3 easy, 4-7 medium, 8-10 hard).
  Choose a level consistent with the subtlety of the pretext.

Requirements:
- Use these placeholders exactly where appropriate: {{{{first_name}}}},
  {{{{company_name}}}}, {{{{department}}}}, {{{{tracking_url}}}}.
- Include at least one visible call-to-action anchor whose href is exactly
  {{{{tracking_url}}}}.
- Do not include <script>, <iframe>, <object>, <embed>, forms, real credentials,
  external tracking pixels, or images hosted on unknown domains.
- Do not mention that this is a simulation inside the email body.
- Keep the subject under 120 characters and the HTML under 12,000 characters.
"""
