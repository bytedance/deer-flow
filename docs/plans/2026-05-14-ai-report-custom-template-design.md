# AI 报告自定义模板功能设计文档（修订版）

> **范围**：分析当前 AI 日报智能体和其它报告功能，重新设计“自定义模板”能力。
> **修订重点**：本版修正了初版设计中运行边界、存储路径、动态 DSL、GenUI 回调安全、多租户权限、ReportRun 与现有 thread/run 关系不清等问题。
> **核心结论**：MVP 不新建独立报告执行引擎，而是在现有 Agent / SOUL / GenUI / ThreadRun / artifact 架构内增加“可校验、可版本化、可运行”的报告模板能力。

---

## 0. 架构决策摘要

| 决策 | 结论 | 原因 |
| ------ | ------ | ------ |
| 自定义模板入口 | 继续使用 [ai-report--custom/SOUL.md](../../agents/builtin/ai-report--custom/SOUL.md) | 符合现有 AI 报告父子智能体入口，不新增割裂入口 |
| 模板创建/编辑 | 由 `ai-report--custom` 通过 GenUI 引导 | 复用现有对话与表单能力 |
| 模板保存/校验 | 必须走后端确定性服务或受控内置工具 | 禁止 LLM 直接用 bash 写模板仓库 |
| 模板运行 MVP | 继续走现有 Agent thread/run | 保留 GenUI streaming、sandbox、artifact、取消、历史能力 |
| ReportRun | 作为报告维度索引，绑定现有 `thread_id` / `run_id` | 不重复实现 RunManager |
| 模板存储 | 不使用 `/mnt/user-data/report-templates` | `/mnt/user-data` 是运行期/sandbox 输出语义，不适合作为长期模板仓库 |
| 报告产物 | 使用 run-scoped output 目录，并通过现有 artifact 路由暴露 | 避免并发覆盖，复用权限模型 |
| DSL v1 | 支持多步动态表单 `form_steps` 和 `options_source` | 才能复刻日报“范围 → 设备 → KPI → 生成”的核心体验 |
| callback_id | 必须包含 thread/template/run/nonce 或底层改为 `(thread_id, callback_id)` | 避免跨线程、跨用户、重复提交冲突 |
| 脚本执行 | 只能通过 allowlist registry，使用参数数组执行 | 防止命令注入和任意代码执行 |

---

## 1. 现有系统分析

### 1.1 AI 报告入口

当前报告能力按“AI 报告父智能体 + 子报告智能体”组织：

- 父入口：[ai-report/SOUL.md](../../agents/builtin/ai-report/SOUL.md)
- 日报：[ai-report--daily/SOUL.md](../../agents/builtin/ai-report--daily/SOUL.md)
- 周报：[ai-report--weekly/SOUL.md](../../agents/builtin/ai-report--weekly/SOUL.md)
- 月度报告：[ai-report--monthly/SOUL.md](../../agents/builtin/ai-report--monthly/SOUL.md)
- 趋势分析报告：[ai-report--trend/SOUL.md](../../agents/builtin/ai-report--trend/SOUL.md)
- 诊断报告：[ai-report--diagnosis/SOUL.md](../../agents/builtin/ai-report--diagnosis/SOUL.md)
- 失效分析报告：[ai-report--failure-analysis/SOUL.md](../../agents/builtin/ai-report--failure-analysis/SOUL.md)
- 闭环报告：[ai-report--closure/SOUL.md](../../agents/builtin/ai-report--closure/SOUL.md)
- 自定义模板：[ai-report--custom/SOUL.md](../../agents/builtin/ai-report--custom/SOUL.md)

前端通用层已经支持 agent 层级关系：

- Agent 类型：[types.ts](../../frontend/src/core/agents/types.ts)
- Agent hook：[hooks.ts](../../frontend/src/core/agents/hooks.ts)
- 子智能体选择器：[agent-child-selector.tsx](../../frontend/src/components/workspace/agent-child-selector.tsx)

后端也已经通过通用 agent 运行链路执行子智能体：

- Agent API：[agents.py](../../backend/app/gateway/routers/agents.py)
- Gateway 服务：[services.py](../../backend/app/gateway/services.py)
- Lead Agent 装配：[agent.py](../../backend/packages/harness/deerflow/agents/lead_agent/agent.py)
- Prompt 注入：[prompt.py](../../backend/packages/harness/deerflow/agents/lead_agent/prompt.py)

因此，自定义模板能力应优先作为 AI 报告体系的增强，而不是新建一个绕开 agent/chat/thread 的独立产品入口。

### 1.2 日报智能体现状

日报是当前最完整的报告流程，已形成多轮 GenUI + 确定性脚本链路：

1. **日报参数表单**：日期、设备类型、对比基准。
2. **设备选择表单**：调用设备目录脚本后动态生成多选设备列表。
3. **KPI 选择表单**：根据设备类型动态生成可选 KPI。
4. **报告生成**：调用数据查询和 KPI 计算脚本。
5. **报告展示**：渲染 `card`、`echart`、`table`、`markdown`。
6. **报告导出**：生成 Markdown/PDF artifact。

日报核心脚本：

| 脚本 | 职责 |
| ------ | ------ |
| [list_equipment.py](../../skills/custom/data-analyst/scripts/list_equipment.py) | 查询设备目录、区域分组、可用 KPI |
| [query_daily.py](../../skills/custom/data-analyst/scripts/query_daily.py) | 生成日报原始数据 |
| [daily_kpi.py](../../skills/custom/data-analyst/scripts/daily_kpi.py) | 生成 KPI、图表、异常表、建议 |
| [export_report.py](../../skills/custom/data-analyst/scripts/export_report.py) | 导出 Markdown/PDF |

日报可以作为自定义模板 MVP 的样板，但不能简单复制为静态模板，因为它的核心价值在于**动态多步参数收集**。

### 1.3 其它报告类型现状

周报、月报、趋势分析、诊断、失效分析、闭环报告目前主要是 prompt-only 模板：

- 有报告定位和章节建议。
- 缺少多轮参数表单。
- 缺少确定性数据查询/转换脚本。
- 缺少可保存、可版本化、可运行的结构化模板模型。

这些报告适合作为后续“预置模板 DSL”的来源，但不应在 MVP 中一次性全部脚本化。

### 1.4 当前自定义模板的问题

[ai-report--custom/SOUL.md](../../agents/builtin/ai-report--custom/SOUL.md) 当前只描述了自由报告助手能力：需求确认、结构协商、数据收集、报告生成、迭代优化。

缺口：

- 没有模板 DSL/schema。
- 没有模板保存、编辑、复制、发布。
- 没有模板版本快照。
- 没有参数表单生成机制。
- 没有脚本 allowlist 和 source 校验。
- 没有报告运行索引。
- 没有权限和租户边界。

---

## 2. 设计目标与非目标

### 2.1 目标

| 目标 | 说明 |
| ------ | ------ |
| 可创建 | 用户通过对话和 GenUI 创建模板草案 |
| 可校验 | 后端校验 DSL、参数、数据步骤、source、权限 |
| 可保存 | 模板保存为结构化 DSL，并形成版本快照 |
| 可运行 | 根据 DSL 动态生成表单，执行 allowlist steps，渲染报告 |
| 可复用 | 用户可从日报或其它预置结构复制模板 |
| 可追溯 | 每次运行记录模板版本、参数、payload、artifact |
| 架构兼容 | MVP 复用现有 agent thread/run、GenUI、artifact、sandbox |

### 2.2 非目标

MVP 不做：

- 完整拖拽式报表设计器。
- 任意 Python/SQL 上传与执行。
- 独立 BI 平台。
- 独立 ReportRun 执行引擎。
- 一次性改造所有报告类型。
- 复杂表达式语言、循环嵌套、跨模板依赖。

---

## 3. 修订后的总体架构

### 3.1 三层架构

```text
┌────────────────────────────────────────────────────────────────────┐
│ ai-report--custom Agent                                             │
│                                                                    │
│ - 通过 SOUL 引导用户创建/编辑/运行模板                              │
│ - 使用 render_ui 输出创建向导和参数表单                              │
│ - 调用受控工具 report_template_*，不直接写模板仓库                   │
│ - 报告生成仍发生在当前 thread/run 上下文中                           │
└──────────────────────────────┬─────────────────────────────────────┘
                               │ built-in tools / backend API
                               ▼
┌────────────────────────────────────────────────────────────────────┐
│ Report Template Service                                             │
│                                                                    │
│ - DSL schema / validator                                            │
│ - template CRUD / version / publish / fork                          │
│ - permission / tenant visibility                                    │
│ - script registry                                                   │
│ - source resolver                                                   │
└──────────────────────────────┬─────────────────────────────────────┘
                               │ run within existing thread/run
                               ▼
┌────────────────────────────────────────────────────────────────────┐
│ Report Template Runtime                                             │
│                                                                    │
│ - generate GenUI form from DSL                                      │
│ - execute allowlisted scripts with sanitized args                   │
│ - write run-scoped outputs                                          │
│ - produce GenUI report payload                                      │
│ - call existing artifact/present_files flow                         │
│ - create ReportRun index bound to thread_id/run_id                  │
└────────────────────────────────────────────────────────────────────┘
```

### 3.2 MVP 运行边界

MVP 中，模板运行必须遵守以下边界：

1. 用户仍然在 `ai-report--custom` 的聊天线程中运行模板。
2. 模板运行对应一个现有 thread/run，不新建独立 job runner。
3. `ReportRun` 只是报告维度的索引，必须保存 `thread_id` 和 `run_id`。
4. GenUI 输出仍通过现有 `render_ui` 机制进入聊天流。
5. 导出 artifact 仍通过现有 artifact 机制下载。
6. 运行文件必须写入当前 run/thread 的输出目录或 run-scoped 子目录。

### 3.3 长期演进边界

当需要脱离聊天线程做定时报告、批量报告、后台异步报告时，再考虑独立 `ReportRun JobRunner`。那时必须补齐：

- 独立状态机。
- 进度事件流。
- 取消与重试。
- artifact 注册。
- 权限校验。
- 输出目录生命周期。
- 调度与并发控制。

MVP 不承担这些复杂度。

---

## 4. 用户流程设计

### 4.1 创建模板

入口：AI 报告 → 自定义模板。

流程：

1. **选择创建方式**
   - 从空白创建。
   - 基于日报复制。
   - 基于周报/月报/趋势/诊断等预置结构复制。
   - 粘贴已有报告样例生成模板草案。

2. **填写基本信息**
   - 名称。
   - 描述。
   - 适用场景。
   - 可见范围：仅自己 / 租户共享。
   - 输出格式：在线报告 / Markdown / PDF。

3. **配置动态参数流程**
   - 静态字段：日期、文本、枚举。
   - 动态字段：设备列表、KPI 列表。
   - 字段依赖：下一步字段可依赖上一步参数或数据步骤输出。

4. **配置数据步骤**
   - 只能从 allowlist 选择脚本或连接器。
   - 参数只能引用已声明的 form 参数或前序 step 输出。
   - 保存前校验所有引用。

5. **配置报告章节**
   - Markdown 摘要。
   - KPI 卡片。
   - ECharts 图表。
   - 表格。
   - 建议与结论。

6. **预览与保存**
   - 后端执行 validate。
   - validate 通过后保存为 draft。
   - 发布时生成不可变版本快照。

### 4.2 运行模板

1. 用户选择模板。
2. `ai-report--custom` 调用 `report_template_prepare_run` 创建 report_run 草稿和 run nonce。
3. Runtime 根据 DSL 的 `form_steps` 渲染第一步 GenUI 表单。
4. 用户提交表单。
5. Runtime 校验 payload，并根据 DSL 决定：
   - 渲染下一步动态表单；或
   - 执行数据步骤并生成报告。
6. 报告结果通过 GenUI blocks 展示。
7. 用户可导出 Markdown/PDF。
8. 系统记录 ReportRun：模板版本、参数、thread/run、payload、artifact。

### 4.3 编辑、复制、发布

- draft：允许原地编辑。
- published：不能原地修改，编辑会创建新 draft 或新 version。
- builtin：普通用户只能 fork，不能修改源模板。
- tenant：只有具备租户模板编辑权限的用户可修改或发布。

---

## 5. DSL v1 设计

### 5.1 DSL 设计原则

- 声明式，不包含任意代码。
- 支持多步动态表单。
- 所有外部执行能力引用 registry 名称。
- 所有 source 使用受限 JSON Pointer / dotted path 子集。
- 保存和运行前必须通过后端 schema 校验。
- DSL 版本必须显式声明。

### 5.2 DSL 示例：基于日报的自定义模板

```yaml
dsl_version: "1"
name: equipment_daily_custom
display_name: "重点机泵日报"
description: "面向重点机泵的运行日报，突出振动、温度和异常事件"
visibility: private

form_steps:
  - id: scope
    title: 生成重点机泵日报
    description: 请选择日报日期、设备类型和对比基准。
    fields:
      - name: report_date
        label: 日报日期
        type: date
        required: true
      - name: equipment_type
        label: 设备类型
        type: select
        required: true
        default: pump
        options:
          - label: 全部
            value: all
          - label: 静设备
            value: static_equipment
          - label: 旋转机组
            value: rotating_machinery
          - label: 机泵
            value: pump
          - label: 往复机组
            value: reciprocating_machinery
      - name: compare_with
        label: 对比基准
        type: select
        required: true
        default: previous_day
        options:
          - label: 前一日
            value: previous_day
          - label: 上周同日
            value: previous_week
          - label: 不对比
            value: none
    next: equipment

  - id: equipment
    title: 选择设备
    description: 请选择本次报告覆盖的设备。
    before_step:
      id: equipment_catalog
      kind: script
      name: list_equipment
      args:
        type: "{{ form.scope.equipment_type }}"
        scope: all
        limit: 10000
    fields:
      - name: equipment_ids
        label: 设备列表
        type: multi-select
        required: true
        searchable: true
        options_source:
          step: equipment_catalog
          path: equipment
          label: id
          value: id
          group: area
          description: name
    next: kpis

  - id: kpis
    title: 选择 KPI
    description: 请选择报告中关注的指标。
    fields:
      - name: kpi_keys
        label: KPI 指标
        type: multi-select
        required: true
        options_source:
          step: equipment_catalog
          path: available_kpis
          label: label
          value: key
          description: description
    next: generate

data_steps:
  - id: daily_data
    kind: script
    name: query_daily
    args:
      date: "{{ form.scope.report_date }}"
      equipment_type: "{{ form.scope.equipment_type }}"
      equipment_ids: "{{ form.equipment.equipment_ids }}"
      kpis: "{{ form.kpis.kpi_keys }}"
      compare: "{{ form.scope.compare_with }}"
    outputs:
      daily_data: daily_data.json

transforms:
  - id: daily_kpi
    kind: script
    name: daily_kpi
    input: daily_data.daily_data
    outputs:
      daily_kpi: daily_kpi.json

sections:
  - id: overview
    title: 总览
    component: markdown
    source: daily_kpi.daily_kpi.overall_status.summary
  - id: kpi_cards
    title: 核心 KPI
    component: card_group
    source: daily_kpi.daily_kpi.kpi_summary
  - id: trend
    title: 趋势图
    component: echart
    source: daily_kpi.daily_kpi.trend_chart
  - id: anomalies
    title: 异常排行
    component: table
    source: daily_kpi.daily_kpi.top_anomalies
  - id: alarms
    title: 告警事件
    component: table
    source: daily_kpi.daily_kpi.alarm_table
  - id: recommendations
    title: 建议
    component: markdown
    source: daily_kpi.daily_kpi.recommendations

export:
  formats: [md, pdf]
  renderer: generic_report
```

### 5.3 form_steps

`form_steps` 用于描述多步参数收集。

字段：

| 字段 | 必填 | 说明 |
| ------ | ------ | ------ |
| `id` | 是 | step 唯一 ID |
| `title` | 是 | 表单标题 |
| `description` | 否 | 表单说明 |
| `before_step` | 否 | 渲染该表单前需要执行的数据步骤 |
| `fields` | 是 | 表单字段 |
| `next` | 是 | 下一步 ID 或 `generate` |

字段类型对齐现有 [FormBlock.tsx](../../frontend/src/components/genui/FormBlock.tsx)：

- `text`
- `textarea`
- `number`
- `date`
- `select`
- `checkbox`
- `multi-select`

字段校验要求：

- 每个字段必须声明 `name`、`label`、`type`。
- `select`、`multi-select` 必须声明静态 `options` 或完整 `options_source`。
- `checkbox` 只表示单个布尔值，不承载选项列表；需要多选时统一使用 `multi-select`。
- `validation` 为可选对象，MVP 仅支持 `pattern`、`min`、`max`、`min_items`、`max_items`，并且只用于前端提示和后端二次校验。
- 字段值最终还必须通过对应 registry args schema 校验，不能只依赖表单校验。

### 5.4 options_source

动态选项通过 `options_source` 描述。

```yaml
options_source:
  step: equipment_catalog
  path: equipment
  label: id
  value: id
  group: area
  description: name
```

校验要求：

- `step` 必须引用当前 step 之前已执行的 step。
- `path` 必须能解析为数组。
- `label`、`value` 必须存在。
- `group`、`description` 可选。
- 输出选项数量需要有上限，避免超大表单。

### 5.5 source resolver

`sections[].source` 使用受限 dotted path：

```text
<step_id>.<output_id>.<json_path>
```

禁止：

- 任意表达式。
- 函数调用。
- 文件路径。
- URL。
- JavaScript 代码。

运行前校验：

- source 引用的 step/output 存在。
- path 可解析。
- 输出类型与组件匹配。

组件类型要求：

| component | source 类型 |
| --------- | ----------- |
| `markdown` | string 或 string[] |
| `card` | object，包含 title/value 或可映射字段 |
| `card_group` | object[] |
| `echart` | 纯 JSON ECharts option |
| `table` | object[] 或 `{columns, data}` |

---

## 6. 数据模型

### 6.1 ReportTemplate

```text
ReportTemplate
- id
- name
- display_name
- description
- owner_user_id
- tenant_id
- visibility: private | tenant | builtin
- status: draft | published | archived
- current_version
- dsl_version
- created_at
- updated_at
```

约束：

- `owner_user_id`、`tenant_id` 来自认证上下文，不接受请求 body 或 DSL 覆盖。
- `visibility=builtin` 只能由平台管理员创建或修改。
- `status=published` 的模板不能直接覆盖，只能生成新版本。

### 6.2 ReportTemplateVersion

```text
ReportTemplateVersion
- id
- template_id
- version
- dsl
- checksum
- created_by
- created_at
- changelog
```

约束：

- 版本快照不可变。
- ReportRun 必须绑定具体 `template_id + version`。
- fork 时必须记录源模板 ID 和源版本。

### 6.3 ReportRun

```text
ReportRun
- id
- template_id
- template_version
- thread_id
- run_id
- user_id
- tenant_id
- idempotency_key
- status: pending | running | succeeded | failed | canceled
- parameters
- report_payload_path
- artifact_paths
- data_snapshot_paths
- error_code
- error_message
- created_at
- started_at
- completed_at
```

MVP 中 `ReportRun` 不是独立执行引擎，只是绑定现有 thread/run 的报告索引。

---

## 7. 存储设计

### 7.1 模板存储

禁止将模板长期存储在 `/mnt/user-data/report-templates`。

推荐优先级：

1. **数据库优先**：PostgreSQL 保存模板 metadata、version、run index，DSL 用 JSONB 或对象路径。
2. **MVP 文件存储**：使用 DeerFlow home 下的用户/租户隔离目录。

文件存储示例：

```text
{DEER_FLOW_HOME}/report-templates/
  users/{user_id}/{template_id}/
    template.json
    versions/{version}.json
  tenants/{tenant_id}/{template_id}/
    template.json
    versions/{version}.json
  builtin/{template_id}/
    template.json
    versions/{version}.json
```

文件存储必须支持：

- 原子写入。
- 文件锁或乐观版本控制。
- ID 安全字符校验。
- 索引文件或可分页查询索引。
- 版本冲突检测。

### 7.2 报告运行输出

报告运行输出必须 run-scoped：

```text
{thread_output_dir}/report-runs/{report_run_id}/
  parameters.json
  template_version.json
  data/
    daily_data.json
    daily_kpi.json
  report_payload.json
  exports/
    report.md
    report.pdf
  status.json
```

要求：

- 不同 ReportRun 不能共享固定 `daily_data.json`。
- 所有脚本输出目录由 runtime 注入。
- artifact 只暴露相对安全路径。
- 产物下载继续走现有 artifact 权限模型。

---

## 8. 后端模块设计

### 8.1 分层原则

```text
backend/app/gateway/
  routers/report_templates.py
  routers/report_runs.py

backend/packages/harness/deerflow/report_templates/
  schema.py
  validator.py
  repository.py
  script_registry.py
  source_resolver.py
  runtime.py
  renderer.py
```

边界：

- `app/gateway`：HTTP、认证上下文、租户上下文、权限、response model。
- `harness/deerflow/report_templates`：纯领域逻辑，不 import `app.*`。
- repository 可抽象文件或 DB，但权限判断仍在 gateway/app 层完成。

### 8.2 受控内置工具

为了让 `ai-report--custom` 在对话中创建和运行模板，建议新增受控内置工具，而不是让 LLM 直接用 bash 写文件。

工具建议：

| 工具 | 职责 |
| ------ | ------ |
| `report_template_list` | 列出用户可见模板 |
| `report_template_get` | 获取模板详情和版本 |
| `report_template_validate` | 校验 DSL 并返回结构化错误 |
| `report_template_save_draft` | 保存草稿 |
| `report_template_publish` | 发布新版本 |
| `report_template_fork` | 从可见模板复制 |
| `report_template_prepare_run` | 创建 ReportRun 草稿和 nonce |
| `report_template_render_step` | 根据 DSL 渲染当前 form step |
| `report_template_submit_step` | 校验 payload，推进下一步或触发生成 |
| `report_template_export` | 导出报告 artifact |

这些工具内部调用 Report Template Service，并使用认证上下文中的 user/tenant 信息。

### 8.3 REST API

REST API 面向前端模板管理页和后续非对话入口。

```text
GET    /api/report-templates
POST   /api/report-templates
GET    /api/report-templates/{template_id}
PUT    /api/report-templates/{template_id}
POST   /api/report-templates/{template_id}/validate
POST   /api/report-templates/{template_id}/publish
POST   /api/report-templates/{template_id}/fork
GET    /api/report-templates/{template_id}/versions
GET    /api/report-runs
GET    /api/report-runs/{report_run_id}
POST   /api/report-runs/{report_run_id}/cancel   # 独立 runner 前可暂不实现
```

API 要求：

- list 支持分页、排序、过滤：`visibility`、`status`、`owner`、`keyword`。
- validate 返回结构化错误数组。
- publish 支持 `expected_current_version`，避免并发覆盖。
- fork 固定源模板版本。
- run 查询必须校验 owner/tenant 可见性。

MVP 不建议通过 `POST /api/report-templates/{id}/runs` 直接执行报告。运行应先保留在 agent thread 中，避免绕开现有运行体系。

---

## 9. Script Registry 与执行安全

### 9.1 Registry 示例

```json
{
  "list_equipment": {
    "path": "/mnt/skills/custom/data-analyst/scripts/list_equipment.py",
    "kind": ["form_options"],
    "args_schema": {
      "type": {"type": "enum", "values": ["all", "static_equipment", "rotating_machinery", "pump", "reciprocating_machinery"], "required": true},
      "scope": {"type": "enum", "values": ["all", "selected"], "default": "all"},
      "limit": {"type": "integer", "min": 1, "max": 10000, "default": 10000}
    },
    "outputs_schema": {
      "equipment": "array",
      "available_kpis": "array"
    }
  },
  "query_daily": {
    "path": "/mnt/skills/custom/data-analyst/scripts/query_daily.py",
    "kind": ["data_step"],
    "args_schema": {
      "date": {"type": "date", "required": true},
      "equipment_type": {"type": "enum", "values": ["all", "static_equipment", "rotating_machinery", "pump", "reciprocating_machinery"]},
      "equipment_ids": {"type": "array", "items": "string"},
      "kpis": {"type": "array", "items": "string"},
      "compare": {"type": "enum", "values": ["previous_day", "previous_week", "none"]}
    },
    "outputs": {
      "daily_data": "{run_output_dir}/data/daily_data.json"
    }
  }
}
```

### 9.2 执行要求

- 使用参数数组调用脚本，不拼接 shell 字符串。
- 所有 args 先经 DSL schema 和 registry schema 双重校验。
- 输出目录由 runtime 创建并注入。
- 脚本不能接受模板传入的任意输出路径。
- 每个输出写 checksum、schema_version、created_at。
- 单个步骤设置超时、输出大小上限和错误码。

---

## 10. GenUI 与 callback 安全

### 10.1 GenUI 输出方式

MVP 中 Runtime 不直接发明新的前端渲染协议，应继续使用现有 `render_ui` 机制。DSL 里的 `sections` 会被转换为现有 GenUI blocks：

- `markdown` → `markdown`
- `card` → `card`
- `card_group` → 多个 `card`
- `echart` → `echart`
- `table` → `table`

历史详情页如果未来要脱离聊天渲染，可以读取 `report_payload.json` 并复用 GenUI renderer，但这是后续增强。

### 10.2 callback_id 策略

禁止固定使用：

```text
custom-report-run-params
```

推荐格式：

```text
custom-report:{thread_id}:{template_id}:{report_run_id}:{step_id}:{nonce}
```

同时建议底层逐步改造为：

```text
InteractionStore key = (thread_id, callback_id)
```

提交时必须校验：

- callback 存在。
- thread_id 匹配。
- 当前用户有权访问该 thread。
- callback 未超时。
- nonce 匹配当前 ReportRun。
- step_id 是当前 expected step，防止乱序提交。

---

## 11. 权限与多租户

### 11.1 权限矩阵

| 操作 | private | tenant | builtin |
| ------ | ------- | ------ | ------- |
| 查看 | owner | tenant member | all users |
| 运行 | owner | tenant member | all users |
| 编辑草稿 | owner | tenant editor/admin | platform admin |
| 发布 | owner | tenant editor/admin | platform admin |
| 归档 | owner | tenant admin | platform admin |
| fork | readable user | readable user | readable user |
| 删除 | owner | tenant admin | platform admin |

### 11.2 权限原则

- `user_id` 和 `tenant_id` 只来自认证上下文。
- 请求 body 和 DSL 中的 owner/tenant 字段只作为展示草案，不作为授权依据。
- `builtin` 模板只能平台管理员修改。
- `tenant` 模板发布需要租户模板编辑权限。
- ReportRun 查询必须同时校验模板可见性和运行记录 owner/tenant。
- artifact 下载必须绑定 ReportRun/thread 权限。

### 11.3 数据安全

报告运行产物可能包含生产设备数据，必须支持：

- 保留期策略。
- 手动删除或归档。
- 下载审计。
- 错误信息脱敏。
- Markdown/PDF XSS 防护。
- ECharts option 只允许纯 JSON，不允许函数、HTML formatter、外链脚本。

---

## 12. 导出与历史

### 12.1 report_payload.json

运行结束后生成标准 payload：

```json
{
  "schema_version": "1",
  "title": "重点机泵日报",
  "template": {
    "id": "tpl_xxx",
    "version": 3,
    "name": "equipment_daily_custom"
  },
  "run": {
    "id": "rr_xxx",
    "thread_id": "...",
    "run_id": "...",
    "generated_at": "2026-05-14T10:00:00+08:00"
  },
  "parameters": {},
  "sections": [
    {"id": "overview", "component": "markdown", "title": "总览", "props": {"content": "..."}},
    {"id": "trend", "component": "echart", "title": "趋势图", "props": {"option": {}}},
    {"id": "alarms", "component": "table", "title": "告警事件", "props": {"columns": [], "data": []}}
  ]
}
```

### 12.2 导出策略

现有 [export_report.py](../../skills/custom/data-analyst/scripts/export_report.py) 可以逐步演进为：

```text
export_report.py
  ├ daily adapter：兼容当前日报输入
  └ generic renderer：根据 report_payload.json 渲染 Markdown/PDF
```

导出要求：

- 输入为 `report_payload.json`。
- 输出到 `{run_output_dir}/exports/`。
- PDF 图表需要提前验证：仅保存 ECharts option 不一定能保证 PDF 渲染有图。
- Markdown 渲染需要做 HTML/XSS 清理。

### 12.3 历史查询

历史以 `ReportRun` 为索引，不依赖聊天消息反向解析。

列表字段：

- 报告标题。
- 模板名称与版本。
- 运行人。
- 运行时间。
- 参数摘要。
- 状态。
- artifact 链接。

详情字段：

- 模板版本快照。
- 参数。
- report_payload。
- data snapshot 路径和 checksum。
- Markdown/PDF artifact。
- 错误信息。

---

## 13. 多报告类型扩展设计

### 13.1 扩展原则

自定义模板平台不能只服务日报。日报只是第一个完整样板，后续所有报告类型都应通过同一套能力扩展：

1. **统一入口**：仍由 AI 报告父智能体展示报告类型，自定义模板入口负责创建、复制和运行用户模板。
2. **统一 DSL**：所有报告都使用 `form_steps`、`data_steps`、`transforms`、`sections`、`export` 描述。
3. **统一 registry**：所有报告专用脚本都必须注册到 Script Registry，禁止模板直接执行任意脚本。
4. **统一运行时**：迁移到模板运行时的日报、周报、月报、趋势、诊断、失效分析、闭环报告都由同一个 Template Runtime 执行。
5. **统一历史**：迁移到模板运行时的报告运行都生成 `ReportRun`，绑定模板版本、thread/run、参数、payload 和 artifact。
6. **差异下沉到模板和脚本**：不同报告的差异主要体现在参数、数据步骤、转换步骤、章节结构和导出样式，不应扩散到前端组件或 Gateway 路由。

### 13.2 报告类型扩展矩阵

| 报告类型 | 典型参数 | 数据步骤 | 转换步骤 | 典型章节 | MVP 优先级 |
| ------ | ------ | ------ | ------ | ------ | ------ |
| 日报 | 日期、设备类型、设备列表、KPI、对比基准 | `list_equipment`、`query_daily` | `daily_kpi` | 运行概览、KPI 卡片、24h 趋势、异常事件、建议 | P0 |
| 周报 | 周期、设备范围、KPI、周对比基准 | `query_weekly` | `weekly_kpi` | 周概览、每日趋势、异常统计、周环比、下周重点 | P1 |
| 月报 | 月份、设备范围、KPI、环比/同比基准 | `query_monthly` | `monthly_kpi` | 月度 KPI、MTBF/MTTR、环比同比、重大事件、改进跟踪 | P1 |
| 趋势分析 | 指标、设备范围、时间窗口、预测周期 | `query_trend` | `trend_analysis` | 趋势概览、趋势分解、异常模式、预测预警、建议 | P2 |
| 诊断报告 | 故障对象、故障时间、现象、关联设备 | `query_fault_context` | `diagnosis_analysis` | 故障概述、时间线、影响评估、根因判断、处理建议 | P2 |
| 失效分析 | 失效对象、失效模式、分析方法、证据范围 | `query_failure_data` | `failure_analysis` | 背景、方法、证据、根因、改进措施、验证计划 | P3 |
| 闭环报告 | 问题单、责任部门、措施、验证周期 | `query_closure_items` | `closure_summary` | 问题回顾、措施执行、验证结果、未闭项、闭环结论 | P3 |
| 巡检报告 | 巡检日期、路线、区域、异常等级 | `query_inspection` | `inspection_summary` | 巡检概况、异常清单、照片/附件摘要、整改建议 | P3 |
| 通用分析报告 | 数据源、分析主题、指标、分组维度 | `query_dataset` | `generic_analysis` | 分析背景、核心发现、图表、结论、建议 | V2 |

趋势、诊断、失效分析等解释性报告的 transform 输出必须包含证据、来源追溯与置信度字段，不能只输出自然语言结论。最低输出要求：

- `findings[]`：发现项。
- `evidence[]`：每条发现对应的数据点、告警、工单、时间窗口或附件摘要引用。
- `evidence[].source_type`：来源类型，例如 `timeseries`、`alarm`、`work_order`、`inspection_record`、`attachment_summary`。
- `evidence[].source_id`：来源对象 ID。
- `evidence[].snapshot_path`：运行时保存的数据快照路径。
- `evidence[].checksum`：快照或证据片段 checksum。
- `evidence[].time_range`：证据覆盖时间范围。
- `evidence[].retrieved_at`：证据获取时间。
- `confidence`：`low` / `medium` / `high`。
- `assumptions[]`：分析假设。
- `data_coverage`：输入数据覆盖范围和缺口。
- `human_review_required`：诊断、失效分析、根因类结论默认必须为 `true`，由用户或专家确认后才能作为正式结论。

> 本节所有 YAML 都是结构片段，用于说明不同报告类型如何接入 DSL；它们不是可直接保存运行的完整模板。正式 builtin 模板必须补齐每个 `form_step` 的 `title`、`next`、完整 `before_step`、完整 `options_source`、所有 `select` 选项，并通过 validator。

### 13.3 周报扩展设计

周报应复用日报的设备和 KPI 选择能力，但时间范围从单日扩展为自然周或自定义 7 天窗口。

#### 周报参数流程

```yaml
form_steps:
  - id: scope
    fields:
      - name: week_start
        type: date
        label: 周开始日期
        required: true
      - name: equipment_type
        type: select
      - name: compare_with
        type: select
        options:
          - label: 上一周
            value: previous_week
          - label: 去年同期
            value: previous_year
          - label: 不对比
            value: none
  - id: equipment
    before_step:
      name: list_equipment
    fields:
      - name: equipment_ids
        type: multi-select
        options_source:
          step: equipment_catalog
          path: equipment
  - id: kpis
    fields:
      - name: kpi_keys
        type: multi-select
        options_source:
          step: equipment_catalog
          path: available_kpis
```

#### 周报脚本扩展

| 脚本 | 职责 |
| ------ | ------ |
| `query_weekly` | 聚合 7 天设备运行、告警、停机、能耗等数据 |
| `weekly_kpi` | 计算周均值、峰值、日趋势、异常统计、周环比 |
| `export_weekly_report` 或 `generic_report` | 基于 `report_payload.json` 导出周报 |

#### 周报章节建议

1. 本周运行概览。
2. 核心 KPI 周统计。
3. 每日趋势图。
4. 异常/告警 TopN。
5. 与上一周对比。
6. 下周关注重点。

### 13.4 月报扩展设计

月报在周报基础上增加长期指标和管理视角，重点是 MTBF、MTTR、环比、同比、改进跟踪。

#### 月报参数流程

```yaml
form_steps:
  - id: scope
    fields:
      - name: report_month
        type: text
        label: 报告月份
        validation:
          pattern: "^\\d{4}-\\d{2}$"
      - name: equipment_type
        type: select
      - name: compare_with
        type: multi-select
        options:
          - label: 环比
            value: mom
          - label: 同比
            value: yoy
```

#### 月报脚本扩展

| 脚本 | 职责 |
| ------ | ------ |
| `query_monthly` | 查询月度运行、维修、告警、缺陷、能耗数据 |
| `monthly_kpi` | 计算月度 KPI、MTBF、MTTR、环比、同比、达标率 |
| `improvement_tracking` | 汇总本月改进措施、完成率和遗留项 |

#### 月报章节建议

1. 月度总览。
2. KPI 达成情况。
3. MTBF / MTTR 分析。
4. 重大异常与事件。
5. 环比/同比分析。
6. 改进措施跟踪。
7. 下月计划。

### 13.5 趋势分析报告扩展设计

趋势报告不是按固定日报/周报/月报周期输出，而是围绕一个或多个指标做长期趋势、异常模式和预测预警。

#### 趋势分析参数流程

```yaml
form_steps:
  - id: trend_scope
    fields:
      - name: metric_keys
        type: multi-select
        label: 分析指标
      - name: date_range
        type: text
        label: 时间范围
      - name: aggregation
        type: select
        options:
          - label: 小时
            value: hourly
          - label: 日
            value: daily
          - label: 周
            value: weekly
      - name: forecast_horizon
        type: number
        label: 预测周期
```

#### 趋势分析脚本扩展

| 脚本 | 职责 |
| ------ | ------ |
| `query_trend` | 查询指定指标的时间序列 |
| `trend_analysis` | 趋势分解、异常检测、斜率/波动率计算、预测 |
| `trend_alert_rules` | 根据阈值和趋势生成预警说明 |

#### 趋势分析章节建议

1. 趋势概览。
2. 指标走势与分解。
3. 异常模式识别。
4. 劣化趋势预警。
5. 未来趋势预测。
6. 处置建议。

### 13.6 诊断报告扩展设计

诊断报告以故障或异常事件为中心，要求围绕事件上下文、时间线、影响范围、候选根因和处置建议生成结构化结论。

#### 诊断报告参数流程

```yaml
form_steps:
  - id: fault_scope
    fields:
      - name: fault_time
        type: date
        label: 故障日期
      - name: equipment_id
        type: text
        label: 故障设备
      - name: symptom
        type: textarea
        label: 故障现象
      - name: include_related_equipment
        type: checkbox
        label: 是否分析关联设备
```

#### 诊断报告脚本扩展

| 脚本 | 职责 |
| ------ | ------ |
| `query_fault_context` | 查询故障前后运行数据、告警、工单、维护记录 |
| `build_fault_timeline` | 生成事件时间线 |
| `diagnosis_analysis` | 生成候选原因、证据链、影响评估和建议 |

#### 诊断报告章节建议

1. 故障概述。
2. 影响范围。
3. 事件时间线。
4. 数据与告警证据。
5. 候选根因分析。
6. 诊断结论。
7. 处置建议。

### 13.7 失效分析报告扩展设计

失效分析比诊断报告更偏工程分析和复盘，需要支持分析方法、证据材料、根因分类、改进措施和验证计划。

#### 失效分析参数流程

```yaml
form_steps:
  - id: failure_scope
    fields:
      - name: asset_id
        type: text
        label: 失效对象
      - name: failure_mode
        type: select
        label: 失效模式
      - name: analysis_method
        type: select
        options:
          - label: 5Why
            value: five_why
          - label: 鱼骨图
            value: fishbone
          - label: FMEA
            value: fmea
      - name: evidence_range
        type: textarea
        label: 证据范围
```

#### 失效分析脚本扩展

| 脚本 | 职责 |
| ------ | ------ |
| `query_failure_data` | 查询失效对象相关运行、维修、检验、备件和环境数据 |
| `failure_analysis` | 基于指定方法生成根因分析结构 |
| `corrective_action_plan` | 生成纠正预防措施和验证计划 |

#### 失效分析章节建议

1. 失效背景。
2. 失效现象与影响。
3. 分析方法。
4. 证据材料。
5. 根因分析。
6. 纠正与预防措施。
7. 验证计划。

### 13.8 闭环报告扩展设计

闭环报告关注问题整改全过程，核心是“问题 → 措施 → 执行 → 验证 → 结论”。

#### 闭环报告参数流程

```yaml
form_steps:
  - id: closure_scope
    fields:
      - name: issue_ids
        type: multi-select
        label: 问题单
        options_source:
          step: issue_catalog
          path: issues
      - name: owner_department
        type: select
        label: 责任部门
      - name: verification_period
        type: text
        label: 验证周期
```

#### 闭环报告脚本扩展

| 脚本 | 职责 |
| ------ | ------ |
| `query_closure_items` | 查询问题单、整改措施、责任人、计划和完成状态 |
| `closure_summary` | 汇总执行情况、验证结果、未闭项和闭环结论 |
| `closure_risk_check` | 判断是否存在重复问题或未消除风险 |

#### 闭环报告章节建议

1. 问题回顾。
2. 原因分析摘要。
3. 整改措施。
4. 执行情况。
5. 验证结果。
6. 未闭项与风险。
7. 闭环结论。

### 13.9 巡检报告扩展设计

巡检报告适合从巡检记录、异常项、照片/附件、整改建议中生成结构化报告。它与日报不同，不一定以 KPI 为中心，而以巡检路线和异常项为中心。

MVP 只支持附件和照片的文本摘要、数量统计、受控 artifact 链接，不新增图片组件，也不允许外链图片直接进入报告正文。若后续需要展示图片，必须先定义 artifact-bound image component、权限校验和导出行为。

#### 巡检报告脚本扩展

| 脚本 | 职责 |
| ------ | ------ |
| `query_inspection` | 查询指定日期、路线、区域的巡检记录 |
| `inspection_summary` | 汇总异常等级、设备分布、整改建议 |
| `inspection_attachment_summary` | 汇总照片、附件和备注信息 |

#### 巡检报告章节建议

1. 巡检概况。
2. 路线和区域覆盖。
3. 异常项清单。
4. 重点问题说明。
5. 附件/照片摘要。
6. 整改建议。

### 13.10 通用分析报告扩展设计

通用分析报告服务于“非固定设备报告”的场景，例如用户选择一个数据集、分析主题和指标后生成探索式分析报告。

该能力不进入 v1 模板平台范围，应后置到 v2。原因是它需要额外的数据源安全模型，而不仅是注册几个脚本。

#### 通用分析报告前置条件

- 建立 connector / dataset registry，明确每个数据源的 owner、tenant、权限、schema 和可查询范围。
- `query_dataset` 必须执行行数、列数、时间窗口、输出大小和超时限制。
- 禁止模板携带任意 SQL 或任意 URL；只能选择已注册数据集和受控查询参数。
- 需要 schema discovery 机制，让用户选择字段时不会暴露无权访问的数据列。
- `generic_analysis` 只能输出可验证的统计结果、图表配置和带证据引用的发现，不允许编造结论。
- source resolver 必须支持通用表格、聚合统计和图表 option，并校验输出大小。

#### 通用分析报告章节建议

1. 分析背景。
2. 数据范围与口径。
3. 核心指标。
4. 主要发现。
5. 图表分析。
6. 结论与建议。

### 13.11 预置模板包设计

为了让其它报告类型能被用户复制和二次编辑，建议引入“预置模板包”：

```text
agents/builtin/report-templates/
  daily-equipment/default.yaml
  weekly-equipment/default.yaml
  monthly-equipment/default.yaml
  trend-equipment/default.yaml
  diagnosis-fault/default.yaml
  failure-analysis/default.yaml
  closure-summary/default.yaml
  inspection/default.yaml
```

预置模板包要求：

- 只包含 DSL，不包含可执行代码。
- 引用的脚本必须存在于 registry。
- 每个模板必须有示例参数和示例 `report_payload`。
- 每个模板必须通过 validator 测试。
- 普通用户不能修改 builtin 模板，只能 fork。

### 13.12 脚本扩展规范

新增报告脚本必须遵守统一契约：

1. 输入通过命令行参数或 JSON input 文件传入，不读取未声明路径。
2. 输出写入 runtime 指定的 run-scoped 目录。
3. 输出 JSON 必须包含 `schema_version`。
4. 错误输出必须是结构化 JSON，包含 `code`、`message`、`details`。
5. 不直接生成 GenUI block，只生成数据或图表 option，由 runtime/renderer 转换。
6. 不做权限判断，权限由 Gateway/Runtime 在调用前完成。
7. 不访问任意外部网络，除非对应连接器已在 registry 注册并授权。

### 13.13 扩展顺序

建议扩展顺序：

1. **日报模板化样板（P0）**：验证动态表单、run-scoped 输出、report_payload、导出。
2. **周报/月报（P1）**：复用设备/KPI 体系，主要扩展时间窗口和聚合逻辑。
3. **趋势分析（P2）**：验证长期时间序列、预测、异常模式章节。
4. **诊断报告（P2）**：验证事件时间线、证据链和半结构化输入。
5. **失效分析/闭环/巡检（P3）**：验证工程复盘、整改跟踪、附件摘要等管理类报告。
6. **通用分析报告（V2）**：最后扩展到更开放的数据集分析；进入该阶段前必须先完成 connector / dataset registry、数据源权限、查询限制和 schema discovery。

### 13.14 扩展验收标准

每新增一种报告类型，必须满足：

1. 有一份 builtin DSL 预置模板。
2. 模板能通过 validator。
3. 所有脚本已在 Script Registry 注册。
4. 至少有一个成功 ReportRun 样例。
5. 能生成 `report_payload.json`。
6. 能渲染 GenUI 报告。
7. 能导出 Markdown。
8. 非法参数、越权数据源、缺失 source 会返回结构化错误。
9. 历史详情能展示该报告的参数、模板版本、payload 和 artifact。
10. 用户能 fork 该预置模板并修改非危险字段。
11. 诊断、趋势预测、失效分析等解释性报告必须输出证据、置信度、数据覆盖范围和 `human_review_required` 标记。

---

## 14. API 与错误结构

### 14.1 validate 错误结构

```json
{
  "valid": false,
  "errors": [
    {
      "code": "UNKNOWN_SCRIPT",
      "path": "data_steps[0].name",
      "message": "脚本 query_xxx 未在 registry 中注册",
      "severity": "error"
    },
    {
      "code": "SOURCE_TYPE_MISMATCH",
      "path": "sections[2].source",
      "message": "echart 组件要求 source 返回 ECharts option object",
      "severity": "error"
    }
  ],
  "warnings": []
}
```

### 14.2 幂等与并发

- 创建 ReportRun 需要 `idempotency_key`，避免用户重复点击生成重复报告。
- publish 需要 `expected_current_version`。
- 文件存储需要乐观锁或原子 rename。
- 同一 ReportRun 只能有一个 active step。
- 乱序提交旧 callback 应返回明确错误。

---

## 15. 实施计划

### Phase 0：技术尖刺与边界确认

1. 验证模板运行继续走现有 agent thread 的方案。
2. 验证通过受控工具返回/推进 GenUI form step。
3. 验证 run-scoped 输出目录与 artifact 下载链路。
4. 验证 PDF 中图表导出方案。
5. 确认 agent config 是否完整纳入当前分支；若缺失，需要先补齐 AI 报告父子 agent 配置。

### Phase 1：DSL schema、registry、validator

1. 新增 DSL Pydantic schema。
2. 新增 script registry。
3. 新增 source resolver。
4. 支持 `form_steps`、`options_source`、`sections` 校验。
5. 单元测试覆盖非法脚本、非法参数、非法 source、组件类型不匹配、动态选项缺字段。

### Phase 2：模板存储与权限

1. 新增 repository 抽象。
2. MVP 采用 DeerFlow home 文件存储或直接接入 PostgreSQL。
3. 新增模板 metadata/version 模型。
4. 新增权限矩阵校验。
5. 支持 draft、publish、fork、archive。

### Phase 3：受控工具与自定义模板 SOUL

1. 新增 `report_template_*` 内置工具。
2. 改造 [ai-report--custom/SOUL.md](../../agents/builtin/ai-report--custom/SOUL.md)。
3. 禁止 SOUL 指示模型用 bash 直接保存模板。
4. 创建模板向导通过 GenUI 表单完成。

### Phase 4：模板运行 MVP

1. 根据 DSL 渲染动态 form step。
2. 支持 `list_equipment → equipment_ids → kpi_keys → query_daily → daily_kpi` 的日报样板模板。
3. 所有输出写入 report_run 专属目录。
4. 生成 `report_payload.json`。
5. 渲染 GenUI 报告。
6. 支持 Markdown 导出。

### Phase 5：历史与管理 UI

1. 新增报告历史列表。
2. 新增模板列表/编辑 UI。
3. 支持历史详情读取 `report_payload.json`。
4. 支持 artifact 重下载。
5. 支持租户共享模板管理。

### Phase 6：扩展报告类型

1. 落地周报和月报预置模板，复用设备/KPI 选择、时间窗口聚合和通用导出。
2. 落地趋势分析预置模板，验证长期时间序列、异常模式、预测预警章节和 provenance 输出。
3. 落地诊断报告预置模板，验证故障上下文、事件时间线、证据链和专家复核标记。
4. 落地失效分析、闭环、巡检预置模板，验证工程复盘、整改跟踪、附件摘要和管理类报告。
5. 每种报告类型必须满足第 13.14 节扩展验收标准，未满足前不得发布，也不得进入下一类报告的发布阶段。
6. 通用分析报告不作为 Phase 6 常规交付项；必须先完成 connector / dataset registry、数据源权限、查询限制、schema discovery、provenance 输出和安全测试后，才能作为 V2 单独立项启动。
7. 后续再考虑定时报告和独立后台 runner。

---

## 16. 风险与应对

| 风险 | 影响 | 应对 |
| ------ | ------ | ------ |
| 绕开现有 thread/run | 失去 GenUI、artifact、取消、权限能力 | MVP 运行绑定现有 thread/run |
| 模板存储放错位置 | 模板跨会话不可控，权限混乱 | 使用 DB 或 DeerFlow home 用户/租户目录 |
| DSL 无法描述动态日报流程 | MVP 无法复刻现有日报体验 | DSL v1 支持 `form_steps` 和 `options_source` |
| 固定 callback_id 冲突 | 跨用户/线程误提交 | callback_id 加 thread/template/run/nonce，底层按 thread 校验 |
| 脚本任意执行 | 命令注入、数据泄漏 | registry allowlist + 参数数组执行 + schema 校验 |
| 固定输出文件覆盖 | 并发运行互相污染 | run-scoped 输出目录 |
| 租户权限不清 | 共享模板或历史报告泄漏 | 权限矩阵 + route-level authz |
| PDF 图表缺失 | 导出不可用 | Phase 0 提前验证 chart → PDF 路径 |
| DSL 过度复杂 | 难实现、难维护 | v1 只支持多步表单、allowlist steps、sections、export |

---

## 17. MVP 验收标准

1. 用户能从“自定义模板”入口创建基于日报的模板草稿。
2. 模板 DSL 支持 `form_steps`、`options_source`、`data_steps`、`transforms`、`sections`。
3. 模板保存前经过后端 validator 校验。
4. 模板不保存在 `/mnt/user-data/report-templates`，而是保存在 DB 或 DeerFlow home 用户/租户目录。
5. 用户运行模板时仍在现有 agent thread 内完成。
6. 动态流程能复刻日报：范围选择 → 设备选择 → KPI 选择 → 报告生成。
7. callback_id 不固定，能防止跨线程/重复提交。
8. 脚本只能从 registry allowlist 执行。
9. 每次运行使用独立 output dir，不覆盖其它运行文件。
10. 生成 `report_payload.json`、Markdown artifact 和 ReportRun 索引。
11. 非法脚本、非法参数、非法 source、越权模板访问都会被拒绝并返回结构化错误。

---

## 18. 推荐结论

自定义模板功能应该被设计为 AI 报告体系中的“模板平台能力”，而不是一个自由对话式报告助手。修订后的推荐路线是：

1. 入口继续使用 `ai-report--custom`。
2. 创建和编辑由 SOUL + GenUI 引导。
3. 保存、校验、运行由后端确定性服务和受控工具完成。
4. MVP 运行继续绑定现有 thread/run，不新建独立执行引擎。
5. 模板存储使用 DB 或 DeerFlow home 用户/租户目录。
6. 报告产物使用 run-scoped output 并复用 artifact 下载。
7. DSL v1 必须支持动态多步表单，才能复用日报的核心体验。

按这个路线实现，可以最大化复用 DeerFlow 当前 Agent / SOUL / GenUI / Skill / artifact 架构，同时避免安全、权限、并发和可追溯性风险。
