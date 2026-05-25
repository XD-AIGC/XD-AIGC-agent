#!/usr/bin/env bash
# 上传参考图（参考海报排版图、或自定义角色参考图）。
# 用法：upload-reference.sh <本地图片绝对路径>
# 输出：{ fileId, localPath } JSON
set -euo pipefail

BASE="${POSTER_API_BASE:-http://10.102.80.15/xd-poster-studio-v2}"
CONNECT_TIMEOUT="${POSTER_CONNECT_TIMEOUT:-5}"
img="${1:-}"

if [ -z "$img" ] || [ ! -f "$img" ]; then
  echo "ERROR: usage: $0 <image-path>" >&2
  exit 2
fi

ext="${img##*.}"
ext="$(printf '%s' "$ext" | tr '[:upper:]' '[:lower:]')"
case "$ext" in
  jpg|jpeg|png|webp|gif) ;;
  *) echo "ERROR: unsupported ext .$ext (need jpg/jpeg/png/webp/gif)" >&2; exit 2 ;;
esac

if ! resp="$(curl -fsS --connect-timeout "$CONNECT_TIMEOUT" -X POST "$BASE/api/upload-reference" \
  -H "x-file-ext: $ext" \
  -H "Content-Type: application/octet-stream" \
  --data-binary "@$img")"; then
  echo "ERROR: cannot reach poster backend: $BASE/api/upload-reference" >&2
  echo "请确认当前 Agent 运行环境能访问公司内网/VPN，或设置 POSTER_API_BASE 为可访问的代理地址。" >&2
  exit 3
fi

file_id="$(printf '%s' "$resp" | python3 -c 'import json,sys; print((json.load(sys.stdin).get("fileId") or ""))' 2>/dev/null || true)"
if [ -z "$file_id" ]; then
  echo "ERROR: upload-reference did not return fileId. Raw response:" >&2
  echo "$resp" >&2
  echo "当前 V2 生成需要 fileId 才能作为 refImageId/customRefFileIds 使用；请检查线上后端是否为最新版本。" >&2
  exit 4
fi

printf '%s\n' "$resp"
