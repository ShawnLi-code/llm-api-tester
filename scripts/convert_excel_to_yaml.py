#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 接口测试用例.xlsx 转成 llm-api-tester 的 YAML 用例格式。

规则：
  - 只转查询类（GET）+ 测试类型为 正常流/参数校验/边界值(仅GET) 的用例
  - 路径里的 ?param=xxx 拆成 params
  - 预期响应码 200/400/401/404 等映射到 expected.status
  - 生成到 接口自动化/examples/real_cases/<模块>.yaml
"""
import re
from pathlib import Path

import openpyxl

BASE = Path(__file__).resolve().parent
XLSX = BASE / "接口测试用例.xlsx"
OUT = BASE / "接口自动化" / "examples" / "real_cases"

# 可自动化的测试类型（先跑查询类）
KEEP_TYPES = {"正常流", "参数校验", "边界值"}


def parse_params(text: str | None) -> dict:
    """?pageNum=xxx&pageSize=xxx -> {'pageNum': 'xxx', ...}，去掉 xxx 占位符"""
    if not text:
        return {}
    text = str(text).strip()
    if text.startswith("?"):
        text = text[1:]
    params = {}
    for pair in text.split("&"):
        if "=" not in pair:
            continue
        k, v = pair.split("=", 1)
        k, v = k.strip(), v.strip()
        if not k:
            continue
        if v in ("xxx", "XXX", "{xxx}", ""):
            continue
        params[k] = v
    return params


def parse_status(text: str | None) -> int | None:
    """'HTTP 200 code=200' -> 200; '200 or 404' -> 200(取第一个)"""
    if not text:
        return None
    m = re.search(r"(\d{3})", str(text))
    return int(m.group(1)) if m else None


def parse_path(path: str) -> tuple[str, dict]:
    """'call-record/list?pageNum=xxx' -> ('/call-record/list', {'pageNum': 'xxx'})"""
    path = str(path).strip()
    if "?" in path:
        p, q = path.split("?", 1)
        return ("/" + p.lstrip("/"), parse_params("?" + q))
    return ("/" + path.lstrip("/"), {})


def main():
    wb = openpyxl.load_workbook(XLSX, read_only=True)
    ws = wb["接口测试用例"]
    rows = list(ws.iter_rows(values_only=True))
    data = rows[1:]

    OUT.mkdir(parents=True, exist_ok=True)
    by_module: dict[str, list] = {}
    skipped = 0
    for r in data:
        module, path, method, case_id, title, ttype = r[0], r[1], r[2], r[3], r[4], r[5]
        status = r[7]
        if method != "GET":
            skipped += 1
            continue
        if ttype not in KEEP_TYPES:
            skipped += 1
            continue
        clean_path, qparams = parse_path(path)
        exp_status = parse_status(status)
        if exp_status is None:
            skipped += 1
            continue
        case = {
            "name": f"{case_id} - {title}"[:60].replace(":", "："),
            "method": "GET",
            "path": clean_path,
            "params": qparams,
            "expected": {"status": exp_status},
            "tags": [str(ttype)],
        }
        by_module.setdefault(str(module), []).append(case)

    total = 0
    for module, cases in sorted(by_module.items()):
        safe = re.sub(r"[^\w\u4e00-\u9fff]+", "_", module).strip("_") or "misc"
        out = OUT / f"{safe}.yaml"
        def yaml_val(v):
            v = str(v)
            if any(ch in v for ch in "%:{}[],#&*!|>'\"\n"):
                return "'" + v.replace("'", "''") + "'"
            return v

        text = "cases:\n"
        for c in cases:
            text += f"  - name: {c['name']}\n"
            text += f"    method: {c['method']}\n"
            text += f"    path: {c['path']}\n"
            if c["params"]:
                text += "    params:\n"
                for k, v in c["params"].items():
                    text += f"      {k}: {yaml_val(v)}\n"
            text += f"    expected:\n      status: {c['expected']['status']}\n"
            text += f"    tags: [{', '.join(c['tags'])}]\n"
        out.write_text(text, encoding="utf-8")
        total += len(cases)
        print(f"  {module}: {len(cases)} 条 -> {out.name}")
    print(f"\n合计 {total} 条查询用例，跳过 {skipped} 条")


if __name__ == "__main__":
    main()
