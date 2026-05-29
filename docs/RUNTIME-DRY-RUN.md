# Runtime Rollout / Dry-Run SOP

> 范围：为当前 v2 conversation runtime 做稳定用户分桶、灰度观察和部署级回滚。

## 1. 定义

`AGENT_RUNTIME_DRY_RUN_*` 只产生稳定 canary 标签：

- `v1` 标签：默认标签。
- `v2` 标签：按 `user_id` hash 命中的 canary 标签。
- `behavior=observability_only`：明确表示不会 dispatch 到另一套 runtime。

当前仓库没有保留一套可用的进程内旧 v1 runtime。线上代码实际执行的是当前
conversation runtime；v1 回滚通过部署上一版镜像/commit 实现，而不是在同一进程里
按用户切换两套执行器。

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
| 100% | `target=v2`, `v2_percent=100` | 为真实 bot smoke test 做基线 |

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

## 5. 100% Smoke Test

当 `target=v2` 且 `v2_percent=100` 后，做一轮真实 bot smoke test：

1. 私聊 bot 发一个完整生图需求。
2. 确认 bot 进入生成并最终 delayed reply 出图。
3. 完成后发送 `谢谢`，应回复继续/调整/换需求边界提示。
4. 完成后发送 `换成横版`，应退出 completed，进入可继续修改状态。
5. 对同一条确认消息制造一次重投递或本地回放，确认不重复 submit：
   - 优先使用 Feishu 事件 replay/webhook replay 工具，重放同一个 `message_id` 的确认事件。
   - 没有 replay 工具时，用本地脚本调用 `_process_locked()`，传入同一 `message_id` 和 `content={"text":"确认"}`。
   - 验证日志应出现 `duplicate_submit`，且 toolbox submit 请求不增加。
6. 生成中发送 `还没好吗`，应恢复/继续等待当前 running job。

观察窗口至少 24h：

```bash
sudo journalctl -u xd-aigc-agent --since '24 hours ago' \
  | grep '\[METRIC\]' \
  | grep -E 'running_job_anomaly|duplicate_submit|delayed_reply_failure'
```

## 6. 回退

常规回退先把标签改回默认值并重启：

```env
AGENT_RUNTIME_DRY_RUN_TARGET=v1
AGENT_RUNTIME_DRY_RUN_V2_PERCENT=0
```

如果需要代码级回滚，部署上一版已知稳定镜像/commit。不要清 Redis；session 按 TTL
自然消化。v2 写入会同步 v1 mirror 字段，所以 completed/collecting 等基础状态可退化
读取；`running_job` 通知能力按 D2 接受丢失。

## 7. running_job 风险提示

代码级回滚到旧 v1 行为时必须额外注意：

- 正在 `running_job` 的用户可能失去后台 worker 通知。
- 建议手工群播：`系统升级回滚，未完成的生成请重发一遍。`
- 影响窗口是回退时刻正在 poll 的 job，通常 1 小时内自然消化。

## 8. 不做进程内 v1/v2 Dispatch 的原因

当前 v1 不是独立可运行的执行器，而是 `ConversationSession` 的降级 mirror 字段。
如果在当前进程里伪造 `label=v1` 分支，会绕过 `active_job`、background worker 和
重复 submit 防线，反而产生更大的行为差异。

因此本阶段不做进程内 v1/v2 双 runtime dispatch。灰度策略是：

- 当前进程始终执行 v2 conversation runtime。
- `AGENT_RUNTIME_DRY_RUN_*` 用于稳定分桶和日志观测。
- 回滚通过部署上一版代码完成。
- v1 兼容性由 `sync_legacy_fields()` 和 session migration tests 保证。
