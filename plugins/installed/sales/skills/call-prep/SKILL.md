---
name: call-prep
description: Prepare for a sales call with account context, attendee research, and suggested agenda. Works standalone with user input and web research, supercharged when you connect your CRM, email, chat, or transcripts. Trigger with "prep me for my call with [company]", "I'm meeting with [company] prep me", "call prep [company]", or "get me ready for [meeting]".
---

# Call Prep

Get fully prepared for any sales call in minutes. This skill works with whatever context you provide, and gets significantly better when you connect your sales tools.

## How It Works

```
┌─────────────────────────────────────────────────────────────────┐
│                        CALL PREP                                 │
├─────────────────────────────────────────────────────────────────┤
│  ALWAYS (works standalone)                                       │
│  ✓ You tell me: company, meeting type, attendees                │
│  ✓ Web search: recent news, funding, leadership changes         │
│  ✓ Company research: what they do, size, industry               │
│  ✓ Output: prep brief with agenda and questions                 │
├─────────────────────────────────────────────────────────────────┤
│  SUPERCHARGED (when you connect your tools)                      │
│  + CRM: account history, contacts, opportunities, activities    │
│  + Email: recent threads, open questions, commitments           │
│  + Chat: internal discussions, colleague insights               │
│  + Transcripts: prior call recordings, key moments              │
│  + Calendar: auto-find meeting, pull attendees                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Getting Started

When you run this skill, I'll ask for what I need:

**Required:**
- Company or contact name
- Meeting type (discovery, demo, negotiation, check-in, etc.)

**Helpful if you have it:**
- Who's attending (names and titles)
- Any context you want me to know (paste prior notes, emails, etc.)

If you've connected your CRM, email, or other tools, I'll pull context automatically and skip the questions.

---

## Connectors (Optional)

Connect your tools to supercharge this skill:

| Connector | What It Adds |
|-----------|--------------|
| **CRM** | Account details, contact history, open deals, recent activities |
| **Email** | Recent threads with the company, open questions, attachments shared |
| **Chat** | Internal chat discussions (e.g. Slack) about the account, colleague insights |
| **Transcripts** | Prior call recordings, topics covered, competitor mentions |
| **Calendar** | Auto-find the meeting, pull attendees and description |

> **No connectors?** No problem. Just tell me about the meeting and paste any context you have. I'll research the rest.

---

## Output Format

```markdown
# Call Prep: [Company Name]

**Meeting:** [Type] — [Date/Time if known]
**Attendees:** [Names with titles]
**Your Goal:** [What you want to accomplish]

---

## Account Snapshot

| Field | Value |
|-------|-------|
| **Company** | [Name] |
| **Industry** | [Industry] |
| **Size** | [Employees / Revenue if known] |
| **Status** | [New prospect / Active opportunity / Customer] |
| **Last Touch** | [Date and summary] |

---

## Who You're Meeting

### [Name] — [Title]
- **Background:** [Career history, education if found]
- **LinkedIn:** [URL]
- **Role in Deal:** [Decision maker / Champion / Evaluator / etc.]
- **Last Interaction:** [Summary if known]
- **Talking Point:** [Something personal/professional to reference]

[Repeat for each attendee]

---

## Context & History

**What's happened so far:**
- [Key point from prior interactions]
- [Open commitments or action items]
- [Any concerns or objections raised]

**Recent news about [Company]:**
- [News item 1 — why it matters]
- [News item 2 — why it matters]

---

## Suggested Agenda

1. **Open** — [Reference last conversation or trigger event]
2. **[Topic 1]** — [Discovery question or value discussion]
3. **[Topic 2]** — [Address known concern or explore priority]
4. **[Topic 3]** — [Demo section / Proposal review / etc.]
5. **Next Steps** — [Propose clear follow-up with timeline]

---

## Discovery Questions

Ask these to fill gaps in your understanding:

1. [Question about their current situation]
2. [Question about pain points or priorities]
3. [Question about decision process and timeline]
4. [Question about success criteria]
5. [Question about other stakeholders]

---

## Potential Objections

| Objection | Suggested Response |
|-----------|-------------------|
| [Likely objection based on context] | [How to address it] |
| [Common objection for this stage] | [How to address it] |

---

## Internal Notes

[Any internal chat context (e.g. Slack), colleague insights, or competitive intel]

---

## After the Call

Run **call-follow-up** to:
- Extract action items
- Update your CRM
- Draft follow-up email
```

---

## Execution Flow

### Step 1: Gather Context

**If connectors available:**
```
1. Calendar → Find upcoming meeting matching company name
   - Pull: title, time, attendees, description, attachments

2. CRM → Query account
   - Pull: account details, all contacts, open opportunities
   - Pull: last 10 activities, any account notes

3. Email → Search recent threads
   - Query: emails with company domain (last 30 days)
   - Extract: key topics, open questions, commitments

4. Chat → Search internal discussions
   - Query: company name mentions (last 30 days)
   - Extract: colleague insights, competitive intel

5. Transcripts → Find prior calls
   - Pull: call recordings with this account
   - Extract: key moments, objections raised, topics covered
```

**If no connectors:**
```
1. Ask user:
   - "What company are you meeting with?"
   - "What type of meeting is this?"
   - "Who's attending? (names and titles if you know)"
   - "Any context you want me to know? (paste notes, emails, etc.)"

2. Accept whatever they provide and work with it
```

### Step 2: Research Supplement

**Always run (web search):**
```
1. "[Company] news" — last 30 days
2. "[Company] funding" — recent announcements
3. "[Company] leadership" — executive changes
4. "[Company] + [industry] trends" — relevant context
5. Attendee LinkedIn profiles — background research
```

### Step 3: Synthesize & Generate

```
1. Combine all sources into unified context
2. Identify gaps in understanding → generate discovery questions
3. Anticipate objections based on stage and history
4. Create suggested agenda tailored to meeting type
5. Output formatted prep brief
```

---

## Meeting Type Variations

### Discovery Call
- Focus on: Understanding their world, pain points, priorities
- Agenda emphasis: Questions > Talking
- Key output: Qualification signals, next step proposal

### Demo / Presentation
- Focus on: Their specific use case, tailored examples
- Agenda emphasis: Show relevant features, get feedback
- Key output: Technical requirements, decision timeline

### Negotiation / Proposal Review
- Focus on: Addressing concerns, justifying value
- Agenda emphasis: Handle objections, close gaps
- Key output: Path to agreement, clear next steps

### Check-in / QBR
- Focus on: Value delivered, expansion opportunities
- Agenda emphasis: Review wins, surface new needs
- Key output: Renewal confidence, upsell pipeline

---

## Tips for Better Prep

1. **More context = better prep** — Paste emails, notes, anything you have
2. **Name the attendees** — Even just titles help me research
3. **State your goal** — "I want to get them to agree to a pilot"
4. **Flag concerns** — "They mentioned budget is tight"

---

## Related Skills

- **account-research** — Deep dive on a company before first contact
- **call-follow-up** — Process call notes and execute post-call workflow
- **draft-outreach** — Write personalized outreach after research
