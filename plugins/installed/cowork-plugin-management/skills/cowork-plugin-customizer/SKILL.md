---
name: cowork-plugin-customizer
description: >
  Customize or personalize a Claude Code plugin for a specific organization's tools and workflows.
  Use when users want to customize a plugin, replace tool placeholders, or configure MCP servers for a plugin.
  This skill requires Cowork mode with mounted plugin directories and will not work in remote or standard CLI sessions.
compatibility: Requires Cowork desktop app environment with access to mounted plugin directories (mnt/.local-plugins, mnt/.plugins).
---

# Cowork Plugin Customization

Adapt a generic plugin template to a specific organization by replacing customization points with actual tool names, configuring MCP servers, and applying organization-specific customizations.

> **Finding the plugin**: To find the plugin's source files, run `find mnt/.local-plugins mnt/.plugins -type d -name "*<plugin-name>*"` to locate the plugin directory, then read its files to understand its structure before making changes. If you cannot find the plugin directory, the user is likely running this conversation in a remote container. Abort and let them know: "Customizing plugins is currently only available in the desktop app's Cowork mode."

## Overview

Generic plugins mark customization points with a `~~` prefix. Any line or value starting with `~~` is a placeholder that should be replaced during customization (e.g., `~~Jira` → `Asana`, `~~your-team-channel` → `#engineering`). To find all customization points in a plugin, use:

```bash
grep -rn '~~\w' /path/to/plugin --include='*.md' --include='*.json'
```

> **Important**: Never change the name of the plugin or skill being customized. Only replace `~~`-prefixed placeholder values and update content — do not rename directories, files, or the plugin/skill name fields.

> **Nontechnical output**: All user-facing output (todo list items, questions, summaries) must be written in plain, nontechnical language. Never mention `~~` prefixes, placeholders, or customization points to the user. Frame everything in terms of learning about the organization and its tools.

The process:
1. **Gather context** — use knowledge MCPs to learn what tools and processes the organization uses
2. **Create todo list** — grep for `~~\w` to find all customization points and build a todo list
3. **Complete todo items** — apply gathered context, falling back to user questions when unclear
4. **Search for useful MCPs** — find and connect MCPs for identified tools

If an answer cannot be found via knowledge MCPs or user input, leave the customization point unchanged for a future customization cycle.

## Customization Workflow

### Phase 1: Gather Context from Knowledge MCPs

Use company-internal knowledge MCPs to collect information. See `references/search-strategies.md` for detailed query patterns by category.

**What to gather:**
- Tool names for each `~~`-prefixed placeholder
- Organizational processes and workflows
- Team conventions (naming, statuses, estimation scales)
- Configuration values (workspace IDs, project names, team identifiers)

**Sources to search:**
1. **Chat/Slack MCPs** — tool mentions, integrations, workflow discussions
2. **Document MCPs** — onboarding docs, tool guides, setup instructions
3. **Email MCPs** — license notifications, admin emails, setup invitations

Record all findings for use in Phase 3.

### Phase 2: Create Todo List from Customization Points

Run `grep -rn '~~\w' /path/to/plugin --include='*.md' --include='*.json'` to find all customization points. Group them by theme and create a todo list with user-friendly descriptions that focus on learning about the organization:

- **Good**: "Learn how standup prep works at Company"
- **Bad**: "Replace placeholders in commands/standup-prep.md"

### Phase 3: Complete Todo Items

Work through each item using Phase 1 context.

**If knowledge MCPs provided a clear answer**: Apply directly without confirmation.

**Otherwise**: Use AskUserQuestion. Don't assume "industry standard" defaults are correct — if knowledge MCPs didn't provide a specific answer, ask. Note: AskUserQuestion always includes a Skip button and a free-text input box for custom answers, so do not include `None` or `Other` as options.

**Types of changes:**

1. **Customization point replacements**: `~~Jira` → `Asana`, `~~your-org-channel` → `#engineering`
2. **URL pattern updates**: `tickets.example.com/your-team/123` → `app.asana.com/0/PROJECT_ID/TASK_ID`
3. **Organization-specific values**: Workspace IDs, project names, team identifiers

If user doesn't know or skips, leave the `~~`-prefixed value unchanged.

### Phase 4: Search for Useful MCPs

After all customization points have been resolved, connect MCPs for the tools that were identified. See `references/mcp-servers.md` for the full workflow, category-to-keywords mapping, and config file format.

For each tool identified during customization:
1. Search the registry: `search_mcp_registry(keywords=[...])` using category keywords from `references/mcp-servers.md`, or search for the specific tool name if already known
2. If unconnected: `suggest_connectors(directoryUuids=["chosen-uuid"])` — user completes OAuth
3. Update the plugin's MCP config file (check `plugin.json` for custom location, otherwise `.mcp.json` at root)

Collect all MCP results and present them together in the summary output (see below) — don't present MCPs one at a time during this phase.

**Note:** First-party integrations (Gmail, Google Calendar, Google Drive) are connected at the user level and don't need plugin `.mcp.json` entries.

## Packaging the Plugin

After all customizations are applied, package the plugin as a `.plugin` file for the user:

1. **Zip the plugin directory** (excluding `setup/` since it's no longer needed):
   ```bash
   cd /path/to/plugin && zip -r /tmp/plugin-name.plugin . -x "setup/*" && cp /tmp/plugin-name.plugin /path/to/outputs/plugin-name.plugin
   ```
2. **Present the file to the user** with the `.plugin` extension so they can install it directly. (Presenting the .plugin file will show to the user as a rich preview where they can look through the plugin files, and they can accept the customization by pressing a button.)

> **Important**: Always create the zip in `/tmp/` first, then copy to the outputs folder. Writing directly to the outputs folder may fail due to permissions and leave behind temporary files.

> **Naming**: Use the original plugin directory name for the `.plugin` file (e.g., if the plugin directory is `coder`, the output file should be `coder.plugin`). Do not rename the plugin or its files during customization — only replace placeholder values and update content.

## Summary Output

After customization, present the user with a summary of what was learned grouped by source. Always include the MCPs sections showing which MCPs were connected during setup and which ones the user should still connect:

```markdown
## From searching Slack
- You use Asana for project management
- Sprint cycles are 2 weeks

## From searching documents
- Story points use T-shirt sizes

## From your answers
- Ticket statuses are: Backlog, In Progress, In Review, Done
```

Then present the MCPs that were connected during setup and any that the user should still connect, with instructions on how to connect them.

If no knowledge MCPs were available in Phase 1, and the user had to answer at least one question manually, include a note at the end:
> By the way, connecting sources like Slack or Microsoft Teams would let me find answers automatically next time you customize a plugin.

## Additional Resources

- **`references/mcp-servers.md`** — MCP discovery workflow, category-to-keywords mapping, config file locations
- **`references/search-strategies.md`** — Knowledge MCP query patterns for finding tool names and org values
- **`examples/customized-mcp.json`** — Example fully configured `.mcp.json`
