#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""本地 HTTP 服务打开 Allure 报告（解决 file:// 打不开/加载中的问题）。

用法:
    python scripts/serve_allure_report.py            # 默认 8787 端口，自动开浏览器
    python scripts/serve_allure_report.py 9000       # 指定端口
    python scripts/serve_allure_report.py --no-browser  # 不自动开浏览器
"""
import sys
import threading
import time
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BASE = Path(__file__).resolve().parents[1]
REPORT_DIR = BASE / "reports" / "allure-report"


def main() -> int:
    port = 8787
    no_browser = "--no-browser" in sys.argv
    for a in sys.argv[1:]:
        if a.isdigit():
            port = int(a)

    if not REPORT_DIR.exists():
        print(f"报告不存在: {REPORT_DIR}\n请先运行: python scripts/gen_allure_report.py")
        return 1

    handler = lambda *a, **kw: SimpleHTTPRequestHandler(*a, directory=str(REPORT_DIR), **kw)  # noqa: E731
    httpd = ThreadingHTTPServer(("127.0.0.1", port), handler)
    url = f"http://127.0.0.1:{port}/index.html"

    if not no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()

    print(f"Allure 报告服务已启动: {url}")
    print(f"报告目录: {REPORT_DIR}")
    print("按 Ctrl+C 停止服务")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
    return 0


if __name__ == "__main__":
    sys.exit(main())
