# 领星数据查询 MCP 服务设计文档

> **版本**: v1.0  
> **日期**: 2026-07-30  
> **服务名称**: `lingxing-mcp`  
> **基准文档**: METRIC_AUDIT_25.md（25个叶子指标）+ 领星开放平台API文档

---

## 一、服务架构

### 1.1 整体架构

```
┌─────────────────────────────────────────────────────────┐
│                    AI Agent (调用方)                      │
└─────────────────────────┬───────────────────────────────┘
                          │ MCP Protocol (stdio/SSE)
┌─────────────────────────▼───────────────────────────────┐
│                   lingxing-mcp Server                     │
├─────────────────────────────────────────────────────────┤
│  ┌───────────┐  ┌───────────┐  ┌────────────────────┐   │
│  │ Auth Mgr  │  │ Rate Limit│  │ Response Normalizer│   │
│  │(自动刷新)  │  │ (限流控制) │  │  (统一出参格式)    │   │
│  └───────────┘  └───────────┘  └────────────────────┘   │
├─────────────────────────────────────────────────────────┤
│                    工具层 (18 Tools)                      │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────────┐   │
│  │基础数据层│ │产品数据层│ │广告数据层│ │订单/财务层  │   │
│  │(2 tools)│ │(3 tools)│ │(4 tools)│ │(2 tools)    │   │
│  └─────────┘ └─────────┘ └─────────┘ └─────────────┘   │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────────┐   │
│  │库存数据层│ │关键词层  │ │竞品/退货│ │评论/评分层  │   │
│  │(2 tools)│ │(2 tools)│ │(2 tools)│ │(1 tool)     │   │
│  └─────────┘ └─────────┘ └─────────┘ └─────────────┘   │
├─────────────────────────────────────────────────────────┤
│              领星开放平台 API                              │
│              https://openapi.lingxing.com                 │
└─────────────────────────────────────────────────────────┘
```

### 1.2 认证机制（内部自动管理，不暴露为工具）

| 配置项 | 说明 | 来源 |
|--------|------|------|
| `LINGXING_APP_ID` | 应用ID | 环境变量 |
| `LINGXING_APP_SECRET` | 应用密钥 | 环境变量 |

**认证流程**:
1. 服务启动时调用 `POST /api/auth-server/oauth/access-token` 获取 `access_token`
2. Token 有效期 7199 秒（≈2小时），服务内部在过期前 5 分钟自动刷新
3. 每次 API 请求携带: `access_token`, `app_key`(=AppID), `timestamp`, `sign`(MD5签名)

**签名算法**: 将所有请求参数按 ASCII 排序拼接 + appSecret，取 MD5。

### 1.3 通用约定

| 项目 | 约定 |
|------|------|
| 请求域名 | `https://openapi.lingxing.com` |
| 日期格式 | `yyyy-MM-dd`（如 `2026-07-01`） |
| 分页 | `offset`(起始位置) + `length`(每页条数) |
| 错误码 | `code=0` 成功；非0为失败，`msg` 字段含错误信息 |
| 币种 | 默认 USD，部分接口支持 CNY 转换 |

---

## 二、工具依赖关系（闭环调用链）

```
用户提问: "查看 ASIN B0XXXX 的产品表现"

AI Agent 调用链:
  ① lx_list_stores → 获得 sid (店铺ID)
  ② lx_product_performance(sid, search_value="B0XXXX") → 获得全维度数据

用户提问: "查看关键词 'yoga mat' 的排名"

AI Agent 调用链:
  ① lx_list_stores → 获得 mid (站点/国家ID)
  ② lx_keyword_rank(mid, search_value="yoga mat") → 获得排名数据
  ③ (若返回为空=未监控) lx_add_keyword_monitor(mid, keywords, asins) → 添加监控，次日可查

用户提问: "查看广告活动近30天预算和ACOS"

AI Agent 调用链:
  ① lx_list_stores → 获得 sid
  ② lx_campaign_list(sid) → 获得 campaign_id + daily_budget
  ③ lx_campaign_reports(sid, start_date, end_date) → 服务端内部按天循环聚合，获得 ACOS/ROAS/CVR

用户提问: "查看ASIN的利润和配送费"

AI Agent 调用链:
  ① lx_list_stores → 获得 sid
  ② lx_profit_report_asin(sids=[sid], searchValue=["B0XXXX"]) → 获得利润明细

用户提问: "B0XXXX 昨天有没有新增差评"

AI Agent 调用链:
  ① lx_list_stores → 获得 sids
  ② lx_review_list(sids, star="1,2,3", start_date=昨天, end_date=昨天) → 差评内容/星级/关联订单

用户提问: "查看ASIN近30天的销量走势"

AI Agent 调用链:
  ① lx_list_stores → 获得 sid
  ② lx_sales_trend(sids, date_start, date_end, summary_field_value="B0XXXX") → 每日销量/销售额/BSR
```

---

## 三、工具详细设计（18个工具）

---

### 3.1 基础数据层

---

#### 工具 1: `lx_list_stores`

**功能**: 查询当前账号下所有亚马逊店铺列表。**这是几乎所有工具的前置依赖**，返回的 `sid` 是大部分API的必传参数。

**领星API**: `GET /erp/sc/data/seller/lists`

**入参**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| （无） | — | — | 返回全部店铺，无需参数 |

**出参**:

| 字段 | 类型 | 说明 |
|------|------|------|
| `stores` | array | 店铺列表 |
| `stores[].sid` | int | **店铺ID（核心依赖字段）** |
| `stores[].mid` | int | **站点/国家ID（关键词工具依赖）** |
| `stores[].name` | string | 店铺名称 |
| `stores[].seller_id` | string | 亚马逊卖家ID |
| `stores[].account_name` | string | 账户名称 |
| `stores[].region` | string | 站点区域（NA/EU） |
| `stores[].country` | string | 国家代码（US/UK/DE等） |
| `stores[].marketplace_id` | string | 亚马逊市场ID |
| `stores[].has_ads_setting` | int | 是否授权广告（0=否, 1=是） |
| `stores[].status` | int | 状态（0=停止, 1=正常, 2=异常, 3=欠费） |

**覆盖指标**: 为所有指标提供 `sid` / `mid` 前置查询

---

#### 工具 2: `lx_list_marketplaces`

**功能**: 查询所有亚马逊市场列表。用于了解各站点信息，辅助选择目标市场。

**领星API**: `GET /erp/sc/data/seller/allMarketplace`

**入参**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| （无） | — | — | 返回全部市场 |

**出参**:

| 字段 | 类型 | 说明 |
|------|------|------|
| `marketplaces` | array | 市场列表 |
| `marketplaces[].mid` | int | 市场/国家ID |
| `marketplaces[].name` | string | 市场名称 |
| `marketplaces[].country` | string | 国家代码 |
| `marketplaces[].region` | string | 区域（NA/EU/FE） |
| `marketplaces[].marketplace_id` | string | 亚马逊Marketplace ID |
| `marketplaces[].currency_code` | string | 币种 |

**覆盖指标**: 辅助工具，提供市场维度信息

---

### 3.2 产品数据层

---

#### 工具 3: `lx_product_performance` ⭐（核心工具）

**功能**: 查询产品表现数据（ASIN维度）。**一站式返回销量、广告、库存、利润、流量、退货、评论全维度数据**，是覆盖指标最多的工具。

**领星API**: `POST /bd/productPerformance/openApi/asinList`

**入参**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| `sid` | int[] | ✅ | 店铺ID列表（上限200），从 `lx_list_stores` 获取 |
| `start_date` | string | ✅ | 开始日期 `yyyy-MM-dd` |
| `end_date` | string | ✅ | 结束日期（与开始日期间隔 ≤ 92天） |
| `summary_field` | string | 否 | 汇总维度: `asin`(默认) / `parent_asin` / `msku` / `sku` |
| `search_field` | string | 否 | 搜索字段: `asin` / `parent_asin` / `msku` / `local_sku` / `item_name` |
| `search_value` | string | 否 | 搜索值（配合 search_field 使用） |
| `sort_field` | string | 否 | 排序字段（如 `volume`, `amount`） |
| `sort_order` | string | 否 | 排序方向: `asc` / `desc` |
| `currency_code` | string | 否 | 币种转换: `USD`(默认) / `CNY` |
| `offset` | int | 否 | 分页偏移，默认 0 |
| `length` | int | 否 | 每页条数，默认 20，最大 10000 |

**出参**:

| 字段 | 类型 | 说明 | 覆盖指标# |
|------|------|------|-----------|
| `total` | int | 总记录数 | — |
| `list` | array | 产品数据列表 | — |
| **基础信息** | | | |
| `list[].asin` / `parent_asin` | string | ASIN / 父ASIN | — |
| `list[].item_name` | string | 商品标题 | — |
| `list[].price_list` | array | 价格列表(含msku/price) | — |
| `list[].categories` | array | 分类 | — |
| `list[].brands` | array | 品牌 | — |
| `list[].small_image_url` | string | 缩略图URL | — |
| **销量指标** | | | |
| `list[].volume` | int | 销量 | #1(达成率计算) |
| `list[].order_items` | int | 订单量 | — |
| `list[].amount` | number | 销售额 | #1(达成率计算) |
| `list[].avg_volume` | number | 日均销量 | — |
| `list[].avg_custom_price` | number | 销售均价 | — |
| `list[].volume_chain_ratio` | number | 销量环比 | — |
| `list[].amount_chain_ratio` | number | 销售额环比 | — |
| `list[].order_chain_ratio` | number | 订单量环比 | — |
| **流量指标** | | | |
| `list[].sessions_total` | int | Sessions总量(PC+移动) | **#2 流量** |
| `list[].sessions` | int | PC Sessions | #2 |
| `list[].sessions_mobile` | int | 移动Sessions | #2 |
| `list[].page_views_total` | int | PV总量 | — |
| `list[].buy_box_percentage` | number | Buy Box占比 | — |
| **转化率** | | | |
| `list[].cvr` | number | 点击转化率(CVR) | **#3 点击转化率** |
| `list[].volume_cvr` | number | 销量CVR | — |
| `list[].ad_cvr` | number | 广告CVR | — |
| **广告指标** | | | |
| `list[].acos` | number | ACOS(广告销售额口径) | **#4 广告-acos** |
| `list[].roas` | number | ROAS | **#5 广告-roas** |
| `list[].acoas` | number | ACOAS(净销售额口径) | **#6 广告-acoas** |
| `list[].tacos` | number | TACOS | — |
| `list[].spend` | number | 广告花费 | — |
| `list[].impressions` | int | 展示量 | — |
| `list[].clicks` | int | 点击量 | — |
| `list[].ctr` | number | CTR | — |
| `list[].cpc` | number | CPC | — |
| `list[].cpo` | number | CPO | — |
| `list[].cpm` | number | CPM | — |
| `list[].ad_sales_amount` | number | 广告销售额 | — |
| `list[].ad_order_quantity` | int | 广告订单量 | — |
| `list[].adv_rate` | number | 广告订单占比 | — |
| `list[].ads_sp_cost` | number | SP广告费 | — |
| `list[].shared_ads_sb_cost` | number | SB广告费 | — |
| `list[].ads_sd_cost` | number | SD广告费 | — |
| `list[].net_amount` | number | 净销售额 | — |
| **利润指标** | | | |
| `list[].gross_profit` | number | 结算毛利润 | — |
| `list[].predict_gross_profit` | number | 订单毛利润 | — |
| `list[].gross_margin` | number | 结算毛利率 | — |
| `list[].roi` | number | ROI | — |
| **排名指标** | | | |
| `list[].cate_rank` | int | 大类排名(BSR) | — |
| `list[].prev_cate_rank` | int | 上期大类排名 | — |
| `list[].small_cate_rank` | array | 小类排名 | — |
| `list[].rank_category` | string | 排名分类 | — |
| **库存指标** | | | |
| `list[].afn_fulfillable_quantity` | int | FBA可售库存 | — |
| `list[].afn_inbound_shipped_quantity` | int | FBA在途 | — |
| `list[].afn_inbound_working_quantity` | int | FBA计划入库 | — |
| `list[].afn_inbound_receiving_quantity` | int | FBA入库中 | — |
| `list[].afn_unsellable_quantity` | int | FBA不可售 | — |
| `list[].fbm_quantity` | int | FBM可售 | — |
| `list[].available_days` | int | **可售预估天数** | **#25 库存可售天数** |
| `list[].fbm_available_days` | int | FBM可售天数 | — |
| `list[].month_stock_sales_ratio` | number | 月库销比 | — |
| **评论指标** | | | |
| `list[].reviews_count` | int | 评论数 | — |
| `list[].avg_star` | number | 当前评分 | **#19 评分变化** |
| `list[].prev_star` | number | 上期评分 | **#19 评分变化(对比)** |
| `list[].comment_rate` | number | 留评率 | — |
| **退货指标** | | | |
| `list[].return_count` | int | 退款量 | — |
| `list[].return_rate` | number | 退款率 | — |
| `list[].return_goods_count` | int | 退货量 | **#21 退货率** |
| `list[].return_goods_rate` | number | 退货率 | **#21 退货率** |
| `list[].fba_return_goods_count` | int | FBA退货量 | — |
| `list[].fbm_return_goods_count` | int | FBM退货量 | — |
| `list[].return_amount` | number | 退款金额 | — |
| **B2B指标** | | | |
| `list[].b2b_volume` | int | B2B销量 | — |
| `list[].b2b_amount` | number | B2B销售额 | — |
| **促销指标** | | | |
| `list[].promotion_volume` | int | 促销销量 | — |
| `list[].promotion_amount` | number | 促销销售额 | — |
| `list[].promotion_discount` | number | 促销折扣 | — |
| **环比时间** | | | |
| `chain_start_date` | string | 环比开始时间 | — |
| `chain_end_date` | string | 环比结束时间 | — |

**覆盖指标**: #1(部分), #2, #3, #4, #5, #6, #19, #21, #25（共9个）

---

#### 工具 4: `lx_sales_target`

**功能**: 查询店铺销售额目标及达成情况。用于计算"店铺销售额达成率"。

**领星API**: `POST /bd/goal/management/open/store/batchSelect`

**入参**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| `assessYear` | string | ✅ | 目标年份，如 `"2026"` |

**出参**:

| 字段 | 类型 | 说明 |
|------|------|------|
| `data` | array | 目标列表 |
| `data[].goalName` | string | 目标名称 |
| `data[].sid` | int | 店铺ID |
| `data[].name` | string | 店铺名称 |
| `data[].currencyCode` | string | 币种 |
| `data[].assessYear` | int | 目标年份 |
| `data[].goalAmount1` ~ `goalAmount12` | number | 1~12月目标金额 |
| `data[].realAmount1` ~ `realAmount12` | number | 1~12月实际完成金额 |
| `data[].completeRateAmount1` ~ `completeRateAmount12` | number | 1~12月完成率 |
| `data[].totalGoalAmount` | number | 年度累计目标 |
| `data[].totalRealAmount` | number | 年度累计完成 |
| `data[].totalCompleteRate` | number | 年度累计完成率 |

**覆盖指标**: **#1 店铺销售额达成率**（店铺维度）

**使用建议**: 达成率 = realAmount / goalAmount（API已计算好 `completeRateAmount`，可直接返回）。

**⚠️ 维度限制**: 目标管理API仅支持**店铺维度**（另有组织/人员维度），**无父ASIN/产品维度目标**。指标#1的业务口径为"父ASIN达成率"，如需ASIN级达成率，需用户另行提供目标值，Agent 用 `lx_product_performance` 的 `amount` 自行计算（达成率 = amount / 用户目标）。

**实现注意**: 目标管理系列接口成功码为 `code=1`（而非常规的 `0`），服务端需对该接口做特殊成功码适配。

---

#### 工具 5: `lx_sales_trend`

**功能**: 查询ASIN销量趋势（按小时/按天聚合）。用于回答"近30天每天销量走势""出单时段分布"类问题。`lx_product_performance` 只返回区间**汇总值**，本工具补充**时间序列**维度。

**领星API**: `POST /basicOpen/salesAnalysis/productPerformance/performanceTrendByHour`

**入参**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| `sids` | string | ✅ | 店铺ID，逗号分隔（上限200），从 `lx_list_stores` 获取 |
| `date_start` | string | ✅ | 开始日期 `yyyy-MM-dd` |
| `date_end` | string | ✅ | 结束日期 |
| `summary_field` | string | ✅ | 汇总维度: `asin` / `parent_asin` / `msku` / `sku` / `spu` |
| `summary_field_value` | string | ✅ | 维度值（如具体ASIN） |
| `granularity` | string | 否 | 粒度: `day`(默认，服务端将24个小时段聚合为天) / `hour`(原始小时) |

**出参**:

| 字段 | 类型 | 说明 |
|------|------|------|
| `data` | array | 趋势数据列表 |
| `data[].r_date` | string | 时间段（原始为小时段00-23；granularity=day时为日期） |
| `data[].volume` | int | 销量 |
| `data[].order_items` | int | 订单量 |
| `data[].amount` | number | 销售额 |
| `data[].price` | number | 销售均价 |
| `data[].sales_rank` | int | 大类排名(BSR) |
| `total` | object | 区间汇总值 |

**覆盖指标**: 辅助 #1/#2 的趋势分析；回答"销量走势""出单时段"类问题的闭环工具

**闭环说明**: `lx_list_stores` → 获得 sids → 本工具（sids + summary_field_value=ASIN）。无需再循环调用单日报表接口。

---

### 3.3 广告数据层

---

#### 工具 6: `lx_campaign_reports`

**功能**: 查询SP广告活动报表数据。返回每个广告活动的展示、点击、花费、订单、销售额等效果数据。**入参为日期范围；领星原生仅支持单日 report_date，由服务端内部按天循环调用并聚合**，对Agent透明。

**领星API**: `POST /pb/openapi/newad/spCampaignReports`（按天循环）  
**请求头**: `X-API-VERSION: 2`

**入参**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| `sid` | int | ✅ | 店铺ID，从 `lx_list_stores` 获取 |
| `start_date` | string | ✅ | 开始日期 `yyyy-MM-dd`（单次跨度 ≤ 31天） |
| `end_date` | string | ✅ | 结束日期 |
| `campaign_id` | number | 否 | 活动ID过滤（服务端过滤，聚焦单个活动） |
| `show_detail` | int | 否 | 是否显示明细（0=否, 1=是，返回1d/7d/14d/30d归因字段） |
| `offset` | int | 否 | 分页偏移，默认 0 |
| `length` | int | 否 | 每页条数 |

**出参**:

| 字段 | 类型 | 说明 | 覆盖指标# |
|------|------|------|-----------|
| `data` | array | 活动报表列表 | — |
| `data[].campaign_id` | number | 广告活动ID | — |
| `data[].campaign_name` | string | 活动名称 | — |
| `data[].targeting_type` | string | 投放类型(auto/manual) | — |
| `data[].report_date` | string | 报表日期 | — |
| `data[].profile_id` | number | 广告Profile ID | — |
| `data[].impressions` | int | 展示量 | — |
| `data[].clicks` | int | 点击量 | — |
| `data[].cost` | number | 花费 | — |
| `data[].orders` | int | 订单数(总) | — |
| `data[].sales` | number | 销售额(总) | — |
| `data[].units` | int | 销量(总) | — |
| `data[].same_orders` | int | 直接成交订单 | — |
| `data[].same_sales` | number | 直接成交销售额 | — |
| `data[].orders_1d` ~ `orders_30d` | int | 1/7/14/30天归因订单 | — |
| `data[].sales_1d` ~ `sales_30d` | number | 1/7/14/30天归因销售额 | — |
| **计算字段（服务端计算后返回）** | | | |
| `data[].acos` | number | ACOS = cost / sales | **#8 广告活动-acos** |
| `data[].roas` | number | ROAS = sales / cost | **#9 广告活动-roas** |
| `data[].cvr` | number | CVR = orders / clicks | **#7 广告活动-CVR** |
| `data[].ctr` | number | CTR = clicks / impressions | — |
| `data[].cpc` | number | CPC = cost / clicks | — |

**覆盖指标**: #7, #8, #9

**注意**: ① 此接口**不返回 budget（预算）字段**，预算需通过 `lx_campaign_list` 获取。② 多日聚合逻辑：绝对值（impressions/clicks/cost/orders/sales）直接求和，比率（ACOS/ROAS/CVR/CTR/CPC）由求和后的绝对值重新计算，不做简单平均。

---

#### 工具 7: `lx_campaign_list`

**功能**: 查询SP广告活动列表（管理数据）。返回活动配置信息，**包含每日预算**。

**领星API**: `POST /pb/openapi/newad/spCampaigns`

**入参**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| `sid` | int | ✅ | 店铺ID |
| `state` | string | 否 | 状态过滤: `enabled` / `paused` / `archived` |
| `offset` | int | 否 | 分页偏移，默认 0 |
| `length` | int | 否 | 每页条数，默认 15 |
| `next_token` | string | 否 | 分页游标（大数据量时使用） |

**出参**:

| 字段 | 类型 | 说明 | 覆盖指标# |
|------|------|------|-----------|
| `data` | array | 广告活动列表 | — |
| `data[].campaign_id` | number | 广告活动ID | — |
| `data[].name` | string | 活动名称 | — |
| `data[].campaign_type` | string | 活动类型 | — |
| `data[].targeting_type` | string | 投放类型(auto/manual) | — |
| `data[].state` | string | 状态(enabled/paused/archived) | — |
| `data[].daily_budget` | number | **每日预算** | **#10 广告活动-预算** |
| `data[].bidding` | string | 竞价策略(JSON) | — |
| `data[].start_date` | string | 活动起始日期 | — |
| `data[].end_date` | string | 活动结束日期 | — |
| `data[].portfolio_id` | number | 广告组合ID | — |
| `data[].tags` | array | 标签信息 | — |

**覆盖指标**: **#10 广告活动-预算**

**闭环说明**: 与 `lx_campaign_reports` 通过 `campaign_id` 关联。Agent 先调本工具获取活动列表+预算，再调 `lx_campaign_reports` 获取效果数据，合并后得到"预算+ACOS+ROAS+CVR"完整视图。

---

#### 工具 8: `lx_sp_keyword_reports`

**功能**: 查询SP广告关键词报表。返回每个广告关键词的展示、点击、花费、转化数据。**入参为日期范围，服务端内部按天循环聚合**（同 `lx_campaign_reports`）。

**领星API**: `POST /pb/openapi/newad/spKeywordReports`（按天循环）  
**请求头**: `X-API-VERSION: 2`

**入参**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| `sid` | int | ✅ | 店铺ID |
| `start_date` | string | ✅ | 开始日期 `yyyy-MM-dd`（单次跨度 ≤ 31天） |
| `end_date` | string | ✅ | 结束日期 |
| `show_detail` | int | 否 | 是否显示明细 |
| `offset` | int | 否 | 分页偏移 |
| `length` | int | 否 | 每页条数 |

**出参**:

| 字段 | 类型 | 说明 |
|------|------|------|
| `data` | array | 关键词报表列表 |
| `data[].keyword_id` | number | 关键词ID |
| `data[].keyword_text` | string | 关键词文本 |
| `data[].match_type` | string | 匹配类型(broad/phrase/exact) |
| `data[].campaign_id` | number | 所属活动ID |
| `data[].campaign_name` | string | 所属活动名称 |
| `data[].ad_group_id` | number | 广告组ID |
| `data[].impressions` | int | 展示量 |
| `data[].clicks` | int | 点击量 |
| `data[].cost` | number | 花费 |
| `data[].orders` | int | 订单数 |
| `data[].sales` | number | 销售额 |
| `data[].units` | int | 销量 |

**覆盖指标**: 辅助 #11(关键词-广告位) 的广告关键词数据

---

#### 工具 9: `lx_search_term_reports`

**功能**: 查询SP广告搜索词报表。返回实际用户搜索词及其转化数据，用于分析关键词流量占比。**入参为日期范围，服务端内部按天循环聚合**（同 `lx_campaign_reports`）。

**领星API**: `POST /pb/openapi/newad/queryWordReports`（按天循环）  
**请求头**: `X-API-VERSION: 2`

**入参**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| `sid` | int | ✅ | 店铺ID |
| `target_type` | string | ✅ | 目标类型: `keyword`(关键词) / `target`(商品投放)，领星原生必填 |
| `start_date` | string | ✅ | 开始日期 `yyyy-MM-dd`（单次跨度 ≤ 31天） |
| `end_date` | string | ✅ | 结束日期 |
| `show_detail` | int | 否 | 是否显示明细 |
| `offset` | int | 否 | 分页偏移 |
| `length` | int | 否 | 每页条数 |

**出参**:

| 字段 | 类型 | 说明 | 覆盖指标# |
|------|------|------|-----------|
| `data` | array | 搜索词报表列表 | — |
| `data[].query` | string | 用户搜索词 | — |
| `data[].campaign_id` | number | 活动ID | — |
| `data[].campaign_name` | string | 活动名称 | — |
| `data[].ad_group_id` | number | 广告组ID | — |
| `data[].keyword_id` | number | 匹配的关键词ID | — |
| `data[].keyword_text` | string | 匹配的关键词 | — |
| `data[].match_type` | string | 匹配类型 | — |
| `data[].asin` | string | 关联ASIN | — |
| `data[].impressions` | int | 展示量 | — |
| `data[].clicks` | int | 点击量 | **#13 关键词-流量占比**(计算) |
| `data[].cost` | number | 花费 | — |
| `data[].orders` | int | 订单数 | — |
| `data[].sales` | number | 销售额 | — |
| `data[].units` | int | 销量 | — |

**覆盖指标**: **#13 关键词-流量占比**（某关键词clicks / 总clicks）

---

### 3.4 订单/财务层

---

#### 工具 10: `lx_orders`

**功能**: 查询亚马逊订单列表。支持按时间、状态、配送方式筛选。

**领星API**: `POST /erp/sc/data/mws/orders`

**入参**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| `sid` | int | ✅ | 店铺ID（或 `sid_list` 最大20个） |
| `start_date` | string | ✅ | 开始日期 `yyyy-MM-dd` |
| `end_date` | string | ✅ | 结束日期（跨度 ≤ 1年） |
| `date_type` | int | 否 | 时间类型: 1=订购时间(站点), 2=修改时间(北京), 3=平台更新(UTC), 10=发货时间 |
| `order_status` | string | 否 | 订单状态: `Pending`/`Unshipped`/`PartiallyShipped`/`Shipped`/`Canceled` |
| `fulfillment_channel` | int | 否 | 配送方式: 1=FBA(AFN), 2=FBM(MFN) |
| `offset` | int | 否 | 分页偏移 |
| `length` | int | 否 | 每页条数，最大 5000 |

**出参**:

| 字段 | 类型 | 说明 |
|------|------|------|
| `total` | int | 总记录数 |
| `data` | array | 订单列表 |
| `data[].amazon_order_id` | string | 亚马逊订单号 |
| `data[].order_status` | string | 订单状态 |
| `data[].order_total_amount` | number | 订单总金额 |
| `data[].fulfillment_channel` | string | 配送方式 |
| `data[].purchase_date_local` | string | 下单时间(站点时间) |
| `data[].shipment_date` | string | 发货时间 |
| `data[].is_return` | int | 是否退货 |
| `data[].refund_amount` | number | 退款金额 |
| `data[].item_list` | array | 订单商品明细 |
| `data[].item_list[].asin` | string | ASIN |
| `data[].item_list[].seller_sku` | string | MSKU |
| `data[].item_list[].local_sku` | string | 本地SKU |
| `data[].item_list[].quantity_ordered` | int | 购买数量 |
| `data[].item_list[].item_price` | number | 商品单价 |

**覆盖指标**: 辅助订单维度分析

---

#### 工具 11: `lx_profit_report_asin`

**功能**: 查询ASIN维度利润报表。返回详细的收入、成本、费用、利润明细，**包含FBA配送费**。

**领星API**: `POST /bd/profit/report/open/report/asin/list`

**入参**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| `sids` | int[] | ✅ | 店铺ID列表 |
| `startDate` | string | ✅ | 开始日期 `yyyy-MM-dd`（跨度 ≤ 31天） |
| `endDate` | string | ✅ | 结束日期 |
| `searchField` | string | 否 | 搜索字段: `"asin"` |
| `searchValue` | string[] | 否 | 搜索值列表（ASIN列表） |
| `mids` | int[] | 否 | 国家ID列表 |
| `monthlyQuery` | bool | 否 | 是否按月汇总（默认false=按天） |
| `currencyCode` | string | 否 | 币种: `CNY` / `USD` |
| `orderStatus` | string | 否 | 订单状态: `Disbursed`/`Deferred`/`All` |
| `offset` | int | 否 | 分页偏移 |
| `length` | int | 否 | 每页条数 |

**出参**:

| 字段 | 类型 | 说明 | 覆盖指标# |
|------|------|------|-----------|
| `data` | array | 利润数据列表 | — |
| `data[].asin` | string | ASIN | — |
| `data[].parentAsin` | string | 父ASIN | — |
| `data[].sellerSku` | string | MSKU | — |
| **销量/销售额** | | | |
| `data[].totalSalesQuantity` | int | 总销量 | — |
| `data[].fbaSalesQuantity` | int | FBA销量 | — |
| `data[].fbmSalesQuantity` | int | FBM销量 | — |
| `data[].totalSalesAmount` | number | 总销售额 | — |
| `data[].fbaSaleAmount` | number | FBA销售额 | — |
| `data[].fbmSaleAmount` | number | FBM销售额 | — |
| **广告费** | | | |
| `data[].totalAdsCost` | number | 广告总花费 | — |
| `data[].adsSpCost` | number | SP广告费 | — |
| `data[].adsSbCost` | number | SB广告费 | — |
| `data[].adsSdCost` | number | SD广告费 | — |
| `data[].totalAdsSales` | number | 广告总销售额 | — |
| **费用明细** | | | |
| `data[].fbaDeliveryFee` | number | **FBA配送费** | **#22 配送费** |
| `data[].totalStorageFee` | number | 仓储费总计 | — |
| `data[].fbaStorageFee` | number | FBA月仓储费 | — |
| `data[].longTermStorageFee` | number | 长期仓储费 | — |
| `data[].sellingFeeRefunds` | number | 销售佣金 | — |
| **退款/退货** | | | |
| `data[].totalSalesRefunds` | number | 退款金额 | — |
| `data[].refundsQuantity` | int | 退款数量 | — |
| `data[].refundsRate` | number | 退款率 | — |
| `data[].fbaReturnsQuantity` | int | FBA退货量 | — |
| `data[].fbaReturnsQuantityRate` | number | FBA退货率 | — |
| **赔偿** | | | |
| `data[].reimbursements` | number | 赔偿金额 | — |
| `data[].fbaInventoryCredit` | number | FBA库存赔偿 | — |
| **利润** | | | |
| `data[].grossProfit` | number | 毛利润 | — |
| `data[].grossMargin` | number | 毛利率 | — |

**覆盖指标**: **#22 配送费**（`fbaDeliveryFee`字段）

---

### 3.5 库存数据层

---

#### 工具 12: `lx_fba_inventory`

**功能**: 查询FBA库存列表。**包含库龄分布数据**，用于计算库存冗余成本和数量。

**领星API**: `POST /erp/sc/routing/fba/fbaStock/fbaList`

**入参**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| `sid` | string | ✅ | 店铺ID（逗号分隔支持多个） |
| `search_field` | string | 否 | 搜索字段: `asin` / `msku` / `fnsku` / `sku` |
| `search_value` | string | 否 | 搜索值 |
| `offset` | int | 否 | 分页偏移 |
| `length` | int | 否 | 每页条数 |

**出参**:

| 字段 | 类型 | 说明 | 覆盖指标# |
|------|------|------|-----------|
| `data` | array | 库存列表 | — |
| `data[].asin` | string | ASIN | — |
| `data[].msku` | string | MSKU | — |
| `data[].fnsku` | string | FNSKU | — |
| `data[].sku` | string | 本地SKU | — |
| `data[].product_name` | string | 商品名称 | — |
| `data[].sid` | int | 店铺ID | — |
| **库存数量** | | | |
| `data[].afn_fulfillable_quantity` | int | FBA可售库存 | — |
| `data[].afn_unsellable_quantity` | int | 不可售库存 | — |
| `data[].reserved_fc_transfers` | int | 待调仓 | — |
| `data[].reserved_fc_processing` | int | 调仓中 | — |
| `data[].reserved_customerorders` | int | 待发货(已下单) | — |
| `data[].afn_inbound_working_quantity` | int | 计划入库 | — |
| `data[].afn_inbound_shipped_quantity` | int | 在途库存 | — |
| `data[].afn_inbound_receiving_quantity` | int | 入库中 | — |
| **库龄分布（冗余核心数据）** | | | |
| `data[].inv_age_0_to_30_days` | int | 0-30天库存量 | — |
| `data[].inv_age_31_to_60_days` | int | 31-60天库存量 | — |
| `data[].inv_age_61_to_90_days` | int | 61-90天库存量 | **#23/24 冗余(90天)** |
| `data[].inv_age_91_to_180_days` | int | 91-180天库存量 | **#23/24 冗余(180天)** |
| `data[].inv_age_181_to_270_days` | int | 181-270天库存量 | **#23/24 冗余(271天)** |
| `data[].inv_age_271_to_365_days` | int | 271-365天库存量 | **#23/24 冗余(365天)** |
| `data[].inv_age_365_plus_days` | int | 365天以上库存量 | **#23/24 冗余(365+)** |
| **成本** | | | |
| `data[].cost` | number | 单位库存成本 | **#23 冗余成本(计算)** |
| `data[].stock_cost_total` | number | 库存总货值 | — |

**覆盖指标**: **#23 库存冗余成本**, **#24 库存冗余数量**

**冗余计算逻辑**:
- 冗余数量 = `inv_age_91_to_180_days` + `inv_age_181_to_270_days` + `inv_age_271_to_365_days` + `inv_age_365_plus_days`（按业务定义的冗余阈值）
- 冗余成本 = 冗余数量 × `cost`（单位成本）
- 支持 90/180/271/365 天多阈值筛选

---

#### 工具 13: `lx_storage_fee`

**功能**: 查询FBA仓储费（月仓储费 + 长期仓储费）。

**领星API**: 
- 月仓储费: `POST /erp/sc/data/fba_report/storageFeeMonth`
- 长期仓储费: `POST /erp/sc/data/fba_report/storageFeeLongTerm`

**入参**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| `sid` | int | ✅ | 店铺ID |
| `fee_type` | string | ✅ | 费用类型: `monthly`(月仓储费) / `long_term`(长期仓储费) |
| `month` | string | 条件必填 | 收费月份 `yyyy-MM`（fee_type=monthly时必填） |
| `start_date` | string | 条件必填 | 开始日期（fee_type=long_term时必填） |
| `end_date` | string | 条件必填 | 结束日期（fee_type=long_term时必填） |
| `offset` | int | 否 | 分页偏移 |
| `length` | int | 否 | 每页条数，默认 1000 |

**出参（月仓储费 fee_type=monthly）**:

| 字段 | 类型 | 说明 |
|------|------|------|
| `data` | array | 仓储费列表 |
| `data[].asin` | string | ASIN |
| `data[].fnsku` | string | FNSKU |
| `data[].product_name` | string | 商品名称 |
| `data[].fulfillment_center` | string | 仓库编号 |
| `data[].estimated_monthly_storage_fee` | number | 预估月仓储费 |
| `data[].storage_rate` | string | 收费标准 |
| `data[].average_quantity_on_hand` | int | 平均库存量 |
| `data[].item_volume` | number | 商品体积 |
| `data[].product_size_tier` | string | 产品尺寸分级 |
| `data[].month_of_charge` | string | 收费月份 |
| `data[].currency` | string | 币种 |

**出参（长期仓储费 fee_type=long_term）**:

| 字段 | 类型 | 说明 |
|------|------|------|
| `data` | array | 长期仓储费列表 |
| `data[].asin` | string | ASIN |
| `data[].fnsku` | string | FNSKU |
| `data[].6_mo_long_terms_storage_fee` | number | 6-12个月长期仓储费 |
| `data[].12_mo_long_terms_storage_fee` | number | 12个月以上长期仓储费 |
| `data[].qty_charged_6_mo_long_term_storage_fee` | int | 6-12月收费商品量 |
| `data[].qty_charged_12_mo_long_term_storage_fee` | int | 12月以上收费商品量 |
| `data[].snapshot_date` | string | 快照日期 |
| `data[].per_unit_volume` | number | 单件体积 |
| `data[].currency` | string | 币种 |

**覆盖指标**: 辅助 #23(库存冗余成本) 的仓储费维度

---

### 3.6 关键词层

---

#### 工具 14: `lx_keyword_rank`

**功能**: 查询关键词排名追踪数据。返回指定关键词在亚马逊搜索结果中的自然排名和广告排名。

**领星API**: `POST /erp/sc/routing/tool/toolKeywordRank/getKeywordList`

**入参**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| `mid` | int | 否 | 国家/市场ID（从 `lx_list_stores` 获取；不传查全部站点） |
| `start_date` | string | 否 | 开始日期 `yyyy-MM-dd` |
| `end_date` | string | 否 | 结束日期 |
| `search_field` | string | 否 | 搜索字段: `key_word` / `asin` |
| `search_value` | string | 否 | 搜索值 |
| `offset` | int | ✅ | 分页偏移 |
| `length` | int | ✅ | 每页条数，最大 2000 |

**出参**:

| 字段 | 类型 | 说明 | 覆盖指标# |
|------|------|------|-----------|
| `data` | array | 关键词排名列表 | — |
| `data[].key_word` | string | 关键词 | — |
| `data[].asin` | string | 监控的ASIN | — |
| `data[].parent_asin` | string | 父ASIN | — |
| `data[].title` | string | 商品标题 | — |
| `data[].rank` | int | **综合排名位置** | **#11/#12** |
| `data[].page` | int | 所在页码 | — |
| `data[].current_page_rank` | int | 当前页内排名 | — |
| `data[].is_sponsored` | int | **0=自然位, 1=广告位** | **#11 广告位 / #12 自然位** |
| `data[].sbv_page` | int | SBV视频排名页 | — |
| `data[].type` | int | 1=PC端, 2=移动端 | — |
| `data[].country` | string | 国家 | — |
| `data[].monitor_time` | string | 监控时间 | — |

**覆盖指标**: **#11 关键词-广告位**, **#12 关键词-自然位**

**闭环说明**: `mid` 从 `lx_list_stores` 获取。`is_sponsored=1` 为广告位排名，`is_sponsored=0` 为自然位排名。**⚠️ 本工具仅返回"已在监控中"的关键词**——若查询返回为空，说明该词未加入监控，需先通过 `lx_add_keyword_monitor` 添加（次日开始有数据），Agent 应主动向用户说明并完成闭环。

**⚠️ 口径说明**: 业务口径来源为"卖家精灵插件→反查流量词"，本工具使用领星API替代。数据维度相似但可能存在差异。

---

#### 工具 15: `lx_add_keyword_monitor` ⚠️（写操作/Beta）

**功能**: 添加关键词排名监控（ASIN维度）。**闭环关键**：`lx_keyword_rank` 只能查询"已在监控中"的关键词；当用户查询的关键词未监控时，Agent 调用本工具添加监控，之后即可正常查询排名。

**领星API**: `POST /basicOpen/tool/keywordRanking/add`

**入参**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| `mid` | int | ✅ | 国家/市场ID（从 `lx_list_stores` 获取） |
| `keywords` | string[] | ✅ | 关键词列表 |
| `asins` | string[] | ✅ | 监控的ASIN列表 |
| `types` | int[] | ✅ | 监控范围: 1=PC端, 2=移动端 |
| `is_sponsors` | int[] | ✅ | 是否监控广告位: 0=否, 1=是 |
| `postcodes` | string[] | 否 | 邮编（不传用默认邮编） |

**出参**:

| 字段 | 类型 | 说明 |
|------|------|------|
| `success` | bool | 是否添加成功 |
| `message` | string | 结果说明 |

**覆盖指标**: 为 #11/#12 提供前置闭环

**⚠️ 重要限制**:
- 此API为**隐藏文档**（未在官方侧边栏公开发布），接口存在变动风险，标记为 **Beta**
- 新添加的监控**从添加日开始采集**，无历史排名数据；通常**次日**才可通过 `lx_keyword_rank` 查到数据
- 写操作：Agent 调用前应先调 `lx_keyword_rank` 查重，并向用户确认后再执行

---

### 3.7 竞品监控层

---

#### 工具 16: `lx_competitor_monitor`

**功能**: 查询竞品监控数据。返回竞品的排名、价格、评分等追踪数据。

**领星API**: `POST /basicOpen/tool/competitiveMonitor/list`

**入参**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| `search_field` | string | 否 | 搜索字段: `asin` |
| `search_value` | string | 否 | 搜索值（ASIN，多个逗号分隔，上限200） |
| `levels` | int[] | 否 | 竞品等级: 1=A, 2=B, 3=C, 4=D |
| `update_time_start` | string | 否 | 更新开始时间 `yyyy-MM-dd` |
| `update_time_end` | string | 否 | 更新结束时间 |
| `offset` | int | 否 | 分页偏移 |
| `length` | int | 否 | 每页条数，默认20，最大200 |

**出参**:

| 字段 | 类型 | 说明 | 覆盖指标# |
|------|------|------|-----------|
| `data` | array | 竞品列表 | — |
| `data[].asin` | string | 竞品ASIN | — |
| `data[].title` | string | 商品标题 | — |
| `data[].big_category_rank` | string | **大类排名(BSR)** | **#16 竞品-排名** |
| `data[].big_category` | string | 大类名称 | — |
| `data[].small_ranks` | array | **小类排名列表** | **#16 竞品-排名** |
| `data[].price` | string | **当前价格** | **#17 竞品-价格** |
| `data[].buybox_price` | string | Buy Box价格 | #17 |
| `data[].avg_price` | string | 平均价格 | #17 |
| `data[].star` | string | 评分 | — |
| `data[].review_num` | string | Review数量 | — |
| `data[].fba_seller_num` | int | FBA卖家数 | — |
| `data[].fbm_seller_num` | int | FBM卖家数 | — |
| `data[].monitor_status` | int | 监控状态(0=暂停, 1=监控中) | — |
| `data[].level_name` | string | 竞品等级名称 | — |

**覆盖指标**: **#16 竞品监控-排名**, **#17 竞品监控-价格**

**⚠️ 限制**: 
- 此API**不直接返回销量字段**（#15 竞品-销量 需通过其他方式获取）
- #18 竞品-关键词流量占比 需额外数据源

---

### 3.8 退货分析层

---

#### 工具 17: `lx_return_analysis`

**功能**: 查询退货分析数据。支持按ASIN/MSKU/父ASIN维度查看退货率及环比变化。

**领星API**: `POST /basicOpen/salesAnalysis/returnOrder/analysisLists`

**入参**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| `startDate` | string | ✅ | 开始日期 `yyyy-MM-dd` |
| `endDate` | string | ✅ | 结束日期（跨度 ≤ 366天） |
| `asinType` | string | ✅ | 维度: `asin` / `msku` / `parentAsin` / `sku` / `spu` |
| `dateType` | int | ✅ | 时间类型: 0=退货时间, 1=下单时间 |
| `storeId` | int[] | 否 | 店铺ID列表 |
| `mids` | int[] | 否 | 国家ID列表 |
| `searchField` | string | 否 | 搜索字段: `msku` / `asin` / `parentAsin` / `localSku` / `localName` / `spu` |
| `searchValue` | string[] | 否 | 搜索值（数组，支持多个） |
| `sortField` | string | 否 | 排序字段 |
| `offset` | int | ✅ | 分页偏移 |
| `length` | int | ✅ | 每页条数 |

**出参**:

| 字段 | 类型 | 说明 | 覆盖指标# |
|------|------|------|-----------|
| `data.records` | array | 退货数据列表 | — |
| `data.records[].asin` | string | ASIN | — |
| `data.records[].curReturnGoodsCount` | int | **当期退货量** | **#21 退货率** |
| `data.records[].curReturnGoodsVolumeRatio` | string | **当期退货率** | **#21 退货率** |
| `data.records[].curVolume` | int | 当期销量 | — |
| `data.records[].preReturnGoodsCount` | int | 上期退货量 | — |
| `data.records[].preReturnGoodsVolumeRatio` | string | 上期退货率 | — |
| `data.records[].returnGoodsCountRatio` | string | 退货量环比 | — |
| `data.records[].returnGoodsVolumeRatioDiff` | string | 退货率环比差异 | — |
| `data.records[].curReturnGoodsCountDistribution` | object | FBA/FBM退货分布 | — |

**覆盖指标**: **#21 退货率**（含环比对比）

**说明**: 虽然 `lx_product_performance` 也返回 `return_goods_rate`，但本工具提供更详细的退货分析维度（环比、FBA/FBM分布、按退货时间/下单时间切换）。

---

### 3.9 评论/评分层

---

#### 工具 18: `lx_review_list`

**功能**: 查询Review明细列表。**支持按星级筛选**，可直接拉取指定日期内的低星差评（含评论内容/图片/视频/关联订单），是 #20 新增差评的完整闭环工具。

**领星API**: `POST /basicOpen/openapi/service/v3/data/mws/reviews`

**入参**:

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| `sids` | string | 否 | 店铺ID，逗号分隔（从 `lx_list_stores` 获取） |
| `mids` | string | 否 | 国家ID，逗号分隔 |
| `start_date` | string | ✅ | 开始日期 `yyyy-MM-dd` |
| `end_date` | string | ✅ | 结束日期 |
| `date_field` | string | ✅ | 时间口径: `review_time`(评价时间) / `create_time` / `last_update_time` |
| `star` | string | 否 | **星级筛选**，如 `"1,2,3"` 拉取差评 |
| `search_field` | string | 否 | 搜索字段: `asin` / `parent_asin` / `amazon_order_id` / `author` / `review_id` / `last_title` / `buyer_email` |
| `search_value` | string | 否 | 搜索值 |
| `status` | int | 否 | 处理状态: 0=待处理, 1=处理中, 2=已完成 |
| `sort_field` / `sort_type` | string | 否 | 排序字段 / 排序方向 |
| `offset` | int | 否 | 分页偏移 |
| `length` | int | 否 | 每页条数，最大 200 |

**出参**:

| 字段 | 类型 | 说明 | 覆盖指标# |
|------|------|------|-----------|
| `data` | array | Review列表 | — |
| `data[].asin` | string | ASIN | — |
| `data[].last_star` | int | **评论星级(1-5)** | **#19/#20** |
| `data[].last_title` | string | 评论标题 | #20 |
| `data[].last_content` | string | **评论内容** | **#20 新增差评** |
| `data[].review_date` | string | 评价时间 | #20 |
| `data[].review_id` / `review_url` | string | 评论ID / 链接 | — |
| `data[].author` | string | 评论客户 | — |
| `data[].is_vp` | bool | 是否VP评论 | — |
| `data[].review_likes` | int | 点赞数 | — |
| `data[].images` / `videos` | array | 评论图片/视频 | — |
| `data[].amazon_order_list` | array | 关联订单(订单号/买家邮箱) | — |
| `data[].seller_sku` / `parent_asin` | array | MSKU / 父ASIN | — |
| `data[].item_name` | array | 商品标题 | — |
| `data[].marketplace` | string | 站点 | — |
| `data[].status` | int | 处理状态 | — |
| `total` | int | 总记录数 | — |

**覆盖指标**: **#20 新增差评**（直接返回差评内容）, 辅助 **#19 评分变化**

**闭环说明**: 查询"昨天新增了哪些差评"：`lx_list_stores` → sids → 本工具(`star="1,2,3"`, 起止日期=昨天)。

**补充**: 
- #19 评分变化的快速对比用 `lx_product_performance` 的 `avg_star` + `prev_star` 即可
- 如需ASIN级**星级分布**（各星级新增数/差评率），可扩展接入 `GET /erp/sc/v2/cs/reviewReport/lists`（见 Stretch Goals）

---

## 四、25个指标覆盖矩阵

| # | 指标名 | 工具 | 关键字段 | 状态 |
|---|--------|------|----------|------|
| 1 | 店铺销售额达成率 | `lx_sales_target` + `lx_product_performance` | completeRateAmount / amount | ⚠️ 部分覆盖（店铺级✅ / 父ASIN级需用户提供目标） |
| 2 | 流量 | `lx_product_performance` | sessions_total | ✅ 完全覆盖 |
| 3 | 点击转化率 | `lx_product_performance` | cvr | ✅ 完全覆盖 |
| 4 | 广告-acos | `lx_product_performance` | acos | ✅ 完全覆盖 |
| 5 | 广告-roas | `lx_product_performance` | roas | ✅ 完全覆盖 |
| 6 | 广告-acoas | `lx_product_performance` | acoas | ✅ 完全覆盖 |
| 7 | 广告活动-CVR | `lx_campaign_reports` | orders/clicks (计算) | ✅ 完全覆盖 |
| 8 | 广告活动-acos | `lx_campaign_reports` | cost/sales (计算) | ✅ 完全覆盖 |
| 9 | 广告活动-roas | `lx_campaign_reports` | sales/cost (计算) | ✅ 完全覆盖 |
| 10 | 广告活动-预算 | `lx_campaign_list` | daily_budget | ✅ 完全覆盖 |
| 11 | 关键词-广告位 | `lx_keyword_rank` | rank + is_sponsored=1 | ⚠️ 领星替代卖家精灵 |
| 12 | 关键词-自然位 | `lx_keyword_rank` | rank + is_sponsored=0 | ⚠️ 领星替代卖家精灵 |
| 13 | 关键词-流量占比 | `lx_search_term_reports` | clicks占比 (计算) | ⚠️ 领星替代卖家精灵 |
| 14 | 关键词-搜索热度排名 | — | — | ❌ 领星无SFR端点 |
| 15 | 竞品监控-销量 | `lx_competitor_monitor` | ⚠️ API不返回销量 | ⚠️ 部分覆盖 |
| 16 | 竞品监控-排名 | `lx_competitor_monitor` | big_category_rank + small_ranks | ✅ 完全覆盖 |
| 17 | 竞品监控-价格 | `lx_competitor_monitor` | price + buybox_price + avg_price | ✅ 完全覆盖 |
| 18 | 竞品-关键词流量占比 | — | — | ❌ 需额外数据源 |
| 19 | 评分变化 | `lx_product_performance` / `lx_review_list` | avg_star + prev_star / last_star | ✅ 完全覆盖 |
| 20 | 新增差评 | `lx_review_list` | star=1,2,3 筛选 + last_content + review_date | ✅ 完全覆盖 |
| 21 | 退货率 | `lx_return_analysis` / `lx_product_performance` | curReturnGoodsVolumeRatio / return_goods_rate | ✅ 完全覆盖 |
| 22 | 配送费 | `lx_profit_report_asin` | fbaDeliveryFee | ✅ 完全覆盖 |
| 23 | 库存冗余成本 | `lx_fba_inventory` | inv_age_*_days × cost (计算) | ✅ 完全覆盖 |
| 24 | 库存冗余数量 | `lx_fba_inventory` | inv_age_91+ 各段求和 | ✅ 完全覆盖 |
| 25 | 库存可售天数 | `lx_product_performance` | available_days | ✅ 完全覆盖 |

**覆盖率**: 18/25 完全覆盖(72%) + 5/25 部分覆盖(20%) + 2/25 无法覆盖(8%)

---

## 五、无法覆盖指标 & 闭环限制说明

### 5.1 无法覆盖的指标

| # | 指标 | 原因 | 替代方案 |
|---|------|------|----------|
| 14 | 关键词-搜索热度排名 | 领星无SFR(Search Frequency Rank)端点，业务口径来源为卖家精灵 | **Stretch**: 做 mcp-plugin 对接卖家精灵API/爬虫 |
| 18 | 竞品-关键词流量占比 | 领星竞品监控不含关键词流量维度 | **Stretch**: 卖家精灵"反查流量词"功能 |

### 5.2 部分覆盖的指标

| # | 指标 | 限制 | 处理方式 |
|---|------|------|----------|
| 1 | 店铺销售额达成率 | 目标管理API仅支持**店铺/组织维度**，无父ASIN维度目标 | 店铺级达成率直接返回✅；父ASIN级需用户提供目标值，Agent用 `lx_product_performance` 的 `amount` 计算 |
| 11/12/13 | 关键词三指标 | 业务口径来源为卖家精灵，领星为替代数据源 | 已用领星实现，口径差异需业务确认 |
| 15 | 竞品监控-销量 | 竞品监控API不返回销量字段 | 通过 BSR 排名变化趋势间接推断；或等领星后续开放 |

### 5.3 闭环限制（设计已内置处理）

| 限制 | 影响工具 | 处理方式 |
|------|----------|----------|
| 关键词排名为**监控制**（未监控的词查不到） | `lx_keyword_rank` | ✅ 已提供 `lx_add_keyword_monitor` 添加监控（Beta）；新词次日有数据 |
| 竞品为**监控制**，且领星**无添加竞品API** | `lx_competitor_monitor` | ⚠️ 竞品需先在**领星ERP网页端**（工具→竞品监控）添加；Agent查询为空时应主动提示用户 |
| 广告报表原生仅支持**单日** report_date | `lx_campaign_reports` / `lx_sp_keyword_reports` / `lx_search_term_reports` | ✅ 工具入参为日期范围，服务端内部按天循环+聚合（单次≤31天），Agent无感知 |
| 订单接口无ASIN筛选参数 | `lx_orders` | Agent拉取后按 `item_list[].asin` 过滤 |
| 仓储费接口无ASIN筛选参数 | `lx_storage_fee` | Agent拉取后按 `asin` 过滤 |
| 目标管理API成功码为 `code=1`（非0） | `lx_sales_target` | 服务端对该接口做特殊成功码适配 |

---

## 六、工具调用闭环流程图

### 场景1: 查询某ASIN的完整产品表现

```
用户: "帮我看看 B0XXXXXXXX 这个产品最近30天的表现"

Agent 调用:
  1. lx_list_stores() 
     → 获得 sid=12345, mid=1, country="US"
  
  2. lx_product_performance(
       sid=[12345], 
       start_date="2026-06-30", 
       end_date="2026-07-30",
       search_field="asin",
       search_value="B0XXXXXXXX",
       summary_field="asin"
     )
     → 获得: 销量、销售额、流量、CVR、ACOS、ROAS、库存、评分、退货率...
```

### 场景2: 查询广告活动预算+效果

```
用户: "看看我US店铺所有广告活动的预算和ACOS"

Agent 调用:
  1. lx_list_stores() 
     → 筛选 country="US" → sid=12345
  
  2. lx_campaign_list(sid=12345, state="enabled")
     → 获得: campaign_id, name, daily_budget
  
  3. lx_campaign_reports(sid=12345, start_date="2026-07-01", end_date="2026-07-30")
     → 服务端按天循环+聚合
     → 获得: campaign_id, impressions, clicks, cost, orders, sales
     → 计算: ACOS, ROAS, CVR
  
  4. Agent 合并 step2 + step3 数据（通过 campaign_id 关联）
     → 输出: 活动名 | 预算 | ACOS | ROAS | CVR
```

### 场景3: 查询关键词排名

```
用户: "查看 'yoga mat' 这个关键词在美国站的排名"

Agent 调用:
  1. lx_list_stores()
     → 筛选 country="US" → mid=1
  
  2. lx_keyword_rank(
       mid=1,
       start_date="2026-07-23",
       end_date="2026-07-30",
       search_field="key_word",
       search_value="yoga mat"
     )
     → 获得: rank, page, is_sponsored(区分广告位/自然位)
```

### 场景4: 库存冗余分析

```
用户: "看看哪些ASIN有库存冗余风险"

Agent 调用:
  1. lx_list_stores()
     → sid=12345
  
  2. lx_fba_inventory(sid="12345")
     → 获得: 各ASIN的库龄分布 + 单位成本
     → 计算: 冗余数量(91天+) + 冗余成本(冗余数量×cost)
  
  3. (可选) lx_storage_fee(sid=12345, fee_type="long_term", ...)
     → 获得: 长期仓储费明细
```

### 场景5: 达成率分析

```
用户: "今年US店铺的销售目标达成了多少？"

Agent 调用:
  1. lx_list_stores()
     → 筛选 country="US" → sid=12345
  
  2. lx_sales_target(assessYear="2026")
     → 获得: goalAmount(月目标), realAmount(月实际), completeRateAmount(完成率)
```

### 场景6: 新增差评追踪

```
用户: "B0XXXXXXXX 昨天有没有新增差评？"

Agent 调用:
  1. lx_list_stores()
     → 获得 sids="12345"
  
  2. lx_review_list(
       sids="12345",
       start_date="2026-07-29",
       end_date="2026-07-29",
       date_field="review_time",
       star="1,2,3",
       search_field="asin",
       search_value="B0XXXXXXXX"
     )
     → 获得: 差评列表(星级/标题/内容/评价时间/关联订单号)
```

### 场景7: 关键词未监控时的闭环

```
用户: "看看 'yoga mat' 这个词我们ASIN排第几"

Agent 调用:
  1. lx_list_stores() → mid=1
  
  2. lx_keyword_rank(mid=1, search_field="key_word", search_value="yoga mat")
     → 返回为空（该词未加入监控）
  
  3. Agent 提示用户: "该关键词未加入监控，是否添加？"
     用户确认后 →
  
  4. lx_add_keyword_monitor(
       mid=1, keywords=["yoga mat"], asins=["B0XXXXXXXX"],
       types=[1,2], is_sponsors=[0,1]
     )
     → 添加成功
  
  5. Agent 告知: "已加入监控，明日起可查询排名数据"
```

### 场景8: 销量趋势分析

```
用户: "B0XXXXXXXX 最近30天销量走势怎么样？"

Agent 调用:
  1. lx_list_stores() → sid=12345
  
  2. lx_sales_trend(
       sids="12345",
       date_start="2026-06-30",
       date_end="2026-07-30",
       summary_field="asin",
       summary_field_value="B0XXXXXXXX",
       granularity="day"
     )
     → 获得: 每日 volume/amount/order_items/sales_rank 序列
```

---

## 七、技术实现要点

### 7.1 服务端配置

```env
# .env
LINGXING_APP_ID=your_app_id
LINGXING_APP_SECRET=your_app_secret
LINGXING_BASE_URL=https://openapi.lingxing.com
```

### 7.2 错误处理

| 错误场景 | 处理方式 |
|----------|----------|
| Token过期 | 自动刷新，透明重试 |
| 频率限制(429) | 指数退避重试（最多3次） |
| 参数错误(400) | 返回明确错误信息+参数说明 |
| 无数据 | 返回空数组 + 提示可能原因 |
| 日期超限 | 提示最大跨度限制 |

### 7.3 分页策略

对于大数据量接口，MCP工具内部自动处理分页：
- `lx_product_performance`: 单次最大10000条，通常够用
- `lx_orders`: 单次最大5000条
- 广告报表系列(`lx_campaign_reports` / `lx_sp_keyword_reports` / `lx_search_term_reports`): 领星原生仅支持单日 `report_date`，工具内部按天循环并聚合（单次跨度≤31天）
- 若数据超过单页，工具返回 `has_more=true` + `next_offset`，Agent可决定是否继续拉取

### 7.4 数据缓存（可选优化）

| 数据 | 缓存时间 | 原因 |
|------|----------|------|
| 店铺列表 | 24小时 | 极少变化 |
| 市场列表 | 7天 | 几乎不变 |
| 广告活动列表 | 1小时 | 预算可能调整 |
| 产品表现 | 不缓存 | 实时性要求高 |

### 7.5 写操作安全

本服务仅 `lx_add_keyword_monitor` 一个写操作工具：
- Agent 调用前应向用户确认
- 调用前先调 `lx_keyword_rank` 查重（已监控的词不重复添加）
- 该API为 Beta 状态，调用失败时降级提示用户到领星ERP网页端手动添加

---

## 八、工具优先级排序

| 优先级 | 工具 | 理由 |
|--------|------|------|
| P0 | `lx_list_stores` | 所有工具的前置依赖 |
| P0 | `lx_product_performance` | 覆盖9个指标，最核心 |
| P0 | `lx_campaign_reports` | 覆盖3个广告活动指标 |
| P0 | `lx_campaign_list` | 唯一获取预算的途径 |
| P1 | `lx_review_list` | 差评闭环，直接返回评论内容 |
| P1 | `lx_sales_trend` | 销量日趋势，产品表现的时间序列补充 |
| P1 | `lx_keyword_rank` | 关键词排名追踪 |
| P1 | `lx_fba_inventory` | 库存冗余分析 |
| P1 | `lx_return_analysis` | 退货率详细分析 |
| P1 | `lx_profit_report_asin` | 配送费+利润明细 |
| P1 | `lx_sales_target` | 达成率 |
| P2 | `lx_add_keyword_monitor` | 关键词监控闭环写操作（Beta） |
| P2 | `lx_search_term_reports` | 关键词流量占比 |
| P2 | `lx_sp_keyword_reports` | 广告关键词分析 |
| P2 | `lx_competitor_monitor` | 竞品追踪 |
| P2 | `lx_storage_fee` | 仓储费明细 |
| P3 | `lx_orders` | 订单明细（产品表现已覆盖大部分） |
| P3 | `lx_list_marketplaces` | 辅助信息 |

---

## 九、后续扩展（Stretch Goals）

| 扩展项 | 说明 | 优先级 |
|--------|------|--------|
| 卖家精灵 MCP Plugin | 覆盖 #14 搜索热度 + #18 竞品关键词流量 | P2 |
| SB/SD广告报表工具 | `lx_sb_campaign_reports` / `lx_sd_campaign_reports` | P3 |
| 广告分析系列 | `/basicOpen/adReport/analyze/keyword`、`analyze/searchTerm`（原生支持31天日期范围+ASIN反查，可作为广告报表的升级数据源） | P3 |
| 广告活动小时数据 | `lx_campaign_hour_data` 用于分时分析 | P3 |
| 评价统计报表 | `reviewReport/lists` ASIN级星级分布/差评率，增强 #19 | P4 |
| 批量ASIN对比 | 工具层面支持多ASIN对比分析 | P3 |
| 数据导出 | 支持CSV/Excel格式导出 | P4 |

