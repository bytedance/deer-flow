# Memory Inspection UI

DeerFlow provides a layered memory inspection UI accessible from both the **Settings** page and the **thread view toolbar**.

## Architecture

The memory system has three layers:

| Layer | Scope | Storage | Lifetime |
|-------|-------|---------|----------|
| **User Memory** | Per-user | File-based (`memory.json`) | Long-term, persists across sessions |
| **Session Memory** | Per-thread | LangGraph Store | Thread lifetime |
| **Domain Memory** | Per-entity | Vector store (`domain_{tenant_id}`) | Persistent with decay |

## Access Points

### Settings Page

Navigate to **Settings → Memory** to access the full memory inspection panel with three tabs:

- **User Memory** — view/edit/delete user facts, manage context summaries, import/export
- **Session Memory** — load and inspect session facts by thread ID
- **Domain Memory** — search domain facts by keyword, domain, and entity

### Thread View Toolbar

Click the **Brain icon** in the thread header to open a dialog showing the current thread's Session Memory.

## Features

### User Memory

- **Search**: keyword search across facts and summaries
- **Filter**: toggle between All / Facts / Summaries views
- **Create**: add manual facts with content, category, and confidence
- **Edit**: modify existing fact content, category, or confidence
- **Delete**: remove individual facts with confirmation dialog
- **Export**: download full memory as JSON
- **Import**: upload a previously exported memory JSON file
- **Clear all**: wipe all memory (irreversible, requires confirmation)

### Session Memory

- **Load**: enter a thread ID to load its session facts
- **Export**: download session facts as JSON
- **Metadata**: each fact shows category, confidence, creation date, and optional correction notes

### Domain Memory

- **Search**: keyword search with optional domain and entity filters
- **Create**: add new domain facts with content, domain, entity ID, and confidence
- **Export**: download filtered domain facts as JSON
- **Metadata**: each fact shows domain badge, entity ID, similarity score, and adjusted score

### Layer Visibility Toggles

Above the tab bar, use the **User / Session / Domain** toggle buttons to show or hide specific layers. At least one layer must remain visible.

### Real-Time Updates

The UI subscribes to Server-Sent Events (SSE) from `/api/memory/events`. When any memory layer is updated (by an agent or another user session), the relevant panel auto-refreshes within 1 second.

## Feature Flags

### Backend: `memory_api.enabled`

Set `memory_api.enabled: false` in `config.yaml` to disable all memory API endpoints (returns HTTP 503).

```yaml
memory_api:
  enabled: true
  max_content_length: 1000
  audit_log_retention_days: 90
```

### Frontend: `NEXT_PUBLIC_MEMORY_UI_ENABLED`

Set `NEXT_PUBLIC_MEMORY_UI_ENABLED=false` in your `.env` file to hide the Memory button in the thread toolbar and disable the Memory settings page.

## Audit Logging

All write operations (create, update, delete) on memory facts are recorded in the `memory_audit` table. See the [Audit Log Schema](#audit-log-schema) section for details.

## Audit Log Schema

The `memory_audit` table records every mutation to memory facts.

### Columns

| Column | Type | Description |
|--------|------|-------------|
| `id` | `INTEGER` | Auto-increment primary key |
| `tenant_id` | `VARCHAR` | Tenant identifier for multi-tenant isolation |
| `user_id` | `VARCHAR` | User who performed the action |
| `action` | `VARCHAR` | Action type: `create`, `update`, `delete`, `import`, `clear` |
| `layer` | `VARCHAR` | Memory layer: `user`, `session`, `domain` |
| `fact_id` | `VARCHAR` | ID of the affected fact (empty for bulk operations) |
| `before` | `JSON` | Fact state before the action (null for `create`) |
| `after` | `JSON` | Fact state after the action (null for `delete`) |
| `timestamp` | `DATETIME` | UTC timestamp of the action |

### Querying Audit Logs

**API endpoint**: `GET /api/memory/audit`

**Query parameters**:
- `user_id` — filter by user
- `action` — filter by action type
- `date_from` / `date_to` — filter by date range (ISO 8601)

**Example**:
```bash
curl "http://localhost:8000/api/memory/audit?action=delete&date_from=2026-01-01T00:00:00Z"
```

**SQL example** (direct database query):
```sql
SELECT id, user_id, action, layer, fact_id, timestamp
FROM memory_audit
WHERE tenant_id = 'default'
  AND action = 'delete'
  AND timestamp > '2026-01-01'
ORDER BY timestamp DESC
LIMIT 50;
```

### Retention

Audit logs are retained for `memory_api.audit_log_retention_days` days (default: 90). Older entries should be purged by a scheduled job or manual cleanup.
