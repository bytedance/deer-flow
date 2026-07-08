# Echart Skill — Enterprise Agent BI

<p align="center">
  <strong>Local-First · Secure & Compliant · Enterprise-Grade Data Analysis Agent</strong>
</p>

<p align="center">
  <b>🇬🇧 English</b>
  &nbsp;|&nbsp;
  <a href="README.md">🇨🇳 中文</a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/version-2.1.0-blue" alt="Version">
  <img src="https://img.shields.io/badge/python-3.10+-green" alt="Python">
  <img src="https://img.shields.io/badge/license-MIT-yellow" alt="License">
  <img src="https://img.shields.io/badge/charts-27_types-orange" alt="Charts">
  <img src="https://img.shields.io/badge/recipes-354-purple" alt="Recipes">
</p>

---

**Echart Skill** is more than a chart generator — it's a comprehensive **local Agent BI capability pack** for enterprise data analysis. It compresses the entire professional analyst workflow (import → clean → metric definition → quality assessment → analysis → visualization → report → audit) into a reusable AI Agent Skill.

> Core Proposition: **Empower enterprises to perform professional, auditable, and deliverable data analysis with AI Agents — without deploying heavy BI platforms, uploading business data, or exposing sensitive data to LLMs.**

---

## Why Echart Skill?

### 🔒 Security First

| Capability | How |
|------|----------|
| **Zero-Network Analysis Pipeline** | CSV/Excel/DuckDB querying, cleaning, statistics, insights, and reporting all run locally. Self-contained HTML works offline. |
| **Zero Raw Data to LLM** | Full tables and detail rows never enter the model context; the model only receives schema, aggregated results, and sample-level summaries. |
| **Auto PII Detection & Masking** | 12 sensitive field types auto-detected (phone, email, ID card, bank card, salary, address, etc.) with column-level masking. |
| **Audit Trail** | Command logs, query hashes, masking status, and classification levels fully recorded. Generate audit reports by date. |
| **Data Lineage** | Track the source tables, columns, metric definitions, and query hashes behind every report and chart — making results reproducible and auditable. |

### 🏢 Enterprise Workflow Integration

Echart Skill integrates deeply into enterprise data governance, not just as a query tool:

- **Custom Metric Definitions (Statistical Calibers)**: Define global or project-level business metrics (GMV, ARPU, conversion rate) via `/scope`. Project-level definitions only apply within the project directory tree, preventing cross-project interference. All reports and dashboards automatically reference the active metric definitions.
- **Custom Table Schema Descriptions**: Manage table structure definitions (column names, types, business meanings, primary/foreign keys) via `/schema`. The Agent references precise field descriptions when generating SQL, eliminating guesswork and query errors.
- **Three-Tier Configuration System**: Global → Project → Runtime. Database connections, table schemas, and metric definitions are all tier-managed.
- **External Database Direct Query**: Connect MySQL / PostgreSQL / MongoDB directly — query without pre-importing into DuckDB. Passwords use `${ENV_VAR}` placeholders to eliminate hardcoded credentials.
- **Data Polling & Refresh**: Scheduled polling from HTTP APIs or external databases to auto-refresh local analysis tables.
- **Non-Destructive Operations**: All data modifications create new tables or views. Any step can be rolled back (Undo).

### 📊 Professional Analysis Engine

| Capability | Description |
|------|------|
| **Auto Insight Discovery** | 7 patterns: trends, anomalies, rankings, composition, correlation, seasonality, change detection |
| **Trend Forecasting** | 4 methods (MA / exponential smoothing / linear regression / ensemble), zero external ML dependencies |
| **Attribution Analysis** | Metric change contribution decomposition with automatic drill-down recommendations |
| **Data Quality Scoring** | Missing rate, duplicate rate, constant columns, suspected ID detection, quality score/grade, and actionable recommendations |
| **10 Domain Expert Libraries** | Sales & e-commerce, traffic & growth, finance, marketing, operations, customer & membership, product & content, risk & data quality, general management |
| **Pyramid-Structured Reports** | Conclusion-first → chart evidence → attribution analysis → action recommendations → appendix data |

### 🎨 Enterprise Data Visualization

- **27 Chart Types**: Bar, line, pie, scatter, radar, funnel, gauge, heatmap, treemap, sankey, graph, candlestick, 3D, and more
- **354 Official ECharts Recipes**: Agent replaces only the data array — no hand-written option code required
- **Multi-Level Maps**: Province (`china.js`) → City (province JS) → District/Street (Baidu Maps API)
- **Interactive Dashboards**: KPI cards, trend charts, anomaly alerts, theme switching, responsive layout, PDF/PNG export
- **Enterprise Visual Standards**: Unified HTML skeleton, semantic colors, print-friendly, light/dark dual themes

---

## Quick Start

### Requirements

- Python 3.10+
- Windows / macOS / Linux

### Installation

```bash
# 1. Unzip the Skill package
unzip echart-skill_*.zip -d ~/skills/
cd ~/skills/echart-skill

# 2. Install dependencies
pip install -r requirements.txt        # Full install (~100 MB)
# or
pip install -r requirements-core.txt   # Core only (~40 MB, covers 90% of use cases)

# 3. Register with your Agent platform
ln -s ~/skills/echart-skill ~/.claude/skills/echart-skill   # Claude Code

# 4. Get started — add to your project's CLAUDE.md:
# @~/.claude/skills/echart-skill/SKILL.md
```

### 30-Second Quick Tour

```bash
/import sales_2024.xlsx                              # Import data
/query SELECT region, SUM(amount) FROM sales_2024 GROUP BY region  # Query
/chart bar Sales by Region                            # Generate chart
/dashboard Create a sales analysis dashboard          # One-click dashboard
/report sales --format html                           # Generate enterprise report
/quality sales_2024                                   # Data quality scoring
```

---

## Capability Architecture

```
                        ┌──────────────────────────────┐
                        │   Decision & Delivery Layer   │
                        │  Dashboard  │  Report  │ Export│
                        └────────────┬─────────────────┘
                                     │
              ┌──────────────────────┼──────────────────────┐
              │                      │                      │
    ┌─────────▼─────────┐  ┌────────▼────────┐  ┌─────────▼─────────┐
    │  Analysis & Insight │  │  Forecast &      │  │  Visualization    │
    │  Insight Engine    │  │  Attribution     │  │  27 types · 354   │
    │  7 insight modes   │  │  4 methods·drill │  │  Maps·3D·Graphs   │
    └─────────┬─────────┘  └────────┬────────┘  └─────────┬─────────┘
              │                     │                      │
              └──────────────────────┼──────────────────────┘
                                     │
                        ┌────────────▼────────────┐
                        │     Data Governance      │
                        │  Metrics │ Quality │ Lineage │
                        │  Audit  │ Privacy │ Masking │
                        └────────────┬────────────┘
                                     │
                        ┌────────────▼────────────┐
                        │      Data Foundation     │
                        │  Import  │  Clean  │ DB  │
                        │  DuckDB  │ External DBs  │
                        └─────────────────────────┘
```

---

## Data Quality: Build Analysis on Trusted Data

Echart Skill treats data quality as a **prerequisite**, not an afterthought.

```bash
/quality orders --format markdown
```

**Quality Report Includes**:
- **Completeness**: Per-column missing rate, missing pattern analysis
- **Uniqueness**: Duplicate row detection, candidate primary key recommendations
- **Validity**: Constant column detection (zero-information columns), type consistency
- **Compliance**: Suspected PII field flags, risk alerts
- **Overall Score**: A/B/C/D four-tier grading with specific improvement recommendations

> Run quality scoring before generating enterprise reports or dashboards. At grade C/D or with critical issues, report conclusions are automatically marked "Preliminary" with data limitations noted.

Together with `/clean` (Agent-guided cleaning workflow: type conversion, multi-column dedup, rule validation, cross-table verification), this forms a **Quality Assessment → Targeted Cleaning → Re-Verification** closed loop.

---

## Custom Metric Definitions: Enterprise Metric Governance

In enterprise analytics, the same metric often means different things to different teams. "Inconsistent definitions" is the primary source of data chaos. Echart Skill provides two-tier metric governance:

```bash
# Global metrics: effective for all projects
/scope set --level global --name "GMV" --desc "SUM(pay_amount) WHERE status='paid'"

# Project metrics: effective only within the project directory tree
/scope set --level project --name "GMV" --desc "SUM(order_amount) WHERE is_valid=1"

# View currently active metrics
/metrics effective
```

**Core Principles**:
- Project-level metrics override global ones by name
- When the working directory is inside a project tree, project metrics auto-activate
- Agent automatically references active metrics when generating SQL, reports, and dashboards
- All artifacts referencing defined metrics are traceable via `/lineage`

---

## Custom Table Schema: Let the Agent Truly Understand Your Data

Column names are often abbreviations or domain jargon (e.g., `pay_amt`, `ch_type`, `uid`). Use `/schema` to provide precise column descriptions, dramatically improving Agent SQL accuracy:

```bash
# Add column-level descriptions for a table
/schema add --name orders --columns "
  id:INT:Order ID:pk,
  pay_amt:DECIMAL:Actual Payment Amount (CNY),
  ch_type:VARCHAR:Channel Type (online/offline/partner),
  uid:INT:User ID:fk->users.id
"

# Project-level definition (visible only within the project)
/schema add --name orders --level project --columns "..."

# List currently active schema definitions
/schema list
```

| Without Schema | With Schema |
|-----------|----------|
| Agent guesses meaning of `pay_amt` | Agent knows it's "Actual Payment Amount (CNY)" |
| Cannot determine valid `ch_type` values | Agent knows channels: online/offline/partner |
| No automatic table joins | Agent knows `uid` references `users.id` |
| Query quality depends on luck | Query quality is predictable and reproducible |

---

## Security & Compliance: Data Protection by Design

```
┌─────────────────────────────────────────────────────────────┐
│                   Security Architecture                      │
│                                                             │
│   User Command → Agent Plans → Local Execution → Local Output│
│                      │              │              │         │
│                      │         ┌────▼────┐         │         │
│                      │         │ DuckDB  │         │         │
│                      │         │ (Local) │         │         │
│                      │         └────┬────┘         │         │
│                      │              │              │         │
│                  Schema/      PrivacyGuard   Audit Pipeline  │
│                  Aggregated   PII Detect·Mask Cmd·Query·Hash │
│                      │              │              │         │
│                      └──────────────┼──────────────┘         │
│                                     │                        │
│                             LLM Context                      │
│                     (schema + aggregations only)              │
└─────────────────────────────────────────────────────────────┘
```

**Protection Checklist**:

| Layer | Mechanism |
|--------|------|
| **Data Isolation** | Raw data exists only in local DuckDB; LLMs have no direct access |
| **Column-Level Masking** | Phone → `138****1234`, Email → `u***@domain.com`, ID → `3201**********1234` |
| **Audit Log** | JSON-lines format: timestamps, table names, columns, row counts, masking status, classification, query hash |
| **4-Tier Classification** | `public < internal < sensitive < restricted` |
| **Read-Only Protection** | Configurable blocking of DROP/DELETE/UPDATE/INSERT/ALTER/TRUNCATE |

External database queries go through the same PrivacyGuard detection and audit pipeline. Use `/audit-report` for a unified view.

---

## 30+ Commands at a Glance

### Data Foundation

| Command | Description |
|------|------|
| `/import` | Import CSV/Excel/URL data with automatic merged-cell handling |
| `/clean` | Agent-guided data cleaning (type conversion, dedup, rule validation, cross-table verification) |
| `/export` | Export query results or whole tables as CSV/Excel |
| `/tables` | View table structures, row counts, column info |
| `/query` | Execute SQL (DuckDB syntax) with JOIN, GROUP BY, subquery support |

### Visualization

| Command | Description |
|------|------|
| `/chart` | Generate single charts (27 types, 354 official recipes) |
| `/chart-list` | View supported chart types and descriptions |
| `/dashboard` | Natural language → interactive enterprise dashboard |

### Analysis Engine

| Command | Description |
|------|------|
| `/analyze` | Auto-analyze tables to discover patterns and anomalies |
| `/insight` | Deep-dive insights on specified dimensions |
| `/report` | One-click pyramid-structured enterprise report |
| `/forecast` | Time-series trend forecasting (4 methods) |
| `/why` | Metric change attribution with contribution breakdown |

### Governance & Security

| Command | Description |
|------|------|
| `/scope` | Global/project-level metric definition management |
| `/metrics` | View currently active metric definitions |
| `/schema` | Global/project-level table schema definition management |
| `/quality` | Data quality scoring and issue reporting |
| `/privacy` | PII masking toggle |
| `/audit-report` | Generate audit report by date |
| `/lineage` | Record and query artifact data lineage |
| `/dbconn` | External database connection management (MySQL/PG/MongoDB) |

### Operations

| Command | Description |
|------|------|
| `/poll` | Data polling management (scheduled API/DB refresh) |
| `/start` `/stop` `/status` | Local preview server management |
| `/context` | Session memory and follow-up question resolution |

---

## Chart Type Panorama

<details>
<summary>Click to expand — 27 chart types</summary>

| Category | Charts | Use Cases |
|------|------|---------|
| **Basic** | `bar` `line` `pie` `scatter` `radar` `area` | Comparison, trends, proportions, relationships, multi-dimensional |
| **Statistical** | `boxplot` `heatmap` `scattergl` `effectScatter` `lines` | Distribution, matrix data, large datasets, trajectories |
| **Hierarchical** | `treemap` `sunburst` `tree` | Hierarchical proportions, multi-level structures |
| **Relational** | `sankey` `graph` | Flow/funnel analysis, network relationships |
| **Specialized** | `funnel` `gauge` `candlestick` `parallel` | Conversion funnels, progress gauges, candlestick, multi-dim analysis |
| **Temporal** | `calendar` `themeRiver` | Calendar distribution, multi-theme time flow |
| **Geographic** | `map` `geo` | China/world maps, geo scatter |
| **3D** | `bar3d` `line3d` `scatter3d` `surface` | 3D matrices, spatial data, scientific visualization |

</details>

**Three-Tier Map Architecture**:

| Tier | Example Data | Rendering | Dependencies |
|------|---------|---------|------|
| Province | Beijing, Shanghai, Guangdong | Local `china.js` | None |
| City | Guangzhou, Shenzhen | Local province JS | None |
| District/Street | Tianhe District | Baidu Maps API | Baidu Maps AK |

---

## Project Structure

```
echart-skill/
├── references/
│   ├── examples/               # 354 self-contained .md chart recipes
│   │   └── INDEX.md            # Recipe lookup decision table
│   └── knowledge/              # ECharts knowledge base (concepts/API/patterns)
├── workflow_specs/
│   ├── dashboard_workflow.md   # Dashboard workflow spec
│   ├── report_workflow.md      # Report workflow spec
│   ├── data_cleaning_workflow.md
│   ├── dashboard_runtime_quality.md  # Runtime quality gate (hard constraint)
│   ├── dashboard_expert_library/     # Dashboard expert library (5 scenarios)
│   ├── expert_library/               # Report expert library (10 domains)
│   ├── dashboard_modules/            # Reusable dashboard modules
│   ├── html_templates/               # Enterprise HTML skeletons
│   └── visual_templates/             # Visual themes (light/dark)
├── assets/                    # JS/CSS assets, map files
├── scripts/                   # 40+ Python utility scripts
├── tests/                     # Test suite
└── outputs/                   # Output directory
```

---

## FAQ

**Q: How is data security guaranteed?**
A: Raw data exists only in local DuckDB. The LLM receives only schema and aggregated results. PII is auto-detected and masked at the column level. See [Security Architecture](#security--compliance-data-protection-by-design).

**Q: How does this differ from traditional BI tools (Tableau, Power BI)?**
A: Echart Skill is Agent BI — you interact through natural language with AI, no manual drag-and-drop configuration required. It requires no server deployment, works offline, and keeps data local. Ideal for teams needing professional analysis without deploying a heavy BI platform.

**Q: How do I define my company's business metric definitions?**
A: Use `/scope set --level global --name "MetricName" --desc "Calculation Rule"` for global metrics. Override per-project with `/scope set --level project`. The Agent automatically references active metric definitions when generating reports and dashboards.

**Q: How do I make the Agent accurately understand our database field meanings?**
A: Use `/schema add` to provide Chinese/English descriptions, data types, valid value ranges, and primary/foreign key relationships for each column. The Agent will reference these precisely when generating SQL, dramatically improving query accuracy.

**Q: Can it connect to our existing databases?**
A: Yes. `/dbconn` manages PostgreSQL/MySQL/MongoDB connections with passwords via `${ENV_VAR}` environment variables. Query directly or import into DuckDB for cross-table analysis.

**Q: Are generated reports and charts delivery-ready for clients?**
A: Absolutely. Dashboards and Reports use enterprise-grade HTML skeletons with light/dark themes, PDF export, and print optimization. Charts are ECharts interactive visualizations — presentation-ready deliverables.

**Q: Is the analysis process auditable?**
A: Fully auditable. `/audit-report --date YYYY-MM-DD` outputs commands, queried tables, columns, row counts, masking status, classification levels, and query hashes by day. `/lineage` provides full artifact data lineage.

---

## License

MIT License — see [LICENSE](LICENSE)

---

<p align="center">
  <sub>Built with ❤️ for data professionals who value privacy, quality, and efficiency.</sub>
</p>
