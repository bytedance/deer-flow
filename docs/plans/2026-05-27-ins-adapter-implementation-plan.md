# InS Adapter 平台化改造实施方案

> 版本: v1.0  
> 日期: 2026-05-27  
> 状态: Draft  
> 相关文档:
> - [多系统租户级集成与共享数据接入层设计](./2026-05-27-multi-system-tenant-integration-architecture.md)
> - [Capability Keys 与 Canonical Models 清单](./2026-05-27-capability-keys-and-canonical-models.md)

---

## 1. 概述

本方案聚焦一个具体目标:

**把当前 DeerFlow 中以 skill / shell / sandbox 工具链形式存在的 InS 接入，改造成平台级共享 adapter。**

当前系统已经具备较丰富的 InS 能力，但这些能力分散在多个位置:

- `docker/sandbox/features-tool/ins/client.py`
- `docker/sandbox/features-tool/tools/get_waveform_data_tool.py`
- `docker/sandbox/features-tool/tools/get_orbit_data_tool.py`
- `skills/custom/ins-get-waveform-data/scripts/run.sh`
- `skills/custom/data-analyst/scripts/_ins_provider.py`
- 各类 `ins-*` skills
- 若干 agent `SOUL.md` 中写死的 shell 调用

这套链路可以工作，但它的主要问题不是“不能用”，而是“不能长期扩展”。

---

## 2. 当前问题

### 2.1 数据接入入口分散

当前 InS 的数据获取链路同时存在:

- sandbox 内 Python client
- features-tool 包装脚本
- shell wrapper
- report 专用 provider
- agent SOUL 里的命令调用

这导致:

- 复用外部系统能力时，上层必须知道具体脚本和路径
- 不同调用链的错误模型、参数规范、输出格式不统一
- 很难平滑扩展到 Sms、CRM、ERP

### 2.2 外部系统访问和业务分析耦合

例如:

- `monitoring-analysis` 通过 shell 直接调用 `ins-get-waveform-data`
- `data-analyst` 通过 `_ins_provider.py` 直接 import `features-tool`
- 诊断 skill 里存在基于运行环境的特殊约束

这意味着“如何拿数据”和“如何分析数据”混在一起。

### 2.3 InS 目前更像 skill 私有能力，而不是平台公共能力

从平台角度看，InS 应该提供的是:

- 设备树
- 测点
- 趋势
- 波形
- 轨迹
- 报警事件

但从现状看，InS 的能力大多通过 `ins-get-*` skill 名或 `run.sh` 入口对上暴露。  
这使得 agent 对“能力”的依赖，退化成了对“某个脚本入口”的依赖。

---

## 3. 改造目标

### 3.1 目标状态

改造后应形成固定调用链:

```text
Agent / Report / Skill
        |
        v
Built-in Tool / Shared Service
        |
        v
InS Adapter
        |
        v
InS System
```

### 3.2 必须达成的效果

- InS 成为平台级共享 adapter
- agent 不再长期依赖 shell 脚本路径
- report 不再私有 import `features-tool`
- features-tool 保留，但只做兼容 wrapper 或算法侧执行器
- 后续接入 Sms 时，不再重复造一套链路

### 3.3 不要求一次性完成的内容

- 不要求立刻删除所有 `ins-*` skill
- 不要求立刻删除所有 `run.sh`
- 不要求将所有 sandbox 工具移出 Docker image

---

## 4. 当前 InS 能力盘点

### 4.1 已存在的底层能力

当前 `features-tool` 中的 `InsApiClient` 已经支持:

- 登录和 token 复用
- 2k / 6k / 8k / 9k 趋势路由
- 波形获取
- 轨迹获取
- machine drop 事件获取
- component slim tree 抽取
- 响应扁平化

因此 Phase 1 不建议重写 `InsApiClient`，而是建议把它上浮为共享 adapter 的 transport/core 实现。

### 4.2 已存在的上层消费方式

当前存在三类主要消费方:

1. 报表脚本
   - `skills/custom/data-analyst/scripts/_ins_provider.py`
   - `query_daily.py`
   - `query_weekly.py`
   - `query_monthly.py`
   - `query_trend.py`

2. 监测与诊断 agent
   - `monitoring-analysis`
   - `pump-fault-diagnosis`
   - `fault-diagnosis--reciprocating`

3. `ins-*` skills
   - `ins-get-waveform-data`
   - `ins-get-orbit-data`
   - `ins-get-trend-data-*`
   - `ins-extract-*`

这些消费方式都要保留兼容，但要逐步迁到 shared service。

---

## 5. 目标目录结构

建议新增:

```text
backend/packages/harness/deerflow/integrations/
  errors.py
  provenance.py
  registry.py
  routing.py

  adapters/
    base.py
    ins/
      __init__.py
      adapter.py
      client_bridge.py
      mapper.py
      requests.py
      responses.py

  services/
    asset_service.py
    monitoring_service.py
```

### 5.1 模块职责

- `adapter.py`
  - 对外提供 InS 领域能力接口

- `client_bridge.py`
  - 复用或封装现有 `InsApiClient`
  - 作为从旧实现向新 adapter 迁移的桥

- `mapper.py`
  - 外部响应 -> canonical model

- `requests.py / responses.py`
  - 定义 InS adapter 内部 contract

- `asset_service.py`
  - 提供设备树、设备上下文、实体解析

- `monitoring_service.py`
  - 提供趋势、波形、轨迹、报警事件

---

## 6. InS Adapter 对外接口

建议 InS adapter 先提供以下接口:

```python
class InSAdapter:
    async def get_asset_catalog(self, req: AssetCatalogQuery) -> AssetCatalog: ...
    async def get_asset_context(self, req: AssetContextQuery) -> AssetContext: ...
    async def get_trend(self, req: TrendQuery) -> TrendSeries: ...
    async def get_waveform(self, req: WaveformQuery) -> WaveformPayload: ...
    async def get_orbit(self, req: OrbitQuery) -> OrbitPayload: ...
    async def get_alarm_history(self, req: AlarmHistoryQuery) -> list[AlarmEvent]: ...
```

### 6.1 设计原则

- 输入是平台统一 query object，不直接暴露原始 InS 参数格式
- 输出是 canonical model，不直接暴露外部 JSON
- `endpoint_series` 判定留在 adapter 内部，不上浮到 agent
- `factory_id` 作为 adapter 配置，不作为上层默认必填参数

### 6.2 特殊说明

对于波形和轨迹:

- 上层仍可以保留 `point_id`、`bearing_id`、`time_ms` 这些工业场景必要参数
- 但这些是业务查询参数，不应暴露为 shell 调用约束

---

## 7. Shared Service 设计

### 7.1 AssetService

职责:

- 获取设备目录
- 获取设备上下文
- 解析设备和测点映射
- 输出统一 `Asset` / `MeasurementPoint`

示例接口:

```python
class AssetService:
    async def get_catalog(self, tenant_id: str, req: AssetCatalogQuery) -> AssetCatalog: ...
    async def get_context(self, tenant_id: str, req: AssetContextQuery) -> AssetContext: ...
```

### 7.2 MonitoringService

职责:

- 获取趋势
- 获取波形
- 获取轨迹
- 获取报警事件

示例接口:

```python
class MonitoringService:
    async def get_trend(self, tenant_id: str, req: TrendQuery) -> TrendSeries: ...
    async def get_waveform(self, tenant_id: str, req: WaveformQuery) -> WaveformPayload: ...
    async def get_orbit(self, tenant_id: str, req: OrbitQuery) -> OrbitPayload: ...
    async def get_alarm_history(self, tenant_id: str, req: AlarmHistoryQuery) -> list[AlarmEvent]: ...
```

### 7.3 Service 的统一行为

每个 service 都必须:

- 按 `tenant_id + capability_key` 查路由
- 装载系统连接配置
- 调 adapter
- 统一封装 provenance
- 转换统一错误

---

## 8. 对现有代码的迁移方案

### 8.1 Phase 1: 抽共享 adapter，不动上层入口

目标:

- 新增 `InSAdapter`
- 现有 skill、report、sandbox wrapper 继续工作

具体动作:

1. 新建 `deerflow/integrations/adapters/ins`
2. 将 `InsApiClient` 的调用逻辑通过 `client_bridge.py` 接入 adapter
3. 新建 `AssetService`、`MonitoringService`
4. 新增第一批 built-in tools:
   - `asset_get_catalog`
   - `equipment_get_context`
   - `monitoring_get_trend`
   - `monitoring_get_waveform`
   - `monitoring_get_orbit`
   - `monitoring_get_alarm_history`

兼容要求:

- `ins-get-*` skill 不删除
- `features-tool` 不删除
- 报表脚本不强制立即迁移

### 8.2 Phase 2: 迁 report

目标:

- `_ins_provider.py` 不再直接 import `features-tool`

具体动作:

1. `_ins_provider.py` 改为依赖 `MonitoringService` / `AssetService`
2. service 内部决定如何使用 adapter 和路由
3. 报表输出继续保留 `data_source` 和 `provenance`

收益:

- 报表脚本脱离 Docker 私有接入细节
- 后续 `Sms` 也能通过同一 service 注入能力

### 8.3 Phase 3: 迁 agent / SOUL

目标:

- agent 从 shell 调用迁到统一 built-in tools

具体动作:

1. 在 SOUL 中将以下模式逐步替换:

```text
bash /mnt/skills/custom/ins-get-waveform-data/scripts/run.sh ...
```

改为:

```text
调用 monitoring_get_waveform
```

2. 对 orbit、alarm history、trend 依次迁移

收益:

- SOUL 更稳定
- agent 不依赖 sandbox 文件路径
- 本地和云端运行形态更容易统一

### 8.4 Phase 4: skill 兼容层收敛

目标:

- `ins-*` skill 保留为兼容入口，但不再是平台主入口

具体动作:

- `run.sh` 内部最终也可转调统一 service 或标准 wrapper
- skill 保留流程和分析价值，不再承担数据源唯一入口价值

---

## 9. Compatibility Layer 策略

建议明确哪些保留，哪些迁移。

### 9.1 保留为兼容层

- `docker/sandbox/features-tool/ins/client.py`
- `docker/sandbox/features-tool/tools/get_waveform_data_tool.py`
- `docker/sandbox/features-tool/tools/get_orbit_data_tool.py`
- `skills/custom/ins-get-waveform-data/scripts/run.sh`
- `skills/custom/ins-get-orbit-data/scripts/run.sh`

### 9.2 优先迁移

- `skills/custom/data-analyst/scripts/_ins_provider.py`
- `monitoring-analysis` SOUL 中的 shell 直连
- 未来新增 agent 的数据访问入口

### 9.3 原则

兼容层可以长期存在，但不得继续成为新功能默认入口。

---

## 10. 错误、超时和运行环境

### 10.1 统一错误

建议在 shared layer 统一错误模型:

- `IntegrationConfigError`
- `IntegrationAuthError`
- `IntegrationTimeoutError`
- `IntegrationUnavailableError`
- `IntegrationDataShapeError`

### 10.2 运行环境差异

当前 `features-tool` 明显依赖 Docker sandbox:

- `FEATURES_TOOL_ROOT`
- Python 依赖预装
- protobuf 解码环境

Phase 1 不要求移除这个依赖，但要把这种依赖下沉到 adapter 内部或 compatibility layer 内部。  
上层不应该再自行感知 `FEATURES_TOOL_ROOT`。

### 10.3 波形/轨迹的特殊性

趋势和报警历史更容易服务化。  
波形和轨迹因为依赖更重、数据量更大、部分解码逻辑在 sandbox 内，建议:

- Phase 1 由 service 调兼容 wrapper
- Phase 2 再评估是否完全内收

---

## 11. 测试策略

### 11.1 单元测试

新增:

- `test_ins_adapter.py`
- `test_monitoring_service.py`
- `test_asset_service.py`

覆盖:

- series 路由
- query 到 response 的映射
- 错误归一
- provenance 输出

### 11.2 兼容测试

保留并增强:

- `test_ai_report_daily_ins_provider.py`
- `test_ai_report_weekly_ins_provider.py`
- `test_ai_report_monthly_ins_provider.py`

目标:

- 迁移后报表链路输出不回归

### 11.3 agent smoke 测试

需要补一类测试:

- built-in tools 存在且 schema 稳定
- `monitoring-analysis` 可通过新工具完成波形获取
- `pump-fault-diagnosis` 不受现有 skill 兼容层变化影响

---

## 12. 实施里程碑

### M1: 结构落地

- 新增 `integrations/adapters/ins`
- 新增 `services/asset_service.py`
- 新增 `services/monitoring_service.py`

### M2: 工具暴露

- 新增 built-in tools
- 新增 capability routing 对应配置项

### M3: 报表迁移

- `_ins_provider.py` 改走 shared service

### M4: agent 迁移

- `monitoring-analysis` 优先
- 诊断 skill 逐步迁移

### M5: 兼容层收敛

- 新增代码默认不再使用 `ins-*` shell 路径

---

## 13. 最终目标状态

最终应达到:

- InS 是平台级 adapter
- 所有 agent 共用统一的 `asset` / `monitoring` capability
- 现有 `ins-*` 入口保留兼容，但不是主入口
- 后续 `Sms` 接入时，直接复制 adapter + service + route 模式

一句话总结:

**当前要做的不是“删掉现有 InS 工具链”，而是“把现有 InS 工具链降级为兼容层，同时抬升一个真正的平台级 InS adapter”。**
