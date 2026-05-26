#!/usr/bin/env bash
# 每 5 分钟 git pull XD-AIGC-skills，watcher 自动检测变化 hot-reload bot
# 安装：
#   sudo cp deploy/cron-pull-skills.sh /usr/local/bin/
#   sudo chmod +x /usr/local/bin/cron-pull-skills.sh
#   echo '*/5 * * * * ubuntu /usr/local/bin/cron-pull-skills.sh >> /var/log/xd-aigc-skills-pull.log 2>&1' \
#     | sudo tee /etc/cron.d/xd-aigc-skills-pull
set -e
cd /AIGC_Group/XD-AIGC-skills
out=$(git pull --ff-only 2>&1)
if ! echo "$out" | grep -q "Already up to date"; then
    echo "[$(date '+%F %T')] skills updated: $(echo "$out" | tail -1)"
fi
