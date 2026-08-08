#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""项目配置加载：多项目隔离的核心。

每个被测项目一个目录 projects/<name>/，含 config.json：
    {
      "name": "中文名",
      "base_url": "http://xxx",
      "gateway_prefix": "gw/enterprise",   # 可选，拼在 base_url 后
      "auth_file": "auth.json",            # 相对项目目录，gitignore
      "auth_cookie": "Admin-Token",        # 从 cookies 数组取该名的 value
      "epic": "Allure epic 名",
      "timeout": 15, "retries": 1,
      "excel": "../../接口测试用例.xlsx",    # 转换器素材（相对测试用例根目录）
      "desc": "../../recon/api_descriptions.json"
    }
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

BASE = Path(__file__).resolve().parents[1]
PROJECTS = BASE / "projects"
DEFAULT_PROJECT = "ziceyunyu"


def resolve_project(name: str | None) -> str:
    """解析 --project 参数；缺省取默认项目，不存在则报错。"""
    name = name or DEFAULT_PROJECT
    if not (PROJECTS / name / "config.json").exists():
        existing = sorted(p.name for p in PROJECTS.iterdir() if p.is_dir())
        print(f"!! 项目 {name!r} 不存在（config.json 缺失）。可用: {existing}")
        sys.exit(1)
    return name


def load_config(name: str) -> dict[str, Any]:
    cfg = json.loads((PROJECTS / name / "config.json").read_text(encoding="utf-8"))
    cfg["project"] = name
    cfg["project_dir"] = PROJECTS / name
    cfg["cases_dir"] = PROJECTS / name / "cases"
    cfg["reports_dir"] = PROJECTS / name / "reports"
    return cfg


def get_auth_token(cfg: dict[str, Any]) -> str:
    """从项目 auth 文件取 token（cookies 数组 + cookie 名匹配）。"""
    auth_file = cfg["project_dir"] / cfg.get("auth_file", "auth.json")
    if not auth_file.exists():
        return ""
    auth = json.loads(auth_file.read_text(encoding="utf-8"))
    for c in auth.get("cookies", []):
        if c["name"] == cfg.get("auth_cookie", "Admin-Token"):
            return c["value"]
    return ""


def base_url_of(cfg: dict[str, Any]) -> str:
    url = cfg["base_url"].rstrip("/")
    prefix = cfg.get("gateway_prefix", "").strip("/")
    return f"{url}/{prefix}" if prefix else url
