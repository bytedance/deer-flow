# 数据指标口径对照审计（25 个叶子指标）

> **基准**：业务口径《数据指标口径说明》共 25 个叶子指标。
> **对照**：lingxing-mcp 7 个已接入工具 + lark-cli + 未接入计划。
> **最后更新**：2026-07-29

---

## 一、25 个指标逐行对照

| 序号 | 完整指标名 | 一级指标 | 业务口径来源 | 统计周期/维度 | 接入情况 | 工具名称 | 出入说明 |
|-----|----------|--------|------------|------------|--------|--------|---------|
| 1 | 店铺销售额达成率 | 店铺销售额达成率 | —（未明确） | 父ASIN达成率 | ❌ 缺失 | lx_parent_sales | asinList 不返回 target 字段，达成率需"目标管理"分类 API，当前未接入 |
| 2 | 流量 | 流量 | 领星→统计→产品表现→父ASIN→Sessions-Total | — | ✅ 已确认 | lx_parent_sales | asinList 返回 `sessions_total` 字段（+sessions Browser +sessions_mobile），已确认 |
| 3 | 点击转化率 | 点击转化率 | 领星→统计→产品表现→父ASIN→CVR | — | ✅ 已确认 | lx_parent_sales | asinList 直接返回 `cvr` 字段（非计算），已确认 |
| 4 | 广告-acos | 广告 | 领星→统计→产品表现→父ASIN/MSKU→acos | 近7/14/30天/基准 | ✅ 已修复 | lx_parent_ad | **已修复**：lx_parent_ad 改用 asinList（原 spProductAdReports），asinList 直接返回 `acos` 字段 |
| 5 | 广告-roas | 广告 | 领星→统计→产品表现→父ASIN/MSKU→roas | 近7/14/30天/基准 | ✅ 已修复 | lx_parent_ad | **已修复**：asinList 直接返回 `roas` 字段 |
| 6 | 广告-acoas | 广告 | 领星→统计→产品表现→父ASIN/MSKU→acoas | 近7/14/30天/基准 | ✅ 已修复 | lx_parent_ad | **已修复**：asinList 直接返回 `acoas` 字段 |
| 7 | 广告活动-点击转化率 | 广告活动 | 领星→广告→全部活动→广告活动→CVR | 近7/14/30天/基准 | ✅ 已接入 | lx_campaign_perf | 一致（spCampaignReports） |
| 8 | 广告活动-acos | 广告活动 | 领星→广告→全部活动→广告活动→ACOS | 近7/14/30天/基准 | ✅ 已接入 | lx_campaign_perf | 一致 |
| 9 | 广告活动-roas | 广告活动 | 领星→广告→全部活动→广告活动→ROAS | 近7/14/30天/基准 | ✅ 已接入 | lx_campaign_perf | 一致 |
| 10 | 广告活动-预算 | 广告活动 | 领星→广告→全部活动→广告活动→预算 | — | ❌ 确认缺失 | lx_campaign_perf | **已确认**：spCampaignReports 不返回 budget 字段，需另调广告活动管理 API |
| 11 | 关键词-广告位 | 关键词 | 卖家精灵插件→反查流量词 | 近7/14/30天 | ⚠️ **来源出入** | lx_keyword_rank | **❌来源出入**：业务口径来源是**卖家精灵插件**，我接的是领星 API。需确认用户是否接受领星替代；若必须用卖家精灵，需做 mcp-plugin（Stretch） |
| 12 | 关键词-自然位 | 关键词 | 卖家精灵插件→反查流量词 | 近7/14/30天 | ⚠️ **来源出入** | lx_keyword_rank | 同序号 11 |
| 13 | 关键词-流量占比 | 关键词 | 卖家精灵插件→反查流量词 | 近7/14/30天 | ⚠️ **来源出入** | lx_keyword_share | 同序号 11，领星 queryWordReports 替代卖家精灵 |
| 14 | 关键词-搜索热度排名 | 关键词 | 卖家精灵插件→月搜索趋势 | — | ❌ 未接入 | —（lx_keyword_heat P1） | 来源是卖家精灵，未接入。领星是否有 SFR 端点待确认 |
| 15 | 竞品监控-销量 | 竞品监控 | — | — | ❌ 未接入 | lx_competitor（P1） | |
| 16 | 竞品监控-排名 | 竞品监控 | — | 大类/小类 | ❌ 未接入 | lx_competitor（P1） | 需确认 CompetitiveMonitorList 返回大类/小类 BSR |
| 17 | 竞品监控-价格 | 竞品监控 | — | — | ❌ 未接入 | lx_competitor（P1） | |
| 18 | 竞品监控-关键词流量占比 | 竞品监控 | — | — | ❌ 未接入 | lx_competitor_keyword（P2） | |
| 19 | 评分变化 | 评分变化 | — | — | ✅ 已接入 | lx_review_rating | last_star 字段，可对比前后变化 |
| 20 | 新增差评 | 新增差评 | — | 对比昨天 | ✅ 已接入 | lx_review_rating | 按 start_date/end_date 筛选，last_star 低星 + 日期对比 |
| 21 | 退货率 | 退货率 | — | 同环比/基准 | ❌ 未接入 | lx_return_rate（P1） | 领星有 MonthRefund 端点待确认 |
| 22 | 配送费 | 配送费 | — | — | ❌ 未接入 | lx_shipping_fee（P2） | 领星有 FBAStorageFeeMonth/FBAStorageFeeLongTerm |
| 23 | 库存冗余成本 | 库存冗余成本 | — | 90/180/271/365天/环比 | ❌ 未接入 | lx_inventory_health（P1） | 需找库龄端点 |
| 24 | 库存冗余数量 | 库存冗余数量 | — | — | ❌ 未接入 | lx_inventory_health（P1） | 同序号 23 |
| 25 | 库存可售天数 | 库存可售天数 | — | 4个月/5个月 | ✅ 已接入 | lx_inventory_days | available_days 字段，阈值 4月（120天）/5月（150天）|

---

## 二、4 处出入详解 + 修正建议

### 出入 1：广告 acos/roas/acoas 来源不一致（序号 4/5/6）❌ 重要

**业务口径**：领星→统计→产品表现→父ASIN/MSKU→acos/roas/acoas
**我的实现**：领星→广告报表→spProductAdReports

**问题**：业务期望广告 ACOS/ROAS/ACOAS 从"统计→产品表现"API（asinList）取，我接的是"广告报表"API（spProductAdReports）。

**可能原因**：领星 asinList（产品表现）可能返回广告汇总指标（acos/roas/acoas），而 spProductAdReports 返回的是详细广告商品数据。两者数据可能一致但来源路径不同。

**修正建议**：
1. **确认 asinList 返回字段**：fetch asinList 文档的"返回结果"段，看是否有 acos/roas/acoas 字段
2. **若 asinList 有广告字段**：lx_parent_ad 改用 asinList（或 lx_parent_sales 扩展返回广告字段），删除 spProductAdReports 调用
3. **若 asinList 无广告字段**：保留 spProductAdReports，但在文档标注"来源为广告报表，非业务口径的统计→产品表现"（口径偏差，需业务确认）

**影响范围**：lx_parent_ad 工具的 API_PATH + 实现逻辑需调整

---

### 出入 2：关键词 4 个指标来源不一致（序号 11/12/13/14）⚠️ 中等

**业务口径**：卖家精灵插件→反查流量词
**我的实现**：领星 API（lx_keyword_rank + lx_keyword_share）

**问题**：业务期望关键词广告位/自然位/流量占比/搜索热度从**卖家精灵插件**取，我从**领星 API** 取。来源不同。

**可能原因**：设计文档第 3.3 节 mcp-plugin 确实用卖家精灵，但 B 子项目用领星 API 替代了（领星有 keyword_rank + queryWordReports 端点）。数据可能有差异（卖家精灵 vs 领星）。

**修正建议**：
1. **确认用户接受领星替代**：如果用户接受领星 API 数据（数据口径可能略有差异但可接受），保留现有实现，文档标注"来源领星，非卖家精灵"
2. **若必须用卖家精灵**：需做 mcp-plugin（设计文档 Stretch），用无头浏览器或插件 API 抓取。这是 B 子项目范围外的工作
3. **搜索热度排名 SFR（序号 14）**：领星是否有 SFR 端点待确认，若无则必须做 mcp-plugin

**影响范围**：lx_keyword_rank + lx_keyword_share 的来源标注 + 可能需补 mcp-plugin

---

### 出入 3：广告活动-预算字段缺失（序号 10）❌ 缺失

**业务口径**：广告活动→预算
**我的实现**：lx_campaign_perf 没有预算字段

**问题**：lx_campaign_perf 用 spCampaignReports，返回 targeting_type/clicks/cost/sales/orders/units，**没返回 budget（预算）**。

**修正建议**：
1. **确认 spCampaignReports 是否返回 budget**：fetch 文档的"返回结果"段
2. **若有 budget**：lx_campaign_perf 补提取 budget 字段
3. **若无 budget**：可能需调另一个端点（如广告活动管理 API `docs/newAd/adReportManagePutSpCampaign`，但那是修改不是查询）。或标注"预算字段该 API 不返回，需另找端点"

**影响范围**：lx_campaign_perf 补字段或标注缺失

---

### 出入 4：达成率/Sessions/CVR 来源待确认（序号 1/2/3）⚠️ 待确认

**业务口径**：
- 序号 1 达成率：来源"—"（未明确），维度"父ASIN达成率"
- 序号 2 流量：来源"领星→统计→产品表现→父ASIN→Sessions-Total"
- 序号 3 CVR：来源"领星→统计→产品表现→父ASIN→CVR"

**我的实现**：
- 达成率：计算（实际/目标），但 asinList 是否返回"目标"字段未确认
- Sessions：⚠️ 待确认 asinList 是否返回 sessions 字段
- CVR：计算（orders/sessions），但业务口径说直接返回 CVR

**修正建议**：
1. **fetch asinList 完整返回字段**：确认 asinList 返回 sessions/cvr/target/达成率 字段
2. **若 asinList 返回这些字段**：lx_parent_sales 直接提取，不用计算
3. **若 asinList 不返回 target**：达成率需另调 API（可能需领星"目标管理"分类的端点）

**影响范围**：lx_parent_sales 字段提取逻辑

---

## 三、25 指标接入汇总（修复后）

| 状态 | 数量 | 序号 |
|---|---|---|
| ✅ 已接入且口径一致 | 11 | 2,3,4,5,6,7,8,9,19,20,25 |
| ⚠️ 已接入但来源有出入 | 3 | 1（达成率缺失）, 11,12,13（领星替代卖家精灵） |
| ❌ 字段缺失（已确认） | 1 | 10（广告活动预算 spCampaignReports 无） |
| ❌ 未接入 | 10 | 14,15,16,17,18,21,22,23,24 |

**覆盖率**：11/25 完全一致 = 44%；+3 已接入有出入 = 56%；完全未接入 10/25 = 40%

> **修复记录（2026-07-29）**：
> - 序号 2/3：asinList 确认返回 `sessions_total` + `cvr`（直接返回，非计算）✅
> - 序号 4/5/6：lx_parent_ad 改用 asinList（原 spProductAdReports），asinList 直接返回 `acos`/`roas`/`acoas` ✅
> - 序号 1：asinList 确认无 target 字段，达成率需"目标管理"API ❌
> - 序号 10：spCampaignReports 确认无 budget 字段 ❌
> - 额外发现：asinList 返回 `gross_profit`（毛利）+ `return_amount`（退款）+ `cate_rank`（大类排名）+ `small_cate_rank`（小类排名），可用于序号 19/21/15/16

---

## 四、修正优先级

| 优先级 | 出入 | 修正动作 | 影响工具 |
|---|---|---|---|
| **P0 紧急** | 序号 4/5/6 广告 acos 来源 | fetch asinList 返回字段，确认是否有 acos/roas/acoas；若有则 lx_parent_ad 改用 asinList | lx_parent_ad |
| **P0 紧急** | 序号 1/2/3 达成率/Sessions/CVR | fetch asinList 返回字段，确认 sessions/cvr/target 字段 | lx_parent_sales |
| **P1 高** | 序号 10 广告活动预算 | fetch spCampaignReports 返回字段，确认 budget | lx_campaign_perf |
| **P1 高** | 序号 11/12/13 关键词来源 | 确认用户接受领星替代卖家精灵；若不接受则需 mcp-plugin | lx_keyword_rank/share |
| **P2 中** | 序号 14 SFR 搜索热度 | 确认领星是否有 SFR 端点；若无则 mcp-plugin | — |
| **P2 中** | 序号 15-18 竞品监控 | P1 工具 lx_competitor 待做 | — |
| **P3 低** | 序号 21-24 退货/配送/冗余 | P1/P2 工具待做 | — |

---

## 五、待确认的 API 字段（需 fetch 文档验证）

| 序号 | 指标 | 待确认 | API 文档 |
|---|---|---|---|
| 1 | 达成率 | asinList 是否返回 target 字段 | docs/Statistics/AsinListNew |
| 2 | Sessions | asinList 是否返回 sessions 或 volume_session_total | 同上 |
| 3 | CVR | asinList 是否直接返回 cvr（非计算） | 同上 |
| 4/5/6 | acos/roas/acoas | asinList 是否返回广告汇总字段 | 同上 |
| 10 | 广告活动预算 | spCampaignReports 是否返回 budget | docs/newAd/report/spCampaignReports |
| 14 | 搜索热度 SFR | 领星是否有 SFR 端点 | 待找 |
