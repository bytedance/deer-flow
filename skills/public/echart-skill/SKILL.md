---
name: echart-skill
description: 专门处理日常办公场景下的高频、复杂数据分析与处理的助手。使用本地代码执行模式（SQL 或 Python + DuckDB）来处理数据导入、清洗、查询、提取、合并拆分及报告生成，支持大数据量且保障数据隐私安全。当用户需要处理 Excel/CSV 文件、跨表查询、生成图表或输出数据分析报告时使用此 Skill。
---

# Data Analysis Assistant Workflow

This skill transforms the agent into a powerful local data analysis assistant, strictly adhering to a **Local Code Execution** paradigm.

## Core Architecture & Principles
1. **Local Execution First**: NEVER read large datasets directly into the context window. Always generate Python scripts or SQL commands and execute them locally using `RunCommand`.
2. **DuckDB as the Engine**: All CSV/Excel files should be imported into a local DuckDB database (default: `workspace.duckdb`). Rely on SQL for robust data manipulation (filtering, joining, grouping). DuckDB's columnar storage delivers superior analytical performance.
3. **Non-Destructive Operations (Undo Mechanism)**: Do not overwrite original tables. When modifying data, create a new table (e.g., `CREATE TABLE table_v2 AS SELECT ...`) or a View. This guarantees the user can always say "undo the last step".
4. **Data Privacy**: Keep data local. Only send aggregated statistics or schema info into the context window.
5. **Chart Output**: After generating ANY HTML chart/dashboard output, follow the server config:
	   - **Default (`server.enabled=false`)**: Return the local file path only. The chart is a self-contained HTML file that works offline.
	   - **If enabled (`server.enabled=true`)**: Start the server and return the access URL. Use `python scripts/server_cli.py start` to auto-start if not running. See Scenario 4 for detailed server check instructions.

---

## Command System

> **双模式支持**: 本 Skill 同时支持**显性指令**和**模糊匹配**。当用户输入以 `/` 开头的指令时，直接执行对应操作；否则进行意图推断。

### 显性指令列表

| 指令 | 别名 | 功能 | 示例 |
|------|------|------|------|
| `/import` | `/i`, `/导入` | 数据导入 | `/import data.xlsx` |
| `/query` | `/q`, `/sql`, `/查询` | 执行 SQL 查询 | `/query SELECT * FROM sales LIMIT 10` |
| `/chart` | `/c`, `/图表`, `/viz` | 生成图表 | `/chart bar 销售额按类别` |
| `/chart-list` | `/cl`, `/图表列表` | 查看支持的图表类型 | `/chart-list` |
| `/export` | `/e`, `/导出` | 数据导出 | `/export result.csv --table sales` |
| `/tables` | `/t`, `/表`, `/结构` | 查看表结构 | `/tables sales` |
| `/history` | `/h`, `/历史` | 查看导入历史 | `/history --limit 20` |
| `/metrics` | `/m`, `/口径`, `/指标` | 指标管理 | `/metrics add 月活用户` |
| `/scope` | `/统计口径`, `/口径设置` | 统计口径设置（全局/项目级） | `/scope set --level project --name GMV --desc "SUM(amount)"` |
| `/privacy` | `/隐私` | 隐私配置，脱敏默认关闭，可开启 | `/privacy mask on` |
| `/audit-report` | `/审计报告` | 按日期生成指令与查询审计报告 | `/audit-report --date 2026-06-27` |
| `/quality` | `/数据质量` | 数据质量评分与问题报告 | `/quality orders --format markdown` |
| `/lineage` | `/血缘` | 记录或查询产物数据血缘 | `/lineage list --table orders` |
| `/help` | `/?`, `/帮助` | 显示帮助 | `/help` |
| `/clean` | `/清洗`, `/清理` | 数据内容清洗或清理旧数据 | `/clean orders --config rules.json` |
| `/poll` | `/轮询` | 轮询管理 | `/poll status` |
| `/dbconn` | `/dbc`, `/连接` | 数据库连接管理（全局/项目级） | `/dbconn add --name pg --type postgresql` |
| `/schema` | `/sc`, `/表结构` | 表结构定义管理（全局/项目级） | `/schema add --name orders --columns "id:INT:ID:pk"` |
| `/dashboard` | `/db`, `/仪表盘` | 生成仪表盘 | `/dashboard config.txt` |
| `/start` | `/server`, `/启动服务` | 启动本地服务 | `/start` |
| `/stop` | `/停止服务` | 停止本地服务 | `/stop` |
| `/status` | `/状态` | 查看服务状态和链接 | `/status` |
| `/echart-update` | `/update`, `/更新` | 从 GitHub 拉取最新代码并备份旧文件 | `/echart-update` |
| `/analyze` | `/a`, `/分析` | 自动分析数据表，发现规律与异常 | `/analyze sales` |
| `/insight` | `/洞察` | 对指定维度生成深度洞察 | `/insight sales --dim region` |
| `/report` | `/r`, `/报告` | 一键生成专业分析报告 | `/report sales --template sales` |
| `/forecast` | `/f`, `/预测` | 时间序列预测 | `/forecast orders 订单日期 金额 --periods 6` |
| `/why` | `/w`, `/归因`, `/为什么` | 数据变化归因分析 | `/why orders 金额 订单日期 2024-01 2024-06` |
| `/context` | `/ctx`, `/会话` | 会话管理（开始/追问/历史/列表） | `/context start sales` |

### 指令处理流程

```
┌─────────────────────────────────────────────────────────────────┐
│                    输入处理流程                                   │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  用户输入                                                        │
│      │                                                          │
│      ▼                                                          │
│  是否以 / 开头？                                                  │
│      │                                                          │
│      ├── 是 ──→ 匹配显性指令 ──→ 直接执行对应 Scenario            │
│      │         │                                                │
│      │         └── 未匹配 ──→ 显示 "未知指令，输入 /help 查看帮助" │
│      │                                                          │
│      └── 否 ──→ 模糊匹配流程                                     │
│                │                                                │
│                ├── 文件上传 ──→ Scenario 1 (数据导入)            │
│                ├── 查询关键词 ──→ Scenario 2 (SQL 查询)           │
│                ├── 图表关键词 ──→ Scenario 4 (图表生成)           │
│                ├── 导出关键词 ──→ Scenario 6 (数据导出)           │
│                ├── 预测关键词 ──→ Scenario 19 (趋势预测)          │
│                ├── 归因关键词 ──→ Scenario 20 (归因分析)          │
│                ├── 会话关键词 ──→ /context 子命令                  │
│                ├── 数据库/连接关键词 ──→ Scenario 13 (数据库连接+分析) │
│                └── 其他 ──→ 自然语言理解                          │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 指令详细说明

#### `/import` - 数据导入
```
/import <文件路径> [--table <表名>] [--db <数据库路径>]
/i <文件路径>  # 别名
/导入 <文件路径>  # 中文别名

示例:
  /import data/sales.xlsx
  /import report.csv --table monthly_report
  /i data.xlsx --db custom.duckdb
```

#### `/query` - SQL 查询
```
/query <SQL语句>
/q <SQL语句>  # 别名
/sql <SQL语句>  # 别名
/查询 <SQL语句>  # 中文别名

示例:
  /query SELECT * FROM sales LIMIT 10
  /q SELECT category, SUM(amount) FROM sales GROUP BY category
  /sql DESCRIBE sales
```

#### `/chart` - 图表生成
```
/chart <图表类型> [描述] [--table <表名>] [--output <路径>]
/c <图表类型> [描述]  # 别名
/图表 <图表类型> [描述]  # 中文别名

支持的图表类型:
  bar, line, pie, scatter, radar, map, funnel, gauge, 
  heatmap, treemap, sunburst, sankey, graph, candlestick,
  line3d, bar3d, scatter3d, surface

示例:
  /chart bar 销售额按类别
  /chart line 月度销售趋势
  /chart pie 各产品占比
  /chart map 各省销售分布
  /c scatter 价格与销量的关系 --table products
```

#### `/chart-list` - 查看支持的图表类型
```
/chart-list [类别]
/cl [类别]  # 别名
/图表列表 [类别]  # 中文别名

显示所有支持的图表类型及其简介。

参数:
  [类别]  可选，筛选特定类别：basic, statistical, hierarchical, 
          geographical, relation, 3d, time, professional

示例:
  /chart-list              # 显示所有图表
  /chart-list basic        # 显示基础图表
  /chart-list 3d           # 显示3D图表
  /cl                      # 别名
```

#### `/dashboard` - 仪表盘生成
```
/dashboard <描述> [--output <输出路径>]
/db <描述>  # 别名
/仪表盘 <描述>  # 中文别名

示例:
  # 自然语言描述（推荐）
  /dashboard 创建销售分析仪表盘，包含：各地区销售柱状图、产品类别饼图、月度趋势折线图、全国分布地图
  
  # 简化配置文件
  /dashboard outputs/configs/dashboard.json
  
  # 指定输出路径
  /dashboard 销售数据仪表盘，包含地区柱状图和类别饼图 --output outputs/html/sales.html

功能:
  - ✅ 自然语言描述自动解析
  - ✅ 智能布局算法自动排版
  - ✅ Agent 自动规划 SQL、KPI 树、布局和图表
  - ✅ 专业卡片式布局
  - ✅ 深色/浅色主题切换
  - ✅ 响应式设计
  - ✅ 自动刷新、导出 PDF
  - ✅ 图表搜索、单独下载
  - ✅ 智能数据洞察卡片（NEW v2.0 — 使用 --insights 启用）

默认按 `workflow_specs/dashboard_workflow.md` 规划仪表盘，并必须读取 `workflow_specs/dashboard_expert_library/INDEX.md` 选择 Dashboard 专用专家，再读取、使用 `workflow_specs/html_templates/dashboard_light.html` 作为企业 BI 页面骨架，结合 `workflow_specs/visual_templates/light.md` 落实视觉方向。需要深色风格时使用 `workflow_specs/visual_templates/dark.md` 调整模板 token。最终 Dashboard 由 Agent 按规范直接生成，不使用固定 Python dashboard 生成器。

Dashboard HTML 必须能看出模板落地：统一背景、卡片层级、字体尺度、图表面板、KPI 网格、语义色和响应式规则。不能生成未设计的默认 HTML。
主题切换必须是页面级切换：切换 `data-theme` 后，页面背景、header、toolbar、KPI 卡片、图表面板、诊断区、按钮和 toast 都要一起变更，不能只切换 ECharts 图表主题。
如果元数据、字段名或样例值包含城市信息，并且存在交易额/销售额/GMV/金额/销量/数量类字段，Dashboard 必须读取 `workflow_specs/dashboard_modules/city_sales_map.md`，增加城市地图 + 销售/销量模块；地图坐标或本地地图覆盖不足时，需要明确说明数据缺口并用城市排行柱图兜底。
Dashboard 标题必须能追溯到用户请求、表名、文件名或真实字段；不能凭空出现“白酒分析”等数据和用户都没有提供的行业/品类。业务 Dashboard 在数据支持时至少包含 KPI、趋势、排行/贡献、结构、交叉分析、异常/归因、地理模块（触发时）和数据口径说明；如果少于 6 个分析模块，必须说明字段不足，否则需要重做。

⚠️ **重要**: 仪表盘 HTML 必须为**自包含单文件**（无外部 CSS/JS 引用，无硬编码端口号）。详见 Scenario 15 的 "Dashboard Single File 铁律"。

选项:
  --insights                    启用数据洞察卡片（自动分析表数据并展示关键发现）
  --insights-dimensions, -d <列> 洞察分析的维度列（逗号分隔）
  --insights-date-column <列>    洞察分析的日期列（用于趋势/周期性检测）
  --insights-max <数量>          最大洞察卡片数（默认 6）

示例:
  # 基础仪表盘（不含洞察）
  /dashboard 创建销售分析仪表盘

  # 含洞察卡片的仪表盘
  /dashboard 销售分析仪表盘 --insights

  # 指定洞察分析的维度和日期列
  /dashboard 销售仪表盘 --insights --insights-dimensions region,category --insights-date-column order_date

洞察卡片功能:
  - 📈 自动发现 7 种洞察模式（趋势、异常、排名、构成、相关性、周期、变化）
  - 🔴🟠🟡⚪ 严重程度分级（严重/重要/中等/信息）
  - 🎯 每个卡片显示关键指标值和变化百分比
  - 🔍 悬停显示"点击深入分析"提示
  - 📊 自动推荐最合适的图表类型
  - 零额外配置 — 只需加 --insights 即可启用

支持图表类型:
  - bar (柱状图): group_by 参数
  - line (折线图): time_column 参数
  - pie (饼图): group_by 参数  
  - map (地图): geo_column 参数
  - scatter (散点图): x_column, y_column
  - radar (雷达图): dimensions
  - funnel (漏斗图): group_by
  - treemap (树图): group_by
  - sunburst (旭日图): hierarchy

自然语言描述示例:
  - 各地区销售柱状图 → 自动识别为 bar 类型，group_by='region'
  - 月度趋势折线图 → 自动识别为 line 类型，time_column='month'
  - 产品类别饼图 → 自动识别为 pie 类型，group_by='category'
  - 全国分布地图 → 自动识别为 map 类型，geo_column='province'
```

**支持的图表类型完整列表：**

| 类型 | 名称 | 类别 | 简介 |
|------|------|------|------|
| `bar` | 柱状图 | 基础 | 用于比较不同类别的数值大小，支持堆叠、分组 |
| `line` | 折线图 | 基础 | 展示数据随时间或类别的变化趋势，支持平滑曲线 |
| `pie` | 饼图 | 基础 | 展示各部分占整体的比例关系，支持环形图、玫瑰图 |
| `scatter` | 散点图 | 基础 | 展示两个变量之间的关系和分布，支持气泡效果 |
| `radar` | 雷达图 | 基础 | 多维度数据对比，适合性能评估、能力分析 |
| `area` | 面积图 | 基础 | 折线图的变体，强调累积变化趋势 |
| `boxplot` | 箱线图 | 统计 | 展示数据分布的五数概括（最小值、Q1、中位数、Q3、最大值） |
| `heatmap` | 热力图 | 统计 | 用颜色深浅表示数值大小，适合矩阵数据可视化 |
| `scattergl` | WebGL散点图 | 统计 | 高性能散点图，适合大数据量（百万级）渲染 |
| `effectScatter` | 涟漪散点图 | 统计 | 带动画效果的散点图，适合突出重点数据 |
| `lines` | 线图 | 统计 | 展示数据流向和轨迹，支持地图上的迁徙线 |
| `treemap` | 矩形树图 | 层级 | 用矩形面积展示层级数据的占比关系 |
| `sunburst` | 旭日图 | 层级 | 多层饼图，展示层级结构的占比关系 |
| `tree` | 树图 | 层级 | 展示层级结构的节点连接关系 |
| `sankey` | 桑基图 | 关系 | 展示数据流向和转化，适合漏斗分析、能量流 |
| `graph` | 关系图 | 关系 | 展示节点之间的网络关系，支持力导向布局 |
| `chord` | 和弦图 | 关系 | 展示节点之间的双向关系强度 |
| `funnel` | 漏斗图 | 专业 | 展示转化漏斗，适合分析各阶段流失率 |
| `gauge` | 仪表盘 | 专业 | 展示单个指标的达成进度，类似速度表 |
| `candlestick` | K线图 | 专业 | 展示股票等金融数据的开盘、收盘、最高、最低价 |
| `parallel` | 平行坐标图 | 专业 | 多维度数据并行展示，适合高维数据分析 |
| `calendar` | 日历图 | 时间 | 在日历上展示数据分布，适合活动打卡、出勤分析 |
| `themeRiver` | 主题河流图 | 时间 | 展示多个主题随时间的变化趋势和占比 |
| `map` | 地图 | 地理 | 展示地理区域数据分布，支持中国、世界地图 |
| `geo` | 地理坐标系 | 地理 | 地理坐标系组件，配合 scatter、lines 使用 |
| `bar3d` | 3D柱状图 | 3D | 三维柱状图，适合展示三维数据矩阵 |
| `line3d` | 3D折线图 | 3D | 三维空间中的折线图 |
| `scatter3d` | 3D散点图 | 3D | 三维空间中的散点图 |
| `surface` | 3D曲面图 | 3D | 展示三维曲面数据，适合科学计算可视化 |

**图表类型类别说明：**

| 类别 | 说明 | 适用场景 |
|------|------|----------|
| **基础** `basic` | 最常用的图表类型 | 数据比较、趋势分析、占比展示 |
| **统计** `statistical` | 用于数据分析的图表 | 数据分布、相关性分析、大规模数据 |
| **层级** `hierarchical` | 展示层级结构 | 组织架构、分类体系、占比层级 |
| **关系** `relation` | 展示节点关系 | 社交网络、流程分析、转化漏斗 |
| **地理** `geographical` | 地图相关可视化 | 区域销售、人口分布、物流轨迹 |
| **3D** `3d` | 三维可视化 | 科学计算、立体展示 |
| **时间** `time` | 时间维度图表 | 日历分析、时间趋势 |
| **专业** `professional` | 特定领域专用 | 金融分析、进度监控、指标展示 |

#### `/export` - 数据导出
```
/export <输出路径> [--table <表名>] [--query <SQL>]
/e <输出路径>  # 别名
/导出 <输出路径>  # 中文别名

示例:
  /export result.csv --table sales
  /export report.xlsx --query "SELECT * FROM sales WHERE year=2024"
  /e output/data.csv
```

#### `/tables` - 查看表结构
```
/tables [表名]
/t [表名]  # 别名
/表 [表名]  # 中文别名
/结构 [表名]  # 中文别名

示例:
  /tables          # 显示所有表
  /tables sales    # 显示 sales 表结构
  /t               # 别名
```

#### `/history` - 查看导入历史
```
/history [--limit <数量>]
/h [--limit <数量>]  # 别名
/历史 [--limit <数量>]  # 中文别名

示例:
  /history          # 显示最近20条
  /history --limit 50
  /h --limit 10
```

#### `/metrics` - 指标管理
```
/metrics [add|list|show] [参数]
/m [操作] [参数]  # 别名
/口径 [操作]  # 中文别名
/指标 [操作]  # 中文别名

示例:
  /metrics list                     # 列出所有指标
  /metrics add 月活用户 --desc "当月至少登录一次的用户"
  /metrics show 月活用户
  /m list
```

#### `/scope` - 统计口径设置（全局/项目级）
```
/scope set --level <global|project> --name <口径名> --desc <定义>
/scope list [--level global|project|effective]
/scope show
/统计口径 set --level project --name GMV --desc "GMV = SUM(pay_amount)"
/口径设置 show

执行方式:
  # 全局口径：写入 skill 根目录 references/metrics.md，所有项目生效
  python scripts/metrics_manager.py set --level global --name "GMV" --desc "SUM(pay_amount)"

  # 项目口径：写入当前项目 .echart-skill/metrics.md，并登记项目目录
  python scripts/metrics_manager.py set --level project --name "GMV" --desc "SUM(pay_amount)" --project-dir "$PWD"

  # 读取当前目录下生效口径：全局 + 当前目录命中的项目口径
  python scripts/metrics_manager.py effective --cwd "$PWD"
```

项目级口径必须记录设置时的项目目录；只有后续执行目录位于该项目目录或其子目录下时才生效。生成 SQL、报告、Dashboard、归因和预测前，必须读取 `python scripts/metrics_manager.py effective --cwd "$PWD"` 的结果作为统计口径上下文。

#### `/privacy` - 隐私配置
```
/privacy mask on      # 开启 PII 脱敏
/privacy mask off     # 关闭 PII 脱敏（默认）
/隐私 脱敏 开启
```

脱敏默认关闭。开启后，将 `echart_config.txt` 中 `privacy.mask_pii` 设置为 `true`；关闭时设置为 `false`。审计默认开启，配置项为 `privacy.audit_enabled=true`。

#### `/audit-report` - 审计报告
```
/audit-report --date <YYYY-MM-DD> [--days 1] [--output <path>]
/审计报告 --date 2026-06-27

执行方式:
  # 执行用户显性指令前先记录指令审计
  python scripts/audit_report.py log-command "/report sales --format html" --cwd "$PWD" --status started

  # 生成指定日期的审计报告
  python scripts/audit_report.py report --date 2026-06-27 --days 1 --print
```

审计报告会汇总当天记录到的用户指令、查询表、访问列、行数、脱敏状态、分类级别、拦截操作和 query hash。所有显性指令在执行前应调用 `log-command` 记录原始指令、当前工作目录和状态。

#### `/quality` - 数据质量评分
```
/quality <表名> [--db workspace.duckdb] [--format markdown|json] [--output <path>]
/数据质量 orders

执行方式:
  python scripts/data_quality.py orders --db workspace.duckdb --format markdown --print
```

生成报告、Dashboard、归因分析前，应优先执行数据质量评分。报告需要把质量分、等级、关键问题和限制写入口径说明；如果质量等级为 C/D 或存在 critical/high 问题，强结论必须降级为“初步判断”并说明数据缺口。

#### `/lineage` - 数据血缘
```
/lineage record --artifact <产物路径> --type report --tables orders --columns amount,region --query "<SQL>"
/lineage list [--artifact <产物路径>] [--type report|dashboard|chart|export] [--table orders]
/血缘 list --table orders

执行方式:
  python scripts/lineage_manager.py record \
    --artifact outputs/reports/orders.html \
    --type report \
    --tables orders \
    --columns amount,region \
    --query "SELECT region, SUM(amount) FROM orders GROUP BY region" \
    --metrics GMV \
    --generated-by "/report orders"

  python scripts/lineage_manager.py list --table orders
```

所有图表、Dashboard、Report 和数据导出在产物生成成功后都应记录血缘。血缘记录只保存 query hash，不保存 SQL 明文，避免泄露敏感查询细节；报告附录可引用血缘记录说明来源表、字段、统计口径和产物路径。

#### `/help` - 显示帮助
```
/help
/?  # 别名
/帮助  # 中文别名
```

#### `/clean` - 数据清洗 / 清理旧数据
```
/clean <表名> [--config <规则文件>] [--output-table <表名>] [--unique-key <列1,列2>]
/清洗 <表名> [选项]  # 中文别名
/清理 [--days <天数>]  # 兼容旧行为：清理旧数据

示例:
  /clean orders --unique-key order_id,line_id --duplicate-keep latest --duplicate-order-by updated_at
  /clean orders --config outputs/configs/orders_cleaning.json --output-table orders_cleaned
  /clean orders --dry-run
  /清理 --days 7
```

数据内容清洗必须读取 `workflow_specs/data_cleaning_workflow.md`。Agent 需要先诊断字段、样例值、缺失率、重复候选和业务口径，再询问用户不明确的清洗规则，不能强行设定。支持日期/金额/数值/布尔/文本类型转换、多列唯一键排重、缺失值处理、异常值处理、归一化/标准化、规则引擎、跨表验证、派生特征和脱敏。

#### `/poll` - 轮询管理
```
/poll [list|status|refresh|add|remove] [参数]
/轮询 [操作]  # 中文别名

示例:
  /poll list              # 列出所有轮询任务
  /poll status            # 显示详细状态
  /poll refresh           # 手动刷新所有任务
  /poll add --type http --name api_data --interval 300 --url "https://api.example.com/data"
  /poll remove <job_id>
```

#### `/start` - 启动本地服务
```
/start [--port <端口>]
/server [--port <端口>]  # 别名
/启动服务 [--port <端口>]  # 中文别名

启动本地 HTTP 服务器以查看生成的图表。

参数:
  --port <端口>  可选，指定端口号（默认自动选择 8100-8200）

示例:
  /start              # 自动选择可用端口启动
  /start --port 8080  # 指定端口启动
  /server             # 别名
```

#### `/stop` - 停止本地服务
```
/stop
/停止服务  # 中文别名

停止正在运行的本地 HTTP 服务器。

示例:
  /stop    # 停止服务
```

#### `/status` - 查看服务状态
```
/status
/状态  # 中文别名

查看服务运行状态和所有可访问的图表链接。

显示内容:
  - 服务状态（运行中/已停止）
  - 运行端口
  - 启动时间
  - 运行时长
  - 可访问图表列表（带完整 URL）

示例:
   /status  # 查看当前状态和链接
```

#### `/echart-update` - 更新 Skill
```
/echart-update
/update  # 别名
/更新  # 中文别名

自动更新 echart-skill，支持首次安装和后续更新。

功能:
  - ✅ 自动检测：是 git 仓库则 pull，否则提示 clone
  - ✅ 更新前自动创建带日期的备份压缩包
  - ✅ 排除临时文件、数据库文件等
  - ✅ 备份文件保存在 backup/ 目录

首次安装:
  # macOS/Linux
  cd ~/.agents/skills  # 或你的 skill 目录
  git clone https://github.com/lgwanai/echart-skill.git

  # Windows (PowerShell)
  cd $env:USERPROFILE\.agents\skills
  git clone https://github.com/lgwanai/echart-skill.git

后续更新:
  /echart-update  # 自动 pull + 备份
  /update         # 别名
  /更新           # 中文别名

输出:
  📦 备份文件: backup/echart-skill_backup_20260524_120000.zip
  ✅ 更新成功
```

#### `/analyze` - 自动数据分析
```
/analyze <表名> [选项]
/a <表名>  # 别名
/分析 <表名>  # 中文别名

自动分析数据表，发现趋势、异常、排名、占比、相关性等规律。

选项:
  --dimensions, -d <列名列表>  指定分析维度（逗号分隔）
  --metric, -m <列名列表>      指定分析指标（逗号分隔）
  --date-column <列名>         指定时间列
  --top-n <数量>               Top-N 数量（默认 5）
  --quick                      快速扫描模式
  --format <text|json>         输出格式

示例:
  /analyze sales                           # 自动分析 sales 表
  /analyze orders --dimensions region,category --metric amount
  /analyze sales --date-column order_date  # 含时间序列分析
  /analyze sales --quick                   # 快速扫描
  /a sales                                 # 别名

洞察类型:
  - 📈 趋势分析: 上升/下降趋势，趋势加速/减速
  - ⚠️ 异常检测: Z-score 检测异常波动
  - 📊 排名分析: Top-N / Bottom-N 排名
  - 🥧 占比分析: 构成分布与集中度
  - 🔗 相关性: 指标间关联关系
  - 📅 季节性: 周期性规律检测
  - 📉 变化分析: 环比/同比变化
```

#### `/insight` - 深度洞察
```
/insight <表名> --dim <维度列> [选项]
/洞察 <表名> --dim <维度列>  # 中文别名

对指定维度生成深度洞察，适合追问"为什么"的场景。

示例:
  /insight sales --dim region          # 各地区深度分析
  /insight sales --dim product --metric amount,quantity
  /insight orders --dim channel --top-n 10
```

#### `/report` - 分析报告生成
```
/report <表名> [选项]
/r <表名>  # 别名
/报告 <表名>  # 中文别名

一键生成企业级专家分析报告，支持 Markdown/HTML/JSON 格式。报告由 Agent 按 `workflow_specs/report_workflow.md` 组织，不由固定 Python 报告生成器渲染。Agent 必须先读取 `workflow_specs/expert_library/INDEX.md`，再动态选择并完整读取匹配专家 `.md` 文件，按专家模式设计分析路径，使用 SQL/Python 工具获取证据，再写出异常、对比、归因、分析结论与行动建议；不是简单图表说明。

报告表达必须遵守金字塔原理：结论 -> 发现 -> 图表举证 -> 解释归因 -> 行动建议 -> 附录数据。每个发现分支内部也必须遵守局部金字塔：先说该发现的结论，再讲观察，再用图表举证，再解释归因，最后给局部行动建议。前文关键结论和发现结论必须引用附录数据表编号，例如 `[Data A1]`。HTML 报告必须先读取并使用 `workflow_specs/html_templates/report_light.html` 作为企业 PDF 风格页面骨架，再结合 `workflow_specs/visual_templates/light.md` 或 `dark.md` 调整视觉方向，不能生成浏览器默认样式或简陋表格页。报告较长时必须分段生成各发现分支，最后统一组装。

每个报告图表都必须搜索并读取 `references/examples/*.md` 中对应的图表配方作为上下文，按配方生成 ECharts option，再嵌入统一 HTML 报告；不得脱离图表配方随手写图表。

每个分析模块都必须补充“统计口径说明”，用口语化业务表达说明数据范围、时间粒度、指标口径、分组维度、筛选条件和当前数据不能证明的内容；主文不展示 SQL。所有结论必须尊重事实数据，不得创造数据中不存在、用户也没有提供定义的概念，例如没有目标或预算字段时不能写目标达成率、预算偏差；没有漏斗/留存字段时不能强行写漏斗转化或留存结论。

涉及季节性波动或外部因素时，不得仅凭内部数据直接断言原因。推荐表达为：补充节假日、活动投放、价格、库存、天气、渠道策略等数据后，可以进一步判断这是季节性波动还是外部因素导致。

选项:
  --title, -t <标题>           报告标题
  --template <模板名>           报告模板: general, sales, quick
  --format <markdown|html|json> 输出格式（默认 markdown）
  --output, -o <路径>          输出路径
  --quick                       快速报告模式

报告模板:
  - general: 企业级通用分析报告（含摘要/结论/专家框架/概览/指标/维度/趋势/异常/归因/建议）
  - sales:   销售分析报告（含销售结论/结构/产品/渠道/区域/趋势/归因）
  - quick:   快速分析摘要（核心发现/分析结论/数据画像/关键洞察/行动建议）

专家分析能力:
  - 自动判断行业：流量/增长、销售/电商、财务、客户/会员、运营履约、营销活动、产品内容、风控/数据质量、通用经营
  - 动态拉取专家：读取 `workflow_specs/expert_library/INDEX.md`，选择主专家和支撑专家，再读取对应专家文件
  - 用户自定义专家：复制 `workflow_specs/expert_library/EXPERT_TEMPLATE.md` 新建专家文件，并在 `INDEX.md` 登记
  - 按专家模式检查：例如流量看规模、效率、留存、漏斗、渠道归因；销售看收入、结构、趋势、利润质量
  - 必须执行专家诊断闭环：基线定义、异常扫描、交叉分析、深度归因、专家结论
  - 自动做异常扫描、最近周期对比、多维交叉、贡献度归因和下钻解释
  - 报告必须结论先行，明确“发生了什么、为什么、下一步做什么”
  - 每个关键发现分支必须内部遵守金字塔结构：局部结论、发现、图表举证、解释归因、局部建议
  - 每个分析模块必须展示口语化统计口径说明，不在主文展示 SQL
  - 不创造事实数据之外的业务概念；没有用户定义或字段支撑时，不写目标达成率、预算偏差、ROI、SLA、留存、漏斗等结论
  - 季节性或外部因素只能在证据充分时下结论；证据不足时写明需要补充哪些外部数据进一步判断
  - 关键发现必须优先用图表举证：趋势用折线，贡献用柱图/瀑布，漏斗用漏斗图，留存用热力图，关系用散点图
  - 明细表、字段画像、SQL、样本数据只能放在附录或作为小型补充表；主文必须引用附录数据表编号
  - Python 只能作为数据工具和计算工具，不能作为最终报告渲染器；最终报告由 Agent 按规范撰写

示例:
  /report sales                                    # 生成通用报告(Markdown)
  /report sales --template sales --format html     # 销售报告(HTML)
  /report traffic --format html                    # Agent 按工作流生成企业级 HTML 报告
  /report orders --quick --format markdown         # 快速摘要
  /r sales --title "Q1销售分析" --format html       # 指定标题
```

#### `/forecast` - 时间序列预测
```
/forecast <表名> <日期列> <指标列> [选项]
/f <表名> <日期列> <指标列>  # 别名
/预测 <表名> <日期列> <指标列>  # 中文别名

基于纯 Python 实现的时间序列预测，支持多种方法，零外部依赖（无需 sklearn/tensorflow）。

选项:
  --periods, -p <数量>        预测期数（默认 6）
  --method, -m <方法>         预测方法: moving_average(移动平均), exponential(指数平滑), linear_trend(线性趋势), ensemble(集成,默认)
  --granularity, -g <粒度>    时间粒度: day(日), week(周), month(月,默认), quarter(季), year(年)
  --filter <条件>             数据过滤条件（SQL WHERE 子句）
  --db <数据库路径>           数据库路径（默认 workspace.duckdb）
  --format <text|json>        输出格式

预测方法说明:
  - moving_average: 移动平均法 — 自适应窗口，适合稳定序列
  - exponential:    指数平滑法 — 含趋势检测，适合有趋势的序列
  - linear_trend:   线性回归法 — 给出 R² 置信度，适合线性趋势
  - ensemble:       集成方法 — 加权融合以上三种方法（推荐）

输出内容:
  - 历史数据摘要（最近 6 期）
  - 未来 N 期预测值
  - 预测区间（上下限 80% 置信区间）
  - 置信度评分 (0-1)
  - 趋势方向（上升/下降/平稳）及变化率

示例:
  /forecast orders 订单日期 金额 --periods 6                   # 默认集成预测
  /forecast orders 订单日期 金额 --method linear_trend -p 12  # 线性趋势预测12期
  /forecast sales order_date amount --granularity quarter    # 按季度预测
  /f orders 下单时间 数量 --periods 3 -m exponential         # 指数平滑预测3期
```

#### `/why` - 归因分析
```
/why <表名> <指标列> <日期列> <起始期> <终止期> [选项]
/w <表名> <指标列> <日期列> <起始期> <终止期>  # 别名
/归因 <表名> <指标列> <日期列> <起始期> <终止期>  # 中文别名
/为什么 <表名> <指标列> <日期列> <起始期> <终止期>  # 中文别名

分析指标变化的根本原因，将总变化分解到各维度的贡献值，自动推荐钻取路径。

选项:
  --dimensions, -d <维度列表>  分析维度，逗号分隔（默认自动检测前3个分类维度）
  --top-n <数量>               每个维度返回的 top 贡献项数（默认 8）
  --db <数据库路径>             数据库路径（默认 workspace.duckdb）
  --format <text|json>         输出格式

分析内容:
  - 总量变化（起始值 → 终止值，变化率）
  - 各维度 Top 驱动力排名（含贡献百分比）
  - 抵消效应检测（增长/下降维度分布）
  - 自动化钻取建议（下一步从哪里深入分析）

贡献度阈值:
  - 贡献度 ≥ 15% 标记为主要驱动力（📌）
  - 贡献度 < 15% 归为次要因素

示例:
  /why orders 金额 订单日期 2024-01 2024-06 -d 商品分类,渠道,支付方式
  /why sales amount order_date 2024-Q1 2024-Q2 --dimensions region,category
  /w orders 数量 日期 2025-01 2025-03
  /为什么 sales 销售额 下单日期 2024-01 2024-06 -d 省份
```

#### `/context` - 会话管理
```
/context <子命令> [参数]
/ctx <子命令>  # 别名
/会话 <子命令>  # 中文别名

管理分析会话状态，支持会话创建、追问解析、历史查看、会话列表等功能。

子命令:
  start <表名> [选项]    开始新的分析会话
  resolve <文本>         解析追问内容（"上个月呢？"等）
  history                查看当前会话的对话历史
  context                查看当前会话的上下文提示词
  list                   列出所有已保存的会话

start 选项:
  --db <路径>                   数据库路径（默认 workspace.duckdb）
  --dimensions, -d <维度列表>   分析维度，逗号分隔
  --metrics, -m <指标列表>      关注指标，逗号分隔
  --date-column <日期列>        日期列名
  --semantic-model, -s <模型>   关联的语义模型名

会话功能说明:
  - 会话持久化存储（SQLite），重启后保留上下文
  - 自动时间上下文检测（从表数据中推断日期范围）
  - 支持 10+ 种时间表达式解析（上个月/去年/Q1/最近N天...）
  - 意图检测：refine(细化)、compare(对比)、pivot(切换维度)、drill_down(深挖)、explain(归因)、predict(预测)

追问类型对照:
  | 类型 | 示例 | 系统行为 |
  |------|------|----------|
  | REFINE | "上个月呢？" | 解析时间引用，调整查询范围 |
  | COMPARE | "和去年同期比" | 检测同比/环比，生成对比查询 |
  | DRILL_DOWN | "深挖一下白酒" | 应用维度过滤器 |
  | EXPLAIN | "为什么下降了" | 触发归因分析（→ /why） |
  | PIVOT | "按渠道分析" | 切换分析维度 |
  | PREDICT | "预测下个月" | 触发趋势预测（→ /forecast） |

示例:
  /context start sales                                          # 开始分析 sales 表
  /context start orders --dimensions region,category --db workspace.duckdb
  /context resolve "上个月呢？"                                   # 解析追问
  /context resolve "和去年同期比" --session-id <id>              # 指定会话
  /context history                                              # 查看历史
  /context context                                              # 查看上下文
  /context list                                                 # 列出所有会话
  /ctx list                                                     # 别名
```

#### `/dbconn` - 数据库连接管理
```
/dbconn <子命令> [参数]
/dbc <子命令>  # 别名
/连接 <子命令>  # 中文别名

独立管理外部数据库连接（MySQL、PostgreSQL、MongoDB），支持全局和项目级配置。

子命令:
  add        添加数据库连接
  list       列出数据库连接
  show       查看连接详情
  remove     删除数据库连接
  test       测试数据库连接

全局 vs 项目级:
  --level global    全局连接（存储在 Skill 根目录 references/db_connections.txt）
                    对所有项目生效
  --level project   项目级连接（存储在当前目录 .echart-skill/db_connections.txt）
                    仅对当前项目目录及其子目录生效
  默认使用 --level global

生效规则:
  - 项目级连接会覆盖同名的全局连接（优先级：项目 > 全局）
  - 项目级连接只在配置时所在项目目录及子目录生效
  - 使用 /dbconn list 查看当前目录下生效的所有连接

密码安全:
  - 密码字段支持 ${ENV_VAR} 占位符，切勿硬编码密码
  - 示例: --password '${PG_PASSWORD}'
  - 连接详情展示时密码自动脱敏为 ***

示例:
  # 添加全局 PostgreSQL 连接
  /dbconn add --name analytics --type postgresql --host localhost --database analytics --username reader --password '${PG_PASSWORD}'

  # 添加项目级 MySQL 连接
  /dbconn add --name prod --type mysql --host db.internal --database production --username admin --password '${MYSQL_PASS}' --level project

  # 添加 MongoDB 连接（使用连接字符串）
  /dbconn add --name mongo_logs --type mongodb --connection-string '${MONGO_URI}'

  # 列出当前生效的所有连接
  /dbconn list

  # 列出全局连接
  /dbconn list --level global

  # 列出项目连接
  /dbconn list --level project

  # 查看连接详情
  /dbconn show analytics

  # 测试连接是否可用
  /dbconn test analytics

  # 删除连接
  /dbconn remove old_db --level global
```

**数据库类型支持:**

| 类型 | 默认端口 | 驱动 | 说明 |
|------|---------|------|------|
| `postgresql` | 5432 | psycopg2 + SQLAlchemy | PostgreSQL 数据库 |
| `mysql` | 3306 | pymysql + SQLAlchemy | MySQL 数据库 |
| `mongodb` | 27017 | pymongo | MongoDB 数据库 |

**连接配置后使用:**

连接添加后，可通过以下方式使用：
```bash
# 查询远程数据库（使用有效配置中的连接）
python scripts/db_cli.py query analytics "SELECT * FROM orders LIMIT 10"

# 查看远程表结构
python scripts/db_cli.py list-tables analytics

# 导入远程数据到本地 DuckDB
python scripts/db_cli.py import analytics "SELECT * FROM orders" --table-name orders_import
```

**执行方式:**
```bash
# 添加连接
python scripts/db_manager.py add --name <name> --type <type> --host <host> --database <db> [--level global|project]

# 列出连接
python scripts/db_manager.py list [--level global|project|effective]

# 查看详情
python scripts/db_manager.py show <name>

# 删除连接
python scripts/db_manager.py remove <name> [--level global|project]

# 测试连接
python scripts/db_manager.py test <name>

# 查看生效配置
python scripts/db_manager.py effective
```



#### `/schema` - 表结构定义管理
```
/schema <子命令> [参数]
/sc <子命令>  # 别名
/表结构 <子命令>  # 中文别名

管理表结构定义（列名、类型、描述），支持全局和项目级配置。
表结构定义作为 Agent 生成 SQL 的核心上下文，大幅提升 SQL 准确度。

列定义简写: "列名:类型:描述:flags"（flags: pk/required/nullable），多列逗号分隔

示例:
  /schema add --name orders --desc "订单表" \
    --columns "order_id:INT:订单ID:pk,amount:DECIMAL(18,2):金额:required,channel:VARCHAR:渠道"

  /schema list                           # 列出生效的表结构
  /schema show orders                    # 查看表结构详情
  /schema remove old_table --level global # 删除
```

执行: `python scripts/schema_manager.py add/list/show/remove/effective`

当用户输入不是显性指令时，通过关键词推断意图：

| 意图 | 触发关键词 | 执行 Scenario |
|------|-----------|---------------|
| 数据导入 | 上传、导入、import、load、打开文件、读取 | Scenario 1 |
| SQL 查询 | 查询、筛选、统计、分组、排序、select、group by | Scenario 2 |
| 数据清洗 | 清洗、去重、缺失值、异常值、标准化、日期格式、金额格式、唯一键、跨表校验 | /clean |
| 图表生成 | 图表、可视化、画图、chart、plot、展示、可视化 | Scenario 4 |
| 数据导出 | 导出、下载、export、保存、输出 | Scenario 6 |
| 表结构 | 表结构、字段、列、describe、schema | Scenario 10 |
| 导入历史 | 历史、导入记录、history | Scenario 10 |
| 指标管理 | 指标、口径、定义、metric | Scenario 8 |
| 服务管理 | 服务、服务器、启动、停止、server、start、stop | 直接执行 /start 或 /stop |
| Skill 更新 | 更新、拉取、update、pull、升级 | 执行 /echart-update |
| 自动分析 | 分析、洞察、发现、规律、趋势、异常、相关性、report、analyze | Scenario 16 |
| 报告生成 | 报告、总结、出报告、结论、写报告、生成报告 | Scenario 17 |
| 追问/继续 | 呢？、比呢？、刚才、上次、继续、深挖、为什么、换 | Scenario 18 |
| 趋势预测 | 预测、预估、趋势、forecast、预测未来、走向、接下来 | Scenario 19 |
| 归因分析 | 为什么、原因、驱动因素、归因、贡献、变化分析、why、explain | Scenario 20 |
| 数据库连接 | 连接、数据库连接、dbconn、配置连接、添加连接、测试连接、外部数据库、postgresql、mysql 连接 | /dbconn 子命令 |
| 表结构定义 | 表结构、schema、列定义、字段定义、建表、表定义 | /schema 子命令 |
| 会话管理 | 会话、上下文、context、session、对话历史、追问 | /context 子命令 |

---

## SQL Generation Protocol (CRITICAL)

> **重要**: 本项目使用 DuckDB 作为 SQL 引擎，其语法与 MySQL/PostgreSQL 有显著差异。为避免 SQL 执行错误，必须严格遵循以下流程。

### 函数类别索引

DuckDB 支持的 SQL 函数按以下类别组织（详见 `references/SQL_FUNCTIONS_REFERENCE.md`）：

| 类别 | 适用场景 | 典型函数 |
|------|----------|----------|
| **聚合函数** | 求和、计数、平均值、最值 | `SUM`, `COUNT`, `AVG`, `MAX`, `MIN`, `GROUP_CONCAT`→`string_agg` |
| **统计聚合函数** | 方差、标准差、相关性、分位数 | `STDDEV_SAMP`, `VAR_SAMP`, `CORR`, `MEDIAN`, `QUANTILE_CONT` |
| **近似聚合函数** | 大数据近似统计 | `APPROX_COUNT_DISTINCT`, `APPROX_QUANTILE` |
| **数值函数** | 数学计算、取整、三角函数 | `ROUND`, `CEIL`, `FLOOR`, `ABS`, `SQRT`, `POW`, `MOD`→`%` |
| **文本/字符串函数** | 字符串处理、拼接、正则 | `CONCAT`, `SUBSTRING`, `UPPER`, `LOWER`, `LENGTH`, `REGEXP_REPLACE` |
| **日期函数** | 日期计算、格式化 | `DATE_TRUNC`, `DATE_DIFF`, `LAST_DAY`, `STRFTIME`, `EXTRACT` |
| **时间函数** | 时间处理 | `MAKE_TIME`, `DATE_PART` |
| **时间戳函数** | 时间戳操作 | `EPOCH`, `STRPTIME`, `MAKE_TIMESTAMP`, `AGE` |
| **时间间隔函数** | 时间间隔计算 | `TO_DAYS`, `TO_HOURS`, `TO_MINUTES` |
| **窗口函数** | 排名、移动平均、前后值 | `ROW_NUMBER`, `RANK`, `LAG`, `LEAD`, `FIRST_VALUE`, `LAST_VALUE` |
| **列表函数** | 数组/列表操作 | `LIST_VALUE`, `LIST_FILTER`, `LIST_TRANSFORM`, `UNNEST` |
| **条件函数** | 条件判断、NULL处理 | `CASE WHEN`, `COALESCE`, `NULLIF`, `IF` |
| **工具函数** | 类型检查、UUID生成 | `TYPEOF`, `UUID`, `HASH` |

### SQL 生成流程（必须遵循）

```
┌─────────────────────────────────────────────────────────────────┐
│                    SQL 生成智能流程 (v2.0)                       │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Step 0: 🆕 表结构上下文加载（Agent 大模型能力）                   │
│  ├─ 根据用户需求推断涉及的表的语义名                                │
│  ├─ 加载生效的表结构定义:                                         │
│  │   python scripts/schema_manager.py effective                 │
│  ├─ 如无预定义 schema → 用 DESCRIBE/采样数据自动推断               │
│  └─ 将表名、列名、类型、描述作为 Agent 上下文                       │
│                                                                 │
│  Step 1: 需求分析                                                │
│  ├─ 结合表结构上下文分析用户查询意图                               │
│  ├─ 匹配需求中的指标/维度到实际列名（Agent 语义匹配）               │
│  └─ 如 "销售额" → 匹配 schema 中的 amount/sales/gmv 列           │
│                                                                 │
│  Step 2: 类别推断                                                │
│  ├─ 根据需求 + 列类型推断需要的函数类别                            │
│  └─ 示例：amount(DECIMAL) + 按月 → 聚合函数 + 日期函数             │
│                                                                 │
│  Step 3: 🆕 函数上下文提取（推断 + 精准摘取）                      │
│  ├─ 根据需求+列类型推断需要的函数类别（Agent 大模型推断）             │
│  ├─ 示例: DECIMAL列按月求和 → 聚合函数 + 日期函数                    │
│  ├─ 👇 精准提取对应函数文档（不读全文件）                            │
│  ├─ grep -n "^## <类别>$" references/SQL_FUNCTIONS_REFERENCE.md    │
│  ├─ Read references/SQL_FUNCTIONS_REFERENCE.md<起始行> limit=80    │
│  └─ 函数语法 + 参数说明 + 示例作为上下文                              │
│                                                                 │
│  📋 需求→类别推断表:                                              │
│  | 需求关键词 | 推断类别 | 提取命令 |                              │
│  |-----------|---------|---------|                              │
│  | 求和/计数/均值/最值 | 聚合函数 | grep "## 聚合函数" |             │
│  | 标准差/方差/分位数/相关性 | 统计聚合函数 | grep "## 统计聚合函数" | │
│  | 取整/绝对值/平方根/幂 | 数值函数 | grep "## 数值函数" |           │
│  | 字符串拼接/截取/正则/大小写 | 文本/字符串函数 | grep "## 文本" |  │
│  | 按月/按周/按年分组,日期差 | 日期函数 | grep "## 日期函数" |       │
│  | 排名/行号/移动平均/前后值 | 窗口函数 | grep "## 窗口函数" |       │
│  | NULL处理/条件分支 | 条件函数 | grep "## 工具函数" |              │
│  | 去重计数/近似统计 | 近似聚合函数 | grep "## 近似聚合函数" |       │
│                                                                 │
│                                                                 │
│  Step 4: SQL 生成（Agent 大模型核心能力）                         │
│  ├─ 上下文包含: 表结构 + 列类型 + 函数参考 + DuckDB 方言规则        │
│  ├─ 仅使用 schema 中存在的列名（避免幻觉列名）                     │
│  ├─ 列类型匹配正确的函数（如 DECIMAL → SUM/AVG，VARCHAR → COUNT）  │
│  └─ 对于不确定的函数，先查阅文档再使用                              │
│                                                                 │
│  Step 5: 执行验证                                                │
│  ├─ 执行 SQL，检查是否有错误                                      │
│  ├─ 如有错误 → Agent 用 schema 上下文修复（列名错？类型错？）       │
│  └─ 3 次失败 → 用 DESCRIBE 验证实际表结构 vs schema 定义          │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

**🆕 表结构上下文对 SQL 准确度的提升:**

| 无 Schema | 有 Schema |
|-----------|----------|
| Agent 猜测列名 → 可能用 `sales_amount` 但实际是 `amount` | Schema 明确列名 → Agent 直接用 `amount` |
| Agent 猜测类型 → VARCHAR 当数字用 `SUM` | Schema 指定 `DECIMAL(18,2)` → Agent 知道可用 `SUM` |
| 自然语言 "销售额" → Agent 不确定用哪列 | Schema 描述匹配 → 明确用 `amount`（描述:"订单金额"） |
| 多表 JOIN 时列名冲突 | Schema 区分 `orders.amount` vs `refunds.amount` |
| reAct 修复 3 轮才找到正确列名 | 第一轮就用对，减少重试 |

**Agent 自动推断 → Schema → Function 完整链路:**

```
用户: "分析各渠道订单金额和转化率"
    │
    ▼
Step 0: Agent 推断所需表
    ├── 关键词 "订单" → 可能表: orders, order_items
    ├── 关键词 "渠道" → 需要 channel/source 列
    ├── 关键词 "金额" → 需要 amount/gmv/price 列
    └── 关键词 "转化率" → 需要 status/conversion 列
    │
    ▼
Step 0: 加载 Schema 上下文
    └─ python scripts/schema_manager.py effective
    └─ orders: order_id(INT pk), amount(DECIMAL(18,2)), channel(VARCHAR), 
               status(VARCHAR), created_at(TIMESTAMP)
    │
    ▼
Step 2: Agent 推断所需 DuckDB 函数类别
    ├── SUM(amount) → 聚合函数
    ├── GROUP BY channel → 聚合函数
    ├── COUNT(*) / COUNT(CASE WHEN...) → 聚合函数 + 条件函数
    ├── 按月分组 → 日期函数 (date_trunc)
    └── 转化率计算→ 数值函数 (ROUND)
    │
    ▼
Step 3: 精准提取函数文档（只摘需要的内容）
    ├─ grep -n "^## 聚合函数" references/SQL_FUNCTIONS_REFERENCE.md → L33
    ├─ Read references/SQL_FUNCTIONS_REFERENCE.md33 limit=50
    │   → 获得: SUM, COUNT, COUNTIF, AVG, string_agg 语法+示例
    ├─ grep -n "^## 日期函数" references/SQL_FUNCTIONS_REFERENCE.md → L337
    ├─ Read references/SQL_FUNCTIONS_REFERENCE.md337 limit=45
    │   → 获得: DATE_TRUNC, DATE_DIFF, STRFTIME 语法+示例
    └─ grep -n "^## 条件函数\|^## 工具函数" ... → 获取 CASE/COALESCE
    │
    ▼
Step 4: Agent 上下文现在包含:
    ├── 表结构: orders(order_id, amount, channel, status, created_at)
    ├── 函数参考: SUM/COUNT/DATE_TRUNC 的 DuckDB 语法
    └── DuckDB 方言规则: string_agg 非 GROUP_CONCAT, date_trunc 非 DATE_FORMAT
    │
    ▼
精准 SQL (一次正确):
    SELECT 
        channel,
        SUM(amount) as total_amount,
        COUNT(*) as order_count,
        ROUND(COUNTIF(status = 'completed') * 100.0 / COUNT(*), 2) as conversion_pct
    FROM orders
    GROUP BY channel
    ORDER BY total_amount DESC
```

### 常见 MySQL → DuckDB 函数映射

| MySQL 函数 | DuckDB 替代 | 说明 |
|-----------|-------------|------|
| `GROUP_CONCAT(col, sep)` | `string_agg(col, sep)` | 聚合字符串连接 |
| `IFNULL(a, b)` | `COALESCE(a, b)` 或 `ifnull(a, b)` | NULL 替换 |
| `IF(cond, a, b)` | `if(cond, a, b)` 或 `CASE WHEN` | 条件表达式 |
| `DATE_FORMAT(date, '%Y-%m')` | `strftime(date, '%Y-%m')` | 日期格式化 |
| `DATEDIFF(a, b)` | `date_diff('day', a, b)` | 日期差值 |
| `NOW()` | `CURRENT_TIMESTAMP` 或 `today()` | 当前时间 |
| `SUBSTRING(str, pos, len)` | `substring(str, pos, len)` | 子串（1-based） |
| `CONCAT_WS(sep, a, b)` | `concat_ws(sep, a, b)` | 带分隔符连接 |
| `FIND_IN_SET(str, list)` | `list_contains(string_split(list, ','), str)` | 列表查找 |
| `REGEXP_LIKE(str, pattern)` | `regexp_matches(str, pattern)` | 正则匹配 |
| `MOD(a, b)` | `a % b` | 取模运算 |
| `POWER(x, y)` | `pow(x, y)` 或 `x ** y` | 幂运算 |

### reAct 错误修复流程

当 SQL 执行出错时，按照以下 reAct 循环进行修复：

```
┌─────────────────────────────────────────────────────────────────┐
│                    reAct 修复循环                                │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  1. Thought: 分析错误信息                                         │
│     ├─ 错误类型：函数不存在？语法错误？类型不匹配？                  │
│     └─ 定位问题：哪个函数/语法导致了错误？                         │
│                                                                 │
│  2. Action: 查阅文档                                              │
│     ├─ 在 SQL_FUNCTIONS_REFERENCE.md 中搜索正确函数               │
│     └─ 或搜索类别索引找到替代方案                                  │
│                                                                 │
│  3. Observation: 确认修复方案                                     │
│     ├─ 验证新函数的语法和参数                                      │
│     └─ 确保与 DuckDB 兼容                                         │
│                                                                 │
│  4. Retry: 重新执行                                               │
│     ├─ 应用修复后的 SQL                                           │
│     └─ 如仍有错误，返回 Step 1                                     │
│                                                                 │
│  5. Fallback: 最多 3 次重试                                       │
│     ├─ 3 次失败后，考虑使用 Python + pandas 替代                   │
│     └─ 或向用户说明限制，寻求替代需求                               │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 示例：完整 SQL 生成过程

**用户需求**: "统计每个产品类别的月销售额，找出销售额前10的月份"

**Step 1 - 需求分析**:
- 聚合：按类别和月份分组求和
- 日期处理：从日期字段提取月份
- 排序：按销售额降序
- 限制：取前10

**Step 2 - 类别推断**:
- 聚合函数 → `SUM`, `GROUP BY`
- 日期函数 → `date_trunc` 或 `strftime`
- 窗口函数（可选）→ `ROW_NUMBER` 或直接用 `ORDER BY + LIMIT`

**Step 3 - 提取函数上下文**:
```markdown
# 从 SQL_FUNCTIONS_REFERENCE.md 读取：
- date_trunc(part, date) - 截断到指定精度
- SUM(arg) - 求和
- string_agg(arg, sep) - 字符串聚合
```

**Step 4 - 生成 SQL**:
```sql
SELECT 
    category,
    date_trunc('month', sale_date) as month,
    SUM(amount) as total_sales
FROM sales
GROUP BY category, date_trunc('month', sale_date)
ORDER BY total_sales DESC
LIMIT 10;
```

**Step 5 - 执行验证**: 
- 成功 → 返回结果
- 失败 → 进入 reAct 流程

---

## Scenarios & Procedures

### Scenario 1: Data Import & Auto-Cleaning
**Trigger**: User uploads or specifies a CSV/Excel/WPS(.et)/Numbers file.
**Action**:
1. Run the built-in importer script (supports `.csv`, `.xlsx`, `.xls`, `.et`, `.numbers`):
   ```bash
   python scripts/data_importer.py "path/to/file.xlsx" --db workspace.duckdb
   ```
   *Note: This script calculates the MD5 hash of the file. If an identical file was already imported, it skips the import and returns the existing table name. It also automatically handles merged cells, detects the real header row, chunks large CSVs, and sanitizes column names for DuckDB.*
2. Once imported, run a quick check to understand the schema and data:
   ```bash
   python -c "import duckdb; conn = duckdb.connect('workspace.duckdb'); print(conn.execute('DESCRIBE table_name').fetchdf())"
   python -c "import duckdb; conn = duckdb.connect('workspace.duckdb'); print(conn.execute('SELECT * FROM table_name LIMIT 3').fetchdf())"
   ```
3. Ask the user if they want to perform standard cleaning (e.g., handling missing values, deduplication). Execute these via SQL.

### Scenario 2: Continuous Queries & Manipulation
**Trigger**: User asks to filter, sort, aggregate, or add columns.
**Action**:
1. **SQL Generation with Function Validation**: Follow the intelligent SQL generation workflow (see `SQL Generation Protocol` section below).
2. Execute it via `RunCommand`: `python -c "import duckdb; conn = duckdb.connect('workspace.duckdb'); print(conn.execute('SELECT ...').fetchdf())"`
3. For structural changes, remember the Undo principle: `CREATE TABLE table_name_step2 AS SELECT ...`
4. **Error Handling**: If SQL execution fails, use the reAct recovery process (see `SQL Error Recovery (reAct)` section below).

### Scenario 3: Semantic Extraction & Fuzzy Join
**Trigger**: User wants to split addresses, do sentiment analysis, or join tables with mismatched keys (e.g., "Beijing Branch" vs "Beijing Office").
**Action**:
1. Generate a Python script using `pandas` and `duckdb`.
2. For Fuzzy Joins, use libraries like `thefuzz` or `difflib` in the Python script to match keys, then write the mapping back to DuckDB.
3. For Semantic extraction, use regex or heuristic rules in Python. If LLM analysis is strictly required, write a script that processes the column locally or prompts the user for permission to send a sample.

### Scenario 4: Chart Generation
**Trigger**: User requests a visualization (bar, pie, line, scatter, map, funnel, 3D charts, Gantt, etc.).
**Action**:

#### 🎯 ECharts 图表生成 — 零模板，纯 .md 驱动

> ⛔ **每个 `.md` 是自包含图表配方——包含完整 JS 代码 + 数据替换点 + HTML 壳。**

```
用户请求 "/chart bar 销售额"
 ↓
Step 1: DuckDB 查询真实数据
   └─ SQL → 获取实际数据行
 ↓
Step 2: 搜索匹配的图表配方
   └─ python scripts/reference_assets.py search "bar 销售额" --limit 5
   └─ 或直接查 references/examples.md 的 INDEX 表（前 ~370 行）
 ↓
Step 3: 精准读取配方 → 获取 JS 代码
   └─ python scripts/reference_assets.py get <chart-name> --line  → 获取行号
   └─ Read references/examples/<name>.md<行号> limit=200  → 精准读取配方内容
 ↓
Step 4: 替换 data 数组为 DuckDB 真实数据
   └─ regex: data: [...] → data: [真实值]
 ↓
Step 5: 包裹 HTML 壳（echarts inline + div#main + script）
 ↓
Step 6: 对照 docs/CHART_DEBUG_LOG.md 避坑（34 条）
 ↓
Step 7: validate_chart.py 硬校验（Single File + Dashboard + 渲染）
   └─ python scripts/validate_chart.py <output.html>
 ↓
通过→返回用户 / 失败→修复→重试
```

**关键原则**：
- ❌ 不用 `build_template.py`（模板系统已废弃）
- ❌ 不用 `{{PLACEHOLDER}}`（占位符系统已废弃）
- ✅ 所有 354 个图表配方合并为 **单个 `references/examples/*.md`**（含 INDEX 表 + 配方正文）
- ✅ Agent 只需：DuckDB + `.md` 配方代码 + 数据替换 → HTML
- ✅ 案例检索用 `reference_assets.py search` 或直接读 INDEX 表（前 ~370 行），不再扫目录

**组合图双坐标硬规则**：
- 折线图 + 柱状图组合时，先判断指标单位和量级。只要单位不同（如金额 vs 转化率、订单数 vs 留存率）或两组最大值相差约 5 倍以上，必须使用双 y 轴。
- 柱状系列默认使用左轴 `yAxisIndex: 0`，折线系列默认使用右轴 `yAxisIndex: 1`；不要把不同量级的柱线系列放在同一个 `value` 轴上，否则小量级折线会贴地。
- 两个 y 轴必须写清楚 `name` 和 `axisLabel.formatter`，让用户能看懂统计口径和单位。无单位时使用真实字段名，不要虚构 KPI 或目标口径。
- 该规则适用于普通 `/chart`、Dashboard 子图表、Report 图表举证和所有基于 `references/examples/*.md` 的图表生成。

### 🗺️ 生成模式决策树（统一流程 — 所有图表走 examples.md 配方）

```
用户图表需求
    │
    ├── 是单个图表？
    │   └── 🎯 统一知识库模式
    │       1. search 或读 INDEX 表 → 定位 chart-name + 行号
    │       2. Read references/examples/<name>.md<行号> limit=200 → 获取配方 JS 代码 + 数据替换指南
    │       3. SQL/Python 查询 DuckDB → 按配方格式转换数据
    │       4. Agent 内联 ECharts + 包裹 HTML 壳 → 输出
    │       5. validate_chart.py 硬校验
    │
    ├── 是多个图表组合？(dashboard / 混合布局)
    │   ├── 每个子图表独立走统一流程
    │   ├── 用 grid/flex 布局将多个图表放入一个 HTML
    │   └── 每个图表独立 init + setOption，所有 JS 内联
    │
    └── 是 Dashboard？（3+ 图表 + 交互）
        └── 🟣 Dashboard 模式
            1. 读取 workflow_specs/dashboard_workflow.md
            2. 自然语言描述 → Agent 建立 KPI 树和布局层级
            3. SQL/Python 只负责取数和计算证据
            4. Agent 直接生成 standalone HTML + ECharts
            5. 参考 Scenario 15
```

### 🎯 统一知识库模式（唯一模式）

每次图表生成使用 **`references/examples/*.md` 中的 1 个配方**：

1. **搜索**：`python scripts/reference_assets.py search "<类型 特征>"` → 获取 chart-name + 行号
2. **读取**：`Read references/examples/<name>.md<行号> limit=200` → 获取 JS 代码 + 数据替换指南
3. **取数**：从 DuckDB 查询数据 → 按配方格式转换
4. **生成**：Agent 内联 ECharts + 包裹 HTML 壳 → 输出
5. **校验**：`python scripts/validate_chart.py <output.html>`

**多图表组合**：每个子图表独立走上述流程 → grid/flex 布局组装 → 单 HTML 输出

### 🗺️ 检索决策树（必须执行）

```
用户请求图表
    │
    ├── 图表是什么类型？
    │   ├── bar/line/pie/scatter → chart-types/0X-*.md
    │   └── candlestick/radar/gauge/funnel/sankey/treemap/sunburst/
    │       graph/tree/heatmap/parallel/boxplot/calendar/map/geo/
    │       pictorialBar/themeRiver/custom → 直接用案例代码作主参考
    │
    ├── 需要什么概念？
    │   ├── 数据绑定 → concepts/01-dataset.md
    │   ├── 颜色/大小映射 → concepts/02-visual-map.md
    │   ├── 数据筛选/排序 → concepts/03-data-transform.md
    │   ├── 样式定制 → concepts/04-style.md
    │   ├── 点击交互 → concepts/05-event.md
    │   ├── 坐标轴配置 → concepts/06-axis.md
    │   ├── 图例配置 → concepts/07-legend.md
    │   └── 容器/响应式 → concepts/08-chart-size.md
    │
    ├── 需要什么模式？
    │   ├── 渲染器选择 → patterns/01-canvas-vs-svg.md
    │   ├── 动画效果 → patterns/02-animation.md
    │   ├── 富文本标签 → patterns/03-rich-text.md
    │   ├── 异步数据加载 → patterns/04-dynamic-data.md
    │   ├── 窗口适配 → patterns/05-responsiveness.md
    │   ├── 用户数据安全 → patterns/06-security.md
    │   ├── 无障碍 → patterns/07-accessibility.md
    │   ├── SVG 底图 → patterns/08-svg-base-map.md
    │   ├── 拖拽交互 → patterns/09-drag-interaction.md
    │   └── 按需引入 → patterns/10-import-strategy.md
    │
    └── 案例匹配（必须做！）
        ├── 优先搜索：`python scripts/reference_assets.py search "<特征>" --limit 5`
        └── 获取行号：`python scripts/reference_assets.py get <chart-name> --line`
            → Read references/examples/<name>.md<行号> limit=200
```


### 📂 文件路径速查

| 类别 | 路径 |
|------|------|
| **图表配方（唯一参考）** | `references/examples/*.md` — 354 个配方合并为 1 个文件，INDEX 表 + 配方正文 |
| 知识库索引 | `references/knowledge/INDEX.md` |
| 案例索引 | `references/knowledge/examples/INDEX.md` |
| 概念文件 | `references/knowledge/concepts/` |
| 图表类型文件 | `references/knowledge/chart-types/` |
| API 文件 | `references/knowledge/api/` |
| 模式文件 | `references/knowledge/patterns/` |
| 案例检索脚本 | `scripts/reference_assets.py` |

> **唯一参考格式**：每次图表生成使用 1 个 `.md` 配方文件。`.md` 包含完整 JS 代码 + 数据替换指南 + HTML 壳指令，是唯一的图表生成参考源。

### 📦 案例检索规则

所有图表配方合并为 **单个 `references/examples/*.md`**（22MB），INDEX 表在文件前 ~370 行。

**方式一：搜索（首选）**
```bash
python scripts/reference_assets.py search "bar waterfall" --limit 5
# → bar-waterfall  type=bar  L8784  (L=行号)
```

**方式二：获取行号 + 精准读取**
```bash
python scripts/reference_assets.py get bar-waterfall --line
# → 8784
```
然后用 Read 工具：`Read references/examples/<name>.md8784 limit=200`

**方式三：直接读 INDEX 表**
```bash
Read references/examples.md limit=50  # INDEX 在前 ~370 行，一次读不完可分页
```

**限定类型**：
```bash
python scripts/reference_assets.py search "race" --chart-type bar --limit 5
python scripts/reference_assets.py list --chart-type line --limit 20
```

---

#### 📋 图表配置生成（原有流程）

1. 执行上述 4 步工作流获取语法约束和参考代码。
2. Do NOT write custom Python scripts for chart generation. Use the Agent-driven workflow: DuckDB query → md reference → data replace → inline ECharts → HTML output.
3. Formulate the SQL query that aggregates the data correctly.
4. Generate the `custom_js` and `echarts_option` based on the knowledge + examples.
5. Construct a JSON configuration file (save it in `outputs/configs/`) matching this structure:
   ```json
    {
        "db_path": "workspace.duckdb",
       "query": "SELECT category, SUM(value) as val FROM table GROUP BY category",
       "title": "Chart Title",
       "output_path": "<echart-skill路径>/outputs/html/output_chart.html",
       "echarts_option": { ... }, // Generated option from prompt
       "custom_js": "..." // Optional JS logic for complex data binding
   }
```
    *Note: Output files MUST be stored in the isolated `outputs/html/` directory.*
    

### 🔒 Single File 模式 — 硬性铁律

> ⛔ **绝对禁止使用任何外部 URL 引用！！所有 CSS、JS、字体、地图数据必须内联到单个 HTML 文件中。**

```
┌─────────────────────────────────────────────────────────────────┐
│                    Single File 铁律                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ❌ 禁止: <script src="https://cdn..."></script>                 │
│  ❌ 禁止: <script src="echarts.min.js"></script>                 │
│  ❌ 禁止: <link rel="stylesheet" href="...">                     │
│  ❌ 禁止: <script src="./local-file.js"></script>                │
│  ❌ 禁止: @import url(...)                                       │
│  ❌ 禁止: $.get() fetch 远程 GeoJSON                             │
│                                                                 │
│  ✅ 必须: <script>/* echarts 完整库代码内联 */</script>          │
│  ✅ 必须: <style>/* 所有 CSS 样式内联 */</style>                 │
│  ✅ 必须: 地图数据由 generator 自动内联注入                       │
│  ✅ 必须: 输出为单个 .html 文件，双击浏览器即可打开              │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

**实现方式**：
- 生成 ECharts option 时，**不写任何 `<script src=...>` 或 `<link href=...>`**
- 只要 HTML 中出现 `echarts.init`，就必须在它之前内联完整的 `assets/echarts/echarts.min.js`；CDN、相对路径、本地文件路径、占位 stub 都不合格
- `new echarts.graphic.LinearGradient(...)` / `RadialGradient(...)` 必须先闭合构造函数 `)`，再闭合 option 对象；少一个括号会让整页图表初始化脚本失败
- 地图数据（china.js, world.js 等）由 generator 自动处理内联，不在 option 中引用
- 百度地图 SDK 是唯一例外（必须远程加载），仅在用户配置了 `BAIDU_AK` 且使用 bmap 模式时才允许

### ⚠️ ECharts 关键规则
    **CRITICAL ECHARTS RULES**:
    1. **Pie on Map**: The ECharts `pie` series DOES NOT support `coordinateSystem: 'geo'`. If the user asks to display data on a map, you MUST use `scatter` or `effectScatter` series with bubble sizes representing the values. NEVER attempt to put a pie chart on a geo map directly.
    
    2. **Map Generation Priority (CRITICAL)**:
       - **Local Static Maps (First Choice)**: For China provinces (`"map": "china"`), World countries (`"map": "world"`), or Chinese provinces (`"map": "guangdong"`, `"map": "beijing"`), ALWAYS use local static map JS files directly. DO NOT use `$.get()` to fetch GeoJSON from remote URLs. DO NOT use `echarts.registerMap()` for these standard maps. Just set `"map": "china"` or `"map": "world"` in the series config - the generator will auto-inject the correct JS file.
       
       - **Example (CORRECT)**:
         ```json
         {
           "series": [{
             "type": "map",
             "map": "china",  // Directly use map name
             "roam": true,
             "data": [{"name": "北京", "value": 15000}]
           }]
         }
         ```
       
       - **Example (WRONG - DO NOT USE)**:
         ```javascript
         // ❌ DO NOT use $.get for local static maps
         $.get(ROOT_PATH + '/data/asset/geo/china.json', function(geoJSON) {
           echarts.registerMap('china', geoJSON);  // Unnecessary!
         });
         ```
       
       - **BMap Mode (Fallback)**: Use `"bmap"` mode only when local static maps don't cover the required granularity (e.g., city-level data without province map, street-level data, or specific foreign countries not in world.js). This requires `BAIDU_AK` environment variable.
    
    3. **Baidu AK Types**: If the user provides a Baidu Map AK, remember there are two types: 1) JavaScript API (Frontend) and 2) Geocoding API (Backend Python). If backend Python geocoding fails with "status 240", it means the AK is a Browser-type AK and lacks Backend Geocoding permissions. Fallback to hardcoded coordinates in JS or ask for a "Server-side" AK.
    
     7. Execute the command:

 8. **[CRITICAL] Return Chart Access**: After generating the chart, check the server configuration:

    ```bash
    # Check config: is server enabled?
    python -c "from scripts.config_manager import get_config; print(get_config().server.enabled)"
    ```

    **If server is disabled (default)**:
    - The chart is a self-contained HTML file (all JS embedded inline).
    - Return the absolute file path directly:
    ```
    ✅ 图表已生成: /absolute/path/to/outputs/html/sales_chart.html
    📂 可在浏览器中直接打开: file:///absolute/path/to/outputs/html/sales_chart.html
    ```

    **If server is enabled** (user has set `server.enabled=true` in `echart_config.txt`):
    - Start or check the server:
      ```bash
      python scripts/server_cli.py status
      python scripts/server_cli.py start  # auto-starts if not running
      ```
    - Return the access URL:
    ```
    ✅ Chart generated: outputs/html/sales_chart.html
    📊 View chart: http://localhost:{port}/outputs/html/sales_chart.html
    ```
    - If server start fails, retry once. If still fails, fall back to showing the local file path.

    **IMPORTANT**: All generated HTML files are now **self-contained** — they embed the ECharts library and all map scripts inline, so they work offline without any server.

 9. **[MANDATORY] Validate the generated HTML** before returning to the user:

    ```bash
    python scripts/validate_chart.py "outputs/html/sales_chart.html"
    ```

    The validator checks:
    - **Single File compliance**: NO external `<script src=...>`, NO external `<link href=...>`, NO hardcoded IP:port URLs
    - **ECharts library integrity**: `echarts.init` 前必须已有完整内联 `assets/echarts/echarts.min.js`
    - **ECharts JS syntax**: 拦截 `LinearGradient` / `RadialGradient` 少括号、formatter 字符串换行等会导致整页空白的问题
    - **Dashboard integrity** (if applicable): DashboardController, html2canvas, jsPDF must all be inlined
    - **Basic rendering**: echarts.init, setOption, chart type, data must be present

    ⛔ **If validation fails (exit code 1): FIX the errors and re-validate BEFORE returning to user.** This is the last line of defense — validation errors that reach the user are bugs.

### Scenario 5: File Merging & Splitting
**Trigger**: User needs to combine multiple identical reports or split a master sheet by department.
**Action**:
- **Merge**: Iterate over the files and run `data_importer.py` pointing to the *same* table name (the script appends automatically if the table exists, or write a custom Python script).
- **Split**: Generate a Python script that reads the master table from DuckDB and exports it into multiple Excel files using `pandas.DataFrame.to_excel()` inside a loop.

### Scenario 6: Export & Reporting
**Trigger**: User wants to download the final result or generate a summary report.
**Action**:
1. **Export CSV/Excel**: Use the built-in exporter script to dump a table or query result to `.csv` or `.xlsx`:
   ```bash
   # Export an entire table
   python scripts/data_exporter.py "outputs/final_result.csv" --table "final_table"
   
   # Export a specific query
   python scripts/data_exporter.py "outputs/final_result.xlsx" --query "SELECT category, SUM(value) FROM sales GROUP BY category"
   ```
2. **Report Generation**: Write a Markdown file summarizing the analysis steps, key metrics (retrieved via SQL), and referencing any generated charts. Provide the user with the path to the report.

### Scenario 7: Data Cleanup
**Trigger**: Routine maintenance or user request to clean up old data.
**Action**:
1. Run the cleaner script to remove tables and metadata not accessed in the last 30 days:
   ```bash
   python scripts/data_cleaner.py --db workspace.duckdb --days 30
   ```

### Scenario 8: Metrics Management
**Trigger**: User describes or defines a specific metric calculation logic or business definition (口径).
**Action**:
1. When the user provides a metric definition, save it to the local markdown file `references/metrics.md` to build up context for future SQL generation.
2. Use the built-in script `scripts/metrics_manager.py` to append the metric:
   ```bash
   python scripts/metrics_manager.py --name "Metric Name" --desc "Metric calculation logic or business description"
   ```
3. When generating SQL queries later, ALWAYS read `references/metrics.md` to ensure the generated SQL aligns with the saved business definitions.

### Scenario 9: Gantt Chart Generation
**Trigger**: User requests project timeline or task schedule visualization.
**Action**:
1. Agent reads `references/examples/custom-gantt-flight.md` for Gantt chart structure reference
2. Agent queries DuckDB for task data (name, start, end dates)
3. Agent generates ECharts Gantt option with `type: 'custom'` + renderItem function
4. Agent wraps in HTML shell (inline ECharts + div#main + script)
5. Return chart access: follow server config — file path by default (server.enabled=false), URL only if server.enabled=true (see Scenario 4 step 8)

**Note**: Gantt charts use ECharts `custom` series type. Dates can be ISO strings or datetime objects.

### Scenario 10: View Import History & Table Structure
**Trigger**: User asks to view import history, check table structures, or see table relationships.
**Action**:
1. **查看导入历史**: Run `python scripts/data_importer.py history --db workspace.duckdb [--limit 20]`
2. **查看指定表结构**: Run `python scripts/data_importer.py structure --db workspace.duckdb --table TABLE_NAME`
3. **查看所有表结构**: Run `python scripts/data_importer.py structure --db workspace.duckdb`
4. **查看表关联关系**: Run `python scripts/data_importer.py relationships --db workspace.duckdb`
5. **一键查看全部**: Run `python scripts/data_importer.py show --db workspace.duckdb`

**Example output**:
```
## 导入历史

| 文件名           | 表名      | 行数 | 导入时间            | 文件路径              |
| -------------- | ------- | -- | --------------- | ----------------- |
| sales.xlsx     | sales   | 1500 | 2026-04-11 10:30 | /path/to/sales.xlsx |

## 表结构: sales

**行数:** 1500

| 列名   | 类型      | 可空  |
| ---- | ------- | --- |
| id   | VARCHAR | YES |
| name | VARCHAR | NO  |
```

### Scenario 11: Export Charts for Offline Sharing
**Trigger**: User wants to share charts/dashboards as standalone HTML files that work offline.

**Action**: Agent generates standalone HTML by inlining ECharts library (~1.1MB). Same workflow as Scenario 4:
1. DuckDB query → real data
2. Read md reference → chart structure
3. Replace data → generate option
4. Wrap with inline ECharts + div#main + script → standalone HTML

**Key Features:**
- Exported files are self-contained (~1.2MB with ECharts library)
- Work offline without any server
- Can be shared via email or file transfer
- Open in any modern browser

### Scenario 12: Batch Export (Agent-driven)
**Trigger**: User needs to export multiple charts for batch processing or automation.

**Action**: Agent executes Scenario 4 workflow for each chart in batch:
1. For each config, read md reference → DuckDB query → replace data → generate HTML
2. Return chart access: follow server config — file paths by default, URLs only if server.enabled=true

**Config File Format:**
```json
{
    "title": "销售数据图表",
    "db_path": "workspace.duckdb",
    "query": "SELECT category, SUM(amount) as total FROM sales GROUP BY category",
    "echarts_option": {
        "xAxis": {"type": "category"},
        "yAxis": {"type": "value"},
        "series": [{"type": "bar"}]
    }
}
```

**Gantt Task Config Format (for export-gantt):**
```json
[
    {"name": "需求分析", "start": "2024-01-01", "end": "2024-01-15"},
    {"name": "系统设计", "start": "2024-01-10", "end": "2024-01-25"},
    {"name": "开发实现", "start": "2024-01-20", "end": "2024-02-20"}
]
```

**Command Parameters:**
- `<config>`: Config file path (`.txt`; complex chart payloads may use JSON content)
- `--output`, `-o`: Output HTML path (optional, default: `{title}_{timestamp}.html`)
- `--theme`: Chart theme (`default` or `dark`, default: `default`)
- `--title`: Gantt chart title (export-gantt only)

**View Help:**
```bash
```

**Batch Export Example:**
```bash
# Batch chart generation (Agent-driven)
# Agent: for each config, read md → DuckDB → replace → generate HTML
for config in outputs/configs/*.json; do
    # Use /chart command or Scenario 4 workflow
done

# Automated daily report (Agent-driven)
# Agent: /dashboard with date parameter
```

**Notes:**
- Exported HTML files work offline (ECharts library embedded)
- File size ~1.2MB per export (includes ECharts library)
- Chinese characters are preserved correctly
- Generated filename format: `{sanitized_title}_{YYYYMMDD_HHMMSS}.html`

### Scenario 13: External Database Connections
**Trigger**: User needs to query data from MySQL, PostgreSQL, or MongoDB databases.

**Action:**

**1. Configure Connections via /dbconn (Recommended):**

```bash
# 添加全局 PostgreSQL 连接
/dbconn add --name analytics --type postgresql --host localhost --database analytics --username reader --password '${PG_PASSWORD}'

# 添加项目级 MySQL 连接（仅当前目录生效）
/dbconn add --name prod --type mysql --host db.internal --database production --level project --username admin --password '${MYSQL_PASS}'

# 添加 MongoDB 连接
/dbconn add --name mongo_logs --type mongodb --connection-string '${MONGO_URI}'
```

**2. 或手动编辑配置文件:**

支持三级配置（优先级从高到低）：

| 级别 | 配置文件路径 | 生效范围 |
|------|-------------|---------|
| **项目级** | `<当前项目>/.echart-skill/db_connections.txt` | 仅该项目目录及子目录 |
| **传统** | `<当前目录>/db_connections.txt` | 当前目录及父目录 |
| **全局** | `<echart-skill>/references/db_connections.txt` | 所有项目 |

配置格式：
```ini
[connections.analytics]
type=postgresql
host=localhost
port=5432
database=analytics
username=reader
password=${PG_PASSWORD}
```

**3. Set Environment Variables for Secrets:**
```bash
export PG_PASSWORD=your_password
export MYSQL_PASS=your_password
export MONGO_URI="mongodb://user:pass@localhost:27017/docs"
```

**4. 管理连接:**
```bash
# 查看所有连接
/dbconn list

# 查看全局连接
/dbconn list --level global

# 查看项目连接
/dbconn list --level project

# 查看连接详情（密码自动脱敏）
/dbconn show analytics

# 测试连接
/dbconn test analytics

# 删除连接
/dbconn remove old_db  # 默认全局
/dbconn remove local_db --level project
```

**5. Query Database:**
```bash
# Execute SQL query (使用有效配置)
python scripts/db_cli.py query analytics "SELECT * FROM orders WHERE date > '2024-01-01'"

# Query from file
python scripts/db_cli.py query analytics --file queries/monthly_sales.sql --output json

# MongoDB query (requires --collection)
python scripts/db_cli.py query mongo_logs '{"status": "active"}' --collection users
```

**6. Discover Schema:**
```bash
# List tables
python scripts/db_cli.py list-tables analytics

# List PostgreSQL tables in specific schema
python scripts/db_cli.py list-tables analytics --schema public

# Describe table structure
python scripts/db_cli.py describe-table analytics users

# MongoDB: list databases
python scripts/db_cli.py list-tables mongo_logs --show-databases

# MongoDB: list collections
python scripts/db_cli.py list-tables mongo_logs --database docs

# MongoDB: infer collection schema
python scripts/db_cli.py describe-table mongo_logs users
```

**7. Import to DuckDB:**
```bash
# Import SQL query results to DuckDB
python scripts/db_cli.py import analytics "SELECT * FROM customers" --table-name customers_import

# Import with custom DuckDB path
python scripts/db_cli.py import analytics "SELECT * FROM sales" --duckdb analytics.duckdb

# Import MongoDB collection
python scripts/db_cli.py import mongo_logs '{}' --collection users --table-name mongo_users
```

**8. After Import, Use with Charts:**
```json
{
    "db_path": "workspace.duckdb",
    "query": "SELECT * FROM customers_import",
    "title": "Imported Customers",
    "echarts_option": {
        "xAxis": {"type": "category"},
        "yAxis": {"type": "value"},
        "series": [{"type": "bar"}]
    }
}
```

**Key Features:**
- ✅ **三级配置**: 全局（所有项目共享）/ 项目级（当前目录生效）/ 传统（向后兼容）
- ✅ **连接管理**: `/dbconn` 独立指令管理连接生命周期
- ✅ **密码安全**: 使用 `${ENV_VAR}` 占位符，展示时自动脱敏
- ✅ **自动发现**: 查询时自动合并全局 + 项目级配置
- ✅ **连接测试**: `/dbconn test` 验证连接可用性
- ✅ **流式导入**: 大数据量（>10K 行）自动流式处理
- ✅ **元数据追踪**: 导入记录存储在 `_data_skill_meta` 表
- 🆕 **审计追溯**: 外部查询自动记录到审计日志（与 DuckDB 同一 Pipeline）
- 🆕 **隐私脱敏**: 外部查询结果自动经过 PrivacyGuard PII 检测与脱敏
- 🆕 **Query Hash**: 每条外部查询生成 SHA256 hash，可追溯但不可逆
- ✅ 支持 MySQL、PostgreSQL（SQLAlchemy）、MongoDB（PyMongo）

**Notes:**
- 项目级连接同名覆盖全局连接
- Default connection timeout: 30 seconds (override with `--timeout`)
- MongoDB documents are flattened for tabular storage (nested fields become `parent_child`)
- Arrays in MongoDB are expanded to indexed fields (`skills_0`, `skills_1`)

---

### 🔍 数据库连接自动识别与数据分析流程

> ⚠️ **核心原则**: 外部数据库**直接查询**，不导入 DuckDB。DuckDB 导入仅在用户需要反复分析、跨表 join、或离线使用时才做。

**自动识别决策树：**

```
用户提出数据分析需求
    │
    ├── 用户是否指定了连接名？（如 "分析 analytics 库的 orders 表"）
    │   └── ✅ 是 → 直接使用指定连接名
    │
    ├── 当前是否有已配置的数据库连接？
    │   ├── 检查有效连接：python scripts/db_manager.py list
    │   │
    │   ├── 有 1 个连接 → 自动使用该连接
    │   │
    │   ├── 有多个连接 → 按以下优先级匹配：
    │   │   1. 连接名与用户提到的关键词匹配（如 "analytics"、"prod"）
    │   │   2. 数据库名与用户提到的表/数据源匹配
    │   │   3. 连接类型匹配（如用户提到 PostgreSQL → 匹配 postgresql 连接）
    │   │   4. 无法匹配 → 列出可用连接，询问用户
    │   │
    │   └── 无连接 → 提示用户配置：
    │       "未找到数据库连接。你可以：
    │        1. 使用 /dbconn add 添加连接
    │        2. 直接上传 CSV/Excel 文件进行分析"
    │
    └── 连接确定后 → 直接查询分析流程
```

**🟢 直接查询分析流程（默认，推荐）：**

```
Step 1: 确定目标连接
    └─ python scripts/db_manager.py list
    └─ 匹配/选择连接名

Step 2: 探索远程数据库结构
    └─ python scripts/db_cli.py list-tables <连接名>
    └─ python scripts/db_cli.py describe-table <连接名> <表名>

Step 3: 直接在远程数据库执行查询 → 拿数据
    └─ python scripts/db_cli.py query <连接名> "SELECT ..." --output json
    └─ Agent 拿到 JSON 数据后直接用于图表/分析/报告

Step 4: 数据 → 图表 / 分析 / 报告
    └─ 图表: 数据替换 ECharts option → 生成 HTML
    └─ 分析: /analyze 直接基于查询结果
    └─ 报告: /report 直接基于查询结果
```

**🟡 DuckDB 导入流程（仅在以下场景使用）：**

> 只在以下情况才导入 DuckDB：
> - 用户明确说"导入到本地"
> - 需要对多张远程表做 JOIN 或跨库查询
> - 数据量大且需要反复分析（避免重复查询远程库）
> - 需要离线使用

```
python scripts/db_cli.py import <连接名> "SELECT * FROM <表名>" --table-name <本地表名>
# 之后在 DuckDB 中分析：/query SELECT ... FROM <本地表名>
```

**自动识别示例：**

| 用户输入 | Agent 行为 |
|---------|-----------|
| "分析 sales 数据" | 1. 检查有效连接 → 发现 `analytics` 连接<br>2. `list-tables analytics` → 有 `sales` 表<br>3. `query analytics "SELECT * FROM sales LIMIT 5"` 看结构<br>4. **直接查询** `analytics` 拿数据 → `/chart` `/report` |
| "查看 PostgreSQL 里的订单趋势" | 1. 匹配 `type=postgresql` 的连接<br>2. 描述表结构，找订单表<br>3. **直接查** `SELECT date, SUM(amount) FROM orders GROUP BY date`<br>4. 数据 → 折线图 |
| "各渠道销售额占比" | 1. 自动发现连接<br>2. **直接查** `SELECT channel, SUM(amount) FROM orders GROUP BY channel`<br>3. 数据 → 饼图 |
| "把 orders 表导入本地分析" | 1. 用户明确说"导入" → 触发 DuckDB 导入<br>2. `import analytics "SELECT * FROM orders" --table-name orders`<br>3. 后续在 DuckDB 中 join/分析 |
| "帮我看看数据库里有什么" | 1. 列出所有有效连接<br>2. 逐个 `list-tables` 展示结构<br>3. 询问用户想分析哪个表 |

### Scenario 15: Dashboard Generation (Simplified Natural Language)
**Trigger**: User needs to create multi-chart dashboards with natural language.

**Method 1: Natural Language Description (Recommended)**

Simply describe what you want in plain language:

```
/dashboard 创建销售分析仪表盘，包含：
- 各地区销售柱状图
- 产品类别饼图
- 月度趋势折线图
- 全国分布地图
```

**Method 2: Agent Dashboard Workflow**

1. 读取 `workflow_specs/dashboard_workflow.md`
1.1. 读取 `workflow_specs/dashboard_runtime_quality.md`，把 Single File、地图、PDF 导出和浏览器 smoke test 作为硬性质量门
2. 读取 `workflow_specs/dashboard_expert_library/INDEX.md`，按用户目标、表名、字段、样例值匹配 Dashboard 主专家和支撑专家
3. 完整读取被选中的专家 `.md` 文件，明确目标用户、业务决策、刷新周期和 KPI 树，而不是先选图表
4. 使用 DuckDB/SQL/Python 计算每个模块的数据
5. Agent 直接撰写 standalone HTML：布局、CSS、ECharts option、洞察卡片和交互逻辑
6. 运行 `python scripts/validate_chart.py <output.html>` 校验单文件完整性

**Dashboard Planning Patterns:**

| Business Need | Recommended Module | Data Needed |
|---------------|--------------------|-------------|
| 指标总览 | KPI cards | 核心指标、上期值、变化率 |
| 趋势判断 | Line / area chart | 日期列、指标列 |
| 结构拆解 | Bar / treemap / pie | 维度列、指标列 |
| 地域分布 | Map / bar fallback | 省市/地区列、指标列 |
| 城市销售/销量地图 | Geo + effectScatter / map fallback | 城市列、交易额/销售额/GMV/金额/销量/数量列 |
| 漏斗流失 | Funnel | 阶段列、人数/次数 |
| 留存质量 | Cohort table / heatmap | 用户、日期、回访/留存字段 |
| 归因分析 | Driver table + bars | 日期、指标、可拆解维度 |
| 异常监控 | Alert cards + trend markers | 日期、指标、阈值或异常检测结果 |

**Layout Rules:**

- First row: KPI summary and current status
- Business dashboards need at least 6 analytical modules when data supports them; 2-3 chart dashboards are incomplete unless visible data-gap notes explain why.
- Dashboard titles must be evidence-based. Do not invent product, brand, or industry labels that are not in the prompt or data.
- Second row: trend and comparison
- Third row: structure/segment breakdown
- Diagnostic area: anomaly, funnel, retention, attribution, drill-down tables
- Filters: time, channel, region, product, user segment where available

**Dashboard Features:**
- ✅ **Professional Card-based Layout**: Modern UI with shadow and hover effects
- ✅ **Dark/Light Theme Toggle**: Press the theme button to switch themes
- ✅ **Responsive Design**: Auto-adjusts for mobile, tablet, and desktop
- ✅ **Interactive Charts**: Each chart supports zoom, pan, tooltip
- ✅ **Auto-refresh**: Configure auto-refresh interval (default: 30 seconds)
- ✅ **Export PDF**: Export entire dashboard as PDF file
- ✅ **Chart Search**: Filter charts by title
- ✅ **Download Charts**: Download individual charts as PNG images

### 🔒 Dashboard Single File 铁律（硬性要求）

> ⛔ **Dashboard HTML MUST be self-contained — same Single File rules as individual charts.**

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    Dashboard HTML Construction Rules                     │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ❌ 禁止: <link rel="stylesheet" href="http://127.0.0.1:8101/...">     │
│  ❌ 禁止: <script src="http://127.0.0.1:8101/..."></script>            │
│  ❌ 禁止: 硬编码端口号（8101 或任何端口）                                 │
│  ❌ 禁止: 任何外部 src/href 引用                                         │
│  ❌ 禁止: 依赖本地文件系统中的 JS/CSS 文件                                │
│                                                                         │
│  ✅ 必须: 将 echarts.min.js 完整内联到 <script> 标签中                   │
│  ✅ 必须: 将 dashboard.css 完整内联到 <style> 标签中                     │
│  ✅ 必须: 将 dashboard.js 完整内联到 <script> 标签中                     │
│  ✅ 必须: 地图数据 JS 文件完整内联到 <script> 标签中                      │
│  ✅ 必须: 输出单个 .html 文件，双击即可在浏览器中打开                      │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

**PDF Export 实现要求：**
- `html2canvas` 和 `jsPDF` 库必须**内联**到 HTML 中（从 `assets/` 目录读取并嵌入）
- 在 `<script>` 标签中内联 html2canvas 库（约 50KB minified）
- 在 `<script>` 标签中内联 jsPDF 库（约 200KB minified）
- `exportDashboard()` 函数检查 `typeof html2canvas !== 'undefined'` 时必须找到内联的库
- 如果内联库不可用，回退到浏览器的 `window.print()` 作为最低兜底
- `exportDashboard()` 必须捕获 html2canvas/jsPDF 异常，失败时用 toast 提示并回退 `window.print()`
- Dashboard CSS 禁止使用 `color-mix()`、`oklch()`、`oklab()`、`lab()`、`lch()` 等 html2canvas 可能无法解析的颜色函数；使用 hex/rgb/rgba token

**Chart Download 实现要求：**
- `downloadChart()` 使用 ECharts 内置的 `chart.getDataURL()` API（无需外部库）
- 所有 chart 实例存入 `charts` 数组，通过 chart ID 查找
- DashboardController 的 `charts` 参数由 HTML 中的 IIFE 自动填充

**实现方式（Agent 工作流，不使用固定 Python 生成器）：**
1. 先读取 `workflow_specs/dashboard_workflow.md`
1.1. 再读取 `workflow_specs/dashboard_runtime_quality.md`，执行运行时质量门
2. 读取 `workflow_specs/dashboard_expert_library/INDEX.md`，选择 Dashboard 主专家和支撑专家，并完整读取对应专家 `.md`
3. 按专家文件建立用户角色、业务决策、KPI 树、布局层级、诊断模块和必要的数据检查
4. 使用 DuckDB/SQL/Python 仅做数据查询、指标计算、异常/归因/洞察卡片证据准备
5. Agent 自行设计 HTML 结构、CSS、ECharts option 和业务解释卡片
6. 完整读取 `workflow_specs/html_templates/dashboard_light.html`，再读取 `workflow_specs/visual_templates/light.md` 或 `dark.md`，并把模板落实到 CSS tokens、布局、工具栏、图表面板、KPI 卡片、诊断区域和响应式规则
7. 读取 `assets/echarts/echarts.min.js` → 内联为 `<script>/* echarts 代码 */</script>`
8. 如需交互控件，可读取 `assets/dashboard/dashboard.css` 和 `assets/dashboard/dashboard.js` 作为参考或基础资产，但不得依赖一个固定 Python renderer
9. 读取 `assets/dashboard/html2canvas.min.js`、`assets/dashboard/jspdf.umd.min.js` → 内联以支持 PDF 导出
10. 读取所需地图 JS 文件（`assets/echarts/china.js` 等）→ 内联到 `<script>` 标签
10.1. 地图 JS 内联后由该文件完成 `echarts.registerMap(...)`；不得额外引用未定义的 `chinaGeoJSON`，也不得从 `geo.datav.aliyun.com` 或 CDN fetch 地图数据
11. 主题切换必须切换整页 `data-theme` 和 CSS token，不允许只重绘图表
12. 元数据、字段名或样例值有城市信息 + 交易额/销售额/GMV/金额/销量/数量字段时，必须读取 `workflow_specs/dashboard_modules/city_sales_map.md` 并补城市地图 + 销售/销量模块；无法可靠绘制地图时，显示数据缺口并用排行柱图兜底
13. 标题、模块深度和城市地图触发规则都必须自检；标题无依据、图表过少、城市地图缺失都属于生成失败
14. ⛔ **[MANDATORY]** 运行 `python scripts/validate_chart.py <output.html>` — 必须通过所有检查才能返回给用户
15. 浏览器自动化不可作为必需前提；必须依赖 `python scripts/validate_chart.py <output.html>` 完成无浏览器静态质量门，拦截外链、自引用 file URL、iframe/object/embed、业务脚本 location 跳转、JS 语法错误、PDF 不兼容 CSS、地图注册和导出/下载缺失
16. 如果环境恰好支持浏览器自动化，可额外用 `file://` 打开 HTML 做 smoke test；这只是增强验证，不是 skill 成功的必要条件

**Dashboard 规范：**
- 默认 HTML 骨架：`workflow_specs/html_templates/dashboard_light.html`
- 运行时质量门：`workflow_specs/dashboard_runtime_quality.md`
- 默认视觉方向：`workflow_specs/visual_templates/light.md`
- 深色视觉方向：`workflow_specs/visual_templates/dark.md`
- Dashboard 专家库索引：`workflow_specs/dashboard_expert_library/INDEX.md`
- 每一种专家对应一个独立 `.md` 文件；新增专家时新增文件并登记到 INDEX
- 自定义 Dashboard 专家模板：`workflow_specs/dashboard_expert_library/DASHBOARD_EXPERT_TEMPLATE.md`
- Dashboard 的布局、卡片、图表、洞察说明由 Agent 结合业务目标决定
- 生成结果必须符合所选视觉模板；如果像默认 HTML 或临时 demo，必须重做
- 自定义样式不得使用外部 `@import`、远程图片、外部字体、外部 CSS/JS
- 用户要求“更正式/更商务/公司风格”时，优先调整工作流规范和最终 HTML，不要新增固定 Python 生成逻辑

**Example Use Cases:**

**E-commerce Dashboard:**
```
/dashboard 创建电商数据仪表盘，包含：
- 各渠道销售柱状图
- 产品类别饼图
- 日销售趋势折线图
- 全国订单分布地图
```

**Financial Dashboard:**
```
/dashboard 创建财务分析仪表盘，包含：
- 月度收入折线图
- 费用类别饼图
- 部门预算柱状图
- 季度对比雷达图
```

**Method 4: Advanced Configuration (Legacy)**

For complex dashboards requiring full control, use JSON config:

```json
{
    "title": "销售数据概览",
    "columns": 3,
    "row_height": 400,
    "gap": 24,
    "db_path": "workspace.duckdb",
    "charts": [
        {
            "id": "chart1",
            "position": {"row": 0, "col": 0, "col_span": 2, "row_span": 1},
            "title": "月度销售趋势",
            "query": "SELECT month, SUM(amount) as sales FROM sales GROUP BY month",
            "echarts_option": {
                "xAxis": {"type": "category"},
                "yAxis": {"type": "value"},
                "series": [{"type": "line", "smooth": true}]
            },
            "custom_js": "option.series[0].data = rawData.map(r => r.sales);"
        }
    ]
}
```

Generate:
```bash
```
**Trigger**: User needs to automatically refresh data from HTTP APIs or databases on a schedule.

**Action:**

**1. Create Polling Configuration (polling_config.txt):**
```ini
[jobs.sales_api]
source_type=http
source_name=sales_api
interval_seconds=300
table_name=live_sales
http_config.url=https://api.example.com/sales
http_config.format=json
http_config.auth.type=bearer
http_config.auth.token=${API_TOKEN}

[jobs.production_db]
source_type=database
source_name=production_db
interval_seconds=600
table_name=live_orders
db_profile=mysql_prod
query=SELECT * FROM orders WHERE created_at > NOW() - INTERVAL 1 HOUR
```

**2. Manage Polling Jobs:**
```bash
# List all polling jobs
python scripts/polling_cli.py list

# Show detailed status
python scripts/polling_cli.py status
python scripts/polling_cli.py status <job_id>

# Manual refresh (trigger immediately)
python scripts/polling_cli.py refresh
python scripts/polling_cli.py refresh <job_id>

# Add new polling job
python scripts/polling_cli.py add --type http --name "my_api" --interval 300 --table api_data --http-config '{"url": "https://api.example.com/data", "format": "json"}'

# Remove polling job
python scripts/polling_cli.py remove <job_id>
```

**3. Use Polled Data in Charts:**
```json
{
    "db_path": "workspace.duckdb",
    "query": "SELECT * FROM live_sales ORDER BY timestamp DESC LIMIT 100",
    "title": "Live Sales Data",
    "echarts_option": {
        "xAxis": {"type": "category"},
        "yAxis": {"type": "value"},
        "series": [{"type": "line", "smooth": true}]
    }
}
```

**Key Features:**
- APScheduler-based background polling
- HTTP sources with all auth types (Basic, Bearer, API Key, OAuth2)
- Database polling for MySQL, PostgreSQL, MongoDB
- Automatic DuckDB table updates
- Last refresh timestamp tracked in `_data_skill_meta`
- Manual refresh on-demand
- Error counting and status tracking

**Notes:**
- Minimum interval: 10 seconds
- Maximum interval: 86400 seconds (24 hours)
- Polling runs in background thread
- Tables are replaced on each poll (not appended)

### Scenario 16: Automated Data Analysis (NEW in v1.6)
**Trigger**: User wants to understand their data — discover patterns, anomalies, trends without manually writing SQL or picking charts.

**Action**:

1. **Run Analysis**: Use the Insight Engine to automatically analyze a table:
   ```bash
   # Full analysis
   python scripts/insight_engine.py analyze <table_name> --db workspace.duckdb

   # Quick scan
   python scripts/insight_engine.py analyze <table_name> --quick --db workspace.duckdb

   # With specific dimensions
   python scripts/insight_engine.py analyze <table_name> \
       --dimensions region,category --metric amount --date-column order_date
   ```

2. **Profile First**: If you need to understand the data structure:
   ```bash
   python scripts/insight_engine.py profile <table_name> --db workspace.duckdb
   ```

3. **Present Insights**: The engine returns structured insights with:
   - 📈 **Trend**: Direction & strength of change over time
   - ⚠️ **Anomaly**: Statistical outliers (Z-score method)
   - 📊 **Ranking**: Top-N / Bottom-N by dimension
   - 🥧 **Composition**: Distribution & concentration
   - 🔗 **Correlation**: Relationships between metrics
   - 📅 **Seasonality**: Periodic patterns
   - 📉 **Change**: Period-over-period comparison

4. **Insight Output Format**: Each insight includes:
   - Severity level (critical/high/medium/low/info)
   - Natural language description in Chinese
   - Supporting evidence (numbers, periods, percentages)
   - Recommended chart type
   - Related columns for follow-up analysis

**From Python API**:
```python
from scripts.insight_engine import InsightEngine

engine = InsightEngine("workspace.duckdb")
insights = engine.analyze("sales", date_column="order_date")
for ins in insights:
    print(f"{ins.severity.value}: {ins.title} — {ins.description}")
```

**Key Features**:
- Completely automated — no need to write SQL or specify chart types
- Data privacy preserved — all computation is local in DuckDB
- Chinese natural language output
- Insights ranked by importance (critical → info)
- Each insight suggests the best chart type for visualization
- Supports time-series, categorical, and cross-metric analysis

### Scenario 17: Analysis Report Generation (NEW in v1.6)
**Trigger**: User wants a professional analysis report, not just individual charts or insights.

**Action**:

1. **Generate Report via Agent Workflow**:
   - Read `workflow_specs/report_workflow.md`
   - Read `workflow_specs/expert_library/INDEX.md`
   - Infer the likely industry/domain from the request and data, then choose one primary expert and optional supporting experts
   - Read every selected expert Markdown file completely before planning the analysis
   - Use SQL/Python only to collect evidence: profile, KPI totals, baseline comparison, anomaly scan, cross-analysis, attribution drill-down, forecast when useful
   - Agent writes the final Markdown/HTML/JSON report directly
   - Do not call a fixed Python report renderer for the final artifact

2. **Report Structures**:
   - `general` — summary, conclusions, expert framework, overview, metrics, dimensions, trends, diagnostics, anomalies, correlation, recommendations
   - `sales` — sales conclusions, structure, product, channel, region, trend, attribution, recommendations
   - `quick` — key findings, conclusions, profile, insights, actions

3. **Output Formats**:
   - `markdown` — Clean markdown, ideal for embedding in AI responses
   - `html` — Agent-authored standalone HTML using `workflow_specs/html_templates/report_light.html`
   - `json` — Structured JSON for programmatic consumption, when explicitly requested

4. **Visual Specs**:
   - HTML shell: `workflow_specs/html_templates/report_light.html`
   - Default visual direction: `workflow_specs/visual_templates/light.md`
   - Dark visual direction: `workflow_specs/visual_templates/dark.md`
   - The HTML shell and selected visual spec must be read completely before HTML/CSS is written
   - The generated HTML/CSS must visibly implement the shell: background, paper canvas, typography, spacing, borders, chart panels, semantic colors, print styles
   - Keep HTML self-contained: no external CSS, JS, fonts, images, or `@import`
   - HTML report should visually read like an enterprise PDF: paper-like page, formal header, numbered sections, printable layout

5. **Chart Context**:
   - Search `references/examples/*.md` for matching chart recipes before choosing chart types
   - Read every selected recipe via `get <name> --line` + Read examples.md offset
   - Generate each report chart from its recipe, data query, and appendix data ID
   - For long reports, write each finding branch and chart independently, then assemble into one report

6. **Pyramid Report Logic**:
   - Start with a one-page conclusion summary, not a data overview
   - Each conclusion must have supporting findings with numbers and comparison periods
   - Each major finding must include a primary chart as evidence
   - Each finding branch must also follow pyramid logic: local conclusion, observations, chart evidence, attribution explanation, local action
   - Every top conclusion and finding conclusion must cite appendix data table IDs, e.g. `[Data A1]`
   - Raw tables, field profiles, SQL, and samples belong in appendix
   - Forbidden: listing metrics/table outputs first, then adding a weak conclusion at the end

6. **Expert Analysis Layer**:
   - Agent detects industry/domain from user brief, table name, column names, sample values, and business context
   - Agent dynamically selects expert files from `workflow_specs/expert_library/INDEX.md`
   - Agent must execute selected experts' `Cross Analysis Matrix`, `Anomaly Patterns`, and `Deep Attribution Paths`
   - Agent applies selected expert files, e.g. traffic/growth checks scale, efficiency, retention, funnel, channel attribution, cohort quality, and segment reversal
   - Agent uses tools to scan anomalies, compare recent periods, cross dimensions, and attribute metric change to drivers
   - Agent writes conclusion-first narrative: what happened, why it likely happened, what to do next
   - Agent states data caveats when required fields are missing, instead of pretending a conclusion is fully supported

7. **Report Content**: Each report includes:
   - Cover: title, scope, period, assumptions, selected experts
   - One-page conclusions: 3-5 actionable conclusions with appendix data references
   - Key finding branches: ordered by business importance; each branch includes local conclusion, observations, chart evidence, attribution, action, and data references
   - Chart evidence: trend/contribution/funnel/retention/relationship/geographic charts where relevant; each chart cites its appendix data table
   - Diagnostic analysis: anomaly + comparison + cross-analysis + deep attribution
   - Actions: priority, expected effect, owner/data needed when possible
   - Appendix: numbered data tables, SQL, field profiles, data limitations; table IDs must support citations from the main body

**Evidence Tools (not final renderers)**:
```python
from scripts.insight_engine import InsightEngine
from scripts.attribution_engine import AttributionEngine

insights = InsightEngine("workspace.duckdb").analyze("sales")
drivers = AttributionEngine("workspace.duckdb").quick_explain(
    table="sales",
    metric="amount",
    date_column="order_date",
    period_before="2024-05",
    period_after="2024-06",
)

# Agent uses these results as evidence, then writes the final report itself
# according to workflow_specs/report_workflow.md.
```

**Tips for Best Results**:
- Ensure table has proper column types (dates as DATE/TIMESTAMP, numbers as INT/DOUBLE)
- For time-series insights, specify a date column
- Use the `sales` template when table contains revenue, product, channel data
- Reports work offline — all analysis is local, no data leaves the machine
- Combine with `/chart` or `/dashboard` to add visualizations to the report

**Interaction Flow**:
```
User: /analyze sales
Agent: [Runs automated analysis, returns 26 insights with severity rankings]
       🔴 Critical: 单价环比增长113.9%
       🟠 High: 数量季节性波动59%
       🟡 Medium: 前2个渠道合计占69.1%
       ...

User: /report sales --template sales --format html
Agent: [Generates professional HTML report with all insights, charts recommendations]
       ✅ Report: outputs/reports/sales_sales_20260613_140000.html
```

**Integration with existing commands**:
- Use `/analyze` to discover what's interesting → Use `/chart` to visualize key findings
- Use `/report` for comprehensive analysis → Use `/dashboard` for interactive monitoring
- Use `/insight` to drill into specific dimensions found by `/analyze`

### Scenario 18: Contextual Follow-up (NEW in v1.7)
**Trigger**: User asks a follow-up question referencing previous analysis — "上个月呢?", "和去年同期比呢?", "深挖一下广东", "为什么下降了".

**Action**:

1. **Detect follow-up intent**: The Context Manager automatically determines if the user is starting a new topic or continuing:
   ```bash
   python scripts/context_manager.py resolve "上个月呢？"
   # Output: intent=FOLLOW_UP, follow_up=REFINE, time=2026-05-01~2026-05-31
   ```

2. **Start a session** (new analysis):
   ```bash
   python scripts/context_manager.py start orders --db workspace.duckdb
   ```

3. **View session context** for prompt injection:
   ```bash
   python scripts/context_manager.py context
   ```

**Supported Follow-up Types**:
| Type | Example | System Action |
|------|---------|--------------|
| REFINE | "上个月呢？" | Resolve time reference, re-run with adjusted time range |
| COMPARE | "和去年同期比" | Detect YoY/MoM, generate comparison query |
| DRILL_DOWN | "深挖一下白酒" | Apply dimension filter, zoom in |
| EXPLAIN | "为什么下降了" | Trigger attribution/root cause analysis |
| PIVOT | "按渠道分析" | Switch dimension, re-aggregate |

**From Python API**:
```python
from scripts.context_manager import ContextManager

ctx = ContextManager()
session = ctx.start_session("sales", dimensions=["region", "category"])

# Record a turn
ctx.record_turn(session, "查看各地区销售额",
                sql="SELECT region, SUM(amount) FROM sales GROUP BY region")

# Resolve follow-up
result = ctx.resolve("上个月呢？", session)
# result["time_range"] = {"start_date": "2026-05-01", "end_date": "2026-05-31", ...}
# result["is_follow_up"] = True
# result["context_prompt"] = "..."  # For LLM injection
```

**Key Features**:
- Session persistence across restarts (SQLite-backed)
- Automatic time context from table profiling
- 10+ time reference patterns (上个月/去年/Q1/最近N天...)
- Intent detection: refine, compare, pivot, drill-down, explain
- Generates prompt context for LLM agents
- Session history with query/SQL/chart tracking

### Scenario 19: Time-Series Forecasting (NEW in v2.0)
**Trigger**: User wants to predict future trends — "预测下季度销售", "接下来6个月的趋势", "预估明年的收入".

**Action**:

1. **Run Forecast**:
   ```bash
   # Basic ensemble forecast (recommended)
   python scripts/forecast_engine.py <table> <date_column> <metric> --periods 6

   # With specific method
   python scripts/forecast_engine.py sales order_date amount --method linear_trend -p 12

   # JSON output for programmatic use
   python scripts/forecast_engine.py sales order_date amount --format json -p 6
   ```

2. **Forecast Methods**:
   | Method | Best For | Confidence Indicator |
   |--------|----------|---------------------|
   | `ensemble` | Most cases (default) | Weighted average of all methods |
   | `moving_average` | Stable, non-trending data | Low CV (coefficient of variation) |
   | `exponential` | Data with trend/seasonality | Trend consistency |
   | `linear_trend` | Strong linear patterns | R² score |

3. **Output Includes**:
   - Historical values (last 6 periods shown)
   - Forecast values with upper/lower bounds (80% CI)
   - Trend direction (上升/下降/平稳) and strength (% per period)
   - Overall confidence score (0-1)

4. **Auto-Visualization**: After generating a forecast, ALWAYS suggest creating a line chart:
   ```
   /chart line 历史趋势与预测 --table <table>
   ```
   Or generate a forecast-specific chart that overlays historical + predicted values with confidence bands.

**From Python API**:
```python
from scripts.forecast_engine import ForecastEngine, ForecastMethod

engine = ForecastEngine("workspace.duckdb")

# Quick forecast
result = engine.quick_forecast("sales", "order_date", "amount", periods=3)
print(f"Trend: {result.trend_direction} ({result.trend_strength_pct:+.1f}%/period)")

# Detailed forecast with specific method
result = engine.forecast(
    "sales", "order_date", "amount",
    periods=12,
    method=ForecastMethod.EXPONENTIAL,
    granularity="month",
)

# Access results
for fp in result.forecast_points:
    print(f"{fp.period}: {fp.value:.1f} [{fp.lower_bound:.1f} - {fp.upper_bound:.1f}]")

# Export as dict
data = result.to_dict()  # Includes historical + forecast arrays
```

**Tips for Best Results**:
- Ensure the date column is properly typed (DATE/TIMESTAMP) for accurate period generation
- Use `--granularity quarter` for quarterly forecasting, `--granularity year` for annual
- The `ensemble` method is recommended for most cases — it blends all 3 methods
- Data with fewer than 4 periods will raise an error — ensure sufficient history
- Combine with `/chart line` for visual trend display
- Use `/why` to understand what drives the trend direction

**Interaction Flow**:
```
User: 预测接下来6个月的销售趋势
Agent: [Runs forecast_engine.py on sales table]
       📈 预测结果: amount
       方法: ensemble | 置信度: 85%
       趋势: up (+3.2%/期)
       
       历史数据 (12 期):
       2024-01           12,400
       ...
       
       预测 (6 期):
       期数         预测值        下限        上限
       2025-01      18,500     15,200     21,800
       ...
       
       💡 建议使用 /chart line 生成趋势图查看预测区间

User: /chart line 过去12个月销售额趋势及未来6个月预测
Agent: [Generates line chart with historical + forecast + confidence bands]
       ✅ Chart: outputs/charts/sales_trend_forecast_*.html
```

### Scenario 20: Attribution Analysis (NEW in v2.0)
**Trigger**: User wants to understand why a metric changed — "为什么销售额下降了", "广东的增长贡献了多少", "分析一下上个月的变化原因".

Note: When user asks "为什么" as a follow-up to an existing analysis session, the Context Manager (Scenario 18) automatically detects this as EXPLAIN intent and may resolve time references. Use attribution for both fresh analysis and as the EXPLAIN action in follow-up flows.

**Action**:

1. **Run Attribution Analysis**:
   ```bash
   # With explicit dimensions
   python scripts/attribution_engine.py <table> <metric> <date_column> <before> <after> \
       --dimensions 商品分类,渠道,支付方式

   # Auto-detect dimensions (uses first 3 category columns)
   python scripts/attribution_engine.py sales amount order_date 2024-01 2024-06

   # JSON output
   python scripts/attribution_engine.py sales amount order_date 2024-01 2024-06 \
       -d region,category --format json
   ```

2. **Period Format**: Use YYYY-MM for month-level analysis (e.g., `2024-01`, `2024-06`).

3. **Output Structure**:
   - **总量变化**: Total before → after, absolute change, percentage change
   - **主要驱动力**: Top contributors sorted by contribution %, with 📌 markers for ≥15% contribution
   - **抵消效应检测**: When some dimensions go up while others go down
   - **钻取建议**: Human-readable recommendations for further analysis

4. **Auto-Visualization**: After attribution, suggest:
   - `/chart bar 各维度变化贡献度` — waterfall/bar chart showing contribution by dimension
   - `/chart pie 各维度占比变化` — compare before vs after pie charts

**From Python API**:
```python
from scripts.attribution_engine import AttributionEngine

engine = AttributionEngine("workspace.duckdb")

# Detailed analysis
result = engine.explain_change(
    "sales", "amount", "order_date",
    "2024-01", "2024-06",
    dimensions=["region", "category", "channel"],
    top_n=8,
)

print(f"Change: {result.total_change_pct:+.1f}%")
print(f"Direction: {result.change_direction}")

for c in result.top_drivers:
    print(f"  {c.dimension}「{c.value}」: {c.change:+.1f} ({c.contribution_pct:+.1f}%)")

for rec in result.drill_recommendations:
    print(f"  💡 {rec}")

# Quick explain with auto-detected dimensions
result = engine.quick_explain("sales", "amount", "order_date", "2024-01", "2024-06")

# Export as dict
data = result.to_dict()
```

**Tips for Best Results**:
- Choose 2-4 meaningful dimensions for best insights (too many dilutes the analysis)
- Compare periods of similar length (e.g., Jan vs Jun, not Jan 2024 vs Jan 2025)
- Use month-level granularity for period format (YYYY-MM)
- Combine with `/analyze` to discover which dimensions are most important
- Combine with `/forecast` to understand if the change will continue
- Primary drivers are those with ≥15% absolute contribution

**Interaction Flow**:
```
User: /why orders 金额 订单日期 2024-01 2024-06 -d 商品分类,渠道
Agent: [Runs attribution_engine.py]
       🔍 归因分析: 金额
       2024-01 → 2024-06
       变化: 125000.0 → 158000.0 (+26.4%)
       
       📌 主要驱动力:
         商品分类「电子」: +22,500 (+19.8%)
         渠道「线上」: +15,800 (+13.9%)
       
       ⚖️ 存在抵消效应：3个维度增长、2个维度下降，建议分别分析。
       
       💡 建议:
         🔍 主要增长驱动力是商品分类维度的「电子」...
         📊 建议深挖该维度的明细数据。

User: 深挖一下电子产品
Agent: [Uses Context Manager to drill down: filter by 商品分类=电子]
       [Re-runs analysis with the filter applied]
```
