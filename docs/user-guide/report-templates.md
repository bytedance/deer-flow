# 报告模板平台 — 用户手册

> 适合人群：希望创建/复用/分享业务报告模板的最终用户、领域专家、业务分析师。
> 阅读时长：15–25 分钟（含动手练习）。
> 配套设计文档：[2026-05-14-ai-report-custom-template-design.md](../plans/2026-05-14-ai-report-custom-template-design.md)。

---

## 1. 你能用它做什么

报告模板平台让你**用 YAML 描述一份报告**，平台会：

1. 把 YAML 翻译成多步参数表单（你看到的是表单，不是 YAML）。
2. 调用受控的 Skill 脚本拉数据、做聚合。
3. 把结果按"章节"渲染成 GenUI 报告（带卡片、ECharts、表格、Markdown）。
4. 导出 Markdown（必有）和 PDF（可选）。

**典型场景**：每天/周/月的设备运行报告、故障诊断报告、巡检汇总、闭环复核——任何"先填几个参数→出一份固定结构的报告"的需求。

**不适合**：临时性、一次性、需要自由对话的探索分析（去用 `ai-report--custom` 直接对话即可）。

---

## 2. 五分钟跑通第一份报告

不需要创建模板，先跑一份现成的 builtin：

1. 打开 DeerFlow Web 界面，进入"AI 报告"智能体。
2. 选子智能体 **"日报"**（`ai-report--daily`）。
3. 它会自动调用 `daily-equipment` builtin 模板，按顺序弹出三轮表单：
   - **范围**：日期、设备类型、对比基准
   - **设备**：勾选要纳入报告的设备（动态拉取）
   - **KPI**：勾选要关注的指标（动态拉取）
4. 提交后等几秒，看到完整报告 + "下载 Markdown" 按钮（PDF 可能不可用，取决于后端是否装了 weasyprint）。

**记住这条路径**：所有 builtin / fork 后的模板都走完全一样的"多步表单 → 报告 → 下载"流程。

---

## 3. 从 fork builtin 开始

直接从空白写 DSL 是 hard mode。推荐先 fork 一份能跑的 builtin。

### 3.1 看看有哪些 builtin

在 `ai-report--custom` 智能体里说："列出所有 builtin 模板"。

它会调用 `report_template_list(visibility="builtin")`，返回当前 8 个 builtin：

| 模板 ID | 用途 |
|---|---|
| `builtin-daily-equipment` | 设备日报 |
| `builtin-weekly-equipment` | 设备周报 |
| `builtin-monthly-equipment` | 设备月报（含 MTBF/MTTR/环比/同比）|
| `builtin-trend-equipment` | 趋势分析（解释性报告，带证据链） |
| `builtin-diagnosis-fault` | 故障诊断（解释性报告） |
| `builtin-failure-analysis` | 失效分析（5Why/鱼骨图/FMEA） |
| `builtin-closure-summary` | 问题闭环报告 |
| `builtin-inspection` | 巡检报告 |

### 3.2 fork 一份

接着说："把 `builtin-daily-equipment` fork 成我的，叫'机泵 A 区日报'"。

agent 会：

```text
report_template_fork(
  source_template_id="builtin-daily-equipment",
  source_version=1,
  new_name="pump-area-a-daily",
  new_display_name="机泵 A 区日报",
)
```

返回新的 `template_id`（形如 `tpl_01H...`），状态是 **draft v0**，归属 `visibility=private`、`owner_user_id=你`。

### 3.3 修改

让 agent 把 YAML 打印出来给你看，你可以让它改：

- "把'设备类型'的默认值改成 pump"
- "去掉'告警事件'章节"
- "把对比基准的'去年同期'选项去掉，只保留'前一日'和'上周同日'"

每一次修改 agent 都会先 `report_template_validate(dsl)`，**校验通过才 `save_draft`**——验证失败它会告诉你错在哪、什么 error code，你不用看后端日志。

### 3.4 发布

满意了让 agent："发布这个模板"：

```text
report_template_publish(template_id="tpl_xxx", expected_current_version=0)
```

成功后状态变成 **v1**，**不可再修改**。下次想改要么先 fork、要么基于 v1 创建新的 draft（v0 工作副本会被覆盖、v1 永远保留）。

---

## 4. DSL 入门（看懂 fork 出来的 YAML）

DSL 文档分 5 大块：

```yaml
dsl_version: "1"           # 锁定 schema 版本，不要改
name: pump-area-a-daily    # 内部 id，不展示给用户
display_name: "机泵 A 区日报"  # 用户看到的标题
description: "..."
visibility: private        # private / tenant / builtin

form_steps:                # ← 第 1 块：多步表单
  - id: scope
    title: 生成日报
    fields: [...]
    next: equipment        # 下一步的 form_step id；最后一步写 "generate"

data_steps:                # ← 第 2 块：拉数据
  - id: daily_data
    kind: script
    name: daily-report/query_daily
    args:
      date: "{{ $.form.scope.report_date }}"   # ← JSONPath 占位符
    outputs:
      daily_data: daily_data.json

transforms:                # ← 第 3 块:转换/聚合
  - id: daily_kpi
    kind: script
    name: daily-report/daily_kpi
    input: daily_data.daily_data
    outputs:
      daily_kpi: daily_kpi.json

sections:                  # ← 第 4 块:报告章节
  - id: kpi_cards
    title: 核心 KPI
    component: card_group
    source: $.steps.daily_kpi.daily_kpi.kpi_summary

export:                    # ← 第 5 块:导出
  formats: [md, pdf]
  renderer: generic_report
```

### 4.1 form_steps — 你的多步表单

每个 step 有 `id`/`title`/`fields`/`next`：

```yaml
- id: scope                # 内部 id；JSONPath 引用为 $.form.scope.<字段>
  title: 选择参数
  description: "请填写日期和设备类型"
  fields:
    - { name: report_date, label: 日报日期, type: date, required: true }
    - { name: equipment_type, label: 设备类型, type: select, required: true,
        options: [{label: 全部, value: all}, {label: 机泵, value: pump}] }
  next: equipment          # 跳到下一个 form_step；最后一步写 "generate"
```

**支持的 field type**：`text` / `textarea` / `number` / `date` / `select` / `multi-select` / `checkbox`。

**动态选项**——`before_step` + `options_source`：

```yaml
- id: equipment
  before_step:                          # 进入这步前先跑一个脚本
    id: equipment_catalog
    kind: script
    name: daily-report/list_equipment
    args:
      type: "{{ $.form.scope.equipment_type }}"   # 引用上一步的字段
  fields:
    - name: equipment_ids
      type: multi-select
      options_source:                   # 选项来自 before_step 的输出
        step: equipment_catalog
        path: equipment                 # JSON 中的字段名
        label: id
        value: id
        group: area                     # 可选:按区域分组
```

### 4.2 JSONPath 占位符（很重要）

DSL 里所有 `"{{ ... }}"` 都是 JSONPath 子集。**只支持 6 种语法**：

| 写法 | 含义 |
|---|---|
| `$.form.<step_id>.<字段>` | 引用某 form_step 的提交值 |
| `$.steps.<step_id>.<output_id>` | 引用某 data_step / transform 的输出 JSON |
| `$.steps.<step_id>.<output_id>.<key>` | 进一步访问输出中的字段 |
| `$.steps.<step_id>.<output_id>[*].<key>` | 数组每个元素的某字段（用于 options_source） |
| `$.run.report_run_id` / `$.run.thread_id` / `$.run.generated_at` | 运行时元数据 |
| `$.template.id` / `$.template.version` / `$.template.name` | 模板元数据 |

**写错最常见的 5 种情况**：

| 错误 | 原因 | 怎么改 |
|---|---|---|
| `"{{ $.form.scope[?(@.x>0)] }}"` | 用了过滤器（黑名单） | 把过滤搬到脚本里 |
| `"{{ $.steps..summary }}"` | 用了递归下降 `..`（黑名单） | 写完整路径 `$.steps.daily_kpi.daily_kpi.summary` |
| `"{{ $.steps.foo.bar.length() }}"` | 用了函数调用（黑名单） | 让脚本输出 `count` 字段，模板直接读 |
| `"{{ $.steps.foo.bar[0] }}"` | 索引访问（只允许 `[*]`） | 让脚本直接输出第一个元素，或全部 |
| `"{{ form.scope.x }}"` | 漏了 `$.` 前缀 | 加上 `$.`；validator 会自动补，但显式写更清楚 |

### 4.3 sections — 章节渲染

每个 section 选一个 `component` 然后给 `source`：

| component | source 应该返回什么 |
|---|---|
| `markdown` | 字符串或字符串数组 |
| `card` | 对象（带 title/value 或 summary 字段） |
| `card_group` | 对象数组 |
| `echart` | 一个完整的 ECharts option 对象 |
| `table` | 对象数组，或 `{columns, data}` 结构 |

**Validator 会提示但不阻止**：如果你的 `source` 路径看起来不像目标 component 期望的形状（例如 `echart` 指向了一个名字像 `summary` 的字段），保存时会有一条 warning，但模板照样能跑。

---

## 5. 解释性报告（趋势/诊断/失效）

如果你在做"分析 → 给结论"类的报告，**必须**遵守设计 §13.2 的证据链规范：

每个 finding 至少要带：

- `evidence[]`：至少 1 条证据，每条带 `source_type`/`source_id`/`snapshot_path`/`checksum`/`time_range`/`retrieved_at`。
- `confidence`：`low` / `medium` / `high`。
- `human_review_required`：诊断/失效/根因结论默认 `true`，提示用户结论需要人工确认。

`builtin-trend-equipment` / `builtin-diagnosis-fault` / `builtin-failure-analysis` 都是模板范本，章节里专门有 "证据链"、"人工复核提示" 这两节，**不要删掉**——平台把这两节当作 §13.2 合规的标志。

---

## 6. 发布与共享

| 状态 | 谁能看 | 谁能编辑 |
|---|---|---|
| `private` (默认) | 只有你 | 只有你 |
| `tenant` | 同租户成员都能看/运行/fork | 只有 `tenant_admin` 能编辑/发布 |
| `builtin` | 所有人 | 只有平台管理员（`superadmin`），且必须通过代码 PR |

**升级 visibility** 需要满足目标层级的写权限：

- `private → tenant`：需要你是 `tenant_admin`。
- `tenant → builtin`：需要 `superadmin`（实际上你做不到，要管理员从仓库提 PR）。

**版本管理**：

- v0 = 工作草稿，可覆写。
- v1, v2, ... = 不可变发布版本。
- ReportRun 永远绑定具体 `(template_id, version)`，可以重现。
- 编辑已发布模板 → fork 出新 draft → 改 → 发布 v(N+1)；老版本继续可运行。

---

## 7. 常见错误码对照

运行中看到结构化错误时，按 error_code 找：

| Code | 含义 | 怎么办 |
|---|---|---|
| `SCHEMA_INVALID` | DSL 不符合 schema（字段拼写、类型）| 看错误的 `path`，按 5.x 节修字段 |
| `UNKNOWN_SCRIPT` | data_step 引用了未注册的脚本 | 检查 skill 是否启用、script_name 是否对（`{skill}/{script}`）|
| `OPTIONS_SOURCE_REF` | options_source 指向了不存在 / 尚未执行的 step | 确认 before_step.id 拼写、顺序在前 |
| `JSONPATH_INVALID` | 用了黑名单语法 | 参考 §4.2 的"5 种常见错误" |
| `PATH_NOT_FOUND` | 运行时 JSONPath 求值失败 | 检查脚本是否真的产出了该字段 |
| `SECTION_TYPE_HINT_MISMATCH` | warning，章节类型与 source 形状不匹配 | 不阻断，但建议改名/换 component |
| `SCRIPT_TIMEOUT` | 脚本超时（默认 60–180s） | 让管理员调 `report_scripts.yaml` 的 `timeout_seconds` |
| `INPUT_UNREADABLE` | transform 读不到上游输出 | 检查 transform.input 路径 |
| `RUN_NOT_FOUND` | 运行被取消或会话清理了 | 重新触发即可 |
| `STATE_MISMATCH` | 工具调用顺序乱了（极少见，LLM 漂移） | 让 agent 重跑 `report_template_resume_run` |
| `INVALID_SEVERITY` 等业务码 | 脚本侧参数校验失败 | 看脚本错误描述，调整表单输入 |
| `PUBLISHED_IMMUTABLE` | 试图直接改已发布版本 | 用 fork 或基于当前版本创建新 draft |

---

## 8. 历史与导出

- **侧边栏 → "报告历史"**：看你所有 ReportRun（按 thread 维度归属）。
- **点开任意 ReportRun**：重新渲染报告（基于 `report_payload.json`），并提供 `.md` / `.pdf` 下载。
- **删除 thread 会一起删掉报告产物**——重要报告**先下载 Markdown/PDF 再删 thread**。

---

## 9. 何时该写一份新模板

适合写自定义模板（fork 不够）：

- 你的报告参数体系（form_steps）和现有 builtin 完全不一样。
- 你需要新增章节、调整 KPI 选择口径、合并/拆分对比维度。
- 你团队有自己一套约定术语、章节顺序、风格。

不适合自己写模板，应当请管理员升级 builtin：

- 改动会影响整个团队/租户使用习惯。
- 涉及新的脚本（要先在 Skill 的 `report_scripts.yaml` 注册）。
- 涉及解释性报告的 §13.2 证据链 schema。

---

## 10. 寻求帮助

- 报告自定义模板平台底层细节：[2026-05-14-ai-report-custom-template-design.md](../plans/2026-05-14-ai-report-custom-template-design.md)
- 找不到的 error code、奇怪的行为：在 `ai-report--custom` 里直接问 agent，它能调 `report_template_validate` 给出结构化诊断。
- 管理员相关问题（共享、回滚、版本回收）：[管理员手册](../admin-guide/report-templates.md)。
