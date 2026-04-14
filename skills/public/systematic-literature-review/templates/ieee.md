# IEEE Citation Template

Use this template when the user targets an IEEE conference or journal, or explicitly asks for IEEE format. IEEE uses **numeric citations** — references are numbered in the order they first appear in the text, and in-text citations use bracketed numbers.

## Citation Format Rules

### In-text citations

- **Single reference**: `[1]` — use the number assigned in the References section.
- **Multiple references**: `[1], [3], [5]` or `[1]–[3]` for consecutive ranges.
- **Citation as a noun**: "As shown in [1], ..." or "Reference [1] demonstrated...".
- **Author attribution**: "Vaswani et al. [1] introduced..." — author names are optional in IEEE; use them when it improves readability, always followed by the bracketed number.

Numbers are assigned in **order of first appearance in the text**, not alphabetically. The first reference you cite is `[1]`, the second new reference is `[2]`, and so on.

### Reference list entry for arXiv preprints

IEEE format for arXiv preprints:

```
[N] A. A. Author, B. B. Author, and C. C. Author, "Title of the paper," arXiv:ARXIV_ID, Year.
```

**Real example**:

```
[1] A. Vaswani, N. Shazeer, N. Parmar, J. Uszkoreit, L. Jones, A. N. Gomez, Ł. Kaiser, and I. Polosukhin, "Attention is all you need," arXiv:1706.03762, 2017.
```

Formatting rules:

- **Author names**: `FirstInitial. LastName` — initials before the last name, opposite of APA. Join with commas; last author gets `and` (no Oxford comma before it in strict IEEE, but accepted).
- **Title**: in double quotes, sentence case. No italics.
- **Source**: `arXiv:<id>` — the literal prefix `arXiv:` followed by the bare id (e.g. `arXiv:1706.03762`, not the full URL).
- **Year**: at the end, after a comma.
- **URL**: optional in IEEE. Include if the publication venue requires it; otherwise the `arXiv:<id>` identifier is sufficient and is the IEEE-preferred form.

### Special cases

- **More than 6 authors**: IEEE allows listing the first author followed by `et al.`: `A. Vaswani et al., "Attention is all you need," arXiv:1706.03762, 2017.` Use this for papers with many authors to keep reference entries readable.
- **If the paper has also been published at a venue**: prefer the venue citation format over arXiv. In this workflow we only have arXiv metadata, so always use the arXiv form.

## Report Structure

Follow this structure verbatim. Note that IEEE reports use **numeric citations throughout**, so you need to assign a number to each paper **in order of first appearance** in the Themes section, then use those numbers consistently in per-paper annotations and the reference list.

```markdown
# Systematic Literature Review: <Topic>

**Date**: <YYYY-MM-DD>
**Papers surveyed**: <N>
**Scope**: <arXiv search query, category, time window>
**Citation format**: IEEE

## Executive Summary

<3-5 sentences summarizing the state of the literature. Cite papers with bracketed numbers as you first introduce them, e.g. "Transformer architectures [1] have become the dominant approach, with extensions focusing on efficiency [2], [3] and long-context handling [4].">

## Methodology

This review surveyed <N> arXiv papers retrieved on <YYYY-MM-DD> using the query `<query>`<, filtered to category <cat>><, published between <start_date> and <end_date>>. Papers were sorted by <relevance | submission date> and the top <N> were included. Metadata extraction was performed by language-model agents, with cross-paper synthesis performed by the lead agent.

**Limitations of this review**: arXiv preprints are not peer-reviewed; coverage is limited to arXiv.

## Themes

<3-6 thematic sections. First appearance of each paper gets a bracketed number; subsequent mentions reuse the same number. The number assignment order is: first paper mentioned in Theme 1 gets [1], next new paper gets [2], etc.>

### Theme 1: <Theme name>

<Paragraphs describing the theme. Cite with bracketed numbers: "The original transformer architecture [1] introduced self-attention, which was later extended in [2] and [3]. Comparative analyses [4] show that...">

### Theme 2: <Theme name>

<...>

## Convergences and Disagreements

**Convergences**: <e.g. "Multiple papers [1], [3], [5] agree that X is necessary.">

**Disagreements**: <e.g. "While [1] argues X, [2] finds the opposite under condition Y.">

## Gaps and Open Questions

<What the collective literature does not yet address, with citations to papers that explicitly mention these gaps.>

## Per-Paper Annotations

<One subsection per paper, ordered by their assigned reference number.>

### [1] Vaswani et al., "Attention is all you need" (2017)

**Research question**: <1 sentence>
**Methodology**: <1-2 sentences>
**Key findings**:
- <bullet>
- <bullet>
- <bullet>
**Limitations**: <1-2 sentences>

### [2] <Next paper>

<...>

## References

<Numbered list in order of first appearance in the text. The number must match the in-text citations above.>

[1] A. Vaswani, N. Shazeer, N. Parmar, J. Uszkoreit, L. Jones, A. N. Gomez, Ł. Kaiser, and I. Polosukhin, "Attention is all you need," arXiv:1706.03762, 2017.

[2] J. Devlin, M.-W. Chang, K. Lee, and K. Toutanova, "BERT: Pre-training of deep bidirectional transformers for language understanding," arXiv:1810.04805, 2018.

<... more entries ...>
```

## Quality checks before finalizing

Before saving the report, verify:

- [ ] Every paper in the surveyed set has a unique reference number.
- [ ] Reference numbers are assigned in order of **first appearance in the text**, not alphabetically.
- [ ] Every bracketed number in the text has a matching entry in the References section.
- [ ] Every entry in References is cited at least once in the text.
- [ ] Author names use `FirstInitial. LastName` format (initials before last name).
- [ ] Titles are in double quotes and sentence case.
- [ ] arXiv identifiers use the `arXiv:<bare_id>` form, not the full URL.
- [ ] Per-paper annotations are ordered by reference number, matching the References section order.
