## ADDED Requirements

### Requirement: Knowledge base is a top-level sidebar item

The system SHALL render the knowledge base entry as a first-level sidebar navigation item directly accessible without expanding a submenu.

#### Scenario: Sidebar renders knowledge base as top-level item

- **WHEN** the workspace sidebar is rendered
- **THEN** "知识库" (Knowledge Bases) is displayed as a top-level `SidebarMenuItem` with a `BookOpenIcon`
- **AND** it appears between "对话历史" (Chats) and "智能体" (Agents) in the navigation order
- **AND** clicking it navigates to `/workspace/knowledge-bases`
- **AND** it highlights when the current path starts with `/workspace/knowledge-bases`

#### Scenario: Tools collapsible menu no longer exists

- **WHEN** the workspace sidebar is rendered
- **THEN** no "工具" (Tools) collapsible menu group is displayed
- **AND** no "TOOLS_MENU_KEY" localStorage logic is present
