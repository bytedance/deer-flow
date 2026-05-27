## Context

DeerFlow 当前已有一套完善的工具体系：

1. **`http_connector_tool`**：通用的 HTTP 端点调用工具，支持租户隔离、认证（bearer/api_key）、重试、缓存、响应截断。配置存储在 `config.yaml` 的 `http_connectors` 段，按 `tenant_id` 分组。
2. **MCP Server 集成**：通过 `extensions_config.json` 声明 MCP 服务器，运行时通过 `get_cached_mcp_tools()` 加载，支持热更新。
3. **社区工具**：位于 `deerflow/community/` 下的 Python 工具模块（如 tavily、jina_ai），在 `config.yaml` 的 `tools:` 段注册。
4. **Skills 体系**：通过 `SOUL.md` 声明工作流，引导 Agent 按步骤调用工具完成任务。
5. **报告模板平台**：DSL 定义模板结构，运行时通过 GenUI 渲染表单和报告。

前端 GenUI 组件（`DeviceSelectorBlock`、`OrgTreePanel`）已直接调用 INS REST API 获取设备树和测点数据，但后端 Agent 无法使用这些数据。

**约束条件**：
- 必须复用现有的租户隔离机制（`get_current_tenant_id()`）
- 必须兼容现有的 `get_available_tools()` 工具加载流程
- 不能修改 Harness → App 的依赖边界（`test_harness_boundary.py`）
- 前端已有的 INS 调用不受影响

## Goals / Non-Goals

**Goals:**

- 让诊断 Agent 能在对话中实时查询 INS 设备数据（设备详情、测点趋势、振动频谱、历史报警、同类对标）
- 支持三种集成模式（社区工具 / MCP Server / Skill 内嵌），不同部署场景可灵活选择
- 报告模板可声明 INS 数据需求，运行时自动注入 Agent 上下文
- 所有 Agent（lead_agent、monitoring-analysis、device-diagnosis、trend-report）均可平等使用 INS 工具
- 平滑迁移：不破坏现有业务，新工具与现有 `http_connector_tool` 共存

**Non-Goals:**

- 不替代前端 GenUI 组件的 INS 调用（前端保持直接调用 INS API）
- 不在 DeerFlow 中存储 INS 数据副本（始终实时查询）
- 不构建工业设备模型库（数据来自 INS，DeerFlow 只做消费）
- 不实现 INS 数据的写入操作（只读）
- 不处理 INS API 的 WebSocket/流式推送（仅 REST 请求-响应）

## Decisions

### Decision 1：社区工具优先，MCP Server 可选

**选择**：先以社区工具模式（`deerflow/community/ins/`）上线，MCP Server 作为可选的标准化封装。

**理由**：
- 社区工具模式开发量最小，直接复用 `http_connector_tool` 的底层基础设施
- 社区工具在 `config.yaml` 的 `tools:` 段注册，与现有工具加载流程完全兼容
- MCP Server 需要额外的进程管理和协议适配，适合作为后期跨平台共享时的升级路径
- 两种模式可以共存：社区工具提供核心能力，MCP Server 提供标准化接口

**替代方案**：
- 仅 MCP Server：开发周期长，需要维护额外的 MCP 进程，不适合快速验证
- 仅 Skill 内嵌（用 web_fetch 调 INS）：不稳定，LLM 容易拼错参数，无法利用认证和缓存

### Decision 2：复用 `http_connector_tool` 基础设施

**选择**：INS 工具基于现有的 `HttpConnectorConfig` 和 `http_connector_tool` 构建，而不是从头写 HTTP 客户端。

**理由**：
- `http_connector_tool` 已经实现了租户隔离、认证、重试、缓存、响应截断等企业级特性
- INS API 的调用模式（GET/POST + JSON）与 `http_connector_tool` 的能力完全匹配
- 配置复用：管理员在 `config.yaml` 的 `http_connectors` 段添加 INS 端点即可，无需新的配置格式

**替代方案**：
- 独立 HTTP 客户端：重复造轮子，维护两套认证/重试/缓存逻辑

### Decision 3：工具粒度 — 5 个语义化工具

**选择**：封装 5 个语义化的 INS 工具，而不是 1 个通用的"调 INS API"工具。

| 工具名 | 功能 | 输入 | 输出 |
|--------|------|------|------|
| `ins_get_device_detail` | 获取设备详情 | `device_id` | 测点列表、阈值、基础信息 |
| `ins_get_measurement_trend` | 获取测点趋势 | `point_id`, `time_range` | 时间序列数据 |
| `ins_get_vibration_spectrum` | 获取振动频谱 | `device_id`, `timestamp` | 频谱数据 |
| `ins_get_alarm_history` | 获取历史报警 | `device_id`, `limit` | 报警记录列表 |
| `ins_get_peer_comparison` | 同类设备对标 | `device_id` | 同型号设备统计 |

**理由**：
- LLM 更容易理解语义化工具名（"获取设备详情" vs "调用 INS API"）
- 每个工具有明确的输入/输出 schema，减少 LLM 幻觉
- 诊断 Skill 的 SOUL.md 可以按步骤引用具体工具名
- 与 `http_connector_tool` 的 `connector_name` 模式互补：`http_connector_tool` 适合通用场景，INS 工具适合需要领域语义的场景

**替代方案**：
- 1 个通用 `ins_query` 工具：灵活但 LLM 使用困难，需要传入 API 路径和参数结构
- 更多工具（10+）：增加 LLM 选择负担，收益递减

### Decision 4：工具实现层 — Provider 模式

**选择**：使用 Provider 模式，将 INS API 调用封装为 `InsProvider` 类，工具函数委托给 Provider。

```python
class InsProvider:
    """INS REST API 客户端，封装认证、租户隔离、缓存"""
    def __init__(self, connector: HttpConnectorConfig, tenant_id: str): ...
    async def get_device_detail(self, device_id: str) -> dict: ...
    async def get_measurement_trend(self, point_id: str, time_range: str) -> dict: ...
    # ...

# 工具函数通过 Provider 调用
@tool("ins_get_device_detail")
async def ins_get_device_detail(device_id: str) -> str:
    provider = get_ins_provider()
    data = await provider.get_device_detail(device_id)
    return format_for_agent(data)
```

**理由**：
- 关注点分离：Provider 负责 HTTP 调用和数据格式化，工具函数负责 LLM 交互
- 可测试：Provider 可以独立于 LangChain 工具框架进行单元测试
- 可复用：同一 Provider 可被社区工具和 MCP Server 共用
- 数据格式化：Provider 可以将 INS 原始响应格式化为 Agent 友好的文本（如将 JSON 转为 Markdown 表格）

### Decision 5：模板声明式数据绑定

**选择**：在报告模板 DSL 中新增 `ins_data_requirements` 字段，声明模板运行时需要哪些 INS 数据。

```yaml
# 模板 DSL 示例
form_steps:
  - id: select_device
    type: device_selector
    filter_device_type: 4  # 离心泵

ins_data_requirements:
  - tool: ins_get_device_detail
    bind_from: form_steps.select_device.device_id
  - tool: ins_get_alarm_history
    bind_from: form_steps.select_device.device_id
    params:
      limit: 10
```

**理由**：
- 声明式：模板作者不需要写代码，只需声明需要什么数据
- 运行时注入：模板执行时，系统自动调用声明的工具并将结果注入 Agent 上下文
- 与现有模板系统兼容：`ins_data_requirements` 是 DSL 的可选扩展字段，不影响现有模板

### Decision 6：Agent 工具发现 — 零配置

**选择**：INS 工具注册到 `get_available_tools()` 后，所有 Agent 自动可用，无需在 Agent 配置中显式声明。

**理由**：
- 与现有工具加载机制一致：`get_available_tools()` 返回的所有工具对所有 Agent 可见
- Agent 的 SOUL.md 通过工具名引用即可，不需要修改 Agent 工厂代码
- 如果某个 Agent 不需要 INS 工具，可以在 SOUL.md 中不提及，LLM 不会主动调用

## Risks / Trade-offs

### Risk 1: INS API 可用性影响 Agent 响应

**风险**：INS API 超时或不可用时，Agent 工具调用失败，用户等待时间长。

**缓解**：
- `http_connector_tool` 已有超时控制（默认 30s）和重试机制（默认 1 次）
- 工具返回友好的错误信息（"INS 服务暂时不可用，请稍后重试"），而不是原始异常
- Agent SOUL.md 中声明降级策略：当 INS 工具不可用时，基于用户提供的数据进行分析

### Risk 2: INS 返回数据过大，撑爆上下文窗口

**风险**：振动频谱、历史趋势等数据量可能很大（数万条记录），直接注入 Agent 上下文会消耗大量 token。

**缓解**：
- Provider 层做数据摘要：趋势数据只返回统计摘要（最大/最小/平均/标准差）+ 异常点，不返回全量时间序列
- `http_connector_tool` 已有 `max_response_bytes` 截断机制（默认 512KB）
- 缓存策略：同一对话轮次内相同查询复用缓存（`cache_ttl_seconds`）

### Risk 3: LLM 误用工具参数

**风险**：LLM 可能传入错误的 `device_id` 或不合理的 `time_range`。

**缓解**：
- 工具函数做输入验证（device_id 格式、time_range 枚举值）
- 工具返回可用设备列表时包含 `device_id`，减少 LLM 猜测
- 诊断 Skill 的 SOUL.md 声明标准流程：先用 `ins_get_device_detail` 确认设备存在，再查其他数据

### Risk 4: 多租户数据隔离

**风险**：租户 A 的 Agent 可能通过 INS 工具访问租户 B 的设备数据。

**缓解**：
- 复用 `http_connector_tool` 的租户隔离机制（`get_current_tenant_id()` + `http_connectors` 按 tenant 分组）
- INS Provider 在初始化时绑定 tenant_id，所有 API 调用自动携带租户上下文
- 与前端 GenUI 组件的租户隔离保持一致

## Migration Plan

### 现有 INS 集成现状分析

当前系统有三条独立的 INS 数据通路：

| 通路                    | 调用方式                                | 使用方                                                              | 职责                                                   |
| ----------------------- | --------------------------------------- | ------------------------------------------------------------------- | ------------------------------------------------------ |
| **前端 GenUI**          | 浏览器直接调 INS REST API               | `DeviceSelectorBlock`、`OrgTreePanel`                               | 设备树展示、设备选择交互                               |
| **沙箱脚本**            | bash → Python 脚本 → INS API            | `query_daily.py`、`query_trend.py`、`run_pump_rule_diagnosis.py`   | 数据查询 + 复杂计算（FFT、规则匹配、Pearson、IQR）     |
| **http_connector_tool** | Agent 调用通用 HTTP 工具                 | 所有 Agent                                                          | 通用 HTTP 端点调用（无 INS 语义）                      |

**关键发现**：沙箱脚本通过 `INS_ACCESS_TOKEN`（运行时自动注入）和 `INS_BASE_URL` 环境变量直接调 INS API。脚本执行的是**数据查询 + 复杂计算**（规则匹配、FFT、Pearson 相关、IQR 异常检测等），不是简单的 CRUD 操作。

### 核心设计原则：补充，非替代

**INS 语义化工具不是替代脚本，而是补充脚本做不到的事**：

| 场景                           | 当前做法                                                         | 新工具能做什么                                         |
| ------------------------------ | ---------------------------------------------------------------- | ------------------------------------------------------ |
| 诊断一台泵                     | bash → `run_pump_rule_diagnosis.py`（拉数据 + 规则匹配 + 报告）  | **不可替代** — 脚本做的计算工具做不了                  |
| 用户问"P-101 最近有没有报警"   | Agent 无法直接回答（要跑脚本才知道）                             | `ins_get_alarm_history("P-101")` 立即返回              |
| 用户说"看看这台设备的情况"     | Agent 不知道有哪些测点                                           | `ins_get_device_detail("P-101")` 返回测点清单          |
| 生成日报                       | bash → `query_daily.py`（批量计算 KPI）                          | **不可替代** — 批量计算需要脚本                        |
| 报告需要 INS 数据上下文        | 脚本内部拉取                                                     | 模板声明 `ins_data_requirements` 自动注入              |

**结论**：脚本做重活（规则匹配、FFT、批量 KPI），工具做轻活（设备查询、报警查看、对标分析）。两条路并行，互不干扰。

### 三层叠加迁移策略

#### 第 1 层：新工具上线（不改任何东西）

```text
✓ 实现 InsProvider + 5 个工具函数
✓ config.yaml 添加 INS 连接器配置（复用 http_connectors）
✓ get_available_tools() 注册新工具
✓ 现有脚本、SOUL.md、前端 全部不动
✓ 现有业务 100% 不受影响
```

**验证点**：

- pump-diagnosis Agent 原有流程完整跑通（不改 SOUL.md）
- monitoring-analysis Agent 原有流程完整跑通
- ai-report--daily Agent 原有流程完整跑通
- 前端设备选择器正常工作
- 新工具能成功调用 INS API 并返回格式化数据

#### 第 2 层：SOUL.md 增强（可选，不改脚本）

在现有 SOUL.md 中**增加** INS 工具的引用段落，**不删除**任何现有步骤：

```markdown
## INS 工具辅助（新增段落）

在首次进入时，如果用户已提供设备 ID，可以先调用 INS 工具获取设备上下文：
- 调用 <tool>ins_get_device_detail</tool> 确认设备存在并获取测点列表
- 调用 <tool>ins_get_alarm_history</tool> 获取最近报警，为诊断提供背景

这些工具调用是**可选的辅助步骤**，不影响后续脚本执行。
如果 INS 工具不可用，直接跳到子设备选择器。
```

**验证点**：

- SOUL.md 增强后，Agent 能在用户对话中主动调用 INS 工具
- INS 工具不可用时，Agent 降级到原有脚本流程（不报错）

#### 第 3 层：模板集成（可选，向后兼容）

```yaml
# 模板 DSL 中 ins_data_requirements 是可选字段
# 不填 = 按原有方式运行（脚本拉数据）
# 填了 = 运行时自动注入 INS 数据到 Agent 上下文
ins_data_requirements:  # 可选，不影响现有模板
  - tool: ins_get_alarm_history
    bind_from: form_steps.select_device.device_id
    params:
      limit: 10
```

**验证点**：

- 现有模板（不含 `ins_data_requirements`）继续正常工作
- 新模板（含 `ins_data_requirements`）能自动注入 INS 数据
- 注入失败时不阻断报告生成

### 认证迁移

| 通路            | 当前认证方式                               | 新工具认证方式                                                                                         |
| --------------- | ------------------------------------------ | ------------------------------------------------------------------------------------------------------ |
| 沙箱脚本        | `INS_ACCESS_TOKEN` 环境变量（运行时注入）   | **不变**                                                                                               |
| 前端 GenUI      | Bearer token（cookie/session）              | **不变**                                                                                               |
| **新 INS 工具** | —                                          | `HttpConnectorConfig.auth_type: "bearer"` + `auth_token_env: "INS_ACCESS_TOKEN"`（复用同一 token）      |

**关键**：新工具复用 `INS_ACCESS_TOKEN`，不需要新增认证配置。`HttpConnectorConfig` 已经支持 bearer auth + 环境变量 token。

### 配置示例（config.yaml 新增段）

```yaml
http_connectors:
  default:  # 默认租户
    - name: ins-device-detail
      url: $INS_BASE_URL/api/devices/{device_id}
      method: GET
      auth_type: bearer
      auth_token_env: INS_ACCESS_TOKEN
      cache_ttl_seconds: 3600  # 设备详情可缓存 1 小时
      description: "获取 INS 设备详情"

    - name: ins-alarm-history
      url: $INS_BASE_URL/api/devices/{device_id}/alarms
      method: GET
      auth_type: bearer
      auth_token_env: INS_ACCESS_TOKEN
      cache_ttl_seconds: 300  # 报警历史缓存 5 分钟
      description: "获取 INS 设备历史报警"

    - name: ins-measurement-trend
      url: $INS_BASE_URL/api/points/{point_id}/trend
      method: GET
      auth_type: bearer
      auth_token_env: INS_ACCESS_TOKEN
      cache_ttl_seconds: 60  # 趋势数据缓存 1 分钟
      description: "获取 INS 测点趋势数据"

    - name: ins-vibration-spectrum
      url: $INS_BASE_URL/api/devices/{device_id}/spectrum
      method: GET
      auth_type: bearer
      auth_token_env: INS_ACCESS_TOKEN
      cache_ttl_seconds: 0  # 频谱数据不缓存
      description: "获取 INS 振动频谱"

    - name: ins-peer-comparison
      url: $INS_BASE_URL/api/devices/{device_id}/peers
      method: GET
      auth_type: bearer
      auth_token_env: INS_ACCESS_TOKEN
      cache_ttl_seconds: 1800  # 同类对标缓存 30 分钟
      description: "获取 INS 同类设备对标数据"
```

### 多租户隔离验证

```text
[ ] 租户 A 的 Agent 使用租户 A 的 INS_ACCESS_TOKEN 调用 INS API
[ ] 租户 B 的 Agent 使用租户 B 的 INS_ACCESS_TOKEN 调用 INS API
[ ] 租户 A 无法访问租户 B 的设备数据
[ ] http_connectors 配置按 tenant_id 分组，各自独立
```

### 降级策略

#### 场景 1：INS 工具不可用

```text
用户："帮我看看 P-101 的情况"
Agent 尝试调用 ins_get_device_detail("P-101") → 失败
Agent 降级："INS 服务暂时不可用。请选择设备后启动诊断流程。"
Agent 渲染 DeviceSelectorBlock → 用户选择设备 → 启动原有脚本流程
```

#### 场景 2：INS 工具超时

```text
Agent 调用 ins_get_alarm_history("P-101") → 30s 超时
工具返回："INS 服务超时，请稍后重试"
Agent 继续执行后续步骤（不阻断）
```

#### 场景 3：INS 返回数据格式异常

```text
Agent 调用 ins_get_vibration_spectrum("P-101") → INS 返回非 JSON
Provider 记录警告日志
工具返回："INS 返回数据格式异常，请联系管理员"
Agent 跳过该步骤，继续执行
```

### 回滚策略

- **工具级回滚**：删除 `config.yaml` 中的 INS 连接器配置 → 工具不再注册 → 现有业务不受影响
- **SOUL.md 级回滚**：删除 SOUL.md 中的 INS 工具引用段落 → Agent 不再主动调用工具 → 回到纯脚本模式
- **模板级回滚**：删除模板 DSL 中的 `ins_data_requirements` 字段 → 模板按原有方式运行

### 迁移验证清单

```text
[ ] 新工具注册成功，现有脚本不受影响
[ ] pump-diagnosis Agent 原有流程完整跑通（不改 SOUL.md）
[ ] monitoring-analysis Agent 原有流程完整跑通
[ ] ai-report--daily Agent 原有流程完整跑通
[ ] 前端设备选择器正常工作
[ ] 新工具能成功调用 INS API 并返回格式化数据
[ ] 多租户隔离验证（租户 A 和 B 各自使用自己的 token）
[ ] INS 工具不可用时，Agent 降级到原有脚本流程
[ ] INS 工具超时时，Agent 继续执行后续步骤
[ ] 模板 ins_data_requirements 注入成功
[ ] 模板 ins_data_requirements 注入失败时不阻断报告生成
```

### Phase 1: 社区工具上线（2 周）

1. 实现 `InsProvider` 和 5 个工具函数
2. 在 `config.yaml` 添加 INS 端点配置
3. 更新诊断 Skill 的 SOUL.md（可选增强）
4. 内部测试验证

### Phase 2: 模板集成（1 周）

1. DSL 扩展 `ins_data_requirements` 字段
2. 模板运行时注入逻辑
3. 现有模板迁移（可选添加 INS 数据声明）

### Phase 3: MCP Server（可选，2 周）

1. 基于 `InsProvider` 封装 MCP Server
2. 在 `extensions_config.json` 注册
3. 验证与社区工具共存

## Open Questions

1. **INS API 文档**：需要 INS 团队提供完整的 REST API 文档（端点、请求参数、响应格式），以确定工具的具体实现细节
2. **数据格式化策略**：振动频谱数据应该返回原始 JSON 还是格式化为 Markdown 表格？需要与诊断专家确认 Agent 消费数据的最佳格式
3. **缓存粒度**：INS 数据的时效性要求不同（设备详情可缓存 1 小时，振动频谱需要实时），是否按工具分别配置 `cache_ttl_seconds`？
4. **MCP Server 优先级**：MCP Server 是否为 Phase 1 必需？如果仅为 DeerFlow 内部使用，社区工具模式已足够
