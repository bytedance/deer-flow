# HTTP Connectors 接入文档

## 概述

`http_connector` 是 DeerFlow 平台的内置工具（builtin tool），允许 Agent 通过预配置的 HTTP 端点调用外部 API。它提供了一种安全、可控的方式让 Agent 访问外部数据源，无需编写自定义代码。

## 快速开始

### 1. 在 config.yaml 中配置 connector

```yaml
http_connectors:
  default:  # tenant_id，"default" 为默认租户
    - name: list_datasets
      description: "列举可用数据集"
      url: "http://your-api.internal/api/v1/datasets"
      method: GET
      auth_type: bearer
      auth_token_env: YOUR_API_TOKEN
      timeout_seconds: 30
      max_response_bytes: 524288
      max_retries: 1
    - name: fetch_dataset
      description: "获取指定数据集的数据"
      url: "http://your-api.internal/api/v1/datasets/query"
      method: POST
      auth_type: bearer
      auth_token_env: YOUR_API_TOKEN
      timeout_seconds: 60
      max_response_bytes: 1048576
      max_retries: 1
```

### 2. 设置环境变量

```bash
export YOUR_API_TOKEN="your-bearer-token-here"
```

### 3. Agent 自动可用

`http_connector` 是 builtin tool，所有 Agent 自动拥有该工具，无需在 agent 的 `config.yaml` 中额外配置。

## 配置参考

### HttpConnectorConfig 字段

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| `name` | string | 是 | - | Connector 名称，Agent 通过此名称调用 |
| `url` | string | 是 | - | 目标 URL |
| `method` | string | 否 | GET | HTTP 方法：GET / POST / PUT |
| `headers` | dict | 否 | {} | 自定义请求头 |
| `auth_type` | string | 否 | none | 认证类型：none / bearer / api_key |
| `auth_token_env` | string | 否 | null | 存放 token 的环境变量名 |
| `auth_header` | string | 否 | Authorization | 认证 header 名称 |
| `timeout_seconds` | float | 否 | 30.0 | 请求超时时间 |
| `description` | string | 否 | "" | 描述信息，展示给 Agent |
| `max_response_bytes` | int | 否 | 524288 (512KB) | 响应最大字节数，超出截断 |
| `max_retries` | int | 否 | 1 | 最大重试次数（0=不重试） |
| `retry_on_status` | int[] | 否 | [502, 503, 504] | 触发重试的 HTTP 状态码 |
| `cache_ttl_seconds` | int | 否 | null | 响应缓存 TTL（预留字段，当前未实现） |

### 认证方式

**Bearer Token：**
```yaml
auth_type: bearer
auth_token_env: MY_TOKEN  # 环境变量名
# 发送: Authorization: Bearer <token_value>
```

**API Key：**
```yaml
auth_type: api_key
auth_token_env: MY_API_KEY
auth_header: X-API-Key  # 自定义 header 名
# 发送: X-API-Key: <key_value>
```

**无认证：**
```yaml
auth_type: none  # 默认值
```

### 多租户配置

`http_connectors` 以 `tenant_id` 为 key，支持不同租户配置不同的 connector：

```yaml
http_connectors:
  tenant-a:
    - name: list_datasets
      url: "http://tenant-a-api.internal/datasets"
      ...
  tenant-b:
    - name: list_datasets
      url: "http://tenant-b-api.internal/datasets"
      ...
```

Agent 运行时自动根据当前 `tenant_id` 查找对应的 connector 配置。

## Agent 调用方式

Agent 通过 tool call 调用 `http_connector`：

```python
# GET 请求
http_connector(connector_name="list_datasets", params={"limit": 50})

# POST 请求
http_connector(connector_name="fetch_dataset", body={"dataset_id": "ds_001", "limit": 1000})

# GET + query params
http_connector(connector_name="dataset_schema", params={"dataset_id": "ds_001"})
```

**参数说明：**

| 参数 | 类型 | 说明 |
|------|------|------|
| `connector_name` | string | 配置中定义的 connector 名称 |
| `params` | dict | GET 请求的 query 参数；POST/PUT 时合并到 body |
| `body` | dict | POST/PUT 请求的 JSON body |

## 与 MCP 的关系

`http_connector` 是 MCP 的轻量替代方案，适用于：

- 外部 API 已有 REST 接口，不想额外开发 MCP Server
- 快速验证集成，无需部署额外进程
- 简单的 GET/POST 调用场景

**优先级链（data-analyst SOUL.md 中定义）：**

1. **MCP tools**（如 `data_catalog.list_datasets`）— 最优先，功能最完整
2. **http_connector** — 配置驱动，无需额外代码
3. **静态表单** — 兜底方案

如果你的数据平台需要复杂的交互逻辑（如流式返回、WebSocket、多步认证），建议实现 MCP Server。参考 [data_catalog MCP 协议文档](data_catalog_mcp_protocol.md)。

## 安全设计

1. **预配置 URL 防 SSRF**：Agent 只能调用 `config.yaml` 中预定义的 URL，无法构造任意请求
2. **环境变量 Token**：认证凭据不出现在配置文件中，通过环境变量注入
3. **租户隔离**：不同租户的 connector 配置完全隔离
4. **响应截断**：防止超大响应占满 Agent 上下文窗口
5. **重试限制**：可配置的重试策略，防止无限重试

## 可观测性

`http_connector` 每次调用输出结构化日志：

```
INFO  http_connector call  connector_name=list_datasets tenant_id=default status_code=200 latency_ms=156.3 response_size=4521 truncated=false retry_count=0
WARN  http_connector call  connector_name=fetch_dataset tenant_id=default status_code=200 latency_ms=12500.0 response_size=1048576 truncated=true retry_count=0
WARN  http_connector retry connector_name=list_datasets tenant_id=default status_code=503 attempt=1 latency_ms=30012.0
```

**日志字段：**

| 字段 | 说明 |
|------|------|
| `connector_name` | 调用的 connector 名称 |
| `tenant_id` | 当前租户 ID |
| `status_code` | HTTP 响应状态码 |
| `latency_ms` | 请求耗时（毫秒） |
| `response_size` | 原始响应大小（字节） |
| `truncated` | 是否被截断 |
| `retry_count` | 重试次数 |

慢请求（>10s）自动升级为 WARN 级别日志。

## 设备日/周/月报真数据（InS）

设备日报、周报、月报支持通过 InS（神固云）实时拉取数据。该链路只在 data-analyst 脚本内生效，不会改变其它 `http_connector` 的调用方式。

### 启用方式

启用真数据只需要设置：

```bash
export DEER_FLOW_DATA_PROVIDER="ins"
```

可选覆盖项：

```bash
export INS_FACTORY_ID="FAC-001"
```

- `DEER_FLOW_DATA_PROVIDER=ins`：切换 daily / weekly / monthly 三类设备报表脚本到 InS provider
- `INS_FACTORY_ID`：可选工厂维度透传；未设置时不会附加 `factoryId` 参数

### 四类 endpoint series

| Series | 典型设备/测点 | 响应形态 | 典型 KPI |
|---|---|---|---|
| `2k` | 机泵旧版多 feature 振动点（PUMP, `positionType 22..30`） | 嵌套 `value[]`，中文 `name` | `vibration_velocity_rms`、`vibration_acceleration_peak`、`kurtosis_index` |
| `6k` | 静设备腐蚀监测点（PIPELINE, `positionType 61..64`） | 嵌套 `value[]`，英文 `key` | `corrosion_rate`、`thickness_loss`、`thinning_rate` |
| `8k` | 旋转机组默认测点（MAC / RM, `positionType 81..83`） | 扁平 `values` | `vibration_level`、`bearing_temp`、`flow_rate`、`outlet_pressure` |
| `9k` | 高端旋转 / 往复机组（RC, `positionType 91..99`） | 扁平 `values` | `runtime_rate`、`downtime_count`、`alarm_count` 及其它旋转类 KPI |

其中 2k / 6k 需要先在 features-tool 内部做展平；8k / 9k 直接消费扁平响应。

### 2k 名称归一化与阈值语义

2k 响应中的中文 `name` 会先归一化为 ASCII key，核心映射包括：

- `速度有效值` → `v_rms`
- `加速度峰值` → `a_peak`
- `加速度有效值` → `a_rms`
- `位移峰峰值` → `pp_value`
- `包络谱峰值` → `envelope_peak`
- `峭度` → `kurtosis`
- `裕度` → `margin`
- `脉冲指标` → `pulse`
- `波形指标` → `wave`

2k 测点还会透传 `alarm_thresholds`，按 feature 暴露 B/C/D 三级阈值：

- `B`：早期预警
- `C`：告警默认阈值，当前 `alarm_count` 默认按这一层统计
- `D`：危险阈值，用于更严格的高危统计

### 10 个新 skill × 4 endpoint series × 适用设备类型

OpenSpec change `wire-equipment-reports-real-data` §11 引入 10 个新 skill，覆盖 2k/6k/9k 三个非默认 series 的数据获取层，外加 1 个 6k 静设备腐蚀诊断上层。8k 默认 series 复用既有 skill，未列出。

| Skill | Endpoint Series | 适用设备类型 | 角色 |
| --- | --- | --- | --- |
| `ins-get-trend-data-2k` | 2k | PUMP 机泵（多 feature 振动） | 原始趋势数据 |
| `ins-extract-trend-features-2k` | 2k | PUMP | 趋势特征提取 |
| `ins-device-analysis-2k` | 2k | PUMP | 子设备/测点树（含 `alarm_thresholds: {B,C,D}`） |
| `ins-get-trend-data-6k` | 6k | PIPELINE 管线 / 容器 / 塔器 | 原始腐蚀趋势 |
| `ins-extract-trend-features-6k` | 6k | PIPELINE | 腐蚀特征（`thickness_loss` / `thinning_rate_fit`） |
| `ins-device-analysis-6k` | 6k | PIPELINE | 静设备测点树 |
| `ins-get-trend-data-9k` | 9k | RC 往复 / 高端旋转机组 | 原始高密度趋势（client.py 自动注入 `density=high` / `includeFilter=history`） |
| `ins-extract-trend-features-9k` | 9k | RC | 高密度特征 |
| `ins-device-analysis-9k` | 9k | RC | 子设备/测点树 |
| `static-equipment-corrosion-diagnosis` | 6k（上层诊断） | PIPELINE | 腐蚀诊断逻辑 + 4 fault families（`corrosion_rate_anomaly` / `thickness_remaining_life` / `thinning_rate_step_change` / `process_temperature_coupling`） |

**上层 SOUL 选 skill 速查**：

- `fault-diagnosis--pump` SOUL 固定走 `ins-*-2k` 三件套；
- `fault-diagnosis--reciprocating` SOUL 固定走 `ins-*-9k` 三件套；
- 静设备腐蚀诊断走 `ins-*-6k` 三件套 + `static-equipment-corrosion-diagnosis`；
- 默认旋转机组（MAC / RM, positionType 81..83）继续走原 8k 默认 skill（`ins-get-trend-data` / `ins-extract-trend-features` / `ins-device-analysis`）。

### 回退触发条件

当以下任一情况发生时，脚本会自动回退到 demo 数据，并在输出里写入 `data_source="demo_fallback"` 与 `data_notes[]`：

- 网络失败 / 超时 / 401 / 其它 InS 请求异常
- KPI 无法映射到 InS 测点
- 设备不存在或找不到可用测点
- features-tool 不可用
- 对比区间与当前区间来源不一致，需要统一降级

成功走 InS 时，输出为 `data_source="ins"` 且 `data_notes=[]`。

### Docker sandbox 约束

这条链路依赖 `FEATURES_TOOL_ROOT` 指向的 features-tool 与 `ins` 客户端，因此默认面向 Docker sandbox 运行环境设计。脱离该环境时，provider 会显式报错并触发 demo fallback，而不是返回不完整真数据。

更多开发约束见 [backend/CLAUDE.md](../CLAUDE.md)。

## 配置热更新

`config.yaml` 修改后，`http_connectors` 配置会在下次 Agent 调用时自动生效（通过 AppConfig 的 mtime 检测机制），无需重启服务。

## 故障排查

| 问题 | 原因 | 解决方案 |
|------|------|---------|
| "No HTTP connectors configured" | 当前 tenant_id 下无配置 | 检查 config.yaml 中的 tenant_id key |
| "Unknown connector 'xxx'" | connector 名称拼写错误 | 检查 name 字段 |
| "Failed after N attempts: timeout" | 外部 API 超时 | 增大 timeout_seconds 或检查网络 |
| 响应被截断 | 数据量超过 max_response_bytes | 增大限制或在请求中加 limit 参数 |
| 认证失败 (401/403) | Token 未设置或过期 | 检查环境变量是否正确设置 |
