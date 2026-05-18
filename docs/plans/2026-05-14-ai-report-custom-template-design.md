# AI 报告自定义模板功能设计文档（修订版）

> **范围**：分析当前 AI 日报智能体和其它报告功能，重新设计“自定义模板”能力。
> **修订重点**：本版修正了初版设计中运行边界、存储路径、动态 DSL、GenUI 回调安全、多租户权限、ReportRun 与现有 thread/run 关系不清等问题。
> **核心结论**：MVP 不新建独立报告执行引擎，而是在现有 Agent / SOUL / GenUI / ThreadRun / artifact 架构内增加“可校验、可版本化、可运行”的报告模板能力。
> **与当前代码基线对齐（2026-05-17）**：本文以仓库当前实现为基线；其中 GenUI `InteractionStore` 已按 `(thread_id, callback_id)` 复合 key 工作，后续章节不再把它当作待设计能力，而是当作既有约束与回归范围。

---

## 0. 架构决策摘要

> 本表是项目执行的"宪法"：所有后续章节、Phase 划分、验收标准都从这些决策派生。涉及决策反转时必须先更新此表。

| 决策项 | 结论 | 原因 |
| ------ | ------ | ------ |
| 自定义模板入口 | 继续使用 [ai-report--custom/SOUL.md](../../agents/builtin/ai-report--custom/SOUL.md) | 符合现有 AI 报告父子智能体入口，不新增割裂入口 |
| 模板创建/编辑 | 由 `ai-report--custom` 通过 GenUI 引导 + Phase 5 独立管理 UI | 对话覆盖创建路径，UI 覆盖管理路径 |
| 模板保存/校验 | 必须走后端确定性服务或受控内置工具 | 禁止 LLM 直接用 bash 写模板仓库 |
| 模板运行 MVP | 继续走现有 Agent thread/run | 保留 GenUI streaming、sandbox、artifact、取消、历史能力 |
| **Runtime 物理实现** | **LLM 驱动**：SOUL 指引 LLM 调用 `report_template_*` 工具，由工具内部模块推进状态机 | 复用现有 agent/SOUL/tool 编排，不新建独立 runner 进程 |
| ReportRun | 作为报告维度索引，绑定现有 `thread_id` / `run_id` | 不重复实现 RunManager |
| **Thread 删除级联** | **MVP 级联删除**：thread 仍是 ReportRun 与 artifact 的生命周期根；删除 thread 时同步删除关联 ReportRun 索引与 run-scoped 输出，不保留孤儿记录 | 当前 artifact 路由绑定 thread，先保证数据与权限闭环；“脱离 thread 保留历史”放到 V2 再立项 |
| **模板存储** | **MVP 文件存储**（`{DEER_FLOW_HOME}/report-templates/`）→ **V2 迁移 PostgreSQL** | MVP 降低实现成本，V2 升级以支持检索/分页 |
| **DSL 序列化格式** | **YAML**（含注释，便于人类阅读和手写） | 与文档示例、SOUL.md 风格一致 |
| 报告产物 | 使用 run-scoped output 目录，并通过现有 artifact 路由暴露 | 避免并发覆盖，复用权限模型 |
| DSL v1 | 支持多步动态表单 `form_steps` 和 `options_source` | 才能复刻日报"范围 → 设备 → KPI → 生成"的核心体验 |
| **DSL 占位符表达式** | **裁剪后的 JSONPath 子集**（仅支持路径访问，禁用过滤器/函数） | 安全可控，表达力够用 |
| **callback_id 安全** | **沿用现有 `(thread_id, callback_id)` 复合 key 实现**，本立项只补回归和命名约束 | 当前代码已落地，设计不应重复计入 Phase 1 新开发 |
| 脚本执行 | 只能通过 allowlist registry，使用参数数组执行 | 防止命令注入和任意代码执行 |
| **Script Registry 维护** | **由 skill 插件贡献**：每个 skill 声明导出的脚本 registry | 与现有 skill 架构同构，安装 skill = 注册脚本 |
| **导出格式** | **Markdown 必需，PDF 可选降级** | 复用现有 `export_report.py` 行为，避免引入 chromium 依赖 |
| **可见范围** | **完整权限矩阵**：private / tenant / builtin | 一次性建立完整模型，避免后续扩展时返工 |
| **平台管理员** | **复用现有 `superadmin` / `tenant_admin` 角色** | 与 `tenant_agents.py` 现有权限模型一致 |
| **发布版本化** | **强制版本迭代**：published 不可改，编辑生成新草稿 / 新版本 | 保证 ReportRun 可复现 |
| **MVP 日报迁移** | **重写为 DSL 模板**，旧 `ai-report--daily/SOUL.md` 保留作为 fallback | 验证 DSL 表达力，保留兜底 |
| **Builtin 预置模板** | **MVP 交付 daily**；`weekly/monthly` 作为 MVP+1（Phase 5）；其余 5 种作为后续增量路线图 | 先验证模板平台成立，再扩展报告覆盖面 |
| **报告历史 UI** | **嵌入现有对话历史**，不新建独立"报告中心" | 复用现有侧边栏和列表组件 |
| **Phase 6 范围** | **作为路线图，不纳入本次立项承诺**；如需启动，按单报告类型拆分排期与验收 | 避免平台能力尚未验证就一次性承诺全部报告类型 |

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

### 3.4 Runtime 物理实现：LLM 驱动 + 受控工具

> **决策**：Runtime 不是独立服务、不是后台 worker，而是一组**受控内置工具的有状态组合**。LLM（在 ai-report--custom SOUL.md 指引下）按顺序调用这些工具，每个工具内部执行确定性逻辑并把结果回流到 LangGraph 上下文。

**调用关系**：

```text
LLM (ai-report--custom) 
  ├── report_template_prepare_run        →  分配 report_run_id + nonce
  ├── report_template_render_step        →  按 DSL 解析当前 step → 注入 GenUI block 到 SSE 流
  │      (用户在前端提交表单)
  ├── report_template_submit_step        →  校验 payload → 写 form 状态 → 决定下一步
  │      ↓ (如果还有 step)
  │      回到 render_step
  │      ↓ (如果到 generate)
  ├── report_template_run_data_steps     →  按 DSL 顺序执行 data_steps + transforms
  ├── report_template_assemble_payload   →  按 sections 装配 report_payload.json
  ├── report_template_render_report      →  把 sections 转换为 GenUI blocks 推送
  └── report_template_export             →  调用 export_report 生成 .md / .pdf
```

**状态保存**：

- 单次模板运行的全部状态保存在 `{run_output_dir}/status.json`，每个工具调用前后读写。
- LLM 不需要在 prompt 中维护 form 历史值，所有跨工具的状态由 `status.json` 承载。
- 重新进入会话只需 `report_template_resume_run` 读取最近未完成的 ReportRun 状态。

**为什么是 LLM 驱动而非后台 runner**：

| 维度 | LLM 驱动 | 独立 runner |
| ------ | ------ | ------ |
| 复用现有 GenUI/SSE/artifact | ✅ 直接复用 | ❌ 需要重新打通 |
| LLM 可在表单之间插入解释/澄清消息 | ✅ 自然支持 | ❌ 需要单独事件流 |
| 失败重试 | LLM 可被引导重试单步 | 需要独立状态机 |
| 上下文窗口压力 | 工具调用次数多，但每次返回精简 | 无压力 |
| 实施复杂度 | 低 | 高 |

**LLM 错误推进的兜底**：

LLM 是非确定性的，可能跳步、漏调或乱序。约束方式：

- 每个工具调用都校验 `report_run_id`、`expected_step` 与 `status.json` 中的状态一致，不一致直接返回结构化错误。
- 工具返回中明确告知 LLM "下一个应该调用的工具"。
- ai-report--custom 的 SOUL.md 必须给 LLM 提供清晰的工具调用流程图。

**Runtime 模块的代码组织**：

```text
backend/packages/harness/deerflow/report_templates/
  runtime/
    state.py            # status.json 读写、状态机校验
    step_renderer.py    # DSL form_step → GenUI block
    step_submitter.py   # form payload 校验、推进
    data_runner.py      # 执行 data_steps / transforms / before_step
    payload_builder.py  # 装配 report_payload.json
    report_renderer.py  # sections → GenUI blocks
    exporter.py         # 调用 export_report
  schema.py             # DSL Pydantic schema
  validator.py          # DSL 整体校验
  repository.py         # 模板/版本/run 持久化
  script_registry.py    # 从 skill 插件加载 registry
  source_resolver.py    # JSONPath 子集解析
```

`report_template_*` 工具是 `tools/builtins/` 下的薄壳，内部委托给 `runtime/` 模块。完整工具列表（含每个工具委托的模块）见 §8.2。

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

### 5.6 占位符表达式解析器（JSONPath 子集）

> **决策**：DSL 中所有 `{{ ... }}` 占位符使用**裁剪后的 JSONPath 子集**，由后端自实现解析器，禁用一切表达式语义。

**支持的语法（白名单）**：

| 语法 | 含义 | 示例 |
| ---- | ---- | ---- |
| `$.form.<step_id>.<field_name>` | 引用某 form_step 的某字段提交值 | `$.form.scope.report_date` |
| `$.steps.<step_id>.<output_id>` | 引用某 data/transform/before_step 输出 JSON 文件全部内容 | `$.steps.daily_data.daily_data` |
| `$.steps.<step_id>.<output_id>.<key>` | 访问输出 JSON 中的字段 | `$.steps.daily_kpi.daily_kpi.overall_status.summary` |
| `$.steps.<step_id>.<output_id>[*].<key>` | 数组所有元素的某字段（用于 options_source） | `$.steps.equipment_catalog.equipment[*].id` |
| `$.run.<key>` | 运行时元数据（仅 `report_run_id`、`thread_id`、`generated_at`） | `$.run.report_run_id` |
| `$.template.<key>` | 模板元数据（仅 `id`、`version`、`name`） | `$.template.version` |

**禁用的语法（黑名单）**：

| 类别 | 原因 |
| ---- | ---- |
| 过滤器 `[?(@.x > 1)]` | 任意表达式入口 |
| 函数调用 `.length()`, `min()`, `concat()` | 计算能力会扩散到模板，应下沉到脚本 |
| 递归下降 `..` | 无法静态校验路径存在性 |
| 反向引用 父节点 | 同上 |
| 运算符 `+ - * /` | 模板不应做计算 |
| 条件 `if/else` | 模板应保持声明式 |
| 字面量字符串拼接 | 拼接交给 sections 内嵌或脚本 |
| 通配符 `[*]` 之外的索引访问 | 仅 `[*]` 用于展开数组，不允许 `[0]`、`[-1]`、`[1:3]` 等 |

**解析器实现要求**：

- 自实现 tokenizer + parser，**不引入 jsonpath-ng / jmespath / jq 等任何第三方表达式库**（避免无意中开放黑名单语法）。
- 解析器输出 AST，AST 节点类型只有 `Root`、`FieldAccess`、`ArrayAll`，三种以外抛 `INVALID_SYNTAX` 错误。
- 解析器在 DSL 保存时（validator 阶段）执行一次，运行时只做求值，不重新解析。
- 求值阶段对 path 任一段不存在抛 `PATH_NOT_FOUND`，不做 silent null。
- 数组展开 `[*]` 后必须紧跟字段访问，不允许 `[*]` 单独出现。
- 路径深度限制 ≤ 8 层，防止过度嵌套。

**与 5.2 节示例语法的对齐**：

5.2 节 DSL 示例使用 `"{{ form.scope.equipment_type }}"` 语法（无 `$.` 前缀）。最终采用：

- 完整语法：`"{{ $.form.scope.equipment_type }}"`（推荐，明确以 `$` 表示根）
- validator 同时接受 `"{{ form.scope.equipment_type }}"` 简写并自动补全 `$.`，便于人类手写

**运行时上下文**：

```python
{
  "form": {
    "scope": {"report_date": "2026-05-14", "equipment_type": "pump", ...},
    "equipment": {"equipment_ids": ["P-001", "P-002"]},
    "kpis": {"kpi_keys": ["runtime_rate", "alarm_count"]},
  },
  "steps": {
    "equipment_catalog": {  # before_step 输出
      "equipment": [{"id": "P-001", "area": "A区", ...}, ...],
      "available_kpis": [...],
    },
    "daily_data": {"daily_data": {...}},  # data_step 输出，key = output_id
    "daily_kpi": {"daily_kpi": {...}},    # transform 输出
  },
  "run": {"report_run_id": "rr_xxx", "thread_id": "...", "generated_at": "..."},
  "template": {"id": "tpl_xxx", "version": 3, "name": "..."},
}
```

**单元测试覆盖（必须）**：

- 合法路径 → 正确求值
- 路径不存在 → 结构化错误
- 黑名单语法 → 解析失败
- 数组 `[*]` 用法
- 深度超限
- form 字段引用未声明的 step
- options_source 引用未执行的 step

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
- dsl_yaml
- checksum
- source_template_id
- source_template_version
- created_by
- created_at
- changelog
```

约束：

- 版本快照不可变。
- `dsl` 是解析后结构化内容，`dsl_yaml` 保留原始文本与注释，二者一起构成可复现快照。
- ReportRun 必须绑定具体 `template_id + version`。
- `version` 对 user/tenant 模板是递增整数；builtin 模板不走这里的版本目录，而是在 ReportRun 侧记录不可变 `template_version_ref`（如 `git_sha[:8]-dsl_version`）。
- fork 时必须记录源模板 ID 和源版本。

### 6.3 ReportRun

```text
ReportRun
- id
- template_id
- template_version
- template_version_ref
- thread_id
- run_id
- user_id
- tenant_id
- idempotency_key
- status: pending | running | succeeded | failed | canceled
- parameters_summary
- parameters_path
- report_payload_path
- artifact_paths
- data_snapshot_paths
- error_code
- error_message
- created_at
- started_at
- completed_at
```

MVP 中 `ReportRun` 不是独立执行引擎，只是绑定现有 thread/run 的报告索引；其生命周期跟随所属 thread，删除 thread 时同步删除对应索引与产物。对 user/tenant 模板，`template_version` 记录数值版号、`template_version_ref` 可取 `v{n}`；对 builtin 模板，`template_version` 可为空，`template_version_ref` 记录不可变源码引用。

---

## 7. 存储设计

### 7.1 模板存储（MVP 文件存储 → V2 DB 迁移）

**MVP 决策**：使用 DeerFlow home 下的用户/租户隔离文件存储，**不进 PostgreSQL**。V2 阶段再迁移到 DB。

#### 7.1.1 文件目录结构

> **决策**：用户/租户模板存储在 `{DEER_FLOW_HOME}/report-templates/`（运行时数据），**Builtin 模板存储在仓库内 `agents/builtin/report-templates/`**（随代码版本控制），启动时加载到内存索引，对外通过统一 repository 接口访问。

**用户/租户运行时数据**（可写）：

```text
{DEER_FLOW_HOME}/report-templates/
  users/{user_id}/
    index.json                          # 用户模板索引（list 接口数据源）
    {template_id}/
      template.json                     # 当前 metadata（含 current_version）
      versions/
        v1.json                         # 版本 1 不可变快照
        v2.json
        ...
      runs/
        {report_run_id}.json            # ReportRun 索引（不存数据，数据在 thread_output_dir）
  tenants/{tenant_id}/
    index.json
    {template_id}/...                   # 同上结构
```

**Builtin 模板**（只读，随代码版本）：

```text
agents/builtin/report-templates/
  daily-equipment/
    default.yaml                        # DSL 模板源文件（YAML，含注释）
    metadata.yaml                       # display_name / description / tags / dsl_version
    examples/
      sample_parameters.json            # 示例参数
      sample_report_payload.json        # 示例输出
  weekly-equipment/
    default.yaml
    metadata.yaml
    examples/...
  monthly-equipment/
    default.yaml
    metadata.yaml
    examples/...
  # Phase 6 新增
  trend-equipment/...
  diagnosis-fault/...
  failure-analysis/...
  closure-summary/...
  inspection/...
```

Builtin 模板的加载机制：

- 应用启动时，`load_builtin_templates()` 扫描 `agents/builtin/report-templates/`，逐个解析 `default.yaml` + `metadata.yaml`，校验 DSL，构造内存索引。
- Builtin 模板的 `id` 由目录名生成（`builtin-daily-equipment` 等），对外保持稳定。
- 普通用户调用 `report_template_get(visibility=builtin, id=...)` 时，repository 从内存索引返回。
- 普通用户**不能写**任何 builtin 路径——`FileSystemReportTemplateRepository` 对 builtin scope 只暴露读接口。
- 平台管理员若要修改 builtin 模板，必须**通过代码 PR**修改仓库源文件后重启加载，而非通过 API 写文件。
- Builtin 模板没有 `versions/` 目录概念，版本号即代码 commit / release 版本；ReportRun 绑定时记录 `template_version_ref = "{git_sha[:8]}-{dsl_version}"`。

#### 7.1.2 文件格式

`template.json`（当前 metadata）：

```json
{
  "id": "tpl_01H...",
  "name": "equipment_daily_custom",
  "display_name": "重点机泵日报",
  "description": "...",
  "owner_user_id": "u_xxx",
  "tenant_id": "t_xxx",
  "visibility": "private",
  "status": "draft",
  "current_version": 0,
  "dsl_version": "1",
  "created_at": "...",
  "updated_at": "...",
  "etag": "uuid-for-optimistic-lock"
}
```

`versions/v{N}.json`（不可变快照）：

```json
{
  "template_id": "tpl_01H...",
  "version": 1,
  "dsl": {...},                           # 完整 YAML 解析后 JSON
  "dsl_yaml": "...",                      # 原始 YAML 文本（保留注释）
  "checksum": "sha256:...",
  "created_by": "u_xxx",
  "created_at": "...",
  "changelog": "..."
}
```

`runs/{report_run_id}.json`：

```json
{
  "id": "rr_01H...",
  "template_id": "tpl_01H...",
  "template_version": 1,
  "template_version_ref": "v1",
  "thread_id": "...",
  "run_id": "...",
  "user_id": "u_xxx",
  "tenant_id": "t_xxx",
  "idempotency_key": "...",
  "status": "succeeded",
  "parameters_summary": {"report_date": "2026-05-14", ...},   # 仅摘要，原文在 parameters.json
  "parameters_path": "{thread_output_dir}/report-runs/rr_xxx/parameters.json",
  "report_payload_path": "{thread_output_dir}/report-runs/rr_xxx/report_payload.json",
  "artifact_paths": {"md": "...", "pdf": null},
  "data_snapshot_paths": ["..."],
  "error_code": null,
  "error_message": null,
  "created_at": "...",
  "started_at": "...",
  "completed_at": "..."
}
```

`index.json`（每个 user/tenant 一份，list 接口和搜索使用）：

```json
{
  "schema_version": "1",
  "updated_at": "...",
  "templates": [
    {
      "id": "tpl_xxx",
      "name": "...",
      "display_name": "...",
      "visibility": "private",
      "status": "draft",
      "current_version": 0,
      "tags": ["daily", "pump"],
      "updated_at": "..."
    }
  ]
}
```

#### 7.1.3 并发控制

**所有写操作必须满足**：

1. **临时文件 + 原子 rename**：`template.json.tmp` → `template.json`，避免读到半写文件。
2. **乐观锁 (etag)**：客户端提供 `expected_etag`，写前比对，不一致返回 `409 Conflict`。
3. **进程内文件锁 (`fcntl.flock`)**：避免同进程多协程同时写同一文件。
4. **跨进程锁回退**：若 fcntl 不可用（Windows），用 `.lock` 哨兵文件 + 超时。
5. **index.json 更新与 template.json 写入需要在同一锁内**，避免索引漂移。

#### 7.1.4 安全约束

**ID 字符校验**（所有进入路径拼装的 ID 都必须强校验）：

- `template_id` 必须匹配 `^tpl_[A-Z0-9]{20,32}$`（ULID 风格），禁止用户自选。
- `report_run_id` 必须匹配 `^rr_[A-Z0-9]{20,32}$`（ULID 风格），禁止用户自选。该 ID 同时用于 `{thread_output_dir}/report-runs/{report_run_id}/` 路径拼接。
- `user_id`、`tenant_id` 必须匹配 `^[a-zA-Z0-9_-]{1,64}$`，路径拼装前强校验。
- 所有 ID 字段在 repository 入口处再校验一次，不依赖上游传入已合法。

**路径越权防护**：

- 写入路径必须经过 `Path.resolve()` 后落在 `{DEER_FLOW_HOME}/report-templates/` 子树内（防 `../` 越权）。
- 运行时输出路径必须经过 `Path.resolve()` 后落在 `{thread_output_dir}/report-runs/` 子树内。
- 读取 builtin 仅允许 `Path.resolve()` 后在仓库内 `agents/builtin/report-templates/`。
- DSL 中所有用户提供的字符串字段（template_id、script name、JSONPath path）在拼接路径或命令前必须显式校验，不依赖运行时偶然失败。

#### 7.1.5 V2 DB 迁移路径

> **决策**：V2 迁移到 PostgreSQL 时，复用现有 `AgentRepository` / `TenantMcpServerRepository` 的 SQLAlchemy async 模式。

迁移工作项（V2 立项后）：

1. 新增 SQLAlchemy 模型：`ReportTemplate`、`ReportTemplateVersion`、`ReportRun`。
2. 新增 alembic 迁移脚本。
3. 新增 `ReportTemplateRepository` 实现，与文件实现并存（通过 config 切换）。
4. 编写 `migrate_report_templates.py` 脚本：扫描 `{DEER_FLOW_HOME}/report-templates/` → 写入 DB，记录已迁移的 template_id。
5. 双写过渡期：MVP repo 写文件，V2 repo 同时写 DB；切换完成后下线文件 repo。
6. ReportRun 索引迁移：用户的运行记录从 `runs/{id}.json` 迁到 `report_runs` 表，但 `report_payload.json`、artifact 仍保留在 `thread_output_dir`。

为 V2 迁移的预先约束（MVP 需要遵守，避免迁移时返工）：

- 文件 schema 必须包含完整 metadata（不能依赖文件名解析）。
- 所有时间戳必须是 ISO 8601 with timezone。
- 所有 ID 字段命名需对齐预期 DB schema 字段名。
- 不在文件中存任何"路径相对当前目录"的引用，全部用绝对 schema 字段。

### 7.2 报告运行输出

报告运行输出必须 run-scoped：

```text
{thread_output_dir}/report-runs/{report_run_id}/
  parameters.json
  template_version.json                  # 模板 DSL 快照副本
  status.json                            # Runtime 状态机状态（form 状态、当前 step）
  data/
    {output_id}.json                     # data_steps / transforms 输出（key = output_id）
  report_payload.json                    # 装配后的 payload
  exports/
    report.md
    report.pdf                           # 可选，weasyprint 不可用时缺失
```

要求：

- 不同 ReportRun 不能共享固定 `daily_data.json`。
- 所有脚本输出目录由 runtime 创建并注入（`{run_output_dir}` 占位符替换为绝对路径）。
- artifact 只暴露相对安全路径（通过 `/api/threads/{thread_id}/artifacts/...`）。
- 产物下载继续走现有 artifact 权限模型。
- `status.json` 是 Runtime 唯一的状态源，重启会话能从它恢复未完成的 run。
- `thread_id` 是产物生命周期根：MVP 中删除 thread 必须同步删除其 `report-runs/` 子树和 ReportRun 索引；若用户需要长期保留，必须先导出 Markdown/PDF。

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

为了让 `ai-report--custom` 在对话中创建和运行模板，新增 14 个受控内置工具，禁止 LLM 直接用 bash 写文件。所有工具是**薄壳**（≤50 行），核心逻辑委托 §3.4 中的 `runtime/` 模块。工具调用流程图见 §3.4。

**模板生命周期工具（6 个）**：

| 工具 | 职责 | 委托模块 |
| ------ | ------ | ------ |
| `report_template_list` | 列出用户可见模板（按 visibility 过滤） | `repository.py` |
| `report_template_get` | 获取模板详情和指定版本 | `repository.py` |
| `report_template_validate` | 校验 DSL 并返回结构化错误 | `validator.py` |
| `report_template_save_draft` | 保存草稿（含 etag 乐观锁） | `repository.py` |
| `report_template_publish` | 发布新版本（强制版本迭代） | `repository.py` |
| `report_template_fork` | 从可见模板复制为自己的草稿 | `repository.py` |

**运行时工具（8 个）**：

| 工具 | 职责 | 委托模块 |
| ------ | ------ | ------ |
| `report_template_prepare_run` | 创建 ReportRun 草稿、分配 run_id 和 nonce、初始化 status.json | `runtime/state.py` |
| `report_template_render_step` | 按 DSL 解析当前 form_step（含 before_step），渲染 GenUI block 推送至 SSE | `runtime/step_renderer.py` |
| `report_template_submit_step` | 校验 callback payload，写入 form 状态，决定下一步（render_step 或 generate） | `runtime/step_submitter.py` |
| `report_template_run_data_steps` | 按 DSL 顺序执行 data_steps + transforms，输出到 run-scoped 目录 | `runtime/data_runner.py` |
| `report_template_assemble_payload` | 按 sections 装配 `report_payload.json` | `runtime/payload_builder.py` |
| `report_template_render_report` | 把 sections 转换为 GenUI blocks 推送渲染 | `runtime/report_renderer.py` |
| `report_template_export` | 调用 `export_report.py` 生成 .md（必需）/.pdf（可选降级） | `runtime/exporter.py` |
| `report_template_resume_run` | 读取最近未完成 ReportRun 的 status.json，恢复执行位置 | `runtime/state.py` |

**通用约束（所有工具）**：

- 内部委托对应的 `runtime/` 模块，工具本体只做参数解包 + 错误包装。
- 使用认证上下文中的 `user_id` / `tenant_id`，不接受请求 body 覆盖。
- 写操作工具调用对应 repository 方法，权限校验在 Gateway 路由或工具内执行。
- 运行时工具校验 `report_run_id` + `expected_step` 与 `status.json` 一致，不一致直接返回结构化错误（`STATE_MISMATCH`）。

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
POST   /api/report-templates/{template_id}/archive
DELETE /api/report-templates/{template_id}
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

### 9.1 Registry 由 skill 插件贡献

> **决策**：Registry 不是中心化的 JSON 文件或 DB 表，而是**由每个 skill 自己声明**。安装一个 skill = 自动注册它导出的脚本。这与现有 [skills 系统](../../backend/packages/harness/deerflow/skills/) 同构。

#### 9.1.1 Skill 中的 registry 文件

每个 skill 可在自己根目录下提供 `report_scripts.yaml`（可选，仅当 skill 想暴露报告脚本时）：

```text
skills/custom/data-analyst/
  SKILL.md
  report_scripts.yaml          # ← 新增
  scripts/
    list_equipment.py
    query_daily.py
    daily_kpi.py
    ...
```

`report_scripts.yaml` 格式：

```yaml
schema_version: "1"
scripts:
  list_equipment:
    entry: scripts/list_equipment.py     # 相对 skill 根目录
    kind: [form_options]
    description: "查询设备目录、区域分组、可用 KPI"
    args_schema:
      type:
        type: enum
        values: [all, static_equipment, rotating_machinery, pump, reciprocating_machinery]
        required: true
      scope:
        type: enum
        values: [all, selected]
        default: all
      limit:
        type: integer
        min: 1
        max: 10000
        default: 10000
    outputs_schema:
      equipment:
        type: array
        items_schema:
          id: {type: string}
          name: {type: string}
          area: {type: string}
      available_kpis:
        type: array
        items_schema:
          key: {type: string}
          label: {type: string}
          unit: {type: string}
          default: {type: boolean}
    timeout_seconds: 30
    max_output_bytes: 10485760              # 10 MB

  query_daily:
    entry: scripts/query_daily.py
    kind: [data_step]
    description: "生成日报原始数据"
    args_schema:
      date:
        type: date
        required: true
      equipment_type:
        type: enum
        values: [all, static_equipment, rotating_machinery, pump, reciprocating_machinery]
      equipment_ids:
        type: array
        items: {type: string, pattern: "^[A-Za-z0-9_-]+$", max_length: 64}
        max_items: 1000
      kpis:
        type: array
        items: {type: string, pattern: "^[a-z_]+$"}
        max_items: 50
      compare:
        type: enum
        values: [previous_day, previous_week, none]
    output_files:
      - id: daily_data
        path: "{run_output_dir}/data/daily_data.json"     # runtime 注入绝对路径
    timeout_seconds: 120
    max_output_bytes: 52428800              # 50 MB

  daily_kpi:
    entry: scripts/daily_kpi.py
    kind: [transform]
    description: "生成 KPI、图表、异常表、建议"
    args_schema:
      input:
        type: file_path                     # 来自前序 step 的输出
        required: true
    output_files:
      - id: daily_kpi
        path: "{run_output_dir}/data/daily_kpi.json"
    timeout_seconds: 60
    max_output_bytes: 10485760
```

#### 9.1.2 Registry 加载逻辑

```text
backend/packages/harness/deerflow/report_templates/script_registry.py

  load_registry() →
    1. 调用 deerflow.skills.load_skills() 获取所有 enabled skills
    2. 对每个 skill 检查 {skill_path}/report_scripts.yaml
    3. 解析 YAML，校验 schema，构建 ScriptDescriptor 列表
    4. namespace：脚本名格式 "{skill_name}/{script_name}"
       例如 "data-analyst/list_equipment"，避免不同 skill 同名脚本冲突
    5. 跨 skill 同名（namespace 内）的脚本视为冲突，启动报错
    6. 缓存结果，监听 skills enable/disable 事件失效缓存
```

#### 9.1.3 DSL 中引用脚本的方式

DSL `data_steps[].name` 必须使用完整 namespace：

```yaml
data_steps:
  - id: daily_data
    kind: script
    name: data-analyst/query_daily        # ← 必须包含 skill 名
    args:
      date: "{{ $.form.scope.report_date }}"
      ...
```

validator 校验：

- 引用的 skill 必须存在且 enabled。
- 脚本必须在该 skill 的 registry 中声明。
- args 必须通过 args_schema 校验。

#### 9.1.4 builtin 脚本

对于不属于任何 skill 的"平台核心脚本"（例如未来可能新增的 `generic_export`），由平台代码注册到 registry 的 `builtin/` 命名空间：

```yaml
# 在 deerflow.report_templates.builtin_scripts 中定义
schema_version: "1"
scripts:
  generic_export:
    entry: deerflow.report_templates.builtin_scripts.generic_export:run
    kind: [export]
    ...
```

builtin 脚本可以是 Python 函数（`module:function`），不必走 sandbox bash。

### 9.2 执行要求

- **仅允许参数数组调用**：`subprocess.run([interpreter, script_path, "--arg1", v1, ...])`，禁止 `shell=True`。
- **所有 args 双重校验**：先 DSL schema，再 registry args_schema。两层校验都通过才执行。
- **输出目录由 runtime 创建并注入**：runtime 在调用前 mkdir，把 `{run_output_dir}` 替换为绝对路径，作为 `--output-dir` 参数传入。
- **脚本不接受任意输出路径**：脚本只能写入它声明的 `output_files` 路径，runtime 在执行后校验输出文件确实存在且大小未超限。
- **每个输出写元数据**：runtime 在脚本输出旁写 `<output>.meta.json`，含 `checksum`、`schema_version`、`created_at`、`script_name`、`script_version`。
- **超时与资源限制**：`subprocess.run(timeout=descriptor.timeout_seconds)`，超时后强杀。Linux 下用 `resource.setrlimit` 限制内存和 CPU。
- **错误码标准化**：脚本 stderr 输出结构化 JSON `{"code": "...", "message": "...", "details": {...}}`，runtime 解析后纳入 ReportRun 的 error_message。

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

> **决策**：沿用当前代码基线中的 `(thread_id, callback_id)` 复合 key 机制；本立项不重复设计这一能力，只在新流程接入时补回归与命名约束。

#### 10.2.1 业务层 callback_id 命名

业务侧仍然使用语义化 callback_id，不再依赖随机后缀防冲突：

```text
custom-report:{template_id}:{report_run_id}:{step_id}
```

`thread_id` 由底层自动注入，业务无需在 ID 中拼接。

#### 10.2.2 提交时的服务端校验

`report_template_submit_step` 工具内部校验：

- callback 存在于 `(current_thread_id, callback_id)`。
- 当前用户有权访问该 thread（已通过现有 thread auth 保证）。
- callback 未超时（沿用现有 `callback_timeout_ms`）。
- `report_run_id` 匹配 `status.json` 中的当前 run。
- `step_id` 等于 `status.json` 中的 expected_step，防止乱序提交。
- 同一 step 已提交过则返回 `STEP_ALREADY_SUBMITTED`，避免重复执行。

### 10.3 InteractionStore 当前基线与回归要求

当前仓库已经实现 thread-scoped callback 机制，本立项应**复用现有能力**，而不是再次发起底层改造。

#### 10.3.1 当前代码基线

当前实现位于 [backend/packages/harness/deerflow/agents/middlewares/genui_middleware.py](../../backend/packages/harness/deerflow/agents/middlewares/genui_middleware.py)：

```python
def _make_key(thread_id: str, callback_id: str) -> str:
    return f"{thread_id}\x1f{callback_id}"
```

已落地的关键行为：

- `InteractionStore` 按 `(thread_id, callback_id)` 组合键存储交互记录。
- `render_ui_tool.py` 在注册交互和检测重复表单时已使用当前 `thread_id`。
- `/api/threads/{thread_id}/ui-interaction` 提交接口已经按 thread 维度查询 callback。
- 现有测试已覆盖“不同 thread 相同 callback_id 不串扰”。

#### 10.3.2 本立项要求

报告模板运行时必须遵守以下接入约束：

- 所有 `report_template_*` 交互都走现有 `render_ui` / `ui-interaction` 链路，不自行维护第二套 callback store。
- `callback_id` 继续使用语义化命名，但必须可追踪到 `template_id / report_run_id / step_id`。
- `report_template_submit_step` 除 thread-scoped callback 校验外，还必须校验 `report_run_id`、`expected_step` 和 `status.json` 的状态一致性。
- 不引入旧 key 兼容迁移逻辑；如发现新流程绕开现有 helper，直接修正新流程，而不是再设计适配层。

#### 10.3.3 回归范围

本立项需要新增或复用的回归测试：

- ai-report--daily 的 3 轮表单（scope / equipment / kpis）行为不变。
- ai-report--custom 新增的模板创建与运行表单支持跨 thread 同名 callback。
- `render_ui_tool` 重复表单保护仍然只在同一 thread 内生效。
- thread 删除时，该 thread 下的 InteractionRecord 与 report-run 输出一并清理。

#### 10.3.4 callback_id 命名约束

虽然底层已做 thread-scoped 隔离，业务侧仍需保持可读性和可排障性：

- 不要在 ai-report--custom 中使用与 ai-report--daily 同语义但不可区分的 callback_id。
- 推荐格式：`custom-report:{template_id}:{report_run_id}:{step_id}`。
- 对于非报告模板业务，继续使用 `{agent-prefix}:{purpose}` 或 `{agent-prefix}:{purpose}:{instance_id}`。

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

> **权限实现**：复用现有 `superadmin` / `tenant_admin` 角色（见 [tenant_agents.py](../../backend/app/gateway/routers/tenant_agents.py)）。"tenant editor" 在 MVP 阶段等同于 `tenant_admin`，未来可在 V2 引入更细的角色分级（`tenant_template_editor`）。"platform admin" 即 `superadmin`。

### 11.2 权限原则

- `user_id` 和 `tenant_id` 只来自认证上下文。
- 请求 body 和 DSL 中的 owner/tenant 字段只作为展示草案，不作为授权依据。
- `builtin` 模板只能平台管理员修改。
- `tenant` 模板发布需要租户模板编辑权限。
- ReportRun 查询必须同时校验模板可见性和运行记录 owner/tenant。
- artifact 下载必须绑定 ReportRun/thread 权限。
- visibility 提升（private → tenant → builtin）必须满足升级目标的写权限：private → tenant 需要 `tenant_admin`，tenant → builtin 需要 `superadmin`。

### 11.3 数据安全

报告运行产物可能包含生产设备数据，必须支持：

- 保留期策略。
- 手动删除或归档。
- 下载审计。
- 错误信息脱敏。
- Markdown/PDF XSS 防护。
- ECharts option 只允许纯 JSON，不允许函数、HTML formatter、外链脚本。

### 11.4 现有日报迁移与 fallback 策略

> **决策**：MVP 阶段把现有日报流程**重写为 DSL 模板**（作为 builtin 预置模板），同时**保留旧 `ai-report--daily/SOUL.md` 作为 fallback**。

#### 11.4.1 双轨并存模型

```text
ai-report--daily/
  config.yaml                          # 不变，仍是 ai-report 的子 agent
  SOUL.md                              # 旧版硬编码流程，保留为 fallback
  SOUL.md.legacy                       # 备份（首次重写时归档）

agents/builtin/report-templates/
  daily-equipment/
    default.yaml                       # 新版 DSL 模板
```

#### 11.4.2 路由策略

`ai-report--daily/SOUL.md` 需要在重写后增加分支判断：

```text
1. 调用 report_template_get(name="daily-equipment", visibility="builtin")
   - 命中：调用 report_template_prepare_run + 后续模板运行流程（DSL 路径）
   - 未命中或工具不可用：走 SOUL.md 内嵌的硬编码流程（fallback 路径）
2. 用户也可以通过 ai-report--custom 的"基于日报复制"创建自己的副本
```

#### 11.4.3 何时下线 fallback

满足以下全部条件后，才能从 `SOUL.md` 中删除 fallback 分支：

1. `daily-equipment` builtin 模板连续生产 30 天，**0 次降级到 fallback**。
2. ReportRun 成功率 ≥ 99%（统计窗口 30 天）。
3. 所有用户的自定义模板（基于日报 fork 的）已迁移到新 DSL。
4. 现有日报回归测试套件全部从"硬编码路径"改造为"DSL 路径"通过。

下线时把 `SOUL.md.legacy` 归档到 `docs/archive/`，保留 git 历史。

#### 11.4.4 fallback 触发场景

以下情况触发 fallback：

- `report_template_*` 工具因后端 bug 抛错。
- builtin 模板 `daily-equipment` 被意外删除/损坏。
- DSL validator 因新增校验规则把旧 builtin 模板判为非法。
- Skill `data-analyst` 被 disable，registry 中查不到 `query_daily` 等脚本。

每次 fallback 触发记录到 ReportRun.error_code = `FALLBACK_TRIGGERED`，便于监控和告警。

#### 11.4.5 用户感知

- 走 DSL 路径：用户看到完全相同的多轮表单和报告内容（DSL 必须复刻日报体验）。
- 走 fallback：用户看到一行不显眼的提示 "正在使用兼容模式生成报告"，行为与现有日报完全一致。
- 报告产物不应有差异（Markdown 格式、章节结构、字段一致）。

#### 11.4.6 fallback 适用范围

> **重要**：fallback 双轨策略**仅适用于 ai-report--daily**（以及未来从硬编码迁移过来的报告 agent，如周报/月报独立 SOUL.md）。

- **`ai-report--custom` 不存在 fallback**：custom agent 完全依赖 `report_template_*` 工具体系，没有可降级的硬编码流程。当 `report_template_*` 工具因后端 bug 或 skill 不可用时，custom agent 的 SOUL.md 必须返回明确的错误提示（"模板平台暂不可用，请稍后重试或联系管理员"），不尝试 fallback。
- **Phase 6 新增的报告 agent**（trend / diagnosis 等）若是从零开始构建（无硬编码前身），同样不需要 fallback。
- **从硬编码迁移而来的 agent**（如 ai-report--weekly、ai-report--monthly 若它们将来也走重写路径），按 §11.4.1-11.4.5 的 daily 模式各自配置 fallback。

判定原则：**fallback 是迁移过渡期的兜底机制，不是常态产品能力**。任何新建 agent 都应直接走 DSL 模板路径，不引入 fallback。

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

> **决策**：**Markdown 必需，PDF 可选降级**。延续现有 `export_report.py` 的 try/except ImportError 行为，不为 PDF 引入 chromium/puppeteer 等重依赖。

#### 12.2.1 export_report.py 演进路径

```text
skills/custom/data-analyst/scripts/export_report.py
  ├ render_markdown(payload, thread_id)        # MVP 已有，处理日报 payload
  ├ render_markdown_generic(payload)           # 新增，处理任意 report_payload.json schema
  ├ write_report(payload, fmt)                 # MVP 已有 .md/.pdf 双格式写入
  └ write_report_generic(payload, fmt)         # 新增，对应 generic renderer
```

新模板走 `*_generic` 路径，旧日报 fallback 走原路径，二者共存。

#### 12.2.2 输入与输出契约

| 项 | 要求 |
| ---- | ---- |
| 输入 | `report_payload.json`（schema 见 §12.1） |
| 输出目录 | `{run_output_dir}/exports/` |
| 文件名 | `report.md`、`report.pdf` |
| Markdown | **必需**，任何运行成功的 ReportRun 都必须有 .md |
| PDF | **可选**，weasyprint 不可用时跳过 |

#### 12.2.3 Markdown 必需路径

- 装配 `report_payload.json` 后，先调用 `render_markdown_generic` 写出 `.md`，**写入失败 = ReportRun 失败**。
- 渲染时按 sections 顺序输出：
  - `markdown` section → 直接拼接
  - `card` / `card_group` → 渲染为标题 + 键值列表或简单表格
  - `echart` → 调用 `trend_chart_to_svg()`（已有）转 SVG，嵌入 `![alt](data:image/svg+xml;base64,...)`
  - `table` → 渲染为标准 Markdown 表格
- 输出前做 HTML/XSS 清理（与现有 daily 路径相同）。

#### 12.2.4 PDF 可选降级路径

```python
md_path = write_report_generic(payload, "md")             # 必需
pdf_available = True
try:
    pdf_path = write_report_generic(payload, "pdf")
except ImportError:
    pdf_available = False                                  # weasyprint 未安装，跳过
except Exception as e:
    pdf_available = False
    log.warning("PDF 导出失败: %s", e)                     # 其它异常也降级
```

ReportRun 记录：

- `artifact_paths.md` = .md 路径（必填）
- `artifact_paths.pdf` = .pdf 路径或 `null`
- `pdf_skipped_reason` = "weasyprint_unavailable" / "render_error" / `null`

#### 12.2.5 ECharts 在 PDF 中的渲染

PDF 路径里 ECharts 不能依赖前端浏览器渲染。处理方案：

- weasyprint 不能直接渲染 JS，所以 PDF 里的图表必须是后端预渲染的 **SVG 或 PNG**。
- 走与 daily 路径相同的 `trend_chart_to_svg()` 后端 SVG 生成方案（已在 [export_report.py](../../skills/custom/data-analyst/scripts/export_report.py) 实现）。
- 复杂图表（pie、scatter、heatmap）若超出 SVG 渲染能力，PDF 中可降级为表格或概要文字，Markdown 路径仍展示 SVG。

#### 12.2.6 用户提示

- 报告底部显示下载链接：
  - `[下载 Markdown](url)` （永远可见）
  - `[下载 PDF](url)` 或 `PDF 不可用（weasyprint 未安装）`（条件可见）
- ReportRun 详情页同样按此规则显示。

### 12.3 历史查询

历史以 `ReportRun` 为索引，不依赖聊天消息反向解析。

MVP 中历史仍然依附于存活的 thread：删除 thread 后，对应 ReportRun 索引与产物一并删除；如需长期保留，用户需先导出 Markdown/PDF。

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

> **决策**：Builtin 预置模板存储在**仓库内** `agents/builtin/report-templates/`，随代码版本控制。详细目录结构和加载机制见 §7.1.1。

```text
agents/builtin/report-templates/
  daily-equipment/
    default.yaml
    metadata.yaml
    examples/
  weekly-equipment/...
  monthly-equipment/...
  # Phase 6 增量交付
  trend-equipment/...
  diagnosis-fault/...
  failure-analysis/...
  closure-summary/...
  inspection/...
```

预置模板包要求：

- 只包含 DSL（`default.yaml`）和 metadata（`metadata.yaml`），不包含可执行代码。
- 引用的脚本必须存在于 Script Registry（即对应 skill 的 `report_scripts.yaml`）。
- 每个模板必须有 `examples/sample_parameters.json` 和 `examples/sample_report_payload.json` 作为参考。
- 每个模板必须通过 validator 的 CI 测试。
- 普通用户不能修改 builtin 模板，只能通过 `report_template_fork` 复制为自己的模板再修改。
- Builtin 模板更新必须通过代码 PR + 应用重启加载；运行时 API 不可写 builtin 路径。

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
7. **能导出 Markdown（必需），PDF 可选降级**（PDF 在 weasyprint 不可用时跳过，不阻塞验收）。
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

> **说明**：本次立项承诺范围为 **Phase 0-5**；Phase 6-7 作为路线图，不纳入当前里程碑承诺。工程量按 **1 名后端主力 + 1 名前端阶段性投入** 估算（含设计 review、测试、文档、bug 修复缓冲）。Phase 之间存在依赖：必须按序执行，**Phase 0 不通过则后续作废**。

### Phase 0：技术尖刺与边界确认（0.5 人月，~1 周）

> **目标**：验证 6 个潜在 blocker，决定是否进入正式实施。任何一项未通过都触发设计回退或调整。

1. **render_ui 程序化推送验证**：实现一个最小 `report_template_render_step` 工具，能从工具内部把 GenUI block 推送到当前 thread 的 SSE 流，前端能正常接收并渲染。
2. **InteractionStore 当前实现对账**：核对现有 `(thread_id, callback_id)` 机制、`render_ui_tool`、Gateway 提交路由与前端交互链路，确认报告模板可以直接复用，不再把它作为待开发大项。
3. **JSONPath 子集解析器原型**：实现一个 ≤200 行的解析器原型，跑通 §5.6 白名单和黑名单测试用例。
4. **run-scoped 输出目录注入链路**：验证 runtime 在调用脚本时能正确创建 `{run_output_dir}` 并替换占位符；验证 artifact 路由能下载到该路径下文件。
5. **export_report.py generic 路径技术验证**：复制现有 `render_markdown` 改造为 `render_markdown_generic`，跑通最简单 sections 数组到 Markdown 的转换。
6. **AI 报告父子 agent 配置已完整就位**：确认 `ai-report` + 8 个子 agent 都已存在（见 [agent-template-selector-design.md](2026-05-13-agent-template-selector-design.md) 已实现状态）。

**Phase 0 验收**：以上 6 项全部通过，输出一份《Phase 0 技术尖刺报告》，确认或调整下游 Phase 的工作量估算。

### Phase 1：DSL + Registry + Validator + GenUI 回归补强（2 人月，~4 周）

1. **DSL Pydantic schema**（`schema.py`）：覆盖 `form_steps`、`fields`、`options_source`、`before_step`、`data_steps`、`transforms`、`sections`、`export`。
2. **JSONPath 子集解析器**（`source_resolver.py`）：基于 Phase 0 原型完成，覆盖完整的白名单语法和单元测试。
3. **DSL Validator**（`validator.py`）：
   - 静态校验：字段名唯一、`next` 引用存在、`options_source.step` 已声明、`source` 路径合法
   - 引用校验：脚本 namespace 存在于 registry，args 通过 args_schema
   - 类型校验：`sections[].component` 与 `source` 输出类型匹配
4. **Script Registry**（`script_registry.py`）：
   - 定义 `report_scripts.yaml` 加载逻辑
   - 实现 `data-analyst` skill 的 `report_scripts.yaml`，覆盖 `list_equipment`、`query_daily`、`daily_kpi`
5. **GenUI 回归补强**：围绕现有 `(thread_id, callback_id)` 机制补齐报告模板接入所需测试与约束；若发现新流程绕开现有 helper，仅修正接入点，不重启底层改造。
6. **回归测试**：现有 `ai-report--daily` 硬编码流程在改造后行为不变。

**Phase 1 验收**：所有单元测试通过；DSL 示例（§5.2 重点机泵日报）通过 validator；现有日报回归测试通过；报告模板相关 GenUI 回归通过；新增覆盖率 ≥ 80%。

### Phase 2：模板存储与权限（1.5 人月，~3 周）

1. **Repository 抽象**（`repository.py`）：定义 `ReportTemplateRepository` interface，MVP 实现为 `FileSystemReportTemplateRepository`。
2. **文件存储**：按 §7.1.1 的目录结构实现，含 atomic write、etag 乐观锁、fcntl 文件锁、index.json 维护。
3. **模板 metadata/version 模型**：实现 `ReportTemplate`、`ReportTemplateVersion`、`ReportRun` 的 Pydantic 模型。
4. **权限矩阵校验**：在 Gateway 路由层实现 §11.1 矩阵，复用 `superadmin` / `tenant_admin` 角色。
5. **模板生命周期**：`save_draft`、`publish`（强制版本迭代）、`fork`、`archive`、`delete`。

**Phase 2 验收**：模板可创建/编辑/发布/fork/archive/delete；权限矩阵单元测试覆盖；并发写入不丢数据；fork 后版本绑定正确。

### Phase 3：受控工具 + ai-report--custom SOUL.md（1 人月，~2 周）

1. **先交付模板生命周期工具**（详见 §8.2）：
   - 模板生命周期（6 个）：`list / get / validate / save_draft / publish / fork`
   - 运行时工具名在接口层保留设计，但实现放到 Phase 4 交付
   生命周期工具是**薄壳**（≤50 行），核心逻辑委托 repository / validator 模块。
2. **改造 ai-report--custom SOUL.md**：完整的工具调用流程、错误处理指引、状态恢复说明。
3. **禁止 LLM 直接 bash 写模板**：通过 `BUILTIN_TOOLS` 而非允许 bash 实现，从工具列表层面隔离。
4. **创建模板向导**：通过 GenUI 多步表单（创建方式 → 基本信息 → 参数流程 → 数据步骤 → 章节 → 预览）完成。

**Phase 3 验收**：用户能通过 ai-report--custom 创建一个 private 模板草稿并发布；所有模板生命周期操作都通过结构化工具完成；无 bash 模板写入。

### Phase 4：运行时 MVP + daily 重写为 DSL 模板（2.5 人月，~5 周）

1. **Runtime 各模块**：`state.py`（status.json 状态机）、`step_renderer.py`、`step_submitter.py`、`data_runner.py`、`payload_builder.py`、`report_renderer.py`、`exporter.py`。
2. **交付 8 个运行时工具**：`prepare_run / render_step / submit_step / run_data_steps / assemble_payload / render_report / export / resume_run`，作为 Phase 3 预留接口的正式实现。
3. **报告章节渲染**：sections → GenUI blocks 转换（markdown / card / card_group / echart / table）。
4. **Markdown/PDF 导出**：扩展 `export_report.py` 增加 generic 路径，PDF 可选降级。
5. **builtin 模板：daily-equipment**：完整 DSL 复刻现有日报流程，通过 validator，能跑通最少一个 ReportRun。
6. **ai-report--daily 双轨**：SOUL.md 增加 DSL 路径优先 + fallback 兜底（按 §11.4）。
7. **回归测试**：旧日报硬编码路径与新 DSL 路径的产物对比测试，章节字段一致。

**Phase 4 验收**：用户从 ai-report--daily 入口生成的报告与 ai-report--custom 运行 daily-equipment 模板的报告完全一致；fallback 触发率 < 1%。

### Phase 5：历史与管理 UI（2 人月，~4 周）

1. **报告历史**：嵌入现有对话历史列表，按 ReportRun 索引。新增侧边栏二级 tab 或列表过滤器（"对话"/"报告"），不新建独立全局入口。
2. **历史详情页**：读取 `report_payload.json` + `template_version.json` + artifact，复用 GenUI renderer 渲染。
3. **artifact 重下载**：复用现有 artifact 路由。
4. **模板管理 UI**：列表（按 visibility 分组）、详情、编辑器（YAML 编辑 + DSL 校验提示）、版本对比、fork 按钮。
5. **租户共享模板管理**：tenant_admin 可发布 tenant 模板，普通成员可查看/运行/fork。
6. **builtin 模板：weekly + monthly**：交付 `weekly-equipment`、`monthly-equipment` builtin 模板。

**Phase 5 验收**：所有历史 UI / 模板管理 UI 在 desktop / responsive 下正常；权限矩阵在 UI 中正确反映；新建 weekly/monthly 模板能跑通运行。

### Phase 6：扩展剩余 5 种报告类型（路线图，不纳入当前里程碑承诺）（4 人月，~8 周）

1. **趋势分析**（P2）：交付 `trend-equipment` builtin 模板 + `data-analyst` skill 新增 `query_trend`、`trend_analysis` 脚本。
2. **诊断报告**（P2）：交付 `diagnosis-fault` builtin 模板 + `query_fault_context`、`build_fault_timeline`、`diagnosis_analysis` 脚本。
3. **失效分析**（P3）：交付 `failure-analysis` builtin 模板 + 配套脚本。
4. **闭环报告**（P3）：交付 `closure-summary` builtin 模板 + 配套脚本。
5. **巡检报告**（P3）：交付 `inspection` builtin 模板 + 配套脚本。
6. **每种报告必须满足 §13.14 验收标准**：未满足不发布，不进入下一类。
7. **通用分析报告（V2）**：本 Phase **不交付**，须先完成 connector/dataset registry、数据源权限、查询限制、schema discovery、provenance 输出和安全测试，才能作为 V2 立项启动。

**Phase 6 验收**：5 种 builtin 模板都通过 §13.14 全部 11 项验收；7 种报告类型（含日报、周报、月报）都至少有 1 个成功 ReportRun 样例。

### Phase 7：监控、告警与运维（独立小立项，路线图）（0.5 人月）

1. ReportRun 运行成功率、错误码分布的 Prometheus 指标。
2. fallback 触发率告警（连续 N 次或日累计超过阈值）。
3. 模板版本爆炸告警（单模板版本数 > 100）。
4. 文件存储用量告警（用户/租户目录超阈值）。
5. 文档：在 `docs/` 下补充用户手册和管理员手册。

### 总工程量与时间窗

**当前立项承诺（Phase 0-5）**

| 阶段 | 人月 | 关键路径周数（按 1 名后端主力 + 1 名前端阶段性投入） |
| ---- | ---- | ---- |
| Phase 0 | 0.5 | 1 周 |
| Phase 1 | 2 | 4 周 |
| Phase 2 | 1.5 | 3 周 |
| Phase 3 | 1 | 2 周 |
| Phase 4 | 2.5 | 5 周 |
| Phase 5 | 2 | 4 周 |
| **小计** | **9.5 人月** | **约 19 周（约 4.5-5 个月）** |

**后续路线图（不纳入当前承诺）**

| 阶段 | 人月 | 关键路径周数 |
| ---- | ---- | ---- |
| Phase 6 | 4 | 8 周 |
| Phase 7 | 0.5 | 1 周 |
| **小计** | **4.5 人月** | **约 9 周** |

> **关键路径**：Phase 0 → 1 → 2 → 3 → 4 是 MVP 关键路径（约 7.5 人月，15 周）。Phase 5 可与 Phase 4 末尾并行启动（前端独立工作）。Phase 6-7 仅在 Phase 5 验收后另行立项。

---

## 16. 风险与应对

### 16.1 已识别风险表

| 风险 | 影响 | 应对 | 严重度 |
| ------ | ------ | ------ | ------ |
| 绕开现有 thread/run | 失去 GenUI、artifact、取消、权限能力 | MVP 运行绑定现有 thread/run | 中 |
| 模板存储放错位置 | 模板跨会话不可控，权限混乱 | 使用 DeerFlow home 用户/租户目录，V2 迁 DB | 中 |
| DSL 无法描述动态日报流程 | MVP 无法复刻现有日报体验 | DSL v1 支持 `form_steps` 和 `options_source`；Phase 4 复刻 daily 验证 | 高 |
| **render_ui 程序化推送路径不存在** | Phase 4 直接卡住 | Phase 0 技术尖刺第 1 项强制验证；不通过则方案回退到 LLM 调用 render_ui | **高** |
| **报告模板接入绕开现有 InteractionStore / render_ui 链路** | 新流程与现有 GenUI 机制分叉，造成回归或维护成本上升 | Phase 0 第 2 项完成代码对账；Phase 1 只补接入测试与约束，不重复做底层改造 | **中** |
| **JSONPath 表达式解析器实现复杂度被低估** | 安全或表达力不足 | Phase 0 第 3 项原型验证；自实现，禁用第三方库 | 中 |
| 固定 callback_id 冲突 | 跨用户/线程误提交 | 复用现有 `(thread_id, callback_id)` 复合 key，并在新模板流程上补回归测试 | 低 |
| 脚本任意执行 | 命令注入、数据泄漏 | registry allowlist + 参数数组执行 + schema 双重校验 | 高 |
| 固定输出文件覆盖 | 并发运行互相污染 | run-scoped 输出目录；不同 ReportRun 完全隔离 | 中 |
| 租户权限不清 | 共享模板或历史报告泄漏 | 完整权限矩阵 + route-level authz | 高 |
| PDF 图表缺失 | 导出不可用 | PDF 可选降级；Markdown 必需 | 低 |
| DSL 过度复杂 | 难实现、难维护 | v1 只支持多步表单、allowlist steps、sections、export | 中 |
| **现有日报 fallback 长期保留导致维护双轨** | 代码膨胀，行为差异 | §11.4.3 明确下线条件（30 天 0 fallback + 99% 成功率） | 中 |
| **PostgreSQL vs 文件存储未决** | Phase 2 反复返工 | 决策已定：MVP 文件存储，V2 迁 DB；MVP 文件 schema 预先对齐 DB schema | 低 |
| **Phase 6 单种报告脚本工作量被低估** | 后续扩展延期，拖累平台口碑 | Phase 6 改为路线图；每种报告独立立项、独立验收，不占用当前 MVP 承诺 | 中 |
| **用户已有日报记录 UX 断层** | 历史报告在新 UI 里找不到 | Phase 5 的历史 UI 同时支持旧硬编码路径产物（按 thread 索引）和新 ReportRun 路径产物 | 中 |
| **thread 删除后历史不可保留** | 用户误删 thread 后无法继续在线查看报告 | MVP 明确 thread 是生命周期根；删除前提供导出提示；V2 再评估脱离 thread 的长期归档能力 | 中 |
| **LLM 误调用工具顺序** | 流程乱序、状态错乱 | §3.4 中所有工具校验 `report_run_id` + `expected_step`，不一致直接报错并提示 LLM 正确顺序 | 中 |
| **Skill disable 后引用它的模板失效** | 已发布模板突然不可运行 | Validator 在运行前检查 skill 状态；失效时返回清晰的"前置 skill 不可用"错误，不静默失败 | 中 |
| **YAML 注释在版本化时丢失** | 用户编辑历史不完整 | 版本快照同时保存 `dsl`（解析后 JSON）和 `dsl_yaml`（原始文本） | 低 |
| **builtin 模板因新增 validator 规则被判非法** | 业务被动停摆 | 所有新增 validator 规则必须先在 builtin 上测试通过；CI 加 builtin 模板 validator 校验 | 中 |
| **callback 约束理解不一致** | 新增模板步骤使用了不可追踪或冲突的 callback_id，排障困难 | §10.3.4 明确命名规范；PR review 必须检查 callback_id 可读性 | 低 |
| **LLM 在长流程中超出上下文窗口** | Phase 4 的多步表单 + 多脚本执行 + 多次 GenUI 推送可能让单 thread 上下文超长 | 工具返回值精简化（不回流脚本完整输出，仅回流 ReportRun ID + 摘要 + 下一步指引）；超长时由 SOUL.md 引导用户开新会话调用 `report_template_resume_run` 续跑；纳入 SummarizationMiddleware 触发条件 | 中 |
| **ai-report--custom 无 fallback 时的可用性** | 后端故障期间 custom agent 完全不可用 | §11.4.6 决策不引入 custom fallback；通过 §16.3 触发回退条件监控 + 工具内部充分错误处理保证错误信息明确，不静默卡死 | 中 |

### 16.2 风险监控指标

部署后必须监控（属于 Phase 7 工作）：

- ReportRun 失败率（按 error_code 分类）
- fallback 触发率（按天聚合）
- DSL validator 失败率（按 error_code 分类）
- 模板版本数分布（识别版本爆炸）
- 文件存储空间使用率（按 user/tenant）
- Skill 不可用导致的运行失败次数

### 16.3 触发回退条件

任一条件触发时：

- 对具备 fallback 的 agent（当前仅 `ai-report--daily`）立即切回 fallback 路径并告警。
- 对 `ai-report--custom` 这类无 fallback 的入口，立即返回明确错误并告警，不做静默降级。

- 单 thread 内连续 3 次 ReportRun 失败
- 全平台 ReportRun 5 分钟成功率 < 80%
- DSL validator 报错率 > 50%（疑似 builtin 模板被 validator 误判）
- GenUI 交互提交失败率 > 5%（疑似报告模板接入链路 bug）

---

## 17. 验收标准

### 17.1 Phase 0 验收

1. render_ui 程序化推送 demo 跑通：从工具内部注入 GenUI block 到 SSE 流，前端正常渲染。
2. InteractionStore / render_ui / ui-interaction 当前实现对账完成，确认报告模板接入边界。
3. JSONPath 子集解析器原型通过白/黑名单测试用例。
4. run-scoped 输出目录 + artifact 下载链路验证通过。
5. `render_markdown_generic` 最小 demo 跑通。
6. AI 报告父子 agent 配置完整，所有 8 个子 agent 目录就位。

### 17.2 MVP 验收（Phase 0-4 完成）

1. 用户能从"自定义模板"入口创建基于日报的模板草稿，并发布为 v1。
2. 模板 DSL 支持 `form_steps`、`options_source`、`data_steps`、`transforms`、`sections`、`export`。
3. 模板保存前经过后端 validator 校验，非法模板返回结构化错误（含 code、path、message）。
4. 模板存储在 `{DEER_FLOW_HOME}/report-templates/`，符合 §7.1 文件结构和并发控制要求。
5. 用户运行模板时仍在现有 agent thread 内完成，**不新增独立 runner 进程**。
6. 动态流程能复刻日报：范围选择 → 设备选择 → KPI 选择 → 报告生成。
7. 复用现有 `(thread_id, callback_id)` 复合 key 机制，跨 thread 不冲突，且报告模板接入无回归。
8. 脚本只能从 skill 提供的 registry allowlist 执行，使用参数数组方式调用，无 shell 注入风险。
9. 每次运行使用独立 `report-runs/{report_run_id}/` 输出目录，不覆盖其它运行。
10. 生成 `report_payload.json`、Markdown artifact（必需）和 ReportRun 索引；PDF 在 weasyprint 不可用时优雅降级。
11. 非法脚本、非法参数、非法 source、越权模板访问都会被拒绝并返回结构化错误。
12. 完整权限矩阵：private / tenant / builtin 三级可见性按 §11.1 工作；复用 `superadmin` / `tenant_admin` 角色。
13. 强制版本迭代：published 模板编辑生成新草稿/版本，不能原地覆盖。
14. JSONPath 子集解析器禁用所有黑名单语法，深度限制 ≤ 8 层。
15. **现有日报 ai-report--daily 走 DSL 路径优先 + SOUL.md fallback 兜底**，DSL 路径产物与旧路径完全一致。
16. Builtin 模板 daily-equipment 通过 §13.14 全部 11 项验收标准。
17. 现有日报、周报等 agent 的 GenUI 表单回归测试全部通过（报告模板接入无回归）。

### 17.3 Phase 5 验收

1. 报告历史嵌入现有对话历史，按 ReportRun 索引展示。
2. 历史详情页能读取 `report_payload.json` 重新渲染报告。
3. 模板管理 UI 提供列表、详情、YAML 编辑器、版本对比、fork。
4. tenant_admin 能发布 tenant 模板，普通成员能查看/运行/fork。
5. Builtin 模板 weekly-equipment、monthly-equipment 通过 §13.14 验收。
6. 所有 UI 在 desktop / responsive 下表现正常。

### 17.4 Phase 6 验收（后续增量，不纳入当前里程碑承诺）

1. 5 种新 builtin 模板（trend / diagnosis / failure-analysis / closure / inspection）全部通过 §13.14 全部 11 项标准。
2. 解释性报告（trend / diagnosis / failure-analysis）输出包含 evidence、confidence、data_coverage、human_review_required 字段。
3. 通用分析报告（generic）**未交付**，列入 V2 立项。

### 17.5 全局非功能验收

1. 整体单元测试覆盖率 ≥ 80%。
2. `make test` 后端测试全通过，无新增 flaky 测试。
3. 前端 `pnpm check` 通过，无 TypeScript 或 ESLint 错误。
4. `tests/test_harness_boundary.py` 通过：`harness/deerflow/report_templates/` 不依赖 `app.*`。
5. 所有面向用户的错误信息都已脱敏（不暴露文件路径、堆栈、内部 ID）。
6. 文档更新：[backend/CLAUDE.md](../../backend/CLAUDE.md) 增加 report-templates 章节；[frontend/CLAUDE.md](../../frontend/CLAUDE.md) 增加报告历史 UI 说明。

---

## 18. 推荐结论

自定义模板功能应该被设计为 AI 报告体系中的"模板平台能力"，而不是一个自由对话式报告助手。修订后的推荐路线是：

1. 入口继续使用 `ai-report--custom`。
2. 创建和编辑由 SOUL + GenUI 引导，Phase 5 提供独立模板管理 UI。
3. 保存、校验、运行由后端确定性服务和受控工具完成。
4. MVP 运行继续绑定现有 thread/run，不新建独立执行引擎。
5. **MVP 模板存储使用 DeerFlow home 用户/租户目录 + 仓库内 builtin 模板，V2 迁移至 PostgreSQL**。
6. 报告产物使用 run-scoped output 并复用 artifact 下载；**Markdown 必需，PDF 可选降级**。
7. DSL v1 必须支持动态多步表单，才能复用日报的核心体验。
8. **现有日报重写为 DSL 模板，旧 SOUL.md 保留作为 fallback**，下线条件见 §11.4.3。
9. **复用现有 `(thread_id, callback_id)` 复合 key 实现**，把重点放在报告模板接入回归，而不是重复发起底层改造。
10. **Script Registry 由 skill 插件贡献**，与现有 skill 架构同构。

当前最稳妥的执行方式是：先完成 **Phase 0-4 的 MVP（含 daily）**，再以 **Phase 5 的管理 UI + weekly/monthly** 作为下一里程碑。剩余 5 种报告类型保留在路线图中，待平台能力与 daily 路径稳定后逐个立项推进。

按这个路线实现，可以最大化复用 DeerFlow 当前 Agent / SOUL / GenUI / Skill / artifact 架构，同时避免安全、权限、并发和可追溯性风险。
