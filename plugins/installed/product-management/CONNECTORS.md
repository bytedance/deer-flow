# Connectors

## How tool references work

Plugin files use `~~category` as a placeholder for whatever tool the user connects in that category. For example, `~~project tracker` might mean Linear, Asana, Jira, or any other tracker with an MCP server.

Plugins are **tool-agnostic** — they describe workflows in terms of categories (project tracker, design, product analytics, etc.) rather than specific products. The `.mcp.json` pre-configures specific MCP servers, but any MCP server in that category works.

## Connectors for this plugin

| Category | Placeholder | Included servers | Other options |
|----------|-------------|-----------------|---------------|
| Chat | `~~chat` | Slack | Microsoft Teams |
| Project tracker | `~~project tracker` | Linear, Asana, monday.com, ClickUp, Atlassian (Jira/Confluence) | Shortcut, Basecamp |
| Knowledge base | `~~knowledge base` | Notion | Confluence, Guru, Coda |
| Design | `~~design` | Figma | Sketch, Adobe XD |
| Product analytics | `~~product analytics` | Amplitude, Pendo | Mixpanel, Heap, FullStory |
| User feedback | `~~user feedback` | Intercom | Productboard, Canny, UserVoice |
| Meeting transcription | `~~meeting transcription` | Fireflies | Gong, Dovetail, Otter.ai |
