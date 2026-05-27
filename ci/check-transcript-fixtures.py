#!/usr/bin/env python3
"""Validate committed transcript fixtures are safe to share in git."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path


FIXTURE_DIR = Path("tests/fixtures/transcripts")
RAW_ID_RE = re.compile(r"\b(?:ou|om|oc)_[A-Za-z0-9_]+\b|\bfile_[A-Za-z0-9_]+\b")


def main() -> int:
    failures: list[str] = []
    for path in sorted(FIXTURE_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            failures.append(f"{path}: invalid JSON: {exc}")
            continue
        raw = json.dumps(data, ensure_ascii=False)
        match = RAW_ID_RE.search(raw)
        if match:
            failures.append(f"{path}: contains raw id {match.group(0)!r}")

    if failures:
        for failure in failures:
            print(failure, file=sys.stderr)
        return 1
    print("OK: transcript fixtures are redacted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
