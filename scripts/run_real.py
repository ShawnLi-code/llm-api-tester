#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""跑真实环境（智策云语 dev）全部查询用例。

用法：
    python scripts/run_real.py                # 全量 95 条
    python scripts/run_real.py 概览           # 只跑某模块
    python scripts/run_real.py --normal-only  # 只跑正常流
"""
import json
import sys
from pathlib import Path

from tester.core.analyzer import triage_report
from tester.core.loader import load_cases
from tester.core.runner import Runner, RunnerConfig
from tester.report import write_json_report

BASE = Path(__file__).resolve().parents[1]
REAL = BASE / "examples" / "real_cases"
AUTH = BASE.parent / "recon" / "auth_default.json"

# 真实 API 前缀（HAR 抓包确认）：nginx 对无前缀路径 fallback 到 index.html（假 200）
GATEWAY_PREFIX = "gw/enterprise"


def get_token() -> str:
    """取 Admin-Token 值（Authorization header 用，HAR 抓包确认）"""
    auth = json.loads(AUTH.read_text(encoding="utf-8"))
    for c in auth.get("cookies", []):
        if c["name"] == "Admin-Token":
            return c["value"]
    return ""


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    normal_only = "--normal-only" in sys.argv
    module_filter = args[0] if args else None

    files = sorted(REAL.glob("*.yaml"))
    if module_filter:
        files = [f for f in files if module_filter in f.name]

    all_cases = []
    for f in files:
        all_cases += load_cases(f)
    if normal_only:
        all_cases = [c for c in all_cases if "正常流" in c.tags]

    print(f"=== 加载 {len(files)} 个文件 / {len(all_cases)} 条用例 ===")
    token = get_token()
    if not token:
        print("!! 未找到 Admin-Token，请刷新 recon/auth_default.json")
        return 1
    config = RunnerConfig(
        base_url=f"http://aiwh-dev.junbangbao.cn/{GATEWAY_PREFIX}",
        headers={"Authorization": token},
        timeout=15,
        retries=1,
    )
    entries = Runner(config).run_all(all_cases)
    passed = sum(1 for e in entries if e.passed)
    print(f"结果: {passed}/{len(entries)} 通过")

    failed = [e for e in entries if not e.passed]
    if failed:
        print(f"\n--- 失败 {len(failed)} 条 (前 20) ---")
        for e in failed[:20]:
            print(f"  [FAIL] {e.name[:44]} -> {e.status_code} | {e.reason[:60]}")
        grouped = triage_report(entries, use_llm=False)
        print("\n三分类(规则):", {k: len(v) for k, v in grouped.items()})

    write_json_report(entries, BASE / "reports" / "real_latest.json")
    print(f"\n报告: reports/real_latest.json")


if __name__ == "__main__":
    main()
