# chatbi-report 实施计划 — 附录 A + 附录 B

> 用途：本文件是 `2026-06-23-chatbi-report-data-agent.md` 主体中"附录 A / 附录 B"占位的真实内容。
> 主体多次引用（如任务 3 步骤 1、任务 4 步骤 1、任务 5 步骤 1、任务 11 步骤 2-8）但**正文不再内联**——全部在此查阅 / 复制。
>
> 来源：从原版 4600 行英文 plan (`863f39fb`) 恢复；中文翻译时这些代码块被"见附录 A.X"占位替代。
>
> **章节映射：**
> - 附录 A（MD fixture）→ 任务 3 / 4 / 5 共用，含 10 个 `.md` 文件
> - 附录 B（集成测试）→ 任务 11，含 1 个 conftest + 6 个 test_*.py + 3 个 expected_outputs

---

# 附录 A：MD fixture 内容

## A.1 `happy.md` —— 干净正常路径（任务 3 步骤 1 创建；任务 4 复用）

`backend/tests/chatbi_report/fixtures/sample_md/happy.md`：

````markdown
# 王益联社 2025 年度经营报表

## 第一章: 经营规模

### 报表: 商户与贷款概览

> 机构: branch_num=27020199; branch_short_name=王益联社
> 时期: time_info=["2025"]
> 计算:
>   收单商户同比 = 本期BAS_0263减去年同期再除同期
>   收单商户.示例: BAS_0263[current=1420, yoy_same=1200] -> 0.1833

<table>
  <thead>
    <tr>
      <th>季度</th>
      <th data-idx="BAS_0263" data-unit="个">贷款收单商户数</th>
      <th data-unit="%">{{收单商户同比}}</th>
    </tr>
  </thead>
  <tbody>
    <tr><td>2025-Q4</td><td></td><td></td></tr>
  </tbody>
</table>
````

## A.2 `no_org_context.md` —— 缺 `> 机构:` 块（任务 3 步骤 1）

````markdown
# 缺机构样例

## 第一章: 经营规模

### 报表: 商户与贷款概览

> 时期: time_info=["2025"]

<table>
  <thead><tr><th>季度</th><th data-idx="BAS_0263" data-unit="个">贷款收单商户数</th></tr></thead>
  <tbody><tr><td>2025-Q4</td><td></td></tr></tbody>
</table>
````

## A.3 `no_time_info.md` —— 缺 `> 时期:` 块（任务 3 步骤 1）

````markdown
# 缺时期样例

## 第一章: 经营规模

### 报表: 商户与贷款概览

> 机构: branch_num=27020199; branch_short_name=王益联社

<table>
  <thead><tr><th>季度</th><th data-idx="BAS_0263" data-unit="个">贷款收单商户数</th></tr></thead>
  <tbody><tr><td>2025-Q4</td><td></td></tr></tbody>
</table>
````

## A.4 `old_style_placeholder.md` —— 旧式占位符（仅 WARN，任务 3 步骤 1）

````markdown
# 旧式占位符样例

## 第一章: 经营规模

### 报表: 商户与贷款概览

> 机构: branch_num=27020199; branch_short_name=王益联社
> 时期: time_info=["2025"]

<table>
  <thead>
    <tr>
      <th>季度</th>
      <th data-unit="个">{{BAS_0263}}</th>
    </tr>
  </thead>
  <tbody><tr><td>2025-Q4</td><td></td></tr></tbody>
</table>
````

## A.5 `lint_error.md` —— 同时触发 6 种 lint ERROR（任务 3 步骤 1）

````markdown
# 错误样例

## 第一章: 经营规模

### 报表: 商户与贷款概览

> 机构: branch_num=27020199
> 时期: time_info="2025"
> 计算:
>   营收同比 = 本期MISSING_ID减去年同期

<table>
  <thead>
    <tr>
      <th>季度</th>
      <th>无属性列</th>
      <th data-idx="bad id" data-unit="个">错误ID</th>
      <th data-idx="BAS_0263" data-unit="%">{{收单商户同比}}</th>
    </tr>
  </thead>
  <tbody><tr><td>2025-Q4</td><td></td><td></td><td></td></tr></tbody>
</table>
````

> 此 MD 同时触发：(1) `> 机构:` 格式错（缺 `branch_short_name`）；(2) `> 时期:` 非 JSON 数组；(3) `<th>` 无 `data-idx` 且无 `{{}}`；(4) `data-idx` 正则失败；(5) 计算列携带 `data-idx`；(6) `> 计算:` 引用表头集合中不存在的 `MISSING_ID`。

## A.6 `multi_chapter.md` —— 2 章节各 1 张报表（任务 4 步骤 1）

````markdown
# 多章节样例

## 第一章: 经营规模

### 报表: 商户与贷款概览

> 机构: branch_num=27020199; branch_short_name=王益联社
> 时期: time_info=["2025"]

<table>
  <thead><tr><th>季度</th><th data-idx="BAS_0263" data-unit="个">贷款收单商户数</th></tr></thead>
  <tbody><tr><td>2025-Q4</td><td></td></tr></tbody>
</table>

## 第二章: 资产负债

### 报表: 存贷款概览

> 机构: branch_num=27020199; branch_short_name=王益联社
> 时期: time_info=["2025"]

<table>
  <thead><tr><th>季度</th><th data-idx="BAS_0264" data-unit="元">贷款余额</th><th data-idx="BAS_0265" data-unit="元">存款余额</th></tr></thead>
  <tbody><tr><td>2025-Q4</td><td></td><td></td></tr></tbody>
</table>
````

## A.7 `multi_header.md` —— 2 行 thead（rowspan + colspan）（任务 4 步骤 1）

````markdown
# 多级表头样例

## 第一章: 经营规模

### 报表: 商户与贷款概览

> 机构: branch_num=27020199; branch_short_name=王益联社
> 时期: time_info=["2025"]

<table>
  <thead>
    <tr>
      <th rowspan="2">季度</th>
      <th colspan="2">商户与贷款</th>
    </tr>
    <tr>
      <th data-idx="BAS_0263" data-unit="个">贷款收单商户数</th>
      <th data-idx="BAS_0264" data-unit="元">贷款余额</th>
    </tr>
  </thead>
  <tbody><tr><td>2025-Q4</td><td></td><td></td></tr></tbody>
</table>
````

## A.8 `multi_header_computed.md` —— 类目父级下挂计算列（任务 4 步骤 1）

````markdown
# 多级表头含计算列样例

## 第一章: 经营规模

### 报表: 商户与贷款概览

> 机构: branch_num=27020199; branch_short_name=王益联社
> 时期: time_info=["2025"]
> 计算:
>   收单商户同比 = 本期BAS_0263减去年同期再除同期

<table>
  <thead>
    <tr>
      <th rowspan="2">季度</th>
      <th colspan="2">商户与贷款</th>
    </tr>
    <tr>
      <th data-idx="BAS_0263" data-unit="个">贷款收单商户数</th>
      <th data-unit="%">{{收单商户同比}}</th>
    </tr>
  </thead>
  <tbody><tr><td>2025-Q4</td><td></td><td></td></tr></tbody>
</table>
````

## A.9 `computed_columns.md` —— 2 计算 spec（任务 5 步骤 1）

````markdown
# 计算列样例

## 第一章: 经营规模

### 报表: 商户与贷款概览

> 机构: branch_num=27020199; branch_short_name=王益联社
> 时期: time_info=["2025", "2024"]
> 计算:
>   收单商户同比 = 本期BAS_0263减去年同期再除同期
>   余额较年初 = 本期BAS_0264减上期

<table>
  <thead><tr><th>季度</th><th data-idx="BAS_0263" data-unit="个">贷款收单商户数</th><th data-idx="BAS_0264" data-unit="元">贷款余额</th><th data-unit="%">{{收单商户同比}}</th><th data-unit="元">{{余额较年初}}</th></tr></thead>
  <tbody><tr><td>2025-Q4</td><td></td><td></td><td></td><td></td></tr></tbody>
</table>
````

## A.10 `computed_with_examples.md` —— 计算列 + `.示例:` 行（任务 5 步骤 1）

````markdown
# 计算列带示例样例

## 第一章: 经营规模

### 报表: 商户与贷款概览

> 机构: branch_num=27020199; branch_short_name=王益联社
> 时期: time_info=["2025", "2024"]
> 计算:
>   收单商户同比 = 本期BAS_0263减去年同期再除同期
>   收单商户同比.示例: BAS_0263[current=1420, yoy_same=1200] -> 0.1833

<table>
  <thead><tr><th>季度</th><th data-idx="BAS_0263" data-unit="个">贷款收单商户数</th><th data-unit="%">{{收单商户同比}}</th></tr></thead>
  <tbody><tr><td>2025-Q4</td><td></td><td></td></tr></tbody>
</table>
````

---

# 附录 B：集成测试 + expected_outputs fixture

## B.1 `backend/tests/chatbi_report/conftest.py`（任务 11 步骤 1）

```python
"""Conftest for backend chatbi-report integration tests.

Adds skills/public/chatbi-report/scripts to sys.path so the scripts
can be imported as top-level modules (retry, sqlbot_client, ...).
"""
import sys
from pathlib import Path

SCRIPTS_DIR = (
    Path(__file__).resolve().parents[2]
    / "skills" / "public" / "chatbi-report" / "scripts"
)
sys.path.insert(0, str(SCRIPTS_DIR))
```

> 提示：6 个集成测试需要 `llm_complete` 可调用对象，**它在各 test_*.py 内部用 `mock.Mock(side_effect=[...])` 现造**——不必放到 conftest 里。

## B.2 `test_happy_path.py`（任务 11 步骤 3）

```python
"""Happy-path E2E: full MD -> JSON + MD + DOCX."""
import json
from pathlib import Path

import parse_md as pm
import render_markdown as rm
import render_docx as rd
import sqlbot_client as sc
import unit_conversion as uc


def test_happy_path_end_to_end(tmp_path):
    fixture_dir = Path(__file__).resolve().parent / "fixtures"
    md_path = fixture_dir / "sample_md" / "happy.md"
    mock_sql = sc.MockSQLBotClient(
        fixture_path=str(fixture_dir / "mock_sqlbot" / "query_responses.json")
    )

    # 1. Parse
    doc = pm.parse_file(str(md_path))
    assert doc.title == "王益联社 2025 年度经营报表"

    # 2. Query SQLBot per-idx (parallel in real flow; sequential here)
    rep = doc.sections[0].reports[0]
    per_idx = {idx: mock_sql.query_report_info(
        org_info=[{"branch_num": rep.org_context.branch_num,
                   "branch_short_name": rep.org_context.branch_short_name}],
        index_info=[{"idx_id": idx}],
        time_info=rep.time_info,
    ) for idx in doc.all_idx_ids}

    # 3. Pivot (this calls compute.assemble_wide_table internally)
    from compute import assemble_wide_table
    wide = [assemble_wide_table(per_idx, rep)]

    # 4. JSON + MD + DOCX
    json_out = {"title": doc.title, "sections": [s.to_dict() for s in doc.sections]}
    (tmp_path / "report.json").write_text(json.dumps(json_out, ensure_ascii=False, indent=2),
                                          encoding="utf-8")
    md_out = rm.render_markdown(doc, wide, compute_status={})
    (tmp_path / "report.md").write_text(md_out, encoding="utf-8")
    rd.render_docx(doc, wide, compute_status={},
                   out_path=str(tmp_path / "report.docx"),
                   style_path=str(fixture_dir.parent.parent.parent
                                  / "skills" / "public" / "chatbi-report"
                                  / "scripts" / "report_style.json"))

    # 5. Verify chatbi-specific contract: NO `(`BAS_0263`)` in MD header
    md_text = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert "贷款收单商户数 (个)" in md_text
    assert "(`BAS_0263`)" not in md_text
    # Status file shape: success
    from assemble_status import write_status
    write_status(str(tmp_path / "report.status.json"),
                 exit_step=9, error_class=None, error_detail="",
                 outputs={"json": "report.json", "md": "report.md", "docx": "report.docx"},
                 metrics={"queried_count": 1, "query_failures": 0,
                          "computed_count": 0, "compute_validation_failures": 0,
                          "llm_calls": 0, "duration_seconds": 0.5})
    status = json.loads((tmp_path / "report.status.json").read_text(encoding="utf-8"))
    assert status["status"] == "success"
```

## B.3 `test_partial_query_failure.py`（任务 11 步骤 4）

```python
"""F18: one idx SQLBot success=false -> ⚠️QUERY_FAILED cells, status=partial."""
import json
from pathlib import Path

import parse_md as pm
import sqlbot_client as sc
import render_markdown as rm


def test_partial_query_failure_marks_cells_and_status(tmp_path):
    fixture_dir = Path(__file__).resolve().parent / "fixtures"
    md_path = fixture_dir / "sample_md" / "happy.md"
    mock_sql = sc.MockSQLBotClient(
        fixture_path=str(fixture_dir / "mock_sqlbot" / "partial_failure.json")
    )
    doc = pm.parse_file(str(md_path))
    rep = doc.sections[0].reports[0]
    per_idx = {idx: mock_sql.query_report_info(
        org_info=[{"branch_num": rep.org_context.branch_num,
                   "branch_short_name": rep.org_context.branch_short_name}],
        index_info=[{"idx_id": idx}],
        time_info=rep.time_info,
    ) for idx in doc.all_idx_ids}
    from compute import assemble_wide_table
    wide = [assemble_wide_table(per_idx, rep)]
    md_out = rm.render_markdown(doc, wide, compute_status={})
    (tmp_path / "report.md").write_text(md_out, encoding="utf-8")

    md_text = (tmp_path / "report.md").read_text(encoding="utf-8")
    # The header carries the failure marker
    assert "贷款收单商户数 (个) ⚠️QUERY_FAILED" in md_text

    # status=partial (1 query failure)
    from assemble_status import write_status
    write_status(str(tmp_path / "report.status.json"),
                 exit_step=9, error_class=None, error_detail="",
                 outputs={"json": "report.json", "md": "report.md", "docx": "report.docx"},
                 metrics={"queried_count": 1, "query_failures": 1,
                          "computed_count": 0, "compute_validation_failures": 0,
                          "llm_calls": 0, "duration_seconds": 0.5})
    status = json.loads((tmp_path / "report.status.json").read_text(encoding="utf-8"))
    assert status["status"] == "partial"
    assert status["metrics"]["query_failures"] == 1
```

## B.4 `test_sqlbot_down.py`（任务 11 步骤 5）

```python
"""F17: SQLBot completely unreachable -> status=error, no outputs."""
import json
import tempfile
from pathlib import Path
from unittest import mock

import pytest
import requests
import parse_md as pm
import sqlbot_client as sc


def test_sqlbot_down_raises_sqlbot_error():
    fixture_dir = Path(__file__).resolve().parent / "fixtures"
    md_path = fixture_dir / "sample_md" / "happy.md"
    doc = pm.parse_file(str(md_path))
    rep = doc.sections[0].reports[0]

    real = sc.RealSQLBotClient(base_url="http://nope.invalid:9999")
    with mock.patch.object(sc.requests, "post",
                           side_effect=requests.ConnectionError("nope")):
        from retry import retry, exponential
        call = retry(max_attempts=3, backoff=exponential(base=0.001, max_delay=0.01),
                     retry_on=(requests.RequestException, sc.SQLBotError))(
            real.query_report_info
        )
        try:
            call(org_info=[], index_info=[{"idx_id": "BAS_0263"}], time_info=[])
        except (requests.RequestException, sc.SQLBotError) as e:
            assert "nope" in str(e) or "ConnectionError" in type(e).__name__
        else:
            pytest.fail("expected connection error after retries")

    # status=error (F17)
    from assemble_status import write_status
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as tf:
        status_path = tf.name
    write_status(status_path,
                 exit_step=5, error_class="F17", error_detail="SQLBot unreachable",
                 outputs={"json": None, "md": None, "docx": None},
                 metrics={"queried_count": 0, "query_failures": 0,
                          "computed_count": 0, "compute_validation_failures": 0,
                          "llm_calls": 0, "duration_seconds": 0.2})
    data = json.loads(Path(status_path).read_text(encoding="utf-8"))
    assert data["status"] == "error"
    assert data["error_class"] == "F17"
    assert data["outputs"]["json"] is None
```

## B.5 `test_no_org_context.py`（任务 11 步骤 6）

```python
"""F19: missing `> 机构:` block -> lint ERROR, status=error."""
import json
import subprocess
import sys
from pathlib import Path

import md_lint


def test_no_org_context_lint_fails():
    fixture_dir = Path(__file__).resolve().parent / "fixtures"
    md_path = fixture_dir / "sample_md" / "no_org_context.md"
    report = md_lint.lint_file(str(md_path))
    assert any(e.code == "F19" for e in report.errors)


def test_no_org_context_cli_exits_nonzero():
    fixture_dir = Path(__file__).resolve().parent / "fixtures"
    md_path = fixture_dir / "sample_md" / "no_org_context.md"
    md_lint_py = (
        fixture_dir.parent.parent.parent
        / "skills" / "public" / "chatbi-report" / "scripts" / "md_lint.py"
    )
    proc = subprocess.run(
        [sys.executable, str(md_lint_py), str(md_path)],
        capture_output=True, text=True,
    )
    assert proc.returncode == 1
    assert "F19" in proc.stderr
```

## B.6 `test_computed_columns_happy.py`（任务 11 步骤 7）

```python
"""F13/F14/F15 happy path: LLM emits valid IR + pandas function, validation passes,
the column gets filled with the expected numbers."""
import json
from pathlib import Path
from unittest import mock

import parse_md as pm


def test_computed_columns_end_to_end(tmp_path):
    fixture_dir = Path(__file__).resolve().parent / "fixtures"
    md_path = fixture_dir / "sample_md" / "computed_columns.md"
    doc = pm.parse_file(str(md_path))
    rep = doc.sections[0].reports[0]
    assert len(rep.computed_specs) == 2

    # Stub LLM: returns canned IR (batched JSON) and a known-good function
    import compute as cp
    ir_payload = json.dumps([
        {"name": "收单商户同比", "formula_repr": "(current-yoy_same)/yoy_same",
         "base_idx_ids": ["BAS_0263"], "periods": ["current", "yoy_same"]},
        {"name": "余额较年初", "formula_repr": "current-prev_period",
         "base_idx_ids": ["BAS_0264"], "periods": ["current", "prev_period"]},
    ], ensure_ascii=False)
    func_payload = (
        "def compute_report_r1_收单商户同比(df):\n"
        "    return (df['current'] - df['yoy_same']) / df['yoy_same']\n"
    )
    fake_llm = mock.Mock(side_effect=[ir_payload, func_payload, func_payload])
    irs = cp.extract_compute_ir(rep, fake_llm)
    assert irs[0].failure_class is None

    # Run the generated function on a synthetic df
    src = (
        "def compute_report_r1_收单商户同比(df):\n"
        "    return (df['current'] - df['yoy_same']) / df['yoy_same']\n"
    )
    cp.validate_ast(src)
    cp.validate_signature(src, "compute_report_r1_收单商户同比")
    import pandas as pd
    df = pd.DataFrame({"current": [1420], "yoy_same": [1200]})
    out = cp.run_smoke(src, "compute_report_r1_收单商户同比", df, smoke_rows=1)
    assert abs(out[0] - 0.1833) < 1e-6

    # status=success (no query/compute failures)
    from assemble_status import write_status
    write_status(str(tmp_path / "report.status.json"),
                 exit_step=9, error_class=None, error_detail="",
                 outputs={"json": "report.json", "md": "report.md", "docx": "report.docx"},
                 metrics={"queried_count": 2, "query_failures": 0,
                          "computed_count": 2, "compute_validation_failures": 0,
                          "llm_calls": 3, "duration_seconds": 2.1})
    data = json.loads((tmp_path / "report.status.json").read_text(encoding="utf-8"))
    assert data["status"] == "success"
```

## B.7 `test_unit_conversion_e2e.py`（任务 11 步骤 8）

```python
"""E2E: raw_unit=元 (SQLBot default) + MD data-unit=万元 -> cell display value
is the Decimal result of raw / 10000. Verifies the JSON cell value and the DOCX
display string both reflect the converted value."""
from decimal import Decimal
from pathlib import Path

import parse_md as pm
import sqlbot_client as sc


def test_unit_conversion_e2e(tmp_path):
    fixture_dir = Path(__file__).resolve().parent / "fixtures"
    md_path = fixture_dir / "sample_md" / "multi_chapter.md"  # has BAS_0264 (元) and BAS_0265 (元)
    doc = pm.parse_file(str(md_path))
    # Rep 1 (BAS_0264 贷款余额) has data-unit=元; we want display in 万元.
    # For this test we override the data-unit post-parse to mimic a designer
    # changing the unit declaration:
    rep = doc.sections[1].reports[0]
    for row in rep.headers:
        for cell in row:
            if cell.idx_id == "BAS_0264":
                cell.data_unit = "万元"
            elif cell.idx_id == "BAS_0265":
                cell.data_unit = "亿元"

    mock_sql = sc.MockSQLBotClient(
        fixture_path=str(fixture_dir / "mock_sqlbot" / "query_responses.json")
    )
    per_idx = {idx: mock_sql.query_report_info(
        org_info=[{"branch_num": rep.org_context.branch_num,
                   "branch_short_name": rep.org_context.branch_short_name}],
        index_info=[{"idx_id": idx}],
        time_info=rep.time_info,
    ) for idx in doc.all_idx_ids}

    from compute import assemble_wide_table
    wide = [assemble_wide_table(per_idx, rep)]

    # Cell value for BAS_0264 (raw 98,765,432.10) at data-unit=万元 -> Decimal("9876.5432100000")
    cells = wide[0]["cells"]
    assert isinstance(cells["BAS_0264"], Decimal)
    assert cells["BAS_0264"] < Decimal("9877")
    assert cells["BAS_0264"] > Decimal("9876")
    # Cell value for BAS_0265 (raw 123,456,789) at data-unit=亿元 -> Decimal("1.23456789")
    assert cells["BAS_0265"] == Decimal("1.23456789")
```

## B.8 `expected_outputs/happy.json`（任务 11 步骤 2）

```json
{
  "title": "王益联社 2025 年度经营报表",
  "section_count": 1,
  "report_count": 1,
  "all_idx_ids": ["BAS_0263"],
  "first_report_first_row": {
    "data_dt": "2025-Q4",
    "BAS_0263_display": "1,420"
  },
  "first_report_first_header_text": "贷款收单商户数",
  "first_report_first_header_has_unit_subtitle": true
}
```

## B.9 `expected_outputs/happy.md`（任务 11 步骤 2）

````markdown
# 王益联社 2025 年度经营报表

## 第一章: 经营规模

### 报表: 商户与贷款概览

| 季度 | 贷款收单商户数 (个) | 收单商户同比 (computed) (%) |
|------|---------------------|------------------------------|
| 2025-Q4 | 1,420 | — |
````

> 关键：表头**不含** `(\`BAS_0263\`)` 后缀；计算列带 `(computed)` 标记。

## B.10 `expected_outputs/partial_query_failure.json`（任务 11 步骤 2）

```json
{
  "title": "缺时期样例",
  "section_count": 1,
  "report_count": 1,
  "all_idx_ids": ["BAS_0263"],
  "first_report_first_row": {
    "data_dt": "2025-Q4",
    "BAS_0263_display": "⚠️QUERY_FAILED"
  }
}
```

---

# 附录 A / B 之间的依赖关系

| Fixture | 被哪些测试消费 | 必备 |
|---|---|---|
| `happy.md` (A.1) | test_md_lint / test_parse_md / test_happy_path / test_partial_query_failure / test_sqlbot_down | 是 |
| `no_org_context.md` (A.2) | test_md_lint / test_no_org_context | 是 |
| `no_time_info.md` (A.3) | test_md_lint | 是 |
| `old_style_placeholder.md` (A.4) | test_md_lint | 是 |
| `lint_error.md` (A.5) | test_md_lint | 是 |
| `multi_chapter.md` (A.6) | test_parse_md / test_unit_conversion_e2e | 是 |
| `multi_header.md` (A.7) | test_parse_md | 是 |
| `multi_header_computed.md` (A.8) | test_parse_md | 是 |
| `computed_columns.md` (A.9) | test_compute / test_computed_columns_happy | 是 |
| `computed_with_examples.md` (A.10) | test_compute | 是 |
| `mock_sqlbot/query_responses.json` | test_happy_path / test_unit_conversion_e2e | 是（任务 2 §2.3） |
| `mock_sqlbot/partial_failure.json` | test_partial_query_failure | 是（任务 2 §2.4） |
| `expected_outputs/*.{json,md}` (B.8-B.10) | 直接断言（不通过测试间接） | 是 |
