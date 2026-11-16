"""Structured operational logging. Never log raw vendor payloads or exceptions."""

import json
import logging
import os
import re

SENSITIVE = re.compile(
    r"(secret|token|password|authorization|api[-_]?key|key[-_]?id|signature|credential)", re.I
)
# Accept header representations such as x-api-key: value and 'x-api-key': 'value'.
AUTH = re.compile(
    r"""(?i)(["']?(?:authorization|x[-_]signature)["']?\s*[:=]\s*)(?:"[^"]*"|'[^']*'|[^\r\n,;}]+)"""
)
INLINE = re.compile(
    r"""(?i)(["']?(?:x[-_])?(?:api[-_]?key|api[-_]?secret|key[-_]?id|secret|token|trading[-_]?token|"""
    r"""password|signature|credential)["']?\s*[:=]\s*)(?:"[^"]*"|'[^']*'|[^\s,;}\]]+)"""
)
_SECRET_ENV_NAMES = ("DNSE_API_KEY", "DNSE_API_SECRET", "DNSE_TRADING_TOKEN", "TRADING_TOKEN")


def redact(value):
    # Exact values are read solely for in-memory substitution, never returned or logged.
    secrets = tuple(os.environ[name] for name in _SECRET_ENV_NAMES if os.environ.get(name))
    return _redact(value, secrets)


def _redact(value, secrets):
    if isinstance(value, dict):
        return {
            (_redact(k, secrets) if isinstance(k, str) else k): (
                "[REDACTED]" if SENSITIVE.search(str(k)) else _redact(v, secrets)
            )
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_redact(v, secrets) for v in value]
    if isinstance(value, str):
        for secret in secrets:
            value = value.replace(secret, "[REDACTED]")
        return INLINE.sub(r"\1[REDACTED]", AUTH.sub(r"\1[REDACTED]", value))
    return value


class JSONFormatter(logging.Formatter):
    def format(self, record):
        return json.dumps(
            redact(
                {
                    "level": record.levelname,
                    "message": record.getMessage(),
                    "metadata": getattr(record, "metadata", {}),
                }
            )
        )


def configure():
    handler = logging.StreamHandler()
    handler.setFormatter(JSONFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.INFO)
    # SDK modules attach their own handlers. SDK clients are blocked at the facade;
    # suppress existing SDK loggers as defense in depth, not as the security boundary.
    for name in list(logging.root.manager.loggerDict):
        if name == "dnse" or name.startswith("dnse."):
            logger = logging.getLogger(name)
            logger.disabled = True
            logger.handlers.clear()
