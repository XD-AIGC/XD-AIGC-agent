---
name: xd-poster-gen
description: 通过对话生成「心动小镇运营海报」。触发后必须先用 Skill 内置中文选项主动收集/确认角色、动作、参考海报、排版构图、主标题、副标题、色调、附加元素和补充文案等 brief，再调用部署在 10.102.80.15 上的 xd-poster-studio-v2 后端完成 2 步生成（角色白底图 → GPT 海报合成），返回成品图 URL 和 fileId。
---

# xd-poster-gen — 心动小镇海报对话式生成

把 `tools/xd-poster-studio-v2` 包装成一个可被任何 agent 复用的 SKILL。无需进入网页，靠对话收集参数 → 一条命令出图。

## 触发条件

只要用户说：
- 「给我生成一张心动小镇海报」「帮我做张运营海报」
- 「皑皑骑滑板的海报」「双人海报，主题 xxxx」
- `/xd-poster-gen`、`/海报`

立即进入下面的「对话流」，不要反问"你想用网页做吗"。

## 后端

- **Base URL**：`http://10.102.80.15/xd-poster-studio-v2`（生产 gateway）
- 可通过环境变量 `POSTER_API_BASE` 覆盖（例如调本地 8088）
- 所有 helper 脚本位于本目录 `scripts/`

网络分层：
- 问询阶段不要依赖后端。角色、排版、比例、清晰度等选项已离线内置在 `references/`。
- 角色三视图、角色头像、排版预览图、Logo 已离线内置在 `assets/`，可用于 Agent 本地查看或兜底上传。
- 只有上传参考图、上传本地角色图、提交生成、轮询结果时才访问 `POSTER_API_BASE`。
- 如果 Agent 沙箱访问不到 `10.102.80.15`，仍然要先用离线选项完成 brief；到生成阶段再提示需要内网/VPN或可访问代理地址。

## 对话流（必读）

### Step 0 — 先进入 Brief 收集模式

默认不要马上出图。触发后先判断用户是否已经提供了完整 brief：

- 如果缺少角色、动作/场景、标题、排版、色调、参考图决策、附加元素/补充文案等信息，先发一条「海报 brief 确认卡」让用户补齐。
- 如果用户明确说「直接生成」「你自由发挥」「不用问了」，可用默认值补足缺失项并出图。
- 如果用户已经把所有关键信息都写清楚，可以直接生成，不需要重复确认。
- 已知信息不要重复问；未知信息集中一次问完，最多再追问一次关键缺口。
- 不要因为拉不到 `POSTER_API_BASE` 就说无法列角色或排版；改用 `references/characters.tsv` 和 `references/options.md`。

#### 海报 brief 确认卡

按下面格式问用户。能从用户原话推断的项直接填入；推断不出的写「请补充」或给 2-4 个建议选项。

```
我先把这张海报的 brief 补齐，确认后就出图：

1. 角色：<中文名（key）；不确定时先列中文候选>
2. 动作/场景：<姿态、表情、地点、服装或氛围>
3. 参考海报：不需要 / 上传参考图 / 已有 refImageId
4. 排版构图：default / center / topimg_bottomtext / diagonal / ...
5. 主标题：<主标题>
6. 副标题：<副标题或活动利益点>
7. 色调：<例如 粉樱+米白、夏日蓝+柠檬黄>
8. 附加元素：<道具、背景物、贴纸、Logo、特效等>
9. 补充文案/标签：<日期、规则、CTA、#标签；没有可写“无”>
10. 比例/清晰度：默认 2:3 / 2K
```

问询口吻要短、像在帮用户填创意单，不要让用户感觉在填表。如果用户只给一句需求，优先给一个已经预填好的版本，例如：

```
我先按你的描述补一版 brief，你确认或改几项就行：
角色：皑皑（aiai）
动作/场景：骑滑板穿过樱花街道，活泼开心
参考海报：不需要
排版构图：topimg_bottomtext（上图下文）
主标题：春日滑板节
副标题：限时活动开启
色调：粉樱+薄荷绿+阳光米白
附加元素：樱花花瓣、街道旗帜、动感速度线
补充文案/标签：登录领取奖励
比例/清晰度：2:3 / 2K
```

### Step 1 — 列角色（当用户不知道有谁时）

```bash
bash <skill-dir>/scripts/list-characters.sh
```

该脚本优先请求后端，失败时自动使用 `references/characters.tsv`。输出必须中文名优先，如：
```
- 皑皑（aiai）：3.5头身Q版，黑色外翻短碎发...
- 安妮（annie）：3.5头身Q版，粉白兔耳发箍...
```

不要默认把完整角色列表全部贴给用户。优先列 6-12 个常用/相关中文候选；用户要求「全部角色」时再贴完整列表。把用户选择的中文名映射为 key 后再生成 payload。

### Step 1.5 — 查离线选项（当用户问排版/比例/字段时）

```bash
bash <skill-dir>/scripts/list-options.sh
```

该脚本只读取 `references/options.md`，不访问后端。排版、比例、清晰度以这里为准。

### Step 1.6 — 内置图片资产兜底

Skill 自带这些本地图片：

- `assets/character-refs/<key>_ref.png`：41 张角色三视图参考图，中文名/key 映射见 `references/characters.tsv`。这是角色动作图 Step 1 的优先参考资产。
- `assets/character-avatars/<key>.jpg`：41 张角色头像，仅用于离线选角预览，不要优先上传为生成参考图。
- `assets/comp-previews/<compositionType>.png`：排版构图预览，只用于让用户理解构图，不要当参考海报上传。
- `assets/logo/logo.png`：官方 Logo，本地说明用；生成时后端会自动处理 Logo。

常规生成优先使用命名角色：

```json
{ "characters": ["aiai"] }
```

当命名角色链路不稳，或 Agent 明确需要使用 Skill 内置角色图作为上传参考图时，先上传本地角色三视图资产：

```bash
bash <skill-dir>/scripts/upload-local-character-refs.sh aiai annie
```

输出里的 `customRefFileIds` 可直接放入 `generate-v2` payload。注意：这一步仍需要能访问 `POSTER_API_BASE`。

### Step 2 — 将 brief 映射为后端参数

后端只接收固定字段。用户 brief 中的主标题、副标题、色调、元素、标签等，需要整理到 `actionDesc` 和 `textContent`：

| 字段 | 必填 | 说明 |
|------|------|------|
| `characters` | 是* | 角色 `key` 数组（如 `["aiai"]`，多人 `["aiai","annie"]`） |
| `actionDesc` | 是 | 动作/场景/表情/服装/附加元素合成一段自然语言。例：「皑皑骑滑板穿过樱花街道，活泼开心，樱花花瓣飞舞，加入街道旗帜和动感速度线」 |
| `textContent` | 是 | 海报文字字符串，多行用 `\n`。按实验工具前端格式拼接：`主标题：`、`副标题：`、`元素：`、`色调：`、补充文案 |
| `ratio` | 否 | 单比例：`2:3` / `9:16` / `1:1` / `3:2` / `16:9`，默认 `2:3` |
| `ratios` | 否 | 多比例数组同时出多张：`["2:3","9:16"]`。传了它就忽略 `ratio` |
| `resolution` | 否 | 实验工具当前固定 `2K`，默认 `2K` |
| `compositionType` | 否 | 排版构图预设，11 选 1（见下表） |
| `refImageId` | 否 | 参考海报 fileId（先用 upload-reference.sh 上传得到） |
| `customRefFileIds` | 否 | 自定义角色参考图 fileId 数组（同上） |
| `cachedStep1FileId` | 否 | 复用上次 Step1 角色白底图，跳过 Step1（省时省钱） |

\* `characters` / `customRefFileIds` / `cachedStep1FileId` 三者至少一项。

`textContent` 推荐格式：

```text
主标题：<主标题>
副标题：<副标题>
元素：<附加元素>
色调：<色调>
【时间】<日期或时间>
【奖励】<奖励/CTA>
<纯文本补充文案>
```

如果用户没有主标题/副标题，但要求「直接生成」，可以用需求主题自动拟定主标题和副标题；否则先问。

#### 排版构图预设（`compositionType`）

| key | 中文 | 适用 |
|-----|------|------|
| `default` | 默认 AI 自由发挥 | 不确定时用这个 |
| `center` | 居中式 | 单角色证件照、产品聚焦 |
| `triangle` | 三角排版 | 多元素呼应，稳定感 |
| `surround` | 包围式 | 主体居中、文字环绕，凝聚感 |
| `lefttext_rightimg` | 左文右图 | 横版/方版宣传图 |
| `leftimg_righttext` | 左图右文 | 同上 |
| `toptext_bottomimg` | 上文下图 | 竖版招贴 |
| `topimg_bottomtext` | 上图下文 | 竖版招贴 |
| `symmetry` | 对称式 | 节日感、仪式感 |
| `diagonal` | 对角式 | 动感、版式跳脱 |
| `curve` | 曲线式（S 形） | 流动叙事 |

### Step 3 — 上传参考图（仅当用户提供了图片）

参考海报排版（让 AI 抄它的版式）：
```bash
bash <skill-dir>/scripts/upload-reference.sh /path/to/ref.jpg
# 输出：{"fileId":"abc123","localPath":"..."}
```
把返回的 `fileId` 填到 `refImageId`。

自定义角色参考图（替换/补充内置角色）：同样的上传脚本，`fileId` 收集到 `customRefFileIds` 数组里。

如果用户在聊天里“上传了一张参考海报”，Agent 必须先确认自己是否拿到了本地文件路径。拿到了路径就直接调用 `upload-reference.sh`；没有路径或附件不可读时，不要编造路径，要求用户重新上传可被当前 Agent 读取的文件，或提供本地绝对路径。

`upload-reference.sh` 必须返回 `fileId` 才算上传成功；如果只返回 `localPath`，不要继续把它当作 `refImageId` 使用，说明当前后端上传接口不是 V2 所需的最新行为，需要后端修复或改用不带参考海报生成。

不要把 `assets/comp-previews/*.png` 当作参考海报上传；它们是灰度构图示意，不是运营海报风格参考。

### Step 4 — 出图

把所有参数拼成 JSON 通过 stdin 传给 generate-poster.sh：

```bash
cat <<'EOF' | bash <skill-dir>/scripts/generate-poster.sh
{
  "characters": ["aiai"],
  "actionDesc": "皑皑挥手打招呼，穿夏日和风浴衣，背景樱花飘落",
  "textContent": "主标题：樱花季限时活动\n副标题：4 月 1 日 - 4 月 30 日\n元素：樱花花瓣、和风纸扇\n色调：粉樱+米白\n【奖励】登录即送限定服饰",
  "ratio": "2:3",
  "compositionType": "topimg_bottomtext"
}
EOF
```

脚本会：
1. `POST /api/generate-v2` → 拿 `v2JobId`
2. 每 3s `GET /api/poll-v2/:id` 直到 `status=completed`（默认 5 分钟超时）
3. 输出最终 JSON，含 `images: [{fileId, url}, ...]`

`url` 是带签名的图片直链，直接 `curl -o out.png "$url"` 即可拿到图。

### Step 5 — 回复用户

把每张图的 `url` 嵌入回复，**同时**保留 `fileId`（以备复用）。例：

```
✅ 已生成 1 张海报（构图：topimg_bottomtext）：

1. 2:3 主视觉  →  https://...signed-url
   fileId: v2_xxx_yyy（可用 cachedStep1FileId 复用角色白底图）
```

## 进阶：复用 Step 1

第一次生成后，response 会把 Step 1 的 fileId 写进 `intermediateImages.characterActionFileId`（轮询完成结果里可读到）。下次同角色同动作只换文案/排版时，**强烈建议**复用：

```json
{
  "characters": ["aiai"],
  "actionDesc": "（同上一次）",
  "cachedStep1FileId": "上次拿到的角色白底图 fileId",
  "textContent": "新文案",
  "compositionType": "diagonal"
}
```

跳过 Step 1 可节省约 30~60s 和一次 gemini-3-pro-image-preview 调用。

## 失败排查

- **HTTP 400 `请至少选择...`**：`characters` / `customRefFileIds` / `cachedStep1FileId` 三者全空。
- **HTTP 404 on poll**：`v2JobId` 拼错，或服务器重启了（`v2Jobs` 是内存 Map）。
- **`failed` + 错误含 `Mivo`**：触发 [[feedback_mivo_cursed_fileid]] 或限速 [[feedback_mivo_rate_limit]]。前者重传角色参考图；后者重试前先 sleep 4s。
- **poll 超时**：调大 `POSTER_POLL_TIMEOUT=600 bash ...`。
- **不出图但 status=completed 且 images 为空**：看 `partialError` 字段，多比例时可能部分失败。

## 不要做

- ❌ 不要直接调 `/api/generate-poster`（旧 v1 接口），用 `/api/generate-v2`。
- ❌ 不要让用户去网页操作，对话流就是入口。
- ❌ `textContent` 不要硬塞 JSON，前端按字符串处理，多行用 `\n`。
- ❌ 不要并行多个 generate-v2 调用，Mivo 后端有节流。需要多张图用 `ratios` 数组让后端内部并行。
