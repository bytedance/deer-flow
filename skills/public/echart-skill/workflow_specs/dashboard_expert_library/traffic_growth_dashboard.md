# Traffic & Growth Dashboard Expert

Use this dashboard expert for traffic, acquisition, conversion, funnel, retention, campaigns, channels, pages, and growth-quality monitoring.

## Dashboard Mission

Help growth and product users decide whether growth is healthy: scale should be evaluated together with conversion, retention, channel quality, funnel loss, and anomalies.

## Required Modules

1. **Growth KPI summary**
   - Purpose: show traffic scale and efficiency.
   - Data needed: PV/UV/sessions/clicks/conversions/users.
   - Card: PV/UV/sessions, conversion rate, new users, returning users when calculable.

2. **Traffic trend**
   - Purpose: show traffic and conversion direction.
   - Data needed: date field + traffic/conversion metric.
   - Chart recipe: `references/examples/line-simple.md`; use dual-axis mixed recipe when traffic and conversion rate differ in unit.

3. **Channel/source breakdown**
   - Purpose: identify acquisition contributors.
   - Data needed: channel/source/campaign + metric.
   - Chart recipe: `references/examples/bar-simple.md`.

4. **Funnel module**
   - Purpose: locate conversion loss.
   - Data needed: funnel stage + users/events.
   - Chart recipe: funnel recipe from `references/examples/INDEX.md`.

5. **Retention/cohort module**
   - Purpose: separate acquisition spikes from retained growth.
   - Data needed: user ID, cohort date, return/active date.
   - Chart recipe: heatmap/calendar/cohort-like recipe from `references/examples/INDEX.md`.

6. **Cross-analysis**
   - Purpose: reveal low-quality acquisition or segment reversal.
   - Data needed: channel x funnel stage, page x device, campaign x conversion.
   - Chart recipe: heatmap, grouped bar, or stacked bar.

7. **Anomaly and attribution**
   - Purpose: flag spikes, bot-like traffic, conversion collapse, and channel mix shifts.
   - Data needed: date + metric + channel/source/device/page.
   - Module: alert cards + driver table.

8. **Data quality and scope note**
   - Purpose: show missing funnel/retention/cost caveats.
   - Required visible note: data range, event grain, user/session definitions, missing denominators.

## Interaction Model

- Filters: date range, channel/source, campaign, device, page, user segment.
- Drill-down dimensions: channel -> campaign -> page/device, funnel stage -> segment.
- Comparison controls: current period vs previous period; cohort comparison when possible.
- Tooltip content: metric, denominator, rate, share, comparison.
- Export/download behavior: export dashboard PDF and download charts.
- Theme behavior: page-level theme toggle.

## Geographic Rules

- If city geography and traffic/conversion/order metrics exist, read `workflow_specs/dashboard_modules/city_sales_map.md` only when the dashboard objective includes downstream sales/orders by city.
- For pure traffic geography without sales/volume, use a map recipe only after confirming the metric is meaningful at city level.

## Diagnostic Modules

- Cross-analysis matrix: time x channel, channel x funnel stage, campaign x device, page x conversion.
- Anomaly scan: traffic spike without conversion, CTR up but CVR down, retention cohort drop, channel concentration jump.
- Attribution path: growth change -> new vs returning -> channel/source -> funnel stage -> page/device/segment.
- Data-gap cards: missing funnel stage, missing user ID, missing retention date, missing spend/cost.

## Layout Guidance

- Header and title rules: use growth/traffic title only when fields support it.
- KPI row: PV/UV/sessions/CVR/new users/returning users where supported.
- Primary charts row: trend + channel breakdown.
- Diagnostic row: funnel + retention + anomaly/attribution.
- Responsive behavior: funnel and retention modules should remain readable with fixed heights.

## Chart Recipe Requirements

- Trend: `references/examples/line-simple.md`
- Mixed traffic/rate trend: `references/examples/mix-line-bar.md`
- Ranking/contribution: `references/examples/bar-simple.md`
- Funnel: choose from `references/examples/INDEX.md`.
- Retention/cohort: choose heatmap/calendar recipe from `references/examples/INDEX.md`.
- Fallback: data-gap card when required fields are missing.

## Validation Checklist

- Title is traceable to prompt/table/fields.
- At least 6 analytical modules are present when data supports them.
- Funnel and retention claims are absent unless fields support them.
- Every chart cites its recipe context.
- Dashboard includes interpretation cards for growth quality, not only traffic volume.
- No ROI/CAC/ROAS claim appears unless spend/cost fields exist.
