## Context

日报性能优化（`daily-report-perf-optimization`）已完成，建立了以下可复用的优化模式：

1. **直执行路径**：`DirectReportExecutor` 编排 query → kpi → export 三步，脚本通过 stdout 契约传递文件路径。
2. **InS 并发**：`asyncio.Semaphore` + `asyncio.gather` 限流并发拉取，`_get_slim_components_cached` 跨调用缓存。
3. **组织树透传**：前端表单 → `--equipment-meta` CLI 参数 → 脚本消费，跳过内部组织树查询。
4. **SMS 异步化（方案 B）**：SMS 获取移入 `*_kpi.py` 的 `compute()` 内，通过 `ThreadPoolExecutor` 与 KPI 计算并发。
5. **性能埋点**：`_perf.py` 的 `PerfTracer` 七段计时，通过 `REPORT_RUN_ID` 环境变量关联 trace。

周报和月报的 Skill 脚本结构与日报高度一致（`query_*.py` → `*_kpi.py` → `export_report.py`），且各自已有 `_ins_client.py`、`_report_common.py`、`query_sms_abnormal.py`。但当前周报/月报 Agent 的 Round 2 仍通过 bash 逐脚本编排，未接入直执行路径，也未应用上述优化。

约束：
- 周报/月报 Skill 必须是自包含的（spec 要求不跨 Skill 导入），因此 `_perf.py`、并发模式等需要从日报**复制**而非引用。
- `DirectReportExecutor.SCRIPT_MAP` 已包含 weekly/monthly 条目，executor 层无需新增路由。
- 月报有独特的批量拉取模式（`monthly-batch-fetch`），并发设计需适配多日数据拉取。

## Goals / Non-Goals

**Goals:**

- 周报和月报 Agent 的 Round 2 回调改为调用 `report_direct_execute`，与日报保持一致的直执行路径。
- 周报/月报 Skill 脚本接入 InS 并发拉取、组织树透传、SMS 异步化、性能埋点。
- 周报/月报 SOUL.md 的 Round 1.5 改用静态 KPI 映射（`get_kpi_catalog`），删除 `list_equipment.py --limit 1` 调用。
- 补充周报/月报直执行路径的单元测试，覆盖 stdout 契约、SMS 异步、并发控制。
- 保持向后兼容：新增 CLI 参数均为可选，现有 DSL 路径不受影响。

**Non-Goals:**

- 不修改 DSL 模板引擎或 DSL provider 字段。
- 不合并三个 Skill 的公共代码（自包含约束优先于去重）。
- 不做跨报告的统一埋点聚合（各报告独立输出 `.perf/<trace_id>.jsonl`）。
- 不修改前端 TodoList 组件或 stream hooks（前端已支持 `thread.values.todos` 渲染）。

## Decisions

### D1: 复制而非共享 `_perf.py` 和并发模块

**决定**：将 `_perf.py` 从 `daily-report/scripts/` 复制到 `weekly-report/scripts/` 和 `monthly-report/scripts/`，并发模式（Semaphore + gather）也分别复制到各 Skill 的 `_ins_client.py`。

**理由**：`weekly-report-skill` spec 明确要求 "Skill MUST NOT import or depend on any other skill's scripts or modules"。跨 Skill 共享会违反自包含约束。

**替代方案**：抽取公共模块到 `skills/shared/`。放弃原因：需要修改 spec 的自包含约束，影响范围大，且三个 Skill 的 `_ins_client.py` 已有差异（月报有批量模式）。

### D2: SMS 异步化沿用方案 B（KPI 脚本内部获取）

**决定**：周报/月报的 `weekly_kpi.py` / `monthly_kpi.py` 新增 `_fetch_sms_direct(payload)` 和 `_sms_kpi(key, value)`，在 `compute()` 内通过 `ThreadPoolExecutor(max_workers=1)` 并发获取 SMS 数据。

**理由**：日报已验证方案 B 的架构优势——executor 不感知 SMS，保持通用性；SMS 失败不阻塞主报告；与 KPI 计算自然并发。

### D3: 月报并发适配多日批量拉取

**决定**：月报的 `_ins_client.py` 在设备级并发的基础上，增加日期级并发——`query_monthly.py` 使用 `ThreadPoolExecutor` 对月内多个工作日并发调用 `fetch_day_with_provenance`，每个日期内部再使用 Semaphore 控制设备级并发。

**理由**：月报需拉取 ~22 个工作日的数据，串行日期会导致耗时 = 日数 × 日均耗时。日期级并发可将总耗时压缩到日均耗时级别。

**替代方案**：保持日期串行，仅设备级并发。放弃原因：22 天的串行开销太大，无法达到与日报相当的性能体验。

### D4: 组织树透传复用日报模式

**决定**：周报/月报 `query_*.py` 新增 `--equipment-meta` 参数（JSON 字符串或 @file 路径），`_report_common.py` 的 `detect_equipment_type` / `resolve_equipment_by_scope` 支持 `resolved_type` / `resolved_records` 关键字参数。

**理由**：与日报完全一致的实现模式，降低维护成本。`executor.py` 已实现 `--equipment-meta` 构造逻辑，weekly/monthly 路径自动复用。

### D5: SOUL.md Round 2 统一为 report_direct_execute

**决定**：周报/月报 SOUL.md 的 Round 2 回调删除逐脚本 bash 编排（包括 SMS 独立调用步骤），改为单次 `report_direct_execute` 调用，透传 `equipment_meta`。

**理由**：与日报保持一致的执行模型，减少 Agent 编排复杂度，消除 bash 注入风险。

## Risks / Trade-offs

- **[代码重复]** 三个 Skill 各自持有 `_perf.py` 和并发实现副本，未来修一处需同步三处。→ 缓解：自包含约束是 spec 强制的，去重需要修改 spec 并引入 shared 模块，作为后续优化项。
- **[月报日期并发风险]** 22 天 × N 设备的并发请求可能对 InS API 造成压力。→ 缓解：Semaphore 全局限流（默认 4），日期级和设备级共享同一个 Semaphore。
- **[SMS 接口差异]** 周报/月报的 `query_sms_abnormal.py` 可能与日报版本有差异（参数签名、返回结构）。→ 缓解：实现前先 diff 三个 `query_sms_abnormal.py`，确保 `_fetch_sms_direct` 适配各自接口。
- **[向后兼容]** 新增 `--equipment-meta` 参数为可选，但 `get_kpi_catalog` 替换 `list_equipment.py` 后，旧 DSL 模板如仍调用 `list_equipment.py` 不受影响（脚本仍保留）。
