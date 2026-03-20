---
description: QA an analysis before sharing -- methodology, accuracy, and bias checks
argument-hint: "<analysis to review>"
---

# /validate - Validate Analysis Before Sharing

> If you see unfamiliar placeholders or need to check which tools are connected, see [CONNECTORS.md](../CONNECTORS.md).

Review an analysis for accuracy, methodology, and potential biases before sharing with stakeholders. Generates a confidence assessment and improvement suggestions.

## Usage

```
/validate <analysis to review>
```

The analysis can be:
- A document or report in the conversation
- A file (markdown, notebook, spreadsheet)
- SQL queries and their results
- Charts and their underlying data
- A description of methodology and findings

## Workflow

### 1. Review Methodology and Assumptions

Examine:

- **Question framing**: Is the analysis answering the right question? Could the question be interpreted differently?
- **Data selection**: Are the right tables/datasets being used? Is the time range appropriate?
- **Population definition**: Is the analysis population correctly defined? Are there unintended exclusions?
- **Metric definitions**: Are metrics defined clearly and consistently? Do they match how stakeholders understand them?
- **Baseline and comparison**: Is the comparison fair? Are time periods, cohort sizes, and contexts comparable?

### 2. Check for Common Analytical Errors

Systematically review for:

**Data completeness:**
- Missing data that could skew results (e.g., nulls in key fields, missing time periods)
- Data freshness issues (is the most recent data actually complete or still loading?)
- Survivorship bias (are you only looking at entities that "survived" to the analysis date?)

**Statistical issues:**
- Simpson's paradox (trend reverses when data is aggregated vs. segmented)
- Correlation presented as causation without supporting evidence
- Small sample sizes leading to unreliable conclusions
- Outliers disproportionately affecting averages (should medians be used instead?)
- Multiple testing / cherry-picking significant results

**Aggregation errors:**
- Double-counting from improper joins (many-to-many explosions)
- Incorrect denominators in rate calculations
- Mixing granularity levels (e.g., user-level metrics averaged with account-level)
- Revenue recognized vs. billed vs. collected confusion

**Time-related issues:**
- Seasonality not accounted for in comparisons
- Incomplete periods included in averages (e.g., partial month compared to full months)
- Timezone inconsistencies between data sources
- Look-ahead bias (using future information to explain past events)

**Selection and scope:**
- Cherry-picked time ranges that favor a particular narrative
- Excluded segments without justification
- Changing definitions mid-analysis

### 3. Verify Calculations and Aggregations

Where possible, spot-check:

- Recalculate a few key numbers independently
- Verify that subtotals sum to totals
- Check that percentages sum to 100% (or close to it) where expected
- Confirm that YoY/MoM comparisons use the correct base periods
- Validate that filters are applied consistently across all metrics

### 4. Assess Visualizations

If the analysis includes charts:

- Do axes start at appropriate values (zero for bar charts)?
- Are scales consistent across comparison charts?
- Do chart titles accurately describe what's shown?
- Could the visualization mislead a quick reader?
- Are there truncated axes, inconsistent intervals, or 3D effects that distort perception?

### 5. Evaluate Narrative and Conclusions

Review whether:

- Conclusions are supported by the data shown
- Alternative explanations are acknowledged
- Uncertainty is communicated appropriately
- Recommendations follow logically from findings
- The level of confidence matches the strength of evidence

### 6. Suggest Improvements

Provide specific, actionable suggestions:

- Additional analyses that would strengthen the conclusions
- Caveats or limitations that should be noted
- Better visualizations or framings for key points
- Missing context that stakeholders would want

### 7. Generate Confidence Assessment

Rate the analysis on a 3-level scale:

**Ready to share** -- Analysis is methodologically sound, calculations verified, caveats noted. Minor suggestions for improvement but nothing blocking.

**Share with noted caveats** -- Analysis is largely correct but has specific limitations or assumptions that must be communicated to stakeholders. List the required caveats.

**Needs revision** -- Found specific errors, methodological issues, or missing analyses that should be addressed before sharing. List the required changes with priority order.

## Output Format

```
## Validation Report

### Overall Assessment: [Ready to share | Share with caveats | Needs revision]

### Methodology Review
[Findings about approach, data selection, definitions]

### Issues Found
1. [Severity: High/Medium/Low] [Issue description and impact]
2. ...

### Calculation Spot-Checks
- [Metric]: [Verified / Discrepancy found]
- ...

### Visualization Review
[Any issues with charts or visual presentation]

### Suggested Improvements
1. [Improvement and why it matters]
2. ...

### Required Caveats for Stakeholders
- [Caveat that must be communicated]
- ...
```

## Examples

```
/validate Review this quarterly revenue analysis before I send it to the exec team: [analysis]
```

```
/validate Check my churn analysis -- I'm comparing Q4 churn rates to Q3 but Q4 has a shorter measurement window
```

```
/validate Here's a SQL query and its results for our conversion funnel. Does the logic look right? [query + results]
```

## Tips

- Run /validate before any high-stakes presentation or decision
- Even quick analyses benefit from a sanity check -- it takes a minute and can save your credibility
- If the validation finds issues, fix them and re-validate
- Share the validation output alongside your analysis to build stakeholder confidence
