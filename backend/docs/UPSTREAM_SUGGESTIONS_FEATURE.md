# Upstream Feature: Follow-up Suggestions ("You May Ask")

**Upstream commit:** `9d2144d431a81960936fb9ae313a34f698c4d236`
**PR:** #981
**Status:** Deferred — backend can be taken as-is; frontend requires manual port

## Overview

After each AI response, the system generates 3 short follow-up questions the user might ask next. These appear as clickable suggestion chips above the input box, reducing friction for continuing conversations.

## Architecture

### Backend: `POST /api/threads/{thread_id}/suggestions`

A new FastAPI router (`backend/src/gateway/routers/suggestions.py`) with a single endpoint:

```
POST /api/threads/{thread_id}/suggestions
```

**Request:**
```json
{
  "messages": [
    { "role": "user", "content": "What is quantum computing?" },
    { "role": "assistant", "content": "Quantum computing uses qubits..." }
  ],
  "n": 3,
  "model_name": null
}
```

**Response:**
```json
{
  "suggestions": [
    "How do qubits differ from classical bits?",
    "What are practical applications of quantum computing?",
    "Which companies are leading in quantum research?"
  ]
}
```

**Implementation details:**
- Takes the last N messages from the conversation (client sends last 6)
- Formats them as `User: ...` / `Assistant: ...` text
- Sends a one-shot prompt to a lightweight LLM (thinking disabled) asking for exactly N questions as a JSON array
- Parses the response (strips markdown code fences, extracts JSON array)
- Returns empty array on any error (graceful degradation)
- Questions are generated in the same language the user is speaking

**Key prompt requirements:**
- Questions must be relevant to the conversation
- Keep each ≤20 words (≤40 Chinese characters)
- No numbering, no markdown — plain JSON string array
- Model override via `model_name` parameter

**Note:** The upstream code has a bug on the prompt line — it uses an f-string with `.format()` which double-substitutes `{n}` and `{conversation}`. This should be fixed when porting (remove the `.format()` call).

### Frontend: Suggestion Chips in Input Box

**Trigger:** When streaming finishes (`wasStreaming && !streaming`), the frontend:
1. Extracts the last 6 human/AI messages
2. Calls `POST /api/threads/{threadId}/suggestions`
3. Displays results as clickable chips above the input box
4. Shows a loading state ("Generating follow-up questions...") during the API call

**Interaction flow:**
- Click a suggestion → auto-fills input and submits immediately
- If the input box already has text → shows a confirmation dialog:
  - "Replace & send" — overwrites existing text
  - "Append & send" — adds suggestion below existing text
  - "Cancel" — keeps existing text, no action
- Close button (X) dismisses suggestions
- Suggestions hidden after any submission
- Deduplicated by `lastGeneratedForAiIdRef` to avoid regenerating for the same response

**i18n:** New keys added to `en-US.ts`, `zh-CN.ts`, and `types.ts`:
- `followupLoading`, `followupConfirmTitle`, `followupConfirmDescription`
- `followupConfirmAppend`, `followupConfirmReplace`

## Files Changed (Upstream)

| File | Type | Notes |
|------|------|-------|
| `backend/src/gateway/routers/suggestions.py` | **New** | Core endpoint — can be taken verbatim (fix the f-string bug) |
| `backend/tests/test_suggestions_router.py` | **New** | 6 unit tests — can be taken verbatim |
| `backend/src/gateway/app.py` | Modified | Register suggestions router — manual 3-line edit |
| `backend/src/gateway/routers/__init__.py` | Modified | Add `suggestions` to exports — 2-line edit |
| `frontend/src/components/workspace/input-box.tsx` | Modified | **Major changes** — 250+ lines added. Cannot cherry-pick (Next.js App Router, different component structure). Must be manually ported to our Vite/React Router `input-box.tsx` |
| `frontend/src/app/workspace/chats/[thread_id]/page.tsx` | Modified | Pass `threadId` prop — file doesn't exist in our fork (App Router) |
| `frontend/src/core/i18n/locales/en-US.ts` | Modified | 6 new i18n keys — easy manual addition |
| `frontend/src/core/i18n/locales/zh-CN.ts` | Modified | 6 new i18n keys |
| `frontend/src/core/i18n/locales/types.ts` | Modified | 5 new type fields |

## Recommended Merge Strategy

### Phase 1: Backend (low effort, no conflicts)
1. Copy `suggestions.py` to `backend/src/gateway/routers/`
2. Fix the f-string bug: remove the `.format(n=n, conversation=conversation)` call
3. Register the router in `app.py` and `__init__.py`
4. Copy `test_suggestions_router.py` to `backend/tests/`
5. Add auth middleware if needed (upstream doesn't authenticate this endpoint)

### Phase 2: Frontend (dedicated task)
1. Add i18n keys to our locale files
2. Port the suggestion chips UI to our `input-box.tsx` (different component structure)
3. Wire up the API call on stream completion
4. Handle the confirmation dialog for non-empty input
5. Use `authFetch` instead of plain `fetch` for the API call

## Considerations

- **Cost:** Each completed AI response triggers an additional LLM call. Consider making this configurable or using a very cheap model.
- **Latency:** Suggestions appear asynchronously — no impact on the main response, but there's a visible loading state.
- **Auth:** The upstream endpoint has no authentication. Our fork should wrap it with `require_auth` like other gateway endpoints.
- **Abort handling:** The frontend correctly uses `AbortController` to cancel in-flight requests on component unmount or new messages.
