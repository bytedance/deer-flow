## Why

当前 AI 报告（ai-report 子智能体）产生的对话散落在通用"最近对话"列表中，无法从"报告历史"入口找到对应的对话上下文。"报告历史"仅展示报告运行记录，与生成报告的聊天对话割裂——用户进入报告历史后看不到是哪个对话生成了该报告，也无法从报告菜单直接浏览历史对话。

## What Changes

- 报告历史页面支持同时展示报告运行记录和报告对话线程
- 从报告历史可一键跳转到对应的聊天上下文（thread/run）
- 侧边栏中报告相关的对话线程可归属到报告历史导航分组下（可选折叠展示）
- 不影响非报告智能体的对话在侧边栏的展示逻辑

## Capabilities

### New Capabilities

- `report-unified-history-view`: 报告历史统一视图——报告运行记录与聊天对话聚合在同一入口下，按时间排序，支持按类型筛选
- `report-sidebar-thread-attribution`: 侧边栏报告对话归属——报告智能体产生的对话线程自动归属到报告历史导航分组下

### Modified Capabilities

<!-- 无现有 spec 涉及报告历史视图的需求变更 -->

## Impact

- 影响 `report-runs-page.tsx`（报告历史列表页）、`workspace-nav-chat-list.tsx`（侧边导航）、`recent-chat-list.tsx`（最近对话列表）
- 需要后端支持按 agent_name metadata 过滤 threads（当前 API 已有 metadata 参数，可能需要验证）
- 依赖现有 Thread → Run → Report 关联链路（ISSUE-01 主对象模型已定义）
