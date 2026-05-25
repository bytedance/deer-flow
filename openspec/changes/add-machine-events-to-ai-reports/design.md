## Context

当前`_ins_provider.py`在拉取旋转机组(8K)和往复机组(9K)的KPI数据时，`alarms`字段返回空列表`[]`。InS-OS系统提供了`getMachineDrops`接口（8K: `/ins-os-view/sg8kData/getMachineDrops`，9K: `/ins-os-view/sg9kData/getMachineDrops`），可查询设备在指定时间范围内的事件数据（报警、启停机、预警等）。

报告数据流：`query_*.py` → `_ins_provider` → `*_data.json`（含alarms字段）→ `*_kpi.py` → `*_kpi.json` → `export_report.py` → `.md/.pdf`。下游KPI脚本和报告模板已支持alarms/alarm_table渲染，只需上游填充真实数据。

## Goals / Non-Goals

**Goals:**
- 当`eq_type`为`rotating_machinery`或`reciprocating_machinery`时，从InS-OS的`getMachineDrops`接口获取设备事件
- 将事件数据映射为统一的alarm格式（`time`, `equipment`, `level`, `message`），填充`alarms`字段
- 事件拉取与趋势数据拉取复用同一个`InsApiClient`会话，避免额外握手开销

**Non-Goals:**
- 不修改静设备(6K)和机泵(2K)的报告数据流程
- 不修改`*_kpi.py`和`export_report.py`的渲染逻辑
- 不新增报告模板DSL section或修改前端组件
- 不处理事件的分页/增量拉取（单次拉取时间窗口内全部事件）

## Decisions

### Decision 1: 在`_async_fetch_payload`和`_async_fetch_daily_series_payload`内部并发拉取事件

**选择**: 在已有`InsApiClient`会话内，与KPI趋势数据并发（`asyncio.gather`）调用`getMachineDrops`。

**理由**: 复用现有client session避免二次TCP/登录握手；并发拉取不增加总耗时；事件与KPI数据在同一时间窗口、同一设备范围，天然属于同一次fetch。

**替代方案**: 单独写一个新provider/脚本拉取事件后merge → 增加调用链复杂度，且需协调时序。

### Decision 2: 事件类型映射

8K (`rotating_machinery`) 设备拉取所有事件类型(1-18)，9K (`reciprocating_machinery`) 设备拉取支持的事件类型(1,2,3,14,15)。

```python
_EVENT_TYPE_MAP = {
    1: ("主报警", "high"),
    2: ("预报警", "warning"),
    3: ("启停机", "info"),
    4: ("黑匣子", "info"),
    5: ("正反进动", "info"),
    6: ("通频值/过程量偏差", "warning"),
    7: ("1X偏差", "warning"),
    8: ("2X偏差", "warning"),
    9: ("0.5X偏差", "warning"),
    10: ("可选偏差", "warning"),
    11: ("残余量偏差", "warning"),
    12: ("振动波动", "warning"),
    13: ("诊断事件", "info"),
    14: ("预警", "warning"),
    15: ("偏差报警", "high"),
    16: ("诊断事件-D", "info"),
    17: ("诊断事件-C", "info"),
    18: ("诊断事件-B", "info"),
}
```

### Decision 3: alarm数据格式对齐现有alarm_table

现有`daily_kpi.py`期望的alarm格式：
```python
{"time": str, "equipment": str, "level": str, "message": str}
```

`getMachineDrops`返回的数据映射为统一格式：
```python
{
    "time": datetime.fromtimestamp(datatime/1000).isoformat(),
    "equipment": posName,  # 测点名称
    "level": level,  # 根据事件类型映射
    "message": f"{event_label} - {posName}",
}
```

### Decision 4: 仅对旋转机组和往复机组拉取事件

**选择**: 在`_fetch_kpi_for_equipment`末尾，当`eq_type`为`rotating_machinery`或`reciprocating_machinery`时追加事件拉取。

**理由**: 静设备和机泵没有对应的8K/9K接口，强行调用会报错。

## Risks / Trade-offs

- **[风险] `getMachineDrops`调用超时或失败可能导致整个报告生成失败** → 缓解：事件拉取失败时降级为空alarms列表（`try/except`吞掉异常并记录warning日志），不阻塞KPI数据返回
- **[风险] 事件数量过多可能撑大payload** → 缓解：按月报场景预估，单设备月事件通常在几十到几百条量级，在可接受范围内
- **[取舍] 不区分posId归属设备** → 目前`getMachineDrops`返回的`posId`为测点ID，反查所属设备需要额外`get_components`调用。初期直接用`posName`作为equipment字段值，后续可按需优化
