# AI 接口自动化测试框架 (llm-api-tester)

基于调研结论落地的 AI 辅助接口测试框架：**OpenAPI 契约驱动（确定性，P0）+ LLM 可选增强（P1/P2）**。

## 架构设计（来自 GitHub 调研）

| 层 | 参考方案（GitHub） | 本项目实现 |
|---|---|---|
| 底座 | httprunner / aomaker / pytestDemo | `tester.core`：YAML 用例 + httpx 执行 + 强断言 |
| 契约生成 | schemathesis / microsoft/restler-fuzzer | `tester.generators.schema`：OpenAPI → 用例（含 path 参数示例值、requestBody 示例、响应状态码） |
| LLM 增强 | WHartTest / APIAuto | `tester.generators.llm`：无 KEY 自动降级，有 KEY 生成边界用例 + 失败分析 |
| 自愈分析 | ReportPortal / flaky-test-detector | `explain_failure()`：失败原因分析 + 修复建议 |

## 快速开始

```bash
pip install -e .            # 安装（httpx/pyyaml/jsonschema/pydantic）
python -m tester.demo_server  # 启动 demo API (127.0.0.1:8000)

# 运行 YAML 用例
python -m tester.cli --cases examples/basic.yaml --base-url http://127.0.0.1:8000

# 从 OpenAPI 生成用例
python -m tester.cli --gen-openapi examples/openapi.json --out examples/from_spec.yaml

# 运行测试套件
python -m pytest tests/
```

## 用例格式 (examples/basic.yaml)

```yaml
cases:
  - name: health check
    method: GET
    path: /health
    expected:
      status: 200
      body: {status: ok}          # 精确子集匹配
      # schema: {...}             # JSON Schema 校验（draft 2020-12）
  - name: create user
    method: POST
    path: /users
    body: {name: carol}
    expected:
      status: 201
      schema:
        type: object
        required: [id, name]
```

断言三选一或组合：`status`（状态码）、`body`（键子集精确匹配）、`schema`（JSON Schema）。

## LLM 增强（可选）

设置 `OPENAI_API_KEY`（兼容任何 OpenAI 风格端点，可用 `OPENAI_BASE_URL` 指向 DeepSeek 等）后：

- `generate_cases_from_spec()` — 从 OpenAPI spec 让 LLM 提出边界用例（鉴权失败、边界值、缺必填字段），返回带 `tags: [llm]` 的用例，人审后入库
- `explain_failure()` — 失败时 LLM 分析根因 + 修复建议

无 KEY 时两者自动返回空/提示，**绝不阻塞确定性测试**。

## 目录结构

```
├── pyproject.toml
├── pytest.ini
├── examples/
│   ├── basic.yaml          # 手写示例用例（8 个）
│   ├── openapi.json        # 演示 OpenAPI spec
│   └── from_spec.yaml      # CLI 生成的用例
├── src/tester/
│   ├── core/
│   │   ├── case.py         # TestCase/Expected 模型（pydantic）
│   │   ├── loader.py       # YAML 加载（跳过 enabled: false）
│   │   ├── contract.py     # JSON Schema 校验 + $ref 解析
│   │   └── runner.py       # httpx 执行器 + 报告条目
│   ├── generators/
│   │   ├── schema.py       # OpenAPI → 确定性用例
│   │   └── llm.py          # LLM 边界用例 + 失败分析（可选）
│   ├── report.py           # 摘要 + JSON 报告
│   ├── cli.py              # CLI 入口
│   └── demo_server.py      # 演示 mock API（stdlib only）
└── tests/
    ├── test_core.py        # 单元测试（模型/加载/校验/生成）
    └── test_e2e.py         # 端到端（demo server + 报告）
```

## 验证结果

```
16 passed, 1 warning in 3.87s     # pytest 全量
8 passed, 0 failed                # CLI 端到端（demo server）
generated 4 cases -> examples/from_spec.yaml   # OpenAPI 生成
```

## 演进路线

- [ ] P1: LLM 生成用例入 CI（人审流程：生成 → review → 入库）
- [ ] P1: 失败自动三分类（真 bug / 环境 / 用例过期）
- [ ] P2: RAG 知识库（接口文档/需求文档 → 生成上下文）
- [ ] P2: Keploy 式流量录制回放（真实流量 → mock + 用例）
