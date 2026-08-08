"""HTTP execution layer (httpx-based, sync-friendly)."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx

from .case import TestCase
from .contract import validate_response


@dataclass
class ReportEntry:
    """One executed case's result."""

    name: str
    method: str
    url: str
    status_code: Optional[int] = None
    passed: bool = False
    reason: str = ""
    latency_ms: float = 0.0
    response_body: Any = None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "method": self.method,
            "url": self.url,
            "status_code": self.status_code,
            "passed": self.passed,
            "reason": self.reason,
            "latency_ms": round(self.latency_ms, 2),
        }


@dataclass
class RunnerConfig:
    base_url: str = "http://127.0.0.1:8000"
    timeout: float = 10.0
    retries: int = 1
    headers: dict[str, str] = field(default_factory=dict)
    strict_status: bool = False  # if True, only expected.status counts as pass


class Runner:
    """Executes TestCase list against base_url, returns ReportEntry list."""

    def __init__(self, config: RunnerConfig | None = None, client: httpx.Client | None = None):
        self.config = config or RunnerConfig()
        self._client = client

    def _get_client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=self.config.timeout)
        return self._client

    def run_one(self, case: TestCase) -> ReportEntry:
        url = self.config.base_url.rstrip("/") + case.path
        # 用例级 headers 覆盖全局；值为空串/None 表示移除该 header（如权限用例去掉 Authorization）
        headers = {**self.config.headers, **case.headers}
        headers = {k: v for k, v in headers.items() if v not in ("", None)}
        client = self._get_client()
        last_err: Optional[Exception] = None
        for attempt in range(self.config.retries + 1):
            try:
                start = time.perf_counter()
                resp = client.request(
                    case.method,
                    url,
                    params=case.params or None,
                    json=case.body if case.method.upper() not in ("GET", "HEAD") else None,
                    headers=headers or None,
                )
                latency = (time.perf_counter() - start) * 1000
                payload: Any = None
                try:
                    payload = resp.json()
                except ValueError:
                    payload = resp.text
                verdict, errors = validate_response(resp.status_code, payload, case.expected.model_dump(by_alias=True))
                return ReportEntry(
                    name=case.name,
                    method=case.method,
                    url=url,
                    status_code=resp.status_code,
                    passed=verdict == "passed",
                    reason="; ".join(errors) if errors else "",
                    latency_ms=latency,
                    response_body=payload,
                )
            except httpx.HTTPError as e:
                last_err = e
            except Exception as e:  # noqa: BLE001 - surface everything as failure
                last_err = e
        return ReportEntry(
            name=case.name,
            method=case.method,
            url=url,
            passed=False,
            reason=f"{type(last_err).__name__}: {last_err}" if last_err else "unknown error",
        )

    def run_all(self, cases: list[TestCase]) -> list[ReportEntry]:
        return [self.run_one(c) for c in cases]


def run_tests(cases: list[TestCase], config: RunnerConfig | None = None) -> list[ReportEntry]:
    """Convenience: build runner, run, close client."""
    runner = Runner(config)
    try:
        return runner.run_all(cases)
    finally:
        if runner._client is not None:
            runner._client.close()
