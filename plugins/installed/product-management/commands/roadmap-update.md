---
description: Update, create, or reprioritize your product roadmap
argument-hint: "<update description>"
---

# Roadmap Update

> If you see unfamiliar placeholders or need to check which tools are connected, see [CONNECTORS.md](../CONNECTORS.md).

Update, create, or reprioritize a product roadmap.

## Workflow

### 1. Understand Current State

If **~~project tracker** is connected:
- Pull current roadmap items with their statuses, assignees, and dates
- Identify items that are overdue, at risk, or recently completed
- Surface any items without clear owners or dates

If no project management tool is connected:
- Ask the user to describe their current roadmap or paste/upload it
- Accept any format: list, table, spreadsheet, screenshot, or prose description

### 2. Determine the Operation

Ask what the user wants to do:

**Add item**: New feature, initiative, or work item to the roadmap
- Gather: name, description, priority, estimated effort, target timeframe, owner, dependencies
- Suggest where it fits based on current priorities and capacity

**Update status**: Change status of existing items
- Options: not started, in progress, at risk, blocked, completed, cut
- For "at risk" or "blocked": ask for the blocker and mitigation plan

**Reprioritize**: Change the order or priority of items
- Ask what changed (new information, strategy shift, resource change, customer feedback)
- Apply a prioritization framework if helpful — see the **roadmap-management** skill for RICE, MoSCoW, ICE, and value-vs-effort frameworks
- Show before/after comparison

**Move timeline**: Shift dates for items
- Ask why (scope change, dependency slip, resource constraint)
- Identify downstream impacts on dependent items
- Flag items that move past hard deadlines

**Create new roadmap**: Build a roadmap from scratch
- Ask about timeframe (quarter, half, year)
- Ask about format preference (Now/Next/Later, quarterly columns, OKR-aligned)
- Gather the list of initiatives to include

### 3. Generate Roadmap Summary

Produce a roadmap view with:

#### Status Overview
Quick summary: X items in progress, Y completed this period, Z at risk.

#### Roadmap Items
For each item, show:
- Name and one-line description
- Status indicator (on track / at risk / blocked / completed / not started)
- Target timeframe or date
- Owner
- Key dependencies

Group items by:
- Timeframe (Now / Next / Later) or quarter, depending on format
- Or by theme/goal if the user prefers

#### Risks and Dependencies
- Items that are blocked or at risk, with details
- Cross-team dependencies and their status
- Items approaching hard deadlines

#### Changes This Update
If this is an update to an existing roadmap, summarize what changed:
- Items added, removed, or reprioritized
- Timeline shifts
- Status changes

### 4. Follow Up

After generating the roadmap:
- Offer to format for a specific audience (executive summary, engineering detail, customer-facing)
- Offer to draft communication about roadmap changes
- If project management tool is connected, offer to update ticket statuses

## Output Format

Use a clear, scannable format. Tables work well for roadmap items. Use text status labels: **Done**, **On Track**, **At Risk**, **Blocked**, **Not Started**.

## Tips

- A roadmap is a communication tool, not a project plan. Keep it at the right altitude — themes and outcomes, not tasks.
- When reprioritizing, always ask what changed. Priority shifts should be driven by new information, not whim.
- Flag capacity issues early. If the roadmap has more work than the team can handle, say so.
- Dependencies are the biggest risk to roadmaps. Surface them explicitly.
- If the user asks to add something, always ask what comes off or moves. Roadmaps are zero-sum against capacity.
