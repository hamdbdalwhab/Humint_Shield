"""Logging stream safety tests.

Provider errors can contain Unicode punctuation. On Windows the console often
uses a legacy code page, so the logging setup must force UTF-8 (or replace)
instead of allowing a log call to crash the request.
"""
from __future__ import annotations

from app.logging_config import _force_utf8


class _ReconfigurableStream:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    def reconfigure(self, **kwargs: str) -> None:
        self.calls.append(kwargs)


def test_force_utf8_reconfigures_stream() -> None:
    stream = _ReconfigurableStream()

    _force_utf8(stream)

    assert stream.calls == [{"encoding": "utf-8", "errors": "replace"}]


def test_force_utf8_ignores_stream_without_reconfigure() -> None:
    class _PlainStream:
        pass

    # Must not raise for captured or third-party streams.
    _force_utf8(_PlainStream())


def test_force_utf8_ignores_reconfigure_failure() -> None:
    class _BrokenStream:
        def reconfigure(self, **kwargs: str) -> None:
            raise OSError("stream is not reconfigurable")

    _force_utf8(_BrokenStream())
