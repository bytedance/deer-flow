## 1. Assistant Persona (Backend — System Prompt)

- [x] 1.1 Add `<assistant_persona>` section to `SYSTEM_PROMPT_TEMPLATE` in `prompt.py` with tone rules, empathy guidelines, and behavioral expectations (~400 tokens)
- [x] 1.2 Define safety-aware tone grading with four levels (Normal/Attention/Warning/Emergency) in persona section, including explicit rules for severity-based tone switching and prohibition of softening language for critical findings
- [x] 1.3 Add language-following instruction to persona section: "match the user's language in all responses"
- [x] 1.4 Include user name injection: read `workContext` from memory and add "address user by context" guidance to persona section
- [x] 1.5 Add persona validation test: verify persona section is present in generated prompts for builtin, tenant, and user agents
- [x] 1.6 Verify token count of persona section stays under 400 tokens (including safety tone grading rules)

## 2. Greeting API (Backend)

- [x] 2.1 Create `GET /api/threads/{thread_id}/greeting` endpoint in a new `greetings` router under `app/gateway/routers/`
- [x] 2.2 Implement greeting generation logic: read user memory (`workContext`, `recentMonths`), current time, and recent thread activity to build personalized greeting text
- [x] 2.3 Implement language detection for greeting: inspect user's last message in thread, detect language via Unicode range (CJK → zh-CN, Latin → en-US), default to zh-CN for new threads
- [x] 2.4 Generate bilingual greeting and suggestion templates: maintain zh-CN and en-US versions for default greetings and generic suggestions
- [x] 2.5 Implement suggestion generation: derive 2-3 context-aware suggestion strings from memory facts and recent analysis history, in detected language
- [x] 2.6 Add 2-second timeout with fallback to default greeting when generation exceeds threshold
- [x] 2.7 Implement alert-aware greeting: query active anomalies/alarms on user's monitored equipment (500ms timeout, non-blocking), and prepend alert message when active alerts exist
- [x] 2.8 Implement equipment-priority-ordered suggestions: query equipment metadata for criticality levels (critical > important > general), sort suggestion chips by priority, and boost devices with recent anomalies (7 days) in suggestion ranking
- [x] 2.9 Add unit tests for greeting generation: with memory, without memory, timeout fallback, active alert override, equipment priority ordering, language detection (zh-CN input, en-US input, new thread default)
- [x] 2.10 Register greetings router in `app/gateway/app.py`

## 3. Greeting Card (Frontend)

- [x] 3.1 Create `GreetingCard` component under `frontend/src/components/workspace/chats/` with avatar, greeting text, and suggestion chips
- [x] 3.2 Create `greeting` API client function in `frontend/src/core/api/` to call `GET /api/threads/{thread_id}/greeting`
- [x] 3.3 Create `useGreeting` hook with loading state, 2s timeout, and error fallback
- [x] 3.4 Replace `ConversationEmptyState` in `chat-box.tsx` with `GreetingCard` when thread has no messages
- [x] 3.5 Implement skeleton loading state for greeting card (shimmer effect)
- [x] 3.6 Wire suggestion chips to populate chat input and submit as user message
- [x] 3.7 Add i18n strings for default greeting text and generic suggestions (zh-CN + en-US)
- [x] 3.8 Add E2E test: new thread shows greeting card with suggestions in correct language

## 4. Empathetic Error Handling (Backend)

- [x] 4.1 Define `ErrorCategory` enum in `deerflow/agents/middlewares/` with values: `network_issue`, `timeout`, `service_unavailable`, `data_not_found`, `permission_denied`, `rate_limited`
- [x] 4.2 Enhance `LLMErrorHandlingMiddleware` to map caught exceptions to `ErrorCategory` and attach `error_category` + `suggested_action` to error ToolMessages
- [x] 4.3 Add unit tests for error category mapping (network errors, timeouts, unknown errors)

## 5. Empathetic Error Handling (Frontend)

- [x] 5.1 Add empathetic error message strings to i18n locales (zh-CN + en-US) keyed by `ErrorCategory`
- [x] 5.2 Update error rendering in chat message components to use i18n empathetic text instead of raw error strings
- [x] 5.3 Add expandable "查看详情" section for technical error details
- [x] 5.4 Add "重试" action button for retryable error categories (`network_issue`, `timeout`)
- [x] 5.5 Add unit tests for error message rendering with each category

## 6. Care Loop Follow-up (Backend)

- [x] 6.1 Add follow-up prompt guidance to `<assistant_persona>` section: after completing analysis/report, summarize key findings and offer 1-2 next actions
- [x] 6.2 Add `followup` category support to memory fact extraction: when assistant generates a follow-up, store a `pendingFollowUp` fact with context
- [x] 6.3 Update greeting generation logic (from task 2.2) to check for `pendingFollowUp` memory facts and reference them in the greeting
- [x] 6.4 Add memory cleanup: clear `pendingFollowUp` fact when user addresses the same topic in conversation
- [x] 6.5 Implement closure ticket status follow-up in greeting API: query open/recently closed tickets linked to user's analyzed devices, surface status changes in greeting (e.g., "您之前为2号泵组开的闭环单已进入处理中状态")
- [x] 6.6 Implement follow-up prompt for recently closed tickets: when a closure ticket linked to recent analysis was closed within 7 days, offer re-inspection analysis in follow-up prompt
- [x] 6.7 Implement preventive maintenance cycle reminder in greeting API: query equipment metadata for scheduled maintenance dates, include maintenance reminder suggestion when within 14 days, offer pre-maintenance status assessment report
- [x] 6.8 Add ticket staleness filter: do not surface closure tickets closed more than 30 days ago in proactive greetings or follow-ups
- [x] 6.9 Add unit tests for follow-up memory lifecycle (create, reference in greeting, clear), closure ticket follow-up, and maintenance reminder

## 7. Assistant Status Indicators (Frontend)

- [x] 7.1 Create `AssistantStatusIndicator` component that derives status text from current streaming tool calls
- [x] 7.2 Map tool call names to human-readable status strings: data tools → "正在查询数据…", report tools → "正在生成报告…", no tools → "正在思考…"
- [x] 7.3 Integrate status indicator into chat message area (replacing generic spinner) during streaming
- [x] 7.4 Add i18n strings for all status indicator texts (zh-CN + en-US)
- [x] 7.5 Add unit tests for tool-name-to-status-text mapping

## 8. Assistant Avatar and Identity (Frontend)

- [x] 8.1 Add agent avatar icon and display name rendering to assistant message bubbles
- [x] 8.2 Create default assistant avatar SVG (friendly robot/AI icon) for agents without custom icons
- [x] 8.3 Read agent icon from thread's agent config and render in message header
- [x] 8.4 Add E2E test: assistant messages show avatar and name label

## 9. Integration and Verification

- [x] 9.1 Run full backend test suite to verify no regressions
- [x] 9.2 Run full frontend type check and lint
- [x] 9.3 Manual E2E verification: open new thread → see greeting card (with alert if active) → click suggestion → see avatar + status indicator → receive response with follow-up and closure ticket status → trigger error → see empathetic error message → verify language follows user input
- [x] 9.4 Update CLAUDE.md and README.md with new assistant persona documentation
