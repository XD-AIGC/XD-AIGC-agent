# XD-AIGC-agent 飞书机器人
# 部署目标：L20_1（10.102.80.15），与 xd-gateway 并列
# 镜像策略：python:3.11-slim + 非 root 用户 toolbox-bot（uid 1100）+ 内置 healthcheck

FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

# 系统依赖：curl 给 healthcheck CLI 兜底；其他都不要
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# 非 root 服务账号（与服务器侧 toolbox-bot 对齐）
RUN groupadd --gid 1100 toolbox-bot \
    && useradd --uid 1100 --gid toolbox-bot --shell /bin/false --create-home toolbox-bot

WORKDIR /app

# 必须 src/ + pyproject.toml 一起在场才能 pip install .（setuptools 包发现）
COPY pyproject.toml ./
COPY src ./src
RUN pip install --upgrade pip && pip install .

# 业务辅助资源（.dockerignore 已剔除 .env / bot.log / __pycache__ / skills/*/assets/）
COPY scripts ./scripts
COPY skills ./skills

# 运行期身份切到 toolbox-bot
RUN chown -R toolbox-bot:toolbox-bot /app
USER toolbox-bot

# Docker HEALTHCHECK：每 30s 跑一次 healthcheck.py，3 次失败标 unhealthy
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD python -m scripts.healthcheck || exit 1

# 飞书用 WebSocket 出站，不监听端口；ENV 在 docker-compose 或 systemd 里注入
CMD ["python", "-m", "src.main"]
