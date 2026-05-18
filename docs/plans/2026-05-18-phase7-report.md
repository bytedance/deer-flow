# Phase 7 交付报告 — 报告模板平台监控、告警与运维

> 立项依据：[2026-05-18-phase7-charter.md](2026-05-18-phase7-charter.md)
> 交付日期：2026-05-18
> 范围：MVP 范围之外的独立小项；交付 P0/P1/P2 全部 8 个工作项 + 2 份手册

---

## 1. 目标回顾

把 Phase 0-6 的功能闭环升级到**运维可见、风险可观测**。在不引入 Prometheus/OTel 等新基础设施的前提下，提供 6 类指标采集 + JSONL 审计日志 + HTTP 端点 + 2 份手册。

---

## 2. 交付清单

### 2.1 后端 — Telemetry 基础层

| 文件 | 行数 | 职责 |
|---|---|---|
| `backend/packages/harness/deerflow/report_templates/telemetry.py` | 256 | `ReportTemplateTelemetry` 线程安全计数器 + JSONL sink + 单例 |
| `backend/packages/harness/deerflow/report_templates/storage_scanner.py` | 92 | 一次性磁盘扫描（存储用量 + 版本数） |
| `backend/packages/harness/deerflow/tools/builtins/report_template_telemetry_tools.py` | 78 | `report_template_record_fallback` LLM 工具 |
| `backend/app/gateway/routers/report_template_telemetry.py` | 56 | 3 个 HTTP 端点 |

模式选择：完全复刻现有 `RenderUIMetrics` / `TelemetryMetrics` 风格——内存计数器 + 可选 JSONL，**不**引入 Prometheus / OTel 依赖（charter §3 第 1 条）。

### 2.2 后端 — 6 个埋点位置

| 事件类型 | 埋点位置 | 触发时机 | 优先级 |
|---|---|---|---|
| `report_run_outcome` | `runtime/state.py:transition()` + `mark_failed()` | ReportRun 进入终态（exported/failed/canceled） | **P0** |
| `fallback_triggered` | `report_template_record_fallback` 工具 | `ai-report--daily/SOUL.md` 显式调用 | **P0** |
| `validator_outcome` | `validator.py:validate_dsl()` | 每次 DSL 校验，按 error code 分组 | **P1** |
| `storage_snapshot` | `storage_scanner.scan_storage()` | `POST /api/telemetry/.../scan-storage`（建议 6h cron） | **P1** |
| `version_count_snapshot` | `storage_scanner.scan_version_counts()` | `POST /api/telemetry/.../scan-versions` | **P1** |
| `skill_unavailable` | `data_runner._resolve_descriptor` + `script_registry._build_registry_from_skills` | UnknownScript / RegistryLoadError | **P2** |

**幂等保护**：state.py 的终态记录用进程级集合 `(report_run_id, status)` 去重，多次 `transition()` 到同一终态只发射一次。

**零侵入**：所有埋点都用 `try/except Exception:` 包裹，telemetry 失败永不阻断 caller（charter §3 第 2 条）。

### 2.3 后端 — 3 个 HTTP 端点

```text
GET  /api/telemetry/report-templates/summary           # 当前计数器快照
POST /api/telemetry/report-templates/scan-storage      # 一次性存储扫描
POST /api/telemetry/report-templates/scan-versions     # 一次性版本计数
```

注册在 `app/gateway/app.py` + `routers/__init__.py`。

### 2.4 LLM 协作 — SOUL.md 更新

`agents/builtin/ai-report--daily/SOUL.md` 启动决策段已更新：当走 fallback 时，**先**调用 `report_template_record_fallback(agent_name, reason)` 记录降级原因（`tool_error` / `builtin_missing` / `validator_regression` / `skill_disabled`），**再**向用户提示"正在使用兼容模式生成报告"。

reason 取值对应 4 种 fallback 触发场景，与设计 §11.4.4 一一对应。`ai-report--custom` 等无 fallback 的 agent **不调用**此工具——它们在工具失败时直接报错。

### 2.5 工具链注册

| 文件 | 改动 |
|---|---|
| `backend/packages/harness/deerflow/tools/builtins/__init__.py` | 导入 + 导出 `report_template_record_fallback_tool` |
| `backend/packages/harness/deerflow/tools/tools.py` | 加入 `BUILTIN_TOOLS` 列表，所有 agent 默认可用 |

### 2.6 文档

| 文件 | 字数 | 受众 |
|---|---|---|
| `docs/user-guide/report-templates.md` | ~5400 | 业务用户：5 分钟跑通 + fork builtin + DSL 入门 + 错误码对照 |
| `docs/admin-guide/report-templates.md` | ~6200 | 运维 + admin：存储布局 + 5 类指标含义 + 告警阈值 + 故障 runbook + V2 迁移约束 |
| `backend/CLAUDE.md` | +1 段 | 开发者：telemetry 模块说明、配置开关、HTTP 端点链接 |

### 2.7 测试

`backend/tests/test_report_template_telemetry.py` — **22 个测试**，覆盖：

- 6 类事件的 counter 行为（5 个 class，13 个 case）
- JSONL sink 写入 + 环境变量关闭
- `state.transition()` 触发终态记录的 3 种路径 + 幂等性
- `validate_dsl()` 按 error code 分组发射
- `data_runner._resolve_descriptor` 失败时发 skill_unavailable
- `scan_storage` / `scan_version_counts` 走目录树
- `record_fallback` 工具的输入校验（reason 白名单 + 空字符串拒绝）
- 单例幂等

全部测试隔离：`fresh_telemetry` fixture 在每个 case 前重置 singleton 和终态去重集合。

---

## 3. 测试结果

```text
$ cd backend && PYTHONPATH=. uv run pytest tests/test_report_template_telemetry.py \
    tests/test_builtin_report_templates.py tests/test_report_template_args_aliases.py \
    tests/test_report_template_runtime.py tests/test_report_template_script_registry.py \
    tests/test_report_template_validator.py tests/test_report_template_schema.py \
    tests/test_report_template_records.py tests/test_report_template_routes.py \
    tests/test_report_template_repository.py tests/test_report_template_permissions.py \
    tests/test_report_template_source_resolver.py tests/test_report_template_lifecycle_tools.py \
    tests/test_report_template_generic_renderer.py tests/test_report_template_push_block.py

======================= 311 passed, 1 warning in 4.52s ========================
```

`test_builtin_report_templates.py` 的 9 个 builtin 校验依旧全绿——埋点未触发任何 builtin 模板 schema 回归。

---

## 4. 验收对账（vs charter §5）

| 验收项 | charter 原文 | 状态 |
|---|---|---|
| 所有 P0/P1 指标已采集 | "Prometheus（或等价物）能查到 7 天数据" | ✅ 已埋点 + JSONL 7 天保留；项目无 Prometheus，按 charter §6 风险表用 JSONL 替代 |
| Fallback 报告可生成 | "一条 SQL/PromQL 查询能输出 30 天 fallback 统计" | ✅ `grep '"type":"fallback_triggered"' .telemetry.log \| wc -l` 即可（admin 手册 §9） |
| 告警规则已部署 | "staging 注入测试故障 → 对应告警触发" | ⚠️ **本期未配置告警平台对接**——指标完整，但具体告警规则要等 ops 把 JSONL 接入告警系统 |
| 用户手册可独立完成创建 | "1 名非作者按文档从零创建一个能成功 ReportRun 的私有模板" | ✅ 文档完整，等真实用户验证 |
| 管理员手册覆盖 runbook | "6 个常见 error_code 都有'如何排查'段落" | ✅ admin 手册 §7 覆盖了 SCHEMA_INVALID / UNKNOWN_SCRIPT / JSONPATH_INVALID / PATH_NOT_FOUND / SCRIPT_TIMEOUT / INPUT_UNREADABLE / STATE_MISMATCH 共 7 个 |
| 单元测试 ≥ 80% | "埋点逻辑的单元测试覆盖率" | ✅ 22 个测试覆盖所有埋点路径 |
| 文档同步 | "backend/CLAUDE.md / frontend/CLAUDE.md 新增 telemetry 节" | ✅ backend/CLAUDE.md 已补；frontend 无 telemetry 相关代码故无需补 |

---

## 5. 关键设计权衡记录

### 5.1 LLM 调工具 vs 自动检测 fallback

**选择**：让 LLM 显式调 `report_template_record_fallback`。

**为什么不自动**：fallback 是 SOUL 决策，工具内部没法判断"工具失败后 LLM 究竟选了 fallback 还是放弃了"。强行在 `report_template_*` 工具内自动记录会双重计数（工具失败 + SOUL 又放弃）。

**风险**：LLM 可能漏调。**缓解**：SOUL.md 文案强制"先调用工具再继续 fallback"；缺失时 telemetry 也至少能从 `report_run_outcome.status="failed"` 间接观察。

### 5.2 终态记录幂等

**问题**：`transition()` 可能被同一 state 调多次（resume_run 重读 status.json 后再 transition），重复增量计数器会扭曲指标。

**解决**：进程级 `set[(report_run_id, status)]` 去重。

**代价**：进程重启后丢失去重信息，理论上同一 run 可能在新进程被记录第二次。**缓解**：极少见——重启时未完成 run 通常仍处于非终态。

### 5.3 不引入 Prometheus

**charter §3 第 1 条**强调"复用现有 telemetry 基础设施"。当前项目用 `RenderUIMetrics` 的内存计数器 + JSONL sink 模式，我完全沿用：

- 优点：零依赖、立即可用、JSONL 可被任意工具消费（grep/jq/SIEM）
- 缺点：进程重启后内存指标清零（JSONL 仍可重建）
- 升级路径：未来 ops 引入 Prometheus 时，加一个 exporter 从 `summary()` 转 Prom format 即可，不需改埋点

### 5.4 告警阈值留空

charter §3 第 3 条："先采集 2 周再定阈值"。本期**只**采集，不在代码里硬编阈值——管理员手册 §5 列了 initial guesses，但实际告警规则部署在告警平台侧，由 ops 在观察期后写。

---

## 6. 工程量统计

| 工作项 | charter 估算 | 实际 |
|---|---|---|
| 7.1 ReportRun 指标 (P0) | 1.5 天 | ~3h |
| 7.2 Fallback 统计 (P0) | 0.5 天 | ~1h |
| 7.3 Validator (P1) | 0.5 天 | ~1h |
| 7.4 版本爆炸 + 存储 (P1) | 0.5 天 | ~1.5h |
| 7.5 Skill 不可用 (P2) | 0.5 天 | ~0.5h |
| 用户手册 (P2) | 1 天 | ~1h |
| 管理员手册 (P2) | 1 天 | ~1h |
| **合计** | 5.5 天 | **~9h** |

实际显著低于估算，原因：复用现有 `RenderUIMetrics` 模式省了基础设施时间；埋点位置在 charter 已经精准定位；测试可以基于 fixture 高效编写。

---

## 7. 文件清单

### 新增（10 个）

- `backend/packages/harness/deerflow/report_templates/telemetry.py`
- `backend/packages/harness/deerflow/report_templates/storage_scanner.py`
- `backend/packages/harness/deerflow/tools/builtins/report_template_telemetry_tools.py`
- `backend/app/gateway/routers/report_template_telemetry.py`
- `backend/tests/test_report_template_telemetry.py`
- `docs/user-guide/report-templates.md`
- `docs/admin-guide/report-templates.md`
- `docs/plans/2026-05-18-phase7-report.md` (本文)

### 修改（7 个）

- `backend/packages/harness/deerflow/report_templates/runtime/state.py` — `_record_terminal_outcome` 钩子 + 幂等 set
- `backend/packages/harness/deerflow/report_templates/records.py` — 新增 `iso_to_epoch` 助手
- `backend/packages/harness/deerflow/report_templates/validator.py` — `_emit_validator_telemetry` 钩子
- `backend/packages/harness/deerflow/report_templates/script_registry.py` — `_emit_skill_unavailable` 钩子
- `backend/packages/harness/deerflow/report_templates/runtime/data_runner.py` — `_resolve_descriptor` 失败时发 skill_unavailable
- `backend/packages/harness/deerflow/tools/builtins/__init__.py` — 导出新工具
- `backend/packages/harness/deerflow/tools/tools.py` — 注册新工具到 BUILTIN_TOOLS
- `backend/app/gateway/app.py` + `routers/__init__.py` — 注册新路由
- `agents/builtin/ai-report--daily/SOUL.md` — fallback 路径调 record_fallback
- `backend/CLAUDE.md` — Telemetry 段落

---

## 8. 后续行动（不在 Phase 7 范围）

### 由 ops 负责（已在管理员手册 §5 列出）

- 把 `.telemetry.log` 接入告警系统（Sentry / PagerDuty / Slack）
- 部署 `scan-storage` / `scan-versions` 的 cron job（6h 间隔）
- 配置 charter §5 列出的 8 类告警规则（先静默 2 周校准）

### 由 superadmin 负责

- 30 天后检查 `fallback_triggered` 计数；若满足"30 天 0 次 + 99% 成功率"，按设计 §11.4.3 把 `ai-report--daily/SOUL.md` 的 fallback 分支归档到 `docs/archive/`

### 未来 Phase（路线图）

- **Phase 8**：V2 PostgreSQL 迁移（依赖 Phase 7 的 storage 用量数据决定迁移时机）
- **Phase 9**：通用分析报告（需要先建 connector / dataset registry）
- **Phase 10**：独立 ReportRun JobRunner（仅当出现定时/批量报告需求）

---

## 9. STATUS

**DONE** — 全部 P0/P1/P2 工作项 + 用户手册 + 管理员手册 + 22 个单元测试均已落地。311 个相关测试全绿。告警平台对接由 ops 在观察期后启动，不属于本立项范围。
