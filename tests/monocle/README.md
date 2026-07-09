# DeerFlow behavioural tests (Monocle Test Tools)

Trace-based tests that lock in DeerFlow's behaviour. Monocle records each run as
a structured trace -- the agent invocation, every tool call, token usage, and
timings -- and each test asserts against that trace: which agent ran, which
tools it called, what it was asked, what it produced, and its token/duration
cost. A later prompt, model, or tool change that regresses the behaviour fails
here.

Traces are loaded by file via the Test Tools file trace source (no keys, no re-run).

## Layout

- `test_deerflow.py` — the suite: four offline file-loaded tests + one live test
- `conftest.py` — Monocle setup, `.env` loading, and `run_deerflow()`
- `traces/` — one recorded trace per curated question
- `requirements.txt` — dependencies

## Tests

| Test | Scenario | What it shows |
|---|---|---|
| `test_q0_ev_battery_briefing` | Solid-state EV battery briefing | input/output, tool counts, a negative assertion, budget |
| `test_q1_vector_db_comparison` | Open-source vector-DB comparison | research path, `web_search`, budget |
| `test_q2_ev_battery_briefing_repeat` | The briefing again (dup of Q0) | a second independent trace of the same question |
| `test_q3_fibonacci_sandbox` | Author a script to a file | `write_file`, sandbox path (no web tools) |
| `test_web_research_live` | The briefing, run live | end-to-end run, structure + budget only |

The offline tests load recorded traces with budgets measured from those runs
(rounded up with headroom). The live test drives the agent end-to-end and asserts
structure and budget only, since the output legitimately varies run to run.

## Run

```bash
pip install -r tests/monocle/requirements.txt   # Monocle Test Tools

# offline file-loaded tests — no network, no keys (standalone test-tools venv is fine)
pytest tests/monocle/

# also run the live end-to-end path (needs OPENAI_API_KEY + the DeerFlow app importable)
pytest tests/monocle/ -k live
```

The live test `importorskip`s the DeerFlow app, so it skips automatically when
run from a venv that only has the Test Tools installed. DeerFlow's `web_search`
is DuckDuckGo, so the live run needs only `OPENAI_API_KEY`.

## Add your own test

1. Run DeerFlow under Monocle and capture a trace of a run you're happy with
   (Monocle writes trace JSON to `.monocle/` by default).
2. Move it into `traces/` and load it with
   `monocle_trace_asserter.with_trace_source("file", trace_path=path)`.
3. Assert with the fluent API — `called_agent(...)`, `called_tool(...)`,
   `contains_input/any_output(...)`, `under_token_limit(...)`,
   `under_duration(..., span_type="workflow")` — then add it alongside the others.

## Evaluations (note)

Structural assertions are the coverage here. Content/quality evaluations are
**not** wired in this suite because, on the current `monocle_test_tools`, local evals
do **not** compose with file-loaded traces:

- Declarative `test_spans[].eval` (`comparer:"metric"`) is silently ignored by
  `validator.validate()` — `_evaluate_span` has no call sites, so an assertion
  that should fail (e.g. a required keyword that is absent) passes vacuously.
- The fluent `check_eval()` path is wired for the Okahu eval-service signature
  (`filtered_spans=`), which the local evaluators (`keyword_presence`, etc.) do
  not accept — it raises `TypeError`.

So local evals are omitted rather than added as vacuous no-ops. The Okahu eval
layer (needs `OKAHU_API_KEY`) remains an option for content grading.
