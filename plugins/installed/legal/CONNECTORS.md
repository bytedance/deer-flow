# Connectors

## How tool references work

Plugin files use `~~category` as a placeholder for whatever tool the user connects in that category. For example, `~~cloud storage` might mean Box, Egnyte, or any other storage provider with an MCP server.

Plugins are **tool-agnostic** — they describe workflows in terms of categories (cloud storage, chat, office suite, etc.) rather than specific products. The `.mcp.json` pre-configures specific MCP servers, but any MCP server in that category works.

## Connectors for this plugin

| Category | Placeholder | Included servers | Other options |
|----------|-------------|-----------------|---------------|
| Chat | `~~chat` | Slack | Microsoft Teams |
| Cloud storage | `~~cloud storage` | Box, Egnyte | Dropbox, SharePoint, Google Drive |
| CLM | `~~CLM` | — | Ironclad, Agiloft |
| CRM | `~~CRM` | — | Salesforce, HubSpot |
| E-signature | `~~e-signature` | — | DocuSign, Adobe Sign |
| Office suite | `~~office suite` | Microsoft 365 | Google Workspace |
| Project tracker | `~~project tracker` | Atlassian (Jira/Confluence) | Linear, Asana |
