## Why

侧边栏"工具"折叠菜单混合了不同性质的功能——知识库是核心业务入口，而平台能力和 A2UI 调试是低频的辅助工具。将知识库提升为一级菜单提高可发现性，将辅助工具迁入设置页减少侧边栏内容密度，使导航更聚焦。

## What Changes

- 侧边栏"工具"折叠菜单移除，其三个子项重新分配
- "知识库"提升为侧边栏一级菜单项（位于"对话历史"和"智能体"之间）
- "平台能力"和"A2UI 调试"迁移到设置页"工具" section 中，与现有工具内容通过 tabs 组织
- 侧边栏不再显示可折叠的"工具"菜单组

## Capabilities

### New Capabilities

- `sidebar-knowledge-base-promotion`: 知识库入口从二级折叠菜单提升为侧边栏一级导航项
- `settings-tools-tabs`: 设置页"工具"section 通过 tabs 组织，包含现有工具管理内容及新增的"平台能力"和"A2UI 调试"入口

### Modified Capabilities

<!-- None -->

## Impact

- `workspace-nav-chat-list.tsx` — 移除"工具"折叠菜单，新增知识库一级菜单项
- `tool-settings-page.tsx` — 扩展为 tabs 布局，集成平台能力和 A2UI 调试入口
- i18n keys — 可能新增 tab 标签（工具管理、平台能力、A2UI 调试）
