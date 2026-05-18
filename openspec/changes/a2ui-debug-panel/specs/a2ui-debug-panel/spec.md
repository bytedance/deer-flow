## 新增需求

### 需求：导航入口
系统应当在 workspace 侧边栏中提供一个导航项，链接到 A2UI 调试面板。

#### 场景：点击调试导航项
- **当** 用户点击左侧边栏中的"A2UI 调试"
- **则** 右侧内容区导航到 `/workspace/debug/a2ui` 并显示调试面板

#### 场景：导航项高亮
- **当** 当前路径为 `/workspace/debug/a2ui`
- **则** 调试导航项应当高亮显示为激活状态

### 需求：展示所有已注册的 A2UI 组件
系统应当在调试面板中展示所有已注册的 A2UI 组件类型。

#### 场景：组件列表渲染
- **当** 调试面板加载
- **则** registry 中所有组件类型（chart, echart, table, card, form, confirm, code, timeline, layout, markdown, image, gauge, alarm, metric, status）应当显示为可选项

#### 场景：选中组件
- **当** 用户点击组件列表中的某个组件类型
- **则** 该组件应当高亮选中，其默认 props 应当加载到 JSON 编辑器中

### 需求：JSON 编辑器
系统应当提供一个文本编辑器用于编辑组件 props 的 JSON。

#### 场景：输入有效 JSON
- **当** 用户在编辑器中输入有效 JSON
- **则** 组件应当在预览区中使用这些 props 渲染

#### 场景：输入无效 JSON
- **当** 用户在编辑器中输入无效 JSON
- **则** 应当显示行内错误信息，预览区显示上一次有效渲染结果或占位提示

#### 场景：编辑器为空
- **当** JSON 编辑器为空
- **则** 预览区应当显示占位提示，引导用户输入 JSON props

### 需求：实时组件预览
系统应当使用现有的 GenUIRenderer 实时渲染所选组件的 JSON props。

#### 场景：有效 props 渲染
- **当** 为选中组件提供有效的 props JSON
- **则** 组件应当在预览区中使用 GenUIRenderer 渲染，并设置 `disableExpiration={true}`

#### 场景：不在白名单的 props
- **当** JSON 中包含组件 sanitizer 白名单之外的键
- **则** sanitizeProps 应当静默丢弃这些键，组件仅使用允许的 props 渲染

#### 场景：无效的组件 props
- **当** JSON 中的值未通过 Zod 校验
- **则** 预览区应当显示来自 GenUIRenderer 的校验错误信息
