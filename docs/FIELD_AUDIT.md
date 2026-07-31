# 字段监控审计文档

> **用途**：逐字段审计 deer-flow 能监控的所有指标，标注来源/接入情况/工具名。便于查漏补缺。
> **最后更新**：2026-07-29

---

## 一、已接入字段（7 个 P0 工具，53 测试通过）

### 销量/产品表现（lx_parent_sales，T+1，TTL 6h）

| 监控字段 | 来源 | 接入情况 | 工具名称 | 备注 |
|---|---|---|---|---|
| 销量 volume | 领星 /bd/productPerformance/openApi/asinList | ✅ 已接入 | lx_parent_sales | 父ASIN 级 |
| 订单量 order_items | 领星 同上 | ✅ 已接入 | lx_parent_sales | 父ASIN 级 |
| 销售额 amount | 领星 同上 | ✅ 已接入 | lx_parent_sales | 父ASIN 级，可按 currency_code 转换 |
| 周环比销量 volume_chain_ratio | 领星 同上（返回字段含链环比） | ✅ 已接入 | lx_parent_sales | 链环比字段直接返回 |
| 订单环比 order_chain_ratio | 领星 同上 | ✅ 已接入 | lx_parent_sales | 链环比字段 |
| 销售额环比 amount_chain_ratio | 领星 同上 | ✅ 已接入 | lx_parent_sales | 链环比字段 |
| B2B 销量 b2b_volume | 领星 同上 | ✅ 已接入 | lx_parent_sales | 可选字段 |
| B2B 订单 b2b_order_items | 领星 同上 | ✅ 已接入 | lx_parent_sales | 可选字段 |
| 促销销量 promotion_volume | 领星 同上 | ✅ 已接入 | lx_parent_sales | 可选字段 |
| 促销销售额 promotion_amount | 领星 同上 | ✅ 已接入 | lx_parent_sales | 可选字段 |
| 促销订单 promotion_order_items | 领星 同上 | ✅ 已接入 | lx_parent_sales | 可选字段 |
| 促销折扣 promotion_discount | 领星 同上 | ✅ 已接入 | lx_parent_sales | 可选字段 |
| 日均销量 avg_volume | 领星 同上 | ✅ 已接入 | lx_parent_sales | 可选字段 |
| 达成率 | 领星 同上（计算字段） | ✅ 已接入 | lx_parent_sales | 计算：实际/目标 |
| Sessions 流量 | 领星 同上 | ⚠️ 待确认 | lx_parent_sales | 需确认 asinList 是否返回 sessions 字段（或需调 extend_search 筛选） |
| CVR 转化率 | 计算 | ✅ 已接入 | lx_parent_sales | 计算：orders/sessions |

### 广告报表（lx_parent_ad + lx_campaign_perf，小时级，TTL 30min）

| 监控字段 | 来源 | 接入情况 | 工具名称 | 备注 |
|---|---|---|---|---|
| 广告曝光 impressions | 领星 /pb/openapi/newad/spProductAdReports | ✅ 已接入 | lx_parent_ad | 父ASIN 级 |
| 广告点击 clicks | 领星 同上 | ✅ 已接入 | lx_parent_ad | 父ASIN 级 |
| CTR 点击率 | 计算 | ✅ 已接入 | lx_parent_ad | 计算：clicks/impressions |
| CPC 点击成本 | 领星 同上 | ✅ 已接入 | lx_parent_ad | 返回字段 |
| 广告花费 cost | 领星 同上 | ✅ 已接入 | lx_parent_ad | 父ASIN 级 |
| 广告销售额 sales | 领星 同上 | ✅ 已接入 | lx_parent_ad | 父ASIN 级 |
| 广告订单 orders | 领星 同上 | ✅ 已接入 | lx_parent_ad | 父ASIN 级 |
| 广告销量 units | 领星 同上 | ✅ 已接入 | lx_parent_ad | 父ASIN 级 |
| ACOS | 计算 | ✅ 已接入 | lx_parent_ad | 计算：cost/sales |
| ROAS | 计算 | ✅ 已接入 | lx_parent_ad | 计算：sales/cost |
| ACOAS | 计算 | ✅ 已接入 | lx_parent_ad | 计算：cost/总销售额（需 parent_sales 配合） |
| 活动级 clicks | 领星 /pb/openapi/newad/spCampaignReports | ✅ 已接入 | lx_campaign_perf | 活动级 |
| 活动级 cost | 领星 同上 | ✅ 已接入 | lx_campaign_perf | 活动级 |
| 活动级 sales | 领星 同上 | ✅ 已接入 | lx_campaign_perf | 活动级 |
| 活动级 orders | 领星 同上 | ✅ 已接入 | lx_campaign_perf | 活动级 |
| 活动级 units | 领星 同上 | ✅ 已接入 | lx_campaign_perf | 活动级 |
| targeting_type 投放类型 | 领星 同上 | ✅ 已接入 | lx_campaign_perf | 活动级 |

### 关键词排名（lx_keyword_rank，T+1，TTL 6h）

| 监控字段 | 来源 | 接入情况 | 工具名称 | 备注 |
|---|---|---|---|---|
| 关键词 key_word | 领星 /erp/sc/routing/tool/toolKeywordRank/getKeywordList | ✅ 已接入 | lx_keyword_rank | |
| 关键词自然位排名 rank | 领星 同上 | ✅ 已接入 | lx_keyword_rank | |
| 当前页排名 current_page_rank | 领星 同上 | ✅ 已接入 | lx_keyword_rank | |
| 广告位排名 sbv_page | 领星 同上 | ✅ 已接入 | lx_keyword_rank | SB/SV 广告位 |
| 关联 ASIN asin | 领星 同上 | ✅ 已接入 | lx_keyword_rank | |

### 搜索词流量（lx_keyword_share，T+1，TTL 6h）

| 监控字段 | 来源 | 接入情况 | 工具名称 | 备注 |
|---|---|---|---|---|
| 搜索词 query | 领星 /pb/openapi/newad/queryWordReports | ✅ 已接入 | lx_keyword_share | 用户搜索词 |
| target_id | 领星 同上 | ✅ 已接入 | lx_keyword_share | |
| match_type 匹配方式 | 领星 同上 | ✅ 已接入 | lx_keyword_share | |
| 搜索词 clicks | 领星 同上 | ✅ 已接入 | lx_keyword_share | |
| 搜索词 cost | 领星 同上 | ✅ 已接入 | lx_keyword_share | |
| 搜索词 sales | 领星 同上 | ✅ 已接入 | lx_keyword_share | |
| 搜索词流量占比 | 计算 | ✅ 已接入 | lx_keyword_share | 计算：该词 sales/总 sales |
| 搜索词订单占比 | 计算 | ✅ 已接入 | lx_keyword_share | 计算：该词 orders/总 orders |
| 搜索词 ACOS | 计算 | ✅ 已接入 | lx_keyword_share | 计算：cost/sales |
| target_type 投放类型 | 参数 | ✅ 已接入 | lx_keyword_share | keyword 关键词/target 商品投放 |

### 评论/评分（lx_review_rating，近实时，TTL 0 不缓存）

| 监控字段 | 来源 | 接入情况 | 工具名称 | 备注 |
|---|---|---|---|---|
| 评论 ID review_id | 领星 /basicOpen/openapi/service/v3/data/mws/reviews | ✅ 已接入 | lx_review_rating | |
| 关联 ASIN asin | 领星 同上 | ✅ 已接入 | lx_review_rating | |
| 星级 last_star | 领星 同上 | ✅ 已接入 | lx_review_rating | 最新星级 |
| 评论标题 last_title | 领星 同上 | ✅ 已接入 | lx_review_rating | |
| 评论内容 last_content | 领星 同上 | ✅ 已接入 | lx_review_rating | 差评内容 |
| 评论作者 author | 领星 同上 | ✅ 已接入 | lx_review_rating | |
| 评论数 | 领星 同上（列表长度） | ✅ 已接入 | lx_review_rating | 计算：len(data) |
| 新增差评 | 领星 同上（按日期筛选） | ✅ 已接入 | lx_review_rating | start_date/end_date 筛选 |
| 新增好评 | 领星 同上（按日期筛选） | ✅ 已接入 | lx_review_rating | start_date/end_date 筛选 |

### 库存/可售天数（lx_inventory_days，日级，TTL 1h）

| 监控字段 | 来源 | 接入情况 | 工具名称 | 备注 |
|---|---|---|---|---|
| 在库库存 in_stock | 领星 /basicOpen/openapi/storage/fbaWarehouseDetail | ✅ 已接入 | lx_inventory_days | FBA 仓库库存 |
| 在途库存 in_transit | 领星 同上 | ✅ 已接入 | lx_inventory_days | |
| 日均销量 daily_sales | 领星 /erp/sc/routing/fbaSug/asin/getDailySalesInfoFeature | ✅ 已接入 | lx_inventory_days | 销量预测 |
| 可售天数 available_days | 计算 | ✅ 已接入 | lx_inventory_days | 计算：in_stock/daily_sales（daily_sales=0 时 None） |

---

## 二、未接入字段（设计文档第 4.2 节监控指标）

### Listing 异常（设计文档"链接状态"场景）

| 监控字段 | 来源 | 接入情况 | 工具名称（计划） | 备注 |
|---|---|---|---|---|
| 链接状态（不可售/下架） | 领星 `docs/Sale/Listing`（erp_listing API） | ❌ 未接入 | lx_listing（P1 可加） | API Path 待 fetch 确认 |
| 购物车丢失 | 领星 待确认端点 | ❌ 未接入 | — | 需找 API 文档 |

### 竞品监控（设计文档"竞品抢量"场景，P1）

| 监控字段 | 来源 | 接入情况 | 工具名称（计划） | 备注 |
|---|---|---|---|---|
| 竞品销量 | 领星 `docs/Tools/CompetitiveMonitorList` | ❌ 未接入 | lx_competitor（P1） | 竞品监控列表 |
| 竞品大类 BSR | 领星 同上 | ❌ 未接入 | lx_competitor（P1） | |
| 竞品小类 BSR | 领星 同上 | ❌ 未接入 | lx_competitor（P1） | |
| 竞品价格 | 领星 同上 | ❌ 未接入 | lx_competitor（P1） | |
| 竞品关键词流量占比 | 领星 待找端点 | ❌ 未接入 | lx_competitor_keyword（P2） | 周维度 |

### 退货率（设计文档"退货率异常"场景，P1）

| 监控字段 | 来源 | 接入情况 | 工具名称（计划） | 备注 |
|---|---|---|---|---|
| 退货量 | 领星 `docs/Statistics/MonthRefund`（退款量旧）+ 待找新端点 | ❌ 未接入 | lx_return_rate（P1） | |
| 退货率 | 计算 | ❌ 未接入 | lx_return_rate（P1） | 计算：退货/总销 |
| 退货原因 | 领星 待找端点 | ❌ 未接入 | lx_return_rate（P1） | |

### 库龄/冗余库存（设计文档"冗余库存"场景，P1）

| 监控字段 | 来源 | 接入情况 | 工具名称（计划） | 备注 |
|---|---|---|---|---|
| 库龄 90 天数量 | 领星 待找端点（Warehouse/FBASug 分类） | ❌ 未接入 | lx_inventory_health（P1） | |
| 库龄 180 天数量 | 领星 同上 | ❌ 未接入 | lx_inventory_health（P1） | |
| 库龄 270 天数量 | 领星 同上 | ❌ 未接入 | lx_inventory_health（P1） | 紧急阈值 |
| 库龄 365 天数量 | 领星 同上 | ❌ 未接入 | lx_inventory_health（P1） | |
| 冗余成本 | 领星 同上 | ❌ 未接入 | lx_inventory_health（P1） | |

### 配送成本（设计文档"配送成本"场景，P2）

| 监控字段 | 来源 | 接入情况 | 工具名称（计划） | 备注 |
|---|---|---|---|---|
| FBA 配送费 | 领星 待找端点 | ❌ 未接入 | lx_shipping_fee（P2） | |
| FBA 仓储费 | 领星 `docs/Statistics/FBAStorageFeeMonth` | ❌ 未接入 | lx_shipping_fee（P2） | 月仓储费 |
| FBA 长期仓储费 | 领星 `docs/Statistics/FBAStorageFeeLongTerm` | ❌ 未接入 | lx_shipping_fee（P2） | |

### 毛利（设计文档"毛利异常"场景，v1.1 mcp-bmb）

| 监控字段 | 来源 | 接入情况 | 工具名称（计划） | 备注 |
|---|---|---|---|---|
| 毛利率 | 领星 `docs/Statistics/statisticsOpenParent`（利润统计-父ASIN） | ❌ 未接入 | lx_profit（可替代 mcp-bmb） | **领星 API 已发现**，无需单独 mcp-bmb |
| MSKU 毛利 | 领星 `docs/Statistics/statisticsOpenMSKU` | ❌ 未接入 | lx_profit_msku | |
| ASIN 毛利 | 领星 `docs/Statistics/statisticsOpenASIN` | ❌ 未接入 | lx_profit_asin | |
| 店铺毛利 | 领星 `docs/Statistics/statisticsOpenSeller` | ❌ 未接入 | lx_profit_seller | |

### 热词/搜索热度（设计文档"热词未承接"场景，P1 + Stretch）

| 监控字段 | 来源 | 接入情况 | 工具名称（计划） | 备注 |
|---|---|---|---|---|
| 搜索热度排名 SFR | 领星 待找端点 | ❌ 未接入 | lx_keyword_heat（P1） | |
| 站外热词外溢（如"拿铁味香水"百万搜索） | 卖家精灵/西柚插件 | ❌ 未接入 | plugin_keyword_trend（Stretch） | 需插件 API 或无头浏览器 |
| 关键词全年搜索热度曲线 | 卖家精灵/西柚 | ❌ 未接入 | plugin_keyword_trend（Stretch） | |
| 竞品 ASIN 流量来源占比 | 卖家精灵/西柚 | ❌ 未接入 | plugin_competitor_traffic（Stretch） | |
| 市场容量/集中度/新品占比 | 卖家精灵/西柚 | ❌ 未接入 | plugin_market_insight（Stretch） | |

### MSKU 级广告（P1）

| 监控字段 | 来源 | 接入情况 | 工具名称（计划） | 备注 |
|---|---|---|---|---|
| MSKU 级 ACOS | 领星 spProductAdReports（改 summary_field=msku？） | ❌ 未接入 | lx_msku_ad（P1） | 待确认 summary_field 是否支持 msku |
| MSKU 级 ROAS | 领星 同上 | ❌ 未接入 | lx_msku_ad（P1） | |
| MSKU 级 ACOAS | 领星 同上 | ❌ 未接入 | lx_msku_ad（P1） | |

---

## 三、额外可接入字段（领星 API 已发现但未在设计文档列）

### 小时级数据（精细化监控）

| 监控字段 | 来源 | 接入情况 | 工具名称（计划） | 备注 |
|---|---|---|---|---|
| ASIN 360 小时数据 | 领星 `docs/Statistics/performanceTrendByHour` | ❌ 未接入 | lx_parent_sales_hourly | 小时级销量趋势 |
| SP 广告位小时数据 | 领星 `docs/newAd/report/spAdPlacementHourData` | ❌ 未接入 | lx_parent_ad_hourly | 小时级广告位 |
| SP 广告活动小时数据 | 领星 `docs/newAd/report/spCampaignHourData` | ❌ 未接入 | lx_campaign_perf_hourly | 小时级活动 |

### 广告分析（高级）

| 监控字段 | 来源 | 接入情况 | 工具名称（计划） | 备注 |
|---|---|---|---|---|
| 广告分析-关键词分析 | 领星 `docs/newAd/report/AdAnalyzeKeyword` | ❌ 未接入 | lx_keyword_analyze | |
| 广告分析-搜索词分析 | 领星 `docs/newAd/report/AdAnalyzeSearchTerm` | ❌ 未接入 | lx_search_term_analyze | |
| SB 广告活动报表 | 领星 `docs/newAd/report/hsaCampaignReports` | ❌ 未接入 | lx_sb_campaign | 品牌广告 |
| SD 广告活动报表 | 领星 `docs/newAd/report/sdCampaignReports` | ❌ 未接入 | lx_sd_campaign | 展示广告 |

### 评价统计（Feedback + Review 汇总）

| 监控字段 | 来源 | 接入情况 | 工具名称（计划） | 备注 |
|---|---|---|---|---|
| Review 列表汇总 | 领星 `docs/Service/reviewLists` | ❌ 未接入 | lx_review_summary | 评价统计 |
| Review 每日新增数 | 领星 `docs/Service/reviewDetail` | ❌ 未接入 | lx_review_daily_new | 每日新增差评/好评数 |
| Feedback 4-5 星列表 | 领星 `docs/Service/FeedbackList` | ❌ 未接入 | lx_feedback_positive | |
| Feedback 1-3 星列表 | 领星 `docs/Service/FeedbackListMws` | ❌ 未接入 | lx_feedback_negative | 差评 Feedback |
| Feedback 每日新增数 | 领星 `docs/Service/feedbackDetail` | ❌ 未接入 | lx_feedback_daily_new | |

### 店铺绩效/预警

| 监控字段 | 来源 | 接入情况 | 工具名称（计划） | 备注 |
|---|---|---|---|---|
| 店铺绩效列表 | 领星 `docs/Service/storePerformanceList` | ❌ 未接入 | lx_store_performance | |
| 预警消息-商品 | 领星 `docs/Tools/warningMessageGoodsList` | ❌ 未接入 | lx_warning_goods | |
| 预警消息-库存 | 领星 `docs/Tools/warningMessageInventoryList` | ❌ 未接入 | lx_warning_inventory | |
| 跟卖监控 | 领星 `docs/Tools/query_erp_follow_sale_monitor` | ❌ 未接入 | lx_follow_sale | |

---

## 四、汇总统计

| 字段类别 | 已接入字段数 | 未接入字段数 | 合计 |
|---|---|---|---|
| 销量/产品表现 | 15 | 1（Sessions 待确认） | 16 |
| 广告报表 | 17 | 0 | 17 |
| 关键词排名 | 5 | 0 | 5 |
| 搜索词流量 | 10 | 0 | 10 |
| 评论/评分 | 9 | 0 | 9 |
| 库存/可售天数 | 4 | 0 | 4 |
| Listing 异常 | 0 | 2 | 2 |
| 竞品监控 | 0 | 5 | 5 |
| 退货率 | 0 | 3 | 3 |
| 库龄/冗余 | 0 | 5 | 5 |
| 配送成本 | 0 | 3 | 3 |
| 毛利 | 0 | 4 | 4 |
| 热词/搜索热度 | 0 | 4 | 4 |
| MSKU 级广告 | 0 | 3 | 3 |
| 小时级数据 | 0 | 3 | 3 |
| 广告分析高级 | 0 | 4 | 4 |
| 评价统计汇总 | 0 | 5 | 5 |
| 店铺绩效/预警 | 0 | 4 | 4 |
| **合计** | **60** | **46** | **106** |

**覆盖率**：60/106 = **56.6%**

---

## 五、设计文档第 4.2 节异常场景 × 字段覆盖对照

| 异常场景 | 主判定指标 | 覆盖情况 | 说明 |
|---|---|---|---|
| 销量/达成骤降 | 周环比/同比销量 | ✅ | lx_parent_sales（volume_chain_ratio） |
| 断货风险 | 库存可售天数 | ✅ | lx_inventory_days（available_days） |
| 差评冲击 | 新增差评/评分 | ✅ | lx_review_rating（last_star + 按日期筛选） |
| Listing 异常 | 链接状态 | ❌ | 需 lx_listing（P1） |
| 广告效率恶化 | 父ASIN ACOS | ✅ | lx_parent_ad（ACOS 计算） |
| 关键词排名丢失 | 核心词广告/自然位排名 | ✅ | lx_keyword_rank（rank + sbv_page） |
| 热词未承接 | 搜索热度排名 vs 自然/广告位 | ⚠️ 部分 | lx_keyword_rank 有排名，但搜索热度 SFR 未接入（lx_keyword_heat P1） |
| 竞品抢量 | 竞品销量/价格 | ❌ | 需 lx_competitor（P1） |
| 退货率异常 | 退货率 | ❌ | 需 lx_return_rate（P1） |
| 冗余库存 | 库龄/冗余成本 | ❌ | 需 lx_inventory_health（P1） |
| 配送成本 | 配送费 | ❌ | 需 lx_shipping_fee（P2） |
| 毛利异常 | 毛利率 | ❌ | 需 lx_profit（领星 statisticsOpenParent 可用） |

**异常场景覆盖**：5/12 完全覆盖 + 1 部分 = **6/12（50%）**
