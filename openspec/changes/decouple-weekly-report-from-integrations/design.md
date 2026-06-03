## Context

### 当前架构

周报数据流（以 `query_weekly.py` 为例）：

```
query_weekly.py
  → _data_providers.get_provider("weekly") → mode="platform"
    → _data_provider_impls.PlatformWeeklyProvider.fetch()
      → _platform_bridge.call_capability("monitoring.trend", {...})
        → subprocess: python -m deerflow.integrations.cli --capability ...
          → (docker exec 进入 sandbox 容器)
            → CapabilityRouter → InsAdapter._handle_batch_trend()
              → InsClientBridge.get_trend_data()
                → features-tool InsApiClient → InS HTTP API
      → _platform_bridge.call_action("aggregate_kpi", adapter="ins_prod", {...})
        → subprocess: python -m deerflow.integrations.cli --action ...
          → kpi_aggregator.aggregate_equipment_kpis()
```

问题点：
1. **7 天循环 × 2 次 subprocess = 14 次进程启动 + docker exec**，每次都需要初始化整个 integration registry、建立 HTTP 连接
2. `_platform_bridge.py` 需要处理 docker exec 环境变量转发、参数文件复制等容器特化逻辑
3. Integrations 子系统（registry、CapabilityRouter、adapter lifecycle）对纯数据查询来说过于重量级
4. 调试困难：subprocess 错误信息需要跨越三层才能看到

### `_ins_provider.py` 的现状

`skills/custom/weekly-report/scripts/_ins_provider.py`（1439 行）已经包含完整的直接 InS 调用实现：
- `_KPI_FEATURE_MAP` — 所有 KPI 到 InS 端点系列/特性的映射
- `_select_points_for_kpi()` — 从组件树选择匹配的测点
- `_aggregate_trend_to_kpi()` — 趋势行 → 单个 KPI 标量
- `_async_fetch_daily_series_payload()` — 连续多天的单 client 批量拉取（复用连接 + 组件缓存）
- `_async_fetch_payload()` — 单天/单周期的数据拉取
- `_fetch_equipment_events()` — 机器停机事件拉取

但公开的 sync wrapper 被人为设为 `NotImplementedError`：

```python
def fetch_daily_series_payload(...):
    raise NotImplementedError(
        "fetch_daily_series_payload is removed. Use the integrations layer..."
    )
```

## Goals / Non-Goals

**Goals:**
- 周报/日报/月报 skill 直接通过 `_ins_provider.py` 调用 InS API，绕过 integrations subprocess CLI
- 复用已有 `_async_fetch_daily_series_payload` 实现（单 client 复用以减少 TCP 握手）
- 保持输出 schema 完全不变（`data_source="ins"`、`data_notes=[]`）
- 集成测试继续通过（`test_ai_report_weekly_*.py`）
- 同样处理日报/月报，统一三条 report skill 的数据获取模式

**Non-Goals:**
- 不删除或修改 integrations 子系统（InsAdapter、CLI 等保留给其他非报告场景如 monitoring tools）
- 不修改 `query_trend.py` 或其他非 equipment report 的脚本
- 不修改 KPI 聚合算法
- 不修改 DSL 模板或 SOUL.md

## Decisions

### Decision 1: 使用 `_ins_provider.py` 直接路径而非继续走 platform bridge

**选择**: 注册 `InsWeeklyProvider`，直接调用 `_ins_provider._async_fetch_daily_series_payload()`

**理由**:
- `_ins_provider.py` 已有完整实现，只是公开 API 被禁用
- 直接调用消除了 subprocess + docker exec + integration registry 初始化开销
- 单 client 复用：7 天数据在一个 `InsApiClient` 实例上拉取，共用 TCP 连接和组件缓存
- 与现有 `equipment-report-data-provider` spec 的意图一致

**替代方案**: 继续走 platform bridge，但优化 bridge 性能（如单次调用拉取全部 7 天数据）
- 驳回：platform bridge 本质设计是为多系统 capability routing，对 InS 直连场景过度抽象

### Decision 2: Provider 注册模式

**选择**: 在 `_data_provider_impls.py` 中注册 `"ins"` 模式（而非 `"platform"`），并设 `get_provider("weekly")` 的默认模式为 `"ins"`

**理由**:
- 与 `equipment-report-data-provider` spec 要求一致（`list_registered()["weekly"]` 应为 `["ins"]`）
- 取消 `PLATFORM_SOURCES` 常量的特殊处理
- `DEER_FLOW_DATA_PROVIDER` 环境变量对 daily/weekly/monthly 三个 source 不再生效

### Decision 3: 同步包装策略

**选择**: `InsWeeklyProvider.fetch()` 内部调用 `asyncio.run(_async_fetch_daily_series_payload(...))`

**理由**:
- query 脚本是同步 CLI 程序（argparse），需要在同步上下文中获取异步结果
- `_ins_provider.py` 中已有 `_run_async()` helper
- 单个 `asyncio.run()` 创建单一 event loop，内部 7 天数据协程式拉取

### Decision 4: 日报/月报同步处理

**选择**: 日报的 `PlatformDailyProvider` 和月报的对应 provider 同样改为直接 InS 路径

**理由**:
- 三条 report skill 有相同的架构问题
- 统一处理减少后续维护成本
- 日报已有 `_ins_provider._async_fetch_payload()` 实现

## Risks / Trade-offs

- **[Risk] features-tool 不可用时行为变化**: 当前 platform bridge 模式在 features-tool 不可用时会抛 `PlatformBridgeError`，新路径会抛 `HttpProviderError("features-tool not available...")` → 错误类型不同但最终都渲染为 `{"error": ...}`，行为等价
- **[Risk] InS API 连接超时**: 直接路径少了 integrations 层的 retry policy → `_ins_provider.py` 中的 `InsApiClient` 本身已有超时配置（从 `load_ins_settings()` 读取），且 `_data_providers.fetch_with_fallback` 不再使用（无 demo fallback），错误直接传播
- **[Risk] subprocess 隔离性丧失**: platform bridge 通过 subprocess 隔离了 InS 客户端的 crash → 直接路径中 crash 会影响 query 脚本进程。但 `InsApiClient` 是纯 HTTP 客户端，crash 风险极低
- **[Trade-off] `_platform_bridge.py` 删除后，未来若有新的非 InS 数据源需要通过 integrations 获取数据，需要重新实现桥接** → 当前没有此需求；若需要，可根据当时场景重新设计更轻量的桥接方式

## Migration Plan

1. 修改 `_data_provider_impls.py`：注册 `InsWeeklyProvider` 替换 `PlatformWeeklyProvider`
2. 恢复 `_ins_provider.py` 中 `fetch_daily_series_payload` 的实现（移除 `NotImplementedError`）
3. 修改 `_data_providers.py`：移除 `PLATFORM_SOURCES`，将 daily/weekly/monthly 的默认模式改为 `"ins"`
4. 同样处理日报、月报的 provider
5. 删除三个 skill 目录下的 `_platform_bridge.py`
6. 运行 `test_ai_report_weekly_*.py`、`test_ai_report_daily_*.py` 等集成测试确认无回归
7. 部署：零停机，skills 脚本按需加载，无持久化状态变更

## Open Questions

- 无
