"""
logging_config.py

Shared structured logging for ROD. Every component (auth, MCP tools, agent
loop, investigations service) calls get_logger(component) and logs through
it, so failures across the whole system land in one file with a consistent
shape instead of being scattered print()s or silent except-blocks.

Output: JSON-lines at logs/rod.log — one JSON object per line, so a single
`grep`/`jq` pass can pull every event for one investigation_id and read the
whole causal chain (auth -> tool call -> agent retry -> escalation) in order.
A plain-text stream handler also prints to stdout for local dev.

Usage:
    from logging_config import get_logger
    logger = get_logger("mcp.suppliers")
    logger.error(
        "delivery query failed",
        extra={"event": "db_error", "error_type": "OperationalError",
               "investigation_id": investigation_id},
    )

Standard `extra` fields (all optional, default to None if omitted):
    event             short machine-stable tag, e.g. "scope_denied", "tool_exception"
    investigation_id  ties a log line back to one investigation for demo grep/jq
    error_type        exception class name or structured error "error" code
"""

import json
import logging
import logging.handlers
import pathlib

LOG_DIR = pathlib.Path(__file__).resolve().parent / "logs"
LOG_FILE = LOG_DIR / "rod.log"

_EXTRA_FIELDS = ("component", "event", "investigation_id", "error_type")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "message": record.getMessage(),
        }
        for field in _EXTRA_FIELDS:
            payload[field] = getattr(record, field, None)
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload)


class _ComponentAdapter(logging.LoggerAdapter):
    """Merges the adapter's fixed `component` into each call's `extra` dict
    instead of the stdlib default, which replaces extra entirely."""

    def process(self, msg, kwargs):
        extra = {**self.extra, **kwargs.get("extra", {})}
        kwargs["extra"] = extra
        return msg, kwargs


_configured = False


def _configure_root() -> None:
    global _configured
    if _configured:
        return
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    file_handler = logging.handlers.RotatingFileHandler(
        LOG_FILE, maxBytes=5_000_000, backupCount=3
    )
    file_handler.setFormatter(JsonFormatter())

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))

    root = logging.getLogger("rod")
    root.setLevel(logging.INFO)
    root.addHandler(file_handler)
    root.addHandler(console_handler)
    root.propagate = False

    _configured = True


def get_logger(component: str) -> logging.LoggerAdapter:
    """Returns a logger scoped to `component` (e.g. "mcp.suppliers",
    "agent.graph"). component is stamped onto every record so log
    lines can be filtered by which part of the system emitted them."""
    _configure_root()
    base = logging.getLogger(f"rod.{component}")
    return _ComponentAdapter(base, {"component": component})
