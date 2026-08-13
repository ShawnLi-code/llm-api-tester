"""Test case data model."""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class Expected(BaseModel):
    """Assertion spec for a case.

    At least one of status/json_schema/body must be set.
    """

    status: int | None = None
    status_in: list[int] | None = None  # 多个可接受状态码（僵尸验证: [200, 404]）
    json_schema: dict | None = Field(default=None, alias="schema")  # JSON Schema
    body: dict | None = None    # exact body match (deep-equal on subset of keys)
    latency_ms_max: int | None = None  # 超时则判失败
    # None -> 使用 RunnerConfig.unwrap_data 全局默认；False 时对 schema/body 断言不做 data 层解包
    unwrap_data: bool | None = None


class TestCase(BaseModel):
    """One API test case, declared in YAML."""

    name: str
    method: str = "GET"
    path: str
    headers: dict[str, Any] = Field(default_factory=dict)
    params: dict[str, Any] = Field(default_factory=dict)
    body: dict[str, Any] | None = None
    expected: Expected = Field(default_factory=Expected)
    enabled: bool = True
    tags: list[str] = Field(default_factory=list)


def load_case(data: dict) -> TestCase:
    """Build a TestCase from a raw dict (YAML node)."""
    return TestCase.model_validate(data)
