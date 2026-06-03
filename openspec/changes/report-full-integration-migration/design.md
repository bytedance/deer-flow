# Report Full Integration Migration - Technical Design

## Context

当前 AI 报告数据获取有三条并存路径，但前一个 `report-integration-migration` 变更留下了未完成的布线：

1. **DSL 模板平台桥接**（目标路径）：`data_runner.py` → subprocess → `query_*.py`（检测 `USE_PLATFORM`）→ `_platform_bridge.py` → CLI → integrations 层
2. **旧 `_ins_provider.py` 直连**（待移除）：`query_*.py` → `_data_provider_impls.py`（`InsDailyProvider` 等）→ `_ins_provider.py` → features-tool HTTP 直连
3. **Agent SOUL.md fallback**（待移除）：当 DSL 路径失败时回退到硬编码 GenUI 表单 + 直接 shell 调脚本

预置基础设施（来自前一个变更，已完成）：
- `integrations/adapters/ins/kpi_aggregator.py` — 纯函数 KPI 聚合模块
- `integrations/cli.py` — `--action aggregate_kpi` 模式
- `_platform_bridge.py` — `call_capability()` + `call_action()` 两个 helper
- `TrendQuery` / `AlarmHistoryQuery` — 批量 `equipment_ids` 参数

未完成的关键布线：
- `DataStep` schema 无 `provider` 字段
- `data_runner` 的 `run_script()` 不接收 `provider` 参数
- 5 个 builtin 模板 DSL 无 `provider: platform` 声明
- `_platform_bridge.py` 的 `_transform_canonical_to_script_shape` 返回空占位
- Agent SOUL.md 仍保留完整的 fallback 章节

## Goals / Non-Goals

**Goals:**
- 补齐 DSL provider 布线：schema → data_runner → subprocess env → 脚本检测
- 所有 AI 报告数据获取唯一路径：integrations layer
- 移除 `_ins_provider.py` 旧直连 KPI 聚合能力
- 移除 Agent SOUL.md 中的双轨降级逻辑
- 修复 platform bridge 空占位数据转换

**Non-Goals:**
- 不新增 capability key（复用 `monitoring.trend` / `monitoring.alarm_history`）
- 不重构报告 DSL schema 执行模型
- 不修改 CRM/ERP/SMS 相关集成
- 不迁移 `query_trend.py` / `query_fault_context.py` 的数据模型（这两个脚本的数据模型与 KPI 聚合差异大，需独立设计——但本次要求全面走 integrations，所以也需要覆盖）

## Decisions

### Decision 1: Schema 用可选 `provider` 字段，默认不注入任何 env

**选择**: `DataStep.provider: str | None = None`，`extra="forbid"` 保持不变。当 `provider` 值为 `"platform"` 时注入 `USE_PLATFORM=true`。

**理由**: 最大程度向后兼容。未声明 provider 的步骤行为不变。`extra="forbid"` 不变——`provider` 是显式白名单字段。

**替代方案**: 要求所有 data_step 必选 provider。问题：对不需要外部数据的 demo/本地脚本侵入性太大。

### Decision 2: 全部走 integrations，移除 `_ins_provider.py` KPI 聚合

**选择**: 删除 `_ins_provider.py` 中的聚合函数体（`_aggregate_trend_to_kpi`、`_hourly_runtime_rate`、`_fetch_kpi_for_equipment` 等），sync wrapper 直接 `raise RuntimeError("Use integrations layer (provider: platform)")`。`_data_provider_impls.py` 中的 `InsDailyProvider` 等不再注册。

**理由**: `kpi_aggregator.py` 已有完整的聚合逻辑副本。保留旧路径只会造成两条路径分叉、KPI 行为不一致的风险。一刀切迫使所有部署走 integrations。

**风险**: 如果 `integrations.enabled: true` 未配置或 `ins_prod` 系统定义缺失，报告直接失败（而非静默降级到 demo 数据）。这是有意为之——宁可报错也不要假数据。

### Decision 3: Agent SOUL.md 只保留 DSL 路径

**选择**: ai-report--daily/weekly/monthly 三个 SOUL.md 中删除：
- `### 启动决策` 中的 `report_template_get` 检测 + "未命中 → 进入 fallback" 分支
- `#### Fallback 路径触发场景` 整节
- 整个 `# Fallback ` 后的硬编码表单 JSON（Round 1/1.5/2 等）

替换为简单逻辑：进来就执行 DSL 路径，失败则报告错误而非降级。

**理由**: 双轨逻辑让 Agent 行为不可预测。运维排查时不知道某次生成走的是 DSL 还是 fallback。统一 DSL 后 Agent prompt 大幅缩短，token 消耗降低。

### Decision 4: `run_script()` 新增 `provider` 参数

**选择**: `run_script()` 签名新增 `provider: str | None = None`。非 None 时注入对应环境变量到 subprocess。`run_data_steps_and_transforms()` 从 `step["provider"]` 提取并传递。

```python
def run_script(
    ...,
    provider: str | None = None,
) -> StepResult:
    ...
    if provider is not None:
        env_var_map = {"platform": "USE_PLATFORM", "demo": "USE_PROVIDER", "ins": "USE_PROVIDER", "http": "USE_PROVIDER"}
        key = env_var_map.get(provider)
        if key:
            subprocess_env[key] = "true" if provider == "platform" else provider
```

**`platform` 特殊处理**: `USE_PLATFORM=true`。其他值用 `USE_PROVIDER=<value>`。

## Risks / Trade-offs

- **无回滚路径**：旧 `_ins_provider.py` 聚合逻辑删除后不可恢复。→ 部署前必须执行 E2E 烟雾测试验证。rollback 意味着 git revert 整个变更。
- **所有环境必须配 `ins_prod`**：之前本地开发可能依赖 demo 数据，现在强制要求 integrations 层可访问。→ 本地开发可以启动 features-tool Docker 容器或配置 mock 后端。
- **Agent SOUL.md 大幅缩短**：删除 fallback 后 prompt 减半，可能影响 Agent 在一些边界场景下的鲁棒性。→ DSL 路径本身已经过充分测试，错误场景由工具返回结构化错误码。
- **`query_trend.py` / `query_fault_context.py` 也在 scope 内**：前一个变更把它们标记为 out-of-scope，数据模型差异较大。本次需要重新评估这两个脚本的迁移方案——如果复杂度超出预期，可能需要单独处理。

## Migration Plan

### Phase 1: Schema + data_runner 布线
1. `schema.py` DataStep 加 `provider` 字段
2. `data_runner.py` `run_script()` 加 `provider` 参数 + env 注入
3. `run_data_steps_and_transforms()` 透传 `step["provider"]`
4. 单元测试验证 env 注入行为

### Phase 2: 模板 DSL 声明 provider
1. 5 个 builtin 模板 `data_steps` 加 `provider: platform`
2. 运行 `test_builtin_report_templates.py` 验证模板仍然通过 validator

### Phase 3: 脚本清理
1. `_ins_provider.py` 聚合函数体替换为 raise NotImplementedError
2. `_data_provider_impls.py` 移除 InsDaily/Weekly/MonthlyProvider 注册
3. `_platform_bridge.py` 修复 `_transform_canonical_to_script_shape`

### Phase 4: Agent SOUL.md 简化
1. 移除 daily/weekly/monthly 三个 SOUL.md 的 fallback 章节
2. 替换为纯 DSL 路径指令

### Phase 5: 验证
1. `make test` 全量回归
2. 真实 InS 环境 E2E 烟雾测试（daily + weekly + monthly）

## Open Questions

- `query_trend.py` 和 `query_fault_context.py` 是否本次一起强行走 integrations？前一个变更把它们标记为 out-of-scope 因为数据模型差异大。建议本次先把 daily/weekly/monthly 彻底迁完，trend/diagnosis 作为 follow-up change。
