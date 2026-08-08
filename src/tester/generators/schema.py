"""Generate deterministic TestCase objects from an OpenAPI 3.x document.

P0 contract source: every path+operation becomes a GET/HEAD smoke case with
status expectation derived from the operation's responses. Bodies use the
schema's example if present, else a minimal type-based value.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

import yaml

from tester.core.case import Expected, TestCase

_METHODS = ("get", "post", "put", "patch", "delete", "head", "options")

_TYPE_DEFAULTS: dict[str, Any] = {
    "string": "",
    "integer": 0,
    "number": 0,
    "boolean": False,
    "array": [],
    "object": {},
    "null": None,
}


def load_openapi(path: str | Path) -> dict:
    """Load an OpenAPI/Swagger document from JSON or YAML file."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"OpenAPI spec not found: {p}")
    text = p.read_text(encoding="utf-8")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return yaml.safe_load(text) or {}


def _example_for(schema: dict | None) -> Any:
    """Pick a sample value for a JSON schema (no $ref resolution needed for
    inline `example`/`default`; falls back to type defaults)."""
    if not schema:
        return None
    if "example" in schema:
        return schema["example"]
    if "default" in schema:
        return schema["default"]
    if "enum" in schema:
        return schema["enum"][0]
    t = schema.get("type", "object")
    if t == "object":
        props = schema.get("properties", {})
        return {k: _example_for(v) for k, v in props.items()}
    if t == "array":
        items = schema.get("items")
        return [_example_for(items)] if items else []
    if t == "string" and schema.get("format") == "date-time":
        return "2026-01-01T00:00:00Z"
    if t == "string" and schema.get("format") == "email":
        return "test@example.com"
    return _TYPE_DEFAULTS.get(t, None)


def _body_from_request_body(rb: dict | None) -> Optional[dict]:
    """Extract a sample body from an OpenAPI requestBody."""
    if not rb:
        return None
    content = rb.get("content", {})
    for ctype, media in content.items():
        if ctype in ("application/json", "*/*"):
            return _example_for(media.get("schema"))
    return None


def _status_from_responses(responses: dict) -> Optional[int]:
    """Pick expected status: prefer 2xx, else any explicit code."""
    for code in ("200", "201", "204", "202"):
        if code in responses:
            return int(code)
    for code, val in responses.items():
        if code.isdigit() and 200 <= int(code) < 300:
            return int(code)
    return None


def generate_cases_from_openapi(spec: dict, enabled: bool = True) -> list[TestCase]:
    """Walk paths -> operations, produce smoke cases."""
    cases: list[TestCase] = []
    paths = spec.get("paths", {})
    for path, ops in paths.items():
        if not isinstance(ops, dict):
            continue
        for method in _METHODS:
            op = ops.get(method)
            if not isinstance(op, dict):
                continue
            op_id = op.get("operationId") or f"{method.upper()} {path}"
            body = _body_from_request_body(op.get("requestBody"))
            expected = Expected(status=_status_from_responses(op.get("responses", {})))
            resolved_path = path
            for p in op.get("parameters", []) or []:
                if p.get("in") == "path":
                    s = p.get("schema") or {}
                    val = s.get("example")
                    if val is None:
                        t = s.get("type")
                        val = "1" if t == "integer" else (_example_for(s) if s else "1")
                    resolved_path = resolved_path.replace("{" + p["name"] + "}", str(val))
            cases.append(
                TestCase(
                    name=op_id,
                    method=method.upper(),
                    path=resolved_path,
                    body=body,
                    expected=expected,
                    enabled=enabled,
                )
            )
    return cases

def cases_to_yaml(cases: list[TestCase]) -> str:
    """Serialize cases to the YAML file format load_cases understands."""
    return yaml.safe_dump(
        {"cases": [c.model_dump(by_alias=True, exclude_none=True) for c in cases]},
        allow_unicode=True,
        sort_keys=False,
    )
