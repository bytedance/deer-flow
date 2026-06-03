# 报告模板平台 — 管理员手册

> 适合人群：平台管理员（`superadmin`）、租户管理员（`tenant_admin`）、运维。
> 阅读时长：30–40 分钟。
> 前置阅读：[用户手册](../user-guide/report-templates.md)、[设计文档](../plans/2026-05-14-ai-report-custom-template-design.md)。

---

## 1. 你负责什么

| 角色 | 主要职责 |
|---|---|
| `superadmin` | 维护 builtin 模板源码、合并 PR、决定 daily fallback 何时下线、调整 Script Registry 默认参数 |
| `tenant_admin` | 审核、发布、归档 tenant 共享模板；处理租户内的版本爆炸 / 存储用量告警 |
| 运维 / SRE | 部署 telemetry 抓取、配置告警阈值、定期跑 storage / version-count 扫描、备份模板存储目录 |

---

## 2. 文件存储布局速查

```text
{DEER_FLOW_HOME}/report-templates/        # 用户/租户运行时数据
  users/{user_id}/
    index.json                            # 用户模板索引（list 接口用）
    {template_id}/
      template.json                       # 元数据 + etag
      versions/{v1.json, v2.json, ...}    # 不可变发布版本
      runs/{report_run_id}.json           # 运行索引
  tenants/{tenant_id}/                    # 同上
  .telemetry.log                          # Phase 7 JSONL 审计日志（charter §4）

agents/builtin/report-templates/          # builtin（随仓库版本控制，只读）
  daily-equipment/{default.yaml,metadata.yaml,examples/}
  weekly-equipment/, monthly-equipment/, ...
  trend-equipment/, diagnosis-fault/, failure-analysis/, closure-summary/, inspection/
```

**关键**：

- 路径里所有 ID 都做了正则强校验（`tpl_[A-Z0-9]{20,32}`、`rr_...`），LLM 写不出越权路径。
- 写操作走 `atomic rename + etag + fcntl/Windows lock`，并发安全。
- 报告产物（`report_payload.json` + `.md` / `.pdf`）**不在** `report-templates/` 下，在 `{thread_output_dir}/report-runs/{report_run_id}/`。
- thread 是产物生命周期根：thread 删了，产物跟着删；想长期保留只能让用户主动下载。

---

## 3. Builtin 模板维护

### 3.1 修改流程（强制路径）

**禁止运行时写 builtin**。所有 builtin 改动都要走代码 PR：

```text
1. 在 agents/builtin/report-templates/{name}/ 改 default.yaml / metadata.yaml
2. 跑测试：cd backend && PYTHONPATH=. uv run pytest tests/test_builtin_report_templates.py -v
3. 跑全套 report-template 测试套件 (300+ tests)
4. PR 审核 → 合并 → 部署 → 重启 Gateway 让 in-memory 索引重新加载
```

### 3.2 何时增加 builtin

- 新增了一种通用业务报告（且至少 2 个租户都会用）。
- 现有模板的章节结构变化已经被 5+ 用户 fork 后做了同样的改动。
- 新业务领域接入（需要新 skill + 新 builtin）。

### 3.3 何时拒绝把用户模板"升级"成 builtin

- 用户模板里有租户专属术语 / 业务规则。
- 用户模板依赖了未在 `report_scripts.yaml` 注册的脚本。
- 用户模板用了占位符黑名单语法（即便 validator 没拦下来，PR review 也应该拦）。

---

## 4. 权限矩阵实操

| 操作 | 谁能做 | 关键校验点 |
|---|---|---|
| 创建 private 模板 | 任何登录用户 | 自动归属到 `user_id` |
| 创建 tenant 模板 | `tenant_admin` 或 `superadmin` | 在 `tenant_id` 上下文里 |
| `private → tenant` 升级 | `tenant_admin` 或 `superadmin` | `permissions.check_permission(action=upgrade_visibility)` |
| `tenant → builtin` 升级 | 通过代码 PR 而非 API | 运行时直接拒绝 |
| 发布版本 | 模板的所有者 / `tenant_admin` | `expected_current_version` 必须等于当前 |
| 归档（soft-disable） | 所有者 / `tenant_admin` | 仅改 status，不删数据 |
| 硬删除 | 所有者 / `tenant_admin` / `superadmin` | 同时清 index 和 versions/ |

### 4.1 处理"误删/锁死"工单

- 用户误删 private 模板 → 从最近的备份（见 §6）恢复 `template.json` + 整个 `versions/` 目录。
- 用户卡在"editor 改了 published 模板但发布失败"→ `expected_etag` 不匹配，让用户拉最新版本再保存。
- 租户 admin 离职 → `superadmin` 直接修改 `template.json` 的 `owner_user_id` 字段（atomic rename），不需要新工具。

---

## 5. Phase 7 监控指标含义

所有指标来自 `/api/telemetry/report-templates/summary`（GET）；运行时埋点写到 `.telemetry.log`（JSONL）。

### 5.1 ReportRun outcome

```json
"report_runs": {
  "total": 1234,
  "success_rate": 0.991,
  "by_template_status_error": [
    {"template_id": "builtin-daily-equipment", "status": "exported", "count": 800},
    {"template_id": "builtin-daily-equipment", "status": "failed", "error_code": "SCRIPT_TIMEOUT", "count": 4},
    ...
  ],
  "avg_duration_seconds_by_template": {"builtin-daily-equipment": 4.2}
}
```

**告警阈值**（charter §4.1 + §16.3）：

- 5 分钟内全平台 `success_rate < 0.80` → **P1**
- 单 thread 内连续 3 次 `failed` → **P1**（应用层逻辑，需要单独 cron）
- 单 template 平均 duration > 60s → **P2**（疑似脚本慢或数据爆炸）

### 5.2 fallback_triggered

```json
"fallback_triggered": {
  "total": 5,
  "by_agent_reason": [
    {"agent_name": "ai-report--daily", "reason": "tool_error", "count": 5}
  ]
}
```

**reason 取值**：`tool_error` / `builtin_missing` / `validator_regression` / `skill_disabled`。

**告警阈值**：

- 日累计 > 10 次 → **P2**（疑似 builtin / skill 出问题）
- 5 分钟连续 > 5 次 → **P1**（疑似 skill 大规模失效）
- 单 user 当日 > 3 次 → **P3**（疑似该用户的私有模板问题——但 fallback 当前只在 daily agent，这条暂时观察）

**fallback 下线判定** (设计 §11.4.3 → charter §4.2)：

- 满足"30 天 0 fallback + 99% 成功率"两个条件 → 可以删除 `ai-report--daily/SOUL.md` 的 fallback 分支。
- 跑 `find ~/.gstack/.telemetry.log -mtime -30 | xargs grep '"type":"fallback_triggered"' | wc -l` 验证。

### 5.3 validator_outcome

```json
"validator": {
  "total": 580,
  "by_outcome_error": [
    {"outcome": "valid", "count": 530},
    {"outcome": "invalid", "error_code": "UNKNOWN_SCRIPT", "count": 30},
    {"outcome": "invalid", "error_code": "JSONPATH_INVALID", "count": 20}
  ]
}
```

**告警**：单个 invalid `error_code` 占总 invalid 数 > 50% → **P2**（疑似 validator 误判或 builtin/schema 漂移）。

### 5.4 storage / version_count

由 `POST /api/telemetry/report-templates/scan-storage` 和 `/scan-versions` 一次扫描触发，建议 6 小时跑一次：

```json
"storage": {
  "by_owner": [{"owner_type": "users", "owner_id": "u123", "bytes_used": 1100000000}],
  "total_bytes": 12345678901
},
"version_counts": [
  {"template_id": "tpl_xxx", "version_count": 137}
]
```

**告警阈值**（initial guess，charter 要求观察 2 周后校准）：

- 单 user > 1 GB → **P3**
- 单 tenant > 10 GB → **P2**
- 总用量 > 80% 文件系统 → **P1**
- 单 template versions > 100 → **P3**（疑似 republish 循环）
- 单 user templates 总数 > 50 → **P3**
- 单 tenant templates 总数 > 500 → **P2**

### 5.5 skill_unavailable

```json
"skill_unavailable": {
  "total": 2,
  "by_skill_action": [
    {"skill_name": "daily-report", "action": "disabled_after_publish", "count": 1},
    {"skill_name": "ops-skill", "action": "registry_load_failed", "count": 1}
  ]
}
```

**告警**：5 分钟内 > 3 次 → **P1**（一个 skill 大概率挂了，影响所有依赖它的模板）。

---

## 6. 备份 / 恢复

### 6.1 备份对象

| 路径 | 频率 | 保留 |
|---|---|---|
| `{DEER_FLOW_HOME}/report-templates/` | 每日全量 | 30 天 |
| `agents/builtin/report-templates/` | 跟随 git 仓库 | 永久（git 历史） |
| `{thread_output_dir}/.../report-runs/` | 不强制备份 | thread 删除即销毁，用户应自行下载 |
| `.telemetry.log` | 周轮换 | 90 天（用于 fallback 下线决策） |

### 6.2 恢复演练

每季度演练一次：

1. 选一个 tenant，把它的 `tenants/{tenant_id}/` 整个目录从备份还原到 staging。
2. 启动 Gateway，跑 `/api/report-templates?visibility=tenant` 应能列出全部模板。
3. 从一个 published 版本触发一次 ReportRun，应能成功导出。
4. 校验 `index.json` 与目录实际内容一致（备份中可能出现 index drift）。

---

## 7. 故障 runbook

按 error_code 排查；用户端的错误信息已经脱敏，详细堆栈在 server log。

### `SCHEMA_INVALID`

**症状**：保存 / validate 时返回 invalid。
**原因**：DSL 字段拼写错、类型错、新增的 schema 字段没适配老模板。
**排查**：
1. 看 error 的 `path` 字段定位到具体字段。
2. 对比 `report_templates/schema.py` 的 Pydantic 定义。
3. 如果是新增 schema 字段导致老 builtin 被判非法，回滚 schema 改动或同步更新所有 builtin。

### `UNKNOWN_SCRIPT`

**症状**：DSL 引用的 script 在 registry 找不到。
**原因**：skill disabled / `report_scripts.yaml` 写错 / script 改名了。
**排查**：
1. `GET /api/skills` 看 skill 是否 `enabled=true`。
2. `cat skills/custom/{skill}/report_scripts.yaml` 看 `scripts.<name>` 存在。
3. DSL 里 `data_steps[].name` 必须用 namespace 形式：`{skill_name}/{script_name}`。
4. 同时会有一条 `skill_unavailable` telemetry，配合告警监控。

### `JSONPATH_INVALID`

**症状**：占位符表达式被拒绝。
**原因**：用户用了过滤器 / `..` / 函数 / 索引 等黑名单语法。
**排查**：
1. 看 path 字段，定位到具体占位符。
2. 用户手册 §4.2 列了 5 种最常见错法。
3. 不要扩展白名单——计算能力下沉到脚本里。

### `PATH_NOT_FOUND`

**症状**：运行时求 JSONPath 失败。
**原因**：脚本没有按 outputs_schema 输出 → 模板 source 读不到字段。
**排查**：
1. 看 `{thread_output_dir}/report-runs/{rr_id}/data/` 里实际 JSON 内容。
2. 对比脚本声明的 `outputs_schema`（在 `report_scripts.yaml` 里）。
3. 通常是脚本侧 bug，让 skill 作者修。

### `SCRIPT_TIMEOUT`

**症状**：脚本执行超过 `timeout_seconds`。
**原因**：数据量超出预期 / TSDB 慢 / 脚本死循环。
**排查**：
1. 看 `{thread_output_dir}/report-runs/{rr_id}/status.json` 里 `error_message` 字段。
2. 临时调大 `report_scripts.yaml` 的 `timeout_seconds`（默认 60–180s 不等）。
3. 长期：让 skill 作者优化脚本 / 分批拉数据。

### `INPUT_UNREADABLE`

**症状**：transform 读不到上游 data_step 输出。
**原因**：上游脚本提前失败 / output 文件路径与 `outputs:` 声明不一致。
**排查**：
1. 看 `{thread_output_dir}/report-runs/{rr_id}/data/` 是否有上游 JSON。
2. transform 的 `input` 字段格式：`{data_step_id}.{output_id}`。
3. 通常是脚本 bug 或 DSL `outputs` 拼写错。

### `STATE_MISMATCH`

**症状**：工具调用顺序与 `status.json` 期望不符。
**原因**：LLM 漂移（极少见），或并发提交了过期 callback。
**排查**：
1. 看 `status.json` 的 `expected_step` 字段。
2. 让 agent 调 `report_template_resume_run` 重置到正确位置。
3. 如果反复出现，看是否多个会话/多个 thread 共用了同一 report_run_id（不应该发生）。

---

## 8. V2 PostgreSQL 迁移前置约束

MVP 是文件存储，V2 会迁到 DB。**现在你要做的**：

- 不在文件里存"路径相对当前目录"的引用——所有 path 字段必须是绝对的 schema 字段（path 本身可以相对，但意义不能依赖目录位置）。
- 所有时间戳必须是 ISO 8601 with timezone（`+00:00`，不要写裸 `Z`，部分老旧 Python 不识别）。
- ID 字段命名要对齐目标 DB schema（已经在 records.py 锁定）。
- 不要在文件里塞 cache / 临时计算结果——一旦 DB 迁移这些会被丢弃。

V2 立项时会写迁移脚本 `migrate_report_templates.py`：扫描所有 `users/*/`、`tenants/*/`，逐条写入 DB，双写过渡 1 周后切换。

---

## 9. 常见运维任务清单

| 任务 | 命令 / 路径 |
|---|---|
| 跑一次存储扫描 | `curl -X POST .../api/telemetry/report-templates/scan-storage` |
| 跑一次版本计数 | `curl -X POST .../api/telemetry/report-templates/scan-versions` |
| 看当前 telemetry 汇总 | `curl .../api/telemetry/report-templates/summary` |
| 看 fallback 30 天总数 | `grep '"type":"fallback_triggered"' {DEER_FLOW_HOME}/report-templates/.telemetry.log \| wc -l` |
| 重新加载 builtin 模板 | 重启 Gateway（Python 进程） |
| 禁用某个 skill | 关掉 `extensions_config.json` → `skills.{name}.enabled = false`；下次 registry 刷新生效 |
| 测试 daily fallback 路径 | 把 `daily-report` skill 临时禁用，跑一次 ai-report--daily → 应触发 fallback 并写入 telemetry |
| 跑所有报告模板测试 | `cd backend && PYTHONPATH=. uv run pytest tests/test_report_template_*.py tests/test_builtin_report_templates.py tests/test_ai_report_*.py` |

---

## 10. 升级路径

| 现状 | 想升级到 | 操作 |
|---|---|---|
| MVP 文件存储 | V2 PostgreSQL | 见 §8 + V2 立项文档（未立项） |
| 无 fallback 监控 | 有告警 | Phase 7 的 telemetry 已就位，对接你的告警平台即可 |
| 仅 daily 走 DSL | weekly/monthly 也走 DSL | builtin 已就位，把对应 agent 的 SOUL.md 改成"先调 report_template_get"模式 |
| 单租户 builtin | 多租户共享 | 升级 visibility 时让 admin 控制 |
| 通用分析报告 | — | 见 §13.10，需要先建 connector/dataset registry，**不在本 Sprint 范围** |
