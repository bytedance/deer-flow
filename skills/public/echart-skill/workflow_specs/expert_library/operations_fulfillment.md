# Operations & Fulfillment Analyst

Use this expert for inventory, delivery, warehouse, fulfillment, SLA, logistics, delay, backlog, and operational efficiency.

## Mission

Identify operational bottlenecks and translate them into process actions.

## Required Analysis Views

1. **Volume and workload**
   - Orders/tasks/shipments/production volume by period.

2. **Timeliness**
   - Delivery time, processing time, SLA achievement, delay rate.

3. **Exception**
   - Shortage, cancellation, failed delivery, return, damage, backlog.

4. **Capacity and utilization**
   - Warehouse, team, carrier, machine, route, shift if available.

5. **Inventory**
   - Stock, turnover, days of inventory, out-of-stock, overstock.

6. **Attribution**
   - Bottleneck by warehouse, region, carrier, product type, process step.

## Cross Analysis Matrix

- Time x process step: identify which step creates delay during peaks.
- Warehouse x carrier/route: separate warehouse capacity problems from logistics partner problems.
- Product type x exception: identify fragile, bulky, cold-chain, or special-handling risks.
- Inventory x demand x fulfillment: connect stock availability with service failure.
- SLA x region/customer segment: identify service-level inequality.

## Anomaly Patterns

- Volume is stable but delay rate or processing time rises.
- SLA breach concentrates in one carrier, warehouse, route, or product type.
- Backlog grows before visible delay increases.
- Stockout and cancellation rise together.
- Inventory increases while availability or fulfillment rate declines.
- Exception rate spikes after process, system, or vendor changes.

## Deep Attribution Paths

1. SLA/delay change -> process step contribution: picking, packing, handoff, transit, delivery.
2. Step delay -> warehouse x shift/team x product type.
3. Transit delay -> carrier x route x region.
4. Inventory risk -> demand change + replenishment lag + allocation issue.
5. Exception change -> shortage/cancel/return/damage/failed delivery by owner.
6. Final explanation must identify the operational bottleneck and whether action is capacity, routing, inventory, process, or vendor governance.

## Required Data Checks

- If timestamps are missing, do not infer timeliness.
- If status fields are missing, do not infer exception rate.
- If inventory fields are missing, do not infer stock risk.

## Core Metrics

- Fulfillment volume
- Average processing/delivery time
- SLA achievement rate / delay rate
- Inventory turnover / out-of-stock rate
- Exception rate by type

## Report Questions

- 履约能力是否稳定？
- 延迟或异常集中在哪些环节？
- 哪些仓库、区域、承运商或商品类型是瓶颈？
- 库存风险是缺货还是积压？
- 下一步应该调拨、补货、优化流程还是治理供应商？

## Dashboard Modules

- KPI cards: volume, SLA, delay, exception, inventory turnover
- Fulfillment trend
- Bottleneck ranking
- Exception breakdown
- Inventory risk table
