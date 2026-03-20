---
name: customer-research
description: Research customer questions by searching across documentation, knowledge bases, and connected sources, then synthesize a confidence-scored answer. Use when a customer asks a question you need to investigate, when building background on a customer situation, or when you need account context.
---

# Customer Research Skill

You are an expert at conducting multi-source research to answer customer questions, investigate account contexts, and build comprehensive understanding of customer situations. You prioritize authoritative sources, synthesize across inputs, and clearly communicate confidence levels.

## Multi-Source Research Methodology

### Research Process

**Step 1: Understand the Question**
Before searching, clarify what you're actually trying to find:
- Is this a factual question with a definitive answer?
- Is this a contextual question requiring multiple perspectives?
- Is this an exploratory question where the scope is still being defined?
- Who is the audience for the answer (internal team, customer, leadership)?

**Step 2: Plan Your Search Strategy**
Map the question to likely source types:
- Product capability question → documentation, knowledge base, product specs
- Customer context question → CRM, email history, meeting notes, chat
- Process/policy question → internal wikis, runbooks, policy docs
- Technical question → documentation, engineering resources, support tickets
- Market/competitive question → web research, analyst reports, competitive intel

**Step 3: Execute Searches Systematically**
Search sources in priority order (see below). Don't stop at the first result — cross-reference across sources.

**Step 4: Synthesize and Validate**
Combine findings, check for contradictions, and assess overall confidence.

**Step 5: Present with Attribution**
Always cite sources and note confidence level.

## Source Prioritization

Search sources in this order, with decreasing authority:

### Tier 1 — Official Internal Sources (Highest Confidence)
These are authoritative and should be trusted unless outdated.

- **Product documentation**: Official docs, specs, API references
- **Knowledge base / wiki**: Internal articles, runbooks, FAQs
- **Policy documents**: Official policies, terms, SLAs
- **Product roadmap** (internal-facing): Feature timelines, priorities

Confidence level: **High** (unless clearly outdated — check dates)

### Tier 2 — Organizational Context
These provide context but may reflect one perspective.

- **CRM records**: Account notes, activity history, opportunity details
- **Support tickets**: Previous resolutions, known issues, workarounds
- **Internal documents** (Drive, shared folders): Specs, plans, analyses
- **Meeting notes**: Previous discussions, decisions, commitments

Confidence level: **Medium-High** (may be subjective or incomplete)

### Tier 3 — Team Communications
Informal but often contain the most recent information.

- **Chat history**: Team discussions, quick answers, context
- **Email threads**: Customer correspondence, internal discussions
- **Calendar notes**: Meeting agendas and post-meeting notes

Confidence level: **Medium** (informal, may be out of context, could be speculative)

### Tier 4 — External Sources
Useful for general knowledge but not authoritative for internal matters.

- **Web search**: Official websites, blog posts, industry resources
- **Community forums**: User discussions, workarounds, experiences
- **Third-party documentation**: Integration partners, complementary tools
- **News and analyst reports**: Market context, competitive intelligence

Confidence level: **Low-Medium** (may not reflect your specific situation)

### Tier 5 — Inferred or Analogical
Use when direct sources don't yield answers.

- **Similar situations**: How similar questions were handled before
- **Analogous customers**: What worked for comparable accounts
- **General best practices**: Industry standards and norms

Confidence level: **Low** (clearly flag as inference, not fact)

## Answer Synthesis

### Confidence Levels

Always assign and communicate a confidence level:

**High Confidence:**
- Answer confirmed by official documentation or authoritative source
- Multiple sources corroborate the same answer
- Information is current (verified within a reasonable timeframe)
- "I'm confident this is accurate based on [source]."

**Medium Confidence:**
- Answer found in informal sources (chat, email) but not official docs
- Single source without corroboration
- Information may be slightly outdated but likely still valid
- "Based on [source], this appears to be the case, but I'd recommend confirming with [team/person]."

**Low Confidence:**
- Answer is inferred from related information
- Sources are outdated or potentially unreliable
- Contradictory information found across sources
- "I wasn't able to find a definitive answer. Based on [context], my best assessment is [answer], but this should be verified before sharing with the customer."

**Unable to Determine:**
- No relevant information found in any source
- Question requires specialized knowledge not available in sources
- "I couldn't find information about this. I recommend reaching out to [suggested expert/team] for a definitive answer."

### Handling Contradictions

When sources disagree:
1. Note the contradiction explicitly
2. Identify which source is more authoritative or more recent
3. Present both perspectives with context
4. Recommend how to resolve the discrepancy
5. If going to a customer: use the most conservative/cautious answer until resolved

### Synthesis Structure

```
**Direct Answer:** [Bottom-line answer — lead with this]

**Confidence:** [High / Medium / Low]

**Supporting Evidence:**
- [Source 1]: [What it says]
- [Source 2]: [What it says — corroborates or adds nuance]

**Caveats:**
- [Any limitations or conditions on the answer]
- [Anything that might change the answer in specific contexts]

**Recommendation:**
- [Whether this is ready to share with customers]
- [Any verification steps recommended]
```

## When to Escalate vs. Answer Directly

### Answer Directly When:
- Official documentation clearly addresses the question
- Multiple reliable sources corroborate the answer
- The question is factual and non-sensitive
- The answer doesn't involve commitments, timelines, or pricing
- You've answered similar questions before with confirmed accuracy

### Escalate or Verify When:
- The answer involves product roadmap commitments or timelines
- Pricing, legal terms, or contract-specific questions
- Security, compliance, or data handling questions
- The answer could set a precedent or create expectations
- You found contradictory information in sources
- The question involves a specific customer's custom configuration
- The answer requires specialized expertise you don't have
- The customer is at risk and the wrong answer could exacerbate the situation

### Escalation Path:
1. **Subject matter expert**: For technical or domain-specific questions
2. **Product team**: For roadmap, feature, or capability questions
3. **Legal/compliance**: For terms, privacy, security, or regulatory questions
4. **Billing/finance**: For pricing, invoice, or payment-related questions
5. **Engineering**: For custom configurations, bugs, or technical root causes
6. **Leadership**: For strategic decisions, exceptions, or high-stakes situations

## Research Documentation for Team Knowledge Base

After completing research, capture the knowledge for future use:

### When to Document:
- Question has come up before or likely will again
- Research took significant effort to compile
- Answer required synthesizing multiple sources
- Answer corrects a common misunderstanding
- Answer involves nuance that's easy to get wrong

### Documentation Format:
```
## [Question/Topic]

**Last Verified:** [date]
**Confidence:** [level]

### Answer
[Clear, direct answer]

### Details
[Supporting detail, context, and nuance]

### Sources
[Where this information came from]

### Related Questions
[Other questions this might help answer]

### Review Notes
[When to re-verify, what might change this answer]
```

### Knowledge Base Hygiene:
- Date-stamp all entries
- Flag entries that reference specific product versions or features
- Review and update entries quarterly
- Archive entries that are no longer relevant
- Tag entries for searchability (by topic, product area, customer segment)

## Using This Skill

When conducting customer research:

1. Always start by clarifying what you're actually looking for
2. Search systematically — don't skip tiers even if you think you know where the answer is
3. Cross-reference findings across multiple sources
4. Be transparent about confidence levels — never present uncertain information as fact
5. When in doubt about whether to share with a customer, err on the side of verifying first
6. Document your research for future team benefit
7. If the research reveals a gap in your knowledge base, flag it for documentation
