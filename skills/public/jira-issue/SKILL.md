---
name: jira-issue
description: "Jira issue management skill for handling comment mentions and task assignments. Use this skill when an agent needs to respond to Jira @mentions, process assigned tasks, manage ticket transitions (Open → In Progress → In Review → Closed), execute code workflows (branch, implement, PR), and post ADF-formatted comments. Covers the full lifecycle: claim ticket, fetch details, execute work, post summary, transition status. Requires the acli skill for CLI operations."
required_tools:
  - acli
---

# Jira Issue Management

This skill defines workflows for handling Jira issue events: **comment mentions** and **task assignments**. It uses `acli` (Atlassian CLI) for all Jira operations — see the [acli skill](../acli/SKILL.md) for command reference and authentication setup.

## Prerequisites

- `acli` installed and authenticated (see [acli skill](../acli/SKILL.md))
- `gh` CLI available if code workflows involve GitHub PRs

## Handling Comment Mentions

Triggered when someone @mentions the agent in a Jira comment.

### Steps

1. **Read context** — parse the issue key and comment from the incoming event.
2. **Fetch full issue details** (if needed):
   ```bash
   acli jira workitem view {ISSUE_KEY} --json
   ```
3. **Determine intent** — does the comment request a code change, information, or action?
4. **If code change requested** — follow the [Code Workflow](#code-workflow) below.
5. **Otherwise** — compose an ADF JSON reply that @mentions the commenter (see [ADF Templates](references/adf-templates.md)).
6. **Post the reply**:
   ```bash
   acli jira workitem comment create --key "{ISSUE_KEY}" --body-file /tmp/jira-reply.json
   ```

### Guidelines

- Always @mention the commenter so they receive a notification.
- Keep responses concise and professional.
- If the request is unclear, ask for clarification in the comment.

## Handling Task Assignments

Triggered when a ticket moves to `Open` status (or is assigned to the agent). Follow these steps **in order**:

### Step 1 — Claim the Ticket

Post a comment acknowledging the task, then transition to **In Progress**:

```bash
# Post acknowledgement (ADF JSON with @mention of reporter)
acli jira workitem comment create --key "{ISSUE_KEY}" --body-file /tmp/jira-reply.json

# Check available transitions
acli jira workitem transition --key "{ISSUE_KEY}" --list

# Move to In Progress
acli jira workitem transition --key "{ISSUE_KEY}" --status "In Progress"
```

### Step 2 — Read Full Issue Details

```bash
acli jira workitem view {ISSUE_KEY} --json --fields "*all"
```

Fetch any linked issues or attachments as needed.

### Step 3 — Execute the Task

**Bug fix or feature requiring code changes:**
Follow the [Code Workflow](#code-workflow) below.

**Investigation, data query, or non-code task:**
Carry out the task directly using available tools. If you hit a blocker requiring human input, post a comment explaining what you need, transition to **On Hold**, and stop.

### Step 4 — Post a Summary Comment

Write an ADF JSON comment summarizing outcomes (PR link, findings, etc.) — see [ADF Templates](references/adf-templates.md):

```bash
acli jira workitem comment create --key "{ISSUE_KEY}" --body-file /tmp/jira-reply.json
```

### Step 5 — Transition to In Review

```bash
acli jira workitem transition --key "{ISSUE_KEY}" --status "In Review"
```

## Code Workflow

When code changes are needed:

1. **Understand the issue** — read provided context. Use `acli jira workitem view` if more detail is needed.
2. **Clone & explore** — clone the repo (if not already local), explore relevant code to understand the problem and existing patterns.
3. **Branch** — create `{ISSUE_KEY}/{short-description}` (e.g. `PROJ-1234/fix-login-redirect`).
4. **Implement** — make minimal, focused changes. Follow existing code style. Add/update tests if applicable.
5. **Verify** — run tests and linters. Review your own diff (`git diff`).
6. **Push & create PR** — commit, push, then create a PR.

### PR Format

- **Title:** `[{ISSUE_KEY}] <concise description>`
- **Body:** include Jira issue link, summary of changes, testing done

### On Success

Post the PR URL in a Jira comment, transition to **In Review**.

### On Blocker

Post a comment explaining what you need, transition to **On Hold**, and stop.

### Quality Rules

- Always use feature branches — never push to main/master.
- Run tests before pushing.
- Only change what's necessary — no unrelated refactoring.
- If tests were already failing before your changes, note it in the PR description.
- If the issue is ambiguous, make reasonable assumptions and document them in the PR.

## Status Reference

| Status      | Meaning                                         |
|-------------|------------------------------------------------|
| Open        | Ready for agent — triggers task assignment      |
| In Progress | Agent is actively working on the task           |
| On Hold     | Blocked — waiting for human input               |
| In Review   | Agent done, awaiting human verification         |
| Closed      | Verified and complete                           |

## Transition Commands Quick Reference

```bash
# List available transitions for an issue
acli jira workitem transition --key "{ISSUE_KEY}" --list

# Transition to a status
acli jira workitem transition --key "{ISSUE_KEY}" --status "In Progress"
acli jira workitem transition --key "{ISSUE_KEY}" --status "In Review"
acli jira workitem transition --key "{ISSUE_KEY}" --status "On Hold"
acli jira workitem transition --key "{ISSUE_KEY}" --status "Closed"
```
