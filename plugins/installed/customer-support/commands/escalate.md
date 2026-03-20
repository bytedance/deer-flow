---
description: Package an escalation for engineering, product, or leadership with full context
argument-hint: "<issue summary> [customer name]"
---

# Escalate

> If you see unfamiliar placeholders or need to check which tools are connected, see [CONNECTORS.md](../CONNECTORS.md).

Package a support issue into a structured escalation brief for engineering, product, or leadership. Gathers context, structures reproduction steps, assesses business impact, and identifies the right escalation target.

## Usage

```
/escalate <issue description> [customer name or account]
```

Examples:
- `/escalate API returning 500 errors intermittently for Acme Corp`
- `/escalate Data export is missing rows — 3 customers reported this week`
- `/escalate SSO login loop affecting all Enterprise customers`
- `/escalate Customer threatening to churn over missing audit log feature`

## Workflow

### 1. Understand the Issue

Parse the input and determine:

- **What's broken or needed**: The core technical or product issue
- **Who's affected**: Specific customer(s), segment, or all users
- **How long**: When did this start? How long has the customer been waiting?
- **What's been tried**: Any troubleshooting or workarounds attempted
- **Why escalate now**: What makes this need attention beyond normal support

Use the "When to Escalate vs. Handle in Support" criteria from the **escalation** skill to confirm this warrants escalation.

### 2. Gather Context

Pull together relevant information from available sources:

- **~~support platform**: Related tickets, timeline of communications, previous troubleshooting
- **~~CRM** (if connected): Account details, key contacts, previous escalations
- **~~chat**: Internal discussions about this issue, similar reports from other customers
- **~~project tracker** (if connected): Related bug reports or feature requests, engineering status
- **~~knowledge base**: Known issues or workarounds, relevant documentation

### 3. Assess Business Impact

Using the impact dimensions from the **escalation** skill, quantify:

- **Breadth**: How many customers/users affected? Growing?
- **Depth**: Blocked vs. inconvenienced?
- **Duration**: How long has this been going on?
- **Revenue**: ARR at risk? Pending deals affected?
- **Time pressure**: Hard deadline?

### 4. Determine Escalation Target

Using the escalation tiers from the **escalation** skill, identify the right target: L2 Support, Engineering, Product, Security, or Leadership.

### 5. Structure Reproduction Steps (for bugs)

If the issue is a bug, follow the reproduction step best practices from the **escalation** skill to document clear repro steps with environment details and evidence.

### 6. Generate Escalation Brief

```
## ESCALATION: [One-line summary]

**Severity:** [Critical / High / Medium]
**Target team:** [Engineering / Product / Security / Leadership]
**Reported by:** [Your name/team]
**Date:** [Today's date]

### Impact
- **Customers affected:** [Who and how many]
- **Workflow impact:** [What they can't do]
- **Revenue at risk:** [If applicable]
- **Time in queue:** [How long this has been an issue]

### Issue Description
[Clear, concise description of the problem — 3-5 sentences]

### What's Been Tried
1. [Troubleshooting step and result]
2. [Troubleshooting step and result]
3. [Troubleshooting step and result]

### Reproduction Steps
[If applicable — follow the format from the escalation skill]

### Customer Communication
- **Last update to customer:** [Date and what was communicated]
- **Customer expectation:** [What they're expecting and by when]
- **Escalation risk:** [Will they escalate further if not resolved by X?]

### What's Needed
- [Specific ask — "investigate root cause", "prioritize fix",
  "make product decision on X", "approve exception for Y"]
- **Deadline:** [When this needs resolution or an update]

### Supporting Context
- [Related tickets or links]
- [Internal discussion threads]
- [Documentation or logs]
```

### 7. Offer Next Steps

After generating the escalation:
- "Want me to post this in a ~~chat channel for the target team?"
- "Should I update the customer with an interim response?"
- "Want me to set a follow-up reminder to check on this?"
- "Should I draft a customer-facing update with the current status?"
