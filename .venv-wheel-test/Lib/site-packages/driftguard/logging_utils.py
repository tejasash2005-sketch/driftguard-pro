"""Logging helpers that never emit credentials."""

from __future__ import annotations

import logging
import os
import re
import sys
from typing import TextIO

_SECRET_ENV_HINTS = ("KEY", "TOKEN", "SECRET", "PASSWORD")
_SK_PATTERN = re.compile(r"sk-[A-Za-z0-9_\-]{8,}")
_BEARER_PATTERN = re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]{8,}")
_ASSIGN_PATTERN = re.compile(
    r"(?i)((?:api[_-]?key|token|secret|password|authorization)[\"']?\s*[:=]\s*[\"']?)"
    r"[^\s\"',}]{4,}"
)
REDACTED = "[REDACTED]"
_HANDLER_MARK = "_driftguard_handler"


def _secret_values() -> list[str]:
    values = {
        value
        for name, value in os.environ.items()
        if len(value) >= 8 and any(hint in name.upper() for hint in _SECRET_ENV_HINTS)
    }
    return sorted(values, key=len, reverse=True)


def redact(text: str) -> str:
    """Mask API keys, bearer tokens and secret-looking environment values."""
    for value in _secret_values():
        text = text.replace(value, REDACTED)
    text = _SK_PATTERN.sub(REDACTED, text)
    text = _BEARER_PATTERN.sub(rf"\1{REDACTED}", text)
    return _ASSIGN_PATTERN.sub(rf"\1{REDACTED}", text)


class RedactingFormatter(logging.Formatter):
    """Formatter that redacts the fully rendered record, including tracebacks."""

    def format(self, record: logging.LogRecord) -> str:
        return redact(super().format(record))


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"driftguard.{name}")


def configure_logging(verbosity: int = 0, stream: TextIO | None = None) -> None:
    """Configure the ``driftguard`` logger. 0=warnings, 1=info, 2+=debug."""
    level = logging.WARNING if verbosity <= 0 else logging.INFO if verbosity == 1 else logging.DEBUG
    root = logging.getLogger("driftguard")
    root.setLevel(level)
    for handler in list(root.handlers):
        if getattr(handler, _HANDLER_MARK, False):
            root.removeHandler(handler)
    handler = logging.StreamHandler(stream or sys.stderr)
    handler.setFormatter(RedactingFormatter("%(levelname)s %(name)s: %(message)s"))
    setattr(handler, _HANDLER_MARK, True)
    root.addHandler(handler)
    root.propagate = False
