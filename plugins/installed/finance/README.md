# Finance & Accounting Plugin

A finance and accounting plugin primarily designed for [Cowork](https://claude.com/product/cowork), Anthropic's agentic desktop application — though it also works in Claude Code. Supports month-end close, journal entry preparation, account reconciliation, financial statement generation, variance analysis, and SOX audit support.

> **Important**: This plugin assists with finance and accounting workflows but does not provide financial, tax, or audit advice. All outputs should be reviewed by qualified financial professionals before use in financial reporting, regulatory filings, or audit documentation.

## Installation

```bash
claude plugins add knowledge-work-plugins/finance
```

## Commands

| Command | Description |
|---------|-------------|
| `/journal-entry` | Journal entry preparation — generate accruals, fixed asset entries, prepaids, payroll, and revenue entries with proper debits/credits and supporting detail |
| `/reconciliation` | Account reconciliation — compare GL balances to subledger, bank, or third-party balances and identify reconciling items |
| `/income-statement` | Income statement generation — produce P&L with period-over-period comparison and variance analysis |
| `/variance-analysis` | Variance/flux analysis — decompose variances into drivers with narrative explanations and waterfall analysis |
| `/sox-testing` | SOX compliance testing — generate sample selections, testing workpapers, and control assessments |

## Skills

| Skill | Description |
|-------|-------------|
| `journal-entry-prep` | JE preparation best practices, standard accrual types, supporting documentation requirements, and review workflows |
| `reconciliation` | Reconciliation methodology for GL-to-subledger, bank recs, and intercompany, with reconciling item categorization and aging |
| `financial-statements` | Income statement, balance sheet, and cash flow statement formats with GAAP presentation and flux analysis methodology |
| `variance-analysis` | Variance decomposition techniques (price/volume, rate/mix), materiality thresholds, narrative generation, and waterfall charts |
| `close-management` | Month-end close checklist, task sequencing, dependencies, status tracking, and common close activities by day |
| `audit-support` | SOX 404 control testing methodology, sample selection, documentation standards, and deficiency classification |

## Example Workflows

### Month-End Close

1. Run `/journal-entry ap-accrual 2024-12` to generate AP accrual entries
2. Run `/journal-entry prepaid 2024-12` to amortize prepaid expenses
3. Run `/journal-entry fixed-assets 2024-12` to book depreciation
4. Run `/reconciliation cash 2024-12` to reconcile bank accounts
5. Run `/reconciliation accounts-receivable 2024-12` to reconcile AR subledger
6. Run `/income-statement monthly 2024-12` to generate the P&L with flux analysis

### Variance Analysis

1. Run `/variance-analysis revenue 2024-Q4 vs 2024-Q3` to analyze revenue variances
2. Run `/variance-analysis opex 2024-12 vs budget` to investigate operating expense variances
3. Review the waterfall analysis and provide context on unexplained variances

### SOX Testing

1. Run `/sox-testing revenue-recognition 2024-Q4` to generate revenue control testing workpapers
2. Run `/sox-testing procure-to-pay 2024-Q4` to test procurement controls
3. Review sample selections and document test results

## MCP Integration

> If you see unfamiliar placeholders or need to check which tools are connected, see [CONNECTORS.md](CONNECTORS.md).

This plugin works best when connected to your financial data sources via MCP servers. Add the relevant servers to your `.mcp.json`:

### ERP / Accounting System

Connect your ERP (e.g., NetSuite, SAP) MCP server to pull trial balances, subledger data, and journal entries automatically.

### Data Warehouse

Connect your data warehouse (e.g., Snowflake, BigQuery) MCP server to query financial data, run variance analysis, and pull historical comparisons.

### Spreadsheets

Connect spreadsheet tools (e.g., Google Sheets, Excel) for workpaper generation, reconciliation templates, and financial model updates.

### Analytics / BI

Connect your BI platform (e.g., Tableau, Looker) to pull dashboards, KPIs, and trend data for variance explanations.

> **Note:** Connect your ERP and data warehouse MCP servers to pull financial data automatically. Without these, you can paste data or upload files for analysis.

## Configuration

Add your data source MCP servers to the `mcpServers` section of `.mcp.json` in this plugin directory. The `recommendedCategories` field lists the types of integrations that enhance this plugin's capabilities:

- `erp-accounting` — ERP or accounting system for GL, subledger, and JE data
- `data-warehouse` — Data warehouse for financial queries and historical data
- `spreadsheets` — Spreadsheet tools for workpaper generation
- `analytics-bi` — BI tools for dashboards and KPI data
- `documents` — Document storage for policies, memos, and support
- `email` — Email for sending reports and requesting approvals
- `chat` — Team communication for close status updates and questions
