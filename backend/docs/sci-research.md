# Sci-Research Skill — Usage Guide

> **Skill path**: `skills/custom/sci-research/`
> **Skill name**: `sci-research`
> **Trigger**: "research X", "review literature on X", "analyze papers about X", "find research gaps in X"

---

## Overview

The `sci-research` skill turns DeerFlow into a professional scientific literature review assistant. It orchestrates a 6-phase pipeline — from requirements intake through literature ingestion, deep analysis, cross-paper synthesis, and final report generation — powered by OpenViking (RAG) and 4 specialized subagents.

```
Phase -1: Intake & Clarification      ← always starts here
Phase  0: Infrastructure Check
Phase  1: Literature Ingestion         ← OV indexing
Phase  2: Deep Analysis                ← per-paper structured analysis
Phase  3: Cross-paper Synthesis        ← Gap Analysis
Phase  4: Report Writing               ← assembled final report
```

---

## Prerequisites

### 1. OpenViking Service

```bash
# Verify OV is running and accessible
ov ls
```

If `ov ls` fails, the skill automatically falls back to web-only mode (no vector search, slower retrieval).

### 2. Model Configuration (`config.yaml`)

Add these model entries. Each subagent has an explicit model assignment:

```yaml
models:
  # High-quality writing — report-writer subagent
  - name: gpt-4o
    use: langchain_openai:ChatOpenAI
    model: gpt-4o
    api_key: $OPENAI_API_KEY

  # Strong reasoning — literature-analyzer subagent
  - name: deepseek-v3
    use: langchain_openai:ChatOpenAI
    model: deepseek-chat
    base_url: https://api.deepseek.com/v1
    api_key: $DEEPSEEK_API_KEY

  # Structured accuracy — data-extractor subagent
  - name: claude-3-5-sonnet
    use: langchain_anthropic:ChatAnthropic
    model: claude-3-5-sonnet-20241022
    api_key: $ANTHROPIC_API_KEY

  # Cost-efficient retrieval — ov-retriever subagent
  - name: doubao-lite
    use: langchain_openai:ChatOpenAI
    model: ep-<your-endpoint-id>
    base_url: https://ark.cn-beijing.volces.com/api/v3
    api_key: $DOUBAO_API_KEY
```

Fallback: if `doubao-lite` is unavailable, set `ov_retriever.py` → `model="gpt-4o-mini"`.

### 3. Skill Enabled

Verify in `extensions_config.json`:

```json
{
  "skills": {
    "sci-research": { "enabled": true }
  }
}
```

Or enable via Gateway API:
```bash
curl -X PUT http://localhost:8001/api/skills/sci-research \
  -H "Content-Type: application/json" \
  -d '{"enabled": true}'
```

---

## Quick Start

### Triggering the Skill

Any of these phrases invoke the skill:

```
Research transformer attention mechanisms in NLP
Review literature on protein structure prediction
Find research gaps in self-supervised learning
Write a survey of federated learning
Analyze papers about diffusion models
```

### Phase -1: Intake Dialogue

The Lead Agent will ask 5 structured questions:
1. Core research question
2. Output type (literature review / gap analysis / paper draft / ...)
3. Target audience and depth
4. Whether you have local documents to upload
5. Database/author/time-range filters

**Upload local papers**: Use the attachment button in the chat UI. Reply "continue" after uploading. Files are automatically indexed into OpenViking.

**Confirm the plan**: The Lead Agent presents a research plan draft. Select option 1 to confirm and start execution.

---

## Subagent Roster

| Subagent | Model | Role | Max turns | Timeout |
|----------|-------|------|-----------|---------|
| `literature-analyzer` | deepseek-v3 | Structured close-reading of single paper (5 sections) | 30 | 600s |
| `data-extractor` | claude-3-5-sonnet | Extract tables, numbers, comparison data | 20 | 300s |
| `report-writer` | gpt-4o | Write report chapters (Methodology / Results / Gaps) | 40 | 900s |
| `ov-retriever` | doubao-lite | Semantic search via OpenViking RAG | 15 | 180s |

**Concurrency**: Maximum 3 subagents run in parallel (enforced by `SubagentLimitMiddleware`).

---

## Output Files

All intermediate files are saved to the thread workspace:

```
/mnt/user-data/
├── uploads/                          # User-uploaded PDFs (auto-indexed)
├── workspace/
│   ├── analysis/                     # One .md file per paper (Phase 2)
│   │   ├── paper1.md
│   │   └── paper2.md
│   ├── data/                         # Extracted tables/numbers (Phase 2)
│   ├── gap-analysis.md               # Cross-paper synthesis (Phase 3)
│   └── report/                       # Chapter drafts (Phase 4)
│       ├── 00_abstract.md
│       ├── 01_introduction.md
│       ├── 03_methodology.md
│       ├── 04_results.md
│       └── 05_gaps.md
└── outputs/
    └── research_report.md            # ← Final assembled report (delivered via present_files)
```

---

## Literature Analysis Format (Phase 2)

Each `literature-analyzer` output contains 6 structured sections:

1. **Research Question / Hypothesis**
2. **Methodology** — study design, data, tools, sample size
3. **Key Findings** — quantitative results with metrics
4. **Limitations** — stated and apparent
5. **Differentiators vs. Prior Work** — novelty claims
6. **Open Questions / Future Work**

---

## Gap Analysis Format (Phase 3)

`gap-analysis.md` contains:

- **Thematic Clusters** — papers grouped by methodology
- **Consensus Findings** — table of agreed-upon results with confidence
- **Contradictions and Debates** — conflicting claims with Position A/B structure
- **Research Gaps** — minimum 3 gaps, each with:
  - Type (Unexplored combination / Missing comparison / Acknowledged limitation / Scope boundary)
  - Description, Evidence (citing specific papers), Significance, Suggested direction
- **Synthesis Notes** — strongest finding, most contested claim, highest-priority gap

---

## Citation Styles

The `report-writer` subagent supports three citation styles. Specify in Phase -1:

| Style | Inline | Example |
|-------|--------|---------|
| **APA** (default) | (Author, Year) | (Vaswani et al., 2017) |
| **IEEE** | [N] | [3] |
| **GB/T 7714** | [N] superscript | [序号] |

See `templates/citation-formats.md` for full formatting rules and journal/conference abbreviations.

---

## Troubleshooting

### OV indexing fails (error_count > 0)

```bash
ov status   # check embedding queue and error details
```

Common causes:
- PDF password-protected → ask user for unlocked version
- URL unreachable (paywalled) → download PDF manually and upload
- Embedding API quota exceeded → wait and retry

### Semantic search returns no results (score < 0.3)

1. Simplify the query (key terms only, no full sentences)
2. Check `ov ls` — confirm papers were indexed
3. Try `ov grep` for keyword fallback
4. Lower threshold: `ov find "query" --threshold 0.1`

### Subagent times out

- `literature-analyzer` timeout (600s): paper is extremely long → split into sections manually
- `report-writer` timeout (900s): chapter scope too broad → narrow the chapter assignment
- `ov-retriever` timeout (180s): OV service unresponsive → restart OV, check `ov status`

### Fewer than 3 research gaps identified

Phase 3 will not proceed to Phase 4 if fewer than 3 gaps are found. Options:
- Add more papers to the corpus (re-run Phase 1 with additional URLs)
- Run `ov-retriever` with different query phrasings
- Explicitly ask the Lead Agent to re-examine limitations sections

---

## Running Tests

```bash
# Fast unit tests (no live services required) — ~0.1s
cd backend
PYTHONPATH=. uv run pytest tests/test_sci_subagents.py tests/test_sci_ingestion.py \
  tests/test_sci_analysis.py tests/test_sci_synthesis.py tests/test_sci_report.py \
  tests/test_sci_e2e.py -v

# Integration tests (require live DeerFlow + OpenViking)
DEERFLOW_URL=http://localhost:2024 \
PYTHONPATH=. uv run pytest -m integration tests/test_sci_e2e.py -v
```

Current test coverage: **225 tests** across Phase 1–5 (unit) + 10 integration scenarios (skipped by default).
