# Phase 进度 — XD-AIGC-agent

> 本项目按 Phase 0→6 推进。每个 Phase 完成后更新本文 + vault `log.md`。
> 主决策记录在 `H:\Obsidian-Vault\Johnny-Knowledge-Base\wiki\synthesis\aigc-toolbox-bot-architecture-2026-05.md`

## ✅ Phase 0-3 全部完成（2026-05-25）

Phase 0：清理 Hermes 残留 ✅
Phase 1：飞书 App「AIGC bot」(`cli_aa99420199f9dbd8`) 已建 + 0.1.4 发布 ✅
Phase 2：仓库骨架 + conda env + 21 测试全绿 ✅
Phase 3：v0.1 端到端跑通（frame-bg-remover 真后端） ✅

## ✅ Phase 4 — 架构升级支持复杂 skill（2026-05-25 夜）

参考 Anthropic 「Building Effective Agents」+「Effective Context Engineering」两篇文章
重构架构，从「单 skill workflow」升级为「multi-skill harness with context engineering」。

- [x] **A1**：Skill loader 双格式（YAML 简单 / manifest+SKILL.md 复杂）
- [x] **A2**：SkillBackend 抽象（HTTP 同步 / Poll 异步两种）
- [x] **A3**：Router/Skill 双模式 + 8-action enum + lazy load
- [x] **A4**：URL 类型结果下载（阿里云 OSS）+ 上传飞书
- [x] **A5**：接入 xd-poster-gen 复杂 skill（SKILL.md 6790 字符 + 41 角色 TSV）
- [x] **A5 实战修复**：submit 保留 session + initial_intent 防失忆 + hallucination 防御 + reply 长度保护
- [x] **A6**：完整 Memory（cachedStep1FileId 持久化复用 step1）— `Step1Cache` Redis 24h TTL，每 user 独立，命中省 30-60s
- [x] **A7-docs**：`docs/SKILL-SPEC.md` 给同事的 skill 接入契约
- [x] **A7-e2e**：`tests/test_e2e.py` 6 个场景 mock 飞书+LLM+toolbox（happy path / retry / enum 兜底 / LLM 失败 / submit 失败 / 串行化）

**Commit 历史**：`5efe66b → 0e49b2b → 1abb093 → 1eb5cdd → 7c2760c → f8a05e0 → 80a6720 → 61b2519 → 62dcf28 → 745a592 → df943fa`（共 11 个，2026-05-26 收工版）

### 2026-05-26 凌晨追加（A5 实战修复 + A6 + A7-docs）

A5 实战测试发现并修复：
- **Per-user lock**：同 user 消息串行化，submit 阻塞期间新消息排队
- **session.completed + retry 快路径**：submit 后 completed=True，"再来一张"等短语不进 LLM 直接重 execute
- **submit 即时反馈**："✅ 已开始生成…"
- **collected_params > initial_intent 优先级 prompt + 用户纠错处理**
- **Enum 兜底**：ask_param 时自动追加 📋 可选值列表
- **Prompts 抽离**到 `src/orchestrator/prompts/*.md`
- **A6 Step1 cache**：跳过 step1，每 user 独立，Redis 24h TTL

**A5 残留**：用户"放权"时 LLM 仍跳过 enum 字段直接 submit —— 见 [issue #1](https://github.com/XD-AIGC/XD-AIGC-agent/issues/1)（待同事改 SKILL.md "自由发挥"语义）

## 🚀 Phase 5 — 生产部署（基本完成，2026-05-26 上午）

本地产物：
- [x] **Dockerfile** + `.dockerignore` — python:3.11-slim，user uid 1100，HEALTHCHECK 内置
- [x] **deploy/xd-aigc-agent.service** — systemd unit
- [x] **scripts/healthcheck.py** — Redis/LLM/toolbox 三路 ping
- [x] **.env.example.prod** — 生产配置模板
- [x] **docs/DEPLOY.md** — 部署手册

L20_1 真部署：
- [x] 起 `xd-aigc-agent-redis` 容器（host network，独立 redis）
- [x] 创建 toolbox-bot 服务账号（uid 1100）
- [x] 部署 `.env` 到 `/etc/xd-aigc-agent/.env`（600 root）
- [x] git clone 代码到 `/AIGC_Group/XD-AIGC-agent/`（git pull 工作流）
- [x] 装 systemd + healthcheck 通过 + bot active healthy
- [x] 飞书后台扩可用范围（Johnny 操作）
- [x] D-1~D-6 改动已上线（chat history + friendly error + log param_name）

延后/待办：
- [ ] LLM proxy 维护者给 bot 单发 service token（暂用 Johnny key，user 同意）
- [ ] 试点同事使用 2-3 天，收集反馈

## ⏳ Phase 6 — 扩展（按需）

- [x] ~~A6 完整版~~（已在 Phase 4 完成，见 A6）
- [x] ~~`docs/SKILL-SPEC.md`~~（已在 A7-docs 完成）
- [ ] **issue #1 同事改 SKILL.md** schema 表 + "自由发挥"语义重定义 → 验证完整 enum 兜底 / LLM 纠错行为
- [ ] **群聊 D-6 chat history 真实验证**（用户测「列方案 ABC → 我选 C」是否能识别）
- [ ] ArtDAM 集成：OBO token exchange 端点（设计已在 vault `bot-obo-via-shared-sso`）
- [ ] 更多 skill 接入（看同事产 SKILL.md 的进度）

## ✅ 2026-05-26 上午完整工作清单

D 系列（D-1~D-6）+ C（A7-e2e）+ Phase 5 真部署 + git workflow。**7 个 commit，64 → 79 测试**。

| # | 项 | commit | 状态 |
|---|---|---|---|
| D-1 | log 加 param_name | 859ffbc | ✅ |
| D-2 | LLM 调用错误兜底 | 859ffbc | ✅ |
| D-3 | toolbox 错误友好提示 + submit 失败保留 session | 2e05edf | ✅ |
| D-4 | 未注册角色 prompt 强化（good/bad case）| 2e05edf | ✅ |
| D-5 | 群聊 @bot 体验测试 | （飞书测试）| ✅ 无群聊特有 bug |
| D-6 | LLM chat history（多轮上下文）| e5e8022 | ✅ |
| C | A7-e2e 测试套（6 场景）| 2e05edf | ✅ |
| Phase 5 真部署 | git workflow + docker + systemd | f6eed3d, 77c7343 | ✅ healthy |

**累计 commit**：`859ffbc` `77c7343` `f6eed3d` `2e05edf` `f58b5ea` `e5e8022` + Phase 5 部署的

## 新 Session 启动 Checklist

1. 读 `CLAUDE.md`（硬约束 / 权限清单 / harness vs agent）
2. 读本文（Phase 状态）
3. 看 vault `feishu-event-permission-gate` 和 `bot-obo-via-shared-sso`（关键 insight）
4. 看 `docs/ARCHITECTURE.md`（技术栈和目录结构）
5. 向 Johnny 确认推进方向

## 当前环境状态（2026-05-26 00:10 收工时）

- Bot 进程：**已停**
- SSH 隧道：`autossh -fNT -L 8080:localhost:80 ubuntu@10.102.80.15` 应该还在跑（pgrep 验证）
- Redis：本地 `/tmp/redis-aigc.pid`
- mock_toolbox：已删（A5 后用真 toolbox via 隧道）
- 飞书 App 当前可用范围：Johnny + 几个测试同事（部分成员模式）

## 启动 bot

```bash
cd /mnt/d/GIT/XD-AIGC-agent
# 确认 SSH 隧道
curl -s -o /dev/null -w "%{http_code}\n" -X POST http://localhost:8080/api/shared/frame-bg-remover/process
# 如果不通：
ssh -fNT -L 8080:localhost:80 ubuntu@10.102.80.15

# 启动 bot
nohup /home/johnnyzxt/miniconda3/envs/xd-aigc-agent/bin/python -m src.main > bot.log 2>&1 &
```

## 写代码自检（每次 commit 前）

- [ ] 没 import `lark_oapi.api.docx/drive/bitable/calendar/contact/mail`
- [ ] 没调 `message.create` / `chat.create` / `chat_members.*` / `contact.*`
- [ ] 所有 HTTP 出站过白名单（toolbox + open.feishu.cn + llm-proxy.tapsvc.com）
- [ ] LLM 输出走 Pydantic schema（BotAction enum 8 个）
- [ ] 新 skill 在 `skills/` 下（YAML）或 `src/skill_manifests/` 下（manifest 指向 SKILL.md）
- [ ] CI `bash ci/check-banned-apis.sh` 必须通过
