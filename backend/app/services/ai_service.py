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

import html
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

#: Channels whose message is a single short segment rather than an email.
SHORT_CHANNELS = frozenset({"sms", "whatsapp"})
#: Maximum delivered length of an SMS/WhatsApp template (including the link).
SHORT_MESSAGE_MAX_LENGTH = 170
#: Stand-in used to size ``{{link}}`` before a short code exists.
SAMPLE_SHORT_LINK = "https://hument.link/s/AbCdEf"
#: Any absolute URL a model invents is replaced by the tracked placeholder.
_URL_RE = re.compile(r"https?://[^\s<>\"']+")

_JSON_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)
#: Some reasoning models wrap their answer in ``<think>...</think>``.  The
#: reasoning is not part of the template and must never reach the parser.
_THINK_RE = re.compile(r"<think\b[^>]*>.*?</think\s*>", re.IGNORECASE | re.DOTALL)

#: Fixed, safe RTL shell for models that return plain text instead of HTML.
#: The body is escaped before insertion, so generated text cannot inject markup.
_EMAIL_WRAPPER = """<div dir="rtl" style="margin:0;padding:0;background:#f3f6fb;font-family:'Segoe UI',Tahoma,Arial,sans-serif;color:#1f2937;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f3f6fb;padding:28px 12px;">
    <tr>
      <td align="center">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:600px;background:#ffffff;border:1px solid #e5e7eb;border-radius:12px;overflow:hidden;">
          <tr>
            <td style="background:#0b5fff;padding:20px 28px;color:#ffffff;font-size:18px;font-weight:700;">{{company_name}}</td>
          </tr>
          <tr>
            <td style="padding:28px;font-size:16px;line-height:1.9;">
              __BODY__
              <p style="margin:28px 0 0;text-align:center;">
                <a href="{{tracking_url}}" style="display:inline-block;background:#0b5fff;color:#ffffff;text-decoration:none;padding:13px 30px;border-radius:8px;font-weight:700;">متابعة الإجراء</a>
              </p>
              <p style="margin:24px 0 0;font-size:12px;color:#6b7280;line-height:1.7;">رسالة داخلية من {{department}} — {{company_name}}</p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</div>"""


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


def sanitize_generated_text(value: str) -> str:
    """Turn model-generated text into escaped plain text.

    The model is asked for plain text, but a provider may still return markup.
    Tags are removed first, then the remaining text is HTML-escaped.  This is
    deliberately stricter than :func:`sanitize_generated_html`: plain text is
    the only thing inserted into the fixed email shell.
    """
    if not isinstance(value, str):
        raise AIProviderError("generated body_text must be a string")
    cleaned = _CONTROL_RE.sub("", value)
    cleaned = re.sub(r"<[^>]*>", "", cleaned)
    cleaned = html.escape(cleaned, quote=False)
    cleaned = re.sub(r"[ \t]+\n", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def short_message_length(body: str) -> int:
    """Return the delivered character count of an SMS body.

    ``{{link}}`` is counted as the short URL that replaces it, matching the
    campaign launcher and the template editor.
    """
    return len((body or "").replace("{{link}}", SAMPLE_SHORT_LINK).strip())


def _render_short_body(body_text: str) -> str:
    """Normalise a model-written SMS body into a safe stored template body.

    Any absolute URL is replaced by ``{{link}}`` (the launcher swaps it for the
    per-recipient short link), a missing placeholder is appended, and the text
    is escaped and wrapped in a single paragraph so the template editor shows
    plain text.
    """
    text = _URL_RE.sub("{{link}}", body_text or "").strip()
    if not text:
        raise AIProviderError("LLM response did not include a usable message body")
    if "{{link}}" not in text:
        text = f"{text} {{{{link}}}}".strip()
    return f"<p>{text}</p>"


def _describe_http_error(status_code: int, detail: str) -> str:
    """Return an actionable message for a provider HTTP failure."""
    suffix = f" {detail}" if detail else ""
    if status_code in (401, 403):
        return (
            f"LLM provider rejected the API key (HTTP {status_code}).{suffix} "
            "Update LLM_API_KEY in the backend environment."
        )
    if status_code == 402:
        return (
            f"LLM provider quota is exhausted (HTTP 402).{suffix} "
            "Top up the provider account or point LLM_BASE_URL/LLM_API_KEY at "
            "a funded OpenAI-compatible endpoint."
        )
    if status_code == 404:
        return (
            f"LLM endpoint or model not found (HTTP 404).{suffix} "
            "Check LLM_BASE_URL and LLM_MODEL."
        )
    if status_code == 429:
        return (
            f"LLM provider rate limit reached (HTTP 429).{suffix} "
            "Retry in a moment or use the fallback model."
        )
    if status_code >= 500:
        return f"LLM provider is unavailable (HTTP {status_code}).{suffix}"
    return f"LLM provider returned HTTP {status_code}.{suffix}"


def _describe_transport_error(exc: Exception) -> str:
    """Return an actionable message for a network-level provider failure."""
    raw = str(exc)
    lowered = raw.lower()
    if "getaddrinfo" in lowered or "name or service not known" in lowered or "nodename" in lowered:
        return (
            f"LLM endpoint host does not resolve ({raw}). LLM_BASE_URL points at "
            "an unreachable host — temporary tunnels expire, so use the "
            "provider's permanent base URL such as "
            "https://inference.dahl.global/v1."
        )
    if "timed out" in lowered:
        return f"LLM provider request timed out ({raw})."
    if "refused" in lowered:
        return (
            f"LLM endpoint refused the connection ({raw}). Check that LLM_BASE_URL "
            "is reachable from this machine."
        )
    return f"LLM provider request failed: {raw}"


def _render_body_html(body_text: str) -> str:
    """Wrap escaped, model-generated text in the fixed RTL email shell."""
    paragraphs = [
        part.strip()
        for part in re.split(r"\n\s*\n|\n", body_text)
        if part.strip()
    ]
    if not paragraphs:
        raise AIProviderError("LLM response did not include body_text")
    body = "".join(
        f'<p style="margin:0 0 14px;">{paragraph}</p>' for paragraph in paragraphs
    )
    return _EMAIL_WRAPPER.replace("__BODY__", body)


def _extract_json(content: str) -> dict[str, Any]:
    """Parse a JSON object from a model response, tolerating Markdown fences."""
    if not isinstance(content, str) or not content.strip():
        raise AIProviderError("LLM returned an empty response")
    text = _THINK_RE.sub("", content).strip()
    text = _JSON_FENCE_RE.sub("", text).strip()
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
        models = [self.settings.llm_model_resolved]
        for fallback in self.settings.llm_fallback_model_list:
            if fallback not in models:
                models.append(fallback)

        payload = {
            "model": models[0],
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a senior security-awareness simulation author. "
                        "You write realistic but safe phishing-simulation templates "
                        "for authorized employee training. Return only valid JSON. "
                        "Do not include reasoning or explanations."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.3,
            "max_tokens": self.settings.llm_max_tokens,
            "response_format": {"type": "json_object"},
        }
        url = f"{self.settings.llm_base_url_resolved.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.settings.llm_api_key.strip()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        last_error: AIProviderError | None = None
        for index, model in enumerate(models):
            payload["model"] = model
            timeout_seconds = (
                self.settings.llm_primary_timeout_seconds
                if index == 0
                else self.settings.llm_timeout_seconds
            )
            try:
                return await self._generate_once(
                    model=model,
                    payload=payload,
                    url=url,
                    headers=headers,
                    timeout_seconds=timeout_seconds,
                    channel=channel,
                    industry=industry,
                    department=target_department,
                )
            except AIProviderError as exc:
                last_error = exc
                if index + 1 < len(models):
                    logger.warning(
                        "ai_model_fallback",
                        failed_model=model,
                        next_model=models[index + 1],
                        error=str(exc)[:300],
                    )
                    continue
                raise

        raise last_error or AIProviderError("AI generation failed")

    async def _generate_once(
        self,
        *,
        model: str,
        payload: dict[str, Any],
        url: str,
        headers: dict[str, str],
        timeout_seconds: float,
        channel: str,
        industry: str,
        department: str,
    ) -> AIGeneratedTemplate:
        """Call one model and turn its response into a validated template."""
        try:
            if self._client is not None:
                response = await self._client.post(
                    url,
                    json=payload,
                    headers=headers,
                    timeout=timeout_seconds,
                )
            else:
                async with httpx.AsyncClient(timeout=timeout_seconds) as client:
                    response = await client.post(url, json=payload, headers=headers)
        except httpx.TimeoutException as exc:
            raise AIProviderError(
                f"LLM provider timed out after {timeout_seconds:g}s"
            ) from exc
        except httpx.HTTPError as exc:
            raise AIProviderError(_describe_transport_error(exc)) from exc

        if response.status_code >= 400:
            detail = (response.text or "").strip()[:400]
            logger.warning(
                "ai_provider_http_error",
                provider=self.settings.llm_provider_slug,
                model=model,
                status_code=response.status_code,
                detail=detail,
            )
            raise AIProviderError(_describe_http_error(response.status_code, detail))

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
        if not subject:
            raise AIProviderError("LLM response did not include a subject")

        short_channel = channel.strip().lower() in SHORT_CHANNELS
        body_html_value = parsed.get("body_html")
        body_text_value = parsed.get("body_text")
        if short_channel:
            # SMS/WhatsApp: one short segment, no email shell.  A model that
            # ignores the instructions and returns HTML is stripped to text.
            candidate = body_text_value if isinstance(body_text_value, str) else ""
            if not candidate.strip() and isinstance(body_html_value, str):
                candidate = re.sub(r"<[^>]*>", " ", body_html_value)
            plain = sanitize_generated_text(html.unescape(candidate))
            body_html = _render_short_body(plain)
            length = short_message_length(plain)
            if length > SHORT_MESSAGE_MAX_LENGTH:
                raise AIProviderError(
                    f"generated {channel.upper()} body is {length} characters; "
                    f"the limit is {SHORT_MESSAGE_MAX_LENGTH} including "
                    "{{link}}. Shorten the scenario and generate again"
                )
        elif isinstance(body_html_value, str) and body_html_value.strip():
            body_html = sanitize_generated_html(body_html_value)
            if not body_html:
                raise AIProviderError("LLM response did not include usable body_html")
            body_html = _ensure_tracking_link(body_html)
        elif isinstance(body_text_value, str) and body_text_value.strip():
            body_text = sanitize_generated_text(body_text_value)
            if not body_text:
                raise AIProviderError("LLM response did not include usable body_text")
            body_html = sanitize_generated_html(_render_body_html(body_text))
        else:
            raise AIProviderError(
                "LLM response did not include body_html or body_text"
            )

        try:
            generated = AIGeneratedTemplate(
                subject=subject,
                body_html=body_html,
                difficulty_level=_coerce_difficulty(parsed.get("difficulty_level")),
                provider=self.settings.llm_provider_slug,
                model=str(data.get("model") or model)[:120],
            )
        except ValidationError as exc:
            raise AIProviderError(
                f"LLM response failed validation: {exc.errors()[0]['msg']}"
            ) from exc

        logger.info(
            "ai_template_generated",
            provider=generated.provider,
            model=generated.model,
            difficulty=generated.difficulty_level,
            channel=channel,
            industry=industry,
            department=department,
        )
        return generated

    @staticmethod
    def _build_prompt(*, industry: str, department: str, scenario: str, channel: str) -> str:
        """Build a compact prompt that asks for text, not HTML.

        The backend owns the HTML shell so a model cannot introduce active
        content and so the response stays small enough for the provider and the
        Cloudflare tunnel's request window.  SMS/WhatsApp get a shorter,
        segment-sized variant with ``{{link}}`` as the only URL.
        """
        if channel.strip().lower() in SHORT_CHANNELS:
            return f"""Create one authorized security-awareness simulation message.

Industry: {industry}
Target department: {department}
Scenario: {scenario}
Channel: {channel} (single SMS segment)

Return only a JSON object with exactly these keys:
- "subject": an internal label under 60 characters (never shown to the recipient).
- "body_text": ONE or TWO short sentences, at most 130 characters INCLUDING the
  literal placeholder {{{{link}}}}, in the scenario's language (Arabic when the
  scenario is Arabic). End with a clear instruction to open the link. Write
  {{{{link}}}} exactly once and do not write any other URL. Do not include HTML
  and never mention that this is a simulation.
- "difficulty_level": an integer from 1 to 10 (1-3 easy, 4-7 medium, 8-10 hard).

Do not explain, reason, or use markdown. Output JSON only.
"""
        return f"""Create one authorized security-awareness simulation template.

Industry: {industry}
Target department: {department}
Scenario: {scenario}
Channel: {channel}

Return only a JSON object with exactly these keys:
- "subject": a concise subject line under 120 characters.
- "body_text": 3 to 5 short sentences of plain text in the scenario's language
  (Arabic when the scenario is Arabic). Use {{{{first_name}}}},
  {{{{company_name}}}}, and {{{{department}}}} where appropriate. End with a
  clear instruction to click the verification link. Do not include HTML, URLs,
  or mention that this is a simulation.
- "difficulty_level": an integer from 1 to 10 (1-3 easy, 4-7 medium, 8-10 hard).
  Choose a level consistent with the subtlety of the pretext.

Do not explain, reason, or use markdown. Output JSON only.
"""
