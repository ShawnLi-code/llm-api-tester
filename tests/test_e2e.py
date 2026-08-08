"""E2E: run YAML cases against the in-process demo server; assert report."""
import pytest

from tester.core.loader import load_cases
from tester.core.runner import Runner, RunnerConfig, run_tests
from tester.demo_server import serve_in_thread
from tester.generators.schema import generate_cases_from_openapi, load_openapi
from tester.report import summarize, write_json_report
from tests.test_core import EXAMPLES, OPENAPI


@pytest.fixture(scope="module")
def server():
    srv = serve_in_thread(port=8123)
    yield srv
    srv.shutdown()


def test_e2e_basic_cases_pass(server):
    cases = load_cases(EXAMPLES / "basic.yaml")
    entries = run_tests(cases, RunnerConfig(base_url="http://127.0.0.1:8123", retries=0))
    assert len(entries) == 8
    failed = [e.name for e in entries if not e.passed]
    assert not failed, f"failed: {failed}"
    assert "8 passed" in summarize(entries)


def test_e2e_openapi_generated_cases(server):
    spec = load_openapi(OPENAPI)
    cases = generate_cases_from_openapi(spec)
    entries = run_tests(cases, RunnerConfig(base_url="http://127.0.0.1:8123", retries=0))
    # POST /users requires body; generated body is {"name":"alice","age":30} -> 201 ok
    failed = [e.name for e in entries if not e.passed]
    assert not failed, f"failed: {failed}"


def test_e2e_report_written(server, tmp_path):
    cases = load_cases(EXAMPLES / "basic.yaml")
    entries = Runner(RunnerConfig(base_url="http://127.0.0.1:8123", retries=0)).run_all(cases)
    out = write_json_report(entries, tmp_path / "report.json")
    import json

    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["summary"].startswith("8 passed")
    assert len(payload["results"]) == 8


def test_e2e_latency_measured(server):
    cases = load_cases(EXAMPLES / "basic.yaml")
    entries = run_tests(cases, RunnerConfig(base_url="http://127.0.0.1:8123", retries=0))
    assert all(e.latency_ms >= 0 for e in entries)
