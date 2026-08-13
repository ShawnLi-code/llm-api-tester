#!/usr/bin/env python3
"""跑真实环境全部用例（多项目隔离版）。

用法：
    python scripts/run_real.py                       # 默认项目 ziceyunyu 全量
    python scripts/run_real.py --project 新项目       # 指定项目
    python scripts/run_real.py 概览 --project xxx     # 只跑某模块
    python scripts/run_real.py --normal-only          # 只跑正常流
    python scripts/run_real.py --workers 8            # 并发 8 线程
"""
import sys
from pathlib import Path

from tester.core.analyzer import triage_report
from tester.core.loader import load_cases
from tester.core.runner import Runner, RunnerConfig
from tester.report import write_json_report

sys.path.insert(0, str(Path(__file__).resolve().parent))
from project_config import BASE, base_url_of, get_auth_token, load_config, resolve_project


def parse_project(argv: list[str]) -> tuple[str | None, list[str]]:
    """从参数中取出 --project <name>，返回 (project, 其余参数)"""
    project = None
    rest: list[str] = []
    i = 0
    while i < len(argv):
        if argv[i] == "--project" and i + 1 < len(argv):
            project = argv[i + 1]
            i += 2
        else:
            rest.append(argv[i])
            i += 1
    return project, rest


def main():
    project, rest = parse_project(sys.argv[1:])
    project = resolve_project(project)
    cfg = load_config(project)
    args = [a for a in rest if not a.startswith("--")]
    normal_only = "--normal-only" in rest
    workers = 1
    for i, a in enumerate(rest):
        if a == "--workers" and i + 1 < len(rest):
            workers = int(rest[i + 1])
    module_filter = args[0] if args else None

    files = sorted(cfg["cases_dir"].glob("*.yaml"))
    if module_filter:
        files = [f for f in files if module_filter in f.name]

    all_cases = []
    for f in files:
        all_cases += load_cases(f)
    if normal_only:
        all_cases = [c for c in all_cases if "正常流" in c.tags]

    print(f"=== 项目 {cfg['name']} / {len(files)} 个文件 / {len(all_cases)} 条用例 ===")
    token = get_auth_token(cfg)
    if not token:
        auth_path = cfg['project_dir'] / cfg.get('auth_file', 'auth.json')
        print(f"!! 未找到 {cfg.get('auth_cookie')}，请刷新 {auth_path}")
        return 1
    if not token.isascii():
        auth_path = cfg['project_dir'] / cfg.get('auth_file', 'auth.json')
        print(f"!! {cfg.get('auth_cookie')} 含非 ASCII 字符（可能是占位符未替换），"
              f"请把真实 token 填入 {auth_path}")
        return 1
    config = RunnerConfig(
        base_url=base_url_of(cfg),
        headers={"Authorization": token},
        timeout=cfg.get("timeout", 15),
        retries=cfg.get("retries", 1),
        max_workers=workers,
    )
    entries = Runner(config).run_all(all_cases)
    passed = sum(1 for e in entries if e.passed)
    print(f"结果: {passed}/{len(entries)} 通过" + (f" (workers={workers})" if workers > 1 else ""))

    failed = [e for e in entries if not e.passed]
    if failed:
        # token 过期检测：大量 401 通常是 token 失效，提示刷新
        auth_fails = [e for e in failed if e.status_code == 401]
        if auth_fails and len(auth_fails) >= max(1, len(failed) // 2):
            print(f"!! {len(auth_fails)}/{len(failed)} 失败均为 401：token 可能已过期，"
                  f"请刷新 {cfg['project_dir'] / cfg.get('auth_file', 'auth.json')} 后重跑")
        print(f"\n--- 失败 {len(failed)} 条 (前 20) ---")
        for e in failed[:20]:
            print(f"  [FAIL] {e.name[:44]} -> {e.status_code} | {e.reason[:60]}")
        grouped = triage_report(entries, use_llm=False)
        print("\n三分类(规则):", {k: len(v) for k, v in grouped.items()})

    out = cfg["reports_dir"] / "real_latest.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    write_json_report(entries, out)
    print(f"\n报告: {out.relative_to(BASE)}")


if __name__ == "__main__":
    main()
