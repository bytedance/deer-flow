# Example Plugins

Three complete plugin structures at different complexity levels. Use these as templates when implementing in Phase 4.

## Minimal Plugin: Single Command

A simple plugin with one slash command and no other components.

### Structure

```
meeting-notes/
├── .claude-plugin/
│   └── plugin.json
├── commands/
│   └── meeting-notes.md
└── README.md
```

### plugin.json

```json
{
  "name": "meeting-notes",
  "version": "0.1.0",
  "description": "Generate structured meeting notes from transcripts",
  "author": {
    "name": "User"
  }
}
```

### commands/meeting-notes.md

```markdown
---
description: Generate structured meeting notes from a transcript
argument-hint: [transcript-file]
allowed-tools: Read, Write
---

Read the transcript at @$1 and generate structured meeting notes.

Include these sections:
1. **Attendees** — list all participants mentioned
2. **Summary** — 2-3 sentence overview of the meeting
3. **Key Decisions** — numbered list of decisions made
4. **Action Items** — table with columns: Owner, Task, Due Date
5. **Open Questions** — anything unresolved

Write the notes to a new file named after the transcript with `-notes` appended.
```

---

## Standard Plugin: Skill + Commands + MCP

A plugin that combines domain knowledge, user commands, and external service integration.

### Structure

```
code-quality/
├── .claude-plugin/
│   └── plugin.json
├── commands/
│   ├── review.md
│   └── fix-lint.md
├── skills/
│   └── coding-standards/
│       ├── SKILL.md
│       └── references/
│           └── style-rules.md
├── .mcp.json
└── README.md
```

### plugin.json

```json
{
  "name": "code-quality",
  "version": "0.1.0",
  "description": "Enforce coding standards with reviews, linting, and style guidance",
  "author": {
    "name": "User"
  }
}
```

### commands/review.md

```markdown
---
description: Review code changes for style and quality issues
allowed-tools: Read, Grep, Bash(git:*)
---

Get the list of changed files: !`git diff --name-only`

For each changed file:
1. Read the file
2. Check against the coding-standards skill for style violations
3. Identify potential bugs or anti-patterns
4. Flag any security concerns

Present a summary with:
- File path
- Issue severity (Error, Warning, Info)
- Description and suggested fix
```

### commands/fix-lint.md

```markdown
---
description: Auto-fix linting issues in changed files
allowed-tools: Read, Write, Edit, Bash(npm:*)
---

Run the linter: !`npm run lint -- --format json 2>&1`

Parse the linter output and fix each issue:
- For auto-fixable issues, apply the fix directly
- For manual-fix issues, make the correction following project conventions
- Skip issues that require architectural changes

After all fixes, run the linter again to confirm clean output.
```

### skills/coding-standards/SKILL.md

```yaml
---
name: coding-standards
description: >
  This skill should be used when the user asks about "coding standards",
  "style guide", "naming conventions", "code formatting rules", or needs
  guidance on project-specific code quality expectations.
version: 0.1.0
---
```

```markdown
# Coding Standards

Project coding standards and conventions for consistent, high-quality code.

## Core Rules

- Use camelCase for variables and functions
- Use PascalCase for classes and types
- Prefer const over let; avoid var
- Maximum line length: 100 characters
- Use explicit return types on all exported functions

## Import Order

1. External packages
2. Internal packages (aliased with @/)
3. Relative imports
4. Type-only imports last

## Additional Resources

- **`references/style-rules.md`** — complete style rules by language
```

### .mcp.json

```json
{
  "mcpServers": {
    "github": {
      "type": "http",
      "url": "https://api.githubcopilot.com/mcp/"
    }
  }
}
```

---

## Full-Featured Plugin: All Component Types

A plugin using skills, commands, agents, hooks, and MCP integration with tool-agnostic connectors.

### Structure

```
engineering-workflow/
├── .claude-plugin/
│   └── plugin.json
├── commands/
│   ├── standup-prep.md
│   └── create-ticket.md
├── skills/
│   └── team-processes/
│       ├── SKILL.md
│       └── references/
│           └── workflow-guide.md
├── agents/
│   └── ticket-analyzer.md
├── hooks/
│   └── hooks.json
├── .mcp.json
├── CONNECTORS.md
└── README.md
```

### plugin.json

```json
{
  "name": "engineering-workflow",
  "version": "0.1.0",
  "description": "Streamline engineering workflows: standup prep, ticket management, and code quality",
  "author": {
    "name": "User"
  },
  "keywords": ["engineering", "workflow", "tickets", "standup"]
}
```

### agents/ticket-analyzer.md

```markdown
---
name: ticket-analyzer
description: Use this agent when the user needs to analyze tickets, triage incoming issues, or prioritize a backlog.

<example>
Context: User is preparing for sprint planning
user: "Help me triage these new tickets"
assistant: "I'll use the ticket-analyzer agent to review and categorize the tickets."
<commentary>
Ticket triage requires systematic analysis across multiple dimensions, making the agent appropriate.
</commentary>
</example>

<example>
Context: User has a large backlog
user: "Prioritize my backlog for next sprint"
assistant: "Let me analyze the backlog using the ticket-analyzer agent to recommend priorities."
<commentary>
Backlog prioritization is a multi-step autonomous task well-suited for the agent.
</commentary>
</example>

model: inherit
color: cyan
tools: ["Read", "Grep"]
---

You are a ticket analysis specialist. Analyze tickets for priority, effort, and dependencies.

**Your Core Responsibilities:**
1. Categorize tickets by type (bug, feature, tech debt, improvement)
2. Estimate relative effort (S, M, L, XL)
3. Identify dependencies between tickets
4. Recommend priority ordering

**Analysis Process:**
1. Read all ticket descriptions
2. Categorize each by type
3. Estimate effort based on scope
4. Map dependencies
5. Rank by impact-to-effort ratio

**Output Format:**
| Ticket | Type | Effort | Dependencies | Priority |
|--------|------|--------|-------------|----------|
| ...    | ...  | ...    | ...         | ...      |

Followed by a brief rationale for the top 5 priorities.
```

### hooks/hooks.json

```json
{
  "SessionStart": [
    {
      "matcher": "",
      "hooks": [
        {
          "type": "command",
          "command": "echo '## Team Context\n\nSprint cycle: 2 weeks. Standup: daily at 9:30 AM. Use ~~project tracker for ticket management.'",
          "timeout": 5
        }
      ]
    }
  ]
}
```

### CONNECTORS.md

```markdown
# Connectors

## How tool references work

Plugin files use `~~category` as a placeholder for whatever tool the user
connects in that category. Plugins are tool-agnostic.

## Connectors for this plugin

| Category | Placeholder | Included servers | Other options |
|----------|-------------|-----------------|---------------|
| Project tracker | `~~project tracker` | Linear | Asana, Jira, Monday |
| Chat | `~~chat` | Slack | Microsoft Teams |
| Source control | `~~source control` | GitHub | GitLab, Bitbucket |
```

### .mcp.json

```json
{
  "mcpServers": {
    "linear": {
      "type": "sse",
      "url": "https://mcp.linear.app/sse"
    },
    "github": {
      "type": "http",
      "url": "https://api.githubcopilot.com/mcp/"
    },
    "slack": {
      "type": "http",
      "url": "https://slack.mcp.claude.com/mcp"
    }
  }
}
```
