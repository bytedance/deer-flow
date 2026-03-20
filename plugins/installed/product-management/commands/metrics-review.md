---
description: Review and analyze product metrics with trend analysis and actionable insights
argument-hint: "<time period or metric focus>"
---

# Metrics Review

> If you see unfamiliar placeholders or need to check which tools are connected, see [CONNECTORS.md](../CONNECTORS.md).

Review and analyze product metrics, identify trends, and surface actionable insights.

## Workflow

### 1. Gather Metrics Data

If **~~product analytics** is connected:
- Pull key product metrics for the relevant time period
- Get comparison data (previous period, same period last year, targets)
- Pull segment breakdowns if available

If no analytics tool is connected, ask the user to provide:
- The metrics and their values (paste a table, screenshot, or describe)
- Comparison data (previous period, targets)
- Any context on recent changes (launches, incidents, seasonality)

Ask the user:
- What time period to review? (last week, last month, last quarter)
- What metrics to focus on? Or should we review the full product metrics suite?
- Are there specific targets or goals to compare against?
- Any known events that might explain changes (launches, outages, marketing campaigns, seasonality)?

### 2. Organize the Metrics

Structure the review using the metrics hierarchy from the **metrics-tracking** skill: North Star metric at the top, L1 health indicators (acquisition, activation, engagement, retention, revenue, satisfaction), and L2 diagnostic metrics for drill-down.

If the user has not defined their metrics hierarchy, help them identify their North Star and key L1 metrics before proceeding.

### 3. Analyze Trends

For each key metric:
- **Current value**: What is the metric today?
- **Trend**: Up, down, or flat compared to previous period? Over what timeframe?
- **vs Target**: How does it compare to the goal or target?
- **Rate of change**: Is the trend accelerating or decelerating?
- **Anomalies**: Any sudden changes, spikes, or drops?

Identify correlations:
- Do changes in one metric correlate with changes in another?
- Are there leading indicators that predict lagging metric changes?
- Do segment breakdowns reveal that an aggregate trend is driven by a specific cohort?

### 4. Generate the Review

#### Summary
2-3 sentences: overall product health, most notable changes, key callout.

#### Metric Scorecard
Table format for quick scanning:

| Metric | Current | Previous | Change | Target | Status |
|--------|---------|----------|--------|--------|--------|
| [Metric] | [Value] | [Value] | [+/- %] | [Target] | [On track / At risk / Miss] |

#### Trend Analysis
For each metric worth discussing:
- What happened and how significant is the change
- Why it likely happened (attribution based on known events, correlated metrics, segment analysis)
- Whether this is a one-time event or a sustained trend

#### Bright Spots
What is going well:
- Metrics beating targets
- Positive trends to sustain
- Segments or features showing strong performance

#### Areas of Concern
What needs attention:
- Metrics missing targets or trending negatively
- Early warning signals before they become problems
- Metrics where we lack visibility or understanding

#### Recommended Actions
Specific next steps based on the analysis:
- Investigations to run (dig deeper into a concerning trend)
- Experiments to launch (test hypotheses about what could improve a metric)
- Investments to make (double down on what is working)
- Alerts to set (monitor a metric more closely)

#### Context and Caveats
- Known data quality issues
- Events that affect comparability (outages, holidays, launches)
- Metrics we should be tracking but are not yet

### 5. Follow Up

After generating the review:
- Ask if any metric needs deeper investigation
- Offer to create a dashboard spec for ongoing monitoring
- Offer to draft experiment proposals for areas of concern
- Offer to set up a metrics review template for recurring use

## Output Format

Use tables for the scorecard. Use clear status indicators. Keep the summary tight — the reader should get the essential story in 30 seconds.

## Tips

- Start with the "so what" — what is the most important thing in this metrics review? Lead with that.
- Absolute numbers without context are useless. Always show comparisons (vs previous period, vs target, vs benchmark).
- Be careful about attribution. Correlation is not causation. If a metric moved, acknowledge uncertainty about why.
- Segment analysis often reveals that an aggregate metric masks important differences. A flat overall number might hide one segment growing and another shrinking.
- Not all metric movements matter. Small fluctuations are noise. Focus attention on meaningful changes.
- If a metric is missing its target, do not just report the miss — recommend what to do about it.
- Metrics reviews should drive decisions. If the review does not lead to at least one action, it was not useful.
