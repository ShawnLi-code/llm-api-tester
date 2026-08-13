#!/usr/bin/env python3
"""本地 HTTP 服务打开 Allure 报告（解决 file:// 打不开/加载中的问题）。

用法:
    python scripts/serve_allure_report.py                     # 默认项目, 8787 端口
    python scripts/serve_allure_report.py --project 新项目     # 指定项目
    python scripts/serve_allure_report.py 9000                # 指定端口
    python scripts/serve_allure_report.py --no-browser        # 不自动开浏览器
"""
import sys
import threading
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from project_config import load_config, resolve_project  # noqa: E402


def main() -> int:
    port = 8787
    no_browser = "--no-browser" in sys.argv
    argv = sys.argv[1:]
    project = None
    for i, a in enumerate(argv):
        if a == "--project" and i + 1 < len(argv):
            project = argv[i + 1]
        elif a.isdigit():
            port = int(a)
    cfg = load_config(resolve_project(project))
    report_dir = cfg["reports_dir"] / "allure-report"

    if not report_dir.exists():
        cmd = "python scripts/gen_allure_report.py --project {}".format(cfg["project"])
        print(f"报告不存在: {report_dir}\n请先运行: {cmd}")
        return 1

    handler = lambda *a, **kw: SimpleHTTPRequestHandler(*a, directory=str(report_dir), **kw)  # noqa: E731
    httpd = ThreadingHTTPServer(("127.0.0.1", port), handler)
    url = f"http://127.0.0.1:{port}/index.html"

    if not no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()

    print(f"Allure 报告服务已启动: {url}")
    print(f"项目: {cfg['name']} / 报告目录: {report_dir}")
    print("按 Ctrl+C 停止服务")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
    return 0


if __name__ == "__main__":
    sys.exit(main())
