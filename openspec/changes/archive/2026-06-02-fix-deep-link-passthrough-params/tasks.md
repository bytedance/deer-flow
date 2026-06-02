## 1. Gateway — Preserve additional_kwargs in message deserialization

- [x] 1.1 Update `normalize_input()` in `backend/app/gateway/services.py` to copy `additional_kwargs` from JSON message dicts into `HumanMessage` constructor
- [x] 1.2 Verify existing Gateway tests pass — ensure no regression in `test_gateway_services.py`

## 2. Backend — PassthroughParamsMiddleware

- [x] 2.1 Create `backend/packages/harness/deerflow/agents/middlewares/passthrough_params_middleware.py` with `PassthroughParamsMiddleware` class following the `UploadsMiddleware` pattern
- [x] 2.2 Implement `before_agent()` to extract non-internal keys from first HumanMessage's `additional_kwargs` and prepend `<deep_link_params>` block to content
- [x] 2.3 Register middleware in `_build_runtime_middlewares()` in `backend/packages/harness/deerflow/agents/middlewares/tool_error_handling_middleware.py` after `ThreadDataMiddleware`

## 3. Tests — PassthroughParamsMiddleware

- [x] 3.1 Write unit tests: passthrough params injected into content correctly
- [x] 3.2 Write unit tests: internal keys (`files`, `hide_from_ui`, `element`) excluded from injection
- [x] 3.3 Write unit tests: no-op when no passthrough params present
- [x] 3.4 Write unit tests: only first HumanMessage is processed (multi-turn safety)
- [x] 3.5 Write unit tests: `additional_kwargs` preserved on message after injection

## 4. Agent SOUL.md — Update deep-link parameter handling

- [x] 4.1 Update `agents/builtin/fault-diagnosis--pump/SOUL.md` to reference `<deep_link_params>` block
- [x] 4.2 Update `agents/builtin/fault-diagnosis--rotating/SOUL.md` to reference `<deep_link_params>` block
- [x] 4.3 Update `agents/builtin/fault-diagnosis--reciprocating/SOUL.md` to reference `<deep_link_params>` block
- [x] 4.4 Update `agents/builtin/monitoring-analysis/SOUL.md` to reference `<deep_link_params>` block
- [x] 4.5 Update `agents/builtin/defect-closure/SOUL.md` to reference `<deep_link_params>` block
- [x] 4.6 Update `agents/builtin/ai-report--daily/SOUL.md` to reference `<deep_link_params>` block

## 5. Verify deep-link flow end-to-end

- [x] 5.1 Verify gateway normalization + middleware injection via unit tests (84/84 passing, no regressions)
- [x] 5.2 Verify auto_send passthrough + agent auto_start passthrough render correctly (middleware: no-op for internal keys, params injected for passthrough keys)
