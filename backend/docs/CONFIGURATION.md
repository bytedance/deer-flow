# Configuration Guide

This guide explains how to configure DeerFlow for your environment.

## Configuration Sections

### Models

Configure the LLM models available to the agent:

```yaml
models:
  - name: gpt-4                    # Internal identifier
    display_name: GPT-4            # Human-readable name
    use: langchain_openai:ChatOpenAI  # LangChain class path
    model: gpt-4                   # Model identifier for API
    api_key: $OPENAI_API_KEY       # API key (use env var)
    max_tokens: 4096               # Max tokens per request
    temperature: 0.7               # Sampling temperature
    supports_vision: true           # Enable vision (image_url blocks)
    # Optional: override the default scientific-image analysis instruction used when
    # ViewImageMiddleware injects recently viewed images into the conversation.
    # vision_prompt: |
    #   Please deeply analyze these scientific images (e.g., Western Blot, t-SNE, FACS, astronomical spectra, microscopy, etc.).
    #   Do not just describe them superficially. You must:
    #   1. Extract quantitative trends and structural patterns directly from the visual data.
    #   2. Identify key features, anomalies, and control group comparisons.
    #   3. Draw rigorous scientific conclusions based on the visual evidence.
```

**Supported Providers**:
- OpenAI (`langchain_openai:ChatOpenAI`)
- Anthropic (`langchain_anthropic:ChatAnthropic`)
- DeepSeek (`langchain_deepseek:ChatDeepSeek`)
- Any LangChain-compatible provider

For OpenAI-compatible gateways (for example Novita), keep using `langchain_openai:ChatOpenAI` and set `base_url`:

```yaml
models:
  - name: novita-deepseek-v3.2
    display_name: Novita DeepSeek V3.2
    use: langchain_openai:ChatOpenAI
    model: deepseek/deepseek-v3.2
    api_key: $NOVITA_API_KEY
    base_url: https://api.novita.ai/openai
    supports_thinking: true
    when_thinking_enabled:
      extra_body:
        thinking:
          type: enabled
```

**Thinking Models**:
Some models support "thinking" mode for complex reasoning:

```yaml
models:
  - name: deepseek-v3
    supports_thinking: true
    when_thinking_enabled:
      extra_body:
        thinking:
          type: enabled
```

### Scientific Vision (ImageReport)

Enable an optional scientific-figure pre-analysis step that generates a structured `<image_report>` (JSON) from images loaded via the `view_image` tool:

```yaml
scientific_vision:
  enabled: true
  # Injection mode:
  # - index: inject references + summaries (recommended; token-efficient, audit-friendly)
  # - full:  inject full JSON payload (token-heavy)
  inject_mode: index
  # A vision-capable model configured in `models:` above.
  # If null, DeerFlow uses the current runtime model.
  model_name: sci-vision-model
  # Where to store audit artifacts (relative to /mnt/user-data/outputs)
  artifact_subdir: scientific-vision/image-reports
  # Reuse existing artifacts when available (cache hit = skip vision model call)
  cache_enabled: true
  max_images: 4
  prompt_template: null
  write_batch_artifact: true
  include_raw_model_output_in_batch: true
  write_index_artifact: true
  # Optional: run type-specific evidence parsers (ROI-based quantification) and persist evidence tables/overlays
  evidence_enabled: true
  evidence_parsers: ["western_blot", "facs", "tsne", "spectrum"]
  evidence_write_csv: true
  evidence_write_overlay: true
  clear_viewed_images_after_report: false
```

When enabled:
- `view_image` tool is available even for text-only main models
- DeerFlow calls the scientific vision model after `view_image` completes and injects an `<image_report>` message into the main conversation
- DeerFlow writes audit-grade artifacts under `/mnt/user-data/outputs/{artifact_subdir}/`:
  - Per-image reports: `images/sha256-<image_sha256>/report-<analysis_sig>.json`
  - Batch artifacts: `batches/batch-<batch_id>.json`
  - Injection indexes: `indexes/index-<index_id>.json`

### Scientific Data

Enable raw scientific-data tooling independent of the ImageReport pipeline:

```yaml
scientific_data:
  enabled: true
```

When `scientific_data.enabled: true` (or `scientific_vision.enabled: true`), DeerFlow exposes:
- `analyze_fcs`, `analyze_embedding_csv`, `analyze_spectrum_csv`, `analyze_densitometry_csv`
- `audit_cross_modal_consistency` (narrative claim -> evidence reverse verification)
- `generate_reproducible_figure` (code-level figure generation with SVG/PDF + metadata)

### Journal Style Alignment

Enable venue-specific few-shot style alignment before `compile_section`:

```yaml
journal_style:
  enabled: true
  sample_size: 5
  recent_year_window: 5
  request_timeout_seconds: 12
  cache_ttl_hours: 24
  max_excerpt_chars: 1200
```

Notes:
- DeerFlow resolves the target venue (for example Nature/Science/Cell and their sub-journals) via OpenAlex.
- It fetches recent high-citation papers and derives sentence-length / paragraph-rhythm directives.
- API-level overrides are available on `POST /research/compile/section`:
  - `journal_style_enabled`
  - `journal_style_force_refresh`
  - `journal_style_sample_size`
  - `journal_style_recent_year_window`

### Native LaTeX Pipeline

Enable direct `.tex` generation and optional PDF compilation:

```yaml
latex:
  enabled: true
  default_engine: auto  # auto|none|latexmk|pdflatex|xelatex
  compile_pdf_default: true
  compile_timeout_seconds: 90
  artifact_subdir: research-writing/latex
```

Notes:
- API endpoint: `POST /api/threads/{id}/research/latex/compile`
- Supports direct markdown input or project/section-based assembly.
- With `default_engine: none` (or request `engine=none`), DeerFlow only emits `.tex` without PDF compile.

### Failure Mode Gate Thresholds

Configure red-team/regression gate thresholds for `research/evals/academic`:

```yaml
failure_mode_gate:
  citation_fidelity_max: 0.75
  overclaim_claim_grounding_max: 0.65
  numeric_drift_abstract_body_max: 0.8
  evidence_chain_claim_grounding_max: 0.55
  style_mismatch_venue_fit_max: 0.7
  superficial_rebuttal_completeness_max: 0.7
  min_target_recall: 0.95
  max_control_false_positive_rate: 0.2
```

Notes:
- These thresholds are applied when generating `failure_mode_gate_*` fields and the `.failure-modes.json` artifact.
- CI can tighten thresholds per branch/stage by providing different `config.yaml` values (for example, stricter `min_target_recall` on release branches).

### Tool Groups

Organize tools into logical groups:

```yaml
tool_groups:
  - name: web          # Web browsing and search
  - name: file:read    # Read-only file operations
  - name: file:write   # Write file operations
  - name: bash         # Shell command execution
```

### Tools

Configure specific tools available to the agent:

```yaml
tools:
  - name: web_search
    group: web
    use: src.community.tavily.tools:web_search_tool
    max_results: 5
    # api_key: $TAVILY_API_KEY  # Optional
```

**Built-in Tools**:
- `web_search` - Search the web (Tavily)
- `web_fetch` - Fetch web pages (Jina AI)
- `ls` - List directory contents
- `read_file` - Read file contents
- `write_file` - Write file contents
- `str_replace` - String replacement in files
- `bash` - Execute bash commands

### Sandbox

DeerFlow supports multiple sandbox execution modes. Configure your preferred mode in `config.yaml`:

**Local Execution** (runs sandbox code directly on the host machine):
```yaml
sandbox:
   use: src.sandbox.local:LocalSandboxProvider # Local execution
```

**Docker Execution** (runs sandbox code in isolated Docker containers):
```yaml
sandbox:
   use: src.community.aio_sandbox:AioSandboxProvider # Docker-based sandbox
```

**Docker Execution with Kubernetes** (runs sandbox code in Kubernetes pods via provisioner service):

This mode runs each sandbox in an isolated Kubernetes Pod on your **host machine's cluster**. Requires Docker Desktop K8s, OrbStack, or similar local K8s setup.

```yaml
sandbox:
   use: src.community.aio_sandbox:AioSandboxProvider
   provisioner_url: http://provisioner:8002
```

When using Docker development (`make docker-start`), DeerFlow starts the `provisioner` service only if this provisioner mode is configured. In local or plain Docker sandbox modes, `provisioner` is skipped.

See [Provisioner Setup Guide](docker/provisioner/README.md) for detailed configuration, prerequisites, and troubleshooting.

Choose between local execution or Docker-based isolation:

**Option 1: Local Sandbox** (default, simpler setup):
```yaml
sandbox:
  use: src.sandbox.local:LocalSandboxProvider
```

**Option 2: Docker Sandbox** (isolated, more secure):
```yaml
sandbox:
  use: src.community.aio_sandbox:AioSandboxProvider
  port: 8080
  auto_start: true
  container_prefix: deer-flow-sandbox

  # Optional: Additional mounts
  mounts:
    - host_path: /path/on/host
      container_path: /path/in/container
      read_only: false
```

### Skills

Configure the skills directory for specialized workflows:

```yaml
skills:
  # Host path (optional, default: ../skills)
  path: /custom/path/to/skills

  # Container mount path (default: /mnt/skills)
  container_path: /mnt/skills
```

**How Skills Work**:
- Skills are stored in `deer-flow/skills/{public,custom}/`
- Each skill has a `SKILL.md` file with metadata
- Skills are automatically discovered and loaded
- Available in both local and Docker sandbox via path mapping

### Title Generation

Automatic conversation title generation:

```yaml
title:
  enabled: true
  max_words: 6
  max_chars: 60
  model_name: null  # Use first model in list
```

## Environment Variables

DeerFlow supports environment variable substitution using the `$` prefix:

```yaml
models:
  - api_key: $OPENAI_API_KEY  # Reads from environment
```

**Common Environment Variables**:
- `OPENAI_API_KEY` - OpenAI API key
- `ANTHROPIC_API_KEY` - Anthropic API key
- `DEEPSEEK_API_KEY` - DeepSeek API key
- `NOVITA_API_KEY` - Novita API key (OpenAI-compatible endpoint)
- `TAVILY_API_KEY` - Tavily search API key
- `DEER_FLOW_CONFIG_PATH` - Custom config file path

## Configuration Location

The configuration file should be placed in the **project root directory** (`deer-flow/config.yaml`), not in the backend directory.

## Configuration Priority

DeerFlow searches for configuration in this order:

1. Path specified in code via `config_path` argument
2. Path from `DEER_FLOW_CONFIG_PATH` environment variable
3. `config.yaml` in current working directory (typically `backend/` when running)
4. `config.yaml` in parent directory (project root: `deer-flow/`)

## Best Practices

1. **Place `config.yaml` in project root** - Not in `backend/` directory
2. **Never commit `config.yaml`** - It's already in `.gitignore`
3. **Use environment variables for secrets** - Don't hardcode API keys
4. **Keep `config.example.yaml` updated** - Document all new options
5. **Test configuration changes locally** - Before deploying
6. **Use Docker sandbox for production** - Better isolation and security

## Troubleshooting

### "Config file not found"
- Ensure `config.yaml` exists in the **project root** directory (`deer-flow/config.yaml`)
- The backend searches parent directory by default, so root location is preferred
- Alternatively, set `DEER_FLOW_CONFIG_PATH` environment variable to custom location

### "Invalid API key"
- Verify environment variables are set correctly
- Check that `$` prefix is used for env var references

### "Skills not loading"
- Check that `deer-flow/skills/` directory exists
- Verify skills have valid `SKILL.md` files
- Check `skills.path` configuration if using custom path

### "Docker sandbox fails to start"
- Ensure Docker is running
- Check port 8080 (or configured port) is available
- Verify Docker image is accessible

## Examples

See `config.example.yaml` for complete examples of all configuration options.
