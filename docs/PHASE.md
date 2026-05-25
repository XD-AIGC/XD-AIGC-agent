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
- [ ] **A6**：完整 Memory（cachedStep1FileId 持久化复用 step1）— 半成品（session 保留已做，cachedStep1 提取未做）
- [ ] **A7**：测试 + 文档收尾

**Commit 历史**：`5efe66b → 0e49b2b → 1abb093 → 1eb5cdd → 7c2760c → f8a05e0 → 80a6720 → 61b2519 → 62dcf28 → 745a592`（共 10 个）

## ⏳ Phase 5 — 生产部署（下次推进）

- [ ] L20_1 创建专用 `toolbox-bot` 服务账号；Dockerfile 加 `USER toolbox-bot`
- [ ] toolbox Gateway 为 bot 单发专属 service token
- [ ] `.env` 生产值（TOOLBOX_BASE_URL=`http://localhost:80`，部署在 L20-1 就不需要 SSH 隧道）
- [ ] Docker + systemd 部署
- [ ] 飞书可用范围扩到全员
- [ ] 试点同事使用 2-3 天，收集反馈

## ⏳ Phase 6 — 扩展（按需）

- [ ] A6 完整版：从 poll 结果提 `intermediateImages.characterActionFileId` 存 Redis，下次同角色同动作自动复用 cachedStep1FileId（省 30-60s）
- [ ] ArtDAM 集成：OBO token exchange 端点（设计已在 vault `bot-obo-via-shared-sso`）
- [ ] `docs/SKILL-SPEC.md`：给同事的 skill 接口契约文档
- [ ] 更多 skill 接入（看同事产 SKILL.md 的进度）

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
