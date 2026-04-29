# acli Commands Reference (Non-Workitem)

## Table of Contents
- [Jira Project Commands](#jira-project-commands)
- [Jira Board Commands](#jira-board-commands)
- [Jira Sprint Commands](#jira-sprint-commands)
- [Jira Filter Commands](#jira-filter-commands)
- [Jira Dashboard Commands](#jira-dashboard-commands)
- [Jira Field Commands](#jira-field-commands)
- [Admin Auth Commands](#admin-auth-commands)
- [Admin User Commands](#admin-user-commands)
- [Rovodev Commands](#rovodev-commands)
- [Feedback Command](#feedback-command)

---

## Jira Project Commands

### jira project list

List projects visible to the user.

```
acli jira project list [flags]
```

| Flag | Short | Type | Description |
|------|-------|------|-------------|
| `--limit` | `-l` | int | Max projects (default: 30) |
| `--paginate` | | | Fetch all pages |
| `--recent` | | | Return up to 20 recently-viewed projects |
| `--json` | | | JSON output |

Examples:
```bash
acli jira project list --recent
acli jira project list --paginate --json
acli jira project list --limit 50
```

### jira project view

View project details.

```
acli jira project view [flags]
```

| Flag | Short | Type | Description |
|------|-------|------|-------------|
| `--key` | | string | Project key |
| `--json` | `-j` | | JSON output |

Examples:
```bash
acli jira project view --key "TEAM"
acli jira project view --key "TEAM" --json
```

### jira project create

Create a Jira project.

```
acli jira project create [flags]
```

| Flag | Short | Type | Description |
|------|-------|------|-------------|
| `--name` | `-n` | string | Project name |
| `--key` | `-k` | string | Project key |
| `--from-project` | `-f` | string | Clone from existing project (company-managed only) |
| `--description` | `-d` | string | Description |
| `--lead-email` | `-l` | string | Lead user email |
| `--url` | `-u` | string | Project URL |
| `--from-json` | `-j` | string | Read from JSON file |
| `--generate-json` | `-g` | | Generate JSON template |

Examples:
```bash
acli jira project create --from-project "TEAM" --key "NEW" --name "New Project"
acli jira project create --from-project "TEAM" --key "NEW" --name "New Project" --description "desc" --lead-email "user@atlassian.com"
acli jira project create --generate-json
acli jira project create --from-json "project.json"
```

### jira project update

Modify a project's properties.

```
acli jira project update [flags]
```

| Flag | Short | Type | Description |
|------|-------|------|-------------|
| `--project-key` | `-p` | string | Key of project to update |
| `--key` | `-k` | string | New project key |
| `--name` | `-n` | string | New name |
| `--description` | `-d` | string | New description |
| `--lead-email` | `-l` | string | New lead email |
| `--url` | `-u` | string | New URL |
| `--from-json` | `-j` | string | Read from JSON file |
| `--generate-json` | `-g` | | Generate JSON template |

Examples:
```bash
acli jira project update --project-key "TEAM1" --key "TEAM" --name "New Name"
acli jira project update --project-key "TEAM1" --from-json "project.json"
```

### jira project delete

> **DESTRUCTIVE: This permanently deletes a project and all its work items. Always confirm with the user before executing.**

Delete a project.

```
acli jira project delete [flags]
```

| Flag | Type | Description |
|------|------|-------------|
| `--key` | string | Project key |

### jira project archive

Archive a project.

```
acli jira project archive [flags]
```

| Flag | Type | Description |
|------|------|-------------|
| `--key` | string | Project key |

### jira project restore

Restore an archived project.

```
acli jira project restore [flags]
```

| Flag | Type | Description |
|------|------|-------------|
| `--key` | string | Project key |

---

## Jira Board Commands

### jira board search

Search boards.

```
acli jira board search [flags]
```

| Flag | Type | Description |
|------|------|-------------|
| `--name` | string | Filter by board name (partial match) |
| `--project` | string | Filter by project key |
| `--type` | string | Filter by type: `scrum`, `kanban`, `simple` |
| `--filter` | string | Filter by filter ID |
| `--orderBy` | string | Order: `name`, `-name`, `+name` |
| `--limit` | int | Max results (default: 50) |
| `--paginate` | | Fetch all pages |
| `--private` | | Include private boards |
| `--json` | | JSON output |
| `--csv` | | CSV output |

Examples:
```bash
acli jira board search --project "TEAM"
acli jira board search --type scrum --json
acli jira board search --name "Sprint" --paginate
```

### jira board list-sprints

List sprints for a board.

```
acli jira board list-sprints [flags]
```

| Flag | Type | Description |
|------|------|-------------|
| `--id` | string | Board ID (required) |
| `--state` | string | Filter: `future`, `active`, `closed` (comma-separated) |
| `--limit` | int | Max sprints (default: 50) |
| `--paginate` | | Fetch all pages |
| `--json` | | JSON output |
| `--csv` | | CSV output |

Examples:
```bash
acli jira board list-sprints --id 123
acli jira board list-sprints --id 123 --state active,closed
acli jira board list-sprints --id 123 --json
```

---

## Jira Sprint Commands

### jira sprint list-workitems

List work items in a sprint.

```
acli jira sprint list-workitems [flags]
```

| Flag | Type | Description |
|------|------|-------------|
| `--sprint` | int | Sprint ID (required) |
| `--board` | int | Board ID (required) |
| `--fields` | string | Comma-separated fields (default: `key,issuetype,summary,assignee,priority,status`) |
| `--jql` | string | JQL filter for sprint items |
| `--limit` | int | Max issues per page (default: 50) |
| `--paginate` | | Fetch all pages |
| `--json` | | JSON output |
| `--csv` | | CSV output |

Example:
```bash
acli jira sprint list-workitems --sprint 1 --board 6
```

---

## Jira Filter Commands

### jira filter list

List owned or favourite filters.

```
acli jira filter list [flags]
```

| Flag | Type | Description |
|------|------|-------------|
| `--my` | | Filters owned by current user |
| `--favourite` | | Favourite filters |
| `--json` | | JSON output |

Examples:
```bash
acli jira filter list --my
acli jira filter list --favourite --json
```

### jira filter search

Search filters.

```
acli jira filter search [flags]
```

| Flag | Short | Type | Description |
|------|-------|------|-------------|
| `--name` | `-n` | string | Partial name match (case-insensitive) |
| `--owner` | `-e` | string | Filter by owner email |
| `--limit` | `-l` | int | Max results (default: 30) |
| `--paginate` | | | Fetch all pages |
| `--json` | | | JSON output |
| `--csv` | | | CSV output |

Examples:
```bash
acli jira filter search --owner user@atlassian.com --name "report"
acli jira filter search --paginate --csv
```

### jira filter add-favourite

Add a filter as favourite.

```
acli jira filter add-favourite [flags]
```

| Flag | Type | Description |
|------|------|-------------|
| `--filterId` | string | Filter ID |

### jira filter change-owner

Reassign filter ownership.

```
acli jira filter change-owner [flags]
```

| Flag | Short | Type | Description |
|------|-------|------|-------------|
| `--id` | | string | Comma-separated filter IDs |
| `--owner` | | string | New owner email |
| `--from-file` | `-f` | string | Read filter IDs from file |
| `--ignore-errors` | | | Continue past failures |
| `--json` | | | JSON output |

Example:
```bash
acli jira filter change-owner --id 123,456 --owner anna@company.com
```

---

## Jira Dashboard Commands

### jira dashboard search

Search dashboards.

```
acli jira dashboard search [flags]
```

| Flag | Short | Type | Description |
|------|-------|------|-------------|
| `--name` | `-n` | string | Partial name match (case-insensitive) |
| `--owner` | `-e` | string | Filter by owner email |
| `--limit` | `-l` | int | Max results (default: 30) |
| `--paginate` | | | Fetch all pages |
| `--json` | | | JSON output |
| `--csv` | | | CSV output |

Examples:
```bash
acli jira dashboard search
acli jira dashboard search --owner user@atlassian.com --name "report"
acli jira dashboard search --paginate --csv
```

---

## Jira Field Commands

### jira field create

Create a custom field.

```
acli jira field create [flags]
```

| Flag | Type | Description |
|------|------|-------------|
| `--name` | string | Field name |
| `--type` | string | Field type (e.g., `com.atlassian.jira.plugin.system.customfieldtypes:textfield`) |
| `--description` | string | Field description |
| `--searcherKey` | string | Searcher key |
| `--json` | | JSON output |

Examples:
```bash
acli jira field create --name "Customer Name" --type "com.atlassian.jira.plugin.system.customfieldtypes:textfield"
acli jira field create --name "Priority Level" --type "com.atlassian.jira.plugin.system.customfieldtypes:select" --searcherKey "com.atlassian.jira.plugin.system.customfieldtypes:multiselectsearcher"
```

### jira field delete

> **CAUTION: This moves a custom field to trash. Use `jira field cancel-delete` to restore if needed. Confirm with the user before executing.**

Move a custom field to trash.

```
acli jira field delete [flags]
```

| Flag | Type | Description |
|------|------|-------------|
| `--id` | string | Custom field ID (e.g., `customfield_12345`) |

### jira field cancel-delete

Restore a field from trash.

```
acli jira field cancel-delete [flags]
```

| Flag | Type | Description |
|------|------|-------------|
| `--id` | string | Custom field ID |

---

## Admin Auth Commands

### admin auth login

Authenticate for admin tasks (requires organization API key).

```
acli admin auth login [flags]
```

| Flag | Short | Type | Description |
|------|-------|------|-------------|
| `--email` | `-e` | string | Admin email (required) |
| `--token` | | | Read API key from stdin |

Examples:
```bash
acli admin auth login --email admin@atlassian.com --token < token.txt
echo "$API_KEY" | acli admin auth login --email admin@atlassian.com --token
```

> **Note:** Never hardcode API keys in commands. Always use environment variables or file-based input. Prefer `< token.txt` over `echo` to avoid shell history exposure.

### admin auth logout

Log out of admin account.

```
acli admin auth logout
```

### admin auth status

Show admin account status.

```
acli admin auth status
```

### admin auth switch

Switch admin accounts.

```
acli admin auth switch [flags]
```

| Flag | Short | Type | Description |
|------|-------|------|-------------|
| `--org` | `-o` | string | Organization name |

---

## Admin User Commands

All admin user commands share these common flags for targeting users:

| Flag | Short | Type | Description |
|------|-------|------|-------------|
| `--email` | `-e` | string | Comma-separated emails |
| `--id` | | string | Comma-separated account IDs |
| `--from-file` | `-f` | string | Read emails/IDs from file |
| `--ignore-errors` | | | Continue past failures |
| `--json` | | | JSON output |

### admin user activate

Activate users.

```
acli admin user activate [flags]
```

Examples:
```bash
acli admin user activate --email john@example.com,anna@example.com
acli admin user activate --id abcd,123
acli admin user activate --from-file users.txt
```

### admin user deactivate

> **CAUTION: This deactivates user accounts, revoking their access. Use `admin user activate` to reverse. Confirm with the user before executing.**

Deactivate users.

```
acli admin user deactivate [flags]
```

### admin user delete

> **DESTRUCTIVE: This deletes managed user accounts. Use `admin user cancel-delete` to cancel pending deletions. Always confirm with the user before executing.**

Delete managed accounts.

```
acli admin user delete [flags]
```

### admin user cancel-delete

Cancel pending account deletion.

```
acli admin user cancel-delete [flags]
```

---

## Rovodev Commands

Rovo Dev is Atlassian's AI coding agent (Beta).

### rovodev auth login

Authenticate for Rovo Dev.

```
acli rovodev auth login [flags]
```

| Flag | Short | Type | Description |
|------|-------|------|-------------|
| `--email` | `-e` | string | User email |
| `--token` | | | Read token from stdin |

Examples:
```bash
acli rovodev auth login
acli rovodev auth login --email "user@atlassian.com" --token < token.txt
```

### rovodev auth logout

```
acli rovodev auth logout
```

### rovodev auth status

```
acli rovodev auth status
```

---

## Feedback Command

Submit feedback or report issues.

```
acli feedback [flags]
```

| Flag | Short | Type | Description |
|------|-------|------|-------------|
| `--summary` | `-s` | string | Summary |
| `--details` | `-d` | string | Details |
| `--email` | `-e` | string | Email for response |
| `--attachments` | `-a` | string | Files to attach |
| `--time` | `-t` | string | When problem occurred (e.g., `1h`, `15m`) |

Example:
```bash
acli feedback --summary "Issue with auth" --details "Token expired unexpectedly" --email "user@atlassian.com"
```
