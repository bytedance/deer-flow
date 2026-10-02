# Agent run control for extensions

`deerflow_extension_api.AgentRuns` is an optional, host-bound capability for
creating and continuing **full Agent runs**. Runs use Gateway's normal admission,
Agent assembly, tools, middleware, checkpoints, run records, and cancellation.
It is distinct from `ModelInvoker`, which makes one bounded model invocation.
No workflow, team roster, delegation policy, or handoff scheduler is built in.

## Acquire the capability

Unified backend actions and model tools receive `context.agent_runs`. Contributed
Gateway routes can call `require_agent_runs(request)` without importing private
host modules. An unsupported host returns `None` from `resolve_agent_runs` and
raises `NotImplementedError` from the required variant.

```python
from deerflow_extension_api import ActionContext

async def begin(payload, context: ActionContext):
    runs = context.agent_runs
    if runs is None:
        raise RuntimeError("This host does not support Agent run control")
    thread_id = await runs.create_thread(assistant_id="researcher")
    run = await runs.start(
        thread_id=thread_id,
        input={"messages": [{"role": "user", "content": payload["prompt"]}]},
        idempotency_key=f"example.team:{payload['operation_id']}",
    )
    return {"thread_id": run.thread_id, "run_id": run.run_id}
```

Gateway binds the handle from authenticated request state. Plugins cannot pass a
user ID to select another principal. Session credentials and local auth-disabled
mode are supported. PAT and internal/channel credentials deliberately do not
receive retained run control: their revocation and owner delegation require a
separate grant contract. Embedded hosts may implement the protocol themselves.
The Gateway worker carries the capability only in its reserved runtime context;
untrusted request input cannot replace it. Direct embedded or subagent execution
does not acquire it automatically.

## Operations

- `create_thread(assistant_id="lead_agent", thread_id=None, metadata=None)` creates
  an owned thread. A caller-chosen ID is idempotent under the ordinary thread
  creation rules. Use a stable ID when recovering uncertain creation.
- `start(thread_id, input, context=None, idempotency_key=None)` starts or continues
  the Agent associated with that existing thread. Select a Custom Agent when
  creating the thread; changing `agent_name` or bootstrapping through `context`
  is rejected. Model/context options follow normal host validation. External
  system/developer messages are rejected. Concurrent starts conflict rather than
  implicitly interrupting each other.
- `get(thread_id, run_id)` returns an `AgentRun` with IDs, status, originating
  assistant, and stop reason. It follows the normal owner-scoped run API.
- `wait(thread_id, run_id, timeout=60)` polls until the run leaves pending/running.
  The timeout must be positive and at most 3600 seconds. Timeout or cancellation
  of the waiting task leaves the Agent run active; call `cancel` explicitly.
- `get_state(thread_id)` returns the latest normal thread-state projection,
  including values, next nodes and interrupt information. This is **mutable
  thread state**, not a snapshot permanently associated with a run ID.
- `resume(thread_id, resume, idempotency_key=None)` submits an explicit LangGraph
  interrupt response through ordinary admission. It never decides whether a
  pending action should be approved.
- `cancel(thread_id, run_id)` requests the normal interrupt action and preserves
  checkpoints. A remote worker may acknowledge before cancellation completes;
  use `wait`/`get` to observe the final status.

Run operations use keyword-only arguments. Input and context are detached JSON objects,
limited to 256 KiB each. Idempotency keys are 1–200 characters. Action/tool handles
automatically scope keys to the registered plugin namespace; contributed routes
use `require_agent_runs(request).for_plugin("example.team")` for the same isolation.
A scoped handle cannot be rebound to another plugin. Gateway additionally scopes
keys to the user and thread. Callers may use colons in their local keys.
Reusing a key with different input is a conflict under existing admission rules.
`AgentRunError.status_code` exposes normal HTTP-equivalent rejection categories,
including denied permissions, missing resources, conflicts, and invalid input.
Unified backend actions preserve these statuses in their HTTP response.

`wait` polls immediately, then backs off from 0.25 seconds to a four-second cap.
The caller's timeout bounds the entire wait, including authorization and polling.

A completed graph invocation can have run status `success` while paused at a
LangGraph interrupt. This matches existing Gateway semantics: inspect the returned
thread state's `next`/`interrupts` before treating success as completed work.
Do not automatically resume or approve merely because a wait returned.

## Service-owned handoffs and lifetime

A trusted plugin service may retain a handle handed to it by an authenticated
action/tool and use it after that handler returns. For an A-to-B handoff, wait
for A, inspect its state and pending interrupts, apply the plugin's policy, then
create B's thread and pass the selected result as B's human input. The plugin
owns its task lifecycle, supervision, concurrency limits, retry policy, and any
durable workflow state. Action/tool handlers retain their existing 30-second
execution limit; long work belongs in a supervised plugin service.

Handles contain no cookies or bearer tokens. They delegate the original user's
permission ceiling for this process lifetime rather than storing the request.
Every operation reloads the session user, rejects deletion/password-reset token
version changes or incomplete setup, intersects current route permissions with
the original grant, and checks thread ownership. Agent/model admission uses that
fresh user. Local auth-disabled grants stop working when that mode is disabled.
Gateway revokes all handles before draining runs at shutdown.

The handle is not serializable and cannot survive a restart. Persist thread/run
IDs and workflow progress, then reacquire a capability from a newly authenticated
request to continue. Existing run/checkpoint durability and orphan recovery remain
the host's responsibility. The original route-permission ceiling cannot widen; Agent/model/tool policy
still evaluates the current user. Do not expose a retained handle to other users.
