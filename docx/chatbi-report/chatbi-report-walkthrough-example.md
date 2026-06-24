# chatbi-report 完整示例：从 MD 定义到报表渲染

日期：2026-06-23
关联：`chatbi-report-data-agent-design.md`（本目录下）

## 目的

把 `chatbi-report` 9 步流水线用**一个具体例子**从头到尾跑一遍。

测试场景：3 个相同的指标列 `BAS_0263` + 1 个计算列 `商户数同比`，单机构 `王益联社`（branch_num=27020199），双年份 `time_info=["2025", "2024"]`（计算列需要 yoy 数据）。

> 设计师给的原始例子 `time_info=["2025"]` 是单年；为了演示完整的 9 步流水线（含计算列 yoy），扩展为 `["2025", "2024"]`。如果只是纯渲染测试不需要 yoy，把 `time_info` 改回 `["2025"]` 即可——步骤 7-8 会跳过。

---

## 1. MD 定义

存为 `/mnt/user-data/uploads/report.md`：

```markdown
# 王益联社 2025 年度经营报表

## 第一章: 经营规模

### 报表: 商户数多视角对比

> 机构: branch_num=27020199; branch_short_name=王益联社
> 时期: time_info=["2025", "2024"]
> 计算:
>   商户数同比 = 本期BAS_0263减去年同期再除同期
>   商户数同比.示例: BAS_0263[current=1420, yoy_same=1200] -> 0.1833

<table>
  <thead>
    <tr>
      <th rowspan="2">季度</th>
      <th colspan="3">商户类指标</th>
      <th rowspan="2" data-unit="%">{{商户数同比}}</th>
    </tr>
    <tr>
      <th data-idx="BAS_0263" data-unit="个">贷款收单商户数</th>
      <th data-idx="BAS_0263" data-unit="个">贷款收单商户数</th>
      <th data-idx="BAS_0263" data-unit="个">贷款收单商户数</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td>2025-12-31</td>
      <td></td><td></td><td></td><td></td>
    </tr>
    <tr>
      <td>2024-12-31</td>
      <td></td><td></td><td></td><td></td>
    </tr>
  </tbody>
</table>
```

**MD 语法约定**：

- **真实指标列**：`<th data-idx="BAS_0263" data-unit="个">贷款收单商户数</th>` —— `data-idx` 携带 SQLBot ID，单元格内容 = 显示用的中文名。render_docx 直接从 MD 读 idx_name，**不再调 SQLBot**
- **计算列**：`<th data-unit="%">{{商户数同比}}</th>` —— 没有 `data-idx`，`{{虚拟名}}` 必须在 `> 计算:` 块左侧出现
- **多级表头**：父级 `<th>` 用 `rowspan`/`colspan`，可无 `data-idx`（纯分类标签）；叶子 `<th>` 才有 `data-idx` 或 `{{虚拟名}}`

设计意图：

- **3 个相同指标列** → 演示"指标去重 + 多列共享同值"逻辑（实际只发 1 次 HTTP）
- **1 个计算列** → 演示 LLM 生成 pandas 代码 + 真实数据跑通
- **2 行 tbody** → 一行 current、一行 yoy_same
- **多级表头** → 演示 rowspan/colspan + 父级无 data-idx 的合法用法

---

## 2. 9 步流水线详解

### Step 1：读取 MD

```bash
bash: cat /mnt/user-data/uploads/report.md
```

→ lead agent 把原文读到上下文。

---

### Step 2：md_lint.py 校验

```bash
python /mnt/skills/public/chatbi-report/scripts/md_lint.py /mnt/user-data/uploads/report.md
```

校验结果（写到 `report.query.log`）：

```
[lint] ✓ 每张报表含 > 机构: 块
[lint] ✓ 每张报表含 > 时期: 块
[lint] ✓ HTML table 闭合（<thead> + <tbody> 都有）
[lint] ✓ 所有真实指标列含 data-idx 属性（4 列：3×BAS_0263 + 1×计算列无 data-idx）
[lint] ✓ data-idx 格式 ^[A-Z]+_\d+$（BAS_0263 合法）
[lint] ✓ data-unit "个" / "%" 在枚举值内
[lint] ✓ > 计算: 块每行格式合法
[lint] ✓ 表头计算列名"商户数同比"出现在 > 计算: 左侧
[lint] ✓ 计算列无 data-idx 属性（lint 区分真实指标 vs 计算列）
[lint] ✓ 多级表头合法（rowspan=2 + colspan=3 解析通过）
[lint] ⚠️ WARN: BAS_0263 在表头出现 3 次（去重后只 1 次 HTTP 查询）
[lint] → pass
```

如果 lint 通过，进入 step 3；如果不通过，F1 中断。

---

### Step 3：parse_md.py → AST

```bash
python /mnt/skills/public/chatbi-report/scripts/parse_md.py /mnt/user-data/uploads/report.md
```

输出 JSON AST：

```json
{
  "title": "王益联社 2025 年度经营报表",
  "sections": [
    {
      "section_id": "sec_001",
      "title": "第一章: 经营规模",
      "reports": [
        {
          "report_id": "rpt_001",
          "title": "商户数多视角对比",
          "org_context": {
            "branch_num": "27020199",
            "branch_short_name": "王益联社"
          },
          "time_info": ["2025", "2024"],
          "headers": [
            [
              {"text": "季度",          "rowspan": 2, "is_indicator": false, "is_computed": false},
              {"text": "商户类指标",    "colspan": 3, "is_indicator": false, "is_computed": false},
              {"text": "商户数同比",    "rowspan": 2, "is_indicator": false, "is_computed": true, "data_unit": "%"}
            ],
            [
              {"text": "贷款收单商户数", "idx_id": "BAS_0263", "is_indicator": true, "is_computed": false, "data_unit": "个"},
              {"text": "贷款收单商户数", "idx_id": "BAS_0263", "is_indicator": true, "is_computed": false, "data_unit": "个"},
              {"text": "贷款收单商户数", "idx_id": "BAS_0263", "is_indicator": true, "is_computed": false, "data_unit": "个"}
            ]
          ],
          "tbody_template": [
            {"data_dt": "2025-12-31", "org_ecd": "王益联社"},
            {"data_dt": "2024-12-31", "org_ecd": "王益联社"}
          ],
          "computed_specs": [
            {
              "name": "商户数同比",
              "prompt": "本期BAS_0263减去年同期再除同期",
              "examples": [
                {"inputs": {"BAS_0263": {"current": 1420, "yoy_same": 1200}}, "expected": "0.1833"}
              ]
            }
          ]
        }
      ]
    }
  ],
  "all_idx_ids": ["BAS_0263"]
}
```

**关键观察**：

- `headers` 是**二维数组**（每行一个数组），对应 MD `<thead>` 的多级结构
- `text` 字段 = MD 单元格内容（如 "贷款收单商户数" / "商户类指标"），render 时**直接显示**
- `idx_id` 来自 `data-idx` 属性；`text` 是中文显示名 —— **两者完全解耦**，不再需要 SQLBot lookup
- `all_idx_ids` 已经**去重**——3 个相同 idx_id 在内部只算 1 个

---

### Step 4：组织 SQLBot 查询参数

```python
query_params = {
    "org_info":   [{"branch_num": "27020199", "branch_short_name": "王益联社"}],
    "index_info": [{"idx_id": "BAS_0263"}],   # ← 去重后只有 1 个
    "time_info":  ["2025", "2024"]
}
```

---

### Step 5：per-idx HTTP 查询（asyncio.gather 并行）

本例只有 1 个 idx_id，所以只发 1 次 HTTP。如果有 N 个 idx_id，并行 N 次。

```python
import requests

resp = requests.post(
    "http://9.6.232.51:9070/api/v1/indicator/query-report-info",
    json={
        "org_info":   [{"branch_num": "27020199", "branch_short_name": "王益联社"}],
        "index_info": [{"idx_id": "BAS_0263"}],
        "time_info":  ["2025", "2024"]
    },
    headers={"Content-Type": "application/json"},   # 无 Authorization
    timeout=30
)
```

**SQLBot 响应**（假设返回 2 行）：

```json
{
  "code": 0,
  "data": [
    {
      "success": true,
      "msg": "指标数据查询成功。",
      "record_id": 0,
      "sql": "[...]",
      "data": [
        {
          "data_dt": "2025-12-31",
          "org_ecd": "王益联社",
          "idx_name": "贷款收单商户数",
          "value": "1,420.00"
        },
        {
          "data_dt": "2024-12-31",
          "org_ecd": "王益联社",
          "idx_name": "贷款收单商户数",
          "value": "1,200.00"
        }
      ],
      "data_interpret": "...",
      "fields": [
        {"name": "日期", "value": "data_dt"},
        {"name": "机构名称", "value": "org_ecd"},
        {"name": "指标名称", "value": "idx_name"},
        {"name": "指标值", "value": "value"}
      ],
      "chart": {
        "type": "table",
        "title": "columns",
        "columns": [
          {"name": "日期", "value": "data_dt"},
          {"name": "机构名称", "value": "org_ecd"},
          {"name": "指标名称", "value": "idx_name"}
        ]
      }
    }
  ]
}
```

**日志输出**：

```
[step 5] query_report_info: per-idx parallel, 1 idx_ids × 1 org × 2 times → 1 HTTP call
[step 5] query_report_info: BAS_0263 → HTTP 200, code=0, 2 data rows (data_dt=2025-12-31, 2024-12-31)
```

`chart` / `fields` 字段**不消费**，只记录在 log 里（按 spec「chart 字段处理」section 的决策）。

> **注意**：SQLBot 响应里的 `idx_name` 字段在新方案下**不消费**——中文名已在 MD 里写明，render_docx 不依赖 SQLBot 拿 idx_name。

---

### Step 6：长表 → 宽表透视

```python
# 1. 铺平 lookup（key = idx_id, data_dt, org_ecd）
lookup = {
    ("BAS_0263", "2025-12-31", "王益联社"): "1,420.00",
    ("BAS_0263", "2024-12-31", "王益联社"): "1,200.00",
}

# 2. 按 tbody 模板生成 wide_rows（按多级表头的叶子行迭代）
wide_rows = [
    {
        "data_dt":   "2025-12-31",
        "org_ecd":   "王益联社",
        "raw_cells": {"BAS_0263": "1420.00"},   # 千分位已去除
        "cells":     {"BAS_0263": "1420"},       # data-unit="个" → 不换算
        # ↑ 注意：3 个叶子表头都引用 BAS_0263，cells 里只 1 个 key；
        #   渲染时按叶子表头顺序依次填同一个值
    },
    {
        "data_dt":   "2024-12-31",
        "org_ecd":   "王益联社",
        "raw_cells": {"BAS_0263": "1200.00"},
        "cells":     {"BAS_0263": "1200"},
    },
]
```

**关键点**：

- 透视层只遍历 `headers` 的**叶子行**（最底层的数组），父级（带 `rowspan/colspan` 的分类标签）只用于渲染表头分组，不参与数据列
- 3 个相同 idx_id 的叶子表头**共享同一个 raw_cells 值**——透视层只按 idx_id 查一次；渲染时按叶子表头顺序填同样的值
- idx_name 已在 MD 里写明，**不需要再从 SQLBot 响应里抽**

---

### Step 7：计算列 IR 提取（batched LLM）

```python
llm_prompt = """
表头 idx_id 列表: ["BAS_0263"]

计算列定义:
  商户数同比 = 本期BAS_0263减去年同期再除同期

请输出 IR（JSON）:
"""
```

LLM 响应（理想情况）：

```json
{
  "columns": [
    {
      "name": "商户数同比",
      "formula_repr": "(current(BAS_0263) - yoy_same(BAS_0263)) / yoy_same(BAS_0263)",
      "base_idx_ids": ["BAS_0263"],
      "periods": ["current", "yoy_same"]
    }
  ]
}
```

**校验**：base_idx_ids = `["BAS_0263"]` 在 step 5 已查询集合 → 通过；否则 F12。

---

### Step 8：计算列代码生成 + 验证

```python
codegen_prompt = """
生成 compute_rpt_001_shsy_tongbi(df: pd.DataFrame) -> pd.Series 函数。

df 列:
  - data_dt: pd.Timestamp 列
  - BAS_0263: float 列

公式: (current - yoy_same) / yoy_same

要求返回:
  1. 函数体（5-10 行 pandas 代码）
  2. 3 行烟雾数据（rows = [data_dt, current, yoy_same] 三种情况）
"""
```

LLM 生成的代码（追加到 `report.computed.py`）：

```python
def compute_rpt_001_shsy_tongbi(df: pd.DataFrame) -> pd.Series:
    """(current - yoy_same) / yoy_same"""
    df = df.sort_values("data_dt").reset_index(drop=True)
    if len(df) < 2:
        return pd.Series([float("nan")] * len(df))
    current = df["BAS_0263"].iloc[-1]
    yoy_same = df["BAS_0263"].iloc[-2]
    if yoy_same == 0:
        return pd.Series([float("nan")] * len(df))
    growth = (current - yoy_same) / yoy_same
    return pd.Series([growth] * len(df))


# 烟雾数据（LLM 同时返回）
_SMOKE_ROWS = [
    {"data_dt": "2023-12-31", "BAS_0263": 1000.0},
    {"data_dt": "2024-12-31", "BAS_0263": 1000.0},   # 同期
    {"data_dt": "2025-12-31", "BAS_0263": 1200.0},   # 当前
]
```

**验证流水**：

1. **AST 白名单校验**：仅 BinOp / Subscript / Call / Constant → ✓ 通过
2. **签名校验**：函数名 = `compute_rpt_001_shsy_tongbi`，参数 `(df: pd.DataFrame)`，返回 `pd.Series` → ✓ 通过
3. **sandbox 烟雾跑**：

   ```python
   df_smoke = pd.DataFrame(_SMOKE_ROWS)
   out = compute_rpt_001_shsy_tongbi(df_smoke)
   assert isinstance(out, pd.Series)
   assert len(out) == 3
   ```

   → ✓ 通过

4. **示例 assert**（用户提供 `.示例:`）：

   ```python
   # inputs: BAS_0263[current=1420, yoy_same=1200] → expected: 0.1833
   df_test = pd.DataFrame([
       {"data_dt": "2024-12-31", "BAS_0263": 1200.0},
       {"data_dt": "2025-12-31", "BAS_0263": 1420.0},
   ])
   out = compute_rpt_001_shsy_tongbi(df_test)
   assert math.isclose(out.iloc[-1], Decimal("0.1833"), rel_tol=1e-6)
   ```

   → ✓ 通过

---

### Step 9：单位换算 + 渲染三件套

#### 9a. 跑计算列

```python
for row in wide_rows:
    df_input = build_df_for_row(row, all_wide_rows, periods=["current", "yoy_same"])
    row["cells"]["商户数同比"] = compute_rpt_001_shsy_tongbi(df_input).iloc[-1]

# wide_rows 最终形态：
# [
#   {"data_dt": "2025-12-31", "org_ecd": "王益联社",
#    "cells": {"BAS_0263": "1420", "商户数同比": "0.1833"},
#    "raw_cells": {"BAS_0263": "1420.00"}},
#   {"data_dt": "2024-12-31", "org_ecd": "王益联社",
#    "cells": {"BAS_0263": "1200", "商户数同比": null},   # ← yoy 视角无同期
#    "raw_cells": {"BAS_0263": "1200.00"}},
# ]
```

#### 9b. JSON 输出（`report.json`）

```json
{
  "title": "王益联社 2025 年度经营报表",
  "report_id": "rpt_001_uuid",
  "sections": [
    {
      "section_id": "sec_001",
      "title": "第一章: 经营规模",
      "reports": [
        {
          "report_id": "rpt_001",
          "title": "商户数多视角对比",
          "org_context": {"branch_num": "27020199", "branch_short_name": "王益联社"},
          "time_info": ["2025", "2024"],
          "headers": [
            [
              {"text": "季度",          "rowspan": 2, "is_indicator": false, "is_computed": false},
              {"text": "商户类指标",    "colspan": 3, "is_indicator": false, "is_computed": false},
              {"text": "商户数同比",    "rowspan": 2, "is_indicator": false, "is_computed": true, "data_unit": "%"}
            ],
            [
              {"text": "贷款收单商户数", "idx_id": "BAS_0263", "is_indicator": true, "is_computed": false, "data_unit": "个"},
              {"text": "贷款收单商户数", "idx_id": "BAS_0263", "is_indicator": true, "is_computed": false, "data_unit": "个"},
              {"text": "贷款收单商户数", "idx_id": "BAS_0263", "is_indicator": true, "is_computed": false, "data_unit": "个"}
            ]
          ],
          "data": [
            {
              "data_dt": "2025-12-31",
              "org_ecd": "王益联社",
              "raw_cells": {"BAS_0263": "1420.00"},
              "cells":     {"BAS_0263": "1420",  "商户数同比": "0.1833"}
            },
            {
              "data_dt": "2024-12-31",
              "org_ecd": "王益联社",
              "raw_cells": {"BAS_0263": "1200.00"},
              "cells":     {"BAS_0263": "1200",  "商户数同比": null}
            }
          ],
          "indicators": [
            {"idx_id": "BAS_0263", "is_computed": false, "raw_unit": "个", "display_unit": "个", "scale_factor": "1", "data_type": "number"},
            {"idx_id": "商户数同比", "is_computed": true,
             "compute_spec": {
               "prompt": "本期BAS_0263减去年同期再除同期",
               "function": "compute_rpt_001_shsy_tongbi",
               "base_idx_ids": ["BAS_0263"],
               "periods": ["current", "yoy_same"],
               "examples": [{"inputs": {"BAS_0263": {"current": 1420, "yoy_same": 1200}}, "expected": "0.1833"}],
               "validation": {
                 "ast_check": "passed", "signature_check": "passed",
                 "smoke_run": "passed", "example_check": "passed"
               }
             }
            }
          ]
        }
      ]
    }
  ],
  "metadata": {
    "generated_at": "2026-06-23T17:52:00",
    "total_indicators": 4,
    "queried_count": 1,
    "unqueried_count": 0,
    "computed_count": 1,
    "query_failures": 0,
    "compute_validation_failures": 0,
    "duration_seconds": 1.23
  },
  "computed_code": {
    "file": "report.computed.py",
    "function_names": ["compute_rpt_001_shsy_tongbi"]
  }
}
```

**对比旧版**：JSON 里 `headers[].text` 现在直接是中文名（"贷款收单商户数"），不再需要从 SQLBot 响应里抽 `idx_name`。render_docx 完全离线读 JSON。

#### 9c. DOCX 结构

```
report.docx
├── 标题: 王益联社 2025 年度经营报表（H1, 微软雅黑 18pt）
└── 第一章: 经营规模（H2, 微软雅黑 14pt）
    └── 商户数多视角对比（H3, 微软雅黑 12pt）
        └── 数据表（python-docx Table）
            ├── 表头（多级合并，单元格文字直接来自 JSON headers[].text）：
            │   ┌─────────┬───────────────────────────┬──────────┐
            │   │         │      商户类指标          │ 商户数同比 │
            │   │  季度   │      (colspan=3)         │ (rowspan=2)│
            │   │(rowspan)├────────┬────────┬────────┤    (%)    │
            │   │   =2   │贷款收单│贷款收单│贷款收单│ (computed)│
            │   │        │商户数  │商户数  │商户数  │           │
            │   │        │  (个)  │  (个)  │  (个)  │           │
            │   ├────────┼────────┼────────┼────────┼──────────┤
            │   │2025-12-31│ 1,420 │ 1,420 │ 1,420 │   18.33% │
            │   │2024-12-31│ 1,200 │ 1,200 │ 1,200 │     —    │  ← yoy 视角无同期
            │   └─────────┴────────┴────────┴────────┴──────────┘
            └── 表头副标：每个叶子单元格下方显示 data_unit（小一号字 + 灰色 #666666）
```

**渲染要点**：

- 叶子表头的**主标文字**直接从 `headers[最后一层][col].text` 读（"贷款收单商户数"）
- 副标 = `data_unit`（如 "个" / "%"）
- 多级表头合并靠 `cell.merge()` + `rowspan/colspan`（从 AST 里读）
- 不需要查 SQLBot、不需要解析 idx_name

#### 9d. 回填 MD（`report.md`）

```markdown
# 王益联社 2025 年度经营报表

## 第一章: 经营规模

### 报表: 商户数多视角对比

> 机构: branch_num=27020199; branch_short_name=王益联社
> 时期: time_info=["2025", "2024"]
> 计算:
>   商户数同比 = 本期BAS_0263减去年同期再除同期
>   商户数同比.示例: BAS_0263[current=1420, yoy_same=1200] -> 0.1833

| 季度 | 贷款收单商户数 (个) | 贷款收单商户数 (个) | 贷款收单商户数 (个) | 商户数同比 (%) |
|------|----------|----------|----------|---------|
| 2025-12-31 | 1,420 | 1,420 | 1,420 | 18.33% |
| 2024-12-31 | 1,200 | 1,200 | 1,200 | — |
```

**对比旧版**：回填 MD 的表头直接显示"贷款收单商户数 (个)"，不再嵌入 `(BAS_0263)` —— 中文名 + 单位就够了。

#### 9e. status.json

```json
{
  "status": "success",
  "exit_step": 9,
  "error_class": null,
  "error_detail": null,
  "outputs": {
    "json": "/mnt/user-data/outputs/{thread_id}/report.json",
    "docx": "/mnt/user-data/outputs/{thread_id}/report.docx",
    "md":   "/mnt/user-data/outputs/{thread_id}/report.md"
  },
  "metrics": {
    "queried_count": 1,
    "query_failures": 0,
    "computed_count": 1,
    "compute_validation_failures": 0,
    "llm_calls": 2,
    "duration_seconds": 1.23
  }
}
```

---

## 关键观察

| 问题 | 答案 |
|------|------|
| **3 个相同 idx_id → 几次 HTTP？** | **1 次**（去重在 AST 层就完成） |
| **3 列渲染什么值？** | 共享同一个 `cells["BAS_0263"]`，3 列填同一值 |
| **计算列 yoy 数据从哪来？** | 同一 idx_id 不同 `data_dt` 的两行（2025 vs 2024），由 `time_info=["2025", "2024"]` 让 SQLBot 一起返回 |
| **chart 字段用了没？** | 没用，只写 log；以 MD schema 为唯一事实源 |
| **idx_id ↔ 数据怎么对应？** | per-idx HTTP 调用 → 1:1 映射零歧义 |
| **2024-12-31 的 yoy 值为什么是 `—`？** | yoy 视角需要更早一年（2023）的数据，本例 `time_info` 没要 2023 → 计算列输出 NaN → 渲染为 `—` |
| **中文名"贷款收单商户数"从哪来？** | **直接从 MD 单元格的文本读**（`<th>贷款收单商户数</th>`），render_docx 不调 SQLBot |
| **多级表头如何渲染？** | 父级 `<th rowspan/colspan>` 走 cell.merge()；叶子 `<th>` 一一对应数据列 |

---

## MD 语法速查（给设计师参考）

| 模式 | 写法 | 何时用 |
|------|------|--------|
| 真实指标列 | `<th data-idx="BAS_0263" data-unit="个">贷款收单商户数</th>` | 99% 场景 |
| 计算列 | `<th data-unit="%">{{商户数同比}}</th>` | 同比/环比/毛利率等 |
| 多级分类 | `<th colspan="3">商户类指标</th>` | 报表表头分组 |
| 旧占位符（兼容） | `<th data-unit="个">{{BAS_0263}}</th>` | 老 MD；lint WARN 不阻断，渲染时回退到 SQLBot lookup |

**`> 机构:` / `> 时期:` / `> 计算:` 块**：必填 `> 机构:` 和 `> 时期:`；计算列必须在 `> 计算:` 块左侧声明公式。

**`data-unit` 合法值**：`元 / 万元 / 亿元 / % / 百分点 / 个 / 次 / 自定义字符串`。

---

## 边界场景

| 场景 | 行为 |
|------|------|
| 3 个 idx_id 全部相同（如本例） | 去重为 1 次 HTTP，3 列共享值 |
| 3 个 idx_id 各不相同 | 3 次并行 HTTP，3 列各取各值 |
| 1 个 idx_id 查询失败（F18） | 该 idx 列标 ⚠️QUERY_FAILED，其他 idx 继续 |
| 整批 HTTP 失败（F17） | 中断，status=error |
| 计算列 base 引用未查询的 idx_id（F12） | 该计算列标 compute_base_missing，status=partial |
| LLM codegen 失败（F13/F14/F15） | 该计算列标 compute_*_failed，status=partial |
| idx_id 不符合 `^[A-Z]+_\d+$`（F1 lint） | 中断，lint 报错 |
| 设计师仍用旧 `{{BAS_0263}}` 占位符写法 | lint WARN 不阻断；render 时回退到 SQLBot lookup `idx_name` |

整个流程跑下来：1 次 HTTP + 2 次 LLM 调用（IR + codegen），总耗时约 1.2 秒（实际取决于 LLM 延迟）。
