"""Transcript fixture runner for P0a.

The runner intentionally lives in tests for this PR: it should exercise the
current v1 runtime without changing production flow.
"""

from pathlib import Path

import pytest

from tests.transcript_runner import (
    assert_fixture_is_redacted,
    load_transcript_fixtures,
    run_transcript_fixture,
)


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "transcripts"
FIXTURES = load_transcript_fixtures(FIXTURE_DIR)


def _fixture_params():
    params = []
    for fixture in FIXTURES:
        marks = []
        if fixture.xfail is not None:
            marks.append(pytest.mark.xfail(reason=fixture.xfail.reason, strict=True))
        params.append(pytest.param(fixture, id=fixture.id, marks=marks))
    return params


def test_transcript_fixtures_are_present_and_redacted():
    assert {f.id for f in FIXTURES} >= {
        "billbill_provenance_xfail",
        "completed_capability_question_v1",
        "completed_date_question_v1",
        "confirmation_submit_v1",
        "numbered_character_choice_v1",
        "ratio_choice_v1",
        "restart_recovery_v1",
        "running_cancel_local_v1",
        "running_chitchat_v1",
        "skill_action_trace_v1",
        "timeout_cancel_local_v1",
        "timeout_continue_wait_v1",
    }
    assert len(FIXTURES) >= 11
    for fixture in FIXTURES:
        assert_fixture_is_redacted(fixture)


@pytest.mark.asyncio
@pytest.mark.parametrize("fixture", _fixture_params())
async def test_transcript_fixture_replays_current_v1_runtime(fixture, monkeypatch):
    await run_transcript_fixture(fixture, monkeypatch)
