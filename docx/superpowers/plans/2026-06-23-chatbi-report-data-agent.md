# chatbi-report Skill 实施计划

> **面向 Agent 执行者：** 必备子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 任务逐项实施本计划。步骤使用复选框（`- [ ]`）语法以便跟踪。

**目标：** 实现 `chatbi-report` skill —— 用户上传一份 Markdown 样例，其 `<th>` 单元格带有 `data-idx="BAS_0263"`（SQLBot 指标 ID）加中文显示名文本，DeerFlow 的 lead agent 将端到端调用 SQLBot `query-report-info`，透视为宽表行，通过 LLM 生成的 pandas 求值计算列，最终把 `report.json` / `report.md` / `report.docx` 输出到线程输出目录。

**架构：** Skill 作为触发层；现有的 DeerFlow lead agent + `SummarizationMiddleware` + LangGraph checkpointer 作为执行层（不新增子 agent，不新增 middleware）。**确定性数据/校验/渲染工作**在 `skills/public/chatbi-report/scripts/*.py` 中由 lead agent 通过 `bash` 调用完成；**LLM 决策（计算列代码生成 + 失败重试）由 lead agent 在 turn 内直接调用 DeerFlow 已绑定模型完成**（参考 `skills/public/data-analysis/scripts/analyze.py` —— skill 脚本零 LLM 依赖），生成的源码用 `write_file` 工具落到 thread output 文件供后续 bash step 校验执行。中文显示名直接放在 MD 的 `<th>` 文本里——`render_docx` 从 AST 读取而不调用 SQLBot，因此即使 SQLBot 宕机，重新渲染已存储的 `report.json` 也能工作。

**两层执行契约：**

| 层 | 谁来做 | 在哪儿 | 产物 |
|---|---|---|---|
| LLM 层：从 `ComputeIR` 生成 `def compute_X(df: pd.DataFrame) -> pd.Series` 源码 | lead agent in-turn（已绑定 LangGraph 模型 + `prompts/compute_codegen.md`） | 不在脚本里 | `report.compute.<slug>.py` 写到 thread output |
| 校验/执行层：AST 白名单 + 签名 + 烟雾 + 示例 + Decimal 列计算 + 单位换算 + 静态 IR 抽取 | `compute.py` / `unit_conversion.py` CLI（纯 bash 调用，零 LLM） | `scripts/compute.py {extract-ir,assemble-wide,validate,evaluate}` | `report.{ir,wide,computed.<slug>}.json` |

**技术栈：** Python 3.12，`requests`（HTTP 客户端，真实 SQLBot 调用），`python-docx`（DOCX 渲染），`pandas`（计算列 DataFrame），`decimal.Decimal`（单位运算），`json`/`dataclasses`/`re`/`ast`（解析、校验），`pytest`（仅开发期测试，使用内置 `unittest.mock.patch` 隔离 HTTP，**不依赖 `pytest-httpx`**）。`requests`/`python-docx`/`pandas` 当前已通过现有 backend 依赖传递安装到 `uv` 环境（已用 `uv run python -c "import X"` 验证）；若未来 `uv.lock` 收紧导致缺失，则需 `cd backend && uv add requests python-docx pandas`。

**规格说明：** `docx/chatbi-report/chatbi-report-data-agent-design.md`

**配套文件：**
- `2026-06-23-chatbi-report-code-blocks.md` — 71 个围栏代码块（python/bash/json/markdown）按 `§任务.序号` 锚定，主体中每个被替换的位置以 `<!-- code-block: §N.M -->` 标记指明。
- `2026-06-23-chatbi-report-appendix-fixtures-and-tests.md` — **附录 A（10 个 MD fixture）**。任务 3 / 4 / 5 中"见附录 A.X"指此文件。**附录 B（集成测试源码 + expected_outputs）已 defer** —— 任务 11+12 移出本阶段，B.1–B.10 内容保留在该附录中但不再被本计划主体引用，待后续集成测试阶段重新启用并按新的两层架构改写 `conftest.py` 中的 `llm_complete` 路径。

**⚠️ 待按本计划新接口重新生成的代码块（执行任务 5 / 任务 9 时由实施者按主体指引重写）：**

| 代码块 | 当前行数 | 重写原因 |
|---|---|---|
| `code-blocks.md` §5.5（test_compute.py） | 182 | 旧接口含 `llm_complete` monkeypatch，按新接口重写为零 mock 测试 |
| `code-blocks.md` §5.7（compute.py） | 287 | 删除 `generate_pandas_function` + `llm_complete` 参数链；`run_smoke` 内补调 `validate_signature`（R3 修复）；新增 argparse CLI 入口 |
| `code-blocks.md` §5.8（compute_codegen.md prompt） | 66 | 顶部加"由 lead agent 加载"注释；强调函数必须带 `: pd.DataFrame` 类型注解 |
| `code-blocks.md` §9.1（SKILL.md 步骤 7/8 段） | 89 | 按"9 步分层契约表"重写 step 7（agent-turn）与 step 8a/8b（bash CLI） |

**保留不动：** §5.1–5.4（unit_conversion 测试与实现）、§5.6/§5.9/§5.10（运行/提交 bash），其余 65 个代码块全部不受影响。

---

## 文件结构

<!-- code-block: §preamble.1 (text, 56 lines) → see chatbi-report-code-blocks.md -->


**创建的生产文件（13 个）：** `SKILL.md`、`README.md`、`.env.example`、`scripts/{retry,sqlbot_client,md_lint,parse_md,compute,render_markdown,render_docx,assemble_status}.py`、`scripts/report_style.json`、`prompts/compute_codegen.md`，以及 `scripts/__init__.py`。

**创建的测试文件：** `scripts/tests/{__init__,conftest,test_retry,test_sqlbot_client,test_md_lint,test_parse_md,test_compute,test_render_markdown,test_render_docx,test_unit_conversion,test_assemble_status}.py`（11 个单元测试文件）。后端集成：`backend/tests/chatbi_report/{__init__,conftest}.py`（仅作为路径占位）+ `fixtures/sample_md/{happy,multi_chapter,multi_header,no_org_context,no_time_info,computed_columns,computed_with_examples,multi_header_computed,old_style_placeholder,lint_error}.md`（10 个 MD，由任务 3/4/5 创建）+ `fixtures/mock_sqlbot/{query_responses,partial_failure}.json`（由任务 2 创建；`code_error.json` / `down.json` 仅在 deferred 的集成测试中需要，本阶段不创建）。

**⚠️ Deferred（与 T11/T12 一起推迟）：** `fixtures/expected_outputs/{happy.json,happy.md,partial_query_failure.json,computed_columns.json}` —— 这是端到端集成测试的快照断言文件，单元测试不需要。`backend/tests/chatbi_report/fixtures/mock_sqlbot/code_error.json` 与 `down.json` 同理。当后续阶段重启集成测试时再创建。

**未变更：** `deerflow.agents.lead_agent.*`、`deerflow.subagents.*`、LangGraph 运行时、Gateway API、前端、`SummarizationMiddleware`、LangGraph checkpointer。

---

## 任务 1：`retry.py` 带指数退避的装饰器

**文件：**
- 新建：`skills/public/chatbi-report/scripts/__init__.py`（空文件）
- 新建：`skills/public/chatbi-report/scripts/retry.py`
- 新建：`skills/public/chatbi-report/scripts/tests/__init__.py`（空文件）
- 新建：`skills/public/chatbi-report/scripts/tests/conftest.py`
- 新建：`skills/public/chatbi-report/scripts/tests/test_retry.py`

**接口：**
- 消费：任意同步可调用对象，重试规范（`max_attempts`、`backoff`、`retry_on` 异常类型元组）
- 产出：`retry(...)` 装饰器，`exponential(base, max_delay)` 工厂返回 `Backoff` 策略

本模块处于依赖图最底层（任务 2、4、5 都消费它），因此最先交付并获得最充分的单元覆盖。

- [ ] **步骤 1：创建空的 `__init__.py` 文件**

分别创建 `skills/public/chatbi-report/scripts/__init__.py` 和 `skills/public/chatbi-report/scripts/tests/__init__.py`，每个仅含一个换行。便于 pytest 在不报 `ModuleNotFoundError` 的情况下发现测试模块。

- [ ] **步骤 2：创建带共享 fixture 的 `conftest.py`**

创建 `skills/public/chatbi-report/scripts/tests/conftest.py`：

<!-- code-block: §1.1 (python, 28 lines) → see chatbi-report-code-blocks.md -->


- [ ] **步骤 3：先写失败测试 —— 首次成功**

创建 `skills/public/chatbi-report/scripts/tests/test_retry.py`：

<!-- code-block: §1.2 (python, 94 lines) → see chatbi-report-code-blocks.md -->


- [ ] **步骤 4：运行测试，验证失败**

在项目根目录运行：
<!-- code-block: §1.3 (bash, 2 lines) → see chatbi-report-code-blocks.md -->

期望：5 个测试全部报 `ModuleNotFoundError: No module named 'retry'`。

- [ ] **步骤 5：实现 `retry.py`**

创建 `skills/public/chatbi-report/scripts/retry.py`：

<!-- code-block: §1.4 (python, 55 lines) → see chatbi-report-code-blocks.md -->


- [ ] **步骤 6：运行测试，验证全部通过**

在项目根目录运行：
<!-- code-block: §1.5 (bash, 2 lines) → see chatbi-report-code-blocks.md -->

期望：5 passed。

- [ ] **步骤 7：提交**

<!-- code-block: §1.6 (bash, 13 lines) → see chatbi-report-code-blocks.md -->


---

## 任务 2：`sqlbot_client.py` —— 真实 + mock 客户端（per-idx 语义）

**文件：**
- 新建：`skills/public/chatbi-report/scripts/sqlbot_client.py`
- 新建：`skills/public/chatbi-report/scripts/tests/test_sqlbot_client.py`

**接口：**
- 消费：`SQLBOT_BASE_URL` 环境变量（无需 API key，依规格 2026-06-23），`requests.post(...)`，`retry.retry` + `retry.exponential`（来自任务 1 的 `retry.py`）
- 产出：`OrgContext`（dataclass），`QueryReportInfoResponse`（带 `code: int`、`data: list[dict]` 的 dataclass），`SQLBotError` 异常，`RealSQLBotClient`（HTTP POST 到 `/api/v1/indicator/query-report-info`，**`query_report_info` 用 `@retry(max_attempts=3, backoff=exponential(...), retry_on=(ConnectionError, Timeout, HTTPError))` 装饰**，当 `code != 0` 时抛出 `SQLBotError`且不重试），`MockSQLBotClient`（按 `idx_id` 读取 fixture JSON，不需要重试）

两个客户端都强制 **per-idx 调用约定**：`query_report_info(...)` 每次针对一个 `idx_id` 调用，传入 `index_info=[{"idx_id": idx}]`。1:1 响应↔idx 的映射消除了 SQLBot "响应中无 idx_id" 的歧义（规格 §"⚠️ Phase 1 已知缺口"）。

**重试策略：** 瞬时 HTTP 错误（连接断开、超时、5xx）自动重试 3 次，指数退避（1s/2s/4s，cap 8s）。`SQLBotError`（code != 0 的业务级失败）**不重试** —— 401/403/参数错误这类是确定性失败，重试也不会变好。这把任务 1 的 `retry.py` 兑现为生产路径，而非死代码。

- [ ] **步骤 1：先写失败测试 —— 真实客户端正常路径**

创建 `skills/public/chatbi-report/scripts/tests/test_sqlbot_client.py`：

<!-- code-block: §2.1 (python, 100 lines) → see chatbi-report-code-blocks.md -->


- [ ] **步骤 2：运行测试，验证失败**

<!-- code-block: §2.2 (bash, 2 lines) → see chatbi-report-code-blocks.md -->

期望：5 个测试全部报 `ModuleNotFoundError: No module named 'sqlbot_client'`。

- [ ] **步骤 3：创建测试使用的 fixture 文件**

创建 `backend/tests/chatbi_report/fixtures/mock_sqlbot/query_responses.json`：

<!-- code-block: §2.3 (json, 21 lines) → see chatbi-report-code-blocks.md -->


创建 `backend/tests/chatbi_report/fixtures/mock_sqlbot/partial_failure.json`：

<!-- code-block: §2.4 (json, 13 lines) → see chatbi-report-code-blocks.md -->


- [ ] **步骤 4：实现 `sqlbot_client.py`**

创建 `skills/public/chatbi-report/scripts/sqlbot_client.py`：

<!-- code-block: §2.5 (python, 119 lines) → see chatbi-report-code-blocks.md -->


- [ ] **步骤 5：运行所有 sqlbot_client 测试，验证通过**

<!-- code-block: §2.6 (bash, 2 lines) → see chatbi-report-code-blocks.md -->

期望：5 passed。

- [ ] **步骤 6：提交**

<!-- code-block: §2.7 (bash, 20 lines) → see chatbi-report-code-blocks.md -->


---

## 任务 3：`md_lint.py` —— 全部 chatbi 专属 ERROR/WARN 规则

**文件：**
- 新建：`skills/public/chatbi-report/scripts/md_lint.py`
- 新建：`skills/public/chatbi-report/scripts/tests/test_md_lint.py`
- 新建：`backend/tests/chatbi_report/fixtures/sample_md/happy.md`
- 新建：`backend/tests/chatbi_report/fixtures/sample_md/no_org_context.md`
- 新建：`backend/tests/chatbi_report/fixtures/sample_md/no_time_info.md`
- 新建：`backend/tests/chatbi_report/fixtures/sample_md/old_style_placeholder.md`
- 新建：`backend/tests/chatbi_report/fixtures/sample_md/lint_error.md`

**接口：**
- 消费：用户上传的 MD 文件路径
- 产出：`LintReport`（dataclass：`errors: list[LintError]`、`warnings: list[LintWarning]`），以及 `main()` CLI —— 干净时退出 0，存在任何 ERROR 时退出 1，仅有 WARN 时退出 0

**chatbi 专属 lint 规则（扩展 sqlbot 集合）—— 下列每条都必须在 `test_md_lint.py` 中至少有一条测试：**

| 严重级别 | 规则 | 触发条件 |
|---|---|---|
| ERROR | `<table>` 必须包含 `<thead>` 和 `<tbody>` | 任一标签缺失 |
| ERROR | 章节必须至少包含一个 `### 报表:` 块 | 空章节 |
| ERROR | F19：报表必须含 `> 机构:` 块 | 缺失 |
| ERROR | F19：报表必须含 `> 时期:` 块 | 缺失 |
| ERROR | `> 机构:` 格式 `branch_num=<code>; branch_short_name=<name>` | 字段缺失/多余 |
| ERROR | `> 时期:` 必须解析为 JSON 数组 | 不是 JSON 列表 |
| ERROR | 真实指标的 `<th>` 必须有 `data-idx` 属性（chatbi） | `<th>` 有文本但既无 `data-idx` 又无 `{{虚拟名}}`（即会渲染成空数据列） |
| ERROR | `data-idx` 值必须匹配 `^[A-Z]+_\d+$` | ID 格式错误 |
| ERROR | 计算列必须为 `{{虚拟名}}` 且不得同时具有 `data-idx` | `<th data-idx="X" data-unit="%">{{X同比}}</th>` |
| ERROR | `> 计算:` 块行必须形如 `<name> = <expr>`，1–200 字符 | 行格式错误 |
| ERROR | 表头计算列名必须出现在 `> 计算:` 块（左侧） | 孤立的 `{{}}` |
| ERROR | `> 计算:` 公式右侧必须引用表头集合中存在的 `data-idx` ID | 引用未查询的 idx |
| WARN | `<table>` 应使用 HTML 而非 Markdown 管道表 | `\|` 前缀的行 |
| WARN | `data-unit` 应为 `元/万元/亿元/%/百分点/个/次` 之一或自定义字符串 | 非空但未识别 |
| WARN | 同一计算名在 >1 个 thead 分支出现 | 重复 `{{虚拟名}}` |
| WARN | `<名>.示例:` 行格式错误 | 正则解析失败（丢弃示例，不阻塞） |
| WARN | 旧式 `<th>{{BAS_0263}}</th>` 占位符（无 `data-idx` 但 `{{}}` 匹配 `^[A-Z]+_\d+$`） | 向后兼容 —— chatbi 规格说 render_docx 在此情形回退 SQLBot 查询 |

- [ ] **步骤 1：创建跨 lint 测试使用的 5 个 MD fixture**

按所示路径创建各 fixture 文件。每个 fixture 的完整 MD 内容见配套文件 `2026-06-23-chatbi-report-appendix-fixtures-and-tests.md` 的 **A.1 `happy.md`、A.2 `no_org_context.md`、A.3 `no_time_info.md`、A.4 `old_style_placeholder.md`、A.5 `lint_error.md`**，原样复制即可。概要如下：

| Fixture | 触发的测试 |
|---|---|
| `happy.md` | 0 errors，0 warnings —— 干净正常路径 MD，含一个指标 + 一个计算列 + 一行 `.示例:` |
| `no_org_context.md` | F19（缺 `> 机构:`） |
| `no_time_info.md` | F19（缺 `> 时期:`） |
| `old_style_placeholder.md` | 仅 WARN —— `<th data-unit="个">{{BAS_0263}}</th>` 不带 `data-idx`（chatbi 向后兼容路径） |
| `lint_error.md` | 同时触发以下 6 条 lint ERROR：<br>① F19：`> 机构:` 格式缺少 `branch_short_name` 字段<br>② F19：`> 时期:` 非 JSON 数组（写成 `"2025"` 而非 `["2025"]`）<br>③ 真实指标 `<th>` 无 `data-idx` 且无 `{{}}` —— "无属性列"<br>④ `data-idx="bad id"` 不匹配 `^[A-Z]+_\d+$` 正则<br>⑤ 计算列 `<th data-idx="BAS_0263">{{收单商户同比}}</th>` 同时有 `data-idx` 和 `{{}}`<br>⑥ `> 计算:` 公式右侧引用 `MISSING_ID`（表头集合中不存在的 idx）|

- [ ] **步骤 2：先写失败测试**

创建 `skills/public/chatbi-report/scripts/tests/test_md_lint.py`：

<!-- code-block: §3.1 (python, 86 lines) → see chatbi-report-code-blocks.md -->


- [ ] **步骤 3：运行测试，验证失败**

<!-- code-block: §3.2 (bash, 2 lines) → see chatbi-report-code-blocks.md -->

期望：11 个测试全部报 `ModuleNotFoundError: No module named 'md_lint'`。

- [ ] **步骤 4：实现 `md_lint.py`**

创建 `skills/public/chatbi-report/scripts/md_lint.py`：

<!-- code-block: §3.3 (python, 386 lines) → see chatbi-report-code-blocks.md -->


- [ ] **步骤 5：运行所有 md_lint 测试，验证通过**

<!-- code-block: §3.4 (bash, 2 lines) → see chatbi-report-code-blocks.md -->

期望：11 passed。

若任何测试失败，需复核 fixture 期望的错误关键字（断言刻意宽松 —— 用子串匹配而非精确字符串）。

- [ ] **步骤 6：对 happy.md 做 CLI 烟雾验证**

<!-- code-block: §3.5 (bash, 3 lines) → see chatbi-report-code-blocks.md -->

期望输出以 `OK: 0 errors, 0 warning(s)` 结尾，退出码 `0`。

然后对 `lint_error.md` 再跑：
<!-- code-block: §3.6 (bash, 3 lines) → see chatbi-report-code-blocks.md -->

期望：多条 ERROR 行，退出码 `1`。

- [ ] **步骤 7：提交**

<!-- code-block: §3.7 (bash, 21 lines) → see chatbi-report-code-blocks.md -->


---

## 任务 4：`parse_md.py` —— MD → ReportDoc AST（二维表头 + 类目标签）

**文件：**
- 新建：`skills/public/chatbi-report/scripts/parse_md.py`
- 新建：`skills/public/chatbi-report/scripts/tests/test_parse_md.py`
- 新建：`backend/tests/chatbi_report/fixtures/sample_md/multi_chapter.md`
- 新建：`backend/tests/chatbi_report/fixtures/sample_md/multi_header.md`
- 新建：`backend/tests/chatbi_report/fixtures/sample_md/multi_header_computed.md`

**接口：**
- 消费：用户上传 MD 文件的路径（假定已通过 lint）
- 产出：`ReportDoc` dataclass 树 —— `sections[Section].reports[Report]`，每个 `Report` 拥有 `headers: Th[ ][ ]`（二维；外层为 thead 行索引，内层为该行的单元格）、`data_rows: list[dict]`、`computed_specs: list[ComputedSpec]`。外加一个供单元测试使用的 `parse_report()` 独立函数。

**Chatbi AST 形态（依规格）：**

| 维度 | 形态 |
|---|---|
| `headers` 形态 | `Th[ ][ ]`（二维，外层 = thead 行，内层 = 该行的单元格） |
| `Th` 字段 | text / is_indicator / idx_id? / data_unit? / is_computed / rowspan? / colspan? |
| `is_indicator` 规则 | 优先使用 `data-idx` HTML 属性；`{{idx_id}}` 占位符正则作为回退 |
| `is_computed` 规则 | `{{虚拟名}}` 文本 **且** 出现在 `> 计算:` 左侧 |
| 两者皆否 → | 类目标签：纯多级 thead 父级（`is_indicator=False`、`is_computed=False`、`idx_id=None`）；解析器自动设此值 |
| 旧式 `<th>{{BAS_0263}}</th>` | `is_indicator=True`、`is_computed=False`、`idx_id="BAS_0263"`；render_docx 在此回退到 SQLBot idx_name 查询 |

- [ ] **步骤 1：创建 3 个 MD fixture**

按所示路径创建 3 个 fixture 文件。每个 fixture 的完整 MD 内容见配套文件 `2026-06-23-chatbi-report-appendix-fixtures-and-tests.md` 的 **A.6 `multi_chapter.md`、A.7 `multi_header.md`、A.8 `multi_header_computed.md`**（`happy.md` 已在任务 3 通过 A.1 创建），原样复制即可。概要如下：

| Fixture | 触发的测试 |
|---|---|
| `multi_chapter.md` | 2 章节，每章 1 张报表 —— `test_parse_multi_chapter_two_sections` |
| `multi_header.md` | 2 行 thead（rowspan=2 + colspan=2），含一个类目父单元格（`is_indicator=False, is_computed=False, idx_id=None`）和两个真实指标子单元格 —— `test_parse_multi_header_two_row_thead` |
| `multi_header_computed.md` | 2 行 thead，含类目父级 + 真实指标 + colspan 下的计算列 —— `test_parse_multi_header_computed_under_category` |

`happy.md` 复用自任务 3（已存在于 `backend/tests/chatbi_report/fixtures/sample_md/happy.md`）；`test_parse_happy_md_returns_single_report`、`test_parse_org_and_time_into_report`、`test_all_idx_ids_collected_at_doc_level` 都引用它。

- [ ] **步骤 2：先写失败测试**

创建 `skills/public/chatbi-report/scripts/tests/test_parse_md.py`：

<!-- code-block: §4.1 (python, 91 lines) → see chatbi-report-code-blocks.md -->


- [ ] **步骤 3：运行测试，验证失败**

<!-- code-block: §4.2 (bash, 2 lines) → see chatbi-report-code-blocks.md -->

期望：7 个测试全部报 `ModuleNotFoundError: No module named 'parse_md'`。

- [ ] **步骤 4：实现 `parse_md.py`**

创建 `skills/public/chatbi-report/scripts/parse_md.py`：

<!-- code-block: §4.3 (python, 332 lines) → see chatbi-report-code-blocks.md -->


- [ ] **步骤 5：运行所有 parse_md 测试，验证通过**

<!-- code-block: §4.4 (bash, 2 lines) → see chatbi-report-code-blocks.md -->

期望：7 passed。

- [ ] **步骤 6：提交**

<!-- code-block: §4.5 (bash, 22 lines) → see chatbi-report-code-blocks.md -->


---

## 任务 5：`unit_conversion.py` + `compute.py` —— 校验器、Decimal 运算（零 LLM）

本任务拆分为两个模块以获得清晰的单元覆盖。`unit_conversion.py` 承载 Decimal 单位换算（纯函数）。`compute.py` 承载 **AST 白名单 + 签名 + 烟雾 + 示例** 四层校验器、`evaluate_column` 顶层执行 API、以及 `extract_compute_ir` 静态实现（从 `ReportDoc.computed_specs` 用 regex/AST 解析公式字符串，**不调 LLM**）。**LLM codegen（生成 pandas 函数源码）不在本模块** —— 由 lead agent 在 turn 内调用 DeerFlow 已绑定模型完成，生成的源码作为字符串传给本模块的校验/执行函数（或通过 CLI 子命令读盘）。**参考 `skills/public/data-analysis/scripts/analyze.py`（35.6KB，零 LLM imports）：DeerFlow skill 脚本应当是纯确定性 CLI，零 LLM 依赖。**

**文件：**
- 新建：`skills/public/chatbi-report/scripts/unit_conversion.py`
- 新建：`skills/public/chatbi-report/scripts/compute.py`
- 新建：`skills/public/chatbi-report/scripts/tests/test_unit_conversion.py`
- 新建：`skills/public/chatbi-report/scripts/tests/test_compute.py`
- 新建：`backend/tests/chatbi_report/fixtures/sample_md/computed_columns.md`
- 新建：`backend/tests/chatbi_report/fixtures/sample_md/computed_with_examples.md`

**`unit_conversion.py` 接口：**
- 消费：原始值（带千分位分隔符的字符串）、`data_unit: str | None`
- 产出：`convert_unit(raw_value: str, data_unit: str | None) -> Decimal` —— 换算后以 Decimal 类型展示；`SCALE_FACTOR` 映射常量

**`compute.py` 接口（零 LLM 依赖）：**
- 消费：`ReportDoc`（来自 `parse_md`）、LLM 生成的 pandas 源码字符串（由 lead agent 用 `write_file` 工具落盘到 thread output，本模块只读字符串/读盘）
- 产出（模块级函数 —— 供单测直接调用）：
  - `extract_compute_ir(report: Report) -> list[ComputeIR]` —— **静态解析** `> 计算:` 块为 `ComputeIR` 列表（无 LLM）。每个 `ComputeIR` 携带 `name`、`formula_repr`（原始公式字符串）、`base_idx_ids`（regex 提取的 `[A-Z]+_\d+`）、`periods`（出现在公式中的时期标识符）。LLM codegen 的输入由 lead agent 在 SKILL.md step 7 用本函数的输出 + `prompts/compute_codegen.md` 模板拼装。
  - `assemble_wide_table(per_idx_responses: list[dict], report: Report) -> list[dict]` —— SQLBot 长表透视为 chatbi 宽表行（按 `branch_num` × `period` 分组）。
  - `validate_ast(source: str) -> None | raise ComputeValidationError` —— 白名单校验（拒绝 `import os`、`eval`、`__import__` 等）。
  - `validate_signature(source: str, expected_name: str) -> None | raise` —— 名称 + 参数 + 返回注解校验（**强制 `: pd.DataFrame` 类型注解** —— 解决既有 review R3）。
  - `run_smoke(source: str, function_name: str, df: pd.DataFrame, smoke_rows: int = 3) -> pd.Series` —— 执行源码、运行函数、断言 `isinstance(out, pd.Series)`。**内部先调 `validate_signature` 再跑函数**，确保单测覆盖 = 生产覆盖（R3 修复）。
  - `run_example(source: str, function_name: str, df: pd.DataFrame, *, expected: str) -> bool` —— 装配 df、`math.isclose` 校验。
  - `evaluate_column(source: str, function_name: str, df: pd.DataFrame) -> pd.Series` —— lead agent 填充列的顶层 API。

**删除项（搬到 SKILL.md step 7 由 agent-turn 执行）：** `generate_pandas_function(...llm_complete)` 和接受 `llm_complete` 参数的 `extract_compute_ir(...)` 重载。

**CLI 入口（参考 `skills/public/data-analysis/scripts/analyze.py` 的 argparse 风格 —— 一份 .py 既是 module 又是 CLI，argparse 在 `if __name__ == "__main__":` 中分发）：**

```bash
# step 4：透视为宽表
python scripts/compute.py assemble-wide \
    --query /mnt/user-data/outputs/{thread}/report.query.json \
    --parsed /mnt/user-data/outputs/{thread}/report.parsed.json \
    --out /mnt/user-data/outputs/{thread}/report.wide.json

# step 6：静态 IR 抽取（零 LLM）
python scripts/compute.py extract-ir \
    --parsed /mnt/user-data/outputs/{thread}/report.parsed.json \
    --out /mnt/user-data/outputs/{thread}/report.ir.json

# step 8a：四层校验（AST + signature + smoke + example）
python scripts/compute.py validate \
    --source /mnt/user-data/outputs/{thread}/report.compute.<slug>.py \
    --function compute_<slug> \
    --df /mnt/user-data/outputs/{thread}/report.wide.json \
    --example-input '{"BAS_0263.current": 1420, "BAS_0263.yoy_same": 1200}' \
    --example-expected 0.1833
# → exit 0 时打印 "OK: validated"；exit 1 时 stderr 打印 "FAIL: <reason>"

# step 8b：执行函数返回 pd.Series
python scripts/compute.py evaluate \
    --source /mnt/user-data/outputs/{thread}/report.compute.<slug>.py \
    --function compute_<slug> \
    --df /mnt/user-data/outputs/{thread}/report.wide.json \
    --out /mnt/user-data/outputs/{thread}/report.computed.<slug>.json
# → 把 pd.Series 序列化为 {"index": [...], "values": [Decimal-as-str...]} JSON
```

这 4 个子命令是 **lead agent 通过 bash 调用脚本的唯一生产入口**。模块级函数仍保留供单测直接调用，但生产链路只走 CLI。

**为什么拆分为两个模块：**
- `unit_conversion.py` 零依赖纯函数 —— 测试覆盖换算精度边界（千分位、负数、小数四舍五入）。
- `compute.py` 含 AST 沙箱 + 签名 + 烟雾 + 示例校验 + Decimal 列计算 + argparse CLI —— 测试覆盖"恶意/错误源码被拒绝"+"合法源码跑出正确结果"两类用例，**全部用预制源码字符串，零 monkeypatch、零 LLM 调用**。

**为何 LLM codegen 不在脚本中：** 对照 `skills/public/data-analysis/scripts/analyze.py`（35.6KB，零 LLM imports）：DeerFlow skill 脚本是 bash 子进程，**沙箱中不可达 LLM**（无 OPENAI/ANTHROPIC 凭证、无网络出口、不能复用 lead agent 的模型工厂/重试/追踪）。把 LLM codegen 留在 agent-turn 等价于直接复用 DeerFlow 已有的 LangGraph 模型绑定 + thinking + Langfuse 追踪 + 限流策略，零额外接线。

- [ ] **步骤 1：创建两个 MD fixture**

按所示路径创建两个 fixture 文件。每个 fixture 的完整 MD 内容见配套文件 `2026-06-23-chatbi-report-appendix-fixtures-and-tests.md` 的 **A.9 `computed_columns.md`、A.10 `computed_with_examples.md`**，原样复制即可。概要如下：

| Fixture | 触发的测试 |
|---|---|
| `computed_columns.md` | 2 个计算 spec（收单商户同比 + 余额较年初）覆盖 2 个基础指标（BAS_0263, BAS_0264），`time_info=["2025","2024"]` —— 驱动 `test_extract_ir`、`test_codegen`、`test_evaluate_column`、`test_validate_signature_*` |
| `computed_with_examples.md` | 1 个计算 spec 配 1 个 `.示例: BAS_0263[current=1420, yoy_same=1200] -> 0.1833` 示例 —— 驱动 `test_run_example_passes` 和 `test_run_example_fails` |

- [ ] **步骤 2：先写 `unit_conversion.py` 的失败测试**

创建 `skills/public/chatbi-report/scripts/tests/test_unit_conversion.py`：

<!-- code-block: §5.1 (python, 70 lines) → see chatbi-report-code-blocks.md -->


- [ ] **步骤 3：运行测试，验证失败**

<!-- code-block: §5.2 (bash, 2 lines) → see chatbi-report-code-blocks.md -->

期望：`ModuleNotFoundError: No module named 'unit_conversion'`。

- [ ] **步骤 4：实现 `unit_conversion.py`**

创建 `skills/public/chatbi-report/scripts/unit_conversion.py`：

<!-- code-block: §5.3 (python, 39 lines) → see chatbi-report-code-blocks.md -->


- [ ] **步骤 5：运行测试，验证通过**

<!-- code-block: §5.4 (bash, 2 lines) → see chatbi-report-code-blocks.md -->

期望：10 passed。

- [ ] **步骤 6：先写 `compute.py` 的失败测试**

创建 `skills/public/chatbi-report/scripts/tests/test_compute.py`。

⚠️ **§5.5 当前 182 行版本基于旧接口（含 `llm_complete` monkeypatch），需按新接口重写**。重写后的测试用例应覆盖以下 6 类（约 12–15 个测试，**零 monkeypatch、零 LLM mock**，全部用预制源码字符串）：

| 测试类别 | 用例数 | 关键断言 |
|---|---|---|
| `extract_compute_ir` 静态解析 | 2 | 从 `computed_columns.md` 解析出 2 个 `ComputeIR`，`base_idx_ids` / `periods` 正确 |
| `validate_ast` | 3 | 拒绝 `import os` / `eval(...)` / `__import__`；接受 `import pandas as pd` + `df["col"].sum()` |
| `validate_signature` | 3 | 拒绝无 `pd.DataFrame` 类型注解、拒绝错误函数名、接受合法签名（**R3 修复关键测试**） |
| `run_smoke` | 2 | 内部调 `validate_signature` 拒绝无注解源码；合法源码返回 `pd.Series` |
| `run_example` | 2 | 1420/1200 期望 0.1833 通过；1420/1200 期望 0.5 失败 |
| `evaluate_column` | 2 | Decimal 列正确填充；非 Series 返回值抛 `ComputeValidationError` |

（§5.5 重写工作单独 commit，待执行任务 5 时由实施者按上表生成。）


- [ ] **步骤 7：运行测试，验证失败**

<!-- code-block: §5.6 (bash, 2 lines) → see chatbi-report-code-blocks.md -->

期望：全部测试报 `ModuleNotFoundError: No module named 'compute'`。

- [ ] **步骤 8：实现 `compute.py`**

创建 `skills/public/chatbi-report/scripts/compute.py`。

⚠️ **§5.7 当前 287 行版本含 `generate_pandas_function` / `llm_complete` 调用，需按新接口重写**（预计 ~240 行，删除约 65 行 LLM 路径，新增 `run_smoke` 内 `validate_signature` 调用，新增 argparse CLI 入口约 50 行）。重写要点：
- **删除：** `generate_pandas_function(...)`、`extract_compute_ir(report, llm_complete)` 的 LLM 重载、`llm_complete` 参数链
- **保留 + 修订：** `extract_compute_ir(report)` 改为纯 regex/AST 解析 `> 计算:` 块
- **新增：** `run_smoke` 头部调 `validate_signature(source, function_name)`（R3 修复）
- **新增 CLI：** `if __name__ == "__main__":` + argparse 4 个子命令 `extract-ir` / `assemble-wide` / `validate` / `evaluate`（按任务 5 标题段的 CLI 入口规范）
- **不变：** `validate_ast` / `run_example` / `evaluate_column` 主体逻辑、`assemble_wide_table`、`Decimal` 列累加

（§5.7 重写工作单独 commit，待执行任务 5 时由实施者按上述要点生成。）


- [ ] **步骤 9：创建 `prompts/compute_codegen.md`（LLM few-shot，由 lead agent 在 SKILL.md step 7 读取）**

创建 `skills/public/chatbi-report/prompts/compute_codegen.md`。

⚠️ **§5.8 当前 66 行 prompt 内容大体可复用**，但需修订两处：
- 顶部加一行注释 `<!-- 由 lead agent 在 SKILL.md step 7 加载，与 ComputeIR JSON 拼装后送入模型；不被任何 Python 脚本 import -->`
- 输出契约段强调"函数必须有 `: pd.DataFrame` 类型注解 + `-> pd.Series` 返回注解"（与 `validate_signature` 对齐）

（本文件无测试 —— 它是 prompt 模板而非代码。）

- [ ] **步骤 10：运行所有 compute 测试，验证通过**

<!-- code-block: §5.9 (bash, 3 lines) → see chatbi-report-code-blocks.md -->

期望：12–15 项通过（按步骤 6 新表格估算）。**R3 修复已落地** —— `run_smoke` 内部调 `validate_signature`，无注解源码会在烟雾阶段就被拒，不再有"单测过、生产报错"的时序冲突。

- [ ] **步骤 11：提交**

<!-- code-block: §5.10 (bash, 31 lines) → see chatbi-report-code-blocks.md -->


---

## 任务 6：`render_markdown.py` —— 回填 `report.md`

**文件：**
- 新建：`skills/public/chatbi-report/scripts/render_markdown.py`
- 新建：`skills/public/chatbi-report/scripts/tests/test_render_markdown.py`

**接口：**
- 消费：`ReportDoc` AST + 每张报表的 `wide_rows` + `compute_validation` 映射
- 产出：`render_markdown(doc: ReportDoc, wide_by_report: list[list[dict]], compute_status: dict) -> str` —— 完整回填后的 MD 内容

**Chatbi 专属行为：**

- 列头渲染为 **`中文显示名 (单位)`** —— 不带 `(\`BAS_0263\`)` 这样的 idx_id 后缀。MD 的 `<th>` 文本里已有中文显示名。
- 计算列表头渲染为 **`中文显示名 (computed) (单位)`** —— `(computed)` 是用来区分 LLM 生成的列与 SQLBot 拉取列的标记（文档审阅者一眼就能看出哪些数字是可复现的）。
- `⚠️QUERY_FAILED` 追加到表头标签本身（如 `贷款收单商户数 (个) ⚠️QUERY_FAILED`），让失败在渲染的列头里即可见，而非仅出现在单元格中。
- `⚠️COMPUTE_FAILED` 对计算列做同样处理。

- [ ] **步骤 1：先写失败测试**

创建 `skills/public/chatbi-report/scripts/tests/test_render_markdown.py`：

<!-- code-block: §6.1 (python, 77 lines) → see chatbi-report-code-blocks.md -->


- [ ] **步骤 2：运行测试，验证失败**

<!-- code-block: §6.2 (bash, 2 lines) → see chatbi-report-code-blocks.md -->

期望：`ModuleNotFoundError: No module named 'render_markdown'`。

- [ ] **步骤 3：实现 `render_markdown.py`**

创建 `skills/public/chatbi-report/scripts/render_markdown.py`：

<!-- code-block: §6.3 (python, 104 lines) → see chatbi-report-code-blocks.md -->


- [ ] **步骤 4：运行测试，验证通过**

<!-- code-block: §6.4 (bash, 2 lines) → see chatbi-report-code-blocks.md -->

期望：4 passed。

- [ ] **步骤 5：提交**

<!-- code-block: §6.5 (bash, 14 lines) → see chatbi-report-code-blocks.md -->


---

## 任务 7：`report_style.json` + `render_docx.py` —— 带多级合并的 python-docx

**文件：**
- 新建：`skills/public/chatbi-report/scripts/report_style.json`
- 新建：`skills/public/chatbi-report/scripts/render_docx.py`
- 新建：`skills/public/chatbi-report/scripts/tests/test_render_docx.py`

**接口（`render_docx.py`）：**
- 消费：`ReportDoc` AST + `wide_by_report` + `compute_status` + `report_style.json` 路径
- 产出：`render_docx(doc, wide_by_report, compute_status, *, out_path, style_path) -> None`（写入 `.docx`）

**Chatbi 专属行为：**

- 每列的 **主表头** 行是 `headers[].text`（来自 MD 的中文显示名），不是 SQLBot 的 `idx_id`。规格 §"表头副标渲染规则"："Heading 文本直接读 `headers[].text`（来自 MD 单元格，**不调 SQLBot**）"。
- **副标题** 仅是 `(data-unit)`（如 `(个)`）—— 不含 `idx_id` 也不含 `idx_name`。中文名是主标题。
- **旧式占位符回退**（当使用 `{{BAS_0263}}` 且 MD 不含中文名时）：若 `headers[].text == idx_id` 且该列带 `data-unit`，`render_docx` 会发起一次 SQLBot 查询以获取 `idx_name`。这是渲染过程中 **唯一** 调用 SQLBot 的路径，且仅对旧式 MD 触发。
- 多级 thead：跨 rowspan/colspan 用 `cell.merge()`。叶子承载中文显示名，类目父级仅在合并区域中渲染。
- 查询/计算失败：单元格文本中保留相同的 `⚠️QUERY_FAILED` / `⚠️COMPUTE_FAILED` 标记。

- [ ] **步骤 1：创建 `report_style.json`**

创建 `skills/public/chatbi-report/scripts/report_style.json`：

<!-- code-block: §7.1 (json, 25 lines) → see chatbi-report-code-blocks.md -->


- [ ] **步骤 2：先写失败测试**

创建 `skills/public/chatbi-report/scripts/tests/test_render_docx.py`：

<!-- code-block: §7.2 (python, 126 lines) → see chatbi-report-code-blocks.md -->


- [ ] **步骤 3：运行测试，验证失败**

<!-- code-block: §7.3 (bash, 2 lines) → see chatbi-report-code-blocks.md -->

期望：`ModuleNotFoundError: No module named 'render_docx'`。

- [ ] **步骤 4：实现 `render_docx.py`**

创建 `skills/public/chatbi-report/scripts/render_docx.py`：

<!-- code-block: §7.4 (python, 176 lines) → see chatbi-report-code-blocks.md -->


- [ ] **步骤 5：运行测试，验证通过**

<!-- code-block: §7.5 (bash, 2 lines) → see chatbi-report-code-blocks.md -->

期望：4 passed（或在 python-docx 对 happy fixture 的 round-trip 有字体名问题时为 3 + 1 skipped）。

若 `test_render_docx_header_uses_chinese_name_not_idx_id` 失败（中文名出现在表中但 `BAS_0263` 也出现，例如作为占位列 季度 的兄弟），需检查断言 —— chatbi 主路径应让 `BAS_0263` 完全不出现在可见表格中。如需放宽断言（例如允许 `BAS_0263` 仅出现在像 季度 的占位表头中），可缩小检查范围。

- [ ] **步骤 6：提交**

<!-- code-block: §7.6 (bash, 24 lines) → see chatbi-report-code-blocks.md -->


---

## 任务 8：`assemble_status.py` + 测试 —— 写出 `report.status.json`

**文件：**
- 新建：`skills/public/chatbi-report/scripts/assemble_status.py`
- 新建：`skills/public/chatbi-report/scripts/tests/test_assemble_status.py`

**接口：**
- 消费：`exit_step: int`、`error_class: str | None`、`error_detail: str`、`outputs: dict`、`metrics: dict`
- 产出：`write_status(out_path: str, **fields) -> None`（按规格 §"lead agent 退出 status" 写入 JSON）

本模块是薄薄的格式模块 —— lead agent 从 9 步执行中算出各字段。TDD 目标是锁定 JSON 形态，确保未来的重构不会静默丢失字段。

- [ ] **步骤 1：先写失败测试**

创建 `skills/public/chatbi-report/scripts/tests/test_assemble_status.py`：

<!-- code-block: §8.1 (python, 77 lines) → see chatbi-report-code-blocks.md -->


- [ ] **步骤 2：运行测试，验证失败**

<!-- code-block: §8.2 (bash, 2 lines) → see chatbi-report-code-blocks.md -->

期望：`ModuleNotFoundError: No module named 'assemble_status'`。

- [ ] **步骤 3：实现 `assemble_status.py`**

创建 `skills/public/chatbi-report/scripts/assemble_status.py`：

<!-- code-block: §8.3 (python, 53 lines) → see chatbi-report-code-blocks.md -->


- [ ] **步骤 4：运行测试，验证通过**

<!-- code-block: §8.4 (bash, 2 lines) → see chatbi-report-code-blocks.md -->

期望：4 passed。

- [ ] **步骤 5：提交**

<!-- code-block: §8.5 (bash, 14 lines) → see chatbi-report-code-blocks.md -->


---

## 任务 9：`SKILL.md` —— skill 入口（面向模型的触发）

**文件：**
- 新建：`skills/public/chatbi-report/SKILL.md`

**为什么这里不做 TDD：** SKILL.md 是散文而非代码。本任务转而校验 YAML frontmatter 能解析（DeerFlow 技能加载器依赖的基本检查）以及 9 步工作流引用了实现所创建的全部脚本。

**9 步工作流分层契约（与任务 5 的两层架构对齐）：**

| Step | 类型 | 命令 / 责任方 | 产物 |
|---|---|---|---|
| 1. lint | bash | `python scripts/md_lint.py <upload.md>` | exit code + LintReport |
| 2. parse | bash | `python scripts/parse_md.py <upload.md> --out report.parsed.json` | `report.parsed.json` |
| 3. query | bash | `python scripts/sqlbot_client.py query --idx-ids ... --out report.query.json` | `report.query.json` |
| 4. assemble wide | bash | `python scripts/compute.py assemble-wide --query report.query.json --parsed report.parsed.json --out report.wide.json` | `report.wide.json` |
| 5. unit convert | bash | `python scripts/unit_conversion.py --in report.wide.json --out report.wide.json` | wide 内 cells 转 Decimal 字符串 |
| 6. extract IR | bash | `python scripts/compute.py extract-ir --parsed report.parsed.json --out report.ir.json` | `report.ir.json`（**静态，零 LLM**） |
| **7. codegen** | **agent-turn** | **lead agent 调 LLM**（读 `prompts/compute_codegen.md` + `report.ir.json`，逐 spec 生成函数源码，**用 `write_file` 工具落盘**） | `report.compute.<slug>.py` × N |
| **8a. validate** | bash | `python scripts/compute.py validate --source ... --function ... --df ... --example-input ... --example-expected ...` | exit 0/1（agent-turn 见 fail 重试 step 7，最多 1 次） |
| **8b. evaluate** | bash | `python scripts/compute.py evaluate --source ... --function ... --df ... --out report.computed.<slug>.json` | `report.computed.<slug>.json` × N |
| 9. render + status | bash | `python scripts/render_markdown.py ...` + `python scripts/render_docx.py ...` + `python scripts/assemble_status.py ...` | `report.{md,docx,status.json}` |

**关键不变量：** step 7 是 **唯一** 的 agent-turn LLM step；step 1–6 与 8a/8b/9 全部是 bash CLI 子进程，沙箱中不可达 LLM。step 7 失败重试也在 agent-turn 内做（agent 读 step 8a 的 stderr，决定要不要再调一次 LLM 生成新版源码），bash 脚本不参与重试调度。

⚠️ **§9.1 当前 SKILL.md 89 行版本需按上表修订 step 7/8 措辞** —— 明确"step 7 是 agent 直接调 LLM 写文件，bash 不参与"，并把所有 bash 行替换为任务 5 标题段定义的 4 个子命令调用。

- [ ] **步骤 1：编写 `SKILL.md`**

创建 `skills/public/chatbi-report/SKILL.md`：

<!-- code-block: §9.1 (markdown, 89 lines) → see chatbi-report-code-blocks.md -->


- [ ] **步骤 2：校验 YAML frontmatter 能解析**

在项目根目录运行：
<!-- code-block: §9.2 (bash, 14 lines) → see chatbi-report-code-blocks.md -->

期望：输出 `chatbi-identifier present: True` 与 `OK`。若 yaml 未安装：
<!-- code-block: §9.3 (bash, 1 lines) → see chatbi-report-code-blocks.md -->


- [ ] **步骤 3：烟雾检查 9 步工作流引用了全部脚本**

运行：
<!-- code-block: §9.4 (bash, 4 lines) → see chatbi-report-code-blocks.md -->

期望：没有 `MISSING` 行（每个脚本至少被提及一次）。

- [ ] **步骤 4：提交**

<!-- code-block: §9.5 (bash, 14 lines) → see chatbi-report-code-blocks.md -->


---

## 任务 10：`README.md` + `.env.example` —— 面向运维的文档

**文件：**
- 新建：`skills/public/chatbi-report/README.md`
- 新建：`skills/public/chatbi-report/.env.example`

- [ ] **步骤 1：创建 `README.md`**

创建 `skills/public/chatbi-report/README.md`：

<!-- code-block: §10.1 (markdown, 72 lines) → see chatbi-report-code-blocks.md -->


- [ ] **步骤 2：创建 `.env.example`**

创建 `skills/public/chatbi-report/.env.example`：

<!-- code-block: §10.2 (bash, 8 lines) → see chatbi-report-code-blocks.md -->


- [ ] **步骤 3：提交**

<!-- code-block: §10.3 (bash, 13 lines) → see chatbi-report-code-blocks.md -->
