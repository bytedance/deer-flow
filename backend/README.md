# DeerFlow Backend

DeerFlow is a LangGraph-based AI super agent with sandbox execution, persistent memory, and extensible tool integration. The backend enables AI agents to execute code, browse the web, manage files, delegate tasks to subagents, and retain context across conversations - all in isolated, per-thread environments.

---

## Architecture

```
                        ┌──────────────────────────────────────┐
                        │          Nginx (Port 2026)           │
                        │      Unified reverse proxy           │
                        └───────┬──────────────────┬───────────┘
                                │                  │
              /api/langgraph/*  │                  │  /api/* (other)
                                ▼                  ▼
               ┌────────────────────┐  ┌────────────────────────┐
               │ LangGraph Server   │  │   Gateway API (8001)   │
               │    (Port 2024)     │  │   FastAPI REST         │
               │                    │  │                        │
               │ ┌────────────────┐ │  │ Models, MCP, Skills,   │
               │ │  Lead Agent    │ │  │ Memory, Uploads,       │
               │ │  ┌──────────┐  │ │  │ Artifacts              │
               │ │  │Middleware│  │ │  └────────────────────────┘
               │ │  │  Chain   │  │ │
               │ │  └──────────┘  │ │
               │ │  ┌──────────┐  │ │
               │ │  │  Tools   │  │ │
               │ │  └──────────┘  │ │
               │ │  ┌──────────┐  │ │
               │ │  │Subagents │  │ │
               │ │  └──────────┘  │ │
               │ └────────────────┘ │
               └────────────────────┘
```

**Request Routing** (via Nginx):
- `/api/langgraph/*` → LangGraph Server - agent interactions, threads, streaming
- `/api/*` (other) → Gateway API - models, MCP, skills, memory, artifacts, uploads
- `/` (non-API) → Frontend - Next.js web interface

---

## Core Components

### Lead Agent

The single LangGraph agent (`lead_agent`) is the runtime entry point, created via `make_lead_agent(config)`. It combines:

- **Dynamic model selection** with thinking and vision support
- **Middleware chain** for cross-cutting concerns (11 middlewares)
- **Tool system** with sandbox, MCP, community, and built-in tools
- **Subagent delegation** for parallel task execution
- **System prompt** with skills injection, memory context, and working directory guidance

### Middleware Chain

Middlewares execute in strict order, each handling a specific concern:

| # | Middleware | Purpose |
|---|-----------|---------|
| 1 | **ThreadDataMiddleware** | Creates per-thread isolated directories (workspace, uploads, outputs) |
| 2 | **UploadsMiddleware** | Injects newly uploaded files into conversation context |
| 3 | **SandboxMiddleware** | Acquires sandbox environment for code execution |
| 4 | **SummarizationMiddleware** | Reduces context when approaching token limits (optional) |
| 5 | **TodoListMiddleware** | Tracks multi-step tasks in plan mode (optional) |
| 6 | **TitleMiddleware** | Auto-generates conversation titles after first exchange |
| 7 | **MemoryMiddleware** | Queues conversations for async memory extraction |
| 8 | **ViewImageMiddleware** | Injects viewed image(s) and a configurable analysis prompt (conditional) |
| 9 | **ScientificImageReportMiddleware** | Generates `<image_report>` (JSON) via a dedicated vision model and injects it into the conversation (optional) |
| 10 | **AutoScientificClosureMiddleware** | Auto-triggers cross-modal audit + reproducible figure generation before final scientific conclusions, injects a strict final-answer template (`证据一致性摘要` + `图表复现路径`), and performs a one-pass hard rewrite fallback if sections are missing or fail quality thresholds (path items must match real artifacts) |
| 11 | **ClarificationMiddleware** | Intercepts clarification requests and interrupts execution (must be last) |

### Sandbox System

Per-thread isolated execution with virtual path translation:

- **Abstract interface**: `execute_command`, `read_file`, `write_file`, `list_dir`
- **Providers**: `LocalSandboxProvider` (filesystem) and `AioSandboxProvider` (Docker, in community/)
- **Virtual paths**: `/mnt/user-data/{workspace,uploads,outputs}` → thread-specific physical directories
- **Skills path**: `/mnt/skills` → `deer-flow/skills/` directory
- **Skills loading**: Recursively discovers nested `SKILL.md` files under `skills/{public,custom}` and preserves nested container paths
- **Tools**: `bash`, `ls`, `read_file`, `write_file`, `str_replace`

### Subagent System

Async task delegation with concurrent execution:

- **Built-in agents**: `general-purpose`, `bash`, `literature-reviewer`, `statistical-analyst`, `code-reviewer`, `data-scientist`
- **Manuscript agent**: `writer-agent` for evidence-aware draft/revision with conservative claim calibration
- **Scientific audit agents**: `facs-auditor`, `blot-auditor`, `tsne-auditor`, `spectrum-auditor`
- **Concurrency**: Max 3 subagents per turn, 15-minute timeout
- **Execution**: Background thread pools with status tracking and SSE events
- **Flow**: Agent calls `task()` tool → executor runs subagent in background → polls for completion → returns result

### Memory System

LLM-powered persistent context retention across conversations:

- **Automatic extraction**: Analyzes conversations for user context, facts, and preferences
- **Structured storage**: User context (work, personal, top-of-mind), history, and confidence-scored facts
- **Debounced updates**: Batches updates to minimize LLM calls (configurable wait time)
- **System prompt injection**: Top facts + context injected into agent prompts
- **Storage**: JSON file with mtime-based cache invalidation
- **Long-horizon intuition memory**: Stores hypothesis validation trajectories (including failed/reopened attempts) and recalls them for future idea checks

### Tool Ecosystem

| Category | Tools |
|----------|-------|
| **Sandbox** | `bash`, `ls`, `read_file`, `write_file`, `str_replace` |
| **Built-in** | `present_files`, `ask_clarification`, `view_image`, `extract_image_evidence`, `analyze_fcs`, `analyze_embedding_csv`, `analyze_spectrum_csv`, `analyze_densitometry_csv`, `audit_cross_modal_consistency`, `generate_reproducible_figure`, `research_project`, `research_fulltext_ingest`, `academic_eval`, `task` (subagent) |
| **Community** | Tavily (web search), Jina AI (web fetch), Firecrawl (scraping), DuckDuckGo (image search) |
| **MCP** | Any Model Context Protocol server (stdio, SSE, HTTP transports) |
| **Skills** | Domain-specific workflows injected via system prompt |

Research-writing runtime highlights:
- `research_fulltext_ingest` now returns passage evidence plus dynamic GraphRAG context: citation graph (co-citation edges, timeline threads) and literature debate graph (support/refute/reconcile claim map with synthesis threads).
- `research_project` now supports capability-governance actions: `get_capability_catalog` (能力清单/指标/失败模式库) and `assess_capabilities` (项目/章节能力评分卡与触发失败模式) for continuous quality gating.
- Section compilation enforces `ClaimConstraintCompiler` grounding so each claim binds to Data ID and/or Citation ID, with strict-mode downgrade markers when grounding is missing.
- `plan_narrative` / `compile_section` now enforce bind-first drafting via a persisted `claim_map` (`Claim ID | core_claim | support_data_ids | support_citation_ids | caveat`), with rewrite-required validation when IDs are missing/invalid.
- Runtime payloads and artifact ledger entries now carry `prompt_pack_id` + `prompt_pack_hash` + `runtime_strategy` (narrative / peer_review / journal_style / policy_snapshot switches) for prompt-strategy traceability across compile/review/eval/latex pipelines.
- HITL policy snapshots now emit thread/section-level `writing_directives`; `compile_section` automatically injects these directives into the L4 style adapter so output style converges toward researcher editing preferences.
- `compile_section` now persists prompt-registry governance metadata to `details.json.metadata` (including `prompt_pack_*`, `runtime_strategy`, and `eval_impact`) and mirrors the same fields in `ArtifactLedger.record(metadata=...)` for end-to-end attribution.
- Prompt strategy is now layered and versioned (`L0` constitution, `L1` runtime protocol, `L2` stage recipes, `L3` role contracts, `L4` venue-style adapter, `L5` expert reasoning chain). Runtime payloads additionally expose `prompt_layer_*` fields for compare/rollback diagnostics.
- Non-writing subagents (`general-purpose`, `bash`, `literature-reviewer`, `statistical-analyst`, `code-reviewer`) now also compose prompts through the same layered L0-L5 header, so role handoff and expert reasoning constraints stay consistent across the full subagent registry.
- `compile_section` now runs a front-loaded `NarrativePlannerAgent` to generate a mandatory pre-writing narrative plan (`takeaway_message`, `logical_flow`, `figure_storyboard`, multi-round `self_questioning`) plus structured rhetorical scaffolds (CARS introduction moves, MEAL paragraph outline, 5-layer discussion stack) before section drafting.
- `compile_section` auto-injects professor-style literature-lineage templates from graph evidence (`citation_graph_*` + `literature_graph_*`), and each injected sentence is explicitly bound to `graph:*` evidence IDs.
- Narrative strategy is venue-aware by default (`target_venue` -> conservative/balanced/aggressive) and can be manually overridden via `narrative_style`, `narrative_max_templates`, and `narrative_evidence_density`.
- Optional journal-style alignment (`journal_style_*`) can fetch top recent high-citation papers from OpenAlex as few-shot exemplars, then adapt sentence rhythm / paragraph pacing before section generation.
- `plan_narrative` / `compile_section` / `simulate_peer_review_loop` / `compile_latex` now attach `runtime_stage_context` based on standardized pipeline stages (`ingest -> plan -> draft -> verify -> revise -> submit`) for operation-level comparability.
- `compile_section` now emits explicit `venue_style_adapter` controls (`claim_tone`, `evidence_density`, `max_templates`, sentence/paragraph rhythm targets) so style pacing is parameterized instead of implicit prompt prose.
- `compile_section` now returns and persists `engineering_gates` (schema `deerflow.engineering_gates.v1`) with hard metrics: constraint violation ratio (`issues.error` + `[grounding required]/[insufficient data]/[citation needed]` sentence rates), safety-valve trigger + reason distribution, strict HITL blocking rate, traceability coverage (`sentence -> claim -> evidence/citation`), and delivery completeness over the minimal artifact set (`compiled.md`, `details.json`, `trace.json`, `diff`, `policy_snapshot`, `compliance_audit`).
- Core-section fail-close now includes sentence-level hard-grounding diagnostics (`hard_grounding_sentence_check`) and literature mechanism-conflict alignment diagnostics (`literature_alignment_check`) to catch citation listing without `[支持]/[反驳]/[调和]` synthesis.
- Native LaTeX pipeline (`research/latex/compile`) can build `.tex` manuscripts directly from project sections or raw markdown, with optional local PDF compile via `latexmk` / `pdflatex` / `xelatex`.
- `research/latex/compile` now returns `latex_quality_gate` (schema `deerflow.engineering_gates.v1`) with cumulative compile-status distribution and failure-type clustering (`missing_engine`, `timeout`, `compile_error`, `missing_pdf`, etc.), persisted under `research-writing/metrics/latex-gates.json`.
- Agentic graph orchestration (`research/orchestration/agentic-graph/run`) introduces a non-linear blackboard loop among `data-scientist` → `experiment-designer` → `writer-agent`, with automatic reroute when evidence gaps remain.
- Hypothesis generation now persists validation outcomes into long-horizon memory and returns historical failed-attempt context to support scientific "intuition from failures".
- `review/self-play` now mines difficult trajectories (including "initially heavily rebutted but eventually accepted"), persists a writer-focused few-shot library, and auto-injects top hard-negative examples into future `writer-agent` L3 contracts.

### Gateway API

FastAPI application providing REST endpoints for frontend integration:

| Route | Purpose |
|-------|---------|
| `GET /api/models` | List available LLM models |
| `GET/PUT /api/mcp/config` | Manage MCP server configurations |
| `GET/PUT /api/skills` | List and manage skills |
| `POST /api/skills/install` | Install skill from `.skill` archive |
| `GET /api/memory` | Retrieve memory data |
| `POST /api/memory/reload` | Force memory reload |
| `GET /api/memory/config` | Memory configuration |
| `GET /api/memory/status` | Combined config + data |
| `POST /api/threads/{id}/uploads` | Upload files (auto-converts PDF/PPT/Excel/Word to Markdown) |
| `GET /api/threads/{id}/uploads/list` | List uploaded files |
| `GET /api/threads/{id}/artifacts/{path}` | Serve generated artifacts |
| `POST /api/threads/{id}/reports/image_report_pdf` | Export scientific image report artifacts as PDF |
| `POST /api/threads/{id}/reports/latex_diagnostics_markdown` | Export clustered LaTeX compile diagnostics as markdown artifact (includes reproducibility appendix with Debian/Ubuntu + Alpine templates, auto-selected runtime recommendation, one-click script, `DRY_RUN=1` preview, `STRICT=1` fail-fast mode, and recent failed-command replay snippet) |
| `POST /api/threads/{id}/research/projects/upsert` | Upsert structured research project state |
| `POST /api/threads/{id}/research/ingest/fulltext` | Ingest literature, extract evidence units, and build dynamic GraphRAG context (citation graph + claim-centric support/refute/reconcile literature graph) |
| `POST /api/threads/{id}/research/plan/narrative` | Generate pre-writing narrative plan for one section (takeaway, logical flow, figure storyboard, multi-round self-questioning, CARS moves, MEAL outline, 5-layer discussion scaffold) and return/persist a bind-first `claim_map` artifact (`claim_map_artifact_path`) |
| `POST /api/threads/{id}/research/orchestration/agentic-graph/run` | Run non-linear blackboard orchestration (`data-scientist` + `experiment-designer` + `writer-agent`) with reroute trace and artifact output |
| `POST /api/threads/{id}/research/compile/section` | Compile a section with claim→evidence→citation constraints + bind-first `claim_map` planning (`claim_id -> data/citation -> sentence_draft`) + venue-aware controllable narrative strategy (`narrative_style`, `narrative_max_templates`, `narrative_evidence_density`) + mandatory NarrativePlanner pre-step (`narrative_self_question_rounds`, `narrative_include_storyboard`) + HITL-driven policy snapshot guidance (supports explicit A/B switch `policy_snapshot_auto_adjust_narrative`) + automatic scientific compliance audit (causal overclaim / sample-bias / ethics / reproducibility) + optional auto hypothesis synthesis + peer-review loop + fail-close safety valve (`风险结论模板`) + hard-grounding/literature-alignment diagnostics (`hard_grounding_sentence_check`, `literature_alignment_check`) + engineering gate block (`engineering_gates`, `engineering_gate_artifact_path`) |
| `POST /api/threads/{id}/research/latex/compile` | Generate native LaTeX artifacts (`.tex`) and optionally compile final PDF preprint from manuscript markdown/sections, with cumulative quality-gate telemetry (`latex_quality_gate`, `latex_quality_gate_artifact_path`) |
| `POST /api/threads/{id}/research/review/simulate` | Venue-calibrated reviewer simulation + rebuttal planning |
| `POST /api/threads/{id}/research/review/peer-loop` | Multi-agent red/blue review loop (Reviewer→Author→Area Chair) with revision rounds |
| `POST /api/threads/{id}/research/review/self-play` | Multi-episode Reviewer/Author/Area-Chair self-play training with hard-negative mining |
| `POST /api/threads/{id}/research/hypotheses/generate` | Generate 3-5 scored mechanism hypotheses from evidence/citations/facts, persist validation trajectories, and return historical failed-attempt context |
| `POST /api/threads/{id}/research/compliance/audit` | Run standalone scientific ethics/compliance audit for a project section |
| `GET /api/threads/{id}/research/capabilities/catalog` | Read capability catalog (`能力清单 -> 指标 -> 失败模式库`) for governance/config review |
| `POST /api/threads/{id}/research/capabilities/assess` | Compute project/section capability scorecards with triggered failure modes and persisted audit artifact |
| `GET /api/threads/{id}/research/projects/{project_id}/policy-snapshot` | Compute policy-learning snapshot from persisted HITL approve/reject decisions |
| `GET/PUT /api/threads/{id}/research/projects/{project_id}/hitl-decisions` | Read/update HITL checkpoint decisions; response includes impact preview + policy snapshot artifact path |
| `POST /api/threads/{id}/research/evals/academic` | Run academic quality evaluations with venue/domain dynamic weighting + calibration (`AUC`, `ECE`, `Brier`) + confidence intervals, persist report artifact, and emit failure-mode red-team gates (`failure_mode_gate_*`) for regression guardrails |
| `GET /api/threads/{id}/research/evals/academic/leaderboard` | Read weekly discipline/venue leaderboard merged from persisted eval runs |

---

### Academic Eval Gate Notes

- Built-in datasets now include `failure_mode_library_v1` (red-team regression set for: citation hallucination, overclaim, numeric drift, evidence-chain break, style mismatch, superficial rebuttal, ethics gap).
- Offline layered benchmark templates are available under `src/evals/academic/templates/offline_benchmark_suite/`:
  - `core_top_venue_accept_reject_raw.json`
  - `failure_mode_hard_negatives_raw.json`
  - `domain_ai_cs_raw.json`, `domain_biomed_raw.json`, `domain_cross_discipline_raw.json`
- Regenerate the layered raw suite with:
  - `uv run python scripts/build_academic_offline_benchmark_suite.py --overwrite`
  - or from repo root: `make build-academic-offline-benchmark-suite OVERWRITE=1`
- Run offline regression gate on layered suite with:
  - `uv run python scripts/run_academic_offline_regression.py --strict-gate --overwrite`
  - or from repo root: `make run-academic-offline-regression STRICT_GATE=1 OVERWRITE=1`
- Offline regression now supports baseline drift gates (`--baseline-report`) and blocks CI on regression in citation hallucination rate / ECE / Brier (`offline-benchmark-drift.json`, `offline-benchmark-drift.md`).
- Run online regression drift automation (commit/week comparisons + alert report) with:
  - `uv run python scripts/run_academic_online_regression.py --branch <branch> --commit-sha <sha> --strict-gate --overwrite`
  - or from repo root: `make run-academic-online-regression BRANCH=<branch> COMMIT_SHA=<sha> STRICT_GATE=1 OVERWRITE=1`
- Convert OpenReview exports into offline raw benchmark payloads with:
  - `uv run python scripts/build_openreview_offline_benchmark.py --input <openreview.jsonl> --overwrite`
- `POST /research/evals/academic` responses now include gate fields:
  - `failure_mode_gate_status`
  - `failure_mode_gate_failed_modes`
  - `failure_mode_gate_targeted_case_count`
  - `failure_mode_gate_control_case_count`
  - `failure_mode_gate_by_mode`
  - `failure_mode_gate_artifact_path`
- Each eval run also writes a dedicated failure-mode artifact:
  - `.../research-writing/evals/<artifact_name>.failure-modes.json`
- Gate thresholds are configurable via `config.yaml`:
  - `failure_mode_gate.citation_fidelity_max`
  - `failure_mode_gate.overclaim_claim_grounding_max`
  - `failure_mode_gate.numeric_drift_abstract_body_max`
  - `failure_mode_gate.evidence_chain_claim_grounding_max`
  - `failure_mode_gate.style_mismatch_venue_fit_max`
  - `failure_mode_gate.superficial_rebuttal_completeness_max`
  - `failure_mode_gate.min_target_recall`
  - `failure_mode_gate.max_control_false_positive_rate`

## Quick Start

### Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) package manager
- API keys for your chosen LLM provider

### Installation

```bash
cd deer-flow

# Copy configuration files
cp config.example.yaml config.yaml

# Install backend dependencies
cd backend
make install
```

### Configuration

Edit `config.yaml` in the project root:

```yaml
models:
  - name: gpt-4o
    display_name: GPT-4o
    use: langchain_openai:ChatOpenAI
    model: gpt-4o
    api_key: $OPENAI_API_KEY
    supports_thinking: false
    supports_vision: true
    # Optional: Override the default scientific image analysis instruction
    # used by ViewImageMiddleware when images are injected.
    # vision_prompt: |
    #   Please deeply analyze these scientific images (e.g., Western Blot, t-SNE, FACS, astronomical spectra, microscopy, etc.).
    #   Do not just describe them superficially. You must:
    #   1. Extract quantitative trends and structural patterns directly from the visual data.
    #   2. Identify key features, anomalies, and control group comparisons.
    #   3. Draw rigorous scientific conclusions based on the visual evidence.

# Optional: scientific vision pre-analysis (ImageReport injection)
scientific_vision:
  enabled: false
  inject_mode: index
  model_name: null
  artifact_subdir: scientific-vision/image-reports
  cache_enabled: true
  max_images: 4
  write_batch_artifact: true
  include_raw_model_output_in_batch: true
  write_index_artifact: true
  evidence_enabled: false
  evidence_parsers: ["western_blot", "facs", "tsne", "spectrum"]
  evidence_write_csv: true
  evidence_write_overlay: true

# Optional: scientific raw-data analysis tools independent of image-report flow
scientific_data:
  enabled: false
  # When enabled (or when scientific_vision.enabled=true), DeerFlow also exposes:
  # - audit_cross_modal_consistency
  # - generate_reproducible_figure
  # plus analyze_fcs / analyze_embedding_csv / analyze_spectrum_csv / analyze_densitometry_csv

# Optional: journal-specific style alignment (few-shot from OpenAlex)
journal_style:
  enabled: false
  sample_size: 5
  recent_year_window: 5
  request_timeout_seconds: 12
  cache_ttl_hours: 24
  max_excerpt_chars: 1200

# Optional: layer-version overrides for prompt-pack experiments/rollback
# Example:
# export DEER_FLOW_PROMPT_LAYER_OVERRIDES='{"L2":"v0","L4":"v0","L5":"v0"}'
# Layer IDs: L0/L1/L2/L3/L4/L5

# Optional: native LaTeX manuscript pipeline
latex:
  enabled: true
  default_engine: auto
  compile_pdf_default: true
  compile_timeout_seconds: 90
  artifact_subdir: research-writing/latex
```

Set your API keys:

```bash
export OPENAI_API_KEY="your-api-key-here"
```

### Running

**Full Application** (from project root):

```bash
make dev  # Starts LangGraph + Gateway + Frontend + Nginx
```

Access at: http://localhost:2026

**Backend Only** (from backend directory):

```bash
# Terminal 1: LangGraph server
make dev

# Terminal 2: Gateway API
make gateway
```

Direct access: LangGraph at http://localhost:2024, Gateway at http://localhost:8001

---

## Project Structure

```
backend/
├── src/
│   ├── agents/                  # Agent system
│   │   ├── lead_agent/         # Main agent (factory, prompts)
│   │   ├── middlewares/        # 9 middleware components
│   │   ├── memory/             # Memory extraction & storage
│   │   └── thread_state.py    # ThreadState schema
│   ├── gateway/                # FastAPI Gateway API
│   │   ├── app.py             # Application setup
│   │   └── routers/           # 6 route modules
│   ├── sandbox/                # Sandbox execution
│   │   ├── local/             # Local filesystem provider
│   │   ├── sandbox.py         # Abstract interface
│   │   ├── tools.py           # bash, ls, read/write/str_replace
│   │   └── middleware.py      # Sandbox lifecycle
│   ├── subagents/              # Subagent delegation
│   │   ├── builtins/          # general-purpose, bash agents
│   │   ├── executor.py        # Background execution engine
│   │   └── registry.py        # Agent registry
│   ├── tools/builtins/         # Built-in tools
│   ├── mcp/                    # MCP protocol integration
│   ├── models/                 # Model factory
│   ├── skills/                 # Skill discovery & loading
│   ├── config/                 # Configuration system
│   ├── community/              # Community tools & providers
│   ├── reflection/             # Dynamic module loading
│   └── utils/                  # Utilities
├── docs/                       # Documentation
├── tests/                      # Test suite
├── langgraph.json              # LangGraph server configuration
├── pyproject.toml              # Python dependencies
├── Makefile                    # Development commands
└── Dockerfile                  # Container build
```

---

## Configuration

### Main Configuration (`config.yaml`)

Place in project root. Config values starting with `$` resolve as environment variables.

Key sections:
- `models` - LLM configurations with class paths, API keys, thinking/vision flags
- `tools` - Tool definitions with module paths and groups
- `tool_groups` - Logical tool groupings
- `sandbox` - Execution environment provider
- `skills` - Skills directory paths
- `title` - Auto-title generation settings
- `summarization` - Context summarization settings
- `subagents` - Subagent system (enabled/disabled)
- `scientific_data` - Enable raw scientific data analysis tools independent of image-report flow
- `memory` - Memory system settings (enabled, storage, debounce, facts limits)

Provider note:
- `models[*].use` references provider classes by module path (for example `langchain_openai:ChatOpenAI`).
- If a provider module is missing, DeerFlow now returns an actionable error with install guidance (for example `uv add langchain-google-genai`).

### Extensions Configuration (`extensions_config.json`)

MCP servers and skill states in a single file:

```json
{
  "mcpServers": {
    "github": {
      "enabled": true,
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-github"],
      "env": {"GITHUB_TOKEN": "$GITHUB_TOKEN"}
    },
    "secure-http": {
      "enabled": true,
      "type": "http",
      "url": "https://api.example.com/mcp",
      "oauth": {
        "enabled": true,
        "token_url": "https://auth.example.com/oauth/token",
        "grant_type": "client_credentials",
        "client_id": "$MCP_OAUTH_CLIENT_ID",
        "client_secret": "$MCP_OAUTH_CLIENT_SECRET"
      }
    }
  },
  "skills": {
    "pdf-processing": {"enabled": true}
  }
}
```

### Environment Variables

- `DEER_FLOW_CONFIG_PATH` - Override config.yaml location
- `DEER_FLOW_EXTENSIONS_CONFIG_PATH` - Override extensions_config.json location
- `DEER_FLOW_PROMPT_PACK_ID` - Override runtime prompt-pack identifier (default: `rw.superagent.v1.3`)
- `DEER_FLOW_PROMPT_PACK_HASH` - Optional manual override for prompt-pack hash in artifacts/ledger metadata
- Model API keys: `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `DEEPSEEK_API_KEY`, etc.
- Tool API keys: `TAVILY_API_KEY`, `GITHUB_TOKEN`, etc.

---

## Development

### Commands

```bash
make install    # Install dependencies
make dev        # Run LangGraph server (port 2024)
make gateway    # Run Gateway API (port 8001)
make lint       # Run linter (ruff)
make format     # Format code (ruff)
```

### Code Style

- **Linter/Formatter**: `ruff`
- **Line length**: 240 characters
- **Python**: 3.12+ with type hints
- **Quotes**: Double quotes
- **Indentation**: 4 spaces

### Testing

```bash
uv run pytest
```

---

## Technology Stack

- **LangGraph** (1.0.6+) - Agent framework and multi-agent orchestration
- **LangChain** (1.2.3+) - LLM abstractions and tool system
- **FastAPI** (0.115.0+) - Gateway REST API
- **langchain-mcp-adapters** - Model Context Protocol support
- **agent-sandbox** - Sandboxed code execution
- **markitdown** - Multi-format document conversion
- **tavily-python** / **firecrawl-py** - Web search and scraping

---

## Documentation

- [Configuration Guide](docs/CONFIGURATION.md)
- [Architecture Details](docs/ARCHITECTURE.md)
- [API Reference](docs/API.md)
- [File Upload](docs/FILE_UPLOAD.md)
- [Path Examples](docs/PATH_EXAMPLES.md)
- [Context Summarization](docs/summarization.md)
- [Plan Mode](docs/plan_mode_usage.md)
- [Setup Guide](docs/SETUP.md)

---

## License

See the [LICENSE](../LICENSE) file in the project root.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for contribution guidelines.
