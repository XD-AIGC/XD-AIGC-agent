# XD-AIGC-agent — 项目宪法

> 新 session 启动后第一权威源。读完本文 → 看 `docs/PHASE.md` 当前进度 → 看 vault 主架构页 = 完整上下文。

## 项目使命

把 [XD-AIGC-toolbox](D:\GIT\XD-AIGC-toolbox)（28 个 web 工具）包装成**飞书机器人对话式入口**，给公司同事用。

| 项 | 值 |
|---|---|
| 飞书 App | XD AIGC Toolbox（待建） |
| 部署 | L20_1（10.102.80.15）Docker，与 `xd-gateway` 并列 |
| 开发位置 | `D:\GIT\XD-AIGC-agent` |
| Conda env | `xd-aigc-agent`（Python 3.11，独立） |
| 首期试点工具 | `frame-bg-remover` |
| **使用范围（锁定）** | **仅公司内部，绝不对外**（2026-05-26 Johnny 明确） |

### 「仅内部」推论（基于此约束的下游决策）

| 项 | 决策 |
|---|---|
| 内容审核 | **完全不接 SaaS**（NudeNet + AnimeNSFW + Freepik + ModelScope cnstd + Qwen2.5-VL 纯本地，¥0/月） |
| GB 45438 标识 | 内部理论可豁免，但 `c2pa-python` 打 trace 留底 |
| 飞书 App 可用范围 | 公司全员 / 指定部门，**不开"对外共享"** |
| 触发"重审整个策略"的事件 | 任何对外服务、外部合作方接入、用户规模超出公司编制 |

**重要**：若有 PM/老板/客户提出"让外部某某也用一下" → **必须立刻停下，重新评估整套合规与隔离方案**，不能临时开口子。

---

## ⚠️ 安全红线（不可妥协）

Hermes 因缺这些约束，被发现授权同事后能访问 Johnny 整台机器。**违反以下任一条款的改动必须立即停止并报告。**

### 🔒 七道隔离闸

| # | 闸 | 硬约束 |
|---|---|--------|
| 1 | 飞书 App scope | 只勾下面 6 个细粒度权限；禁勾 docs/drive/base/calendar/mail/wiki/contact（详细清单见下方 §「权限清单」） |
| 2 | OAuth | 不实现 `user_access_token` 流程；bot 永远 tenant 身份 |
| 3 | Skill 白名单 | 只加载 `./skills/` 下的 toolbox skill；禁加任何 `lark-*` skill |
| 4 | 出站 HTTP 白名单 | 只允许 `${TOOLBOX_BASE_URL}/*` + `open.feishu.cn/*` + `llm-proxy.tapsvc.com/*` |
| 5 | 代码层禁 import | 禁 import `lark_oapi.api.docx/drive/bitable/calendar/contact/mail` |
| 6 | Bot reply-only | 只调 `message.reply`；禁 `message.create` / `chat.create` / `chat_members.*` / `contact.*` |
| 7 | OS 凭证隔离 | 专用 `toolbox-bot` 服务账号；不挂 `~/.ssh`、`~/.gitconfig`、Johnny 的 `.env`；调 toolbox 用专属 service token |

### 权限清单（必须，且只勾这些）

**⚠️ 历史教训**：旧版宪法写「只勾 `im:message` + `im:resource`」是错的——`im:message` 是粗粒度 umbrella，**不触发** `im.message.receive_v1` 事件投递。详见 vault `wiki/concepts/feishu-event-permission-gate`。

```
im:message.p2p_msg:readonly        # 必须，收 P2P 消息事件
im:message.group_at_msg:readonly   # 群里 @bot 时收事件
im:message:send_as_bot             # 作为 bot 发消息
im:resource                        # 上传/下载图片
im:chat:readonly                   # 读会话信息（事件投递可能依赖）
contact:user.id:readonly           # 读用户标识（事件 payload 含 open_id）
```

**禁勾**：`im:message` (umbrella), docs/drive/base/calendar/mail/wiki/contact 的任何权限。

### 飞书 API 禁用清单（CI grep，命中即 fail）

以下字符串不允许出现在 `src/` 任何文件：

```
message.create  message.create_urgent  chat.create  chat_members
contact.  docx.  drive.  bitable.  calendar.  mail.  wiki.
```

### 写代码自检（每次 commit 前）

- [ ] 没 import `lark_oapi.api.docx/drive/bitable/calendar/contact/mail`
- [ ] 没调 `message.create` / `chat.create` / `chat_members.*` / `contact.*`
- [ ] 所有 HTTP 出站过白名单拦截器
- [ ] LLM 输出走 Pydantic schema（不接自由文本动作）
- [ ] 没引入 Johnny 个人凭证
- [ ] 新 skill 在 `skills/` 下且符合 YAML 格式

---

## 文档索引

### 本仓库 docs/

| 文件 | 内容 |
|------|------|
| `docs/ARCHITECTURE.md` | 架构图 / 技术栈 / LLM schema / Skill 系统 / frame-bg-remover API / 目录结构 |
| `docs/PHASE.md` | Phase 0-3 详细进度 / 新 session 启动 checklist / 写代码自检（完整版） |
| `docs/SKILL-SPEC.md` | 给同事的 skill 接入契约：manifest / SkillParam / Backend / enum 兜底 / SKILL.md 写作规范 |
| `docs/DEPLOY.md` | L20_1 生产部署手册：Dockerfile / systemd / .env.prod / 健康检查 / 升级回滚 / 故障排查 |
| `docs/L20-1-SERVICES.md` | L20-1 服务端口清单：toolbox 子工具端口表 / 基础设施 / 写 manifest 时怎么填 base_url |
| `docs/CODE-REVIEW-GUIDE.md` | PR review 方法论：P0/P1/P2 分级 / 三层验证 / 8 维度 / bias 控制 / 实战快查 |

### 关联仓库

| 仓库 | 作用 |
|------|------|
| **[XD-AIGC-skills](https://github.com/XD-AIGC/XD-AIGC-skills)** (PRIVATE) | 同事维护的 skill 库；agent 通过 SKILLS_DIR 加载，cron 5min 自动 pull，watcher hot-reload 不重启 bot |

### Vault（推理过程 / 决策依据 / 对话历史）

| 路径 | 何时读 |
|------|--------|
| `H:\Obsidian-Vault\Johnny-Knowledge-Base\wiki\synthesis\aigc-toolbox-bot-architecture-2026-05.md` | 开工前必读（主架构决策） |
| `H:\Obsidian-Vault\Johnny-Knowledge-Base\wiki\sources\hermes-agent-nousresearch.md` | 涉及"为什么不用 Hermes" |
| `H:\Obsidian-Vault\Johnny-Knowledge-Base\raw\chats\2026-05-25-aigc-bot-hermes-suitability.md` | 回溯决策依据 |
| `D:\GIT\XD-AIGC-toolbox\CLAUDE.md` | 涉及 toolbox 集成（服务器路径 / Conda / Gateway） |

Vault 索引：`H:\Obsidian-Vault\Johnny-Knowledge-Base\index.md`；事件日志：`log.md`。

## 新 Session 启动顺序

1. 读本文件 ✓
2. 读 `docs/PHASE.md` 看当前 Phase 状态
3. 读 vault 主架构页（上表第 1 行）
4. 向 Johnny 确认这次推进哪个 Phase 哪个待办

## 警告

- 不要参考 Hermes 实现（prosumer 哲学，与本项目相反）
- 不要为"agent 更智能"放松约束（LLM 越自由 = 攻击面越大）
- 任何"临时打开"的口子（CI 检查 / import / 白名单）必须在合并前关掉
- 文档分层原则：**任何单 markdown 文件 ≤ 200 行**，超了分到 `docs/`
