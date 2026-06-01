## Context

当前 `TodoCountIndicator` 渲染三个并排的 `CountBadge`（异常/启机/停机），各占 icon + 标签 + 数字。数据来自 `GET /api/workbench/todo-stats`，60s 轮询。

项目中已有 shadcn `DropdownMenu` 组件可用，铃铛图标使用 lucide-react 的 `BellIcon`。

## Goals / Non-Goals

**Goals:**
- 三个独立 badge 合并为单个铃铛按钮，点击展开下拉面板
- 铃铛上显示总待办数（三项之和），有数字时高亮
- 下拉面板每行显示一项待办（图标 + 标签 + 数量），保留原有颜色语义

**Non-Goals:**
- 不改变数据获取逻辑（API + 轮询频率不变）
- 不改变两个 chat page 中的引用方式（组件接口不变）
- 不新增路由或页面

## Decisions

1. **铃铛位置与样式**：替换原三个 badge 的 flex 容器。铃铛按钮使用 `Button variant="ghost" size="icon"`，总待办数显示为 Badge 角标（右上角小圆点或数字）。如果总数为 0，铃铛保持默认色；如果有待办（总数 > 0），铃铛高亮为 amber/warning 色调。

2. **下拉面板结构**：使用 `DropdownMenu` + `DropdownMenuContent`，每项使用 `DropdownMenuItem` 只读展示（不可点击操作）：
   ```
   ┌──────────────────┐
   │ 🔺 异常  3      │  ← 橙色背景/文字
   │ ▶  启机  2      │  ← 蓝色背景/文字
   │ ⏻  停机  1      │  ← 灰色背景/文字
   │                  │
   │ 最后更新: 14:30  │  ← 次要信息
   └──────────────────┘
   ```

3. **保持现有颜色语义**：异常 = amber/warning, 启机 = blue/info, 停机 = gray/neutral。下拉项每行左侧显示对应彩色圆点指示器。

4. **删除原 CountBadge 内部组件**：不再需要，直接在下拉内容中内联渲染。

## Risks / Trade-offs

- **待办信息不可一眼看到**：需要点击铃铛才能查看详情，而非直接可见。→ 铃铛上显示总数角标作为摘要，总数 > 0 时视觉突出。
- **点击操作多一步**：原来直接可见，现在需要点击。→ 待办检查不是高频操作，多一步点击可接受。
