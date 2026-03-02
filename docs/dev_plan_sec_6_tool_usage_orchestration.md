# Development Plan: Section 6 — Tool Usage & Orchestration

## Context

The `docs/DEEP_RESEARCH_AGENT_IMPROVEMENT_REPORT.md` Section 6 identifies six improvement areas for DeerFlow's tool orchestration. Currently, DeerFlow assembles tools from 5 sources (config, MCP, built-in, subagent, community) but lacks: a think tool for structured reflection, tool retry/error recovery, rich tool documentation beyond basic docstrings, phase-aware tool filtering, and a dedicated code execution tool. This plan implements all six recommendations in dependency order.

**Current state summary:**
- Tools loaded in `backend/src/tools/tools.py` via `get_available_tools()`
- Tool definitions use `@tool(parse_docstring=True)` in `backend/src/sandbox/tools.py` and `backend/src/tools/builtins/`
- 12-middleware pipeline in `backend/src/agents/lead_agent/agent.py` `_build_middlewares()`
- `ClarificationMiddleware.wrap_tool_call()` is the only existing tool-call interceptor pattern
- No think tool, no retry middleware, no phase filtering, minimal tool docstrings

---

## Step 1: Think Tool (6.2C) — Day 1

**Goal:** Add a lightweight scratchpad tool that forces explicit reasoning between tool calls.

### Files to Create

**`backend/src/tools/builtins/think_tool.py`**
```python
@tool("think", parse_docstring=True)
def think_tool(thought: str) -> str:
    """Use this tool to think and reflect on information before acting.
    # Docstring includes: when to use, when NOT to use, examples
    """
    return thought
```

### Files to Modify

| File | Change |
|------|--------|
| `backend/src/tools/builtins/__init__.py` | Add `from .think_tool import think_tool` and to `__all__` |
| `backend/src/tools/tools.py` | Add `think_tool` to `BUILTIN_TOOLS` list (always available, no gating) |
| `backend/src/agents/lead_agent/prompt.py` | Add `<tool_usage_policies>` section with think-after-search rule between `</clarification_system>` and `{skills_section}` |

### Testing
- `backend/tests/test_think_tool.py`: Verify `think_tool.invoke({"thought": "test"})` returns `"test"`; verify tool present in `get_available_tools()` output; verify tool not in any subagent disallowed_tools list

---

## Step 2: Tool Use Examples in Definitions (6.2F) — Day 1

**Goal:** Enrich tool docstrings with concrete usage examples (72% -> 90% accuracy per Anthropic).

### Files to Modify

| File | Tool | Examples to Add |
|------|------|-----------------|
| `backend/src/sandbox/tools.py` | `bash_tool` | pip install, python script, wc/grep data |
| `backend/src/sandbox/tools.py` | `read_file_tool` | Read full file, read line range |
| `backend/src/sandbox/tools.py` | `write_file_tool` | Create new file, append to log |
| `backend/src/sandbox/tools.py` | `str_replace_tool` | Fix typo, update import, replace_all |
| `backend/src/community/tavily/tools.py` | `web_search_tool` | Specific query, research query |
| `backend/src/community/tavily/tools.py` | `web_fetch_tool` | Fetch URL from search results |
| `backend/src/tools/builtins/present_file_tool.py` | `present_files` | Present single file, multiple files |

**Pattern:** Add `Examples:` block after the main description, before `Args:`. The `parse_docstring=True` flag passes the full docstring (including examples) to the LLM as tool description.

### Testing
- Unit test: iterate `get_available_tools()`, verify each tool with 3+ params has "Examples:" in its description

---

## Step 3: Three-Layer Tool Documentation (6.2A) — Days 2-4

**Goal:** Create a tool documentation system with schema-level (Step 2), behavioral rules, and cross-cutting policies.

### Files to Create

**`backend/src/tools/docs/__init__.py`** — empty package init

**`backend/src/tools/docs/tool_policies.py`** — Python constants (not separate files, avoids I/O overhead):
- `CROSS_CUTTING_POLICIES`: Tool preference cascade (prefer `read_file` over `bash cat`, prefer `str_replace` over `write_file` for edits, etc.), anti-patterns, parallel calling guidance
- `TOOL_BEHAVIORAL_RULES: dict[str, str]`: Per-tool rules keyed by tool name (`bash`, `web_search`, `str_replace`, `write_file`, `execute_python`), each containing when/how/error-recovery guidance

### Files to Modify

| File | Change |
|------|--------|
| `backend/src/tools/tools.py` | Add `get_tool_usage_policies(tools: list[BaseTool]) -> str` — assembles cross-cutting policies + relevant per-tool rules based on available tool names |
| `backend/src/agents/lead_agent/prompt.py` | Replace static `<tool_usage_policies>` from Step 1 with `{tool_policies_section}` placeholder; add `tool_policies: str = ""` param to `apply_prompt_template()` |
| `backend/src/agents/lead_agent/agent.py` | In `make_lead_agent()`, compute `tool_policies = get_tool_usage_policies(tools)` and pass to `apply_prompt_template()` |

### Design Decision
Python constants over markdown files — importable, testable, no deployment file path dependency. Migrates cleanly to Jinja2 templates (Section 3.2A) if adopted later.

### Testing
- Unit test `get_tool_usage_policies()` with mock tool list — verify only relevant rules included
- Unit test system prompt contains "Tool Preference Cascade"

---

## Step 4: Tool Error Recovery Middleware (6.2D) — Days 2-5

**Goal:** Add retry middleware for transient tool failures using exponential backoff.

### Files to Create

**`backend/src/agents/middlewares/tool_retry_middleware.py`**

Follows exact same `wrap_tool_call` / `awrap_tool_call` pattern as `ClarificationMiddleware` (reference: `backend/src/agents/middlewares/clarification_middleware.py`):

```python
class ToolRetryMiddleware(AgentMiddleware[AgentState]):
    def __init__(self, max_retries=2, base_delay=1.0): ...

    def wrap_tool_call(self, request, handler):
        # 1. Call handler(request)
        # 2. If result starts with "Error:" and classify_error() == TRANSIENT
        # 3. Retry up to max_retries with exponential backoff
        # 4. On final failure, enrich error with retry info
        # 5. Commands pass through (never retry)
```

**Error classification** (from tool result strings — tools return `f"Error: {e}"` strings, not exceptions):
- **TRANSIENT**: timeout, connection, rate limit, 502/503/504, temporarily unavailable
- **AUTH**: 401, 403, forbidden, api key, credential
- **PERSISTENT**: not found, invalid, permission denied, is a directory, no such file
- **UNKNOWN**: everything else

**NO_RETRY_TOOLS**: `{"ask_clarification", "think", "present_files"}` — never retry these

### Files to Modify

| File | Change |
|------|--------|
| `backend/src/agents/lead_agent/agent.py` | Insert `ToolRetryMiddleware()` after `DanglingToolCallMiddleware()` and before `UsageTrackingMiddleware()` in `_build_middlewares()` (line ~207) |

**Middleware position rationale:** Before `UsageTrackingMiddleware` so retried calls accumulate usage. Before `ClarificationMiddleware` (which is always last). After `DanglingToolCallMiddleware` which fixes history, not tool execution.

### Configuration
Start hardcoded: `max_retries=2`, `base_delay=1.0s`. Can later expose in `config.yaml` under `tool_retry:` section.

### Testing
- `backend/tests/test_tool_retry_middleware.py`:
  - `classify_error()` with various error strings
  - `_should_retry()` returns False for NO_RETRY_TOOLS
  - `_should_retry()` returns False after max_retries exhausted
  - Mock handler failing twice then succeeding → verify 3 calls made
  - Command results pass through without retry
  - Enriched error message includes retry info on final failure

---

## Step 5: Context-Aware Tool Filtering (6.2E) — Days 5-7

**Goal:** Guide tool usage based on execution phase (planning/execution/synthesis/review).

### Approach: Prompt-guided soft enforcement

Manus uses logit masking (requires custom decoding — not available in LangChain). Instead, add phase awareness to the `<tool_usage_policies>` section from Step 3. The model self-regulates based on prompt guidance.

### Files to Modify

| File | Change |
|------|--------|
| `backend/src/tools/docs/tool_policies.py` | Add phase awareness section to `CROSS_CUTTING_POLICIES` documenting which tools are appropriate in planning/execution/synthesis/review phases |

### Files to Create (Foundation for Future Hard Enforcement)

**`backend/src/agents/middlewares/phase_filter_middleware.py`** — Skeleton middleware with `ExecutionPhase` enum and `PHASE_TOOL_ALLOWLIST` dict. Initially only logs detected phase in `before_model`. Can later be extended to strip disallowed tool calls in `after_model` (like `SubagentLimitMiddleware` truncates excess task calls).

### Phase Definitions

| Tool | Planning | Execution | Synthesis | Review |
|------|----------|-----------|-----------|--------|
| web_search, web_fetch | Yes | Yes | No | No |
| think, read_file, ls | Yes | Yes | Yes | Yes |
| ask_clarification | Yes | Yes | Yes | Yes |
| bash, write_file, str_replace | No | Yes | Yes | No |
| present_files, task | No | Yes | No | No |

### Testing
- Unit test `PHASE_TOOL_ALLOWLIST` contains expected tools per phase
- Manual: observe if model follows phase guidance in system prompt

---

## Step 6: Code Execution Tool (6.2B) — Days 5-12

**Goal:** Dedicated Python execution tool with structured I/O and output truncation for token efficiency.

### Files to Create

**`backend/src/sandbox/code_execution.py`**

```python
@tool("execute_python", parse_docstring=True)
def execute_python_tool(
    runtime: ToolRuntime[ContextT, ThreadState],
    description: str,
    code: str,
    save_output_to: str | None = None,
) -> str:
    # 1. Write code to temp file in sandbox workspace
    # 2. Execute via sandbox.execute_command(f"python {script_path}")
    # 3. Clean up temp file
    # 4. Optionally save full output to save_output_to
    # 5. Truncate output to MAX_OUTPUT_LENGTH (4096 chars) before returning
    # 6. Return structured result with truncation notice if applicable
```

**Key advantages over `bash(command="python ...")`:**
- Structured output with truncation (saves context tokens)
- Optional `save_output_to` for full output persistence
- Docstring with data analysis examples guides proper usage
- Error handling specific to Python execution

### Files to Modify

| File | Change |
|------|--------|
| `config.yaml` | Add tool entry: `{name: execute_python, group: bash, use: src.sandbox.code_execution:execute_python_tool}` |
| `backend/src/tools/docs/tool_policies.py` | Add `"execute_python"` behavioral rules to `TOOL_BEHAVIORAL_RULES` |
| `backend/src/subagents/builtins/general_purpose.py` | Ensure `execute_python` not in disallowed_tools (should be available to subagents) |

### Testing
- `backend/tests/test_code_execution.py`:
  - Execute simple Python code, verify output
  - Output truncation at MAX_OUTPUT_LENGTH
  - `save_output_to` writes full output to file
  - Temp script cleanup
  - Syntax error handling
  - Empty code handling

---

## Implementation Sequence

```
Day 1:  Step 1 (Think Tool) + Step 2 (Tool Examples) — independent quick wins
Day 2-4: Step 3 (Three-Layer Docs) + Step 4 (Retry Middleware) — independent, parallelizable
Day 5-7: Step 5 (Phase Filtering)
Day 5-12: Step 6 (Code Execution) — can start Day 5, largest scope
```

## All Files Summary

### New Files (9)
| File | Step |
|------|------|
| `backend/src/tools/builtins/think_tool.py` | 1 |
| `backend/src/tools/docs/__init__.py` | 3 |
| `backend/src/tools/docs/tool_policies.py` | 3 |
| `backend/src/agents/middlewares/tool_retry_middleware.py` | 4 |
| `backend/src/agents/middlewares/phase_filter_middleware.py` | 5 |
| `backend/src/sandbox/code_execution.py` | 6 |
| `backend/tests/test_think_tool.py` | 1 |
| `backend/tests/test_tool_retry_middleware.py` | 4 |
| `backend/tests/test_code_execution.py` | 6 |

### Modified Files (9)
| File | Steps |
|------|-------|
| `backend/src/tools/builtins/__init__.py` | 1 |
| `backend/src/tools/tools.py` | 1, 3 |
| `backend/src/agents/lead_agent/prompt.py` | 1, 3 |
| `backend/src/agents/lead_agent/agent.py` | 3, 4 |
| `backend/src/sandbox/tools.py` | 2 |
| `backend/src/community/tavily/tools.py` | 2 |
| `backend/src/tools/builtins/present_file_tool.py` | 2 |
| `config.yaml` | 6 |
| `backend/src/subagents/builtins/general_purpose.py` | 6 |

## Verification

After implementation, test end-to-end:
1. `cd backend && uv run pytest` — all existing + new tests pass
2. `cd backend && make lint` — ruff passes
3. `make dev` — start full application, open browser
4. Test think tool: ask agent a research question, observe `think` tool calls in agent timeline
5. Test tool examples: ask agent to modify a file, observe it uses `str_replace` correctly
6. Test retry: simulate a network error in a tool, verify retry in logs
7. Test code execution: ask agent to analyze a CSV, observe `execute_python` usage
8. Check system prompt: inspect agent timeline for `<tool_usage_policies>` section
