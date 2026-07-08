# Expert Library Index

Use this index before creating an enterprise report or dashboard.

The Agent must dynamically select experts from this library. Do not hardcode expert
selection in Python. Select at least one primary expert and, when useful, one or two
supporting experts.

## Selection Protocol

1. Inspect the user request, table/file names, column names, metric names, and sample values.
2. Match candidate experts using the trigger terms below.
3. Read the full Markdown file for each selected expert before writing the analysis plan.
4. State selected experts and confidence in the report/dashboard planning notes.
5. If no expert strongly matches, use `general_management.md` as the primary expert.
6. Do not select `EXPERT_TEMPLATE.md`; it is only a schema for custom experts.

## Mandatory Expert Reasoning Loop

Every selected expert must run this loop before writing conclusions:

1. **Define the primary KPI and baseline**
   - Identify the business metric to explain.
   - Choose a comparison baseline: previous period, same period last year, target, budget, cohort, or peer segment.
   - State why the baseline is valid.

2. **Scan anomalies before summarizing**
   - Detect spikes, drops, outliers, distribution shifts, missing periods, duplicated records, and denominator changes.
   - Separate likely business anomalies from data quality anomalies.
   - Do not average away abnormal segments.

3. **Run cross-analysis**
   - Cross the primary metric with at least two relevant dimensions when data allows.
   - Prefer combinations such as time x channel, product x region, customer x product, campaign x cohort, warehouse x carrier.
   - Look for Simpson's paradox: total improves while key segments deteriorate, or total declines while important segments grow.

4. **Perform deep attribution**
   - Decompose change into drivers: volume, price/rate, mix, conversion, retention, cost, efficiency, or exception rate.
   - Rank positive and negative contributors.
   - Continue drill-down until the next split no longer changes the explanation materially or data becomes insufficient.

5. **Generate expert conclusion**
   - Conclusion must name the driver, affected segment, magnitude, evidence, and recommended action.
   - If the cause is uncertain, state the competing hypotheses and what data would resolve them.

## Analysis Depth Rules

- A report is weak if it only lists KPI totals, rankings, or charts without explaining drivers.
- Every primary expert must include at least one cross-analysis and one attribution path when data supports it.
- Supporting experts should challenge the primary explanation: margin quality, retention quality, data quality, operational bottleneck, campaign efficiency, or risk.
- If required dimensions are missing, explicitly state which deep diagnosis cannot be performed and provide the best fallback.

## Expert Catalog

| Expert | File | Use When |
|--------|------|----------|
| General Management Analyst | `general_management.md` | Ambiguous business data, executive summaries, cross-domain operating reports |
| Traffic & Growth Analyst | `traffic_growth.md` | PV, UV, sessions, clicks, conversion, funnel, retention, campaign traffic |
| Sales & E-commerce Analyst | `sales_ecommerce.md` | Orders, GMV, revenue, product, category, channel, region, refund, AOV |
| Finance & Management Analyst | `finance_management.md` | Revenue, cost, expense, profit, margin, budget, cash, receivables |
| Customer & Membership Analyst | `customer_membership.md` | Customers, members, churn, repeat purchase, LTV, lifecycle, cohorts |
| Operations & Fulfillment Analyst | `operations_fulfillment.md` | Inventory, delivery, warehouse, fulfillment, SLA, delay, shortage |
| Marketing Campaign Analyst | `marketing_campaign.md` | Campaigns, ads, spend, impressions, CTR, CAC, ROAS, creative/channel performance |
| Product & Content Analyst | `product_content.md` | Features, pages, content, engagement, activation, usage paths, product retention |
| Risk & Data Quality Analyst | `risk_data_quality.md` | Missing values, anomalies, fraud, outliers, compliance, audit, suspicious records |

## Trigger Terms

### Traffic & Growth

`traffic`, `visit`, `visitor`, `session`, `pv`, `uv`, `click`, `ctr`, `conversion`,
`retention`, `cohort`, `funnel`, `page`, `source`, `campaign`, `用户`, `访问`,
`点击`, `转化`, `留存`, `漏斗`, `渠道`

### Sales & E-commerce

`sales`, `order`, `amount`, `revenue`, `gmv`, `product`, `sku`, `category`,
`refund`, `discount`, `订单`, `销售`, `商品`, `品类`, `支付`, `客单`, `收入`, `金额`

### Finance & Management

`profit`, `cost`, `expense`, `budget`, `margin`, `cash`, `receivable`, `payable`,
`利润`, `成本`, `费用`, `预算`, `毛利`, `现金`, `应收`, `应付`

### Customer & Membership

`customer`, `member`, `crm`, `churn`, `ltv`, `repeat`, `loyalty`, `会员`, `客户`,
`复购`, `流失`, `生命周期`, `分层`

### Operations & Fulfillment

`delivery`, `fulfillment`, `inventory`, `stock`, `warehouse`, `sla`, `delay`,
`物流`, `库存`, `履约`, `仓`, `配送`, `延迟`, `缺货`

### Marketing Campaign

`campaign`, `ad`, `spend`, `impression`, `cpc`, `cpm`, `cac`, `roas`, `creative`,
`投放`, `广告`, `消耗`, `曝光`, `素材`, `获客`, `活动`

### Product & Content

`feature`, `module`, `activation`, `engagement`, `page`, `content`, `path`,
`功能`, `模块`, `激活`, `参与`, `页面`, `内容`, `路径`

### Risk & Data Quality

`risk`, `fraud`, `audit`, `outlier`, `missing`, `null`, `duplicate`, `异常`,
`风险`, `欺诈`, `审计`, `缺失`, `重复`, `脏数据`

## Multi-expert Examples

- Traffic dashboard with ad spend: primary `traffic_growth.md`, support `marketing_campaign.md`
- E-commerce sales report with refund/margin: primary `sales_ecommerce.md`, support `finance_management.md`
- Member purchase analysis: primary `customer_membership.md`, support `sales_ecommerce.md`
- Delivery delay report: primary `operations_fulfillment.md`, support `risk_data_quality.md`

## Custom Expert Contract

To add a custom expert:

1. Copy `EXPERT_TEMPLATE.md` to a new file in this folder.
2. Fill every required section.
3. Add the new expert to the Expert Catalog.
4. Add trigger terms that distinguish it from existing experts.
5. Keep business judgement in Markdown. Do not implement the expert as Python rules.
