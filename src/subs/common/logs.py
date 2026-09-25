"""Structured JSON logs with session_id (RF-034, research.md R14).

At INFO and above, subtitle text and audio never reach the output, even if passed by mistake.
Text is allowed only in DEBUG records; audio is never logged.
"""

import json
import logging
import sys
from datetime import UTC, datetime

# Attributes every LogRecord has; anything else came from `extra=`.
_STANDARD_ATTRS = frozenset(vars(logging.LogRecord("", 0, "", 0, "", None, None))) | {"message", "asctime"}
_NEVER_LOGGED = frozenset({"audio"})
_DEBUG_ONLY = frozenset({"text"})


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "session_id": getattr(record, "session_id", None),
        }
        for key, value in vars(record).items():
            if key in _STANDARD_ATTRS or key in entry or key in _NEVER_LOGGED:
                continue
            if key in _DEBUG_ONLY and record.levelno > logging.DEBUG:
                continue
            entry[key] = value
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False, default=str)


def setup_logging(level: str) -> None:
    """Send JSON logs to stdout. Safe to call more than once."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())
