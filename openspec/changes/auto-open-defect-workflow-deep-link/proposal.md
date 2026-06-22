## Why

EHM 缺陷管理页将新增“AI分析”操作，用户点击某条待办后需要直接进入 AI 工作台的“缺陷闭环” Agent，并自动定位同一条缺陷待办和打开详情。当前 deep-link 只能进入 Agent 并透传参数，用户仍需在待办列表中手动查找目标缺陷，影响从 EHM 业务页面到 AI 辅助分析的闭环效率。

## What Changes

- `defect-workflow-closure` Agent 页面解析 `task_id`、`defect_id`、`defect_no` 和 `auto_open` deep-link 参数。
- 缺陷待办 GenUI 块接收目标定位参数，并在当前用户待办列表加载后自动匹配目标行。
- 命中目标待办时自动选中该行并打开详情，复用现有详情加载和上下文注入流程。
- 未命中目标待办时保留待办列表并展示温和提示，说明目标缺陷未在当前用户待办中找到。
- 更新 deep-link API 文档，明确 EHM “AI分析”集成方式和找不到目标待办时的行为。

## Capabilities

### New Capabilities

### Modified Capabilities

- `deep-link-passthrough`: 增强缺陷闭环 Agent 对 deep-link 业务参数的使用，使 EHM 传入的 `task_id`、`defect_id`、`defect_no` 可驱动当前用户待办列表中的自动定位和详情打开。

## Impact

- Frontend Agent chat page: 读取缺陷闭环 deep-link 目标参数并传入本地 GenUI block。
- Frontend defect workflow GenUI components: 增加自动匹配、自动选中、未命中提示和状态保持。
- Frontend tests: 增加 deep-link 参数传递、匹配优先级、未命中提示和自动详情打开相关测试。
- Documentation: 更新 `docs/deep-link-api.md` 中“缺陷闭环”章节。
- No backend API or database schema changes are required for the first version; matching is limited to the current loaded todo list.
