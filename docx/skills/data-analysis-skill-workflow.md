# Data-Analysis Skill 完整工作流程

**文档版本**：v1.0
**更新日期**：2026-05-25
**Skill 路径**：`/mnt/skills/public/data-analysis/`

---

## 一、文件结构

```
skills/public/data-analysis/
├── SKILL.md                    # Skill 定义（LLM 读取的指令）
├── scripts/
│   ├── analyze.py              # 主入口脚本（DuckDB 分析引擎）
│   └── header_processor.py     # Excel 多级表头展平工具
└── docs/
    └── 2026-05-24-...-debugging.md  # 调试报告
```

---

## 二、整体架构

```
┌─────────────────────────────────────────────────────────────────┐
│                        User (用户)                               │
│            "分析我上传的文件" / "看看数据情况"                    │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Frontend (前端)                               │
│  1. 用户选择文件 → prompt-input.tsx                              │
│  2. 文件转 Blob → data URL                                       │
│  3. 提交消息 → use-thread-chat.ts                               │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│               POST /api/threads/{thread_id}/uploads            │
│                    uploads.py (后端)                             │
│  - 保存文件到 .deer-flow/threads/{thread_id}/uploads/           │
│  - 同步到 sandbox                                                │
│  - 可选：Excel 转 Markdown                                        │
│  - 返回: { filename, size, path, virtual_path }                │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    UploadsMiddleware                            │
│              uploads_middleware.py (before_agent)               │
│  - 读取 additional_kwargs.files                                  │
│  - 扫描 uploads 目录历史文件                                      │
│  - 生成 <uploaded_files> 块注入 HumanMessage                    │
│  - 包含：文件名、大小、路径、文档大纲（outline）                  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Lead Agent (LLM)                           │
│  1. 看到 <uploaded_files> 块                                     │
│  2. 识别文件类型：Excel/CSV                                       │
│  3. 匹配 skill 描述 → 决定使用 data-analysis skill               │
│  4. 调用 read_file(/mnt/skills/public/data-analysis/SKILL.md)   │
│  5. 读取 SKILL.md 获取执行指令                                    │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                        Skill 执行                                │
│                  SKILL.md 中的指令引导                           │
│                                                                  │
│  根据请求复杂度选择执行路径：                                     │
│  ┌─────────┐    ┌─────────┐    ┌─────────┐                     │
│  │ Simple  │    │ Medium  │    │Complex  │                     │
│  │ inspect │    │inspect  │    │inspect  │                     │
│  │   +1句  │    │  +query │    │+overview│                     │
│  │   结束  │    │  +summary│    │+summary │                     │
│  └─────────┘    └─────────┘    │ +query  │                     │
│                                 └─────────┘                     │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    analyze.py (执行器)                          │
│                                                                  │
│  python /mnt/skills/public/data-analysis/scripts/analyze.py    │
│    --files /mnt/user-data/uploads/data.xlsx                     │
│    --action [inspect|query|summary|overview]                    │
│    --sql "SELECT ..." (query 时)                                │
│    --output-file /mnt/user-data/outputs/result.csv              │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                     DuckDB 引擎                                  │
│                                                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │  L1 Cache    │→ │  L2 Cache    │→ │   DuckDB     │          │
│  │ (展平 CSV)   │  │ (DuckDB DB)  │  │  In-Memory   │          │
│  └──────────────┘  └──────────────┘  └──────────────┘          │
│                                                                  │
│  Excel 文件 → header_processor.py 展平 → CSV → DuckDB           │
│  CSV 文件 → 直接加载 → DuckDB                                   │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      结果返回                                    │
│  - 控制台/日志输出                                               │
│  - 返回 JSON/CSV/MD 格式（如果指定 --output-file）               │
│  - Agent 解读结果 → 用户友好的回复                               │
└─────────────────────────────────────────────────────────────────┘
```

---

## 三、详细步骤分解

### Step 1-2：文件上传

```
用户选择文件 → Frontend 转换为 Blob → POST /api/threads/{id}/uploads
→ backend/app/gateway/routers/uploads.py 保存文件
→ 返回 { filename, size, path: "/mnt/user-data/uploads/xxx.xlsx" }
```

**关键文件**：
- `frontend/src/components/ai-elements/prompt-input.tsx` — 文件选择 UI
- `frontend/src/components/workspace/input-box.tsx` — 提交处理
- `frontend/src/core/threads/hooks.ts` — sendMessage + 文件上传
- `backend/app/gateway/routers/uploads.py` — 保存文件到磁盘

### Step 3：UploadsMiddleware 注入上下文

```python
# uploads_middleware.py (before_agent)
<uploaded_files>
The following files were uploaded in this message:
- sales_data.xlsx (1.2 MB)
  Path: /mnt/user-data/uploads/sales_data.xlsx
  Document outline:
    L1: Sales Report 2024
    L15: Monthly Breakdown
...

To work with these files:
- Read from the file first — use the outline line numbers
- Use `grep` to search for keywords
</uploaded_files>
```

**关键文件**：`backend/packages/harness/deerflow/agents/middlewares/uploads_middleware.py`

### Step 4：LLM 识别 Skill

```
系统提示包含：
<skill>
  <name>data-analysis</name>
  <description>Use this skill when the user uploads Excel (.xlsx/.xls)
               or CSV files and wants to perform data analysis...</description>
  <location>/mnt/skills/public/data-analysis/SKILL.md</location>
</skill>

LLM 判断：用户上传了 Excel + 说"分析" → 匹配 data-analysis skill
→ 调用 read_file(/mnt/skills/public/data-analysis/SKILL.md)
```

**关键文件**：
- `backend/packages/harness/deerflow/agents/lead_agent/prompt.py` — 构建系统提示
- `backend/packages/harness/deerflow/skills/` — skill 加载逻辑

### Step 5：LLM 执行 Skill

根据 SKILL.md 的复杂度判断：

**Simple 路径**（用户说"分析这个文件"）：
```
1. bash: python /mnt/skills/.../analyze.py --files ... --action inspect
2. 收到结果 → 一句话描述 → 结束
```

**Medium 路径**（用户说"哪些产品卖得最好"）：
```
1. bash: python /mnt/skills/.../analyze.py --files ... --action inspect
2. bash: python /mnt/skills/.../analyze.py --files ... --action query --sql "..."
3. 呈现结果 → 结束
```

**Complex 路径**（用户说"生成季度报告"）：
```
1. inspect
2. overview
3. summary
4. 多次 query（聚合、环比、同比）
5. 汇总报告 → 结束
```

---

## 四、analyze.py 执行流程

```
main()
  ├─ parse_args()
  ├─ compute_files_hash()        # 计算文件哈希作为缓存键
  ├─ 检查缓存 ~/.data-analysis-cache/
  │   ├─ 有缓存 → 连接 DuckDB (read_only)
  │   └─ 无缓存 → 创建 DuckDB
  │       ├─ load_files()
  │       │   ├─ Excel → header_processor.py 展平
  │       │   ├─ CSV → 直接 read_csv_auto
  │       │   └─ 保存 table_map.json
  │       └─ 持久化到 .duckdb 文件
  ├─ 执行 action
  │   ├─ inspect → action_inspect()  # 表结构、行数、列类型、非空统计、样例
  │   ├─ query → action_query()      # SQL 查询
  │   ├─ summary → action_summary()   # 数值统计（mean/std/min/max/percentile）
  │   └─ overview → action_overview() # 综合概览（结构+统计+样例）
  └─ 输出结果 / 导出文件
```

**analyze.py 参数说明**：

| 参数 | 必填 | 说明 |
|------|------|------|
| `--files` | Yes | Excel/CSV 文件路径，支持多个文件 |
| `--action` | Yes | inspect / query / summary / overview |
| `--sql` | query 时必填 | SQL 查询语句 |
| `--table` | summary 时必填 | 表/Sheet 名称 |
| `--output-file` | No | 导出路径（.csv/.json/.md） |

**action 说明**：

| Action | 功能 | 输出内容 |
|--------|------|----------|
| `inspect` | 表结构检查 | 行数、列名、类型、非空统计、样例 5 行 |
| `query` | SQL 查询 | 查询结果（表格/导出文件） |
| `summary` | 统计摘要 | 数值列：mean/std/min/max/percentiles；字符串列：unique/mode/top5 |
| `overview` | 综合概览 | inspect + numeric stats + string top3 + 样例 3 行 |

---

## 五、header_processor.py 工作流程（Excel 多级表头展平）

```
flatten_excel_headers(file_path, output_dir)
  └─ _flatten_single_sheet(file_path, sheet_name, output_dir, file_hash)
      ├─ fill_merged_cells()       # 填充合并单元格
      ├─ read_excel_preview()      # 读前 20 行（含填充）
      ├─ detect_header_structure() # 检测表头行数
      │   ├─ skip_rows: 连续全 None 行数
      │   ├─ header_rows: 连续非数据行数
      │   └─ header_type: flat | multi
      ├─ flatten_headers()         # 展平多级表头为单一列名
      ├─ read_data_rows()          # 读取数据行（含合并单元格填充）
      └─ save_flat_csv()           # 保存为 CSV (UTF-8-sig)
```

**detect_header_structure 规则**：
- `skip_rows`：连续全 None 行数
- `header_rows`：从第一个非空行开始，连续的非数据行行数
- 非数据行判断：`str_ratio > 0.3`（字符串占比 > 30%）
- `data_start_row = skip_rows + header_rows + 1`

**flatten_headers 规则**：
- 从最底层行开始向上合并
- 跳过与上一行完全相同的重复行
- 用 `_` 连接各层级名称
- 特殊字符替换为 `_`

---

## 六、双层缓存机制

```
~/.data-analysis-cache/
├── {hash}_flat_v1_{sheet_name}.csv    # L1: 展平后的 CSV
├── {hash}.duckdb                       # L2: DuckDB 数据库
└── {hash}.table_map.json               # 表名映射
```

**缓存命中流程**：
1. 根据文件内容哈希检查是否存在 `.duckdb`
2. 存在 → 直接连接 DuckDB（秒级启动）
3. 不存在 → 重新解析文件

**L1 vs L2**：
- L1（展平 CSV）：Excel 多级表头展平后存储，避免重复解析
- L2（DuckDB）：SQL 查询层，复用解析结果

**缓存版本**：
- `FLATTEN_VERSION = "v1"` — 表头展平版本号
- 文件内容变化 → 哈希不同 → 新缓存

---

## 七、Skill 复杂度判断流程

```
用户输入 → LLM 匹配
     │
     ├─ "这是什么" / "帮我看看" / "分析这个文件"
     │   → Simple → inspect → 一句话 → 结束
     │
     ├─ "哪些" / "多少" / "top N" / "按...汇总"
     │   → Medium → inspect + query → 结束
     │
     └─ "报告" / "趋势" / "环比同比" / "生成..."
         → Complex → inspect + overview + summary + query → 结束
```

**复杂度表格**：

| 级别 | 判断标准 | 执行模式 |
|------|----------|----------|
| **Simple** | "分析文件"、"看看数据"、"这是什么" | inspect → 一句话描述 → 结束 |
| **Medium** | "哪些"、"top N"、"按...汇总" | inspect → 合并 query → 结束 |
| **Complex** | "报告"、"趋势"、"环比同比" | inspect → overview → summary → 1次 query 总结 → 结束 |

---

## 八、完整对话示例

```
用户: "分析这个文件" (上传了 sales.xlsx)
     │
     ▼
[1] UploadsMiddleware: 注入 <uploaded_files>
[2] LLM: 匹配 data-analysis skill
[3] LLM: read_file(SKILL.md)
[4] LLM: 判断 Simple 级
[5] LLM: bash(analyze.py --action inspect)
[6] analyze.py:
    - 检查缓存（miss）
    - header_processor.py 展平多级表头
    - 创建 DuckDB
    - 执行 inspect: 表结构/行数/列类型/非空/样例
[7] LLM: "该表为销售订单表，共 1523 行，8 列..."
[8] 结束（4 步）
```

**Medium 对话示例**：
```
用户: "哪些产品卖得最好" (上传了 sales.xlsx)
     │
     ▼
[1-2] 同上
[3] LLM: 判断 Medium 级
[4] LLM: bash(analyze.py --action inspect)
[5] LLM: 分析表结构，决定查询策略
[6] LLM: bash(analyze.py --action query --sql "SELECT product, SUM(amount) as total FROM sales GROUP BY product ORDER BY total DESC LIMIT 10")
[7] LLM: 呈现 Top 10 产品表格
[8] 结束
```

---

## 九、相关文件清单

| 文件路径 | 说明 |
|----------|------|
| `skills/public/data-analysis/SKILL.md` | Skill 定义文件（已修改） |
| `skills/public/data-analysis/scripts/analyze.py` | DuckDB 分析脚本 |
| `skills/public/data-analysis/scripts/header_processor.py` | Excel 多级表头展平 |
| `skills/public/data-analysis/docs/2026-05-24-simple-request-12-steps-debugging.md` | 调试报告 |
| `frontend/src/components/ai-elements/prompt-input.tsx` | 文件选择 UI |
| `frontend/src/components/workspace/input-box.tsx` | 提交处理 |
| `frontend/src/core/threads/hooks.ts` | 消息发送 + 文件上传 |
| `backend/app/gateway/routers/uploads.py` | 文件上传 API |
| `backend/packages/harness/deerflow/agents/middlewares/uploads_middleware.py` | 文件上下文注入 |
| `backend/packages/harness/deerflow/agents/lead_agent/prompt.py` | 系统提示构建 |
| `backend/packages/harness/deerflow/sandbox/tools.py` | Bash 工具执行 |
| `backend/packages/harness/deerflow/agents/middlewares/loop_detection_middleware.py` | 循环检测 |

---

## 十、注意事项

1. **虚拟路径**：`analyze.py` 执行时使用 `/mnt/user-data/uploads/` 等虚拟路径，由 sandbox tools 进行路径转换
2. **缓存失效**：文件内容变化时哈希不同，自动创建新缓存
3. **表名映射**：`table_map.json` 存储原始 sheet 名称到 SQL 表名的映射
4. **特殊字符**：表名含空格或数字时自动转换，如 `Sheet1` → `"Sheet1"`
5. **输出格式**：指定 `--output-file` 时自动根据扩展名选择格式（.csv/.json/.md）