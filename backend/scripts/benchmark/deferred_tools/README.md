# Deferred-tool retrieval benchmark

Offline, synthetic evaluation for [#6191](https://github.com/bytedance/deer-flow/issues/6191).
It calls production discovery code, not a reimplementation, and never executes
a catalog tool. No model, credentials, running Gateway, or network is needed
during a run. Production routing and dependencies are unchanged.

## Run

From `backend/`, prepare the existing locked environment with `uv sync --locked`:

```bash
PYTHONPATH=. uv run --no-sync python -m scripts.benchmark.deferred_tools \
  --repeats 30 --output-dir /tmp/deferred-native

# Explicit optional dependency installation in uv's separate evaluation env.
PYTHONPATH=. uv run --with 'schemarouter==0.17.0' \
  python -m scripts.benchmark.deferred_tools \
  --adapters keywords,regex,auto-promote,schemarouter \
  --repeats 30 --output-dir /tmp/deferred-comparison

PYTHONPATH=. uv run pytest tests/test_bench_deferred_tools.py -q
```

On PowerShell set `$env:PYTHONPATH='.'` before the commands. Output directories
must be new. Reports belong outside the checkout. `--fixture` accepts a local
version-1 synthetic fixture; the runner never downloads a dataset or package.
An explicitly requested missing/wrong SchemaRouter version fails the run;
there is no fallback to a homegrown implementation.

[SchemaRouter](https://github.com/JDeun/SchemaRouter) is an optional MIT-licensed
third-party comparator. The measured PyPI wheel is pinned in
`requirements-schemarouter.txt` by version and SHA-256. For an already prepared
evaluation environment, `uv pip install --python <python> --no-deps
--require-hashes -r scripts/benchmark/deferred_tools/requirements-schemarouter.txt`
installs that exact wheel. Its dependencies come from the prepared backend
environment. No upstream dataset text or implementation is vendored.

## Fixed inputs and adapters

`fixtures.json` contains 12 invented tool contracts and 22 annotated queries:
17 positive/ambiguous/multiple-tool cases and five unsupported/policy-negative
cases, including an empty allowed catalog, similarly named read/write actions,
schema-field-only intent, Unicode, and literal regex punctuation. Tool order,
per-case allowed names, descriptions, schemas and routing hints are frozen.
This is a small contract fixture, not representative production traffic.

Every adapter receives only the **same post-policy catalog** and query; expected
tool/field annotations are supplied only to the grader. The denied administrator
tool is never registered with either system. This exercises an assumed host
policy projection; it does not establish DeerFlow's production authorization
correctness or turn a frozen catalog into an execution permission grant.

- `keywords`: invokes the real `build_tool_search_tool` with `keywords:<query>`
  and reads its graph-state promotion command and returned schema.
- `regex`: invokes that same tool with the unchanged query. This intentionally
  measures direct raw-query compatibility. It is **not** an evaluation of an
  LLM translating intent into regex; low recall is not evidence the regex engine
  is defective. `select:` oracle queries are not synthesized from labels.
- `auto-promote`: calls production `McpRoutingMiddleware.before_model` built by
  `build_mcp_routing_middleware`, on a fresh user turn for each case. It consumes
  the fixture's operator-supplied routing hints, an additional signal absent from
  raw text search. It is a configuration control, not an equivalent NLP router.
- `schemarouter`: compiles the exact native exported parameter schemas through
  `tool_from_langchain` and calls **SchemaRouter 0.17.0 `retrieve(k=5)`**, without
  binding executors. Its local default analyzer/planner is used; no LLM plugin,
  endpoint, model or credentials are configured. An empty host policy returns
  no candidates before calling its planner, which rejects empty registries.

For dict `args_schema` tools, LangChain's generic invocation schema can differ
from its OpenAI function export. The bridge supplies that exact exported schema
through a read-only view so the comparator does not accidentally receive generic
`ToolCall` arguments instead of the same contract. No tool invocation is bound.

## Metrics and interpretation

All adapters have a top-five budget. Each authorized catalog is constructed once
per adapter, with setup time recorded separately. One unmeasured warmup precedes
each query's timed repeats. p50/p95 are measured with `perf_counter`; they include
local retrieval and adapter serialization, excluding setup, schema expansion and
grading. They are not end-to-end Agent latency or provider/network measurements.

`report.json` contains provenance, summaries and per-case rows; `rows.jsonl`
contains the same rows for analysis. Neither includes queries or full schemas.

| Metric | Definition |
| --- | --- |
| Tool recall | Fraction of annotated required/acceptable tool names present; macro-average over positive cases only. All annotated names count in ambiguous/multiple-tool cases. |
| Input-field recall | Fraction of annotated **top-level input field names** available in returned schemas, qualified by tool name. This measures contract availability, not argument correctness, output-field selection, or independently inferred types. |
| Unsupported rejection | Number of five negative cases returning no candidate. Empty positives do not receive vacuous perfect recall. |
| False-positive tool count | Returned names outside the case's annotation. For auto-promote these are unnecessary schema promotions; for other adapters these are extra shortlist candidates, **not executed wrong calls**. |
| Loaded tool count | Shortlist size, never more than five. No live model binding is performed. |
| Schema bytes | UTF-8 size of the same compact canonical native full-schema list expanded from each shortlist; `[]` costs two bytes. Enables like-for-like expansion cost. |
| Retrieval payload bytes | Actual native search response, canonical auto-promotion schemas, or canonical SchemaRouter retrieval object. Formats differ; do not compare this column as equivalent schema cost. |

Unsupported intent may still have lexically related authorized tools. A shortlist
is not an execution decision: broad retrieval can improve recall while hurting
rejection and schema size. Report both, including negative results. No adoption,
quality win, production speedup or token/cost savings follows from this fixture.

Provenance records the fixture SHA-256, git revision/dirty state, benchmark and
production source hashes, Python/platform and package versions, adapter identity,
and the optional SchemaRouter package source digest. There are no random seeds,
model prompts, inference parameters or retries: this is deterministic local
discovery. Repeat results must agree; denied names or over-budget results fail
closed. Native discovery-budget errors fail the run rather than counting as
successful unsupported rejections. Tests forbid socket connections and catalog-tool execution for all
installed adapters.

The framework is intended to accept a larger independently annotated synthetic
fixture next. Live model-generated search queries, execution correctness, field
value extraction, realistic workload distributions and large-catalog scaling
remain separate experiments.
