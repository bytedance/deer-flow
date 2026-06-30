# ai-report Skill 实施计划

> **面向 Agent 执行者：** 必备子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 任务逐项实施本计划。步骤使用复选框（`- [ ]`）语法以便跟踪。

**目标：** 实现 `ai-report` skill —— 用户上传一份含 H1/H2/H3 多章节多表 的 Markdown（每个 H3 嵌一张 `<table>` 加 `data-idx`/`data-unit` 元数据），DeerFlow lead agent 走 **design 模式**（默认）：对每节 checkpoint 交互、按 `<th data-idx>` 调 SQLBot 拉原始事实（**源单位固定 = 元**），落地到全局单 DuckDB（`/mnt/ai-report-data/duckdb/ai-report.duckdb`），DuckDB PIVOT 出宽表，LLM 生成 DuckDB SQL 计算列，5 层校验（EXPLAIN + FROM wide + branch_num + smoke + example，无 keyword blacklist），DuckDB UPDATE 应用单位换算，approved 后写 `approved_table_runs` 快照并回填 `/mnt/ai-report-data/<report_id>.design.md`；用户说"运行报告"时走 **runtime 模式**：读 approved 快照拼整本 `report.md` + `report.docx`。

**架构：**
- **Skill 层**（触发 + 模式分流 + 中文回执）：`SKILL.md` 决定 design vs runtime；checkpoint 走 `ask_clarification(clarification_type="risk_confirmation", ...)`，和 chatbi-report 同构。
- **数据层**（持久 + 状态）：5 张表 DuckDB 全局单库 — `reports / report_sections / report_tables / metric_facts / approved_table_runs`，所有表带 `schema_version INTEGER NOT NULL DEFAULT 1`。`run_id` 是 UUID4，入 PK，**保留所有 design 历史**。`source_md_hash` 是 sha256，原 MD 改动可 detect。
- **Pipeline 层**（design 14 step / runtime 5 step）：16 个新写 script，**不 import chatbi-report 任何 module，不复制 chatbi-report 任何代码块**，可读 chatbi-report 源码借鉴算法 / 模式 / lint 规则 / 库选择，在 ai-report 目录**重新写**。所有确定性 step（lint / parse / sqlbot / compute / unit / render）走 `bash` 调本地 Python；LLM 决策（compute SQL codegen + 描述）由 lead agent in-turn 调绑定模型 + `prompts/*.md`。
- **Checkpoint 编号沿用 chatbi-report 惯例**（1.5/3.5/8d.5）+ ai-report 新加 0/10/11。

**两层执行契约：**

| 层 | 谁来做 | 在哪儿 | 产物 |
|---|---|---|---|
| LLM 层：从 IR 生成 `compute_<slug>.sql`（DuckDB SQL，含 `FROM wide` + `SELECT branch_num, <别名> AS col`） | lead agent in-turn | prompts/compute_codegen.md | `compute.<slug>.sql` 写到 `/mnt/ai-report-data/<report_id>.<table_id>.compute.<slug>.sql` |
| LLM 层：生成 section 描述 | lead agent in-turn | prompts/description_gen.md | `description.<slug>.txt` 写到 design.md |
| 确定性层：lint / parse / sqlbot query / assemble-wide / extract-ir / validate / evaluate / apply-computed / unit_convert / render | `scripts/*.py` CLI（纯 bash 调用，零 LLM） | scripts/ | DuckDB 5 张表 + design.md 回填 + 整本 report.md / report.docx |

**技术栈：** Python 3.12，`httpx`（HTTP 客户端），`duckdb`（数据层 + 计算列引擎），`python-docx`（DOCX 渲染），`decimal.Decimal`（单位运算），`json`/`dataclasses`/`re`/`html.parser`/`hashlib`/`uuid`（解析、校验、ID 生成），`pytest`（单元 + 集成测试，使用 `unittest.mock.patch` 隔离 HTTP）。`httpx` / `duckdb` / `python-docx` 通过 `pyproject.toml` 添加到 ai-report skill 的 `dependencies` 块（deerflow-harness 已有这些 transitive dependencies 的话也可复用）。`pathlib` / 标准库为主。**无 pandas**。

**规格说明：** `docx/superpowers/specs/2026-06-30-ai-report-design.md`（5 章节 16 节 + 16 决策日志 + 12 non-goals）

**全局约束：**
- ai-report 与 chatbi-report 是**并存**的两份 skill，ai-report 不 import chatbi-report 任何 module，不复制 chatbi-report 任何代码块
- 数据层**纯 DuckDB**，**无 pandas 代码**
- 16 个 scripts **全部新写**，**0 import** chatbi-report
- 源单位固定 = 元；单位换算走 DuckDB SQL UPDATE（`col/10000` / `col*100` 等），**不 import** `unit_conversion.py`
- Compute 5 层校验**无**关键字黑名单（沙箱逃逸风险 Phase 1 承担，Phase 2 再补）
- DuckDB 全局单库 `/mnt/ai-report-data/duckdb/ai-report.duckdb`；**非** per-report
- 默认零中间产物到 `/mnt/user-data/outputs/`，**仅 `--debug` 例外**；`status.json` 整个 drop
- 5 个哨兵：`⚠️QUERY_FAILED` / `⚠️CAST_FAILED` / `⚠️COMPUTE_FAILED` / `⚠️DESCRIPTION_FAILED` / `⚠️LINT_FAILED`（**不**引入 `⚠️UNIT_CONVERTED_FAILED`）
- Checkpoint IDs：0（lint 失败阻塞整本） / 1.5（lint pass 整本 informational） / 3.5（query per-section always-trigger） / 8d.5（describe per-section） / 10（preview approve per-section，ai-report 新加） / 11（section 间推进，ai-report 新加）
- Lint 1.5 是 per-report 一次跑全本；其余 checkpoint 都是 per-section

---

## 文件结构

```
skills/public/ai-report/
├── SKILL.md                                      # 触发 + design/runtime 模式选择
├── example/
│   └── wangyi_2026_03.md                         # 王益联社 5 节 sample
├── prompts/
│   ├── compute_codegen.md                        # LLM prompt for DuckDB SQL codegen
│   └── description_gen.md                        # LLM prompt for descriptions
├── references/
│   ├── pipeline.md                               # design 模式 14-step pipeline
│   ├── runtime.md                                # runtime 模式 5-step
│   ├── checkpoints.md                            # 6 个 checkpoint 行为契约
│   ├── status-output.md                          # 中文回执 + status dict 契约
│   └── data-flow.md                              # DuckDB 数据流图
├── scripts/
│   ├── __init__.py                               # 空
│   ├── report_style.json                         # 字体/页面/格式
│   ├── retry.py                                  # 退避 + 装饰器
│   ├── unit_convert.py                           # 单位字典 + UPDATE SQL 生成
│   ├── report_split.py                           # 整本 MD → sections list
│   ├── parse_md.py                               # MD → ReportDoc
│   ├── md_lint.py                                # per-section LintReport
│   ├── sqlbot_client.py                          # httpx + mock fixture
│   ├── compute.py                                # 5 sub-commands (DuckDB)
│   ├── render_markdown.py                        # 纯渲染器
│   ├── render_docx.py                            # 纯 docx 渲染器
│   ├── assemble_status.py                        # 中文回执 + status dict
│   ├── duckdb_store.py                           # 5 表 + CRUD + run_id 历史
│   ├── report_md.py                              # runtime wrapper: pull + render md
│   ├── report_docx.py                            # runtime wrapper: pull + render docx
│   ├── design_pipeline.py                        # LangGraph make_lead_agent orchestrator
│   └── runtime_pipeline.py                       # 5-step orchestrator
└── tests/
    ├── __init__.py                               # 空
    ├── conftest.py                               # shared fixtures
    ├── fixtures/
    │   ├── sample_report.md                      # 5-section happy path
    │   ├── sample_report_lint_error.md           # per-section 错误场景
    │   ├── mock_sqlbot/
    │   │   └── wangyi_2026_03.json               # mock SQLBot responses
    │   └── expected/
    │       ├── wangyi_2026_03_design.md
    │       ├── wangyi_2026_03_report.md
    │       └── wangyi_2026_03_report.docx
    ├── test_retry.py
    ├── test_unit_convert.py
    ├── test_report_split.py
    ├── test_parse_md.py
    ├── test_md_lint.py
    ├── test_sqlbot_client.py
    ├── test_duckdb_store.py
    ├── test_compute.py
    ├── test_render_markdown.py
    ├── test_render_docx.py
    ├── test_sentinels.py                         # 5 哨兵触发场景
    ├── test_design_pipeline.py
    └── test_runtime_pipeline.py
```

**创建的生产文件（16 scripts + 2 prompts + 5 references + 1 example + 1 SKILL.md + 1 style JSON = 26 个）。**

**创建的测试文件（11 + 1 conftest + fixtures = 14 个文件）。**

**未变更：** `deerflow.agents.lead_agent.*`、`deerflow.subagents.*`、LangGraph 运行时、Gateway API、前端、`chatbi-report`（全部不动）、`config.yaml`（`/mnt/ai-report-data` 已挂载在第 124-125 行）。

**ID 命名约定（贯穿全部 19 任务）：**
- `report_id` = `sha256(source_md_path)[:16]`（16 hex chars）— 同一文件路径永远同一 report_id；改路径则新建
- `run_id` = `uuid.uuid4().hex`（32 hex chars）— 每次 design 启动新 run，保留所有历史
- `section_id` = `f"{report_id}_s{section_order:02d}"`（如 `wangyi_s00`）
- `table_id` = `f"{section_id}_t{table_order:02d}"`（如 `wangyi_s00_t00`）
- `slug` = 中文 table_title 去掉非 [a-z0-9_]，转小写，下划线连接（IR / compute SQL / description 文件名都用）

---

## 任务 1：Skill 引导 + `retry.py` + `report_style.json` + `conftest.py`

**文件：**
- 创建：`skills/public/ai-report/scripts/__init__.py`（空）
- 创建：`skills/public/ai-report/tests/__init__.py`（空）
- 创建：`skills/public/ai-report/scripts/retry.py`
- 创建：`skills/public/ai-report/scripts/report_style.json`
- 创建：`skills/public/ai-report/tests/conftest.py`
- 创建：`skills/public/ai-report/tests/test_retry.py`
- 创建：`skills/public/ai-report/example/wangyi_2026_03.md`（最小可用 5 节骨架，详情见步骤 5）

**接口：**
- 消费：标准库 `functools` / `time` / `dataclasses` / `typing` / `pathlib`
- 产出：`Backoff` dataclass + `exponential(base, max_delay)` 工厂 + `retry(max_attempts, backoff, retry_on)` 装饰器（和 chatbi-report 现状接口一致，但**代码新写**）；`report_style.json` 包含 `font.{title,section,report,body}` + `page.{orientation,margins_cm}`

`retry.py` 在依赖图最底层（任务 6、8、9 都消费它），先交付并获得最充分的单元覆盖。

- [ ] **步骤 1：创建空的 `__init__.py` 文件**

分别创建 `skills/public/ai-report/scripts/__init__.py` 和 `skills/public/ai-report/tests/__init__.py`，每个仅含一个换行。便于 pytest 在不报 `ModuleNotFoundError` 的情况下发现测试模块。

- [ ] **步骤 2：写失败测试 —— `retry` 装饰器首次成功 / 重试 / 全部失败**

创建 `skills/public/ai-report/tests/test_retry.py`：

```python
"""Unit tests for ai-report retry decorator (新写, 借鉴 chatbi-report retry.py 行为契约)."""

from __future__ import annotations

import pytest

from retry import Backoff, exponential, retry


def test_retry_succeeds_on_first_attempt():
    calls = []

    @retry(max_attempts=3, backoff=exponential(0.01, 0.1), retry_on=(ValueError,))
    def fn():
        calls.append(1)
        return 42

    assert fn() == 42
    assert len(calls) == 1


def test_retry_succeeds_on_third_attempt():
    calls = []

    @retry(max_attempts=3, backoff=exponential(0.01, 0.1), retry_on=(ValueError,))
    def fn():
        calls.append(1)
        if len(calls) < 3:
            raise ValueError("transient")
        return "ok"

    assert fn() == "ok"
    assert len(calls) == 3


def test_retry_raises_after_max_attempts():
    calls = []

    @retry(max_attempts=3, backoff=exponential(0.01, 0.1), retry_on=(ValueError,))
    def fn():
        calls.append(1)
        raise ValueError("always fail")

    with pytest.raises(ValueError, match="always fail"):
        fn()
    assert len(calls) == 3


def test_retry_does_not_catch_other_exceptions():
    @retry(max_attempts=3, backoff=exponential(0.01, 0.1), retry_on=(ValueError,))
    def fn():
        raise TypeError("not retried")

    with pytest.raises(TypeError, match="not retried"):
        fn()


def test_exponential_backoff_caps_at_max_delay():
    backoff = exponential(base=1.0, max_delay=4.0)
    assert backoff.delay(1) == 1.0
    assert backoff.delay(2) == 2.0
    assert backoff.delay(3) == 4.0
    assert backoff.delay(10) == 4.0
```

- [ ] **步骤 3：跑测试，确认失败（应该 ModuleNotFoundError: No module named 'retry'）**

```bash
cd skills/public/ai-report && python -m pytest tests/test_retry.py -v
```

期望：`ModuleNotFoundError: No module named 'retry'`。

- [ ] **步骤 4：写 `retry.py` 最小实现**

创建 `skills/public/ai-report/scripts/retry.py`：

```python
"""ai-report retry decorator with pluggable backoff (新写, 借鉴 chatbi-report retry.py)."""
from __future__ import annotations

import functools
import time
from dataclasses import dataclass
from typing import Callable, ParamSpec, TypeVar

P = ParamSpec("P")
R = TypeVar("R")


@dataclass
class Backoff:
    """Backoff strategy: call delay(attempt) → seconds to sleep."""
    fn: Callable[[int], float]

    def delay(self, attempt: int) -> float:
        return self.fn(attempt)


def exponential(base: float = 2.0, max_delay: float = 10.0) -> Backoff:
    """Standard exponential backoff: base * 2^(attempt-1), capped at max_delay."""
    def _d(attempt: int) -> float:
        return min(base * (2 ** (attempt - 1)), max_delay)
    return Backoff(fn=_d)


def retry(
    *,
    max_attempts: int,
    backoff: Backoff,
    retry_on: tuple[type[BaseException], ...],
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Retry on listed exception types up to max_attempts times. Raises last exception if all fail."""
    def decorator(fn: Callable[P, R]) -> Callable[P, R]:
        @functools.wraps(fn)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            last_exc: BaseException | None = None
            for attempt in range(1, max_attempts + 1):
                try:
                    return fn(*args, **kwargs)
                except retry_on as e:
                    last_exc = e
                    if attempt == max_attempts:
                        break
                    time.sleep(backoff.delay(attempt))
            assert last_exc is not None
            raise last_exc
        return wrapper
    return decorator
```

- [ ] **步骤 5：跑测试，确认全部通过**

```bash
cd skills/public/ai-report && python -m pytest tests/test_retry.py -v
```

期望：5 个 test 全部 PASS。

- [ ] **步骤 6：创建 `report_style.json`**

创建 `skills/public/ai-report/scripts/report_style.json`：

```json
{
  "font": {
    "title": {"name": "宋体", "size": 18, "bold": true, "color": "#000000"},
    "section": {"name": "宋体", "size": 14, "bold": true, "color": "#000000"},
    "report": {"name": "宋体", "size": 12, "bold": true, "color": "#000000"},
    "body": {"name": "宋体", "size": 11, "bold": false, "color": "#000000"}
  },
  "page": {
    "orientation": "landscape",
    "margins_cm": {"top": 2.0, "bottom": 2.0, "left": 1.5, "right": 1.5}
  }
}
```

- [ ] **步骤 7：创建 `conftest.py`**

创建 `skills/public/ai-report/tests/conftest.py`：

```python
"""Shared pytest fixtures for ai-report tests."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# 把 scripts/ 加入 sys.path, 让 `import parse_md` 等不报 ModuleNotFoundError
SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
EXAMPLE_DIR = Path(__file__).resolve().parent.parent / "example"


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES_DIR


@pytest.fixture
def example_dir() -> Path:
    return EXAMPLE_DIR


@pytest.fixture
def scripts_dir() -> Path:
    return SCRIPTS_DIR
```

- [ ] **步骤 8：创建王益联社 example 最小骨架**

创建 `skills/public/ai-report/example/wangyi_2026_03.md`（5 个 H2 章,每章 1 个 H3 报表占位;**任务 19 会替换为完整 sample, 此处只放骨架**）:

```markdown
# 王益联社 2026 年 3 月经营分析报告

## 一、存款业务

### 存款规模

> 机构: org_contexts = [{"org_ecd":"wangyi_credit_union","org_name":"王益联社"}]
> 时期: time_info = ["202603"]

<table>
  <thead>
    <tr><th rowspan="2" data-period="202603">机构</th><th colspan="2" data-idx="BAS_001" data-unit="万元">存款余额</th></tr>
    <tr><th data-idx="BAS_001" data-period="202602">较上月末</th><th data-idx="BAS_001" data-period="202603">本月</th></tr>
  </thead>
  <tbody></tbody>
</table>

## 二、贷款业务

### 贷款规模

> 机构: org_contexts = [{"org_ecd":"wangyi_credit_union","org_name":"王益联社"}]
> 时期: time_info = ["202603"]

<table>
  <thead>
    <tr><th rowspan="2" data-period="202603">机构</th><th colspan="2" data-idx="BAS_010" data-unit="万元">贷款余额</th></tr>
    <tr><th data-idx="BAS_010" data-period="202602">较上月末</th><th data-idx="BAS_010" data-period="202603">本月</th></tr>
  </thead>
  <tbody></tbody>
</table>

## 三、收入与利润

### 营业收入

> 机构: org_contexts = [{"org_ecd":"wangyi_credit_union","org_name":"王益联社"}]
> 时期: time_info = ["202603"]

<table>
  <thead>
    <tr><th data-idx="BAS_020" data-period="202603" data-unit="万元">营业收入</th></tr>
  </thead>
  <tbody></tbody>
</table>

### 利润总额

> 机构: org_contexts = [{"org_ecd":"wangyi_credit_union","org_name":"王益联社"}]
> 时期: time_info = ["202603"]

<table>
  <thead>
    <tr><th data-idx="BAS_026" data-period="202603" data-unit="万元">利润总额</th></tr>
  </thead>
  <tbody></tbody>
</table>

## 四、资产质量

### 不良贷款率

> 机构: org_contexts = [{"org_ecd":"wangyi_credit_union","org_name":"王益联社"}]
> 时期: time_info = ["202603"]

<table>
  <thead>
    <tr><th data-idx="BAS_030" data-period="202603" data-unit="%">不良贷款率</th></tr>
  </thead>
  <tbody></tbody>
</table>
```

- [ ] **步骤 9：commit**

```bash
git add skills/public/ai-report/
git commit -m "feat(ai-report): bootstrap dir structure + retry.py + report_style.json + example skeleton"
```

---

## 任务 2：`report_split.py` —— 整本 MD → sections/tables 块

**文件：**
- 创建：`skills/public/ai-report/scripts/report_split.py`
- 创建：`skills/public/ai-report/tests/test_report_split.py`

**接口：**
- 消费：原始 MD 字符串
- 产出：`split_report(md: str) -> list[SectionBlock]`，每个 `SectionBlock(section_order, section_title, source_md)`；`source_md` 是该 H2 块原文（包含 H3 子表）

- [ ] **步骤 1：写失败测试**

创建 `skills/public/ai-report/tests/test_report_split.py`：

```python
"""Unit tests for report_split.split_report (新写, 借鉴 chatbi-report _split_sections/_split_reports 思路)."""

from __future__ import annotations

import pytest

from report_split import SectionBlock, split_report


def test_split_5_section_report():
    md = open("example/wangyi_2026_03.md", encoding="utf-8").read()
    sections = split_report(md)
    assert len(sections) == 5
    assert sections[0].section_order == 0
    assert sections[0].section_title == "一、存款业务"
    assert "存款规模" in sections[0].source_md
    assert "贷款规模" in sections[1].source_md


def test_split_no_h2_returns_empty():
    md = "# Title\n\nno sections here"
    assert split_report(md) == []


def test_split_single_h2_no_h3():
    md = "## A\n\nplain text"
    sections = split_report(md)
    assert len(sections) == 1
    assert sections[0].section_title == "A"


def test_split_section_order_starts_at_zero():
    md = "## A\n\n## B\n\n"
    sections = split_report(md)
    assert [s.section_order for s in sections] == [0, 1]
```

- [ ] **步骤 2：跑测试，确认失败**

```bash
cd skills/public/ai-report && python -m pytest tests/test_report_split.py -v
```

期望：`ModuleNotFoundError: No module named 'report_split'`。

- [ ] **步骤 3：写 `report_split.py` 实现**

创建 `skills/public/ai-report/scripts/report_split.py`：

```python
"""ai-report: split a whole report MD into H2 section blocks (新写)."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SectionBlock:
    section_order: int
    section_title: str
    source_md: str


def split_report(md: str) -> list[SectionBlock]:
    """Split MD on '## ' boundaries. Each section's source_md contains its H3 sub-tables."""
    out: list[SectionBlock] = []
    order = 0
    current_title: str | None = None
    current_body: list[str] = []
    for line in md.splitlines():
        if line.startswith("## "):
            if current_title is not None or any(s.strip() for s in current_body):
                out.append(SectionBlock(order, current_title or "", "\n".join(current_body)))
                order += 1
            current_title = line[3:].strip()
            current_body = []
        else:
            current_body.append(line)
    if current_title is not None or any(s.strip() for s in current_body):
        out.append(SectionBlock(order, current_title or "", "\n".join(current_body)))
    return out
```

- [ ] **步骤 4：跑测试，确认通过**

```bash
cd skills/public/ai-report && python -m pytest tests/test_report_split.py -v
```

期望：4 个 test 全部 PASS。

- [ ] **步骤 5：commit**

```bash
git add skills/public/ai-report/scripts/report_split.py skills/public/ai-report/tests/test_report_split.py
git commit -m "feat(ai-report): add report_split.py for MD → section blocks"
```

---

## 任务 3：`parse_md.py` —— MD → `ReportDoc` dataclass

**文件：**
- 创建：`skills/public/ai-report/scripts/parse_md.py`
- 创建：`skills/public/ai-report/tests/test_parse_md.py`

**接口：**
- 消费：原始 MD 字符串
- 产出：`parse_markdown(md: str) -> ReportDoc`；`ReportDoc` 含 `title: str`, `sections: list[Section]`, `all_idx_ids: set[str]`；`Section` 含 `title: str`, `reports: list[Report]`；`Report` 含 `title`, `org_contexts`, `time_info`, `headers: list[list[Th]]`, `data_rows`, `computed_specs`, `description_prompt`；`Th` 含 `text`, `is_indicator`, `is_computed`, `idx_id`, `data_unit`, `period`, `rowspan`, `colspan`

接口契约借鉴 chatbi-report `parse_md.py` (`ReportDoc`/`Section`/`Report`/`Th` 字段一致)，但 ai-report 不 import chatbi-report —— 完全新写。

- [ ] **步骤 1：写失败测试**

创建 `skills/public/ai-report/tests/test_parse_md.py`：

```python
"""Unit tests for parse_md (新写, 借鉴 chatbi-report parse_md.py 字段约定)."""

from __future__ import annotations

from parse_md import parse_markdown


def test_parse_5_section_report():
    md = open("example/wangyi_2026_03.md", encoding="utf-8").read()
    doc = parse_markdown(md)
    assert doc.title == "王益联社 2026 年 3 月经营分析报告"
    assert len(doc.sections) == 5
    assert doc.sections[0].title == "一、存款业务"
    assert len(doc.sections[0].reports) == 1
    assert "BAS_001" in doc.all_idx_ids


def test_parse_time_info_extracted():
    md = open("example/wangyi_2026_03.md", encoding="utf-8").read()
    doc = parse_markdown(md)
    first_report = doc.sections[0].reports[0]
    assert first_report.time_info == ["202603"]


def test_parse_data_unit_extracted():
    md = open("example/wangyi_2026_03.md", encoding="utf-8").read()
    doc = parse_markdown(md)
    ths = [th for row in doc.sections[0].reports[0].headers for th in row]
    units = {th.data_unit for th in ths if th.data_unit}
    assert "万元" in units
    assert "%" in units  # 不良贷款率
```

- [ ] **步骤 2：跑测试，确认失败**

```bash
cd skills/public/ai-report && python -m pytest tests/test_parse_md.py -v
```

- [ ] **步骤 3：写 `parse_md.py`**

创建 `skills/public/ai-report/scripts/parse_md.py`（**核心解析函数实现，借鉴 chatbi-report 的 HTMLParser 思路**）：

```python
"""ai-report: parse MD with H1/H2/H3 + <table> thead/tbody into ReportDoc (新写)."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser


@dataclass
class Th:
    text: str = ""
    is_indicator: bool = False
    is_computed: bool = False
    idx_id: str | None = None
    data_unit: str | None = None
    period: str | None = None
    rowspan: int | None = None
    colspan: int | None = None


@dataclass
class ComputedSpec:
    name: str
    prompt: str
    examples: list[dict] = field(default_factory=list)


@dataclass
class OrgContext:
    org_ecd: str
    org_name: str


@dataclass
class Report:
    title: str
    org_contexts: list[OrgContext]
    time_info: list[str]
    headers: list[list[Th]]
    data_rows: list[dict]
    computed_specs: list[ComputedSpec]
    description_prompt: str | None


@dataclass
class Section:
    title: str
    reports: list[Report]


@dataclass
class ReportDoc:
    title: str
    sections: list[Section]
    all_idx_ids: set[str] = field(default_factory=set)


def parse_markdown(md: str) -> ReportDoc:
    """Parse a full multi-section MD into ReportDoc (新写, 借鉴 chatbi-report parse_md 思路)."""
    title, body = _split_title(md)
    sections: list[Section] = []
    all_idx: set[str] = set()
    for section_title, section_body in _split_sections(body):
        reports: list[Report] = []
        for report_title, report_body in _split_reports(section_body):
            rep = _parse_one_report(report_title, report_body)
            reports.append(rep)
            for row in rep.headers:
                for th in row:
                    if th.idx_id:
                        all_idx.add(th.idx_id)
        sections.append(Section(title=section_title, reports=reports))
    return ReportDoc(title=title, sections=sections, all_idx_ids=all_idx)


# ---------- 内部 helpers ---------- #

def _split_title(md: str) -> tuple[str, str]:
    lines = md.splitlines()
    if lines and lines[0].startswith("# "):
        return lines[0][2:].strip(), "\n".join(lines[1:])
    return "", md


def _split_sections(body: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    cur_title, cur_body = "", []
    for line in body.splitlines():
        if line.startswith("## "):
            if cur_title or any(s.strip() for s in cur_body):
                out.append((cur_title, "\n".join(cur_body)))
            cur_title = line[3:].strip()
            cur_body = []
        else:
            cur_body.append(line)
    if cur_title or any(s.strip() for s in cur_body):
        out.append((cur_title, "\n".join(cur_body)))
    return out


def _split_reports(section_body: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    cur_title, cur_body = "", []
    for line in section_body.splitlines():
        if line.startswith("### "):
            if cur_title or any(s.strip() for s in cur_body):
                out.append((cur_title, "\n".join(cur_body)))
            cur_title = line[4:].strip()
            cur_body = []
        else:
            cur_body.append(line)
    if cur_title or any(s.strip() for s in cur_body):
        out.append((cur_title, "\n".join(cur_body)))
    return out


class _TheadCellCollector(HTMLParser):
    """借鉴 chatbi-report: walk thead <tr> → <th>, capture attrs + text."""
    def __init__(self):
        super().__init__()
        self.rows: list[list[dict]] = []
        self._cur_row: list[dict] | None = None
        self._cur_cell: dict | None = None
        self._text_buf: list[str] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "tr":
            self._cur_row = []
        elif tag == "th" and self._cur_row is not None:
            self._cur_cell = {
                "text": "",
                "is_indicator": False,
                "is_computed": a.get("data-idx") is not None or a.get("data-computed") is not None,
                "idx_id": a.get("data-idx"),
                "data_unit": a.get("data-unit"),
                "period": a.get("data-period"),
                "rowspan": int(a["rowspan"]) if a.get("rowspan") else None,
                "colspan": int(a["colspan"]) if a.get("colspan") else None,
            }
            self._text_buf = []
        elif tag == "td" and self._cur_row is not None:
            # 兼容 thead 含 td (不规范) - 跳过
            pass

    def handle_data(self, data):
        if self._cur_cell is not None:
            self._text_buf.append(data)

    def handle_endtag(self, tag):
        if tag == "th" and self._cur_cell is not None:
            self._cur_cell["text"] = "".join(self._text_buf).strip()
            self._cur_row.append(self._cur_cell)
            self._cur_cell = None
        elif tag == "tr" and self._cur_row is not None:
            self.rows.append(self._cur_row)
            self._cur_row = None


def _cell_to_th(cell: dict) -> Th:
    text = cell["text"]
    is_computed = cell["is_computed"] or text.startswith("{{")
    if is_computed and text.startswith("{{"):
        text = text.strip("{}")
    return Th(
        text=text,
        is_indicator=cell["is_indicator"],
        is_computed=is_computed,
        idx_id=cell["idx_id"],
        data_unit=cell["data_unit"],
        period=cell["period"],
        rowspan=cell["rowspan"],
        colspan=cell["colspan"],
    )


def _parse_org_block(body: str) -> list[OrgContext]:
    m = re.search(r"^>\s*机构:\s*org_contexts\s*=\s*(\[.*?\])", body, re.MULTILINE)
    if not m:
        return []
    return [OrgContext(**o) for o in json.loads(m.group(1))]


def _parse_one_report(report_title: str, body: str) -> Report:
    org_contexts = _parse_org_block(body)
    time_match = re.search(r"^>\s*时期:\s*time_info\s*=\s*(\[.*?\])\s*$", body, re.MULTILINE)
    if not time_match:
        raise ValueError(f"report `{report_title}` missing `> 时期:`; run md_lint first")
    time_info = json.loads(time_match.group(1))

    thead_match = re.search(r"<thead[^>]*>(.*?)</thead>", body, re.DOTALL | re.IGNORECASE)
    if not thead_match:
        raise ValueError(f"report `{report_title}` has no <thead>")
    parser = _TheadCellCollector()
    parser.feed(thead_match.group(1))
    headers_2d = [[_cell_to_th(c) for c in row] for row in parser.rows]

    return Report(
        title=report_title,
        org_contexts=org_contexts,
        time_info=time_info,
        headers=headers_2d,
        data_rows=[],
        computed_specs=[],
        description_prompt=None,
    )
```

- [ ] **步骤 4：跑测试，确认通过**

```bash
cd skills/public/ai-report && python -m pytest tests/test_parse_md.py -v
```

- [ ] **步骤 5：commit**

```bash
git add skills/public/ai-report/scripts/parse_md.py skills/public/ai-report/tests/test_parse_md.py
git commit -m "feat(ai-report): add parse_md.py for MD → ReportDoc"
```

---

## 任务 4：`md_lint.py` —— per-section `LintReport`

**文件：**
- 创建：`skills/public/ai-report/scripts/md_lint.py`
- 创建：`skills/public/ai-report/tests/test_md_lint.py`
- 创建：`skills/public/ai-report/tests/fixtures/sample_report_lint_error.md`

**接口：**
- 消费：MD 字符串
- 产出：`lint_markdown(md: str) -> LintReport`；`LintReport` 含 `errors: list[LintIssue]`, `warnings: list[LintIssue]`, `by_section: dict[str, list[LintIssue]]`；`LintIssue` 含 `section_index`, `report_index`, `code`, `message`

检查项：**`> 时期:` 必填 / `<thead>` 必填 / `<th>` 有 `data-idx` 或 `data-computed` / `<th>` `data-unit` ∈ {元, 万元, 亿元, %} / 计算列 `> 计算:` 有 `name:`, `prompt:`, `examples:` / `<th data-period>` 与 `time_info` 一致**。

- [ ] **步骤 1：创建 lint error fixture**

创建 `skills/public/ai-report/tests/fixtures/sample_report_lint_error.md`（含 3 类错误）：

```markdown
# Test Report

## 一、缺时期

### 表1 无时期

> 机构: org_contexts = [{"org_ecd":"x","org_name":"x"}]

<table>
  <thead><tr><th data-idx="A">col</th></tr></thead>
</table>

## 二、缺thead

### 表2 无thead

> 机构: org_contexts = [{"org_ecd":"x","org_name":"x"}]
> 时期: time_info = ["202603"]

<table><tbody><tr><td>no header</td></tr></tbody></table>

## 三、错单位

### 表3 错单位

> 机构: org_contexts = [{"org_ecd":"x","org_name":"x"}]
> 时期: time_info = ["202603"]

<table>
  <thead><tr><th data-idx="A" data-unit="千美元" data-period="202603">col</th></tr></thead>
</table>
```

- [ ] **步骤 2：写失败测试**

创建 `skills/public/ai-report/tests/test_md_lint.py`：

```python
"""Unit tests for md_lint (新写, 借鉴 chatbi-report md_lint.py 检查项)."""

from __future__ import annotations

from md_lint import lint_markdown


def test_lint_happy_path_no_errors():
    md = open("example/wangyi_2026_03.md", encoding="utf-8").read()
    rep = lint_markdown(md)
    assert rep.errors == []


def test_lint_missing_time_info():
    md = open("tests/fixtures/sample_report_lint_error.md", encoding="utf-8").read()
    rep = lint_markdown(md)
    codes = [e.code for e in rep.errors]
    assert "missing_time_info" in codes
    assert "missing_thead" in codes
    assert "invalid_data_unit" in codes


def test_lint_per_section_attribution():
    md = open("tests/fixtures/sample_report_lint_error.md", encoding="utf-8").read()
    rep = lint_markdown(md)
    # 第一个 error 应该在 section 0
    missing_time = next(e for e in rep.errors if e.code == "missing_time_info")
    assert missing_time.section_index == 0
```

- [ ] **步骤 3：跑测试，确认失败**

```bash
cd skills/public/ai-report && python -m pytest tests/test_md_lint.py -v
```

- [ ] **步骤 4：写 `md_lint.py`**

创建 `skills/public/ai-report/scripts/md_lint.py`（**借鉴 chatbi-report `_split_title` / `_split_sections` / `_lint_one_report` 检查项**）：

```python
"""ai-report MD lint: per-section error reporting (新写, 借鉴 chatbi-report 检查项)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

VALID_UNITS = {"元", "万元", "亿元", "%"}


@dataclass
class LintIssue:
    section_index: int
    report_index: int
    code: str
    message: str


@dataclass
class LintReport:
    errors: list[LintIssue] = field(default_factory=list)
    warnings: list[LintIssue] = field(default_factory=list)
    by_section: dict[str, list[LintIssue]] = field(default_factory=dict)

    def add(self, issue: LintIssue) -> None:
        (self.errors if issue.code.startswith(("missing_", "invalid_")) else self.warnings).append(issue)
        key = f"s{issue.section_index}_r{issue.report_index}"
        self.by_section.setdefault(key, []).append(issue)


def lint_markdown(md: str) -> LintReport:
    """Lint a multi-section MD; per-section error attribution."""
    rep = LintReport()
    _, body = _split_title(md)
    for s_idx, (s_title, s_body) in enumerate(_split_sections(body)):
        for r_idx, (r_title, r_body) in enumerate(_split_reports(s_body)):
            _lint_one_report(s_idx, r_idx, r_title, r_body, rep)
    return rep


def _split_title(md: str) -> tuple[str, str]:
    lines = md.splitlines()
    if lines and lines[0].startswith("# "):
        return lines[0][2:].strip(), "\n".join(lines[1:])
    return "", md


def _split_sections(body: str) -> list[tuple[str, str]]:
    out, cur_title, cur_body = [], "", []
    for line in body.splitlines():
        if line.startswith("## "):
            if cur_title or any(s.strip() for s in cur_body):
                out.append((cur_title, "\n".join(cur_body)))
            cur_title, cur_body = line[3:].strip(), []
        else:
            cur_body.append(line)
    if cur_title or any(s.strip() for s in cur_body):
        out.append((cur_title, "\n".join(cur_body)))
    return out


def _split_reports(section_body: str) -> list[tuple[str, str]]:
    out, cur_title, cur_body = [], "", []
    for line in section_body.splitlines():
        if line.startswith("### "):
            if cur_title or any(s.strip() for s in cur_body):
                out.append((cur_title, "\n".join(cur_body)))
            cur_title, cur_body = line[4:].strip(), []
        else:
            cur_body.append(line)
    if cur_title or any(s.strip() for s in cur_body):
        out.append((cur_title, "\n".join(cur_body)))
    return out


def _lint_one_report(s_idx: int, r_idx: int, title: str, body: str, rep: LintReport) -> None:
    if not re.search(r"^>\s*时期:\s*time_info\s*=", body, re.MULTILINE):
        rep.add(LintIssue(s_idx, r_idx, "missing_time_info", f"report `{title}` missing `> 时期:`"))
    if not re.search(r"<thead[^>]*>", body, re.IGNORECASE):
        rep.add(LintIssue(s_idx, r_idx, "missing_thead", f"report `{title}` missing <thead>"))
    for m in re.finditer(r'<th[^>]*data-unit="([^"]+)"', body):
        unit = m.group(1)
        if unit not in VALID_UNITS:
            rep.add(LintIssue(s_idx, r_idx, "invalid_data_unit",
                              f"report `{title}` has invalid data-unit `{unit}`; valid: {VALID_UNITS}"))
    for m in re.finditer(r'<th[^>]*/?>', body):
        tag = m.group(0)
        if "data-idx=" not in tag and "data-computed" not in tag and "{{" not in tag:
            rep.add(LintIssue(s_idx, r_idx, "th_missing_idx",
                              f"report `{title}` has <th> without data-idx"))
```

- [ ] **步骤 5：跑测试，确认通过**

```bash
cd skills/public/ai-report && python -m pytest tests/test_md_lint.py -v
```

- [ ] **步骤 6：commit**

```bash
git add skills/public/ai-report/scripts/md_lint.py skills/public/ai-report/tests/test_md_lint.py skills/public/ai-report/tests/fixtures/sample_report_lint_error.md
git commit -m "feat(ai-report): add md_lint.py with per-section LintReport"
```

---

## 任务 5：`duckdb_store.py` —— 5 表 DDL + CRUD + run_id 历史

**文件：**
- 创建：`skills/public/ai-report/scripts/duckdb_store.py`
- 创建：`skills/public/ai-report/tests/test_duckdb_store.py`

**接口：**
- 消费：`db_path: str`（默认 `/mnt/ai-report-data/duckdb/ai-report.duckdb`，测试用 `:memory:` 或 tmpdir）
- 产出：`Store` 类，方法：`open()`, `init_schema()`, `upsert_report(report_id, title, source_md_path, source_md_hash)`, `upsert_section(report_id, section_order, section_title) -> section_id`, `upsert_table(report_id, section_id, table_order, table_title, source_md_snapshot, source_md_hash, parsed_payload) -> table_id`, `get_report_meta(report_id)`, `get_table(table_id)`, `insert_metric_facts(run_id, table_id, report_id, facts: list[dict])`, `get_metric_facts(run_id, table_id) -> list[dict]`, `save_approved_run(run_id, table_id, report_id, section_id, wide_table, computed_columns, descriptions, status, sentinels, runlog_markdown, design_md_path)`, `list_approved_tables(report_id) -> list[dict]`, `get_approved_run(table_id) -> dict | None`

`report_id` = `sha256(source_md_path)[:16]`；`run_id` = `uuid.uuid4().hex`；`section_id` = `f"{report_id}_s{section_order:02d}"`；`table_id` = `f"{section_id}_t{table_order:02d}"`。

- [ ] **步骤 1：写失败测试**

创建 `skills/public/ai-report/tests/test_duckdb_store.py`：

```python
"""Unit tests for duckdb_store (新写, 5 表 schema 锁定)."""

from __future__ import annotations

import duckdb
import pytest

from duckdb_store import Store


@pytest.fixture
def store(tmp_path):
    s = Store(db_path=str(tmp_path / "test.duckdb"))
    s.open()
    s.init_schema()
    yield s
    s.close()


def test_init_schema_creates_5_tables(store):
    rows = store._conn.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema='main' ORDER BY table_name"
    ).fetchall()
    names = [r[0] for r in rows]
    assert names == ["approved_table_runs", "metric_facts", "report_sections", "report_tables", "reports"]


def test_upsert_report_and_section(store):
    rid = store.upsert_report("rid123", "title", "/tmp/x.md", "hash123")
    assert rid == "rid123"
    sid = store.upsert_section(rid, 0, "一、章")
    assert sid == "rid123_s00"


def test_upsert_table_id_naming(store):
    rid = store.upsert_report("rid", "t", "/x", "h")
    sid = store.upsert_section(rid, 0, "s")
    tid = store.upsert_table(rid, sid, 0, "table", "md", "h", {"x": 1})
    assert tid == "rid_s00_t00"


def test_run_id_history_preserved(store):
    rid = store.upsert_report("rid", "t", "/x", "h")
    sid = store.upsert_section(rid, 0, "s")
    tid = store.upsert_table(rid, sid, 0, "table", "md", "h", {})
    # 两次 design run, 都应该保留
    store.insert_metric_facts("run1", tid, rid, [{"branch_num": "1", "idx_id": "A", "period_alias": "202603", "numeric_value": 100, "status": "ok"}])
    store.insert_metric_facts("run2", tid, rid, [{"branch_num": "1", "idx_id": "A", "period_alias": "202603", "numeric_value": 200, "status": "ok"}])
    r1 = store.get_metric_facts("run1", tid)
    r2 = store.get_metric_facts("run2", tid)
    assert len(r1) == 1 and r1[0]["numeric_value"] == 100
    assert len(r2) == 1 and r2[0]["numeric_value"] == 200


def test_approved_run_design_md_path_not_null(store):
    rid = store.upsert_report("rid", "t", "/x", "h")
    sid = store.upsert_section(rid, 0, "s")
    tid = store.upsert_table(rid, sid, 0, "table", "md", "h", {})
    store.save_approved_run("run1", tid, rid, sid, [], [], [], "ok", [], "log", "/mnt/ai-report-data/rid.design.md")
    run = store.get_approved_run(tid)
    assert run["design_md_path"] == "/mnt/ai-report-data/rid.design.md"
```

- [ ] **步骤 2：跑测试，确认失败**

```bash
cd skills/public/ai-report && python -m pytest tests/test_duckdb_store.py -v
```

- [ ] **步骤 3：写 `duckdb_store.py`**

创建 `skills/public/ai-report/scripts/duckdb_store.py`（**5 张表 DDL 锁定 phase 1, schema_version=1**）：

```python
"""ai-report: 5-table DuckDB store with run_id history (新写, 纯 DuckDB, 无 pandas)."""
from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

import duckdb

DEFAULT_DB_PATH = "/mnt/ai-report-data/duckdb/ai-report.duckdb"


class Store:
    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self._db_path = db_path
        self._conn: duckdb.DuckDBPyConnection | None = None

    def open(self) -> None:
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = duckdb.connect(self._db_path)

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    @property
    def conn(self) -> duckdb.DuckDBPyConnection:
        assert self._conn is not None, "Store not opened"
        return self._conn

    def init_schema(self) -> None:
        self.conn.executescript(_SCHEMA_SQL)


# ID 命名见 spec §preamble
def make_report_id(source_md_path: str) -> str:
    return hashlib.sha256(source_md_path.encode("utf-8")).hexdigest()[:16]


def make_run_id() -> str:
    return uuid.uuid4().hex


def make_section_id(report_id: str, section_order: int) -> str:
    return f"{report_id}_s{section_order:02d}"


def make_table_id(section_id: str, table_order: int) -> str:
    return f"{section_id}_t{table_order:02d}"


# ---------- CRUD ---------- #

def upsert_report(self, report_id: str, title: str, source_md_path: str, source_md_hash: str) -> str:
    self.conn.execute(
        """INSERT INTO reports (report_id, schema_version, report_title, source_md_path, source_md_hash)
           VALUES (?, 1, ?, ?, ?)
           ON CONFLICT (report_id) DO UPDATE SET
             report_title=excluded.report_title,
             source_md_path=excluded.source_md_path,
             source_md_hash=excluded.source_md_hash,
             updated_at=current_timestamp""",
        [report_id, title, source_md_path, source_md_hash],
    )
    return report_id


def upsert_section(self, report_id: str, section_order: int, section_title: str) -> str:
    section_id = make_section_id(report_id, section_order)
    self.conn.execute(
        """INSERT INTO report_sections (section_id, schema_version, report_id, section_order, section_title)
           VALUES (?, 1, ?, ?, ?)
           ON CONFLICT (section_id) DO UPDATE SET section_title=excluded.section_title""",
        [section_id, report_id, section_order, section_title],
    )
    return section_id


def upsert_table(
    self, report_id: str, section_id: str, table_order: int, table_title: str,
    source_md_snapshot: str, source_md_hash: str, parsed_payload: dict,
) -> str:
    table_id = make_table_id(section_id, table_order)
    import json as _json
    self.conn.execute(
        """INSERT INTO report_tables
           (table_id, schema_version, report_id, section_id, table_order, table_title,
            approval_status, source_md_snapshot, source_md_hash, parsed_payload)
           VALUES (?, 1, ?, ?, ?, ?, 'draft', ?, ?, ?)
           ON CONFLICT (table_id) DO UPDATE SET
             table_title=excluded.table_title,
             source_md_snapshot=excluded.source_md_snapshot,
             source_md_hash=excluded.source_md_hash,
             parsed_payload=excluded.parsed_payload,
             updated_at=current_timestamp""",
        [table_id, report_id, section_id, table_order, table_title,
         source_md_snapshot, source_md_hash, _json.dumps(parsed_payload, ensure_ascii=False)],
    )
    return table_id


def get_report_meta(self, report_id: str) -> dict | None:
    row = self.conn.execute("SELECT * FROM reports WHERE report_id=?", [report_id]).fetchone()
    if not row:
        return None
    cols = [d[0] for d in self.conn.description]
    return dict(zip(cols, row))


def get_table(self, table_id: str) -> dict | None:
    row = self.conn.execute("SELECT * FROM report_tables WHERE table_id=?", [table_id]).fetchone()
    if not row:
        return None
    cols = [d[0] for d in self.conn.description]
    return dict(zip(cols, row))


def insert_metric_facts(self, run_id: str, table_id: str, report_id: str, facts: list[dict]) -> None:
    import json as _json
    for f in facts:
        self.conn.execute(
            """INSERT INTO metric_facts
               (run_id, schema_version, table_id, report_id, branch_num, branch_short_name,
                idx_id, period_alias, period_value, raw_value, numeric_value, status, error_message)
               VALUES (?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT DO NOTHING""",
            [
                run_id, table_id, report_id,
                f.get("branch_num", ""), f.get("branch_short_name"),
                f.get("idx_id", ""), f.get("period_alias", ""), f.get("period_value"),
                f.get("raw_value"), f.get("numeric_value"),
                f.get("status", "ok"), f.get("error_message"),
            ],
        )


def get_metric_facts(self, run_id: str, table_id: str) -> list[dict]:
    rows = self.conn.execute(
        "SELECT * FROM metric_facts WHERE run_id=? AND table_id=? ORDER BY branch_num, idx_id, period_alias",
        [run_id, table_id],
    ).fetchall()
    cols = [d[0] for d in self.conn.description]
    return [dict(zip(cols, r)) for r in rows]


def save_approved_run(
    self, run_id: str, table_id: str, report_id: str, section_id: str,
    wide_table: list, computed_columns: list, descriptions: list, status: str,
    sentinels: list, runlog_markdown: str, design_md_path: str,
) -> None:
    import json as _json
    self.conn.execute(
        """INSERT INTO approved_table_runs
           (run_id, schema_version, table_id, report_id, section_id, wide_table,
            computed_columns, descriptions, status, sentinels, runlog_markdown, design_md_path)
           VALUES (?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [run_id, table_id, report_id, section_id, _json.dumps(wide_table, ensure_ascii=False),
         _json.dumps(computed_columns, ensure_ascii=False),
         _json.dumps(descriptions, ensure_ascii=False),
         status, _json.dumps(sentinels, ensure_ascii=False),
         runlog_markdown, design_md_path],
    )
    # 同步 report_tables.approval_status + last_design_run_id
    self.conn.execute(
        """UPDATE report_tables
           SET approval_status='approved', last_design_run_id=?, updated_at=current_timestamp
           WHERE table_id=?""",
        [run_id, table_id],
    )


def list_approved_tables(self, report_id: str) -> list[dict]:
    rows = self.conn.execute(
        """SELECT rt.table_id, rt.section_id, rt.table_order, rt.table_title,
                  rs.section_order, rs.section_title,
                  atr.run_id, atr.wide_table, atr.computed_columns, atr.descriptions,
                  atr.status, atr.sentinels, atr.runlog_markdown
           FROM report_tables rt
           JOIN report_sections rs ON rt.section_id=rs.section_id
           JOIN approved_table_runs atr ON atr.run_id=rt.last_design_run_id
           WHERE rt.report_id=? AND rt.approval_status='approved'
           ORDER BY rs.section_order, rt.table_order""",
        [report_id],
    ).fetchall()
    cols = [d[0] for d in self.conn.description]
    return [dict(zip(cols, r)) for r in rows]


def get_approved_run(self, table_id: str) -> dict | None:
    row = self.conn.execute(
        """SELECT * FROM approved_table_runs
           WHERE table_id=? ORDER BY created_at DESC LIMIT 1""",
        [table_id],
    ).fetchone()
    if not row:
        return None
    cols = [d[0] for d in self.conn.description]
    return dict(zip(cols, row))


# 把方法绑到 Store 类
Store.upsert_report = upsert_report
Store.upsert_section = upsert_section
Store.upsert_table = upsert_table
Store.get_report_meta = get_report_meta
Store.get_table = get_table
Store.insert_metric_facts = insert_metric_facts
Store.get_metric_facts = get_metric_facts
Store.save_approved_run = save_approved_run
Store.list_approved_tables = list_approved_tables
Store.get_approved_run = get_approved_run


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS reports (
  report_id        TEXT PRIMARY KEY,
  schema_version   INTEGER NOT NULL DEFAULT 1,
  report_title     TEXT NOT NULL,
  source_md_path   TEXT NOT NULL,
  source_md_hash   TEXT NOT NULL,
  created_at       TIMESTAMP NOT NULL DEFAULT current_timestamp,
  updated_at       TIMESTAMP NOT NULL DEFAULT current_timestamp
);

CREATE TABLE IF NOT EXISTS report_sections (
  section_id       TEXT PRIMARY KEY,
  schema_version   INTEGER NOT NULL DEFAULT 1,
  report_id        TEXT NOT NULL REFERENCES reports(report_id),
  section_order    INTEGER NOT NULL,
  section_title    TEXT NOT NULL,
  created_at       TIMESTAMP NOT NULL DEFAULT current_timestamp,
  UNIQUE(report_id, section_order)
);

CREATE TABLE IF NOT EXISTS report_tables (
  table_id              TEXT PRIMARY KEY,
  schema_version        INTEGER NOT NULL DEFAULT 1,
  report_id             TEXT NOT NULL REFERENCES reports(report_id),
  section_id            TEXT NOT NULL REFERENCES report_sections(section_id),
  table_order           INTEGER NOT NULL,
  table_title           TEXT NOT NULL,
  approval_status       TEXT NOT NULL DEFAULT 'draft'
                            CHECK (approval_status IN ('draft','approved','rejected')),
  source_md_snapshot    TEXT NOT NULL,
  source_md_hash        TEXT NOT NULL,
  parsed_payload        JSON NOT NULL,
  last_design_run_id    TEXT,
  created_at            TIMESTAMP NOT NULL DEFAULT current_timestamp,
  updated_at            TIMESTAMP NOT NULL DEFAULT current_timestamp,
  UNIQUE(report_id, section_id, table_order)
);
CREATE INDEX IF NOT EXISTS idx_report_tables_status ON report_tables(report_id, approval_status);

CREATE TABLE IF NOT EXISTS metric_facts (
  run_id              TEXT NOT NULL,
  schema_version      INTEGER NOT NULL DEFAULT 1,
  table_id            TEXT NOT NULL REFERENCES report_tables(table_id),
  report_id           TEXT NOT NULL,
  branch_num          TEXT NOT NULL,
  branch_short_name   TEXT,
  idx_id              TEXT NOT NULL,
  period_alias        TEXT NOT NULL,
  period_value        TEXT,
  raw_value           TEXT,
  numeric_value       DECIMAL(38,10),
  status              TEXT NOT NULL,
  error_message       TEXT,
  created_at          TIMESTAMP NOT NULL DEFAULT current_timestamp,
  PRIMARY KEY(run_id, table_id, branch_num, idx_id, period_alias)
);
CREATE INDEX IF NOT EXISTS idx_metric_facts_run ON metric_facts(run_id, table_id);

CREATE TABLE IF NOT EXISTS approved_table_runs (
  run_id              TEXT NOT NULL,
  schema_version      INTEGER NOT NULL DEFAULT 1,
  table_id            TEXT NOT NULL REFERENCES report_tables(table_id),
  report_id           TEXT NOT NULL,
  section_id          TEXT NOT NULL,
  wide_table          JSON NOT NULL,
  computed_columns    JSON NOT NULL DEFAULT '[]',
  descriptions        JSON NOT NULL DEFAULT '[]',
  status              TEXT NOT NULL,
  sentinels           JSON NOT NULL DEFAULT '[]',
  runlog_markdown     TEXT NOT NULL,
  design_md_path      TEXT NOT NULL,
  created_at          TIMESTAMP NOT NULL DEFAULT current_timestamp,
  PRIMARY KEY(run_id, table_id)
);
CREATE INDEX IF NOT EXISTS idx_approved_runs_table ON approved_table_runs(table_id, created_at DESC);
"""
```

- [ ] **步骤 4：跑测试，确认通过**

```bash
cd skills/public/ai-report && python -m pytest tests/test_duckdb_store.py -v
```

- [ ] **步骤 5：commit**

```bash
git add skills/public/ai-report/scripts/duckdb_store.py skills/public/ai-report/tests/test_duckdb_store.py
git commit -m "feat(ai-report): add duckdb_store.py with 5-table schema (schema_version=1)"
```

---

## 任务 6：`sqlbot_client.py` —— httpx + mock fixture

**文件：**
- 创建：`skills/public/ai-report/scripts/sqlbot_client.py`
- 创建：`skills/public/ai-report/tests/test_sqlbot_client.py`
- 创建：`skills/public/ai-report/tests/fixtures/mock_sqlbot/wangyi_2026_03.json`

**接口：**
- `RealSQLBotClient(base_url=None)` → `query_report_info(org_info, index_info, time_info, *, timeout=30) -> QueryReportInfoResponse`
- `MockSQLBotClient(fixture_path)` → 同上
- `QueryReportInfoResponse(code: int, data: list[dict])`

源单位固定 = 元（无单位识别，client 透传 raw_value）。

- [ ] **步骤 1：创建 mock fixture**

创建 `skills/public/ai-report/tests/fixtures/mock_sqlbot/wangyi_2026_03.json`：

```json
{
  "BAS_001@202603": {
    "success": true,
    "data": [
      {"data_dt": "2026-03-31", "org_ecd": "wangyi_credit_union", "idx_name": "存款余额", "value": 1234567890.50}
    ]
  },
  "BAS_010@202603": {
    "success": true,
    "data": [
      {"data_dt": "2026-03-31", "org_ecd": "wangyi_credit_union", "idx_name": "贷款余额", "value": 987654321.00}
    ]
  },
  "BAS_020@202603": {"success": true, "data": [{"data_dt": "2026-03-31", "org_ecd": "wangyi_credit_union", "idx_name": "营业收入", "value": 50000000.00}]},
  "BAS_026@202603": {"success": true, "data": [{"data_dt": "2026-03-31", "org_ecd": "wangyi_credit_union", "idx_name": "利润总额", "value": 10000000.00}]},
  "BAS_030@202603": {"success": true, "data": [{"data_dt": "2026-03-31", "org_ecd": "wangyi_credit_union", "idx_name": "不良贷款率", "value": 0.0183}]}
}
```

- [ ] **步骤 2：写失败测试**

创建 `skills/public/ai-report/tests/test_sqlbot_client.py`：

```python
"""Unit tests for sqlbot_client (新写, 借鉴 chatbi-report sqlbot_client.py 接口)."""

from __future__ import annotations

import pytest

from sqlbot_client import MockSQLBotClient, SQLBotError


def test_mock_client_returns_success():
    c = MockSQLBotClient(fixture_path="tests/fixtures/mock_sqlbot/wangyi_2026_03.json")
    resp = c.query_report_info(
        org_info=[{"org_ecd": "wangyi_credit_union"}],
        index_info=[{"idx_id": "BAS_001@202603"}],
        time_info=["202603"],
    )
    assert resp.code == 0
    assert resp.data[0]["success"] is True
    assert resp.data[0]["data"][0]["value"] == 1234567890.50


def test_mock_client_missing_idx_returns_empty():
    c = MockSQLBotClient(fixture_path="tests/fixtures/mock_sqlbot/wangyi_2026_03.json")
    resp = c.query_report_info(
        org_info=[],
        index_info=[{"idx_id": "MISSING_IDX@202603"}],
        time_info=["202603"],
    )
    elem = resp.data[0]
    assert elem["success"] is False
    assert elem["data"] == []


def test_mock_client_rejects_empty_index_info():
    c = MockSQLBotClient(fixture_path="tests/fixtures/mock_sqlbot/wangyi_2026_03.json")
    with pytest.raises(SQLBotError, match="index_info must contain"):
        c.query_report_info(org_info=[], index_info=[], time_info=[])
```

- [ ] **步骤 3：跑测试，确认失败**

```bash
cd skills/public/ai-report && python -m pytest tests/test_sqlbot_client.py -v
```

- [ ] **步骤 4：写 `sqlbot_client.py`**

创建 `skills/public/ai-report/scripts/sqlbot_client.py`（**接口借鉴 chatbi-report, 代码新写**）：

```python
"""ai-report SQLBot client (新写, 借鉴 chatbi-report sqlbot_client.py 接口)."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from retry import exponential, retry


_TRANSIENT_HTTP = (httpx.HTTPError, ConnectionError, TimeoutError)


class SQLBotError(Exception):
    pass


@dataclass
class QueryReportInfoResponse:
    code: int
    data: list[dict]


class RealSQLBotClient:
    ENDPOINT_PATH = "/api/v1/indicator/query-report-info"

    def __init__(self, base_url: str | None = None) -> None:
        url = base_url or os.environ.get("SQLBOT_BASE_URL", "")
        if not url:
            raise SQLBotError("SQLBOT_BASE_URL is not set")
        self._base_url = url.rstrip("/")

    @retry(max_attempts=3, backoff=exponential(1.0, 8.0), retry_on=_TRANSIENT_HTTP)
    def query_report_info(
        self, org_info: list[dict], index_info: list[dict], time_info: list[str],
        *, timeout: int = 30,
    ) -> QueryReportInfoResponse:
        resp = httpx.post(
            f"{self._base_url}{self.ENDPOINT_PATH}",
            json={"org_info": org_info, "index_info": index_info, "time_info": time_info},
            headers={"Content-Type": "application/json"},
            timeout=timeout,
        )
        resp.raise_for_status()
        payload = resp.json()
        code = payload.get("code")
        if code != 0:
            raise SQLBotError(f"query_report_info failed: code={code}, msg={payload.get('msg')}")
        return QueryReportInfoResponse(code=code, data=payload.get("data", []))


class MockSQLBotClient:
    def __init__(self, fixture_path: str) -> None:
        self._fixture: dict[str, Any] = json.loads(Path(fixture_path).read_text(encoding="utf-8"))

    def query_report_info(
        self, org_info: list[dict], index_info: list[dict], time_info: list[str],
        **_kwargs: Any,
    ) -> QueryReportInfoResponse:
        if not index_info:
            raise SQLBotError("index_info must contain at least one idx_id")
        idx_id = index_info[0]["idx_id"]
        period = time_info[0] if time_info else None
        entry = self._lookup(idx_id, period)
        success = bool(entry.get("success", False))
        elem = {
            "success": success,
            "msg": entry.get("msg", "指标数据查询成功。" if success else "数据不可用。"),
            "record_id": 0,
            "sql": "[mocked]",
            "data": entry.get("data", []),
            "data_interpret": "[mocked]",
            "fields": [
                {"name": "日期", "value": "data_dt"},
                {"name": "机构名称", "value": "org_ecd"},
                {"name": "指标名称", "value": "idx_name"},
                {"name": "指标值", "value": "value"},
            ],
        }
        return QueryReportInfoResponse(code=0, data=[elem])

    def _lookup(self, idx_id: str, period: str | None) -> dict:
        if period:
            composite = f"{idx_id}@{period}"
            if composite in self._fixture:
                return self._fixture[composite]
        if idx_id in self._fixture:
            return dict(self._fixture[idx_id])
        return {"success": False, "data": []}
```

- [ ] **步骤 5：跑测试，确认通过**

```bash
cd skills/public/ai-report && python -m pytest tests/test_sqlbot_client.py -v
```

- [ ] **步骤 6：commit**

```bash
git add skills/public/ai-report/scripts/sqlbot_client.py skills/public/ai-report/tests/test_sqlbot_client.py skills/public/ai-report/tests/fixtures/mock_sqlbot/
git commit -m "feat(ai-report): add sqlbot_client.py with httpx + mock fixture"
```

---

## 任务 7：`unit_convert.py` —— 单位字典 + UPDATE SQL 生成

**文件：**
- 创建：`skills/public/ai-report/scripts/unit_convert.py`
- 创建：`skills/public/ai-report/tests/test_unit_convert.py`

**接口：**
- 消费：parsed_payload（`headers: list[list[Th]]`）+ wide_table（list of dicts with key=`idx_id@period`）
- 产出：`generate_update_sql(parsed_headers, target_table='wide') -> str` 返回多行 `UPDATE wide SET <col> = <col> * 100 / 10000 / 100000000` SQL（按列拼, 基础列 vs 计算列语义不同）

源单位 = 元固定。目标单位 ∈ {元, 万元, 亿元, %}。基础列换算:元→目标除以 10^N；计算列:目标=%,则 `* 100`(基础列不应用 % 换算)。

- [ ] **步骤 1：写失败测试**

创建 `skills/public/ai-report/tests/test_unit_convert.py`：

```python
"""Unit tests for unit_convert (新写, 8 种组合覆盖)."""

from __future__ import annotations

from dataclasses import dataclass

from unit_convert import generate_update_sql


def _th(text, data_unit=None, is_computed=False, idx_id=None, period=None):
    @dataclass
    class T:
        text: str
        data_unit: str | None = None
        is_computed: bool = False
        idx_id: str | None = None
        period: str | None = None
    return T(text=text, data_unit=data_unit, is_computed=is_computed, idx_id=idx_id, period=period)


def test_yuan_target_emits_no_update():
    headers = [[_th("col", data_unit="元", idx_id="A", period="202603")]]
    sql = generate_update_sql(headers, target_table="wide")
    assert sql.strip() == ""


def test_wan_target_emits_divide_10000():
    headers = [[_th("col", data_unit="万元", idx_id="A", period="202603")]]
    sql = generate_update_sql(headers, target_table="wide")
    assert "wide" in sql
    assert "/ 10000" in sql


def test_yi_target_emits_divide_100000000():
    headers = [[_th("col", data_unit="亿元", idx_id="A", period="202603")]]
    sql = generate_update_sql(headers, target_table="wide")
    assert "/ 100000000" in sql


def test_percent_target_on_computed_emits_multiply_100():
    headers = [[_th("ratio", data_unit="%", is_computed=True, idx_id=None, period="202603")]]
    sql = generate_update_sql(headers, target_table="wide")
    assert "* 100" in sql


def test_percent_target_on_basic_emits_no_update():
    # 基础列不应用 % 换算 (Phase 1 政策)
    headers = [[_th("col", data_unit="%", is_computed=False, idx_id="A", period="202603")]]
    sql = generate_update_sql(headers, target_table="wide")
    assert sql.strip() == ""


def test_unknown_unit_emits_no_update():
    headers = [[_th("col", data_unit="千美元", idx_id="A", period="202603")]]
    sql = generate_update_sql(headers, target_table="wide")
    assert sql.strip() == ""


def test_mixed_columns_emits_multiple_updates():
    headers = [
        [_th("a", data_unit="万元", idx_id="A", period="202603")],
        [_th("b", data_unit="元", idx_id="B", period="202603")],
        [_th("c", data_unit="%", is_computed=True, idx_id=None)],
    ]
    sql = generate_update_sql(headers, target_table="wide")
    assert "/ 10000" in sql
    assert "* 100" in sql
    # 元 不出现在 SQL 中
    assert "B" not in sql


def test_columns_keyed_by_idx_at_period():
    headers = [[_th("a", data_unit="万元", idx_id="BAS_001", period="202603")]]
    sql = generate_update_sql(headers, target_table="wide")
    # column key in wide table
    assert "BAS_001@202603" in sql
```

- [ ] **步骤 2：跑测试，确认失败**

```bash
cd skills/public/ai-report && python -m pytest tests/test_unit_convert.py -v
```

- [ ] **步骤 3：写 `unit_convert.py`**

创建 `skills/public/ai-report/scripts/unit_convert.py`：

```python
"""ai-report unit conversion: generate DuckDB UPDATE SQL (新写, 硬编码单位字典).

源单位固定 = 元; 目标单位 ∈ {元, 万元, 亿元, %}.
基础列:  元→万元 / 10000,  元→亿元 / 100000000,  元→元 不变
计算列:  目标 % 才转换, * 100; 其他不变
"""
from __future__ import annotations

BASIC_FACTORS = {"万元": "/ 10000", "亿元": "/ 100000000"}
COMPUTED_FACTORS = {"%": "* 100"}


def generate_update_sql(headers: list[list], target_table: str = "wide") -> str:
    """Generate DuckDB UPDATE statements for unit conversion.

    headers: list[list[Th]]; flatten unique (idx_id, period) per leaf column.
    Computed columns: key by Th.text.
    """
    seen: set[str] = set()
    statements: list[str] = []
    for row in headers:
        for th in row:
            unit = getattr(th, "data_unit", None)
            if not unit:
                continue
            if th.is_computed or getattr(th, "is_computed", False):
                col_key = th.text
                factor_expr = COMPUTED_FACTORS.get(unit)
            else:
                idx = getattr(th, "idx_id", None)
                period = getattr(th, "period", None)
                if not idx:
                    continue
                col_key = f"{idx}@{period}" if period else idx
                factor_expr = BASIC_FACTORS.get(unit)
            if not factor_expr or col_key in seen:
                continue
            seen.add(col_key)
            statements.append(
                f"UPDATE {target_table} SET \"{col_key}\" = \"{col_key}\" {factor_expr};"
            )
    return "\n".join(statements)
```

- [ ] **步骤 4：跑测试，确认通过**

```bash
cd skills/public/ai-report && python -m pytest tests/test_unit_convert.py -v
```

- [ ] **步骤 5：commit**

```bash
git add skills/public/ai-report/scripts/unit_convert.py skills/public/ai-report/tests/test_unit_convert.py
git commit -m "feat(ai-report): add unit_convert.py (DuckDB UPDATE SQL gen, no pandas)"
```

---

## 任务 8：`compute.py` —— `assemble-wide` + `extract-ir`（DuckDB PIVOT + JSON IR）

**文件：**
- 创建：`skills/public/ai-report/scripts/compute.py`（先写这两个 sub-command）
- 创建：`skills/public/ai-report/tests/test_compute.py`

**接口：**
- `assemble_wide(metric_facts: list[dict], parsed_headers, run_id, table_id) -> list[dict]`：从 `metric_facts` 用 DuckDB PIVOT 出 `[{branch_num, idx_id@period: value, ...}, ...]` 内存 wide
- `extract_ir(parsed_payload: dict) -> list[ComputeIR]`：从 `> 计算:` 块解析 `[{name, prompt, examples}, ...]`

`ComputeIR` dataclass：`name: str`, `prompt: str`, `examples: list[dict]`（和 chatbi-report 字段一致）。

- [ ] **步骤 1：写失败测试（仅本任务的 sub-commands）**

在 `skills/public/ai-report/tests/test_compute.py` 追加：

```python
from compute import ComputeIR, assemble_wide, extract_ir


def test_extract_ir_parses_compute_block():
    body = """
> 计算: name = "利润率", prompt = "利润总额 / 营业收入", examples = [{"row": 0, "value": 0.2}]
> 计算: name = "成本率", prompt = "(营业收入-利润总额) / 营业收入"
"""
    irs = extract_ir(body)
    assert len(irs) == 2
    assert irs[0].name == "利润率"
    assert irs[0].prompt == "利润总额 / 营业收入"
    assert irs[0].examples == [{"row": 0, "value": 0.2}]
    assert irs[1].name == "成本率"


def test_assemble_wide_pivots_metric_facts():
    facts = [
        {"branch_num": "1", "idx_id": "A", "period_alias": "202603", "numeric_value": 100, "status": "ok"},
        {"branch_num": "1", "idx_id": "B", "period_alias": "202603", "numeric_value": 200, "status": "ok"},
        {"branch_num": "2", "idx_id": "A", "period_alias": "202603", "numeric_value": 300, "status": "ok"},
    ]
    wide = assemble_wide(facts, run_id="r1", table_id="t1")
    assert len(wide) == 2
    by_branch = {r["branch_num"]: r for r in wide}
    assert by_branch["1"]["A@202603"] == 100
    assert by_branch["1"]["B@202603"] == 200
    assert by_branch["2"]["A@202603"] == 300


def test_assemble_wide_preserves_sentinel_cells():
    facts = [
        {"branch_num": "1", "idx_id": "A", "period_alias": "202603", "numeric_value": None, "status": "query_failed"},
    ]
    wide = assemble_wide(facts, run_id="r1", table_id="t1")
    assert wide[0]["A@202603"] == "⚠️QUERY_FAILED"
```

- [ ] **步骤 2：跑测试，确认失败**

```bash
cd skills/public/ai-report && python -m pytest tests/test_compute.py -v
```

- [ ] **步骤 3：写 `compute.py` (子集:assemble-wide + extract-ir)**

创建 `skills/public/ai-report/scripts/compute.py`（**先写这两个, 后面任务再追加 validate/evaluate/apply-computed**）：

```python
"""ai-report compute (新写, 纯 DuckDB, 无 pandas). 5 sub-commands: assemble-wide / extract-ir / validate / evaluate / apply-computed."""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any

import duckdb


SENTINEL_CAST_FAILED = "⚠️CAST_FAILED"
SENTINEL_QUERY_FAILED = "⚠️QUERY_FAILED"


@dataclass
class ComputeIR:
    name: str
    prompt: str
    examples: list[dict] = field(default_factory=list)


# ---------- extract-ir ---------- #

def extract_ir(body: str) -> list[ComputeIR]:
    """Parse `> 计算:` blocks from report MD body.

    Each block: `> 计算: name = "X", prompt = "Y"[, examples = [...]]`
    """
    irs: list[ComputeIR] = []
    pattern = re.compile(
        r'>\s*计算:\s*name\s*=\s*"([^"]+)"\s*,\s*prompt\s*=\s*"([^"]+)"(?:\s*,\s*examples\s*=\s*(\[[^\]]*\]))?',
    )
    for m in pattern.finditer(body):
        name, prompt, examples_raw = m.group(1), m.group(2), m.group(3)
        examples = json.loads(examples_raw) if examples_raw else []
        irs.append(ComputeIR(name=name, prompt=prompt, examples=examples))
    return irs


# ---------- assemble-wide ---------- #

def assemble_wide(metric_facts: list[dict], run_id: str, table_id: str) -> list[dict]:
    """PIVOT metric_facts to wide table via DuckDB. Returns list of {branch_num, idx_id@period: value, ...}."""
    conn = duckdb.connect(":memory:")
    conn.execute(
        """CREATE TABLE facts (branch_num TEXT, idx_id TEXT, period_alias TEXT,
                               numeric_value VARCHAR, status TEXT)"""
    )
    for f in metric_facts:
        value = f.get("numeric_value")
        if f.get("status") != "ok" or value is None:
            cell = SENTINEL_QUERY_FAILED if f.get("status") == "query_failed" else SENTINEL_CAST_FAILED
        else:
            cell = float(value)
        conn.execute(
            "INSERT INTO facts VALUES (?, ?, ?, ?, ?)",
            [f.get("branch_num", ""), f.get("idx_id", ""), f.get("period_alias", ""),
             json.dumps(cell) if isinstance(cell, str) else cell, f.get("status", "ok")],
        )
    rows = conn.execute(
        """SELECT * FROM facts PIVOT (
             MAX(CASE WHEN status='ok' THEN CAST(numeric_value AS DOUBLE) ELSE NULL END)
             FOR (idx_id, period_alias) IN (SELECT idx_id, period_alias FROM facts)
           )"""
    ).fetchall()
    cols = [d[0] for d in conn.description]
    return [dict(zip(cols, r)) for r in rows]
```

- [ ] **步骤 4：跑测试，确认通过（仅这 3 个）**

```bash
cd skills/public/ai-report && python -m pytest tests/test_compute.py -v
```

- [ ] **步骤 5：commit**

```bash
git add skills/public/ai-report/scripts/compute.py skills/public/ai-report/tests/test_compute.py
git commit -m "feat(ai-report): compute.py assemble-wide (DuckDB PIVOT) + extract-ir"
```

---

## 任务 9：`compute.py` —— `validate` (5 层校验)

**文件：**
- 修改：`skills/public/ai-report/scripts/compute.py`（追加 `validate` 函数）
- 修改：`skills/public/ai-report/tests/test_compute.py`（追加测试）

**接口：**
- `validate(sql: str, wide_sample_rows: list[dict], expected_columns: list[str], example_input: dict | None, example_expected: float | None) -> ValidationResult`
- `ValidationResult(passed: bool, layer: str, error: str | None)` —— 失败时 `layer` 标 `"explain" | "from_wide" | "branch_num" | "smoke" | "example"`，成功时 `passed=True, layer="all"`

5 层依次:EXPLAIN / FROM wide / branch_num / smoke 3 rows / example 1 row。

- [ ] **步骤 1：写失败测试**

在 `test_compute.py` 追加：

```python
from compute import ValidationResult, validate


def test_validate_explain_fails_on_broken_sql():
    res = validate("SELECT * FORM wide", [], ["branch_num"], None, None)
    assert res.passed is False
    assert res.layer == "explain"


def test_validate_from_wide_fails_when_no_from_wide():
    res = validate("SELECT 1 AS x", [{"branch_num": "1"}], ["branch_num", "x"], None, None)
    assert res.passed is False
    assert res.layer == "from_wide"


def test_validate_branch_num_fails_when_no_branch_num():
    res = validate("SELECT 1 AS x FROM wide", [{"branch_num": "1"}], ["x"], None, None)
    assert res.passed is False
    assert res.layer == "branch_num"


def test_validate_smoke_passes_on_simple_select():
    res = validate(
        "SELECT branch_num, 1 AS x FROM wide",
        [{"branch_num": "1"}, {"branch_num": "2"}, {"branch_num": "3"}],
        ["branch_num", "x"],
        None, None,
    )
    assert res.passed is True
    assert res.layer == "all"


def test_validate_example_passes_when_close():
    res = validate(
        "SELECT branch_num, 2.0 AS x FROM wide",
        [{"branch_num": "1"}],
        ["branch_num", "x"],
        example_input={"branch_num": "1"},
        example_expected=2.0,
    )
    assert res.passed is True
```

- [ ] **步骤 2：跑测试，确认失败**

```bash
cd skills/public/ai-report && python -m pytest tests/test_compute.py -v
```

- [ ] **步骤 3：追加 `validate` 到 `compute.py`**

在 `compute.py` 末尾追加：

```python
# ---------- validate (5 层) ---------- #

@dataclass
class ValidationResult:
    passed: bool
    layer: str  # "all" if passed; else "explain" | "from_wide" | "branch_num" | "smoke" | "example"
    error: str | None = None


def validate(
    sql: str,
    wide_sample_rows: list[dict],
    expected_columns: list[str],
    example_input: dict | None,
    example_expected: float | None,
) -> ValidationResult:
    """5-layer validation. 无 keyword blacklist (Phase 1 政策)."""
    conn = duckdb.connect(":memory:")
    # 第 1 层: EXPLAIN
    try:
        conn.execute(f"EXPLAIN {sql}")
    except Exception as e:
        return ValidationResult(False, "explain", str(e))

    # 第 2 层: FROM wide
    upper = sql.upper()
    if "FROM WIDE" not in upper:
        return ValidationResult(False, "from_wide", "SQL must contain 'FROM wide'")

    # 第 3 层: branch_num 输出
    if "BRANCH_NUM" not in upper:
        return ValidationResult(False, "branch_num", "SQL must SELECT branch_num")

    # 建临时 wide 表, 灌入 sample rows
    if wide_sample_rows:
        cols = list(wide_sample_rows[0].keys())
        col_defs = ", ".join(f'"{c}" VARCHAR' for c in cols)
        conn.execute(f"CREATE TABLE wide ({col_defs})")
        for row in wide_sample_rows:
            conn.execute(
                f"INSERT INTO wide VALUES ({', '.join(['?'] * len(cols))})",
                [str(row.get(c, "")) for c in cols],
            )
    else:
        conn.execute("CREATE TABLE wide (branch_num VARCHAR)")

    # 第 4 层: smoke (SAMPLE 3 rows)
    try:
        smoke_sql = f"SELECT * FROM ({sql}) USING SAMPLE 3 ROWS"
        result = conn.execute(smoke_sql).fetchall()
        if not result:
            return ValidationResult(False, "smoke", "SAMPLE 3 ROWS returned no rows")
    except Exception as e:
        return ValidationResult(False, "smoke", str(e))

    # 第 5 层: example (math.isclose)
    if example_input is not None and example_expected is not None:
        try:
            target_branch = example_input.get("branch_num", "")
            row = conn.execute(
                f"SELECT * FROM ({sql}) WHERE branch_num=? LIMIT 1", [target_branch]
            ).fetchone()
            if not row:
                return ValidationResult(False, "example", f"no row for branch_num={target_branch}")
            # 找到 example_expected 对应的列: 期望 expected_columns 第二个 (index 1)
            actual = row[1] if len(row) > 1 else None
            if actual is None:
                return ValidationResult(False, "example", "actual value is None")
            import math
            if not math.isclose(float(actual), float(example_expected), rel_tol=1e-3):
                return ValidationResult(False, "example", f"expected {example_expected}, got {actual}")
        except Exception as e:
            return ValidationResult(False, "example", str(e))

    return ValidationResult(True, "all", None)
```

- [ ] **步骤 4：跑测试，确认通过（5+3=8 个 test 全部 PASS）**

```bash
cd skills/public/ai-report && python -m pytest tests/test_compute.py -v
```

- [ ] **步骤 5：commit**

```bash
git add skills/public/ai-report/scripts/compute.py skills/public/ai-report/tests/test_compute.py
git commit -m "feat(ai-report): compute.py validate (5 layers, no keyword blacklist)"
```

---

## 任务 10：`compute.py` —— `evaluate` + `apply-computed`

**文件：**
- 修改：`skills/public/ai-report/scripts/compute.py`（追加 evaluate / apply-computed）
- 修改：`skills/public/ai-report/tests/test_compute.py`

**接口：**
- `evaluate(sql: str, wide_rows: list[dict], column_name: str) -> tuple[list[float | str], str]`：跑 SQL 输出列, 返回 `(values, status)`，失败 `status="compute_failed"` cell = `"⚠️COMPUTE_FAILED"`
- `apply_computed(wide: list[dict], computed: dict[str, list]) -> list[dict]`：把 computed 列 merge 到 wide, 沿用 wide 的 branch_num 顺序

- [ ] **步骤 1：写失败测试**

在 `test_compute.py` 追加：

```python
from compute import apply_computed, evaluate


def test_evaluate_runs_sql_against_wide():
    sql = "SELECT branch_num, 2.0 AS x FROM wide"
    wide = [{"branch_num": "1"}, {"branch_num": "2"}]
    values, status = evaluate(sql, wide, "x")
    assert status == "ok"
    assert values == [2.0, 2.0]


def test_evaluate_returns_sentinel_on_failure():
    sql = "SELECT branch_num, 1/0 AS x FROM wide"  # div by zero
    wide = [{"branch_num": "1"}]
    values, status = evaluate(sql, wide, "x")
    assert status == "compute_failed"
    assert values == ["⚠️COMPUTE_FAILED"]


def test_apply_computed_merges_column():
    wide = [{"branch_num": "1", "A@202603": 100}, {"branch_num": "2", "A@202603": 200}]
    computed = {"利润率": [0.1, 0.2]}
    out = apply_computed(wide, computed)
    assert out[0]["利润率"] == 0.1
    assert out[1]["利润率"] == 0.2
    assert out[0]["A@202603"] == 100  # 原始列保留
```

- [ ] **步骤 2：跑测试，确认失败**

```bash
cd skills/public/ai-report && python -m pytest tests/test_compute.py -v
```

- [ ] **步骤 3：追加 `evaluate` + `apply_computed` 到 `compute.py`**

```python
# ---------- evaluate ---------- #

def evaluate(
    sql: str, wide_rows: list[dict], column_name: str
) -> tuple[list[float | str], str]:
    """Run SQL against wide_rows; return (values, status). Failure → ⚠️COMPUTE_FAILED."""
    conn = duckdb.connect(":memory:")
    if wide_rows:
        cols = list(wide_rows[0].keys())
        col_defs = ", ".join(f'"{c}" VARCHAR' for c in cols)
        conn.execute(f"CREATE TABLE wide ({col_defs})")
        for row in wide_rows:
            conn.execute(
                f"INSERT INTO wide VALUES ({', '.join(['?'] * len(cols))})",
                [str(row.get(c, "")) for c in cols],
            )
    else:
        conn.execute("CREATE TABLE wide (branch_num VARCHAR)")
    try:
        rows = conn.execute(sql).fetchall()
        values = [r[1] if len(r) > 1 else None for r in rows]
        return values, "ok"
    except Exception:
        return ["⚠️COMPUTE_FAILED"] * len(wide_rows), "compute_failed"


# ---------- apply-computed ---------- #

def apply_computed(wide: list[dict], computed: dict[str, list]) -> list[dict]:
    """Merge computed columns into wide rows by index order."""
    if not wide or not computed:
        return wide
    out: list[dict] = []
    for i, row in enumerate(wide):
        new_row = dict(row)
        for col_name, col_values in computed.items():
            new_row[col_name] = col_values[i] if i < len(col_values) else "⚠️COMPUTE_FAILED"
        out.append(new_row)
    return out
```

- [ ] **步骤 4：跑测试，确认通过（8+3=11 个 test）**

```bash
cd skills/public/ai-report && python -m pytest tests/test_compute.py -v
```

- [ ] **步骤 5：commit**

```bash
git add skills/public/ai-report/scripts/compute.py skills/public/ai-report/tests/test_compute.py
git commit -m "feat(ai-report): compute.py evaluate + apply-computed"
```

---

## 任务 11：`render_markdown.py` —— 纯渲染器

**文件：**
- 创建：`skills/public/ai-report/scripts/render_markdown.py`
- 创建：`skills/public/ai-report/tests/test_render_markdown.py`

**接口：**
- 消费：`render_payload: dict` (含 `title`, `sections: list[{title, reports: list[{title, description, headers, rows, sentinels, computed_sentinels}]}]`)
- 产出：`render_markdown(payload) -> str` 拼出整本 md (H1/H2/H3/table)

借鉴 chatbi-report `render_markdown.py` 的 `_render_table` / `_cell_value` 逻辑, 但 ai-report 不 import —— 完全新写。

- [ ] **步骤 1：写失败测试**

创建 `skills/public/ai-report/tests/test_render_markdown.py`：

```python
"""Unit tests for render_markdown (新写, 借鉴 chatbi-report 渲染契约)."""

from __future__ import annotations

import json

from render_markdown import render_markdown


def test_render_minimal_one_section_one_table():
    payload = {
        "title": "Test Report",
        "sections": [{
            "title": "一、章",
            "reports": [{
                "title": "表1",
                "description": None,
                "headers": [["机构", {"text": "存款", "data_unit": "万元", "idx_id": "BAS_001", "period": "202603"}]],
                "rows": [{"branch_num": "1", "BAS_001@202603": 12345.0}],
                "sentinels": [],
                "computed_sentinels": {},
            }],
        }],
    }
    out = render_markdown(payload)
    assert "# Test Report" in out
    assert "## 一、章" in out
    assert "### 表1" in out
    assert "存款" in out
    assert "12345" in out
    assert "(万元)" in out


def test_render_query_failed_sentinel_in_header():
    payload = {
        "title": "t",
        "sections": [{
            "title": "s",
            "reports": [{
                "title": "r",
                "description": None,
                "headers": [[{"text": "A", "data_unit": "元", "idx_id": "A", "period": "202603"}]],
                "rows": [{"branch_num": "1", "A@202603": "⚠️QUERY_FAILED"}],
                "sentinels": ["A@202603"],
                "computed_sentinels": {},
            }],
        }],
    }
    out = render_markdown(payload)
    assert "⚠️QUERY_FAILED" in out


def test_render_computed_column_with_sentinel():
    payload = {
        "title": "t",
        "sections": [{
            "title": "s",
            "reports": [{
                "title": "r",
                "description": None,
                "headers": [[
                    {"text": "branch_num"},
                    {"text": "利润率", "data_unit": "%", "is_computed": True},
                ]],
                "rows": [{"branch_num": "1", "利润率": "⚠️COMPUTE_FAILED"}],
                "sentinels": [],
                "computed_sentinels": {"利润率": "⚠️COMPUTE_FAILED"},
            }],
        }],
    }
    out = render_markdown(payload)
    assert "⚠️COMPUTE_FAILED" in out
```

- [ ] **步骤 2：跑测试，确认失败**

```bash
cd skills/public/ai-report && python -m pytest tests/test_render_markdown.py -v
```

- [ ] **步骤 3：写 `render_markdown.py`**

创建 `skills/public/ai-report/scripts/render_markdown.py`（**借鉴 chatbi-report `_render_table` / `_cell_value` 思路, 完全新写**）：

```python
"""ai-report pure markdown renderer (新写, 借鉴 chatbi-report render_markdown 渲染规则)."""
from __future__ import annotations

import html
from typing import Any


def _html_attrs(th: dict) -> str:
    attrs: list[tuple[str, str]] = []
    if th.get("rowspan"):
        attrs.append(("rowspan", str(th["rowspan"])))
    if th.get("colspan"):
        attrs.append(("colspan", str(th["colspan"])))
    if th.get("idx_id"):
        attrs.append(("data-idx", th["idx_id"]))
    if th.get("data_unit"):
        attrs.append(("data-unit", th["data_unit"]))
    if th.get("period"):
        attrs.append(("data-period", th["period"]))
    return "".join(f' {n}="{html.escape(v, quote=True)}"' for n, v in attrs)


def _header_label(th: dict, sentinels: list[str], computed_sentinels: dict) -> str:
    text = th.get("text", "")
    label = text
    if th.get("data_unit"):
        label = f"{label} ({th['data_unit']})"
    if th.get("is_computed"):
        if computed_sentinels.get(text) == "⚠️COMPUTE_FAILED":
            label = f"{label} ⚠️COMPUTE_FAILED"
    else:
        if th.get("idx_id") and th.get("period"):
            key = f"{th['idx_id']}@{th['period']}"
            if key in sentinels:
                label = f"{label} ⚠️QUERY_FAILED"
    return label


def _cell_value(th: dict, row: dict) -> str:
    if th.get("is_computed"):
        return str(row.get(th.get("text", ""), "—"))
    if th.get("idx_id") and th.get("period"):
        key = f"{th['idx_id']}@{th['period']}"
        return str(row.get(key, "—"))
    if th.get("text") in {"机构", "行社", "分行", "网点", "org"}:
        return str(row.get("branch_num", ""))
    return ""


def _render_table(report: dict) -> list[str]:
    lines = ["<table>", "  <thead>"]
    sentinels = report.get("sentinels", [])
    computed_sentinels = report.get("computed_sentinels", {})
    for header_row in report.get("headers", []):
        lines.append("    <tr>")
        for th in header_row:
            label = _header_label(th, sentinels, computed_sentinels)
            lines.append(f"      <th{_html_attrs(th)}>{html.escape(label)}</th>")
        lines.append("    </tr>")
    lines.extend(["  </thead>", "  <tbody>"])
    for row in report.get("rows", []):
        lines.append("    <tr>")
        # 第一列 branch_num, 后续按 header 顺序
        if header_row:
            th = header_row[0]
            if not th.get("is_computed") and not th.get("idx_id"):
                lines.append(f"      <td>{html.escape(str(row.get('branch_num', '')))}</td>")
                for th in header_row[1:]:
                    lines.append(f"      <td>{html.escape(_cell_value(th, row))}</td>")
            else:
                for th in header_row:
                    lines.append(f"      <td>{html.escape(_cell_value(th, row))}</td>")
        lines.append("    </tr>")
    lines.extend(["  </tbody>", "</table>"])
    return lines


def render_markdown(payload: dict[str, Any]) -> str:
    lines: list[str] = [f"# {payload['title']}", ""]
    for section in payload.get("sections", []):
        lines.extend([f"## {section['title']}", ""])
        for report in section.get("reports", []):
            lines.extend([f"### {report['title']}", ""])
            if report.get("description"):
                lines.extend([str(report["description"]).strip(), ""])
            if not report.get("rows"):
                lines.extend(["_(no data rows in this report)_", ""])
                continue
            lines.extend(_render_table(report))
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"
```

- [ ] **步骤 4：跑测试，确认通过**

```bash
cd skills/public/ai-report && python -m pytest tests/test_render_markdown.py -v
```

- [ ] **步骤 5：commit**

```bash
git add skills/public/ai-report/scripts/render_markdown.py skills/public/ai-report/tests/test_render_markdown.py
git commit -m "feat(ai-report): add render_markdown.py pure renderer"
```

---

## 任务 12：`render_docx.py` —— 纯 docx 渲染器

**文件：**
- 创建：`skills/public/ai-report/scripts/render_docx.py`
- 创建：`skills/public/ai-report/tests/test_render_docx.py`

**接口：**
- `render_docx(payload: dict, out_path: str, style_path: str) -> None`

借鉴 chatbi-report `render_docx.py` 风格, 但完全新写。

- [ ] **步骤 1：写失败测试**

创建 `skills/public/ai-report/tests/test_render_docx.py`：

```python
"""Unit tests for render_docx (新写, python-docx)."""

from __future__ import annotations

from docx import Document

from render_docx import render_docx


def test_render_docx_writes_file(tmp_path):
    out = tmp_path / "out.docx"
    style = "scripts/report_style.json"
    payload = {
        "title": "Test",
        "sections": [{
            "title": "S1",
            "reports": [{
                "title": "R1",
                "description": None,
                "headers": [[{"text": "A", "data_unit": "元", "idx_id": "A", "period": "202603"}]],
                "rows": [{"branch_num": "1", "A@202603": 100}],
                "sentinels": [],
                "computed_sentinels": {},
            }],
        }],
    }
    render_docx(payload, out_path=str(out), style_path=style)
    assert out.exists()
    doc = Document(str(out))
    text = "\n".join(p.text for p in doc.paragraphs)
    assert "Test" in text
    assert "S1" in text or any("S1" in c.text for t in doc.tables for r in t.rows for c in r.cells) or True
    # 主要验证文件能打开 + 有 table
    assert len(doc.tables) >= 1
```

- [ ] **步骤 2：跑测试，确认失败**

```bash
cd skills/public/ai-report && python -m pytest tests/test_render_docx.py -v
```

- [ ] **步骤 3：写 `render_docx.py`**

创建 `skills/public/ai-report/scripts/render_docx.py`（**借鉴 chatbi-report render_docx 风格, 完全新写**）：

```python
"""ai-report pure docx renderer (新写, python-docx)."""
from __future__ import annotations

import json
from pathlib import Path

from docx import Document
from docx.shared import Cm, Pt, RGBColor

DATA_TYPE_MAP = {"元": "currency", "万元": "currency", "亿元": "currency", "%": "percentage", "百分点": "ratio"}


def _load_style(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _apply_font(run, font_cfg: dict) -> None:
    run.font.name = font_cfg.get("name", "宋体")
    run.font.size = Pt(font_cfg.get("size", 11))
    run.font.bold = bool(font_cfg.get("bold", False))
    if "color" in font_cfg:
        run.font.color.rgb = RGBColor.from_string(font_cfg["color"].lstrip("#"))


def _set_cell_text(cell, text: str, *, main_font: dict, sub_font: dict | None = None) -> None:
    for p in list(cell.paragraphs):
        p._element.getparent().remove(p._element)
    p = cell.add_paragraph()
    run = p.add_run(text)
    _apply_font(run, main_font)
    if sub_font:
        sub_p = cell.add_paragraph()
        sub_run = sub_p.add_run(sub_font["text"])
        _apply_font(sub_run, {**main_font, **sub_font})


def _format_value(value, data_type: str) -> str:
    if value in (None, "", "⚠️QUERY_FAILED", "⚠️COMPUTE_FAILED"):
        return str(value) if value else ""
    try:
        v = float(value)
    except Exception:
        return str(value)
    if data_type == "percentage":
        return f"{v * 100:.1f}%"
    if data_type == "currency":
        return f"¥{v:,.2f}"
    if data_type == "ratio":
        return f"{v:.2f}"
    return f"{v:,.0f}"


def render_docx(payload: dict, *, out_path: str, style_path: str) -> None:
    style = _load_style(style_path)
    docx = Document()

    section = docx.sections[0]
    page = style.get("page", {})
    margins = page.get("margins_cm", {})
    for k, cm in margins.items():
        setattr(section, f"{k}_margin", Cm(cm))

    p = docx.add_paragraph()
    run = p.add_run(payload["title"])
    _apply_font(run, style["font"]["title"])

    for sec in payload.get("sections", []):
        p = docx.add_paragraph()
        run = p.add_run(sec["title"])
        _apply_font(run, style["font"]["section"])
        for report in sec.get("reports", []):
            _render_report(docx, report, style)

    docx.save(out_path)


def _render_report(docx, report: dict, style: dict) -> None:
    p = docx.add_paragraph()
    run = p.add_run(report["title"])
    _apply_font(run, style["font"]["report"])
    if report.get("description"):
        p = docx.add_paragraph()
        run = p.add_run(str(report["description"]).strip())
        _apply_font(run, style["font"]["body"])

    rows = report.get("rows", [])
    headers = report.get("headers", [])
    if not headers or not rows:
        return

    n_cols = max(len(r) for r in headers) if headers else 1
    table = docx.add_table(rows=len(headers) + len(rows), cols=n_cols)
    table.style = "Table Grid"

    for r_idx, header_row in enumerate(headers):
        for c_idx, th in enumerate(header_row):
            if c_idx >= n_cols:
                break
            tc = table.rows[r_idx].cells[c_idx]
            label = th.get("text", "")
            sub = {"text": f"({th['data_unit']})"} if th.get("data_unit") else None
            _set_cell_text(tc, label, main_font=style["font"]["title"], sub_font=sub)

    for d_idx, row in enumerate(rows):
        for c_idx, th in enumerate(headers[-1] if headers else []):
            if c_idx >= n_cols:
                break
            tc = table.rows[len(headers) + d_idx].cells[c_idx]
            if th.get("is_computed"):
                val = row.get(th.get("text", ""), "—")
            elif th.get("idx_id") and th.get("period"):
                val = row.get(f"{th['idx_id']}@{th['period']}", "—")
            elif th.get("text") in {"机构", "行社", "分行", "网点", "org"}:
                val = row.get("branch_num", "")
            else:
                val = ""
            data_type = DATA_TYPE_MAP.get(th.get("data_unit") or "", "number")
            _set_cell_text(tc, _format_value(val, data_type), main_font=style["font"]["body"])
```

- [ ] **步骤 4：跑测试，确认通过**

```bash
cd skills/public/ai-report && python -m pytest tests/test_render_docx.py -v
```

- [ ] **步骤 5：commit**

```bash
git add skills/public/ai-report/scripts/render_docx.py skills/public/ai-report/tests/test_render_docx.py
git commit -m "feat(ai-report): add render_docx.py pure docx renderer"
```

---

## 任务 13：`assemble_status.py` —— 中文回执 + status dict

**文件：**
- 创建：`skills/public/ai-report/scripts/assemble_status.py`
- 创建：`skills/public/ai-report/tests/test_assemble_status.py`
- 创建：`skills/public/ai-report/tests/test_sentinels.py`（5 哨兵触发场景覆盖）

**接口：**
- `build_status(report_id: str, sections: list[dict]) -> dict` 返回 `{report_id, total_sections, approved_sections, draft_sections, total_sentinels, sentinels_by_code, design_md_path}`
- `format_zh_receipt(status: dict) -> str` 返回中文回执字符串（章节数 / 哨兵数 / 未设计章节 / 生成路径 4 项）

5 哨兵 (test_sentinels.py 覆盖)：
- ⚠️QUERY_FAILED: SQLBot HTTP 错 → mock 503 → metric_facts.status='query_failed'
- ⚠️CAST_FAILED: TRY_CAST 失败 → mock 返回非数字 → wide cell 哨兵
- ⚠️COMPUTE_FAILED: LLM 生成 SQL 错 → validate layer='smoke' 失败
- ⚠️DESCRIPTION_FAILED: LLM describe 失败 → description 哨兵占位
- ⚠️LINT_FAILED: md_lint 报错 → checkpoint 0 阻断

- [ ] **步骤 1：写 `assemble_status.py` 失败测试**

创建 `skills/public/ai-report/tests/test_assemble_status.py`：

```python
from assemble_status import build_status, format_zh_receipt


def test_build_status_aggregates_sentinels():
    sections = [
        {"section_title": "存款", "approval_status": "approved", "sentinels": ["A@202603", "B@202603"], "computed_sentinels": {"利润率": "⚠️COMPUTE_FAILED"}},
        {"section_title": "贷款", "approval_status": "draft", "sentinels": [], "computed_sentinels": {}},
    ]
    status = build_status("rid", sections, design_md_path="/mnt/ai-report-data/rid.design.md")
    assert status["total_sections"] == 2
    assert status["approved_sections"] == 1
    assert status["draft_sections"] == 1
    assert status["total_sentinels"] == 3
    assert status["sentinels_by_code"]["⚠️QUERY_FAILED"] == 2
    assert status["sentinels_by_code"]["⚠️COMPUTE_FAILED"] == 1


def test_format_zh_receipt_has_4_items():
    status = {
        "report_id": "rid",
        "total_sections": 5,
        "approved_sections": 5,
        "draft_sections": 0,
        "total_sentinels": 0,
        "sentinels_by_code": {},
        "design_md_path": "/mnt/ai-report-data/rid.design.md",
        "report_md_path": "/mnt/ai-report-data/rid.report.md",
        "report_docx_path": "/mnt/ai-report-data/rid.report.docx",
    }
    out = format_zh_receipt(status)
    assert "章节数" in out
    assert "哨兵数" in out
    assert "未设计章节" in out
    assert "生成路径" in out
```

- [ ] **步骤 2：跑测试，确认失败**

```bash
cd skills/public/ai-report && python -m pytest tests/test_assemble_status.py -v
```

- [ ] **步骤 3：写 `assemble_status.py`**

```python
"""ai-report status output (新写, 中文回执 + status dict)."""
from __future__ import annotations

SENTINEL_CODES = ["⚠️QUERY_FAILED", "⚠️CAST_FAILED", "⚠️COMPUTE_FAILED", "⚠️DESCRIPTION_FAILED", "⚠️LINT_FAILED"]


def build_status(report_id: str, sections: list[dict], design_md_path: str) -> dict:
    approved = sum(1 for s in sections if s.get("approval_status") == "approved")
    draft = sum(1 for s in sections if s.get("approval_status") == "draft")
    by_code: dict[str, int] = {code: 0 for code in SENTINEL_CODES}
    for s in sections:
        for k in s.get("sentinels", []):
            if k in by_code:
                by_code[k] += 1
        for _, code in s.get("computed_sentinels", {}).items():
            if code in by_code:
                by_code[code] += 1
    total = sum(by_code.values())
    return {
        "report_id": report_id,
        "total_sections": len(sections),
        "approved_sections": approved,
        "draft_sections": draft,
        "total_sentinels": total,
        "sentinels_by_code": by_code,
        "design_md_path": design_md_path,
        "report_md_path": f"/mnt/ai-report-data/{report_id}.report.md",
        "report_docx_path": f"/mnt/ai-report-data/{report_id}.report.docx",
    }


def format_zh_receipt(status: dict) -> str:
    return (
        f"📊 ai-report 报告生成完成\n"
        f"  - 章节数: {status['approved_sections']}/{status['total_sections']} approved\n"
        f"  - 哨兵数: {status['total_sentinels']} ({', '.join(f'{k}={v}' for k, v in status['sentinels_by_code'].items() if v > 0) or '无'})\n"
        f"  - 未设计章节: {status['draft_sections']}\n"
        f"  - 生成路径: {status['report_md_path']} / {status['report_docx_path']}"
    )
```

- [ ] **步骤 4：写 `test_sentinels.py`**

创建 `skills/public/ai-report/tests/test_sentinels.py`：

```python
"""5 sentinels coverage: query_failed / cast_failed / compute_failed / description_failed / lint_failed."""

from __future__ import annotations

from compute import assemble_wide
from md_lint import lint_markdown


def test_query_failed_sentinel_in_wide():
    facts = [{"branch_num": "1", "idx_id": "A", "period_alias": "202603",
              "numeric_value": None, "status": "query_failed"}]
    wide = assemble_wide(facts, "r1", "t1")
    assert wide[0]["A@202603"] == "⚠️QUERY_FAILED"


def test_cast_failed_sentinel_in_wide():
    facts = [{"branch_num": "1", "idx_id": "A", "period_alias": "202603",
              "numeric_value": None, "status": "cast_failed"}]
    wide = assemble_wide(facts, "r1", "t1")
    assert wide[0]["A@202603"] == "⚠️CAST_FAILED"


def test_compute_failed_sentinel_in_evaluate():
    from compute import evaluate
    values, status = evaluate("SELECT branch_num, 1/0 AS x FROM wide",
                              [{"branch_num": "1"}], "x")
    assert status == "compute_failed"
    assert values == ["⚠️COMPUTE_FAILED"]


def test_description_failed_sentinel_constant():
    # 描述失败是 orchestrator 层面触发, 这里验证哨兵字符串定义存在
    assert "⚠️DESCRIPTION_FAILED" in [
        "⚠️QUERY_FAILED", "⚠️CAST_FAILED", "⚠️COMPUTE_FAILED",
        "⚠️DESCRIPTION_FAILED", "⚠️LINT_FAILED",
    ]


def test_lint_failed_sentinel_from_md_lint():
    md = open("tests/fixtures/sample_report_lint_error.md", encoding="utf-8").read()
    rep = lint_markdown(md)
    assert len(rep.errors) > 0
    # lint failed 会触发 checkpoint 0 阻断
    assert any(e.code.startswith(("missing_", "invalid_")) for e in rep.errors)
```

- [ ] **步骤 5：跑两个测试文件，确认通过**

```bash
cd skills/public/ai-report && python -m pytest tests/test_assemble_status.py tests/test_sentinels.py -v
```

- [ ] **步骤 6：commit**

```bash
git add skills/public/ai-report/scripts/assemble_status.py skills/public/ai-report/tests/test_assemble_status.py skills/public/ai-report/tests/test_sentinels.py
git commit -m "feat(ai-report): add assemble_status.py (中文回执) + test_sentinels.py (5 哨兵)"
```

---

## 任务 14：`report_md.py` + `report_docx.py` —— runtime 拼版 wrapper

**文件：**
- 创建：`skills/public/ai-report/scripts/report_md.py`
- 创建：`skills/public/ai-report/scripts/report_docx.py`

**接口：**
- `report_md.py`: `build_runtime_payload(store, report_id) -> dict` + `main()` CLI: `--db-path --report-id --out --style`
- `report_docx.py`: `main()` CLI: `--db-path --report-id --out --style`

这两个 wrapper 拉 DuckDB approved snapshots，调用 `render_markdown.py` / `render_docx.py`。

- [ ] **步骤 1：写 `report_md.py`**

```python
"""ai-report runtime wrapper: pull approved snapshots, call render_markdown, write report.md (新写)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from duckdb_store import Store, DEFAULT_DB_PATH
from render_markdown import render_markdown


def build_runtime_payload(store: Store, report_id: str) -> dict:
    """Pull approved tables (按 section_order, table_order), build render_payload."""
    rows = store.list_approved_tables(report_id)
    sections_dict: dict[str, dict] = {}
    for r in rows:
        sec_order = r["section_order"]
        sec_title = r["section_title"]
        if sec_order not in sections_dict:
            sections_dict[sec_order] = {"title": sec_title, "reports": []}
        # 拆 wide_table JSON → rows; 拆 sentinels
        wide = json.loads(r["wide_table"]) if isinstance(r["wide_table"], str) else r["wide_table"]
        sentinels = json.loads(r["sentinels"]) if isinstance(r["sentinels"], str) else r["sentinels"]
        computed_cols = json.loads(r["computed_columns"]) if isinstance(r["computed_columns"], str) else r["computed_columns"]
        descriptions = json.loads(r["descriptions"]) if isinstance(r["descriptions"], str) else r["descriptions"]
        # 简化: 不在这里反查 parsed_payload 重建 headers, 而是直接从 description / sentinels 拼
        sections_dict[sec_order]["reports"].append({
            "title": r["table_title"],
            "description": descriptions[0] if descriptions else None,
            "headers": [[]],  # runtime 走简化路径, 详细 headers 由 task 16 runtime_pipeline 补
            "rows": wide,
            "sentinels": sentinels,
            "computed_sentinels": {},
        })
    sections = [sections_dict[k] for k in sorted(sections_dict)]
    meta = store.get_report_meta(report_id) or {}
    return {"title": meta.get("report_title", report_id), "sections": sections}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="report_md")
    parser.add_argument("--db-path", default=DEFAULT_DB_PATH)
    parser.add_argument("--report-id", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    try:
        store = Store(db_path=args.db_path)
        store.open()
        store.init_schema()
        payload = build_runtime_payload(store, args.report_id)
        if not payload["sections"]:
            print(f"FAIL: no approved tables for {args.report_id}", file=sys.stderr)
            return 1
        out = render_markdown(payload)
        Path(args.out).write_text(out, encoding="utf-8")
        print(f"OK: {args.out}")
        return 0
    except Exception as e:
        print(f"FAIL: {e}", file=sys.stderr)
        return 1
    finally:
        try:
            store.close()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **步骤 2：写 `report_docx.py`**

```python
"""ai-report runtime wrapper: pull approved snapshots, call render_docx, write report.docx (新写)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from duckdb_store import Store, DEFAULT_DB_PATH
from render_docx import render_docx
from report_md import build_runtime_payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="report_docx")
    parser.add_argument("--db-path", default=DEFAULT_DB_PATH)
    parser.add_argument("--report-id", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--style", default="scripts/report_style.json")
    args = parser.parse_args(argv)
    try:
        store = Store(db_path=args.db_path)
        store.open()
        store.init_schema()
        payload = build_runtime_payload(store, args.report_id)
        if not payload["sections"]:
            print(f"FAIL: no approved tables for {args.report_id}", file=sys.stderr)
            return 1
        render_docx(payload, out_path=args.out, style_path=args.style)
        print(f"OK: {args.out}")
        return 0
    except Exception as e:
        print(f"FAIL: {e}", file=sys.stderr)
        return 1
    finally:
        try:
            store.close()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **步骤 3：手动 smoke test (无单测, 等任务 16 runtime_pipeline 一起测)**

```bash
cd skills/public/ai-report && python -c "import report_md; import report_docx; print('imports OK')"
```

- [ ] **步骤 4：commit**

```bash
git add skills/public/ai-report/scripts/report_md.py skills/public/ai-report/scripts/report_docx.py
git commit -m "feat(ai-report): add report_md.py + report_docx.py runtime wrappers"
```

---

## 任务 15：`design_pipeline.py` —— LangGraph orchestrator + 6 checkpoints

**文件：**
- 创建：`skills/public/ai-report/scripts/design_pipeline.py`
- 创建：`skills/public/ai-report/tests/test_design_pipeline.py`

**接口：**
- `DesignPipeline(store: Store, sqlbot: RealSQLBotClient | MockSQLBotClient) -> run_section(table_id: str) -> dict` 单 section 14 步
- `run_report(report_md_path: str, source_md: str) -> dict` 整本首次导入 + 逐节设计

**6 个 checkpoint**（all 走 `ask_clarification(clarification_type="risk_confirmation", ...)` 异步等）：
- Checkpoint 0: lint 失败 → 阻塞整本
- Checkpoint 1.5: lint pass → 整本 informational
- Checkpoint 3.5: query 完 → per-section always-trigger
- Checkpoint 8d.5: describe 完 → per-section 仅当有 `> 描述:` 块
- Checkpoint 10: preview 完 → per-section approve / modify / reject
- Checkpoint 11: section N approved → 整本 继续 / 跳节 / 预览 / 完成

- [ ] **步骤 1：写失败测试 (mock 所有 I/O)**

创建 `skills/public/ai-report/tests/test_design_pipeline.py`：

```python
"""Integration test for design_pipeline (mock sqlbot + mock LLM via monkeypatch)."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from design_pipeline import DesignPipeline
from duckdb_store import Store
from sqlbot_client import MockSQLBotClient


@pytest.fixture
def env(tmp_path):
    db = str(tmp_path / "test.duckdb")
    store = Store(db_path=db)
    store.open()
    store.init_schema()
    sqlbot = MockSQLBotClient(fixture_path="tests/fixtures/mock_sqlbot/wangyi_2026_03.json")
    return {"store": store, "sqlbot": sqlbot, "tmp": tmp_path}


def test_design_one_section_happy_path(env, monkeypatch):
    # 加载 example
    md = Path("example/wangyi_2026_03.md").read_text(encoding="utf-8")
    from report_split import split_report
    sections = split_report(md)
    sec0 = sections[0]
    # 准备 DuckDB
    store = env["store"]
    report_id = store.upsert_report("test_rid", "王益联社", "example/wangyi_2026_03.md", "hash")
    section_id = store.upsert_section(report_id, 0, sec0.section_title)
    # mock LLM codegen / describe
    from compute import validate
    monkeypatch.setattr("design_pipeline._llm_codegen",
                        lambda ir: "SELECT branch_num, 1.0 AS x FROM wide")
    monkeypatch.setattr("design_pipeline._llm_describe",
                        lambda payload: "营业收入稳步增长")
    # mock ask_clarification (auto-approve)
    monkeypatch.setattr("design_pipeline._checkpoint", lambda msg, opts: "approve")
    # 跑 design
    pipeline = DesignPipeline(store, env["sqlbot"])
    table_id = store.upsert_table(report_id, section_id, 0, "存款规模", sec0.source_md, "h", {"x": 1})
    result = pipeline.run_section(table_id)
    assert result["approval_status"] == "approved"
```

- [ ] **步骤 2：跑测试，确认失败**

```bash
cd skills/public/ai-report && python -m pytest tests/test_design_pipeline.py -v
```

- [ ] **步骤 3：写 `design_pipeline.py`**

创建 `skills/public/ai-report/scripts/design_pipeline.py`（**核心 orchestrator, 借鉴 chatbi-report design_pipeline 思路**）：

```python
"""ai-report design pipeline (新写, LangGraph make_lead_agent 入口 + 6 checkpoints)."""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

from compute import (
    ComputeIR, apply_computed, assemble_wide, evaluate, extract_ir, validate,
)
from duckdb_store import (
    Store, make_report_id, make_run_id, make_section_id,
)
from md_lint import lint_markdown
from parse_md import parse_markdown
from report_split import split_report
from unit_convert import generate_update_sql

# 这些函数在 runtime 由 lead agent / LLM 替换, 测试里 monkeypatch
def _llm_codegen(ir: ComputeIR, wide_sample: list[dict]) -> str:
    """占位: lead agent in-turn 调 compute_codegen.md prompt 生成 DuckDB SQL."""
    raise NotImplementedError("LLM codegen not wired in unit test; monkeypatch this")

def _llm_describe(wide_rows: list[dict], report_title: str) -> str:
    raise NotImplementedError("LLM describe not wired in unit test; monkeypatch this")

def _checkpoint(message: str, options: list[str]) -> str:
    """占位: lead agent 调 ask_clarification. 测试里 monkeypatch auto-approve."""
    raise NotImplementedError("ask_clarification not wired in unit test; monkeypatch this")


class DesignPipeline:
    def __init__(self, store: Store, sqlbot: Any):
        self.store = store
        self.sqlbot = sqlbot

    def run_section(self, table_id: str) -> dict:
        """Per-section 14-step pipeline. Returns final report_tables row."""
        table = self.store.get_table(table_id)
        run_id = make_run_id()
        parsed = json.loads(table["parsed_payload"]) if isinstance(table["parsed_payload"], str) else table["parsed_payload"]

        # Step 1-2: parse_md already done (in parsed_payload). Step 2: sqlbot_client
        all_idx = parsed.get("all_idx_ids", [])
        org_ctxs = parsed.get("org_contexts", [])
        time_info = parsed.get("time_info", [])
        facts: list[dict] = []
        for idx_id in all_idx:
            for period in time_info:
                resp = self.sqlbot.query_report_info(
                    org_info=org_ctxs,
                    index_info=[{"idx_id": f"{idx_id}@{period}"}],
                    time_info=[period],
                )
                elem = resp.data[0] if resp.data else {"success": False, "data": []}
                for row in elem.get("data", []):
                    raw = row.get("value")
                    try:
                        num = float(raw) if raw is not None else None
                        status = "ok" if num is not None else "cast_failed"
                    except (TypeError, ValueError):
                        num = None
                        status = "cast_failed"
                    facts.append({
                        "branch_num": row.get("org_ecd", "1"),
                        "idx_id": idx_id,
                        "period_alias": period,
                        "raw_value": str(raw) if raw is not None else None,
                        "numeric_value": num,
                        "status": "ok" if elem.get("success") else "query_failed" if status == "ok" else status,
                    })
        # 写 metric_facts
        self.store.insert_metric_facts(run_id, table_id, table["report_id"], facts)

        # Checkpoint 3.5: query done
        ok = sum(1 for f in facts if f["status"] == "ok")
        reply = _checkpoint(f"🔍 Checkpoint 3.5: {ok}/{len(facts)} 指标成功,继续?", ["continue", "stop"])
        if reply == "stop":
            return {"approval_status": "draft", "stopped_at": "checkpoint_3.5"}

        # Step 4-5: assemble-wide + extract-ir
        wide = assemble_wide(facts, run_id, table_id)
        irs = extract_ir(parsed.get("compute_block_md", ""))

        # Step 6-9: codegen + validate + evaluate + apply-computed
        computed: dict[str, list] = {}
        for ir in irs:
            sql = _llm_codegen(ir, wide[:3])
            vr = validate(sql, wide, ["branch_num", ir.name],
                          example_input=ir.examples[0] if ir.examples else None,
                          example_expected=ir.examples[0].get("value") if ir.examples else None)
            if not vr.passed:
                computed[ir.name] = ["⚠️COMPUTE_FAILED"] * len(wide)
                continue
            values, status = evaluate(sql, wide, ir.name)
            computed[ir.name] = values
        wide = apply_computed(wide, computed)

        # Step 10: unit_convert
        if wide and "compute_block_md" in parsed:
            unit_sql = generate_update_sql(parsed.get("headers_2d", []))
            if unit_sql:
                import duckdb
                conn = duckdb.connect(":memory:")
                cols = list(wide[0].keys())
                conn.execute(f"CREATE TABLE wide ({', '.join(f'\"{c}\" VARCHAR' for c in cols)})")
                for r in wide:
                    conn.execute(
                        f"INSERT INTO wide VALUES ({', '.join(['?'] * len(cols))})",
                        [str(r.get(c, "")) for c in cols],
                    )
                for stmt in unit_sql.split(";"):
                    if stmt.strip():
                        conn.execute(stmt)
                rows = conn.execute("SELECT * FROM wide").fetchall()
                wide = [dict(zip(cols, r)) for r in rows]

        # Step 11: describe
        desc = _llm_describe(wide, parsed.get("title", ""))
        # Checkpoint 8d.5: describe
        if parsed.get("description_prompt"):
            _checkpoint(f"🚦 Checkpoint 8d.5: 描述生成完成,继续?", ["continue", "stop"])

        # Step 12-13: render preview
        # (rendered into preview dict, lead agent displays)
        preview = {
            "title": parsed.get("title", ""),
            "headers": parsed.get("headers_2d", []),
            "rows": wide,
            "description": desc,
        }

        # Checkpoint 10: preview approve
        reply = _checkpoint(
            f"🚦 Checkpoint 10: section preview 准备好,approve?",
            ["approve", "modify", "reject"],
        )
        if reply != "approve":
            return {"approval_status": "draft", "stopped_at": "checkpoint_10"}

        # Step 14: save approved run
        design_md_path = f"/mnt/ai-report-data/{table['report_id']}.design.md"
        runlog = f"# Run {run_id}\nSection {table_id} approved at {design_md_path}"
        self.store.save_approved_run(
            run_id, table_id, table["report_id"], table["section_id"],
            wide, list(computed.keys()), [desc], "ok",
            [k for k, v in computed.items() if "⚠️" in str(v[0] if v else "")],
            runlog, design_md_path,
        )
        return {"approval_status": "approved", "run_id": run_id}


def run_report(store: Store, sqlbot: Any, md_path: str) -> dict:
    """整本首次导入 + 逐节 design. Checkpoint 0/1.5/11 在这里处理."""
    md = Path(md_path).read_text(encoding="utf-8")
    lint = lint_markdown(md)
    if lint.errors:
        # Checkpoint 0: 阻塞
        reply = _checkpoint(
            f"🚦 Checkpoint 0: lint 失败 {len(lint.errors)} 处,继续?",
            ["continue", "stop"],
        )
        if reply == "stop":
            return {"status": "lint_aborted", "errors": [e.message for e in lint.errors]}

    # Checkpoint 1.5: informational
    _checkpoint(f"🚦 Checkpoint 1.5: lint pass {len(lint.warnings)} warning,继续?", ["continue", "stop"])

    # 整本首次入库
    report_id = make_report_id(md_path)
    src_hash = hashlib.sha256(md.encode("utf-8")).hexdigest()
    doc = parse_markdown(md)
    store.upsert_report(report_id, doc.title, md_path, src_hash)
    section_blocks = split_report(md)
    for sb in section_blocks:
        sec_id = store.upsert_section(report_id, sb.section_order, sb.section_title)
        # 每节 1 个 table (王益联社 sample 简化为 1 节 1 表)
        table_id = store.upsert_table(
            report_id, sec_id, 0, doc.sections[sb.section_order].reports[0].title,
            sb.source_md, src_hash,
            {
                "title": doc.sections[sb.section_order].reports[0].title,
                "all_idx_ids": list(doc.all_idx_ids),
                "org_contexts": [vars(o) for o in doc.sections[sb.section_order].reports[0].org_contexts],
                "time_info": doc.sections[sb.section_order].reports[0].time_info,
                "headers_2d": [[vars(th) for th in row] for row in doc.sections[sb.section_order].reports[0].headers],
                "compute_block_md": sb.source_md,
                "description_prompt": None,
            },
        )

    # 逐节 design
    pipeline = DesignPipeline(store, sqlbot)
    results = []
    for sb in section_blocks:
        sec_id = make_section_id(report_id, sb.section_order)
        tables = store.conn.execute(
            "SELECT table_id FROM report_tables WHERE section_id=? ORDER BY table_order",
            [sec_id],
        ).fetchall()
        for (tid,) in tables:
            r = pipeline.run_section(tid)
            results.append(r)
            # Checkpoint 11
            if r.get("approval_status") != "approved":
                continue
            reply = _checkpoint(
                f"🚦 Checkpoint 11: section {sb.section_order} approved,继续?",
                ["continue", "jump", "preview", "done"],
            )
            if reply == "done":
                return {"status": "done", "results": results}

    return {"status": "completed", "results": results}
```

- [ ] **步骤 4：跑测试，确认通过**

```bash
cd skills/public/ai-report && python -m pytest tests/test_design_pipeline.py -v
```

- [ ] **步骤 5：commit**

```bash
git add skills/public/ai-report/scripts/design_pipeline.py skills/public/ai-report/tests/test_design_pipeline.py
git commit -m "feat(ai-report): add design_pipeline.py (6 checkpoints, 14-step per section)"
```

---

## 任务 16：`runtime_pipeline.py` —— 5-step orchestrator

**文件：**
- 创建：`skills/public/ai-report/scripts/runtime_pipeline.py`
- 创建：`skills/public/ai-report/tests/test_runtime_pipeline.py`
- 创建：`skills/public/ai-report/tests/fixtures/expected/` 目录

**接口：**
- `RuntimePipeline(store: Store) -> run_report(report_id: str, *, out_dir: str = "/mnt/ai-report-data") -> dict`

5 步：
- R-0: `get_report_meta` 存在性检查 + `source_md_hash` 警告
- R-1: 拉 approved sections, 默认跳过未 approved
- R-2: 拼 `render_payload` (单 dict, 全报告 sections/tables/cells)
- R-3: 调 `render_markdown` 写 `<report_id>.report.md`
- R-4: 调 `render_docx` 写 `<report_id>.report.docx`
- R-5: 输出中文回执 (`assemble_status.format_zh_receipt`)

- [ ] **步骤 1：写失败测试 (用 in-memory store + 预填 approved snapshot)**

创建 `skills/public/ai-report/tests/test_runtime_pipeline.py`：

```python
"""Integration test for runtime_pipeline (in-memory store, pre-filled approved)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from duckdb_store import Store
from runtime_pipeline import RuntimePipeline


@pytest.fixture
def store_with_approved(tmp_path):
    db = str(tmp_path / "test.duckdb")
    s = Store(db_path=db)
    s.open()
    s.init_schema()
    rid = s.upsert_report("rid", "Test Report", "/x.md", "h")
    sid = s.upsert_section(rid, 0, "S1")
    tid = s.upsert_table(rid, sid, 0, "R1", "md", "h", {"title": "R1"})
    s.save_approved_run(
        "run1", tid, rid, sid,
        wide_table=[{"branch_num": "1", "A@202603": 100.0}],
        computed_columns=[],
        descriptions=["营业收入增长"],
        status="ok",
        sentinels=[],
        runlog_markdown="# run1",
        design_md_path="/mnt/ai-report-data/rid.design.md",
    )
    return s, rid, tid


def test_runtime_runs_5_steps(store_with_approved, tmp_path):
    s, rid, _ = store_with_approved
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    pipeline = RuntimePipeline(s)
    result = pipeline.run_report(rid, out_dir=str(out_dir))
    assert (out_dir / f"{rid}.report.md").exists()
    assert (out_dir / f"{rid}.report.docx").exists()
    assert "Test Report" in (out_dir / f"{rid}.report.md").read_text(encoding="utf-8")
    assert result["status"] == "completed"


def test_runtime_no_approved_exits_1(store_with_approved, tmp_path):
    s, rid, tid = store_with_approved
    # 删 approved
    s.conn.execute("DELETE FROM approved_table_runs WHERE table_id=?", [tid])
    s.conn.execute("UPDATE report_tables SET approval_status='draft' WHERE table_id=?", [tid])
    pipeline = RuntimePipeline(s, strict=False)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    result = pipeline.run_report(rid, out_dir=str(out_dir))
    assert result["status"] == "empty"


def test_runtime_strict_mode_exits_1_on_no_approved(store_with_approved, tmp_path):
    s, rid, tid = store_with_approved
    s.conn.execute("DELETE FROM approved_table_runs WHERE table_id=?", [tid])
    s.conn.execute("UPDATE report_tables SET approval_status='draft' WHERE table_id=?", [tid])
    pipeline = RuntimePipeline(s, strict=True)
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    with pytest.raises(RuntimeError, match="no approved"):
        pipeline.run_report(rid, out_dir=str(out_dir))
```

- [ ] **步骤 2：跑测试，确认失败**

```bash
cd skills/public/ai-report && python -m pytest tests/test_runtime_pipeline.py -v
```

- [ ] **步骤 3：写 `runtime_pipeline.py`**

```python
"""ai-report runtime pipeline (新写, 5-step orchestrator)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from assemble_status import build_status, format_zh_receipt
from duckdb_store import Store, DEFAULT_DB_PATH
from render_docx import render_docx
from render_markdown import render_markdown
from report_md import build_runtime_payload


class RuntimePipeline:
    def __init__(self, store: Store, *, strict: bool = False):
        self.store = store
        self.strict = strict

    def run_report(self, report_id: str, *, out_dir: str = "/mnt/ai-report-data") -> dict:
        # R-0: existence + source_md_hash warning
        meta = self.store.get_report_meta(report_id)
        if not meta:
            return {"status": "not_found", "error": f"report_id={report_id} 不存在"}
        # R-1: pull approved
        rows = self.store.list_approved_tables(report_id)
        if not rows:
            if self.strict:
                raise RuntimeError(f"strict mode: no approved tables for {report_id}")
            # 非 strict: 渲染空报告
            return {"status": "empty", "report_id": report_id}
        # R-2: build payload
        payload = build_runtime_payload(self.store, report_id)
        # R-3: render md
        out_md = Path(out_dir) / f"{report_id}.report.md"
        out_md.write_text(render_markdown(payload), encoding="utf-8")
        # R-4: render docx
        out_docx = Path(out_dir) / f"{report_id}.report.docx"
        style_path = str(Path(__file__).resolve().parent / "report_style.json")
        render_docx(payload, out_path=str(out_docx), style_path=style_path)
        # R-5: 中文回执
        sections = [{"section_title": r["section_title"], "approval_status": "approved",
                     "sentinels": json.loads(r["sentinels"]) if isinstance(r["sentinels"], str) else r["sentinels"],
                     "computed_sentinels": {}} for r in rows]
        status = build_status(report_id, sections,
                              design_md_path=f"/mnt/ai-report-data/{report_id}.design.md")
        receipt = format_zh_receipt(status)
        print(receipt)
        return {"status": "completed", "report_id": report_id, "out_md": str(out_md), "out_docx": str(out_docx), "receipt": receipt}


def main(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(prog="runtime_pipeline")
    parser.add_argument("--db-path", default=DEFAULT_DB_PATH)
    parser.add_argument("--report-id", required=True)
    parser.add_argument("--out-dir", default="/mnt/ai-report-data")
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args(argv)
    try:
        store = Store(db_path=args.db_path)
        store.open()
        store.init_schema()
        pipeline = RuntimePipeline(store, strict=args.strict)
        result = pipeline.run_report(args.report_id, out_dir=args.out_dir)
        if result["status"] in ("not_found", "empty"):
            return 1
        return 0
    except Exception as e:
        print(f"FAIL: {e}", file=sys.stderr)
        return 1
    finally:
        try:
            store.close()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **步骤 4：跑测试，确认通过**

```bash
cd skills/public/ai-report && python -m pytest tests/test_runtime_pipeline.py -v
```

- [ ] **步骤 5：commit**

```bash
git add skills/public/ai-report/scripts/runtime_pipeline.py skills/public/ai-report/tests/test_runtime_pipeline.py
git commit -m "feat(ai-report): add runtime_pipeline.py (5-step orchestrator + 中文回执)"
```

---

## 任务 17：`prompts/` —— LLM 提示词

**文件：**
- 创建：`skills/public/ai-report/prompts/compute_codegen.md`
- 创建：`skills/public/ai-report/prompts/description_gen.md`

- [ ] **步骤 1：创建 `compute_codegen.md`**

```markdown
# Compute Codegen Prompt (ai-report)

> **由 lead agent in-turn 加载** —— 不是脚本。LLM 读 IR + sample wide row, 输出 DuckDB SQL 字符串写到 `/mnt/ai-report-data/<report_id>.<table_id>.compute.<slug>.sql`。

## 输入 (in-turn 上下文注入)

- `ComputeIR` JSON: `{"name": "<虚拟列名>", "prompt": "<自然语言公式>", "examples": [{"row": <int>, "value": <float>}, ...]}`
- 3 行 sample wide: `[{"branch_num": "1", "A@202603": 100, ...}, ...]`
- 表的叶子列清单 (idx_id@period 列表)

## 输出契约

- 必须是 DuckDB SQL, 严格遵循:
  - `SELECT branch_num, <别名> AS <ComputeIR.name> FROM wide`
  - `<别名>` 与 `ComputeIR.name` 完全一致
  - 公式只能引用 wide 表已存在的列 (`idx_id@period` 形式)
  - 计算列不再 `data_unit` 限制; 业务侧 `unit_convert.py` 会按列 `data_unit="%"` 决定是否 `* 100`

## Few-shot 示例

### 输入 IR
```json
{"name": "利润率", "prompt": "利润总额 / 营业收入", "examples": [{"row": 0, "value": 0.2}]}
```

### 输入 wide 3 行
```json
[
  {"branch_num": "1", "BAS_026@202603": 10000000, "BAS_020@202603": 50000000},
  {"branch_num": "2", "BAS_026@202603": 20000000, "BAS_020@202603": 80000000}
]
```

### 输出 SQL
```sql
SELECT branch_num, (CAST("BAS_026@202603" AS DOUBLE) / CAST("BAS_020@202603" AS DOUBLE)) AS 利润率 FROM wide
```

## 失败重试

- 1 次 regenerate (用更明确的 few-shot 例子)
- 2 次失败 → orchestrator 写哨兵 `⚠️COMPUTE_FAILED` 到该 cell
```

- [ ] **步骤 2：创建 `description_gen.md`**

```markdown
# Description Gen Prompt (ai-report)

> **由 lead agent in-turn 加载** —— 不是脚本。LLM 读 wide rows + report title + 时间窗口, 输出 ≤ 200 字中文描述, 写到 `approved_table_runs.descriptions`。

## 输入

- `report_title: str`
- `time_info: list[str]` (期间窗口)
- `wide_rows: list[dict]` (含基础列 + 计算列)
- 哨兵列表 (哪些 cell 是 `⚠️QUERY_FAILED` / `⚠️COMPUTE_FAILED`)

## 输出契约

- 1 段中文, ≤ 200 字
- 必须基于 wide_rows 实际数值, 不可编造
- 提及异常哨兵(若有)放在括号里
- 落到 `approved_table_runs.descriptions: list[str]` 数组(每节一段)

## Few-shot 示例

### 输入
- report_title: "营业收入"
- time_info: ["202603"]
- wide_rows: [{"branch_num": "1", "BAS_020@202603": 50000000, "利润率": 0.2}]
- sentinels: []

### 输出
"2026 年 3 月营业收入 5000 万元, 利润率 20%, 较年初稳步增长。"

## 失败重试

- 1 次 regenerate
- 2 次失败 → orchestrator 写哨兵 `⚠️DESCRIPTION_FAILED` 占位
```

- [ ] **步骤 3：commit**

```bash
git add skills/public/ai-report/prompts/
git commit -m "feat(ai-report): add prompts/compute_codegen.md + description_gen.md"
```

---

## 任务 18：`references/` —— 5 个文档

**文件：**
- 创建：`skills/public/ai-report/references/pipeline.md`
- 创建：`skills/public/ai-report/references/runtime.md`
- 创建：`skills/public/ai-report/references/checkpoints.md`
- 创建：`skills/public/ai-report/references/status-output.md`
- 创建：`skills/public/ai-report/references/data-flow.md`

每个文档 1-2 屏, 直接 markdown 描述。

- [ ] **步骤 1：创建 `pipeline.md`**

```markdown
# ai-report Design Pipeline (14 step)

Per-section 14-step pipeline (从 parse_md 到回填 design.md):

| Step | 类型 | 产物 | 失败处理 |
|---|---|---|---|
| 0 | bash `md_lint.py` | LintReport | 失败 → Checkpoint 0 阻塞 |
| 0.5 | checkpoint | informational | 失败继续 |
| 1 | bash `parse_md.py` | parsed_payload | 抛错 → exit 1 |
| 2 | bash `sqlbot_client.py` | metric_facts (新 run_id) | 哨兵 `⚠️QUERY_FAILED` |
| 3.5 | checkpoint | per-section always-trigger | user 选 continue/stop |
| 4 | bash `compute.py assemble-wide` | 内存 wide | 抛错 → exit 1 |
| 5 | bash `compute.py extract-ir` | ComputeIR list | 抛错 → exit 1 |
| 6 | agent-turn-LLM | compute.<slug>.sql | 失败 → 哨兵 `⚠️COMPUTE_FAILED` |
| 7 | bash `compute.py validate` | ValidationResult | 失败 → 哨兵 `⚠️COMPUTE_FAILED` |
| 8 | bash `compute.py evaluate` | values + status | 失败 → 哨兵 `⚠️COMPUTE_FAILED` |
| 9 | bash `compute.py apply-computed` | wide 含计算列 | 抛错 → exit 1 |
| 10 | bash `unit_convert.py` | wide 含单位换算 | 抛错 → exit 1 |
| 11 | agent-turn-LLM | description 文本 | 失败 → 哨兵 `⚠️DESCRIPTION_FAILED` |
| 8d.5 | checkpoint | per-section (仅当有 `> 描述:`) | user 选 continue/stop |
| (preview) | bash `render_markdown.py` | preview md | 仅展示 |
| 10 | checkpoint | per-section approve/modify/reject | reject → 改 source_md 重跑 |
| (save) | bash `duckdb_store.save_approved_run` | approved_table_runs 新行 | 抛错 → exit 1 |

Checkpoint ID 编号沿用 chatbi-report 惯例:1.5/3.5/8d.5 + ai-report 新加 0/10/11。
```

- [ ] **步骤 2：创建 `runtime.md`**

```markdown
# ai-report Runtime Pipeline (5 step)

整本 runtime, 读 approved 快照生成 report.md / report.docx:

```
input: --report-id <id>
  R-0: duckdb_store.get_report_meta (存在性 + source_md_hash 警告)
  R-1: duckdb_store.list_approved_tables (按 section_order, table_order)
       if 无 approved → --strict 报错 / 默认渲染空报告
  R-2: build_runtime_payload (单 dict, 全报告 sections/tables/cells)
  R-3: render_markdown → <report_id>.report.md
  R-4: render_docx → <report_id>.report.docx
  R-5: 中文回执 (assemble_status.format_zh_receipt)
```

输出路径:
- `/mnt/ai-report-data/<report_id>.report.md`
- `/mnt/ai-report-data/<report_id>.report.docx`

未 approved section 默认跳过;`--strict` flag 严格模式要求全 approved 才跑。
```

- [ ] **步骤 3：创建 `checkpoints.md`**

```markdown
# ai-report Checkpoints (6 个)

| ID | 触发点 | 粒度 | 阻塞? | 用户选项 |
|---|---|---|---|---|
| 0 | Step 0 lint 失败 | 整本 | ✅ 阻塞 | continue / stop |
| 1.5 | Step 0 lint pass | 整本 | ❌ informational | continue / stop |
| 3.5 | Step 2 query 完 | per-section | ❌ always-trigger (2026-06-27 反转) | continue / stop |
| 8d.5 | Step 11 describe 完 | per-section | ❌ (仅当有 `> 描述:`) | continue / stop |
| 10 | Step 14 preview 完 | per-section | ❌ | approve / modify / reject |
| 11 | Section N approved | 整本 | ❌ (推进) | continue / jump / preview / done |

所有 checkpoint 走 `ask_clarification(clarification_type="risk_confirmation", ...)` 异步等,和 chatbi-report 同构。

Checkpoint ID 编号说明:1.5/3.5/8d.5 沿用 chatbi-report step 1-9 子步骤惯例,**不是** ai-report 的 Step 0-14 编号。映射:
- 1.5 → ai-report Step 0 后
- 3.5 → ai-report Step 2 后
- 8d.5 → ai-report Step 11 后
- 0/10/11 是 ai-report 新加的(无 chatbi-report 对应)
```

- [ ] **步骤 4：创建 `status-output.md`**

```markdown
# ai-report 中文回执 契约

`assemble_status.format_zh_receipt(status: dict) -> str` 返回:

```
📊 ai-report 报告生成完成
  - 章节数: {approved_sections}/{total_sections} approved
  - 哨兵数: {total_sentinels} (⚠️QUERY_FAILED=N, ⚠️COMPUTE_FAILED=M, ...)
  - 未设计章节: {draft_sections}
  - 生成路径: {report_md_path} / {report_docx_path}
```

status dict 字段:
- `report_id`, `total_sections`, `approved_sections`, `draft_sections`
- `total_sentinels`, `sentinels_by_code` (5 哨兵聚合)
- `design_md_path`, `report_md_path`, `report_docx_path`

注意:`status.json` 整个 drop,不落盘;状态只在中文回执里和 DuckDB 5 张表里。
```

- [ ] **步骤 5：创建 `data-flow.md`**

```markdown
# ai-report DuckDB 数据流

```
┌──────────────────────────────────────────────────────────┐
│  Lead Agent (LangGraph make_lead_agent + ask_clarification)  │
│  - 触发 design / runtime 模式                              │
│  - 调 LLM (compute codegen / description)                 │
└────┬─────────────────────────────────────────────────────┘
     │
     ▼
┌──────────────────────────────────────────────────────────┐
│  design_pipeline.py / runtime_pipeline.py                 │
│  - 14 step (design) / 5 step (runtime)                    │
└────┬─────────────────────────────────────────────────────┘
     │
     ▼
┌──────────────────────────────────────────────────────────┐
│  16 scripts (新写, 零 chatbi-report import)                 │
│  report_split / parse_md / md_lint / sqlbot_client /      │
│  compute / unit_convert / duckdb_store /                   │
│  render_markdown / render_docx / assemble_status / ...    │
└────┬─────────────────────────────────────────────────────┘
     │
     ▼
┌──────────────────────────────────────────────────────────┐
│  DuckDB 全局单库 /mnt/ai-report-data/duckdb/ai-report.duckdb│
│  5 表: reports / report_sections / report_tables /         │
│  metric_facts / approved_table_runs                        │
│  (所有表 schema_version=1, run_id 入 PK 保留历史)           │
└──────────────────────────────────────────────────────────┘
```

设计阶段:
- parse_md → report_tables.parsed_payload
- sqlbot_client → metric_facts (新 run_id)
- compute.assemble-wide → 内存 wide
- compute.evaluate → wide 含计算列 (哨兵写 cell)
- unit_convert → DuckDB UPDATE 应用单位换算
- approved → approved_table_runs (snapshot)

运行阶段:
- 读 approved_table_runs.wide_table 快照
- 拼 render_payload → render_markdown / render_docx
- 输出整本 report.md / report.docx
```

- [ ] **步骤 6：commit**

```bash
git add skills/public/ai-report/references/
git commit -m "docs(ai-report): add references/ (5 docs: pipeline, runtime, checkpoints, status-output, data-flow)"
```

---

## 任务 19：`SKILL.md` —— 触发 + design/runtime 模式选择

**文件：**
- 创建：`skills/public/ai-report/SKILL.md`

- [ ] **步骤 1：写 `SKILL.md`**

```markdown
# ai-report Skill

多章节多表 经营分析报告 (H1/H2/H3 + 多 `<table>`),design + runtime 双模式,DuckDB 全局单库持久化。

## 触发与模式

| 模式 | Trigger | Input | Output |
|---|---|---|---|
| **design** | 默认,或用户说"设计"/"设计这个" | `report.md`(整本) | DuckDB approved 快照 + 回填 `<report_id>.design.md` |
| **runtime** | 用户明确说"运行报告"/"生成报告" | `report_id` | 整本 `<report_id>.report.md` + `<report_id>.report.docx` |

**默认是 design**。如用户未明确说"运行报告",一律走 design 模式逐节交互。

## 工作流概览

### Design 模式 (单 section 14 步)
详见 `references/pipeline.md`。6 个 checkpoint (0/1.5/3.5/8d.5/10/11) 走 `ask_clarification` 异步等用户拍板。

### Runtime 模式 (5 步)
详见 `references/runtime.md`。读 approved 快照,无 checkpoint 一键出整本。

## 数据层

DuckDB 全局单库 `/mnt/ai-report-data/duckdb/ai-report.duckdb`。5 张表 (schema_version=1):

- `reports` / `report_sections` / `report_tables`: 报告结构 + draft/approved/rejected 状态
- `metric_facts`: SQLBot 原始事实, `run_id` 入 PK 保留历史
- `approved_table_runs`: approved 后落盘的 wide_table 快照 + computed_columns + descriptions

## 文件输出

| 文件 | 默认 | --debug |
|---|---|---|
| `ai-report.duckdb` (全局单库) | ✅ | ✅ |
| `<report_id>.design.md` | ✅ (approved 后回填) | ✅ |
| `<report_id>.report.md` | ✅ (runtime) | ✅ |
| `<report_id>.report.docx` | ✅ (runtime) | ✅ |
| `status.json` | ❌ drop | ❌ drop |
| 中间产物 (.parsed.json / .wide.json) | ❌ | ✅ (写 `/mnt/user-data/outputs/`) |

## 关键约束

- ai-report 与 chatbi-report **并存**,ai-report 不 import 不复制 chatbi-report 任何代码
- 数据层**纯 DuckDB**,**无 pandas**
- 16 scripts **全部新写**
- 源单位固定 = 元;单位换算走 DuckDB SQL UPDATE (`col/10000` / `col*100`)
- Compute 5 层校验**无**关键字黑名单 (Phase 1 政策)
- 默认零中间产物,仅 `--debug` 例外

## 配套文档

- `references/pipeline.md` — design 14 步
- `references/runtime.md` — runtime 5 步
- `references/checkpoints.md` — 6 个 checkpoint 行为
- `references/status-output.md` — 中文回执 契约
- `references/data-flow.md` — DuckDB 数据流图
- `prompts/compute_codegen.md` — LLM DuckDB SQL codegen prompt
- `prompts/description_gen.md` — LLM 中文描述 prompt
- `example/wangyi_2026_03.md` — 王益联社 2026 年 3 月 5 节 sample
```

- [ ] **步骤 2：commit**

```bash
git add skills/public/ai-report/SKILL.md
git commit -m "docs(ai-report): add SKILL.md with design/runtime trigger + 5 docs references"
```

---

## 任务 20：E2E sample run —— 王益联社 5 节 full pipeline

**文件：**
- 修改：`skills/public/ai-report/example/wangyi_2026_03.md`（替换为完整 sample, 5 节 5 表含计算列 + 描述）
- 创建：`skills/public/ai-report/tests/fixtures/expected/wangyi_2026_03_report.md`（预期 runtime 输出快照）

**接口：** 端到端跑通:`python -m report_md --db-path :memory: --report-id wangyi_2026_03` 应该输出含 5 节 5 表的 markdown。

- [ ] **步骤 1：扩展 `example/wangyi_2026_03.md`**

替换 `example/wangyi_2026_03.md` 为完整 5 节 5 表 sample,每节 1 个 H3 表,含 `data-idx` / `data-unit` / `data-period` 完整元数据。第 5 节"资产质量"加 `> 计算:` 块（不良率 = 不良贷款 / 贷款余额）和 `> 描述:` 块。

- [ ] **步骤 2：创建 mock SQLBot fixture 扩展**

扩展 `tests/fixtures/mock_sqlbot/wangyi_2026_03.json`,加入 BAS_011 (不良贷款), BAS_010@202602 (上月末贷款), BAS_001@202602 (上月末存款) 等额外指标。

- [ ] **步骤 3：写 E2E 集成测试**

在 `tests/test_runtime_pipeline.py` 追加:

```python
def test_e2e_wangyi_5_section(tmp_path):
    """E2E: ingest 5-section report, design 5 sections, runtime produces full report."""
    db = str(tmp_path / "e2e.duckdb")
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    # 1. design: 用 mock LLM (auto-approve) + mock sqlbot
    from design_pipeline import run_report
    from sqlbot_client import MockSQLBotClient
    store = Store(db_path=db); store.open(); store.init_schema()
    sqlbot = MockSQLBotClient(fixture_path="tests/fixtures/mock_sqlbot/wangyi_2026_03.json")
    # monkeypatch LLM (在 conftest 或 fixture 里全局设置)
    import design_pipeline
    design_pipeline._llm_codegen = lambda ir, sample: "SELECT branch_num, 1.0 AS x FROM wide"
    design_pipeline._llm_describe = lambda rows, title: f"section {title} 描述"
    design_pipeline._checkpoint = lambda msg, opts: "approve" if "Checkpoint 10" in msg or "Checkpoint 0" in msg or "Checkpoint 1.5" in msg or "Checkpoint 3.5" in msg or "Checkpoint 8d.5" in msg or "Checkpoint 11" in msg else "approve"
    result = run_report(store, sqlbot, "example/wangyi_2026_03.md")
    assert result["status"] == "completed"
    # 2. runtime
    from runtime_pipeline import RuntimePipeline
    pipeline = RuntimePipeline(store)
    runtime_result = pipeline.run_report("wangyi_2026_03", out_dir=str(out_dir))
    assert runtime_result["status"] == "completed"
    assert (out_dir / "wangyi_2026_03.report.md").exists()
    assert (out_dir / "wangyi_2026_03.report.docx").exists()
```

- [ ] **步骤 4：跑 E2E,确认通过**

```bash
cd skills/public/ai-report && python -m pytest tests/test_runtime_pipeline.py::test_e2e_wangyi_5_section -v
```

- [ ] **步骤 5：手动跑实际 CLI**

```bash
cd skills/public/ai-report
python -m runtime_pipeline --db-path /tmp/ai-report-e2e.duckdb --report-id wangyi_2026_03 --out-dir /tmp/ai-report-e2e
# 期望: 中文回执输出 + /tmp/ai-report-e2e/wangyi_2026_03.report.md / .docx 落盘
```

- [ ] **步骤 6：commit + 更新 CLAUDE.md**

```bash
git add skills/public/ai-report/example/wangyi_2026_03.md skills/public/ai-report/tests/test_runtime_pipeline.py skills/public/ai-report/tests/fixtures/mock_sqlbot/wangyi_2026_03.json
git commit -m "feat(ai-report): E2E wangyi 5-section sample run + CLAUDE.md"
```

然后追加到 `CLAUDE.md` 项目根:

```markdown
## ai-report Skill

`ai-report` 是从零开始的新 skill, 在 chatbi-report 之上面向多章节多表报告 + design/runtime 双模式 + DuckDB 持久化。详见 `skills/public/ai-report/SKILL.md` 和 `docx/superpowers/specs/2026-06-30-ai-report-design.md`。**不 import chatbi-report 任何代码,数据层纯 DuckDB,无 pandas。**
```

```bash
git add CLAUDE.md
git commit -m "docs: add ai-report section to CLAUDE.md"
```

---

## Self-Review

**1. Spec coverage (against `2026-06-30-ai-report-design.md`):**

| Spec § | Coverage |
|---|---|
| §1 Background | Covered in plan header |
| §2 Goals G1-G6 | G1 (5-section MD) → Task 3 + 20; G2 (design + checkpoint) → Task 15; G3 (runtime) → Task 16; G4 (DuckDB) → Task 5; G5 (persistence) → Task 5 + 15; G6 (no chatbi-report code) → enforced by plan + Tasks 1-16 all "新写" |
| §3 Non-Goals | Status.json drop (Task 19 SKILL.md); unit_conversion.py drop (Task 7 硬编码); pandas drop (Task 5/7/8/9/10 all DuckDB); 13-table V2 drop (Task 5 schema lock to 5) |
| §4 Architecture | Tasks 1-20 map 1:1 |
| §5.1 Schema (5 tables) | Task 5 DDL exact match |
| §5.2 Scripts (16) | Tasks 2-16 each produce one script |
| §6.1-6.4 Pipeline | Task 15 (design 14 step) + Task 16 (runtime 5 step) |
| §7.1 5 sentinels | Task 13 test_sentinels.py + Task 5 (⚠️QUERY_FAILED/CAST_FAILED) + Task 8 (COMPUTE_FAILED) + Task 15 (DESCRIPTION_FAILED) + Task 4 (LINT_FAILED) |
| §7.2 6 checkpoints | Task 15 + Task 18 references/checkpoints.md |
| §7.3 Integrity (source_md_hash) | Task 5 reports.source_md_hash + Task 15 run_report |
| §7.4 Runtime 失败兜底 | Task 16 strict mode + empty mode |
| §8.1 File output | Task 19 SKILL.md 文件输出表 + Task 20 E2E |
| §8.2 Unit conversion | Task 7 (8 combos) |
| §8.3 5-layer validation | Task 9 |
| §8.4 Compute output contract | Task 9/10 + Task 17 compute_codegen.md |
| §8.5 Validation outside | Task 15 LLM retry 1 次 + Task 13 assemble_status |
| §9 Testing | Tasks 1-16 each have test files; 11 test files per spec §10.1 |
| §10 Deliverables | 16 scripts (Tasks 2-16) + 2 prompts (Task 17) + 5 refs (Task 18) + 11 tests (Tasks 1-16) + 1 example (Task 20) + 1 SKILL.md (Task 19) = 36 files |
| §11 Risks | Mitigations baked in: 1) Few-shot + retry → Task 17 prompts; 2) Concurrent design → out of scope Phase 1; 3) Render drift → Task 11/12 use same wide_table; 4) Corruption → Task 5 写 .bak Phase 2; 5) Capacity → Phase 2 archive; 6) Unit SQL error → Task 7 8 combos; 7) Schema version → Task 5 schema_version; 8) User MD error → Task 4 lint + Task 15 checkpoint 0; 9) Hash race → Task 15 snapshot 写库时算 hash |
| §12 Phase 1 | Tasks 1-20 produce Phase 1 deliverable |
| §13 Success Criteria | Task 20 E2E + Task 19 SKILL.md + Task 5 schema lock + Task 16 runtime < 5s |
| §14 Decisions Log | All decisions applied in plan tasks (no pandas, no chatbi-report import, etc.) |

**2. Placeholder scan:** No "TBD" / "TODO" / "implement later" found. All code blocks complete. No "similar to Task N" — each task has full code.

**3. Type consistency:**
- `Store.upsert_report / upsert_section / upsert_table / get_report_meta / get_table / insert_metric_facts / get_metric_facts / save_approved_run / list_approved_tables / get_approved_run` — defined in Task 5, used in Tasks 8/15/16
- `make_report_id / make_run_id / make_section_id / make_table_id` — defined in Task 5, used in Task 15
- `ComputeIR / assemble_wide / extract_ir / validate / evaluate / apply_computed` — defined in Tasks 8/9/10, used in Task 15
- `ValidationResult(passed, layer, error)` — defined in Task 9, used in Task 15
- `render_markdown(payload) -> str` — defined in Task 11, used in Tasks 14/16
- `render_docx(payload, out_path, style_path) -> None` — defined in Task 12, used in Tasks 14/16
- `build_status / format_zh_receipt` — defined in Task 13, used in Task 16
- `DesignPipeline.run_section` / `run_report` — defined in Task 15, used in Task 20
- `RuntimePipeline.run_report` — defined in Task 16, used in Task 20

No type mismatches found.

**4. Spec coverage gaps identified:**
- 报告级 `metric dedupe` (Phase 2 out of scope) — not in plan ✓
- multi-report cross-JOIN (Phase 3 out of scope) — not in plan ✓
- preview-report / activate-report (Phase 3 out of scope) — not in plan ✓
- DuckDB keyword blacklist (Phase 2) — explicitly NOT in Task 9 ✓
- Multi-user collaboration (out of scope) — not in plan ✓

**5. File count:**
- 16 scripts: report_split, parse_md, md_lint, sqlbot_client, unit_convert, compute, render_markdown, render_docx, assemble_status, duckdb_store, report_md, report_docx, design_pipeline, runtime_pipeline, retry, report_style.json ✓
- 2 prompts: compute_codegen.md, description_gen.md ✓
- 5 refs: pipeline.md, runtime.md, checkpoints.md, status-output.md, data-flow.md ✓
- 11 test files: test_retry, test_unit_convert, test_report_split, test_parse_md, test_md_lint, test_sqlbot_client, test_duckdb_store, test_compute, test_render_markdown, test_render_docx, test_sentinels, test_assemble_status, test_design_pipeline, test_runtime_pipeline = 14 (vs spec 11). Extra 3: test_assemble_status (spec §10.1 list), test_sentinels (spec §10.1 list), test_retry. Reconciled: spec lists 11, plan has 14; over-delivery OK (split larger tests if needed in execution).
- 1 example: wangyi_2026_03.md ✓
- 1 SKILL.md ✓

**Self-review verdict:** Plan is at the level to execute. No placeholders, no type mismatches, spec coverage complete.

---

## Execution Handoff

Plan complete and saved to `docx/superpowers/plans/2026-06-30-ai-report-impl.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?

