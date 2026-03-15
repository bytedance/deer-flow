---
name: peer-review
description: Simulate multi-perspective peer review for manuscripts, including reviewer comments, response letters, and revision tracking.
license: MIT
---

# Peer Review Simulation Skill

## Purpose

Simulate rigorous peer review of academic manuscripts from multiple reviewer perspectives, generate structured reviewer reports, and help draft Response to Reviewers letters.

## When to Use

- Before submitting a manuscript to a journal/conference
- After receiving actual reviewer comments (to help draft responses)
- During internal review rounds
- For thesis/dissertation chapter review

## Workflow

### Phase 1: Reviewer Persona Assignment

Assign 3 reviewers with distinct perspectives:

| Reviewer | Perspective | Focus Areas |
|----------|-------------|-------------|
| Reviewer 1 | Domain Expert | Technical accuracy, novelty, related work completeness |
| Reviewer 2 | Methodologist | Statistical rigor, experimental design, reproducibility |
| Reviewer 3 | Generalist/Editor | Clarity, impact, structure, readability |

### Phase 2: Structured Review Template

Each reviewer evaluates using this template:

```
## Reviewer N Report

### Summary (2-3 sentences)
### Strengths (3-5 bullet points)
### Weaknesses (3-5 bullet points, classified as Major/Minor)
### Detailed Comments (numbered, with section references)
### Questions for Authors
### Recommendation: Accept / Minor Revision / Major Revision / Reject
### Confidence: High / Medium / Low
```

### Phase 3: Meta-Review Synthesis

Synthesize all reviews into:
1. Consensus strengths and weaknesses
2. Contradictions between reviewers (and how to resolve)
3. Priority-ranked revision action items
4. Estimated revision effort (1-2 weeks / 1 month / 2+ months)

### Phase 4: Response to Reviewers Template

For each reviewer comment, generate a response using this format:

```
**Reviewer N, Comment M**: [original comment]

**Response**: [your response]

**Changes Made**: [specific changes with page/line numbers]
```

### Phase 5: Revision Tracking

After revisions:
- Diff summary of all changes
- Cross-check: does each response address its comment?
- New consistency check across all sections

## Review Quality Criteria

A good simulated review should:
- Reference specific sections, equations, figures, or tables
- Cite relevant papers the authors may have missed (use `semantic_scholar_search` to find them)
- Suggest concrete improvements, not just identify problems
- Distinguish between required changes and suggestions
- Be constructive, not adversarial
- Calibrate severity: Critical issues that would lead to rejection vs. minor suggestions

## Common Reviewer Concerns (Top 10)

1. Insufficient novelty over prior work
2. Missing comparison with state-of-the-art baselines
3. Statistical significance not established (no p-values, effect sizes)
4. Reproducibility concerns (missing details, no code)
5. Overclaimed contributions (results don't support conclusions)
6. Incomplete related work (missing key references)
7. Unclear methodology (can't replicate from paper alone)
8. Poor writing quality (structure, grammar, flow)
9. Missing ablation studies
10. Ethical concerns (bias, fairness, privacy)

## Venue-Specific Review Standards

### Top ML Conferences (NeurIPS, ICML, ICLR)
- Novelty weight: 30%, Soundness: 30%, Significance: 20%, Clarity: 20%
- Expect: Ablation studies, comparison with SOTA, theoretical justification
- Typical accept rate: 20-25%

### Nature / Science
- Impact weight: 40%, Novelty: 30%, Rigor: 20%, Presentation: 10%
- Expect: Broad significance, mechanistic insight, impeccable methodology
- Typical accept rate: 5-8%

### Domain Journals (JMLR, TPAMI, etc.)
- Technical depth: 35%, Novelty: 25%, Completeness: 25%, Presentation: 15%
- Expect: Thorough experiments, detailed proofs, comprehensive related work

## Response Strategy Guide

### For "Insufficient Novelty" Comments
1. Clearly differentiate your contribution from cited prior work
2. Add a detailed comparison table (your method vs. alternatives)
3. Emphasize the specific technical advance (not just "better results")

### For "Missing Experiments" Comments
1. Run the requested experiment
2. If infeasible, explain why and offer alternatives
3. Add the results to an appendix if the main text is space-constrained

### For "Writing Quality" Comments
1. Thank the reviewer for the suggestions
2. List specific changes made (section X, paragraph Y)
3. Consider having the paper proofread by a native speaker

### For "Reproducibility" Comments
1. Release code (or commit to releasing upon acceptance)
2. Provide a detailed experimental setup section
3. Include random seeds, hardware specs, and training time
