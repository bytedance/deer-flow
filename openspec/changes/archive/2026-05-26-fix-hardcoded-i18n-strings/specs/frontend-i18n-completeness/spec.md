## ADDED Requirements

### Requirement: Report template page strings shall use i18n

The report templates list page (`report-templates-page.tsx`) SHALL replace all hardcoded Chinese strings with `t.xxx` references from the `useI18n()` hook.

Hardcoded strings to replace:
- Visibility filter labels: "我的模板", "租户共享", "预置模板"
- Status labels: "草稿", "已发布", "已归档"
- Page title: "报告模板"
- Page description: "管理自定义报告模板、版本和发布状态。"
- Navigation: "模板市场"
- Actions: "创建模板"
- Loading states: "加载中…", "加载失败"
- Empty states: "你还没有自定义模板。点击右上角「创建模板」开始。", "暂无模板。"
- Meta: "更新于"

#### Scenario: User views report templates page in Chinese
- **WHEN** the user's locale is `zh-CN` and navigates to `/workspace/report-templates`
- **THEN** all page labels, status badges, and empty state messages SHALL display in Chinese

#### Scenario: User views report templates page in English
- **WHEN** the user's locale is `en-US` and navigates to `/workspace/report-templates`
- **THEN** all page labels, status badges, and empty state messages SHALL display in English (e.g., "My Templates", "Tenant Shared", "Built-in", "Draft", "Published", "Archived", "Report Templates", "Create Template", "Template Marketplace")

### Requirement: Report runs page strings shall use i18n

The report runs history page (`report-runs-page.tsx`) SHALL replace all hardcoded Chinese strings with `t.xxx` references.

Hardcoded strings to replace:
- Status labels: "等待中", "运行中", "成功", "失败", "已取消"
- Loading states: "加载中…", "加载失败"
- Empty states: "暂无报告运行记录。先在子智能体或自定义模板中跑一次报告。", "暂无报告对话"
- Table headers: "运行 ID", "模板", "版本", "状态", "创建时间", "参数摘要", "来源对话"
- Page title: "报告历史"
- Page description: "查看已生成的报告运行记录及其对应的对话。"
- Tab labels: "运行记录", "对话"

#### Scenario: User views report runs page in English
- **WHEN** the user's locale is `en-US` and navigates to `/workspace/report-runs`
- **THEN** all table headers, status badges, tab labels, and empty state messages SHALL display in English

#### Scenario: User views report runs page in Chinese
- **WHEN** the user's locale is `zh-CN` and navigates to `/workspace/report-runs`
- **THEN** all text SHALL display in Chinese as currently shown

### Requirement: Report run detail page strings shall use i18n

The report run detail page (`report-run-detail-page.tsx`) SHALL replace all hardcoded Chinese strings with `t.xxx` references.

Hardcoded strings to replace:
- Title prefix: "[报告]"
- Action labels: "创建整改单", "关联整改单"

#### Scenario: User views report run detail in English
- **WHEN** the user's locale is `en-US` and views a report run detail
- **THEN** the title prefix SHALL be "[Report]", action labels SHALL be "Create Ticket" and "Link Ticket"

#### Scenario: User views report run detail in Chinese
- **WHEN** the user's locale is `zh-CN` and views a report run detail
- **THEN** the text SHALL display in Chinese as currently shown

### Requirement: Device selector GenUI blocks shall use i18n

The device selector GenUI blocks (`DeviceSelectorBlock.tsx`, `DeviceSelectorMultiBlock.tsx`, `SubDeviceSelectorBlock.tsx`) SHALL replace all hardcoded Chinese strings with `t.xxx` references.

Hardcoded strings to replace:
- Device type labels: "旋转机组" (type 1), "机泵" (type 4), "静设备" (type 6), "往复机组" (type 9)
- ARIA labels: "设备选择器", "设备多选选择器", "子设备选择器"
- Loading states: "加载组织树中...", "加载子设备中..."
- Error states: "加载失败"
- Actions: "重试"
- Prompts: "请选择组织节点", "该组织节点下无设备", "该设备下无子设备"
- Multi-select: "全选", "已选", "确认选择", "提交中..."
- Sub-device: "子设备列表"

#### Scenario: Device selector renders in English
- **WHEN** the user's locale is `en-US` and a device selector block is rendered
- **THEN** device type labels SHALL display as "Rotating Machinery", "Pump", "Static Equipment", "Reciprocating Machinery"
- **AND** UI prompts SHALL display in English (e.g., "Select an org node", "No devices under this node", "Select All", "Selected", "Confirm Selection")

#### Scenario: Device selector renders in Chinese
- **WHEN** the user's locale is `zh-CN` and a device selector block is rendered
- **THEN** all text SHALL display in Chinese as currently shown

### Requirement: Markdown editor block shall use i18n

The `MarkdownBlock.tsx` SHALL replace all hardcoded Chinese strings with `t.xxx` references.

Hardcoded strings to replace:
- Toast: "保存成功"
- Confirm dialog: "放弃未保存的更改？"
- Button labels: "编辑", "取消", "保存"

#### Scenario: Markdown block renders in English
- **WHEN** the user's locale is `en-US` and interacts with a markdown block
- **THEN** buttons SHALL display "Edit", "Cancel", "Save"; toast SHALL show "Saved successfully"; confirm dialog SHALL show "Discard unsaved changes?"

#### Scenario: Markdown block renders in Chinese
- **WHEN** the user's locale is `zh-CN` and interacts with a markdown block
- **THEN** all text SHALL display in Chinese as currently shown

### Requirement: Metric block shall use i18n

The `MetricBlock.tsx` SHALL replace all hardcoded Chinese ARIA labels with `t.xxx` references.

Hardcoded strings to replace:
- ARIA labels: "偏差", "设定点", "低低限", "低限", "高限", "高高限"

#### Scenario: Metric block ARIA labels in English
- **WHEN** the user's locale is `en-US` and a metric block renders
- **THEN** ARIA labels SHALL be "Deviation", "Setpoint", "Low-Low Limit", "Low Limit", "High Limit", "High-High Limit"

#### Scenario: Metric block ARIA labels in Chinese
- **WHEN** the user's locale is `zh-CN` and a metric block renders
- **THEN** ARIA labels SHALL display in Chinese as currently shown

### Requirement: Form block shall use i18n

The `FormBlock.tsx` SHALL replace all hardcoded Chinese strings with `t.xxx` references.

Hardcoded strings to replace:
- Search placeholder: "🔍 搜索..."
- Selection labels: "全选", "全不选"
- Empty state: "无数据"
- Counter: "已选"
- Submit: "提交中...", "提交", "跳过"

#### Scenario: Form block renders in English
- **WHEN** the user's locale is `en-US` and a form block renders
- **THEN** labels SHALL display "Search...", "Select All", "Deselect All", "No data", "Selected", "Submitting...", "Submit", "Skip"

#### Scenario: Form block renders in Chinese
- **WHEN** the user's locale is `zh-CN` and a form block renders
- **THEN** all text SHALL display in Chinese as currently shown

### Requirement: Status block shall use i18n

The `StatusBlock.tsx` SHALL replace all hardcoded Chinese status labels with `t.xxx` references.

Hardcoded strings to replace:
- Status labels: "运行", "停机", "维修", "备用", "故障", "失联"

#### Scenario: Status block renders in English
- **WHEN** the user's locale is `en-US` and a status block renders
- **THEN** status labels SHALL display "Running", "Stopped", "Maintenance", "Standby", "Fault", "Comm Loss"

#### Scenario: Status block renders in Chinese
- **WHEN** the user's locale is `zh-CN` and a status block renders
- **THEN** all text SHALL display in Chinese as currently shown

### Requirement: Alarm block shall use i18n

The `AlarmBlock.tsx` SHALL replace all hardcoded Chinese strings with `t.xxx` references.

Hardcoded strings to replace:
- Level labels: "紧急", "高", "中", "低", "记录"
- Empty state: "无报警"
- Acknowledged: "已确认"
- ARIA suffix: "级"

#### Scenario: Alarm block renders in English
- **WHEN** the user's locale is `en-US` and an alarm block renders
- **THEN** level labels SHALL display "Critical", "High", "Medium", "Low", "Journal"; empty state SHALL be "No alarms"; acknowledged SHALL be "Acknowledged"

#### Scenario: Alarm block renders in Chinese
- **WHEN** the user's locale is `zh-CN` and an alarm block renders
- **THEN** all text SHALL display in Chinese as currently shown

### Requirement: Org tree panel shall use i18n

The `OrgTreePanel.tsx` SHALL replace all hardcoded Chinese strings with `t.xxx` references.

Hardcoded strings to replace:
- Search placeholder: "搜索..."
- Empty states: "无匹配结果", "无组织数据"

#### Scenario: Org tree panel renders in English
- **WHEN** the user's locale is `en-US` and the org tree panel renders
- **THEN** search placeholder SHALL be "Search..."; empty states SHALL be "No matches" and "No org data"

#### Scenario: Org tree panel renders in Chinese
- **WHEN** the user's locale is `zh-CN` and the org tree panel renders
- **THEN** all text SHALL display in Chinese as currently shown

### Requirement: i18n type definitions shall be extended

The `src/core/i18n/locales/types.ts` SHALL be extended with new translation key namespaces to support all the above requirements while maintaining type safety.

New namespaces to add:
- `reportRuns` — report run page and detail strings
- `genui` — GenUI block strings (device selectors, form, markdown, metric, status, alarm, org tree)

Existing namespaces to extend:
- `marketplace` — report template page strings (reuses existing marketplace namespace)

#### Scenario: TypeScript compilation succeeds with new keys
- **WHEN** `pnpm typecheck` is run
- **THEN** no type errors SHALL be reported for the new i18n keys

#### Scenario: Missing translation key causes compile error
- **WHEN** a developer adds a new i18n key to `types.ts` but forgets to add the translation in `zh-CN.ts` or `en-US.ts`
- **THEN** TypeScript SHALL report a type error
