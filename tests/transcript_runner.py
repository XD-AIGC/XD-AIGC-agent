"""Fixture-driven transcript runner used by P0a tests.

This is deliberately a test helper, not production runtime. It lets us pin
observed conversation failures before the v2 state/session work exists.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

from src.orchestrator.schema import BotAction, UserSession
from src.skill.executor import ExecuteResult
from src.skill.schema import PollBackend, Skill, SkillOutput


_RAW_ID_RE = re.compile(r"\b(?:ou|om|oc)_[A-Za-z0-9_]+\b|\bfile_[A-Za-z0-9_]+\b")


def load_transcript_fixtures(directory: Path) -> list[dict[str, Any]]:
    """Load transcript fixtures in deterministic order."""
    if not directory.exists():
        return []
    fixtures: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*.json")):
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        data["_path"] = str(path)
        fixtures.append(data)
    return fixtures


def assert_fixture_is_redacted(fixture: dict[str, Any]) -> None:
    """Reject raw Feishu/file identifiers in committed transcript fixtures."""
    raw = json.dumps(fixture, ensure_ascii=False)
    match = _RAW_ID_RE.search(raw)
    assert match is None, f"{fixture.get('_path', fixture.get('id'))} contains raw id {match.group(0)!r}"


async def run_transcript_fixture(fixture: dict[str, Any]) -> None:
    """Replay one text-only fixture against the current v1 agent loop."""
    from src import main as main_mod

    session = UserSession.model_validate(fixture.get("initial_session", {}))
    store = _FakeStore()
    registry = _fake_registry(session.skill_name or "xd-poster-gen")

    reply_text = AsyncMock()
    reply_image = AsyncMock()
    router_decide = AsyncMock()
    skill_decide = AsyncMock()
    execute = AsyncMock()

    original_store = main_mod._store
    original_reply_text = main_mod.reply_text
    original_reply_image = main_mod.reply_image
    original_router_decide = main_mod.router_decide
    original_skill_decide = main_mod.skill_decide
    original_execute = main_mod.execute
    original_get_registry = main_mod.get_registry
    original_maybe_inject = main_mod._maybe_inject_cached_step1

    try:
        main_mod._store = store
        main_mod.reply_text = reply_text
        main_mod.reply_image = reply_image
        main_mod.router_decide = router_decide
        main_mod.skill_decide = skill_decide
        main_mod.execute = execute
        main_mod.get_registry = lambda: registry
        main_mod._maybe_inject_cached_step1 = _identity_payload

        for turn in fixture.get("turns", []):
            router_decide.side_effect = _actions(turn.get("router_actions", []))
            skill_decide.side_effect = _actions(turn.get("skill_actions", []))
            execute.side_effect = _execute_results(turn.get("execute_results", []))

            before = _counts(router_decide, skill_decide, execute, reply_text, reply_image)
            await main_mod._agentic_loop(turn["text"], session, "fixture-user", turn["message_id"])
            after = _counts(router_decide, skill_decide, execute, reply_text, reply_image)
            delta = {key: after[key] - before[key] for key in before}

            _assert_turn_expectations(turn["expect"], session, delta, reply_text, reply_image)
    finally:
        main_mod._store = original_store
        main_mod.reply_text = original_reply_text
        main_mod.reply_image = original_reply_image
        main_mod.router_decide = original_router_decide
        main_mod.skill_decide = original_skill_decide
        main_mod.execute = original_execute
        main_mod.get_registry = original_get_registry
        main_mod._maybe_inject_cached_step1 = original_maybe_inject


class _FakeStore:
    def __init__(self) -> None:
        self.saved: list[UserSession] = []
        self.cleared = False

    async def save(self, _user_id: str, session: UserSession) -> None:
        self.saved.append(session.model_copy(deep=True))

    async def clear(self, _user_id: str) -> None:
        self.cleared = True


async def _identity_payload(payload: Any, _user_id: str) -> Any:
    return payload


def _fake_registry(skill_name: str) -> dict[str, Skill]:
    skill = Skill(
        name=skill_name,
        description="我可以继续帮你做图",
        api=PollBackend(
            type="poll",
            submit_path="/api/generate-v2",
            poll_path_template="/api/poll-v2/{job_id}",
        ),
        params=[],
        output=SkillOutput(type="image_url", display_as="feishu_image"),
        system_prompt_core="test skill core",
    )
    return {skill_name: skill}


def _actions(items: list[dict[str, Any]]) -> list[BotAction]:
    return [BotAction.model_validate(item) for item in items]


def _execute_results(items: list[dict[str, Any]]) -> list[ExecuteResult]:
    return [ExecuteResult(**item) for item in items]


def _counts(*mocks: AsyncMock) -> dict[str, int]:
    router_decide, skill_decide, execute, reply_text, reply_image = mocks
    return {
        "router_llm_calls": router_decide.await_count,
        "skill_llm_calls": skill_decide.await_count,
        "execute_calls": execute.await_count,
        "reply_text_calls": reply_text.await_count,
        "reply_image_calls": reply_image.await_count,
    }


def _assert_turn_expectations(
    expect: dict[str, Any],
    session: UserSession,
    trace_delta: dict[str, int],
    reply_text: AsyncMock,
    reply_image: AsyncMock,
) -> None:
    for key, value in expect.get("trace", {}).items():
        assert trace_delta.get(key) == value, f"trace.{key}: expected {value}, got {trace_delta.get(key)}"

    if "reply_text_contains" in expect:
        texts = _recent_reply_texts(reply_text, trace_delta.get("reply_text_calls", 0))
        joined = "\n".join(texts)
        for needle in expect["reply_text_contains"]:
            assert needle in joined

    if expect.get("reply_image_called") is not None:
        assert bool(trace_delta.get("reply_image_calls")) is expect["reply_image_called"]

    _assert_subset(expect.get("session", {}), session.model_dump(), "session")
    _assert_v2_optional(expect.get("v2_optional", {}), session)


def _recent_reply_texts(reply_text: AsyncMock, count: int) -> list[str]:
    if count <= 0:
        return []
    calls = reply_text.await_args_list[-count:]
    return [call.args[2] for call in calls]


def _assert_subset(expected: dict[str, Any], actual: dict[str, Any], prefix: str) -> None:
    for key, expected_value in expected.items():
        assert key in actual, f"{prefix}.{key} missing"
        actual_value = actual[key]
        if isinstance(expected_value, dict):
            assert isinstance(actual_value, dict), f"{prefix}.{key} is not a dict"
            _assert_subset(expected_value, actual_value, f"{prefix}.{key}")
        else:
            assert actual_value == expected_value, f"{prefix}.{key}: expected {expected_value!r}, got {actual_value!r}"


def _assert_v2_optional(expected: dict[str, Any], session: UserSession) -> None:
    """Assert target v2 fields only when the current object already exposes them."""
    if not expected:
        return
    if "phase" in expected and hasattr(session, "phase"):
        assert getattr(session, "phase") == expected["phase"]
    if "last_processed_message_ids_contains" in expected and hasattr(session, "last_processed_message_ids"):
        assert expected["last_processed_message_ids_contains"] in getattr(session, "last_processed_message_ids")
    if "last_options_written" in expected and hasattr(session, "last_options"):
        assert bool(getattr(session, "last_options")) is expected["last_options_written"]
