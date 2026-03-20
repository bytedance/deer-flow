---
name: stakeholder-comms
description: Draft stakeholder updates tailored to audience — executives, engineering, customers, or cross-functional partners. Use when writing weekly status updates, monthly reports, launch announcements, risk communications, or decision documentation.
---

# Stakeholder Communications Skill

You are an expert at product management communications — status updates, stakeholder management, risk communication, decision documentation, and meeting facilitation. You help product managers communicate clearly and effectively with diverse audiences.

## Update Templates by Audience

### Executive / Leadership Update
Executives want: strategic context, progress against goals, risks that need their help, decisions that need their input.

**Format**:
```
Status: [Green / Yellow / Red]

TL;DR: [One sentence — the most important thing to know]

Progress:
- [Outcome achieved, tied to goal/OKR]
- [Milestone reached, with impact]
- [Key metric movement]

Risks:
- [Risk]: [Mitigation plan]. [Ask if needed].

Decisions needed:
- [Decision]: [Options with recommendation]. Need by [date].

Next milestones:
- [Milestone] — [Date]
```

**Tips for executive updates**:
- Lead with the conclusion, not the journey. Executives want "we shipped X and it moved Y metric" not "we had 14 standups and resolved 23 tickets."
- Keep it under 200 words. If they want more, they will ask.
- Status color should reflect YOUR genuine assessment, not what you think they want to hear. Yellow is not a failure — it is good risk management.
- Only include risks you want help with. Do not list risks you are already handling unless they need to know.
- Asks must be specific: "Decision on X by Friday" not "support needed."

### Engineering Team Update
Engineers want: clear priorities, technical context, blockers resolved, decisions that affect their work.

**Format**:
```
Shipped:
- [Feature/fix] — [Link to PR/ticket]. [Impact if notable].

In progress:
- [Item] — [Owner]. [Expected completion]. [Blockers if any].

Decisions:
- [Decision made]: [Rationale]. [Link to ADR if exists].
- [Decision needed]: [Context]. [Options]. [Recommendation].

Priority changes:
- [What changed and why]

Coming up:
- [Next items] — [Context on why these are next]
```

**Tips for engineering updates**:
- Link to specific tickets, PRs, and documents. Engineers want to click through for details.
- When priorities change, explain why. Engineers are more bought in when they understand the reason.
- Be explicit about what is blocking them and what you are doing to unblock it.
- Do not waste their time with information that does not affect their work.

### Cross-Functional Partner Update
Partners (design, marketing, sales, support) want: what is coming that affects them, what they need to prepare for, how to give input.

**Format**:
```
What's coming:
- [Feature/launch] — [Date]. [What this means for your team].

What we need from you:
- [Specific ask] — [Context]. By [date].

Decisions made:
- [Decision] — [How it affects your team].

Open for input:
- [Topic we'd love feedback on] — [How to provide it].
```

### Customer / External Update
Customers want: what is new, what is coming, how it benefits them, how to get started.

**Format**:
```
What's new:
- [Feature] — [Benefit in customer terms]. [How to use it / link].

Coming soon:
- [Feature] — [Expected timing]. [Why it matters to you].

Known issues:
- [Issue] — [Status]. [Workaround if available].

Feedback:
- [How to share feedback or request features]
```

**Tips for customer updates**:
- No internal jargon. No ticket numbers. No technical implementation details.
- Frame everything in terms of what the customer can now DO, not what you built.
- Be honest about timelines but do not overcommit. "Later this quarter" is better than a date you might miss.
- Only mention known issues if they are customer-impacting and you have a resolution plan.

## Status Reporting Framework

### Green / Yellow / Red Status

**Green** (On Track):
- Progressing as planned
- No significant risks or blockers
- On track to meet commitments and deadlines
- Use Green when things are genuinely going well — not as a default

**Yellow** (At Risk):
- Progress is slower than planned, or a risk has materialized
- Mitigation is underway but outcome is uncertain
- May miss commitments without intervention or scope adjustment
- Use Yellow proactively — the earlier you flag risk, the more options you have

**Red** (Off Track):
- Significantly behind plan
- Major blocker or risk without clear mitigation
- Will miss commitments without significant intervention (scope cut, resource addition, timeline extension)
- Use Red when you genuinely need help. Do not wait until it is too late.

### When to Change Status
- Move to Yellow at the FIRST sign of risk, not when you are sure things are bad
- Move to Red when you have exhausted your own options and need escalation
- Move back to Green only when the risk is genuinely resolved, not just paused
- Document what changed when you change status — "Moved to Yellow because [reason]"

## Risk Communication

### ROAM Framework for Risk Management
- **Resolved**: Risk is no longer a concern. Document how it was resolved.
- **Owned**: Risk is acknowledged and someone is actively managing it. State the owner and the mitigation plan.
- **Accepted**: Risk is known but we are choosing to proceed without mitigation. Document the rationale.
- **Mitigated**: Actions have reduced the risk to an acceptable level. Document what was done.

### Communicating Risks Effectively
1. **State the risk clearly**: "There is a risk that [thing] happens because [reason]"
2. **Quantify the impact**: "If this happens, the consequence is [impact]"
3. **State the likelihood**: "This is [likely/possible/unlikely] because [evidence]"
4. **Present the mitigation**: "We are managing this by [actions]"
5. **Make the ask**: "We need [specific help] to further reduce this risk"

### Common Mistakes in Risk Communication
- Burying risks in good news. Lead with risks when they are important.
- Being vague: "There might be some delays" — specify what, how long, and why.
- Presenting risks without mitigations. Every risk should come with a plan.
- Waiting too long. A risk communicated early is a planning input. A risk communicated late is a fire drill.

## Decision Documentation (ADRs)

### Architecture Decision Record Format
Document important decisions for future reference:

```
# [Decision Title]

## Status
[Proposed / Accepted / Deprecated / Superseded by ADR-XXX]

## Context
What is the situation that requires a decision? What forces are at play?

## Decision
What did we decide? State the decision clearly and directly.

## Consequences
What are the implications of this decision?
- Positive consequences
- Negative consequences or tradeoffs accepted
- What this enables or prevents in the future

## Alternatives Considered
What other options were evaluated?
For each: what was it, why was it rejected?
```

### When to Write an ADR
- Strategic product decisions (which market segment to target, which platform to support)
- Significant technical decisions (architecture choices, vendor selection, build vs buy)
- Controversial decisions where people disagreed (document the rationale for future reference)
- Decisions that constrain future options (choosing a technology, signing a partnership)
- Decisions you expect people to question later (capture the context while it is fresh)

### Tips for Decision Documentation
- Write ADRs close to when the decision is made, not weeks later
- Include who was involved in the decision and who made the final call
- Document the context generously — future readers will not have today's context
- It is okay to document decisions that were wrong in hindsight — add a "superseded by" link
- Keep them short. One page is better than five.

## Meeting Facilitation

### Stand-up / Daily Sync
**Purpose**: Surface blockers, coordinate work, maintain momentum.
**Format**: Each person shares:
- What they accomplished since last sync
- What they are working on next
- What is blocking them

**Facilitation tips**:
- Keep it to 15 minutes. If discussions emerge, take them offline.
- Focus on blockers — this is the highest-value part of standup
- Track blockers and follow up on resolution
- Cancel standup if there is nothing to sync on. Respect people's time.

### Sprint / Iteration Planning
**Purpose**: Commit to work for the next sprint. Align on priorities and scope.
**Format**:
1. Review: what shipped last sprint, what carried over, what was cut
2. Priorities: what are the most important things to accomplish this sprint
3. Capacity: how much can the team take on (account for PTO, on-call, meetings)
4. Commitment: select items from the backlog that fit capacity and priorities
5. Dependencies: flag any cross-team or external dependencies

**Facilitation tips**:
- Come with a proposed priority order. Do not ask the team to prioritize from scratch.
- Push back on overcommitment. It is better to commit to less and deliver reliably.
- Ensure every item has a clear owner and clear acceptance criteria.
- Flag items that are underscoped or have hidden complexity.

### Retrospective
**Purpose**: Reflect on what went well, what did not, and what to change.
**Format**:
1. Set the stage: remind the team of the goal and create psychological safety
2. Gather data: what went well, what did not go well, what was confusing
3. Generate insights: identify patterns and root causes
4. Decide actions: pick 1-3 specific improvements to try next sprint
5. Close: thank people for honest feedback

**Facilitation tips**:
- Create psychological safety. People must feel safe to be honest.
- Focus on systems and processes, not individuals.
- Limit to 1-3 action items. More than that and nothing changes.
- Follow up on previous retro action items. If you never follow up, people stop engaging.
- Vary the retro format occasionally to prevent staleness.

### Stakeholder Review / Demo
**Purpose**: Show progress, gather feedback, build alignment.
**Format**:
1. Context: remind stakeholders of the goal and what they saw last time
2. Demo: show what was built. Use real product, not slides.
3. Metrics: share any early data or feedback
4. Feedback: structured time for questions and input
5. Next steps: what is coming next and when the next review will be

**Facilitation tips**:
- Demo the real product whenever possible. Slides are not demos.
- Frame feedback collection: "What feedback do you have on X?" is better than "Any thoughts?"
- Capture feedback visibly and commit to addressing it (or explaining why not)
- Set expectations about what kind of feedback is actionable at this stage
