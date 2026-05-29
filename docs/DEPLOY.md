# DEPLOY — XD-AIGC-agent 生产部署手册

> 目标：部署到 L20_1（10.102.80.15），与 xd-gateway 并列运行。
> 受众：Johnny（部署者）+ 接手运维的人。

## 1. 前置条件（一次性）

### 1.1 服务器环境
- ssh 到 L20_1：`ssh ubuntu@10.102.80.15`
- Docker 已装（与 xd-gateway 共享）：`docker --version` 应 ≥ 20
- 本机 Redis 在跑（与 toolbox 共享）：`redis-cli ping` 返回 `PONG`
- 本机 toolbox 在 80 端口：`curl -s -o /dev/null -w "%{http_code}\n" http://localhost:80` 返回 `200/404`

### 1.2 创建服务账号
```bash
sudo groupadd --gid 1100 toolbox-bot
sudo useradd --uid 1100 --gid toolbox-bot --shell /bin/false --create-home toolbox-bot
```
（与 Dockerfile 内 user 对齐）

### 1.3 准备配置目录
```bash
sudo mkdir -p /etc/xd-aigc-agent
sudo chown root:root /etc/xd-aigc-agent
sudo chmod 750 /etc/xd-aigc-agent
```

## 2. 构建 + 部署（每次发版）

### 2.0 前置：Redis 容器（首次部署）

```bash
# 起一个专用 Redis container，host network 让 agent 直连 localhost:6379
sudo docker run -d --name xd-aigc-agent-redis \
    --restart=always --network=host \
    redis:7-alpine redis-server --bind 127.0.0.1 \
    --maxmemory 256mb --maxmemory-policy allkeys-lru

# 验证
sudo docker exec xd-aigc-agent-redis redis-cli ping  # 应返回 PONG
```

### 2.1 首次部署：git clone agent + skills 两个仓库

```bash
# 本地：把 agent 代码 push 到 GitHub
git push origin main

# 服务器
ssh ubuntu@10.102.80.15
cd /AIGC_Group

# clone 两个仓库
git clone https://github.com/XD-AIGC/XD-AIGC-agent.git
git clone https://github.com/XD-AIGC/XD-AIGC-skills.git   # PRIVATE，需要 .git-credentials 配 PAT

# build agent 镜像
cd XD-AIGC-agent
sudo docker build -t xd-aigc-agent:latest .  # 首次约 2-5 分钟
sudo docker images xd-aigc-agent  # 验证
```

### 2.1b 装 cron 自动拉 skills（每 5 分钟）

```bash
sudo cp /AIGC_Group/XD-AIGC-agent/deploy/cron-pull-skills.sh /usr/local/bin/
sudo chmod +x /usr/local/bin/cron-pull-skills.sh
echo '*/5 * * * * ubuntu /usr/local/bin/cron-pull-skills.sh >> /var/log/xd-aigc-skills-pull.log 2>&1' \
    | sudo tee /etc/cron.d/xd-aigc-skills-pull
sudo touch /var/log/xd-aigc-skills-pull.log
sudo chown ubuntu /var/log/xd-aigc-skills-pull.log
```

配置后：同事 push skill → 5min 内 cron 拉到服务器 → agent watcher 检测变化 → 自动 reload registry（对话不中断）。

### 2.2 配置 `.env`
```bash
# 在服务器上，第一次部署需要拷模板并填密钥
sudo cp /AIGC_Group/XD-AIGC-agent/.env.example.prod /etc/xd-aigc-agent/.env
sudo chmod 600 /etc/xd-aigc-agent/.env
sudo chown root:root /etc/xd-aigc-agent/.env
sudo vim /etc/xd-aigc-agent/.env  # 填 FEISHU_APP_SECRET / LLM_API_KEY
```

**密钥来源**：
- `FEISHU_APP_SECRET`：[飞书开放平台](https://open.feishu.cn/app/cli_aa99420199f9dbd8) → 凭证与基础信息
- `LLM_API_KEY`：找 LLM proxy 维护者拿 bot 专属 service token（不要用 Johnny 个人 key！）

### 2.2b Agent runtime 灰度开关

默认保持 v1 观测模式：

```env
AGENT_RUNTIME=v1
AGENT_RUNTIME_V2_PERCENT=0
```

灰度时只改 `.env` 后重启服务：

```bash
sudo vim /etc/xd-aigc-agent/.env
sudo systemctl restart xd-aigc-agent
sudo journalctl -u xd-aigc-agent --since '5 min ago' | grep RUNTIME
```

建议节奏：

| 阶段 | 配置 | 观察 |
|---|---|---|
| 0% | `AGENT_RUNTIME=v1`, `AGENT_RUNTIME_V2_PERCENT=0` | 基线日志 |
| 10% | `AGENT_RUNTIME=v2`, `AGENT_RUNTIME_V2_PERCENT=10` | 观察 1 周 |
| 50% | `AGENT_RUNTIME=v2`, `AGENT_RUNTIME_V2_PERCENT=50` | 观察 1 周 |
| 100% | `AGENT_RUNTIME=v2`, `AGENT_RUNTIME_V2_PERCENT=100` | 跑稳 2 周后再考虑删 v1 兼容字段 |

回退：把 `AGENT_RUNTIME=v1`、`AGENT_RUNTIME_V2_PERCENT=0` 写回 `.env` 并重启。不要清 Redis；按 session TTL 自然消化。

### 2.3 跑健康检查（部署前自检）
```bash
sudo docker run --rm --network=host --env-file=/etc/xd-aigc-agent/.env \
    xd-aigc-agent:latest python -m scripts.healthcheck
# 期望输出：[OK] redis ... / [OK] llm ... / [OK] toolbox ...  退出码 0
```

### 2.4 安装 systemd 服务
```bash
sudo cp /AIGC_Group/XD-AIGC-agent/deploy/xd-aigc-agent.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now xd-aigc-agent
sudo systemctl status xd-aigc-agent  # 应该 active (running)
```

### 2.5 看日志
```bash
sudo journalctl -u xd-aigc-agent -f                # 实时
sudo journalctl -u xd-aigc-agent --since '10 min ago' | grep -E "ERROR|MSG|ACT"
```

## 3. 飞书后台

### 3.1 扩可用范围（试点）
1. 登录 [飞书开放平台](https://open.feishu.cn/app/cli_aa99420199f9dbd8)
2. 应用功能 → 可用范围 → 部分成员模式 → 添加 5-10 个试点同事
3. 试点 2-3 天收集反馈后扩到全员

### 3.2 验证 WebSocket 连接
部署后第一时间：找一个有可用范围的同事用飞书私聊 bot，发「画一张测试海报」，确认 bot 有回应。
若无回应：`journalctl -u xd-aigc-agent | grep -i "connected\|websocket"` 看 WS 是否连上。

## 4. 升级流程（已部署后）

### 4.1 升级 agent 代码（harness 改动）

```bash
# 本地（开发机）
git push origin main

# 服务器
ssh ubuntu@10.102.80.15
cd /AIGC_Group/XD-AIGC-agent
git pull origin main
sudo docker build -t xd-aigc-agent:latest .
sudo systemctl restart xd-aigc-agent
sudo journalctl -u xd-aigc-agent -f --since '30 sec ago'  # 验证启动
```

### 4.2 升级 skill（同事侧改 SKILL.md / manifest）

**完全自动，不需要你做任何事**：
1. 同事 push 到 XD-AIGC-skills
2. 服务器 cron 5 分钟内 git pull
3. agent watcher 检测变化 → reload registry
4. 对话不中断、不重启 bot、不重 build docker

如果你想手动加速：
```bash
ssh ubuntu@10.102.80.15
sudo /usr/local/bin/cron-pull-skills.sh   # 立即手动跑一次
# watcher 2s 内自动 reload
```

**回滚**（恢复到上一个 commit）：
```bash
cd /AIGC_Group/XD-AIGC-agent
git log --oneline -10  # 找到要回退的 commit hash
git checkout <commit-hash>
sudo docker build -t xd-aigc-agent:latest .
sudo systemctl restart xd-aigc-agent
```

## 5. 故障排查

| 症状 | 命令 | 处理 |
|------|------|------|
| 服务 inactive | `systemctl status xd-aigc-agent` | 看 Reason，多半 docker run 失败 |
| 容器一直重启 | `docker logs xd-aigc-agent` | 多半 `.env` 缺字段或 LLM/Redis 不通 |
| WebSocket 不连 | `journalctl ... \| grep -i websocket` | 检查 FEISHU_APP_ID/SECRET |
| 出图慢/超时 | `journalctl ... \| grep POLL` | toolbox 后端问题，不是 bot |
| 健康检查 fail | `docker exec xd-aigc-agent python -m scripts.healthcheck` | 看哪项 FAIL 针对性修 |

## 6. 安全检查清单（部署前必过）

- [ ] `.env` 文件 `chmod 600` 且 `chown root:root`
- [ ] `LLM_API_KEY` 是 bot 专属 service token，不是 Johnny 个人 key
- [ ] `FEISHU_APP_ID` = `cli_aa99420199f9dbd8`（公开），SECRET 已正确
- [ ] 容器 `--user 1100:1100`（非 root）+ `--read-only`
- [ ] 飞书 App scope 只勾 6 个权限（详见 CLAUDE.md §权限清单）
- [ ] `bash ci/check-banned-apis.sh` 通过
- [ ] 健康检查全 OK
- [ ] 试点同事 ≤ 10 人，2-3 天后再扩
