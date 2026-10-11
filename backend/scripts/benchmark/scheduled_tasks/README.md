# Synthetic scheduled-work Gateway pilot

This runs the production Gateway, scheduler, conversation tools, goal worker,
sandbox artifact tools and persistence. It does not provide another agent loop.
All sources and expected artifacts are explicitly synthetic and pinned by the
committed fixture's SHA-256. No external dataset or network source is fetched.

`plan` is offline. Only an explicit `run-live` starts paid agent work. The runner
never starts a Gateway, loads credentials, changes models or adds account funds.
Use a separately started, disposable loopback Gateway, a new `DEER_FLOW_HOME`
and SQLite directory, empty extension/MCP configuration, and disabled channels,
memory and automatic titles. Never point it at existing user data.

## Required pilot configuration

The reproduction pilot uses the user's selected official DeepSeek V4.1 Flash
profile: alias and API model ID `deepseek-flash`, official endpoint
`https://api.deepseek.com`, non-thinking mode, temperature 0, output cap 1024,
SDK `max_retries: 0`, normal per-run token budget 60,000, the repository's default
recursion limit 1000 and request
timeout 120 seconds. Credentials belong only in the named `DEEPSEEK_API_KEY`
environment variable of the separately started Gateway.

The normal budget was raised after one pilot occurrence used about 25,000
tokens to produce and deliver a correct report. Use the same 60,000-token budget
for both matched arms so that this early threshold does not confound their
comparison. Provenance records the actual configured budget and the normal
reference separately; the independent tiny-budget phase remains 1000 tokens.

The configured USD rates are conservative peak estimates: input 0.30 and output
1.20 per million tokens. The operator checked the
[official pricing page](https://api-docs.deepseek.com/quick_start/pricing/) for
this pilot. Provider billing and off-peak/cache discounts are not established by
the runner. Cost is calculated with production Console `_run_cost` from durable
`RunRow` usage, using the configured miss price conservatively.

The pilot configuration must include:

```yaml
models:
  - name: deepseek-flash
    use: langchain_openai:ChatOpenAI
    model: deepseek-flash
    base_url: https://api.deepseek.com
    api_key: $DEEPSEEK_API_KEY
    temperature: 0
    max_tokens: 1024
    max_retries: 0
    timeout: 120
    extra_body:
      thinking:
        type: disabled
    pricing:
      currency: USD
      input_per_million: 0.30
      output_per_million: 1.20
database:
  backend: sqlite
  sqlite_dir: /ABSOLUTE/DISPOSABLE/DATABASE/DIRECTORY
scheduler:
  enabled: true
  tool_enabled: true
  min_once_delay_seconds: 1
  poll_interval_seconds: 1
  max_concurrent_runs: 1
token_budget:
  enabled: true
  max_tokens: 60000
recursion_limit: 1000
max_recursion_limit: 1000
memory:
  enabled: false
title:
  enabled: false
sandbox:
  use: deerflow.sandbox.local:LocalSandboxProvider
tools:
  - name: read_scheduled_fixture
    group: benchmark
    use: scripts.benchmark.scheduled_tasks.fixture_tools:read_scheduled_fixture
  - name: write_file
    group: file
    use: deerflow.sandbox.tools:write_file_tool
  - name: read_file
    group: file
    use: deerflow.sandbox.tools:read_file_tool
  - name: read_conversation
    group: conversation
    use: deerflow.tools.conversation:read_conversation
```

The fixture reader is operator-controlled Python configuration. It accepts only
four committed case IDs and never opens a caller-selected file or URL. Expected
answers are withheld from its return value. Actual reports use production
`write_file` and `present_files`, and are opened through the Gateway artifact
endpoint before an independent JSON/value grade is recorded.

Mark only the disposable database directory after Gateway initialized it:

```bash
touch "$SCHEDULED_PILOT_SQLITE_DIR/.scheduled-benchmark-disposable"
```

## Commands

Run from `backend/`, with the exact configuration used by the separately
started Gateway. Each output directory must be new. Outputs belong in the
outer workspace's `outputs/scheduler-agent-20261003/`, outside the Git worktree.

```bash
uv run --no-sync python -m scripts.benchmark.scheduled_tasks plan \
  --config "$SCHEDULED_PILOT_CONFIG" --model deepseek-flash

uv run --no-sync python -m scripts.benchmark.scheduled_tasks run-live \
  --config "$SCHEDULED_PILOT_CONFIG" --model deepseek-flash \
  --base-url http://127.0.0.1:8023 --phase lifecycle \
  --output "$SCHEDULED_PILOT_OUTPUT/lifecycle" \
  --max-cost 1 --reserve-per-run 0.08 --timeout 180 --interval 90

uv run --no-sync python -m scripts.benchmark.scheduled_tasks run-live \
  --config "$SCHEDULED_PILOT_CONFIG" --model deepseek-flash \
  --base-url http://127.0.0.1:8023 --phase paired \
  --output "$SCHEDULED_PILOT_OUTPUT/paired" \
  --max-cost 1 --reserve-per-run 0.08 --timeout 120
```

For `--phase budget`, deliberately restart/reconfigure the disposable Gateway
with `token_budget.max_tokens: 1000` and pass that exact new config file. The
runner requires a tiny budget no greater than 2000, schedules one goal fixture,
and checks the durable `token_capped` stop or its recorded verdict stand-down
reason. The public history API projects title/thread-data/messages and omits the
goal channel. The benchmark reads the same marked disposable SQLite database
through the production `CheckpointStateAccessor` and native saver with
`mode=ro` and `query_only=ON`, using the configured full/delta mode and cadence.
It reads the complete root history, requires zero continuations and counters
within their recorded limit, checks
goal cleanup, and observes no later lead-model turn or second occurrence. Missing
counter evidence fails the phase. It records actual usage, including any one-call
overshoot. Do not change the model or prices for this phase.

An already recorded tiny-budget run can be rechecked without a Gateway or a
provider call. Use its exact original configuration and a new output file:

```bash
uv run --no-sync python -m scripts.benchmark.scheduled_tasks recheck-budget \
  --config "$SCHEDULED_PILOT_BUDGET_CONFIG" --model deepseek-flash \
  --run-output "$SCHEDULED_PILOT_OUTPUT/budget-1" \
  --output "$SCHEDULED_PILOT_OUTPUT/budget-evidence-recheck-v2.json"
```

The reader is constrained to the disposable default-owner lead assistant and
base schema without custom/plugin middleware. It preserves the original
failure/results, matches the actual run's objective, status, calls and usage,
and labels the new result as a read-only persisted-state recheck of the existing
real Gateway run. Missing snapshots or counters fail; no zero is fabricated.

The USD 1 admission guard sums all runs in the disposable database, including
earlier pilot phases, and reserves USD 0.08 before each new run. It polls live
usage and cancels active pilot work after a guard failure. This is an estimated
spend guard, **not a hard provider billing limit**: usage becomes visible after
calls, token budgets can overshoot once, and billing may differ from configured
rates. The reserve and observed usage are preserved in provenance and results.
No application-level or provider retries are added by the runner.

## What each phase proves

`lifecycle` creates one schedule through `schedule_task` in a real conversation.
An automatic fresh-thread occurrence reads the fixture and produces the main
branch report. The runner pauses between occurrences solely to avoid a note
timing race, adds the exact user note through the same original conversation,
then resumes. The second automatic occurrence must read the first through
`read_conversation`, follow the develop note, write the independently graded
report and call `stop_scheduled_task`. The runner checks the durable stop-run ID,
parent paused state, different occurrence threads and no next dispatch. Its
temporary between-occurrence pause does not count as self-stop evidence.
An unsuccessful creation or note run, or failed first artifact/source grade,
fails immediately and cleans up instead of paying for the next stage. A task
committed by the creation tool is discovered for cleanup even if the surrounding
interactive run fails. Preserve failed configuration trials separately. A small
graph recursion budget can stop a correct model response because the middleware
chain uses many supersteps per turn; the pilot records configuration failures
without counting them as model loops or implementation defects.

`paired` uses three matched synthetic inputs, with alternating arm order and
fresh threads. Fixture setup uses production `ScheduledTaskRepository.create`
and shared Gateway creation validation on one real HTTP-created owner origin
thread. Both arms carry the same origin binding, sources, prompt, output name,
model settings and budget; only the goal field differs. This setup bypasses the
conversation creation step to avoid charging setup-model calls to the study;
the lifecycle phase independently covers that user-facing step. The real
Gateway poller and ordinary run worker execute every occurrence.

An alleged goal arm is rejected unless its actual run has goal metadata and a
durable `goal_verdict`. A plain arm is rejected if either appears. Artifact and
source-use grades are independent of the evaluator's verdict. Delivery is checked
separately against the host's `run.delivery` receipt and its successful
`present_files` path binding; an AI claim or requested tool-call name cannot
establish delivery. Effective independent completion requires correct artifact
values, source use, host delivery and successful run status. A subsequent
`token_capped` stop does not erase verified completion; a capped run without
delivery remains incomplete. The cap flag, goal verdict and all evidence columns
are preserved separately for analysis of partial results and evaluator false
negatives. Results retain
the raw occurrence status, goal verdict, lead-model turns, total model calls,
input/output/per-model tokens, peak-price cost estimate and artifact hashes.
The summary reports each arm descriptively. Three synthetic cases are not a
statistical or general completion-rate claim, and zero benefit is a valid result.

## Recovery and delivery limits

The lifecycle phase records `restart_recovery: not_exercised_by_this_phase`.
Testing a crash between durable self-stop and completion needs a separately
controlled pause/barrier in the disposable agent and a restart of the exact
Gateway process the operator started. Preserve the stop-request row before the
crash, then verify recovery pauses the parent, leaves no further dispatch and
that a repeated completion after user resume cannot pause it again. Offline
repository/runtime regressions cover this contract; do not relabel them as a
real-Gateway restart observation.

No provider-account IM delivery is attempted. Writing an outbox row is not
evidence of receiving a WeCom notification. The runner reports delivery as
`not_tested` and never reads or messages existing user chats/platform accounts.

Provenance stores config/fixture/prompt hashes, tracked Git diff hash, explicit
untracked Python/contract/fixture source hashes, model parameters, timestamps,
timeouts and rates. It never stores credentials, response headers or complete
provider request payloads. Failures and cleanup failures remain visible, and
terminal task definitions are preserved. If cleanup cannot pause active work,
stop the disposable Gateway before leaving it unattended.

Offline validation:

```bash
uv run --no-sync pytest tests/test_bench_scheduled_tasks.py -q
```
