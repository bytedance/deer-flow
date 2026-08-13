# Thread Boundary Detection

The root `detect-thread-boundaries` target statically inventories execution
boundaries under `backend/app/` and `backend/packages/harness/deerflow/`. It
prints a concise count by execution domain and writes the complete, versioned
JSON payload to `.deer-flow/thread-boundary-inventory.json`. Every finding has
a stable `boundary_kind`: `asyncio_default_executor`, `dedicated_executor`,
`anyio_worker_thread`, `direct_event_loop_blocking`, `separate_event_loop`, or
`unresolved_dynamic_boundary`.

The AST inventory covers `asyncio.to_thread`, default and explicit
`run_in_executor` submissions, imported aliases, simple same-module helper
wrappers (after pre-registering dedicated executor targets), `set_default_executor`,
`ThreadPoolExecutor` construction/submission,
additional event loops, synchronous LangChain tools, and direct
`BaseChatModel` fallback inheritance. It remains read-only and does not alter
executor routing or sizing.

To supplement the static scan with configured runtime types, run:

```bash
python scripts/detect_thread_boundaries.py \
  --runtime-config config.yaml \
  --json-output .deer-flow/thread-boundary-inventory.json
```

Runtime inspection imports configured tool objects and model classes so it can
record concrete tool names/types/modules, sync functions, async coroutines,
and `_agenerate`/`_astream` ownership. It does not invoke tools, instantiate
models, or call external services; import failures remain in the JSON as
`unresolved_dynamic_boundary` records. The detector implementation and focused
coverage live in `tests/support/detectors/thread_boundaries.py` and
`tests/test_detect_thread_boundaries.py`.
