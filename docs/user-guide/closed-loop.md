# 闭环管理 — 用户手册

> 适合人群：负责整改跟踪、巡检复核或运行报告闭环的运维主管、班组长、专责工程师。
> 阅读时长：10–15 分钟（含动手练习）。
> 配套设计与发布材料：
> - 状态机与字段设计：[2026-05-19-closed-loop-management-release-and-rollback.md](../plans/2026-05-19-closed-loop-management-release-and-rollback.md)
> - OpenSpec 变更：`openspec/changes/closed-loop-management/`

---

## 1. 你能用它做什么

闭环管理把「发现问题 → 派单 → 处置 → 验证 → 关闭」一条龙搬到工作台里：

1. 故障诊断 Agent 出严重结论时，自动建一张「闭环单」并附上诊断 run / 设备 / 严重等级。
2. 日报 / 周报 / 月报 / 自定义报告 Agent 在生成报告时，把识别出的整改项也登记成闭环单。
3. 你在工作台「闭环管理」页面派单 → 处置人填写处置过程 → 验证人确认或退回 → 关闭。
4. 整改进度回流到下一周期的报告里（`closure_section` 区块），不会再"发现归发现、整改归整改"。

**典型场景**：

- 振动 / 温度 / 油液 类严重诊断结论的整改跟踪
- 日报里"建议复查"的设备纳入下周复盘
- 月度安全 / 可靠性指标里的"未关闭项"看板

**不适合**：

- 一次性、与设备无关的临时事项（用普通待办即可）
- 跨业务系统的工单流转（本期不与外部 EAM/CMMS 对接，仅在工作台内闭环）

---

## 2. 五分钟跑通第一张闭环单

最快的方式是让诊断 Agent 帮你建一张：

1. 在工作台进入「故障诊断」智能体，给它一段你设备的最近运行情况（或直接选设备）。
2. 当 Agent 输出严重等级 ≥ `high` 的结论时，它会自动调用 `create_closure_ticket` 工具，并在回复里告诉你新单的 ID（形如 `tkt-xxxxxxxxxxxx`）。
3. 点击侧边栏「闭环管理」入口，徽标会显示当前未关闭数 / 超期数。
4. 在列表中找到刚刚的单子，点击进入详情抽屉，依次执行：
   - **派单**：填一个受理人 user id（同租户即可）
   - **开始处置**：受理人确认接单
   - **提交验证**：处置人写一段处置经过 / 验证依据
   - **验证关闭**（仅租户管理员或超管可执行）：确认整改有效，关闭单子

走完一遍你就掌握了闭环管理的全部核心动作。

---

## 3. 来源：单子是从哪里来的

闭环单的 `source_type` 字段固定为下列六种之一，决定了「来源」入口：

| source_type | 来源 | 谁建的 |
|-------------|------|--------|
| `diagnosis` | 故障诊断会话 | `fault-diagnosis*` Agent 工具自动 |
| `daily_report` | 日报 | `ai-report--daily` Agent 工具自动 |
| `weekly_report` | 周报 | `ai-report--weekly` Agent 工具自动 |
| `monthly_report` | 月报 | `ai-report--monthly` Agent 工具自动 |
| `custom_report` | 自定义报告 | `ai-report--custom` Agent 工具自动 |
| `manual` | 手工 | 用户在工作台手工新建（API 直连） |

每张单子的详情页右上角都有「前往原始 …」链接：

- 来源是 `diagnosis` / `manual`：跳到原始诊断 / 对话会话
- 来源是 `*_report`：跳到对应报告运行（`/workspace/report-runs/{run_id}`）

不会出现"找不到出处"的情况。

---

## 4. 状态机：单子会经历哪些阶段

```
pending ──assign──▶ assigned ──start──▶ in_progress ──submit_verification──▶ pending_verification
                                                                              │
                                                                              ├──verify_close──▶ closed
                                                                              └──reject──▶ rejected
```

每一步在抽屉里都对应一个按钮；按钮按当前状态自动出现 / 隐藏，且按权限点过滤：

| 动作 | 谁能执行 | 必填 | 效果 |
|------|---------|------|------|
| 派单（assign） | 任意拥有 `closure:write` 的成员 | `assignee_id` | 单子进入 `assigned` |
| 开始处置（start） | 同上 | — | 单子进入 `in_progress`，开始计 SLA |
| 提交验证（submit_verification） | 同上 | `verification_summary` | 单子进入 `pending_verification` |
| 验证关闭（verify_close） | 仅 `tenant_admin` / `superadmin`（拥有 `closure:verify`） | 验证摘要可选 | 单子 `closed` |
| 退回（reject） | 仅 `tenant_admin` / `superadmin` | `rejection_reason` | 单子 `rejected`，可被重新派单 |

> 系统不会让你"一口吃成胖子"——比如不能从 `pending` 直接跳到 `closed`，状态机会把跨步的请求拒绝。

---

## 5. SLA 与超期：怎么判定 / 看哪里

每张单子在被派单时会按优先级算出 `due_at`：

| 优先级 | 默认 SLA |
|--------|---------|
| `urgent` | 4 小时 |
| `important` | 72 小时 |
| `normal` | 7 天 |
| `observe` | 30 天 |

> 这是租户级默认值，由后端 seed 数据写入；想调整请联系租户管理员配合更新 SLA 配置。

到期未关闭时：

- 后台扫描任务（每 5 分钟一轮）会把 `is_overdue` 置为 `true`，写入 `closure.overdue` 事件。
- 列表里整行会被红色背景高亮。
- 看板上对应卡片边框变红。
- 侧边栏「闭环管理」徽标会显示超期数（红色），并优先于"未关闭数"显示。
- 头部 Pill「超期」会变红色提示。

---

## 6. 列表 vs 看板：什么时候用哪个

**列表视图**（默认）

- 适合：需要按状态 / 优先级 / 来源 / 是否超期组合筛选
- 支持：URL 查询参数同步（可以把链接发给同事，对方打开就是同样的过滤条件）
- 支持：分页（每页 50）

**看板视图**

- 适合：每日站会、可视化巡视、看积压
- 五列：待派单 / 已派单 / 处置中 / 待验证 / 已关闭
- 看板是只读的——你点卡片仍然弹详情抽屉做动作；不支持拖拽改状态（避免越过状态机校验）

切换：右上角「列表 / 看板」分段控件。

---

## 7. 报告里的整改追踪段（`closure_section`）

当你 fork 一份报告模板时，可以在 YAML 里加一个 `closure_section` 区块，让报告自动渲染未关闭 / 超期的闭环单表格。最小例子：

```yaml
sections:
  - id: open-tickets
    title: "未关闭整改项"
    component: closure_section
    filters:
      statuses: ["pending", "assigned", "in_progress", "pending_verification"]
      page_size: 20
```

可用的 `filters`：

| 字段 | 说明 |
|------|------|
| `statuses` | 闭环状态白名单（默认未关闭四态） |
| `device_ids` | 设备 ID 数组（支持 JSONPath 引用上一步表单值） |
| `period_start` / `period_end` | ISO8601 时间窗，按 `created_at` 过滤 |
| `page_size` | 1–100 |

> 详细字段释义见 [`agents/builtin/report-templates/closure-summary/default.yaml`](../../agents/builtin/report-templates/closure-summary/default.yaml) 的注释版示例。

如果筛选结果为空，区块会渲染一句"暂无符合条件的闭环单"占位文本，而不是把表格留空。

---

## 8. 权限与多租户

- 所有闭环单严格按 `tenant_id` 隔离，跨租户不可见。
- 前端 / 工具 / API 都会注入当前用户的 `tenant_id`（`principal_from_runnable_config`），无法人为指定。
- 三个权限点：

  | 权限 | 默认拥有者 | 用于 |
  |------|-----------|------|
  | `closure:read` | 全体登录用户 | 列表 / 详情 / 看板 / 报告区块 |
  | `closure:write` | 全体登录用户 | 派单 / 处置 / 提交验证 / 手工建单 |
  | `closure:verify` | tenant_admin / superadmin | 验证关闭 / 退回 |

- 抽屉里的"验证关闭 / 退回"按钮会基于当前用户的 `system_role` 自动隐藏；后端也会在路由层兜底校验，前端绕过也没用。

---

## 9. 常见问题

**Q1. 我的诊断结论很严重，为什么没建闭环单？**
A. Agent 仅在严重等级达到 `high` 及以上才建单。`medium` / `low` 默认不建——避免噪音。
你可以在抽屉里手工新建（或要求 Agent 重新评估）。

**Q2. 误建的单怎么办？**
A. 进入抽屉，处置人 / 受理人提交"提交验证"，附说明`此单为误判`，再由验证人按"退回"操作（或者验证关闭并写明"误判"）。
不建议直接删数据库——闭环事件审计依赖完整时间线。

**Q3. 谁能看见受理人 / 创建人的真实姓名？**
A. 当前版本字段存的是 `user_id`。前端如需展示姓名，请等待 RBAC 用户档案对接。

**Q4. 我把 feature flag 关了，但已建立的单还在吗？**
A. 在。Feature flag 仅控制路由 / 工具是否对外暴露，数据库内的 `closure_tickets` 表不会被清空，重新打开后所有历史数据都还在。

**Q5. 我能批量导出未关闭单吗？**
A. 可以，使用 `ai-report--closure` Agent 生成「闭环复核报告」，它会调用 `list_closure_tickets` 并按"已闭环 / 未闭环 / 超期未闭环"三段输出 Markdown。

---

## 10. 我从哪儿继续

- 想自己 fork 一份"闭环复核周报"模板：见 [报告模板平台用户手册](report-templates.md) §3 fork builtin 流程。
- 想改 SLA 默认值：联系租户管理员更新 `sla_config` 表（仅当前授权方式）。
- 想把闭环事件接到外部告警渠道：现阶段事件只发布到内部 `run_event` 通道。如有外接需求，请向后端团队提需求。
- 出问题想回滚：见 [发布与回滚清单](../plans/2026-05-19-closed-loop-management-release-and-rollback.md) 第 2 节。
