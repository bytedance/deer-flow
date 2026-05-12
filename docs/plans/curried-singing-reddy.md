# Plan: P0 (RAG Tool KB Selection) + P1 (ALLOW_NO_AUTH_KB Guard)

## Context

The knowledge base feature allows users to select specific KBs per session. The middleware (`rag_middleware.py`) already injects KB context automatically before each agent turn, but the `search_knowledge_base` tool (invoked explicitly by the agent) ignores the user's KB selection and only searches a single named collection. Additionally, there is no guard preventing KB access in no-auth mode, which could lead to production misuse.

## P0: Make `search_knowledge_base` tool respect KB selection

### Goal
When the agent explicitly calls `search_knowledge_base` without specifying a collection, it should automatically search across the user's selected knowledge bases (from `runtime.context["knowledge_base_selection"]`), falling back to the existing single-collection behavior when no selection exists.

### Approach
Use the `InjectedToolArg` pattern (same as `invoke_acp_agent_tool.py:165`) to inject `RunnableConfig` into the tool function. Extract `knowledge_base_selection` from `config["configurable"]["__pregel_runtime"].context`.

### Changes to `backend/packages/harness/deerflow/rag/tools.py`

1. Add imports: `Annotated`, `RunnableConfig`, `InjectedToolArg`, `multi_kb_retrieve`, `KnowledgeBaseRepository`, `get_session_factory`, `get_current_tenant_id`, `get_effective_user_id`, `asyncio`, `ThreadPoolExecutor`
2. Change function signature to:
   ```python
   def search_knowledge_base(
       query: str,
       collection: str = "default",
       config: Annotated[RunnableConfig, InjectedToolArg] = None,
   ) -> str:
   ```
3. Add logic after the `config.enabled` check:
   - Extract runtime context from `config["configurable"]["__pregel_runtime"].context`
   - Check for `knowledge_base_selection` (same logic as `RagMiddleware._get_kb_selection`)
   - If selection exists AND `collection == "default"` (user didn't explicitly specify a collection):
     - Resolve active KBs via `KnowledgeBaseRepository.resolve_active_by_ids()`
     - Call `multi_kb_retrieve()` with resolved KBs
     - Format results with KB metadata (kb_name, doc_title, score)
   - Otherwise: fall through to existing single-collection retrieval

### Key reuse
- `RagMiddleware._get_kb_selection` logic (inline extraction, same pattern)
- `multi_kb_retrieve()` from `deerflow.knowledge_base.retrieval`
- `KnowledgeBaseRepository.resolve_active_by_ids()` from `deerflow.persistence.knowledge_base.repository`
- Async-in-sync pattern from `rag_middleware.py:164-171` (ThreadPoolExecutor + new event loop)

---

## P1: Add `allow_no_auth_kb` configuration guard

### Goal
Prevent knowledge base access (both middleware injection and tool search) when running in no-auth mode unless explicitly opted in via config. This prevents accidental data leakage in development/demo environments.

### Changes

1. **`backend/packages/harness/deerflow/config/rag_config.py`** — Add field:
   ```python
   allow_no_auth_kb: bool = Field(
       default=False,
       description="Allow knowledge base access when user is unauthenticated (user_id='default'). "
                   "Set to True only for development/demo environments.",
   )
   ```

2. **`backend/packages/harness/deerflow/rag/tools.py`** — Add guard at the top of the multi-KB path:
   ```python
   if user_id == "default" and not rag_config.allow_no_auth_kb:
       return json.dumps({"error": "Knowledge base access requires authentication", "results": []})
   ```

3. **`backend/packages/harness/deerflow/agents/middlewares/rag_middleware.py`** — Add guard in `_retrieve_from_selected_kbs` (after resolving `owner_user_id`, before DB call):
   ```python
   if owner_user_id == "default" and not config.allow_no_auth_kb:
       logger.debug("RagMiddleware: KB access blocked in no-auth mode (allow_no_auth_kb=False)")
       return None
   ```

---

## Files to modify

| File | Change |
|------|--------|
| `backend/packages/harness/deerflow/rag/tools.py` | P0: Add InjectedToolArg, multi-KB retrieval logic; P1: no-auth guard |
| `backend/packages/harness/deerflow/config/rag_config.py` | P1: Add `allow_no_auth_kb` field |
| `backend/packages/harness/deerflow/agents/middlewares/rag_middleware.py` | P1: Add no-auth guard in `_retrieve_from_selected_kbs` |
| `backend/tests/test_knowledge_base_retrieval.py` | Tests for both P0 and P1 |

## Verification

1. Run existing tests: `cd backend && PYTHONPATH=. uv run pytest tests/test_knowledge_base_retrieval.py -v`
2. Add new tests:
   - `test_search_tool_uses_kb_selection_from_config` — mock RunnableConfig with KB selection, verify `multi_kb_retrieve` is called
   - `test_search_tool_falls_back_to_collection` — no KB selection in config, verify single-collection retrieval
   - `test_search_tool_blocked_in_no_auth_mode` — user_id="default", allow_no_auth_kb=False → error response
   - `test_search_tool_allowed_in_no_auth_when_configured` — user_id="default", allow_no_auth_kb=True → proceeds
   - `test_middleware_blocked_in_no_auth_mode` — verify middleware returns None when guard triggers
3. Run full test suite: `cd backend && make test`
