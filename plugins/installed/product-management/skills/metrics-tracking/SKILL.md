---
name: metrics-tracking
description: Define, track, and analyze product metrics with frameworks for goal setting and dashboard design. Use when setting up OKRs, building metrics dashboards, running weekly metrics reviews, identifying trends, or choosing the right metrics for a product area.
---

# Metrics Tracking Skill

You are an expert at product metrics — defining, tracking, analyzing, and acting on product metrics. You help product managers build metrics frameworks, set goals, run reviews, and design dashboards that drive decisions.

## Product Metrics Hierarchy

### North Star Metric
The single metric that best captures the core value your product delivers to users. It should be:

- **Value-aligned**: Moves when users get more value from the product
- **Leading**: Predicts long-term business success (revenue, retention)
- **Actionable**: The product team can influence it through their work
- **Understandable**: Everyone in the company can understand what it means and why it matters

**Examples by product type**:
- Collaboration tool: Weekly active teams with 3+ members contributing
- Marketplace: Weekly transactions completed
- SaaS platform: Weekly active users completing core workflow
- Content platform: Weekly engaged reading/viewing time
- Developer tool: Weekly deployments using the tool

### L1 Metrics (Health Indicators)
The 5-7 metrics that together paint a complete picture of product health. These map to the key stages of the user lifecycle:

**Acquisition**: Are new users finding the product?
- New signups or trial starts (volume and trend)
- Signup conversion rate (visitors to signups)
- Channel mix (where are new users coming from)
- Cost per acquisition (for paid channels)

**Activation**: Are new users reaching the value moment?
- Activation rate: % of new users who complete the key action that predicts retention
- Time to activate: how long from signup to activation
- Setup completion rate: % who complete onboarding steps
- First value moment: when users first experience the core product value

**Engagement**: Are active users getting value?
- DAU / WAU / MAU: active users at different timeframes
- DAU/MAU ratio (stickiness): what fraction of monthly users come back daily
- Core action frequency: how often users do the thing that matters most
- Session depth: how much users do per session
- Feature adoption: % of users using key features

**Retention**: Are users coming back?
- D1, D7, D30 retention: % of users who return after 1 day, 7 days, 30 days
- Cohort retention curves: how retention evolves for each signup cohort
- Churn rate: % of users or revenue lost per period
- Resurrection rate: % of churned users who come back

**Monetization**: Is value translating to revenue?
- Conversion rate: free to paid (for freemium)
- MRR / ARR: monthly or annual recurring revenue
- ARPU / ARPA: average revenue per user or account
- Expansion revenue: revenue growth from existing customers
- Net revenue retention: revenue retention including expansion and contraction

**Satisfaction**: How do users feel about the product?
- NPS: Net Promoter Score
- CSAT: Customer Satisfaction Score
- Support ticket volume and resolution time
- App store ratings and review sentiment

### L2 Metrics (Diagnostic)
Detailed metrics used to investigate changes in L1 metrics:

- Funnel conversion at each step
- Feature-level usage and adoption
- Segment-specific breakdowns (by plan, company size, geography, user role)
- Performance metrics (page load time, error rate, API latency)
- Content-specific engagement (which features, pages, or content types drive engagement)

## Common Product Metrics

### DAU / WAU / MAU
**What they measure**: Unique users who perform a qualifying action in a day, week, or month.

**Key decisions**:
- What counts as "active"? A login? A page view? A core action? Define this carefully — different definitions tell different stories.
- Which timeframe matters most? DAU for daily-use products (messaging, email). WAU for weekly-use products (project management). MAU for less frequent products (tax software, travel booking).

**How to use them**:
- DAU/MAU ratio (stickiness): values above 0.5 indicate a daily habit. Below 0.2 suggests infrequent usage.
- Trend matters more than absolute number. Is active usage growing, flat, or declining?
- Segment by user type. Power users and casual users behave very differently.

### Retention
**What it measures**: Of users who started in period X, what % are still active in period Y?

**Common retention timeframes**:
- D1 (next day): Was the first experience good enough to come back?
- D7 (one week): Did the user establish a habit?
- D30 (one month): Is the user retained long-term?
- D90 (three months): Is this a durable user?

**How to use retention**:
- Plot retention curves by cohort. Look for: initial drop-off (activation problem), steady decline (engagement problem), or flattening (good — you have a stable retained base).
- Compare cohorts over time. Are newer cohorts retaining better than older ones? That means product improvements are working.
- Segment retention by activation behavior. Users who completed onboarding vs those who did not. Users who used feature X vs those who did not.

### Conversion
**What it measures**: % of users who move from one stage to the next.

**Common conversion funnels**:
- Visitor to signup
- Signup to activation (key value moment)
- Free to paid (trial conversion)
- Trial to paid subscription
- Monthly to annual plan

**How to use conversion**:
- Map the full funnel and measure conversion at each step
- Identify the biggest drop-off points — these are your highest-leverage improvement opportunities
- Segment conversion by source, plan, user type. Different segments convert very differently.
- Track conversion over time. Is it improving as you iterate on the experience?

### Activation
**What it measures**: % of new users who reach the moment where they first experience the product's core value.

**Defining activation**:
- Look at retained users vs churned users. What actions did retained users take that churned users did not?
- The activation event should be strongly predictive of long-term retention
- It should be achievable within the first session or first few days
- Examples: created first project, invited a teammate, completed first workflow, connected an integration

**How to use activation**:
- Track activation rate for every signup cohort
- Measure time to activate — faster is almost always better
- Build onboarding flows that guide users to the activation moment
- A/B test activation flows and measure impact on retention, not just activation rate

## Goal Setting Frameworks

### OKRs (Objectives and Key Results)

**Objectives**: Qualitative, aspirational goals that describe what you want to achieve.
- Inspiring and memorable
- Time-bound (quarterly or annually)
- Directional, not metric-specific

**Key Results**: Quantitative measures that tell you if you achieved the objective.
- Specific and measurable
- Time-bound with a clear target
- Outcome-based, not output-based
- 2-4 Key Results per Objective

**Example**:
```
Objective: Make our product indispensable for daily workflows

Key Results:
- Increase DAU/MAU ratio from 0.35 to 0.50
- Increase D30 retention for new users from 40% to 55%
- 3 core workflows with >80% task completion rate
```

### OKR Best Practices
- Set OKRs that are ambitious but achievable. 70% completion is the target for stretch OKRs.
- Key Results should measure outcomes (user behavior, business results), not outputs (features shipped, tasks completed).
- Do not have too many OKRs. 2-3 objectives with 2-4 KRs each is plenty.
- OKRs should be uncomfortable. If you are confident you will hit all of them, they are not ambitious enough.
- Review OKRs at mid-period. Adjust effort allocation if some KRs are clearly off track.
- Grade OKRs honestly at end of period. 0.0-0.3 = missed, 0.4-0.6 = progress, 0.7-1.0 = achieved.

### Setting Metric Targets
- **Baseline**: What is the current value? You need a reliable baseline before setting a target.
- **Benchmark**: What do comparable products achieve? Industry benchmarks provide context.
- **Trajectory**: What is the current trend? If the metric is already improving at 5% per month, a 6% target is not ambitious.
- **Effort**: How much investment are you putting behind this? Bigger bets warrant more ambitious targets.
- **Confidence**: How confident are you in hitting the target? Set a "commit" (high confidence) and a "stretch" (ambitious).

## Metric Review Cadences

### Weekly Metrics Check
**Purpose**: Catch issues quickly, monitor experiments, stay in touch with product health.
**Duration**: 15-30 minutes.
**Attendees**: Product manager, maybe engineering lead.

**What to review**:
- North Star metric: current value, week-over-week change
- Key L1 metrics: any notable movements
- Active experiments: results and statistical significance
- Anomalies: any unexpected spikes or drops
- Alerts: anything that triggered a monitoring alert

**Action**: If something looks off, investigate. Otherwise, note it and move on.

### Monthly Metrics Review
**Purpose**: Deeper analysis of trends, progress against goals, strategic implications.
**Duration**: 30-60 minutes.
**Attendees**: Product team, key stakeholders.

**What to review**:
- Full L1 metric scorecard with month-over-month trends
- Progress against quarterly OKR targets
- Cohort analysis: are newer cohorts performing better?
- Feature adoption: how are recent launches performing?
- Segment analysis: any divergence between user segments?

**Action**: Identify 1-3 areas to investigate or invest in. Update priorities if metrics reveal new information.

### Quarterly Business Review
**Purpose**: Strategic assessment of product performance, goal-setting for next quarter.
**Duration**: 60-90 minutes.
**Attendees**: Product, engineering, design, leadership.

**What to review**:
- OKR scoring for the quarter
- Trend analysis for all L1 metrics over the quarter
- Year-over-year comparisons
- Competitive context: market changes and competitor movements
- What worked and what did not

**Action**: Set OKRs for next quarter. Adjust product strategy based on what the data shows.

## Dashboard Design Principles

### Effective Product Dashboards
A good dashboard answers the question "How is the product doing?" at a glance.

**Principles**:

1. **Start with the question, not the data**. What decisions does this dashboard support? Design backwards from the decision.

2. **Hierarchy of information**. The most important metric should be the most visually prominent. North Star at the top, L1 metrics next, L2 metrics available on drill-down.

3. **Context over numbers**. A number without context is meaningless. Always show: current value, comparison (previous period, target, benchmark), trend direction.

4. **Fewer metrics, more insight**. A dashboard with 50 metrics helps no one. Focus on 5-10 that matter. Put everything else in a detailed report.

5. **Consistent time periods**. Use the same time period for all metrics on a dashboard. Mixing daily and monthly metrics creates confusion.

6. **Visual status indicators**. Use color to indicate health at a glance:
   - Green: on track or improving
   - Yellow: needs attention or flat
   - Red: off track or declining

7. **Actionability**. Every metric on the dashboard should be something the team can influence. If you cannot act on it, it does not belong on the product dashboard.

### Dashboard Layout

**Top row**: North Star metric with trend line and target.

**Second row**: L1 metrics scorecard — current value, change, target, status for each key metric.

**Third row**: Key funnels or conversion metrics — visual funnel showing drop-off at each stage.

**Fourth row**: Recent experiments and launches — active A/B tests, recent feature launches with early metrics.

**Bottom / drill-down**: L2 metrics, segment breakdowns, and detailed time series for investigation.

### Dashboard Anti-Patterns
- **Vanity metrics**: Metrics that always go up but do not indicate health (total signups ever, total page views)
- **Too many metrics**: Dashboards that require scrolling to see. If it does not fit on one screen, cut metrics.
- **No comparison**: Raw numbers without context (current value with no previous period or target)
- **Stale dashboards**: Metrics that have not been updated or reviewed in months
- **Output dashboards**: Measuring team activity (tickets closed, PRs merged) instead of user and business outcomes
- **One dashboard for all audiences**: Executives, PMs, and engineers need different views. One size does not fit all.

### Alerting
Set alerts for metrics that require immediate attention:

- **Threshold alerts**: Metric drops below or rises above a critical threshold (error rate > 1%, conversion < 5%)
- **Trend alerts**: Metric shows sustained decline over multiple days/weeks
- **Anomaly alerts**: Metric deviates significantly from expected range

**Alert hygiene**:
- Every alert should be actionable. If you cannot do anything about it, do not alert on it.
- Review and tune alerts regularly. Too many false positives and people ignore all alerts.
- Define an owner for each alert. Who responds when it fires?
- Set appropriate severity levels. Not everything is P0.
