## Context

日报生成链路的性能问题已通过事实核查确认（参见 proposal.md）。当前状态：

- **直执行器路径已存在但仅覆盖 deep-link 入口**：常规入口仍走多轮 Agent 编排（SOUL.md Round 1 → Round 1.5 → Round 2 → Agent 逐脚本调用），性能瓶颈被放大。
- **直执行器 stdout 契约存在 bug**：executor 把脚本 stdout（`{"output": path}` 元数据）覆写到 `daily_data.json`，覆盖了脚本刚写入的实际数据。该 bug 目前因常规入口不走直执行而未暴露，但一旦切流会立即引发故障。
- **组织树查询冗余**：前端设备选择器查一次，Round 1.5 的 `list_equipment.py --limit 1` 查一次（为拿 KPI 元数据），生成阶段 `detect_equipment_type` / `resolve_equipment_by_scope` 再查 1-2 次。同一轮内组织树被请求 3-4 次。
- **InS 串行拉数**：设备维度串行（`for eq_id in equipment_ids`），当天/对比日顺序执行，无缓存。
- **SMS 在 Agent 编排第 5 步串行调用**：虽 best-effort 但仍在关键路径上。
- **无分段计时埋点**：七段（表单交互、组织树、当天 InS、对比日 InS、SMS、KPI 计算、导出）无计时，优化只能凭感觉。

约束：

- 直执行器修改影响 daily/weekly/monthly 三类报告，需同步验证。
- InS 并发需确认上游 API 限流策略。
- `compare_with` 默认值变更有口径风险，本次不调整。

## Goals / Non-Goals

**Goals:**

- 建立七段计时埋点基线，所有计时统一 `trace_id` + `step_name` + `duration_ms` + `record_count` 字段。
- 修复直执行器 stdout 契约，使常规入口可安全切流。
- 消除 Round 1.5 的无效组织树查询，改为消费静态 KPI 元数据映射。
- 合并后续重复组织树查询，通过表单 payload 透传设备信息。
- 常规入口切到直执行，消除 Agent 多轮编排开销。
- InS 拉数改为限流并发，设备维度并发上限可配（默认 4–8），当天/对比日并发，`get_slim_components` 单次运行内缓存。
- SMS 从主链路挪到直执行器 post-processing 阶段，不阻塞首屏。

**Non-Goals:**

- 不调整 `compare_with` 默认值。待埋点跑一周后独立评估。
- 不重构 weekly/monthly 报告的 Agent 编排逻辑（仅修复直执行器契约，切流另行排期）。
- 不引入 OpenTelemetry 等外部依赖。埋点输出为结构化 JSON 日志，后续可桥接。
- 不修改前端设备选择器组件。

## Decisions

### Decision 1: 埋点输出格式 — 结构化 JSON 日志（非 OpenTelemetry）

**选择**：每个计时点输出 `{"trace_id": "<report_run_id>", "step_name": "<...>", "duration_ms": N, "record_count": M, "timestamp": "..."}` 到 stderr（与现有 `[数据查询]` 日志混排），同时写入 `<output_dir>/.perf/<trace_id>.jsonl`。

**替代方案**：引入 OpenTelemetry SDK + exporter。

**理由**：当前阶段目标是建立基线，不是生产级可观测性。JSON 日志足够定位瓶颈，且无外部依赖。后续若需接入 APM，可写桥接层解析 JSONL。

### Decision 2: 直执行器 stdout 契约修复策略 — executor 解析 `output` 字段

**选择**：executor 从 stdout 解析 `output` 字段获取实际数据文件路径，将该文件复制到 `self.output_dir / daily_data.json`（或直接使用该路径作为下游输入）。

**替代方案**：让脚本不再写文件，纯靠 stdout 传递数据。

**理由**：脚本写文件是现有约定（SOUL.md 中 Agent 编排也依赖 `/mnt/user-data/outputs/daily_data.json`），改动影响面大。executor 侧解析更局部，且保持向后兼容。weekly/monthly 脚本同此契约，一并修复。

### Decision 3: Round 1.5 KPI 元数据来源 — 静态映射（非轻量接口）

**选择**：扩充 `_EQUIPMENT_TYPE_DEFAULT_KPIS` 映射，覆盖所有设备类型。Round 1.5 直接从映射读取 KPI 列表，不再调 `list_equipment.py`。

**替代方案**：新增 `get_kpi_catalog(equipment_type)` 轻量接口。

**理由**：`_EQUIPMENT_TYPE_DEFAULT_KPIS` 已覆盖 pump/rotating/reciprocating 等主要类型，只需验证完整性。静态映射无网络开销，且 KPI 元数据变化频率极低（新增 KPI 需改脚本逻辑，非动态配置）。轻量接口引入新脚本，增加维护成本。

### Decision 4: 组织树查询结果透传方式 — 表单 payload 扩展

**选择**：Round 1.5 的 `device-selector-multi` 回调 payload 已包含 `selected: [{id, label, type, path}]`。Round 2 确认表单提交时，将 `equipment_type`（从 Round 1 透传）+ `selected`（含 type/path）作为标准输入传给直执行器。直执行器将 `equipment_type` 和 `equipment_meta`（从 selected 构建）写入中间参数文件，`query_daily.py` 从该文件读取，不再回头查树。

**替代方案**：在直执行器内部缓存组织树查询结果。

**理由**：缓存方案仍会有首次查询开销，且缓存失效策略复杂。透传方案零查询开销，且数据一致性由前端保证（用户选的设备列表即最终列表）。

### Decision 5: InS 并发实现 — `asyncio.Semaphore` + `asyncio.gather`

**选择**：`fetch_trend_data_async` 和 `fetch_alarm_events_async` 内部使用 `asyncio.Semaphore(concurrency_limit)` 控制并发，`asyncio.gather` 并行执行。`get_slim_components` 结果以 `equipment_id` 为 key 缓存到 `dict`（单次运行内有效）。当天/对比日在 `query_daily.py` 的 `build_result` 中用 `asyncio.gather` 并发调用 `fetch_day_with_provenance`。

**替代方案**：使用 `concurrent.futures.ThreadPoolExecutor`。

**理由**：`_ins_client.py` 已是 async 实现（`async def fetch_trend_data_async`），用 asyncio 原生并发更自然。ThreadPool 需额外包装，且与现有 async 代码风格不一致。并发上限默认 4，可通过环境变量 `INS_CONCURRENCY_LIMIT` 覆盖。

### Decision 6: SMS 异步化落点 — 直执行器 post-processing

**选择**：直执行器在 `export_report.py` 生成主报告后，异步调用 `query_sms_abnormal.py`，将结果注入报告末尾或作为可展开区块。SMS 失败不阻塞主报告。

**替代方案**：在 `query_daily.py` 内部并发发起 SMS 请求。

**理由**：SMS 逻辑独立于 InS 数据，混入 `query_daily.py` 会增加脚本复杂度。直执行器层处理更清晰，且可与主报告生成解耦（先出主报告，再补 SMS）。SOUL.md 中 Agent 编排的第 5 步 SMS 调用将随常规入口切直执行而自然消失。

## Risks / Trade-offs

- **[风险] 直执行器契约修复影响 weekly/monthly** → 缓解：三类报告的 query 脚本 stdout 契约一致（均返回 `{"output": path}`），executor 侧解析逻辑统一。修复后需同步验证 weekly/monthly 直执行路径。
- **[风险] InS 并发触发上游限流** → 缓解：默认并发上限 4，可通过环境变量调整。首次上线后压测 4/8/16 并发，观察上游响应时间和错误率。若触发限流，回退到 2 并发。
- **[风险] 常规入口切直执行后 Agent 编排层容错逻辑丢失** → 缓解：直执行器已有 `ScriptFailedError` / `NoDataError` 结构化错误处理。Agent 编排层的重试/回退逻辑需迁移到直执行器，具体映射在 tasks.md 中列出。
- **[取舍] 埋点输出到 stderr + JSONL 文件（非 APM）** → 接受：当前阶段目标是建立基线，JSON 日志足够。后续接入 APM 需写桥接层，属于已知技术债。
- **[取舍] 静态 KPI 映射（非动态接口）** → 接受：KPI 元数据变化频率极低，静态映射维护成本可接受。若未来需动态 KPI，再引入轻量接口。
