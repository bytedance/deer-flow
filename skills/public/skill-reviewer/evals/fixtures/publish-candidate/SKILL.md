---
name: example-safe-skill
description: Reviews a single Markdown troubleshooting note for clarity. Invoke when the user asks to improve a provided troubleshooting note.
allowed-tools: []
---

# Example Safe Skill

Use this skill only when the user provides one troubleshooting note and asks for clarity feedback.

1. Confirm the note is present.
2. Identify unclear steps, missing prerequisites, and unverifiable claims.
3. Return concise rewrite suggestions.

Do not edit files. Do not fetch external URLs. Stop after reporting recommendations.
