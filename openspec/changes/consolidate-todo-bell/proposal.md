## Why

右上角三个待办指标 badge（异常、启机、停机）各占 icon + 文字标签 + 数字，占用较多水平空间。对于小屏或侧边栏展开时 header 空间紧张。合并为一个铃铛图标可节省约 2/3 的空间，同时保留全部待办信息的可访问性。

## What Changes

- `TodoCountIndicator` 组件重构：三个独立 badge 替换为单个铃铛按钮 + 下拉面板
- 铃铛图标显示总待办数（三项之和），有数字时高亮显示
- 点击铃铛弹出 `DropdownMenu`，列出异常、启机、停机各项及对应数量
- 数据获取逻辑（`/api/workbench/todo-stats` + 60s 轮询）保持不变
- Header 中 `TodoCountIndicator` 使用方式不变，仅内部实现变化

## Capabilities

### New Capabilities

- `todo-bell-dropdown`: 待办指标从三个独立 badge 合并为铃铛图标下拉面板，保留数据获取逻辑和轮询频率

### Modified Capabilities

<!-- None -->

## Impact

- `todo-count-indicator.tsx` — 重写渲染逻辑，从三个 badge 改为铃铛 + DropdownMenu
- `chats/[thread_id]/page.tsx` — 无变化（组件接口不变）
- `agents/[agent_name]/chats/[thread_id]/page.tsx` — 无变化（组件接口不变）
- i18n keys — 可能需要新增 tooltip 文本（如 "待办事项"）
