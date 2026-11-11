# Sandbox

## Sandbox Mode

DeerFlow supports multiple sandbox execution modes:
- **Local Execution** (runs sandbox code directly on the host machine)
- **Docker Execution** (runs sandbox code in isolated Docker containers)
- **Docker Execution with Kubernetes** (runs sandbox code in Kubernetes pods via provisioner service)

The optional [Tenki provider](../../backend/packages/harness/deerflow/community/tenki/README.md)
retains failed termination handles for retry and rejects late acquisitions after
reset or shutdown. If shutdown reports outstanding work, retry after its SDK
workers finish or the remote service recovers.
At process exit, outstanding cleanup is logged without an exception traceback.
                                   
In Local Execution, `glob` and `grep` can search the skills root (default
`/mnt/skills`) across its mounted categories. Patterns stay relative to that
root, and one result limit covers all categories. User isolation, disabled-skill
filtering and read-only mounts still apply. Configured category mounts such as
`build` or `logs` remain searchable; ignore rules apply inside each mount. A broken
category mount stops the root search, and the Gateway warning log identifies its
virtual path.

Sandbox references in conversation state are server-owned. External run and
thread-state APIs reject caller-supplied `sandbox` values; when restoring a
checkpoint, the runtime resolves the reference against the authenticated user
and thread before a tool can reuse it. A missing runtime thread ID raises an
error even when the referenced sandbox is cached.

When host Bash is enabled for Local Execution, DeerFlow starts OS detection with `uname -s`, then uses `sw_vers` on Darwin. On Linux, it reads host system files such as `/etc/os-release` only when the active sandbox policy permits it. Host filesystem path checks still apply; after a blocked path, the agent is directed to use a permitted command-only probe or virtual path instead of repeating the rejected command.

For Docker development and production, service startup follows the configured
sandbox mode, including when the `sandbox:` header or `use` field has a trailing
YAML comment. With `AioSandboxProvider`, an omitted `provisioner_url`, an empty
string (`""` or `''`), or YAML null (`null`, `~`, or a blank value), including
trailing comments, selects `aio`: `provisioner` is not started and the Docker
socket overlay is enabled. This grants the gateway host root-equivalent Docker
access; see the [sandbox security notes](../../backend/docs/CONFIGURATION.md#sandbox-isolation-and-the-docker-socket-dood).
A nonempty URL selects provisioner mode without that overlay. Quoted `"null"`
and `"~"` are nonempty strings, not YAML nulls; mode detection does not validate
URLs. The default local provider never enables the socket overlay.

Local AIO sandbox port allocation stops at TCP port 65535. If the remaining
ports from the configured starting port are occupied, allocation reports
that no port is available instead of attempting an out-of-range bind.
In open network mode, a missing Docker/Apple Container CLI or a permission-denied
CLI startup returns the reserved port while reporting the original error, so
repeated attempts do not exhaust the port range. Restricted network creation
returns its reservation when no proxy could have been created or after confirming
that the proxy has been removed, including when later network cleanup fails.
An uncertain proxy keeps its reservation in the existing local cleanup ledger.
Later creation attempts do not automatically reclaim it. The reservation remains
until the existing ownership-fenced absent teardown completes or the backend
process restarts. This bookkeeping does not provide durable recovery across
backend instances.

AIO teardown failures retain a generation-bound cleanup record. Partial shutdown
reports failure and can be retried; retries verify the runtime identity and absence
before completing cleanup. Healthy replacements with the same logical ID remain
reusable, including after background recovery into the warm pool.

See the [Sandbox Configuration Guide](../../backend/docs/CONFIGURATION.md#sandbox) to configure your preferred mode. For absolute skills paths and custom directory mappings on Linux, macOS, Windows, WSL, or a Docker Gateway, see [Skills and sandbox paths](../../backend/docs/CONFIGURATION.md#skills-and-sandbox-paths).

Managed async AIO runs can opt into bounded sandbox prewarming to overlap startup
with the first model call. Direct SDK graphs keep lazy acquisition. It defaults off; see the guide and
[sandbox benchmarks](../../backend/scripts/benchmark/sandbox/README.md) before enabling it on a shared host.

Remote directory listings report traversal failures (for example, unreadable
directories) as incomplete results, even when no entries were returned. A
missing start path is reported separately as “Directory not found.”

The optional [Tenki cloud sandbox provider](../../backend/packages/harness/deerflow/community/tenki/README.md)
uses Tenki SDK 1.4.0 or newer. Timed-out commands preserve partial output and
report `Exit Code: 124`; unsuccessful health checks cannot reclaim a warm sandbox.
Health probes tolerate login-shell output around the `ok` line, and failures log
the sandbox ID and probe output before replacing the sandbox.

The optional OpenSandbox provider mirrors generated output files to local thread
storage at turn completion for Gateway previews and downloads; see its
[synchronization limits and failure behavior](../../backend/packages/harness/deerflow/community/opensandbox/README.md#lifecycle-and-contract).
An invalid UTF-8 filename is skipped without blocking other outputs, and
same-size content edits are still copied on release.
Outputs with case- or Unicode-equivalent file or directory names are skipped
before copying, and aliases of existing local paths are rejected, preserving
previous complete copies.

The [sandbox benchmark](../../backend/scripts/benchmark/sandbox/README.md#opensandbox)
also supports OpenSandbox cold acquisition, warm reuse and concurrent scopes,
using the configured service connection and reporting unconfirmed cleanup as a
failed run. Live runs require a disposable OpenSandbox service and runtime home.

BoxLite shutdown rejects late VM registration and keeps its SDK loop open while
in-flight acquisitions finish. If they cannot drain within five seconds,
shutdown fails with resources still owned and can be retried.
Startup-recovered BoxLite VMs use the same private async loop as newly created
VMs for health checks, commands, and shutdown. Recovery skips boxes removed
after discovery without creating replacement VMs.

Successful `read_file` calls treat a JSON document's `error` field as file data,
not a failure of the read tool. This keeps receipts accurate when inspecting
saved API error responses and avoids blocking later reads when the optional
`tool_progress` guard is enabled. Actual read failures and output truncation
still retain their error or partial-result status.

## Sandbox & File System

AIO runs commands from independent subagents concurrently, including Lark CLI
and skill commands with per-call environment variables. Commands within one
subagent stay ordered, and each environment-bearing call uses a fresh session.
Environment-bearing calls share a per-sandbox Bash admission limit, configured
by `sandbox.environment.AIO_BASH_MAX_SESSIONS` (positive integer, default `50`).
Excess calls wait without creating a session and can be cancelled while waiting;
the slot is retained through session cleanup. This pool is separate from
`MAX_SHELL_SESSIONS`. Docker reuse checks the persisted container environment;
K8s reuse checks the provisioner's Pod-reported Bash capacity. Upgrade the
provisioner with the Gateway: missing capacity metadata blocks admission.
Cancellation remains routed to the running command while scope release or
sandbox close waits for it to finish and clean up.
Scope release waits for in-flight execution and cleanup without a separate drain
deadline. Allow for the remaining command timeout (600 seconds by default), plus
session/transport/recovery/cleanup time when setting operator-facing release
budgets; the HTTP cleanup timeout does not bound the preceding lock wait.

With local host bash enabled, the path guard permits division in simple shell
arithmetic and recognized single-quoted Python, Node.js and Perl programs.
Variable-built paths remain checked even when the filename is numeric or a
glob precedes the slash. This is a best-effort guard; host filesystem isolation
requires an isolated sandbox provider.

Local `grep` reports file permission and I/O failures as errors rather than
successful empty or partial searches. Binary files and files that disappear
during scanning remain excluded.

AIO sandboxes recycle after an uncertain implicit-shell outcome or session
creation; a confirmed `hard_timeout` remains eligible for warm reuse. The Gateway
waits for all execution and upload holders to finish, including command-session
cleanup. An in-flight session creation alone does not trigger recycling or
interrupt a concurrent run. Before recycling, the Gateway records the container ID or Pod UID under
`{DEER_FLOW_HOME}/sandbox-quarantine`. These records survive failed stops and
Gateway restarts. Gateways sharing AIO containers must share this home in
addition to their ownership store. A new runtime instance can reuse the thread's
sandbox ID; an unverifiable generation fails closed against existing records.
Before recreating a quarantined ID, the Gateway retires its old records only
after the backend confirms that no container or Pod remains, while holding the
normal teardown fences. This also permits recovery when a runtime cannot report
a generation. If a partial deletion leaves a container or a Pod behind, the
Gateway inspects it independently of health checks and Service availability,
then retries cleanup only for a quarantined generation. A replacement generation
keeps its resources. A delete acknowledgement or failed health check is
insufficient to clear the records.
Recovery also clears leftover local proxy and network resources before recreation.

Lark broker provisioning requires confirmed capabilities. Probe failures cannot
select credential mounts or overwrite a known broker requirement. Update the
Gateway and provisioner together: the provisioner reports each Pod's actual
broker mode, and incompatible Pods are replaced through the normal ownership
fences before reuse. Lark commands use that admitted mode.
If an older provisioner omits a Pod's broker mode, the Gateway refuses reuse
with an explicit upgrade error and preserves the Pod. An omitted mode is not
evidence that the existing runtime needs replacement.
Capability probes share one request per provisioner and briefly back off after
failure. A Pod mode that contradicts the cache triggers a fresh observation
before replacement. Failed admission after creation uses ownership-fenced cleanup.
A create request whose lark provisioning mode conflicts with the provisioner's
current configuration is marked as a capability refresh; the Gateway drops its
cached observation so the next acquire re-probes instead of repeating the
failure until the cache entry expires.
On sandboxes without an attested broker mode, lark-cli
commands fail with an explicit unverified-mode error instead of running
against an unauthenticated profile.

Host-externalized tool outputs use the Gateway's normal file-creation permissions.
Restoring those outputs from shared blob storage applies the recovering Gateway's
creation policy too, including its umask and any inherited default ACL.
Host and sandbox outputs use deterministic filenames hashed from the raw tool
call ID and output content. Missing, colliding, or oversized IDs cannot overwrite
different output or make the filename too long; identical output can reuse its path.
Host and remote sandbox persistence failures, including invalid Unicode during filename
hashing, use the configured inline fallback.
`tool_output` character/count budgets, including per-tool overrides, require
non-negative integers; YAML booleans are rejected rather than treated as 0 or 1.
An explicit zero per-tool override disables externalization while preserving
any positive global fallback limit.
Structured JSON tool results follow these budgets, including results mixed with
media; externalization keeps the full JSON available through a file reference.
Superseded `write_file` payload elision is opt-in because enabling it rewrites
earlier model-request prefixes when later file actions supersede a write.
MindIE renders JSON tool results as escaped text, with configured tool exemptions
preserved. Enabled PII redaction scans nested JSON keys and values before rendering.
Mounted sandboxes running under another UID need read access through the shared
storage permissions. An unclean shutdown can leave `.tool-output-*.tmp` files in
`tool_output.storage_subdir` (default `.tool-results`) under thread outputs.
Remove leftovers during thread-data maintenance with all Gateway writers stopped,
or when deleting the corresponding inactive thread's data.

Workspace change summaries scan up to 2,000 files by default, in sorted order:
the workspace root first, then outputs. A workspace that alone reaches the limit
leaves outputs unscanned. When a scan is incomplete, files missing from that
partial snapshot are not reported as created or deleted. Changes to files
observed in both snapshots are still reported, and the summary is marked as
truncated; if no change can be established, no summary is recorded.

Output-delivery verification uses these same snapshots. When the pre-run scan
is truncated, genuinely new outputs can be omitted even if the post-run scan
sees them. If no output changes can be established, the run does not fail with
"Artifact delivery incomplete". If the pre-run scan was truncated, its persisted
`run.delivery` receipt records `verification_skipped: "truncated_pre_run_snapshot"`
instead of an output-verification verdict. This distinguishes an incomplete scan
from a complete scan with no produced outputs; it does not prove that no outputs
were produced. Outputs modified and observed in both snapshots still participate
in that check.

`E2BSandboxProvider` uses `wait` as its default overflow policy. It waits for
`acquire_timeout`, then fails the agent turn. DeerFlow does not retry the turn
automatically. Clients can use the structured error to schedule a retry.

Use `burst` with `burst_limit` to permit bounded extra VMs. The `wait` and
`reject` policies use only `replicas`. The `reject` policy can remove one warm
VM before it returns an error.

With in-memory ownership, `replicas` limits one Gateway process. With Redis
ownership, E2B shares one capacity Hash between workers using the same
`sandbox.ownership.key_prefix`; `replicas` (plus a configured burst) is then a
deployment-wide hard limit. Use one unique prefix and the same effective limit
per deployment. To change the limit, stop its Gateways, delete the capacity
Hash, and restart; mismatched workers fail closed.

The Hash counts remote VMs and in-flight creates, repairs interrupted creates
from E2B metadata, grace-protects stale inventory omissions, and blocks new
creates while Redis or initial inventory is unavailable. Run Redis with persistence, non-evicting memory, and HA.

E2B reconciliation renews active VMs with a positive timeout covering its
configured cadence, even when `idle_timeout` is zero or shorter than that
cadence. Warm VMs retain the configured idle-timeout behavior. Expired local
warm entries do not directly free shared capacity: remote inventory must
confirm disappearance through the existing grace period first.
Active renewal completes before release sets the warm timeout, so a concurrent
maintenance pass cannot extend an idle VM's lifetime. Warm-entry cleanup also
preserves ownership acquired by a new request during the sweep.
Ownership heartbeats remain independent of slow E2B timeout requests, preventing
control-plane delays from making active sandbox leases expire.

E2B snapshots `skills.container_path` when the provider starts and includes the
canonical root in its thread identity, warm-pool seed, and remote metadata. A
VM created for a different root is never adopted; reconciliation reaps it after
the configured grace period once no live peer owns it. Restart the Gateway after
changing the root.

E2B acquisition uses a bounded executor. Waiting acquisitions do not use the
default asyncio executor.

When an E2B sandbox expires between conversation turns, its replacement restores
the same user's saved thread files from `workspace`, `uploads`, `outputs`, and
the ACP workspace before tools can use it. Live sandbox reuse does not overwrite
remote files with older saved copies. Restoration failure or an exceeded upload
limit rejects the new sandbox. Transient failures may succeed on a later attempt.
Capacity breaches report the resource tree and exceeded cap: 100 MiB per file,
2,000 files / 512 MiB per tree, and 2,000 files / 512 MiB across the creation pass.
An operator must archive or remove unneeded files from the Gateway's persisted
thread directories to fit those limits before retrying; retrying unchanged data
cannot resolve a capacity breach. Deleting only the remote copies is insufficient.
Other restoration errors identify the resource tree and cause category; Gateway
logs retain the underlying exception for diagnosis.
Recovery requires the Gateway's persisted thread directories to remain available;
files that never synchronized before the VM disappeared cannot be recovered.
The existing release sync saves workspace/output files but does not mirror file
deletions, so saved copies of remotely deleted files can reappear on recreation.

Each E2B mount upload pass accepts at most 512 MiB and 2,000 files. The pass
also has a cooperative 120-second deadline. Thread restoration runs first and
shares these limits with skill projections and configured mounts. The provider
checks the deadline before each mount and during directory preflight. The deadline
stops new file uploads after it expires. It does not interrupt active filesystem
or E2B SDK calls.

An E2B VM keeps its slot until E2B confirms destruction. This rule covers
create and reclaim operations. Discovery can find a VM from another Gateway.
Shutdown closes an unowned discovery client without destroying its VM.
Release stops counting a transition when the VM enters the warm pool.
Shutdown races retry remote cleanup after a transient kill failure.
Reset destroys tracked active and warm E2B VMs. The old provider instance
cannot accept new acquisitions.

DeerFlow doesn't just *talk* about doing things. It has its own computer.

Each task gets its own execution environment with a full filesystem view — skills, workspace, uploads, outputs. The agent reads, writes, and edits files. It can view images and, when configured safely, execute shell commands.

The read-before-write gate ties each read mark to that `read_file` call's result, including custom tools returning multi-message `Command` updates. An unrelated result cannot authorize a write after a failed read or hide a successful read.

Deeply nested JSON returned by tools, including `read_file`, keeps its original content when result analysis reaches the JSON parser's depth limit. Explicit tool failures remain errors with an unknown category when depth prevents analysis.
Tool-call arguments and clarification options nested past the JSON parser's recursion limit are treated as unusable opaque values instead of aborting the run.

On Linux and macOS, local sandbox `write_file` replacements and `str_replace` stage complete text before replacing the destination, so write, flush or publication errors retain the previous file. Existing write access is checked; ownership, permission bits, ACLs and extended attributes are transferred before writing staging content. Failure to transfer metadata aborts the save. Successful revisions get a fresh modification time, including empty saves; source-descriptor cleanup errors are warnings and do not change the save result. Files with set-id bits, macOS file flags or content-bound Linux privilege attributes are refused unchanged. Replacement requires parent-directory write access and publishes a new inode; other hard links retain the previous version. Symlinks follow the existing path-validation rules. Append writes, other host platforms (including Windows), shell writes and remote providers keep their existing behavior. This is not a concurrent-writer or power-loss recovery guarantee.

Loop warnings let agents save collected results before their final answer. If the save is blocked by the read-before-write gate, the agent may read the target file and retry the save once. A looping or stopped tool must be replaced by an available alternative; if no permitted save path exists or the retry fails, the final answer includes the collected results and reports that the file was not saved. When `present_files` is available, the warning also asks the agent to present the files it already created in `/mnt/user-data/outputs` before answering, so finished outputs are delivered. Recovery calls still count toward the loop limits, and a hard stop prevents further tool execution.

Ranged `read_file` calls count lines the same way on every sandbox provider: a line ends only at a newline. On E2B, BoxLite, Tenki, and OpenSandbox, a file with bare carriage returns (such as a saved progress log), form feeds, or Unicode line separators therefore returns the same lines as on the local sandbox, and the `start_line` a truncated read suggests points at the next unread line.

Concurrent reads and writes to the same file share a gate across synchronous and asynchronous tool calls. Async callers waiting for that gate do not occupy worker threads needed to finish the current read or write. Cancelling a waiting call leaves the current operation running; a call that already started file inspection still waits for that work to finish before releasing its gate.

The built-in `grep` tool searches either one text file or all matching text files below a directory, so an agent can search an uploaded document directly without first broadening the request to the entire uploads directory.
On the local sandbox, `grep(literal=True)` also searches long lines in minified text or single-line JSON, within the existing file-size limit. Case-insensitive literal matching avoids repeated-prefix rescans while preserving Unicode case behavior. Regex searches retain their long-line safety guard.

Across sandbox providers, returned previews show only the beginning of each matched line (200 characters by default), so a match later in a long line may not appear in the preview. Use the reported path and line number to inspect the source. The `truncated` flag concerns match-count limits, not preview length.
E2B's `glob` filter preserves spaces, quotes, and dollar signs in filename patterns, while wildcard matching and root-relative directory scoping remain unchanged.
E2B `grep` also preserves colons in file and directory names when reporting matching paths and line numbers.
`glob` and `grep` preserve non-LF separator characters, such as vertical tabs and Unicode line separators, inside returned paths on E2B, BoxLite, Tenki, and OpenSandbox; `grep` also preserves them inside matched text.

Remote `ls` excludes ignored descendants before applying its 500-entry listing limit, so dependency and build trees do not crowd out visible files. Explicitly listing an ignored directory still lists its contents; normal depth and output limits remain in effect.

AIO directory listings discard missing shell sessions so the next request can recover.
After a dropped connection, directory listings and persistent shell commands report an
unknown outcome without replaying the operation; later calls use a fresh session.

Current-upload context tolerates malformed attachment metadata: invalid filename
references and files that cannot be checked are skipped individually, while valid
attachments in the same message remain available. Unusable or display-overflowing
file sizes use the existing zero-size display fallback without dropping the file.
Probe errors are logged at debug level. Sizes of 1 TB or more that can be rendered
safely display as `>= 1 TB` to keep the prompt compact; stored byte counts remain
unchanged.

When `uploads.auto_convert_documents: true` is enabled, document parsing runs
outside the Gateway event loop for every file size, including small compressed
Office files. Cancelling an upload waits for its conversion worker before
removing the worker's temporary source. Automatic conversion remains off by default.

Uploaded Markdown outlines recognize ATX heading syntax, clean closing markers with a linear suffix scan, and skip HTML comment blocks and fenced and indented code examples, so hashtags and code comments do not
crowd out real document sections from the agent's heading preview. Indented bold examples are also excluded; PDF-style bold headings with up to three leading spaces remain supported.
Whole-title bold wrappers and adjacent PDF bold spans are cleaned; separate bold
spans joined by ordinary text retain their markers instead of losing only the outer pair.
Split-bold numeric table rows, including parenthesized years, signed values, and
currency-prefixed amounts, are excluded when any block after the section number
is a numeric column, so they do not consume the outline's heading budget.
UTF-8 Markdown files with or without a byte-order mark (BOM) produce the same
outlines and fallback previews, with original line numbers preserved.
Outline titles are limited to 200 characters and fallback previews to 2,000
characters per file, with truncation markers. Full uploaded files remain available
for targeted reads.

Converted upload outlines and previews require matching source and Markdown versions,
including modification timestamps. A detected change to either file invalidates its
previous conversion association, including equal-length edits. Older ownership records
without source timestamps or the Markdown modification timestamp are also rejected;
re-upload the source with `uploads.auto_convert_documents: true` to restore
conversion-backed outlines. Debug logs distinguish these legacy records, which need
re-registration, from a changed file. Files remain available, and unvalidated Markdown
conversions appear as standalone files in the agent's historical listing.
On Windows, `st_ctime_ns` may represent creation time; a same-size rewrite of either
file that restores the original `mtime` can evade validation. Timestamp checks are
conservative metadata validation, not a guarantee of content equality or tamper resistance.

Sandbox image downloads enforce the 20 MiB vision limit while reading, including model-context rereads. Oversized streams stop at the first over-limit chunk. Custom sandbox providers must accept and enforce the `download_file(..., max_bytes=...)` keyword; older implementations fail the image read instead of falling back to an unrestricted download.

Image bytes loaded for a vision-model call are transient: DeerFlow removes the hidden base64 message after the model consumes it so later checkpoints do not keep duplicating that payload.

After each run, DeerFlow records a workspace change summary for the run-owned `workspace` and `outputs` directories. The Web UI shows a compact "files changed" badge on the assistant turn; opening it reveals created, modified, and deleted files with text diffs when safe to display. Uploads are excluded because they are user inputs, not agent-generated changes, and stdio MCP temporary/debug files under the DeerFlow-owned `.mcp/` namespace are excluded because they are process-internal state (like `.git/` and `node_modules/`, any directory named `.mcp` is excluded at any depth). Large, binary, or sensitive-looking files are shown as metadata only.

If a file disappears while being hashed, the scan omits that file and continues
recording the others. A concurrent scratch-file removal therefore does not
discard the whole snapshot or suppress detection of other produced outputs.
This remains a best-effort scan, not an atomic filesystem snapshot.

`present_shared_artifact` publishes another conversation's persisted output using `origin_thread_id + path + sha256`. Same-user, runtime-home-confined reads and writes reject path traversal, symlinks and changed content; an existing destination with different content is retained, while identical concurrent handoffs succeed. Successful handoffs count as run delivery and archive receipts. The current POSIX implementation does not acquire a source sandbox or cross user boundaries.

When you reopen the destination conversation, the Artifacts sidebar restores
files from confirmed handoffs.

Files presented through `present_files` remain part of the thread's artifact state, and the Web UI restores the artifact panel and selected document after a page refresh. Long artifact lists scroll within the panel on desktop and in the mobile drawer, keeping every file reachable. When a completed response successfully presents between 2 and 50 files, its final file card also offers one ZIP download. Archive membership comes from the terminal delivery receipt rather than browser-supplied paths, and the ZIP contains the current file versions, which may have changed since the response. The currently selected formal artifact is refreshed once when the run finishes so edits become visible without a manual reload. Existing UTF-8 text artifacts under `/mnt/user-data/outputs` can also be edited and explicitly saved from the panel on Unix and Windows while the thread is idle; saves use content revisions to prevent overwriting agent changes. A delayed background read cannot replace a successfully saved revision in the editor; cancelled preview and full-file reads also abort their HTTP requests. Source previews also recognize extensionless `Dockerfile` and `Makefile` artifacts by their file names. Unknown file types, including names such as `constructor` and `__proto__`, retain the download fallback.

Unsaved artifact edits survive switching chats, workspace pages, or visiting the
home page and returning in the same browser tab. Drafts stay in memory for the
current account until saved or discarded; changing accounts or signing out clears them.
Public showcase visits and unavailable Gateway auth probes retain hidden drafts
until authentication is known. Recovering as another account or confirming logout
clears the retained content.
Refreshing or closing the tab warns while any chat has unsaved edits. Draft file
contents are not stored in browser storage and do not survive a reload.

Artifact content revisions refresh when an output file is atomically replaced,
even if its size and modification time are preserved. Refreshing the preview
then provides the new revision for saving; an older preview still requires a reload.
Regular files over the 2 MiB editing limit use file identity and change metadata
for range validators without hashing the whole file. Conditional byte ranges for
regular files require a matching ETag; date-form `If-Range` requests receive the full current file.
Saving also bounds the existing-file read to 2 MiB plus one detection byte, so a
file that grows or is replaced after the size check is rejected without loading
the entire oversized file into memory.

CSV and TSV artifacts open as tables in the artifact panel and in a separate window. The preview preserves text values (including leading zeros), supports an optional header row, and pages through up to 200 rows and 50 columns from the initial sample. Long or multiline cells can be opened and copied in full. Switch to source to inspect or edit the file; downloads and separate windows use the saved version.

HTML artifact previews resolve relative assets from the artifact directory unless the document contains a real `<base>` element. Base-tag examples in comments or script text do not change that resolution.

With authentication enabled, static resources in the same thread's artifact route
(images, responsive images, classic scripts and CSS, including nested imports)
are fetched by the parent and inlined without weakening the opaque iframe sandbox.
Preparation has resource, byte, CSS-depth and time limits and reports partial
previews. Dynamic JavaScript requests, ES module imports, nested iframes and
navigation remain subject to sandbox restrictions; see the
[frontend preview notes](../../frontend/README.md#development-notes) for the supported
scope and limits.
Optional resource failures, including 401 responses, keep the conversation open
with a partial-preview notice. HTML doctypes and doctype-less rendering modes
are preserved, and CSS references inside inline SVG styles are prepared too.

Markdown report previews in the artifact panel and separate window resolve local
images from the report's own directory and conversation. Both relative paths
such as `./charts/summary.png` and absolute `/mnt/...` paths are supported;
external image URLs keep their existing behavior.

If the sample cuts a CRLF line ending in half, the preview keeps the earlier complete rows and omits the incomplete final record, including when its last field is quoted.

Text artifacts are streamed with HTTP byte-range support. A resumed download
validates its ETag against the file version that supplies its response bytes.
The Web UI initially loads at most 1 MiB, shows the preview size for larger files, and waits for
an explicit **Load full file** action before fetching the remainder or mounting
the full code editor. Editing becomes available once the complete file has loaded;
unsaved-change detection uses the full content, including when reverting edits
or deleting the portion beyond the initial preview. If a reload fails or returns
only a preview, users can still exit editing while retaining their unsaved draft.
Active HTML, XHTML, and SVG artifacts remain forced downloads at the Gateway
boundary.

Artifact previews and downloads preserve literal percent sequences in file names:
`report%20final.md` and `report final.md` remain distinct files. Markdown links
continue to accept URL-encoded paths.

The `write_file` guidance reflects the active model's output token limit, including custom-agent and thinking-mode overrides. For longer documents, the agent is guided to write sections with `append=True`; models without a known limit receive no numeric budget hint.

With `AioSandboxProvider`, shell execution runs inside isolated containers. With `LocalSandboxProvider`, file tools still map to per-thread directories on the host, but host `bash` is disabled by default because it is not a secure isolation boundary. Re-enable host bash only for fully trusted local workflows. Host bash commands have a wall-clock timeout, and long-lived processes should be started in the background with output redirected to a workspace log. If local command startup fails after spawning a child, DeerFlow attempts to kill and reap that child before propagating the startup error. On Windows, Git Bash/MSYS argument-conversion exclusions are limited to safe non-root virtual path prefixes, so host-native CLI launchers retain their normal MSYS compatibility. When the local sandbox falls back to PowerShell, it captures output as UTF-8 so CJK text does not depend on the Gateway host locale.

Docker AIO sandboxes default to their existing open egress behavior for
compatibility. Operators can set `sandbox.network.mode` to `isolated` or
`allowlist`; allowlist mode supports operator-defined domains and an interactive
Human Input card for temporary or sandbox-lifetime HTTP(S) approval. Private,
loopback, link-local, multicast, and cloud metadata addresses remain
unapprovable. Denied hostnames are rejected before DNS resolution.
Runs in `scheduled`, `webhook`, or `autonomous` interaction mode auto-deny
without opening a card. These unattended runs proceed with minimal assumptions
only for low-risk, reversible work; high-risk or irreversible work without
sufficient authorization returns a structured `BLOCKED` result naming the
missing decision, even if the model attempts to ask for clarification.
The trusted sidecar uses a dedicated per-sandbox egress bridge rather than
Docker's shared default bridge, and rejects ambiguous HTTP field names before
forwarding. See
[Sandbox configuration](../../backend/docs/CONFIGURATION.md#sandbox-network-policy)
for runtime requirements and the complete policy model.

`AioSandboxProvider` normally detects thread-data mounts from its backend: local
containers use the mounted gateway directories, while remote/provisioner
sandboxes receive uploaded files through explicit synchronization. Deployments
where both sides are guaranteed to share the same thread user-data directories
can set `sandbox.thread_data_mounts: true` to skip that per-upload sandbox
acquire and sync. Leave the field unset for automatic detection; setting it
incorrectly can make uploaded files unavailable inside the sandbox.

Failed upload commits report the original error even if temporary-file cleanup
also fails, for example because of a Windows sharing violation.
Once the file is published, a temporary-file cleanup failure is logged without
failing the upload; hidden staging files are left for the startup sweep.
If that sweep cannot scan an uploads directory, it logs a warning and preserves
its files while continuing cleanup elsewhere. A directory that disappears
during cleanup is skipped quietly.

Uploads, new skill support files, and new local sandbox paths reject Windows
reserved device names on every platform, including `COM¹`, `LPT²`, the console
aliases `CONIN$` and `CONOUT$`, and names with extensions such as `com³.txt`.
ASCII spaces before the extension do not make a device name portable:
`NUL .txt` and `COM1  .log` are rejected too. Ordinary names such as
`report .txt` are preserved unchanged.
Rename these files before creating or uploading them so the same file tree
remains usable on Windows.

Uploaded filenames matching `.upload-*.part` are rejected because that pattern is
reserved for temporary staging files. Rename such a file before uploading it.
The restriction includes Windows aliases with trailing dots or spaces and
case variants, such as `.upload-notes.part.`, `.upload-notes.part `, and
`.UPLOAD-NOTES.PART`, on every host.
The HTTP check recognizes both `/` and `\` as path separators, including on
Linux, when extracting the basename. The endpoint returns `400` with a rename
hint before publishing any file in a batch containing a reserved name, so the
chat reports the upload error instead
of continuing without the attachment. The SDK validates filenames for the whole
batch before copying any files. New project document names follow the same
restriction, whether defaulted from the source or explicitly supplied on upload
or promotion to the shelf; an older shelf document with a reserved name
remains downloadable but cannot be attached directly. Download it, rename it,
and upload it to the thread. This change does not recover or migrate older
thread uploads that already match the staging pattern.

Upload listings remain available during concurrent cleanup: removed files are
omitted, and if the upload directory disappears or is replaced by a file, the
listing returns any entries already collected. Permission and other operational
errors still surface.

This is the difference between a chatbot with tool access and an agent with an actual execution environment.

```
# Paths inside the sandbox container
/mnt/user-data/
├── uploads/          ← your files
├── workspace/        ← agents' working directory
└── outputs/          ← final deliverables
```
