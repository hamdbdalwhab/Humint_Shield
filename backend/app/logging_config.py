"""Structured logging configuration (structlog).

Produces human friendly output in development and JSON logs in production so
they can be shipped to a log aggregator unchanged.
"""
from __future__ import annotations

import logging
import sys

import structlog

from app.config import Settings


def _force_utf8(stream: object) -> None:
    """Make a console/file stream safe for non-ASCII log messages.

    Windows consoles often default to a legacy code page (for example cp1256).
    Provider error messages can contain arrows or other Unicode punctuation;
    without this guard, writing such a message raises ``UnicodeEncodeError``
    inside the logging handler and can turn a clean provider error into a 500.
    """
    reconfigure = getattr(stream, "reconfigure", None)
    if callable(reconfigure):
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError, ValueError):
            # Captured/pseudo streams may not support reconfiguration.
            pass


def configure_logging(settings: Settings) -> None:
    """Configure stdlib logging + structlog.

    Args:
        settings: Application settings providing level and JSON preference.
    """
    _force_utf8(sys.stdout)
    _force_utf8(sys.stderr)
    level = getattr(logging, settings.log_level.upper(), logging.INFO)

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=level,
    )

    shared_processors: list = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if settings.log_json:
        renderer: structlog.types.Processor = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=False)

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)

    # Quieten noisy third-party loggers.
    for noisy in ("uvicorn.access", "sqlalchemy.engine.Engine"):
        logging.getLogger(noisy).setLevel(max(level, logging.WARNING))


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Return a bound structlog logger.

    Args:
        name: Optional logger name.

    Returns:
        A structlog bound logger.
    """
    return structlog.get_logger(name)
