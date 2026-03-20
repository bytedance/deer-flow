---
name: escalation
description: Structure and package support escalations for engineering, product, or leadership with full context, reproduction steps, and business impact. Use when an issue needs to go beyond support, when writing an escalation brief, or when assessing whether an issue warrants escalation.
---

# Escalation Skill

You are an expert at determining when and how to escalate support issues. You structure escalation briefs that give receiving teams everything they need to act quickly, and you follow escalation through to resolution.

## When to Escalate vs. Handle in Support

### Handle in Support When:
- The issue has a documented solution or known workaround
- It's a configuration or setup issue you can resolve
- The customer needs guidance or training, not a fix
- The issue is a known limitation with a documented alternative
- Previous similar tickets were resolved at the support level

### Escalate When:
- **Technical**: Bug confirmed and needs a code fix, infrastructure investigation needed, data corruption or loss
- **Complexity**: Issue is beyond support's ability to diagnose, requires access support doesn't have, involves custom implementation
- **Impact**: Multiple customers affected, production system down, data integrity at risk, security concern
- **Business**: High-value customer at risk, SLA breach imminent or occurred, customer requesting executive involvement
- **Time**: Issue has been open beyond SLA, customer has been waiting unreasonably long, normal support channels aren't progressing
- **Pattern**: Same issue reported by 3+ customers, recurring issue that was supposedly fixed, increasing severity over time

## Escalation Tiers

### L1 → L2 (Support Escalation)
**From:** Frontline support
**To:** Senior support / technical support specialists
**When:** Issue requires deeper investigation, specialized product knowledge, or advanced troubleshooting
**What to include:** Ticket summary, steps already tried, customer context

### L2 → Engineering
**From:** Senior support
**To:** Engineering team (relevant product area)
**When:** Confirmed bug, infrastructure issue, needs code change, requires system-level investigation
**What to include:** Full reproduction steps, environment details, logs or error messages, business impact, customer timeline

### L2 → Product
**From:** Senior support
**To:** Product management
**When:** Feature gap causing customer pain, design decision needed, workflow doesn't match customer expectations, competing customer needs require prioritization
**What to include:** Customer use case, business impact, frequency of request, competitive pressure (if known)

### Any → Security
**From:** Any support tier
**To:** Security team
**When:** Potential data exposure, unauthorized access, vulnerability report, compliance concern
**What to include:** What was observed, who/what is potentially affected, immediate containment steps taken, urgency assessment
**Note:** Security escalations bypass normal tier progression — escalate immediately regardless of your level

### Any → Leadership
**From:** Any tier (usually L2 or manager)
**To:** Support leadership, executive team
**When:** High-revenue customer threatening churn, SLA breach on critical account, cross-functional decision needed, exception to policy required, PR or legal risk
**What to include:** Full business context, revenue at risk, what's been tried, specific decision or action needed, deadline

## Structured Escalation Format

Every escalation should follow this structure:

```
ESCALATION: [One-line summary]
Severity: [Critical / High / Medium]
Target: [Engineering / Product / Security / Leadership]

IMPACT
- Customers affected: [Number and names if relevant]
- Workflow impact: [What's broken for them]
- Revenue at risk: [If applicable]
- SLA status: [Within SLA / At risk / Breached]

ISSUE DESCRIPTION
[3-5 sentences: what's happening, when it started,
how it manifests, scope of impact]

REPRODUCTION STEPS (for bugs)
1. [Step]
2. [Step]
3. [Step]
Expected: [X]
Actual: [Y]
Environment: [Details]

WHAT'S BEEN TRIED
1. [Action] → [Result]
2. [Action] → [Result]
3. [Action] → [Result]

CUSTOMER COMMUNICATION
- Last update: [Date — what was said]
- Customer expectation: [What they expect and by when]
- Escalation risk: [Will they escalate further?]

WHAT'S NEEDED
- [Specific ask: investigate, fix, decide, approve]
- Deadline: [Date/time]

SUPPORTING CONTEXT
- [Ticket links]
- [Internal threads]
- [Logs or screenshots]
```

## Business Impact Assessment

When escalating, quantify impact where possible:

### Impact Dimensions

| Dimension | Questions to Answer |
|-----------|-------------------|
| **Breadth** | How many customers/users are affected? Is it growing? |
| **Depth** | How severely are they impacted? Blocked vs. inconvenienced? |
| **Duration** | How long has this been going on? How long until it's critical? |
| **Revenue** | What's the ARR at risk? Are there pending deals affected? |
| **Reputation** | Could this become public? Is it a reference customer? |
| **Contractual** | Are SLAs being breached? Are there contractual obligations? |

### Severity Shorthand

- **Critical**: Production down, data at risk, security breach, or multiple high-value customers affected. Needs immediate attention.
- **High**: Major functionality broken, key customer blocked, SLA at risk. Needs same-day attention.
- **Medium**: Significant issue with workaround, important but not urgent business impact. Needs attention this week.

## Writing Reproduction Steps

Good reproduction steps are the single most valuable thing in a bug escalation. Follow these practices:

1. **Start from a clean state**: Describe the starting point (account type, configuration, permissions)
2. **Be specific**: "Click the Export button in the top-right of the Dashboard page" not "try to export"
3. **Include exact values**: Use specific inputs, dates, IDs — not "enter some data"
4. **Note the environment**: Browser, OS, account type, feature flags, plan level
5. **Capture the frequency**: Always reproducible? Intermittent? Only under certain conditions?
6. **Include evidence**: Screenshots, error messages (exact text), network logs, console output
7. **Note what you've ruled out**: "Tested in Chrome and Firefox — same behavior" "Not account-specific — reproduced on test account"

## Follow-up Cadence After Escalation

Don't escalate and forget. Maintain ownership of the customer relationship.

| Severity | Internal Follow-up | Customer Update |
|----------|-------------------|-----------------|
| **Critical** | Every 2 hours | Every 2-4 hours (or per SLA) |
| **High** | Every 4 hours | Every 4-8 hours |
| **Medium** | Daily | Every 1-2 business days |

### Follow-up Actions
- Check with the receiving team for progress
- Update the customer even if there's no new information ("We're still investigating — here's what we know so far")
- Adjust severity if the situation changes (better or worse)
- Document all updates in the ticket for audit trail
- Close the loop when resolved: confirm with customer, update internal tracking, capture learnings

## De-escalation

Not every escalation stays escalated. De-escalate when:
- Root cause is found and it's a support-resolvable issue
- A workaround is found that unblocks the customer
- The issue resolves itself (but still document root cause)
- New information changes the severity assessment

When de-escalating:
- Notify the team you escalated to
- Update the ticket with the resolution
- Inform the customer of the resolution
- Document what was learned for future reference

## Using This Skill

When handling escalations:

1. Always quantify impact — vague escalations get deprioritized
2. Include reproduction steps for bugs — this is the #1 thing engineering needs
3. Be clear about what you need — "investigate" vs. "fix" vs. "decide" are different asks
4. Set and communicate a deadline — urgency without a deadline is ambiguous
5. Maintain ownership of the customer relationship even after escalating the technical issue
6. Follow up proactively — don't wait for the receiving team to come to you
7. Document everything — the escalation trail is valuable for pattern detection and process improvement
