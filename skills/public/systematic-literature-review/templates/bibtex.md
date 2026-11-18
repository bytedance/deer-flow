# BibTeX Citation Template

This is an optional formatting example. Adapt sections and length to the request and available evidence. Paper names below illustrate citation syntax only; include them only if they belong to the actual selected corpus. Describe only searches, screening, reading and delegation that actually occurred.

Use this template when the user mentions BibTeX, LaTeX, wants machine-readable references, or is writing a paper that will be typeset with a LaTeX citation style (natbib, biblatex, etc.).

## Choose the entry type from verified publication metadata

An arXiv identifier does not establish a paper's current publication status. Check available venue metadata and the user's bibliography system before selecting an entry type.

- Use `@article` for a verified journal article and `@inproceedings` for a verified conference paper, with the actual venue fields. Do not invent a journal or conference.
- For a known preprint without verified venue metadata, the standard BibTeX `@misc` example below is a useful default. A bibliography system such as biblatex may support a more specific entry type.
- Preserve the arXiv identifier as an electronic reference where supported; its presence does not force a published paper to remain a preprint citation.

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

<Summarize supported findings and uncertainty, using \cite{actual_key} citations from the selected corpus.>

## Methodology

<Describe actual databases, query variants, dates, pagination or result caps, screening, deduplication and included count. Distinguish metadata/abstract inspection from full-text reading. Mention agents only if used. Record the actual bibliography delivery path.>

**Limitations of this review**: <State actual coverage, publication status, unavailable full text and selection limitations. An arXiv-only search cannot establish coverage of the wider literature; verify publication status per paper.>

## Themes

### Theme 1: <Theme name>

<Explain the theme using \cite{actual_key} references from the selected corpus. Report only supported relationships.>

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

- [ ] Entry types match verified publication status; known arXiv-only preprints use `@misc`.
- [ ] Cite keys are unique within the report.
- [ ] Cite keys follow the `<firstauthorlast><year><firstword>` pattern, all lowercase.
- [ ] `author` field uses ` and ` (the literal word) between authors, not commas.
- [ ] LaTeX special characters in author names are escaped or brace-wrapped.
- [ ] `eprint` is the bare arXiv id (no `arXiv:` prefix, no version suffix).
- [ ] `primaryClass` is set from the paper's first category.
- [ ] Every `\cite{key}` in the text has a matching bibliography entry with verified metadata.
- [ ] The bibliography is emitted inside a fenced ```` ```bibtex ```` code block so users can copy-paste directly into a `.bib` file.
