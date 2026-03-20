---
description: Decompose variances into drivers with narrative explanations and waterfall analysis
argument-hint: "<line item> <period> vs <comparison>"
---

# Variance / Flux Analysis

> If you see unfamiliar placeholders or need to check which tools are connected, see [CONNECTORS.md](../CONNECTORS.md).

**Important**: This command assists with variance analysis workflows but does not provide financial advice. All analyses should be reviewed by qualified financial professionals before use in reporting.

Decompose variances into underlying drivers, provide narrative explanations for significant variances, and generate waterfall analysis.

## Usage

```
/flux <area> <period-comparison>
```

### Arguments

- `area` — The area to analyze:
  - `revenue` — Revenue variance by stream, product, geography, customer segment
  - `opex` — Operating expense variance by category, department, cost center
  - `capex` — Capital expenditure variance vs budget by project and asset class
  - `headcount` — Headcount and compensation variance by department and role level
  - `cogs` or `cost-of-revenue` — Cost of revenue variance by component
  - `gross-margin` — Gross margin analysis with mix and rate effects
  - Any specific GL account or account group
- `period-comparison` — The periods to compare. Formats:
  - `2024-12 vs 2024-11` — Month over month
  - `2024-12 vs 2023-12` — Year over year
  - `2024-Q4 vs 2024-Q3` — Quarter over quarter
  - `2024-12 vs budget` — Actual vs budget
  - `2024-12 vs forecast` — Actual vs forecast
  - `2024-Q4 vs 2024-Q3 vs 2023-Q4` — Three-way comparison

## Workflow

### 1. Gather Data

If ~~erp or ~~data warehouse is connected:
- Pull actuals for both comparison periods at the detail level
- Pull budget/forecast data if comparing to plan
- Pull supporting operational metrics (headcount, volumes, rates)
- Pull prior variance analyses for context

If no data source is connected:
> Connect ~~erp or ~~data warehouse to pull financial data automatically. To analyze manually, provide:
> 1. Actual data for both comparison periods (at account or line-item detail)
> 2. Budget/forecast data (if comparing to plan)
> 3. Any operational metrics that drive the financial results (headcount, volumes, pricing, etc.)

### 2. Calculate Top-Level Variance

```
VARIANCE SUMMARY: [Area] — [Period 1] vs [Period 2]

                              Period 1   Period 2   Variance ($)   Variance (%)
                              --------   --------   ------------   ------------
Total [Area]                  $XX,XXX    $XX,XXX    $X,XXX         X.X%
```

### 3. Decompose Variance by Driver

Break down the total variance into constituent drivers. Use the appropriate decomposition method for the area:

**Revenue Decomposition:**
- **Volume effect:** Change in units/customers/transactions at prior period pricing
- **Price/rate effect:** Change in pricing/ASP applied to current period volume
- **Mix effect:** Shift between products/segments at different margin levels
- **New vs existing:** Revenue from new customers/products vs base business
- **Currency effect:** FX impact on international revenue (if applicable)

**Operating Expense Decomposition:**
- **Headcount-driven:** Salary and benefits changes from headcount additions/reductions
- **Compensation changes:** Merit increases, promotions, bonus accruals
- **Volume-driven:** Expenses that scale with business activity (hosting, commissions, travel)
- **New programs/investments:** Incremental spend on new initiatives
- **One-time items:** Non-recurring expenses (severance, legal settlements, write-offs)
- **Timing:** Expenses shifted between periods (prepaid amortization changes, contract timing)

**CapEx Decomposition:**
- **Project-level:** Variance by capital project vs approved budget
- **Timing:** Projects ahead of or behind schedule
- **Scope changes:** Approved scope expansions or reductions
- **Cost overruns:** Unit cost increases vs plan

**Headcount Decomposition:**
- **Hiring pace:** Actual hires vs plan by department and level
- **Attrition:** Unplanned departures and backfill timing
- **Compensation mix:** Salary, bonus, equity, benefits variance
- **Contractor/temp:** Supplemental workforce changes

### 4. Waterfall Analysis

Generate a text-based waterfall showing how each driver contributes to the total variance:

```
WATERFALL: [Area] — [Period 1] vs [Period 2]

[Period 2 Base]                           $XX,XXX
  |
  |--[+] [Driver 1 description]          +$X,XXX
  |--[+] [Driver 2 description]          +$X,XXX
  |--[-] [Driver 3 description]          -$X,XXX
  |--[+] [Driver 4 description]          +$X,XXX
  |--[-] [Driver 5 description]          -$X,XXX
  |
[Period 1 Actual]                         $XX,XXX

Variance Reconciliation:
  Driver 1:    +$X,XXX  (XX% of total variance)
  Driver 2:    +$X,XXX  (XX% of total variance)
  Driver 3:    -$X,XXX  (XX% of total variance)
  Driver 4:    +$X,XXX  (XX% of total variance)
  Driver 5:    -$X,XXX  (XX% of total variance)
  Unexplained: $X,XXX   (XX% of total variance)
               --------
  Total:       $X,XXX   (100%)
```

### 5. Narrative Explanations

For each significant driver, generate a narrative explanation:

> **[Driver name]** — [Favorable/Unfavorable] variance of $X,XXX (X.X%)
>
> [2-3 sentence explanation of what caused this variance, referencing specific operational factors, business events, or decisions. Include quantification where possible.]
>
> *Outlook:* [Whether this is expected to continue, reverse, or change in future periods]

### 6. Identify Unexplained Variances

If the decomposition does not fully explain the total variance, flag the residual:

> **Unexplained variance:** $X,XXX (X.X% of total)
>
> Possible causes to investigate:
> - [Suggested area 1]
> - [Suggested area 2]
> - [Suggested area 3]

Ask the user for additional context on unexplained variances:
- "Can you provide context on [specific unexplained item]?"
- "Were there any business events in [period] that would explain [variance area]?"
- "Is the [specific driver] variance expected or a surprise?"

### 7. Output

Provide:
1. Top-level variance summary
2. Detailed variance decomposition by driver
3. Waterfall analysis (text format, or suggest chart if spreadsheet tool is connected)
4. Narrative explanations for each significant driver
5. Unexplained variance flag with investigation suggestions
6. Trend context (is this variance new, growing, or consistent with recent periods?)
7. Suggested actions or follow-ups
