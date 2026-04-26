# APA 7th Edition Citation Template

Use this template when the user requests APA format, or when they do not specify a format. APA 7th is the default for social sciences and most CS journals outside of IEEE venues.

## Citation Format Rules

### In-text citations

- **Single author**: `(Vaswani, 2017)` or `Vaswani (2017) showed that...`
- **Two authors**: `(Vaswani & Shazeer, 2017)` — use `&` inside parentheses, "and" in running text.
- **Three or more authors**: `(Vaswani et al., 2017)` — use `et al.` from the first citation onward (APA 7th changed this from APA 6th).
- **Multiple citations**: `(Vaswani et al., 2017; Devlin et al., 2018)` — alphabetical order, separated by semicolons.

### Reference list entry for arXiv preprints

arXiv papers are preprints, not formally published articles. Cite them as preprints with the arXiv identifier:

```
Author, A. A., Author, B. B., & Author, C. C. (Year). Title of the paper. arXiv. https://arxiv.org/abs/ARXIV_ID
```

**Real example** (from paper metadata `{id: "1706.03762", title: "Attention Is All You Need", authors: ["Ashish Vaswani", "Noam Shazeer", "Niki Parmar", "Jakob Uszkoreit", "Llion Jones", "Aidan N. Gomez", "Łukasz Kaiser", "Illia Polosukhin"], published: "2017-06-12"}`):

```
Vaswani, A., Shazeer, N., Parmar, N., Uszkoreit, J., Jones, L., Gomez, A. N., Kaiser, Ł., & Polosukhin, I. (2017). Attention is all you need. arXiv. https://arxiv.org/abs/1706.03762
```

Formatting rules:

- **Author names**: `LastName, FirstInitial.` (middle initial optional). Join with commas; last author gets an `&`.
- **Year**: the `published` field's year, in parentheses.
- **Title**: sentence case (only first word and proper nouns capitalized). Italicize titles in typeset output; in plain markdown, leave plain.
- **Source**: the literal word `arXiv`, then the full abs URL.
- **No DOI** unless the paper has also been published in a venue with a DOI. arXiv alone uses the URL.

### Special cases

- **Up to 20 authors**: list all of them separated by commas, with `&` before the last.
- **21 or more authors**: list the first 19, then `...`, then the final author.
- **No DOI and no URL**: not possible for arXiv papers; always use the `abs_url` from the paper metadata.

## Report Structure

Follow this structure verbatim when writing the SLR report body. Fill in content from your Phase 3 extraction and Phase 4 synthesis.

```markdown
# Systematic Literature Review: <Topic>

**Date**: <YYYY-MM-DD>
**Papers surveyed**: <N>
**Scope**: <arXiv search query, category, time window>
**Citation format**: APA 7th edition

## Executive Summary

<3-5 sentences summarizing the state of the literature on this topic. What do the surveyed papers collectively tell us? What is the shape of the field? Avoid listing papers — synthesize.>

## Methodology

This review surveyed <N> arXiv papers retrieved on <YYYY-MM-DD> using the query `<query>`<, filtered to category <cat>><, published between <start_date> and <end_date>>. Papers were sorted by <relevance | submission date> and the top <N> were included. Metadata extraction (research question, methodology, key findings, limitations) was performed by language-model agents, with cross-paper synthesis performed by the lead agent.

**Limitations of this review**: arXiv preprints are not peer-reviewed; some included papers may not reflect their final published form. Coverage is limited to arXiv — papers published directly in venues without arXiv preprints are not represented.

## Themes

<3-6 thematic sections. Each theme is a recurring research direction, problem framing, or methodological approach across the surveyed papers.>

### Theme 1: <Theme name>

<2-4 paragraphs describing this theme. Cite papers inline as you discuss them, e.g. "Vaswani et al. (2017) introduced X, while subsequent work (Devlin et al., 2018; Liu et al., 2019) extended it to Y." Do not just list papers — describe the intellectual thread that connects them.>

### Theme 2: <Theme name>

<...>

## Convergences and Disagreements

**Convergences**: <findings that multiple papers agree on — e.g. "Most surveyed papers agree that X is necessary, citing evidence from Y and Z.">

**Disagreements**: <where papers reach different conclusions — e.g. "Vaswani et al. (2017) argue that X, while Dai et al. (2019) find the opposite under condition Y.">

## Gaps and Open Questions

<What the collective literature does not yet address. Pull from the "limitations" field of your Phase 3 extraction and identify patterns — if 5 papers all mention the same missing piece, that is a gap worth flagging.>

## Per-Paper Annotations

<One subsection per paper, ordered by year then first author. Each subsection is a mini-summary of that paper's contribution.>

### Vaswani et al. (2017)

**Research question**: <1 sentence from Phase 3 metadata>
**Methodology**: <1-2 sentences>
**Key findings**:
- <bullet>
- <bullet>
- <bullet>
**Limitations**: <1-2 sentences>

### <Next paper>

<...>

## References

<Alphabetical list by first author's last name, APA 7th format as described above.>

Devlin, J., Chang, M.-W., Lee, K., & Toutanova, K. (2018). BERT: Pre-training of deep bidirectional transformers for language understanding. arXiv. https://arxiv.org/abs/1810.04805

Vaswani, A., Shazeer, N., Parmar, N., Uszkoreit, J., Jones, L., Gomez, A. N., Kaiser, Ł., & Polosukhin, I. (2017). Attention is all you need. arXiv. https://arxiv.org/abs/1706.03762

<... more entries, one per paper ...>
```

## Quality checks before finalizing

Before saving the report, verify:

- [ ] Every paper in the surveyed set appears **both** in "Per-Paper Annotations" **and** in "References".
- [ ] Every in-text citation matches a reference entry (no dangling citations).
- [ ] Authors are formatted `LastName, FirstInitial.` — not `FirstName LastName`.
- [ ] Years are in parentheses inline, and at the start of reference entries.
- [ ] Titles are in sentence case in references (only first word + proper nouns capitalized).
- [ ] arXiv URLs use the `abs_url` form (`https://arxiv.org/abs/...`), not `pdf_url`.
- [ ] References are alphabetized by first author's last name.
