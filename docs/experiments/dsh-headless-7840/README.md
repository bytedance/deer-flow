# DSH headless experiment for DeerFlow RFC #7840

Can two host turns use one native DSH session after the first worker exits? The test reads a randomly generated synthetic supplier quote ID with the real DSH read tool. Its first reply acknowledges receipt without repeating the ID. After the file is removed, a second process retrieves the ID from the persisted tool history. A fresh session takes the same second prompt and finds no ID.

The caller uses DeerFlow's public `ModelTool` handler and `ToolContext` types. Tests construct the host contexts, assign different run UUIDs and keep the session binding in a local dictionary. The production Gateway constructs these contexts from its authenticated runtime. The experiment boots the real DSH CLI. Only the model is scripted. The read tool, loop, session log, serialization, process exit and restoration are real. See [the host wrapper](../../../backend/packages/harness/deerflow/extensions/plugin_tools.py).

## Reproduce

Use a POSIX host with Python 3.12 and a built DSH source checkout. The recorded environment used Darwin arm64, Python 3.12.14, Node 26.12.0 and DSH `0.2.2-rc.2` at `e8f7b93a344964de3dca1ace9e72b6e4d6de87cb`. DSH's source build instructions are in the [pinned upstream README](https://github.com/deepseek-ai/deepseek-harness/tree/e8f7b93a344964de3dca1ace9e72b6e4d6de87cb). The tests resolve Node from PATH and require both `apps/cli/lib/bin.js` and the built LLM library in that checkout.

From this experiment directory, set `DSH_CHECKOUT` to the absolute path of the build, then run:

```sh
export DSH_CHECKOUT=/absolute/path/to/deepseek-harness
PYTHONPATH=../../../backend/packages/extension-api PYTHONDONTWRITEBYTECODE=1 \
  SPIKE_EVIDENCE=1 python3.12 -m unittest -v test_runner
```

Every test allocates a temporary workspace, HOME and DSH_HOME. The child receives an explicit environment with a fixture-module path and no inherited model credentials. The test profile uses the built-in read-only preset, declines interactive approvals and writes an inspectable JSONL session log. Run it against synthetic inputs. A local DSH plugin executes with the privileges of its process. The PoC only supplies a trusted fixture and a fixed read request. A deployment needs its own execution boundary.

## Observations

Eight tests passed in two consecutive executions (9.530 s and 9.582 s). The second run's compact observations are in [evidence.json](evidence.json). The timing includes process launch, execution, shutdown and verification, with a scripted model on one host. The suite takes no dependency on a running Gateway, database, Redis, Docker or a model endpoint.

| Path | Observed result |
| --- | --- |
| Read, resume, fresh control | First process emits a matching read call and result. Second process recovers the exact original ID without a tool call. Fresh session cannot recover it. |
| In-turn model failure | DSH emits a final reason of `error` and exits 1. Host records `error`. |
| Unknown session | DSH emits an error before opening a session. Host records `error`. |
| Owner cancel during first step | SIGTERM exits 0 in the recorded run. Owner records `interrupted`. Before reopening, the durable turn already ends in `aborted`. After the next turn, the log contains `aborted`, then `completed`. |
| Unexpected process loss | Real Node process receives SIGKILL inside the fixture. It exits by signal 9 without a final frame. Host records `error`. |
| Deadline | A bounded wait ends in `timeout`. Return codes during startup/shutdown can vary. |
| Broken wire (synthetic producers) | Clean EOF with no final frame, invalid JSON and a mismatching final session ID each fail. |
| Descendant cleanup (synthetic producer) | A launcher exits while a helper holds stdout. The deadline stops the process group. Tests probe the PID and process group after each invocation and the helper PID in this case. |

`runner.py` reads NDJSON as it arrives. Its fixture envelope contains a caller-supplied run ID, a per-invocation sequence, an event kind and a payload. The run outcome is returned separately after the process has been reaped. Ordinary success requires the right session, a final reason of `completed` and exit status zero. The record size limit here is 1 MiB, including a final answer. Host task cancellation also runs the cleanup path. Tests cover explicit owner cancellation and same-group subprocesses. Parent death, detached processes, external tool side effects and distributed cleanup require different tests.

The synthetic observer receives tool payloads for assertions. It omits thinking frames. A production event sink would need owner scoping, redaction, bounded queues, replay IDs and storage policy. This directory has no route registration, default dependencies or deployment configuration.

For this two-turn workflow, retaining the native session was sufficient. A peer driver would need a workflow with requirements that the delegated approach cannot meet. The existing host wrapper has a 30-second call deadline and a 64 KiB result limit. The RFC and the experiment feedback are in [the issue discussion](https://github.com/bytedance/deer-flow/issues/7840).
