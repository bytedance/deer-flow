---
name: newsletter-generation
description: Use this skill when the user requests to generate, create, write, or draft a newsletter, email digest, weekly roundup, industry briefing, or curated content summary. Supports topic-based research, content curation from multiple sources, and professional formatting for email or web distribution. Trigger on requests like "create a newsletter about X", "write a weekly digest", "generate a tech roundup", or "curate news about Y".
---

# Newsletter Generation Skill

## Overview

This skill generates professional, well-researched newsletters that combine curated content from multiple sources with original analysis and commentary. It follows modern newsletter best practices from publications like Morning Brew, The Hustle, TLDR, and Benedict Evans to produce content that is informative, engaging, and actionable.

The output is a complete, ready-to-publish newsletter in Markdown format, suitable for email distribution platforms, web publishing, or conversion to HTML.

## Core Capabilities

- Research and curate content from multiple web sources on specified topics
- Generate topic-focused or multi-topic newsletters with consistent voice
- Write engaging headlines, summaries, and original commentary
- Structure content for optimal readability and scanning
- Support multiple newsletter formats (daily digest, weekly roundup, deep-dive, industry briefing)
- Include relevant links, sources, and attributions
- Adapt tone and style to target audience (technical, executive, general)
- Generate recurring newsletter series with consistent branding and structure

## When to Use This Skill

**Always load this skill when:**

- User asks to generate a newsletter, email digest, or content roundup
- User requests a curated summary of news or developments on a topic
- User wants to create a recurring newsletter format
- User asks to compile recent developments in a field into a briefing
- User needs a formatted email-ready content piece with multiple curated items
- User asks for a "weekly roundup", "monthly digest", or "morning briefing"

## Newsletter Workflow

### Phase 1: Planning

#### Step 1.1: Understand Newsletter Requirements

Identify the key parameters:

| Parameter | Description | Default |
|-----------|-------------|---------|
| **Topic(s)** | Primary subject area(s) to cover | Required |
| **Format** | Daily digest, weekly roundup, deep-dive, or industry briefing | Weekly roundup |
| **Target Audience** | Technical, executive, general, or niche community | General |
| **Tone** | Professional, conversational, witty, or analytical | Conversational-professional |
| **Length** | Short (5-min read), medium (10-min), long (15-min+) | Medium |
| **Sections** | Number and type of content sections | 4-6 sections |
| **Frequency Context** | One-time or part of a recurring series | One-time |

#### Step 1.2: Define Newsletter Structure

Based on the format, select the appropriate structure:

**Daily Digest Structure**:
```
1. Top Story (1 item, detailed)
2. Quick Hits (3-5 items, brief)
3. One Stat / Quote of the Day
4. What to Watch
```

**Weekly Roundup Structure**:
```
1. Editor's Note / Intro
2. Top Stories (2-3 items, detailed)
3. Trends & Analysis (1-2 items, original commentary)
4. Quick Bites (4-6 items, brief summaries)
5. Tools & Resources (2-3 items)
6. One More Thing / Closing
```

**Deep-Dive Structure**:
```
1. Introduction & Context
2. Background / Why It Matters
3. Key Developments (detailed analysis)
4. Expert Perspectives
5. What's Next / Implications
6. Further Reading
```

**Industry Briefing Structure**:
```
1. Executive Summary
2. Market Developments
3. Company News & Moves
4. Product & Technology Updates
5. Regulatory & Policy Changes
6. Data & Metrics
7. Outlook
```

### Phase 2: Research & Curation

#### Step 2.1: Multi-Source Research

Conduct thorough research using web search. **The quality of the newsletter depends directly on the quality and recency of research.**

**Search Strategy**:

```
# Current news and developments
"[topic] news [current month] [current year]"
"[topic] latest developments"
"[topic] announcement this week"

# Trends and analysis
"[topic] trends [current year]"
"[topic] analysis expert opinion"
"[topic] industry report"

# Data and statistics
"[topic] statistics [current year]"
"[topic] market data latest"
"[topic] growth metrics"

# Tools and resources
"[topic] new tools [current year]"
"[topic] open source release"
"best [topic] resources [current year]"
```

> **IMPORTANT**: Always check `<current_date>` to ensure search queries use the correct temporal context. Never use hardcoded years.

#### Step 2.2: Source Evaluation and Selection

Evaluate each source and curate the best content:

| Criterion | Priority |
|-----------|----------|
| **Recency** | Prefer content from the last 7-30 days |
| **Authority** | Prioritize primary sources, official announcements, established publications |
| **Uniqueness** | Select stories that offer fresh perspective or are underreported |
| **Relevance** | Every item must clearly connect to the newsletter's stated topic(s) |
| **Actionability** | Prefer content readers can act on (tools, insights, strategies) |
| **Diversity** | Mix of news, analysis, data, and practical resources |

#### Step 2.3: Deep Content Extraction

For key stories, use `web_fetch` to read full articles and extract:

1. **Core facts** — What happened, who is involved, when
2. **Context** — Why this matters, background information
3. **Data points** — Specific numbers, metrics, or statistics
4. **Quotes** — Relevant expert quotes or official statements
5. **Implications** — What this means for the reader

### Phase 3: Writing

#### Step 3.1: Newsletter Header

Every newsletter starts with a consistent header:

```markdown
# [Newsletter Name]

*[Tagline or description] — [Date]*

---

[Optional: One-sentence preview of what's inside]
```

#### Step 3.2: Section Writing Guidelines

**Top Stories / Featured Items**:
- **Headline**: Compelling, clear, benefit-oriented (not clickbait)
- **Hook**: Opening sentence that makes the reader care (1-2 sentences)
- **Body**: Key facts and context (2-4 paragraphs)
- **Why it matters**: Connect to the reader's world (1 paragraph)
- **Source link**: Always attribute and link to the original source

**Quick Bites / Brief Items**:
- **Format**: Bold headline + 2-3 sentence summary + source link
- **Focus**: One key takeaway per item
- **Efficiency**: Readers should get the essential insight without clicking through

**Analysis / Commentary Sections**:
- **Voice**: The newsletter's unique perspective on trends or developments
- **Structure**: Observation → Context → Implication → (Optional) Actionable takeaway
- **Evidence**: Every claim backed by data or sourced information

#### Step 3.3: Writing Standards

| Principle | Implementation |
|-----------|---------------|
| **Scannable** | Use headers, bold text, bullet points, and short paragraphs |
| **Engaging** | Lead with the most interesting angle, not chronological order |
| **Concise** | Every sentence earns its place — cut filler ruthlessly |
| **Accurate** | Every fact is sourced, every number is verified |
| **Attributive** | Always credit original sources with inline links |
| **Human** | Write like a knowledgeable friend, not a press release |

**Tone Calibration by Audience**:

| Audience | Tone | Example |
|----------|------|---------|
| **Technical** | Precise, no jargon explanations, assumed expertise | "The new API supports gRPC streaming with backpressure handling via flow control windows." |
| **Executive** | Impact-focused, bottom-line, strategic | "This acquisition gives Company X a 40% market share in the enterprise segment, directly threatening Incumbent Y's pricing power." |
| **General** | Accessible, analogies, explains concepts | "Think of it like a universal translator for data — it lets any app talk to any database without learning a new language." |

### Phase 4: Assembly & Polish

#### Step 4.1: Assemble the Newsletter

Combine all sections into the final document following the chosen structure template.

#### Step 4.2: Footer

Every newsletter ends with:

```markdown
---

*[Newsletter Name] is [description of what it is].*
*[How to subscribe/share/give feedback]*

*Sources: All links are provided inline. This newsletter curates and summarizes
publicly available information with original commentary.*
```

#### Step 4.3: Quality Checklist

Before finalizing, verify:

- [ ] **Every factual claim has a source link** — No unsourced assertions
- [ ] **All links are functional** — Verified URLs from search results
- [ ] **Date references use the actual current date** — No hardcoded or assumed dates
- [ ] **Content is current** — All major items are from within the expected timeframe
- [ ] **No duplicate stories** — Each item appears only once
- [ ] **Consistent formatting** — Headers, bullets, links use the same style throughout
- [ ] **Balanced coverage** — Not dominated by a single source or perspective
- [ ] **Appropriate length** — Matches the specified length target
- [ ] **Engaging opening** — The first 2 sentences make the reader want to continue
- [ ] **Clear closing** — The newsletter ends with a memorable or actionable note
- [ ] **Proofread** — No typos, broken formatting, or incomplete sentences

## Newsletter Output Template

```markdown
# [Newsletter Name]

*[Tagline] — [Full date, e.g., April 4, 2026]*

---

[Preview sentence: "This week: [topic 1], [topic 2], and [topic 3]."]

## 🔥 Top Stories

### [Headline 1]

[Hook — why this matters in 1-2 sentences.]

[Body — 2-4 paragraphs covering key facts, context, and implications.]

**Why it matters:** [1 paragraph connecting to reader's interests or industry impact.]

📎 [Source: Publication Name](URL)

### [Headline 2]

[Same structure as above]

## 📊 Trends & Analysis

### [Trend Title]

[Original commentary on an emerging trend, backed by data from research.]

[Key data points presented clearly — consider inline stats or a brief comparison.]

**The bottom line:** [One-sentence takeaway.]

## ⚡ Quick Bites

- **[Headline]** — [2-3 sentence summary with key takeaway.] [Source](URL)
- **[Headline]** — [2-3 sentence summary.] [Source](URL)
- **[Headline]** — [2-3 sentence summary.] [Source](URL)
- **[Headline]** — [2-3 sentence summary.] [Source](URL)

## 🛠️ Tools & Resources

- **[Tool/Resource Name]** — [What it does and why it's useful.] [Link](URL)
- **[Tool/Resource Name]** — [Description.] [Link](URL)

## 💬 One More Thing

[Closing thought, insightful quote, or forward-looking statement.]

---

*[Newsletter Name] curates the most important [topic] news and analysis.*
*Found this useful? Share it with a colleague.*

*All sources are linked inline. Views and commentary are original.*
```

## Adaptation Examples

### Technology Newsletter
- Emoji usage: ✅ Moderate (section headers)
- Sections: Top Stories, Deep Dive, Quick Bites, Open Source Spotlight, Dev Tools
- Tone: Technical-conversational

### Business/Finance Newsletter
- Emoji usage: ❌ Minimal to none
- Sections: Market Overview, Deal Flow, Company News, Data Corner, Outlook
- Tone: Professional-analytical

### Industry-Specific Newsletter
- Emoji usage: Moderate
- Sections: Regulatory Updates, Market Data, Innovation Watch, People Moves, Events
- Tone: Expert-authoritative

### Creative/Marketing Newsletter
- Emoji usage: ✅ Liberal
- Sections: Campaign Spotlight, Trend Watch, Viral This Week, Tools We Love, Inspiration
- Tone: Enthusiastic-professional

## Output Handling

After generation:

- Save the newsletter to `/mnt/user-data/outputs/newsletter-{topic}-{date}.md`
- Present the newsletter to the user using the `present_files` tool
- Offer to adjust sections, tone, length, or focus areas
- If the user wants HTML output, note that the Markdown can be converted using standard tools

## Notes

- This skill works best in combination with the `deep-research` skill for comprehensive topic coverage — load both for newsletters requiring deep analysis
- Always use `<current_date>` for temporal context in searches and date references in the newsletter
- For recurring newsletters, suggest maintaining a consistent structure so readers develop expectations
- When curating, quality beats quantity — 5 excellent items beat 15 mediocre ones
- Attribute all content properly — newsletters build trust through transparent sourcing
- Avoid summarizing paywalled content that the reader cannot access
- If the user provides specific URLs or articles to include, incorporate them alongside your curated findings
- The newsletter should provide enough value in the summaries that readers benefit even without clicking through to every link
