#!/bin/bash
set -e

BANNED=(
  "message\.create[^_]"
  "message\.create_urgent"
  "chat\.create"
  "chat_members"
  "lark_oapi\.api\.docx"
  "lark_oapi\.api\.drive"
  "lark_oapi\.api\.bitable"
  "lark_oapi\.api\.calendar"
  "lark_oapi\.api\.contact"
  "lark_oapi\.api\.mail"
  "lark_oapi\.api\.wiki"
)

FOUND=0
for pattern in "${BANNED[@]}"; do
  if grep -rEn "$pattern" src/ 2>/dev/null; then
    echo "BANNED API found: $pattern"
    FOUND=1
  fi
done

if [ $FOUND -eq 1 ]; then
  echo "CI FAILED: banned API usage detected."
  exit 1
fi

echo "OK: No banned APIs found."
