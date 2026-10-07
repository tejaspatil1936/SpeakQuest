"""Structured JSON logging.

CloudWatch Logs Insights can filter on any key, so every log line is a JSON
object with a stable ``event`` name plus context (``analysis_id``, ``stage``).
"""

from __future__ import annotations

import json
import logging
import sys
import time
from typing import Any

_RESERVED = set(vars(logging.makeLogRecord({})).keys()) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created))
            + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _RESERVED and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, separators=(",", ":"))


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    root = logging.getLogger("speakquest")
    if not root.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JsonFormatter())
        root.addHandler(handler)
        root.setLevel(logging.INFO)
        root.propagate = False
    return logger if name.startswith("speakquest") else logging.getLogger(f"speakquest.{name}")


def log_event(logger: logging.Logger, event: str, **fields: Any) -> None:
    logger.info(event, extra=fields)
