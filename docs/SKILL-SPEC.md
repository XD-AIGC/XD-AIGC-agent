# SKILL-SPEC — 给同事的 skill 接入契约

> 受众：维护 SKILL.md 和 toolbox 后端的同事。
> 目的：让 agent harness 能正确加载并对话式调用你的 skill，不用碰我们的 Python 代码。

## 1. 两种 skill 模式

| 模式 | 适用场景 | 同事维护 | agent harness 维护 |
|---|---|---|---|
| **Simple** | 参数少（≤ 3 个），无复杂业务流程，一次性提交出结果 | `skills/<name>.yaml` 单文件 | 按 SkillParam 顺序自动问，收齐 submit |
| **Complex** | 参数多 / 需要 lazy resource / 自定义 brief 流程 | `skills/<name>/SKILL.md` + manifest | LLM 按 SKILL.md 引导对话，manifest 声明 enum 兜底 |

判断标准：**只用 Simple 能搞定就用 Simple**，不必要复杂化。

## 2. Manifest 字段（两种模式共用）

文件路径：`src/skill_manifests/<name>.yaml`（complex）或 `skills/<name>.yaml`（simple inline）

```yaml
name: my-skill                              # 必填，全局唯一，kebab-case
description: 一句话描述 skill 干啥           # 必填，router 选 skill 时给 LLM 看
skill_md_path: skills/my-skill/SKILL.md     # 仅 complex 需要，加载后注入 LLM system prompt
api: <Backend>                              # 必填，见 §4
params: [<SkillParam>, ...]                 # 必填可空，见 §3
output:
  type: image_url | image_binary | text
  display_as: feishu_image | feishu_card | feishu_text
lazy_resources:                             # 可选，complex skill 才用
  lookup_characters: skills/my-skill/references/characters.tsv
  lookup_options: skills/my-skill/references/options.md
```

## 3. SkillParam 详解

```yaml
- name: compositionType                     # API payload 里的字段名（英文）
  type: enum | text | number | image | json # 必填
  required: true | false                    # 默认 true
  values:                                   # type=enum 时必填
    - default
    - center
  prompt_to_user: 排版构图                  # 用户看到的中文提示词
```

**重要**：
- `type: enum` 且 `values` 非空时，**agent 会在 ask_param 时自动追加 📋 可选值列表**给用户看（兜底防 LLM 漏列，详见 §5）
- 字段名要和后端 API JSON payload 完全对应
- 简单 skill 参数顺序就是 ask_param 顺序；复杂 skill 由 LLM 按 SKILL.md 引导

## 4. Backend 两种

### HttpBackend（同步）

```yaml
api:
  type: http
  endpoint_path: /xxx/api/process
  method: POST                              # 默认 POST
  content_type: multipart/form-data         # 或 application/json
```

### PollBackend（异步长任务）

```yaml
api:
  type: poll
  submit_path: /xxx/api/generate
  submit_method: POST
  submit_content_type: application/json
  poll_path_template: /xxx/api/poll/{job_id}
  job_id_field: jobId
  status_field: status
  done_value: completed
  failed_value: failed
  error_field: error
  result_path: images[0].url                # 支持 'a.b[0].c' 嵌套
  poll_interval_sec: 3
  poll_timeout_sec: 300
```

agent 用 PollBackend 时**自动给用户发 "✅ 已开始生成，预计 30-60 秒…" 即时反馈**，无需 SKILL.md 写。

## 5. Enum 兜底（关键）

LLM 经常在问 enum 字段时不列选项（只问"要哪种排版？"用户懵）。agent 端在 `ask_param` 时**强制追加可选值**，但需要你在 manifest 里声明：

```yaml
params:
  - name: compositionType
    type: enum
    required: true
    values: [default, center, diagonal]
    prompt_to_user: 排版构图
```

效果：LLM 输出 `ask_param param_name=compositionType` 时，用户实际看到：
```
选择构图

📋 排版构图 可选值（回复其中一个）：
- default
- center
- diagonal
```

**最佳实践**：所有 enum 字段都在 manifest 声明 `values` —— manifest 是给 agent 代码看的，SKILL.md 是给 LLM 看的，**两边都要**。

## 6. SKILL.md 写作建议（complex skill）

SKILL.md 整段注入 LLM system prompt，控制 LLM 的对话节奏。

**推荐结构**：
1. 顶部 frontmatter：`name` + `description`
2. **参数 Schema 表**（强烈推荐 — LLM 对表格格式天然敏感）：

```markdown
## 参数 Schema

| 字段 | 类型 | 必填 | 可选值 | 必列选项? |
|------|------|------|--------|----------|
| characters | enum | 是 | 见 references/characters.tsv | 用户没指定时 |
| compositionType | enum | 是 | default/center/... | **必列** |
| ratio | enum | 否 | 2:3/1:1/...（默认 2:3） | 可不列 |
```

3. 对话流（Step 0 brief 收集，Step 1 调 toolbox 等）
4. payload 映射规则（哪个字段映射到 API JSON 的哪个 key）
5. lazy_resources 引用（什么时机用 `lookup_characters` action）

**避免**：
- 散文式描述 enum（LLM 不易抓"哪些是 enum"）
- 一次性 brief 卡问 10+ 字段（用户压力大，建议分阶段）
- 不写 good/bad case（LLM 对例子比对规则敏感得多）

## 7. Lazy Resources

大文件（角色清单 TSV、选项说明 MD）**不要塞 SKILL.md**，会撑爆 context。

```yaml
# manifest
lazy_resources:
  lookup_characters: skills/my-skill/references/characters.tsv
  lookup_options: skills/my-skill/references/options.md
```

```markdown
<!-- SKILL.md 提示 LLM 何时 lazy load -->
当用户问"有哪些角色" → 输出 action=`lookup_characters`（agent 自动加载并回喂你）
当用户问"有哪些排版" → 输出 action=`lookup_options`
```

agent 第一次看到这些 action 会读文件 + 重新调 LLM；同一对话内不会重复加载。

## 8. Agent 内置增值能力

下列行为 agent 端**自动提供**，不需要 SKILL.md 写：

| 能力 | 触发条件 | 行为 |
|------|----------|------|
| **Per-user 串行化** | 同 user 多条消息 | 排队不并发，submit 阻塞期间新消息等候 |
| **即时反馈** | submit/retry + PollBackend | 立即 reply "✅ 已开始生成…" |
| **Retry 快路径** | 用户说"再来一张/再生成"等 | 不进 LLM，直接重 execute（省 LLM 调用）|
| **Enum 选项兜底** | ask_param + enum 字段 | 自动追加 📋 可选值列表 |
| **Step1 cache 复用** | PollBackend 含 `intermediateImages.characterActionFileId` | 同 user 同 characters+actionDesc 自动复用，跳过 step1 省 30-60s |
| **session.completed 引导** | submit 成功后 | LLM 看到 completed=True 时按 adjust/new_task/retry 路径处理 |

## 9. 完整示例

### Simple：frame-bg-remover
参考 `skills/frame-bg-remover.yaml`：单 yaml，2 个 param（image + format），HttpBackend。

### Complex：xd-poster-gen
参考 `src/skill_manifests/xd-poster-gen.yaml` + `skills/xd-poster-gen-skill/SKILL.md`：
manifest 含 PollBackend + 3 个 enum params（compositionType/ratio/resolution，agent 兜底用）；SKILL.md 详细描述 brief 收集流程 + payload 映射。

## 10. CI 与约束

- **HTTP 出站白名单**：backend URL 必须在 `TOOLBOX_BASE_URL` 之下（详见 `src/http_client/allowlist.py`）
- **禁用飞书 API**：SKILL.md 和后端**禁止**调 `lark` 的 docs/drive/base/calendar/mail/wiki/contact 任何接口
- **CI 检查**：`bash ci/check-banned-apis.sh` 必须通过（命中即 fail）

## 11. 接入流程

1. 写 manifest（参考 §2/§3/§4）
2. 复杂 skill 写 SKILL.md（参考 §6）
3. 本地起 bot（`python -m src.main`）冒烟测
4. 对话验证：触发词 → brief 收集 → submit → 出图
5. 若 LLM 行为不对，先看 `bot.log` 的 `[ACT mode=skill] ... updated_params=...`；决定改 SKILL.md prompt 还是反馈给 agent 侧
