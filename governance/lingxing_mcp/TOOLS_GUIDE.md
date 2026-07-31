# 领星 MCP 工具指南

> **服务**: `lingxing-mcp`（SSE，`http://localhost:8102/sse`）
> **版本**: 2026-07-30 v2（对齐 docs/lingxing-mcp-design.md；经真实数据 E2E 验证 14/14 链路 + sid 三种形式/紧凑签名探测）
> **工具数**: 19 个（设计 18 个 + 附加 `lx_inventory_days`）

---

## 一、调用须知（通用约定）

### 1.1 闭环第一规则

**几乎所有工具都需要 `sid`（店铺ID）或 `mid`（站点/国家ID），必须先调用 `lx_list_stores` 获取**，再调业务工具。

```
lx_list_stores() → 拿 sid / mid → 再调任何业务工具
```

### 1.2 传输与认证（对调用方透明）

- 业务域名：`https://openapi.lingxing.com`
- GET 端点（仅 2 个）：所有参数走 URL query
- POST 端点：业务参数走 **JSON body**（原始类型），鉴权参数（access_token/app_key/timestamp/sign）走 query；签名覆盖全部业务参数（list/dict 取**紧凑无空格** JSON 序列化值，如 `[8074,8075]`——带空格的 `[8074, 8075]` 会签验失败）
- Token 自动获取/刷新（有效期 7199s，提前 5 分钟刷新）；429 限流自动指数退避重试（0.5s/1s/2s，最多 3 次）

### 1.3 错误与空结果约定

| 情况 | 返回 | Agent 处理 |
|------|------|-----------|
| API 失败（鉴权/参数/限流） | `[{"error": "原因"}]` 或 `{"error": "...", ...}` | 把原因转告用户，勿当成"无数据" |
| 正常无数据 | `[]` / `{"total": 0, "list": []}` | 正常答复"该时段无数据" |
| 关键词未监控 | `[{"info": "...", "hint": "..."}]` | 引导用户确认后调 `lx_add_keyword_monitor` |
| 竞品未添加 | `[{"info": "...", "hint": "..."}]` | 提示用户到领星 ERP 网页端添加 |

### 1.4 数据时效与缓存

| 数据类 | TTL | 说明 |
|--------|-----|------|
| 店铺/市场列表 | 24h / 7d | 极少变化 |
| 业务报表（T+1） | 6h | 产品表现/达成率/趋势/利润/退货/搜索词/竞品/仓储费 |
| 广告数据（小时级） | 30min | 活动报表/关键词报表 |
| 活动列表（预算） | 1h | 预算可能调整 |
| 库存 | 1h | 断货风险 |
| 评论 / 写操作 | 不缓存 | 实时 |

---

## 二、工具明细

### 基础数据层

---

#### 1. `lx_list_stores` ⭐ 闭环总入口

- **作用**: 查询当前账号下所有亚马逊店铺。**所有工具的前置依赖，必须最先调用**
- **领星接口**: `GET /erp/sc/data/seller/lists`
- **入参**: 无

**出参要点**: `sid`（店铺ID，大部分工具必传）、`mid`（站点/国家ID，关键词工具必传）、`name`、`seller_id`、`region`、`country`、`status`(0停止/1正常/2异常/3欠费)、`has_ads_setting`

---

#### 2. `lx_list_marketplaces`

- **作用**: 查询所有亚马逊市场列表，辅助选择目标市场
- **领星接口**: `GET /erp/sc/data/seller/allMarketplace`
- **入参**: 无

**出参要点**: `mid`、`name`、`country`、`region`(NA/EU/FE)、`marketplace_id`、`currency_code`

---

### 产品数据层

---

#### 3. `lx_product_performance` ⭐ 核心工具

- **作用**: 产品表现一站式查询，单工具覆盖 9 个指标（#2 流量 / #3 CVR / #4 ACOS / #5 ROAS / #6 ACOAS / #19 评分 / #21 退货率 / #25 可售天数 / #1 部分）
- **领星接口**: `POST /bd/productPerformance/openApi/asinList`

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `sid` | int[] / str / int | ✅ | 店铺ID。与官方一致的三种形式：多店铺数组 `[5609,5608]`（上限200）；单店铺字符串 `"5608"` / int `5608` / 单元素数组 `[5608]` |
| `start_date` | string | ✅ | 开始日期 `yyyy-MM-dd` |
| `end_date` | string | ✅ | 结束日期（与开始间隔 ≤ 92 天） |
| `summary_field` | string | 否 | 汇总维度：`asin`(默认)/`parent_asin`/`msku`/`sku` |
| `search_field` | string | 否 | 搜索字段：`asin`/`parent_asin`/`msku`/`local_sku`/`item_name` |
| `search_value` | string | 否 | 搜索值（配合 search_field） |
| `sort_field` | string | 否 | 排序字段（如 `volume`/`amount`） |
| `sort_order` | string | 否 | `asc`/`desc`（给了 sort_field 时默认 desc） |
| `currency_code` | string | 否 | `USD`(默认)/`CNY` |
| `offset` / `length` | int | 否 | 分页，默认 0 / 100 |

**出参**: `{"total": n, "list": [...]}`；每行含 `volume`/`amount`/`sessions_total`/`cvr`/`acos`/`roas`/`acoas`/`spend`/`avg_star`+`prev_star`/`return_goods_rate`/`available_days`/`afn_fulfillable_quantity`/`cate_rank` 等全维度字段（数值可能为字符串格式，如 `"431.64"`）

---

#### 4. `lx_sales_target`

- **作用**: 店铺销售额目标及达成率（指标 #1）
- **领星接口**: `POST /bd/goal/management/open/store/batchSelect`

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `assess_year` | string | ✅ | 目标年份，如 `"2026"`（映射为 API 的 `assessYear`） |

**出参要点**: `goalAmount1~12`（月目标）、`realAmount1~12`（月实际）、`completeRateAmount1~12`（月完成率）、`totalGoalAmount`/`totalRealAmount`/`totalCompleteRate`
**注意**: 该接口成功码为 `code=1`（非常规 0），服务端已适配；仅店铺维度，ASIN 级达成率需用户提供目标值后用工具 3 的 `amount` 计算

---

#### 5. `lx_sales_trend`

- **作用**: ASIN 销量趋势（时间序列），回答"近 N 天销量走势 / 出单时段分布"
- **领星接口**: `POST /basicOpen/salesAnalysis/productPerformance/performanceTrendByHour`

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `sids` | string | ✅ | 店铺ID，逗号分隔（如 `"8074"` 或 `"8074,8075"`） |
| `date_start` | string | ✅ | 开始日期 |
| `date_end` | string | ✅ | 结束日期 |
| `summary_field` | string | ✅ | 维度：`asin`/`parent_asin`/`msku`/`sku`/`spu` |
| `summary_field_value` | string | ✅ | 维度值（如具体 ASIN） |
| `granularity` | string | 否 | `day`(默认，服务端把 24 个小时段聚合为天)/`hour` |

**出参**: `{"data": [{r_date, volume, order_items, amount, price, sales_rank}...], "total": {区间汇总}}`；day 模式下 price 由 amount/volume 重算，sales_rank 取当天最后值

---

### 广告数据层

> 该层 3 个报表工具的领星原生接口仅支持**单日** `report_date`，工具内部**按天循环调用并聚合**（单次跨度 ≤ 31 天）：绝对值求和，`acos`/`roas`/`cvr`/`ctr`/`cpc` 由求和结果重算（非简单平均）。对 Agent 完全透明。

---

#### 6. `lx_campaign_reports` ⭐

- **作用**: SP 广告活动报表（指标 #7 CVR / #8 ACOS / #9 ROAS）
- **领星接口**: `POST /pb/openapi/newad/spCampaignReports`（按天循环）

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `sid` | int | ✅ | 店铺ID |
| `start_date` | string | ✅ | 开始日期（跨度 ≤ 31 天） |
| `end_date` | string | ✅ | 结束日期 |
| `campaign_id` | int | 否 | 活动ID过滤（聚合后服务端侧过滤，聚焦单个活动） |
| `show_detail` | int | 否 | 1 返回 1d/7d/14d/30d 归因字段，默认 0 |
| `offset` / `length` | int | 否 | 分页，默认 0 / 100（按天请求时透传） |

**出参**: `[{campaign_id, campaign_name, impressions, clicks, cost, orders, sales, units, acos, roas, cvr, ctr, cpc}...]`
**注意**: 不返回预算，预算用 `lx_campaign_list` 获取后按 `campaign_id` 合并

---

#### 7. `lx_campaign_list`

- **作用**: SP 广告活动列表（管理数据），**唯一获取每日预算的途径**（指标 #10）
- **领星接口**: `POST /pb/openapi/newad/spCampaigns`

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `sid` | int | ✅ | 店铺ID |
| `state` | string | 否 | 状态过滤：`enabled`/`paused`/`archived` |
| `offset` / `length` | int | 否 | 分页，默认 0 / 15 |
| `next_token` | string | 否 | 分页游标（大数据量时） |

**出参要点**: `campaign_id`、`name`、`state`、`daily_budget`、`targeting_type`、`start_date`、`end_date`、`bidding`、`tags`
**闭环**: 与 `lx_campaign_reports` 通过 `campaign_id` 关联，合并出"预算+ACOS+ROAS+CVR"完整视图

---

#### 8. `lx_sp_keyword_reports`

- **作用**: SP 广告关键词报表（辅助 #11）
- **领星接口**: `POST /pb/openapi/newad/spKeywordReports`（按天循环）

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `sid` | int | ✅ | 店铺ID |
| `start_date` / `end_date` | string | ✅ | 日期范围（跨度 ≤ 31 天） |
| `show_detail` | int | 否 | 归因明细，默认 0 |
| `offset` / `length` | int | 否 | 分页，默认 0 / 100 |

**出参**: `[{keyword_id, keyword_text, match_type, campaign_id, campaign_name, ad_group_id, impressions, clicks, cost, orders, sales, acos, roas...}...]`（按 keyword_id 聚合）

---

#### 9. `lx_search_term_reports`

- **作用**: SP 广告搜索词报表（指标 #13 关键词-流量占比）
- **领星接口**: `POST /pb/openapi/newad/queryWordReports`（按天循环）

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `sid` | int | ✅ | 店铺ID |
| `target_type` | string | ✅ | `keyword`(关键词)/`target`(商品投放)，领星原生必填 |
| `start_date` / `end_date` | string | ✅ | 日期范围（跨度 ≤ 31 天） |
| `show_detail` | int | 否 | 默认 0 |
| `offset` / `length` | int | 否 | 分页，默认 0 / 100 |

**出参**: `[{query(用户搜索词), keyword_text, match_type, campaign_id, campaign_name, ad_group_id, asin, impressions, clicks, cost, orders, sales}...]`（按 query+campaign+ad_group+keyword 聚合）
**计算**: 流量占比 = 某词 `clicks` / 全部搜索词总 `clicks`（Agent 自行计算）

---

### 订单/财务层

---

#### 10. `lx_orders`

- **作用**: 亚马逊订单列表，支持时间/状态/配送方式筛选
- **领星接口**: `POST /erp/sc/data/mws/orders`

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `sid` | int | ✅ | 店铺ID |
| `start_date` / `end_date` | string | ✅ | 日期范围（跨度 ≤ 1 年） |
| `date_type` | int | 否 | 1=订购时间(站点)/2=修改时间(北京)/3=平台更新(UTC)/10=发货时间 |
| `order_status` | string | 否 | `Pending`/`Unshipped`/`PartiallyShipped`/`Shipped`/`Canceled` |
| `fulfillment_channel` | int | 否 | 1=FBA / 2=FBM |
| `offset` / `length` | int | 否 | 分页，默认 0 / 100（最大 5000） |

**出参**: `{"total": n, "data": [{amazon_order_id, order_status, order_total_amount, purchase_date_local, is_return, refund_amount, item_list: [{asin, seller_sku, local_sku, quantity_ordered, item_price}]}...]}`
**注意**: 接口无 ASIN 筛选参数，按 ASIN 分析请拉取后按 `item_list[].asin` 过滤

---

#### 11. `lx_profit_report_asin`

- **作用**: ASIN 维度利润报表（指标 #22 配送费）
- **领星接口**: `POST /bd/profit/report/open/report/asin/list`

| 参数（工具层） | 映射到 API | 类型 | 必填 | 说明 |
|------|------|------|------|------|
| `sids` | `sids` | int[] / str / int | ✅ | 店铺ID列表（上限200）；int 或字符串 `"5608"` 自动规范化为单元素数组 |
| `start_date` | `startDate` | string | ✅ | 开始日期（跨度 ≤ 31 天） |
| `end_date` | `endDate` | string | ✅ | 结束日期 |
| `search_field` | `searchField` | string | 否 | 搜索字段：`"asin"` |
| `search_value` | `searchValue` | string[] | 否 | ASIN 列表 |
| `mids` | `mids` | int[] | 否 | 国家ID列表 |
| `monthly_query` | `monthlyQuery` | bool | 否 | true=按月汇总（默认按天） |
| `currency_code` | `currencyCode` | string | 否 | `CNY`/`USD` |
| `order_status` | `orderStatus` | string | 否 | `Disbursed`/`Deferred`/`All` |
| `offset` / `length` | 同名 | int | 否 | 分页，默认 0 / 100 |

**出参要点**: `asin`/`parentAsin`/`sellerSku`/`totalSalesQuantity`/`totalSalesAmount`/`totalAdsCost`/`fbaDeliveryFee`(FBA配送费)/`totalStorageFee`/`sellingFeeRefunds`/`totalSalesRefunds`/`reimbursements`/`grossProfit`/`grossMargin`（响应为 `data.records` 结构，工具已提取）

---

### 库存数据层

---

#### 12. `lx_fba_inventory`

- **作用**: FBA 库存列表含库龄分布（指标 #23 冗余成本 / #24 冗余数量）
- **领星接口**: `POST /erp/sc/routing/fba/fbaStock/fbaList`

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `sid` | string | ✅ | 店铺ID（逗号分隔支持多个，如 `"8074"`；int 会自动转字符串） |
| `search_field` | string | 否 | `asin`/`msku`/`fnsku`/`sku` |
| `search_value` | string | 否 | 搜索值 |
| `redundant_threshold_days` | int | 否 | 冗余阈值天数，默认 90（可选 180/271/365） |
| `offset` / `length` | int | 否 | 分页，默认 0 / 100 |

**出参**: 每行含 `asin`/`msku`/`fnsku`/`afn_fulfillable_quantity`(可售)/`afn_unsellable_quantity`/`afn_inbound_shipped_quantity`(在途)/`inv_age_0_to_30_days`…`inv_age_365_plus_days`(7 个库龄段)/`cost`(单位成本)，**外加服务端计算字段**：
- `redundant_quantity` = 分段下限 > 阈值的库龄段库存量之和（阈值 90 → 91-180 + 181-270 + 271-365 + 365+）
- `redundant_cost` = 冗余数量 × cost
- `redundant_threshold_days` = 使用的阈值

---

#### 13. `lx_storage_fee`

- **作用**: FBA 仓储费（月仓储费 + 长期仓储费），辅助冗余成本分析
- **领星接口**:
  - `POST /erp/sc/data/fba_report/storageFeeMonth`（fee_type=monthly）
  - `POST /erp/sc/data/fba_report/storageFeeLongTerm`（fee_type=long_term）

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `sid` | int | ✅ | 店铺ID |
| `fee_type` | string | ✅ | `monthly` / `long_term` |
| `month` | string | 条件 | `yyyy-MM`，fee_type=monthly 时必填 |
| `start_date` / `end_date` | string | 条件 | fee_type=long_term 时必填 |
| `offset` / `length` | int | 否 | 分页，默认 0 / 1000 |

**出参（monthly）**: `asin`/`fnsku`/`estimated_monthly_storage_fee`/`storage_rate`/`average_quantity_on_hand`/`item_volume`/`product_size_tier`/`month_of_charge`/`currency`
**出参（long_term）**: `asin`/`fnsku`/`6_mo_long_terms_storage_fee`/`12_mo_long_terms_storage_fee`/`qty_charged_*`/`snapshot_date`/`currency`
**注意**: 无 ASIN 筛选参数，请拉取后按 `asin` 过滤；参数缺失/类型错误会返回 `{"error": ...}`

---

### 关键词层

---

#### 14. `lx_keyword_rank`

- **作用**: 关键词排名追踪（指标 #11 广告位 / #12 自然位）
- **领星接口**: `POST /erp/sc/routing/tool/toolKeywordRank/getKeywordList`

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `mid` | int | 否 | 国家/市场ID（从 `lx_list_stores` 获取；不传查全部站点） |
| `start_date` / `end_date` | string | 否 | 日期范围 |
| `search_field` | string | 否 | `key_word` / `asin` |
| `search_value` | string | 否 | 搜索值（如 `"yoga mat"`） |
| `offset` / `length` | int | 否 | 分页，默认 0 / 20（最大 2000） |

**出参要点**: `key_word`/`asin`/`rank`(综合排名)/`page`/`current_page_rank`/`is_sponsored`(**0=自然位,1=广告位**)/`sbv_page`/`type`(1=PC,2=移动)/`monitor_time`
**闭环**: 仅返回**已监控**的关键词；返回 `[{"info": "keyword not monitored...", "hint": ...}]` 表示未监控，经用户确认后调 `lx_add_keyword_monitor`（次日有数据）

---

#### 15. `lx_add_keyword_monitor` ⚠️ 写操作/Beta

- **作用**: 添加关键词排名监控——关键词未监控时的闭环工具
- **领星接口**: `POST /basicOpen/tool/keywordRanking/add`

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `mid` | int | ✅ | 国家/市场ID |
| `keywords` | string[] | ✅ | 关键词列表 |
| `asins` | string[] | ✅ | 监控的 ASIN 列表 |
| `types` | int[] | ✅ | 监控范围：1=PC端, 2=移动端 |
| `is_sponsors` | int[] | ✅ | 是否监控广告位：0=否, 1=是 |
| `postcodes` | string[] | 否 | 邮编（不传用默认） |

**出参**: `{"success": bool, "message": "..."}`
**限制**: 隐藏文档接口（Beta，有变动风险）；新监控从添加日开始采集，**次日**才可查；调用前先用 `lx_keyword_rank` 查重并向用户确认；失败时降级提示用户到领星 ERP 网页端手动添加

---

### 竞品监控层

---

#### 16. `lx_competitor_monitor`

- **作用**: 竞品监控数据（指标 #16 竞品-排名 / #17 竞品-价格）
- **领星接口**: `POST /basicOpen/tool/competitiveMonitor/list`

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `search_field` | string | 否 | `asin` |
| `search_value` | string | 否 | ASIN（多个逗号分隔，上限 200） |
| `levels` | int[] | 否 | 竞品等级：1=A, 2=B, 3=C, 4=D |
| `update_time_start` / `update_time_end` | string | 否 | 更新时间范围 |
| `offset` / `length` | int | 否 | 分页，默认 0 / 20（最大 200） |

**出参要点**: `asin`/`title`/`big_category_rank`(大类BSR)/`small_ranks`(小类)/`price`/`buybox_price`/`avg_price`/`star`/`review_num`/`fba_seller_num`/`monitor_status`
**限制**: 监控制，领星无添加竞品 API——需先在领星 ERP 网页端（工具→竞品监控）添加；查询为空会返回 hint 提示；不返回销量字段（#15 只能由 BSR 趋势间接推断）

---

### 退货分析层

---

#### 17. `lx_return_analysis`

- **作用**: 退货分析（指标 #21 退货率，含环比与 FBA/FBM 分布）
- **领星接口**: `POST /basicOpen/salesAnalysis/returnOrder/analysisLists`

| 参数（工具层） | 映射到 API | 类型 | 必填 | 说明 |
|------|------|------|------|------|
| `start_date` | `startDate` | string | ✅ | 开始日期（跨度 ≤ 366 天） |
| `end_date` | `endDate` | string | ✅ | 结束日期 |
| `asin_type` | `asinType` | string | ✅ | 维度：`asin`/`msku`/`parentAsin`/`sku`/`spu` |
| `date_type` | `dateType` | int | ✅ | 0=退货时间, 1=下单时间 |
| `store_id` | `storeId` | int[] | 否 | 店铺ID列表 |
| `mids` | `mids` | int[] | 否 | 国家ID列表 |
| `search_field` | `searchField` | string | 否 | `msku`/`asin`/`parentAsin`/`localSku`/`localName`/`spu` |
| `search_value` | `searchValue` | string[] | 否 | 搜索值列表 |
| `sort_field` | `sortField` | string | 否 | 排序字段 |
| `offset` / `length` | 同名 | int | 否 | 分页，默认 0 / 100 |

**出参要点**: 响应为 `data.records` 结构（工具已提取）：`asin`/`curReturnGoodsCount`(当期退货量)/`curReturnGoodsVolumeRatio`(当期退货率)/`curVolume`/`preReturnGoodsCount`/`preReturnGoodsVolumeRatio`(上期)/`returnGoodsCountRatio`(环比)/`returnGoodsVolumeRatioDiff`/`curReturnGoodsCountDistribution`(FBA/FBM 分布)

---

### 评论/评分层

---

#### 18. `lx_review_list`

- **作用**: Review 明细列表（指标 #20 新增差评，辅助 #19），实时数据不缓存
- **领星接口**: `POST /basicOpen/openapi/service/v3/data/mws/reviews`

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `date_field` | string | ✅ | 时间口径：`review_time`(评价时间)/`create_time`/`last_update_time` |
| `start_date` / `end_date` | string | ✅ | 日期范围 |
| `sids` | string | 否 | 店铺ID，逗号分隔 |
| `star` | string | 否 | 星级筛选，如 `"1,2,3"` 拉取差评 |
| `search_field` | string | 否 | `asin`/`parent_asin`/`amazon_order_id`/`author`/`review_id`/`last_title`/`buyer_email` |
| `search_value` | string | 否 | 搜索值 |
| `status` | string | 否 | 处理状态：0=待处理, 1=处理中, 2=已完成 |
| `sort_field` / `sort_type` | string | 否 | 默认 `review_date` / `desc` |
| `offset` / `length` | int | 否 | 分页，默认 0 / 20（最大 200） |

**出参要点**: `asin`/`last_star`(星级)/`last_title`/`last_content`(评论内容)/`review_date`/`author`/`is_vp`/`review_likes`/`images`/`videos`/`amazon_order_list`(关联订单)/`marketplace`
**闭环**: "昨天新增差评" → `lx_list_stores` 得 sids → 本工具(`star="1,2,3"`, 起止=昨天)

---

### 附加工具

---

#### 19. `lx_inventory_days`

- **作用**: FBA 库存 + 销量预测合并，返回可售天数（预测口径，与工具 3 的 `available_days` 统计口径互补）
- **领星接口**（合并两个）:
  - `POST /erp/sc/routing/fba/fbaStock/fbaList`（库存）
  - `POST /erp/sc/routing/fbaSug/asin/getDailySalesInfoFeature`（销量预测）

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `sid` | int | ✅ | 店铺ID |
| `asin` | string | ✅ | 商品 ASIN |
| `sug_type` | int | 否 | 1=建议采购量 / 2=建议本地仓发货量 / 3=建议海外仓发货量（默认） |
| `mode` | int | 否 | 预测模式 |

**出参**: `{asin, in_stock(FBA可售), in_transit(在途), daily_sales(预测日销), available_days(=in_stock/daily_sales，日销为0时为 null)}`

---

## 三、指标覆盖速查（25 指标）

| # | 指标 | 工具 | 状态 |
|---|------|------|------|
| 1 | 店铺销售额达成率 | `lx_sales_target` / `lx_product_performance` | ⚠️ 店铺级✅ / ASIN 级需用户提供目标 |
| 2 | 流量 | `lx_product_performance`(sessions_total) | ✅ |
| 3 | 点击转化率 | `lx_product_performance`(cvr) | ✅ |
| 4/5/6 | 广告 acos/roas/acoas | `lx_product_performance` | ✅ |
| 7/8/9 | 活动 CVR/ACOS/ROAS | `lx_campaign_reports` | ✅ |
| 10 | 活动预算 | `lx_campaign_list`(daily_budget) | ✅ |
| 11/12 | 关键词广告位/自然位 | `lx_keyword_rank`(is_sponsored) | ✅（监控制，配 #15 工具闭环） |
| 13 | 关键词流量占比 | `lx_search_term_reports`(clicks 占比) | ✅ |
| 14 | 搜索热度排名 | — | ❌ 领星无端点（Stretch: 卖家精灵） |
| 15 | 竞品销量 | `lx_competitor_monitor` | ⚠️ 不直接返回销量，BSR 推断 |
| 16/17 | 竞品排名/价格 | `lx_competitor_monitor` | ✅ |
| 18 | 竞品关键词流量占比 | — | ❌ 需额外数据源 |
| 19 | 评分变化 | `lx_product_performance`(avg_star+prev_star) / `lx_review_list` | ✅ |
| 20 | 新增差评 | `lx_review_list`(star="1,2,3") | ✅ |
| 21 | 退货率 | `lx_return_analysis` / `lx_product_performance` | ✅ |
| 22 | 配送费 | `lx_profit_report_asin`(fbaDeliveryFee) | ✅ |
| 23/24 | 库存冗余成本/数量 | `lx_fba_inventory`(redundant_*) | ✅ |
| 25 | 库存可售天数 | `lx_product_performance`(available_days) / `lx_inventory_days` | ✅ |

---

## 四、常用调用链速查

| 用户问题 | 调用链 |
|---------|--------|
| "B0XXXX 最近 30 天表现怎么样" | `lx_list_stores` → `lx_product_performance(sid, search_field="asin", search_value="B0XXXX")` |
| "US 店铺广告活动预算和 ACOS" | `lx_list_stores`(筛 country) → `lx_campaign_list(sid)` + `lx_campaign_reports(sid, 近30天)` → 按 campaign_id 合并 |
| "关键词 'yoga mat' 排名" | `lx_list_stores` → `lx_keyword_rank(mid, search_value="yoga mat")` → 为空则确认后 `lx_add_keyword_monitor` |
| "今年销售目标达成多少" | `lx_sales_target(assess_year="2026")` |
| "B0XXXX 近 30 天销量走势" | `lx_list_stores` → `lx_sales_trend(sids, summary_field_value="B0XXXX")` |
| "B0XXXX 的利润和配送费" | `lx_list_stores` → `lx_profit_report_asin(sids, search_value=["B0XXXX"])` |
| "哪些 ASIN 有库存冗余" | `lx_list_stores` → `lx_fba_inventory(sid)` → 看 redundant_quantity/redundant_cost |
| "B0XXXX 昨天有没有新增差评" | `lx_list_stores` → `lx_review_list(sids, star="1,2,3", 起止=昨天, search_value="B0XXXX")` |
| "店铺退货率环比" | `lx_list_stores` → `lx_return_analysis(store_id, asin_type="asin", date_type=0)` |

---

## 五、sid 参数形式（官方口径实测）

`lx_product_performance` 的 `sid` 与官方文档一致的三种形式（2026-07-30 真实探测）：

| 形式 | 示例 | 结果 |
|------|------|------|
| 单店铺字符串 | `"sid": "8074"` | ✅ success |
| 单店铺 int | `"sid": 8074` | ✅ success |
| 单元素数组 | `"sid": [8074]` | ✅ success |
| 多店铺数组 | `"sid": [8074, 8075]` | ✅ success（要求签名用紧凑 JSON，服务端已处理） |

> 注意：多店铺数组在签名序列化时必须紧凑无空格（`[8074,8075]`），否则领星返回 `api sign not correct`。本服务 client 已按此实现；`lx_profit_report_asin` 的 `sids` 同样兼容数组/int/字符串（自动规范化为数组）。

---

## 六、验证与运维

- **单元测试**: `cd governance/lingxing_mcp && uv run pytest tests/ -q`（110 个用例）
- **E2E 复验**（真实数据，走 MCP 协议 14 条链路）: `cd governance/lingxing_mcp && .venv/bin/python3 e2e_closed_loop.py`
- **端点探测**（query/body 传输方式）: `.venv/bin/python3 probe_endpoints.py`
- **重启服务**: `LINGXING_APP_ID=xxx LINGXING_APP_SECRET=yyy .venv/bin/python3 -m governance_lingxing_mcp.server`
