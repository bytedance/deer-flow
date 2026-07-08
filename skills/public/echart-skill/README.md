# Echart Skill — Enterprise Agent BI

<p align="center">
  <strong>本地优先 · 安全合规 · 企业级数据分析 Agent</strong>
</p>

<p align="center">
  <a href="README_EN.md">🇬🇧 English</a>
  &nbsp;|&nbsp;
  <b>🇨🇳 中文</b>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/version-2.1.0-blue" alt="Version">
  <img src="https://img.shields.io/badge/python-3.10+-green" alt="Python">
  <img src="https://img.shields.io/badge/license-MIT-yellow" alt="License">
  <img src="https://img.shields.io/badge/charts-27_types-orange" alt="Charts">
  <img src="https://img.shields.io/badge/recipes-354-purple" alt="Recipes">
</p>

---

**Echart Skill** 不是单纯的图表生成器，而是一套面向企业数据分析全流程的 **本地 Agent BI 能力包**——将专业数据分析师的工作流（导入→清洗→口径定义→质量评估→分析→可视化→报告→审计）压缩为一个可复用的 AI Agent Skill。

> 核心主张：**让企业在不引入重型 BI 平台、不上传业务数据、不把敏感数据交给大模型的前提下，用 AI Agent 完成专业、可审计、可交付的数据分析。**

---

## 为什么选择 Echart Skill？

### 🔒 数据安全第一

| 能力 | 实现方式 |
|------|----------|
| **0 联网分析链路** | CSV/Excel/DuckDB 查询、清洗、统计、洞察、报告均在本地完成，自包含 HTML 离线可打开 |
| **0 明细过大模型** | 不将整表、明细行塞入模型上下文；模型仅接收 schema、聚合结果和样本级摘要 |
| **PII 自动检测与脱敏** | 12 类敏感字段自动识别（手机号、邮箱、身份证、银行卡、薪资、地址等），支持列级脱敏 |
| **审计追踪** | 指令日志、查询 hash、脱敏状态、分类级别全量记录，支持按日期生成审计报告 |
| **数据血缘** | 追踪每份报告/图表的数据来源表、字段、统计口径和 query hash，让结果可复核 |

### 🏢 企业级工作流集成

Echart Skill 深度融入企业数据管理体系，不只是查询工具：

- **自定义统计口径**：通过 `/scope` 定义全局/项目级业务指标（如 GMV、客单价、转化率），保证不同报告和 Dashboard 使用同一口径。项目级口径仅在项目目录及子目录生效，互不干扰。
- **自定义表结构数据描述**：通过 `/schema` 管理表结构定义（列名、类型、含义、主外键），Agent 生成 SQL 时自动引用精确的字段描述，避免猜测字段含义导致的查询错误。
- **三级配置体系**：全局 → 项目级 → 运行时配置，数据库连接、表结构定义、统计口径均可按级别管理。
- **外部数据库直连**：支持 MySQL / PostgreSQL / MongoDB 直连查询，无需预先导入 DuckDB；连接密码使用 `${ENV_VAR}` 环境变量占位符，杜绝硬编码。
- **数据轮询刷新**：支持 HTTP API / 外部数据库定时轮询，自动刷新本地分析表。
- **非破坏式操作**：所有数据修改创建新表或视图，支持任意步骤回退（Undo）。

### 📊 专业分析引擎

| 能力 | 说明 |
|------|------|
| **自动洞察发现** | 7 种模式：趋势、异常、排名、构成、相关性、周期性、变化检测 |
| **趋势预测** | 4 种方法（移动平均/指数平滑/线性回归/集成），零外部 ML 依赖 |
| **归因分析** | 指标变化贡献度分解、自动钻取下钻建议 |
| **数据质量评分** | 缺失率、重复率、常量列、疑似 ID 检测、质量分、等级和建议 |
| **10 大领域专家库** | 销售电商、流量增长、财务管理、营销活动、运营履约、客户会员、产品内容、风控数据质量、通用经营等 |
| **金字塔结构报告** | 结论先行 → 图表举证 → 归因解释 → 行动建议 → 附录数据 |

### 🎨 企业级数据可视化

- **27 类图表**：柱状/折线/饼图/散点/雷达/漏斗/仪表盘/热力图/树图/桑基图/关系图/K线/3D 等
- **354 个 ECharts 官方配方**：Agent 无需手写 option 代码，直接替换数据数组即可生成
- **多层地图**：省份（china.js）→ 城市（省份 JS）→ 区县街道（百度地图 API）
- **交互式 Dashboard**：KPI 卡片、趋势图、异常提醒、主题切换、响应式布局、PDF/PNG 导出
- **企业级视觉**：统一 HTML 骨架、语义色、打印友好、暗色/亮色双主题

---

## 快速开始

### 环境要求

- Python 3.10+
- Windows / macOS / Linux

### 安装

```bash
# 1. 解压 Skill 包
unzip echart-skill_*.zip -d ~/skills/
cd ~/skills/echart-skill

# 2. 安装依赖
pip install -r requirements.txt        # 完整安装（~100 MB）
# 或
pip install -r requirements-core.txt   # 核心依赖（~40 MB，覆盖 90% 场景）

# 3. 注册到 Agent 平台
ln -s ~/skills/echart-skill ~/.claude/skills/echart-skill   # Claude Code

# 4. 开始使用
# 在项目目录创建 CLAUDE.md，添加 @~/.claude/skills/echart-skill/SKILL.md
```

### 30 秒体验

```bash
/import sales_2024.xlsx                        # 导入数据
/query SELECT region, SUM(amount) FROM sales_2024 GROUP BY region  # 查询
/chart bar 各区域销售额对比                      # 生成图表
/dashboard 创建销售分析仪表盘                    # 一键仪表盘
/report sales --format html                     # 生成企业报告
/quality sales_2024                             # 数据质量评分
```

---

## 核心能力图谱

```
                        ┌──────────────────────────────┐
                        │      企业决策与交付层          │
                        │  Dashboard  │  Report  │ 导出  │
                        └────────────┬─────────────────┘
                                     │
              ┌──────────────────────┼──────────────────────┐
              │                      │                      │
    ┌─────────▼─────────┐  ┌────────▼────────┐  ┌─────────▼─────────┐
    │   分析与洞察层      │  │   预测与归因层   │  │   可视化引擎层      │
    │ Insight Engine    │  │ Forecast/Attrib │  │ 27类 · 354配方     │
    │ 7 种洞察模式       │  │ 4 种方法 · 钻取  │  │ 地图 · 3D · 关系   │
    └─────────┬─────────┘  └────────┬────────┘  └─────────┬─────────┘
              │                     │                      │
              └──────────────────────┼──────────────────────┘
                                     │
                        ┌────────────▼────────────┐
                        │       数据治理层          │
                        │  口径  │  质量  │  血缘   │
                        │  审计  │  隐私  │  脱敏   │
                        └────────────┬────────────┘
                                     │
                        ┌────────────▼────────────┐
                        │       数据基础层          │
                        │  Import  │  Clean  │ DB  │
                        │  DuckDB  │ 外部数据库      │
                        └─────────────────────────┘
```

---

## 数据质量：让分析建立在可信数据之上

Echart Skill 将数据质量作为分析流程的**前置环节**，而非事后补救。

```bash
/quality orders --format markdown
```

**质量报告包含**：
- **完整性**：每列缺失率、缺失模式分析
- **唯一性**：重复行检测、疑似主键推荐
- **有效性**：常量列检测（无信息列）、类型一致性
- **合规性**：疑似 ID 字段标记、PII 风险提示
- **综合评分**：A/B/C/D 四级，附带具体改进建议

> 生成企业报告或 Dashboard 前建议先跑质量评分。等级 C/D 或有 critical 问题时，报告结论自动标注「初步判断」并说明数据限制。

配合 `/clean` 的 Agent 引导式清洗流程（类型转换、多列唯一键排重、规则引擎校验、跨表验证），形成 **质量评估 → 定向清洗 → 再次验证** 的闭环。

---

## 自定义口径：企业级指标治理

在企业数据分析中，同一个指标在不同部门可能有不同定义。"口径不一致"是数据混乱的首要来源。Echart Skill 提供两级口径管理：

```bash
# 全局口径：所有项目生效
/scope set --level global --name "GMV" --desc "SUM(pay_amount) WHERE status='paid'"

# 项目口径：仅在当前项目目录及子目录生效
/scope set --level project --name "GMV" --desc "SUM(order_amount) WHERE is_valid=1"

# 查看当前生效的口径
/metrics effective
```

**核心原则**：
- 项目级口径同名覆盖全局口径
- 执行目录位于项目目录树内时，自动切换为项目口径
- Agent 生成 SQL/报告/Dashboard 时自动引用当前生效口径
- 所有使用口径的产物通过 `/lineage` 可追踪

---

## 自定义表结构：让 Agent 真正理解你的数据

数据表列名往往是缩写或业务术语（如 `pay_amt`、`ch_type`、`uid`）。通过 `/schema` 为表结构提供精确描述，Agent 生成 SQL 将显著提升准确性：

```bash
# 为表添加列级描述
/schema add --name orders --columns "
  id:INT:订单ID:pk,
  pay_amt:DECIMAL:实付金额(元),
  ch_type:VARCHAR:渠道类型(online/offline/partner),
  uid:INT:用户ID:fk->users.id
"

# 项目级定义（表结构仅在该项目可见）
/schema add --name orders --level project --columns "..."

# 查询当前生效的表结构
/schema list
```

| 无 Schema | 有 Schema |
|-----------|----------|
| Agent 根据 `pay_amt` 猜测含义 | Agent 精确知道是「实付金额(元)」 |
| 无法判断 `ch_type` 的合法值 | Agent 知道渠道分为 online/offline/partner |
| 不会自动关联用户表 | Agent 知道 `uid` 关联 `users.id` |
| 查询质量依赖 Agent 运气 | 查询质量可预期、可复现 |

---

## 安全与合规：从设计上保护数据

```
┌─────────────────────────────────────────────────────────────┐
│                     安全架构                                 │
│                                                             │
│   用户指令 ──→ Agent 规划 ──→ 本地执行 ──→ 本地输出          │
│                  │               │              │            │
│                  │          ┌────▼────┐         │            │
│                  │          │ DuckDB  │         │            │
│                  │          │ (本地)  │         │            │
│                  │          └────┬────┘         │            │
│                  │               │              │            │
│              Schema/       PrivacyGuard    Audit Pipeline    │
│              聚合结果       PII 检测·脱敏    指令·查询·Hash    │
│                  │               │              │            │
│                  └───────────────┼──────────────┘            │
│                                  │                           │
│                          大模型上下文                         │
│                     (仅含 schema + 聚合)                      │
└─────────────────────────────────────────────────────────────┘
```

**安全防护清单**：

| 防护层 | 机制 |
|--------|------|
| **数据隔离** | 原始数据仅存在于本地 DuckDB，大模型无法直接访问 |
| **列级脱敏** | 手机号 → `138****1234`，邮箱 → `u***@domain.com`，身份证 → `3201**********1234` |
| **审计日志** | JSON-lines 格式，记录时间戳、表名、列、行数、脱敏状态、分类级别、query hash |
| **4 级数据分类** | `public < internal < sensitive < restricted` |
| **只读保护** | 可配置阻断 DROP/DELETE/UPDATE/INSERT/ALTER/TRUNCATE |

外部数据库查询同样经过 PrivacyGuard 检测与审计管线，使用 `/audit-report` 统一查看。

---

## 30+ 命令速览

### 数据基础

| 命令 | 说明 |
|------|------|
| `/import` | 导入 CSV/Excel/URL 数据，自动处理合并单元格 |
| `/clean` | Agent 引导式数据清洗（类型转换、去重、规则校验、跨表验证） |
| `/export` | 导出查询结果或整表为 CSV/Excel |
| `/tables` | 查看表结构、行数、列信息 |
| `/query` | 执行 SQL（DuckDB 语法），支持 JOIN、GROUP BY、子查询 |

### 可视化

| 命令 | 说明 |
|------|------|
| `/chart` | 生成单图表（27 类，354 官方配方） |
| `/chart-list` | 查看支持的图表类型和简介 |
| `/dashboard` | 自然语言生成交互式企业 Dashboard |

### 分析引擎

| 命令 | 说明 |
|------|------|
| `/analyze` | 自动分析数据表，发现规律与异常 |
| `/insight` | 指定维度深度洞察 |
| `/report` | 一键生成金字塔结构企业报告 |
| `/forecast` | 时间序列趋势预测（4 种方法） |
| `/why` | 指标变化归因分析，贡献度分解 |

### 治理与安全

| 命令 | 说明 |
|------|------|
| `/scope` | 全局/项目级统计口径管理 |
| `/metrics` | 查看当前生效的指标定义 |
| `/schema` | 全局/项目级表结构定义管理 |
| `/quality` | 数据质量评分与问题报告 |
| `/privacy` | PII 脱敏开关控制 |
| `/audit-report` | 按日期生成审计报告 |
| `/lineage` | 记录和查询产物数据血缘 |
| `/dbconn` | 外部数据库连接管理（MySQL/PG/MongoDB） |

### 运维

| 命令 | 说明 |
|------|------|
| `/poll` | 数据轮询管理（定时刷新 API/DB 数据） |
| `/start` `/stop` `/status` | 本地预览服务管理 |
| `/context` | 会话记忆与追问解析 |

---

## 图表类型全景

<details>
<summary>点击展开 27 类图表完整列表</summary>

| 类别 | 图表 | 适用场景 |
|------|------|---------|
| **基础** | `bar` `line` `pie` `scatter` `radar` `area` | 对比、趋势、占比、关系、多维对比 |
| **统计** | `boxplot` `heatmap` `scattergl` `effectScatter` `lines` | 分布分析、矩阵数据、大数据量、轨迹 |
| **层级** | `treemap` `sunburst` `tree` | 层级占比、多层结构 |
| **关系** | `sankey` `graph` | 流程转化、网络关系 |
| **专业** | `funnel` `gauge` `candlestick` `parallel` | 漏斗转化、进度仪表、金融K线、多维分析 |
| **时间** | `calendar` `themeRiver` | 日历分布、多主题时间流 |
| **地理** | `map` `geo` | 中国/世界地图、地理散点 |
| **3D** | `bar3d` `line3d` `scatter3d` `surface` | 三维矩阵、空间数据、科学可视化 |

</details>

**地图三层级架构**：

| 层级 | 示例数据 | 渲染方式 | 依赖 |
|------|---------|---------|------|
| 省份 | 北京、上海、广东 | 本地 `china.js` | 无 |
| 城市 | 广州市、深圳市 | 本地省份 JS | 无 |
| 区县/街道 | 天河区 | 百度地图 API | 百度地图 AK |

---

## 项目结构

```
echart-skill/
├── references/
│   ├── examples/               # 354 个 .md 自包含图表配方
│   │   └── INDEX.md            # 配方映射决策表
│   └── knowledge/              # ECharts 知识库（概念/API/模式）
├── workflow_specs/
│   ├── dashboard_workflow.md   # Dashboard 工作流规范
│   ├── report_workflow.md      # Report 工作流规范
│   ├── data_cleaning_workflow.md
│   ├── dashboard_runtime_quality.md  # 运行时质量门（硬性约束）
│   ├── dashboard_expert_library/     # Dashboard 专家库（5 个场景）
│   ├── expert_library/               # Report 专家库（10 个领域）
│   ├── dashboard_modules/            # Dashboard 可复用模块
│   ├── html_templates/               # 企业级 HTML 骨架
│   └── visual_templates/             # 视觉方向（亮色/暗色）
├── assets/                    # JS/CSS 资源、地图文件
├── scripts/                   # 40+ Python 工具脚本
├── tests/                     # 测试文件
└── outputs/                   # 输出目录
```

---

## FAQ

**Q: 数据安全如何保证？**
A: 原始数据仅存在于本地 DuckDB，大模型只接收 schema 和聚合结果。PII 自动检测脱敏，支持按列标记敏感级别。详见[安全架构](#安全与合规从设计上保护数据)。

**Q: 和传统 BI 工具（Tableau、Power BI）的区别？**
A: Echart Skill 是 Agent BI——通过自然语言与 AI 交互完成分析，无需手动拖拽配置。同时它无需部署服务端、可离线运行、数据不出本地。适合需要专业分析但不想引入重型 BI 平台的场景。

**Q: 如何定义我们公司的业务指标口径？**
A: 使用 `/scope set --level global --name "指标名" --desc "计算规则"` 定义全局口径；不同项目可用 `/scope set --level project` 覆盖。Agent 在生成报告和 Dashboard 时自动引用当前生效口径。

**Q: 如何让 Agent 准确理解我们数据库表的字段含义？**
A: 使用 `/schema add` 为表的每个列提供中文描述、数据类型、合法值范围和主外键关系。Agent 会在生成 SQL 时精确引用，显著提升查询准确率。

**Q: 支持连接公司已有的数据库吗？**
A: 支持。`/dbconn` 管理 PostgreSQL/MySQL/MongoDB 连接，密码通过 `${ENV_VAR}` 环境变量传入，支持直接查询或导入 DuckDB 进行跨表分析。

**Q: 生成的报告和图表能否直接交付给客户？**
A: 可以。Dashboard 和 Report 使用企业级 HTML 骨架，支持深色/亮色主题、PDF 导出、打印优化，图表为 ECharts 交互式可视化，可直接作为交付物。

**Q: 分析过程是否可审计？**
A: 完全可审计。`/audit-report --date YYYY-MM-DD` 按天输出指令、查询表、列、行数、脱敏状态、分类级别和 query hash。`/lineage` 追踪产物完整数据血缘。

---

## 许可证

MIT License — 详见 [LICENSE](LICENSE)

---

<p align="center">
  <sub>Built with ❤️ for data professionals who value privacy, quality, and efficiency.</sub>
</p>
