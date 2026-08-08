"""Contract validation: validate request body / response against JSON Schema.

P0 ground truth: the OpenAPI spec. Local $ref resolution is supported for
specs embedded in a single document.
"""
from __future__ import annotations

import json
import re
from typing import Any

import jsonschema
from jsonschema import Draft202012Validator

_REF_RE = re.compile(r"^#/components/schemas/(.+)$")


def _resolve_refs(schema: dict, root: dict, seen: set | None = None) -> dict:
    """Inline local $refs (#/components/schemas/...) recursively."""
    seen = seen or set()
    if not isinstance(schema, dict):
        return schema
    out: dict[str, Any] = {}
    for k, v in schema.items():
        if k == "$ref" and isinstance(v, str):
            m = _REF_RE.match(v)
            if m and m.group(1) not in seen:
                seen.add(m.group(1))
                target = root.get("components", {}).get("schemas", {}).get(m.group(1))
                if target:
                    out.update(_resolve_refs(dict(target), root, seen))
                    continue
            out[k] = v
        elif isinstance(v, dict):
            out[k] = _resolve_refs(v, root, seen)
        elif isinstance(v, list):
            out[k] = [_resolve_refs(i, root, seen) if isinstance(i, dict) else i for i in v]
        else:
            out[k] = v
    return out


def validate_case_body(body: Any, schema: dict | None, root: dict | None = None) -> tuple[str, list[str]]:
    """Validate `body` against `schema`.

    Returns (verdict, errors) where verdict in {"passed", "failed", "missing_schema"}.
    """
    if not schema:
        return "missing_schema", ["no schema provided"]
    resolved = _resolve_refs(schema, root or {})
    try:
        Draft202012Validator(resolved).validate(body)
        return "passed", []
    except jsonschema.ValidationError as e:
        return "failed", [e.message]


def validate_response(status_code: int, payload: Any, expected: Any) -> tuple[str, list[str]]:
    """Validate an HTTP response against a compact expectation.

    expected may be:
      - {"status": int}                          -> status match
      - {"schema": {...}}                        -> JSON Schema on payload
      - {"body": {...}}                          -> subset deep-equal on payload
    Returns (verdict, errors), verdict in {"passed", "failed", "missing"}.
    """
    if not isinstance(expected, dict):
        return "missing", ["empty expectation"]
    errors: list[str] = []
    ok = True
    if expected.get("status") is not None and status_code != expected["status"]:
        ok = False
        errors.append(f"status {status_code} != expected {expected['status']}")
    schema = expected.get("schema")
    if schema:
        verdict, errs = validate_case_body(payload, schema)
        if verdict == "failed":
            ok = False
            errors.extend(errs)
    body = expected.get("body")
    if body:
        if not isinstance(payload, dict):
            ok = False
            errors.append(f"payload not an object: {type(payload).__name__}")
        else:
            for k, v in body.items():
                if k not in payload:
                    ok = False
                    errors.append(f"missing key {k!r}")
                elif payload[k] != v:
                    ok = False
                    errors.append(f"key {k!r}: {payload[k]!r} != {v!r}")
    return ("passed" if ok else "failed", errors)


def validate_case(case, schema: dict | None, root: dict | None = None) -> tuple[str, list[str]]:
    """Validate a TestCase's body against an OpenAPI-derived schema."""
    return validate_case_body(case.body, schema, root)
