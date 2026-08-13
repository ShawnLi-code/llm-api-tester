#!/usr/bin/env python3
"""发送飞书通知，支持两种机器人：

模式 A（群机器人 webhook）:
    FEISHU_WEBHOOK=https://open.feishu.cn/open-apis/bot/v2/hook/xxx
    FEISHU_SECRET=加签密钥(可选)

模式 B（应用机器人，单聊）:
    FEISHU_APP_ID=cli_xxx
    FEISHU_APP_SECRET=xxx
    FEISHU_OPEN_ID=ou_xxx（接收人的 open_id）

从 pytest --junitxml 读取测试结果，组装富文本卡片发送。

用法:
    python scripts/notify_feishu.py --junit reports/junit.xml --title "接口自动化回归"

参数:
    --junit <xml>     pytest --junitxml 输出（必填）
    --title <str>     卡片标题（默认 "接口自动化测试"）
    --report-url     报告/流水线链接（可选，默认取 REPORT_URL 环境变量）
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

MAX_FAILURES_SHOWN = 10  # 卡片里最多列出的失败用例数
AUTH_MARKERS = ("401", "token 过期", "token为空", "未登录")


def load_junit(path: str | Path) -> dict:
    """解析 pytest junit.xml，返回 {tests, failures, errors, skipped, failed_cases}."""
    root = ET.parse(path).getroot()
    failed_cases: list[dict] = []
    for tc in root.iter("testcase"):
        failure = tc.find("failure")
        if failure is not None:
            msg = (failure.get("message") or "").strip()
            failed_cases.append({"name": tc.get("name", ""), "message": msg[:200]})
    return {
        "tests": int(root.get("tests", 0)),
        "failures": int(root.get("failures", 0)),
        "errors": int(root.get("errors", 0)),
        "skipped": int(root.get("skipped", 0)),
        "failed_cases": failed_cases,
    }


def _feishu_sign(secret: str) -> tuple[str, str]:
    """飞书加签：timestamp + secret -> sign，附到 webhook query。"""
    timestamp = str(round(time.time()))
    string_to_sign = f"{timestamp}\n{secret}"
    digest = hmac.new(string_to_sign.encode("utf-8"), digestmod=hashlib.sha256).digest()
    sign = base64.b64encode(digest).decode("utf-8")
    return timestamp, sign


def build_card(title: str, stats: dict, report_url: str = "") -> dict:
    """组装飞书 interactive 卡片。"""
    total = stats["tests"]
    failed = stats["failures"] + stats["errors"]
    passed = total - failed - stats["skipped"]
    rate = f"{passed / total * 100:.1f}%" if total else "N/A"

    color = "green" if failed == 0 else "red"
    header = f"{title} {'✅ 全部通过' if failed == 0 else f'❌ {failed} 个失败'}"

    lines = [
        f"**测试结果** 共 {total} 条｜通过 **{passed}**（{rate}）｜"
        f"失败 **{failed}**｜跳过 {stats['skipped']}",
    ]
    auth_hit = any(
        any(m in c["message"] for m in AUTH_MARKERS) for c in stats["failed_cases"]
    )
    if auth_hit:
        lines.append("⚠️ 存在 401/token 类失败：**token 可能已过期**，"
                     "请刷新 `auth.json` 后重跑")
    if failed_cases := stats["failed_cases"][:MAX_FAILURES_SHOWN]:
        lines.append(f"**失败用例（前 {len(failed_cases)} 条）**")
        for c in failed_cases:
            msg = (c["message"] or "").replace("\n", " ")[:80]
            lines.append(f"<font color='red'>{c['name'][:60]}</font>\n{msg}")
        if len(stats["failed_cases"]) > MAX_FAILURES_SHOWN:
            lines.append(f"… 其余 {len(stats['failed_cases']) - MAX_FAILURES_SHOWN} 条见报告")

    elements: list[dict] = [
        {"tag": "div", "text": {"tag": "lark_md", "content": "\n".join(lines)}},
        {"tag": "hr"},
    ]
    if report_url:
        elements.append({
            "tag": "action",
            "actions": [{
                "tag": "button",
                "text": {"tag": "plain_text", "content": "查看完整报告"},
                "type": "primary",
                "url": report_url,
            }],
        })
    elements.append({"tag": "note",
                     "elements": [{"tag": "plain_text",
                                   "content": time.strftime("%Y-%m-%d %H:%M:%S") + " · llm-api-tester"}]})

    return {
        "msg_type": "interactive",
        "card": {
            "config": {"wide_screen_mode": True},
            "header": {"title": {"tag": "plain_text", "content": header}, "template": color},
            "elements": elements,
        },
    }


def _http_post(url: str, payload: dict, token: str = "") -> tuple[int, str]:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                 headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, resp.read().decode("utf-8", errors="ignore")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="ignore")


def send_webhook(webhook: str, secret: str, card: dict) -> tuple[int, str]:
    """模式 A：群机器人 webhook 发送。"""
    url = webhook
    if secret:
        timestamp, sign = _feishu_sign(secret)
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}timestamp={timestamp}&sign={sign}"
    return _http_post(url, card)


def _tenant_access_token(app_id: str, app_secret: str) -> str:
    """应用模式：获取 tenant_access_token。"""
    code, body = _http_post(
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        {"app_id": app_id, "app_secret": app_secret},
    )
    d = json.loads(body)
    if d.get("code") != 0:
        raise RuntimeError(f"获取 tenant_access_token 失败: {d.get('msg')}")
    return d["tenant_access_token"]


def send_as_app(app_id: str, app_secret: str, open_id: str, card: dict) -> tuple[int, str]:
    """模式 B：应用机器人单聊，发送 interactive 卡片给指定 open_id。"""
    token = _tenant_access_token(app_id, app_secret)
    payload = {
        "receive_id": open_id,
        "msg_type": "interactive",
        "content": json.dumps(card["card"], ensure_ascii=False),
    }
    return _http_post(
        "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=open_id",
        payload, token,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="发送飞书测试通知")
    parser.add_argument("--junit", required=True, help="pytest --junitxml 文件")
    parser.add_argument("--title", default="接口自动化测试")
    parser.add_argument("--report-url", default=os.getenv("REPORT_URL", ""),
                        help="报告/流水线链接")
    args = parser.parse_args()

    junit = Path(args.junit)
    if not junit.exists():
        print(f"!! junit 文件不存在: {junit}，跳过通知")
        return 0

    stats = load_junit(junit)
    card = build_card(args.title, stats, args.report_url)

    # 模式 A：群机器人 webhook
    webhook = os.getenv("FEISHU_WEBHOOK", "")
    if webhook:
        code, body = send_webhook(webhook, os.getenv("FEISHU_SECRET", ""), card)
        print(f"飞书 webhook 通知: HTTP {code} {body[:120]}")
        return 0 if code == 200 else 1

    # 模式 B：应用机器人单聊
    app_id = os.getenv("FEISHU_APP_ID", "")
    app_secret = os.getenv("FEISHU_APP_SECRET", "")
    open_id = os.getenv("FEISHU_OPEN_ID", "")
    if app_id and app_secret and open_id:
        code, body = send_as_app(app_id, app_secret, open_id, card)
        print(f"飞书应用单聊通知: HTTP {code} {body[:120]}")
        return 0 if code == 200 else 1

    print("!! 未配置通知渠道：请设置 FEISHU_WEBHOOK(+SECRET) 或 FEISHU_APP_ID/APP_SECRET/OPEN_ID")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
