# BibTeX Citation Template

Use this template when the user mentions BibTeX, LaTeX, wants machine-readable references, or is writing a paper that will be typeset with a LaTeX citation style (natbib, biblatex, etc.).

## Critical: use `@misc`, not `@article`, for arXiv papers

**arXiv preprints must be cited as `@misc`, not `@article`.** This is the most common mistake when generating BibTeX for arXiv papers, and it matters:

- `@article` requires a `journal` field. arXiv is not a journal — it is a preprint server. Using `@article` with `journal = {arXiv}` is technically wrong and some bibliography styles will complain or render it inconsistently.
- `@misc` is the correct entry type for preprints, technical reports, and other non-journal publications. It accepts `howpublished` and `eprint` fields, which is exactly what arXiv citations need.
- Only switch to `@article` (or `@inproceedings`) when the paper has been **formally published** in a peer-reviewed venue and you have the venue metadata. In this workflow we only have arXiv metadata, so always emit `@misc`.

## Citation Format Rules

### Entry structure for arXiv preprints

```bibtex
@misc{citekey,
  author        = {LastName1, FirstName1 and LastName2, FirstName2 and ...},
  title         = {Title of the Paper},
  year          = {YYYY},
  eprint        = {ARXIV_ID},
  archivePrefix = {arXiv},
  primaryClass  = {PRIMARY_CATEGORY},
  url           = {https://arxiv.org/abs/ARXIV_ID}
}
```

**Real example**:

```bibtex
@misc{vaswani2017attention,
  author        = {Vaswani, Ashish and Shazeer, Noam and Parmar, Niki and Uszkoreit, Jakob and Jones, Llion and Gomez, Aidan N. and Kaiser, {\L}ukasz and Polosukhin, Illia},
  title         = {Attention Is All You Need},
  year          = {2017},
  eprint        = {1706.03762},
  archivePrefix = {arXiv},
  primaryClass  = {cs.CL},
  url           = {https://arxiv.org/abs/1706.03762}
}
```

### Field rules

- **Cite key**: `<firstauthorlast><year><firstwordoftitle>`, all lowercase, no punctuation. Example: `vaswani2017attention`. Keys must be unique within the report.
- **`author`**: `LastName, FirstName and LastName, FirstName and ...` — note the literal word `and` between authors, not a comma. LaTeX requires this exact separator. LastName comes first, then a comma, then the given names.
- **Special characters**: escape or wrap LaTeX-sensitive characters. For example, `Łukasz` becomes `{\L}ukasz`, `é` becomes `{\'e}` (or wrap the whole name in braces to preserve casing: `{Łukasz}`). If unsure, wrap the problematic name in curly braces.
- **`title`**: preserve the paper's capitalization by wrapping it in double braces if it contains acronyms or proper nouns you need to keep capitalized: `title = {{BERT}: Pre-training of Deep Bidirectional Transformers}`. Otherwise plain braces are fine.
- **`year`**: the 4-digit year from the paper's `published` field.
- **`eprint`**: the **bare arXiv id** (e.g. `1706.03762`), **without** the `arXiv:` prefix and **without** the version suffix.
- **`archivePrefix`**: literal string `{arXiv}`.
- **`primaryClass`**: the first category from the paper's `categories` list (e.g. `cs.CL`, `cs.CV`, `stat.ML`). This is the paper's primary subject area.
- **`url`**: the full `abs_url` from paper metadata.

## Report Structure

The BibTeX report is slightly different from APA / IEEE: the **bibliography is a separate `.bib` file**, and the main report uses LaTeX-style `\cite{key}` references that would resolve against that file. Since we are emitting markdown, we show `\cite{key}` verbatim in the prose and emit the BibTeX entries inside a fenced code block at the end.

```markdown
# Systematic Literature Review: <Topic>

**Date**: <YYYY-MM-DD>
**Papers surveyed**: <N>
**Scope**: <arXiv search query, category, time window>
**Citation format**: BibTeX

## Executive Summary

<3-5 sentences. Use \cite{key} form for citations, e.g. "Transformer architectures \cite{vaswani2017attention} have become the dominant approach.">

## Methodology

This review surveyed <N> arXiv papers retrieved on <YYYY-MM-DD> using the query `<query>`<, filtered to category <cat>><, published between <start_date> and <end_date>>. Metadata extraction was performed by language-model agents, with cross-paper synthesis performed by the lead agent. All citations in this report use BibTeX cite keys; the corresponding `.bib` entries are at the end of this document.

**Limitations of this review**: arXiv preprints are not peer-reviewed; coverage is limited to arXiv.

## Themes

### Theme 1: <Theme name>

<Paragraphs describing the theme. Cite with \cite{key} form: "The original transformer architecture \cite{vaswani2017attention} introduced self-attention, which was later extended in \cite{dai2019transformerxl}.">

### Theme 2: <Theme name>

<...>

## Convergences and Disagreements

**Convergences**: <e.g. "Multiple papers \cite{key1,key2,key3} agree that X is necessary.">

**Disagreements**: <...>

## Gaps and Open Questions

<...>

## Per-Paper Annotations

### \cite{vaswani2017attention} — "Attention Is All You Need" (2017)

**Research question**: <1 sentence>
**Methodology**: <1-2 sentences>
**Key findings**:
- <bullet>
- <bullet>
- <bullet>
**Limitations**: <1-2 sentences>

### \cite{devlin2018bert} — "BERT: Pre-training of Deep Bidirectional Transformers" (2018)

<...>

## BibTeX Bibliography

Save the entries below to a `.bib` file and reference them from your LaTeX document with `\bibliography{filename}`.

\`\`\`bibtex
@misc{vaswani2017attention,
  author        = {Vaswani, Ashish and Shazeer, Noam and Parmar, Niki and Uszkoreit, Jakob and Jones, Llion and Gomez, Aidan N. and Kaiser, {\L}ukasz and Polosukhin, Illia},
  title         = {Attention Is All You Need},
  year          = {2017},
  eprint        = {1706.03762},
  archivePrefix = {arXiv},
  primaryClass  = {cs.CL},
  url           = {https://arxiv.org/abs/1706.03762}
}

@misc{devlin2018bert,
  author        = {Devlin, Jacob and Chang, Ming-Wei and Lee, Kenton and Toutanova, Kristina},
  title         = {{BERT}: Pre-training of Deep Bidirectional Transformers for Language Understanding},
  year          = {2018},
  eprint        = {1810.04805},
  archivePrefix = {arXiv},
  primaryClass  = {cs.CL},
  url           = {https://arxiv.org/abs/1810.04805}
}

... more entries, one per paper ...
\`\`\`
```

(Note: in the actual saved report, use a real fenced code block `` ```bibtex `` — the backticks above are escaped only because this template file itself is inside a markdown code block when rendered.)

## Quality checks before finalizing

Before saving the report, verify:

- [ ] Every entry is `@misc`, not `@article` (this workflow only has arXiv metadata).
- [ ] Cite keys are unique within the report.
- [ ] Cite keys follow the `<firstauthorlast><year><firstword>` pattern, all lowercase.
- [ ] `author` field uses ` and ` (the literal word) between authors, not commas.
- [ ] LaTeX special characters in author names are escaped or brace-wrapped.
- [ ] `eprint` is the bare arXiv id (no `arXiv:` prefix, no version suffix).
- [ ] `primaryClass` is set from the paper's first category.
- [ ] Every `\cite{key}` in the text has a matching `@misc` entry in the bibliography.
- [ ] The bibliography is emitted inside a fenced ```` ```bibtex ```` code block so users can copy-paste directly into a `.bib` file.
