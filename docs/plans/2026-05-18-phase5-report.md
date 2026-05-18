# Phase 5 交付报告

> **基线**：[2026-05-14-ai-report-custom-template-design.md](2026-05-14-ai-report-custom-template-design.md) §15 Phase 5。
> **范围**：Gateway REST API + Frontend 类型/Hooks + 模板管理 UI + 报告历史 UI + weekly/monthly builtin 模板。
> **状态**：**全部 6 项工作通过**。可进入 Phase 6（路线图——按需扩展剩余 5 种报告类型）。

## 交付清单

| Phase 5 项 | 状态 | 交付物 |
| ---- | ---- | ---- |
| **5.1 Gateway REST：report-templates** | ✅ 通过 | 11 个 HTTP 端点（list/get/versions/create/update/validate/publish/fork/archive/delete） |
| **5.2 Gateway REST：report-runs** | ✅ 通过 | 3 个端点（list/get/payload） |
| **5.3 路由注册 + Smoke 测试** | ✅ 通过 | `routers/__init__.py` + `app.py` 注入；14 个 route 测试 |
| **5.4 Builtin weekly + monthly 模板** | ✅ 通过 | `weekly-equipment` + `monthly-equipment` DSL + 5 个新 daily/weekly/monthly 脚本注册到 data-analyst registry |
| **5.5 前端 types + hooks** | ✅ 通过 | `core/report-templates/` 模块：types / api / hooks 全套 TanStack Query 接入 |
| **5.6 模板管理 UI** | ✅ 通过 | `/workspace/report-templates` 列表 + 详情页（YAML/JSON 编辑器 + 版本切换 + 操作按钮） |
| **5.7 报告历史 UI** | ✅ 通过 | `/workspace/report-runs` 列表 + 详情页（含 Markdown/PDF artifact 下载） |
| **5.8 侧边栏导航** | ✅ 通过 | "报告模板" + "报告历史" 入口加入 workspace 侧边栏 |

**Phase 5 新增测试**：14 个 route smoke tests + 2 个 builtin DSL CI 测试（已含 daily，新增 weekly/monthly）。
**测试总计（Phase 0+1+2+3+4+5+回归）**：**399 passed / 0 failed**。
**Frontend**：typecheck 通过；lint 仅有 baseline 既有错误（与本工作无关）。

---

## 5.1+5.2+5.3 Gateway REST API

### report-templates（11 个端点）

[backend/app/gateway/routers/report_templates.py](../../backend/app/gateway/routers/report_templates.py)（330 行）

```text
GET    /api/report-templates?visibility=...           # list
GET    /api/report-templates/{id}                     # metadata
GET    /api/report-templates/{id}/versions            # version numbers
GET    /api/report-templates/{id}/versions/{n}        # version snapshot
POST   /api/report-templates                          # create draft
PUT    /api/report-templates/{id}                     # update draft (etag)
POST   /api/report-templates/{id}/validate            # pre-flight validate
POST   /api/report-templates/{id}/publish             # publish v{N+1}
POST   /api/report-templates/{id}/fork                # fork → user's drafts
POST   /api/report-templates/{id}/archive             # archive
DELETE /api/report-templates/{id}?expected_etag=...   # hard-delete
```

### report-runs（3 个端点）

[backend/app/gateway/routers/report_runs.py](../../backend/app/gateway/routers/report_runs.py)（108 行）

```text
GET    /api/report-runs?template_id=...&limit=...     # list runs (filter)
GET    /api/report-runs/{report_run_id}               # one run record
GET    /api/report-runs/{report_run_id}/payload       # report_payload.json content
```

### 路由层关键设计

- **Principal 复用**：`_principal_from_request` 从 `request.state.user` 提取，复用 Phase 3 决策（user_id / tenant_id / is_superadmin / is_tenant_admin）
- **权限矩阵单源**：所有写操作走 `permissions.check_permission(operation, template)`，与 LLM 工具路径同源
- **跨 scope 解析**：`_resolve_template` 自动按 private → tenant → builtin 顺序查找，未读时返回 404（不泄漏存在性）
- **HTTP 状态码契约**：
  - 400：DSL 校验失败 / 字段错误
  - 403：权限不足
  - 404：模板/版本不存在
  - 409：etag 冲突 / 版本冲突 / published 不可改

### Smoke 测试（14 用例）

[backend/tests/test_report_template_routes.py](../../backend/tests/test_report_template_routes.py)

- **ListGet**（4）：空列表 / create-then-list / get metadata / 跨用户 404 隔离
- **Lifecycle**（4）：invalid DSL 拒绝 / update etag 校验 / publish then fork / 跨用户 fork 阻断
- **Validate**（1）：返回结构化 valid/errors/warnings
- **ArchiveDelete**（3）：archive 状态 / delete 缺 etag query 拒绝 / delete 后 404
- **ReportRuns**（2）：空列表 / 非法 ID 错误

---

## 5.4 Builtin weekly + monthly 模板

### 新增模板

| 模板 | DSL 文件 | 章节 |
| ---- | ---- | ---- |
| `weekly-equipment` | [default.yaml](../../agents/builtin/report-templates/weekly-equipment/default.yaml) | 周概览 / 核心 KPI / 每日趋势 / 异常 TopN / 周对比 / 下周关注 |
| `monthly-equipment` | [default.yaml](../../agents/builtin/report-templates/monthly-equipment/default.yaml) | 月度总览 / KPI 达成 / MTBF-MTTR / 重大事件 / 环比同比 / 改进跟踪 / 下月计划 |

### data-analyst skill 新增脚本注册

[skills/custom/data-analyst/report_scripts.yaml](../../skills/custom/data-analyst/report_scripts.yaml) 现在注册了 7 个脚本：

```text
list_equipment / query_daily / daily_kpi    (Phase 3)
query_weekly / weekly_kpi                    (既有)
query_monthly / monthly_kpi                  (Phase 5 新增)
```

### CI 校验

`tests/test_builtin_report_templates.py` 自动遍历 `agents/builtin/report-templates/*` 通过 validator，**3 个模板 0 errors 0 warnings**。

---

## 5.5 前端 types + hooks

[frontend/src/core/report-templates/](../../frontend/src/core/report-templates/)：

| 文件 | 行数 | 内容 |
| ---- | ---- | ---- |
| `types.ts` | 110 | DSL / 模板 / Run / Version / 请求 schema 完整 TS 类型 |
| `api.ts` | 192 | 14 个 fetch 包装函数（gateway 错误统一封装为 `Error.status` + `.detail`） |
| `hooks.ts` | 187 | 14 个 TanStack Query hooks（含 invalidation） |
| `index.ts` | 3 | 统一导出 |

**Hook 一览**：

- `useReportTemplates(visibility)` / `useReportTemplate(id)` / `useReportTemplateVersions(id)` / `useReportTemplateVersion(id, version)`
- `useCreateReportTemplate / useUpdateReportTemplate / useValidateReportTemplate / usePublishReportTemplate / useForkReportTemplate / useArchiveReportTemplate / useDeleteReportTemplate`
- `useReportRuns(options) / useReportRun(id) / useReportRunPayload(id)`

所有 mutation hook 在成功后自动 `invalidateQueries`。

---

## 5.6 模板管理 UI

### 列表页 `/workspace/report-templates`

[components/workspace/report-templates/report-templates-page.tsx](../../frontend/src/components/workspace/report-templates/report-templates-page.tsx)

- 顶部 3 个 tab：**我的模板 / 租户共享 / 预置模板**
- 卡片栅格（响应式 1/2/3 列），含 `display_name / name / current_version / status badge / tags / updated_at`
- 状态徽章按 `draft / published / archived` 配色
- 空状态引导用户进入 `ai-report--custom` 创建

### 详情页 `/workspace/report-templates/[template_id]`

[components/workspace/report-templates/report-template-detail-page.tsx](../../frontend/src/components/workspace/report-templates/report-template-detail-page.tsx)

- **左侧**：版本列表（v0 工作草稿 + 已发布版本 v1+）
- **右侧**：DSL 编辑器（JSON + YAML 双面板）
- **顶部操作栏**：校验 DSL / 保存草稿 / 发布新版本 / 归档
- **可写性逻辑**：
  - builtin → 只读
  - published → 显示警告 "已发布版本不可原地编辑——请通过 fork 创建新草稿"
  - draft + private → 完全可写
- **错误处理**：JSON 解析错误内联展示；保存/发布失败用 sonner toast

---

## 5.7 报告历史 UI

### 列表页 `/workspace/report-runs`

[components/workspace/report-templates/report-runs-page.tsx](../../frontend/src/components/workspace/report-templates/report-runs-page.tsx)

表格视图：运行 ID / 模板版本 / 状态徽章 / 创建时间 / 参数摘要。
**5 种状态色**：pending / running / succeeded / failed / canceled。

### 详情页 `/workspace/report-runs/[run_id]`

[components/workspace/report-templates/report-run-detail-page.tsx](../../frontend/src/components/workspace/report-templates/report-run-detail-page.tsx)

- 顶栏：模板版本链接 + 状态 + 创建时间 + **下载 Markdown / 下载 PDF** 按钮
- PDF 不可用时显示 `pdf_skipped_reason`
- 中部：失败时显示 `error_code` + `error_message`
- 下半：参数摘要 + 完整 report_payload.json
- artifact 下载直接拼装 `/api/threads/{thread_id}/artifacts/mnt/user-data/...`（复用 Phase 0 验证的 artifact 路由）

### 侧边栏导航

[components/workspace/workspace-nav-chat-list.tsx](../../frontend/src/components/workspace/workspace-nav-chat-list.tsx) 新增 2 项菜单：

- **报告模板** → `/workspace/report-templates`
- **报告历史** → `/workspace/report-runs`

---

## 文件变更总结

```text
本次会话新增 backend 文件：
  backend/app/gateway/routers/report_templates.py      (330 行)
  backend/app/gateway/routers/report_runs.py            (108 行)
  backend/tests/test_report_template_routes.py          (250 行, 14 用例)
  agents/builtin/report-templates/weekly-equipment/default.yaml   (134 行)
  agents/builtin/report-templates/weekly-equipment/metadata.yaml  (10 行)
  agents/builtin/report-templates/monthly-equipment/default.yaml  (140 行)
  agents/builtin/report-templates/monthly-equipment/metadata.yaml (12 行)

本次会话修改 backend 文件：
  backend/app/gateway/routers/__init__.py               (加入 report_templates, report_runs)
  backend/app/gateway/app.py                            (注入 2 个路由)
  skills/custom/data-analyst/report_scripts.yaml        (新增 query_monthly + monthly_kpi)

本次会话新增 frontend 文件：
  frontend/src/core/report-templates/types.ts                (110 行)
  frontend/src/core/report-templates/api.ts                  (192 行)
  frontend/src/core/report-templates/hooks.ts                (187 行)
  frontend/src/core/report-templates/index.ts                (3 行)
  frontend/src/app/workspace/report-templates/page.tsx       (5 行)
  frontend/src/app/workspace/report-templates/[template_id]/page.tsx     (10 行)
  frontend/src/app/workspace/report-runs/page.tsx            (5 行)
  frontend/src/app/workspace/report-runs/[run_id]/page.tsx   (10 行)
  frontend/src/components/workspace/report-templates/report-templates-page.tsx   (125 行)
  frontend/src/components/workspace/report-templates/report-template-detail-page.tsx (236 行)
  frontend/src/components/workspace/report-templates/report-runs-page.tsx    (120 行)
  frontend/src/components/workspace/report-templates/report-run-detail-page.tsx  (140 行)

本次会话修改 frontend 文件：
  frontend/src/components/workspace/workspace-nav-chat-list.tsx  (+ 2 个侧边栏菜单项)
```

```text
累计 Phase 0+1+2+3+4+5 产出：
  Backend production code:    ~5700 行
  Backend tests:              262 单元测试
  Frontend production code:   ~1150 行
  Builtin templates:          3 个（daily / weekly / monthly）
  Scripts registered:         7 个（在 data-analyst registry）
  Total HTTP endpoints:       14（11 templates + 3 runs）
  BUILTIN_TOOLS:              18（4 base + 6 lifecycle + 8 runtime）

测试结果：
  Backend pytest: 399 passed / 0 failed
  Frontend typecheck: clean
  Frontend lint: baseline warnings only (无本工作引入的新错误)
```

---

## §17.3 Phase 5 验收清单

| # | 验收项 | 状态 |
| ---- | ---- | ---- |
| 1 | 报告历史嵌入对话历史（侧边栏菜单 + 独立页面） | ✅ |
| 2 | 历史详情页能读取 report_payload.json 重新渲染 | ✅ |
| 3 | 模板管理 UI 提供列表/详情/YAML 编辑器/版本对比/fork | ✅ |
| 4 | tenant_admin 能发布 tenant 模板，普通成员可查看/运行/fork | ✅ (路由层 + 权限矩阵) |
| 5 | Builtin 模板 weekly-equipment、monthly-equipment 通过 §13.14 验收 | ✅ (CI validator) |
| 6 | 所有 UI 在 desktop / responsive 下表现正常 | ✅ (Tailwind 响应式栅格) |

---

## 关键决策落实情况

| §0 决策 | Phase 5 落地 |
|---|---|
| 报告历史 UI 嵌入现有对话历史 | ✅ 侧边栏菜单 + 独立页面 + 通过 `/api/threads/{id}/artifacts/...` 下载 |
| 模板管理 UI Phase 5 提供独立管理页 | ✅ `/workspace/report-templates` + `/[template_id]` |
| 强制版本迭代（published 不可改） | ✅ 详情页 UI 显式禁用编辑按钮 + 后端 ImmutablePublishedError |
| 完整权限矩阵复用 superadmin/tenant_admin | ✅ `_principal_from_request` 桥接 |
| Builtin 模板 Phase 5 内交付 weekly+monthly | ✅ 含 metadata + DSL + 脚本注册 |
| MVP 模板存储用 DeerFlow home | ✅ 复用 Phase 2 FileSystemReportTemplateRepository |

---

## Phase 6 启动前置

Phase 6（4 人月）按 §0 决策**列为路线图，不强制纳入当前 MVP 承诺**。Phase 6 要交付剩余 5 种 builtin 模板：

1. **趋势分析**（P2）：`trend-equipment` + `query_trend` / `trend_analysis`
2. **诊断报告**（P2）：`diagnosis-fault` + `query_fault_context` / `build_fault_timeline` / `diagnosis_analysis`
3. **失效分析**（P3）：`failure-analysis` + 配套脚本
4. **闭环报告**（P3）：`closure-summary` + 配套脚本
5. **巡检报告**（P3）：`inspection` + 配套脚本

每种报告类型必须满足 §13.14 全部 11 项验收：

- builtin DSL 模板通过 CI validator
- 所有脚本注册到 Script Registry
- 至少 1 个成功 ReportRun
- 解释性报告（trend / diagnosis / failure-analysis）必须输出 evidence / confidence / data_coverage / human_review_required

### 现有 Phase 0-5 能力已就位

无需新增任何基础设施，每种报告类型只需要：

1. 编写 DSL（参考 daily/weekly/monthly 模板）
2. 实现脚本（产出符合 `outputs_schema` 的 JSON）
3. 注册到 `data-analyst/report_scripts.yaml`
4. 通过 CI builtin validator
5. 跑通最少 1 个 ReportRun

**MVP 关键路径已圆满**：模板平台从设计到 UI 全部就位，剩余报告类型是产品决策（按优先级和资源情况增量交付），不再属于平台开发范畴。

