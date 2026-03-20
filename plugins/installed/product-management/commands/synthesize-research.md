---
description: Synthesize user research from interviews, surveys, and feedback into structured insights
argument-hint: "<research topic or question>"
---

# Synthesize Research

> If you see unfamiliar placeholders or need to check which tools are connected, see [CONNECTORS.md](../CONNECTORS.md).

Synthesize user research from multiple sources into structured insights and recommendations.

## Workflow

### 1. Gather Research Inputs

Accept research from any combination of:
- **Pasted text**: Interview notes, transcripts, survey responses, feedback
- **Uploaded files**: Research documents, spreadsheets, recordings summaries
- **~~knowledge base** (if connected): Search for research documents, interview notes, survey results
- **~~user feedback** (if connected): Pull recent support tickets, feature requests, bug reports
- **~~product analytics** (if connected): Pull usage data, funnel metrics, behavioral data
- **~~meeting transcription** (if connected): Pull interview recordings, meeting summaries, and discussion notes

Ask the user what they have:
- What type of research? (interviews, surveys, usability tests, analytics, support tickets, sales call notes)
- How many sources / participants?
- Is there a specific question or hypothesis they are investigating?
- What decisions will this research inform?

### 2. Process the Research

For each source, extract:
- **Key observations**: What did users say, do, or experience?
- **Quotes**: Verbatim quotes that illustrate important points
- **Behaviors**: What users actually did (vs what they said they do)
- **Pain points**: Frustrations, workarounds, and unmet needs
- **Positive signals**: What works well, moments of delight
- **Context**: User segment, use case, experience level

### 3. Identify Themes and Patterns

Apply thematic analysis — see the **user-research-synthesis** skill for detailed methodology including affinity mapping and triangulation techniques.

Group observations into themes, count frequency across participants, and assess impact severity. Note contradictions and surprises.

Create a priority matrix:
- **High frequency + High impact**: Top priority findings
- **Low frequency + High impact**: Important for specific segments
- **High frequency + Low impact**: Quality-of-life improvements
- **Low frequency + Low impact**: Note but deprioritize

### 4. Generate the Synthesis

Produce a structured research synthesis:

#### Research Overview
- Methodology: what types of research, how many participants/sources
- Research question(s): what we set out to learn
- Timeframe: when the research was conducted

#### Key Findings
For each major finding (aim for 5-8):
- **Finding statement**: One clear sentence describing the insight
- **Evidence**: Supporting quotes, data points, or observations (with source attribution)
- **Frequency**: How many participants/sources support this finding
- **Impact**: How significantly this affects the user experience or business
- **Confidence level**: High (strong evidence), Medium (suggestive), Low (early signal)

Order findings by priority (frequency x impact).

#### User Segments / Personas
If the research reveals distinct user segments:
- Segment name and description
- Key characteristics and behaviors
- Unique needs and pain points
- Size estimate if data is available

#### Opportunity Areas
Based on the findings, identify opportunity areas:
- What user needs are unmet or underserved
- Where do current solutions fall short
- What new capabilities would unlock value
- Prioritized by potential impact

#### Recommendations
Specific, actionable recommendations:
- What to build, change, or investigate further
- Tied back to specific findings
- Prioritized by impact and feasibility

#### Open Questions
What the research did not answer:
- Gaps in understanding
- Areas needing further investigation
- Suggested follow-up research methods

### 5. Review and Extend

After generating the synthesis:
- Ask if any findings need more detail or different framing
- Offer to generate specific artifacts: persona documents, opportunity maps, research presentations
- Offer to create follow-up research plans for open questions
- Offer to draft product implications (how findings should influence the roadmap)

## Output Format

Use clear headers and structured formatting. Each finding should stand on its own — a reader should be able to read any single finding and understand it without reading the rest.

## Tips

- Let the data speak. Do not force findings into a predetermined narrative.
- Distinguish between what users say and what they do. Behavioral data is stronger than stated preferences.
- Quotes are powerful evidence. Include them generously, with attribution to participant type (not name).
- Be explicit about confidence levels. A finding from 2 interviews is a hypothesis, not a conclusion.
- Contradictions in the data are interesting, not inconvenient. They often reveal distinct user segments.
- Recommendations should be specific enough to act on. "Improve onboarding" is not actionable. "Add a progress indicator to the setup flow" is.
- Resist the temptation to synthesize too many themes. 5-8 strong findings are better than 20 weak ones.
