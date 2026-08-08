#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一键生成 Allure 报告：跑真实环境用例 -> allure-results -> HTML。

用法:
    python scripts/gen_allure_report.py
    然后浏览器打开 reports/allure-report/index.html
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
ALLURE_BIN = BASE / "tools" / "allure-2.30.0" / "bin" / "allure.bat"
AUTH = BASE.parent / "recon" / "auth_default.json"


def write_environment() -> None:
    """写 allure 环境信息（显示在报告 Environment 标签）。

    Java properties 格式只认 ISO-8859-1，中文必须 Unicode 转义（反斜杠 uXXXX），
    否则 allure 解析出乱码。
    """
    env: dict[str, str] = {
        "Environment": "dev",
        "Base URL": "http://aiwh-dev.junbangbao.cn",
        "Python": sys.version.split()[0],
        "测试框架": "llm-api-tester",
        "生成时间": __import__("time").strftime("%Y-%m-%d %H:%M:%S"),
    }
    if AUTH.exists():
        auth = json.loads(AUTH.read_text(encoding="utf-8"))
        cookies = "; ".join(c["name"] for c in auth.get("cookies", []))
        env["认证"] = f"{cookies} (token 已脱敏)"
    env_dir = BASE / "reports" / "allure-results"
    env_dir.mkdir(parents=True, exist_ok=True)

    def esc(v: str) -> str:
        return "".join(
            c if ord(c) < 128 else "\\u%04x" % ord(c) for c in v
        )

    lines = "\n".join(f"{esc(k)}={esc(v)}" for k, v in env.items())
    (env_dir / "environment.properties").write_text(lines, encoding="utf-8")


def main() -> int:
    # 1. 清旧结果
    for d in ("allure-results", "allure-report"):
        p = BASE / "reports" / d
        if p.exists():
            shutil.rmtree(p)
    # 2. 环境信息
    write_environment()
    # 3. 跑 pytest（真实环境用例 + 自检用例）
    print("=== 执行测试 ===")
    r = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/test_real.py", "-q",
         "--alluredir", str(BASE / "reports" / "allure-results")],
        capture_output=True, text=True,
    )
    print(r.stdout[-500:] if r.stdout else "")
    # 4. 生成 HTML
    print("=== 生成 Allure 报告 ===")
    gen = subprocess.run(
        [str(ALLURE_BIN), "generate", str(BASE / "reports" / "allure-results"),
         "-o", str(BASE / "reports" / "allure-report"), "--clean"],
        capture_output=True, text=True,
    )
    print(gen.stdout.strip().splitlines()[-1] if gen.stdout else gen.stderr[-200:])
    print(f"\n报告: {BASE / 'reports' / 'allure-report' / 'index.html'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
