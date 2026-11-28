"""Proof-of-accuracy run: call the pretext engine five times, print the JSON.

Each case uses a different psychological trigger, channel and target profile, so
the output proves the engine adapts instead of returning one canned message.

Usage (from the ``backend`` directory, with the provider configured in ``.env``)::

    python scripts/pretext_demo.py

Exit codes: ``0`` all five generated, ``1`` provider not configured,
``2`` at least one generation failed.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

# Allow ``python scripts/pretext_demo.py`` without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings  # noqa: E402
from app.schemas.ai import PretextGenerateRequest  # noqa: E402
from app.services.ai_service import AIService, AIServiceError  # noqa: E402

CASES: list[dict[str, Any]] = [
    {
        "label": "1. Authority / Email / Finance",
        "request": PretextGenerateRequest(
            employee_name="Ahmed",
            job_title="Accountant",
            department="Finance",
            company_name="Acme Corp",
            industry="Banking",
            pretext="authority",
            channel="email",
            language="ar",
        ),
    },
    {
        "label": "2. Urgency / SMS / IT",
        "request": PretextGenerateRequest(
            employee_name="Sara",
            job_title="System Administrator",
            department="IT",
            company_name="Acme Corp",
            industry="Technology",
            pretext="urgency",
            channel="sms",
            language="ar",
        ),
    },
    {
        "label": "3. Familiarity / Email / HR",
        "request": PretextGenerateRequest(
            employee_name="Noura",
            job_title="HR Specialist",
            department="HR",
            company_name="Acme Corp",
            industry="Consulting",
            pretext="familiarity",
            channel="email",
            language="ar",
        ),
    },
    {
        "label": "4. Fear / WhatsApp / Executive",
        "request": PretextGenerateRequest(
            employee_name="Khalid",
            job_title="Chief Financial Officer",
            department="Executive",
            company_name="Acme Corp",
            industry="Banking",
            pretext="fear",
            channel="whatsapp",
            language="ar-SA",
        ),
    },
    {
        "label": "5. Scarcity / Email / Sales",
        "request": PretextGenerateRequest(
            employee_name="Layla",
            job_title="Account Executive",
            department="Sales",
            company_name="Acme Corp",
            industry="Retail",
            pretext="scarcity",
            channel="email",
            language="ar",
        ),
    },
]


async def main() -> int:
    """Run the five cases and print each validated JSON result."""
    settings = get_settings()
    if not settings.llm_configured:
        missing = ", ".join(settings.llm_missing_settings())
        print(
            "AI provider is not configured; set "
            f"{missing} in backend/.env before running this demo.",
            file=sys.stderr,
        )
        return 1

    service = AIService(settings)
    failures = 0
    for case in CASES:
        request: PretextGenerateRequest = case["request"]
        print("=" * 78)
        print(case["label"])
        print("-" * 78)
        try:
            result = await service.generate_pretext(request)
        except AIServiceError as exc:
            failures += 1
            print(json.dumps({"error": str(exc)}, ensure_ascii=False, indent=2))
            continue
        print(json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2))
    print("=" * 78)
    print(f"generated={len(CASES) - failures} failed={failures}")
    return 0 if failures == 0 else 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
