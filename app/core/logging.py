"""Logging setup with request-ID correlation and secret redaction."""

import json
import logging
import re
import sys
from contextvars import ContextVar
from datetime import UTC, datetime

request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")

_REDACTED = "***"
_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)\b(basic|bearer)\s+[A-Za-z0-9+/=._~-]{8,}"),
    re.compile(
        r"(?i)((?:api[_-]?token|api[_-]?key|password|secret|authorization)"
        r"[\"']?\s*[:=]\s*[\"']?)[^\s\"',}]+"
    ),
)


def redact(text: str) -> str:
    """Mask credentials that may appear in a log message."""
    text = _SECRET_PATTERNS[0].sub(lambda m: f"{m.group(1)} {_REDACTED}", text)
    return _SECRET_PATTERNS[1].sub(lambda m: f"{m.group(1)}{_REDACTED}", text)


class _RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_ctx.get()
        return True


class _TextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return redact(super().format(record))


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "request_id": getattr(record, "request_id", "-"),
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return redact(json.dumps(payload, ensure_ascii=False))


def setup_logging(level: str = "INFO", json_output: bool = False) -> None:
    """Configure the root logger. Safe to call more than once."""
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(_RequestIdFilter())
    if json_output:
        handler.setFormatter(_JsonFormatter())
    else:
        handler.setFormatter(
            _TextFormatter("%(asctime)s %(levelname)-7s [%(request_id)s] %(name)s: %(message)s")
        )
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())
    # httpx logs full URLs at INFO; keep it quiet - our client logs its own redacted lines.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
