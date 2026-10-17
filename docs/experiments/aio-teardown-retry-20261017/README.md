# AIO teardown retry verification

## Scope and revisions

This report verifies recovery after a failed AIO stop, independently of the
opt-in prewarming work in [#6998](https://github.com/bytedance/deer-flow/pull/6998).
The existing behavior also reproduces without prewarming enabled or installed.

- Baseline: `34316550dffbe8fbaed5678a6be87c5d3c65155b`.
- Initial teardown fix and Docker probe revision: `997cb9bc30a0aec5804d1cd55bda3b87f36f5c31`.
- Environment: macOS arm64, Python 3.12.13, Docker client/server 29.7.2.
- Image: `enterprise-public-cn-beijing.cr.volces.com/vefaas-public/all-in-one-sandbox:1.11.0`.
- Local Docker image ID: `sha256:6328d7fd2f0ff0b4c147c3d05b3df1ce331f4a482eb6e550ecd64ed1fcf906e7`
  (an image ID, not a portable registry manifest digest).

[evidence.json](evidence.json) contains allowlisted observations and production
source hashes. Host paths, account names, random container prefixes, container
IDs, Pod identifiers, and raw exception messages are omitted. The local raw
observations were checked against the production source hashes from that initial
probe revision.

## Method

[probe.py](probe.py) constructs a complete typed production AppConfig and uses
the real AioSandboxProvider. Each case has a separate process, home directory,
and randomly generated container prefix. No model is configured or called.

The fault is **one injected TimeoutExpired before stopping a particular test
container**. This leaves a real container running. Docker inspection, subsequent
stops, and cleanup use the real backend. This is controlled fault injection,
not a claim about production failure frequency or performance.

The replacement case removes the old container after the injected failure,
creates a new generation under the same logical ID, and checks whether retry
preserves it. The shutdown cases also include an unaffected resource, so a
failure cannot silently skip the rest of the cleanup.

## Observed results

| Scenario | Baseline | Candidate |
| --- | --- | --- |
| Explicit destroy | First stop raises; second destroy returns True without another stop; target still exists | Generation is fenced; second destroy stops it; absence confirmed; record retired |
| Active shutdown failure | First call reports success; failed container remains; singleton detached; second call does nothing | First call raises and retains provider; second call retries only the failed resource and completes |
| Warm shutdown failure | Failed warm resource loses tracking; second call does nothing | Failed warm resource remains retryable and is removed on the second call |
| Shutdown with unfinished execution | Failed resource remains after both calls | Execution binding survives the first failure; full shutdown retry still removes the resource |
| Replacement under the same logical ID | Second destroy reports True without identifying the old cleanup intent | Retry returns False and preserves the observed replacement and the old fence |

All five candidate scenarios matched their expected observations. Explicit
recovery makes two main-container stop attempts; partial shutdown recovery
makes three in total: one failure, one unaffected resource, one retry. The
replacement retry makes no additional stop attempt against the replacement.
All owned test containers were removed during final probe cleanup.

Normalized observations from the explicit case (not verbatim raw logs):

```text
baseline: first=TimeoutExpired; after_first: absent=false, quarantined=false, stops=1
baseline: second=True;        after_second: absent=false, quarantined=false, stops=1
candidate: first=TimeoutExpired; after_first: absent=false, quarantined=true, stops=1
candidate: second=True;        after_second: absent=true, quarantined=false, stops=2
```

## Related Docker error format

Real Docker 29.7.2 returned this exact missing-network shape (resource name
normalized here):

```text
Error response from daemon: network <network-name> not found
exit status 1
```

The strict parser previously rejected the second line and prevented cleanup
completion even after the container was absent. Three new regressions failed
before the parser fix. The fix accepts only this optional terminal line;
wrong targets, different exit codes, and additional diagnostics remain errors.

## Initial teardown verification

| Check | Result |
| --- | --- |
| Seven relevant offline test files | 633 passed, 3 live tests deselected |
| Strict blocking-I/O suite | 256 passed, 1 skipped |
| `make lint` | Passed, including Ruff formatting |
| Final standard four-shard `make test` | 32,407 passed, 564 skipped, **3 failed**, exit code 2 |
| Clean baseline standard `make test` | 32,384 passed, 565 skipped, **3 failed** |

The final full-suite failures match the baseline: two frontend/AGENTS.md
hard-budget assertions (32,805 bytes against 32,768) and the native Cargo
acceptance case `unit-with-empty-doc`, affected by inherited GNU Make jobserver
flags. The full suite is **not green**. Those files are unchanged by this fix.

An earlier full run also had one unchanged Docker orphan test miss `multi00`.
Its isolated rerun passed all three tests; the baseline's two-shard rerun also
passed; the final full run did not repeat the failure. Shared-prefix cleanup
between shards is a possible explanation, not a proven diagnosis.

An additional restricted-network live test failed with HTTPS CONNECT 403
(281 passed, 1 failed in that invocation). It is not counted as successful
network acceptance, and no network policy was relaxed. The offline selection
and the controlled Docker teardown probes above do not require external traffic.

## Reproduction

Prepare the selected checkout's own backend virtual environment with
`uv sync --locked --extra postgres` and make the stated AIO image available.
Run the same probe separately against the baseline and the fix, using each
checkout's interpreter. Keep the probe path absolute when selecting a different
checkout:

```bash
REPO_ROOT="$PWD"
PROBE="$REPO_ROOT/docs/experiments/aio-teardown-retry-20261017/probe.py"
RESULTS_DIR="$(mktemp -d)"
"$REPO_ROOT/backend/.venv/bin/python" "$PROBE" \
  --root "$REPO_ROOT" --output "$RESULTS_DIR"
```

`--case explicit`, `shutdown-active`, `shutdown-warm`, `shutdown-held`, or
`replacement` runs one scenario. A zero exit means the probe ran and its final
container cleanup completed; compare the observations above to determine
behavioral acceptance. Generated outputs are local raw diagnostics and can
contain paths and resource IDs; this committed report includes only allowlisted
observations.

The scoped offline command, from `backend/`, was:

```bash
uv run --no-sync pytest -m 'not live' -q --tb=short \
  tests/test_aio_sandbox_provider.py tests/test_sandbox_orphan_reconciliation.py \
  tests/test_sandbox_provider_lifecycle.py tests/test_sandbox_quarantine.py \
  tests/test_sandbox_leases.py tests/test_sandbox_lease_rebind_cancellation.py \
  tests/test_aio_sandbox_local_backend.py
```

Full backend tests used the standard `make test` with Python 3.12 and Node 24 on
PATH, `NO_COLOR` unset, and no `UV_NO_SYNC` override. No acceptance assertions
were weakened. Kubernetes, Apple Container, and Redis multi-Gateway deployments
were not exercised as live environments; their contracts retain existing unit
coverage. No new authorization, prewarming, or configuration behavior is claimed.

## Replacement admission follow-up

[Review #5557122845](https://github.com/bytedance/deer-flow/pull/7001#discussion_r4302123092)
identified a regression in the initial fix: after a failed stop, a healthy new
generation with the same logical ID could be adopted into the warm pool, then
promoted without clearing the old in-memory retry marker. Acquisition returned
an ID, but cached client lookup failed; the execution lease manager therefore
raised `SandboxClientUnavailableError`.

Warm-to-active promotion now clears that obsolete marker in the same metadata
critical section as client registration, after reuse and ownership checks. If
the warm entry changes during those checks, promotion defers rather than
admitting an unvalidated entry. Generation-bound quarantine records are retained.

Eight offline regressions cover:

- Direct discovery and orphan adoption, each through the provider and the real
  execution lease manager. All four cases also release and reacquire the new
  generation and verify that no extra stop occurs.
- Retaining the retry fence for quarantined and unknown generations.
- Retaining that fence when either unsafe entry replaces the validated warm
  entry during ownership publication.

Before the follow-up, four cases failed and four passed; afterward all eight
passed. These tests use real provider, quarantine and lease-manager methods with
mocked backend and SDK transport. The original Docker results above remain tied
to their recorded revision; Docker was unavailable for this follow-up.

Follow-up validation against the working tree based on `673304c7`:

| Check | Result |
| --- | --- |
| Eight new regression cases | 8 passed |
| Seven relevant offline files | 641 passed, 3 live tests deselected |
| Strict blocking-I/O suite, before and after | 256 passed, 1 skipped in each run |
| `make format`, `make lint`, frontend `pnpm check` | Passed |
| Agent guidance size check | 0 errors, 0 warnings |
| Standard `make test`, before follow-up | 32,520 passed, 565 skipped, 1 failed |
| Standard `make test`, after follow-up | 32,528 passed, 565 skipped, 1 failed |

Both full runs fail only the unchanged native Cargo acceptance case
`unit-with-empty-doc`, already observed in the initial local verification. Its
isolated run without inherited Make flags passes. The full local suite is not
green; there are no additional failures after the follow-up.
