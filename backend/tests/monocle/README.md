# DeerFlow behavioural tests (Monocle Test Tools)

Trace-based tests for DeerFlow. Monocle records each run as a structured trace
(the agent invocation, every tool call, token usage, timings), and these tests
assert against that trace with [Monocle Test Tools](https://github.com/monocle2ai/monocle).

## How this is meant to be used

Instrument the agent with Monocle and run it against a question. Once it answers
the way you expect and makes the agent and tool calls you expect, capture that
run as a trace. That trace is a golden, labelled reference for the question: a
record of correct behaviour, not just sample data. You turn it into assertions
(the offline example shows how), and then you point those same assertions at the
live agent for the same question, so every later run has to reproduce that
behaviour. The offline test is where you pin down what good looks like; the live
test is what enforces it against a real run.

## Layers

The suite has two:

- **One offline example** (`test_assertion_api_example`) loads a recorded trace
  from file and shows the full fluent vocabulary in one place. It needs no keys
  and no network. Because it asserts against frozen JSON, it guards the trace
  format and the asserter wiring, not DeerFlow's behaviour. Treat it as the
  worked example for writing your own assertions.
- **Two live tests** drive the agent end-to-end and assert on the trace the real
  run emits. These are the behavioural guards: a change that alters routing, tool
  selection, or token cost is caught here. They are explicit opt-in via
  `MONOCLE_LIVE_TESTS=1` and skip by default, so a plain run never spends model
  tokens or hits the network, even on a fully configured checkout.

## Layout

- `test_deerflow.py` — the offline example + two live tests
- `conftest.py` — the `run_agent` fixture (live path only)
- `_helpers.py` — paths and `run_deerflow()`
- `traces/` — the recorded trace the offline example loads
- `requirements.txt` — standalone dependencies

## The committed trace

`traces/web_research_ev_battery.json` is a full, unmodified recording of a real
run, committed whole so the offline example parses a genuine trace. That means
it embeds the DeerFlow system prompt as of the recording date and the content
the run fetched from the web, alongside the span structure the assertions read.
It contains no credentials.

The offline assertions are pinned to this exact trace and to the
`monocle_apptrace` 0.8.8 span shapes: the `LangGraph` agent span name, the tool
names, and the input phrasing. A rename of any of those breaks the offline test
even when behaviour is unchanged; re-record the trace when the prompt, tools, or
model change.

## Run

`monocle_test_tools` hard-depends on the ML eval stack (torch, transformers,
sentence-transformers), so it is a standalone `requirements.txt` install rather
than a backend dependency. When it is absent (e.g. a plain backend venv) the
whole suite skips cleanly via `pytest.importorskip`.

Because that dependency is deliberately absent from the backend deps, **none of
these tests run in CI** — `make test` collects and skips the whole module,
including the offline example. This is an on-demand suite: install the
requirements and run it locally (or wire a dedicated CI job with the
requirements installed) when changing agent behaviour, tools, or routing.

```bash
# from the repo root
pip install -r backend/tests/monocle/requirements.txt

# offline — no network, no keys; the live tests skip unless opted in
pytest backend/tests/monocle/

# opt in to the live behavioural tests (real model calls + web requests)
MONOCLE_LIVE_TESTS=1 pytest backend/tests/monocle/
```

Or, following the backend convention (from `backend/`, with uv):

```bash
uv pip install -r tests/monocle/requirements.txt
uv run pytest tests/monocle/                          # offline
MONOCLE_LIVE_TESTS=1 uv run pytest tests/monocle/     # + live
```

The live tests are opt-in by design: without `MONOCLE_LIVE_TESTS=1` they skip
even on a checkout where credentials and `config.yaml` are present, so the
default command can never spend tokens or write to a sandbox. When opted in,
they still skip if the DeerFlow app is not importable or `config.yaml` is
missing. Model credentials are validated by the configured model itself —
`config.yaml` may select any provider (OpenAI, Anthropic, Gemini, and so on),
so there is no hard-coded key requirement. DeerFlow's `web_search` is
DuckDuckGo and needs no key of its own.

The `monocle_trace_asserter` fixture is provided by `monocle_test_tools`' own
pytest plugin, which registers automatically on install (a `pytest11` entry
point); no `pytest_plugins` configuration is needed.

## Add your own test

1. Run DeerFlow under Monocle and capture a trace of a run you are happy with
   (Monocle writes trace JSON to `.monocle/` by default).
2. For an offline example, move it into `traces/` and load it with
   `monocle_trace_asserter.with_trace_source("file", trace_path=path)`.
3. For a behavioural test, drive the agent live via the `run_agent` fixture and
   `monocle_trace_asserter.validator.test_workflow(run_agent, {"test_input": (...)})`.
4. Assert with the fluent API: `called_agent(...)`, `called_tool(...)`,
   `contains_input` / `contains_any_output(...)`, `under_token_limit(...)`,
   `under_duration(..., span_type="workflow")`.

## Evaluations (note)

Structural assertions are the coverage here. Content/quality evaluations are
**not** wired in this suite because, on the current `monocle_test_tools`, local
evals do **not** compose with file-loaded traces:

- Declarative `test_spans[].eval` (`comparer:"metric"`) is silently ignored by
  `validator.validate()` — `_evaluate_span` has no call sites, so an assertion
  that should fail (e.g. a required keyword that is absent) passes vacuously.
- The fluent `check_eval()` path is wired for the Okahu eval-service signature
  (`filtered_spans=`), which the local evaluators (`keyword_presence`, etc.) do
  not accept — it raises `TypeError`.

So local evals are omitted rather than added as vacuous no-ops. The Okahu eval
layer (needs `OKAHU_API_KEY`) remains an option for content grading.
