#!/usr/bin/env bash
# 上传 Skill 内置角色三视图参考图，输出可直接放入 generate-v2 的 customRefFileIds。
# 用法：upload-local-character-refs.sh aiai annie
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
CHAR_TSV="$ROOT_DIR/references/characters.tsv"
REF_DIR="$ROOT_DIR/assets/character-refs"

if [ "$#" -lt 1 ]; then
  echo "ERROR: usage: $0 <character-key-or-chinese-name> [more...]" >&2
  exit 2
fi

resolve_key() {
  local query="$1"
  python3 - "$CHAR_TSV" "$query" <<'PY'
import csv
import sys

path, query = sys.argv[1], sys.argv[2]
with open(path, newline="", encoding="utf-8") as f:
    rows = list(csv.DictReader(f, delimiter="\t"))
for row in rows:
    if query in (row["key"], row["中文名"]):
        print(row["key"])
        raise SystemExit(0)
raise SystemExit(1)
PY
}

tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT

for input in "$@"; do
  if ! key="$(resolve_key "$input")"; then
    echo "ERROR: unknown character: $input" >&2
    exit 2
  fi
  image="$REF_DIR/${key}_ref.png"
  if [ ! -f "$image" ]; then
    echo "ERROR: missing local character three-view asset: $image" >&2
    exit 2
  fi
  resp="$("$SCRIPT_DIR/upload-reference.sh" "$image")"
  file_id="$(printf '%s' "$resp" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("fileId",""))')"
  if [ -z "$file_id" ]; then
    echo "ERROR: upload returned no fileId: $resp" >&2
    exit 3
  fi
  printf '%s\t%s\t%s\n' "$key" "$image" "$file_id" >> "$tmp"
done

python3 - "$tmp" "$CHAR_TSV" <<'PY'
import csv
import json
import sys

uploads_path, chars_path = sys.argv[1], sys.argv[2]
names = {}
with open(chars_path, newline="", encoding="utf-8") as f:
    for row in csv.DictReader(f, delimiter="\t"):
        names[row["key"]] = row["中文名"]

items = []
with open(uploads_path, encoding="utf-8") as f:
    for line in f:
        key, image, file_id = line.rstrip("\n").split("\t")
        items.append({"key": key, "name": names.get(key, key), "asset": image, "fileId": file_id})

print(json.dumps({
    "customRefFileIds": [item["fileId"] for item in items],
    "items": items,
}, ensure_ascii=False))
PY
