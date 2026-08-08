#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 接口测试用例.xlsx 转成 llm-api-tester 的 YAML 用例格式（v2）。

规则：
  1. 查询类（GET）: 正常流/参数校验/边界值
  2. 安全非查询类（不污染环境）:
     - 僵尸验证 (POST/DELETE/PUT): 预期 404/废弃确认，无有效数据变更
     - 异常 (POST): 对查询接口发错误方法，预期 405/400，不写数据
     - 权限 (POST): 预期 401/403
  3. 中文接口描述: 从 recon/api_descriptions.json（接口文档解析）注入 name
  4. 路径修正: {userId} 模板替换为 1, 易失效参数过滤（时间/长ID/dynamicLabelJson）
"""
import json
import re
from pathlib import Path

import openpyxl

BASE = Path(__file__).resolve().parent
XLSX = BASE / "接口测试用例.xlsx"
OUT = BASE / "接口自动化" / "examples" / "real_cases"
DESC = BASE / "recon" / "api_descriptions.json"
# GET 可自动化类型
GET_TYPES = {"正常流", "参数校验", "边界值"}
# 安全非查询类型（不污染环境）
SAFE_WRITE_TYPES = {"僵尸验证", "异常", "权限"}

# 僵尸验证类中仍会真实写库的高危路径片段（排除，避免污染环境）
RISKY_WRITE_MARKERS = (
    "create", "add", "update", "save", "batch", "import", "upload",
    "register", "login", "/del", "delete", "remove",
)

# 跳过时间参数（固定值导致服务端 LocalDateTime 解析失败）
TIME_PARAMS = {"startTime", "endTime", "startDate", "endDate",
               "sendStartTime", "sendEndTime", "queryDate"}


def load_desc() -> dict:
    if not DESC.exists():
        return {}
    return json.loads(DESC.read_text(encoding="utf-8"))


def parse_params(text: str | None) -> dict:
    """?pageNum=xxx&pageSize=xxx -> {'pageNum': 'xxx', ...}，去掉占位符与易失效参数"""
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
        if k in TIME_PARAMS:
            continue
        if k == "dynamicLabelJson":
            continue
        if v.isdigit() and len(v) >= 16:
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


def parse_fields(text: str | None) -> list[str] | None:
    """预期关键字段 -> schema required（只接受纯字段列表）"""
    if not text:
        return None
    parts = [p.strip() for p in str(text).split(",")]
    if not parts or any(not p or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", p) for p in parts):
        return None
    return parts


def parse_path(path: str) -> tuple[str, dict]:
    """'call-record/list?pageNum=xxx' -> ('/call-record/list', {'pageNum': 'xxx'})

    路径模板 {userId}/{id}/{callScriptId} 等替换为 1；DELETE 的 {id} 用 999999（不存在的 id，安全）。
    """
    path = str(path).strip()
    q = ""
    if "?" in path:
        path, q = path.split("?", 1)
    path = "/" + path.lstrip("/")
    path = re.sub(r"\{(\w+)\}", "999999" if path.count("{") >= 1 and "del" in path.lower() else "1", path)
    return path, parse_params("?" + q) if q else {}


def parse_body(text: str | None) -> dict | None:
    """请求参数(示例)列可能是 JSON -> 解析为 body"""
    if not text:
        return None
    t = str(text).strip()
    if t.startswith("{") and t.endswith("}"):
        try:
            return json.loads(t)
        except json.JSONDecodeError:
            return None
    return None


def main():
    wb = openpyxl.load_workbook(XLSX, read_only=True)
    ws = wb["接口测试用例"]
    rows = list(ws.iter_rows(values_only=True))
    data = rows[1:]
    desc = load_desc()

    OUT.mkdir(parents=True, exist_ok=True)
    by_module: dict[str, list] = {}
    skipped = 0

    for r in data:
        module, path, method, case_id, title, ttype = r[0], r[1], r[2], r[3], r[4], r[5]
        status = r[7]
        method = str(method).upper()
        ttype = str(ttype)

        # 类型过滤
        if method == "GET":
            if ttype not in GET_TYPES:
                skipped += 1
                continue
        else:
            if ttype not in SAFE_WRITE_TYPES:
                skipped += 1  # 正常流/差异标记等写操作会污染环境，跳过
                continue
            if method not in ("POST", "DELETE", "PUT"):
                skipped += 1
                continue
            # 僵尸验证类里仍会真实写库的高危接口（create/add/upload/register 等）排除。
            # DELETE 删除不存在的 id 本身安全，不受此限制。
            if (ttype == "僵尸验证" and method in ("POST", "PUT")
                    and any(m in str(path).lower() for m in RISKY_WRITE_MARKERS)):
                skipped += 1
                continue

        clean_path, qparams = parse_path(path)
        exp_status = parse_status(status)
        expected: dict = {}
        # 僵尸验证：接口可能已废弃(404)或仍在线(200)，两者都接受
        if ttype == "僵尸验证":
            expected["status_in"] = [exp_status or 200, 404]
        else:
            expected["status"] = exp_status if exp_status is not None else 200

        # 关键字段 -> schema（仅对确定成功响应有意义；僵尸验证 status_in 不校验字段）
        if expected.get("status") == 200:
            fields = parse_fields(r[8])
            if fields:
                expected["schema"] = {
                    "type": "object",
                    "required": fields,
                    "properties": {f: {} for f in fields},
                }

        # 中文描述：接口文档标题
        desc_key = f"{method} {clean_path}"
        desc_info = desc.get(desc_key) or desc.get(f"{method} {clean_path.split('?')[0]}")
        cn_title = ""
        if desc_info:
            cn_title = desc_info["title"]
        elif title and title != "正常请求":
            cn_title = str(title)

        case = {
            "name": f"{case_id} - {cn_title}"[:70].replace(":", "：") if cn_title else f"{case_id}",
            "method": method,
            "path": clean_path,
            "params": qparams,
            "body": parse_body(r[6]) if method == "POST" and parse_body(r[6]) else None,
            "headers": {"Authorization": ""} if ttype == "权限" else {},
            "expected": expected,
            "tags": [ttype],
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
            if c.get("headers"):
                text += "    headers:\n"
                for k, v in c["headers"].items():
                    text += f"      {k}: {yaml_val(v)}\n"
            if c["params"]:
                text += "    params:\n"
                for k, v in c["params"].items():
                    text += f"      {k}: {yaml_val(v)}\n"
            if c["body"]:
                text += "    body:\n"
                for k, v in c["body"].items():
                    text += f"      {k}: {yaml_val(v)}\n"
            if "status_in" in c["expected"]:
                text += f"    expected:\n      status_in: [{', '.join(str(s) for s in c['expected']['status_in'])}]\n"
            else:
                text += f"    expected:\n      status: {c['expected']['status']}\n"
            schema = c["expected"].get("schema")
            if schema:
                text += "      schema:\n"
                text += "        type: object\n"
                text += f"        required: [{', '.join(schema['required'])}]\n"
            text += f"    tags: [{', '.join(c['tags'])}]\n"
        out.write_text(text, encoding="utf-8")
        total += len(cases)
        print(f"  {module}: {len(cases)} 条 -> {out.name}")
    print(f"\n合计 {total} 条用例，跳过 {skipped} 条")


if __name__ == "__main__":
    main()
