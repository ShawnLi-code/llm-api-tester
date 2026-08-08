#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一键生成 Allure 报告（多项目隔离版）：跑真实环境用例 -> allure-results -> HTML。

用法:
    python scripts/gen_allure_report.py                    # 默认项目 ziceyunyu
    python scripts/gen_allure_report.py --project 新项目
    然后浏览器打开 projects/<项目>/reports/allure-report/index.html
"""
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
ALLURE_BIN = BASE / "tools" / "allure-2.30.0" / "bin" / "allure.bat"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from project_config import load_config, resolve_project


def write_environment(cfg: dict) -> None:
    """写 allure 环境信息（显示在报告 Environment 标签）。

    Java properties 格式只认 ISO-8859-1，中文必须 Unicode 转义（反斜杠 uXXXX），
    否则 allure 解析出乱码。
    """
    env: dict[str, str] = {
        "Environment": "dev",
        "Base URL": cfg["base_url"],
        "项目": cfg["name"],
        "Python": sys.version.split()[0],
        "测试框架": "llm-api-tester",
        "生成时间": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    auth_file = cfg["project_dir"] / cfg.get("auth_file", "auth.json")
    if auth_file.exists():
        auth = json.loads(auth_file.read_text(encoding="utf-8"))
        cookies = "; ".join(c["name"] for c in auth.get("cookies", []))
        env["认证"] = f"{cookies} (token 已脱敏)"
    env_dir = cfg["reports_dir"] / "allure-results"
    env_dir.mkdir(parents=True, exist_ok=True)

    def esc(v: str) -> str:
        return "".join(
            c if ord(c) < 128 else "\\u%04x" % ord(c) for c in v
        )

    lines = "\n".join(f"{esc(k)}={esc(v)}" for k, v in env.items())
    (env_dir / "environment.properties").write_text(lines, encoding="utf-8")


def main() -> int:
    project = resolve_project(None)
    argv = sys.argv[1:]
    for i, a in enumerate(argv):
        if a == "--project" and i + 1 < len(argv):
            project = resolve_project(argv[i + 1])
    cfg = load_config(project)
    res_dir = cfg["reports_dir"] / "allure-results"
    html_dir = cfg["reports_dir"] / "allure-report"

    # 1. 清旧结果
    for p in (res_dir, html_dir):
        if p.exists():
            shutil.rmtree(p)
    # 2. 环境信息
    write_environment(cfg)
    # 3. 跑 pytest（真实环境用例）
    print(f"=== 项目 {cfg['name']}：执行测试 ===")
    r = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_real.py", "-q",
         "--alluredir", str(res_dir)],
        capture_output=True, text=True,
        env={**__import__("os").environ, "OMP_PROJECT": project},
    )
    print(r.stdout[-500:] if r.stdout else "")
    # 4. 生成 HTML
    print("=== 生成 Allure 报告 ===")
    gen = subprocess.run(
        [str(ALLURE_BIN), "generate", str(res_dir),
         "-o", str(html_dir), "--clean"],
        capture_output=True, text=True,
    )
    print(gen.stdout.strip().splitlines()[-1] if gen.stdout else gen.stderr[-200:])
    print(f"\n报告: {html_dir / 'index.html'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
