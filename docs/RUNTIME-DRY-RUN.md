# Runtime Dry-Run 观测 SOP

> 范围：为未来 v1/v2 灰度分流做稳定用户分桶和日志观测。当前版本不切换执行路径。

## 1. 定义

`AGENT_RUNTIME_DRY_RUN_*` 只产生稳定标签：

- `v1` 标签：默认标签。
- `v2` 标签：按 `user_id` hash 命中的 canary 标签。
- `behavior=observability_only`：明确表示不会 dispatch 到另一套 runtime。

这不是生产 runtime 开关。不要把 `label=v2` 解读成用户已经执行 v2 runtime。

## 2. 默认配置

```env
AGENT_RUNTIME_DRY_RUN_TARGET=v1
AGENT_RUNTIME_DRY_RUN_V2_PERCENT=0
```

## 3. Dry-run 分桶节奏

```env
AGENT_RUNTIME_DRY_RUN_TARGET=v2
AGENT_RUNTIME_DRY_RUN_V2_PERCENT=10
```

建议节奏：

| 阶段 | 配置 | 观察 |
|---|---|---|
| 0% | `target=v1`, `v2_percent=0` | 启动日志基线 |
| 10% | `target=v2`, `v2_percent=10` | 验证稳定分桶和日志查询 |
| 50% | `target=v2`, `v2_percent=50` | 评估日志量和 cohort 覆盖 |
| 100% | `target=v2`, `v2_percent=100` | 为后续真实 dispatch PR 做基线 |

## 4. 操作命令

```bash
sudo vim /etc/xd-aigc-agent/.env
sudo systemctl restart xd-aigc-agent
sudo journalctl -u xd-aigc-agent --since '5 min ago' | grep RUNTIME_DRY_RUN
```

启动时应看到：

```text
[RUNTIME_DRY_RUN] target=v2 v2_percent=10 behavior=observability_only
```

用户级 label 日志是 DEBUG 级，默认生产日志只保留启动配置，避免每条消息刷屏。

## 5. 回退

把配置改回默认值并重启：

```env
AGENT_RUNTIME_DRY_RUN_TARGET=v1
AGENT_RUNTIME_DRY_RUN_V2_PERCENT=0
```

不要清 Redis；session 按 TTL 自然消化。

## 6. running_job 风险提示

如果未来真实 runtime dispatch 已接入，回退到 v1 时必须额外注意：

- 正在 `running_job` 的用户可能失去后台 worker 通知。
- 建议手工群播：`系统升级回滚，未完成的生成请重发一遍。`
- 影响窗口是回退时刻正在 poll 的 job，通常 1 小时内自然消化。

当前 dry-run 版本没有真实 runtime dispatch，因此不会触发这类行为差异。

## 7. 后续真实开关要求

后续如果要把 dry-run 升级成真实 runtime dispatch，PR 必须同时提供：

- `runtime_label` 到执行路径的明确分支。
- v1/v2 兼容读写和 rollback 验证。
- `running_job` 回退广播 SOP。
- transcript eval 覆盖 v1/v2 分流路径。
