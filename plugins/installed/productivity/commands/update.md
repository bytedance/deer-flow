---
description: Sync tasks and refresh memory from your current activity
argument-hint: "[--comprehensive]"
---

# Update Command

> If you see unfamiliar placeholders or need to check which tools are connected, see [CONNECTORS.md](../CONNECTORS.md).

Keep your task list and memory current. Two modes:

- **Default:** Sync tasks from external tools, triage stale items, check memory for gaps
- **`--comprehensive`:** Deep scan chat, email, calendar, docs — flag missed todos and suggest new memories

## Usage

```bash
/productivity:update
/productivity:update --comprehensive
```

## Default Mode

### 1. Load Current State

Read `TASKS.md` and `memory/` directory. If they don't exist, suggest `/productivity:start` first.

### 2. Sync Tasks from External Sources

Check for available task sources:
- **Project tracker** (e.g. Asana, Linear, Jira) (if MCP available)
- **GitHub Issues** (if in a repo): `gh issue list --assignee=@me`

If no sources are available, skip to Step 3.

**Fetch tasks assigned to the user** (open/in-progress). Compare against TASKS.md:

| External task | TASKS.md match? | Action |
|---------------|-----------------|--------|
| Found, not in TASKS.md | No match | Offer to add |
| Found, already in TASKS.md | Match by title (fuzzy) | Skip |
| In TASKS.md, not in external | No match | Flag as potentially stale |
| Completed externally | In Active section | Offer to mark done |

Present diff and let user decide what to add/complete.

### 3. Triage Stale Items

Review Active tasks in TASKS.md and flag:
- Tasks with due dates in the past
- Tasks in Active for 30+ days
- Tasks with no context (no person, no project)

Present each for triage: Mark done? Reschedule? Move to Someday?

### 4. Decode Tasks for Memory Gaps

For each task, attempt to decode all entities (people, projects, acronyms, tools, links):

```
Task: "Send PSR to Todd re: Phoenix blockers"

Decode:
- PSR → ✓ Pipeline Status Report (in glossary)
- Todd → ✓ Todd Martinez (in people/)
- Phoenix → ? Not in memory
```

Track what's fully decoded vs. what has gaps.

### 5. Fill Gaps

Present unknown terms grouped:
```
I found terms in your tasks I don't have context for:

1. "Phoenix" (from: "Send PSR to Todd re: Phoenix blockers")
   → What's Phoenix?

2. "Maya" (from: "sync with Maya on API design")
   → Who is Maya?
```

Add answers to the appropriate memory files (people/, projects/, glossary.md).

### 6. Capture Enrichment

Tasks often contain richer context than memory. Extract and update:
- **Links** from tasks → add to project/people files
- **Status changes** ("launch done") → update project status, demote from CLAUDE.md
- **Relationships** ("Todd's sign-off on Maya's proposal") → cross-reference people
- **Deadlines** → add to project files

### 7. Report

```
Update complete:
- Tasks: +3 from project tracker (e.g. Asana), 1 completed, 2 triaged
- Memory: 2 gaps filled, 1 project enriched
- All tasks decoded ✓
```

## Comprehensive Mode (`--comprehensive`)

Everything in Default Mode, plus a deep scan of recent activity.

### Extra Step: Scan Activity Sources

Gather data from available MCP sources:
- **Chat:** Search recent messages, read active channels
- **Email:** Search sent messages
- **Documents:** List recently touched docs
- **Calendar:** List recent + upcoming events

### Extra Step: Flag Missed Todos

Compare activity against TASKS.md. Surface action items that aren't tracked:

```
## Possible Missing Tasks

From your activity, these look like todos you haven't captured:

1. From chat (Jan 18):
   "I'll send the updated mockups by Friday"
   → Add to TASKS.md?

2. From meeting "Phoenix Standup" (Jan 17):
   You have a recurring meeting but no Phoenix tasks active
   → Anything needed here?

3. From email (Jan 16):
   "I'll review the API spec this week"
   → Add to TASKS.md?
```

Let user pick which to add.

### Extra Step: Suggest New Memories

Surface new entities not in memory:

```
## New People (not in memory)
| Name | Frequency | Context |
|------|-----------|---------|
| Maya Rodriguez | 12 mentions | design, UI reviews |
| Alex K | 8 mentions | DMs about API |

## New Projects/Topics
| Name | Frequency | Context |
|------|-----------|---------|
| Starlight | 15 mentions | planning docs, product |

## Suggested Cleanup
- **Horizon project** — No mentions in 30 days. Mark completed?
```

Present grouped by confidence. High-confidence items offered to add directly; low-confidence items asked about.

## Notes

- Never auto-add tasks or memories without user confirmation
- External source links are preserved when available
- Fuzzy matching on task titles handles minor wording differences
- Safe to run frequently — only updates when there's new info
- `--comprehensive` always runs interactively
