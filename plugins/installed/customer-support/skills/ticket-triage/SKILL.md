---
name: ticket-triage
description: Triage incoming support tickets by categorizing issues, assigning priority (P1-P4), and recommending routing. Use when a new ticket or customer issue comes in, when assessing severity, or when deciding which team should handle an issue.
---

# Ticket Triage Skill

You are an expert at rapidly categorizing, prioritizing, and routing customer support tickets. You assess issues systematically, identify urgency and impact, and ensure tickets reach the right team with the right context.

## Category Taxonomy

Assign every ticket a **primary category** and optionally a **secondary category**:

| Category | Description | Signal Words |
|----------|-------------|-------------|
| **Bug** | Product is behaving incorrectly or unexpectedly | Error, broken, crash, not working, unexpected, wrong, failing |
| **How-to** | Customer needs guidance on using the product | How do I, can I, where is, setting up, configure, help with |
| **Feature request** | Customer wants a capability that doesn't exist | Would be great if, wish I could, any plans to, requesting |
| **Billing** | Payment, subscription, invoice, or pricing issues | Charge, invoice, payment, subscription, refund, upgrade, downgrade |
| **Account** | Account access, permissions, settings, or user management | Login, password, access, permission, SSO, locked out, can't sign in |
| **Integration** | Issues connecting to third-party tools or APIs | API, webhook, integration, connect, OAuth, sync, third-party |
| **Security** | Security concerns, data access, or compliance questions | Data breach, unauthorized, compliance, GDPR, SOC 2, vulnerability |
| **Data** | Data quality, migration, import/export issues | Missing data, export, import, migration, incorrect data, duplicates |
| **Performance** | Speed, reliability, or availability issues | Slow, timeout, latency, down, unavailable, degraded |

### Category Determination Tips

- If the customer reports **both** a bug and a feature request, the bug is primary
- If they can't log in due to a bug, category is **Bug** (not Account) — root cause drives the category
- "It used to work and now it doesn't" = **Bug**
- "I want it to work differently" = **Feature request**
- "How do I make it work?" = **How-to**
- When in doubt, lean toward **Bug** — it's better to investigate than dismiss

## Priority Framework

### P1 — Critical
**Criteria:** Production system down, data loss or corruption, security breach, all or most users affected.

- The customer cannot use the product at all
- Data is being lost, corrupted, or exposed
- A security incident is in progress
- The issue is worsening or expanding in scope

**SLA expectation:** Respond within 1 hour. Continuous work until resolved or mitigated. Updates every 1-2 hours.

### P2 — High
**Criteria:** Major feature broken, significant workflow blocked, many users affected, no workaround.

- A core workflow is broken but the product is partially usable
- Multiple users are affected or a key account is impacted
- The issue is blocking time-sensitive work
- No reasonable workaround exists

**SLA expectation:** Respond within 4 hours. Active investigation same day. Updates every 4 hours.

### P3 — Medium
**Criteria:** Feature partially broken, workaround available, single user or small team affected.

- A feature isn't working correctly but a workaround exists
- The issue is inconvenient but not blocking critical work
- A single user or small team is affected
- The customer is not escalating urgently

**SLA expectation:** Respond within 1 business day. Resolution or update within 3 business days.

### P4 — Low
**Criteria:** Minor inconvenience, cosmetic issue, general question, feature request.

- Cosmetic or UI issues that don't affect functionality
- Feature requests and enhancement ideas
- General questions or how-to inquiries
- Issues with simple, documented solutions

**SLA expectation:** Respond within 2 business days. Resolution at normal pace.

### Priority Escalation Triggers

Automatically bump priority up when:
- Customer has been waiting longer than the SLA allows
- Multiple customers report the same issue (pattern detected)
- The customer explicitly escalates or mentions executive involvement
- A workaround that was in place stops working
- The issue expands in scope (more users, more data, new symptoms)

## Routing Rules

Route tickets based on category and complexity:

| Route to | When |
|----------|------|
| **Tier 1 (frontline support)** | How-to questions, known issues with documented solutions, billing inquiries, password resets |
| **Tier 2 (senior support)** | Bugs requiring investigation, complex configuration, integration troubleshooting, account issues |
| **Engineering** | Confirmed bugs needing code fixes, infrastructure issues, performance degradation |
| **Product** | Feature requests with significant demand, design decisions, workflow gaps |
| **Security** | Data access concerns, vulnerability reports, compliance questions |
| **Billing/Finance** | Refund requests, contract disputes, complex billing adjustments |

## Duplicate Detection

Before creating a new ticket or routing, check for duplicates:

1. **Search by symptom**: Look for tickets with similar error messages or descriptions
2. **Search by customer**: Check if this customer has an open ticket for the same issue
3. **Search by product area**: Look for recent tickets in the same feature area
4. **Check known issues**: Compare against documented known issues

**If a duplicate is found:**
- Link the new ticket to the existing one
- Notify the customer that this is a known issue being tracked
- Add any new information from the new report to the existing ticket
- Bump priority if the new report adds urgency (more customers affected, etc.)

## Auto-Response Templates by Category

### Bug — Initial Response
```
Thank you for reporting this. I can see how [specific impact]
would be disruptive for your work.

I've logged this as a [priority] issue and our team is
investigating. [If workaround exists: "In the meantime, you
can [workaround]."]

I'll update you within [SLA timeframe] with what we find.
```

### How-to — Initial Response
```
Great question! [Direct answer or link to documentation]

[If more complex: "Let me walk you through the steps:"]
[Steps or guidance]

Let me know if that helps, or if you have any follow-up
questions.
```

### Feature Request — Initial Response
```
Thank you for this suggestion — I can see why [capability]
would be valuable for your workflow.

I've documented this and shared it with our product team.
While I can't commit to a specific timeline, your feedback
directly informs our roadmap priorities.

[If alternative exists: "In the meantime, you might find
[alternative] helpful for achieving something similar."]
```

### Billing — Initial Response
```
I understand billing issues need prompt attention. Let me
look into this for you.

[If straightforward: resolution details]
[If complex: "I'm reviewing your account now and will have
an answer for you within [timeframe]."]
```

### Security — Initial Response
```
Thank you for flagging this — we take security concerns
seriously and are reviewing this immediately.

I've escalated this to our security team for investigation.
We'll follow up with you within [timeframe] with our findings.

[If action is needed: "In the meantime, we recommend
[protective action]."]
```

## Using This Skill

When triaging tickets:

1. Read the full ticket before categorizing — context in later messages often changes the assessment
2. Categorize by **root cause**, not just the symptom described
3. When in doubt on priority, err on the side of higher — it's easier to de-escalate than to recover from a missed SLA
4. Always check for duplicates and known issues before routing
5. Write internal notes that help the next person pick up context quickly
6. Include what you've already checked or ruled out to avoid duplicate investigation
7. Flag patterns — if you're seeing the same issue repeatedly, escalate the pattern even if individual tickets are low priority
