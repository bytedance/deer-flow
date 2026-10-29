---
name: deep-research
description: Use this skill instead of a single web_search call for ANY question requiring web research. Trigger on queries like "what is X", "explain X", "compare X and Y", "research X", or before content generation tasks. Provides a systematic multi-angle, multi-source, multi-engine research methodology with quantitative minimums, source-quality hierarchy and triangulation-based conflict handling. Use proactively when the user's question needs online information.
---

# Deep Research Skill

## Overview

This skill provides a systematic methodology for conducting thorough web research. **Load this skill BEFORE starting any content generation task** to ensure you gather sufficient information from multiple angles, depths and sources.

## When to Use This Skill

**Always load this skill when:**

### Research Questions
- User asks "what is X", "explain X", "research X", "investigate X"
- User wants to understand a concept, technology, or topic in depth
- The question requires current, comprehensive information from multiple sources
- A single web search would be insufficient to answer properly

### Content Generation (Pre-research)
- Creating presentations (PPT/slides)
- Creating frontend designs or UI mockups
- Writing articles, reports, or documentation
- Producing videos or multimedia content
- Any content that requires real-world information, examples, or current data

## Core Principle

**Never generate content based solely on general knowledge.** The quality of your output directly depends on the quality and quantity of research conducted beforehand. A single search query is NEVER enough.

## Research Floors (non-negotiable minimums)

These are hard lower bounds. Falling below them means the research is incomplete — not a stylistic preference.

| Floor | Minimum | Rationale |
|---|---|---|
| **Distinct queries per topic** | **≥ 5** | Single-query findings are sample size 1 |
| **Independent sources per key claim** | **≥ 3** | Two sources can both trace to the same origin; three breaks coincidence |
| **Different engines per research task** | **≥ 2** | Cross-engine validation catches engine-specific bias and blind spots |
| **Full-content reads (via `web_fetch`)** | **≥ 1 per main finding** | Snippets lie; the body is what counts |
| **Opposing-angle queries** | **≥ 1 per claim** | Always search for critique / limitations / counter-evidence |

If any floor is not met when you reach the synthesis step, **do not write output yet**. Go back and search more.

## Research Methodology

### Phase 1: Broad Exploration

Start with broad searches to understand the landscape:

1. **Initial Survey**: Search for the main topic to understand the overall context
2. **Identify Dimensions**: From initial results, identify key subtopics, themes, angles, or aspects that need deeper exploration
3. **Map the Territory**: Note different perspectives, stakeholders, or viewpoints that exist

Example:
```
Topic: "AI in healthcare"
Initial searches:
- "AI healthcare applications 2026"
- "artificial intelligence medical diagnosis"
- "healthcare AI market trends"

Identified dimensions:
- Diagnostic AI (radiology, pathology)
- Treatment recommendation systems
- Administrative automation
- Patient monitoring
- Regulatory landscape
- Ethical considerations
```

### Phase 2: Deep Dive

For each important dimension identified, conduct targeted research:

1. **Specific Queries**: Search with precise keywords for each subtopic
2. **Multiple Phrasings**: Try different keyword combinations and phrasings
3. **Fetch Full Content**: Use `web_fetch` to read important sources in full, not just snippets
4. **Follow References**: When sources mention other important resources, search for those too

#### Source-Quality Hierarchy

Weight sources by authority. A claim is as strong as its strongest source.

| Tier | Examples | Evidentiary weight |
|---|---|---|
| **Primary** | Original documents, laws, court rulings, company filings, peer-reviewed research, official statistics (Eurostat, BLS, WHO, OECD), government publications, first-party documentation | **Maximum** — cite directly where possible |
| **Secondary** | Established newsrooms (Reuters, AP, AFP, BBC, FAZ, Le Monde, NYT, Bloomberg), established industry analysts (Gartner, McKinsey reports, academic reviews), reputable encyclopedias with citations | **Strong** — use when Primary is unavailable or summarises Primary |
| **Tertiary** | Blog posts, Medium articles, Substack, aggregators, social media, forum discussions, AI-generated summaries | **Weak** — acceptable as *leads to chase down* but never the sole support for a claim |

**Claim-evidence mapping**: for each non-trivial assertion in your output, hold in mind (and be prepared to cite) the specific Tier-1 or Tier-2 source it rests on. If you cannot name one, the claim is not yet research-backed.

Example:
```
Dimension: "Diagnostic AI in radiology"
Targeted searches (at least 2 engines):
- "AI radiology FDA approved systems"
- "chest X-ray AI detection accuracy"
- "radiology AI clinical trials results"

Sources to fetch in full:
- FDA 510(k) database entry (Primary)
- Peer-reviewed meta-analysis (Primary)
- Industry report summarising the above (Secondary)
```

### Phase 3: Diversity, Triangulation & Validation

Ensure comprehensive coverage and cross-check.

| Information Type | Purpose | Example Searches |
|-----------------|---------|------------------|
| **Facts & Data** | Concrete evidence | "statistics", "data", "numbers", "market size" |
| **Examples & Cases** | Real-world applications | "case study", "example", "implementation" |
| **Expert Opinions** | Authority perspectives | "expert analysis", "interview", "commentary" |
| **Trends & Predictions** | Future direction | "trends", "forecast", "future of" |
| **Comparisons** | Context and alternatives | "vs", "comparison", "alternatives" |
| **Challenges & Criticisms** | Balanced view — ≥ 1 query mandatory | "challenges", "limitations", "criticism", "risks" |

#### Triangulation Protocol (conflict handling)

When two sources contradict — different dates, different numbers, different causal stories — **never silently pick one**.

1. Search for a **third, independent** source to resolve the disagreement.
2. Check **date of publication**: a newer source may supersede an older one, but not always — verify the newer one isn't just repeating a rumour.
3. Check **source tier** (see hierarchy above): Primary generally beats Secondary, which generally beats Tertiary.
4. If the third source confirms one side → cite the confirmed version, mention that an older/lesser source claimed otherwise if it's likely to come up.
5. If the conflict remains unresolvable → **explicitly surface it in the output**:
   `"Source A (Reuters, 2026-03) reports X; Source B (Bloomberg, 2026-02) reports Y. The discrepancy has not been resolved in available reporting."`

Don't pick arbitrarily and don't hide the conflict.

#### Multilingual Coverage

For any topic with a non-English regional dimension, search in the **domain language** as well as English.

- German tech / politics / law → English **and** German queries (`"Bundesnetzagentur Breitbandausbau 2026"`)
- French policy → English **and** French
- Chinese manufacturing → English **and** (transliterated) Chinese if feasible
- Spanish-language region affairs → English **and** Spanish

Local-language sources often have earlier, more detailed reporting on regional events than English-language coverage. Ignoring them is a common blind spot.

### Phase 4: Stop Criteria

Stop when all of the following hold — **not before**:

- [ ] Every **Research Floor** above is met (5 queries / 3 sources / 2 engines / 1 fetch / 1 opposing query).
- [ ] Every **key claim** that will appear in the output has a specific Tier-1 or Tier-2 source you can name.
- [ ] Every **identified dimension** from Phase 1 has at least one dedicated dive in Phase 2.
- [ ] Every **contradiction encountered** is either resolved (via triangulation) or surfaced explicitly.
- [ ] Three **consecutive new queries** produced no new facts — a signal of topic saturation, legitimate stop.
- [ ] For regional topics: at least one query has been run in the domain language.

If any box is unchecked, **go back and research more**. The Stop Criteria supersede any earlier "looks good enough" feeling.

## Search Strategy Tips

### Effective Query Patterns

```
# Be specific with context
❌ "AI trends"
✅ "enterprise AI adoption trends 2026"

# Include authoritative source hints
"[topic] research paper"
"[topic] McKinsey report"
"[topic] industry analysis"
"[topic] primary source"
"[topic] government statistics"

# Search for specific content types
"[topic] case study"
"[topic] statistics"
"[topic] expert interview"
"[topic] criticism"
"[topic] limitations"

# Use temporal qualifiers — always use the ACTUAL current year from <current_date>
"[topic] 2026"   # ← replace with real current year, never hardcode a past year
"[topic] latest"
"[topic] recent developments"
```

### Temporal Awareness

**Always check `<current_date>` in your context before forming ANY search query.**

`<current_date>` gives you the full date: year, month, day, and weekday (e.g. `2026-02-28, Saturday`). Use the right level of precision depending on what the user is asking:

| User intent | Temporal precision needed | Example query |
|---|---|---|
| "today / this morning / just released" | **Month + Day** | `"tech news February 28 2026"` |
| "this week" | **Week range** | `"technology releases week of Feb 24 2026"` |
| "recently / latest / new" | **Month** | `"AI breakthroughs February 2026"` |
| "this year / trends" | **Year** | `"software trends 2026"` |

**Rules:**
- When the user asks about "today" or "just released", use **month + day + year** in your search queries to get same-day results
- Never drop to year-only when day-level precision is needed — `"tech news 2026"` will NOT surface today's news
- Try multiple phrasings: numeric form (`2026-02-28`), written form (`February 28 2026`), and relative terms (`today`, `this week`) across different queries

❌ User asks "what's new in tech today" → searching `"new technology 2026"` → misses today's news
✅ User asks "what's new in tech today" → searching `"new technology February 28 2026"` + `"tech news today Feb 28"` → gets today's results

### When to Use web_fetch

Use `web_fetch` to read full content when:
- A search result looks highly relevant and authoritative
- You need detailed information beyond the snippet
- The source contains data, case studies, or expert analysis
- You want to understand the full context of a finding
- A Tier-1 Primary source is surfaced — always fetch those

### Iterative Refinement

Research is iterative. After initial searches:
1. Review what you've learned — which dimensions are thin, which are saturated
2. Identify gaps in your understanding
3. Formulate new, more targeted queries — switch engines, switch language, switch phrasing
4. Repeat until Stop Criteria are met

## Quality Bar

Your research is sufficient when you can confidently answer:
- What are the key facts and data points, and which Tier-1/Tier-2 source backs each?
- What are 2-3 concrete real-world examples?
- What do experts say about this topic?
- What are the current trends and future directions?
- What are the challenges, limitations, or counter-arguments?
- Where do sources disagree, and how did you handle it?
- What makes this topic relevant or important now?

## Common Mistakes to Avoid

- ❌ Stopping after 1-2 searches
- ❌ Running all queries through a single engine
- ❌ Relying on search snippets without reading full sources
- ❌ Searching only one aspect of a multi-faceted topic
- ❌ Ignoring contradicting viewpoints or challenges
- ❌ Silently picking one side when sources disagree
- ❌ Skipping domain-language searches for regional topics
- ❌ Using outdated information when current data exists
- ❌ Treating Tertiary sources (blogs, social) as evidentiary
- ❌ Starting content generation before Stop Criteria are met

## Output

After completing research, you should have:
1. A comprehensive understanding of the topic from multiple angles
2. Specific facts, data points, and statistics — each tied to a namable Tier-1 or Tier-2 source
3. Real-world examples and case studies
4. Expert perspectives and authoritative sources
5. Current trends and relevant context
6. Explicit handling of any contradictions encountered
7. For regional topics: at least one reading in the domain language

**Only then proceed to content generation**, using the gathered information to create high-quality, well-informed content.
