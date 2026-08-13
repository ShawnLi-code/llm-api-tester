"""HTTP execution layer (httpx-based, sync-friendly).

Features:
  - sequential or thread-pool parallel execution (RunnerConfig.max_workers)
  - per-case retries, timeout, latency assertion
  - `unwrap_data` auto-unwraps {code, msg, data} wrapper (configurable)
"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

import httpx

from .case import TestCase
from .contract import validate_response


@dataclass
class ReportEntry:
    """One executed case's result."""

    name: str
    method: str
    url: str
    status_code: int | None = None
    passed: bool = False
    reason: str = ""
    latency_ms: float = 0.0
    response_body: Any = None
    request_body: Any = None  # for --verbose / debugging
    request_params: Any = None

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
    unwrap_data: bool = True  # global default: unwrap {code,msg,data} for schema/body asserts
    max_workers: int = 1  # >1 enables thread-pool parallel execution


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
        last_err: Exception | None = None
        unwrap = case.expected.unwrap_data
        if unwrap is None:
            unwrap = self.config.unwrap_data
        for _ in range(self.config.retries + 1):
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
                verdict, errors = validate_response(
                    resp.status_code, payload, case.expected.model_dump(by_alias=True), unwrap=unwrap
                )
                if case.expected.latency_ms_max is not None and latency > case.expected.latency_ms_max:
                    verdict = "failed"
                    errors = [*errors, f"latency {latency:.0f}ms > max {case.expected.latency_ms_max}ms"]
                return ReportEntry(
                    name=case.name,
                    method=case.method,
                    url=url,
                    status_code=resp.status_code,
                    passed=verdict == "passed",
                    reason="; ".join(errors) if errors else "",
                    latency_ms=latency,
                    response_body=payload,
                    request_body=case.body,
                    request_params=case.params,
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
            request_body=case.body,
            request_params=case.params,
        )

    def run_all(self, cases: list[TestCase]) -> list[ReportEntry]:
        if self.config.max_workers > 1 and len(cases) > 1:
            self._get_client()  # 预创建共享 client（httpx.Client 线程安全）
            with ThreadPoolExecutor(max_workers=self.config.max_workers) as ex:
                return list(ex.map(self.run_one, cases))
        return [self.run_one(c) for c in cases]


def run_tests(cases: list[TestCase], config: RunnerConfig | None = None) -> list[ReportEntry]:
    """Convenience: build runner, run, close client."""
    runner = Runner(config)
    try:
        return runner.run_all(cases)
    finally:
        if runner._client is not None:
            runner._client.close()
