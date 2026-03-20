---
name: variance-analysis
description: Decompose financial variances into drivers with narrative explanations and waterfall analysis. Use when analyzing budget vs. actual, period-over-period changes, revenue or expense variances, or preparing variance commentary for leadership.
---

# Variance Analysis

**Important**: This skill assists with variance analysis workflows but does not provide financial advice. All analyses should be reviewed by qualified financial professionals before use in reporting.

Techniques for decomposing variances, materiality thresholds, narrative generation, waterfall chart methodology, and budget vs actual vs forecast comparisons.

## Variance Decomposition Techniques

### Price / Volume Decomposition

The most fundamental variance decomposition. Used for revenue, cost of goods, and any metric that can be expressed as Price x Volume.

**Formula:**
```
Total Variance = Actual - Budget (or Prior)

Volume Effect  = (Actual Volume - Budget Volume) x Budget Price
Price Effect   = (Actual Price - Budget Price) x Actual Volume
Mix Effect     = Residual (interaction term), or allocated proportionally

Verification:  Volume Effect + Price Effect = Total Variance
               (when mix is embedded in the price/volume terms)
```

**Three-way decomposition (separating mix):**
```
Volume Effect = (Actual Volume - Budget Volume) x Budget Price x Budget Mix
Price Effect  = (Actual Price - Budget Price) x Budget Volume x Actual Mix
Mix Effect    = Budget Price x Budget Volume x (Actual Mix - Budget Mix)
```

**Example — Revenue variance:**
- Budget: 10,000 units at $50 = $500,000
- Actual: 11,000 units at $48 = $528,000
- Total variance: +$28,000 favorable
  - Volume effect: +1,000 units x $50 = +$50,000 (favorable — sold more units)
  - Price effect: -$2 x 11,000 units = -$22,000 (unfavorable — lower ASP)
  - Net: +$28,000

### Rate / Mix Decomposition

Used when analyzing blended rates across segments with different unit economics.

**Formula:**
```
Rate Effect = Sum of (Actual Volume_i x (Actual Rate_i - Budget Rate_i))
Mix Effect  = Sum of (Budget Rate_i x (Actual Volume_i - Expected Volume_i at Budget Mix))
```

**Example — Gross margin variance:**
- Product A: 60% margin, Product B: 40% margin
- Budget mix: 50% A, 50% B → Blended margin 50%
- Actual mix: 40% A, 60% B → Blended margin 48%
- Mix effect explains 2pp of margin compression

### Headcount / Compensation Decomposition

Used for analyzing payroll and people-cost variances.

```
Total Comp Variance = Actual Compensation - Budget Compensation

Decompose into:
1. Headcount variance    = (Actual HC - Budget HC) x Budget Avg Comp
2. Rate variance         = (Actual Avg Comp - Budget Avg Comp) x Budget HC
3. Mix variance          = Difference due to level/department mix shift
4. Timing variance       = Hiring earlier/later than planned (partial-period effect)
5. Attrition impact      = Savings from unplanned departures (partially offset by backfill costs)
```

### Spend Category Decomposition

Used for operating expense analysis when price/volume is not applicable.

```
Total OpEx Variance = Actual OpEx - Budget OpEx

Decompose by:
1. Headcount-driven costs    (salaries, benefits, payroll taxes, recruiting)
2. Volume-driven costs       (hosting, transaction fees, commissions, shipping)
3. Discretionary spend       (travel, events, professional services, marketing programs)
4. Contractual/fixed costs   (rent, insurance, software licenses, subscriptions)
5. One-time / non-recurring  (severance, legal settlements, write-offs, project costs)
6. Timing / phasing          (spend shifted between periods vs plan)
```

## Materiality Thresholds and Investigation Triggers

### Setting Thresholds

Materiality thresholds determine which variances require investigation and narrative explanation. Set thresholds based on:

1. **Financial statement materiality:** Typically 1-5% of a key benchmark (revenue, total assets, net income)
2. **Line item size:** Larger line items warrant lower percentage thresholds
3. **Volatility:** More volatile line items may need higher thresholds to avoid noise
4. **Management attention:** What level of variance would change a decision?

### Recommended Threshold Framework

| Comparison Type | Dollar Threshold | Percentage Threshold | Trigger |
|----------------|-----------------|---------------------|---------|
| Actual vs Budget | Organization-specific | 10% | Either exceeded |
| Actual vs Prior Period | Organization-specific | 15% | Either exceeded |
| Actual vs Forecast | Organization-specific | 5% | Either exceeded |
| Sequential (MoM) | Organization-specific | 20% | Either exceeded |

*Set dollar thresholds based on your organization's size. Common practice: 0.5%-1% of revenue for income statement items.*

### Investigation Priority

When multiple variances exceed thresholds, prioritize investigation by:

1. **Largest absolute dollar variance** — biggest P&L impact
2. **Largest percentage variance** — may indicate process issue or error
3. **Unexpected direction** — variance opposite to trend or expectation
4. **New variance** — item that was on track and is now off
5. **Cumulative/trending variance** — growing each period

## Narrative Generation for Variance Explanations

### Structure for Each Variance Narrative

```
[Line Item]: [Favorable/Unfavorable] variance of $[amount] ([percentage]%)
vs [comparison basis] for [period]

Driver: [Primary driver description]
[2-3 sentences explaining the business reason for the variance, with specific
quantification of contributing factors]

Outlook: [One-time / Expected to continue / Improving / Deteriorating]
Action: [None required / Monitor / Investigate further / Update forecast]
```

### Narrative Quality Checklist

Good variance narratives should be:

- [ ] **Specific:** Names the actual driver, not just "higher than expected"
- [ ] **Quantified:** Includes dollar and percentage impact of each driver
- [ ] **Causal:** Explains WHY it happened, not just WHAT happened
- [ ] **Forward-looking:** States whether the variance is expected to continue
- [ ] **Actionable:** Identifies any required follow-up or decision
- [ ] **Concise:** 2-4 sentences, not a paragraph of filler

### Common Narrative Anti-Patterns to Avoid

- "Revenue was higher than budget due to higher revenue" (circular — no actual explanation)
- "Expenses were elevated this period" (vague — which expenses? why?)
- "Timing" without specifying what was early/late and when it will normalize
- "One-time" without explaining what the item was
- "Various small items" for a material variance (must decompose further)
- Focusing only on the largest driver and ignoring offsetting items

## Waterfall Chart Methodology

### Concept

A waterfall (or bridge) chart shows how you get from one value to another through a series of positive and negative contributors. Used to visualize variance decomposition.

### Data Structure

```
Starting value:  [Base/Budget/Prior period amount]
Drivers:         [List of contributing factors with signed amounts]
Ending value:    [Actual/Current period amount]

Verification:    Starting value + Sum of all drivers = Ending value
```

### Text-Based Waterfall Format

When a charting tool is not available, present as a text waterfall:

```
WATERFALL: Revenue — Q4 Actual vs Q4 Budget

Q4 Budget Revenue                                    $10,000K
  |
  |--[+] Volume growth (new customers)               +$800K
  |--[+] Expansion revenue (existing customers)      +$400K
  |--[-] Price reductions / discounting               -$200K
  |--[-] Churn / contraction                          -$350K
  |--[+] FX tailwind                                  +$50K
  |--[-] Timing (deals slipped to Q1)                 -$150K
  |
Q4 Actual Revenue                                    $10,550K

Net Variance: +$550K (+5.5% favorable)
```

### Bridge Reconciliation Table

Complement the waterfall with a reconciliation table:

| Driver | Amount | % of Variance | Cumulative |
|--------|--------|---------------|------------|
| Volume growth | +$800K | 145% | +$800K |
| Expansion revenue | +$400K | 73% | +$1,200K |
| Price reductions | -$200K | -36% | +$1,000K |
| Churn / contraction | -$350K | -64% | +$650K |
| FX tailwind | +$50K | 9% | +$700K |
| Timing (deal slippage) | -$150K | -27% | +$550K |
| **Total variance** | **+$550K** | **100%** | |

*Note: Percentages can exceed 100% for individual drivers when there are offsetting items.*

### Waterfall Best Practices

1. Order drivers from largest positive to largest negative (or in logical business sequence)
2. Keep to 5-8 drivers maximum — aggregate smaller items into "Other"
3. Verify the waterfall reconciles (start + drivers = end)
4. Color-code: green for favorable, red for unfavorable (in visual charts)
5. Label each bar with both the amount and a brief description
6. Include a "Total Variance" summary bar

## Budget vs Actual vs Forecast Comparisons

### Three-Way Comparison Framework

| Metric | Budget | Forecast | Actual | Bud Var ($) | Bud Var (%) | Fcast Var ($) | Fcast Var (%) |
|--------|--------|----------|--------|-------------|-------------|---------------|---------------|
| Revenue | $X | $X | $X | $X | X% | $X | X% |
| COGS | $X | $X | $X | $X | X% | $X | X% |
| Gross Profit | $X | $X | $X | $X | X% | $X | X% |

### When to Use Each Comparison

- **Actual vs Budget:** Annual performance measurement, compensation decisions, board reporting. Budget is set at the beginning of the year and typically not changed.
- **Actual vs Forecast:** Operational management, identifying emerging issues. Forecast is updated periodically (monthly or quarterly) to reflect current expectations.
- **Forecast vs Budget:** Understanding how expectations have changed since planning. Useful for identifying planning accuracy issues.
- **Actual vs Prior Period:** Trend analysis, sequential performance. Useful when budget is not meaningful (new business lines, post-acquisition).
- **Actual vs Prior Year:** Year-over-year growth analysis, seasonality-adjusted comparison.

### Forecast Accuracy Analysis

Track how accurate forecasts are over time to improve planning:

```
Forecast Accuracy = 1 - |Actual - Forecast| / |Actual|

MAPE (Mean Absolute Percentage Error) = Average of |Actual - Forecast| / |Actual| across periods
```

| Period | Forecast | Actual | Variance | Accuracy |
|--------|----------|--------|----------|----------|
| Jan    | $X       | $X     | $X (X%)  | XX%      |
| Feb    | $X       | $X     | $X (X%)  | XX%      |
| ...    | ...      | ...    | ...      | ...      |
| **Avg**|          |        | **MAPE** | **XX%**  |

### Variance Trending

Track how variances evolve over the year to identify systematic bias:

- **Consistently favorable:** Budget may be too conservative (sandbagging)
- **Consistently unfavorable:** Budget may be too aggressive or execution issues
- **Growing unfavorable:** Deteriorating performance or unrealistic targets
- **Shrinking variance:** Forecast accuracy improving through the year (normal pattern)
- **Volatile:** Unpredictable business or poor forecasting methodology
