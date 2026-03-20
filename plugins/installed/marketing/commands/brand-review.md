---
description: Review content against your brand voice, style guide, and messaging pillars
argument-hint: "<content to review>"
---

# Brand Review

> If you see unfamiliar placeholders or need to check which tools are connected, see [CONNECTORS.md](../CONNECTORS.md).

Review marketing content against brand voice, style guidelines, and messaging standards. Flag deviations and provide specific improvement suggestions.

## Trigger

User runs `/brand-review` or asks to review, check, or audit content against brand guidelines.

## Inputs

1. **Content to review** — accept content in any of these forms:
   - Pasted directly into the conversation
   - A file path or ~~knowledge base reference (e.g. Notion page, shared doc)
   - A URL to a published page
   - Multiple pieces for batch review

2. **Brand guidelines source** (determined automatically):
   - If a brand style guide is configured in local settings, use it automatically
   - If not configured, ask: "Do you have a brand style guide or voice guidelines I should review against? You can paste them, share a file, or describe your brand voice. Otherwise, I'll do a general review for clarity, consistency, and professionalism."

## Review Process

### With Brand Guidelines Configured

Evaluate the content against each of these dimensions:

#### Voice and Tone
- Does the content match the defined brand voice attributes?
- Is the tone appropriate for the content type and audience?
- Are there shifts in voice that feel inconsistent?
- Flag specific sentences or phrases that deviate with an explanation of why

#### Terminology and Language
- Are preferred brand terms used correctly?
- Are any "avoid" terms or phrases present?
- Is jargon level appropriate for the target audience?
- Are product names, feature names, and branded terms used correctly (capitalization, formatting)?

#### Messaging Pillars
- Does the content align with defined messaging pillars or value propositions?
- Are claims consistent with approved messaging?
- Is the content reinforcing or contradicting brand positioning?

#### Style Guide Compliance
- Grammar and punctuation per style guide (e.g., Oxford comma, title case vs. sentence case)
- Formatting conventions (headers, lists, emphasis)
- Number formatting, date formatting
- Acronym usage (defined on first use?)

### Without Brand Guidelines (Generic Review)

Evaluate the content for:

#### Clarity
- Is the main message clear within the first paragraph?
- Are sentences concise and easy to understand?
- Is the structure logical and easy to follow?
- Are there ambiguous statements or unclear references?

#### Consistency
- Is the tone consistent throughout?
- Are terms used consistently (no switching between synonyms for the same concept)?
- Is formatting consistent (headers, lists, capitalization)?

#### Professionalism
- Is the content free of typos, grammatical errors, and awkward phrasing?
- Is the tone appropriate for the intended audience?
- Are claims supported or substantiated?

### Legal and Compliance Flags (Always Checked)

Regardless of whether brand guidelines are configured, flag:
- **Unsubstantiated claims** — superlatives ("best", "fastest", "only") without evidence or qualification
- **Missing disclaimers** — financial claims, health claims, or guarantees that may need legal disclaimers
- **Comparative claims** — comparisons to competitors that could be challenged
- **Regulatory language** — content that may need compliance review (financial services, healthcare, etc.)
- **Testimonial issues** — quotes or endorsements without attribution or disclosure
- **Copyright concerns** — content that appears to be closely paraphrased from other sources

## Output Format

Present the review as:

### Summary
- Overall assessment: how well the content aligns with brand standards (or general quality)
- 1-2 sentence summary of the biggest strengths
- 1-2 sentence summary of the most important improvements

### Detailed Findings

For each issue found, provide:

| Issue | Location | Severity | Suggestion |
|-------|----------|----------|------------|

Where severity is:
- **High** — contradicts brand voice, contains compliance risk, or significantly undermines messaging
- **Medium** — inconsistent with guidelines but not damaging
- **Low** — minor style or preference issue

### Revised Sections

For the top 3-5 highest-severity issues, provide a before/after showing the original text and a suggested revision.

### Legal/Compliance Flags

List any legal or compliance concerns separately with recommended actions.

## After Review

Ask: "Would you like me to:
- Revise the full content with these suggestions applied?
- Focus on fixing just the high-severity issues?
- Review additional content against the same guidelines?
- Help you document your brand voice for future reviews?"
