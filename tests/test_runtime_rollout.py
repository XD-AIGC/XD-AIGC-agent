import pytest

from src.runtime_rollout import RuntimeRolloutConfig, choose_runtime


def test_runtime_rollout_defaults_to_v1():
    config = RuntimeRolloutConfig.from_env({})

    assert config.mode == "v1"
    assert config.v2_percent == 0
    assert choose_runtime("user-1", config) == "v1"


def test_runtime_rollout_v2_at_100_percent():
    config = RuntimeRolloutConfig.from_env(
        {"AGENT_RUNTIME": "v2", "AGENT_RUNTIME_V2_PERCENT": "100"}
    )

    assert choose_runtime("user-1", config) == "v2"
    assert choose_runtime("user-2", config) == "v2"


def test_runtime_rollout_v2_at_0_percent_stays_v1():
    config = RuntimeRolloutConfig.from_env(
        {"AGENT_RUNTIME": "v2", "AGENT_RUNTIME_V2_PERCENT": "0"}
    )

    assert choose_runtime("user-1", config) == "v1"


def test_runtime_rollout_hash_is_stable():
    config = RuntimeRolloutConfig.from_env(
        {"AGENT_RUNTIME": "v2", "AGENT_RUNTIME_V2_PERCENT": "10"}
    )

    assert choose_runtime("fixture-user", config) == choose_runtime("fixture-user", config)


def test_runtime_rollout_rejects_invalid_mode():
    with pytest.raises(ValueError, match="AGENT_RUNTIME"):
        RuntimeRolloutConfig.from_env({"AGENT_RUNTIME": "prod"})


def test_runtime_rollout_rejects_invalid_percent():
    with pytest.raises(ValueError, match="AGENT_RUNTIME_V2_PERCENT"):
        RuntimeRolloutConfig.from_env({"AGENT_RUNTIME": "v2", "AGENT_RUNTIME_V2_PERCENT": "101"})
