---
name: acli
description: "Reference guide for the Atlassian CLI (acli) - a command-line tool for interacting with Jira Cloud and Atlassian organization administration. Use this skill when the user wants to perform Jira operations (create/edit/search/transition work items, manage projects, boards, sprints, filters, dashboards), administer Atlassian organizations (manage users, authentication), or automate Atlassian workflows from the terminal. Covers all acli commands including: jira workitem (create, edit, search, assign, transition, comment, clone, link, archive), jira project (create, list, update, archive), jira board/sprint, jira filter/dashboard, admin user management, and rovodev (Rovo Dev AI agent). Requires an authenticated acli binary already installed on the system."
required_tools:
  - acli
env_vars:
  - name: API_TOKEN
    description: "Atlassian API token for non-interactive Jira authentication (optional — only needed for CI/automation, not for interactive OAuth login)"
    required: false
  - name: API_KEY
    description: "Atlassian Admin API key for organization administration commands (optional — only needed for admin commands)"
    required: false
---

# Atlassian CLI (acli) Reference

## Prerequisites

This skill requires `acli` to be installed and authenticated. The binary is NOT bundled with this skill.

If acli is not installed, guide the user to: https://developer.atlassian.com/cloud/acli/guides/install-acli/

Verify availability:
```bash
acli --help
```

## Authentication

Check auth status before running commands:
```bash
acli jira auth status
acli admin auth status
```

If not authenticated, there are three methods:

**OAuth (interactive, recommended for users):**
```bash
acli jira auth login --web
```

**API Token (non-interactive, recommended for CI/automation):**
```bash
echo "$API_TOKEN" | acli jira auth login --site "mysite.atlassian.net" --email "user@atlassian.com" --token
```

**Admin API Key (for admin commands only):**
```bash
echo "$API_KEY" | acli admin auth login --email "admin@atlassian.com" --token
```

Switch between accounts:
```bash
acli jira auth switch --site mysite.atlassian.net --email user@atlassian.com
acli admin auth switch --org myorgname
```

## Security

### Secret Handling
- **Never hardcode tokens or API keys in commands.** Always use environment variables (`$API_TOKEN`, `$API_KEY`) or file-based input (`< token.txt`).
- **Never log, echo, or display tokens** in output. Avoid piping secrets through intermediate files that persist on disk.
- **Prefer OAuth (`--web`) for interactive use.** Only use token-based auth for CI/automation where OAuth is not feasible.
- **Do not store tokens in shell history.** If using `echo "$API_TOKEN" | acli ...`, ensure the variable is set in the environment rather than inlined as a literal value.

### Destructive Operations
The following commands are **destructive or irreversible** — always confirm with the user before executing:
- `acli jira workitem delete` — permanently deletes work items
- `acli jira project delete` — permanently deletes a project and all its work items
- `acli admin user delete` — deletes managed user accounts
- `acli admin user deactivate` — deactivates user accounts
- `acli jira field delete` — moves custom fields to trash

These commands are **impactful but reversible**:
- `acli jira workitem archive` / `unarchive`
- `acli jira project archive` / `restore`
- `acli admin user cancel-delete` — cancels pending deletion
- `acli jira field cancel-delete` — restores field from trash

**Agent safety rules:**
1. Never run destructive commands without explicit user confirmation, even if `--yes` is available.
2. When bulk-targeting via `--jql` or `--filter`, first run a search with the same query to show the user what will be affected.
3. Prefer `--json` output to verify targets before applying destructive changes.
4. Do not combine `--yes` with destructive bulk operations unless the user explicitly requests unattended execution.

## Command Structure

```
acli <command> [<subcommand> ...] {MANDATORY FLAGS} [OPTIONAL FLAGS]
```

Four top-level command groups:
- `acli jira` - Jira Cloud operations (workitems, projects, boards, sprints, filters, dashboards, fields)
- `acli admin` - Organization administration (user management, auth)
- `acli rovodev` - Rovo Dev AI coding agent (Beta)
- `acli feedback` - Submit feedback/bug reports

## Common Patterns

### Output Formats
Most list/search commands support: `--json`, `--csv`, and default table output.

### Bulk Operations
Target multiple items via:
- `--key "KEY-1,KEY-2,KEY-3"` - comma-separated keys
- `--jql "project = TEAM AND status = 'To Do'"` - JQL query
- `--filter 10001` - saved filter ID
- `--from-file "items.txt"` - file with keys/IDs (comma/whitespace/newline separated)

Use `--ignore-errors` to continue past failures in bulk operations.
Use `--yes` / `-y` to skip confirmation prompts (useful for automation).

### Pagination
- `--limit N` - max items to return (defaults vary: 30-50)
- `--paginate` - fetch all pages automatically (overrides --limit)

### JSON Templates
Many create/edit commands support `--generate-json` to produce a template, and `--from-json` to consume it:
```bash
acli jira workitem create --generate-json > template.json
# edit template.json
acli jira workitem create --from-json template.json
```

## Quick Reference: Most Common Operations

### Work Items
```bash
# Create
acli jira workitem create --summary "Fix login bug" --project "TEAM" --type "Bug"
acli jira workitem create --summary "New feature" --project "TEAM" --type "Story" --assignee "@me" --label "frontend,p1"

# Search
acli jira workitem search --jql "project = TEAM AND assignee = currentUser()" --json
acli jira workitem search --jql "project = TEAM AND status = 'In Progress'" --fields "key,summary,assignee" --csv

# View
acli jira workitem view KEY-123
acli jira workitem view KEY-123 --json --fields "*all"

# Edit
acli jira workitem edit --key "KEY-123" --summary "Updated title" --assignee "user@atlassian.com"

# Transition
acli jira workitem transition --key "KEY-123" --status "Done"
acli jira workitem transition --jql "project = TEAM AND sprint in openSprints()" --status "In Progress"

# Assign
acli jira workitem assign --key "KEY-123" --assignee "@me"

# Comment (plain text)
acli jira workitem comment create --key "KEY-123" --body "Work completed"

# Comment (ADF with @mention — write ADF JSON to file, then use --body-file)
acli jira workitem comment create --key "KEY-123" --body-file /tmp/jira-reply.json

# Bulk create
acli jira workitem create-bulk --from-csv issues.csv
```

### Projects
```bash
acli jira project list --paginate --json
acli jira project view --key "TEAM" --json
acli jira project create --from-project "TEAM" --key "NEW" --name "New Project"
```

### Boards & Sprints
```bash
acli jira board search --project "TEAM"
acli jira board list-sprints --id 123 --state active
acli jira sprint list-workitems --sprint 1 --board 6
```

## Detailed Command Reference

For complete flag details, parameters, and examples for every command:

- **Jira work item commands** (create, edit, search, assign, transition, comment, clone, link, archive, attachment, watcher): See [references/jira-workitem-commands.md](references/jira-workitem-commands.md)
- **All other commands** (jira project/board/sprint/filter/dashboard/field, admin, rovodev, feedback): See [references/other-commands.md](references/other-commands.md)
