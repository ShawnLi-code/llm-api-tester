"""Test case data model."""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class Expected(BaseModel):
    """Assertion spec for a case.

    At least one of status/json_schema/body must be set.
    """

    status: Optional[int] = None
    status_in: Optional[list[int]] = None  # 多个可接受状态码（僵尸验证: [200, 404]）
    json_schema: Optional[dict] = Field(default=None, alias="schema")  # JSON Schema
    body: Optional[dict] = None    # exact body match (deep-equal on subset of keys)
    latency_ms_max: Optional[int] = None


class TestCase(BaseModel):
    """One API test case, declared in YAML."""

    name: str
    method: str = "GET"
    path: str
    headers: dict[str, Any] = Field(default_factory=dict)
    params: dict[str, Any] = Field(default_factory=dict)
    body: Optional[dict[str, Any]] = None
    expected: Expected = Field(default_factory=Expected)
    enabled: bool = True
    tags: list[str] = Field(default_factory=list)


def load_case(data: dict) -> TestCase:
    """Build a TestCase from a raw dict (YAML node)."""
    return TestCase.model_validate(data)
