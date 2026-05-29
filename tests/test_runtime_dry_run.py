import pytest

from src.runtime_dry_run import RuntimeDryRunConfig, choose_runtime_label


def test_runtime_dry_run_defaults_to_v1_label():
    config = RuntimeDryRunConfig.from_env({})

    assert config.target == "v1"
    assert config.v2_percent == 0
    assert choose_runtime_label("user-1", config) == "v1"


def test_runtime_dry_run_labels_v2_at_100_percent():
    config = RuntimeDryRunConfig.from_env(
        {"AGENT_RUNTIME_DRY_RUN_TARGET": "v2", "AGENT_RUNTIME_DRY_RUN_V2_PERCENT": "100"}
    )

    assert choose_runtime_label("user-1", config) == "v2"
    assert choose_runtime_label("user-2", config) == "v2"


def test_runtime_dry_run_v2_target_at_0_percent_stays_v1_label():
    config = RuntimeDryRunConfig.from_env(
        {"AGENT_RUNTIME_DRY_RUN_TARGET": "v2", "AGENT_RUNTIME_DRY_RUN_V2_PERCENT": "0"}
    )

    assert choose_runtime_label("user-1", config) == "v1"


def test_runtime_dry_run_hash_is_stable():
    config = RuntimeDryRunConfig.from_env(
        {"AGENT_RUNTIME_DRY_RUN_TARGET": "v2", "AGENT_RUNTIME_DRY_RUN_V2_PERCENT": "10"}
    )

    assert choose_runtime_label("fixture-user", config) == choose_runtime_label("fixture-user", config)


def test_runtime_dry_run_rejects_invalid_target():
    with pytest.raises(ValueError, match="AGENT_RUNTIME_DRY_RUN_TARGET"):
        RuntimeDryRunConfig.from_env({"AGENT_RUNTIME_DRY_RUN_TARGET": "prod"})


def test_runtime_dry_run_rejects_invalid_percent():
    with pytest.raises(ValueError, match="AGENT_RUNTIME_DRY_RUN_V2_PERCENT"):
        RuntimeDryRunConfig.from_env(
            {"AGENT_RUNTIME_DRY_RUN_TARGET": "v2", "AGENT_RUNTIME_DRY_RUN_V2_PERCENT": "101"}
        )
