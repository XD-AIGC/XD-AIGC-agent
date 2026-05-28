"""Fixture-driven transcript runner used by P0a tests.

This is deliberately a test helper, not production runtime. It lets us pin
observed conversation failures before the v2 state/session work exists.
"""

from __future__ import annotations

import json
import asyncio
import re
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

from pydantic import BaseModel, ConfigDict, Field

from src.conversation.session import load_session
from src.orchestrator.schema import BotAction, UserSession
from src.skill.actions import SkillActionObservation
from src.skill.executor import ExecuteResult
from src.skill.schema import PollBackend, Skill, SkillOutput


_RAW_ID_RE = re.compile(r"\b(?:ou|om|oc)_[A-Za-z0-9_]+\b|\bfile_[A-Za-z0-9_]+\b")
_NUMERIC_TRACE_KEYS = {
    "router_llm_calls",
    "skill_llm_calls",
    "skill_action_calls",
    "submit_job_calls",
    "execute_calls",
    "reply_text_calls",
    "reply_image_calls",
}


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class XfailSpec(_StrictModel):
    reason: str


class ExpectSpec(_StrictModel):
    reply_text_contains: list[str] = Field(default_factory=list)
    reply_image_called: bool | None = None
    trace: dict[str, Any] = Field(default_factory=dict)
    session: dict[str, Any] = Field(default_factory=dict)
    v2_optional: dict[str, Any] = Field(default_factory=dict)


class TurnSpec(_StrictModel):
    message_id: str
    text: str
    router_actions: list[dict[str, Any]] = Field(default_factory=list)
    skill_actions: list[dict[str, Any]] = Field(default_factory=list)
    skill_action_results: list[dict[str, Any]] = Field(default_factory=list)
    execute_results: list[dict[str, Any]] = Field(default_factory=list)
    expect: ExpectSpec


class TranscriptFixture(_StrictModel):
    id: str
    description: str
    initial_session: dict[str, Any] = Field(default_factory=dict)
    turns: list[TurnSpec] = Field(default_factory=list)
    requires_session_fields: list[str] = Field(default_factory=list)
    xfail: XfailSpec | None = None
    path: str | None = None


def load_transcript_fixtures(directory: Path) -> list[TranscriptFixture]:
    """Load transcript fixtures in deterministic order."""
    if not directory.exists():
        return []
    fixtures: list[TranscriptFixture] = []
    for path in sorted(directory.glob("*.json")):
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        data["path"] = str(path)
        fixtures.append(TranscriptFixture.model_validate(data))
    return fixtures


def assert_fixture_is_redacted(fixture: TranscriptFixture) -> None:
    """Reject raw Feishu/file identifiers in committed transcript fixtures."""
    raw = json.dumps(fixture.model_dump(), ensure_ascii=False)
    match = _RAW_ID_RE.search(raw)
    assert match is None, f"{fixture.path or fixture.id} contains raw id {match.group(0)!r}"


async def run_transcript_fixture(fixture: TranscriptFixture, monkeypatch) -> None:
    """Replay one text-only fixture against the current v1 agent loop."""
    from src import main as main_mod

    session = load_session(fixture.initial_session)
    _assert_required_session_fields(fixture, session)

    store = _FakeStore(session)
    registry = _fake_registry(session.skill_name or "xd-poster-gen")

    reply_text = AsyncMock()
    reply_image = AsyncMock()
    router_decide = AsyncMock()
    skill_decide = AsyncMock()
    execute_skill_action = AsyncMock()
    execute = AsyncMock()
    submit_poll_job = AsyncMock(return_value="backend-job-fixture")
    poll_existing_job = AsyncMock()
    send_skill_artifact = AsyncMock()
    send_file_id_image = AsyncMock(return_value=None)
    download_url = AsyncMock(return_value=b"image-bytes")
    upload_image = AsyncMock(return_value="img_key_fixture")

    monkeypatch.setattr(main_mod, "_store", store)
    monkeypatch.setattr(main_mod, "reply_text", reply_text)
    monkeypatch.setattr(main_mod, "reply_image", reply_image)
    monkeypatch.setattr(main_mod, "router_decide", router_decide)
    monkeypatch.setattr(main_mod, "skill_decide", skill_decide)
    monkeypatch.setattr(main_mod, "execute_skill_action", execute_skill_action)
    monkeypatch.setattr(main_mod, "execute", execute)
    monkeypatch.setattr(main_mod, "submit_poll_job", submit_poll_job)
    monkeypatch.setattr(main_mod, "poll_existing_job", poll_existing_job)
    monkeypatch.setattr(main_mod, "get_registry", lambda: registry)
    monkeypatch.setattr(main_mod, "_maybe_inject_cached_step1", _identity_payload)
    monkeypatch.setattr(main_mod, "_send_skill_action_artifact", send_skill_artifact)
    monkeypatch.setattr(main_mod, "_maybe_send_skill_image_by_file_id", send_file_id_image)
    monkeypatch.setattr(main_mod, "download_url", download_url)
    monkeypatch.setattr(main_mod, "upload_image", upload_image)

    for turn in fixture.turns:
        router_decide.side_effect = _actions(turn.router_actions)
        skill_decide.side_effect = _actions(turn.skill_actions)
        execute_skill_action.side_effect = _skill_action_results(turn.skill_action_results)
        execute.side_effect = _execute_results(turn.execute_results)
        submit_poll_job.reset_mock()
        poll_existing_job.side_effect = _execute_results(turn.execute_results)

        before = _trace_snapshot(
            router_decide,
            skill_decide,
            execute_skill_action,
            execute,
            submit_poll_job,
            reply_text,
            reply_image,
            store,
        )
        await main_mod._agentic_loop(turn.text, session, "fixture-user", turn.message_id)
        await _drain_background_tasks(main_mod)
        after = _trace_snapshot(
            router_decide,
            skill_decide,
            execute_skill_action,
            execute,
            submit_poll_job,
            reply_text,
            reply_image,
            store,
        )
        delta = _trace_delta(before, after)

        _assert_turn_expectations(turn.expect, session, delta, reply_text, reply_image)


class _FakeStore:
    def __init__(self, session: UserSession) -> None:
        self.session = session
        self.saved: list[UserSession] = []
        self.cleared = False

    async def save(self, _user_id: str, session: UserSession) -> None:
        self.session = session
        self.saved.append(session.model_copy(deep=True))

    async def get_conversation(self, _user_id: str):
        return self.session

    async def save_conversation(self, _user_id: str, session):
        self.session = session
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


def _skill_action_results(items: list[dict[str, Any]]) -> list[SkillActionObservation]:
    return [SkillActionObservation(**item) for item in items]


def _trace_snapshot(
    router_decide: AsyncMock,
    skill_decide: AsyncMock,
    execute_skill_action: AsyncMock,
    execute: AsyncMock,
    submit_poll_job: AsyncMock,
    reply_text: AsyncMock,
    reply_image: AsyncMock,
    store: _FakeStore,
) -> dict[str, Any]:
    return {
        "router_llm_calls": router_decide.await_count,
        "skill_llm_calls": skill_decide.await_count,
        "skill_action_calls": execute_skill_action.await_count,
        "skill_action_names": [call.args[1] for call in execute_skill_action.await_args_list],
        "submit_job_calls": submit_poll_job.await_count,
        "submit_payloads": [call.args[1] for call in submit_poll_job.await_args_list],
        "execute_calls": execute.await_count,
        "reply_text_calls": reply_text.await_count,
        "reply_image_calls": reply_image.await_count,
        "phase_transitions": _phase_transitions(store.saved),
    }


async def _drain_background_tasks(main_mod) -> None:
    tasks = list(main_mod._background_tasks.values())
    if tasks:
        await asyncio.wait_for(asyncio.gather(*tasks), timeout=5)


def _trace_delta(before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    delta: dict[str, Any] = {}
    for key in _NUMERIC_TRACE_KEYS:
        delta[key] = after[key] - before[key]
    for key in ("skill_action_names", "submit_payloads", "phase_transitions"):
        delta[key] = after[key][len(before[key]):]
    return delta


def _assert_turn_expectations(
    expect: ExpectSpec,
    session: UserSession,
    trace_delta: dict[str, Any],
    reply_text: AsyncMock,
    reply_image: AsyncMock,
) -> None:
    for key, value in expect.trace.items():
        assert trace_delta.get(key) == value, f"trace.{key}: expected {value}, got {trace_delta.get(key)}"

    if expect.reply_text_contains:
        texts = _recent_reply_texts(reply_text, trace_delta.get("reply_text_calls", 0))
        joined = "\n".join(texts)
        for needle in expect.reply_text_contains:
            assert needle in joined

    if expect.reply_image_called is not None:
        assert bool(trace_delta.get("reply_image_calls")) is expect.reply_image_called

    _assert_subset(expect.session, session.model_dump(), "session")
    _assert_v2_optional(expect.v2_optional, session, trace_delta)


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
        elif isinstance(expected_value, list):
            _assert_list(expected_value, actual_value, f"{prefix}.{key}")
        else:
            assert actual_value == expected_value, f"{prefix}.{key}: expected {expected_value!r}, got {actual_value!r}"


def _assert_list(expected: list[Any], actual: Any, prefix: str) -> None:
    assert isinstance(actual, list), f"{prefix} is not a list"
    assert len(actual) == len(expected), f"{prefix}: expected len {len(expected)}, got {len(actual)}"
    for idx, expected_item in enumerate(expected):
        actual_item = actual[idx]
        if isinstance(expected_item, dict):
            assert isinstance(actual_item, dict), f"{prefix}[{idx}] is not a dict"
            _assert_subset(expected_item, actual_item, f"{prefix}[{idx}]")
        else:
            assert actual_item == expected_item, f"{prefix}[{idx}]: expected {expected_item!r}, got {actual_item!r}"


def _assert_v2_optional(expected: dict[str, Any], session: UserSession, trace_delta: dict[str, Any]) -> None:
    """Assert target v2 fields only when the current object already exposes them."""
    if not expected:
        return
    if "phase" in expected and hasattr(session, "phase"):
        assert getattr(session, "phase") == expected["phase"]
    if "last_processed_message_ids_contains" in expected and hasattr(session, "last_processed_message_ids"):
        assert expected["last_processed_message_ids_contains"] in getattr(session, "last_processed_message_ids")
    if "last_options_present" in expected and hasattr(session, "last_options"):
        assert bool(getattr(session, "last_options")) is expected["last_options_present"]
    if "phase_transitions" in expected and trace_delta.get("phase_transitions"):
        assert trace_delta["phase_transitions"] == expected["phase_transitions"]


def _assert_required_session_fields(fixture: TranscriptFixture, session: UserSession) -> None:
    for field in fixture.requires_session_fields:
        assert hasattr(session, field), f"{fixture.id} requires session field {field!r}"


def _phase_transitions(sessions: list[UserSession]) -> list[str]:
    phases: list[str] = []
    for session in sessions:
        phase = getattr(session, "phase", None)
        if phase is None:
            continue
        phases.append(getattr(phase, "value", str(phase)))
    return phases
