# Host model invocation for extensions

Extension API **0.2.4** adds an optional `ExtensionRuntimeDeps.model_invoker`.
An operator-authorized service can make an asynchronous, non-streaming text call
using DeerFlow's configured models. The host constructs the provider client and
returns plain data; the extension needs no provider credentials or LangChain dependency.

## Grant and route logical roles

Add `host_access` to the relevant entry in the operator-owned `config.yaml`:

```yaml
plugins:
  - name: classifier
    use: my_classifier:install
    host_access:
      model_invocation:
        roles:
          default: my-configured-model
          fast: my-small-model
        max_concurrency: 2
        timeout_seconds: 60
        max_input_chars: 262144
        max_output_chars: 65536
```

The mapping values are names from `models:`. Role names are deployment-defined;
an omitted request role selects `default`, which must be explicitly mapped.
An extension cannot request an arbitrary configured model name. No grant (or
`model_invocation: null`) means `deps.model_invoker is None`, preserving existing
services. `host_access` is separate from the extension-private `config` passed to
`install()` and cannot be edited through `extensions_config.json`.

Each successful installation owns its grant and concurrency budget. Multiple
services from that installation share the budget; another installation using
the same Python entry point does not inherit its grant. Grants and model
configuration are bound at service startup. As with all `plugins:` changes,
changing the grant, source, or extension model configuration requires a Gateway
restart. Startup failure revokes that service's handle. Shutdown revokes retained
handles and cancels callers before invoking its `stop()` method. Already-running
provider work retains its budget until it actually finishes; its result is discarded.

This capability follows the trusted extension model: installed Python code already
runs with Gateway privileges. It is not a sandbox or a per-user authorization API.
A service exposing an HTTP route must authorize callers and their input itself.

## Call from a service

```python
from deerflow_extension_api import (
    ModelInvocationRequest,
    ModelMessage,
    extension,
)


class Classifier:
    async def start(self, deps):
        self.invoker = deps.model_invoker

    async def stop(self):
        pass

    async def classify(self, text):
        if self.invoker is None:
            raise RuntimeError("Operator has not granted model invocation")
        result = await self.invoker.invoke(ModelInvocationRequest(
            messages=[ModelMessage("user", text)],
            purpose="classification",
            response_schema={
                "type": "object",
                "properties": {"label": {"enum": ["positive", "negative"]}},
                "required": ["label"],
                "additionalProperties": False,
            },
        ))
        return result.structured_output["label"]


@extension(api="0.2.4")
def install(registry, config):
    registry.service(Classifier())
```

Invoke from the service's event loop. Messages support `system`, `user`, and
`assistant` text, with 1–256 messages per call. `purpose` is an optional 1–128
character tracing label, not a prompt or an authorization selector. Do not put
secrets in it. The caller can shorten `timeout_seconds`, but cannot extend the
host timeout. Queueing, provider construction, schema-worker startup, and validation
count toward the same deadline. Cancellation propagates as `asyncio.CancelledError`.
Timeout and cancellation stop waiting promptly, but cannot terminate synchronous
provider threads. Both synchronous and asynchronous provider calls therefore keep
their concurrency and admission slots until the actual operation finishes. No
additional provider request starts if construction finishes after its caller left.
Configure provider-side timeouts as well: a stuck provider keeps its slot occupied.
Stopping a service does not wait for those provider operations to finish.

`response_schema` accepts inline JSON Schema Draft 2020-12 object schemas.
References (`$ref`, `$dynamicRef`, `$recursiveRef`) and other schema dialects are
rejected before dispatch; schema validation never fetches network resources.
The host adds a JSON-only instruction and validates the returned text locally,
so the contract does not depend on a provider's native structured-output feature.
Schema checking and response validation each run in a short-lived isolated Python
process using the host interpreter. This adds process startup overhead to structured
calls. Expensive regexes or schema combinations cannot block the Gateway event loop
or its GIL. On timeout/cancellation the host kills and reaps the child before
releasing admission (pipe cancellation is polled every 50 ms). No schema-worker
process is used for plain text calls.
Malformed JSON, non-finite numbers, and schema violations are explicit failures;
no partially populated success is returned. Batching, row-ID reconciliation,
file handling, and workflow-specific checks belong to the extension.

Successful results contain `content`, optional validated `structured_output`,
the resolved configured model name, and optional `ModelUsage` token counts.
Provider response metadata, framework messages, and exceptions are not exposed.
The standard model factory retains provider adaptation, configured RPM admission,
and tracing callbacks; invocation metadata attributes calls to their extension
source, logical role, and purpose.

## Failures and bounds

| Exception | Meaning |
| --- | --- |
| `ModelInvocationUnavailable` | Unsupported host, stopped capability, wrong event loop, or missing configured model |
| `ModelInvocationUnauthorized` | The requested logical role is not granted |
| `ModelInvocationFailed` | Invalid request, provider failure, timeout, unsupported response, or host limit exceeded |
| `ModelOutputValidationError` | Malformed JSON or schema mismatch; a subclass of `ModelInvocationFailed` |

All these derive from `ModelInvocationError`. Provider failures use a normalized
message without the original exception chain. Host deadline expiry reports
`Model invocation timed out`; a provider's own `TimeoutError` reports
`Model provider timed out`. A provider task that cancels itself reports
`ModelInvocationFailed("Model provider cancelled")`; it does not cancel the
extension's calling task. Normal caller cancellation remains
`asyncio.CancelledError`, rather than being converted to an ordinary failure.

Concurrency defaults to 2 (range 1–64), timeout to 60 seconds (maximum 600), and
input/output character limits to 262144/65536 (maximum 1048576 each). At most
`2 * max_concurrency` calls are admitted per installation, including running,
queued, and abandoned-but-still-running provider calls. Excess calls fail immediately
with `ModelInvocationFailed("Model invocation capacity exceeded")`, before payload
conversion or validation. Schema workers share the execution slots, so at most
`max_concurrency` children can run per installation. Input
counting includes the schema instruction. Output bounds apply to returned text
after generation; configure the underlying model's token limits to bound provider
generation costs. This is a per-installation, per-Gateway-process budget, not a
distributed quota. Provider SDK retries retain their configured behavior.

Tool calls, streaming, agent execution, and conversation persistence are outside
this capability. Jev/TypeSafe typed-decision workflows remain extension-owned;
`model_invoker` is the chat-style path for host-configured models.

The offline tests in `backend/tests/test_extension_model_invocation.py` cover the
classification success and failure cases, source isolation, shared admission,
timeouts, cancellation, limits, and lifecycle revocation without real API calls.
