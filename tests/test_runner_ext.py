"""Extended runner tests: latency assert, unwrap config, parallel, retries, loader edge cases."""
import threading

import pytest

from tester.core.case import TestCase
from tester.core.contract import validate_response
from tester.core.loader import load_cases
from tester.core.runner import ReportEntry, Runner, RunnerConfig, run_tests
from tester.demo_server import serve_in_thread
from tests.test_core import EXAMPLES

PORT = 8124  # 与 test_e2e 的 8123 错开，避免全量跑时端口复用冲突


@pytest.fixture(scope="module")
def server_unused():
    srv = serve_in_thread(port=PORT)
    yield
    srv.shutdown()
    srv.server_close()  # 释放端口，否则下一个 module 的 server 起不来


# ---------- latency assertion ----------

def test_latency_max_fails_on_slow(server_unused):
    case = TestCase(name="slow", method="GET", path="/health",
                    expected={"status": 200, "latency_ms_max": 1})
    entries = run_tests([case], RunnerConfig(base_url=f"http://127.0.0.1:{PORT}", retries=0))
    assert not entries[0].passed
    assert "latency" in entries[0].reason


def test_latency_max_passes_on_fast(server_unused):
    case = TestCase(name="fast", method="GET", path="/health",
                    expected={"status": 200, "latency_ms_max": 60_000})
    entries = run_tests([case], RunnerConfig(base_url=f"http://127.0.0.1:{PORT}", retries=0))
    assert entries[0].passed


# ---------- unwrap_data configurability ----------

def test_validate_response_unwrap_on():
    payload = {"code": 0, "msg": "ok", "data": {"id": 1, "name": "alice"}}
    verdict, _ = validate_response(200, payload, {"body": {"name": "alice"}}, unwrap=True)
    assert verdict == "passed"
    verdict, _ = validate_response(200, payload, {"body": {"data": {"name": "alice"}}}, unwrap=True)
    assert verdict == "failed"  # data 层已解包，不能再找 data.name


def test_validate_response_unwrap_off():
    payload = {"code": 0, "msg": "ok", "data": {"id": 1, "name": "alice"}}
    # 未解包：body 顶层子集直接匹配外层
    verdict, _ = validate_response(200, payload, {"body": {"code": 0, "msg": "ok"}}, unwrap=False)
    assert verdict == "passed"
    # 未解包：schema 作用于整个 payload
    schema = {"type": "object", "required": ["code", "data"],
              "properties": {"code": {"type": "integer"}, "data": {"type": "object"}}}
    verdict, _ = validate_response(200, payload, {"schema": schema}, unwrap=False)
    assert verdict == "passed"
    # 未解包：外层没有 name 字段 -> 失败
    verdict, _ = validate_response(200, payload, {"body": {"name": "alice"}}, unwrap=False)
    assert verdict == "failed"


def test_case_level_unwrap_overrides_global(server_unused):
    # 用例级 unwrap_data=False 覆盖全局默认 True
    case = TestCase(name="no-unwrap", method="GET", path="/config",
                    expected={"status": 200, "body": {"title": "Demo Config"}, "unwrap_data": False})
    entries = run_tests([case], RunnerConfig(base_url=f"http://127.0.0.1:{PORT}", retries=0))
    assert entries[0].passed  # /config 返回裸 JSON，无需解包


# ---------- parallel execution ----------

def test_parallel_matches_sequential(server_unused):
    cases = load_cases(EXAMPLES / "basic.yaml")
    seq = run_tests(cases, RunnerConfig(base_url=f"http://127.0.0.1:{PORT}", retries=0, max_workers=1))
    par = run_tests(cases, RunnerConfig(base_url=f"http://127.0.0.1:{PORT}", retries=0, max_workers=4))
    assert [e.passed for e in seq] == [e.passed for e in par]
    assert [e.status_code for e in seq] == [e.status_code for e in par]


def test_parallel_reports_all_results(server_unused):
    cases = load_cases(EXAMPLES / "basic.yaml")
    entries = run_tests(cases, RunnerConfig(base_url=f"http://127.0.0.1:{PORT}", retries=0, max_workers=8))
    assert len(entries) == len(cases)
    assert all(isinstance(e, ReportEntry) for e in entries)


# ---------- retries / network failure ----------

def test_network_failure_reports_env_reason():
    case = TestCase(name="unreachable", method="GET", path="/x")
    entries = run_tests([case], RunnerConfig(base_url="http://127.0.0.1:9", retries=0, timeout=2))
    assert not entries[0].passed
    assert entries[0].status_code is None
    assert entries[0].reason  # e.g. ConnectError: ...


def test_retries_still_fails_after_all_attempts():
    case = TestCase(name="unreachable", method="GET", path="/x")
    entries = run_tests([case], RunnerConfig(base_url="http://127.0.0.1:9", retries=2, timeout=2))
    assert not entries[0].passed


# ---------- loader edge cases ----------

def test_loader_empty_yaml(tmp_path):
    p = tmp_path / "empty.yaml"
    p.write_text("", encoding="utf-8")
    assert load_cases(p) == []


def test_loader_no_cases_key(tmp_path):
    p = tmp_path / "no_cases.yaml"
    p.write_text("foo: bar\n", encoding="utf-8")
    assert load_cases(p) == []


def test_loader_invalid_yaml_raises(tmp_path):
    p = tmp_path / "bad.yaml"
    p.write_text(": : :\n", encoding="utf-8")
    with pytest.raises(Exception):
        load_cases(p)


# ---------- thread-safety smoke ----------

def test_runner_reusable_across_threads(server_unused):
    runner = Runner(RunnerConfig(base_url=f"http://127.0.0.1:{PORT}", retries=0))
    results = {}

    def work(name):
        case = TestCase(name=name, method="GET", path="/health")
        results[name] = runner.run_one(case).passed

    threads = [threading.Thread(target=work, args=(f"t{i}",)) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert all(results.values())
