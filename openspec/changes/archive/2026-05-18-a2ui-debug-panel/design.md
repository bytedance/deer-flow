## 背景

当前 A2UI (GenUI) 系统已有 15 个注册组件，开发者调试时只能通过实际对话触发组件渲染。需要一个独立的调试面板来快速预览和测试组件。

约束：复用现有 `GenUIRenderer` 和 `registry`；不引入重型依赖；前端栈：Next.js 16 + React 19 + shadcn/ui + Tailwind CSS 4。

## 目标 / 非目标

**目标：**
- 左侧导航新增 "A2UI 调试" 入口，点击进入独立调试页面
- 右侧列出所有已注册组件，选中后可编辑 JSON props 并实时渲染
- 复用现有 `GenUIRenderer` 组件，保留 sanitize/validate 链路

**非目标：**
- 不做组件 props 的图形化表单编辑器（仅 JSON 文本输入）
- 不支持交互式组件（form/confirm）的 callback 提交功能
- 不做多组件组合布局调试

## 决策

### 1. 路由：`/workspace/debug/a2ui`

放在 workspace layout 下，复用侧边栏布局结构。页面使用 `"use client"` 因为需要本地状态管理组件选择和 JSON 编辑。

### 2. 组件数据源：直接从 registry 导出列表

在 `registry.ts` 中新增 `KNOWN_COMPONENTS` 常量导出组件类型列表，调试页面直接读取。不做网络请求。

### 3. JSON 编辑器：轻量 textarea + 高亮

不引入 Monaco Editor（~2MB），使用 `<textarea>` + 手动 JSON 解析 + 错误提示。足够满足调试场景，零额外依赖。

### 4. 渲染：构造临时 UIBlock 传入 GenUIRenderer

调试模式下构造 `UIBlock` 对象（schema_version: "1.0", type: "ui_block", action: "create"），传入 `GenUIRenderer` 并设置 `disableExpiration={true}`。

### 5. 页面布局：左右分栏

- 左侧：组件列表（可滚动的卡片列表）
- 右侧上半部：JSON 编辑器
- 右侧下半部：实时渲染预览（带 border/背景区分的预览区）

### 6. 导航图标：使用 `BugIcon`（lucide-react）

在 `workspace-nav-chat-list.tsx` 的 `SidebarMenu` 末尾新增一个 `SidebarMenuItem`，链接到 `/workspace/debug/a2ui`。

## 风险 / 取舍

- [风险] 用户输入非法 JSON 导致渲染失败 → 缓解：try-catch 解析 + 行内错误提示
- [风险] 组件 props 白名单外的字段被丢弃 → 缓解：编辑器下方可显示 sanitize 后的实际 props（后续优化）
- [风险] 新增路由可能影响现有 workspace 路由匹配 → 缓解：`/workspace/debug/a2ui` 不会与现有 `[thread_id]` 等动态路由冲突
