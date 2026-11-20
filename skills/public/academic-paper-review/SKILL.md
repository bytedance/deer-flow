---
name: academic-paper-review
description: Use this skill when the user requests to review, analyze, critique, or summarize academic papers, research articles, preprints, or scientific publications. Supports comprehensive structured reviews covering methodology assessment, contribution evaluation, literature positioning, and constructive feedback generation. Trigger on queries involving paper URLs, uploaded PDFs, arXiv links, or requests like "review this paper", "analyze this research", "summarize this study", or "write a peer review".
---

# Academic Paper Review Skill

## Overview

This skill produces structured, peer-review-quality analyses of academic papers and research publications. It follows established academic review standards used by top-tier venues (NeurIPS, ICML, ACL, Nature, IEEE) to provide rigorous, constructive, and balanced assessments.

The review covers **summary, strengths, weaknesses, methodology assessment, contribution evaluation, literature positioning, and actionable recommendations** — all grounded in evidence from the paper itself.

## Core Capabilities

- Parse and comprehend academic papers from uploaded PDFs or fetched URLs
- Generate structured reviews following top-venue review templates
- Assess methodology rigor (experimental design, statistical validity, reproducibility)
- Evaluate novelty and significance of contributions
- Position the work within the broader research landscape via targeted literature search
- Identify limitations, gaps, and potential improvements
- Produce both detailed review and concise executive summary formats
- Support papers in any scientific domain (CS, biology, physics, social sciences, etc.)

## When to Use This Skill

**Always load this skill when:**

- User provides a paper URL (arXiv, DOI, conference proceedings, journal link)
- User uploads a PDF of a research paper or preprint
- User asks to "review", "analyze", "critique", "assess", or "summarize" a research paper
- User wants to understand the strengths and weaknesses of a study
- User requests a peer-review-style evaluation of academic work
- User asks for help preparing a review for a conference or journal submission

## Review Methodology

### Phase 1: Paper Comprehension

Thoroughly read and understand the paper before forming any judgments.

#### Step 1.1: Identify Paper Metadata

Extract and record:

| Field | Description |
|-------|-------------|
| **Title** | Full paper title |
| **Authors** | Author list and affiliations |
| **Venue / Status** | Publication venue, preprint server, or submission status |
| **Year** | Publication or submission year |
| **Domain** | Research field and subfield |
| **Paper Type** | Empirical, theoretical, survey, position paper, systems paper, etc. |

#### Step 1.2: Deep Reading Pass

Read the paper systematically:

1. **Abstract & Introduction** — Identify the claimed contributions and motivation
2. **Related Work** — Note how authors position their work relative to prior art
3. **Methodology** — Understand the proposed approach, model, or framework in detail
4. **Experiments / Results** — Examine datasets, baselines, metrics, and reported outcomes
5. **Discussion & Limitations** — Note any self-identified limitations
6. **Conclusion** — Compare concluded claims against actual evidence presented

#### Step 1.3: Key Claims Extraction

List the paper's main claims explicitly:

```
Claim 1: [Specific claim about contribution or finding]
Evidence: [What evidence supports this claim in the paper]
Strength: [Strong / Moderate / Weak]

Claim 2: [...]
...
```

### Phase 2: Critical Analysis

#### Step 2.1: Literature Context Search

Use web search to understand the research landscape:

```
Search queries:
- "[paper topic] state of the art [current year]"
- "[key method name] comparison benchmark"
- "[authors] previous work [topic]"
- "[specific technique] limitations criticism"
- "survey [research area] recent advances"
```

Use `web_fetch` on key related papers or surveys to understand where this work fits.

#### Step 2.2: Methodology Assessment

Evaluate the methodology using the following framework:

| Criterion | Questions to Ask | Rating |
|-----------|-----------------|--------|
| **Soundness** | Is the approach technically correct? Are there logical flaws? | 1-5 |
| **Novelty** | What is genuinely new vs. incremental improvement? | 1-5 |
| **Reproducibility** | Are details sufficient to reproduce? Code/data available? | 1-5 |
| **Experimental Design** | Are baselines fair? Are ablations adequate? Are datasets appropriate? | 1-5 |
| **Statistical Rigor** | Are results statistically significant? Error bars reported? Multiple runs? | 1-5 |
| **Scalability** | Does the approach scale? Are computational costs discussed? | 1-5 |

#### Step 2.3: Contribution Significance Assessment

Evaluate the significance level:

| Level | Description | Criteria |
|-------|-------------|----------|
| **Landmark** | Fundamentally changes the field | New paradigm, widely applicable breakthrough |
| **Significant** | Strong contribution advancing the state of the art | Clear improvement with solid evidence |
| **Moderate** | Useful contribution with some limitations | Incremental but valid improvement |
| **Marginal** | Minimal advance over existing work | Small gains, narrow applicability |
| **Below threshold** | Does not meet publication standards | Fundamental flaws, insufficient evidence |

#### Step 2.4: Strengths and Weaknesses Analysis

For each strength or weakness, provide:
- **What**: Specific observation
- **Where**: Section/figure/table reference
- **Why it matters**: Impact on the paper's claims or utility

### Phase 3: Review Synthesis

#### Step 3.1: Assemble the Structured Review

Produce the final review using the template below.

## Review Output Template

```markdown
# Paper Review: [Paper Title]

## Paper Metadata
- **Authors**: [Author list]
- **Venue**: [Publication venue or preprint server]
- **Year**: [Year]
- **Domain**: [Research field]
- **Paper Type**: [Empirical / Theoretical / Survey / Systems / Position]

## Executive Summary

[2-3 paragraph summary of the paper's core contribution, approach, and main findings.
State your overall assessment upfront: what the paper does well, where it falls short,
and whether the contribution is sufficient for the claimed venue/impact level.]

## Summary of Contributions

1. [First claimed contribution — one sentence]
2. [Second claimed contribution — one sentence]
3. [Additional contributions if any]

## Strengths

### S1: [Concise strength title]
[Detailed explanation with specific references to sections, figures, or tables in the paper.
Explain WHY this is a strength and its significance.]

### S2: [Concise strength title]
[...]

### S3: [Concise strength title]
[...]

## Weaknesses

### W1: [Concise weakness title]
[Detailed explanation with specific references. Explain the impact of this weakness on
the paper's claims. Suggest how it could be addressed.]

### W2: [Concise weakness title]
[...]

### W3: [Concise weakness title]
[...]

## Methodology Assessment

| Criterion | Rating (1-5) | Assessment |
|-----------|:---:|------------|
| Soundness | X | [Brief justification] |
| Novelty | X | [Brief justification] |
| Reproducibility | X | [Brief justification] |
| Experimental Design | X | [Brief justification] |
| Statistical Rigor | X | [Brief justification] |
| Scalability | X | [Brief justification] |

## Questions for the Authors

1. [Specific question that would clarify a concern or ambiguity]
2. [Question about methodology choices or alternative approaches]
3. [Question about generalizability or practical applicability]

## Minor Issues

- [Typos, formatting issues, unclear figures, notation inconsistencies]
- [Missing references that should be cited]
- [Suggestions for improved clarity]

## Literature Positioning

[How does this work relate to the current state of the art?
Are key related works cited? Are comparisons fair and comprehensive?
What important related work is missing?]

## Recommendations

**Overall Assessment**: [Accept / Weak Accept / Borderline / Weak Reject / Reject]

**Confidence**: [High / Medium / Low] — [Justification for confidence level]

**Contribution Level**: [Landmark / Significant / Moderate / Marginal / Below threshold]

### Actionable Suggestions for Improvement
1. [Specific, constructive suggestion]
2. [Specific, constructive suggestion]
3. [Specific, constructive suggestion]
```

## Review Principles

### Constructive Criticism
- **Always suggest how to fix it** — Don't just point out problems; propose solutions
- **Give credit where due** — Acknowledge genuine contributions even in flawed papers
- **Be specific** — Reference exact sections, equations, figures, and tables
- **Separate minor from major** — Distinguish fatal flaws from fixable issues

### Objectivity Standards
- ❌ "This paper is poorly written" (vague, unhelpful)
- ✅ "Section 3.2 introduces notation X without formal definition, making the proof in Theorem 1 difficult to follow. Consider adding a notation table after the problem formulation." (specific, actionable)

### Ethical Review Practices
- Do NOT dismiss work based on author reputation or affiliation
- Evaluate the work on its own merits
- Flag potential ethical concerns (bias in datasets, dual-use implications) constructively
- Maintain confidentiality of unpublished work

## Adaptation by Paper Type

| Paper Type | Focus Areas |
|------------|-------------|
| **Empirical** | Experimental design, baselines, statistical significance, ablations, reproducibility |
| **Theoretical** | Proof correctness, assumption reasonableness, tightness of bounds, connection to practice |
| **Survey** | Comprehensiveness, taxonomy quality, coverage of recent work, synthesis insights |
| **Systems** | Architecture decisions, scalability evidence, real-world deployment, engineering contributions |
| **Position** | Argument coherence, evidence for claims, impact potential, fairness of characterizations |

## Common Pitfalls to Avoid

- ❌ Reviewing the paper you wish was written instead of the paper that was submitted
- ❌ Demanding additional experiments that are unreasonable in scope
- ❌ Penalizing the paper for not solving a different problem
- ❌ Being overly influenced by writing quality versus technical contribution
- ❌ Treating absence of comparison to your own work as a weakness
- ❌ Providing only a summary without critical analysis

## Quality Checklist

Before finalizing the review, verify:

- [ ] Paper was read completely (not just abstract and introduction)
- [ ] All major claims are identified and evaluated against evidence
- [ ] At least 3 strengths and 3 weaknesses are provided with specific references
- [ ] The methodology assessment table is complete with ratings and justifications
- [ ] Questions for authors target genuine ambiguities, not rhetorical critiques
- [ ] Literature search was conducted to contextualize the contribution
- [ ] Recommendations are actionable and constructive
- [ ] The overall assessment is consistent with the identified strengths and weaknesses
- [ ] The review tone is professional and respectful
- [ ] Minor issues are separated from major concerns

## Output Format

- Output the complete review in **Markdown** format
- Save the review to `/mnt/user-data/outputs/review-{paper-topic}.md` when working in sandbox
- Present the review to the user using the `present_files` tool

## Notes

- This skill complements the `deep-research` skill — load both when the user wants the paper reviewed in the context of the broader field
- For papers behind paywalls, work with whatever content is accessible (abstract, publicly available versions, preprint mirrors)
- Adapt the review depth to the user's needs: a brief assessment for quick triage versus a full review for submission preparation
- When reviewing multiple papers comparatively, maintain consistent criteria across all reviews
- Always disclose limitations of your review (e.g., "I could not verify the proofs in Appendix B in detail")
