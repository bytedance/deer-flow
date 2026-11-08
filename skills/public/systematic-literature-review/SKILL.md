---
name: systematic-literature-review
description: Use this skill when the user wants a systematic literature review, survey, or synthesis across multiple academic papers on a topic. Also covers annotated bibliographies and cross-paper comparisons. Searches arXiv and outputs reports in APA, IEEE, or BibTeX format. Not for single-paper tasks — use academic-paper-review for reviewing one paper.
---

# Systematic Literature Review Skill

## Overview

This skill produces a structured **systematic literature review (SLR)** across multiple academic papers on a research topic. Given a topic query, it searches arXiv, extracts structured metadata (research question, methodology, key findings, limitations) from each paper in parallel, synthesizes themes across the full set, and emits a final report with consistent citations.

**Distinct from `academic-paper-review`:** that skill does deep peer review of a single paper. This skill does breadth-first synthesis across many papers. If the user hands you one paper URL and asks "review this paper", route to `academic-paper-review` instead.

## When to Use This Skill

Use this skill when the user wants any of the following:

- A literature survey on a topic ("survey transformer attention variants", "review the literature on diffusion models")
- A synthesis across multiple papers ("what do recent papers say about X", "compare methodologies across papers on Y")
- A systematic review with consistent citation format ("do an SLR on Z in APA format")
- An annotated bibliography on a topic
- An overview of research trends in a field over a time window

Do **not** use this skill when:

- The user provides exactly one paper and asks to review it (use `academic-paper-review`)
- The user asks a factual question that does not require synthesizing multiple sources (answer directly)
- The user wants general web research without academic rigor (use standard web search)

## Workflow

Use the phases as a guide, reusing information and evidence already supplied.

### Phase 1: Plan

Use the supplied context for these choices. Ask a concise clarification only when missing information would materially change the review; otherwise state reasonable scope assumptions and begin retrieval.

- **Topic**: the research question in the user’s language (e.g. "transformer attention variants").
- **Scope**: how many papers (choose a useful initial scope when unspecified), optional time window (e.g. "last 2 years"), optional arXiv category (e.g. `cs.CL`, `cs.CV`).
- **Citation format**: APA, IEEE, or BibTeX (default APA if the user does not specify and does not seem to be writing for a specific venue).
- **Output location**: where to save the final report (default `/mnt/user-data/outputs/`).

For large surveys, agree on coverage and resource limits; organize extraction by sub-topic when useful. Report the actual coverage rather than imposing an arbitrary paper ceiling.

### Phase 2: Search arXiv

Call the bundled search script. Do **not** try to scrape arXiv by other means and do **not** write your own HTTP client — this script handles URL encoding, Atom XML parsing, and id normalization correctly.

```bash
python /mnt/skills/public/systematic-literature-review/scripts/arxiv_search.py \
  "<topic>" \
  --max-results <N> \
  [--category <cat>] \
  [--sort-by relevance] \
  [--start-date YYYY-MM-DD] \
  [--end-date YYYY-MM-DD]
```

Preserve the user's research question, including population, application, comparison and time constraints. The script quotes multi-word queries as phrases; choose a useful concept phrase and apply supported category/date filters. If one phrase cannot express the scope, use a bounded set of complementary searches and screen against the original question. Do not silently drop meaningful qualifiers.

The script prints a JSON array to stdout. Each paper has: `id`, `title`, `authors`, `abstract`, `published`, `updated`, `categories`, `pdf_url`, `abs_url`.

**Sort strategy**:

- Start with relevance sorting for topical retrieval. Use date sorting when recency or chronology is the main selection criterion, and screen every result against the research question.
- Combine a time-window request with supported date filters. Choose relevance or date order according to whether topical fit or recency is the user's selection priority.
- Use lastUpdatedDate when revision activity matters to the question. Record the chosen sort and filters so coverage is reproducible.

Refine a search when empty, off-topic or incomplete results justify it. Record queries and filters, deduplicate by arXiv identifier, and stop when the requested coverage is met or the available search budget is exhausted. Explain remaining coverage gaps.

**If the script returns fewer papers than requested**, report the returned count without padding. This does not establish exhaustive coverage of the topic; refine or complement the query when warranted.

**If the script fails** (network error, non-200 from arXiv), tell the user which error and stop. Do not try to fabricate paper metadata.

Keep search provenance with the report. Intermediate files are optional when they help reproducibility or context management.

### Phase 3: Extract evidence

Extract small collections directly. For larger collections, delegate only when available, authorized and useful for the workload and context budget. Choose batch size from abstract length and extraction complexity; respect the runtime's current concurrency limit. Each delegated batch receives the existing source text and returns structured evidence with paper identifiers. Avoid duplicate network searches.

Distinguish abstract-based findings from full-text findings. Do not infer experimental details or results absent from the supplied source. Validate extraction identifiers and coverage before synthesis. The following schema can be used directly or in a delegated request.

**What each subagent receives**, as a structured prompt:

```
Execute this task: extract structured metadata and key findings from the
following arXiv papers.

Papers:
[Paper 1]
arxiv_id: 1706.03762
title: Attention Is All You Need
authors: Ashish Vaswani, Noam Shazeer, ...
published: 2017-06-12
abstract: <full abstract text>

[Paper 2]
arxiv_id: ...
...

For each paper, return a JSON object with these fields:
- arxiv_id (string)
- title (string)
- authors (list of strings)
- published_date (string, YYYY-MM-DD)
- research_question (1 sentence, what problem the paper tackles)
- methodology (1-2 sentences, how they tackle it)
- key_findings (source-supported findings; an empty list is valid if none are available)
- limitations (1-2 sentences, what they acknowledge or what is obviously missing)

Return the result as a JSON array, one object per paper, in the same
order as the input. Do not include any text outside the JSON — no
preamble, no markdown fences, just the array.
```

**Parsing subagent results**: the task tool returns strings with a fixed prefix like `Task Succeeded. Result: [...JSON...]`. Strip the `Task Succeeded. Result: ` prefix (or `Task failed.` / `Task timed out.` prefixes) before trying to parse JSON. If a batch fails or returns unparseable JSON, log it, note which papers were affected, and continue with the remaining batches — do not fail the whole synthesis on one bad batch.

After all rounds complete, flatten the per-batch arrays into a single list of paper metadata objects, preserving order.

### Phase 4: Synthesize and format

Now produce the final SLR report. Two things happen here: cross-paper synthesis (thematic analysis) and citation formatting.

**Cross-paper synthesis**: the report must do more than list papers. At minimum, identify:

- **Themes**: recurring research directions, approaches, or problem framings supported by the set; do not impose a theme count.
- **Convergences**: findings that multiple papers agree on.
- **Disagreements**: where papers reach different conclusions or use incompatible methodologies.
- **Gaps**: what the collective literature does not yet address (often stated explicitly in the "limitations" fields).

If the paper set is too small or too heterogeneous to support thematic synthesis (e.g. 5 papers on wildly different sub-topics), say so explicitly in the report — do not force themes that are not there.

**Citation formatting**: the exact format depends on user preference. Read **only** the template file that matches the user's requested format, not all three:

- [templates/apa.md](templates/apa.md) — APA 7th edition. Default for social sciences and most CS journals. Use when the user requests APA or does not specify a format.
- [templates/ieee.md](templates/ieee.md) — IEEE numeric citations. Use when the user targets an IEEE conference or journal, or explicitly asks for IEEE.
- [templates/bibtex.md](templates/bibtex.md) — BibTeX entries. Use when the user mentions BibTeX, LaTeX, or wants machine-readable references. Known preprints without verified venue metadata use `@misc`; verified publications use the appropriate entry type.

Each template contains both the citation rules and a full report structure (executive summary, themes, per-paper annotations, references, methodology section). Adapt the template structure to the requested scope, filling it with source-supported evidence from Phase 3. Omit unsupported sections.

### Phase 5: Save and present

Save the full report to `/mnt/user-data/outputs/slr-<topic-slug>-<YYYYMMDD>.md` where `<topic-slug>` is a lowercased hyphenated version of the topic (e.g. `transformer-attention`). Then call the `present_files` tool with that path so the user can download it.

**In the chat message**, show a short preview so the user immediately sees value without opening the file:

1. **Executive summary** — the main supported findings and material uncertainty, at a length appropriate to the request.
2. **Themes list** — bullet list of the themes you identified in Phase 4 synthesis (just the theme names + one-line gloss, not the full theme sections).
3. **Paper count + a pointer to the file** — e.g. "Full report with 20 papers, per-paper annotations, and formatted references saved to `slr-transformer-attention-20260409.md`."

Do **not** dump the full 2000+ word report inline — per-paper annotations, references, and methodology belong in the file. The preview is there to let the user judge the report at a glance and decide whether to open it.

## Examples

**Example 1: Typical SLR request**

User: "Do a systematic literature review of recent transformer attention variants, 20 papers, APA format."

Your flow:
1. Phase 1: use the supplied topic, 20-paper scope and APA format. Choose and state a reasonable time window from context; ask only if that choice materially affects the review.
2. Phase 2: search the specified attention-variant topic using complementary query terms and an explicit date window relative to the actual review date. Preserve qualifiers and record caps, screening and deduplication.
3. Phase 3: Extract the papers directly or in bounded batches, according to context and available authorized tools. Aggregate and check coverage.
4. Phase 4: read `templates/apa.md`, write the report using its structure, fill in themes + per-paper annotations from Phase 3 metadata.
5. Phase 5: save to `slr-transformer-attention-20260409.md`, call `present_files`.

**Example 2: Small-set request with ambiguity**

User: "Survey a few papers on diffusion models for me."

Your flow:
1. Phase 1: choose and state a modest initial scope from context; ask only if the scope would materially affect usefulness.
2. If the user specifies "10, BibTeX", use those choices.
3. Phase 2: `arxiv_search.py "diffusion models" --max-results 10 --category cs.CV`.
4. Phase 3: Extract the small collection directly; optional delegation depends on available tools and workload.
5. Phase 4: read `templates/bibtex.md`, choosing entry types from verified publication metadata.
6. Phase 5: save and present.

**Example 3: Out-of-scope request**

User: "Here's one paper (https://arxiv.org/abs/1706.03762). Can you review it?"

This is a single-paper peer review, not a literature survey. Do not use this skill. Route to `academic-paper-review` instead.

## Notes

- **arXiv only, by design**. This skill does not query Semantic Scholar, PubMed, or Google Scholar. State this database limitation in the report; do not claim exhaustive literature coverage. Multi-source academic search belongs in a dedicated MCP server, not inside this skill.
- **Subagent results are strings, not objects**. Always strip the `Task Succeeded. Result: ` / `Task failed.` / `Task timed out.` prefixes before parsing the JSON payload.
- **The `id` field is a bare arXiv id** (e.g. `1706.03762`), not a URL and not with a version suffix. `abs_url` / `pdf_url` hold the full URLs if you need them.
- **Synthesis, not listing**. The final report must identify themes and compare findings across papers. A report that only lists papers one after another is a failure mode — if you cannot find themes, say so explicitly instead of faking them.
