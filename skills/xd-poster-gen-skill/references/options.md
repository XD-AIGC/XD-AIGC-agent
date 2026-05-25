# xd-poster-gen 离线选项清单

这些选项来自 `tools/xd-poster-studio-v2` 当前实验工具源码。问询阶段优先使用本清单，不要为了列选项访问后端或打开网页。

## Brief 字段

- 角色：使用中文名和 key 映射，详见 `references/characters.tsv`。
- 动作/场景：角色姿态、表情、地点、服装变化、氛围。
- 参考海报：不需要 / 上传参考图 / 使用已有 `refImageId`。
- 排版构图：见下方 `compositionType`。
- 主标题：必填，前端限制约 30 字以内。
- 副标题：可选，前端限制约 60 字以内。
- 元素：可选，道具、背景物、贴纸、特效、Logo 外的装饰元素。
- 整体色调：可选，例如「粉樱+薄荷绿+阳光米白」「清冷蓝白色」。
- 补充文案：可选，可为 `【标签】内容` 或纯文本，最多建议 10 条。
- 比例/清晰度：默认 `2:3 / 2K`。

## 内置图片资产

- 角色三视图参考图：`assets/character-refs/<key>_ref.png`，共 41 张，来自本地 `tools/xd-town-studio/assets/characters/*/*_ref.png`，这是 Step 1 生图更依赖的角色多视角参考。
- 角色头像：`assets/character-avatars/<key>.jpg`，共 41 张，仅用于离线选角预览，不要优先作为生成参考图。
- 排版预览图：`assets/comp-previews/<compositionType>.png`，只用于帮助用户选择构图，不建议上传为参考海报。
- 官方 Logo：`assets/logo/logo.png` 和 `assets/logo/logo-size-ref.jpg`，仅用于离线说明；后端生成时会自动注入 Logo。

当命名角色链路不稳定、或 Agent 需要把 Skill 自带角色图显式上传时，使用：

```bash
bash scripts/upload-local-character-refs.sh aiai annie
```

脚本默认上传三视图参考图，输出的 `customRefFileIds` 可以直接放入 `generate-v2` payload。常规情况下仍优先使用 `characters: ["aiai"]`，因为后端会自动读取自己的角色库；当 Agent 无法信任后端角色库或需要完全使用 Skill 内置角色参考图时，再上传三视图。

## 排版构图 compositionType

- `default`：默认（AI 自由发挥），不指定特定构图。
- `lefttext_rightimg`：左文右图，适合横版或方版宣传图。
- `leftimg_righttext`：左图右文，适合横版或方版宣传图。
- `toptext_bottomimg`：上文下图，适合竖版招贴、文字先行。
- `topimg_bottomtext`：上图下文，适合竖版招贴、主体先行。
- `center`：居中式，适合单主体聚焦、证件照感或产品聚焦。
- `triangle`：三角形，适合多元素呼应和稳定构图。
- `symmetry`：对称式，适合节日感、仪式感、左右/上下均衡。
- `surround`：包围式，适合主体居中、文字环绕和凝聚感。
- `diagonal`：对角式，适合运动感、速度感、跳脱版式。
- `curve`：曲线式，适合 S 形流动叙事；横版从左至右，竖版从上至下。

## 比例 ratio

实验工具前端当前提供：

- `2:3`：默认竖版海报。
- `9:16`：手机竖屏。
- `1:1`：方图。
- `3:2`：横向短版。
- `16:9`：横屏。

后端支持 `ratios` 数组同时生成多张；如果用户没明确要多比例，只传单个 `ratio`。

## 清晰度 resolution

- `2K`：实验工具当前固定值，默认使用。
