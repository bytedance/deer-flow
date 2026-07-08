# Expert Name

Use this expert for: `<business domain, table types, metrics, scenarios>`.

This is a template for custom experts. Do not select this file directly. Copy it
to a new Markdown file, fill every section, and register the new file in
`INDEX.md`.

## Mission

State what this expert is responsible for explaining. Describe the business
judgement the expert should make beyond charts and totals.

## Required Analysis Views

1. **View name**
   - What to measure.
   - How to compare it.
   - What abnormal pattern to look for.

2. **View name**
   - What to measure.
   - How to compare it.
   - What abnormal pattern to look for.

## Cross Analysis Matrix

- Time x primary segment:
- Segment x secondary segment:
- Metric x quality indicator:
- Value x risk/exception indicator:

Use these combinations to find hidden segment reversals, mix effects, and weak averages.

## Anomaly Patterns

- Sudden spike/drop:
- Distribution shift:
- Concentration change:
- Denominator change:
- Data quality anomaly:

For every anomaly, state whether it is likely business behavior, data quality, or unresolved.

## Deep Attribution Paths

1. Primary KPI change = driver A + driver B + driver C.
2. Drill into top positive contributor by the most relevant dimensions.
3. Drill into top negative contributor by the most relevant dimensions.
4. Stop only when additional splits do not materially change the explanation or data is insufficient.

## Required Data Checks

- If required field A is missing, state what conclusion cannot be supported.
- If required field B is missing, state the fallback analysis.
- If grain is ambiguous, state the assumption before calculating metrics.

## Core Metrics

- Metric 1
- Metric 2
- Metric 3
- Dimension contribution
- Period-over-period comparison

## Report Questions

- What happened?
- Why did it likely happen?
- Which segment contributed most?
- What risk or opportunity should the business act on?
- What data gap limits the conclusion?

## Dashboard Modules

- KPI cards
- Trend and comparison chart
- Segment breakdown
- Driver contribution table
- Risk/anomaly cards
- Data gap note
