# Upstream Custom Agents Feature — Merge Plan

**Upstream Commits**:
- `7de94394d4295182701ffb47e938e7c39b963091` — bytedance/deer-flow#957 (main feature)
- `14d1e01149177ac4f15dc0c9c936f7ee8790ace3` — bytedance/deer-flow#962 (follow-up: refactor hooks, fix error handling in agent config loading, improve chat page)

**Author**: JeffJiang (for-eleven@hotmail.com)
**Dates**: 2026-03-03 / 2026-03-04

## Feature Overview

This commit adds a complete **custom agent management system** — users can create, configure, and chat with named agents that have their own personality (SOUL.md), model overrides, tool group restrictions, and per-agent memory.

### What It Adds

#### Backend

| Component | Path | Description |
|-----------|------|-------------|
| **Agent Config** | `backend/src/config/agents_config.py` | `AgentConfig` Pydantic model, `load_agent_config()`, `load_agent_soul()`, `list_custom_agents()` |
| **Agent CRUD API** | `backend/src/gateway/routers/agents.py` | Full REST API: `GET/POST /api/agents`, `GET/PUT/DELETE /api/agents/{name}`, `GET /api/agents/check`, user profile endpoints |
| **Setup Agent Tool** | `backend/src/tools/builtins/setup_agent_tool.py` | LangGraph tool that creates agent config + SOUL.md on disk during bootstrap flow |
| **Bootstrap Skill** | `skills/public/bootstrap/SKILL.md` | Conversational onboarding skill that guides users through agent creation via multi-phase dialogue |
| **SOUL Template** | `skills/public/bootstrap/templates/SOUL.template.md` | Template for agent personality files |
| **Conversation Guide** | `skills/public/bootstrap/references/conversation-guide.md` | Detailed phases for the bootstrap conversation |

#### Backend Modifications

| File | Changes |
|------|---------|
| `lead_agent/agent.py` | Agent-aware model resolution (`agent_config.model`), `is_bootstrap` mode for agent creation, `agent_name` in metadata and middleware |
| `lead_agent/prompt.py` | `{agent_name}` and `{soul}` template variables, per-agent memory via `_get_memory_context(agent_name)`, skill filtering via `available_skills` param |
| `memory/updater.py` | Per-agent memory storage paths (`get_memory_data(agent_name)`) |
| `memory/queue.py` | Agent-aware memory queue |
| `middlewares/memory_middleware.py` | `MemoryMiddleware(agent_name=...)` constructor |
| `config/paths.py` | `get_paths().agent_dir(name)`, `user_md_file` |
| `gateway/app.py` | Register agents router |
| `tools/builtins/__init__.py` | Export `setup_agent` tool |

#### Frontend

| Component | Path | Description |
|-----------|------|-------------|
| **Agent Types** | `core/agents/types.ts` | `Agent` interface (`name`, `description`, `model`, `tool_groups`, `soul`) |
| **Agent API** | `core/agents/api.ts` | `listAgents()`, `getAgent()`, `createAgent()`, `updateAgent()`, `deleteAgent()`, `checkAgentName()` |
| **Agent Hooks** | `core/agents/hooks.ts` | `useAgents()`, `useAgent()`, `useDeleteAgent()` (TanStack Query) |
| **Agent Gallery** | `components/workspace/agents/agent-gallery.tsx` | Grid of agent cards with create button |
| **Agent Card** | `components/workspace/agents/agent-card.tsx` | Card component with delete action |
| **Agent Welcome** | `components/workspace/agent-welcome.tsx` | Welcome message showing agent description on new threads |
| **New Agent Page** | `app/workspace/agents/new/page.tsx` | Two-step creation flow: name input then bootstrap chat |
| **Agent Chat Page** | `app/workspace/agents/[agent_name]/chats/[thread_id]/page.tsx` | Agent-scoped chat page |
| **Agents Index** | `app/workspace/agents/page.tsx` | Gallery page |
| **ChatBox** | `components/workspace/chats/chat-box.tsx` | Extracted reusable chat component |
| **Chat Mode** | `components/workspace/chats/use-chat-mode.ts` | Chat mode hook (flash/pro) |
| **Artifact Trigger** | `components/workspace/artifacts/artifact-trigger.tsx` | Artifact panel visibility toggle |

#### Frontend Modifications

| File | Changes |
|------|---------|
| `core/threads/hooks.ts` | `useThreadStream` accepts `context` (for `is_bootstrap`, `agent_name`), `onToolEnd` callback |
| `core/threads/types.ts` | Thread type additions for agent context |
| `core/threads/utils.ts` | Agent-aware thread creation |
| `core/i18n/locales/{en-US,zh-CN,types}.ts` | New `agents` i18n namespace with ~30 keys |
| `core/api/api-client.ts` | Backend base URL helper |
| `core/artifacts/loader.ts` | `isMock` parameter for demo mode |
| `core/config/index.ts` | Config updates |
| `core/settings/hooks.ts` | Settings hook refinements |
| `workspace/messages/message-list.tsx` | Rendering logic adjustments |
| `workspace/messages/message-list-item.tsx` | Message item changes |
| `workspace/todo-list.tsx` | Todo list adjustments |
| `workspace/thread-title.tsx` | Thread title component changes |

#### Infrastructure

| File | Changes |
|------|---------|
| `docker/nginx/nginx.conf` | Route `/api/agents/*` to Gateway |
| `docker/nginx/nginx.local.conf` | Same for local nginx |
| `Makefile` | Minor addition |

### Data Model

Agents are stored on disk under a configurable agents directory:

```
backend/.think-tank/agents/
├── my-agent/
│   ├── config.yaml      # AgentConfig: name, description, model, tool_groups
│   └── SOUL.md           # Personality, values, behavioral guardrails
└── another-agent/
    ├── config.yaml
    └── SOUL.md
```

Agent names must match `^[A-Za-z0-9-]+$` and are normalized to lowercase.

### API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/agents` | List all custom agents |
| `GET` | `/api/agents/check?name=X` | Validate name availability |
| `GET` | `/api/agents/{name}` | Get agent details + SOUL.md |
| `POST` | `/api/agents` | Create agent (name, description, model, tool_groups, soul) |
| `PUT` | `/api/agents/{name}` | Update agent config/soul |
| `DELETE` | `/api/agents/{name}` | Delete agent |
| `GET` | `/api/user-profile` | Get global USER.md |
| `PUT` | `/api/user-profile` | Set global USER.md |

### Agent Creation Flow

1. User navigates to `/workspace/agents/new`
2. **Step 1**: Enter agent name (validated against `^[A-Za-z0-9-]+$`, checked for availability via `/api/agents/check`)
3. **Step 2**: Bootstrap chat — a special `is_bootstrap=true` thread with the `bootstrap` skill guides the user through defining the agent's personality
4. The bootstrap conversation culminates in the LLM calling `setup_agent` tool, which writes `config.yaml` + `SOUL.md` to disk
5. UI detects `setup_agent` tool completion, fetches the created agent, shows success card

### Runtime Behavior

- `make_lead_agent(config)` reads `agent_name` from `config.configurable`
- If `agent_name` is set, loads `AgentConfig` → uses agent's model, tool groups, SOUL.md
- System prompt includes `{agent_name}` and `<soul>` section
- Memory is stored/loaded per-agent (separate from global memory)
- `MemoryMiddleware` receives `agent_name` for per-agent storage

## Merge Complexity

**28 conflicting files** out of 61 total. Key conflict areas:

### High-Conflict Files (require careful manual resolution)

| File | Conflict Type | Notes |
|------|---------------|-------|
| `lead_agent/agent.py` | Content | Our version has runtime model_spec, provider-based resolution, reasoning_effort, usage tracking middleware — heavily diverged |
| `lead_agent/prompt.py` | Content | Our version has different template variables, tool policies, date formatting |
| `threads/hooks.ts` | Content | Our version has subagent trajectory handling, SSE event processing |
| `memory/updater.py` | Content | Our version has different memory data structure |
| `message-list.tsx` | Content | Our version has subagent visualization, trajectory loading |
| `en-US.ts` / `zh-CN.ts` / `types.ts` | Content | Our version has extensive i18n additions (agent timeline, subagent UI) |

### Structural Conflicts (files we deleted/restructured)

| File | Issue |
|------|-------|
| `workspace/chats/[thread_id]/page.tsx` | Deleted in HEAD (we use different routing) |
| `workspace/layout.tsx` | Deleted in HEAD |
| `workspace-nav-chat-list.tsx` | Deleted in HEAD |
| `nginx.local.conf` | Deleted in HEAD |
| `test_client_live.py` | Deleted in HEAD |

## Recommended Merge Strategy

### Phase 1: Backend (lower conflict, higher value)

1. **New files** — copy directly, no conflicts:
   - `backend/src/config/agents_config.py`
   - `backend/src/gateway/routers/agents.py`
   - `backend/src/tools/builtins/setup_agent_tool.py`
   - `backend/tests/test_custom_agent.py`
   - `skills/public/bootstrap/` (entire directory)

2. **Adapt to our codebase** (manual merge):
   - `lead_agent/agent.py` — add `agent_name`/`is_bootstrap` config reading, `load_agent_config()` call, agent-aware model resolution, bootstrap agent branch. Preserve our runtime model_spec, provider resolution, reasoning_effort, and middleware chain.
   - `lead_agent/prompt.py` — add `{agent_name}`, `{soul}`, `available_skills` params. Keep our template content (we use "Thinktank.ai" not "DeerFlow 2.0").
   - `memory/updater.py` — add `agent_name` parameter to `get_memory_data()` for per-agent storage paths.
   - `memory/queue.py` — add agent-aware queuing.
   - `middlewares/memory_middleware.py` — add `agent_name` constructor param.
   - `config/paths.py` — add `agent_dir()` and `user_md_file` to our paths module.
   - `gateway/app.py` — register agents router.
   - `tools/builtins/__init__.py` — export `setup_agent`.

3. **Infrastructure**:
   - `docker/nginx/nginx.conf` — add `/api/agents` location block.

### Phase 2: Frontend (higher conflict, requires careful adaptation)

1. **New files** — copy directly:
   - `core/agents/` (entire directory: types, api, hooks, index)
   - `components/workspace/agents/` (agent-card, agent-gallery)
   - `components/workspace/agent-welcome.tsx`
   - `components/workspace/chats/` (chat-box, use-chat-mode, use-thread-chat, index)
   - `components/workspace/artifacts/artifact-trigger.tsx`
   - `app/workspace/agents/` (page, new/page)

2. **Adapt to our codebase** (manual merge):
   - `core/threads/hooks.ts` — add `context` and `onToolEnd` to `useThreadStream`. Preserve our subagent trajectory handling.
   - `core/threads/types.ts` — add agent-related type fields.
   - `core/i18n/locales/*` — add `agents` namespace. Keep our existing additions.
   - `core/api/api-client.ts` — add backend base URL helper.
   - Route the agent chat page for our routing setup (we don't use Next.js file-based routing the same way).

3. **Skip/defer**:
   - `workspace/chats/[thread_id]/page.tsx` — we deleted this; our chat page is structured differently
   - `workspace/layout.tsx` — we deleted this
   - `workspace-nav-chat-list.tsx` — we deleted this
   - `isMock` parameter additions — demo/testing feature, low priority

### Phase 3: Testing & Validation

1. Run `uv run pytest` — ensure existing + new tests pass
2. Run `pnpm check` — ensure frontend compiles
3. Test agent creation flow end-to-end:
   - Create agent via `/workspace/agents/new`
   - Verify config.yaml + SOUL.md written to disk
   - Chat with created agent
   - Verify per-agent memory isolation
4. Test that default (non-agent) chat still works unchanged

## Estimated Effort

- **Backend**: ~2-3 hours (mostly new files, moderate merge in agent.py and prompt.py)
- **Frontend**: ~3-4 hours (routing adaptation, thread hooks merge, i18n merge)
- **Testing**: ~1-2 hours
- **Total**: ~6-9 hours

## Dependencies

This commit depends on upstream's `paths.py` refactoring (centralized path management from commit `d24a66f`), which may need to be merged first or adapted inline.

## Follow-up Commit: #962 (`14d1e01`)

This commit must be merged together with `#957`. It fixes issues introduced by the main feature:

| File | Changes |
|------|---------|
| `backend/src/agents/lead_agent/agent.py` | Skip `load_agent_config()` during bootstrap mode (`is_bootstrap`) to avoid FileNotFoundError when agent doesn't exist yet |
| `frontend/src/app/workspace/agents/[agent_name]/chats/[thread_id]/page.tsx` | Add "New Chat" button, fix `threadId` reference, remove unused `thread_id` param destructuring |
| `frontend/src/app/workspace/agents/new/page.tsx` | Pass `threadId` to `useThreadStream` only when in chat step |
| `frontend/src/components/workspace/artifacts/artifact-trigger.tsx` | Fix null-safety: `!artifacts \|\| artifacts.length === 0` instead of `artifacts?.length === 0` |
| `frontend/src/components/workspace/chats/use-thread-chat.ts` | Reset thread state on pathname change to `/new`; use `useState` + `useEffect` instead of `useMemo` for threadId |
| `frontend/src/core/threads/hooks.ts` | Sync internal `_threadId` with prop via `useEffect`; simplify `onFinish` to use `queryClient.invalidateQueries` instead of manual cache update |
