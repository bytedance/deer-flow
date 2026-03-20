---
description: Generate a weighted sales forecast with best/likely/worst scenarios, commit vs. upside breakdown, and gap analysis
argument-hint: "<period>"
---

# /forecast

> If you see unfamiliar placeholders or need to check which tools are connected, see [CONNECTORS.md](../CONNECTORS.md).

Generate a weighted sales forecast with risk analysis and commit recommendations.

## Usage

```
/forecast
```

Then provide your pipeline data and targets.

---

## How It Works

```
┌─────────────────────────────────────────────────────────────────┐
│                        FORECAST                                  │
├─────────────────────────────────────────────────────────────────┤
│  STANDALONE (always works)                                       │
│  ✓ Upload CSV export from your CRM                              │
│  ✓ Or paste/describe your pipeline deals                        │
│  ✓ Set your quota and timeline                                  │
│  ✓ Get weighted forecast with stage probabilities               │
│  ✓ Risk-adjusted projections (best/likely/worst case)           │
│  ✓ Commit vs. upside breakdown                                  │
│  ✓ Gap analysis and recommendations                             │
├─────────────────────────────────────────────────────────────────┤
│  SUPERCHARGED (when you connect your tools)                      │
│  + CRM: Pull pipeline automatically, real-time data             │
│  + Historical win rates by stage, segment, deal size            │
│  + Activity signals for risk scoring                            │
│  + Automatic refresh and tracking over time                     │
└─────────────────────────────────────────────────────────────────┘
```

---

## What I Need From You

### Step 1: Your Pipeline Data

**Option A: Upload a CSV**
Export your pipeline from your CRM (e.g. Salesforce, HubSpot). I need at minimum:
- Deal/Opportunity name
- Amount
- Stage
- Close date

Helpful if you have:
- Owner (if team forecast)
- Last activity date
- Created date
- Account name

**Option B: Paste your deals**
```
Acme Corp - $50K - Negotiation - closes Jan 31
TechStart - $25K - Demo scheduled - closes Feb 15
BigCo - $100K - Discovery - closes Mar 30
```

**Option C: Describe your territory**
"I have 8 deals in pipeline totaling $400K. Two are in negotiation ($120K), three in evaluation ($180K), three in discovery ($100K)."

### Step 2: Your Targets

- **Quota**: What's your number? (e.g., "$500K this quarter")
- **Timeline**: When does the period end? (e.g., "Q1 ends March 31")
- **Already closed**: How much have you already booked this period?

---

## Output

```markdown
# Sales Forecast: [Period]

**Generated:** [Date]
**Data Source:** [CSV upload / Manual input / CRM]

---

## Summary

| Metric | Value |
|--------|-------|
| **Quota** | $[X] |
| **Closed to Date** | $[X] ([X]% of quota) |
| **Open Pipeline** | $[X] |
| **Weighted Forecast** | $[X] |
| **Gap to Quota** | $[X] |
| **Coverage Ratio** | [X]x |

---

## Forecast Scenarios

| Scenario | Amount | % of Quota | Assumptions |
|----------|--------|------------|-------------|
| **Best Case** | $[X] | [X]% | All deals close as expected |
| **Likely Case** | $[X] | [X]% | Stage-weighted probabilities |
| **Worst Case** | $[X] | [X]% | Only commit deals close |

---

## Pipeline by Stage

| Stage | # Deals | Total Value | Probability | Weighted Value |
|-------|---------|-------------|-------------|----------------|
| Negotiation | [X] | $[X] | 80% | $[X] |
| Proposal | [X] | $[X] | 60% | $[X] |
| Evaluation | [X] | $[X] | 40% | $[X] |
| Discovery | [X] | $[X] | 20% | $[X] |
| **Total** | [X] | $[X] | — | $[X] |

---

## Commit vs. Upside

### Commit (High Confidence)
Deals you'd stake your forecast on:

| Deal | Amount | Stage | Close Date | Why Commit |
|------|--------|-------|------------|------------|
| [Deal] | $[X] | [Stage] | [Date] | [Reason] |

**Total Commit:** $[X]

### Upside (Lower Confidence)
Deals that could close but have risk:

| Deal | Amount | Stage | Close Date | Risk Factor |
|------|--------|-------|------------|-------------|
| [Deal] | $[X] | [Stage] | [Date] | [Risk] |

**Total Upside:** $[X]

---

## Risk Flags

| Deal | Amount | Risk | Recommendation |
|------|--------|------|----------------|
| [Deal] | $[X] | Close date passed | Update close date or move to lost |
| [Deal] | $[X] | No activity in 14+ days | Re-engage or downgrade stage |
| [Deal] | $[X] | Close date this week, still in discovery | Unlikely to close — push out |

---

## Gap Analysis

**To hit quota, you need:** $[X] more

**Options to close the gap:**
1. **Accelerate [Deal]** — Currently [stage], worth $[X]. If you can close by [date], you're at [X]% of quota.
2. **Revive [Stalled Deal]** — Last active [date]. Worth $[X]. Reach out to [contact].
3. **New pipeline needed** — You need $[X] in new opportunities at [X]x coverage to be safe.

---

## Recommendations

1. [ ] [Specific action for highest-impact deal]
2. [ ] [Action for at-risk deal]
3. [ ] [Pipeline generation recommendation if gap exists]
```

---

## Stage Probabilities (Default)

If you don't provide custom probabilities, I'll use:

| Stage | Default Probability |
|-------|---------------------|
| Closed Won | 100% |
| Negotiation / Contract | 80% |
| Proposal / Quote | 60% |
| Evaluation / Demo | 40% |
| Discovery / Qualification | 20% |
| Prospecting / Lead | 10% |

Tell me if your stages or probabilities are different.

---

## If CRM Connected

- I'll pull your pipeline automatically
- Use your actual historical win rates
- Factor in activity recency for risk scoring
- Track forecast changes over time
- Compare to previous forecasts

---

## Tips

1. **Be honest about commit** — Only commit deals you'd bet on. Upside is for everything else.
2. **Update close dates** — Stale close dates kill forecast accuracy. Push out deals that won't close in time.
3. **Coverage matters** — 3x pipeline coverage is healthy. Below 2x is risky.
4. **Activity = signal** — Deals with no recent activity are at higher risk than stage suggests.
