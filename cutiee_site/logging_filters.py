"""Hand-rolled JSON log formatter so we do not pull a third-party logger.

The format mirrors what Render's log drain and Loki ingesters expect.
Each record produces a single JSON line with timestamp, level, logger,
message, module, and any structured `extra` keys passed via
`logger.info("...", extra={"k": "v"})`. Exception info, when present,
is captured under `exc_info` to keep tracebacks searchable.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

_RESERVED_LOG_RECORD_FIELDS = frozenset(
    {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "message",
        "module",
        "msecs",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "thread",
        "threadName",
        "taskName",
    }
)


class JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
        }
        for key, value in record.__dict__.items():
            if key in _RESERVED_LOG_RECORD_FIELDS or key.startswith("_"):
                continue
            try:
                json.dumps(value)
            except (TypeError, ValueError):
                value = repr(value)
            payload[key] = value
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str, separators=(",", ":"))
