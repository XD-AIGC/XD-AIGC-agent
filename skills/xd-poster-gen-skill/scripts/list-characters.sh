#!/usr/bin/env bash
# 列出可选角色。优先请求后端；后端不可达时使用 Skill 内置中文清单。
set -euo pipefail

BASE="${POSTER_API_BASE:-http://10.102.80.15/xd-poster-studio-v2}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
FALLBACK_TSV="$ROOT_DIR/references/characters.tsv"
CONNECT_TIMEOUT="${POSTER_CONNECT_TIMEOUT:-3}"
LIST_TIMEOUT="${POSTER_LIST_TIMEOUT:-8}"

print_remote() {
  python3 -c '
import sys, json
data = json.load(sys.stdin)
items = list(data.values()) if isinstance(data, dict) else list(data)
def group_of(ch):
    key = ch.get("key") or ch.get("id") or ""
    if key.startswith("cat_"):
        return "猫咪"
    if key.startswith("dog_"):
        return "狗狗"
    return "人物"
order = {"人物": 0, "猫咪": 1, "狗狗": 2}
items.sort(key=lambda ch: (order.get(group_of(ch), 9), ch.get("name") or ch.get("key") or ""))
current = None
for ch in items:
    key = ch.get("key") or ch.get("id") or ""
    name = ch.get("name") or key
    desc = ch.get("fusionDescription") or ch.get("fusionDesc") or ch.get("description") or ""
    group = group_of(ch)
    if group != current:
        print(f"\n【{group}】")
        current = group
    print(f"- {name}（{key}）：{desc[:80]}")
'
}

print_fallback() {
  python3 - "$FALLBACK_TSV" <<'PY'
import csv
import sys

path = sys.argv[1]
with open(path, newline="", encoding="utf-8") as f:
    rows = list(csv.DictReader(f, delimiter="\t"))

current = None
for row in rows:
    group = row["group"]
    if group != current:
        print(f"\n【{group}】")
        current = group
    desc = row["中文描述"]
    print(f"- {row['中文名']}（{row['key']}）：{desc[:80]}")
PY
}

if [ "${POSTER_OFFLINE:-0}" != "1" ]; then
  if remote_json="$(curl -fsS --connect-timeout "$CONNECT_TIMEOUT" --max-time "$LIST_TIMEOUT" "$BASE/api/characters" 2>/dev/null)"; then
    if printf '%s' "$remote_json" | print_remote; then
      exit 0
    fi
  fi
fi

if [ -f "$FALLBACK_TSV" ]; then
  if [ "${POSTER_OFFLINE:-0}" = "1" ]; then
    echo "（离线模式：以下为 Skill 内置中文角色清单）"
  else
    echo "（后端角色接口不可达，以下为 Skill 内置中文角色清单）"
  fi
  print_fallback
else
  echo "ERROR: cannot fetch characters and fallback file is missing: $FALLBACK_TSV" >&2
  exit 2
fi
