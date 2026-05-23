# Data-Analysis Skill 多级表头处理设计文档

**日期**: 2026-05-23
**版本**: v1
**状态**: 已确认

---

## 1. 背景与目标

### 1.1 当前问题

现有 `analyze.py` 使用 GDAL `st_read()` 加载 Excel，`HEADERS=FORCE` 只能把第一行作为列名，无法处理多级表头结构。

**问题现象**：
- 列名变成 `Field1, Field2...`（无意义）
- 多级表头的层级关系丢失
- 数据分析无法正确识别列的业务含义

### 1.2 目标

在加载 DuckDB 之前，先用 Python + openpyxl 将 Excel 多级表头展平为扁平 CSV，再供 DuckDB 查询。

---

## 2. 设计原则

1. **纯本地运行** — Agent Skill，无需 API Key
2. **规则检测** — 基于行/列统计规则检测表头结构
3. **版本锁定缓存** — 展平逻辑固定版本号，cache key 含版本
4. **职责分离** — 新增 `header_processor.py`，展平逻辑与 DuckDB 加载解耦

---

## 3. 核心流程

```
Excel 文件 (多级表头)
    │
    ▼
[Step1] read_excel_preview()
        读取前 20 行（含合并单元格）
    │
    ▼
[Step2] fill_merged_cells()
        合并单元格填充相同值
    │
    ▼
[Step3] detect_header_rules()
        规则检测 skip_rows, header_rows, data_start_row, header_type
    │
    ▼
[Step4] flatten_headers()
        展平多级表头为单一列名
        • 多级用 `_` 连接
        • `（` → `_`，`）` 去掉
        • 横杠 `-` 保留
        • 连续空行去重
    │
    ▼
[Step5] read_data_rows()
        从 data_start_row 读取数据行
    │
    ▼
[Step6] save_flat_csv()
        保存展平后的 CSV
    │
    ▼
DuckDB 加载展平 CSV
```

---

## 4. 表头展平示例

**输入（3行表头）**：
```
行3: 当月活跃用户数（16-60岁）| 机构编码 | 收单商户数
行4:          人              |          | 期末
行5:           1000           | 27000099 | 603968
```

**输出（展平后）**：
```
当月活跃用户数_16-60岁_人 | 机构编码 | 收单商户数_期末
```

---

## 5. 特殊字符处理规则

| 字符 | 处理方式 |
|------|----------|
| 括号 `（` `）` | `（` → `_`，`）` → 去掉 |
| 横杠 `-` | 保留（如 `16-60岁`） |
| 其他特殊字符 | 原样保留 |

---

## 6. 缓存策略

### 6.1 缓存分层

| 层级 | 内容 | 过期策略 |
|------|------|----------|
| **L1: 展平 CSV** | `{hash}_flat_v{version}.csv` | 基于原文件 hash + 版本号 |
| **L2: DuckDB DB** | `{hash}_v{version}.duckdb` | 基于原文件 hash + 版本号 |

### 6.2 缓存 key 设计

```python
FLATTEN_VERSION = "v1"  # 展平逻辑版本号，改变时自动重建缓存

# Cache key 格式
l1_key = f"{files_hash}_flat_{FLATTEN_VERSION}.csv"
l2_key = f"{files_hash}_{FLATTEN_VERSION}.duckdb"
```

### 6.3 缓存流程

```
Excel 文件
    ↓
[计算: files_hash + FLATTEN_VERSION]
    ↓
[L1 Cache 检查] → 有 CSV → 跳过展平
    ↓ 无
[Step1-6] 展平处理 → 保存 L1
    ↓
[加载到 DuckDB] → 保存 L2
    ↓
后续查询直接用 L2
```

---

## 7. 文件变更

### 7.1 新增文件

```
~/.claude/skills/data-analysis/scripts/
├── analyze.py              # 修改：load_files() 调用展平
└── header_processor.py    # 新增：多级表头处理模块
```

### 7.2 header_processor.py 核心函数

| 函数 | 功能 |
|------|------|
| `read_excel_preview(file_path, sheet_name, max_rows=20)` | 读取预览数据 |
| `fill_merged_cells(ws)` | 合并单元格填充映射 |
| `detect_header_structure(preview)` | 规则检测表头结构 |
| `flatten_headers(preview, header_info)` | 展平表头 |
| `read_data_rows(file_path, sheet_name, header_info)` | 读取数据行 |
| `save_flat_csv(headers, data_rows, output_path)` | 保存 CSV |
| `flatten_excel_headers(file_path, sheet_name, output_dir)` | 主入口，一键完成 |

### 7.3 修改 analyze.py

在 `_load_excel()` 之前调用展平逻辑：

```python
def load_files(con, files):
    for file_path in files:
        if ext in (".xlsx", ".xls"):
            # 先尝试展平
            flat_csv = flatten_excel_headers(file_path, sheet_name, cache_dir)
            if flat_csv:
                _load_csv(con, flat_csv, table_map)  # 加载展平后的 CSV
            else:
                _load_excel(con, file_path, table_map)  # 回退到原 GDAL 方式
        else:
            _load_csv(con, file_path, table_map)
```

---

## 8. 正确性保证

| 规则 | 说明 |
|------|------|
| 连续空行去重 | 同一列连续空值只保留一个 |
| 合并单元格填充 | 每个被合并单元格填入相同值 |
| 列名唯一性 | 重复列名末尾加 `_N` |
| 列名长度限制 | 超过 200 字符截断 |

---

## 9. 错误处理

| 场景 | 处理方式 |
|------|----------|
| 展平失败 | 回退到原 GDAL `st_read()` 方式 |
| 缓存损坏 | 删除损坏缓存，重新生成 |
| 内存不足 | 记录警告，继续处理（部分数据） |

---

## 10. 后续优化（不纳入本次设计）

1. 列名长度限制（≤ 200）
2. UTF-8 BOM 处理
3. 大文件流式处理
4. Parquet 支持
5. 全 NULL 列检测
6. 多 sheet 参数
7. 错误恢复机制

---

## 11. 正确性自检

- [x] 无占位符（TBD/TODO）
- [x] 无矛盾之处
- [x] 范围明确（单文件单 sheet 展平）
- [x] 无歧义（字符处理规则明确）