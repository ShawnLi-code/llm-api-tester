"""CLI: run YAML cases against a base URL, print summary, write JSON report.

Usage:
    python -m tester.cli --cases examples/basic.yaml --base-url http://127.0.0.1:8000
    python -m tester.cli --cases examples/basic.yaml --base-url ... --report reports/out.json
    python -m tester.cli --gen-openapi examples/openapi.json --cases examples/from_spec.yaml
    python -m tester.cli --gen-llm examples/openapi.json --out examples/llm_review.yaml
    python -m tester.cli --cases ... --triage            # run + failure triage in report
"""
from __future__ import annotations

import argparse
import sys

from tester.core.loader import load_cases
from tester.core.runner import Runner, RunnerConfig
from tester.generators.schema import cases_to_yaml, generate_cases_from_openapi, load_openapi
from tester.report import summarize, write_json_report

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tester", description="AI-driven API testing harness")
    parser.add_argument("--cases", help="YAML test cases file")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="API base URL")
    parser.add_argument("--report", default="reports/latest.json", help="JSON report path")
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--retries", type=int, default=1)
    parser.add_argument("--gen-openapi", help="generate YAML cases from an OpenAPI spec (writes --out)")
    parser.add_argument("--gen-llm", help="LLM-generate edge cases from an OpenAPI spec (writes --out, human review before use)")
    parser.add_argument("--out", default="examples/from_spec.yaml", help="output for --gen-openapi/--gen-llm")
    parser.add_argument("--triage", action="store_true", help="classify failures (bug/env/stale_case) into report")
    parser.add_argument("--no-llm", action="store_true", help="force rule-based triage, skip LLM refinement")
    args = parser.parse_args(argv)

    if args.gen_llm:
        from tester.generators.llm import generate_cases_from_spec

        spec = load_openapi(args.gen_llm)
        cases = generate_cases_from_spec(spec, max_cases=5)
        if not cases:
            print("LLM returned no cases (check OPENAI_API_KEY / connectivity)")
            return 1
        text = cases_to_yaml(cases)
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"generated {len(cases)} LLM cases -> {args.out}  (REVIEW before adding to suite)")
        return 0
    if args.gen_openapi:
        spec = load_openapi(args.gen_openapi)
        cases = generate_cases_from_openapi(spec)
        text = cases_to_yaml(cases)
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"generated {len(cases)} cases -> {args.out}")
        return 0

    if not args.cases:
        parser.error("--cases is required unless --gen-openapi/--gen-llm is used")
    cases = load_cases(args.cases)
    config = RunnerConfig(base_url=args.base_url, timeout=args.timeout, retries=args.retries)
    entries = Runner(config).run_all(cases)
    print(summarize(entries))
    for e in entries:
        flag = "PASS" if e.passed else "FAIL"
        print(f"  [{flag}] {e.method} {e.url} -> {e.status_code} {e.reason}")
    if args.triage:
        from tester.core.analyzer import triage_report

        grouped = triage_report(entries, use_llm=not args.no_llm)
        for cat in ("bug", "env", "stale_case"):
            items = grouped.get(cat, [])
            print(f"  triage[{cat}]: {len(items)}")
            for it in items[:5]:
                t = it["triage"]
                print(f"    - {it['name']}: {t['reason'][:80]} (conf={t['confidence']})")
    write_json_report(entries, args.report)
    print(f"report: {args.report}")
    return 0 if all(e.passed for e in entries) else 1


if __name__ == "__main__":
    sys.exit(main())
