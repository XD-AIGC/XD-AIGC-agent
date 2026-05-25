#!/usr/bin/env bash
# xd-poster-gen 海报生成 helper
# 用法：以单独的 JSON 描述任务，从 stdin 读取，或通过 --payload 传文件
#
# 必传参数（JSON）：
#   actionDesc    角色动作描述
#   characters    角色 key 数组，例如 ["aiai","huahua"]  (与 customRefFileIds 二选一)
#
# 可选：
#   textContent   字符串，推荐多行格式：主标题/副标题/元素/色调/补充文案
#   ratio         "2:3" | "9:16" | "1:1" | "3:2" | "16:9"  (默认 2:3)
#   ratios        多比例数组，例如 ["2:3","9:16"]；传了 ratios 则忽略 ratio
#   resolution    "2K" (默认，实验工具当前固定 2K)
#   compositionType  排版构图预设 key（9 选 1，见 SKILL.md）
#   refImageId    参考海报 fileId（先用 upload-reference 上传）
#   cachedStep1FileId  复用上次 Step1 角色白底图 fileId（跳过 Step1）
#   customRefFileIds   [fileId, ...] 自定义角色参考图（上传后得到）
#
# 输出（stdout，JSON）：
#   { status, v2JobId, images: [{fileId, url}], steps, error? }
set -euo pipefail

BASE="${POSTER_API_BASE:-http://10.102.80.15/xd-poster-studio-v2}"
TIMEOUT="${POSTER_POLL_TIMEOUT:-300}"   # 秒
INTERVAL="${POSTER_POLL_INTERVAL:-3}"
CONNECT_TIMEOUT="${POSTER_CONNECT_TIMEOUT:-5}"

payload=""
if [ "${1:-}" = "--payload" ] && [ -n "${2:-}" ]; then
  payload="$(cat "$2")"
else
  payload="$(cat)"
fi

if [ -z "$payload" ]; then
  echo "ERROR: empty payload" >&2
  exit 2
fi

# 启动 v2 生成
if ! resp="$(curl -fsS --connect-timeout "$CONNECT_TIMEOUT" -X POST "$BASE/api/generate-v2" \
  -H "Content-Type: application/json" \
  -d "$payload" 2>/tmp/xd-poster-gen-curl.err)"; then
  err="$(cat /tmp/xd-poster-gen-curl.err 2>/dev/null || true)"
  echo "ERROR: cannot reach poster backend: $BASE/api/generate-v2" >&2
  if [ -n "$err" ]; then echo "$err" >&2; fi
  echo "请确认当前 Agent 运行环境能访问公司内网/VPN，或设置 POSTER_API_BASE 为可访问的代理地址。" >&2
  exit 3
fi

job_id="$(printf '%s' "$resp" | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('v2JobId') or '')" 2>/dev/null || true)"

if [ -z "$job_id" ]; then
  echo "ERROR: generate-v2 failed: $resp" >&2
  exit 3
fi

# 轮询
deadline=$(( $(date +%s) + TIMEOUT ))
while :; do
  if ! poll="$(curl -fsS --connect-timeout "$CONNECT_TIMEOUT" "$BASE/api/poll-v2/$job_id" 2>/tmp/xd-poster-gen-curl.err)"; then
    err="$(cat /tmp/xd-poster-gen-curl.err 2>/dev/null || true)"
    echo "ERROR: cannot poll poster backend: $BASE/api/poll-v2/$job_id" >&2
    if [ -n "$err" ]; then echo "$err" >&2; fi
    exit 5
  fi
  status="$(printf '%s' "$poll" | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('status') or '')" 2>/dev/null || true)"

  case "$status" in
    completed)
      printf '%s\n' "$poll"
      exit 0
      ;;
    failed)
      printf '%s\n' "$poll"
      exit 4
      ;;
    "")
      echo "ERROR: poll returned no status: $poll" >&2
      exit 5
      ;;
  esac

  if [ "$(date +%s)" -ge "$deadline" ]; then
    echo "ERROR: poll timeout after ${TIMEOUT}s. Last: $poll" >&2
    exit 6
  fi
  sleep "$INTERVAL"
done
