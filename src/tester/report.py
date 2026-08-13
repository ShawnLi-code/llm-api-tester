"""Report generation: summary line + JSON dump."""
from __future__ import annotations

import json
import time
from collections.abc import Iterable
from pathlib import Path

from tester.core.runner import ReportEntry


def summarize(entries: Iterable[ReportEntry]) -> str:
    """Human summary: `10 passed, 2 failed`."""
    entries = list(entries)
    passed = sum(1 for e in entries if e.passed)
    failed = len(entries) - passed
    total = len(entries)
    if total == 0:
        return "0 tests collected"
    return f"{passed} passed, {failed} failed (total {total})"


def write_json_report(entries: list[ReportEntry], path: str | Path) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "summary": summarize(entries),
        "results": [e.to_dict() for e in entries],
    }
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return p
