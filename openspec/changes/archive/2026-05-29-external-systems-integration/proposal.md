## Why

DeerFlow 是工业 AI Agent 平台，已有 16 个 builtin Agent，其中 10+ 个需要设备数据。当前数据获取完全碎片化：每个 Agent 的 SOUL.md 写死了 bash 命令、脚本路径、参数格式，接一个新系统（Sms）要改 10+ 个 SOUL.md。没有统一数据模型、没有租户隔离、没有能力路由、系统边界混乱。根本问题是"Agent 直连外部系统"，应该是"Agent 调用平台能力，平台调用外部系统"。

## What Changes

- 建立三层分离架构：Adapter（协议层）→ Service（能力层）→ Tool（消费层），层间单向依赖
- 新增 canonical models（`Asset`, `AssetContext`, `MeasurementPoint`, `TrendSeries`, `WaveformPayload`, `OrbitPayload`, `AlarmEvent`, `HealthAssessment`, `AnomalyStats`, `RiskRanking`, `AssetOverview`, `Provenance` 等 frozen dataclass），配套 Query Objects（`TrendQuery`, `WaveformQuery`, `OrbitQuery`, `AlarmHistoryQuery`, `HealthAssessmentQuery`, `AssetOverviewQuery`），adapter 负责转换，上层只依赖强类型模型
- 新增租户级集成配置：`IntegrationSystem`（系统连接）、`CapabilityRoute`（能力路由，primary + enrich + fallback）、`EntityLink`（跨系统 ID 映射）
- 新增 `CapabilityRouter` 按路由表调度请求，多系统 enrich 并行扇出，部分失败容忍
- 新增 `InsAdapter`（委托现有 MachineServiceClient + 扩展监测端点）和 `SmsAdapter`（httpx + API Key）
- 新增 `AssetService`、`MonitoringService`、`AssessmentService` 能力服务层
- 新增能力查询工具集（LangChain `@tool`），Agent 按 `data_tools` 声明选择性注入
- Agent `config.yaml` 新增 `data_tools` 字段，驱动工具注入和 prompt 裁剪
- 管道式报表脚本通过 subprocess CLI 桥接调用平台 service 层，保留 features-tool fallback
- 扩展 `RpcClient`：per-service `auth_headers`、`response_unwrapper`、`health_check()`

## Capabilities

### New Capabilities

- `integration-config`: 租户级集成系统配置。`IntegrationSystemConfig`（含 `connector_ref`、`transport_type`、`retry_policy`、`capabilities` 声明）、`CapabilityRouteConfig`（含 `merge_policy`、`partial_failure_policy`）、`EntityLinkConfig`（含 `EntityLinkEntry` 多系统映射）Pydantic 模型，声明式管理。配套 REST API：Integration Systems CRUD + 连通性校验、Capability Routes 单个/批量更新、Entity Links CRUD。含租户级访问控制、变更审计日志、API 限流策略、系统降级策略
- `canonical-models`: 平台统一数据模型。`Asset`、`AssetContext`、`MeasurementPoint`、`TrendSeries`、`WaveformPayload`、`OrbitPayload`、`AlarmEvent`、`HealthAssessment`、`AnomalyStats`、`RiskRanking`、`Provenance` 等 frozen dataclass，配套 Query Objects（`TrendQuery`、`WaveformQuery`、`OrbitQuery`、`AlarmHistoryQuery`、`HealthAssessmentQuery`、`AssetCatalogQuery`、`AssetContextQuery`）
- `integration-registry`: 集成注册中心。`IntegrationRegistry` 管理 adapter 生命周期、健康检查调度、`CapabilityRouter` 路由调度（primary + enrich + fallback）、统一错误模型（7 种错误类型：`IntegrationError`、`IntegrationConfigError`、`IntegrationAuthError`、`IntegrationTimeoutError`、`IntegrationUnavailableError`、`IntegrationDataShapeError`、`EntityLinkNotFound`、`CapabilityRouteNotFoundError`）
- `ins-adapter`: InS 协议适配器。6 个 capability（`asset.catalog`、`asset.context`、`monitoring.trend`、`monitoring.waveform`、`monitoring.orbit`、`monitoring.alarm_history`）。通过 `client_bridge.py` 复用现有 `InsApiClient`，`kpi_map.py` 提取 KPI Feature Map，`transform.py` 纯函数转换到 canonical model
- `sms-adapter`: Sms 协议适配器。3 个 capability（`health.assessment`、`health.anomaly_statistics`、`health.risk_ranking`）。独立 `httpx.AsyncClient` + API Key 认证，`transform.py` 纯函数转换到 canonical model
- `integration-services`: 能力服务层。`AssetService`、`MonitoringService`、`AssessmentService` 面向业务的统一接口
- `agent-data-config`: Agent 数据配置。`config.yaml` 中 `data_tools` 字段声明 Agent 使用哪些能力工具，驱动工具注入和 prompt 裁剪
- `integration-tools`: 能力查询工具集。LangChain `@tool` 定义的能力工具，内部走 service 层

### Modified Capabilities

- `equipment-report-pipeline`: 报表管道底层迁移。脚本内部从 features-tool 直连切换到 subprocess 调平台 service CLI
- `java-rpc-client`: RPC 客户端扩展。per-service `auth_headers`、`response_unwrapper`、`health_check()`

## Impact

- **新增模块**: `deerflow/integrations/`（约 20 个文件，含 models/ + adapters/ + services/ + tools/）
- **新增配置**: `integrations` 顶级配置段（systems + routes + entity_links）
- **修改模块**: `deerflow/config/app_config.py`（+1 字段）、`deerflow/config/rpc_config.py`（+2 字段）、`deerflow/rpc/rpc_client.py`（+auth_headers, +health_check）、`deerflow/tools/tools.py`（+integration tools 注入）、`deerflow/agents/lead_agent/prompt.py`（+data_sources 段）、`app/gateway/routers/capabilities.py`（+INTEGRATION_SYSTEM）
- **新增 API**: Integration Systems 完整 CRUD（`POST/GET/PUT/DELETE /api/tenants/{tenant_id}/integration-systems` + `PUT .../enabled` + `POST .../connectivity-check`）、Capability Routes 单个/批量更新（`GET/PUT /api/tenants/{tenant_id}/capability-routes`）、Entity Links 完整 CRUD（`POST/GET/PUT/DELETE /api/tenants/{tenant_id}/entity-links`）
- **Agent 配置**: Agent `config.yaml` 可选新增 `data_tools` 字段
- **向后兼容**: 未声明 `data_tools` 的 Agent 行为不变。现有 `MachineServiceClient`、`InsBaseAuthProvider`、`_ins_provider.py` 全部保留
- **依赖**: 无新增外部依赖（复用 httpx + langchain tools + 现有 RPC 设施）
- **数据库**: 无 schema 变更（初期配置全部 YAML 驱动，entity_links 可后续迁移到 DB）
- **风险**: 低 — 全部增量层，可通过 `integrations.enabled: false` 完全禁用回退
