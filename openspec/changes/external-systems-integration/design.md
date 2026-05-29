## Context

DeerFlow 16 个 builtin Agent 中至少 10 个需要设备数据，但数据获取完全碎片化：

**碎片化现状**：
- `ai-report--daily/weekly/monthly` 各自 bash 调 `query_daily/weekly/monthly.py` → `_ins_provider.py` → features-tool InsApiClient
- `monitoring-analysis` bash 调 `query_trend.py` + `query_daily.py` + `ultra_*` 脚本
- `fault-diagnosis--pump/rotating/reciprocating` bash 调 features-tool 频谱分析
- `ai-report--diagnosis` bash 调 `query_fault_context.py` → demo/http provider
- `ai-report--custom` 用 DSL `data_steps` 引用上述脚本

每个 Agent 的 SOUL.md 写死了 bash 命令、参数格式、输出解析。10 个 Agent × 3 个系统（Ins/Sms/未来）= 维护爆炸。

**可复用的现有资产**：
- `MachineServiceClient`（`deerflow/rpc/machine_service.py`）— 设备查询已封装
- `InsBaseAuthServiceClient`（`deerflow/rpc/ins_base_auth_service.py`）— RSA 登录已封装
- `InsBaseAuthProvider`（`app/gateway/auth/ins_base_provider.py`）— token 缓存 + orgId→tenantId 解析
- `_ins_provider.py`（`skills/custom/data-analyst/scripts/`）— KPI Feature Map、point selection、trend aggregation 逻辑
- `_data_providers.py`（`skills/custom/data-analyst/scripts/`）— Provider Protocol + Registry + ProviderResult 模式
- `RpcClient`（`deerflow/rpc/rpc_client.py`）— httpx 连接池、Nacos 发现、重试、超时
- `config.yaml` 已有 `ins-bus-rpc` 和 `ins-base-rpc` 服务配置
- `InS-OS-API-文档.md`（`backend/docs/`）— 27 个接口组已整理

**约束**：
- Harness 层（`deerflow.*`）不能 import App 层（`app.*`）— `test_harness_boundary.py` 强制
- sandbox 脚本 dependency-free — 不能 import langchain/langgraph
- 现有 `MachineServiceClient`、`InsBaseAuthProvider`、`_ins_provider.py` 向后兼容
- `config_version` 变更需迁移路径

**利益相关者**：
- AI Agent（推理式）— 需要工具化的能力访问 + prompt 知识注入
- AI Agent（管道式）— 需要确定性数据管道 + 底层 adapter 共享
- 平台开发者 — 接入新系统 = YAML 声明 + adapter 实现，不改 Agent
- 运维团队 — 声明式配置，可见可控
- 租户管理员 — 配置自己租户的系统连接和能力路由

## Goals / Non-Goals

**Goals:**

1. **三层分离架构** — Adapter（协议层，面向系统）、Service（能力层，面向业务）、Tool（消费层，面向 Agent），层间单向依赖
2. **Canonical Models** — 平台统一数据模型（`Asset`、`AssetContext`、`MeasurementPoint`、`TrendSeries`、`WaveformPayload`、`OrbitPayload`、`AlarmEvent`、`HealthAssessment`、`AnomalyStats`、`RiskRanking`、`AssetOverview`、`Provenance`），配套 Query Objects，adapter 负责转换，上层只依赖 canonical model
3. **租户级集成配置** — `IntegrationSystem`（系统连接）、`CapabilityRoute`（能力路由）、`EntityLink`（跨系统 ID 映射），声明式管理
4. **能力路由** — `CapabilityRouter` 按 `CapabilityRoute` 表调度请求，支持 primary + enrich + fallback 策略
5. **Agent 声明式数据配置** — Agent `config.yaml` 的 `data_tools` 字段声明使用哪些能力工具，驱动工具注入和 prompt 裁剪
6. **双模式消费** — 推理式（LangChain 工具）和管道式（bash 脚本 subprocess 桥接）共享同一个 Service 层
7. **系统权威边界** — 明确每个系统的权威数据域，设备主数据以 InS 为准，其他系统通过 EntityLink 映射

**Non-Goals:**

- **不改变管道式 Agent 的 SOUL.md** — 日报/周报/月报 Agent 的 GenUI 收参 → bash → 脚本流程不变
- **不替换现有认证** — `InsBaseAuthProvider` 继续管理认证，adapter 通过 `AuthContext` 接收 token
- **不做数据写入** — 本次只做只读接入
- **不做消息订阅** — Sms 的推送/webhook 不在本次范围
- **不做 ETL** — 不是把数据搬进来，是按需查询
- **不做数据库存储** — 初期 `EntityLink` 在 YAML 中声明，后续可迁移到 DB

## Decisions

### D1: 三层分离 — Adapter / Service / Tool

**选择**: 集成架构分为三层，层间单向依赖：

```
Agent Tool（消费层）
    ↓ 调用
Service（能力层）
    ↓ 调用
CapabilityRouter → Adapter（协议层）
    ↓ 连接
外部系统（InS / Sms / CRM / ERP）
```

**Adapter 层** — 面向系统协议：
- 处理认证、重试、字段转换、响应校验
- 每个外部系统一个 adapter（`InsAdapter`、`SmsAdapter`）
- 输入是系统特定的查询参数，输出是 canonical model
- 不知道"能力"的概念，只知道"系统端点"

**Service 层** — 面向业务能力：
- 聚合多个 adapter 的结果，提供业务级接口
- `MonitoringService.get_trend()` 内部走 CapabilityRouter 找到正确的 adapter
- 处理 enrich（从次级系统补充数据）和 fallback
- 返回 `ServiceResult`（canonical model + provenance）

**Tool 层** — 面向 Agent 消费：
- LangChain `@tool` 装饰的函数
- 每个 tool 对应一个 service 方法
- 负责参数校验、错误处理、输出格式化（中文、按概念组织）

**理由**:
- 换外部系统只换 adapter，service 和 tool 不动
- 换业务逻辑只改 service，adapter 和 tool 不动
- 换 Agent 交互只改 tool，adapter 和 service 不动

**替代方案**: 两层（Adapter + Tool）— 业务逻辑散落在 tool 里，10 个 tool × N 个系统 = 维护爆炸。

### D2: Canonical Models — 强类型统一模型

**选择**: 定义 frozen dataclass 作为平台统一数据模型，adapter 负责将系统响应转换为 canonical model。

```python
# deerflow/integrations/models/asset.py

@dataclass(frozen=True)
class Asset:
    id: str                        # platform unified ID
    name: str                      # short code
    display_name: str              # human-readable
    kind: str                      # platform enum
    subtype: str | None
    area: str | None
    location: str | None
    status: str
    tags: tuple[str, ...]
    source_metadata: dict[str, Any]
    provenance: Provenance

@dataclass(frozen=True)
class MeasurementPoint:
    id: str
    asset_id: str
    name: str
    point_type: str
    unit: str
    endpoint_series: str | None
    position_type: str | None
    alarm_thresholds: dict[str, float]
    source_metadata: dict[str, Any]
    provenance: Provenance

@dataclass(frozen=True)
class AssetContext:
    asset: Asset
    children: tuple[Asset, ...]
    points: tuple[MeasurementPoint, ...]
    related_assets: tuple[Asset, ...]
    source_metadata: dict[str, Any]
    provenance: Provenance

# deerflow/integrations/models/monitoring.py

@dataclass(frozen=True)
class TrendSeries:
    series_id: str
    asset_id: str
    point_id: str
    metric_key: str
    display_name: str
    unit: str
    aggregation: str               # "hourly", "daily", "raw"
    time_range: TimeRange
    samples: tuple[TrendPoint, ...]
    statistics: TrendStatistics | None
    anomalies: tuple[dict[str, Any], ...]
    source_metadata: dict[str, Any]
    provenance: Provenance

@dataclass(frozen=True)
class TrendPoint:
    ts: str                        # ISO 8601
    value: float
    quality: str | None

@dataclass(frozen=True)
class TrendStatistics:
    min: float
    max: float
    avg: float
    stddev: float | None

@dataclass(frozen=True)
class WaveformPayload:
    asset_id: str
    point_id: str
    sample_rate: float
    captured_at: str
    wave_x: tuple[float, ...]
    wave_y: tuple[float, ...]
    spec_x: tuple[float, ...]
    spec_y: tuple[float, ...]
    speed_rpm: float | None
    unit: str
    source_metadata: dict[str, Any]
    provenance: Provenance

@dataclass(frozen=True)
class OrbitPayload:
    asset_id: str
    bearing_id: str
    captured_at: str
    probe_ids: tuple[str, ...]
    points: tuple[tuple[float, float], ...]
    points_1x: tuple[tuple[float, float], ...]
    points_2x: tuple[tuple[float, float], ...]
    speed_rpm: float | None
    source_metadata: dict[str, Any]
    provenance: Provenance

@dataclass(frozen=True)
class AlarmEvent:
    id: str
    asset_id: str
    point_id: str | None
    event_type: str
    severity: str
    title: str
    message: str
    started_at: str
    ended_at: str | None
    duration_seconds: float | None
    source_metadata: dict[str, Any]
    provenance: Provenance

# deerflow/integrations/models/assessment.py

@dataclass(frozen=True)
class HealthAssessment:
    asset_id: str
    assessment_time: str
    overall_score: float
    level: str
    summary: str
    dimensions: dict[str, float]
    risk_items: tuple[RiskItem, ...]
    recommendations: tuple[str, ...]
    source_metadata: dict[str, Any]
    provenance: Provenance

@dataclass(frozen=True)
class RiskItem:
    code: str
    severity: str
    message: str

@dataclass(frozen=True)
class RiskRanking:
    period: str
    rankings: tuple[EquipmentRisk, ...]
    source_metadata: dict[str, Any]
    provenance: Provenance

# deerflow/integrations/models/provenance.py

@dataclass(frozen=True)
class Provenance:
    source_system: str
    capability_key: str
    fetched_at: str
    partial_failures: tuple[PartialFailure, ...]

# deerflow/integrations/models/queries.py

@dataclass(frozen=True)
class TrendQuery:
    asset_id: str
    point_id: str | None = None
    metric_key: str | None = None
    time_range: TimeRange | None = None
    aggregation: str = "hourly"

@dataclass(frozen=True)
class WaveformQuery:
    asset_id: str
    point_id: str
    captured_at: str | None = None

@dataclass(frozen=True)
class OrbitQuery:
    asset_id: str
    bearing_id: str
    captured_at: str | None = None
```

**理由**:
- 上层代码 `result.data.samples[0].value` 而不是 `result["data"]["samples"][0]["value"]`
- 类型检查在 adapter 转换时发生，不在 10 个 tool 里各自检查
- frozen 保证不可变，符合项目 coding style
- 新增系统只需实现新的 transform 函数
- Query Objects 稳定 service 层接口，参数变更不影响调用方
- Provenance 独立模型便于跨系统追踪

**替代方案**: dict + TypedDict — 灵活性高但类型安全弱，dict 嵌套解析容易出错。

### D3: 租户级集成配置 — IntegrationSystem + CapabilityRoute + EntityLink

**选择**: 三个配置对象管理租户的集成关系。

**IntegrationSystem** — 系统连接信息：

```python
class IntegrationSystemConfig(BaseModel):
    system_key: str            # "ins_prod"
    system_type: str           # "ins" | "sms" | "crm" | "erp"
    base_url: str
    auth_type: str             # "bearer" | "api_key" | "ins_base"
    secret_ref: str | None     # "$ENV_VAR" 或 "tenant://secrets/xxx"
    timeout_seconds: float = 15.0
    enabled: bool = True
    extra_config: dict[str, Any] = Field(default_factory=dict)
```

**CapabilityRoute** — 能力路由规则：

```python
class CapabilityRouteConfig(BaseModel):
    capability_key: str        # "monitoring.trend"
    primary_system_key: str     # "ins_prod"
    enrich_system_keys: list[str] = Field(default_factory=list)
    fallback_system_keys: list[str] = Field(default_factory=list)
```

**EntityLink** — 跨系统实体映射：

```python
class EntityLinkConfig(BaseModel):
    entity_type: str           # "equipment"
    canonical_id: str          # 平台统一 ID
    system_key: str            # "ins_prod"
    remote_id: str             # 该系统中的 ID
    confidence: float = 1.0
    metadata: dict[str, Any] = Field(default_factory=dict)
```

**理由**:
- 租户 A 和租户 B 可以接不同的系统组合
- 能力路由声明式管理，不散落在 Agent prompt 里
- EntityLink 用 confidence 处理 ID 映射的不确定性（不同系统 ID 几乎不可能完全对齐）
- 现有 `RpcServiceConfig` 可以作为 `IntegrationSystemConfig` 的底层传输配置

### D4: CapabilityRouter — primary + enrich + fallback

**选择**: `CapabilityRouter` 按路由表调度请求，支持三种策略：

```python
class CapabilityRouter:
    async def route(self, capability_key: str, params: dict,
                    tenant_id: str, auth_context: AuthContext | None
                    ) -> ServiceResult:
        route = self._get_route(tenant_id, capability_key)
        adapter = self._registry.get(route.primary_system_key)

        # 1. primary 调用
        try:
            data = await adapter.call(capability_key, params, auth_context)
        except AdapterError:
            # fallback
            for fallback_key in route.fallback_system_keys:
                fb_adapter = self._registry.get(fallback_key)
                try:
                    data = await fb_adapter.call(capability_key, params, auth_context)
                    break
                except AdapterError:
                    continue
            else:
                raise IntegrationError("所有系统均不可用")

        # 2. enrich（并行扇出）
        partial_failures = []
        if route.enrich_system_keys:
            enrich_tasks = [
                self._registry.get(k).call(capability_key, params, auth_context)
                for k in route.enrich_system_keys
            ]
            enrich_results = await asyncio.gather(*enrich_tasks, return_exceptions=True)
            for k, result in zip(route.enrich_system_keys, enrich_results):
                if isinstance(result, Exception):
                    partial_failures.append(f"{k}: {type(result).__name__}")
                else:
                    data = self._merge(data, result)

        return ServiceResult(
            data=data,
            source_system=route.primary_system_key,
            connector_key=route.primary_system_key,
            fetched_at=datetime.utcnow().isoformat(),
            partial_failures=partial_failures,
        )
```

**理由**:
- primary 是权威数据源，enrich 是补充数据，fallback 是降级方案
- enrich 并行降低延迟
- fallback 串行尝试，第一个成功就返回
- `partial_failures` 让上层知道 enrich 是否完整

### D5: InsAdapter — 委托现有客户端 + 扩展

**选择**: `InsAdapter` 内部委托 `MachineServiceClient`（设备查询）+ 扩展实时监测端点（趋势、波形、轨迹、报警）。

```python
class InsAdapter:
    def __init__(self, config: IntegrationSystemConfig, rpc_client: RpcClient):
        self._client_bridge = InsClientBridge(rpc_client)  # 封装 InsApiClient
        self._config = config

    async def call(self, capability_key: str, query: Any,
                   auth_context: AuthContext | None) -> Any:
        if capability_key == "asset.catalog":
            raw = await self._client_bridge.get_machine_detail_info(query, auth_context)
            return transform_to_assets(raw)
        elif capability_key == "asset.context":
            raw = await self._client_bridge.get_equipment_context(query, auth_context)
            return transform_to_asset_context(raw)
        elif capability_key == "monitoring.trend":
            raw = await self._client_bridge.fetch_trend(query, auth_context)
            return transform_to_trend_series(raw, query)
        elif capability_key == "monitoring.waveform":
            raw = await self._client_bridge.fetch_waveform(query, auth_context)
            return transform_to_waveform_payload(raw, query)
        elif capability_key == "monitoring.orbit":
            raw = await self._client_bridge.fetch_orbit(query, auth_context)
            return transform_to_orbit_payload(raw, query)
        elif capability_key == "monitoring.alarm_history":
            raw = await self._client_bridge.fetch_alarms(query, auth_context)
            return transform_to_alarm_events(raw)
```

**关键设计**:
- `client_bridge.py` 封装现有 `InsApiClient`，复用认证、路由、响应扁平化逻辑，不重写
- `kpi_map.py` 提取 `_KPI_FEATURE_MAP` 和 `_select_points_for_kpi`，sandbox 脚本保留本地副本作为 fallback
- `transform.py` 纯函数转换，Ins 响应 → canonical model，填充 `source_metadata` 和 `provenance`
- Query Objects（`AssetCatalogQuery`、`AssetContextQuery`、`TrendQuery`、`WaveformQuery`、`OrbitQuery`、`AlarmHistoryQuery`）作为参数类型，稳定接口

**理由**:
- `MachineServiceClient` 的所有现有调用者不受影响
- adapter 只做协议转换，不包含业务逻辑
- `client_bridge.py` 是临时迁移桥，Phase 2+ 可能内化到 adapter
- 现有 `RpcClient` 的 `auth_headers` + `response_unwrapper` 扩展直接服务于 adapter

### D6: SmsAdapter — 独立 httpx + API Key

**选择**: `SmsAdapter` 使用独立 `httpx.AsyncClient`，认证复用 `HttpConnectorConfig` 的 `auth_type`/`auth_token_env`/`auth_header` 模式。

```python
class SmsAdapter:
    def __init__(self, config: IntegrationSystemConfig):
        self._http = httpx.AsyncClient(
            base_url=config.base_url,
            timeout=config.timeout_seconds,
        )
        self._api_key = self._resolve_secret(config.secret_ref)

    async def call(self, capability_key: str, query: Any,
                   auth_context: AuthContext | None) -> Any:
        headers = {"X-API-Key": self._api_key}
        if capability_key == "health.assessment":
            resp = await self._http.post("/api/v1/health/assessment",
                                          json=asdict(query), headers=headers)
            return transform_to_health_assessment(resp.json(), query)
        elif capability_key == "health.anomaly_statistics":
            resp = await self._http.post("/api/v1/anomaly/statistics",
                                          json=query, headers=headers)
            return transform_to_anomaly_stats(resp.json())
        elif capability_key == "health.risk_ranking":
            resp = await self._http.post("/api/v1/risk/ranking",
                                          json=query, headers=headers)
            return transform_to_risk_ranking(resp.json())
```

**理由**:
- `RpcClient` 假设 Java FeignClient 响应格式，Sms 可能是任意 REST API
- httpx 更灵活，adapter 内部处理响应格式
- `transform.py` 纯函数转换，Sms 响应 → canonical model（`HealthAssessment`、`AnomalyStats`、`RiskRanking`）
- API key 从 `secret_ref` 解析，支持环境变量引用

### D7: Agent config.yaml 声明式数据配置

**选择**: Agent `config.yaml` 新增可选 `data_tools` 字段，声明该 Agent 使用哪些能力工具。

```yaml
name: monitoring-analysis
tool_groups:
  - monitoring:pro
skills:
  - data-analyst
data_tools:                    # ← 新增
  - monitoring_get_trend
  - monitoring_get_waveform
  - monitoring_get_alarm_history
  - health_get_assessment
  - asset_get_catalog
```

**效果**:
1. `get_available_tools()` 按 `data_tools` 选择性注入能力工具
2. `apply_prompt_template()` 按 Agent 的 `data_tools` 裁剪 `<data_sources>` prompt 段
3. 未声明 `data_tools` 的 Agent 不受影响（向后兼容）
4. 通配符 `"*"` 注入所有能力工具

**理由**:
- 不是所有 Agent 都需要所有能力工具
- 全量注入 prompt 会导致 token 浪费和 Agent 困惑
- 声明式配置和现有 `tool_groups`、`skills`、`mcp_servers` 模式一致

### D8: 双模式消费 — 推理式工具 + 管道式 subprocess 桥接

**选择**: 推理式和管道式共享同一个 Service 层，但消费方式不同。

**推理式** — Agent 通过 LangChain 工具调用 Service：

```
Agent → monitoring_get_trend(equipment_id="123") ← LangChain tool
      → MonitoringService.get_trend(tenant_id, req)
      → CapabilityRouter → InsAdapter → TrendSeries
      → Tool 格式化为中文 → Agent
```

**管道式** — Agent 通过 bash 调脚本，脚本通过 subprocess 调 Service CLI：

```
Agent → bash query_daily.py --date ... --equipment ...
      → 脚本 subprocess.run(["python", "-m", "deerflow.integrations.cli", ...])
      → CLI → MonitoringService → CapabilityRouter → InsAdapter
      → JSON stdout → 脚本解析 → KPI 计算 → export
```

**理由**:
- 日报/周报的 SOUL.md 写死了 bash 命令和 GenUI 流程，改成工具调用会破坏现有工作流
- 但底层 adapter/service 共享后，新增 Sms 数据只需实现一个 SmsAdapter，两种模式自动获得
- sandbox 脚本不能 import `deerflow.*`（会拉入 langchain），subprocess CLI 绕过这个约束

### D9: RpcClient 扩展向后兼容

**选择**: `RpcServiceConfig` 新增 `auth_headers` 和 `response_unwrapper` 两个可选字段，默认值保持现有行为。

```python
class RpcServiceConfig(BaseModel):
    # ... existing fields ...
    auth_headers: dict[str, str] | None = None
    response_unwrapper: str = "java_standard"
```

`RpcClient._do_request()` 新增 `headers: dict | None = None` 参数。默认 `None` 不改变行为。

**理由**:
- 现有 `ins-base-rpc` 和 `ins-bus-rpc` 不需要任何配置改动
- Sms 服务可以用 `auth_headers: {"X-API-Key": "$SMS_API_KEY"}` + `response_unwrapper: "http_status_only"`
- `test_harness_boundary.py` 不检查配置字段追加

### D10: 外部系统权威边界

**选择**: 明确每个系统的权威数据域，不允许重叠定义。

```
InS（权威）: 设备树、测点、趋势、波形/频谱/轨迹、报警事件
Sms（权威）: 异常统计、健康评估、风险评分、排名与评估历史
CRM（未来）: 客户、合同、装置归属、服务对象信息
ERP（未来）: 工单、备件、库存、维修记录、采购信息
```

**跨系统数据合并规则**:
- 设备主数据以 InS 为准（canonical_id 来自 InS）
- 健康评估以 Sms 为准（InS 不提供）
- enrich 数据标记 `partial_failures`，不覆盖 primary 数据
- 冲突检测：InS 报警 > 0 + Sms 异常 = 0 → 标记 `ConflictRecord`

**理由**:
- 防止"设备到底是谁定义的"这种问题
- enrich 是补充不是覆盖，数据主权清晰
- 冲突检测留给 Service 层，Adapter 不管

## Risks / Trade-offs

### [R1] 三层架构引入间接层

三层比两层多一层 Service，调用链更长。

→ **缓解**: Service 层很薄（路由 + 合并 + provenance），逻辑清晰。调试时 `source_system` + `fetched_at` 提供完整追踪链。

### [R2] Canonical Model 版本演进

新增系统可能需要扩展 canonical model 字段。

→ **缓解**: frozen dataclass 用 `metadata: dict[str, Any]` 存放扩展字段。大版本变更走 `config_version` 迁移。

### [R3] EntityLink 完整性

不同系统的 ID 映射可能不完整。

→ **缓解**: `EntityLink.confidence` 标注映射可信度。查询时缺失映射 → 返回 `EntityLinkNotFound` 错误，不静默忽略。

### [R4] 管道式脚本 subprocess 桥接增加延迟

subprocess 调用比直接 import 慢（Python 启动开销 ~100ms）。

→ **缓解**: 日报/周报是批处理场景，100ms 可忽略。如果成为瓶颈，可以考虑 Unix socket 长连接。

### [R5] 租户隔离粒度

初期配置在 `config.yaml`，所有租户共享。

→ **缓解**: Phase 1 用 `tenant_id` 过滤路由表。Phase 2 迁移到 per-tenant REST API 管理。

### [R6] Prompt 膨胀

Agent 声明了全部 data_tools 时 prompt 段可能很长。

→ **缓解**: prompt_builder 有 token 预算（默认 800 tokens），超出时按 reliability 排序截断。

## Migration Plan

**Phase 1（本次变更，2 周）**: 三层架构 + InsAdapter + 推理式工具

- 新增 `deerflow/integrations/` 模块（models + adapters + services + routing + registry）
- 新增 `IntegrationSystemConfig`、`CapabilityRouteConfig`、`EntityLinkConfig` 配置模型
- 新增 `InsAdapter`（委托 MachineServiceClient + 扩展监测端点）
- 新增 `SmsAdapter`（httpx + API Key）
- 新增 `AssetService`、`MonitoringService`、`AssessmentService`
- 新增 `CapabilityRouter`（primary + enrich + fallback）
- 新增能力工具（LangChain `@tool`）
- Agent `config.yaml` 新增 `data_tools` 字段
- `get_available_tools()` 按 `data_tools` 注入工具
- `apply_prompt_template()` 按 `data_tools` 裁剪 prompt 段
- `RpcClient` 扩展（`auth_headers`、`response_unwrapper`、`health_check()`）
- `INTEGRATION_SYSTEM` 能力类型 + `/api/tenants/{tenant_id}/integration-systems` 路由
- `monitoring-analysis` Agent 配置 `data_tools` 作为试点

**Phase 2（后续 sprint，1 周）**: 管道式脚本底层迁移

- 平台层提供 CLI 入口（`python -m deerflow.integrations.cli`）
- `query_daily.py` 等脚本内部从 features-tool 切换到 subprocess 调 CLI
- 旧 `_ins_provider.py` 保留作为 fallback
- 回归测试确认日报/周报/月报输出格式不变

**Phase 3（清理 + 扩展，1 周）**: 清理 + CRM/ERP 接入

- 确认所有脚本走平台 Service
- 移除 `_ins_provider.py` 中的 features-tool import
- 按同模式接 CRM adapter（客户、合同）
- 按同模式接 ERP adapter（工单、备件）
- EntityLink 迁移到数据库（如果需要）

**回滚策略**: `integrations.enabled: false` → Agent 回退到现有工具集，零影响。管道式脚本 `USE_PLATFORM=false` 回退到 features-tool。

## Open Questions

1. **Sms 认证方式**: API Key、OAuth、还是与 Ins 共享认证？当前假设独立 API Key。
2. **Sms API 文档**: 需要 Sms 团队提供完整 API 文档。
3. **EntityLink 初始数据**: InS 和 Sms 的设备 ID 是否完全一致？是否有现成映射表？
4. **多租户存储**: EntityLink 和 CapabilityRoute 是否需要 per-tenant 数据库存储？初期 YAML 是否足够？
5. **CLI 入口设计**: `deerflow.integrations.cli` 的参数格式和输出格式需要定义。
6. **features-tool 定位**: features-tool 保留为"算法执行器"还是逐步废弃？
