# Agent tracing profiles

Agent settings includes a **Tracing** section with its own **Apply tracing**
button. Saving the Agent's name or instructions does not change tracing.

## Storage and deployment

Use `database.backend: sqlite` for processes sharing one local database or
`postgres` for independent Gateway replicas. Gateway startup and the embedded
Python client's first conversation initialize and migrate the application
database. Embedded initialization owns a temporary engine and leaves any
running Gateway's engine intact. The memory backend preserves environment-based tracing
and reports profile management as unavailable; it cannot persist profile edits.

Profiles, credential versions, Agent bindings, and resolved run snapshots use
the application database. Declared multi-instance deployments require the same
`DEER_FLOW_CREDENTIALS_KEY` on every replica. A single local instance can use
the automatically generated runtime-home key file without that environment
variable. Back up the key with the database. Keep old encryption
keys available while historical runs still need their snapshots.

## Configure and select a profile

Administrators create or edit profiles in **Manage tracing profiles**. A profile
can enable Arize, LangSmith, Langfuse, or a combination of distinct providers.
Authorize users by ID; an empty authorization list permits administrators only.
Users with Agent write permission select an authorized profile for their own
Agent without acquiring permission to read or manage its credentials.

Choose one mode:

| Mode | Behavior for new runs |
| --- | --- |
| Inherit | Freeze the deployment's enabled tracing providers and destinations. |
| Disabled | Suppress deployment tracing for this Agent's runs. |
| Configured | Export only through the selected profile's providers. |

Arize requires a Space ID, project, API key, and collector endpoint. The default
HTTP endpoint is `https://otlp.arize.com/v1/traces`. Select gRPC only when the
collector supports it, install `uv sync --extra tracing-grpc` in `backend/`
(or `pip install 'deerflow-harness[tracing-grpc]'`), and enter its corresponding
endpoint. HTTP export does not import the gRPC transport; other dependencies
such as `langgraph-api` can still install gRPC independently. A browser-console
URL is not necessarily an OTLP collector URL. See the
[Arize OTLP configuration reference](https://arize.com/docs/ax/integrations/opentelemetry/opentelemetry-arize-otel).

LangSmith requires an API endpoint, project, and API key. Its optional Workspace
ID is explicit; configured profiles never inherit the SDK's ambient workspace.
Langfuse requires its
base URL and public/secret key pair; configured profiles use its native
`/api/public/otel/v1/traces` endpoint with a private tracer provider. See
[Langfuse OTLP property mappings](https://langfuse.com/integrations/native/opentelemetry).

Credential inputs are write-only. Empty inputs retain the saved credential;
changing provider, endpoint, transport, or a Langfuse public key requires the
corresponding new credential. Responses contain presence flags, never the
credential or ciphertext. Agent package exports exclude tracing profiles and
bindings.

Managed profiles require HTTPS for public endpoints. Plain HTTP is accepted
only for `localhost`, loopback IPs, RFC 1918 IPv4 addresses, and IPv6 unique-local
addresses; saving one logs a warning without its URL or credentials. Internal
DNS names require HTTPS too: profile validation does not resolve names to decide
whether a destination is private. Use TLS beyond a trusted collector network.
Recovery applies the same managed-endpoint policy. Historical snapshots with
public plaintext endpoints are rejected rather than redirected; migrate the
profile to HTTPS and admit a new run.

## Activation and concurrency

Profile and binding writes require an `expected_revision`. Concurrent edits
return HTTP 409 instead of overwriting another user's change. The editor keeps
the unsaved draft so it can be copied before reopening the latest revision.

Every new admission reads the authoritative binding and profile. A shared
database fence orders profile activation against durable run/queue admission;
if the selected revision changes during admission, the request is rejected for
retry. Notifications and process caches are not the source of truth.

A run keeps an encrypted immutable snapshot. Persisted run data, checkpoints
and background-batch specifications contain references, not decrypted secrets.
Delegated work, queued occurrences, and resumptions recover that snapshot;
independent new runs resolve the current configuration. Missing snapshots,
decryption failures, and unavailable configuration authority reject execution
instead of falling back to a different destination.

**Configuration ready** means the database accepted the revision. **Delivery
unverified** remains visible because saving a setting does not prove that spans
arrived. Export failures are logged without payloads or credentials, use bounded
network calls, and do not change a successful Agent result. Check the target
project for the actual Agent, LLM and tool spans and their correlation metadata.

## Isolation and exporter lifetime

Configured providers use explicit credentials and private callback/exporter
instances. They do not switch process environment variables or replace the
global OpenTelemetry provider per request. OTLP requests exclude ambient OTEL
headers, disable redirects, and retain the deployment's proxy/TLS policy.

Destination and credential changes produce a new exporter lease. Active users
keep the previous lease; the last user closes it with a bounded queue drain.
Historical snapshots can recreate the corresponding exporter after a restart.
LangSmith child callbacks retain their parent's run, trace and dotted-order
identities when rebuilt for delegated or delayed work. The transported parent
context is bound to the frozen snapshot and destination; it does not restore
ambient callbacks or route through a different profile.

Monocle remains deployment-wide instrumentation. Gateway startup installs a
fixed sampler only when Monocle is enabled, before instrumenting, allowing inherited Monocle spans and
suppressing global spans for configured/disabled runs. If another global provider
prevents that guard from being installed, overrides are explicitly unavailable.
A frozen Monocle run also records a deployment-configuration fingerprint. A
worker with different Monocle destinations or credentials refuses recovery;
it cannot silently redirect that historical run. The fingerprint follows the
selected exporters' settings; unrelated cloud credentials do not invalidate
file or console recovery. Standard cloud SDK credential discovery remains
supported; an offline environment fingerprint does not establish the identity
returned by a metadata service or credential plugin.
New fingerprints use the `monocle-v2:` format. Historical unversioned
fingerprints still use their original strict comparison so unchanged old runs
remain recoverable. Their broader inputs cannot be reconstructed from the
stored digest; unrelated environment changes can still block those historical
runs. Deploy compatible workers together when introducing a new format; older
workers fail closed on snapshots they cannot validate.

Profile revisions and encrypted snapshots are retained for recovery. There is
no automatic history garbage collection; include these tables in database
capacity planning and backup retention.
Fully untraced durable runs retain an explicit frozen snapshot as well. Missing
references mean legacy/unmanaged execution, so omitting an empty snapshot could
let a queued or resumed run adopt subsequently enabled global tracing.

## API

| Route | Access |
| --- | --- |
| `GET /api/tracing/profiles` | Agent read; returns authorized profiles and management availability. |
| `POST /api/tracing/profiles` | Administrator with Agent write. |
| `PUT /api/tracing/profiles/{id}` | Administrator with Agent write and expected profile revision. |
| `GET /api/agents/{name}/tracing` | Agent owner with read; includes effective source, destinations and revision. |
| `PUT /api/agents/{name}/tracing` | Agent owner with write and expected binding revision. |

Custom-Agent routes require `agents_api.enabled: true`. The default Agent uses
the reserved name `lead_agent`. Credentials are never accepted through ordinary
Agent definition or package APIs.
