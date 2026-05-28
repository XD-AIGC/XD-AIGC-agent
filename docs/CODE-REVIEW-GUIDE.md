# Code Review Guide — XD-AIGC-agent

> 本项目 PR review 的方法论与 checklist。源于 2026-05 reform 期间 6 个 PR review 的实战沉淀。
> 配套：`SPEC` / `RUNTIME` / `PLAN` / `OPEN-ITEMS`。

## 1. 优先级分级

| 级别 | 定义 | 处理 |
|---|---|---|
| **P0** | correctness bug / SPEC 关键约束违反 / 红线撞线 / 数据丢失 | **阻塞合并** |
| **P1** | 体验/语义反转、性能边缘、测试覆盖关键缺失 | 应修，本 PR 或紧接 follow-up |
| **P2** | 命名、注释、可读性、非紧急 follow-up | 建议，挂 issue |

**判断 P0 的硬标准**：
- 用户实际可见的反向语义（如 PR#9「取消」收到「继续等待」）
- SPEC §X.Y 原文要求未实现且无 disclaim
- 红线条款（reply-only / banned API / 权限白名单）被绕过
- 数据 race / lost update 可重现

## 2. 三层验证

### Layer 1 — 跑测试
```bash
conda run -n xd-aigc-agent pytest -q
bash ci/check-banned-apis.sh
conda run -n xd-aigc-agent python ci/check-transcript-fixtures.py
```

### Layer 2 — 手工重现边缘 case
写 `/tmp/verify_prN.py` 跑反例，**不进 git**。典型场景：
- cancel / timeout / continue_wait / chitchat 在 running_job 下行为
- LLM 凭空写 / 同值更新 / OptionSet 过期 / pending_param 残留
- 飞书事件重投递 / message_id 复用

### Layer 3 — 对照 SPEC 原文
每条 P0/P1 必须引用 `SPEC §X.Y` 或 `RUNTIME §X.Y` 原文。空对空的 review 一律退回。

## 3. 八个验收维度

每个 PR 过这张清单：

| 维度 | 检查点 |
|---|---|
| **功能正确** | PR description 说的事是否真做了 |
| **SPEC 一致** | 哪些验收已达成、哪些 disclaim/defer、哪些与原文不符 |
| **红线合规** | reply-only / banned-apis / 单实例 / 权限白名单 / 不撞 `CLAUDE.md §安全红线` |
| **测试覆盖** | unit + integration + transcript fixture + 边缘 case |
| **Race / lock** | worker 持锁正确性、并发 save、CAS、跨进程 |
| **代码质量** | DRY、命名、错误处理、log 可观察性 |
| **渐进性** | 不破坏向后兼容、不留 dead code、与前序 PR 衔接 |
| **边缘 case** | fallthrough、空输入、并发、超时、status 全枚举 |

## 4. 反馈结构（固定模板）

```markdown
本地验证：
- pytest -q → N passed, M xfailed
- bash ci/check-banned-apis.sh → OK
- python ci/check-transcript-fixtures.py → OK

零回归。无/有 P0 correctness bug，N 个 P1。

## ✅ 做得好的（8-10 项）
（正向反馈：让 implementer 知道哪些设计是对的，避免误改）

## 🔴 P0 必修
（每条引用 SPEC §X.Y + 重现脚本输出）

## 🟡 P1 应修
（每条引用 SPEC + 修复建议）

## 🟢 P2 建议
（可挂 follow-up）

## 红线复查
- ✅/❌ banned-apis
- ✅/❌ 不引入新飞书 API
- ✅/❌ N passed 零回归

## 总结
是否可合 → 下一步该开什么 PR
```

## 5. 关键工具

| 工具 | 用途 |
|---|---|
| `gh pr view N --json title,body,files,additions` | metadata + body |
| `git diff main..HEAD -- <path>` | 全量变更 |
| `pytest -q` + 2 个 CI 脚本 | 跑测试 |
| `/tmp/verify_*.py` | 边缘 case 重现（不进 git） |
| `WebFetch` | 外部 spec 对比（如 deer-flow、Hermes） |
| Read `SPEC` / `RUNTIME` / `PLAN` / `OPEN-ITEMS` | 每条 review 项对照原文 |

## 6. 后续追踪

- approve 后**明示下一步 PR**（如「合并后开 PR-2c」）
- defer 项写明属于哪个 follow-up / issue
- `issue#2` 是 master tracker，每个 S 项状态：✅ / partial / pending

## 7. 隐性 Bias 控制（最关键）

| Bias | 反例 | 规避 |
|---|---|---|
| **只看 happy path** | PR#9 测试全绿，但 cancel 反向语义没暴露 | 必跑 cancel/timeout/race 反例 |
| **依赖测试结果** | 测试 pass ≠ 无 bug；测试可能没覆盖该 case | 手工重现边缘场景 |
| **放过 fallthrough** | PR#11 两个漏洞都是 if/elif 链末尾的 `else accept` | 见 if/elif 链必检查 last branch |
| **空对空** | "这里可能有问题" 不引用原文 | 每条 P0/P1 引用 SPEC §X.Y |
| **不看负面 case** | submit/poll/running 都对，但 cancelled/failed phase 没实现 | enum 全枚举（如 status 所有值都跑一遍） |
| **只看 diff 不看周边** | 改 A 函数没看到 B 函数依赖 A 的输出 | 看完 diff 后 grep 调用方 |

## 8. 实战 PR 经验快查

| PR | 关键学习 |
|---|---|
| PR-0a | 测试 fixture 用 v1/v2 两套字段，pydantic strict schema 防漂移 |
| PR-0b | SPEC §7.2.2「save 与 sync 不可分」要在实现层（SessionStore.save union 签名）落 |
| PR-0c | OptionResolver 在 main.py 集成层有 fallthrough：matched 后必须清 last_options + pending_param |
| PR-2b | `_handle_running_job_turn` 不能不看 intent，否则 cancel 被错应答为「继续等待」 |
| PR-2c | worker 后台 save 必须持 user_lock，否则 lost update |
| PR-3a | filter 末尾 `accepted[key] = new_value` fallthrough = 漏防 |

## 9. 何时不阻塞合并

- PR description 明确 disclaim "first slice" / "partial" / "stays for PR-X" 且不撞红线
- P1/P2 可单独 PR 解决且不放大主路径风险
- 测试覆盖核心场景，边缘 case 可挂 follow-up

## 10. 何时必须阻塞

- 红线撞线（reply-only / banned API / 权限超界）
- 数据丢失 / lost update 可重现
- 用户可见反向语义
- SPEC 关键约束违反且无 disclaim
