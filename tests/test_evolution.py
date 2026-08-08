"""Tests for evolution features: triage, RAG, recorder, CLI gen-llm."""
import json
from pathlib import Path

import pytest

from tester.core.analyzer import TriageResult, _rule_classify, triage_report
from tester.core.runner import ReportEntry
from tester.generators.schema import cases_to_yaml, generate_cases_from_openapi, load_openapi
from tester.rag import KnowledgeBase, build_kb_from_dir, chunk_text
from tester.recorder import Recorder, RecorderTransport
from tests.test_core import EXAMPLES, OPENAPI


# ---------- failure triage ----------

def _entry(status=None, reason="", name="x"):
    return ReportEntry(name=name, method="GET", url="http://x/y",
                       status_code=status, reason=reason)


def test_rule_classify_5xx_bug():
    r = _rule_classify(_entry(500, "status 500 != expected 200"))
    assert r.category == "bug"
    assert r.confidence >= 0.5


def test_rule_classify_connection_env():
    r = _rule_classify(_entry(None, "Connection refused: connect"))
    assert r.category == "env"


def test_rule_classify_status_mismatch_stale():
    r = _rule_classify(_entry(404, "status 404 != expected 200"))
    assert r.category == "stale_case"


def test_rule_classify_schema_mismatch_stale():
    r = _rule_classify(_entry(200, "'' is not of type 'object'"))
    assert r.category == "stale_case"


def test_triage_report_groups():
    entries = [
        _entry(500, "boom", "a"),
        _entry(None, "Connection refused", "b"),
        _entry(404, "status 404 != expected 200", "c"),
    ]
    grouped = triage_report(entries, use_llm=False)
    assert [e["name"] for e in grouped["bug"]] == ["a"]
    assert [e["name"] for e in grouped["env"]] == ["b"]
    assert [e["name"] for e in grouped["stale_case"]] == ["c"]
    # passed entries are skipped
    ok = ReportEntry(name="ok", method="GET", url="http://x", status_code=200, passed=True)
    grouped2 = triage_report([ok], use_llm=False)
    assert sum(len(v) for v in grouped2.values()) == 0


# ---------- RAG ----------

def test_chunk_text_splits():
    parts = chunk_text("a" * 1000, chunk_size=400, overlap=60)
    assert len(parts) >= 2
    assert all(p for p in parts)


def test_kb_add_and_search():
    kb = KnowledgeBase()
    kb.add("The login endpoint returns a JWT token when credentials are valid.", source="api.md")
    kb.add("Users are created with a POST request containing name and email.", source="api.md")
    hits = kb.search("how to get a token after login", top_k=1)
    assert hits and hits[0][1] > 0
    assert "JWT" in hits[0][0].text


def test_kb_build_context_injects_source():
    kb = KnowledgeBase()
    kb.add("Payment requires amount > 0 and currency ISO code.", source="rules.md")
    ctx = kb.build_context("payment amount rules", top_k=1)
    assert "rules.md" in ctx and "currency" in ctx


def test_kb_from_dir(tmp_path):
    (tmp_path / "doc1.md").write_text("Interface doc: health endpoint returns status ok.", encoding="utf-8")
    kb = build_kb_from_dir(tmp_path)
    assert len(kb.chunks) >= 1


# ---------- recorder ----------

def test_recorder_save_load_roundtrip(tmp_path):
    rec = Recorder(tmp_path / "t.yaml")
    rec.record("GET", "http://x/health", {"Authorization": "Bearer secret", "Host": "x"},
               None, 200, {"Content-Type": "application/json"}, {"status": "ok"}, 1.2)
    p = rec.save()
    rec2 = Recorder(p)
    rec2.load()
    assert len(rec2.exchanges) == 1
    ex = rec2.exchanges[0]
    assert ex["method"] == "GET"
    assert "Authorization" not in ex["request"]["headers"]
    assert ex["response"]["body"] == {"status": "ok"}


def test_recorder_find():
    rec = Recorder("x.yaml")
    rec.exchanges = [{"method": "GET", "url": "http://x/a", "response": {"status_code": 200, "headers": {}, "body": {"ok": 1}}}]
    assert rec.find("GET", "http://x/a") is not None
    assert rec.find("GET", "http://x/nope") is None


def test_recorder_replay_miss_returns_502(tmp_path):
    rec = Recorder(tmp_path / "t.yaml")
    rec.exchanges = [{
        "method": "GET", "url": "http://x/a",
        "response": {"status_code": 200, "headers": {}, "body": {"ok": 1}},
    }]
    import httpx
    transport = RecorderTransport(rec, replay=True)
    client = httpx.Client(transport=transport)
    resp = client.get("http://x/a")
    assert resp.status_code == 200
    assert resp.json() == {"ok": 1}
    resp2 = client.get("http://x/miss")
    assert resp2.status_code == 502
    assert ("GET", "http://x/miss") in transport.missed
    client.close()


# ---------- CLI gen-llm (offline path: no key -> clean message) ----------

def test_cli_gen_llm_no_key(tmp_path, monkeypatch):
    import subprocess
    import sys
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    r = subprocess.run(
        [sys.executable, "-m", "tester.cli", "--gen-llm", str(OPENAPI),
         "--out", str(tmp_path / "out.yaml")],
        capture_output=True, text=True, cwd=str(Path(__file__).resolve().parents[1]),
        env={**__import__("os").environ, "OPENAI_API_KEY": ""},
    )
    assert r.returncode == 1
    assert "no cases" in r.stdout


def test_cli_gen_openapi_offline(tmp_path):
    import subprocess
    import sys
    out = tmp_path / "gen.yaml"
    r = subprocess.run(
        [sys.executable, "-m", "tester.cli", "--gen-openapi", str(OPENAPI), "--out", str(out)],
        capture_output=True, text=True,
        env={**__import__("os").environ, "OPENAI_API_KEY": ""},
    )
    assert r.returncode == 0
    assert "generated 4 cases" in r.stdout
    assert out.exists()
