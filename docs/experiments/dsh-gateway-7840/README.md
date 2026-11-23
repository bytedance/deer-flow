# A coding conversation routed by the DeerFlow Gateway

This local experiment follows [the use case in RFC #7840](https://github.com/bytedance/deer-flow/issues/7840#issuecomment-7090744165). It starts the actual FastAPI Gateway with its normal lifespan, a temporary SQLite database, single-user mode and offline model fixtures. Requests use an in-process HTTP client. Each DSH turn runs the built upstream CLI in a new OS process. No model credentials are required.

## Reproduce

From the DeerFlow worktree root on a POSIX host, with Node on PATH, uv and the built DSH checkout used in [the headless baseline](../dsh-headless-7840/README.md):

```sh
DSH_CHECKOUT=/absolute/path/to/deepseek-harness sh docs/experiments/dsh-gateway-7840/check.sh
```

The script uses the backend lockfile. To use an existing environment containing its dependencies, set `PROBE_PYTHON` to the absolute path of that Python executable. Append `-k dsh-shell` to run only the case where DSH executes the repository test. This case requires a host that can launch the upstream DSH shell sandbox with the workspace-write preset and unattended approvals. The toy Git repository, logs and session files use pytest temporary directories.

## What goes through the Gateway

1. Clients call the existing `POST /api/threads` endpoint. A coding thread sets the synthetic assistant ID `dsh-coding`. A native thread uses the default assistant.
2. A turn uses a test-only `POST /api/experiment/threads/{thread_id}/turn` route with a single prompt. The handler looks up the stored assistant on the thread. The native branch delegates to the existing `wait_run` handler. Its test checks the actual AI reply and queries the regular run-list endpoint for a successful run.
3. For DSH, the handler starts the CLI with the thread's previous session ID, if present. DSH owns its JSONL log. Its new process receives only the current prompt. The single Gateway keeps the session ID in memory by thread incarnation.

The models script a known edit and the expected tool decisions. The repository starts with a subtraction bug in an addition function. A passing regression test generates a fresh random receipt. The first turn acknowledges success without returning that receipt. The resumed DSH process must recover the exact receipt without a tool call. A fresh DSH conversation, with the same working directory and follow-up prompt, must find nothing. An interleaved native conversation must complete through DeerFlow.

## Recorded on November 23, 2026

DeerFlow worktree HEAD `11ddcf726`, DSH `e8f7b93a344964de3dca1ace9e72b6e4d6de87cb`, Darwin arm64, Node 26.12.0 and Python 3.12.14.

| Check | Observation |
| --- | --- |
| Native conversation | Passed. The Gateway returned the fixture model's AI reply, recorded a successful native run and launched zero DSH processes. |
| DSH edit, host-run test and session recovery | Passed. The test failed before the edit. DSH wrote the one-line fix and the host ran the passing test. DSH read the random receipt using its native read tool. After deletion of the receipt file and exit of the process, a new process recovered the exact receipt from the same session. The native conversation and fresh DSH negative control both behaved as expected. |
| DSH edit and DSH-run test, ordinary macOS terminal | The contributor reported `1 passed` for `-k dsh-shell`. The test checks that DSH edits the file and runs the regression test with its native bash tool. After the first process exits and a separate native DeerFlow turn completes, a new process reopens the same DSH session and returns the exact receipt from bash output without a tool call. A fresh session given the same prompt finds no receipt. |
| Same DSH shell check, managed macOS environment | DSH wrote the fix, but its bash tool returned `SANDBOX_UNAVAILABLE` with `sandbox-exec: sandbox_apply: Operation not permitted`. The host independently verified the expected diff and a passing regression test. |
| Existing headless suite | All eight tests passed in the same environment. |

This shows that the example can route by conversation and recover DSH-owned history across process exits with a live Gateway. It does not measure coding quality or business value. The opt-in route is registered only by the test. The DSH path has no native DeerFlow run record, and the experiment does not exercise Gateway restart, multi-worker admission, user isolation, SSE, approval or cancellation through that route. The assistant ID is a laboratory selector. A production design would need to preserve the distinction between the user's assistant and its execution harness.
