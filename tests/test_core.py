"""Unit tests: case model, loader, contract validation, openapi generation."""
import json
from pathlib import Path

import pytest

from tester.core.case import TestCase
from tester.core.contract import validate_case_body, validate_response
from tester.core.loader import load_cases
from tester.generators.schema import cases_to_yaml, generate_cases_from_openapi, load_openapi

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
OPENAPI = EXAMPLES / "openapi.json"


def test_load_cases_from_yaml():
    cases = load_cases(EXAMPLES / "basic.yaml")
    assert len(cases) == 8
    assert all(isinstance(c, TestCase) for c in cases)
    names = [c.name for c in cases]
    assert "health check" in names
    assert cases[0].expected.status == 200


def test_load_cases_missing_file():
    with pytest.raises(FileNotFoundError):
        load_cases(EXAMPLES / "nope.yaml")


def test_load_cases_skips_disabled():
    p = EXAMPLES / "tmp_disabled.yaml"
    p.write_text(
        "cases:\n"
        "  - name: enabled-case\n    method: GET\n    path: /x\n    expected: {status: 200}\n"
        "  - name: disabled-case\n    method: GET\n    path: /y\n    enabled: false\n    expected: {status: 200}\n",
        encoding="utf-8",
    )
    try:
        cases = load_cases(p)
        assert [c.name for c in cases] == ["enabled-case"]
    finally:
        p.unlink()


def test_validate_case_body_passed():
    schema = {
        "type": "object",
        "required": ["id", "name"],
        "properties": {"id": {"type": "integer"}, "name": {"type": "string"}},
    }
    verdict, errors = validate_case_body({"id": 1, "name": "a"}, schema)
    assert verdict == "passed"
    assert not errors


def test_validate_case_body_failed_type():
    schema = {"type": "object", "properties": {"id": {"type": "integer"}}}
    verdict, errors = validate_case_body({"id": "not-an-int"}, schema)
    assert verdict == "failed"
    assert errors


def test_validate_case_body_missing_schema():
    verdict, errors = validate_case_body({"a": 1}, None)
    assert verdict == "missing_schema"


def test_validate_response_status_mismatch():
    verdict, errors = validate_response(500, {}, {"status": 200})
    assert verdict == "failed"
    assert "500" in errors[0]


def test_validate_response_body_subset():
    verdict, errors = validate_response(200, {"status": "ok", "extra": 1}, {"body": {"status": "ok"}})
    assert verdict == "passed"


def test_validate_response_schema():
    verdict, errors = validate_response(200, {"items": [], "total": 1}, {
        "schema": {"type": "object", "required": ["items", "total"]}
    })
    assert verdict == "passed"


def test_generate_cases_from_openapi():
    spec = load_openapi(OPENAPI)
    cases = generate_cases_from_openapi(spec)
    assert len(cases) == 4  # health GET, users GET+POST, users/{id} GET
    by_op = {c.name: c for c in cases}
    assert by_op["createUser"].method == "POST"
    assert by_op["createUser"].body == {"name": "alice", "age": 30}
    assert by_op["createUser"].expected.status == 201
    assert by_op["listUsers"].expected.status == 200


def test_cases_to_yaml_roundtrip():
    spec = load_openapi(OPENAPI)
    cases = generate_cases_from_openapi(spec)
    text = cases_to_yaml(cases)
    import yaml

    reloaded = yaml.safe_load(text)
    assert len(reloaded["cases"]) == 4


def test_spec_has_components_schema():
    spec = json.loads(OPENAPI.read_text(encoding="utf-8"))
    assert "User" in spec["components"]["schemas"]
