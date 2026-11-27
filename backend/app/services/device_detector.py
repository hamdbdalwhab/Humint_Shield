"""Deep device identification service.

Extracts the exact device brand, model, and OS version from:
1. User-Agent string parsing (via user_agents & regex model maps)
2. Client Hints (Sec-CH-UA-Model, Sec-CH-UA-Platform)
3. Screen geometry & hardware characteristics (for iOS disambiguation)
"""
from __future__ import annotations

import re
from typing import Any
import user_agents

#: User agents that only fetch a URL to build a link preview or crawl a page.
#: WhatsApp, Telegram, Slack, Teams and the social networks all fetch shared
#: links this way; counting them as QR scans inflates campaign statistics by
#: exactly the number of times the link was pasted into a chat.
PREVIEW_BOT_PATTERNS: tuple[str, ...] = (
    "whatsapp/",
    "telegrambot",
    "facebookexternalhit",
    "facebot",
    "twitterbot",
    "linkedinbot",
    "slackbot",
    "slack-imgproxy",
    "discordbot",
    "skypeuripreview",
    "pinterest/",
    "redditbot",
    "embedly",
    "vkshare",
    "mattermost",
    "googlebot",
    "bingbot",
    "applebot",
    "duckduckbot",
    "yandexbot",
    "baiduspider",
    "headlesschrome",
    "phantomjs",
    "python-requests",
    "python-httpx",
    "httpx/",
    "aiohttp/",
    "curl/",
    "wget/",
    "go-http-client",
    "libwww-perl",
    "okhttp/",
)


def is_preview_bot(user_agent: str | None) -> bool:
    """Return ``True`` for link-preview fetchers and crawlers.

    A real phone browser never carries these tokens, so the caller can skip the
    scan instead of creating a phantom QR interaction.
    """
    value = (user_agent or "").strip().lower()
    if not value:
        return False
    return any(token in value for token in PREVIEW_BOT_PATTERNS)

# Known Samsung Galaxy Model Number to Commercial Name Mapping
_SAMSUNG_MODELS: dict[str, str] = {
    # Galaxy S24 Series
    "SM-S921": "Samsung Galaxy S24",
    "SM-S926": "Samsung Galaxy S24+",
    "SM-S928": "Samsung Galaxy S24 Ultra",
    # Galaxy S23 Series
    "SM-S911": "Samsung Galaxy S23",
    "SM-S916": "Samsung Galaxy S23+",
    "SM-S918": "Samsung Galaxy S23 Ultra",
    "SM-S711": "Samsung Galaxy S23 FE",
    # Galaxy S22 Series
    "SM-S901": "Samsung Galaxy S22",
    "SM-S906": "Samsung Galaxy S22+",
    "SM-S908": "Samsung Galaxy S22 Ultra",
    # Galaxy S21 Series
    "SM-G991": "Samsung Galaxy S21",
    "SM-G996": "Samsung Galaxy S21+",
    "SM-G998": "Samsung Galaxy S21 Ultra",
    "SM-G990": "Samsung Galaxy S21 FE",
    # Galaxy S20 Series
    "SM-G980": "Samsung Galaxy S20",
    "SM-G981": "Samsung Galaxy S20 5G",
    "SM-G985": "Samsung Galaxy S20+",
    "SM-G986": "Samsung Galaxy S20+ 5G",
    "SM-G988": "Samsung Galaxy S20 Ultra",
    "SM-G780": "Samsung Galaxy S20 FE",
    "SM-G781": "Samsung Galaxy S20 FE 5G",
    # Galaxy A Series
    "SM-A546": "Samsung Galaxy A54 5G",
    "SM-A556": "Samsung Galaxy A55 5G",
    "SM-A346": "Samsung Galaxy A34 5G",
    "SM-A356": "Samsung Galaxy A35 5G",
    "SM-A536": "Samsung Galaxy A53 5G",
    "SM-A525": "Samsung Galaxy A52",
    "SM-A528": "Samsung Galaxy A52s 5G",
    "SM-A736": "Samsung Galaxy A73 5G",
    "SM-A145": "Samsung Galaxy A14",
    "SM-A146": "Samsung Galaxy A14 5G",
    "SM-A155": "Samsung Galaxy A15",
    "SM-A156": "Samsung Galaxy A15 5G",
    "SM-A245": "Samsung Galaxy A24",
    "SM-A256": "Samsung Galaxy A25 5G",
    # Galaxy Z Fold & Flip Series
    "SM-F946": "Samsung Galaxy Z Fold 5",
    "SM-F731": "Samsung Galaxy Z Flip 5",
    "SM-F936": "Samsung Galaxy Z Fold 4",
    "SM-F721": "Samsung Galaxy Z Flip 4",
    "SM-F926": "Samsung Galaxy Z Fold 3",
    "SM-F711": "Samsung Galaxy Z Flip 3",
    "SM-F956": "Samsung Galaxy Z Fold 6",
    "SM-F741": "Samsung Galaxy Z Flip 6",
    # Note Series
    "SM-N986": "Samsung Galaxy Note 20 Ultra",
    "SM-N980": "Samsung Galaxy Note 20",
    "SM-N975": "Samsung Galaxy Note 10+",
}

# Known Xiaomi / Redmi / POCO Model Codes
_XIAOMI_MODELS: dict[str, str] = {
    "2201116SG": "Xiaomi Redmi Note 11 Pro 5G",
    "2201117TY": "Xiaomi Redmi Note 11S",
    "2201117TG": "Xiaomi Redmi Note 11",
    "2312DRA50G": "Xiaomi Redmi Note 13 Pro",
    "23090RA98G": "Xiaomi Redmi Note 13 Pro+",
    "23129RAA4G": "Xiaomi Redmi Note 13 5G",
    "22101316G": "Xiaomi Redmi Note 12 Pro+",
    "22101316UG": "Xiaomi Redmi Note 12 Pro",
    "23021RAAEG": "Xiaomi Redmi Note 12 4G",
    "23078PND5G": "Xiaomi 13T Pro",
    "2306EPN60G": "Xiaomi 13 Ultra",
    "2201123G": "Xiaomi 12",
    "2201122G": "Xiaomi 12 Pro",
    "23049PCD8G": "POCO F5",
    "23013PC75G": "POCO X5 Pro 5G",
    "22011211G": "POCO F4 GT",
    "M2012K11AG": "POCO F3",
}

# iOS Screen Dimension & Pixel Ratio Mapping
_IOS_SCREEN_MAP: dict[tuple[int, int, int], str] = {
    # (width, height, pixel_ratio)
    (430, 932, 3): "Apple iPhone 15 Pro Max / 16 Plus / 16 Pro Max",
    (393, 852, 3): "Apple iPhone 15 / 15 Pro / 16 / 16 Pro",
    (428, 926, 3): "Apple iPhone 14 Plus / 13 Pro Max / 12 Pro Max",
    (390, 844, 3): "Apple iPhone 14 / 13 / 13 Pro / 12 / 12 Pro",
    (375, 812, 3): "Apple iPhone 13 mini / 12 mini / 11 Pro / XS / X",
    (414, 896, 3): "Apple iPhone 11 Pro Max / XS Max",
    (414, 896, 2): "Apple iPhone 11 / XR",
    (375, 667, 2): "Apple iPhone SE (2nd/3rd Gen) / 8 / 7",
    (414, 736, 3): "Apple iPhone 8 Plus / 7 Plus",
    (360, 780, 3): "Apple iPhone 13 mini / 12 mini",
    # iPads
    (1024, 1366, 2): "Apple iPad Pro 12.9-inch",
    (834, 1194, 2): "Apple iPad Pro 11-inch",
    (820, 1180, 2): "Apple iPad Air (4th/5th Gen) / 10th Gen",
    (810, 1080, 2): "Apple iPad (7th/8th/9th Gen)",
    (744, 1133, 2): "Apple iPad mini (6th Gen)",
}


def detect_device_model(
    user_agent_str: str | None,
    client_hints: dict[str, str] | None = None,
    fingerprint_data: dict[str, Any] | None = None,
) -> str:
    """Resolve the precise hardware brand and model.

    Args:
        user_agent_str: Raw User-Agent header string.
        client_hints: Optional HTTP Client Hints (Sec-CH-UA-Model, etc.)
        fingerprint_data: Optional client-side telemetry (screen, platform, etc.)

    Returns:
        Exact model name, e.g. "Samsung Galaxy S23 Ultra", "Apple iPhone 15 Pro Max",
        "Xiaomi Redmi Note 12 Pro", or a high-accuracy fallback.
    """
    hints = client_hints or {}
    fp = fingerprint_data or {}

    # 1. Explicit Client Hints (highest fidelity for Chromium browsers)
    ch_model = hints.get("sec-ch-ua-model") or hints.get("Sec-CH-UA-Model")
    if ch_model and ch_model.strip().strip('"'):
        clean_model = ch_model.strip().strip('"')
        if clean_model not in ("Nexus 5", "generic", "Android"):
            # Check Samsung mapping
            for prefix, name in _SAMSUNG_MODELS.items():
                if clean_model.startswith(prefix):
                    return name
            return clean_model

    # 2. Explicit Client Model from navigator.userAgentData
    client_model = fp.get("client_model") or fp.get("device_model")
    if isinstance(client_model, str) and client_model.strip():
        cm = client_model.strip()
        for prefix, name in _SAMSUNG_MODELS.items():
            if cm.startswith(prefix):
                return name
        for code, name in _XIAOMI_MODELS.items():
            if code in cm:
                return name
        if len(cm) > 2 and cm not in ("iPhone", "Android", "Unknown"):
            return cm

    ua_clean = (user_agent_str or "").strip()
    if not ua_clean:
        return "Unknown Device"

    ua_lower = ua_clean.lower()

    # 3. iOS Device Disambiguation (Safari freezes UA to "iPhone")
    if "iphone" in ua_lower or "ipad" in ua_lower or fp.get("platform") in ("iPhone", "iPad", "iOS"):
        screen_str = str(fp.get("screen") or fp.get("screen_resolution") or "")
        pixel_ratio = int(fp.get("pixel_ratio") or 3)
        if "x" in screen_str:
            try:
                parts = screen_str.split("x")
                w, h = int(parts[0]), int(parts[1])
                # Ensure width <= height for portrait matching
                if w > h:
                    w, h = h, w
                # Lookup exact screen match
                key = (w, h, pixel_ratio)
                if key in _IOS_SCREEN_MAP:
                    return _IOS_SCREEN_MAP[key]
                # Fallback to (w, h) with any ratio
                for (sw, sh, _), model in _IOS_SCREEN_MAP.items():
                    if (w, h) == (sw, sh):
                        return model
            except (ValueError, IndexError):
                pass
        # If screen dimensions not available or unmapped
        if "ipad" in ua_lower:
            return "Apple iPad"
        return "Apple iPhone"

    # 4. Samsung Galaxy Model Extraction
    samsung_match = re.search(r"\b(SM-[A-Z0-9]{4,6}[A-Z]?)\b", ua_clean)
    if samsung_match:
        code = samsung_match.group(1)
        # Check 7-char prefix (e.g. SM-S918)
        prefix_7 = code[:7]
        if prefix_7 in _SAMSUNG_MODELS:
            return _SAMSUNG_MODELS[prefix_7]
        return f"Samsung Galaxy ({code})"

    # 5. Xiaomi / Redmi / POCO Model Extraction
    for code, name in _XIAOMI_MODELS.items():
        if code in ua_clean:
            return name
    xiaomi_match = re.search(
        r"\b(Redmi Note \d+[A-Za-z0-9 ]*|Redmi \d+[A-Za-z0-9 ]*|POCO [A-Za-z0-9 ]+|Mi \d+[A-Za-z0-9 ]*)\b",
        ua_clean,
        re.IGNORECASE,
    )
    if xiaomi_match:
        return f"Xiaomi {xiaomi_match.group(1)}"

    # 6. Google Pixel
    pixel_match = re.search(r"\b(Pixel \d[a-zA-Z0-9 ]*)\b", ua_clean)
    if pixel_match:
        return f"Google {pixel_match.group(1)}"

    # 7. Huawei / Honor
    huawei_match = re.search(r"\b(HMA-[A-Z0-9]+|VOG-[A-Z0-9]+|ELE-[A-Z0-9]+|ANA-[A-Z0-9]+|ELS-[A-Z0-9]+)\b", ua_clean)
    if huawei_match:
        return f"Huawei ({huawei_match.group(1)})"

    # 8. User-Agents library parsing as standard fallback
    try:
        parsed = user_agents.parse(ua_clean)
        brand = parsed.device.brand
        family = parsed.device.family
        model = parsed.device.model

        parts = [p for p in (brand, model or family) if p and p not in ("Generic", "Spider", "Other")]
        if parts:
            result = " ".join(dict.fromkeys(parts))  # de-duplicate consecutive tokens
            # If result is just "Generic Smartphone", enhance it
            if result.lower() not in ("generic", "generic smartphone", "other"):
                return result
    except Exception:
        pass

    # 9. Generic OS fallback
    if "android" in ua_lower:
        v_match = re.search(r"Android (\d+(\.\d+)?)", ua_clean)
        v = v_match.group(1) if v_match else ""
        return f"Android Device {v}".strip()
    if "windows" in ua_lower:
        return "Windows PC"
    if "macintosh" in ua_lower or "mac os" in ua_lower:
        return "Apple Mac"
    if "linux" in ua_lower:
        return "Linux Device"

    return "Generic Device"
