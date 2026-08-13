"""Optional LLM augmentation (P1).

Gated on OPENAI_API_KEY. Uses the openai SDK against any OpenAI-compatible
endpoint (set OPENAI_BASE_URL to point at DeepSeek/Ollama/etc.).

Two capabilities:
  1. generate_cases_from_spec  - LLM proposes extra edge-case TestCases from a spec
  2. explain_failure           - LLM failure analysis (P2 self-healing suggestions)
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from tester.core.case import Expected, TestCase


def _load_dotenv(path: str | Path | None = None) -> None:
    """Load .env from project root if present (no external deps)."""
    if os.getenv("OPENAI_API_KEY"):
        return  # env already set wins
    dotenv_path = Path(path) if path else None
    if dotenv_path is None:
        # walk up from this file to find project root .env
        here = Path(__file__).resolve()
        for parent in [here, *here.parents]:
            cand = parent / ".env"
            if cand.exists():
                dotenv_path = cand
                break
    if dotenv_path is None or not dotenv_path.exists():
        return
    for line in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())


_load_dotenv()


def llm_available() -> bool:
    return bool(os.getenv("OPENAI_API_KEY"))


def _client():
    from openai import OpenAI

    return OpenAI(
        api_key=os.getenv("OPENAI_API_KEY"),
        base_url=os.getenv("OPENAI_BASE_URL") or None,
    )


def _chat(messages: list[dict], model: str | None = None, temperature: float = 0.2) -> str:
    client = _client()
    resp = client.chat.completions.create(
        model=model or os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        messages=messages,
        temperature=temperature,
    )
    return resp.choices[0].message.content or ""


def generate_cases_from_spec(spec: dict, max_cases: int = 5) -> list[TestCase]:
    """Ask the LLM to propose edge cases for paths in the spec.

    Returns [] when no API key configured or parsing fails (callers must
    treat LLM output as advisory only).
    """
    if not llm_available():
        return []
    paths = list((spec.get("paths") or {}).keys())[:20]
    prompt = (
        "You are an API test designer. Given these OpenAPI paths, propose up to "
        f"{max_cases} high-value edge case tests (auth failures, boundary values, "
        "missing required fields). Reply STRICTLY with JSON array, each item: "
        "{\"name\": str, \"method\": str, \"path\": str, \"params\": {..}, \"body\": {..}|null, "
        "\"expected_status\": int}. Paths: " + ", ".join(paths)
    )
    try:
        raw = _chat([{"role": "user", "content": prompt}], temperature=0.3)
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.strip("`")
            if raw.startswith("json"):
                raw = raw[4:]
        data = json.loads(raw)
        cases: list[TestCase] = []
        for item in data[:max_cases]:
            cases.append(
                TestCase(
                    name=item["name"],
                    method=str(item.get("method", "GET")).upper(),
                    path=item["path"],
                    params=item.get("params") or {},
                    body=item.get("body"),
                    expected=Expected(status=item.get("expected_status", 200)),
                    tags=["llm"],
                )
            )
        return cases
    except Exception:  # noqa: BLE001 - LLM output is advisory, never fatal
        return []


def explain_failure(entry: dict, spec: dict | None = None) -> str:
    """LLM analysis of a failed case: likely root cause + fix suggestion."""
    if not llm_available():
        return "(LLM disabled: set OPENAI_API_KEY to enable failure analysis)"
    prompt = (
        "An API contract test failed. Analyze the likely root cause and suggest "
        "a fix. Be concise, 3-6 bullets.\n\n"
        f"Test: {json.dumps(entry, ensure_ascii=False, default=str)}"
    )
    if spec:
        prompt += f"\n\nSpec excerpt: {json.dumps(spec, ensure_ascii=False)[:2000]}"
    try:
        return _chat([{"role": "user", "content": prompt}])
    except Exception as e:  # noqa: BLE001
        return f"(LLM analysis failed: {e})"
