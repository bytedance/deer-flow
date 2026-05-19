# Closed-Loop Management — 灰度发布与回滚清单

> 适用于 OpenSpec change `closed-loop-management`。本文档由 §10.4 / §10.5 任务产出，
> 仅供发布与运维使用，未进入终端用户文档（用户文档默认跳过，详见 §10.3）。

## 1. 灰度发布检查清单（§10.4）

### 1.1 数据库迁移

- [ ] 在目标租户共享的 PostgreSQL 实例上执行 `alembic upgrade head`，确认
  - `closure_tickets` 表已建
  - `closure_ticket_events` 表已建
  - 唯一索引 `uq_closure_tickets_source` 与时间序索引存在
  - SLA 默认配置 (urgent=4h / important=72h / normal=7d / observe=30d) 已 seed
- [ ] 反向回滚（`alembic downgrade -1`）在 staging 上演练成功（已在 §1.4 测试覆盖，发布前再手动执行一次以确认 schema 漂移可恢复）

### 1.2 Feature flag

- [ ] 在配置中心为目标租户开启 `closed_loop_management`（默认值：关闭）
- [ ] 全量租户列表（generation 1）：内部测试租户
- [ ] 全量租户列表（generation 2）：1 个生产试点租户
- [ ] 灰度过程中保持 `closed_loop_management=false` 时，下列接口必须仍 404：
  - `POST /api/closure/tickets`
  - `GET /api/closure/tickets`
  - `POST /api/closure/tickets/{id}/transition`

### 1.3 Agent SOUL 与工具

- [ ] `agents/builtin/defect-closure/SOUL.md` 已切换为闭环单中心工作流
- [ ] `agents/builtin/ai-report--closure/SOUL.md` 已分段（已闭环 / 未闭环 / 超期未闭环）
- [ ] `agents/builtin/fault-diagnosis*/SOUL.md` 已加入"严重等级达标 → `create_closure_ticket`"步骤
- [ ] `agents/builtin/ai-report--{daily,weekly,monthly,custom}/SOUL.md` 已加入整改项登记 / 撤回流程
- [ ] `agents/builtin/report-templates/closure-summary/default.yaml` 已包含 `closure_section` 范例
- [ ] 灰度租户的运行时 SOUL 缓存已刷新（重启 langgraph worker 或主动 `POST /admin/agents/refresh`）

### 1.4 后台任务

- [ ] FastAPI startup 启动了 `closure_overdue_scan_job`（5 分钟周期）
- [ ] PG advisory lock id 已注册并未与其他周期任务冲突
- [ ] 启动后第 1 周期日志中能看到 `closure_overdue_scan: scanned=N, overdue=M`

### 1.5 监控指标 / 看板

- [ ] Grafana 看板新增 panel：
  - `closure.created` 计数（按 source_type 分布）
  - `closure.overdue` 计数（按 priority 分布）
  - `closure.closed` 计数（按 reject vs verify 分布）
  - 5 分钟扫描任务的执行时延 P95
- [ ] 告警规则：单租户 `closure.overdue` 在 1 小时内增长 > 10 触发 P3 告警

### 1.6 前端

- [ ] `/workspace/closed-loop` 路由可访问（仅 feature flag on 且具备 `closure:read` 时）
- [ ] 侧边栏「闭环管理」入口仅在汇总接口返回数据时显示徽标
- [ ] 列表 / 看板 / 抽屉的乐观更新可被服务端真实状态覆盖（不会卡住"派单中…"）

### 1.7 单元 / 集成 / E2E 验证

- [ ] 后端：`pytest -k closed_loop` 全绿
- [ ] 前端：`pnpm test tests/unit/components/workspace/closed-loop/` 全绿
- [ ] E2E：`pnpm test:e2e closed-loop.spec.ts closed-loop-from-daily-report.spec.ts` 全绿

## 2. 回滚演练手册（§10.5，仅文档不执行）

> 注意：以下流程为演练 SOP。生产环境真实回滚需经过变更评审与 CTO 批准。
> 本节描述「禁用 feature flag → revert Agent SOUL → 验证旧链路功能正常」的步骤
> 与回滚验收点。

### 2.1 触发回滚的判据（任一即可）

- 闭环单创建/迁移接口在生产 5 分钟错误率 > 5%
- 后台超期扫描任务连续 3 个周期失败且无法即时修复
- Agent 误触发建单导致工单暴涨（24h 内单租户 > 1000 单且无关联诊断证据）
- 看板出现关键回归（旧报告渲染失败 / 现有 Agent 流程被阻断）

### 2.2 步骤 1：禁用 feature flag

1. 在配置中心将 `closed_loop_management` 改为 `false`
2. 验收：5 分钟内 `/api/closure/*` 返回 404 / 403
3. 验收：前端侧边栏「闭环管理」入口隐藏，访问 `/workspace/closed-loop` 显示 "无权限"

> ⚠️ 已建立的 ticket 数据保留在 DB，不删除。后续修复后可继续使用。

### 2.3 步骤 2：回退 Agent SOUL

1. 通过 `git revert` 回退以下文件至上一稳定 tag：
   - `agents/builtin/defect-closure/SOUL.md`、`config.yaml`
   - `agents/builtin/ai-report--closure/SOUL.md`
   - `agents/builtin/fault-diagnosis*/SOUL.md`
   - `agents/builtin/ai-report--{daily,weekly,monthly,custom}/SOUL.md`
2. 灰度发布回退 commit
3. 调用 `POST /admin/agents/refresh` 强制刷新 SOUL 缓存
4. 验收：诊断 Agent 在严重故障场景下不再调用 `create_closure_ticket`，回到上一版回复格式

### 2.4 步骤 3：停用后台扫描

1. 在 deployment manifest 中临时把 `CLOSURE_OVERDUE_SCAN_ENABLED` 设为 `false`
2. 滚动重启 FastAPI gateway 副本
3. 验收：日志中不再出现 `closure_overdue_scan` 行；PG advisory lock 释放

### 2.5 步骤 4：旧链路冒烟

逐一在受影响租户验证以下旧链路恢复正常：

- 故障诊断 Agent：触发严重诊断 → 直接生成总结消息（无 ticket id）
- 日报 Agent：识别整改项 → 直接在报告正文中给出建议（无新建工单）
- 报告模板渲染：包含 `closure_section` 的模板渲染时应回退到「该区块在当前发布中不可用」占位文本
  - 检查 `report_templates/runtime/payload_builder.py` 在 `closed_loop_management=false`
    时的兜底分支
- `/workspace/closed-loop` 路由不可达
- `/workspace/chats/...`、`/workspace/agents/...` 无回归

### 2.6 步骤 5：留存与复盘

- 保留所有 `closure_tickets` 与 `closure_ticket_events` 数据，便于事后复盘与二次发布
- 在 incident channel 同步：触发原因、影响面、回滚耗时、后续修复 owner
- 复盘后更新本 runbook，把实际遇到的问题作为 §2.1 判据补充

## 3. 不在本期范围

- 用户文档（§10.3，已与用户确认默认跳过）
- 多语言（i18n）
- 移动端样式专项优化
