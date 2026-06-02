# Architecture — XD-AIGC-agent

> 本项目的架构、技术栈、Skill 系统、目录结构。
> 推理过程/为什么不用 X 选 Y → `H:\Obsidian-Vault\Johnny-Knowledge-Base\wiki\synthesis\aigc-toolbox-bot-architecture-2026-05.md`

## 架构图

```
飞书 (WebSocket, 无需公网 IP)
  ↓
toolbox-bot (Docker, L20_1)
  消息层 [lark-oapi WS / Redis 去重 / per-user 锁] (仅 reply)
  控制层 [Skill Registry → LLM (BotAction) → Skill Executor / Mivo MCP]
  状态层 [Redis per user_id session]
  ↓ HTTP only (白名单拦截器)
Nginx Gateway (L20_1:80) → 28 工具 API → L20_0 GPU
Mivo Hub (`MIVO_ENDPOINT`) ← 受控全局 `call_mivo_mcp`
```

预估代码量 < 600 行（不含 skill 定义）。

## 技术栈

| 组件 | 选型 |
|------|------|
| 语言 | Python 3.11 (conda env `xd-aigc-agent`) |
| Agent | LangGraph + Redis checkpointer |
| LLM | LiteLLM Proxy (`llm-proxy.tapsvc.com`) |
| Schema | Pydantic |
| Session | Redis (AOF) |
| 飞书 SDK | lark-oapi (Python, WebSocket, **仅 IM 模块**) |
| HTTP | httpx + 白名单拦截器 |
| 部署 | Docker + systemd |

## LLM 输出 Schema（硬约束）

LLM 不允许自由文本动作。所有输出走 Pydantic：

```python
class BotAction(BaseModel):
    action: Literal[
        "select_skill", "lookup_characters", "lookup_options",
        "call_skill_action", "call_mivo_mcp", "ask_param",
        "await_confirmation", "submit", "exit_skill", "reply", "out_of_scope",
    ]
    skill_name: Optional[str] = None
    param_name: Optional[str] = None
    param_value: Optional[str] = None
    message: Optional[str] = None
```

Skill 范围外 → 强制 `out_of_scope` → 固定回复"我只能帮你做：..."

## Mivo MCP 全局能力

Mivo 不作为某个 toolbox skill 的后端，而是 agent 全局窄工具：Router/Skill 均可输出
`call_mivo_mcp`，但只能调用 `MIVO_MCP_ALLOWED_TOOLS` 白名单内的工具。

当前按 `mivo-mcp-0.6.0` 注册入口对齐的工具：

| 工具 | 能力 |
|---|---|
| `submit_gen_image` / `poll_result` / `download_file` | 生图、轮询、下载图片 |
| `segment_image` / `super_resolution_image` | 抠图、超分 |
| `submit_gen_3d_model` / `poll_3d_result` | 图生/文生 3D、轮询模型文件 |
| `convert_3d_model_format` | GLB/OBJ/FBX 转换 |
| `list_tools` | 返回工具目录、schema、飞书图片映射 |
| `generate_image` | agent 宏：submit + poll + download |

飞书消息里的图片不直接传给 Mivo。agent 使用 `download_image` 取回飞书图片，再上传到
Mivo `/api/v1/file/`，把 `feishu://image/current` 替换成 Mivo fileId 后写入
`image` / `images` / `referenceImages` 参数。

## Skill 系统

Skill 是**声明式执行规格**（不是给 LLM 读的提示文档）。Executor 严格按字段执行，LLM 只负责理解意图 + 选 skill + 收参数。

### Skill YAML 格式

```yaml
---
name: <skill-id>
description: <一句话功能描述>
api:
  endpoint: <完整 URL，必须 localhost:80 开头>
  method: POST | GET
  content_type: multipart/form-data | application/json
params:
  - name: <字段名>
    type: enum | text | number | image
    values: [...]              # 仅 enum
    required: true | false
    prompt_to_user: "<引导文案>"
output:
  type: image_url | text | image_binary
  display_as: feishu_card | feishu_image | feishu_text
---

## When to Use
<触发条件，LLM 选 skill 判断依据>

## Procedure
1. <步骤 1>
2. <步骤 2>

## Verification
<怎么确认成功>
```

### 首期 Skill: frame-bg-remover

| 项 | 值 |
|---|---|
| 端点 | `POST http://localhost:80/api/shared/frame-bg-remover/process` |
| 请求 | `multipart/form-data`，单字段 `image` (file) |
| 响应 | `image/png` 二进制 |
| 错误 | 400 / 413 (>50MB) / 500，JSON `{"detail": "..."}` |
| 上游文档 | `D:\GIT\XD-AIGC-toolbox\tools\frame-bg-remover\README.md` |

对话流程：

```
用户：帮我去白底 / 我要抠图
  bot：请上传一张图片
用户：[发图]
  bot：[POST → 接 PNG bytes → 飞书 image upload → reply image]
```

## 目录结构（待建）

```
D:\GIT\XD-AIGC-agent\
├── CLAUDE.md  README.md  .env.example  .gitignore
├── pyproject.toml  Dockerfile  docker-compose.yml
├── ci/check-banned-apis.sh
├── docs/
│   ├── ARCHITECTURE.md   # 本文
│   └── PHASE.md          # Phase 进度
├── skills/
│   └── frame-bg-remover.yaml
├── src/
│   ├── main.py  config.py
│   ├── feishu/{adapter,reply,upload}.py   # lark-oapi WS, 仅 reply
│   ├── orchestrator/{llm,schema}.py       # LiteLLM + BotAction
│   ├── skill/{registry,executor,schema}.py
│   ├── session/redis_store.py
│   └── http_client/allowlist.py
└── tests/
```
