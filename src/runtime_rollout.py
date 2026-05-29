"""Runtime rollout helpers for gradual agent harness deployment."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Literal, Mapping, cast


RuntimeMode = Literal["v1", "v2"]


@dataclass(frozen=True)
class RuntimeRolloutConfig:
    mode: RuntimeMode = "v1"
    v2_percent: int = 0

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "RuntimeRolloutConfig":
        mode = env.get("AGENT_RUNTIME", "v1").strip().lower()
        if mode not in {"v1", "v2"}:
            raise ValueError("AGENT_RUNTIME must be 'v1' or 'v2'")
        raw_percent = env.get("AGENT_RUNTIME_V2_PERCENT", "0").strip()
        try:
            percent = int(raw_percent)
        except ValueError as exc:
            raise ValueError("AGENT_RUNTIME_V2_PERCENT must be an integer 0-100") from exc
        if not 0 <= percent <= 100:
            raise ValueError("AGENT_RUNTIME_V2_PERCENT must be in range 0-100")
        return cls(mode=cast(RuntimeMode, mode), v2_percent=percent)


def choose_runtime(user_id: str, config: RuntimeRolloutConfig) -> RuntimeMode:
    """Choose a stable runtime variant for one user."""
    if config.mode == "v1" or config.v2_percent <= 0:
        return "v1"
    if config.v2_percent >= 100:
        return "v2"
    bucket = _stable_bucket(user_id)
    return "v2" if bucket < config.v2_percent else "v1"


def _stable_bucket(value: str) -> int:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % 100
