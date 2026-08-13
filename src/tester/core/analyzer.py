"""Failure triage: classify test failures into bug / env / stale_case.

P2 self-healing. Two layers:
  1. Rule-based classification (always available, deterministic)
  2. LLM refinement when OPENAI_API_KEY is set (adds confidence + patch suggestion)

Categories:
  - bug        : server returned wrong status/body for a valid request -> report defect
  - env        : connection refused/timeout/DNS -> environment problem, retry or check infra
  - stale_case : assertion no longer matches current contract (response shape changed,
                 status code changed legitimately) -> update the case, human review patch
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from tester.core.runner import ReportEntry

#: status codes that usually indicate a server-side bug when the request was valid
_BUG_STATUSES = {500, 501, 502, 503, 504}
#: network-ish failure markers
_ENV_MARKERS = ("Connection refused", "Connection error", "ConnectTimeout",
                "ReadTimeout", "Name or service not known", "getaddrinfo",
                "RemoteProtocolError", "ProxyError", "network is unreachable")


@dataclass
class TriageResult:
    category: str  # "bug" | "env" | "stale_case"
    confidence: float  # 0..1
    reason: str
    suggestion: str = ""
    patch: dict | None = None  # suggested new expected block (stale_case only)
    llm_note: str = ""

    def to_dict(self) -> dict:
        return {
            "category": self.category,
            "confidence": self.confidence,
            "reason": self.reason,
            "suggestion": self.suggestion,
            "patch": self.patch,
            "llm_note": self.llm_note,
        }


def _rule_classify(entry: ReportEntry) -> TriageResult:
    """Deterministic classification from status code / error markers."""
    status = entry.status_code
    reason = entry.reason or ""
    if status is None:
        if any(m in reason for m in _ENV_MARKERS):
            return TriageResult("env", 0.9, f"network error: {reason[:120]}",
                                "check service availability / network / proxy, then retry")
        return TriageResult("env", 0.6, f"no response captured: {reason[:120]}",
                            "verify service is up and reachable")
    if status in _BUG_STATUSES:
        return TriageResult("bug", 0.7, f"server returned {status} for a valid request",
                            "open a defect with request/response and server logs")
    if status in (401, 403):
        return TriageResult("bug", 0.45, f"auth failure (HTTP {status}): {reason[:120]}",
                            "check token validity/permissions; bulk 401 usually means token "
                            "expired - refresh auth.json")
    if status == 404 and "expected 404" not in reason:
        return TriageResult("stale_case", 0.5, "got 404 but expected success",
                            "endpoint may have moved or been removed; verify contract")
    if "expected" in reason and "!= expected" in reason:
        return TriageResult("stale_case", 0.55,
                            f"status mismatch: {reason[:120]}",
                            "contract may have changed; verify against latest spec")
    if "is not of type" in reason or "missing key" in reason:
        return TriageResult("stale_case", 0.6,
                            f"response shape mismatch: {reason[:120]}",
                            "response schema changed; update expected schema after review")
    return TriageResult("bug", 0.4, f"unclassified failure: {reason[:120]}",
                        "manual review required")


def _llm_refine(entry: ReportEntry, spec: dict | None = None) -> TriageResult | None:
    """Ask the LLM to refine classification and propose a patch (stale_case)."""
    from tester.generators.llm import _chat, llm_available

    if not llm_available():
        return None
    prompt = (
        "Classify this API test failure into exactly one of: "
        "\"bug\" (server error on valid request), \"env\" (network/infra problem), "
        "\"stale_case\" (assertion outdated vs current contract). "
        "Reply STRICTLY with JSON: "
        '{"category": str, "confidence": float 0..1, "reason": str, '
        '"suggestion": str, "patch": {expected: {status: int, schema: {...}|null, body: {...}|null}}|null} '
        "patch is only for stale_case and only if you can infer the new expectation.\n\n"
        f"Failure: {json.dumps(entry.to_dict(), ensure_ascii=False, default=str)}"
    )
    if spec:
        prompt += f"\n\nSpec excerpt: {json.dumps(spec, ensure_ascii=False)[:1500]}"
    try:
        raw = _chat([{"role": "user", "content": prompt}], temperature=0.1)
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.strip("`")
            if raw.startswith("json"):
                raw = raw[4:]
        data = json.loads(raw)
        category = data.get("category")
        if category not in ("bug", "env", "stale_case"):
            return None
        return TriageResult(
            category=category,
            confidence=float(data.get("confidence", 0.5)),
            reason=str(data.get("reason", "")),
            suggestion=str(data.get("suggestion", "")),
            patch=data.get("patch"),
            llm_note="llm-refined",
        )
    except Exception:  # noqa: BLE001 - advisory only
        return None


def triage_failure(entry: ReportEntry, spec: dict | None = None,
                   use_llm: bool = True) -> TriageResult:
    """Classify a failure. Rule-based always; LLM refines when available."""
    rule = _rule_classify(entry)
    if use_llm:
        refined = _llm_refine(entry, spec)
        if refined is not None and refined.confidence >= rule.confidence:
            return refined
    return rule


def triage_report(entries: list[ReportEntry], spec: dict | None = None,
                  use_llm: bool = True) -> dict:
    """Triage every failed entry, return {category: [entries]} grouping."""
    grouped: dict[str, list[dict]] = {"bug": [], "env": [], "stale_case": []}
    for e in entries:
        if e.passed:
            continue
        result = triage_failure(e, spec, use_llm=use_llm)
        grouped[result.category].append({**e.to_dict(), "triage": result.to_dict()})
    return grouped
