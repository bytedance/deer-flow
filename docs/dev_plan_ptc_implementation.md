# Development Plan: Programmatic Tool Calling (PTC) Integration

## Context

Lance Martin's article describes **Programmatic Tool Calling** — where instead of each MCP tool call round-tripping through the LLM context window, Claude writes Python code that orchestrates tool calls inside a sandbox. Intermediate results stay in code memory; only the final summary returns to the LLM. Anthropic reports **+11% accuracy, -24% input tokens** on search benchmarks.

Our system already has `execute_python` for sandbox code execution and MCP tools loaded via `langchain-mcp-adapters`, but the two are disconnected — code in the sandbox **cannot call MCP tools**. This plan bridges them using a **hybrid architecture**: a host-side HTTP proxy for most MCP servers (default), with optional in-sandbox MCP for data-sensitive workloads.

**Reference implementation**: [open-ptc-agent](https://github.com/Chen-zexi/open-ptc-agent) — its `ToolFunctionGenerator` and `mcp_client.py` patterns are the primary design inspiration.

---

## Phase 1: Core PTC Infrastructure

### Step 1.1 — MCP Tool Schema Extractor

**Goal**: Extract structured tool schemas from loaded MCP tools, preserving server-to-tool mapping.

**New files**:
- `backend/src/ptc/__init__.py` — package init, exports public API
- `backend/src/ptc/schema_extractor.py`:
  ```python
  @dataclass
  class ToolParamSchema:
      name: str
      type: str           # "string", "integer", "boolean", "object", "array"
      required: bool
      description: str
      default: Any = None

  @dataclass
  class ToolSchema:
      name: str
      server_name: str
      description: str
      params: list[ToolParamSchema]

  def extract_mcp_tool_schemas() -> dict[str, list[ToolSchema]]:
      """Extract schemas from all enabled MCP servers.
      Returns server_name -> list[ToolSchema] mapping."""
  ```

**Modify**: `backend/src/mcp/tools.py`
- Add `get_mcp_tools_by_server() -> dict[str, list[BaseTool]]` — same logic as `get_mcp_tools()` but returns per-server mapping instead of flat list. The existing for-loop at lines 42-49 already iterates per-server; just return the dict instead of extending a flat list.

**Tests**: `backend/tests/test_schema_extractor.py`
- Mock `BaseTool` objects with known `args_schema` (Pydantic models)
- Verify extraction produces correct `ToolSchema` objects
- Edge cases: tools with no params, nested objects, array params, optional params with defaults

---

### Step 1.2 — Tool Function Generator

**Goal**: Generate Python wrapper modules from MCP tool schemas. Each MCP server becomes an importable Python module with typed wrapper functions.

**New file**: `backend/src/ptc/tool_function_generator.py`

```python
class ToolFunctionGenerator:
    def __init__(self, schemas: dict[str, list[ToolSchema]]):
        self._schemas = schemas

    def generate_server_module(self, server_name: str, tools: list[ToolSchema]) -> str:
        """Generate Python source for one MCP server's tools.

        Output example (tools/postgres.py):
            from mcp_client import call_tool

            def query(sql: str, database: str = "default") -> dict:
                '''Execute a SQL query. ...'''
                return call_tool("postgres", "query", {"sql": sql, "database": database})
        """

    def generate_init_module(self) -> str:
        """Generate tools/__init__.py importing all server modules."""

    def generate_all(self) -> dict[str, str]:
        """Returns {relative_path: source_code} for all files to upload."""
```

**Key design**:
- JSON Schema types → Python type hints (`string→str`, `integer→int`, `boolean→bool`, `object→dict`, `array→list`)
- Function names normalized (dashes/dots → underscores, collision avoidance)
- Each function calls `call_tool(server_name, tool_name, args_dict)` — defined in `mcp_client.py`
- Docstrings generated from tool descriptions and param descriptions
- All generated code validated with `ast.parse()` before returning

**Depends on**: Step 1.1

**Tests**: `backend/tests/test_tool_function_generator.py`
- Feed mock schemas, verify generated code compiles (`ast.parse()`)
- Verify function signatures match schema (correct params, types, defaults)
- Test name normalization edge cases
- Test multi-server generation with init module

---

### Step 1.3 — PTC Proxy Endpoint (Host-Side)

**Goal**: HTTP endpoint on the Gateway that receives tool call requests from sandbox code and forwards them to actual MCP servers.

**New file**: `backend/src/gateway/routers/ptc_proxy.py`

```python
router = APIRouter(prefix="/api/ptc", tags=["ptc"])

class ToolCallRequest(BaseModel):
    server_name: str
    tool_name: str
    arguments: dict[str, Any]
    session_token: str

class ToolCallResponse(BaseModel):
    success: bool
    result: Any = None
    error: str | None = None

@router.post("/call", response_model=ToolCallResponse)
async def proxy_tool_call(request: ToolCallRequest) -> ToolCallResponse:
    """Forward tool call from sandbox to MCP server.
    1. Validate session token (HMAC-based, see Step 1.4)
    2. Load MCP server config from extensions_config.json
    3. Create single-use MultiServerMCPClient for that server
    4. Invoke tool with arguments
    5. Return result
    """
```

**Modify**:
- `backend/src/gateway/app.py` — add `from src.gateway.routers import ptc_proxy` and `app.include_router(ptc_proxy.router)` (after line 155)
- `docker/nginx/nginx.conf` — add `/api/ptc` location block (already covered by existing `/api/` → Gateway rule)

**Auth**: HMAC-based session tokens (see Step 1.4). The proxy validates `HMAC-SHA256(PTC_SECRET, thread_id + sandbox_id)` — both the LangGraph server (which generates it) and Gateway (which validates it) derive from the same `PTC_SECRET` environment variable. No cross-process state needed.

**Tests**: `backend/tests/test_ptc_proxy.py`
- FastAPI `TestClient` with mocked `MultiServerMCPClient`
- Valid token → tool executes → result returned
- Invalid/missing token → 401
- Unknown server/tool → 404
- Tool execution error → error response with details

---

### Step 1.4 — Session Token & MCP Client Generator

**Goal**: Generate the `mcp_client.py` module that runs INSIDE the sandbox and provides `call_tool()`.

**New files**:
- `backend/src/ptc/session.py` — HMAC token generation and validation:
  ```python
  def generate_ptc_token(thread_id: str, sandbox_id: str, secret: str) -> str:
      """Generate HMAC-SHA256 session token."""

  def validate_ptc_token(token: str, thread_id: str, sandbox_id: str, secret: str) -> bool:
      """Validate HMAC-SHA256 session token."""
  ```
  Secret read from `PTC_SECRET` env var (fallback: auto-generated at startup, written to `.think-tank/ptc_secret`).

- `backend/src/ptc/mcp_client_generator.py`:
  ```python
  def generate_mcp_client(
      proxy_url: str,
      session_token: str,
      in_sandbox_servers: dict[str, dict] | None = None,  # Phase 3: in-sandbox MCP configs
  ) -> str:
      """Generate mcp_client.py source code for the sandbox.

      The generated module provides call_tool(server, tool, args) that:
      - Default: Makes HTTP POST to proxy_url/api/ptc/call (stdlib urllib only)
      - In-sandbox servers: Launches MCP subprocess, communicates via JSON-RPC stdio
      """
  ```

**Key design**:
- Uses only `urllib.request` (stdlib) — no third-party HTTP libs needed in sandbox
- `call_tool()` dispatches by server name: proxy for most, subprocess for in-sandbox
- Timeout: 300 seconds per tool call
- Error handling: `RuntimeError` with descriptive messages

**Proxy URL resolution logic** (used during sandbox setup):
| Sandbox Type | Proxy URL |
|---|---|
| Local (no container) | `http://localhost:8001` |
| AIO Docker (local) | `http://host.docker.internal:8001` |
| AIO Docker (K8s/provisioner) | Configured via `ptc_proxy_url` in config |
| Daytona (cloud) | Configured via `ptc_proxy_url` in config |

**Depends on**: Step 1.3

**Tests**: `backend/tests/test_ptc_session.py`, `backend/tests/test_mcp_client_generator.py`
- Token generation/validation roundtrip
- Generated code compiles (`ast.parse()`)
- Proxy URL substitution for each sandbox type

---

### Step 1.5 — PTC Sandbox Setup (Module Upload)

**Goal**: After sandbox acquisition, upload generated PTC modules to the sandbox filesystem.

**New file**: `backend/src/ptc/sandbox_setup.py`

```python
PTC_TOOLS_PATH = "/mnt/user-data/workspace/.ptc/tools"

async def setup_ptc_in_sandbox(
    sandbox: Sandbox,
    sandbox_type: str,  # "local", "aio_local", "aio_remote", "daytona"
    thread_id: str,
    sandbox_id: str,
    proxy_base_url: str | None = None,
) -> PTCState:
    """Upload PTC modules to sandbox. Returns PTCState for ThreadState.

    Steps:
    1. Extract MCP tool schemas (cached after first call)
    2. Generate tool wrapper modules via ToolFunctionGenerator
    3. Generate session token via HMAC
    4. Determine proxy URL based on sandbox type
    5. Generate mcp_client.py with proxy URL and token
    6. Upload all modules to sandbox via sandbox.write_file()
    7. Return PTCState with session_token, modules_path, proxy_url
    """
```

**Why `/mnt/user-data/workspace/.ptc/tools`**: Inside workspace (mounted in all sandbox types), `.ptc` prefix keeps it hidden, consistent virtual path across all backends.

**Modify**: `backend/src/agents/thread_state.py` — add `PTCState`:
```python
class PTCState(TypedDict):
    session_token: NotRequired[str | None]
    modules_path: NotRequired[str | None]
    proxy_url: NotRequired[str | None]
    is_setup: NotRequired[bool]

class ThreadState(AgentState):
    # ... existing fields ...
    ptc: NotRequired[PTCState | None]  # NEW
```

**Lazy setup**: PTC setup is triggered on first `execute_python` call, not on sandbox init. This matches the existing `ensure_sandbox_initialized()` lazy pattern and avoids setup cost when PTC isn't used.

**Caching**: Generated modules are cached in-memory (keyed by `extensions_config.json` mtime). Re-upload only when MCP config changes or sandbox is new.

**Depends on**: Steps 1.1, 1.2, 1.4

**Tests**: `backend/tests/test_ptc_sandbox_setup.py`
- Mock `Sandbox` class (capture `write_file()` and `execute_command()` calls)
- Verify correct files written to correct paths
- Verify session token generated and included in PTCState
- Verify proxy URL inference for each sandbox type
- Verify no-op when no MCP tools are configured

---

### Step 1.6 — Update `execute_python` for PTC

**Goal**: Inject PYTHONPATH and PTC environment variables when executing Python code in the sandbox.

**Modify**: `backend/src/sandbox/code_execution.py`

Replace the execution command (lines 74-78):
```python
# Current:
output = sandbox.execute_command(f"python {script_path}")

# New:
ptc_state = runtime.state.get("ptc")
if ptc_state and ptc_state.get("is_setup"):
    modules_path = ptc_state["modules_path"]
    proxy_url = ptc_state["proxy_url"]
    session_token = ptc_state["session_token"]
    cmd = (
        f"PYTHONPATH={modules_path}:$PYTHONPATH "
        f"PTC_PROXY_URL={proxy_url} "
        f"PTC_SESSION_TOKEN={session_token} "
        f"python {script_path}"
    )
else:
    cmd = f"python {script_path}"
output = sandbox.execute_command(cmd)
```

Also add PTC lazy setup before execution:
```python
# After ensure_sandbox_initialized(runtime), before writing temp script:
ptc_state = runtime.state.get("ptc")
if not ptc_state or not ptc_state.get("is_setup"):
    ptc_config = _get_ptc_config()  # from sandbox config
    if ptc_config.get("ptc_enabled", True):
        sandbox_type = _detect_sandbox_type(runtime)
        ptc_state = await setup_ptc_in_sandbox(sandbox, sandbox_type, thread_id, sandbox_id)
        # Store in state for subsequent calls
```

**Note**: The `execute_python_tool` is currently synchronous. The PTC setup uses `get_mcp_tools_by_server()` which is async. We have two options:
1. Make `execute_python_tool` async (preferred — LangGraph supports async tools)
2. Run the async setup in a thread pool (fallback)

**Also modify**: `backend/src/sandbox/tools.py` `bash_tool` — when the command starts with `python `, prepend the same PYTHONPATH and PTC env vars if PTC is set up.

**Depends on**: Step 1.5

**Tests**: Update `backend/tests/test_code_execution.py`
- PTC state set → PYTHONPATH included in command
- PTC state absent → original command unchanged
- Lazy setup triggered when PTC state missing and `ptc_enabled=True`

---

### Step 1.7 — Configuration Updates

**Goal**: Add PTC-related configuration fields.

**Modify**: `backend/src/config/extensions_config.py`
```python
class McpServerConfig(BaseModel):
    # ... existing fields ...
    ptc_mode: str = Field(
        default="proxy",
        description="PTC mode: 'proxy' (host-side, default), 'in_sandbox', 'disabled'"
    )
```

**Modify**: `backend/src/config/sandbox_config.py`
```python
class SandboxConfig(BaseModel):
    # ... existing fields ...
    ptc_enabled: bool = Field(default=True, description="Enable PTC for MCP tools")
    ptc_proxy_url: str | None = Field(default=None, description="Override PTC proxy URL")
```

**Tests**: `backend/tests/test_ptc_config.py`
- Config parsing with/without PTC fields
- Default values
- Backward compatibility (existing configs without PTC fields)

---

### Step 1.8 — System Prompt PTC Instructions

**Goal**: Tell the LLM how to use PTC — when to write orchestration code and how to import tool wrappers.

**New file**: `backend/src/agents/lead_agent/prompts/context/ptc_instructions.md`

```markdown
## Programmatic Tool Calling (PTC)

You can write Python code that calls MCP tools directly from within `execute_python`.
This is more efficient than individual tool calls when chaining 3+ MCP operations.

**When to use PTC**: Multi-step data pipelines, search-then-analyze workflows,
iterating over results and calling tools for each item.

**When NOT to use PTC**: Single tool calls (use the tool directly).

**Available MCP Tool Modules:**
$ptc_tool_summaries

**Usage:**
```python
from tools.postgres import query
results = query(sql="SELECT * FROM employees LIMIT 10")
print(results)  # Only this returns to your context
```

All tool calls go through the host proxy automatically.
Wrap calls in try/except for robust error handling.
```

**Modify**: `backend/src/agents/lead_agent/prompt.py`
- Add `_build_ptc_section()` — generates PTC tool summaries from loaded MCP tools
- Pass `ptc_section` to prompt template
- Only included when MCP tools are available AND `ptc_enabled=True`

**Modify**: `backend/src/agents/lead_agent/prompts/composer.py`
- Add `ptc_section` as a pass-through parameter in `compose()` (like `subagent_section`, `skills_section`)

**Tests**: Update `backend/tests/test_prompt_engineering.py`
- PTC section present when MCP tools available
- PTC section absent when no MCP tools or `ptc_enabled=False`
- Tool summaries list correct server names and tool counts

---

## Phase 2: Progressive Tool Discovery

### Step 2.1 — Per-Tool Documentation Generator

**Goal**: Generate markdown docs for each MCP tool so the LLM can read them on-demand instead of having full schemas in the prompt.

**New file**: `backend/src/ptc/doc_generator.py`

```python
class ToolDocGenerator:
    def generate_tool_doc(self, tool: ToolSchema) -> str:
        """Generate markdown doc for one tool.
        Includes: signature, parameter table, return type, usage example."""

    def generate_all_docs(self, schemas: dict[str, list[ToolSchema]]) -> dict[str, str]:
        """Returns {relative_path: markdown} for all tool docs."""
```

Output structure in sandbox:
```
/mnt/user-data/workspace/.ptc/tools/
├── mcp_client.py
├── __init__.py
├── postgres.py
├── tavily.py
└── docs/
    ├── postgres/
    │   ├── query.md
    │   └── list_schemas.md
    └── tavily/
        └── search.md
```

**Depends on**: Step 1.1

**Tests**: `backend/tests/test_ptc_doc_generator.py`

---

### Step 2.2 — Upload Docs & Update Discovery Prompt

**Modify**: `backend/src/ptc/sandbox_setup.py` — include doc generation in setup flow. Upload markdown docs alongside Python modules.

**Modify**: `backend/src/agents/lead_agent/prompts/context/ptc_instructions.md` — add discovery workflow:
```markdown
To discover tool details: read_file("/mnt/user-data/workspace/.ptc/tools/docs/postgres/query.md")
```

---

### Step 2.3 — Reduce MCP Tools in Prompt (Optional)

**Goal**: When PTC is fully operational, optionally replace full MCP tool bindings with summaries only — the LLM uses PTC code for all MCP operations.

**Modify**: `backend/src/tools/tools.py` — add config flag `ptc_replace_mcp_tools`:
- `False` (default): MCP tools bound to model AND PTC available (gradual transition)
- `True`: MCP tools NOT bound to model; only PTC summaries in prompt (full PTC mode)

This is a config-driven transition, not a code change. Default stays `False` until PTC is proven reliable.

---

## Phase 3: Optimization & In-Sandbox MCP

### Step 3.1 — In-Sandbox MCP Support (Hybrid)

**Goal**: For MCP servers marked `ptc_mode: "in_sandbox"`, generate subprocess-based clients.

**Modify**: `backend/src/ptc/mcp_client_generator.py` — add subprocess-based MCP client path:
- Launches MCP server as subprocess inside sandbox (`subprocess.Popen` with stdin/stdout pipes)
- JSON-RPC initialize → tools/call protocol over stdio
- Server lifecycle management (start on first call, reuse across calls, cleanup on exit)
- Requires MCP server binary installed in sandbox image

**Modify**: `backend/src/ptc/sandbox_setup.py` — for in-sandbox servers:
- Upload MCP server scripts to sandbox (e.g., custom Python MCP servers)
- Install required npm packages in sandbox if needed (for Node.js MCP servers)
- Pass API keys as environment variables to sandbox

**Container image changes**: For in-sandbox MCP to work, the sandbox image must include:
- Node.js + npm (for npm-based MCP servers like `tavily-mcp`)
- `uvx` / `uv` (for Python-based MCP servers)
- Document image extension requirements

### Step 3.2 — Token Savings Measurement

**New file**: `backend/src/ptc/metrics.py`

Track per-session:
- Number of tool calls made via PTC vs direct
- Estimated tokens saved (avoided round-trips × avg tool result size)
- PTC execution latency

Integrate with `UsageTrackingMiddleware` for SSE event emission.

### Step 3.3 — Result Artifact Management

**Modify**: `backend/src/sandbox/code_execution.py`

After PTC execution:
- Scan outputs directory for new files
- Register in `ThreadState.artifacts`
- Support image/chart upload to cloud storage (optional, like open-ptc-agent's R2/S3 support)

---

## Dependency Graph & Build Order

```
Step 1.7 (Config)  ──────────────────────────────────────────┐
                                                              │
Step 1.1 (Schema Extractor) ─┬─ Step 1.2 (Code Gen) ────┐   │
                              │                           │   │
                              └─ Step 1.8 (Prompt) ──┐   │   │
                                                      │   │   │
Step 1.3 (Proxy) ─── Step 1.4 (Client Gen + Auth) ──┐│   │   │
                                                      │   │   │
                   Step 1.5 (Sandbox Setup) ◄─────────┴───┘   │
                              │                                │
                   Step 1.6 (execute_python update) ◄──────────┘
                              │
              ┌───────────────┴───────────────┐
              │                               │
     Step 2.1 (Doc Gen)              Step 3.2 (Metrics)
              │
     Step 2.2 (Upload Docs)
              │
     Step 2.3 (Optional: replace MCP binding)
```

**Recommended implementation order**:
1. Step 1.7 (config) — enables everything else
2. Step 1.1 (schema extractor) — foundational data model
3. Step 1.2 (code generator) + Step 1.3 (proxy endpoint) — **parallel**
4. Step 1.4 (client generator + auth) — needs Step 1.3
5. Step 1.5 (sandbox setup) — needs Steps 1.1, 1.2, 1.4
6. Step 1.6 (execute_python update) — needs Step 1.5
7. Step 1.8 (prompt updates) — needs Step 1.1, can run **parallel** with Steps 1.3-1.6
8. Phase 2 steps (progressive discovery)
9. Phase 3 steps (optimization)

---

## File Manifest

### New Files (16)

| File | Step | Purpose |
|------|------|---------|
| `backend/src/ptc/__init__.py` | 1.1 | Package init, public API exports |
| `backend/src/ptc/schema_extractor.py` | 1.1 | MCP tool schema extraction |
| `backend/src/ptc/tool_function_generator.py` | 1.2 | Python wrapper code generation |
| `backend/src/gateway/routers/ptc_proxy.py` | 1.3 | Host-side HTTP proxy endpoint |
| `backend/src/ptc/session.py` | 1.4 | HMAC session token gen/validation |
| `backend/src/ptc/mcp_client_generator.py` | 1.4 | Sandbox-side mcp_client.py generator |
| `backend/src/ptc/sandbox_setup.py` | 1.5 | PTC module upload orchestrator |
| `backend/src/ptc/doc_generator.py` | 2.1 | Per-tool markdown doc generator |
| `backend/src/ptc/metrics.py` | 3.2 | Token savings tracking |
| `backend/src/agents/lead_agent/prompts/context/ptc_instructions.md` | 1.8 | System prompt PTC fragment |
| `backend/tests/test_schema_extractor.py` | 1.1 | Unit tests |
| `backend/tests/test_tool_function_generator.py` | 1.2 | Unit tests |
| `backend/tests/test_ptc_proxy.py` | 1.3 | Proxy endpoint tests |
| `backend/tests/test_ptc_session.py` | 1.4 | Session token tests |
| `backend/tests/test_ptc_sandbox_setup.py` | 1.5 | Sandbox setup tests |
| `backend/tests/test_ptc_e2e.py` | E2E | End-to-end integration test |

### Modified Files (10)

| File | Steps | Change |
|------|-------|--------|
| `backend/src/mcp/tools.py` | 1.1 | Add `get_mcp_tools_by_server()` |
| `backend/src/agents/thread_state.py` | 1.5 | Add `PTCState` TypedDict |
| `backend/src/sandbox/code_execution.py` | 1.6 | PTC lazy setup + PYTHONPATH injection |
| `backend/src/sandbox/tools.py` | 1.6 | PYTHONPATH in bash_tool for `python` commands |
| `backend/src/gateway/app.py` | 1.3 | Register `ptc_proxy` router |
| `backend/src/config/extensions_config.py` | 1.7 | Add `ptc_mode` to `McpServerConfig` |
| `backend/src/config/sandbox_config.py` | 1.7 | Add `ptc_enabled`, `ptc_proxy_url` |
| `backend/src/agents/lead_agent/prompt.py` | 1.8 | Add `_build_ptc_section()` |
| `backend/src/agents/lead_agent/prompts/composer.py` | 1.8 | Add `ptc_section` parameter |
| `backend/tests/test_code_execution.py` | 1.6 | Add PTC-aware execution tests |

---

## Testing Strategy

### Unit Tests (no external dependencies)

| Test File | What It Tests | Key Assertions |
|-----------|--------------|----------------|
| `test_schema_extractor.py` | Schema extraction from mock BaseTools | Correct ToolSchema output, handles edge cases |
| `test_tool_function_generator.py` | Python code generation | `ast.parse()` succeeds, signatures match schemas |
| `test_ptc_proxy.py` | Proxy endpoint via TestClient | Auth validation, tool dispatch, error handling |
| `test_ptc_session.py` | HMAC token gen/validation | Roundtrip correctness, wrong secret rejects |
| `test_mcp_client_generator.py` | mcp_client.py generation | `ast.parse()` succeeds, proxy URL substituted |
| `test_ptc_sandbox_setup.py` | Module upload with mock sandbox | Correct files at correct paths, PTCState correct |
| `test_ptc_config.py` | Config parsing with new fields | Defaults, backward compat |
| `test_ptc_doc_generator.py` | Markdown doc generation | Contains params, types, examples |

### Integration Tests (`@pytest.mark.integration`, require Docker)

| Test | Prerequisites | What It Tests |
|------|--------------|---------------|
| `test_ptc_sandbox_integration` | Docker running | Start AIO sandbox → upload PTC modules → execute `from tools import ...` → verify importable |
| `test_ptc_proxy_integration` | Docker + MCP server (postgres-mcp) | Gateway + proxy → sandbox calls proxy → MCP tool executes → result returns |

### E2E Test (`@pytest.mark.e2e`)

**File**: `backend/tests/test_ptc_e2e.py`

**Full pipeline test**:
1. Configure postgres MCP server in `extensions_config.json`
2. Start Gateway with PTC proxy
3. Start AIO sandbox container
4. Call `setup_ptc_in_sandbox()` → modules uploaded
5. Execute Python code in sandbox: `from tools.postgres import query; result = query(sql="SELECT 1"); print(result)`
6. Verify: sandbox code → HTTP to proxy → MCP tool call → result back to code → stdout captured
7. Verify session token authentication works (valid token succeeds, invalid rejected)

**Daytona variant** (manual/CI-optional):
- Same test but with Daytona sandbox
- Requires `DAYTONA_API_KEY` and network-accessible `ptc_proxy_url`

### Mock Strategy

- `MockSandbox(Sandbox)` — in-memory filesystem, captures `execute_command` and `write_file` calls
- `MockMCPClient` — returns predetermined tool results without real MCP connections
- FastAPI `TestClient` — tests proxy without running a real server
- `unittest.mock.patch` for config singletons and provider instances

---

## Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| **Host-side proxy as default** | API keys stay on host, no container image changes, works for MCP servers needing host-network resources (databases). Simpler than in-sandbox MCP. |
| **HMAC tokens (not JWT/random)** | LangGraph server and Gateway are separate processes. HMAC tokens derived from shared secret — no cross-process storage needed. Both processes can independently generate and validate. |
| **stdlib-only mcp_client.py** | Sandbox images may lack `requests`/`httpx`. `urllib.request` is always available. Zero dependency requirement for generated code. |
| **Lazy PTC setup** | Many sessions never use PTC. Avoid schema extraction and module upload overhead on every sandbox init. Matches existing `ensure_sandbox_initialized()` pattern. |
| **Modules at `/mnt/user-data/workspace/.ptc/tools`** | Inside workspace (mounted in all sandbox types). `.ptc` prefix hides from listings. Virtual path system handles translation for local sandbox. |
| **Per-server `ptc_mode` config** | Hybrid approach — proxy by default, in-sandbox opt-in per server. Incremental adoption without all-or-nothing. |

---

## Verification Plan

After implementation, verify end-to-end:

1. **Unit tests**: `cd backend && uv run pytest tests/test_ptc_*.py tests/test_schema_extractor.py -v`
2. **Lint**: `cd backend && make lint`
3. **Integration test** (requires Docker + postgres-mcp):
   ```bash
   cd backend && uv run pytest tests/test_ptc_e2e.py -v -m integration
   ```
4. **Manual verification**:
   - `make dev` → open browser
   - Enable postgres MCP server in extensions_config.json
   - Ask agent: "Write Python code to query the employees table and summarize the results using execute_python"
   - Verify: agent generates PTC code with `from tools.postgres import query`
   - Verify: code executes successfully, results appear in response
   - Check agent timeline for PTC execution trace
5. **Prompt inspection**: Check system prompt in agent timeline contains `<ptc_system>` section with correct tool summaries
6. **Both sandbox types**: Test with both `AioSandboxProvider` (Docker) and `DaytonaSandboxProvider` (if available)
