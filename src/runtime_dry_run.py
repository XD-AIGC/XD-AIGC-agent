"""Runtime dry-run labels for future agent harness rollout planning."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Literal, Mapping, cast


RuntimeLabel = Literal["v1", "v2"]


@dataclass(frozen=True)
class RuntimeDryRunConfig:
    target: RuntimeLabel = "v1"
    v2_percent: int = 0

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "RuntimeDryRunConfig":
        target = env.get("AGENT_RUNTIME_DRY_RUN_TARGET", "v1").strip().lower()
        if target not in {"v1", "v2"}:
            raise ValueError("AGENT_RUNTIME_DRY_RUN_TARGET must be 'v1' or 'v2'")
        raw_percent = env.get("AGENT_RUNTIME_DRY_RUN_V2_PERCENT", "0").strip()
        try:
            percent = int(raw_percent)
        except ValueError as exc:
            raise ValueError("AGENT_RUNTIME_DRY_RUN_V2_PERCENT must be an integer 0-100") from exc
        if not 0 <= percent <= 100:
            raise ValueError("AGENT_RUNTIME_DRY_RUN_V2_PERCENT must be in range 0-100")
        return cls(target=cast(RuntimeLabel, target), v2_percent=percent)


def choose_runtime_label(user_id: str, config: RuntimeDryRunConfig) -> RuntimeLabel:
    """Choose a stable observability label; this does not change execution."""
    if config.target == "v1" or config.v2_percent <= 0:
        return "v1"
    if config.v2_percent >= 100:
        return "v2"
    bucket = _stable_bucket(user_id)
    return "v2" if bucket < config.v2_percent else "v1"


def _stable_bucket(value: str) -> int:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % 100
