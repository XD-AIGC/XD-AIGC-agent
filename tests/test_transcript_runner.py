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


def test_transcript_fixtures_are_present_and_redacted():
    fixtures = load_transcript_fixtures(FIXTURE_DIR)

    assert {f["id"] for f in fixtures} >= {
        "completed_capability_question_v1",
        "numbered_character_choice_v1",
        "ratio_choice_v1",
    }
    for fixture in fixtures:
        assert_fixture_is_redacted(fixture)


@pytest.mark.asyncio
@pytest.mark.parametrize("fixture", load_transcript_fixtures(FIXTURE_DIR), ids=lambda f: f["id"])
async def test_transcript_fixture_replays_current_v1_runtime(fixture):
    await run_transcript_fixture(fixture)
