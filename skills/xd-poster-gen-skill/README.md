# xd-poster-gen — 心动小镇海报对话式生成 SKILL

把 `xd-poster-studio-v2` 工具封装成一个可被任何 Claude/Agent 复用的 SKILL，
**无需打开网页**，对话流收集参数 → 一条命令出图。

## 默认交互

触发后 Agent 会先主动补齐海报 brief，不会在信息不足时直接出图。默认会确认：

- 角色和动作/场景
- 是否上传参考海报
- 排版构图
- 主标题、副标题
- 色调
- 附加元素
- 补充文案、标签或纯文本
- 比例和清晰度

用户明确说「直接生成」「你自由发挥」「不用问了」时，Agent 可以用默认值补足并直接调用后端。

角色、排版、比例、清晰度等选项已离线内置在 `references/`。如果 Agent 沙箱访问不到 `10.102.80.15`，仍然可以先完成 brief；只有上传参考图和生成图片必须能访问后端。

本包还内置了本地图片资产：

- `assets/character-refs/`：41 张角色三视图参考图，来自 `tools/xd-town-studio/assets/characters/*/*_ref.png`，可用 `scripts/upload-local-character-refs.sh` 上传为 `customRefFileIds`。
- `assets/character-avatars/`：41 张角色头像，仅用于离线选角预览。
- `assets/comp-previews/`：排版构图预览图，只用于选择构图，不建议上传为参考海报。
- `assets/logo/`：官方 Logo 参考；实际生成时后端会自动注入 Logo。

上传用户参考海报时，Agent 必须拿到可读取的本地图片路径。如果平台只展示了图片但没有提供文件路径，需要让用户重新上传可读附件或提供本地绝对路径。

`scripts/upload-reference.sh` 必须拿到后端返回的 `fileId` 才算成功。如果后端只返回 `localPath`，当前 V2 参考海报链路不可用，需要修复后端上传接口或先不带参考海报生成。

## 安装

把整个文件夹放到 Agent 的 Skill 目录。Codex 常用：

```bash
mkdir -p ~/.codex/skills
cp -R xd-poster-gen-skill ~/.codex/skills/xd-poster-gen
chmod +x ~/.codex/skills/xd-poster-gen/scripts/*.sh
```

Claude Code 项目内安装：

```bash
mkdir -p <your-repo>/.claude/skills/
cp -R xd-poster-gen-skill <your-repo>/.claude/skills/xd-poster-gen
chmod +x <your-repo>/.claude/skills/xd-poster-gen/scripts/*.sh
```

Agent 通过文件夹名 `xd-poster-gen` 触发；用户说「帮我生成海报」「皑皑骑滑板的海报」等会自动进入对话流。

## 环境变量

| 变量 | 默认 | 说明 |
|------|------|------|
| `POSTER_API_BASE` | `http://10.102.80.15/xd-poster-studio-v2` | 后端 base url。本地调试可设 `http://localhost:8088` |
| `POSTER_POLL_TIMEOUT` | `300` | 轮询超时（秒），慢卡可调到 600 |
| `POSTER_POLL_INTERVAL` | `3` | 轮询间隔（秒） |
| `POSTER_OFFLINE` | `0` | 设为 `1` 时角色列表只读离线清单 |

## 一键试一下

```bash
# 列角色
bash scripts/list-characters.sh

# 列排版/比例/brief 字段
bash scripts/list-options.sh

# 可选：上传 Skill 内置角色图，得到 customRefFileIds
bash scripts/upload-local-character-refs.sh aiai annie

# 出图
cat <<'EOF' | bash scripts/generate-poster.sh
{
  "characters": ["aiai"],
  "actionDesc": "皑皑挥手打招呼，穿夏日和风浴衣，背景樱花飘落",
  "textContent": "主标题：樱花季限时活动\n副标题：4 月 1 日 - 4 月 30 日\n元素：樱花花瓣、和风纸扇\n色调：粉樱+米白",
  "ratio": "2:3",
  "compositionType": "topimg_bottomtext"
}
EOF
```

输出 JSON 含 `images: [{fileId, url}]`，`url` 是带签名的图片直链。

## 更多

完整对话流、11 种排版构图、复用 Step1 优化、失败排查见 `SKILL.md`。
