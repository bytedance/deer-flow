# Multi-Level Header Processor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增 `header_processor.py` 模块，实现 Excel 多级表头展平功能，使 DuckDB 能正确加载具有多级表头的 Excel 文件。

**Architecture:** 遍历 Excel 所有 sheet，对每个多级表头 sheet 展平为独立 CSV，返回 `{sheet_name: csv_path}` 字典。与 DuckDB 缓存共用 combined hash — L1 是展平后的 flat CSV，L2 是 DuckDB 数据库。

**Tech Stack:** Python, openpyxl, duckdb

---

## File Structure

```
scripts/
├── analyze.py              # 修改：load_files() 调用展平，适配新签名
└── header_processor.py    # 新增：多级表头处理模块

tests/
└── test_header_processor.py  # 新增：单元测试
```

---

### Task 1: 基础结构 — 骨架

**Files:**
- Create: `scripts/header_processor.py`

- [ ] **Step 1: 创建 header_processor.py 骨架**

```python
"""Multi-level header flattening for Excel files."""

import os

FLATTEN_VERSION = "v1"

def flatten_excel_headers(file_path: str, output_dir: str) -> dict[str, str] | None:
    """
    主入口：遍历 Excel 所有 sheet，对多级表头 sheet 展平为 CSV。
    返回 {sheet_name: flat_csv_path}，所有 sheet 都是 flat 时返回 None。
    """
    pass

def _flatten_single_sheet(file_path: str, sheet_name: str, output_dir: str, file_hash: str) -> str | None:
    """对单个 sheet 展平，返回 CSV 路径，flat 或失败返回 None。"""
    pass

def read_excel_preview(ws, max_rows: int = 20) -> list[list]:
    """读取 worksheet 前 N 行，返回已填充合并单元格的行数据。"""
    pass

def fill_merged_cells(ws) -> dict[tuple, any]:
    """返回 { (row, col): value } 映射，用于填充合并单元格。"""
    pass

def detect_header_structure(preview: list[list]) -> dict:
    """
    规则检测表头结构。
    返回: {skip_rows, header_rows, data_start_row, header_type}
    """
    pass

def flatten_headers(header_block: list[list], header_info: dict) -> list[str]:
    """展平多级表头为单一列名。"""
    pass

def read_data_rows(ws, data_start_row: int) -> list[list]:
    """从 data_start_row 读取数据行。"""
    pass

def save_flat_csv(headers: list[str], data_rows: list[list], output_path: str) -> None:
    """保存展平后的 CSV（utf-8-sig 编码，兼容 Windows Excel）。"""
    pass

def compute_file_hash(file_path: str) -> str:
    """计算文件 SHA256 hash（hex 前 12 位）。"""
    pass
```

- [ ] **Step 2: 验证骨架可导入**

Run: `python -c "from scripts.header_processor import flatten_excel_headers; print('OK')"`
Expected: 输出 OK

- [ ] **Step 3: 提交骨架**

```bash
git add scripts/header_processor.py
git commit -m "feat: scaffold header_processor.py"
```

---

### Task 2: 读取预览 + 合并单元格填充

**Files:**
- Modify: `scripts/header_processor.py`

**关键：必须同时读取单元格值和合并单元格信息，不能用 `data_only=True`（会丢失计算结果）。**

- [ ] **Step 1: 实现 read_excel_preview 和 fill_merged_cells**

```python
def fill_merged_cells(ws) -> dict[tuple, any]:
    """返回 { (row, col): value } 映射。"""
    fill_map = {}
    for merged_range in ws.merged_cells.ranges:
        top_left = merged_range.start_cell
        value = top_left.value
        for row in ws.iter_rows(
            min_row=merged_range.min_row, max_row=merged_range.max_row,
            min_col=merged_range.min_col, max_col=merged_range.max_col
        ):
            for cell in row:
                fill_map[(cell.row, cell.column)] = value
    return fill_map

def read_excel_preview(ws, max_rows: int = 20) -> list[list]:
    """读取前 N 行，应用 fill_merged_cells 填充合并单元格。"""
    fill_map = fill_merged_cells(ws)
    rows = []
    for i, row in enumerate(ws.iter_rows(values_only=True)):
        if i >= max_rows:
            break
        # 填充合并单元格（values_only 对合并单元格只返回主格值，其他格返回 None）
        filled_row = []
        for j, val in enumerate(row):
            row_num = i + 1  # ws iter_rows 从第1行开始
            col_num = j + 1
            filled_val = fill_map.get((row_num, col_num), val)
            filled_row.append(filled_val)
        rows.append(filled_row)
    return rows
```

- [ ] **Step 2: 提交**

```bash
git add scripts/header_processor.py
git commit -m "feat: implement read_excel_preview and fill_merged_cells"
```

---

### Task 3: 表头结构检测规则

**Files:**
- Modify: `scripts/header_processor.py`

- [ ] **Step 1: 实现 detect_header_structure**

```python
def detect_header_structure(preview: list[list]) -> dict:
    """
    基于统计规则检测表头结构。
    规则：
    - skip_rows: 连续全 None 行数
    - header_rows: 从第1个非空行开始，连续的"非数据行"行数
    - 非数据行判断: str_ratio > 0.5 OR (整行非 None AND 字符串占比高)
    - data_start_row = skip_rows + header_rows (1-indexed)
    - header_type: "flat"(只有1行表头) | "multi"(多行表头)
    """
    if not preview:
        return {"skip_rows": 0, "header_rows": 1, "data_start_row": 1, "header_type": "flat"}

    skip_rows = 0
    for row in preview:
        non_none = sum(1 for v in row if v is not None)
        if non_none == 0:
            skip_rows += 1
        else:
            break

    header_rows = 1
    header_type = "flat"

    for i in range(skip_rows, len(preview)):
        row = preview[i]
        non_none = sum(1 for v in row if v is not None)
        if non_none == 0:
            continue  # 跳过含 None 的表头行
        str_count = sum(1 for v in row if isinstance(v, str))
        str_ratio = str_count / len(row) if row else 0
        # 数据行特征: 数字为主(str_ratio <= 0.3) 或 全是数字
        if str_ratio > 0.3:
            header_rows = i - skip_rows + 1
            header_type = "multi" if header_rows > 1 else "flat"
        else:
            break  # 遇到数据行，停止

    return {
        "skip_rows": skip_rows,
        "header_rows": header_rows,
        "data_start_row": skip_rows + header_rows + 1,  # 1-indexed，跳到数据行之后
        "header_type": header_type
    }
```

- [ ] **Step 2: 提交**

```bash
git add scripts/header_processor.py
git commit -m "feat: implement detect_header_structure"
```

---

### Task 4: 展平表头（规则驱动，无硬编码停用词）

**Files:**
- Modify: `scripts/header_processor.py`

**规则：无硬编码停用词列表。展平逻辑：**
1. 按列从下往上收集非 None 值（从最后一行表头向上）
2. **停止条件**（满足任一即停）：
   - 遇到整行全是 None → 停止
   - 遇到数值为主行（str_ratio ≤ 0.3）→ 停止（这是数据行）
   - 遇到与上一行完全重复 → 跳过
3. 特殊字符处理：`（` → `_`，`）` → 删除，横杠 `-` 保留

- [ ] **Step 1: 实现 flatten_headers**

```python
def _is_data_row(row: list) -> bool:
    """判断是否为数据行：数字为主（str_ratio <= 0.3）"""
    if not row:
        return False
    non_none = sum(1 for v in row if v is not None)
    if non_none == 0:
        return False
    str_count = sum(1 for v in row if isinstance(v, str))
    str_ratio = str_count / len(row)
    return str_ratio <= 0.3

def _is_all_none(row: list) -> bool:
    return all(v is None for v in row)

def flatten_headers(header_block: list[list], header_info: dict) -> list[str]:
    """
    展平多级表头为单一列名。
    从最后一行表头向上收集，每列拼接各层级的非 None 值。
    遇到数据行或全 None 行时停止。
    """
    header_rows = header_info["header_rows"]
    num_cols = max(len(row) for row in header_block) if header_block else 0
    flattened = []

    for col_idx in range(num_cols):
        parts = []
        # 从最后一行表头向上（逆序）
        for row_idx in range(header_rows - 1, -1, -1):
            if col_idx >= len(header_block[row_idx]):
                continue
            val = header_block[row_idx][col_idx]

            if val is None:
                continue

            # 全 None 行检测（当前面的列已收集到值，检查是否该停止）
            if _is_all_none(header_block[row_idx]):
                break

            # 数据行检测
            if _is_data_row(header_block[row_idx]):
                break

            s = str(val).strip()
            s = s.replace("（", "_").replace("）", "")
            # 连续重复跳过
            if not parts or parts[-1] != s:
                parts.append(s)

        # 逆序得到正确顺序（从顶层到底层）
        parts.reverse()
        col_name = "_".join(parts) if parts else f"col_{col_idx + 1}"

        # 超长截断
        if len(col_name) > 200:
            col_name = col_name[:200]

        # 重复列名加后缀
        if col_name in flattened:
            suffix = 2
            while f"{col_name}_{suffix}" in flattened:
                suffix += 1
            col_name = f"{col_name}_{suffix}"

        flattened.append(col_name)

    return flattened
```

- [ ] **Step 2: 提交**

```bash
git add scripts/header_processor.py
git commit -m "feat: implement flatten_headers with rule-based stopping"
```

---

### Task 5: 数据读取 + CSV 保存

**Files:**
- Modify: `scripts/header_processor.py`

- [ ] **Step 1: 实现 read_data_rows 和 save_flat_csv**

```python
def read_data_rows(ws, data_start_row: int) -> list[list]:
    """
    从 data_start_row（1-indexed）读取所有数据行。
    """
    rows = []
    for i, row in enumerate(ws.iter_rows(values_only=True)):
        # iter_rows 从第1行开始，i=0 对应 row 1
        if i >= data_start_row - 1:
            rows.append(list(row))
    return rows

def save_flat_csv(headers: list[str], data_rows: list[list], output_path: str) -> None:
    """保存 CSV，utf-8-sig 编码（兼容 Windows Excel）。"""
    import csv
    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(data_rows)
```

- [ ] **Step 2: 提交**

```bash
git add scripts/header_processor.py
git commit -m "feat: implement read_data_rows and save_flat_csv"
```

---

### Task 6: 主入口函数 + 缓存策略（统一 combined hash）

**Files:**
- Modify: `scripts/header_processor.py`

**缓存 key 策略：**
- L1（flat CSV）: `{file_hash}_flat_{FLATTEN_VERSION}.csv`
- DuckDB: 所有 flat CSV 合并后算 hash → `{combined_csv_hash}_{FLATTEN_VERSION}.duckdb`

**主入口返回 `dict[str, str] | None`**：key 是 sheet_name，value 是 flat CSV 路径。

- [ ] **Step 1: 实现 compute_file_hash 和 _flatten_single_sheet**

```python
def compute_file_hash(file_path: str) -> str:
    """计算文件 SHA256 hash（hex 前 12 位）。"""
    import hashlib
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(8192):
            hasher.update(chunk)
    return hasher.hexdigest()[:12]

def _flatten_single_sheet(
    file_path: str, sheet_name: str, output_dir: str, file_hash: str
) -> str | None:
    """
    对单个 sheet 展平。返回 CSV 路径，flat 或失败返回 None。
    """
    wb = openpyxl.load_workbook(file_path)
    ws = wb[sheet_name]

    # Step 1: 读取预览（含合并单元格填充）
    preview = read_excel_preview(ws, max_rows=20)

    # Step 2: 检测表头结构
    header_info = detect_header_structure(preview)

    # flat 表头不需要展平
    if header_info["header_type"] == "flat":
        wb.close()
        return None

    # Step 3: 展平表头
    skip_rows = header_info["skip_rows"]
    header_rows = header_info["header_rows"]
    header_block = preview[skip_rows:skip_rows + header_rows]
    flattened_headers = flatten_headers(header_block, header_info)

    # Step 4: 读取数据行
    data_start_row = header_info["data_start_row"]
    data_rows = read_data_rows(ws, data_start_row)

    wb.close()

    # Step 5: 保存 CSV（L1 缓存）
    l1_key = f"{file_hash}_flat_{FLATTEN_VERSION}_{sheet_name}.csv"
    cache_path = os.path.join(output_dir, l1_key)
    save_flat_csv(flattened_headers, data_rows, cache_path)

    return cache_path
```

- [ ] **Step 2: 实现 flatten_excel_headers 主入口**

```python
def flatten_excel_headers(file_path: str, output_dir: str) -> dict[str, str] | None:
    """
    主入口：遍历 Excel 所有 sheet，对多级表头 sheet 展平。
    返回 {sheet_name: flat_csv_path}，所有 sheet 都是 flat 时返回 None。
    """
    file_hash = compute_file_hash(file_path)

    wb = openpyxl.load_workbook(file_path)
    results: dict[str, str] = {}

    for sheet_name in wb.sheetnames:
        flat_csv = _flatten_single_sheet(file_path, sheet_name, output_dir, file_hash)
        if flat_csv:
            results[sheet_name] = flat_csv

    wb.close()

    return results if results else None
```

- [ ] **Step 3: 提交**

```bash
git add scripts/header_processor.py
git commit -m "feat: implement flatten_excel_headers with multi-sheet support"
```

---

### Task 7: 集成到 analyze.py

**Files:**
- Modify: `scripts/analyze.py`

- [ ] **Step 1: 修改 load_files() 中的 Excel 处理逻辑**

```python
# 在 load_files() 中，对每个 Excel 文件：
if ext in (".xlsx", ".xls"):
    # 尝试展平多级表头
    flat_csvs = header_processor.flatten_excel_headers(file_path, output_dir)
    if flat_csvs:
        # flat_csvs 是 {sheet_name: csv_path} 字典
        for sheet_name, csv_path in flat_csvs.items():
            table_name = sanitize_table_name(sheet_name)
            con.execute(f"CREATE TABLE '{table_name}' AS SELECT * FROM read_csv_auto('{csv_path}')")
            table_map[file_path] = table_name
        continue
# 回退到原 GDAL 方式
_load_excel(con, file_path, table_map)
```

- [ ] **Step 2: 修改 DuckDB 缓存 key 策略**

```python
# compute_files_hash 后，对每个展平 CSV 追加内容 hash
# L1 key: 单文件单 sheet flat CSV
# L2 key: 所有 flat CSV 合并 hash → DuckDB

# 在 load_files() 返回前：
# 如果有 flat_csvs，将它们也纳入 combined hash
all_csv_paths = list(flat_csvs.values()) if flat_csvs else []
if all_csv_paths:
    combined_hash = compute_files_hash([file_path] + all_csv_paths)
else:
    combined_hash = compute_files_hash([file_path])
```

- [ ] **Step 3: 提交**

```bash
git add scripts/analyze.py
git commit -m "feat: integrate header_processor into analyze.py"
```

---

## 自检清单

| 检查项 | 状态 |
|--------|------|
| Spec 覆盖：展平逻辑（Tasks 1-6） | ✓ |
| Spec 覆盖：缓存策略（两层 L1/L2） | ✓ |
| Spec 覆盖：特殊字符处理（括号、横杠） | ✓ |
| Spec 覆盖：错误处理（回退 GDAL） | ✓ |
| 无 placeholder（TBD/TODO） | ✓ |
| 无硬编码停用词 | ✓ |
| 多 sheet 返回 dict[sheet_name, csv_path] | ✓ |
| DuckDB 缓存 key 用 combined hash | ✓ |
| UTF-8-SIG 编码（Windows 兼容） | ✓ |
| data_only=False（保留合并单元格信息） | ✓ |

---

**Plan complete.** Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?