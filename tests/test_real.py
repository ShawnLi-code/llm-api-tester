"""真实环境用例的 pytest 封装（Allure 报告用，多项目隔离版）。

从 projects/<项目>/cases/*.yaml 加载，参数化为 pytest 用例，
每用例输出: 请求信息附件 + 响应附件 + Allure 步骤。

用法:
    python -m pytest tests/test_real.py --alluredir=reports/allure-results
    python -m pytest tests/test_real.py --alluredir=... -o OMP_PROJECT=新项目
    tools/allure-2.30.0/bin/allure.bat generate reports/allure-results -o reports/allure-report
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import allure
import pytest

from tester.core.loader import load_cases
from tester.core.runner import Runner, RunnerConfig

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from project_config import base_url_of, get_auth_token, load_config

PROJECT = os.environ.get("OMP_PROJECT", "ziceyunyu")
CFG = load_config(PROJECT)


def get_token() -> str:
    return get_auth_token(CFG)


def _all_cases():
    cases = []
    for f in sorted(CFG["cases_dir"].glob("*.yaml")):
        cases.extend(load_cases(f))
    return cases


ALL_CASES = _all_cases()


@pytest.fixture(scope="session")
def runner():
    config = RunnerConfig(
        base_url=base_url_of(CFG),
        headers={"Authorization": get_token()},
        timeout=CFG.get("timeout", 15),
        retries=CFG.get("retries", 1),
    )
    return Runner(config)


def _case_id(c) -> str:
    return c.name.split(" - ")[0] if " - " in c.name else c.name


@pytest.mark.parametrize("case", ALL_CASES, ids=_case_id)
def test_real_api(runner, case):
    module = case.name.split("-")[0] if "-" in case.name else "未分组"
    allure.dynamic.epic(CFG["epic"])
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
