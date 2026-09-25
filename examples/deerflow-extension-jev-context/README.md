# Jev context pruning — independent plugin example

An opt-in Python plugin that uses Jev to shorten clearly obsolete **read-only
tool results** before DeerFlow's normal summarization. It uses the existing
extension API 0.2.2 and full-stack plugin catalog, with no host code changes.
Distributed under DeerFlow's [MIT license](LICENSE).

## Install and configure

From `backend/` in a compatible DeerFlow deployment:

```sh
uv run deerflow extensions install ../examples/deerflow-extension-jev-context --yes
export TYPESAFE_API_KEY='your-deployment-secret'
```

Set the registered entry in the deployment configuration:

```yaml
plugins:
  - use: deerflow_extension_jev_context:install
    enabled: true
    config:
      enabled: true
      trigger_tokens: 60000
      min_calls_between_attempts: 16
```

Provide the environment variable to the actual Gateway process (including its
container, if applicable). Restart Gateway after installing or changing deployment
configuration; refresh Capability Center to see **Jev context pruning**. The outer
switch loads the package; `config.enabled` enables its middleware and contribution.
It is disabled by default. The plugin catalog is read-only; there is no online
key editor, custom browser page, or new slash command. The authenticated `status`
backend action reports enabled/configured/threshold without exposing credentials.
`configured` means the key environment variable is nonempty, not that authentication
or connectivity has been verified.
No frontend rebuild is required.

**Deployment opt-in sends bounded conversation excerpts, recent user goals,
read-tool arguments and result samples to `https://api.typesafe.ai/v1/systemone`.**
The service uses `jev-latest` and typed `noul` decisions. This is a separate API
from the main chat model; a free main model does not make Jev free. Keys are read
only from the named environment variable, never from plugin settings or messages.

## Behavior and limits

- Runs on the lead agent through `before_model` / `abefore_model` at
  `MODEL_LOGICAL`. No subagent interception or provider retry multiplier.
- Only considers old, successful, plain-text results of `read_file`, `grep`,
  `glob` and `ls`. Calls/results must match unambiguously with stable message IDs.
  Protects the first message, newest six messages, skill reads, errors, multimodal
  outputs, assistant text, users, and all tool-call records. Write/bash/task and
  other tools are never candidates. Deployments must preserve the read-only
  meaning of these built-in names.
  Host-stamped errors, partial results and unknown/malformed structured outcomes
  are protected even when LangChain's message status still says `success`.
- A result is shortened only when its keep probability is below 0.2. Preserves
  300 characters at each end plus an explicit omission note. Samples cannot
  prove that the omitted middle is irrelevant: **this is lossy**, and historical
  source contents may not be reproducible by reading again.
- Applies a batch only when estimated total context reduction reaches 10%.
  Sends at most eight candidates in one request, capped at 24,000 UTF-8 bytes
  including question instructions. Oversized candidates are skipped while later,
  smaller candidates can still fit in the same request. It does not repeatedly
  call Jev to process the entire conversation.
- Replaces result contents under their existing IDs in the **persisted graph
  state**. Disabling the plugin does not restore omitted text. It creates no
  transcript archive. Existing message metadata and call/result pairing remain.
  Replacements carry `jev_context_shortened: true` in their additional metadata,
  but no original-to-replacement hash mapping or detailed audit event is retained.
  Extension API 0.2.2 exposes `CompactionEvent` and observer registration, but no
  public event-emission API for this middleware; this plugin does not notify those
  observers through host internals. The marker identifies a shortened message but
  cannot reconstruct omitted facts or explain the classifier's decision.
- HTTP failures, missing/invalid answers, missing keys or insufficient reduction
  leave messages unchanged. The host's usual summarization remains available.
  Cancellation propagates. There are no automatic Jev retries or payload logs.
  For caught request/response failures, the
  `deerflow_extension_jev_context.compaction` logger emits a DEBUG message containing
  only the exception class. Enable that logger to diagnose failures; the plugin
  never includes exception text, tracebacks, URLs, credentials or conversation data
  in these diagnostics.
- After an attempt (including failure/no change), skips the next 16 logical model
  calls before trying again (attempts at calls 1, 18, 35, ...). This cooldown is
  checkpointed per thread, so a shared agent instance does not mix users' state. Already shortened results
  are not scored again. It does not intercept manual native compaction.
- Declares effective non-secret options through `release_policy_parameters()` so
  the host's assembly fingerprint changes when pruning policy changes. Neither
  the API key nor its environment variable name participates in that identity.

Optional deployment fields (all validated; unknown fields rejected):

| Field | Default | Meaning |
| --- | --- | --- |
| `api_key_env` | `TYPESAFE_API_KEY` | Environment variable name, never the key itself |
| `trigger_tokens` | `60000` | Approximate history tokens; choose for your main model |
| `preserve_recent_messages` | `6` | Protected suffix, minimum six |
| `min_result_chars` | `4000` | Minimum eligible result length |
| `min_calls_between_attempts` | `16` | Number of intervening calls to skip, including after failed attempts |
| `max_candidates` | `8` | Per-request candidate limit, maximum 16 |
| `keep_threshold` | `0.2` | Shorten only below this keep probability; maximum 0.5 |
| `min_reduction_ratio` | `0.1` | Minimum estimated reduction of the whole history |
| `timeout_seconds` | `8.0` | HTTP connect/read/write/pool timeout per phase |

## Prompt caches and cost

Shortening an old result changes the prompt prefix from that point onward and
can invalidate the following cached suffix. The stable prefix before the edit
can still be reused; subsequent calls can reuse the new prefix. Thresholds and
spacing reduce how often history is rewritten, but **do not guarantee a net
cost or latency saving**. Include Jev charges, the cache refill, cache discounts,
future turns and any extra rereads when measuring. Approximate tokens removed
are not money saved; providers' actual usage/cache counters are the evidence.

## Verify

From `backend/`:

```sh
uv run pytest tests/test_jev_context_extension.py
```

Coverage includes sync/async host isolation, checkpoint persistence, per-thread
cooldown, message pairing, protected content, malformed decisions, failure
fallback to real native summarization, cancellation and the plugin catalog.
The **Jev Plugin Package** CI workflow separately builds and installs the wheel,
then loads its declared entry point and registers its contributions through the
real host. `scripts/verify_package.py --installed-dir PATH` runs that check against
an isolated `uv pip install --no-deps --target PATH` installation; it does not
substitute a source-tree import for the installed distribution.

An opt-in synthetic smoke test calls real Jev and a caller-selected
OpenAI-compatible chat endpoint, without using real user transcripts:

```sh
export TEST_CHAT_BASE_URL='http://localhost:8000'
export TEST_CHAT_MODEL='your-test-model'
uv run python ../examples/deerflow-extension-jev-context/scripts/verify_live.py
```

This script deliberately sends no chat `Authorization` header. Use a test endpoint
that supports unauthenticated access; only Jev receives the Jev bearer token.
It compares the baseline/pruned prompt usage and checks retention of two recent
facts. This small smoke test is not a general relevance or cost benchmark.
