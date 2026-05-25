# Phase 进度 — XD-AIGC-agent

> 本项目按 Phase 0→3 推进。每个 Phase 完成后更新本文 + vault `log.md`。
> 主决策记录在 `H:\Obsidian-Vault\Johnny-Knowledge-Base\wiki\synthesis\aigc-toolbox-bot-architecture-2026-05.md`

## ✅ 已完成（2026-05-25）

- 决策：七道隔离闸
- 决策：仓库归属（`D:\GIT\XD-AIGC-agent`）+ conda env（`xd-aigc-agent`）
- 决策：用户范围策略（白名单 → 全员两阶段）
- 决策：首期试点工具 `frame-bg-remover`
- 摸清 frame-bg-remover API（详见 ARCHITECTURE.md）
- Johnny 操作：收回 Hermes 飞书 bot 对同事的授权

## 🔄 Phase 0 — 清理 Hermes 残留风险（Johnny 操作）

这两步不做，Hermes 的飞书文档泄露风险持续存在。

- [ ] 飞书开发者后台 → Hermes 当前 App → 撤销除 `im:message` / `im:resource` 之外的所有 scope
  - 重点撤：`docx:*` / `drive:*` / `bitable:*` / `calendar:*` / `mail:*` / `contact:*` / `wiki:*`
- [ ] 删除 Hermes 加载的所有 `lark-*` 非 IM skill（`lark-doc` `lark-drive` `lark-base` `lark-calendar` `lark-mail` `lark-contact` `lark-im` `lark-task` `lark-okr` `lark-attendance` `lark-approval` `lark-vc` `lark-wiki` `lark-minutes`）

## ⏳ Phase 1 — 飞书 App（Johnny 操作）

- [ ] 飞书开发者后台新建 App「XD AIGC Toolbox」
  - **权限管理**：只勾 `im:message` + `im:resource`，**绝不勾任何其他**
  - **事件订阅**：连接方式选「长连接（WebSocket）」
  - **机器人**：启用
  - **可用范围**：先填 Johnny + 1-2 个试点同事
- [ ] 记录 App ID / App Secret（不要贴对话，写本地 `.env`）

## ⏳ Phase 2 — 仓库与环境

- [ ] 按 ARCHITECTURE.md "目录结构" 起骨架
- [ ] `git init` + `.gitignore`（务必包含 `.env` / `__pycache__` / `*.log`）
- [ ] `conda create -n xd-aigc-agent python=3.11`
- [ ] 装依赖：`lark-oapi langgraph pydantic redis httpx python-dotenv`
- [ ] **审查 import**：只 `lark_oapi.api.im`，禁止 `lark_oapi.api.docx/drive/bitable/calendar/contact/mail`

## ⏳ Phase 3 — v0.1 端到端

- [ ] 写 `skills/frame-bg-remover.yaml`
- [ ] 实现 5 核心组件：`feishu/` + `orchestrator/` + `skill/` + `session/` + `http_client/allowlist.py`
- [ ] CI grep 脚本 `ci/check-banned-apis.sh`（禁用 API 命中即 fail）
- [ ] L20_1 创建专用 `toolbox-bot` 服务账号；Dockerfile 加 `USER toolbox-bot`
- [ ] toolbox Gateway 为 bot 单发专属 service token（不复用 Johnny 凭证）
- [ ] 端到端跑通：飞书 → 上传图 → 去白底 → 返图
- [ ] Docker + systemd 部署
- [ ] 试点同事使用 2-3 天，收集反馈

## 新 Session 启动 Checklist

1. 读 `CLAUDE.md`（硬约束）
2. 读 vault 主架构页（路径见 CLAUDE.md "Vault 索引"）
3. 查本文当前 Phase 状态
4. 向 Johnny 确认这次推进哪个 Phase 哪个待办
5. 开干前自检：本次改动是否触碰任何禁用 API / 任何隔离闸？

## 写代码自检（每次 commit 前）

- [ ] 没 import `lark_oapi.api.docx/drive/bitable/calendar/contact/mail`
- [ ] 没调 `message.create` / `chat.create` / `chat_members.*` / `contact.*`
- [ ] 所有 HTTP 出站过白名单拦截器（只放 `localhost:80` + `open.feishu.cn`）
- [ ] LLM 输出走 Pydantic schema（不接自由文本动作）
- [ ] 没引入 Johnny 个人凭证（SSH key / git config / 个人 .env）
- [ ] 新 skill 在 `skills/` 下且符合 YAML 格式
