## Context

当前月报数据获取流程：

```
query_monthly.py
  → fetch_with_fallback(source="monthly")
    → get_provider("monthly")  // 硬编码 mode="platform"
      → PlatformMonthlyProvider.fetch()
        → for each day in month:
            call_capability("monitoring.trend", ...)
              → 子进程: python -m deerflow.integrations.cli
                → CapabilityRouter → InsAdapter._handle_batch_trend()
                  → InsClientBridge.get_trend_data() → InS API
            call_action("aggregate_kpi", ...)
              → 子进程: python -m deerflow.integrations.cli
                → InsAdapter.get_aggregator().aggregate_equipment_kpis()
```

`_ins_provider.py` 中已有完整的进程内异步编排逻辑（`_async_fetch_payload`、`_fetch_kpi_for_equipment`、`_fetch_equipment_events` 等），其同步包装器 `fetch_monthly_payload` 当前被替换为 `NotImplementedError` 桩（注释写明 "Use the integrations layer with provider: platform"）。该模块的所有核心逻辑都完好无损：

- `_KPI_FEATURE_MAP` — 声明所有 KPI 如何从 InS 端点映射
- `_select_points_for_kpi` — 从组件树中筛选测点
- `_aggregate_trend_to_kpi` — 6 种聚合方法（mean/max/alarm_count/runtime_rate/downtime_count/thickness_loss）
- `_async_fetch_payload` — 完整的异步编排器：组件缓存 + 批量趋势调用 + KPI 聚合 + 事件获取
- `_fetch_equipment_events` — 批量获取 machine drops 事件

关键约束：月报脚本在沙箱容器内运行，`features-tool`（InS HTTP 客户端）在该环境中可用。

## Goals / Non-Goals

**Goals:**

1. 月报能通过进程内直连 InS API 获取数据，不再通过 integrations CLI 子进程
2. 保留 `platform` 路径作为可选/默认模式，支持向后兼容
3. 通过环境变量 `DEER_FLOW_DATA_PROVIDER=ins` 切换模式，不修改月报的 CLI 参数或输出 schema
4. 复用 `_ins_provider.py` 中已有的异步逻辑，不重新实现 KPI 映射和聚合

**Non-Goals:**

- 不修改日/周报的数据获取路径（它们使用各自的 `_ins_provider.py` 和 `_data_providers.py` 副本）
- 不修改 integrations 层的路由和 adapter 实现
- 不修改前端
- 不处理日/周报的直连迁移（可为后续 change 留口子）

## Decisions

### Decision 1: 复用而非重写 `_ins_provider.py`

**选择**: 恢复 `_ins_provider.py` 中 `fetch_monthly_payload` 的实际实现，而不是在 `_data_provider_impls.py` 中重新调用 InS API。

**替代方案**: 在 `DirectInsMonthlyProvider` 中直接使用 `InsClientBridge`（绕过 `_ins_provider.py`）。

**理由**: `_ins_provider.py` 已有 1439 行经过测试的 InS 交互逻辑（KPI 映射、测点选择、聚合算法、事件格式化）。直接复用这些逻辑零风险，而重写需要重新实现所有 KPI 推导方法和测点过滤逻辑。同时保持与日/周报实现一致性——它们的直连路径也在各自的 `_ins_provider.py` 中。

### Decision 2: 环境变量切换，默认保持 platform

**选择**: 通过 `DEER_FLOW_DATA_PROVIDER` 环境变量选择，默认值为 `platform`（保持当前行为）。

**替代方案**: 直接改为 `ins` 默认值，废弃 platform 路径。

**理由**: 渐进式迁移——允许先在特定租户/场景中验证直连模式的稳定性和性能，确认无误后再考虑将默认值切换为 `ins`。`platform` 路径已有线上流量验证，不应一次性移除。

### Decision 3: 修改 `_resolve_mode` 去掉 `PLATFORM_SOURCES` 硬编码

**选择**: 将 `_resolve_mode` 中的设备报表数据源（`daily`/`weekly`/`monthly`）从硬编码 `platform` 改为从 `DEER_FLOW_DATA_PROVIDER` 读取，默认 `platform`。

**当前代码** (`_data_providers.py:286-303`):
```python
PLATFORM_SOURCES = {"daily", "weekly", "monthly"}

def _resolve_mode(source: str, mode: str | None) -> str:
    if mode is not None:
        return mode.lower()
    if source in PLATFORM_SOURCES:
        return "platform"
    ...
```

**改为**:
```python
def _resolve_mode(source: str, mode: str | None) -> str:
    if mode is not None:
        return mode.lower()
    if source in PLATFORM_SOURCES:
        return os.environ.get("DEER_FLOW_DATA_PROVIDER", "platform").lower()
    ...
```

### Decision 4: `DirectInsMonthlyProvider` 的 fetch 策略

**选择**: 一次异步调用获取整月数据，而非逐日循环。

当前 `PlatformMonthlyProvider.fetch()` 逐日循环（每月 28-31 次调用），每天 2 个子进程。直连模式将在一个 `asyncio.run()` 调用内完成整月数据拉取：

1. 计算整月的时间范围（`month_start` 00:00:00 → `month_end` 23:59:59）
2. 调用 `_async_fetch_payload(period_kind="range", period_args={start, end}, ...)` 获取整月聚合的 KPI + 事件
3. 同时调用 `_async_fetch_daily_series_payload(start_date, day_count, ...)` 获取每日序列用于周桶分组和趋势图

这样整月数据只需 1 次组件树查询 + 若干次批量趋势调用（按 endpoint_series 分组），而非 60 次独立的子进程。

## Risks / Trade-offs

- **[风险] 直连模式下 features-tool 不可用时失败无降级**: `_ins_provider.py` 在 `_FEATURES_TOOL_AVAILABLE=False` 时抛出 `HttpProviderError`
  → **缓解**: 保持 `platform` 为默认模式；用户显式设置 `DEER_FLOW_DATA_PROVIDER=ins` 表示已确认环境有 features-tool

- **[风险] 直连和 platform 路径可能行为差异**: `PlatformMonthlyProvider` 通过 integrations CLI 的 `InsAdapter._handle_batch_trend` + `_select_measurement_points` 获取趋势数据，而 `_ins_provider._select_points_for_kpi` 有更细粒度的 KPI 感知筛选逻辑
  → **缓解**: `_ins_provider` 的筛选逻辑比 `InsAdapter._select_measurement_points` 更精确（考虑了 KPI 特定的 position_type 范围和 name_keywords），直连模式的数据质量应优于或等于 platform 模式。编写对比测试验证两种路径对相同输入产生一致结果

- **[权衡] 内存使用增加**: 整月数据一次性加载到内存（vs 逐日子进程的流式处理）
  → **可接受**: 月度趋势数据量级（一个设备一个月约 30×24×60 = 43200 行原始数据点）远小于可用内存
