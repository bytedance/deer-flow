---
name: find-skills
description: Helps users discover and install agent skills when they ask questions like "how do I do X", "find a skill for X", "is there a skill that can...", or express interest in extending capabilities. This skill should be used when the user is looking for functionality that might exist as an installable skill.
---

# Find Skills

This skill helps you discover and install skills from the open agent skills ecosystem.

## When to Use This Skill

Use this skill when the user:

- Asks "how do I do X" where X might be a common task with an existing skill
- Says "find a skill for X" or "is there a skill for X"
- Asks "can you do X" where X is a specialized capability
- Expresses interest in extending agent capabilities
- Wants to search for tools, templates, or workflows
- Mentions they wish they had help with a specific domain (design, testing, deployment, etc.)

## What is the Skills CLI?

The Skills CLI (`npx skills`) is the package manager for the open agent skills ecosystem. Skills are modular packages that extend agent capabilities with specialized knowledge, workflows, and tools.

**Key commands:**

- `npx skills find [query]` - Search for skills interactively or by keyword
- `npx skills check` - Check for skill updates
- `npx skills update` - Update all installed skills

**Browse skills at:** https://skills.sh/

## How to Help Users Find Skills

### Step 1: Understand What They Need

When a user asks for help with something, identify:

1. The domain (e.g., React, testing, design, deployment)
2. The specific task (e.g., writing tests, creating animations, reviewing PRs)
3. Whether this is a common enough task that a skill likely exists

### Step 2: Search for Skills

Run the find command with a relevant query:

```bash
npx skills find [query]
```

For example:

- User asks "how do I make my React app faster?" → `npx skills find react performance`
- User asks "can you help me with PR reviews?" → `npx skills find pr review`
- User asks "I need to create a changelog" → `npx skills find changelog`

The command will return results like:

```
Install with bash /path/to/skill/scripts/install-skill.sh vercel-labs/agent-skills@vercel-react-best-practices

vercel-labs/agent-skills@vercel-react-best-practices
└ https://skills.sh/vercel-labs/agent-skills/vercel-react-best-practices
```

### Step 3: Present Options to the User

When you find relevant skills, present them to the user with:

1. The skill name and what it does
2. The installation action for their current environment (see Step 4)
3. A link to learn more at skills.sh

Example response:

```
I found a skill that might help! The "vercel-react-best-practices" skill provides
React and Next.js performance optimization guidelines from Vercel Engineering.

To install it in a host DeerFlow checkout, run this command from the repository root:
bash skills/public/find-skills/scripts/install-skill.sh vercel-labs/agent-skills@vercel-react-best-practices

In a DeerFlow sandbox or Web session, use the administrator .skill import flow described in Step 4.

Learn more: https://skills.sh/vercel-labs/agent-skills/vercel-react-best-practices
```

### Step 4: Install the Skill

Choose the installation path for the current environment.

**Inside a host DeerFlow checkout**, run [install-skill.sh](scripts/install-skill.sh) from the repository root. It installs the skill under `$HOME/.agents/skills/` and links it into that checkout's `skills/custom/` directory:

```bash
bash skills/public/find-skills/scripts/install-skill.sh <owner/repo@skill-name>
```

For example:

```bash
bash skills/public/find-skills/scripts/install-skill.sh vercel-labs/agent-skills@vercel-react-best-practices
```

**Inside an isolated DeerFlow sandbox or Web session**, do not run this helper. The host checkout and its writable `skills/custom/` directory are unavailable, and `/mnt/skills` is a read-only projection. Instead, provide the skill as a `.skill` archive and ask an administrator to install it through **Capability Center → Skills → My skills → Install .skill**. If the source does not provide an archive, package the downloaded skill directory first with `python /mnt/skills/public/skill-creator/scripts/package_skill.py <skill-directory> <output-directory>` or an equivalent ZIP tool. Installation uses the administrator's per-user skill storage and makes the skill available through the normal skill projection. Do not copy skill files into `/mnt/skills` or claim that writing files into the thread workspace installs a skill.

## Common Skill Categories

When searching, consider these common categories:

| Category        | Example Queries                          |
| --------------- | ---------------------------------------- |
| Web Development | react, nextjs, typescript, css, tailwind |
| Testing         | testing, jest, playwright, e2e           |
| DevOps          | deploy, docker, kubernetes, ci-cd        |
| Documentation   | docs, readme, changelog, api-docs        |
| Code Quality    | review, lint, refactor, best-practices   |
| Design          | ui, ux, design-system, accessibility     |
| Productivity    | workflow, automation, git                |

## Tips for Effective Searches

1. **Use specific keywords**: "react testing" is better than just "testing"
2. **Try alternative terms**: If "deploy" doesn't work, try "deployment" or "ci-cd"
3. **Check popular sources**: Many skills come from `vercel-labs/agent-skills` or `ComposioHQ/awesome-claude-skills`

## When No Skills Are Found

If no relevant skills exist:

1. Acknowledge that no existing skill was found
2. Offer to help with the task directly using your general capabilities
3. Suggest the user could create their own skill with `npx skills init`

Example:

```
I searched for skills related to "xyz" but didn't find any matches.
I can still help you with this task directly! Would you like me to proceed?

If this is something you do often, you could create your own skill:
npx skills init my-xyz-skill
```
