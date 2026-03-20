# Domain Reference File Template

Use this template when creating reference files for specific data domains (e.g., revenue, users, marketing).

---

```markdown
# [DOMAIN_NAME] Tables

This document contains [domain]-related tables, metrics, and query patterns.

---

## Quick Reference

### Business Context

[2-3 sentences explaining what this domain covers and key concepts]

### Entity Clarification

**"[AMBIGUOUS_TERM]" can mean:**
- **[MEANING_1]**: [DEFINITION] ([TABLE]: [ID_FIELD])
- **[MEANING_2]**: [DEFINITION] ([TABLE]: [ID_FIELD])

Always clarify which one before querying.

### Standard Filters

For [domain] queries, always:
```sql
WHERE [STANDARD_FILTER_1]
  AND [STANDARD_FILTER_2]
```

---

## Key Tables

### [TABLE_1_NAME]
**Location**: `[project.dataset.table]` or `[schema.table]`
**Description**: [What this table contains, when to use it]
**Primary Key**: [COLUMN(S)]
**Update Frequency**: [Daily/Hourly/Real-time] ([LAG] lag)
**Partitioned By**: [PARTITION_COLUMN] (if applicable)

| Column | Type | Description | Notes |
|--------|------|-------------|-------|
| **[column_1]** | [TYPE] | [DESCRIPTION] | [GOTCHA_OR_CONTEXT] |
| **[column_2]** | [TYPE] | [DESCRIPTION] | |
| **[column_3]** | [TYPE] | [DESCRIPTION] | Nullable |

**Relationships**:
- Joins to `[OTHER_TABLE]` on `[JOIN_KEY]`
- Parent of `[CHILD_TABLE]` via `[FOREIGN_KEY]`

**Nested/Struct Fields** (if applicable):
- `[struct_name].[field_1]`: [DESCRIPTION]
- `[struct_name].[field_2]`: [DESCRIPTION]

---

### [TABLE_2_NAME]
[REPEAT FORMAT]

---

## Key Metrics

| Metric | Definition | Table | Formula | Notes |
|--------|------------|-------|---------|-------|
| [METRIC_1] | [DEFINITION] | [TABLE] | `[FORMULA]` | [CAVEATS] |
| [METRIC_2] | [DEFINITION] | [TABLE] | `[FORMULA]` | |

---

## Sample Queries

### [QUERY_PURPOSE_1]
```sql
-- [Brief description of what this query does]
SELECT
    [columns]
FROM [table]
WHERE [standard_filters]
GROUP BY [grouping]
ORDER BY [ordering]
```

### [QUERY_PURPOSE_2]
```sql
[ANOTHER_COMMON_QUERY]
```

### [QUERY_PURPOSE_3]: [More Complex Pattern]
```sql
WITH [cte_name] AS (
    [CTE_LOGIC]
)
SELECT
    [final_columns]
FROM [cte_name]
[joins_and_filters]
```

---

## Common Gotchas

1. **[GOTCHA_1]**: [EXPLANATION]
   - Wrong: `[INCORRECT_APPROACH]`
   - Right: `[CORRECT_APPROACH]`

2. **[GOTCHA_2]**: [EXPLANATION]

---

## Related Dashboards (if applicable)

| Dashboard | Link | Use For |
|-----------|------|---------|
| [DASHBOARD_1] | [URL] | [DESCRIPTION] |
| [DASHBOARD_2] | [URL] | [DESCRIPTION] |
```

---

## Tips for Creating Domain Files

1. **Start with the most-queried tables** - Don't try to document everything
2. **Include column-level detail only for important columns** - Skip obvious ones like `created_at`
3. **Real query examples > abstract descriptions** - Show don't tell
4. **Document the gotchas prominently** - These save the most time
5. **Keep sample queries runnable** - Use real table/column names
6. **Note nested/struct fields explicitly** - These trip people up

## Suggested Domain Files

Common domains to document (create separate files for each):

- `revenue.md` - Billing, subscriptions, ARR, transactions
- `users.md` - Accounts, authentication, user attributes
- `product.md` - Feature usage, events, sessions
- `growth.md` - DAU/WAU/MAU, retention, activation
- `sales.md` - CRM, pipeline, opportunities
- `marketing.md` - Campaigns, attribution, leads
- `support.md` - Tickets, CSAT, response times
