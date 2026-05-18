# a2ui-debug-panel Specification

## Purpose
TBD - created by archiving change a2ui-debug-panel. Update Purpose after archive.
## Requirements
### Requirement: 导航入口
系统 SHALL 在 workspace 侧边栏中提供一个导航项，链接到 A2UI 调试面板。

#### Scenario: 点击调试导航项
- **当** 用户点击左侧边栏中的"A2UI 调试"
- **则** 右侧内容区导航到 `/workspace/debug/a2ui` 并显示调试面板

#### Scenario: 导航项高亮
- **当** 当前路径为 `/workspace/debug/a2ui`
- **则** 调试导航项应当高亮显示为激活状态

### Requirement: 展示所有已注册的 A2UI 组件
系统 SHALL 在调试面板中展示所有已注册的 A2UI 组件类型。

#### Scenario: 组件列表渲染
- **当** 调试面板加载
- **则** registry 中所有组件类型（chart, echart, table, card, form, confirm, code, timeline, layout, markdown, image, gauge, alarm, metric, status）应当显示为可选项

#### Scenario: 选中组件
- **当** 用户点击组件列表中的某个组件类型
- **则** 该组件应当高亮选中，其默认 props 应当加载到 JSON 编辑器中

### Requirement: JSON 编辑器
系统 SHALL 提供一个文本编辑器用于编辑组件 props 的 JSON。

#### Scenario: 输入有效 JSON
- **当** 用户在编辑器中输入有效 JSON
- **则** 组件应当在预览区中使用这些 props 渲染

#### Scenario: 输入无效 JSON
- **当** 用户在编辑器中输入无效 JSON
- **则** 应当显示行内错误信息，预览区显示上一次有效渲染结果或占位提示

#### Scenario: 编辑器为空
- **当** JSON 编辑器为空
- **则** 预览区应当显示占位提示，引导用户输入 JSON props

### Requirement: 实时组件预览
系统 SHALL 使用现有的 GenUIRenderer 实时渲染所选组件的 JSON props。

#### Scenario: 有效 props 渲染
- **当** 为选中组件提供有效的 props JSON
- **则** 组件应当在预览区中使用 GenUIRenderer 渲染，并设置 `disableExpiration={true}`

#### Scenario: 不在白名单的 props
- **当** JSON 中包含组件 sanitizer 白名单之外的键
- **则** sanitizeProps 应当静默丢弃这些键，组件仅使用允许的 props 渲染

#### Scenario: 无效的组件 props
- **当** JSON 中的值未通过 Zod 校验
- **则** 预览区应当显示来自 GenUIRenderer 的校验错误信息

