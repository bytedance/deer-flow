## 1. 共享工具：报告对话过滤 Hook

- [x] 1.1 在 `frontend/src/core/report-templates/` 下新增 `useReportThreads.ts`，导出 `useReportThreads()` hook
- [x] 1.2 hook 内从 `useAgents()` 获取 `tags` 包含 `"report"` 的 agent name 列表
- [x] 1.3 对每个 report agent name 调用 `useThreads({ metadata: { agent_name: name } })`，客户端合并结果并按 `updated_at` 降序排列
- [x] 1.4 添加对应的 `useReportThreads.test.ts` 单元测试

## 2. 报告历史页改造：Tab 导航 + 对话列表

- [x] 2.1 在 `report-runs-page.tsx` 中增加 Tab 组件（"运行记录" / "对话"），Tab 状态通过 URL search param（如 `?tab=chats`）或组件 state 管理
- [x] 2.2 实现"对话" Tab 内容：使用 `useReportThreads()` 获取数据，复用类似 `RecentChatList` 的列表项 UI 展示 thread 标题和跳转链接
- [x] 2.3 添加"对话" Tab 的空状态提示："暂无报告对话"
- [x] 2.4 更新 `report-runs-page.test.tsx` 覆盖新 Tab 的交互（5 个测试通过）

## 3. 侧边栏改造：报告对话子列表

- [x] 3.1 在 `WorkspaceNavChatList` 的 `dynamicNavItems` 渲染中，对"报告历史"（`/workspace/report-runs`）导航项特殊处理——增加 `Collapsible` 包裹的子列表
- [x] 3.2 使用 `useReportThreads()` 获取最近 5 条报告对话，渲染为子列表项
- [x] 3.3 子列表项点击跳转到对应 thread 页面（使用 `pathOfThread` 工具函数）
- [x] 3.4 子列表折叠状态通过 localStorage 持久化（如 `sidebar-report-threads-collapsed`）
- [x] 3.5 更新侧边栏相关测试（`sidebar.spec.ts` E2E 测试已添加 2 个新用例）

## 4. 验证与收尾

- [x] 4.1 运行 `pnpm check` 确保类型和 lint 通过
- [x] 4.2 运行 `pnpm test` 确保单元测试通过
- [ ] 4.3 手动验证：从侧边栏"报告历史"进入 → 切换到"对话" Tab → 点击对话跳转 → 面包屑可回到报告历史（**需启动 dev server**）
- [ ] 4.4 手动验证：侧边栏"报告对话"子列表正确展示、折叠、跳转（**需启动 dev server**）
