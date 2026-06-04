## Context

当前日报数据链路为 InS 单一数据源：`query_daily.py` → `InsDailyProvider` → InS API（趋势数据 + 机器报警），完全不涉及 SMS（设备异常统计与评估系统）。

SMS 通过 `SmsAdapter` 已接入平台，`abnormal-judgment--rotating` Agent 通过前端组件 `abnormal-list-selector` → `GET /api/abnormal/list` 和 `query_abnormal_detail.py` → `GET /api/abnormal/detail` 深度消费 SMS 数据。SMS 异常事件带有完整生命周期（待处理→已处理）、健康评分、AI 分析和风险评估，这些信息在日报中完全缺失。

日报 DSL 模板 `daily-equipment/default.yaml` 已有 `anomalies` 章节，但其数据来源是 KPI 阈值计算（`_build_top_anomalies`），不包含 SMS 跟踪的异常事件。

### 约束

- SMS `abnormal.list` API 按时间范围过滤（`startTime`/`endTime`，毫秒时间戳），不支持按设备 ID 列表过滤，需要客户端侧筛选
- SMS API 认证使用 Bearer token，与 InS 共用 `INS_ACCESS_TOKEN` 环境变量
- 日报 DSL 模板的 `sections` 无条件渲染——新增 SMS 章节对所有设备类型可见，非旋转机组类型时返回空数据集即可
- 日报脚本运行在沙箱中，可直接发起 HTTP 请求（参考 `query_abnormal_detail.py` 的 `urllib.request` 模式）

## Goals / Non-Goals

**Goals:**
- 在日报数据链路中新增 SMS 异常事件数据源，为旋转机组提供 SMS 侧跟踪的异常概览
- DSL 模板新增 "SMS 异常事件" 章节（表格），展示当日 SMS 异常列表（设备、部件、健康值、等级、状态）
- 在日报 KPI 计算中纳入 SMS 异常计数（新增异常数、待处理数），影响整体运行状态判定
- 脚本层直连 SMS API，复用现有 token 注入机制，无需后端修改

**Non-Goals:**
- 不修改 SMS API 或 SmsAdapter 本身
- 不在日报中展示 SMS 异常详情（events、AI 分析等）——深度信息通过 abnormal-judgment Agent 获取
- 不修改异常研判 Agent 的流程
- 不为非旋转机组类型（静设备、机泵、往复机组）新增 SMS 章节（SMS 当前主要覆盖旋转机组）
- 不修改日报 legacy 硬编码路径（`query_daily.py` → `daily_kpi.py` 的 SOUL 驱动流程）——仅覆盖 DSL 模板路径

## Decisions

### D1: 新增独立脚本 `query_sms_abnormal.py`，而非在 `InsDailyProvider` 中增加 SMS 调用

**选择**：新建 `/mnt/skills/custom/daily-report/scripts/query_sms_abnormal.py`，独立于 InS 数据获取链路。

**理由**：
- SMS 和 InS 是不同的后端系统（不同的 base URL、API 契约、数据模型）
- `InsDailyProvider` 职责单一（InS 趋势 + 报警），混入 SMS 逻辑会增加耦合
- 独立脚本失败不影响 InS 数据获取（SMS 不可用时日报仍可生成，仅 SMS 章节为空）
- 与 `query_abnormal_detail.py`（被 abnormal-judgment 使用）保持一致模式

**替代方案考虑**：在 `_data_providers.py` 中新增 `SmsAbnormalProvider` 注册到 provider 工厂。但这会引入对 SMS 的强依赖——provider 模式下 SMS 失败会影响整个 fetch 链路。独立脚本更灵活。

### D2: 脚本身份认证复用 `INS_ACCESS_TOKEN`，直连 SMS HTTP API

**选择**：脚本通过 `urllib.request` 直连 SMS API（`${INS_BASE_URL}/api/abnormal/list`），使用环境变量 `INS_ACCESS_TOKEN` 做 Bearer 认证。

**理由**：
- `INS_ACCESS_TOKEN` 已由 DeerFlow 运行上下文自动注入沙箱环境
- `query_abnormal_detail.py` 已验证此模式可行
- 无需经过 Gateway 代理层（`/api/abnormal/list`），减少一跳网络延迟
- SMS base URL 可通过 `INS_BASE_URL` 环境变量覆盖（默认 `http://182.92.187.198`）

### D3: DSL 模板新增 data_step + section，不修改现有 sections

**选择**：在 `daily-equipment/default.yaml` 中新增独立的 `data_step`（`sms_abnormal`）和 `section`（`sms_abnormal_table`），不改变现有 `anomalies` section 的语义。

**理由**：
- 现有 `anomalies` section 展示 KPI 阈值异常（运行率偏低、振动偏高等），属于"指标异常"
- SMS 异常事件是"管理系统跟踪的异常事件"，有独立的生命周期和健康评分
- 两者语义不同，分开展示更清晰
- 不改现有 section 避免破坏已有报告格式

**section 渲染条件**：非旋转机组类型时脚本返回空列表，表格自然为空——不需要模板层面的条件逻辑。

### D4: 客户端侧按设备 ID 过滤 SMS 异常列表

**选择**：脚本请求 SMS `abnormal.list` 时使用报告日期的时间窗口（`startTime`/`endTime`），拿到全量结果后在 Python 侧按 `mac_id` 过滤。

**理由**：
- SMS API 不支持按设备 ID 列表过滤
- 单日异常量通常 < 100 条，全量拉取 + 客户端过滤性能可接受
- 使用 `page_size=200` 确保一次请求覆盖全天数据

### D5: SMS 异常计数纳入 KPI 和整体状态判定

**选择**：在 DSL 模板的 `transforms` 中新增 `sms_kpi_merge` 步骤，将 SMS 异常计数合并到 `daily_kpi.json` 的 `kpi_summary` 和 `overall_status` 中。

**理由**：
- 如果当日有高级别 SMS 异常（`serious_level >= 60`），整体状态应从 `ok` 提升为 `warning` 或 `danger`
- SMS 异常计数（`sms_abnormal_count`）作为新的 KPI 卡片展示

## Risks / Trade-offs

- **[SMS API 不可用]** → SMS 脚本返回 `{"error": ...}` 时，日报仍正常生成（InS 部分完整），SMS 章节显示 "SMS 数据不可用"。脚本返回非零但 DSL 的 data_step 将其视为可选。
- **[时间窗口语义差异]** → SMS `abnormal.list` 的 `startTime`/`endTime` 可能按异常"创建时间"而非"事件发生时间"过滤。如果某异常在报告日期之前创建但仍在处理中，可能不被包含。→ 优先按事件时间过滤；如果 API 实际按创建时间过滤，需在文档中注明此限制。
- **[设备 ID 不匹配]** → SMS 返回的 `mac_id` 可能与 Organize Tree 的设备 ID 格式不一致（如 `P-203A` vs `P203A`）。→ 脚本中做标准化处理（去连字符、统一大小写）后再匹配。
- **[增加一次 HTTP 往返]** → 日报生成多一次 SMS API 调用，总耗时增加约 1-3 秒。→ 可接受；如果后续成为瓶颈，可与 InS 数据获取并行化。

## Open Questions

1. SMS `abnormal.list` 的 `startTime`/`endTime` 参数按什么字段过滤？（创建时间 / 首次事件时间 / 最近事件时间？）需要在实际环境中验证。
2. SMS 对非旋转机组类型（静设备、机泵、往复机组）是否有异常数据？如果有，后续可扩展到全类型。
