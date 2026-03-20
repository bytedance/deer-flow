---
name: task-management
description: Simple task management using a shared TASKS.md file. Reference this when the user asks about their tasks, wants to add/complete tasks, or needs help tracking commitments.
---

# Task Management

Tasks are tracked in a simple `TASKS.md` file that both you and the user can edit.

## File Location

**Always use `TASKS.md` in the current working directory.**

- If it exists, read/write to it
- If it doesn't exist, create it with the template below

## Dashboard Setup (First Run)

A visual dashboard is available for managing tasks and memory. **On first interaction with tasks:**

1. Check if `dashboard.html` exists in the current working directory
2. If not, copy it from `${CLAUDE_PLUGIN_ROOT}/skills/dashboard.html` to the current working directory
3. Inform the user: "I've added the dashboard. Run `/productivity:start` to set up the full system."

The task board:
- Reads and writes to the same `TASKS.md` file
- Auto-saves changes
- Watches for external changes (syncs when you edit via CLI)
- Supports drag-and-drop reordering of tasks and sections

## Format & Template

When creating a new TASKS.md, use this exact template (without example tasks):

```markdown
# Tasks

## Active

## Waiting On

## Someday

## Done
```

Task format:
- `- [ ] **Task title** - context, for whom, due date`
- Sub-bullets for additional details
- Completed: `- [x] ~~Task~~ (date)`

## How to Interact

**When user asks "what's on my plate" / "my tasks":**
- Read TASKS.md
- Summarize Active and Waiting On sections
- Highlight anything overdue or urgent

**When user says "add a task" / "remind me to":**
- Add to Active section with `- [ ] **Task**` format
- Include context if provided (who it's for, due date)

**When user says "done with X" / "finished X":**
- Find the task
- Change `[ ]` to `[x]`
- Add strikethrough: `~~task~~`
- Add completion date
- Move to Done section

**When user asks "what am I waiting on":**
- Read the Waiting On section
- Note how long each item has been waiting

## Conventions

- **Bold** the task title for scannability
- Include "for [person]" when it's a commitment to someone
- Include "due [date]" for deadlines
- Include "since [date]" for waiting items
- Sub-bullets for additional context
- Keep Done section for ~1 week, then clear old items

## Extracting Tasks

When summarizing meetings or conversations, offer to add extracted tasks:
- Commitments the user made ("I'll send that over")
- Action items assigned to them
- Follow-ups mentioned

Ask before adding - don't auto-add without confirmation.
