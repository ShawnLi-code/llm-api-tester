"""真实环境用例的 pytest 封装（Allure 报告用）。

从 examples/real_cases/*.yaml 加载，参数化为 pytest 用例，
每用例输出: 请求信息附件 + 响应附件 + Allure 步骤。

用法:
    python -m pytest tests/test_real.py --alluredir=reports/allure-results
    tools/allure-2.30.0/bin/allure.bat generate reports/allure-results -o reports/allure-report
"""
from __future__ import annotations

import json
from pathlib import Path

import allure
import pytest
from tester.core.loader import load_cases
from tester.core.runner import Runner, RunnerConfig

BASE = Path(__file__).resolve().parents[1]
REAL = BASE / "examples" / "real_cases"
AUTH = BASE.parent / "recon" / "auth_default.json"

GATEWAY_PREFIX = "gw/enterprise"


def get_token() -> str:
    """取 Admin-Token 值（Authorization header 用，HAR 抓包确认）"""
    auth = json.loads(AUTH.read_text(encoding="utf-8"))
    for c in auth.get("cookies", []):
        if c["name"] == "Admin-Token":
            return c["value"]
    return ""


def _all_cases():
    cases = []
    for f in sorted(REAL.glob("*.yaml")):
        cases.extend(load_cases(f))
    return cases


ALL_CASES = _all_cases()


@pytest.fixture(scope="session")
def runner():
    config = RunnerConfig(
        base_url=f"http://aiwh-dev.junbangbao.cn/{GATEWAY_PREFIX}",
        headers={"Authorization": get_token()},
        timeout=15,
        retries=1,
    )
    return Runner(config)


def _case_id(c) -> str:
    return c.name.split(" - ")[0] if " - " in c.name else c.name


@pytest.mark.parametrize("case", ALL_CASES, ids=_case_id)
def test_real_api(runner, case):
    module = case.name.split("-")[0] if "-" in case.name else "未分组"
    allure.dynamic.epic("智策云语 接口自动化")
    allure.dynamic.feature(module)
    allure.dynamic.story(case.name)
    allure.dynamic.tag(*case.tags)

    with allure.step(f"{case.method} {case.path}"):
        if case.params:
            with allure.step(f"参数: {json.dumps(case.params, ensure_ascii=False, default=str)}"):
                pass
        entry = runner.run_one(case)

    with allure.step(f"响应: HTTP {entry.status_code}"):
        pass

    # 附件：请求 + 响应（便于失败排查）
    allure.attach(
        json.dumps({
            "method": entry.method,
            "url": entry.url,
            "params": case.params,
            "body": case.body,
        }, ensure_ascii=False, default=str, indent=2),
        name="请求信息",
        attachment_type=allure.attachment_type.JSON,
    )
    body_preview = json.dumps(entry.response_body, ensure_ascii=False, default=str)[:4000]
    allure.attach(
        body_preview,
        name="响应内容",
        attachment_type=allure.attachment_type.TEXT,
    )
    if not entry.passed:
        allure.attach(entry.reason, name="失败原因", attachment_type=allure.attachment_type.TEXT)
        pytest.fail(entry.reason)
