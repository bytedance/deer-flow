## Context

当前侧边栏"工具"是可折叠的二级菜单（`workspace-nav-chat-list.tsx` 197-262 行），包含三个子项：知识库、平台能力、A2UI 调试。知识库是核心业务入口，使用频率高于其他两项，不应隐藏在折叠菜单中。

设置页已有 `ToolSettingsPage`，目前仅展示 MCP 服务器开关列表。设置弹窗为 `h-[75vh] max-w-6xl`，有足够空间嵌入功能内容。

已有页面的复杂度：
- **平台能力列表页** (~150 行)：类型过滤 tabs + 作用域下拉 + 汇总表格。详情子路由页面 (~170 行) 通过 `useParams` 读取 URL 参数。
- **A2UI 调试面板** (~215 行)：三栏布局（组件列表 | JSON 编辑器 | 预览区），纯 `useState` 驱动，无路由依赖，组件已封装为 `A2UIDebugPanel`。

## Goals / Non-Goals

**Goals:**
- 知识库提升为侧边栏一级菜单项，使用 `BookOpenIcon`
- 平台能力和 A2UI 调试迁入设置页"工具"section，通过 tabs 与现有 MCP 管理内容共存
- 两个 tab 均直接内嵌功能内容，不使用"描述文字 + 打开按钮"的跳转模式
- 移除侧边栏"工具"折叠菜单组

**Non-Goals:**
- 不改变 MCP 服务器的开关逻辑
- 不修改知识库页面本身
- 不删除原有路由页面（`/workspace/capabilities`、`/workspace/debug/a2ui` 保留，直接访问仍可用）

## Decisions

1. **知识库菜单位置**：放在"对话历史"和"智能体"之间，作为独立的 `SidebarMenuItem`，无折叠。理由是它和对话、智能体一样属于核心导航。

2. **设置页 tabs 结构**：在 `ToolSettingsPage` 中使用 shadcn `Tabs` 组件，三个 tab 均直接内嵌功能内容：
   - **Tab "工具管理"**（默认）—— 现有 MCP 服务器开关列表
   - **Tab "平台能力"**—— 内嵌 `CapabilitiesPage` 组件（列表视图），点击某行进入详情视图（tab 内部 state 切换）
   - **Tab "A2UI 调试"**—— 直接复用 `A2UIDebugPanel` 组件（无路由依赖，纯 state 驱动）
   
   理由：弹窗内跳转会割裂体验（设置关闭→页面跳转→再打开设置），内嵌可保证 tab 切换即用即走。

3. **Capabilities 详情适配**：当前 `[type]/[name]/page.tsx` 通过 `useParams` 从 URL 读取参数。嵌入 tab 后需提取一个 `CapabilityDetailView` 组件，接收 `capType` 和 `capName` 作为 props。列表 tab 内通过 `useState<{type, name} | null>` 管理"列表视图 ↔ 详情视图"切换，显示返回按钮。

4. **空间分配**：A2UI 调试面板的三栏布局（280px 组件列表 | JSON 编辑器(上) | 预览区(下)）在 `max-w-6xl` 弹窗内有足够宽度。垂直方向，设置弹窗 75vh 减去 header + tab bar 后剩余约 55-60vh，JSON 编辑器和预览区各约 28-30vh，可正常使用。

5. **原路由页面保留**：`/workspace/capabilities` 和 `/workspace/debug/a2ui` 不删除。用户直接访问 URL 或收藏链接不受影响。

## Risks / Trade-offs

- **A2UI 调试在弹窗内空间受限**：55-60vh 的可用高度约为原全屏页面的 60%，JSON 编辑区和预览区各约 30vh。对大多数 GenUI 组件预览足够，极端复杂组件可能需要滚动。如果频繁需要全屏调试，建议保留直接路由作为备选入口。
- **知识库对无权限用户可见**：一级菜单项始终渲染，但知识库页面本身有权限控制。如果用户无权限访问，页面会自行处理。可接受。
- **平台能力/A2UI 可发现性降低**：从侧边栏移到设置页会减少曝光。但这两项是低频开发者工具，合理折中。原路由保留作为直接入口。
