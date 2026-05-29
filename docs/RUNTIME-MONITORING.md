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
| `duplicate_submit` | A submit was suppressed because the same request already has an active/completed job | `skill_name`, `action_name`, `job_status` |
| `delayed_reply_failure` | Background worker could not send a delayed result/follow-up reply | `stage`, `skill_name`, `job_status`, `result_kind` |
| `running_job_anomaly` | `phase=running_job` state was inconsistent with the expected active job | `stage`, `reason`, `skill_name`, `job_status` |

## 3. Quick Checks

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

## 4. Rollout Gate

For the first internal rollout:

- `delayed_reply_failure` must stay at `0`.
- `running_job_anomaly` should stay at `0`; any non-zero line needs inspection.
- `duplicate_submit` can be non-zero, but should be checked against user retry/repost behavior.

If delayed reply failures exceed 1% of completed background jobs, stop rollout and fall back to the timeout/user-triggered recovery flow.
