"""Logging setup: structured JSON on Cloud Run, readable text locally."""

from __future__ import annotations

import json
import logging
import os
import sys


class CloudJsonFormatter(logging.Formatter):
    """One JSON object per line; Cloud Logging maps 'severity' and 'message'."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "severity": record.levelname,
            "message": record.getMessage(),
            "logger": record.name,
        }
        extra = getattr(record, "json_fields", None)
        if isinstance(extra, dict):
            payload.update(extra)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


class ReadableFormatter(logging.Formatter):
    """Human-friendly local logs that still show the structured fields."""

    def format(self, record: logging.LogRecord) -> str:
        text = super().format(record)
        extra = getattr(record, "json_fields", None)
        if isinstance(extra, dict):
            text += " " + json.dumps(extra, default=str)
        return text


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    if os.getenv("K_SERVICE"):  # set by Cloud Run
        handler.setFormatter(CloudJsonFormatter())
    else:
        handler.setFormatter(ReadableFormatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
