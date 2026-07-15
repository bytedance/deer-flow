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
  selection, or token cost is caught here. They need `OPENAI_API_KEY` and the
  DeerFlow app, so they skip by default.

## Layout

- `test_deerflow.py` — the offline example + two live tests
- `conftest.py` — the `run_agent` fixture (live path only)
- `_helpers.py` — paths and `run_deerflow()`
- `traces/` — the recorded trace the offline example loads
- `requirements.txt` — standalone dependencies

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

# offline example — no network, no keys
pytest backend/tests/monocle/

# add the live behavioural tests (needs OPENAI_API_KEY + the DeerFlow app)
pytest backend/tests/monocle/ -k live
```

Or, following the backend convention (from `backend/`, with uv):

```bash
uv pip install -r tests/monocle/requirements.txt
uv run pytest tests/monocle/            # offline
uv run pytest tests/monocle/ -k live    # + live
```

The live tests skip automatically when `OPENAI_API_KEY` is unset, when the
DeerFlow app is not importable, or when `config.yaml` is missing. DeerFlow's
`web_search` is DuckDuckGo, so a live run needs only `OPENAI_API_KEY`.

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
