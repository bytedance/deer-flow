---
description: Generate contextual briefings for legal work — daily summary, topic research, or incident response
argument-hint: "[daily | topic <query> | incident]"
---

# /brief -- Legal Team Briefing

> If you see unfamiliar placeholders or need to check which tools are connected, see [CONNECTORS.md](../CONNECTORS.md).

Generate contextual briefings for legal work. Supports three modes: daily brief, topic brief, and incident brief.

**Important**: This command assists with legal workflows but does not provide legal advice. Briefings should be reviewed by qualified legal professionals before being relied upon.

## Invocation

```
/brief daily              # Morning brief of legal-relevant items
/brief topic [query]      # Research brief on a specific legal question
/brief incident [topic]   # Rapid brief on a developing situation
```

If no mode is specified, ask the user which type of brief they need.

## Modes

---

### Daily Brief

A morning summary of everything a legal team member needs to know to start their day.

#### Sources to Scan

Check each connected source for legal-relevant items:

**Email (if connected):**
- New contract requests or review requests
- Compliance questions or reports
- Responses from counterparties on active negotiations
- Flagged or urgent items from the legal team inbox
- External counsel communications
- Regulatory or legal update newsletters

**Calendar (if connected):**
- Today's meetings that need legal prep (board meetings, deal reviews, vendor calls)
- Upcoming deadlines this week (contract expirations, filing deadlines, response deadlines)
- Recurring legal team syncs

**Chat (if connected):**
- Overnight messages in legal team channels
- Direct messages requesting legal input
- Mentions of legal-relevant topics (contract, compliance, privacy, NDA, terms)
- Escalations or urgent requests

**CLM (if connected):**
- Contracts awaiting review or signature
- Approaching expiration dates (next 30 days)
- Newly executed agreements

**CRM (if connected):**
- Deals moving to stages that require legal involvement
- New opportunities flagged for legal review

#### Output Format

```
## Daily Legal Brief -- [Date]

### Urgent / Action Required
[Items needing immediate attention, sorted by urgency]

### Contract Pipeline
- **Awaiting Your Review**: [count and list]
- **Pending Counterparty Response**: [count and list]
- **Approaching Deadlines**: [items due this week]

### New Requests
[Contract review requests, NDA requests, compliance questions received since last brief]

### Calendar Today
[Meetings with legal relevance and what prep is needed]

### Team Activity
[Key messages or updates from legal team channels]

### This Week's Deadlines
[Upcoming deadlines and filing dates]

### Sources Not Available
[Any sources that were not connected or returned errors]
```

---

### Topic Brief

Research and brief on a specific legal question or topic across available sources.

#### Workflow

1. Accept the topic query from the user
2. Search across connected sources:
   - **Documents**: Internal memos, prior analyses, playbooks, precedent
   - **Email**: Prior communications on the topic
   - **Chat**: Team discussions about the topic
   - **CLM**: Related contracts or clauses
3. Synthesize findings into a structured brief

#### Output Format

```
## Topic Brief: [Topic]

### Summary
[2-3 sentence executive summary of findings]

### Background
[Context and history from internal sources]

### Current State
[What the organization's current position or approach is, based on available documents]

### Key Considerations
[Important factors, risks, or open questions]

### Internal Precedent
[Prior decisions, memos, or positions found in internal sources]

### Gaps
[What information is missing or what sources were not available]

### Recommended Next Steps
[What the user should do with this information]
```

#### Important Notes
- Topic briefs synthesize what is available in connected sources; they do not substitute for formal legal research
- If the topic requires current legal authority or case law, recommend the user consult a legal research platform (Westlaw, Lexis, etc.) or outside counsel
- Always note the limitations of the sources searched

---

### Incident Brief

Rapid briefing for developing situations that require immediate legal attention (data breaches, litigation threats, regulatory inquiries, IP disputes, etc.).

#### Workflow

1. Accept the incident topic or description
2. Rapidly scan all connected sources for relevant context:
   - **Email**: Communications about the incident
   - **Chat**: Real-time discussions and escalations
   - **Documents**: Relevant policies, response plans, insurance coverage
   - **Calendar**: Scheduled response meetings
   - **CLM**: Affected contracts, indemnification provisions, insurance requirements
3. Compile into an actionable incident brief

#### Output Format

```
## Incident Brief: [Topic]
**Prepared**: [timestamp]
**Classification**: [severity assessment if determinable]

### Situation Summary
[What is known about the incident]

### Timeline
[Chronological summary of events based on available sources]

### Immediate Legal Considerations
[Regulatory notification requirements, preservation obligations, privilege concerns]

### Relevant Agreements
[Contracts, insurance policies, or other agreements that may be implicated]

### Internal Response
[What response activity has already occurred based on email/chat]

### Key Contacts
[Relevant internal and external contacts identified from sources]

### Recommended Immediate Actions
1. [Most urgent action]
2. [Second priority]
3. [etc.]

### Information Gaps
[What is not yet known and needs to be determined]

### Sources Checked
[What was searched and what was not available]
```

#### Important Notes for Incident Briefs
- Speed matters. Produce the brief quickly with available information rather than waiting for complete information
- Flag any litigation hold or preservation obligations immediately
- Note privilege considerations (mark the brief as attorney-client privileged / work product if appropriate)
- If the incident may involve a data breach, flag applicable notification deadlines (e.g., 72 hours for GDPR)
- Recommend outside counsel engagement if the matter is significant

## General Notes

- If sources are unavailable, note the gaps prominently so the user knows what was not checked
- For daily briefs, learn the user's preferences over time (what they find useful, what they want filtered out)
- Briefs should be actionable: every item should have a clear next step or reason for inclusion
- Keep briefs concise. Link to source materials rather than reproducing them in full
