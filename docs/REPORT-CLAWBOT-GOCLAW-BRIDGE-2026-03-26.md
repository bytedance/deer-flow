# CLAWBOT REPORT — DeerFlow GoClaw Bridge Implementation (Phase 1)

## 1) Metadata
- Date: 2026-03-26 (Asia/Saigon)
- Repo: `D:/project/research-agentic/deer-flow`
- Scope: Bridge Implementation for GPT-4o via GoClaw OAuth Gateway
- Owner Role: Codex (Implementation Lead)

## 2) Objective
Enable DeerFlow to call OpenAI models through GoClaw Bridge with:
- OpenAI model prefix normalization: `openai-codex/`
- No manual API key entry in DeerFlow
- OAuth gateway token auto-load
- Runtime readiness for chat using `gpt-4o` in DeerFlow

## 3) Delivered Changes
1. Custom provider added: `GoClawBridgeChatModel`
- File: `backend/packages/harness/deerflow/models/goclaw_bridge_provider.py`
- Capabilities:
  - Normalizes model name to `openai-codex/<model>`
  - Auto-loads gateway token from runtime/env (`GOCLAW_GATEWAY_TOKEN`/bridge env file)
  - Resolves bridge base URL with precedence:
    - explicit `base_url/openai_api_base`
    - explicit `bridge_base_url`
    - env `GOCLAW_BRIDGE_BASE_URL`
    - fallback default
  - Auto-injects GoClaw headers:
    - `X-GoClaw-User-Id` from `GOCLAW_USER_ID` (fallback `deerflow`)
    - `X-GoClaw-Agent-Id` from `GOCLAW_AGENT_ID`/`GOCLAW_AGENT_KEY` when present

2. Credential loader extended for GoClaw gateway token discovery
- File: `backend/packages/harness/deerflow/models/credential_loader.py`

3. Tests added/updated
- Files:
  - `backend/tests/test_credential_loader.py`
  - `backend/tests/test_goclaw_bridge_provider.py`
- Coverage includes:
  - model prefix normalization
  - token loading behavior
  - base URL env override
  - GoClaw header injection behavior
  - strict/no-token path and anonymous mode path

4. Dev/runtime config updates
- Files:
  - `.dockerignore` (exclude problematic pytest cache build context)
  - `.env.example` (document `GOCLAW_USER_ID`, `GOCLAW_AGENT_ID`)
  - `README.md` (bridge usage notes)

## 4) Runtime Bring-up and Verification
### 4.1 Containers
Gateway/langgraph images rebuilt and services recreated via:
- `docker compose -f docker/docker-compose.yaml build gateway langgraph`
- `docker compose -f docker/docker-compose.yaml up -d --force-recreate --no-deps gateway langgraph`

### 4.2 API Model Registration Check
`GET http://localhost:2026/api/models` returned model list including:
- `gpt-4o-goclaw-bridge`
- `gemini-3.0-flash`
- `gemini-2.5-flash`
- `qwen-2.5-72b`

## 5) Test Evidence (Interface Discipline)
Executed inside `deer-flow-gateway` container:
- Command:
  - `uv run pytest tests/test_credential_loader.py tests/test_goclaw_bridge_provider.py`
- Result:
  - `19 passed in 10.25s`

## 6) End-to-End Smoke Evidence
Executed inside `deer-flow-gateway` container using factory-loaded model:
- Model resolved: `openai-codex/gpt-4o`
- Base URL resolved: `http://host.docker.internal:18790/v1`
- Injected headers:
  - `X-GoClaw-User-Id: deerflow`
  - `X-GoClaw-Agent-Id: chuyen-gia-code`
- Invocation result:
  - `INVOKE_OK=True`
  - Response sample: `Artisan 👋`

## 7) Operational Notes
Local runtime env in this machine was aligned to bridge requirements:
- `GOCLAW_BRIDGE_BASE_URL=http://host.docker.internal:18790/v1`
- `GOCLAW_USER_ID=deerflow`
- `GOCLAW_AGENT_ID=chuyen-gia-code`

## 8) Verdict
- Bridge Integration Status: **READY**
- You can start chat with **GPT-4o** in DeerFlow UI by selecting model `gpt-4o-goclaw-bridge`.

## 9) Hotfix Note (UI Chat Error)
- Incident observed: UI chat run failed with
  - `400 invalid request: json: cannot unmarshal array into ... messages.content of type string`
- Root cause:
  - LangChain payload could send `messages[].content` as array blocks
  - GoClaw `/v1/chat/completions` currently expects `content` as string
- Fix applied:
  - Added payload coercion in `GoClawBridgeChatModel._get_request_payload()` to normalize every message `content` into plain string before sending to GoClaw
- Post-fix evidence:
  - `tests/test_credential_loader.py + tests/test_goclaw_bridge_provider.py` => `20 passed`
  - Smoke invoke from gateway container => success (`Artisan`)
