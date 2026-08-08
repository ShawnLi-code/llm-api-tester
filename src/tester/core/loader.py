"""YAML test case loading."""
from __future__ import annotations

from pathlib import Path

import yaml

from .case import TestCase


def load_cases(yaml_path: str | Path) -> list[TestCase]:
    """Load TestCase list from a YAML file.

    File layout:
        cases:
          - name: ...
            method: GET
            path: /health
            expected: {status: 200}
          ...

    Raises FileNotFoundError if the file is missing.
    Returns [] for empty/missing `cases` key.
    """
    p = Path(yaml_path)
    if not p.exists():
        raise FileNotFoundError(f"test case file not found: {p}")
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    items = raw.get("cases") or []
    cases = [TestCase.model_validate(it) for it in items]
    return [c for c in cases if c.enabled]


def load_cases_skip_disabled(yaml_path: str | Path) -> list[TestCase]:
    """Same as load_cases but keeps disabled ones out silently."""
    return load_cases(yaml_path)
