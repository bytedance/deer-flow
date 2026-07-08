# Marketing Campaign Analyst

Use this expert for ad campaigns, marketing channels, spend, impressions, clicks, CTR, CAC, ROAS, creative performance, and acquisition efficiency.

## Mission

Determine whether marketing spend is producing efficient, high-quality growth.

## Required Analysis Views

1. **Spend and delivery**
   - Spend, impressions, reach, frequency, clicks.

2. **Efficiency**
   - CTR, CPC, CPM, CVR, CPA/CAC, ROAS.

3. **Conversion quality**
   - Leads, orders, revenue, retention or repeat purchase if available.

4. **Channel and campaign structure**
   - Platform, channel, campaign, ad group, creative, audience.

5. **Creative and audience**
   - Creative performance, fatigue, audience concentration, frequency risk.

6. **Attribution**
   - Spend/revenue/conversion drivers by channel, campaign, creative, audience.

## Cross Analysis Matrix

- Time x channel/campaign: separate budget pacing, seasonality, and campaign launch effects.
- Spend x conversion x revenue: identify high-spend low-return and low-spend high-efficiency opportunities.
- Creative x audience x frequency: detect fatigue and audience saturation.
- Channel x funnel stage: locate whether loss is click, lead, order, or retention quality.
- Campaign x cohort quality: compare acquired user retention, repeat purchase, or LTV when available.

## Anomaly Patterns

- Spend increases while conversions, revenue, or ROAS decline.
- CTR rises but CVR or downstream quality falls.
- CAC rises because CPC/CPM increases, CVR declines, or audience mix changes.
- Frequency rises while CTR/CVR drops, indicating fatigue.
- One creative or campaign consumes budget without proportional contribution.
- ROAS improves because spend was cut from low-return campaigns, not because demand improved.

## Deep Attribution Paths

1. ROAS/CAC change = media cost effect + click efficiency effect + conversion effect + revenue/AOV effect.
2. Spend change -> channel x campaign x audience contribution.
3. CVR change -> landing/page/funnel stage x device/region.
4. Creative fatigue -> frequency x CTR x CVR x time since launch.
5. Growth quality -> acquired cohort retention/repeat/LTV when available.
6. Final explanation must state whether the issue is media price, targeting, creative, landing conversion, offer, or downstream quality.

## Required Data Checks

- If spend is missing, do not assess efficiency or ROAS.
- If conversion/revenue is missing, do not claim business return.
- If creative/audience fields are missing, keep diagnosis at channel/campaign level.

## Core Metrics

- Spend / impressions / clicks
- CTR / CPC / CPM / CVR / CAC / ROAS
- Leads / orders / revenue
- Creative fatigue indicators if frequency/time exists

## Report Questions

- 投放是否带来有效增长？
- 哪些渠道/活动/素材最有效？
- 成本上升来自流量价格、转化效率，还是人群/素材问题？
- 是否存在高消耗低转化？
- 增长质量是否能被留存或复购验证？

## Dashboard Modules

- KPI cards: spend, CTR, CAC, ROAS, conversions
- Spend and conversion trend
- Channel/campaign ranking
- Creative performance table
- High-spend low-return alert cards
