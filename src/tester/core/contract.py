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


def validate_fields_loose(payload: Any, required: list[str]) -> tuple[str, list[str]]:
    """宽松字段断言：required 字段在顶层或 data 层存在即通过。

    兼容真实后端 {code, msg, data} 包装 + Excel 把 code/msg 与业务字段混写的场景。
    只做存在性检查，不做类型校验。
    """
    if not isinstance(payload, dict):
        return "failed", [f"payload not an object: {type(payload).__name__}"]
    data = payload.get("data") if isinstance(payload.get("data"), dict) else None
    missing = [f for f in required if f not in payload and (data is None or f not in data)]
    if missing:
        return "failed", [f"missing fields: {', '.join(missing)}"]
    return "passed", []


def _unwrap_data(payload: Any) -> Any:
    """真实后端统一 {code, msg, data} 包装：字段断言作用到 data 层。"""
    if isinstance(payload, dict) and "data" in payload and set(payload) <= {"code", "msg", "data"}:
        return payload["data"]
    return payload


def validate_response(status_code: int, payload: Any, expected: Any) -> tuple[str, list[str]]:
    """Validate an HTTP response against a compact expectation.

    expected may be:
      - {"status": int}                          -> status match
      - {"schema": {...}}                        -> JSON Schema on payload
      - {"body": {...}}                          -> subset deep-equal on payload
    Returns (verdict, errors), verdict in {"passed", "failed", "missing"}.

    兼容真实后端 {code, msg, data} 包装：schema/body 断言自动作用到 data 层
    （顶层存在同名 key 时优先顶层）。
    """
    if not isinstance(expected, dict):
        return "missing", ["empty expectation"]
    errors: list[str] = []
    ok = True
    if expected.get("status") is not None and status_code != expected["status"]:
        ok = False
        errors.append(f"status {status_code} != expected {expected['status']}")
    if expected.get("status_in") is not None and status_code not in expected["status_in"]:
        ok = False
        errors.append(f"status {status_code} not in expected {expected['status_in']}")
    schema = expected.get("schema")
    if schema:
        required = schema.get("required")
        # 纯字段存在性断言（Excel 关键字段）-> 宽松跨层校验
        if required and not schema.get("properties") and schema.get("type") == "object":
            verdict, errs = validate_fields_loose(payload, required)
            if verdict == "failed":
                ok = False
                errors.extend(errs)
        else:
            target = _unwrap_data(payload)
            verdict, errs = validate_case_body(target, schema)
            if verdict == "failed":
                ok = False
                errors.extend(errs)
    body = expected.get("body")
    if body:
        target = _unwrap_data(payload)
        if not isinstance(target, dict):
            ok = False
            errors.append(f"payload not an object: {type(target).__name__}")
        else:
            for k, v in body.items():
                if k not in target:
                    ok = False
                    errors.append(f"missing key {k!r}")
                elif target[k] != v:
                    ok = False
                    errors.append(f"key {k!r}: {target[k]!r} != {v!r}")
    return ("passed" if ok else "failed", errors)


def validate_case(case, schema: dict | None, root: dict | None = None) -> tuple[str, list[str]]:
    """Validate a TestCase's body against an OpenAPI-derived schema."""
    return validate_case_body(case.body, schema, root)
