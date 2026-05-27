#!/usr/bin/env python3
"""Redact Feishu/toolbox identifiers from transcript JSON on stdin.

Usage:
  python tests/fixtures/transcripts/redact.py < raw.json > redacted.json
"""

from __future__ import annotations

import re
import sys


PATTERNS = [
    (re.compile(r"\bou_[A-Za-z0-9_]+\b"), "USER"),
    (re.compile(r"\bom_[A-Za-z0-9_]+\b"), "MSG"),
    (re.compile(r"\boc_[A-Za-z0-9_]+\b"), "CHAT"),
    (re.compile(r"\bfile_[A-Za-z0-9_]+\b"), "FILE"),
]


def redact_text(text: str) -> str:
    for pattern, label in PATTERNS:
        seen: dict[str, str] = {}

        def repl(match: re.Match[str]) -> str:
            value = match.group(0)
            if value not in seen:
                seen[value] = f"<{label}_{len(seen) + 1}>"
            return seen[value]

        text = pattern.sub(repl, text)
    return text


if __name__ == "__main__":
    sys.stdout.write(redact_text(sys.stdin.read()))
