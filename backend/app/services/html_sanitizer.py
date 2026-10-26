"""Email-safe HTML sanitisation.

The visual editor is a trusted admin surface, but the generated markup is still
untrusted data: it can be edited through the API, imported from an old template,
or produced by an AI model.  This module implements a conservative allow-list
sanitiser tailored to email markup.

It deliberately keeps the table/layout tags used by real HTML email while
removing active content (``script``, event handlers, dangerous URL schemes,
CSS expressions).  The result is safe to store and to render inside the
sandboxed preview iframe.
"""
from __future__ import annotations

import html
import re
from html.parser import HTMLParser

#: Tags whose entire content is discarded.
DROP_CONTENT_TAGS = {
    "applet",
    "base",
    "embed",
    "form",
    "frame",
    "frameset",
    "iframe",
    "input",
    "link",
    "object",
    "option",
    "script",
    "select",
    "textarea",
    "template",
}

#: Tags that may appear in the sanitised output.
ALLOWED_TAGS = {
    "a",
    "abbr",
    "b",
    "blockquote",
    "body",
    "br",
    "caption",
    "center",
    "col",
    "colgroup",
    "dd",
    "div",
    "dl",
    "dt",
    "em",
    "font",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "head",
    "hr",
    "html",
    "i",
    "img",
    "li",
    "meta",
    "ol",
    "p",
    "small",
    "span",
    "strike",
    "strong",
    "style",
    "sub",
    "sup",
    "table",
    "tbody",
    "td",
    "tfoot",
    "th",
    "thead",
    "title",
    "tr",
    "u",
    "ul",
}

VOID_TAGS = {
    "br",
    "col",
    "hr",
    "img",
    "meta",
}

GLOBAL_ATTRS = {
    "align",
    "background",
    "bgcolor",
    "border",
    "cellpadding",
    "cellspacing",
    "class",
    "color",
    "dir",
    "face",
    "height",
    "id",
    "lang",
    "role",
    "size",
    "style",
    "title",
    "valign",
    "width",
}

TAG_ATTRS = {
    "a": {"href", "name", "rel", "target"},
    "font": {"color", "face", "size"},
    "html": {"dir", "lang", "xmlns"},
    "img": {"alt", "border", "height", "src", "width"},
    "meta": {"charset", "content", "name"},
    "style": {"media", "type"},
    "table": {"bgcolor", "border", "cellpadding", "cellspacing", "role", "width"},
    "td": {"bgcolor", "colspan", "height", "nowrap", "rowspan", "valign", "width"},
    "th": {"bgcolor", "colspan", "height", "nowrap", "rowspan", "valign", "width"},
    "tr": {"bgcolor", "height", "valign"},
}

URL_ATTRS = {"background", "href", "src"}
SCHEME_RE = re.compile(r"^[a-z][a-z0-9+.-]*:", re.IGNORECASE)
DANGEROUS_CSS_RE = re.compile(
    r"(expression\s*\(|behavior\s*:|-moz-binding|javascript\s*:|vbscript\s*:)",
    re.IGNORECASE,
)


def _is_safe_url(value: str, *, allow_data_image: bool = False) -> bool:
    """Return ``True`` when a URL attribute is safe for email.

    Args:
        value: Raw attribute value.
        allow_data_image: Permit inline ``data:image/*`` sources (used by old
            templates; new uploads are served from the application).

    Returns:
        ``True`` when the URL uses a permitted scheme or is relative.
    """
    raw = html.unescape(value or "").strip()
    if not raw:
        return True
    if raw.startswith(("{{", "[")):
        # Merge tags and branding placeholders are resolved after sanitisation.
        return True
    compact = re.sub(r"[\x00-\x20]+", "", raw).lower()
    if compact.startswith("#") or compact.startswith(("/", "./", "../", "?")):
        return True
    if compact.startswith(("http://", "https://", "mailto:", "tel:", "cid:")):
        return True
    if allow_data_image:
        return bool(re.match(r"^data:image/(?:png|jpe?g|gif|webp);base64,", compact))
    if not SCHEME_RE.match(compact):
        # A relative path or a bare domain; both are inert.
        return True
    return False


def _sanitize_css(css: str) -> str:
    """Remove active CSS constructs while preserving layout rules.

    Args:
        css: CSS text from a ``style`` element or attribute.

    Returns:
        Sanitised CSS.
    """
    text = re.sub(r"(?is)<\s*/\s*style", "", css or "")
    text = DANGEROUS_CSS_RE.sub("", text)
    text = re.sub(r"(?is)@import[^;]+;?", "", text)

    def _url(match: re.Match[str]) -> str:
        value = match.group(1).strip().strip("'\"")
        if _is_safe_url(value, allow_data_image=True):
            return f"url('{value}')"
        return "none"

    text = re.sub(r"(?is)url\(\s*([^)]*)\s*\)", _url, text)
    return text


class _EmailSanitizer(HTMLParser):
    """Streaming allow-list sanitiser."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.stack: list[str] = []
        self.skip_depth = 0
        self.in_style = False

    # ------------------------------------------------------------------ #
    # Parser callbacks
    # ------------------------------------------------------------------ #
    def handle_decl(self, decl: str) -> None:
        """Keep only a standards-mode doctype."""
        if decl.strip().lower().startswith("doctype"):
            self.parts.append("<!DOCTYPE html>")

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Emit an allowed start tag with sanitised attributes."""
        tag = tag.lower()
        if tag in DROP_CONTENT_TAGS:
            self.skip_depth += 1
            return
        if self.skip_depth:
            return
        if tag not in ALLOWED_TAGS:
            return
        if tag == "style":
            self.in_style = True
            self.stack.append("style")
            self.parts.append('<style type="text/css">')
            return
        self.parts.append(f"<{tag}{self._render_attrs(tag, attrs)}>")
        if tag not in VOID_TAGS:
            self.stack.append(tag)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Handle self-closing tags as a start+end pair."""
        self.handle_starttag(tag, attrs)
        if tag.lower() not in VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        """Close the matching allowed tag and repair malformed nesting."""
        tag = tag.lower()
        if tag in DROP_CONTENT_TAGS:
            if self.skip_depth:
                self.skip_depth -= 1
            return
        if self.skip_depth:
            return
        if tag == "style":
            if self.in_style:
                self.in_style = False
                self.parts.append("</style>")
                if "style" in self.stack:
                    self.stack.remove("style")
            return
        if tag not in self.stack:
            return
        while self.stack:
            current = self.stack.pop()
            self.parts.append(f"</{current}>")
            if current == tag:
                break

    def handle_data(self, data: str) -> None:
        """Emit escaped text or sanitised CSS."""
        if self.skip_depth:
            return
        if self.in_style:
            self.parts.append(_sanitize_css(data))
        else:
            self.parts.append(html.escape(data, quote=False))

    def handle_comment(self, data: str) -> None:
        """Drop comments (including Outlook conditional comments)."""
        return None

    def handle_pi(self, data: str) -> None:
        """Drop processing instructions."""
        return None

    def handle_entityref(self, name: str) -> None:  # pragma: no cover - parser normally decodes
        """Preserve an unknown entity."""
        if not self.skip_depth:
            self.parts.append(f"&{html.escape(name, quote=False)};")

    def handle_charref(self, name: str) -> None:  # pragma: no cover - parser normally decodes
        """Preserve a numeric entity."""
        if not self.skip_depth:
            self.parts.append(f"&#{html.escape(name, quote=False)};")

    # ------------------------------------------------------------------ #
    # Attribute handling
    # ------------------------------------------------------------------ #
    def _render_attrs(self, tag: str, attrs: list[tuple[str, str | None]]) -> str:
        """Render safe attributes for ``tag``."""
        allowed = GLOBAL_ATTRS | TAG_ATTRS.get(tag, set())
        rendered: list[str] = []
        for raw_name, raw_value in attrs:
            name = (raw_name or "").lower().strip()
            value = raw_value or ""
            if not name or name.startswith("on"):
                continue
            if name.startswith("data-") or name.startswith("aria-"):
                # Editor metadata is inert; still escape it for safe markup.
                rendered.append(f'{name}="{html.escape(value, quote=True)}"')
                continue
            if name not in allowed:
                continue
            if name == "style":
                rendered.append(f'style="{html.escape(_sanitize_css(value), quote=True)}"')
                continue
            if name in URL_ATTRS:
                allow_data = tag == "img" and name == "src"
                if not _is_safe_url(value, allow_data_image=allow_data):
                    continue
            if name == "target":
                value = value if value in {"_blank", "_self"} else "_blank"
            rendered.append(f'{name}="{html.escape(value, quote=True)}"')
        return (" " + " ".join(rendered)) if rendered else ""


def sanitize_email_html(html_text: str) -> str:
    """Sanitise an email HTML document or fragment.

    Args:
        html_text: Raw markup.

    Returns:
        Markup containing only allow-listed tags, attributes and URL schemes.
    """
    if not html_text:
        return ""
    parser = _EmailSanitizer()
    try:
        parser.feed(html_text)
        parser.close()
    except Exception:  # pragma: no cover - malformed markup should never 500
        # Fall back to a conservative escaped representation.
        return html.escape(html_text, quote=False)
    return "".join(parser.parts)


__all__ = ["sanitize_email_html"]
