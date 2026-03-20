---
description: Draft a knowledge base article from a resolved issue or common question
argument-hint: "<resolved issue or ticket>"
---

# KB Article

> If you see unfamiliar placeholders or need to check which tools are connected, see [CONNECTORS.md](../CONNECTORS.md).

Draft a publish-ready knowledge base article from a resolved support issue, common question, or documented workaround. Structures the content for searchability and self-service.

## Usage

```
/kb-article <resolved issue, ticket reference, or topic description>
```

Examples:
- `/kb-article How to configure SSO with Okta — resolved this for 3 customers last month`
- `/kb-article Ticket #4521 — customer couldn't export data over 10k rows`
- `/kb-article Common question: how to set up webhook notifications`
- `/kb-article Known issue: dashboard charts not loading on Safari 16`

## Workflow

### 1. Understand the Source Material

Parse the input to identify:

- **What was the problem?** The original issue, question, or error
- **What was the solution?** The resolution, workaround, or answer
- **Who does this affect?** User type, plan level, or configuration
- **How common is this?** One-off or recurring issue
- **What article type fits best?** Use the article types from the **knowledge-management** skill (how-to, troubleshooting, FAQ, known issue, reference)

If a ticket reference is provided, look up the full context:

- **~~support platform**: Pull the ticket thread, resolution, and any internal notes
- **~~knowledge base**: Check if a similar article already exists (update vs. create new)
- **~~project tracker**: Check if there's a related bug or feature request

### 2. Draft the Article

Using the article structure and formatting standards from the **knowledge-management** skill:

- Follow the template for the chosen article type (how-to, troubleshooting, FAQ, known issue, or reference)
- Apply the searchability best practices: customer-language title, plain-language opening sentence, exact error messages, common synonyms
- Keep it scannable: headers, numbered steps, short paragraphs

### 3. Generate the Article

Present the draft with metadata:

```
## KB Article Draft

**Title:** [Article title]
**Type:** [How-to / Troubleshooting / FAQ / Known Issue / Reference]
**Category:** [Product area or topic]
**Tags:** [Searchable tags]
**Audience:** [All users / Admins / Developers / Specific plan]

---

[Full article content — using the appropriate template
from the knowledge-management skill]

---

### Publishing Notes
- **Source:** [Ticket #, customer conversation, or internal discussion]
- **Existing articles to update:** [If this overlaps with existing content]
- **Review needed from:** [SME or team if technical accuracy needs verification]
- **Suggested review date:** [When to revisit for accuracy]
```

### 4. Offer Next Steps

After generating the article:
- "Want me to check if a similar article already exists in your ~~knowledge base?"
- "Should I adjust the technical depth for a different audience?"
- "Want me to draft a companion article (e.g., a how-to to go with this troubleshooting guide)?"
- "Should I create an internal-only version with additional technical detail?"
