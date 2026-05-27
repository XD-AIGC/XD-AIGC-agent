# Transcript Fixtures

These fixtures lock down conversational behavior for the Feishu agent harness.
They are not raw production transcripts and must not contain real Feishu IDs,
file IDs, user names, tokens, or signed URLs.

## Fixture Types

- `*_v1.json`: behavior expected to pass on the current v1 orchestrator.
- `*_xfail.json`: known gap captured as a strict pytest xfail. These should
  become passing fixtures when the matching phase lands.

## Schema

Fixtures are loaded through `tests.transcript_runner.TranscriptFixture`.
Unknown fields are rejected so test data cannot silently drift from the runner.

Important fields:

- `id`: stable fixture name, matching the filename stem.
- `initial_session`: optional session state before replay.
- `turns`: user messages plus mocked router, skill, and backend outputs.
- `expect`: required final state and trace assertions.
- `v2_optional`: assertions checked only when the runtime exposes v2 fields.
- `xfail`: reason for a known failing scenario.

## Trace

Trace assertions should prove the orchestration boundary:

- `router_llm_calls`
- `skill_llm_calls`
- `skill_action_calls`
- `skill_action_names`
- `submit_job_calls`
- `submit_payloads`
- `phase_transitions`

Mock `execute_skill_action` and toolbox submit paths in the fixture. The runner
must not call a real toolbox backend.

## Redaction

Run this before committing fixture changes:

```bash
python ci/check-transcript-fixtures.py
```

Use placeholders such as `user_test`, `msg_test_1`, `result_file_key`, and
`https://example.invalid/...` for synthetic identifiers.
