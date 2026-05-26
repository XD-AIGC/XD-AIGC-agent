# SKILL-SPEC — 给同事的 skill 接入契约

> 受众：维护 SKILL.md 和 toolbox 后端的同事。
> 目的：让 agent harness（飞书 bot）能正确加载并对话式调用你的 skill，不用碰我们的 Python 代码。

## 0. 仓库 + 工作流（新）

所有 skill 维护在独立仓库 **[XD-AIGC/XD-AIGC-skills](https://github.com/XD-AIGC/XD-AIGC-skills)**（PRIVATE）。

**工作流**：
```
同事 git push XD-AIGC-skills
    ↓ 服务器 cron 每 5 分钟自动 git pull
    ↓ agent 文件 watcher 检测变化（debounce 2s）
    ↓ 自动 reload skill registry，对话不中断
    ↓ 同事下次发飞书消息就能看到新 skill 生效
```

**全程不用找 Johnny / 不用重启 bot / 不用 docker rebuild**。

## 1. 目录结构

```
XD-AIGC-skills/
├── heartopia/                ← 业务线分组（你随意命名）
│   ├── xd-poster-studio-v2/
│   │   ├── manifest.yaml     ← 必有，agent 加载凭这个
│   │   ├── SKILL.md          ← 可选，complex skill 用
│   │   ├── references/       ← 可选，lazy_resources 引用
│   │   └── assets/           ← 可选，agent 不读
│   └── xd-town-studio/
│       └── ...
├── ro/                       ← 另一个业务线
└── taptap/                   ← 任意层数都支持
```

Agent 用 `rglob("manifest.yaml")` **递归扫描**所有层级，找到就加载。

## 2. Manifest 字段

```yaml
name: my-skill                  # 必填，全局唯一，kebab-case
description: 一句话描述           # 必填，router 选 skill 时给 LLM 看
skill_md_path: SKILL.md         # 可选，相对 manifest 同目录
api: <Backend>                  # 必填，见 §4
params: [<SkillParam>, ...]     # 可空，见 §3
output:
  type: image_url | image_binary | text
  display_as: feishu_image | feishu_card | feishu_text
lazy_resources:                 # 可选，路径相对 manifest 同目录
  lookup_characters: references/characters.tsv
  lookup_options: references/options.md
```

**所有路径相对 manifest 所在目录**（agent 自动解析为绝对路径）。

## 3. SkillParam

```yaml
- name: compositionType                   # API payload 字段名（英文）
  type: enum | text | number | image | json
  required: true | false                  # 默认 true
  values: [default, center, diagonal]     # type=enum 时必填
  prompt_to_user: 排版构图                  # 用户看到的中文提示
```

**重要**：`type: enum` + `values` 非空时，agent 在 `ask_param` 时**自动追加 📋 可选值列表**给用户看（兜底防 LLM 漏列）。

## 4. Backend 两种

### HttpBackend（同步）
```yaml
api:
  type: http
  endpoint_path: /xxx/api/process
  method: POST                            # 默认 POST
  content_type: multipart/form-data       # 或 application/json
```

### PollBackend（异步长任务）
```yaml
api:
  type: poll
  submit_path: /xxx/api/generate
  poll_path_template: /xxx/api/poll/{job_id}
  job_id_field: jobId
  status_field: status
  done_value: completed
  failed_value: failed
  result_path: images[0].url              # 支持 'a.b[0].c' 嵌套
  poll_interval_sec: 3
  poll_timeout_sec: 300
```

PollBackend 时 agent 自动发**"✅ 已开始生成，预计 30-60 秒…"** 即时反馈。

## 5. SKILL.md 写作建议（complex skill）

整段注入 LLM system prompt。**强烈推荐结构**：

1. 顶部 frontmatter `name` + `description`
2. **参数 Schema 表**（表格格式 LLM 更易遵守）：

```markdown
## 参数 Schema

| 字段 | 类型 | 必填 | 可选值 | 必列选项? |
|------|------|------|--------|----------|
| characters | enum | 是 | 见 references/characters.tsv | 用户没指定时 |
| compositionType | enum | 是 | default/center/... | **必列** |
```

3. 对话流（brief 收集 → 调 toolbox）
4. payload 映射规则（字段 → API JSON）
5. lazy_resources 引用时机

**避免**：散文式描述 enum / 一次性 brief 卡问 10+ 字段 / 不写 good/bad case。

## 6. Lazy Resources

大文件不要塞 SKILL.md，会撑爆 LLM context：

```yaml
lazy_resources:
  lookup_characters: references/characters.tsv
  lookup_options: references/options.md
```

LLM 需要时输出 action=`lookup_characters` → agent 自动读文件回喂 LLM。同一对话内不重复加载。

## 7. Agent 内置增值能力（无需 SKILL.md 写）

| 能力 | 触发 | 行为 |
|------|------|------|
| Per-user 串行化 | 同 user 多消息 | 排队不并发 |
| 即时反馈 | submit + PollBackend | "✅ 已开始生成…" |
| Retry 快路径 | 用户说"再来一张" | 不进 LLM 直接重 execute |
| Enum 选项兜底 | ask_param + enum 字段 | 自动追加 📋 可选值 |
| Step1 cache 复用 | poll response 含 `intermediateImages.characterActionFileId` | 同 user 同 characters+actionDesc 自动复用 |
| chat history | 多轮对话 | 自动传最近 10 条给 LLM 看 |
| session.completed 引导 | submit 成功后 | LLM 按 adjust/new_task/retry 处理 |

## 8. 完整示例

参考 `XD-AIGC-skills/heartopia/xd-poster-studio-v2/` 目录。

## 9. CI 与约束

- **HTTP 出站白名单**：backend URL 必须在 `TOOLBOX_BASE_URL` 之下（详见 agent `src/http_client/allowlist.py`）
- **禁用飞书 API**：SKILL.md 和后端禁止调 `lark` 的 docs/drive/base/calendar/mail/wiki/contact
- **敏感信息**：SKILL.md / manifest **不要写真域名**（如 `xxx.xindong.com`），用占位符 `${XXX_BASE_URL}`，由 agent 侧 `.env` 配
- **CI 检查**：agent 仓库 `bash ci/check-banned-apis.sh` 必须通过

## 10. 接入流程

1. 在 `XD-AIGC-skills/<your-project>/<skill-name>/` 下写 manifest.yaml（参考 §2/§3/§4）
2. 复杂 skill 写 SKILL.md（参考 §5）
3. `git push` → 5 分钟内生产 bot 自动生效
4. 飞书测试：触发词 → brief 收集 → submit → 出图
5. 若 LLM 行为不对，让 Johnny 看 `bot.log` 的 `[ACT mode=skill] ... updated_params=...`；决定改 SKILL.md prompt 还是反馈给 agent 侧
