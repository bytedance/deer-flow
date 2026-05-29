# Report Integration Migration - Technical Design

## Context

DeerFlow 的外部系统集成层（`integrations/`）已在 `external-systems-integration` 变更中建好基础架构：Adapter → Service → Tool 三层、CapabilityRouter、canonical models、CLI 桥接。但 AI 报告的数据获取仍停留在过渡状态：

- **旧路径** `_ins_provider.py`：sync wrapper 已全部 raise `HttpProviderError`（Phase 3 废弃），但 KPI 聚合逻辑（`_KPI_FEATURE_MAP`、`_aggregate_trend_to_kpi`、`_hourly_runtime_rate`）仍只存在于该模块
- **桥接层** `_platform_bridge.py`：调用 CLI 子进程，返回 canonical model JSON
- **数据转换** `_transform_canonical_to_script_shape`：返回全空占位（KPI 全 None、hourly 全 0），导致报告功能实际不可用
- **报告脚本** `query_daily/weekly/monthly.py`：有 platform 路径分支但无实际数据

核心问题不只是"聚合逻辑放哪"，而是三类职责没有分清：

1. **平台通用数据获取**（`monitoring.trend` 返回原始趋势点）— 任何 Agent / 工具可消费
2. **系统特有数据解释**（`position_type 22-30 + endpoint_series 2k → vibration_velocity_rrms`）— 只有理解 InS 数据模型的代码才能做
3. **报告业务组装**（`current + compare + hourly_runtime_rate → 输出 JSON`）— 只属于报告 Agent / skill

## Scope

**In-scope**: `query_daily.py`、`query_weekly.py`、`query_monthly.py` 三个报告脚本的平台桥接路径修复。

**Out-of-scope（本次不迁移）**:

- `query_trend.py` — 模板已标记 `provider: platform`，但脚本不读 `USE_PLATFORM`，仍走 `_data_provider_impls.fetch_with_fallback()` 路径。趋势报告的数据模型（time_series per metric + forecast）与 KPI 聚合模式差异较大，需单独设计
- `query_fault_context.py` — 模板已标记 `provider: platform`，但脚本同样不读 `USE_PLATFORM`，走 `_data_provider_impls` 的 `fault_context` source。诊断报告涉及 operations/alarms/work_orders/maintenance_records 多源数据，需独立迁移
- 上述两个脚本当前在 `USE_PLATFORM=true` 环境下会 fallback 到 demo/synthetic 数据，不会报错但也不会返回真实数据

## Goals / Non-Goals

**Goals:**

- 建立三层分离：平台通用能力 / 系统特有计算 / 报告业务组装，各层独立演进
- 将 KPI 聚合逻辑从报告脚本/废弃 provider 迁移到 adapter 内部纯函数模块，通过 CLI action 暴露
- 报告脚本通过基础能力获取原始数据 + CLI action 做聚合 + 自身组装报告结构
- 不新增 `report.*` 能力键路由，复用现有 `monitoring.*` / `alarm_history` 路由
- 保留报告脚本的 CLI 参数和输出 JSON shape 完全不变（向后兼容）
- 支持多设备批量查询，避免脚本在循环中多次调用单个 capability

**Non-Goals:**

- 不重构报告 DSL schema 或 `data_runner.py` 的执行模型
- 不引入新的外部系统 adapter（仅扩展现有 `InsAdapter`）
- 不改变 Agent 的 SOUL.md 或 prompt 模板（Agent 不感知数据源切换）
- 不实现 CRM/ERP 相关的报告能力（本报告迁移仅覆盖 InS 监测数据）
- 不迁移 diagnosis 报告的复杂诊断逻辑（仅迁移其数据获取部分）
- 不为报告新增 capability key（`report.*` 命名空间不存在）

## Decisions

### Decision 1: 聚合逻辑作为 adapter 内部纯函数，而非 capability key

**选择**: 在 `InsAdapter` 包内新增 `kpi_aggregator.py` 纯函数模块，通过 CLI `--action` 模式暴露，不作为 capability key 注册。

**理由**: KPI 聚合不是"平台通用能力"——它强依赖 InS 特有的数据模型概念（`position_types` 22-30/61-64/81-83、`endpoint_series` 2k/6k/8k/9k、`alarm_thresholds` B/C/D 三级）。如果暴露为 capability key，意味着任何 adapter（包括未来的 SMS adapter）都必须实现相同的 `report.daily_kpi` 接口——但它们的数据模型完全不同。

**三层边界对照**:

| 层 | 内容 | 暴露方式 | 消费者 |
| --- | --- | --- | --- |
| 平台通用能力 | `monitoring.trend` 返回原始点序列 | capability key + router | 任何 Agent tool / 脚本 |
| 系统特有计算 | `kpi_aggregator` 将原始点聚合为 KPI | CLI `--action` | 需要 KPI 的脚本 / Agent |
| 报告业务组装 | current + compare + output JSON | 脚本内部逻辑 | 仅报告 skill |

**替代方案**: 新增 `report.daily_kpi` capability key + adapter handler。问题：

- 路由配置膨胀（每个报告类型一个 route）
- 其他 adapter 被迫实现相同接口（SMS 没有 `position_types`）
- 报告结构变更（如新增 compare 基线）需要改 adapter handler，违反分层

### Decision 2: CLI 新增 `--action` 模式与 `--capability` 互斥

**选择**: `cli.py` 新增 `--action` 参数，支持 `aggregate_kpi` / `select_points` 操作。`--action` 和 `--capability` 互斥，action 模式不走 CapabilityRouter。

**理由**: action 操作的是 adapter 内部的知识（InS 数据模型解释规则），不是跨系统路由的能力。走 router 会引入不必要的 adapter 查找和路由调度开销，且语义不对——router 解决的是"这个能力从哪个系统取"的问题，action 解决的是"拿到数据后怎么计算"的问题。

```bash
# capability 模式：跨系统路由，返回原始数据
python -m deerflow.integrations.cli \
    --capability monitoring.trend \
    --params '{"equipment_ids": ["E1"], "start_time": "...", "end_time": "..."}'

# action 模式：直接调用 adapter 内部计算，返回聚合结果
python -m deerflow.integrations.cli \
    --action aggregate_kpi \
    --adapter ins_prod \
    --params '{"trend_data": {...}, "kpi_keys": ["runtime_rate"], "eq_type": "rotating_machinery"}'
```

**替代方案**: 脚本直接 `import kpi_aggregator`。问题：脚本是 subprocess 运行的（`data_runner.py` 通过 `subprocess.run` 调用），虽然同一个 venv 理论上可以 import，但这打破了 subprocess 隔离的设计意图，且让 skill 脚本对 harness 内部模块产生直接依赖。

### Decision 3: 报告脚本编排两次调用，而非一次调用返回聚合结果

**选择**: 报告脚本的 platform bridge 路径做两步：

1. 调用 `monitoring.trend`（capability）获取原始趋势数据
2. 调用 `aggregate_kpi`（action）将原始数据聚合为 KPI

脚本自身负责报告结构组装（current + compare + hourly + output JSON）。

**理由**: 这让报告脚本保持对报告结构的完全控制权。如果未来报告需要新增 compare 基线（如同环比）、新增字段、改变输出格式，只需改脚本，不需要改平台层。

```python
# query_daily.py platform 路径
def fetch_day_with_provenance(date_str, equipment_ids, kpi_keys, eq_type, ...):
    if is_platform_mode():
        # Step 1: 获取原始数据（基础能力）
        trend_result = call_capability("monitoring.trend", {
            "equipment_ids": equipment_ids,
            "start_time": day_start, "end_time": day_end,
        })
        alarm_result = call_capability("monitoring.alarm_history", {...})

        # Step 2: KPI 聚合（系统特有计算）
        kpi_result = call_action("aggregate_kpi", adapter="ins_prod", params={
            "trend_data": trend_result["data"],
            "kpi_keys": kpi_keys,
            "eq_type": eq_type,
        })

        # Step 3: 报告结构组装（报告特有逻辑）
        return {
            "kpis": kpi_result["data"]["kpis"],
            "hourly_runtime_rate": kpi_result["data"]["hourly_runtime_rate"],
            "alarms": alarm_result["data"],
            ...
        }
```

**替代方案**: adapter handler 一次调用返回完整聚合结果。问题：报告结构（current/compare 的组装方式）被硬编码在 adapter 中，报告需求变更需要改平台层。

### Decision 4: 扩展现有 Query 对象而非新建报告 Query

**选择**: 在 `TrendQuery` 上新增可选的 `equipment_ids: tuple[str, ...]` 和 `eq_type: str` 字段，而非新建 `DailyKpiQuery`。

**理由**: 基础能力需要支持多设备批量查询——这不仅服务于报告，dashboard、分析 Agent 也需要。扩展 `TrendQuery` 让这些消费者都能受益。报告脚本不再需要新建 Query 类型（因为不存在 `report.*` 能力键）。

```python
@dataclass(frozen=True)
class TrendQuery:
    tenant_id: str
    asset_id: str | None = None              # 单设备（向后兼容）
    measurement_point_id: str | None = None   # 单测量点（向后兼容）
    equipment_ids: tuple[str, ...] = ()       # 多设备批量（新增）
    eq_type: str = "all"                      # 设备类型过滤（新增）
    start_time: datetime | None = None
    end_time: datetime | None = None
    aggregation: str = "avg"
    sample_interval: str = "1h"
```

### Decision 5: 聚合代码提取到 adapter 包内纯函数模块

**选择**: 将 `_ins_provider.py` 中的聚合逻辑提取到 `deerflow/integrations/adapters/ins/kpi_aggregator.py`，adapter 通过 `get_aggregator()` 方法暴露给 CLI action。

**理由**:

- 聚合逻辑是纯函数（输入趋势行 → 输出 KPI 标量），易于提取和测试
- 放在 adapter 包内（`adapters/ins/`）明确表达"这是 InS 特有的知识"
- `_KPI_FEATURE_MAP` 已在 `integrations/adapters/ins/kpi_map.py` 中有副本，聚合模块复用该副本
- 提取后可对聚合逻辑做独立单元测试，确保与旧路径输出一致
- 未来如果 SMS adapter 有自己的 KPI 计算规则，它在自己的包内实现，不共享 `kpi_aggregator`

## Risks / Trade-offs

- **两次 subprocess 调用**: 报告脚本需要先调 capability 再调 action，两次 subprocess 开销。→ 可接受的代价。未来可优化为一次 `--capability monitoring.trend --then-action aggregate_kpi` 管道模式。超时时间从默认 60 秒调整为 300 秒（月报 31 天 × 2 次调用场景需要更长窗口）
- **脚本编排复杂度**: 报告脚本需要编排两步调用 + 自身组装，比一次调用返回结果复杂。→ 这是正确的职责分配——报告结构是报告的事。且当前脚本已经有 `_fetch_day_via_platform` 的编排框架，只需替换空转换逻辑
- **数据一致性风险**: KPI 聚合逻辑迁移后，新旧路径可能产生微小数值差异。→ 通过端到端对比测试验证：对同一组输入数据，新旧路径输出的 KPI 值差异 < 0.001%
- **CLI action 的认证**: action 模式不走 router，但仍需要 adapter 实例（adapter 持有认证信息）。→ CLI action 通过 `--adapter ins_prod` 指定 adapter key，CLI 从 registry 获取已初始化的 adapter 实例

## Migration Plan

**当前仓库基线**（迁移起点，非目标状态）：

- 4 个模板（daily/weekly/monthly/trend）已有 `provider: platform`
- `data_runner.py` 已在注入 `USE_PLATFORM=true`
- `_ins_provider.py` sync wrapper 已直接 `raise HttpProviderError`
- `_platform_bridge.py` 的 `_transform_canonical_to_script_shape` 返回全空占位
- `query_daily/weekly/monthly.py` 已有 `is_platform_mode()` 分支和 `_fetch_*_via_platform()` 框架，但数据转换层返回空数据
- `query_trend.py` / `query_fault_context.py` 不读 `USE_PLATFORM`，走 `_data_provider_impls` 路径

**回滚说明**：移除模板的 `provider: platform` **不能**回滚到旧路径——旧路径的 sync wrapper 已直接报错。回滚只会导致脚本走到 `_ins_provider.py` 的 `raise HttpProviderError` 分支。因此本次迁移没有"无损回滚"选项，只能向前修复。

### Phase 1 — 聚合层（adapter 内部纯函数）

- 创建 `kpi_aggregator.py`，从 `_ins_provider.py` 提取聚合逻辑
- 独立单元测试，确保与旧路径输出一致

### Phase 2 — CLI action 模式

- `cli.py` 新增 `--action` 参数（与 `--capability` 互斥）
- `InsAdapter` 新增 `get_aggregator()` 方法

### Phase 3 — Query 扩展

- 扩展 `TrendQuery` / `AlarmHistoryQuery` 支持批量参数
- adapter handler 适配批量查询

### Phase 4 — 脚本桥接修复（核心工作）

- 重写 `query_daily.py` `_fetch_day_via_platform()`：capability + action 两步调用
- 重写 `query_weekly.py` `_fetch_week_via_platform()`：同上
- 重写 `query_monthly.py` `_fetch_month_via_platform()`：同上
- 修复 `_transform_canonical_to_script_shape()` 返回真实数据而非空占位

### Phase 5 — 验证

- 端到端对比测试：platform 路径输出 vs 旧路径输出（对同一组输入数据）
- 确认 daily/weekly/monthly 报告在 `USE_PLATFORM=true` 下生成完整报告
