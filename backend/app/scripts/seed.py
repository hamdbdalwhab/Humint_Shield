"""Seed CLI: ``python -m app.scripts.seed``.

Creates (idempotently) the bootstrap organization, admin user, the eight
built-in email templates and the training-library catalogue.  Safe to run on
every deployment.
"""
from __future__ import annotations

import asyncio
import sys

from app.config import get_settings
from app.database import dispose_engine, get_session_factory
from app.logging_config import configure_logging, get_logger
from app.services.seed import ensure_bootstrap_data

logger = get_logger(__name__)


async def _main() -> int:
    """Run the seed routine and print a summary."""
    settings = get_settings()
    configure_logging(settings)
    async with get_session_factory()() as session:
        summary = await ensure_bootstrap_data(session)
    await dispose_engine()
    logger.info("seed_complete", **summary)
    print("Seed complete:")
    for key, value in summary.items():
        print(f"  {key}: {value}")
    return 0


def main() -> int:
    """Entry point."""
    try:
        return asyncio.run(_main())
    except KeyboardInterrupt:  # pragma: no cover
        return 130


if __name__ == "__main__":
    sys.exit(main())
