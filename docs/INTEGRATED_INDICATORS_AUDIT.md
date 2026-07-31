# 已接入指标审计文档

> **用途**：审计 deer-flow 当前接入的所有数据指标 + MCP 工具方法。便于及时更新（新增/变更/废弃）。
> **维护**：每次新增 MCP 工具或调整指标后，更新本文档对应表格 + 日期。
> **最后更新**：2026-07-29

---

## 一、总览

deer-flow 通过两个 MCP 数据源接入指标：

| MCP Server | 类型 | 位置 | 状态 | 工具数 |
|---|---|---|---|---|
| **lingxing-mcp**（自建） | SSE :8102 | `governance/lingxing_mcp/` | ✅ 已启用 | 7 个 P0 工具 |
| **lark-cli**（飞书官方） | stdio MCP | `skills/public/lark/`（submodule v1.0.77） | ✅ 已启用 | 3 个 skill 启用（27 个可用） |

**数据流**：
```
deer-flow agent
  ├─ lingxing-mcp (:8102) → 领星 ERP OpenAPI (openapi.lingxing.com) → 亚马逊业务数据
  └─ lark-cli (bash 调用) → 飞书 OpenAPI → 推送消息 + 多维表 CRUD
```

---

## 二、lingxing-mcp 已接入的 7 个 P0 工具

> 对应设计文档 `爆品打造专家Agent_设计文档_v1.md` 第 3.2 节的 P0 标记工具。

| # | MCP 工具方法名 | 领星 API 端点 | TTL | 实时性 | 返回关键字段 | 设计文档工具 |
|---|---|---|---|---|---|---|
| 1 | `lx_parent_sales` | `POST /bd/productPerformance/openApi/asinList` | 6h | T+1 | 达成率、Sessions、CVR、Orders、销售额（父ASIN 级） | lx_parent_sales |
| 2 | `lx_parent_ad` | `POST /pb/openapi/newad/spProductAdReports` | 30min | 小时级 | impressions、clicks、CTR、CPC、cost、sales、ACOS、ROAS（父ASIN） | lx_parent_ad |
| 3 | `lx_campaign_perf` | `POST /pb/openapi/newad/spCampaignReports` | 30min | 小时级 | targeting_type、clicks、cost、sales、orders、units（活动级） | lx_campaign_perf |
| 4 | `lx_keyword_rank` | `POST /erp/sc/routing/tool/toolKeywordRank/getKeywordList` | 6h | T+1 | key_word、rank、current_page_rank、sbv_page、asin | lx_keyword_rank |
| 5 | `lx_keyword_share` | `POST /pb/openapi/newad/queryWordReports` | 6h | T+1 | query、target_id、match_type、clicks、cost、sales（搜索词） | lx_keyword_share |
| 6 | `lx_review_rating` | `POST /basicOpen/openapi/service/v3/data/mws/reviews` | 0（不缓存） | 近实时 | review_id、asin、last_star、last_title、last_content、author | lx_review_rating |
| 7 | `lx_inventory_days` | `POST /basicOpen/openapi/storage/fbaWarehouseDetail` + `POST /erp/sc/routing/fbaSug/asin/getDailySalesInfoFeature`（2 端点合并） | 1h | 日 | in_stock、in_transit、daily_sales、available_days | lx_inventory_days |

### 工具方法签名速查

```python
# 1. 产品表现（父ASIN 级）
lx_parent_sales(sid, start_date, end_date, search_value=None, summary_field="parent_asin", length=100)

# 2. 广告商品报表（父ASIN 级）
lx_parent_ad(start_date, end_date, sid, search_value=None, length=100)

# 3. 广告活动报表
lx_campaign_perf(start_date, end_date, sid, search_value=None, length=100)

# 4. 关键词排名
lx_keyword_rank(start_date, end_date, asin=None, keyword=None, length=100)

# 5. 搜索词报表
lx_keyword_share(start_date, end_date, sid, target_type="keyword", search_value=None, length=100)

# 6. 评论/评分
lx_review_rating(start_date, end_date, sid, asin=None, length=100)

# 7. 库存可售天数
lx_inventory_days(asin, sid, length=100)
```

### TTL 缓存策略

| 数据类 | TTL | 缓存方式 | 说明 |
|---|---|---|---|
| 业务报告（产品表现/关键词排名/搜索词） | 6 小时 | per-key dict+timestamp | T+1 数据，一天变化一次 |
| 广告数据（广告商品/活动） | 30 分钟 | per-key dict+timestamp | 小时级刷新，防限频 |
| 评论/评分 | 0（不缓存） | 每次真实拉取 | 紧急级 |
| 库存可售天数 | 1 小时 | per-key dict+timestamp | 断货风险 |

---

## 三、lingxing-mcp 未接入的指标（设计文档列但未做）

> 对应设计文档第 3.2 节的 P1/P2 工具 + 第 3.3 节 mcp-plugin + 第 3.4 节 mcp-bmb。

### P1 工具（第二阶段补齐）

| # | 设计文档工具 | 返回关键字段 | 实时性 | 优先级 | 领星 API 文档路径（待确认） | 状态 |
|---|---|---|---|---|---|---|
| 8 | lx_msku_ad | MSKU 级 ACOS/ROAS/ACOAS | 小时级 | P1 | `docs/newAd/report/spProductAdReports`（同 parent_ad，改 summary_field=msku？待确认） | ❌ 未接入 |
| 9 | lx_keyword_heat | 搜索热度/搜索频率排名 SFR | 日/周 | P1 | 领星官方 MCP 有 `query_erp_keyword_ranking_keyword`，待找文档端点 | ❌ 未接入 |
| 10 | lx_competitor | 竞品销量、大类/小类 BSR、价格 | 日 | P1 | `docs/Tools/CompetitiveMonitorList`（竞品监控列表） | ❌ 未接入 |
| 11 | lx_return_rate | 退货量/率/原因 | T+1 | P1 | 待找文档端点（可能在 Statistics 分类） | ❌ 未接入 |
| 12 | lx_inventory_health | 库龄 90/180/270/365 天数量、冗余成本 | 日 | P1 | 待找文档端点（可能在 Warehouse/FBASug 分类） | ❌ 未接入 |

### P2 工具

| # | 设计文档工具 | 返回关键字段 | 实时性 | 优先级 | 领星 API 文档路径（待确认） | 状态 |
|---|---|---|---|---|---|---|
| 13 | lx_competitor_keyword | 竞品关键词流量占比、排名 | 周 | P2 | 待找文档端点 | ❌ 未接入 |
| 14 | lx_shipping_fee | FBA 配送费、仓储费 | 日 | P2 | `docs/Statistics/FBAStorageFeeMonth`（FBA月仓储费）+ `docs/Statistics/FBAStorageFeeLongTerm`（长期仓储费） | ❌ 未接入 |

### mcp-plugin（Stretch，未做）

| # | 设计文档工具 | 返回关键字段 | 数据来源 | 状态 |
|---|---|---|---|---|
| 15 | plugin_keyword_trend | 关键词全年搜索热度曲线、月度搜索量 | 卖家精灵/西柚（API 优先，否则无头浏览器抓取） | ❌ 未接入（Stretch） |
| 16 | plugin_competitor_traffic | 竞品 ASIN 流量来源占比 | 卖家精灵/西柚 | ❌ 未接入（Stretch） |
| 17 | plugin_market_insight | 市场容量、集中度、新品占比、价格区间 | 卖家精灵/西柚 | ❌ 未接入（Stretch） |

### mcp-bmb（v1.1，未做）

| # | 设计文档工具 | 返回关键字段 | 状态 | 备注 |
|---|---|---|---|---|
| 18 | bmb_profit | 毛利率 | ❌ 未接入 | **但领星 API 已发现利润端点**：`docs/Statistics/statisticsOpenParent`（利润统计-父ASIN），可在 lingxing-mcp 加一个 `lx_profit` 工具覆盖，无需单独 mcp-bmb |

### 额外发现的领星 API（未在设计文档列，但可用）

| 领星 API 文档 | 能力 | 可作为 | 状态 |
|---|---|---|---|
| `docs/Statistics/statisticsOpenParent` | 利润统计-父ASIN | lx_profit（替代 mcp-bmb） | ❌ 未接入（可按需加） |
| `docs/Statistics/statisticsOpenASIN` | 利润统计-ASIN | lx_profit_asin | ❌ 未接入 |
| `docs/Statistics/statisticsOpenMSKU` | 利润统计-MSKU | lx_profit_msku | ❌ 未接入 |
| `docs/Statistics/statisticsOpenSeller` | 利润统计-店铺 | lx_profit_seller | ❌ 未接入 |
| `docs/Statistics/performanceTrendByHour` | asin360 小时数据 | lx_parent_sales_hourly | ❌ 未接入 |
| `docs/newAd/report/spAdPlacementHourData` | SP广告位小时数据 | lx_parent_ad_hourly | ❌ 未接入 |
| `docs/newAd/report/spCampaignHourData` | SP广告活动小时数据 | lx_campaign_perf_hourly | ❌ 未接入 |
| `docs/newAd/report/AdAnalyzeKeyword` | 广告分析-关键词分析 | lx_keyword_analyze | ❌ 未接入 |
| `docs/newAd/report/AdAnalyzeSearchTerm` | 广告分析-搜索词分析 | lx_search_term_analyze | ❌ 未接入 |
| `docs/Service/FeedbackList` | 评价统计-Feedback（4-5星） | lx_feedback_positive | ❌ 未接入 |
| `docs/Service/FeedbackListMws` | 评价统计-Feedback（1-3星） | lx_feedback_negative | ❌ 未接入 |
| `docs/Service/reviewLists` | 评价统计-Review 列表 | lx_review_summary | ❌ 未接入 |
| `docs/Service/reviewDetail` | 评价统计-Review 每日新增数 | lx_review_daily_new | ❌ 未接入 |
| `docs/Service/storePerformanceList` | 店铺绩效列表 | lx_store_performance | ❌ 未接入 |
| `docs/Tools/CompetitiveMonitorList` | 竞品监控列表 | lx_competitor | ❌ 未接入（P1） |
| `docs/Tools/warningMessageGoodsList` | 预警消息-商品 | lx_warning_goods | ❌ 未接入 |
| `docs/Tools/warningMessageInventoryList` | 预警消息-库存 | lx_warning_inventory | ❌ 未接入 |

---

## 四、lark-cli（飞书官方 MCP）接入情况

> lark-cli 是飞书官方 CLI 工具（npm `@larksuite/cli`），通过 git submodule 挂在 `skills/public/lark/`（v1.0.77），格式兼容 deer-flow 技能系统。agent 通过 bash 工具调用。

### 已启用的 3 个 skill

| skill 名 | 能力 | 用途 | 状态 |
|---|---|---|---|
| `lark-shared` | 认证基础（app config/auth login/identity/scope） | 所有其他 lark skill 依赖 | ✅ 已启用 |
| `lark-im` | 发消息/回复/群管理/搜索/上传下载/加急/交互卡片 | 推送告警（🔴紧急@/🟡警告卡片/🔵信息日报） | ✅ 已启用 |
| `lark-base` | 多维表 CRUD（表/字段/记录/视图/仪表盘/工作流/表单/角色权限） | C 子项目多维表 schema 搭建 + 写异常告警表 | ✅ 已启用 |

### 未启用但可用的 24 个 skill

| skill 名 | 能力 | 后续可用场景 |
|---|---|---|
| `lark-calendar` | 日历事件/议程/空闲查询/会议室 | — |
| `lark-doc` | 文档创建/读/更新/搜索 | 生成归因报告文档 |
| `lark-drive` | 文件上传下载/权限/评论 | — |
| `lark-markdown` | Drive 原生 .md 文件 | — |
| `lark-sheets` | 电子表格 CRUD/查找/导出 | — |
| `lark-slides` | 演示文稿 | — |
| `lark-task` | 任务/子任务/提醒/分配 | 跟踪异常处理任务 |
| `lark-mail` | 邮件浏览/搜索/发送/回复 | 邮件告警 |
| `lark-contact` | 用户搜索/资料 | 查负责人 |
| `lark-wiki` | 知识空间/节点/文档 | 知识库 |
| `lark-event` | 实时事件订阅（WebSocket） | 实时触发 |
| `lark-vc` | 会议记录/分钟 | — |
| `lark-vc-agent` | VC agent | — |
| `lark-whiteboard` | 白板/图表 DSL | — |
| `lark-minutes` | 分钟元数据/AI 制品 | — |
| `lark-openapi-explorer` | 探索底层 API | — |
| `lark-skill-maker` | 自定义 skill 创建 | — |
| `lark-attendance` | 考勤打卡 | — |
| `lark-approval` | 审批查询/处理 | — |
| `lark-workflow-meeting-summary` | 工作流：会议分钟汇总 | — |
| `lark-workflow-standup-report` | 工作流：议程+待办汇总 | — |
| `lark-okr` | OKR 查询/创建/更新 | — |
| `lark-note` | 笔记 | — |
| `lark-apps` | Spark/Miaoda 应用 | — |

---

## 五、接入状态汇总

| 类别 | 已接入 | 未接入 | 合计 |
|---|---|---|---|
| lingxing-mcp P0 工具 | 7 | 0 | 7 |
| lingxing-mcp P1 工具 | 0 | 5 | 5 |
| lingxing-mcp P2 工具 | 0 | 2 | 2 |
| mcp-plugin（Stretch） | 0 | 3 | 3 |
| mcp-bmb（v1.1） | 0 | 1（但领星 API 可替代） | 1 |
| lark-cli skill | 3 | 24 | 27 |
| **合计** | **10** | **35** | **45** |

---

## 六、维护说明

### 新增 lingxing-mcp 工具时

1. 在 `governance/lingxing_mcp/governance_lingxing_mcp/tools/` 加 `<name>.py`（参考 `parent_sales.py` 模板）
2. 在 `server.py` 注册 `@mcp.tool()` 方法
3. 在 `tests/` 加 `test_<name>.py`
4. 更新本文档第二节的表格
5. 重启 lingxing-mcp 服务

### 新增 lark-cli skill 启用时

1. 在 `extensions_config.json` 的 `skills` 段加 `"<skill-name>": {"enabled": true}`
2. 更新本文档第四节的"已启用"表格
3. deer-flow reload 配置生效

### 领星 API 端点变更时

1. fetch 领星 API 文档（`https://apidoc.lingxing.com/docs/<category>/<name>.md`）确认新端点
2. 更新 `governance_lingxing_mcp/tools/<name>.py` 的 `API_PATH` 常量
3. 更新本文档第二节的"领星 API 端点"列
4. 跑 `PYTHONPATH=. uv run pytest tests/ -v` 确认测试通过

### 鉴权变更时

- lingxing appId/appSecret 变更：更新环境变量 `LINGXING_APP_ID`/`LINGXING_APP_SECRET`，重启 lingxing-mcp
- lark-cli 凭据失效：跑 `lark-cli auth login --recommend` 重新授权
