# Component Schemas

Detailed format specifications for every plugin component type. Reference this when implementing components in Phase 4.

## Commands

**Location**: `commands/command-name.md`
**Format**: Markdown with optional YAML frontmatter

### Frontmatter Fields

| Field | Required | Type | Description |
|-------|----------|------|-------------|
| `description` | No | String | Brief description shown in `/help` (under 60 chars) |
| `allowed-tools` | No | String or Array | Tools the command can use |
| `model` | No | String | Model override: `sonnet`, `opus`, `haiku` |
| `argument-hint` | No | String | Documents expected arguments for autocomplete |

### Example Command

```markdown
---
description: Review code for security issues
allowed-tools: Read, Grep, Bash(git:*)
argument-hint: [file-path]
---

Review @$1 for security vulnerabilities including:
- SQL injection
- XSS attacks
- Authentication bypass
- Insecure data handling

Provide specific line numbers, severity ratings, and remediation suggestions.
```

### Key Rules

- **Commands are instructions FOR Claude**, not messages for the user. Write them as directives.
- `$ARGUMENTS` captures all arguments as a single string; `$1`, `$2`, `$3` capture positional arguments.
- `@path` syntax includes file contents in the command context.
- `!` backtick syntax executes bash inline for dynamic context (e.g., `` !`git diff --name-only` ``).
- Use `${CLAUDE_PLUGIN_ROOT}` to reference plugin files portably.

### allowed-tools Patterns

```yaml
# Specific tools
allowed-tools: Read, Write, Edit, Bash(git:*)

# Bash with specific commands only
allowed-tools: Bash(npm:*), Read

# MCP tools (specific)
allowed-tools: ["mcp__plugin_name_server__tool_name"]
```

## Skills

**Location**: `skills/skill-name/SKILL.md`
**Format**: Markdown with YAML frontmatter

### Frontmatter Fields

| Field | Required | Type | Description |
|-------|----------|------|-------------|
| `name` | Yes | String | Skill identifier |
| `description` | Yes | String | Third-person description with trigger phrases |
| `version` | No | String | Semver version |

### Example Skill

```yaml
---
name: api-design
description: >
  This skill should be used when the user asks to "design an API",
  "create API endpoints", "review API structure", or needs guidance
  on REST API best practices, endpoint naming, or request/response design.
version: 0.1.0
---
```

### Writing Style Rules

- **Frontmatter description**: Third-person ("This skill should be used when..."), with specific trigger phrases in quotes.
- **Body**: Imperative/infinitive form ("Parse the config file," not "You should parse the config file").
- **Length**: Keep SKILL.md body under 3,000 words (ideally 1,500-2,000). Move detailed content to `references/`.

### Skill Directory Structure

```
skill-name/
├── SKILL.md              # Core knowledge (required)
├── references/           # Detailed docs loaded on demand
│   ├── patterns.md
│   └── advanced.md
├── examples/             # Working code examples
│   └── sample-config.json
└── scripts/              # Utility scripts
    └── validate.sh
```

### Progressive Disclosure Levels

1. **Metadata** (always in context): name + description (~100 words)
2. **SKILL.md body** (when skill triggers): core knowledge (<5k words)
3. **Bundled resources** (as needed): references, examples, scripts (unlimited)

## Agents

**Location**: `agents/agent-name.md`
**Format**: Markdown with YAML frontmatter

### Frontmatter Fields

| Field | Required | Type | Description |
|-------|----------|------|-------------|
| `name` | Yes | String | Lowercase, hyphens, 3-50 chars |
| `description` | Yes | String | Triggering conditions with `<example>` blocks |
| `model` | Yes | String | `inherit`, `sonnet`, `opus`, or `haiku` |
| `color` | Yes | String | `blue`, `cyan`, `green`, `yellow`, `magenta`, `red` |
| `tools` | No | Array | Restrict to specific tools |

### Example Agent

```markdown
---
name: code-reviewer
description: Use this agent when the user asks for a thorough code review or wants detailed analysis of code quality, security, and best practices.

<example>
Context: User has just written a new module
user: "Can you do a deep review of this code?"
assistant: "I'll use the code-reviewer agent to provide a thorough analysis."
<commentary>
User explicitly requested a detailed review, which matches this agent's specialty.
</commentary>
</example>

<example>
Context: User is about to merge a PR
user: "Review this before I merge"
assistant: "Let me run a comprehensive review using the code-reviewer agent."
<commentary>
Pre-merge review benefits from the agent's structured analysis process.
</commentary>
</example>

model: inherit
color: blue
tools: ["Read", "Grep", "Glob"]
---

You are a code review specialist focused on identifying issues across security, performance, maintainability, and correctness.

**Your Core Responsibilities:**
1. Analyze code structure and organization
2. Identify security vulnerabilities
3. Flag performance concerns
4. Check adherence to best practices

**Analysis Process:**
1. Read all files in scope
2. Identify patterns and anti-patterns
3. Categorize findings by severity
4. Provide specific remediation suggestions

**Output Format:**
Present findings grouped by severity (Critical, Warning, Info) with:
- File path and line number
- Description of the issue
- Suggested fix
```

### Agent Naming Rules

- 3-50 characters
- Lowercase letters, numbers, hyphens only
- Must start and end with alphanumeric
- No underscores, spaces, or special characters

### Color Guidelines

- Blue/Cyan: Analysis, review
- Green: Success-oriented tasks
- Yellow: Caution, validation
- Red: Critical, security
- Magenta: Creative, generation

## Hooks

**Location**: `hooks/hooks.json`
**Format**: JSON

### Available Events

| Event | When it fires |
|-------|--------------|
| `PreToolUse` | Before a tool call executes |
| `PostToolUse` | After a tool call completes |
| `Stop` | When Claude finishes a response |
| `SubagentStop` | When a subagent finishes |
| `SessionStart` | When a session begins |
| `SessionEnd` | When a session ends |
| `UserPromptSubmit` | When the user sends a message |
| `PreCompact` | Before context compaction |
| `Notification` | When a notification fires |

### Hook Types

**Prompt-based** (recommended for complex logic):
```json
{
  "type": "prompt",
  "prompt": "Evaluate whether this file write follows project conventions: $TOOL_INPUT",
  "timeout": 30
}
```
Supported events: Stop, SubagentStop, UserPromptSubmit, PreToolUse.

**Command-based** (deterministic checks):
```json
{
  "type": "command",
  "command": "bash ${CLAUDE_PLUGIN_ROOT}/hooks/scripts/validate.sh",
  "timeout": 60
}
```

### Example hooks.json

```json
{
  "PreToolUse": [
    {
      "matcher": "Write|Edit",
      "hooks": [
        {
          "type": "prompt",
          "prompt": "Check that this file write follows project coding standards. If it violates standards, explain why and block.",
          "timeout": 30
        }
      ]
    }
  ],
  "SessionStart": [
    {
      "matcher": "",
      "hooks": [
        {
          "type": "command",
          "command": "cat ${CLAUDE_PLUGIN_ROOT}/context/project-context.md",
          "timeout": 10
        }
      ]
    }
  ]
}
```

### Hook Output Format (Command Hooks)

Command hooks return JSON to stdout:

```json
{
  "decision": "block",
  "reason": "File write violates naming convention"
}
```

Decisions: `approve`, `block`, `ask_user` (ask for confirmation).

## MCP Servers

**Location**: `.mcp.json` at plugin root
**Format**: JSON

### Server Types

**stdio** (local process):
```json
{
  "mcpServers": {
    "my-server": {
      "command": "node",
      "args": ["${CLAUDE_PLUGIN_ROOT}/servers/server.js"],
      "env": {
        "API_KEY": "${API_KEY}"
      }
    }
  }
}
```

**SSE** (hosted with OAuth):
```json
{
  "mcpServers": {
    "asana": {
      "type": "sse",
      "url": "https://mcp.asana.com/sse"
    }
  }
}
```

**HTTP** (REST API):
```json
{
  "mcpServers": {
    "api-service": {
      "type": "http",
      "url": "https://api.example.com/mcp",
      "headers": {
        "Authorization": "Bearer ${API_TOKEN}"
      }
    }
  }
}
```

### Server Type Selection Guide

| Type | Best for | Auth method |
|------|----------|-------------|
| stdio | Local tools, custom servers | Environment variables |
| SSE | Hosted cloud services | OAuth (automatic) |
| HTTP | REST API backends | Token headers |

### Environment Variable Expansion

All MCP configs support `${VAR_NAME}` substitution:
- `${CLAUDE_PLUGIN_ROOT}` — plugin directory (always use for portability)
- `${ANY_ENV_VAR}` — user environment variables

Document all required environment variables in the plugin README.

## CONNECTORS.md

**Location**: Plugin root
**When to create**: When the plugin references external tools by category rather than specific product

### Format

```markdown
# Connectors

## How tool references work

Plugin files use `~~category` as a placeholder for whatever tool the user
connects in that category. For example, `~~project tracker` might mean
Asana, Linear, Jira, or any other project tracker with an MCP server.

Plugins are tool-agnostic — they describe workflows in terms of categories
rather than specific products.

## Connectors for this plugin

| Category | Placeholder | Included servers | Other options |
|----------|-------------|-----------------|---------------|
| Chat | `~~chat` | Slack | Microsoft Teams, Discord |
| Project tracker | `~~project tracker` | Linear | Asana, Jira, Monday |
```

### Using ~~ Placeholders

In plugin files (commands, skills, agents), reference tools generically:

```markdown
Check ~~project tracker for open tickets assigned to the user.
Post a summary to ~~chat in the team channel.
```

During customization (via the cowork-plugin-customizer skill), these get replaced with specific tool names.

## README.md

Every plugin should include a README with:

1. **Overview** — what the plugin does
2. **Components** — list of commands, skills, agents, hooks, MCP servers
3. **Setup** — any required environment variables or configuration
4. **Usage** — how to use each command or trigger each skill
5. **Customization** — if CONNECTORS.md exists, mention it
