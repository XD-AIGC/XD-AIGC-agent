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

### 2.1 本地（开发机）构建镜像并推到服务器

方案 A：直接在服务器上构建（小项目推荐）
```bash
# 在开发机：把源码 rsync 到服务器
rsync -av --exclude='.git' --exclude='.env' --exclude='bot.log' \
    /mnt/d/GIT/XD-AIGC-agent/ ubuntu@10.102.80.15:/AIGC_Group/XD-AIGC-agent/

# ssh 到服务器
ssh ubuntu@10.102.80.15
cd /AIGC_Group/XD-AIGC-agent
sudo docker build -t xd-aigc-agent:latest .
sudo docker images xd-aigc-agent  # 验证
```

方案 B：本地 build → tar → scp（若服务器构建环境太干净没缓存）
```bash
# 本地
docker build -t xd-aigc-agent:latest .
docker save xd-aigc-agent:latest | gzip > /tmp/xd-aigc-agent.tar.gz
scp /tmp/xd-aigc-agent.tar.gz ubuntu@10.102.80.15:/tmp/

# 服务器
ssh ubuntu@10.102.80.15 'sudo docker load < /tmp/xd-aigc-agent.tar.gz'
```

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

```bash
# 1. rsync 新代码到 /AIGC_Group/XD-AIGC-agent/
# 2. 在服务器
cd /AIGC_Group/XD-AIGC-agent
sudo docker build -t xd-aigc-agent:latest .
sudo systemctl restart xd-aigc-agent  # 滚动重启，~10s 完成
sudo journalctl -u xd-aigc-agent -f   # 验证启动成功
```

回滚：`sudo docker tag xd-aigc-agent:<old-sha> xd-aigc-agent:latest && systemctl restart xd-aigc-agent`

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
