---
name: data-validation
description: QA an analysis before sharing with stakeholders — methodology checks, accuracy verification, and bias detection. Use when reviewing an analysis for errors, checking for survivorship bias, validating aggregation logic, or preparing documentation for reproducibility.
---

# Data Validation Skill

Pre-delivery QA checklist, common data analysis pitfalls, result sanity checking, and documentation standards for reproducibility.

## Pre-Delivery QA Checklist

Run through this checklist before sharing any analysis with stakeholders.

### Data Quality Checks

- [ ] **Source verification**: Confirmed which tables/data sources were used. Are they the right ones for this question?
- [ ] **Freshness**: Data is current enough for the analysis. Noted the "as of" date.
- [ ] **Completeness**: No unexpected gaps in time series or missing segments.
- [ ] **Null handling**: Checked null rates in key columns. Nulls are handled appropriately (excluded, imputed, or flagged).
- [ ] **Deduplication**: Confirmed no double-counting from bad joins or duplicate source records.
- [ ] **Filter verification**: All WHERE clauses and filters are correct. No unintended exclusions.

### Calculation Checks

- [ ] **Aggregation logic**: GROUP BY includes all non-aggregated columns. Aggregation level matches the analysis grain.
- [ ] **Denominator correctness**: Rate and percentage calculations use the right denominator. Denominators are non-zero.
- [ ] **Date alignment**: Comparisons use the same time period length. Partial periods are excluded or noted.
- [ ] **Join correctness**: JOIN types are appropriate (INNER vs LEFT). Many-to-many joins haven't inflated counts.
- [ ] **Metric definitions**: Metrics match how stakeholders define them. Any deviations are noted.
- [ ] **Subtotals sum**: Parts add up to the whole where expected. If they don't, explain why (e.g., overlap).

### Reasonableness Checks

- [ ] **Magnitude**: Numbers are in a plausible range. Revenue isn't negative. Percentages are between 0-100%.
- [ ] **Trend continuity**: No unexplained jumps or drops in time series.
- [ ] **Cross-reference**: Key numbers match other known sources (dashboards, previous reports, finance data).
- [ ] **Order of magnitude**: Total revenue is in the right ballpark. User counts match known figures.
- [ ] **Edge cases**: What happens at the boundaries? Empty segments, zero-activity periods, new entities.

### Presentation Checks

- [ ] **Chart accuracy**: Bar charts start at zero. Axes are labeled. Scales are consistent across panels.
- [ ] **Number formatting**: Appropriate precision. Consistent currency/percentage formatting. Thousands separators where needed.
- [ ] **Title clarity**: Titles state the insight, not just the metric. Date ranges are specified.
- [ ] **Caveat transparency**: Known limitations and assumptions are stated explicitly.
- [ ] **Reproducibility**: Someone else could recreate this analysis from the documentation provided.

## Common Data Analysis Pitfalls

### Join Explosion

**The problem**: A many-to-many join silently multiplies rows, inflating counts and sums.

**How to detect**:
```sql
-- Check row count before and after join
SELECT COUNT(*) FROM table_a;  -- 1,000
SELECT COUNT(*) FROM table_a a JOIN table_b b ON a.id = b.a_id;  -- 3,500 (uh oh)
```

**How to prevent**:
- Always check row counts after joins
- If counts increase, investigate the join relationship (is it really 1:1 or 1:many?)
- Use `COUNT(DISTINCT a.id)` instead of `COUNT(*)` when counting entities through joins

### Survivorship Bias

**The problem**: Analyzing only entities that exist today, ignoring those that were deleted, churned, or failed.

**Examples**:
- Analyzing user behavior of "current users" misses churned users
- Looking at "companies using our product" ignores those who evaluated and left
- Studying properties of "successful" outcomes without "unsuccessful" ones

**How to prevent**: Ask "who is NOT in this dataset?" before drawing conclusions.

### Incomplete Period Comparison

**The problem**: Comparing a partial period to a full period.

**Examples**:
- "January revenue is $500K vs. December's $800K" -- but January isn't over yet
- "This week's signups are down" -- checked on Wednesday, comparing to a full prior week

**How to prevent**: Always filter to complete periods, or compare same-day-of-month / same-number-of-days.

### Denominator Shifting

**The problem**: The denominator changes between periods, making rates incomparable.

**Examples**:
- Conversion rate improves because you changed how you count "eligible" users
- Churn rate changes because the definition of "active" was updated

**How to prevent**: Use consistent definitions across all compared periods. Note any definition changes.

### Average of Averages

**The problem**: Averaging pre-computed averages gives wrong results when group sizes differ.

**Example**:
- Group A: 100 users, average revenue $50
- Group B: 10 users, average revenue $200
- Wrong: Average of averages = ($50 + $200) / 2 = $125
- Right: Weighted average = (100*$50 + 10*$200) / 110 = $63.64

**How to prevent**: Always aggregate from raw data. Never average pre-aggregated averages.

### Timezone Mismatches

**The problem**: Different data sources use different timezones, causing misalignment.

**Examples**:
- Event timestamps in UTC vs. user-facing dates in local time
- Daily rollups that use different cutoff times

**How to prevent**: Standardize all timestamps to a single timezone (UTC recommended) before analysis. Document the timezone used.

### Selection Bias in Segmentation

**The problem**: Segments are defined by the outcome you're measuring, creating circular logic.

**Examples**:
- "Users who completed onboarding have higher retention" -- obviously, they self-selected
- "Power users generate more revenue" -- they became power users BY generating revenue

**How to prevent**: Define segments based on pre-treatment characteristics, not outcomes.

## Result Sanity Checking

### Magnitude Checks

For any key number in your analysis, verify it passes the "smell test":

| Metric Type | Sanity Check |
|---|---|
| User counts | Does this match known MAU/DAU figures? |
| Revenue | Is this in the right order of magnitude vs. known ARR? |
| Conversion rates | Is this between 0% and 100%? Does it match dashboard figures? |
| Growth rates | Is 50%+ MoM growth realistic, or is there a data issue? |
| Averages | Is the average reasonable given what you know about the distribution? |
| Percentages | Do segment percentages sum to ~100%? |

### Cross-Validation Techniques

1. **Calculate the same metric two different ways** and verify they match
2. **Spot-check individual records** -- pick a few specific entities and trace their data manually
3. **Compare to known benchmarks** -- match against published dashboards, finance reports, or prior analyses
4. **Reverse engineer** -- if total revenue is X, does per-user revenue times user count approximately equal X?
5. **Boundary checks** -- what happens when you filter to a single day, a single user, or a single category? Are those micro-results sensible?

### Red Flags That Warrant Investigation

- Any metric that changed by more than 50% period-over-period without an obvious cause
- Counts or sums that are exact round numbers (suggests a filter or default value issue)
- Rates exactly at 0% or 100% (may indicate incomplete data)
- Results that perfectly confirm the hypothesis (reality is usually messier)
- Identical values across time periods or segments (suggests the query is ignoring a dimension)

## Documentation Standards for Reproducibility

### Analysis Documentation Template

Every non-trivial analysis should include:

```markdown
## Analysis: [Title]

### Question
[The specific question being answered]

### Data Sources
- Table: [schema.table_name] (as of [date])
- Table: [schema.other_table] (as of [date])
- File: [filename] (source: [where it came from])

### Definitions
- [Metric A]: [Exactly how it's calculated]
- [Segment X]: [Exactly how membership is determined]
- [Time period]: [Start date] to [end date], [timezone]

### Methodology
1. [Step 1 of the analysis approach]
2. [Step 2]
3. [Step 3]

### Assumptions and Limitations
- [Assumption 1 and why it's reasonable]
- [Limitation 1 and its potential impact on conclusions]

### Key Findings
1. [Finding 1 with supporting evidence]
2. [Finding 2 with supporting evidence]

### SQL Queries
[All queries used, with comments]

### Caveats
- [Things the reader should know before acting on this]
```

### Code Documentation

For any code (SQL, Python) that may be reused:

```python
"""
Analysis: Monthly Cohort Retention
Author: [Name]
Date: [Date]
Data Source: events table, users table
Last Validated: [Date] -- results matched dashboard within 2%

Purpose:
    Calculate monthly user retention cohorts based on first activity date.

Assumptions:
    - "Active" means at least one event in the month
    - Excludes test/internal accounts (user_type != 'internal')
    - Uses UTC dates throughout

Output:
    Cohort retention matrix with cohort_month rows and months_since_signup columns.
    Values are retention rates (0-100%).
"""
```

### Version Control for Analyses

- Save queries and code in version control (git) or a shared docs system
- Note the date of the data snapshot used
- If an analysis is re-run with updated data, document what changed and why
- Link to prior versions of recurring analyses for trend comparison
