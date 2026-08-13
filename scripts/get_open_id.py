#!/usr/bin/env python3
"""通过手机号/邮箱查询飞书用户的 open_id（应用机器人单聊通知用）。

用法:
    FEISHU_APP_ID=cli_xxx FEISHU_APP_SECRET=xxx \
    python scripts/get_open_id.py --mobile 13800138000
    python scripts/get_open_id.py --email xxx@company.com

依赖权限（开放平台后台给应用开通）:
    - contact:user.base:readonly  （读取用户信息，手机号/邮箱查询需要）
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from notify_feishu import _tenant_access_token  # noqa: E402


def _post(url: str, payload: dict, token: str) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {token}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return json.loads(e.read().decode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="查询飞书用户 open_id")
    parser.add_argument("--mobile", help="手机号")
    parser.add_argument("--email", help="邮箱")
    args = parser.parse_args()

    app_id = os.getenv("FEISHU_APP_ID", "")
    app_secret = os.getenv("FEISHU_APP_SECRET", "")
    if not app_id or not app_secret:
        print("!! 需要设置 FEISHU_APP_ID / FEISHU_APP_SECRET 环境变量")
        return 1
    if not args.mobile and not args.email:
        print("!! 需要提供 --mobile 或 --email")
        return 1

    try:
        token = _tenant_access_token(app_id, app_secret)
    except Exception as e:
        print(f"!! 获取 token 失败: {e}")
        return 1

    payload = {}
    if args.mobile:
        payload["mobiles"] = [args.mobile]
    if args.email:
        payload["emails"] = [args.email]

    d = _post("https://open.feishu.cn/open-apis/contact/v3/users/batch_get_id",
              payload, token)
    if d.get("code") != 0:
        print(f"!! 查询失败 code={d.get('code')} msg={d.get('msg')}")
        print("   可能原因：应用未发布 / 缺少 contact:user.base:readonly 权限 / 手机号不在企业通讯录")
        return 1

    for user in d.get("data", {}).get("user_list", []):
        print(f"user_id : {user.get('user_id')}")
        print(f"open_id : {user.get('open_id')}   <- 填入 FEISHU_OPEN_ID")
        print(f"name    : {user.get('name')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
