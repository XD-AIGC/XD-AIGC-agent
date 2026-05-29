# Runtime Monitoring SOP

> Scope: log-based metrics for P4 rollout checks. No external metrics stack is required for the first internal rollout.

## 1. Metric Format

Runtime counters are emitted as structured log lines:

```text
[METRIC] name=<metric_name> key=value key=value
```

Values are single-token strings so they can be counted with `grep`, `awk`, or log aggregation later.

## 2. Metrics

| Metric | Meaning | Important fields |
|---|---|---|
| `duplicate_submit` | A submit was suppressed because the same request already has an active/completed job | `skill_name`, `action_name`, `job_status`, `user_key` |
| `delayed_reply_failure` | Background worker could not send a delayed result/follow-up reply | `stage`, `skill_name`, `job_status`, `result_kind`, `reply_channel`, `user_key` |
| `running_job_anomaly` | `phase=running_job` state was inconsistent with the expected active job | `stage`, `reason`, `skill_name`, `job_status`, `user_key` |

## 3. Sample Logs

```text
[METRIC] name=duplicate_submit action_name=submit job_status=running skill_name=xd-poster-gen user_key=u_c6c289e49e9c
[METRIC] name=delayed_reply_failure job_status=running reply_channel=image result_kind=binary skill_name=xd-poster-gen stage=send_result user_key=u_c6c289e49e9c
[METRIC] name=running_job_anomaly job_status=running reason=active_job_mismatch skill_name=xd-poster-gen stage=complete user_key=u_c6c289e49e9c
```

`reply_channel` marks the Feishu IM reply API that failed (`text` or `image`).
It does not cover toolbox download or image upload exceptions; those are tracked
as `running_job_anomaly`.

`user_key` is a stable hash prefix for attribution; raw Feishu user IDs are not
logged. Treat it as internal operational data: do not publish it externally or
copy it into transcript fixtures.

## 4. Quick Checks

```bash
sudo journalctl -u xd-aigc-agent --since '24 hours ago' | grep '\[METRIC\]'
```

Duplicate submit count:

```bash
sudo journalctl -u xd-aigc-agent --since '24 hours ago' \
  | grep '\[METRIC\] name=duplicate_submit' \
  | wc -l
```

Delayed reply failures:

```bash
sudo journalctl -u xd-aigc-agent --since '24 hours ago' \
  | grep '\[METRIC\] name=delayed_reply_failure'
```

Running job anomalies:

```bash
sudo journalctl -u xd-aigc-agent --since '24 hours ago' \
  | grep '\[METRIC\] name=running_job_anomaly'
```

## 5. Rollout Gate

For the first internal rollout:

- `delayed_reply_failure` must stay at `0`.
- `running_job_anomaly` should stay at `0`; any non-zero line needs inspection.
- `duplicate_submit` can be non-zero, but should be checked against user retry/repost behavior.

If delayed reply failures exceed 1% of completed background jobs, stop rollout and fall back to the timeout/user-triggered recovery flow.
