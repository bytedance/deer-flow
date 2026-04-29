# Jira Work Item Commands Reference

## Table of Contents
- [workitem create](#workitem-create)
- [workitem create-bulk](#workitem-create-bulk)
- [workitem edit](#workitem-edit)
- [workitem view](#workitem-view)
- [workitem search](#workitem-search)
- [workitem assign](#workitem-assign)
- [workitem transition](#workitem-transition)
- [workitem delete](#workitem-delete)
- [workitem clone](#workitem-clone)
- [workitem archive](#workitem-archive)
- [workitem unarchive](#workitem-unarchive)
- [workitem comment create](#workitem-comment-create)
- [workitem comment update](#workitem-comment-update)
- [workitem comment delete](#workitem-comment-delete)
- [workitem comment list](#workitem-comment-list)
- [workitem comment visibility](#workitem-comment-visibility)
- [workitem link create](#workitem-link-create)
- [workitem link delete](#workitem-link-delete)
- [workitem link list](#workitem-link-list)
- [workitem link type](#workitem-link-type)
- [workitem attachment list](#workitem-attachment-list)
- [workitem attachment delete](#workitem-attachment-delete)
- [workitem watcher remove](#workitem-watcher-remove)

---

## workitem create

Create a Jira work item.

```
acli jira workitem create [flags]
```

| Flag | Short | Type | Description |
|------|-------|------|-------------|
| `--summary` | `-s` | string | Work item summary/title |
| `--project` | `-p` | string | Project key |
| `--type` | `-t` | string | Type: Epic, Story, Task, Bug, Subtask |
| `--assignee` | `-a` | string | Email, account ID, `@me`, or `default` |
| `--description` | `-d` | string | Plain text or ADF description |
| `--description-file` | | string | Read description from file |
| `--label` | `-l` | strings | Comma-separated labels |
| `--parent` | | string | Parent work item ID |
| `--from-json` | | string | Read from JSON file |
| `--from-file` | `-f` | string | Read summary/description from file |
| `--generate-json` | | | Generate JSON template |
| `--editor` | `-e` | | Open text editor for summary/description |
| `--json` | | | JSON output |

Examples:
```bash
acli jira workitem create --summary "New Task" --project "TEAM" --type "Task"
acli jira workitem create --summary "Bug report" --project "PROJ" --type "Bug" --assignee "user@atlassian.com" --label "bug,cli"
acli jira workitem create --from-json "workitem.json"
acli jira workitem create --generate-json
```

### AfterShip Required Custom Fields

When creating tickets in AfterShip Jira projects, the **"Source of requirements"** field (`customfield_11532`) is required. Standard `--summary`/`--type` flags alone will be rejected. Use `--from-json` to include it:

```bash
cat > /tmp/new-issue.json << 'EOF'
{
  "summary": "Your ticket summary",
  "project": { "key": "ABU" },
  "issuetype": { "name": "Task" },
  "customfield_11532": { "id": "10856" }
}
EOF

acli jira workitem create --from-json /tmp/new-issue.json
```

**"Source of requirements" option IDs (`customfield_11532`):**

| optionId | Value |
|----------|-------|
| `10855` | 客户定制化需求（仅该客户能用）Customized requirement |
| `10856` | 功能特性（非客户定制需求）Non-customized requirement |
| `10857` | 运营需求 Operational requirement |
| `10858` | 内部组织管理需求 Internal management requirement |

Choose the option that best matches the ticket's context. If unsure, default to `10856` (Non-customized requirement).

---

## workitem create-bulk

Bulk create Jira issues from structured data.

```
acli jira workitem create-bulk [flags]
```

| Flag | Type | Description |
|------|------|-------------|
| `--from-csv` | string | CSV file (columns: summary, projectKey, issueType, description, label, parentIssueId, assignee) |
| `--from-json` | string | JSON file with array of issue objects |
| `--generate-json` | | Output example JSON structure |
| `--ignore-errors` | | Continue past failures |
| `--yes` | | Skip confirmation |

Examples:
```bash
acli jira workitem create-bulk --from-json issues.json
acli jira workitem create-bulk --from-csv issues.csv
acli jira workitem create-bulk --generate-json
```

---

## workitem edit

Modify one or multiple Jira work items.

```
acli jira workitem edit [flags]
```

| Flag | Short | Type | Description |
|------|-------|------|-------------|
| `--key` | `-k` | string | Comma-separated work item keys |
| `--jql` | | string | JQL query selecting work items |
| `--filter` | | string | Filter ID |
| `--summary` | `-s` | string | New title |
| `--description` | `-d` | string | New description (plain text or ADF) |
| `--description-file` | | string | Read description from file |
| `--assignee` | `-a` | string | Email, account ID, `@me`, or `default` |
| `--remove-assignee` | | | Unassign |
| `--type` | `-t` | string | Change work item type |
| `--labels` | `-l` | string | Modify labels |
| `--remove-labels` | | string | Remove specified labels |
| `--from-json` | | string | Load from JSON file |
| `--generate-json` | | | Create JSON template |
| `--ignore-errors` | | | Continue despite errors |
| `--json` | | | JSON output |
| `--yes` | `-y` | | Skip confirmation |

Examples:
```bash
acli jira workitem edit --key "KEY-1,KEY-2" --summary "New Summary"
acli jira workitem edit --jql "project = TEAM" --assignee "user@atlassian.com"
acli jira workitem edit --filter 10001 --description "Updated description" --yes
acli jira workitem edit --from-json "workitem.json"
```

---

## workitem view

View work item details.

```
acli jira workitem view [key] [flags]
```

| Flag | Short | Type | Description |
|------|-------|------|-------------|
| `--fields` | `-f` | string | Fields to return. Supports `*all`, `*navigable`, minus prefix to exclude. Default: `key,issuetype,summary,status,assignee,description` |
| `--json` | | | JSON output |
| `--web` | `-w` | | Open in browser |

Examples:
```bash
acli jira workitem view KEY-123
acli jira workitem view KEY-123 --json
acli jira workitem view KEY-123 --fields "summary,comment"
acli jira workitem view KEY-123 --fields "*all" --json
acli jira workitem view KEY-123 --web
```

---

## workitem search

Search for work items using JQL.

```
acli jira workitem search [flags]
```

| Flag | Short | Type | Description |
|------|-------|------|-------------|
| `--jql` | `-j` | string | JQL query |
| `--filter` | | string | Saved filter ID |
| `--fields` | `-f` | string | Comma-separated fields. Default: `issuetype,key,assignee,priority,status,summary` |
| `--limit` | `-l` | int | Max results |
| `--paginate` | | | Fetch all pages |
| `--count` | | | Return count only |
| `--json` | | | JSON output |
| `--csv` | | | CSV output |
| `--web` | `-w` | | Open in browser |

Examples:
```bash
acli jira workitem search --jql "project = TEAM" --paginate
acli jira workitem search --jql "project = TEAM AND status = 'In Progress'" --json
acli jira workitem search --jql "assignee = currentUser()" --fields "key,summary,status" --csv
acli jira workitem search --jql "project = TEAM" --count
acli jira workitem search --filter 10001
```

---

## workitem assign

Assign work items to users.

```
acli jira workitem assign [flags]
```

| Flag | Short | Type | Description |
|------|-------|------|-------------|
| `--key` | `-k` | string | Comma-separated keys |
| `--jql` | | string | JQL query |
| `--filter` | | string | Filter ID |
| `--from-file` | `-f` | string | Read keys from file |
| `--assignee` | `-a` | string | Email, account ID, `@me`, or `default` |
| `--remove-assignee` | | | Remove assignee |
| `--ignore-errors` | | | Continue past failures |
| `--json` | | | JSON output |
| `--yes` | `-y` | | Skip confirmation |

Examples:
```bash
acli jira workitem assign --key "KEY-1" --assignee "@me"
acli jira workitem assign --jql "project = TEAM" --assignee "user@atlassian.com"
acli jira workitem assign --key "KEY-1" --remove-assignee
```

---

## workitem transition

Transition work items to another status.

```
acli jira workitem transition [flags]
```

| Flag | Short | Type | Description |
|------|-------|------|-------------|
| `--key` | `-k` | string | Comma-separated keys |
| `--jql` | | string | JQL query |
| `--filter` | | string | Filter ID |
| `--status` | `-s` | string | Target status name |
| `--ignore-errors` | | | Continue past failures |
| `--json` | | | JSON output |
| `--yes` | `-y` | | Skip confirmation |

Examples:
```bash
acli jira workitem transition --key "KEY-1,KEY-2" --status "Done"
acli jira workitem transition --jql "project = TEAM" --status "In Progress"
acli jira workitem transition --filter 10001 --status "To Do" --yes
```

---

## workitem delete

> **DESTRUCTIVE: This permanently deletes work items. Always confirm with the user before executing. For bulk operations via `--jql` or `--filter`, first run a search to show what will be affected.**

Delete work items.

```
acli jira workitem delete [flags]
```

| Flag | Short | Type | Description |
|------|-------|------|-------------|
| `--key` | `-k` | string | Comma-separated keys |
| `--jql` | | string | JQL query |
| `--filter` | | string | Filter ID |
| `--from-file` | `-f` | string | Read keys from file |
| `--ignore-errors` | | | Continue past failures |
| `--json` | | | JSON output |
| `--yes` | `-y` | | Skip confirmation |

Examples:
```bash
acli jira workitem delete --key "KEY-1,KEY-2"
acli jira workitem delete --jql "project = TEAM AND status = Done" --yes
```

---

## workitem clone

Clone work items within the same project or across projects/sites.

```
acli jira workitem clone [flags]
```

| Flag | Short | Type | Description |
|------|-------|------|-------------|
| `--key` | `-k` | string | Comma-separated keys to clone |
| `--jql` | | string | JQL query |
| `--filter` | | string | Filter ID |
| `--from-file` | `-f` | string | Read keys from file |
| `--to-project` | | string | Target project key |
| `--to-site` | | string | Target site (defaults to current) |
| `--ignore-errors` | | | Continue past failures |
| `--json` | | | JSON output |
| `--yes` | `-y` | | Skip confirmation |

Example:
```bash
acli jira workitem clone --key "KEY-1,KEY-2" --to-project "TEAM"
```

---

## workitem archive

Archive work items (read-only, not deleted).

```
acli jira workitem archive [flags]
```

| Flag | Short | Type | Description |
|------|-------|------|-------------|
| `--key` | `-k` | string | Comma-separated keys |
| `--jql` | | string | JQL query |
| `--filter` | | string | Filter ID |
| `--from-file` | `-f` | string | Read keys from file |
| `--ignore-errors` | | | Continue past failures |
| `--json` | | | JSON output |
| `--yes` | `-y` | | Skip confirmation |

Examples:
```bash
acli jira workitem archive --key "KEY-1,KEY-2"
acli jira workitem archive --jql "project = TEAM AND status = Done" --yes
```

---

## workitem unarchive

Restore archived work items.

```
acli jira workitem unarchive [flags]
```

| Flag | Short | Type | Description |
|------|-------|------|-------------|
| `--key` | `-k` | string | Comma-separated keys |
| `--from-file` | `-f` | string | Read keys from file |
| `--ignore-errors` | | | Continue past failures |
| `--json` | | | JSON output |
| `--yes` | `-y` | | Skip confirmation |

---

## workitem comment create

Add a comment to work items.

```
acli jira workitem comment create [flags]
```

| Flag | Short | Type | Description |
|------|-------|------|-------------|
| `--key` | `-k` | string | Comma-separated keys |
| `--jql` | | string | JQL query |
| `--filter` | | string | Filter ID |
| `--body` | `-b` | string | Comment text (plain text or ADF) |
| `--body-file` | `-F` | string | Read comment from file (plain text or ADF JSON) |
| `--editor` | | | Open text editor |
| `--edit-last` | `-e` | | Modify the most recent comment by same author |
| `--ignore-errors` | | | Continue past failures |
| `--json` | | | JSON output |

Examples:
```bash
# Plain text comment
acli jira workitem comment create --key "KEY-1" --body "This is a comment"
acli jira workitem comment create --jql "project = TEAM" --body-file "comment.txt"
acli jira workitem comment create --key "KEY-1" --editor
```

### ADF (Atlassian Document Format) Comments

For rich comments with @mentions, formatting, or structured content, use ADF JSON. The `--body` flag accepts inline ADF, or use `--body-file` to read ADF from a file.

**ADF structure:**
```json
{
  "version": 1,
  "type": "doc",
  "content": [
    {
      "type": "paragraph",
      "content": [
        { "type": "text", "text": "Your comment text" }
      ]
    }
  ]
}
```

**@mentioning a user (requires ADF):**

Write the ADF JSON to a file, then pass it with `--body-file`:

```bash
cat > /tmp/jira-reply.json << 'ENDJSON'
{
  "version": 1,
  "type": "doc",
  "content": [
    {
      "type": "paragraph",
      "content": [
        {
          "type": "mention",
          "attrs": {
            "id": "5b10ac8d82e05b22cc7d4ef5",
            "text": "@John Smith",
            "accessLevel": ""
          }
        },
        { "type": "text", "text": " " },
        { "type": "text", "text": "Your response here" }
      ]
    }
  ]
}
ENDJSON

acli jira workitem comment create --key "KEY-123" --body-file /tmp/jira-reply.json
```

**ADF tips:**
- The `mention` node's `id` is the user's Atlassian account ID, `text` is the display name prefixed with `@`
- Keep `accessLevel` as an empty string
- For multi-paragraph responses, add multiple `paragraph` objects in the top-level `content` array
- Place the `mention` node first in the paragraph so the user gets notified

---

## workitem comment update

Update an existing comment.

```
acli jira workitem comment update [flags]
```

| Flag | Short | Type | Description |
|------|-------|------|-------------|
| `--key` | | string | Work item key |
| `--id` | | string | Comment ID |
| `--body` | `-b` | string | New comment text |
| `--body-file` | `-F` | string | Read body from file |
| `--body-adf` | | string | Body in ADF format (JSON file) |
| `--notify` | | | Notify users about the change |
| `--visibility-group` | | string | Restrict visibility to group |
| `--visibility-role` | | string | Restrict visibility to role |

Examples:
```bash
acli jira workitem comment update --key TEST-123 --id 10001 --body "Updated text"
acli jira workitem comment update --key TEST-123 --id 10001 --body "Internal" --visibility-role "Administrators"
```

---

## workitem comment delete

Delete a comment from a work item.

```
acli jira workitem comment delete [flags]
```

| Flag | Type | Description |
|------|------|-------------|
| `--key` | string | Work item key |
| `--id` | string | Comment ID |

Example:
```bash
acli jira workitem comment delete --key TEST-1 --id 10023
```

---

## workitem comment list

List comments on a work item.

```
acli jira workitem comment list [flags]
```

| Flag | Type | Description |
|------|------|-------------|
| `--key` | string | Work item key (required) |
| `--limit` | int | Max comments per page (default: 50) |
| `--order` | string | Sort: `created`, `updated`, `+created`, `-created` (default: `+created`) |
| `--paginate` | | Fetch all pages |
| `--json` | | JSON output |

Example:
```bash
acli jira workitem comment list --key TEST-123 --json
```

---

## workitem comment visibility

Get available visibility options for comments.

```
acli jira workitem comment visibility [flags]
```

| Flag | Type | Description |
|------|------|-------------|
| `--role` | | List project roles |
| `--group` | | List available groups |
| `--project` | string | Project key (required with `--role`) |

Examples:
```bash
acli jira workitem comment visibility --role --project PROJ-123
acli jira workitem comment visibility --group
```

---

## workitem link create

Create links between work items.

```
acli jira workitem link create [flags]
```

| Flag | Type | Description |
|------|------|-------------|
| `--out` | string | Outward work item ID |
| `--in` | string | Inward work item ID |
| `--type` | string | Link type (e.g., `Blocks`, `Cloners`, `Duplicate`) |
| `--from-json` | string | Read link mapping from JSON file |
| `--from-csv` | string | CSV with outward IDs, inward IDs, and link type |
| `--generate-json` | | Show example JSON structure |
| `--ignore-errors` | | Continue past failures |
| `--yes` | | Skip confirmation |

Examples:
```bash
acli jira workitem link create --out KEY-123 --in KEY-456 --type Blocks
acli jira workitem link create --from-json links.json
```

---

## workitem link delete

Delete links between work items.

```
acli jira workitem link delete [flags]
```

| Flag | Type | Description |
|------|------|-------------|
| `--id` | string | Link ID(s) to delete |
| `--from-json` | string | Read link IDs from JSON |
| `--from-csv` | string | Read link IDs from CSV |
| `--ignore-errors` | | Continue past failures |
| `--yes` | | Skip confirmation |

---

## workitem link list

List all links of a work item.

```
acli jira workitem link list [flags]
```

| Flag | Type | Description |
|------|------|-------------|
| `--key` | string | Work item key |
| `--json` | | JSON output |

---

## workitem link type

Get available link types.

```
acli jira workitem link type [flags]
```

| Flag | Type | Description |
|------|------|-------------|
| `--json` | | JSON output |

---

## workitem attachment list

List attachments on a work item.

```
acli jira workitem attachment list [flags]
```

| Flag | Type | Description |
|------|------|-------------|
| `--key` | string | Work item key |
| `--json` | | JSON output |

---

## workitem attachment delete

> **DESTRUCTIVE: This permanently deletes an attachment. Confirm with the user before executing.**

Delete an attachment.

```
acli jira workitem attachment delete [flags]
```

| Flag | Type | Description |
|------|------|-------------|
| `--id` | string | Attachment ID |

---

## workitem watcher remove

Remove a watcher from an issue.

```
acli jira workitem watcher remove [flags]
```

| Flag | Type | Description |
|------|------|-------------|
| `--key` | string | Issue key |
| `--user` | string | Account ID of user to remove |

Example:
```bash
acli jira workitem watcher remove --key TEST-1 --user 5b10ac8d82e05b22cc7d4ef5
```
