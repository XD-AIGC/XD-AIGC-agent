#!/usr/bin/env bash
# 打印 Skill 内置的离线选项：brief 字段、排版构图、比例、清晰度。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cat "$ROOT_DIR/references/options.md"
