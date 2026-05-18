# Phase 7 立项 — 报告模板平台监控、告警与运维

> **立项类型**：独立路线图小项（不属于 AI 报告自定义模板平台 MVP 范围）
> **依赖**：[2026-05-14-ai-report-custom-template-design.md](2026-05-14-ai-report-custom-template-design.md) Phase 0-6 已交付
> **预估工程量**：0.5 人月（约 1-1.5 周）
> **建议启动时机**：daily-equipment / 用户自定义模板进入正式生产环境后 2 周内

---

## 1. 立项背景

Phase 0-6 已交付完整的"创建—校验—保存—运行—导出"闭环，347 个单元测试全绿。系统已经具备**功能层面的完备性**，但缺少**运行期可观测性**：

1. 一个 ReportRun 失败时，运维不知道是 DSL 校验失败、脚本超时、还是 weasyprint 缺失
2. ai-report--daily 的 fallback 触发率没有指标，无法判断 §11.4.3 "30 天 0 fallback" 下线条件
3. 一个 builtin 模板版本爆炸（用户疯狂 fork + republish）目前要等到磁盘满才会被发现
4. 一个 skill 的 `report_scripts.yaml` 误删后，依赖它的模板会静默失败

Phase 7 的目标是把这些**已知未观测**的运行风险变成**已观测、可告警**。

---

## 2. 范围

### 2.1 In Scope（本期交付）

| 工作项 | 优先级 | 简述 |
|---|---|---|
| ReportRun 指标采集 | P0 | 成功/失败计数、按 error_code 分布、按模板分布、运行时长直方图 |
| Fallback 触发统计 | P0 | `error_code = FALLBACK_TRIGGERED` 的计数 + 日维度聚合 |
| DSL Validator 失败率 | P1 | 按 error code 分类的 validator 失败率（用于发现 builtin 模板误判） |
| 模板版本爆炸告警 | P1 | 单 template 版本数 > 100 时告警 |
| 文件存储用量告警 | P1 | `{DEER_FLOW_HOME}/report-templates/` 总用量 + 每 user/tenant 用量 |
| Skill 不可用告警 | P2 | 因 skill disabled 或 registry 缺失导致的运行失败计数 |
| 用户手册 | P2 | `docs/user-guide/report-templates.md` — 创建模板的端到端教程 |
| 管理员手册 | P2 | `docs/admin-guide/report-templates.md` — builtin 模板维护、permission 管理、迁移路径 |

### 2.2 Out of Scope（不在本期）

- **V2 PostgreSQL 迁移**：单独立项，见设计文档 §7.1.5
- **通用分析报告**：单独立项，需要先建 connector / dataset registry
- **独立 ReportRun JobRunner**：仅在出现明确定时/批量报告需求时立项
- **Prometheus 之外的 telemetry 后端**：本期只对接现有指标采集，不引入新基础设施

---

## 3. 设计原则

1. **复用现有 telemetry 基础设施**：不为报告平台新建独立 metrics endpoint。如项目已用 Prometheus / OpenTelemetry，沿用；如尚未引入，先输出 JSON-log 指标供 grep。
2. **零侵入采集**：在 runtime/repository 现有调用点埋点；不为埋点修改 ReportRun 数据 schema。
3. **告警先观察，再阈值**：所有指标先采集 2 周，根据真实分布定阈值；不预设拍脑袋数字。
4. **文档跟代码走**：用户手册和管理员手册必须随 8 个 builtin 模板的实际行为同步更新。

---

## 4. 工作分解

### 4.1 ReportRun 指标采集（P0，~1.5 天）

**埋点位置**：`runtime/state.py` 的状态转换函数（`mark_succeeded` / `mark_failed`）

**指标列表**：

```text
report_runs_total{template_id, visibility, status, error_code}      counter
report_runs_duration_seconds{template_id}                            histogram
report_run_steps_total{template_id, step_kind, outcome}              counter
report_run_data_step_duration_seconds{script_qualified_name}         histogram
```

**实现要点**：

- error_code 必须从 `runs/{id}.json` 已有字段读，不要新增 enum
- 不采集 `parameters_summary` 内容（潜在用户数据泄漏风险）
- 在 ReportRun 写入磁盘时同步写指标，避免延迟双源

**测试**：埋点单元测试 + 一次端到端 daily 运行后指标曲线验证。

### 4.2 Fallback 触发统计（P0，~0.5 天）

**埋点位置**：`ai-report--daily/SOUL.md` 的 fallback 分支 + 抛出 `FALLBACK_TRIGGERED` 的工具

**指标**：

```text
report_template_fallback_triggered_total{agent_name, reason}    counter
```

reason 取值约束：`tool_error`, `builtin_missing`, `validator_regression`, `skill_disabled`。

**告警规则**：

- 日累计 > 10 次 → P2 告警（疑似 builtin 模板 broken）
- 5 分钟连续 > 5 次 → P1 告警（疑似 skill 大规模失效）
- 单个 user 当日 > 3 次 → P3 告警（疑似该用户的私有模板出问题）

**联动**：满足设计 §11.4.3 "30 天 0 fallback + 99% 成功率"时，Phase 7 工具应能输出一份可信的 30 天报告，作为下线 fallback 的决策依据。

### 4.3 DSL Validator 失败率（P1，~0.5 天）

**埋点位置**：`validator.py` 的 `validate_dsl` 返回路径

**指标**：

```text
report_template_validator_total{outcome, error_code}    counter
```

`outcome ∈ {valid, invalid}`。error_code 取自 `ValidationIssue.code`。

**告警**：单个 error_code 占比 > 50% → P2（疑似 validator 误判或 DSL schema 漂移）。

### 4.4 模板版本爆炸告警（P1，~0.5 天）

**触发器**：定时任务（每小时一次）扫描 `{DEER_FLOW_HOME}/report-templates/{users,tenants}/*/*/versions/` 计数

**告警阈值**：

- 单 template versions > 100 → P3 告警（用户疯狂 republish 或脚本误用 publish API）
- 单 user 总 template 数 > 50 → P3 告警（疑似程序化创建）
- 单 tenant 总 template 数 > 500 → P2 告警

**自动响应**：仅告警，不自动清理（避免误删用户工作）。

### 4.5 文件存储用量告警（P1，~0.5 天）

**触发器**：定时任务（每 6 小时）调用 `shutil.disk_usage` + 递归大小

**指标**：

```text
report_template_storage_bytes{owner_type, owner_id}    gauge
report_template_storage_total_bytes                     gauge
```

**告警阈值**（initial guess，2 周后校准）：

- 单 user > 1 GB → P3
- 单 tenant > 10 GB → P2
- `{DEER_FLOW_HOME}/report-templates/` 总用量 > 80% 文件系统 → P1

### 4.6 Skill 不可用告警（P2，~0.5 天）

**埋点位置**：`data_runner.py` 的 `UnknownScriptError` 抛出点 + `script_registry.py` 的 skill disable 事件

**指标**：

```text
report_template_skill_unavailable_total{skill_name, action}    counter
```

`action ∈ {disabled_after_publish, registry_load_failed}`。

**告警**：5 分钟内 > 3 次 → P1（一个 skill 被禁用导致大量已发布模板失效）。

### 4.7 用户手册（P2，~1 天）

**位置**：[docs/user-guide/report-templates.md](../user-guide/report-templates.md)（新增目录）

**覆盖内容**：

1. 报告平台是什么 / 何时该用
2. 从 builtin 模板 fork 创建第一份私有模板
3. DSL 入门：form_steps → data_steps → transforms → sections
4. JSONPath 子集语法（带 5 个常见正确/错误示例）
5. 解释性报告章节（evidence / confidence / human_review_required）
6. 发布、版本管理、共享给 tenant
7. 常见错误码对照表（取自 validator + runtime）

**质量门槛**：1 名非作者按手册从零创建一个能跑通的模板。

### 4.8 管理员手册（P2，~1 天）

**位置**：[docs/admin-guide/report-templates.md](../admin-guide/report-templates.md)

**覆盖内容**：

1. Builtin 模板的修改流程（仓库 PR → review → restart）
2. tenant_admin 权限模型 + 如何发布 tenant 模板
3. 文件存储路径布局 + 备份建议
4. Phase 7 指标含义和告警阈值含义
5. fallback 下线决策流程（§11.4.3 实操步骤）
6. V2 DB 迁移前置约束（避免现在就引入路径耦合）
7. 故障排查 runbook（按 error_code 索引）

---

## 5. 验收标准

| 项 | 验收方式 |
|---|---|
| 所有 P0/P1 指标已采集 | Prometheus（或等价物）能查到 7 天数据，曲线非空 |
| Fallback 报告可生成 | 一条 SQL/PromQL 查询能输出 30 天 fallback 触发统计，分维度 |
| 告警规则已部署 | 在 staging 注入测试故障 → 对应告警触发 |
| 用户手册可独立完成创建 | 1 名非作者按文档从零创建一个能成功 ReportRun 的私有模板 |
| 管理员手册覆盖 runbook | 列举 6 个常见 error_code 都有"如何排查"段落 |
| 单元测试 ≥ 80% | 埋点逻辑的单元测试覆盖率 |
| 文档同步 | [backend/CLAUDE.md](../../backend/CLAUDE.md) / [frontend/CLAUDE.md](../../frontend/CLAUDE.md) 新增"监控指标"分节 |

---

## 6. 风险与依赖

| 风险 | 影响 | 应对 |
|---|---|---|
| 项目暂无 Prometheus 基础设施 | 指标输出形式需调整 | 先用结构化日志（JSON），并在告警工作项前协调引入 telemetry |
| 阈值设定不准导致告警噪音 | 告警疲劳 | 所有 P2/P3 告警先静默 2 周，根据真实分布 calibrate 后启用 |
| 文档撰写人力被业务挤占 | P2 文档延后 | 优先交付 P0/P1，文档可在后续里程碑补齐；硬限制：M1 内必须有用户手册 alpha |
| Phase 7 与 V2 DB 迁移工作冲突 | 重复工作 | Phase 7 全部指标必须复用现有 metrics 命名空间，不为文件存储专门写一遍 |

---

## 7. 与设计文档对应章节

- §15 Phase 7：本立项继承设计文档 Phase 7 的 5 条工作项，并细化到指标/告警/手册级别
- §16.2 风险监控指标：本立项 P0/P1 工作项即对应此 6 个监控点
- §16.3 触发回退条件：本立项的告警阈值校验设计中的回退触发条件是否可观测、可达

---

## 8. 时间表（如启动）

| Week | 工作项 |
|---|---|
| W1 Day 1-2 | 4.1 + 4.2 P0 埋点 + 单元测试 |
| W1 Day 3-4 | 4.3-4.5 P1 埋点 + 告警规则起草 |
| W1 Day 5 | 4.6 P2 埋点 + 在 staging 跑一次故障注入 |
| W2 Day 1-2 | 4.7 用户手册 alpha + 1 名非作者验证 |
| W2 Day 3-4 | 4.8 管理员手册 + runbook |
| W2 Day 5 | 告警规则上线（先静默观察 2 周） + 交付报告 |

---

## 9. 后续路线图链接

- Phase 8（潜在）：V2 PostgreSQL 迁移（依赖 Phase 7 的 storage 用量数据决策迁移时机）
- Phase 9（潜在）：通用分析报告（依赖 connector / dataset registry 立项）
- Phase 10（潜在）：独立 ReportRun JobRunner（仅当定时报告或批量报告需求出现时启动）
