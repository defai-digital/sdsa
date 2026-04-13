"""Structured logging with field scrubbing (ADR-0007).

No raw row values ever land in logs. Only metadata: session IDs, shapes,
column names (column *names* are treated as metadata per the PRD — if a
deployment considers column names sensitive, subclass the scrubber).
"""
from __future__ import annotations

import json
import logging
import sys
from typing import Any

SENSITIVE_KEYS = frozenset({
    "body", "column_values", "sample_rows", "row", "value", "values",
    "raw", "data", "payload", "content",
})


class ScrubbingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key in payload or key.startswith("_"):
                continue
            if key in {"args", "msg", "name", "levelname", "levelno", "pathname",
                       "filename", "module", "exc_info", "exc_text", "stack_info",
                       "lineno", "funcName", "created", "msecs", "relativeCreated",
                       "thread", "threadName", "processName", "process", "message",
                       "taskName"}:
                continue
            if key in SENSITIVE_KEYS:
                payload[key] = "[SCRUBBED]"
            else:
                payload[key] = _safe(value)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info).splitlines()[-1]
        return json.dumps(payload, default=str)


def _safe(value: Any) -> Any:
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return str(type(value).__name__)


def setup_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    root.setLevel(level)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(ScrubbingFormatter())
    root.handlers = [handler]


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
