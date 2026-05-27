# L20-1 服务清单

> 给 skill 维护者：写 `manifest.yaml` 的 `api.base_url` 时从这里查端口。
> 给 agent 维护者：知道 agent 出站可能打到哪些服务。
>
> 服务器：`10.102.80.15`（L20-1）。Agent 与所有 toolbox 子工具同机部署，**用 `localhost:<port>` 访问**。
> 启动脚本权威来源：`/AIGC_Group/start-all-l20-1.sh`

## 1. 基础设施（不是 skill 后端，但 agent 可能间接依赖）

| 端口 | 服务 | 说明 |
|---|---|---|
| 22 | sshd | SSH |
| 80 | docker-proxy | 公网 HTTP |
| 443 | docker-proxy | 公网 HTTPS |
| 3082 | artdam-backend | ArtDAM 后端（toolbox 子工具用 `ARTDAM_SKILL_TOKEN` 调） |
| 3090 | artdam-frontend | ArtDAM 前端 |
| 6379 | redis | agent session store（容器内 `xd-aigc-agent-redis`） |
| 8000 | toolbox-api | toolbox 主 API |
| 8080 | comfyui-proxy-default | **ComfyUI 共享代理，不是 toolbox 子工具网关**。`TOOLBOX_BASE_URL` 历史指向此 |
| 8081/8083 | comfyui-proxy | 指向 L20-0 的 ComfyUI 实例 |
| 9002 | mcp-server | MCP 协议服务端 |
| 9003 | blender-service | Blender 渲染服务 |

## 2. toolbox 子工具（agent 真正 submit 的目的地）

每个工具一份独立 node/python 服务，agent 通过 `api.base_url: http://localhost:<port>` 直连。

| 端口 | 工具名 | 用途 | 类型 |
|---|---|---|---|
| 7860 | hymotion | GPU 视频生成（≈20GB 显存） | python |
| 8082 | sprite-animator | 序列帧动画 | python |
| 8084 | tapip-studio | TapTap IP 素材生成 | node |
| **8085** | **xd-town-studio** | **心动小镇角色素材**（已接 bot） | node |
| 8086 | xd-poster-studio | 心动小镇活动海报（旧版） | node |
| 8087 | ro-story-studio | RO 故事版素材 | node |
| 8089 | xd-fashion-trend-studio | 时尚大片归档 / 换装 | node |
| **8090** | **xd-poster-studio-v2** | **心动小镇运营海报 v2**（已接 bot） | node |
| 8091 | tapip-poster-studio | TapTap IP 系列海报 | node |
| 8092 | heart | 二次元动作 → 真人 | python |
| 8093 | tap-avatar-frame | TapTap 头像框 | node |
| 8095 | xd-town-design-check | 美术设计稿 AI 自检 | node |
| 8096 | character-hair-generator | 角色发型生成 | node |
| 8097 | xd-town-tittle-translation | 多语言活动标题图 | node |
| 9001 | asset-extractor | BiRefNet 抠图 | python |

## 3. agent 自身

| 端口 | 服务 | 说明 |
|---|---|---|
| 6379（容器内） | redis | session 存储 |
| WS 出站 | feishu-msg-frontier | 无监听端口，主动连飞书 |

## 4. 写 manifest 时怎么填

```yaml
# heartopia/<skill>/manifest.yaml
api:
  type: poll
  base_url: http://localhost:8090        # ← 从上表找对应端口
  submit_path: /api/generate-v2
  poll_path_template: /api/poll-v2/{job_id}
  ...

lazy_resources:
  lookup_characters:
    type: http
    url: http://localhost:8090/api/characters?refresh=1   # ← 同端口
    cache_ttl_sec: 300
```

**注意**：`api.base_url` 和 `lazy_resources.*.url` 的 host:port 都会自动加入 agent HTTP 白名单（见 `src/skill/registry.py:_register_http_resource_url`），无需手动改 allowlist。

## 5. 已接入 bot 的 skill

| skill 名 | toolbox 后端端口 | 状态 |
|---|---|---|
| xd-poster-studio-v2 | 8090 | ✅ 已配 base_url + lazy_resources |
| xd-town-studio | 8085 | ✅ 已配 base_url（注意：8085 的 `/api/characters` 端点可能尚未实现，需 toolbox 维护者确认） |

## 6. 已知约束

- toolbox 子工具的 `.env` 必须含 `ARTDAM_SKILL_TOKEN`（向 ArtDAM 拉角色图），否则 `/api/characters` 可能拉空，submit 时也会失败
- 8080 ≠ toolbox 网关，是 ComfyUI proxy。早期项目宪法把 `TOOLBOX_BASE_URL` 设到 8080，新 skill 必须用 `api.base_url` 指向具体子工具端口
- 部分服务（如 ip_char/8013）由其他人维护，不在 `start-all-l20-1.sh` 控制范围，重启需联系 owner

## 7. 重启 / 排查

```bash
# 重启全部
sudo bash /AIGC_Group/start-all-l20-1.sh

# 只重启某个
sudo bash /AIGC_Group/start-all-l20-1.sh xd-poster-studio-v2

# 看哪些端口在监听
sudo ss -tlnp | grep -E 'LISTEN.*:80[0-9]{2}'

# 直接 ping 某个工具是否健康
curl -sw 'HTTP %{http_code}\n' http://localhost:8090/api/characters?refresh=