"""Log-based monitoring events for production rollout checks."""

from __future__ import annotations

import logging
from typing import Any


log = logging.getLogger(__name__)


def record_metric(name: str, **fields: Any) -> None:
    """Emit a structured metric line that can be counted from service logs."""
    suffix = _format_fields(fields)
    log.info("[METRIC] name=%s%s", name, f" {suffix}" if suffix else "")


def _format_fields(fields: dict[str, Any]) -> str:
    parts = []
    for key, value in sorted(fields.items()):
        if value is None:
            continue
        parts.append(f"{key}={_format_value(value)}")
    return " ".join(parts)


def _format_value(value: Any) -> str:
    return str(value).replace("\n", "\\n").replace("\r", "\\r").replace(" ", "_")
