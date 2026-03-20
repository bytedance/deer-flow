---
description: Triage and prioritize a support ticket or customer issue
argument-hint: "<ticket or issue description>"
---

# Triage

> If you see unfamiliar placeholders or need to check which tools are connected, see [CONNECTORS.md](../CONNECTORS.md).

Categorize, prioritize, and route an incoming support ticket or customer issue. Produces a structured triage assessment with a suggested initial response.

## Usage

```
/triage <ticket text, customer message, or issue description>
```

Examples:
- `/triage Customer says their dashboard has been showing a blank page since this morning`
- `/triage "I was charged twice for my subscription this month"`
- `/triage User can't connect their SSO — getting a 403 error on the callback URL`
- `/triage Feature request: they want to export reports as PDF`

## Workflow

### 1. Parse the Issue

Read the input and extract:

- **Core problem**: What is the customer actually experiencing?
- **Symptoms**: What specific behavior or error are they seeing?
- **Customer context**: Who is this? Any account details, plan level, or history available?
- **Urgency signals**: Are they blocked? Is this production? How many users affected?
- **Emotional state**: Frustrated, confused, matter-of-fact, escalating?

### 2. Categorize and Prioritize

Using the category taxonomy and priority framework from the **ticket-triage** skill:

- Assign a **primary category** (bug, how-to, feature request, billing, account, integration, security, data, performance) and an optional secondary category
- Assign a **priority** (P1–P4) based on impact and urgency
- Identify the **product area** the issue maps to

### 3. Check for Duplicates and Known Issues

Before routing, check available sources:

- **~~support platform**: Search for similar open or recently resolved tickets
- **~~knowledge base**: Check for known issues or existing documentation
- **~~project tracker**: Check if there's an existing bug report or feature request

### 4. Determine Routing

Using the routing rules from the **ticket-triage** skill, recommend which team or queue should handle this based on category and complexity.

### 5. Generate Triage Output

```
## Triage: [One-line issue summary]

**Category:** [Primary] / [Secondary if applicable]
**Priority:** [P1-P4] — [Brief justification]
**Product area:** [Area/team]

### Issue Summary
[2-3 sentence summary of what the customer is experiencing]

### Key Details
- **Customer:** [Name/account if known]
- **Impact:** [Who and what is affected]
- **Workaround:** [Available / Not available / Unknown]
- **Related tickets:** [Links to similar issues if found]
- **Known issue:** [Yes — link / No / Checking]

### Routing Recommendation
**Route to:** [Team or queue]
**Why:** [Brief reasoning]

### Suggested Initial Response
[Draft first response to the customer — acknowledge the issue,
set expectations, provide workaround if available.
Use the auto-response templates from the ticket-triage skill
as a starting point.]

### Internal Notes
- [Any additional context for the agent picking this up]
- [Reproduction hints if it's a bug]
- [Escalation triggers to watch for]
```

### 6. Offer Next Steps

After presenting the triage:
- "Want me to draft a full response to the customer?"
- "Should I search for more context on this issue?"
- "Want me to check if this is a known bug in the tracker?"
- "Should I escalate this? I can package it with /escalate."
