## 1. Registry 和数据

- [x] 1.1 从 `frontend/src/core/genui/registry.ts` 导出 `KNOWN_COMPONENTS` 列表，供调试面板使用
- [x] 1.2 从 `frontend/src/core/genui/index.ts` 导出 `KNOWN_COMPONENTS`

## 2. 调试页面路由

- [x] 2.1 创建路由目录 `frontend/src/app/workspace/debug/a2ui/`
- [x] 2.2 创建 `page.tsx` 客户端组件，引入 `A2UIDebugPage`

## 3. 调试面板 UI 组件

- [x] 3.1 创建 `frontend/src/components/debug/` 目录
- [x] 3.2 创建 `A2UIDebugPanel.tsx` — 左右分栏主布局（左侧组件列表，右侧编辑器+预览）
- [x] 3.3 创建 `ComponentList.tsx` — 可滚动的已注册组件列表，支持选中态
- [x] 3.4 创建 `JsonEditor.tsx` — textarea + JSON 解析错误展示
- [x] 3.5 创建 `PreviewArea.tsx` — 包装 GenUIRenderer，构造临时 UIBlock，无 props 时显示占位提示

## 4. 导航入口

- [x] 4.1 在 `frontend/src/components/workspace/workspace-nav-chat-list.tsx` 中添加调试导航项，链接到 `/workspace/debug/a2ui`

## 5. 国际化

- [x] 5.1 在 i18n 类型定义 `types.ts` 的 sidebar 中添加 `a2uiDebug: string`
- [x] 5.2 在 en-US 翻译中添加 `a2uiDebug: "A2UI Debug"`
- [x] 5.3 在 zh-CN 翻译中添加 `a2uiDebug: "A2UI 调试"`

## 6. 收尾

- [x] 6.1 确保 GenUIRenderer 设置 `disableExpiration={true}`，避免调试模式下超时警告
- [x] 6.2 确保页面在 workspace 布局中响应式、独立可滚动
