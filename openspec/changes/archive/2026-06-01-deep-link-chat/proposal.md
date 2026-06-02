## Why

External systems (monitoring dashboards, alerting platforms, ERP systems, equipment management UIs) need to deep-link into DeerFlow with pre-populated context — a specific agent, a pre-filled prompt, or metadata — so operators can jump from "something looks wrong" to "ask the AI about it" in one click. Without this, users must manually navigate, select an agent, and type out the context each time, creating friction for high-frequency operator workflows.

## What Changes

- Define a URL query parameter convention for deep-linking into chat/agent pages with pre-filled message text, auto-start flag, and optional context metadata
- Add parameter parsing and sanitization on the frontend (both `/workspace/chats/[thread_id]` and `/workspace/agents/[agent_name]/chats/[thread_id]` pages)
- Support `auto_start` flag that triggers `sendMessage` immediately on page load (new threads only)
- Reuse existing `useSpecificChatMode` pattern — extend it to handle the deep-link parameters generically
- Validate parameters at the boundary: reject malformed params, sanitize prompt text, enforce length limits

## Capabilities

### New Capabilities
- `deep-link-chat`: URL parameter convention for external systems to deep-link into DeerFlow chats/agents with pre-filled or auto-started messages

### Modified Capabilities
<!-- None — this is a new capability with no requirement changes to existing specs -->

## Impact

- Frontend: `use-chat-mode.ts`, `use-thread-chat.ts`, agent chat page, general chat page
- No backend changes required — parameters are consumed entirely on the frontend
- No API contract changes
- No breaking changes to existing URL patterns
