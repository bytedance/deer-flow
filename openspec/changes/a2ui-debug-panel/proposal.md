## 为什么

开发者在构建和调试 A2UI (GenUI) 组件时缺乏可视化的调试工具，无法快速预览组件渲染效果、测试 props 组合。当前只能通过实际对话触发组件渲染来验证，效率低下。需要一个独立的调试界面，支持组件目录浏览和 JSON 实时预览。

## 改什么

- 在左侧导航树新增 "A2UI 调试" 入口
- 新增 `/workspace/debug/a2ui` 路由页面
- 右侧展示所有已注册的 A2UI 组件列表（chart, table, card, form, confirm, code, timeline, layout, markdown, image, gauge, alarm, metric, status, echart）
- 支持 JSON 编辑器输入组件 props，实时渲染预览
- 复用现有 `GenUIRenderer` 和 `registry` 实现组件渲染

## 能力

### 新增能力

- `a2ui-debug-panel`: A2UI 组件调试面板，提供组件目录浏览、JSON 参数编辑和实时渲染预览功能

### 修改的能力

<!-- 无现有能力的需求变更 -->

## 影响范围

- 新增路由 `/workspace/debug/a2ui` (`frontend/src/app/workspace/debug/a2ui/page.tsx`)
- 修改导航组件 `frontend/src/components/workspace/workspace-nav-chat-list.tsx` 添加导航项
- 新增调试页面组件 `frontend/src/components/debug/` 目录
- 依赖现有 `GenUIRenderer`、`registry`（`getBlockComponent`、`KNOWN_COMPONENTS`）
- 需新增 i18n 翻译键（`sidebar.a2uiDebug`）
