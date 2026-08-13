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
python -m tester.cli --cases examples/basic.yaml --base-url http://127.0.0.1:8000 --workers 8   # 并发 8 线程
python -m tester.cli --cases examples/basic.yaml --base-url http://127.0.0.1:8000 --verbose     # 打印请求/响应体
python -m tester.cli --cases ... --triage          # 失败三分类（bug/env/stale_case）

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
可选断言：`status_in`（多个可接受状态码）、`latency_ms_max`（响应耗时上限，超时判失败）。

## 响应包装兼容（unwrap_data）

国内后端常见统一包装 `{code, msg, data}`。默认 `unwrap_data: true` 时，`schema`/`body`
断言自动作用到 `data` 层；通用 REST API 可在 `config.json` 或 CLI `--no-unwrap` 关闭，
也可在单个用例 `expected.unwrap_data: false` 覆盖：

```yaml
cases:
  - name: 标准 REST 响应（不解包）
    method: GET
    path: /api/v1/items
    expected:
      status: 200
      unwrap_data: false
      schema:
        type: object
        required: [items, total]
```

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
│   ├── core/analyzer.py    # 失败三分类（规则 + LLM 精炼）
│   ├── recorder.py         # 流量录制/回放（P2）
│   ├── rag.py              # 轻量 RAG 知识库（P2）
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
    ├── test_e2e.py         # 端到端（demo server + 报告）
    ├── test_evolution.py   # triage / RAG / recorder / CLI
    └── test_runner_ext.py  # 并发 / 重试 / unwrap / latency 断言
```

## 质量保障

```bash
python -m pytest tests/        # 43 个测试全量自检
ruff check src tests scripts    # lint（E/F/W/I/UP/B/SIM）
```

## CI / 定时回归 / 飞书通知

GitHub Actions 提供两条流水线，均可在仓库 **Actions** 页面查看：

### 1. CI（push/PR 触发）— `.github/workflows/ci.yml`
- 3 个 Python 版本（3.10/3.11/3.12）跑 pytest + ruff
- main 分支 push 失败时自动发飞书通知

### 2. 定时回归（cron + 手动）— `.github/workflows/regression.yml`
- 每天 **09:00（北京时间）** 自动跑真实环境用例（`tests/test_real.py`）
- 也可在 Actions 页面手动触发（Run workflow）
- 失败不中断：生成 Allure 报告 → 上传 artifact → 飞书通知（含通过率 / 失败列表 / 401 过期提示）

### 需要配置的 GitHub Secrets

仓库 **Settings → Secrets and variables → Actions → New repository secret**：

| Secret 名 | 必填 | 内容 |
|---|---|---|
| `OMP_AUTH_JSON` | ✅（定时回归用） | `projects/ziceyunyu/auth.json` 的完整内容（含 token） |
| `FEISHU_WEBHOOK` | 二选一 | 飞书群机器人 webhook（模式 A） |
| `FEISHU_SECRET` | 可选 | 群机器人"签名校验"密钥 |
| `FEISHU_APP_ID` | 二选一 | 飞书应用机器人 App ID（模式 B 单聊） |
| `FEISHU_APP_SECRET` | 二选一 | 应用机器人 App Secret |
| `FEISHU_OPEN_ID` | 模式 B | 接收人 open_id（用 `get_open_id.py` 查） |

> token 会过期，过期后需更新 `OMP_AUTH_JSON`。也可以不配定时回归，只手动在本地跑 `run_real.py`。

### 配置飞书通知（两种模式任选）

**模式 A：群机器人**（消息发到群里）
1. 飞书群 → 设置 → 群机器人 → 自定义机器人 → 复制 webhook 填 `FEISHU_WEBHOOK`
2. 勾了"签名校验"则 secret 填 `FEISHU_SECRET`

**模式 B：应用机器人**（消息单聊发给你，需要应用审核）
1. 开放平台 `open.feishu.cn/app` 创建企业自建应用，加"机器人"能力，发布审核
2. 开通权限：`contact:user.id:readonly`（查 open_id）+ `im:message`（发消息），重新发布生效
3. 查接收人 open_id：
   ```bash
   FEISHU_APP_ID=cli_xxx FEISHU_APP_SECRET=xxx python scripts/get_open_id.py --mobile 你的手机号
   ```
4. 把 `FEISHU_APP_ID / FEISHU_APP_SECRET / FEISHU_OPEN_ID` 配到 Secrets 或本地环境变量

本地测试：`FEISHU_APP_ID=... FEISHU_APP_SECRET=... FEISHU_OPEN_ID=... \
python scripts/notify_feishu.py --junit <junit文件>`

## 验证结果

```
43 passed                    # pytest 自检全量（单元 + E2E + 演化特性）
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
python scripts/run_real.py --workers 8           # 并发执行（大量用例时显著提速）

python scripts/gen_allure_report.py --project 新项目   # 生成 Allure
# 打开 projects/新项目/reports/allure-report/index.html
```
认证：每项目读自己的 `auth.json` 的 Admin-Token cookie；
token 过期需重新抓取（浏览器 devtools -> Application -> Cookies）。
若某次跑完超过半数失败均为 401，会提示 token 可能过期并指引刷新位置。

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

### 本地开发
```bash
pip install -e ".[dev]"      # 含 pytest/ruff
ruff check src tests scripts  # 静态检查
python -m pytest tests/       # 全量自检
```


### 已知环境问题
- dev 环境 API 网关偶发不可用（返回 SPA index.html 兜底），表现为 200 + text/html，
  需等环境恢复后重跑（2026-08-08 12:50 观测到）。
- 服务端对边界值/参数校验的非法参数不返回 400（实测 200），保留 400 预期以暴露缺陷。
