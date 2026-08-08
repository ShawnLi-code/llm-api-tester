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
├── scripts/
│   ├── project_config.py   # 多项目配置加载（核心）
│   ├── run_real.py         # 跑真实环境用例
│   ├── convert_excel_to_yaml.py  # Excel -> YAML 转换器
│   ├── gen_allure_report.py      # 一键生成 Allure 报告
│   └── serve_allure_report.py    # HTTP 服务打开报告
├── projects/
│   └── <项目名>/
│       ├── config.json     # base_url/token/epic 等项目配置
│       ├── cases/*.yaml    # 转换后的用例（入库）
│       ├── auth.json       # token（gitignore，勿提交）
│       └── reports/        # allure 结果与报告（gitignore）
└── tests/
    ├── test_core.py        # 单元测试（模型/加载/校验/生成）
    └── test_e2e.py         # 端到端（demo server + 报告）
```

## 验证结果

```
30 passed                    # pytest 自检全量
8 passed, 0 failed           # CLI 端到端（demo server）
78/176 通过（44.3%）          # 智策云语真实环境（98 失败 = 服务端缺陷暴露）
```

## 真实环境接入（多项目隔离）

框架与项目数据完全分离：每个被测系统一个 `projects/<项目名>/` 目录，
互相不干扰，新增项目 = 新建目录 + config.json，零代码改动。

### 新建项目
```bash
mkdir projects/新项目
# 复制 ziceyunyu/config.json 并修改：
#   base_url / gateway_prefix / auth_file / auth_cookie / epic
#   excel / desc（转换器素材路径，相对测试用例根目录）
cp ../recon/auth_default.json projects/新项目/auth.json   # 各自项目的 token
```
config.json 字段：
- `base_url`：被测环境根地址
- `gateway_prefix`：网关前缀（如 gw/enterprise），拼在 base_url 后
- `auth_file` / `auth_cookie`：token 文件与 cookie 名（每项目独立，gitignore）
- `epic`：Allure 报告项目名
- `excel` / `desc`：Excel 用例与接口描述 json（转换器素材）

### Excel → YAML
```bash
python scripts/convert_excel_to_yaml.py                 # 默认 -> projects/ziceyunyu/cases/
python scripts/convert_excel_to_yaml.py --out projects/新项目/cases --excel 新项目.xlsx --desc 新项目描述.json
```
只转 GET 查询类（正常流/参数校验/边界值）+ 安全非查询类（僵尸验证/异常/权限），
路径参数拆为 params，**预期关键字段列 → schema 断言**（required 字段校验），
预期状态码用 Excel 原始值（边界值/参数校验保留 400 预期以暴露服务端校验缺失）。

### 运行与报告
```bash
python scripts/run_real.py                      # 默认项目 ziceyunyu 全量
python scripts/run_real.py --project 新项目      # 指定项目
python scripts/run_real.py 概览                  # 按模块
python scripts/run_real.py --normal-only         # 只跑正常流

python scripts/gen_allure_report.py --project 新项目   # 生成 Allure
# 打开 projects/新项目/reports/allure-report/index.html
```
认证：每项目读自己的 `auth.json` 的 Admin-Token cookie；
token 过期需重新抓取（浏览器 devtools -> Application -> Cookies）。

Allure 多文件版不能直接双击 file:// 打开（浏览器禁止 fetch 本地 JSON，
会一直"加载中"）。**单文件版可双击直接打开**：
```bash
tools/allure-2.30.0/bin/allure.bat generate projects/新项目/reports/allure-results \
  -o projects/新项目/reports/allure-report-single --single-file --clean
```
或起本地 HTTP 服务：`python scripts/serve_allure_report.py`。
每个用例含：请求信息附件 + 响应内容附件 + 失败原因附件，
按 epic(项目名) / feature(模块) / story(用例) 分层。

### pytest 直接跑（CI 用）
```bash
OMP_PROJECT=新项目 python -m pytest tests/test_real.py --alluredir=projects/新项目/reports/allure-results
```


### 已知环境问题
- dev 环境 API 网关偶发不可用（返回 SPA index.html 兜底），表现为 200 + text/html，
  需等环境恢复后重跑（2026-08-08 12:50 观测到）。
- 服务端对边界值/参数校验的非法参数不返回 400（实测 200），保留 400 预期以暴露缺陷。
