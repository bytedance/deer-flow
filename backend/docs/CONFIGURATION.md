# Configuration Guide

This guide explains how to configure DeerFlow for your environment.

## Config Versioning

`config.example.yaml` contains a `config_version` field that tracks schema changes. When the example version is higher than your local `config.yaml`, the application emits a startup warning:

```
WARNING - Your config.yaml (version 0) is outdated — the latest version is 1.
Run `make config-upgrade` to merge new fields into your config.
```

- **Missing `config_version`** in your config is treated as version 0.
- Run `make config-upgrade` to auto-merge missing fields (your existing values are preserved, a `.bak` backup is created).
- When changing the config schema, bump `config_version` in `config.example.yaml`.

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
```

**Supported Providers**:
- OpenAI (`langchain_openai:ChatOpenAI`)
- Anthropic (`langchain_anthropic:ChatAnthropic`)
- DeepSeek (`langchain_deepseek:ChatDeepSeek`)
- Claude Code OAuth (`deerflow.models.claude_provider:ClaudeChatModel`)
- Codex CLI (`deerflow.models.openai_codex_provider:CodexChatModel`)
- Any LangChain-compatible provider

CLI-backed provider examples:

```yaml
models:
  - name: gpt-5.4
    display_name: GPT-5.4 (Codex CLI)
    use: deerflow.models.openai_codex_provider:CodexChatModel
    model: gpt-5.4
    supports_thinking: true
    supports_reasoning_effort: true

  - name: claude-sonnet-4.6
    display_name: Claude Sonnet 4.6 (Claude Code OAuth)
    use: deerflow.models.claude_provider:ClaudeChatModel
    model: claude-sonnet-4-6
    max_tokens: 4096
    supports_thinking: true
```

**Auth behavior for CLI-backed providers**:
- `CodexChatModel` loads Codex CLI auth from `~/.codex/auth.json`
- The Codex Responses endpoint currently rejects `max_tokens` and `max_output_tokens`, so `CodexChatModel` does not expose a request-level token cap
- `ClaudeChatModel` accepts `CLAUDE_CODE_OAUTH_TOKEN`, `ANTHROPIC_AUTH_TOKEN`, `CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR`, `CLAUDE_CODE_CREDENTIALS_PATH`, or plaintext `~/.claude/.credentials.json`
- On macOS, DeerFlow does not probe Keychain automatically. Use `scripts/export_claude_code_oauth.py` to export Claude Code auth explicitly when needed

To use OpenAI's `/v1/responses` endpoint with LangChain, keep using `langchain_openai:ChatOpenAI` and set:

```yaml
models:
  - name: gpt-5-responses
    display_name: GPT-5 (Responses API)
    use: langchain_openai:ChatOpenAI
    model: gpt-5
    api_key: $OPENAI_API_KEY
    use_responses_api: true
    output_version: responses/v1
```

For OpenAI-compatible gateways (for example Novita or OpenRouter), keep using `langchain_openai:ChatOpenAI` and set `base_url`:

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

  - name: minimax-m2.5
    display_name: MiniMax M2.5
    use: langchain_openai:ChatOpenAI
    model: MiniMax-M2.5
    api_key: $MINIMAX_API_KEY
    base_url: https://api.minimax.io/v1
    max_tokens: 4096
    temperature: 1.0  # MiniMax requires temperature in (0.0, 1.0]
    supports_vision: true

  - name: minimax-m2.5-highspeed
    display_name: MiniMax M2.5 Highspeed
    use: langchain_openai:ChatOpenAI
    model: MiniMax-M2.5-highspeed
    api_key: $MINIMAX_API_KEY
    base_url: https://api.minimax.io/v1
    max_tokens: 4096
    temperature: 1.0  # MiniMax requires temperature in (0.0, 1.0]
    supports_vision: true
  - name: openrouter-gemini-2.5-flash
    display_name: Gemini 2.5 Flash (OpenRouter)
    use: langchain_openai:ChatOpenAI
    model: google/gemini-2.5-flash-preview
    api_key: $OPENAI_API_KEY
    base_url: https://openrouter.ai/api/v1
```

If your OpenRouter key lives in a different environment variable name, point `api_key` at that variable explicitly (for example `api_key: $OPENROUTER_API_KEY`).

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

**Gemini with thinking via OpenAI-compatible gateway**:

When routing Gemini through an OpenAI-compatible proxy (Vertex AI OpenAI compat endpoint, AI Studio, or third-party gateways) with thinking enabled, the API attaches a `thought_signature` to each tool-call object returned in the response.  Every subsequent request that replays those assistant messages **must** echo those signatures back on the tool-call entries or the API returns:

```
HTTP 400 INVALID_ARGUMENT: function call `<tool>` in the N. content block is
missing a `thought_signature`.
```

Standard `langchain_openai:ChatOpenAI` silently drops `thought_signature` when serialising messages.  Use `deerflow.models.patched_openai:PatchedChatOpenAI` instead — it re-injects the tool-call signatures (sourced from `AIMessage.additional_kwargs["tool_calls"]`) into every outgoing payload:

```yaml
models:
  - name: gemini-2.5-pro-thinking
    display_name: Gemini 2.5 Pro (Thinking)
    use: deerflow.models.patched_openai:PatchedChatOpenAI
    model: google/gemini-2.5-pro-preview   # model name as expected by your gateway
    api_key: $GEMINI_API_KEY
    base_url: https://<your-openai-compat-gateway>/v1
    max_tokens: 16384
    supports_thinking: true
    supports_vision: true
    when_thinking_enabled:
      extra_body:
        thinking:
          type: enabled
```

For Gemini accessed **without** thinking (e.g. via OpenRouter where thinking is not activated), the plain `langchain_openai:ChatOpenAI` with `supports_thinking: false` is sufficient and no patch is needed.

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
    use: deerflow.community.tavily.tools:web_search_tool
    max_results: 5
    # api_key: $TAVILY_API_KEY  # Optional
```

**Built-in Tools**:
- `web_search` - Search the web (DuckDuckGo, Tavily, Exa, InfoQuest, Firecrawl)
- `web_fetch` - Fetch web pages (Jina AI, Exa, InfoQuest, Firecrawl)
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
   use: deerflow.sandbox.local:LocalSandboxProvider # Local execution
   allow_host_bash: false # default; host bash is disabled unless explicitly re-enabled
```

**Docker Execution** (runs sandbox code in isolated Docker containers):
```yaml
sandbox:
   use: deerflow.community.aio_sandbox:AioSandboxProvider # Docker-based sandbox
```

**Docker Execution with Kubernetes** (runs sandbox code in Kubernetes pods via provisioner service):

This mode runs each sandbox in an isolated Kubernetes Pod on your **host machine's cluster**. Requires Docker Desktop K8s, OrbStack, or similar local K8s setup.

```yaml
sandbox:
   use: deerflow.community.aio_sandbox:AioSandboxProvider
   provisioner_url: http://provisioner:8002
```

When using Docker development (`make docker-start`), DeerFlow starts the `provisioner` service only if this provisioner mode is configured. In local or plain Docker sandbox modes, `provisioner` is skipped.

See [Provisioner Setup Guide](../../docker/provisioner/README.md) for detailed configuration, prerequisites, and troubleshooting.

Choose between local execution or Docker-based isolation:

**Option 1: Local Sandbox** (default, simpler setup):
```yaml
sandbox:
  use: deerflow.sandbox.local:LocalSandboxProvider
  allow_host_bash: false
```

`allow_host_bash` is intentionally `false` by default. DeerFlow's local sandbox is a host-side convenience mode, not a secure shell isolation boundary. If you need `bash`, prefer `AioSandboxProvider`. Only set `allow_host_bash: true` for fully trusted single-user local workflows.

**Option 2: Docker Sandbox** (isolated, more secure):
```yaml
sandbox:
  use: deerflow.community.aio_sandbox:AioSandboxProvider
  port: 8080
  auto_start: true
  container_prefix: deer-flow-sandbox

  # Optional: Additional mounts
  mounts:
    - host_path: /path/on/host
      container_path: /path/in/container
      read_only: false
```

When you configure `sandbox.mounts`, DeerFlow exposes those `container_path` values in the agent prompt so the agent can discover and operate on mounted directories directly instead of assuming everything must live under `/mnt/user-data`.

For bare-metal Docker sandbox runs that use localhost, DeerFlow binds the sandbox HTTP port to `127.0.0.1` by default so it is not exposed on every host interface. Docker-outside-of-Docker deployments that connect through `host.docker.internal` keep the broad legacy bind for compatibility. Set `DEER_FLOW_SANDBOX_BIND_HOST` explicitly if your deployment needs a different bind address.

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

**Per-Agent Skill Filtering**:
Custom agents can restrict which skills they load by defining a `skills` field in their `config.yaml` (located at `workspace/agents/<agent_name>/config.yaml`):
- **Omitted or `null`**: Loads all globally enabled skills (default fallback).
- **`[]` (empty list)**: Disables all skills for this specific agent.
- **`["skill-name"]`**: Loads only the explicitly specified skills.

### Title Generation

Automatic conversation title generation:

```yaml
title:
  enabled: true
  max_words: 6
  max_chars: 60
  model_name: null  # Use first model in list
```

### GitHub API Token (Optional for GitHub Deep Research Skill)

The default GitHub API rate limits are quite restrictive. For frequent project research, we recommend configuring a personal access token (PAT) with read-only permissions.

**Configuration Steps**:
1. Uncomment the `GITHUB_TOKEN` line in the `.env` file and add your personal access token
2. Restart the DeerFlow service to apply changes

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
- `DEER_FLOW_PROJECT_ROOT` - Project root for relative runtime paths
- `DEER_FLOW_CONFIG_PATH` - Custom config file path
- `DEER_FLOW_EXTENSIONS_CONFIG_PATH` - Custom extensions config file path
- `DEER_FLOW_HOME` - Runtime state directory (defaults to `.deer-flow` under the project root)
- `DEER_FLOW_SKILLS_PATH` - Skills directory when `skills.path` is omitted
- `GATEWAY_ENABLE_DOCS` - Set to `false` to disable Swagger UI (`/docs`), ReDoc (`/redoc`), and OpenAPI schema (`/openapi.json`) endpoints (default: `true`)

## Configuration Location

The configuration file should be placed in the **project root directory** (`deer-flow/config.yaml`). Set `DEER_FLOW_PROJECT_ROOT` when the process may start from another working directory, or set `DEER_FLOW_CONFIG_PATH` to point at a specific file.

## Configuration Priority

DeerFlow searches for configuration in this order:

1. Path specified in code via `config_path` argument
2. Path from `DEER_FLOW_CONFIG_PATH` environment variable
3. `config.yaml` under `DEER_FLOW_PROJECT_ROOT`, or under the current working directory when `DEER_FLOW_PROJECT_ROOT` is unset
4. Legacy backend/repository-root locations for monorepo compatibility

## Best Practices

1. **Place `config.yaml` in project root** - Set `DEER_FLOW_PROJECT_ROOT` if the runtime starts elsewhere
2. **Never commit `config.yaml`** - It's already in `.gitignore`
3. **Use environment variables for secrets** - Don't hardcode API keys
4. **Keep `config.example.yaml` updated** - Document all new options
5. **Test configuration changes locally** - Before deploying
6. **Use Docker sandbox for production** - Better isolation and security

## Troubleshooting

### "Config file not found"
- Ensure `config.yaml` exists in the **project root** directory (`deer-flow/config.yaml`)
- If the runtime starts outside the project root, set `DEER_FLOW_PROJECT_ROOT`
- Alternatively, set `DEER_FLOW_CONFIG_PATH` environment variable to custom location

### "Invalid API key"
- Verify environment variables are set correctly
- Check that `$` prefix is used for env var references

### "Skills not loading"
- Check that `deer-flow/skills/` directory exists
- Verify skills have valid `SKILL.md` files
- Check `skills.path` or `DEER_FLOW_SKILLS_PATH` if using a custom path

### "Docker sandbox fails to start"
- Ensure Docker is running
- Check port 8080 (or configured port) is available
- Verify Docker image is accessible

## Examples

See `config.example.yaml` for complete examples of all configuration options.
