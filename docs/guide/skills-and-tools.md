# Skills & Tools

**Runtime tool approvals**: Enable `hitl_approval.enabled` to offer Ask and Auto
independently of reasoning mode. Operators can also enable Full access in
`hitl_approval.allowed_modes`. Ask presents the complete operation before
execution. Auto makes a separate, tool-free review call using
an existing model profile and requests human approval when risk or authorization
is uncertain. Full skips individual reviews within the operator's policy.
Mandatory guardrails and account permissions apply in every mode.

Approval cards support allow, reject, edited arguments, and exact-operation chat
grants that can be revoked from Tool permissions. Root approvals survive restart
through checkpoints. A delegated call waits in its original execution; stopping
its run, timing out, or restarting the worker invalidates that child approval.
Unattended runs cannot wait for a human. The feature is disabled by default.
Missing, empty or duplicate tool-call IDs are rejected before execution so an
unanswerable approval cannot block the chat.
See [HITL Tool Approval](../../backend/docs/CONFIGURATION.md#hitl-tool-approval) for
configuration and safety semantics.

Agents can call the read-only `inspect_run_status` tool to inspect visible run
token usage, message and tool-call counts, an approximate context-window fill,
and whether a summary or unfinished to-dos exist. It returns counts only, not
conversation or to-do text. Token counts depend on provider usage metadata;
compaction can remove earlier messages, and context fill is unavailable when
the model has no configured `context_window` or its latest response reports no
input usage. It is also unavailable after a subagent dispatch because subagent
usage may be attributed to that response. The result identifies whether a
current-run boundary is known.

Open **Capability Center** from the workspace sidebar to manage **Plugins**
(MCP servers and Lark/Feishu integration) and **Skills**. Both catalogs support
search; skill cards show concise descriptions with full descriptions in a detail
view. Built-in and user-created/imported skills are listed separately. The
Community tab supports importing `.skill` archives into My skills.
General preferences remain in Settings.

Failed skill requests retain their HTTP error status and a readable fallback
when the server returns an unusable error body.

The **ppt-generation** skill applies photo EXIF orientation before fitting and
embedding slide images, so rotated or mirrored photos retain their displayed
orientation.

The **ppt-generation** skill preserves transparent slide images when composing a presentation, including grayscale and palette PNG transparency.

Administrators can see **Could not load** warnings in Capability Center > Skills
when their own custom skill's `SKILL.md` contains invalid YAML. Warnings show the
package-relative file and, when available, its line and column, with a quoting
hint for unquoted colon values. Fix the file on disk and select **Reload skills**
to refresh the list and invalidate skill prompt caches for subsequent runs;
active runs retain their existing snapshot. This covers caller-owned custom
skills only, excluding legacy/global, public, integration, and external linked
packages. These warnings cover YAML syntax errors only: missing frontmatter,
non-mapping metadata, missing/invalid name or description, invalid allowed-tools
or required-secrets declarations, non-UTF-8 files, and file-read failures
(including permission denied) are not reported. A missing warning does not
establish that a package is valid or readable. The scope note remains visible
even when there are no YAML warnings; check Gateway logs for other load failures.
Parsing remains strict and invalid skills stay unavailable to agents.

## Read-only knowledge sources

Three retrieval tools can be configured independently in `tools[]`: document
`knowledge_search`, published `knowledge_entries_search` through the
[WeKnora plugin](../../examples/deerflow-extension-weknora/README.md), and
`entity_relations_search` through the optional
[LightRAG plugin](../../examples/deerflow-extension-lightrag/README.md). Remove a tool
entry to disable it. They share scope admission, source validation, budgets and
citation rendering. Wiki queries that return no pages retry up to four individual
keywords within the same authorized base. Unsupported filters fail closed;
multiple providers with different resource namespaces support only all/disabled scope. The new adapters
have offline coverage and [local live validation](../../examples/deerflow-extension-lightrag/VALIDATION.md)
with bge-m3 and GLM-5.3; see that record for coverage limits.

Configure `knowledge_search` with either
`deerflow.community.ragflow.tools:knowledge_search_tool` or
`deerflow.community.lightrag.tools:knowledge_search_tool` in `config.yaml`.
Both support attributable retrieval evidence. Both clients load HTTP client
TLS trust in a worker thread before asynchronous requests, keeping synchronous
certificate loading off the event loop. LightRAG and RAGFlow responses
without complete provider locators use the shared DeerFlow source contract;
complete RAGFlow responses retain their existing citation snapshots and scope
controls. Knowledge citations show the
provider, document title, and retrieved excerpt in chat, including after reload
and when a subagent performed the retrieval. Missing page numbers and public
URLs remain absent; sources without a URL are readable as local evidence.
Inline citations remain readable after Markdown sanitization, and supplied page
numbers use the selected interface language.
Shared knowledge results skip entries that exceed the remaining output budget
and retain later fitting entries in provider order. Retained citations stay
paired with their visible evidence.
Copying a source reference produces a Markdown link that escapes brackets in the
visible title and wraps a URL containing parentheses in angle brackets, so the
copied reference stays a valid link. New providers use the shared
envelope; existing RAGFlow citation histories remain supported.
Expand a completed subtask card to inspect its report's forwarded knowledge
sources, including when reopening a saved conversation.
Shortened mixed-provider task reports remove dangling citation fragments
without flattening retained shared-source links.
Existing web citations and the text-only Python `knowledge_search(query)` APIs
remain supported. No knowledge management service or page is required.
See [the knowledge contract guide](../../backend/docs/KNOWLEDGE.md).

Knowledge scope selection also works with operator-installed read-only Provider
extensions. The shared selector shows only the filters a Provider supports:
knowledge-base selection requires a catalog and dataset filtering; file
selection additionally requires document listing and document filtering.
Unsupported or inaccessible filters fail without expanding the search scope.
Choosing no knowledge search stops retrieval before loading the Provider.
Provider resource IDs are preserved up to 256 Unicode code points; longer IDs
are rejected without truncation.
RAGFlow keeps its existing configuration and citations, and search-only
Providers remain usable without a catalog or management page. See the
[offline Provider example](../../examples/deerflow-extension-knowledge/README.md)
for extension registration and configuration. The installable
[WeKnora read-only extension](../../examples/deerflow-extension-weknora/README.md)
targets WeKnora v0.8.3 and adds knowledge-base/document selection and shared
retrieval citations. Configure explicit user-to-workspace credential bindings,
or opt into shared read-only access for authenticated users without maintaining
a user-ID list. Resource authorization remains with WeKnora. The extension directory includes
its installation guide.

The optional [knowledge platform extension](../../examples/deerflow-extension-knowledge-platform/README.md)
adds connection policies, hierarchical spaces, members and explicit resource sharing.
Space-routed management retains existing administrator and Provider grants. It is
disabled by default and includes no management page or global chat retrieval ACL.

The optional [knowledge center extension](../../examples/deerflow-extension-knowledge-center/README.md)
adds an independently enabled workspace page for authorized spaces, file/URL/text
ingestion and document processing snapshots. It consumes the platform and management
APIs; it does not grant permissions or add entry editing, versions, graph browsing,
complete document/task directories or Trace. Retrieval works without it.

The optional [knowledge management extension](../../examples/deerflow-extension-knowledge-management/README.md)
adds administrator-authorized file, URL and manual ingestion, processing status,
reprocessing and cancellation through WeKnora. Parsing, indexing and optional
Wiki/graph generation remain upstream. It is disabled by default, requires
explicit resource/operation grants, and installs no management page. Its
provider-independent API is covered by offline contract tests. Real ingestion,
GLM-5.3/BGE integration, browser citation replay and observed limitations are
recorded in the [acceptance report](../../examples/deerflow-extension-knowledge-management/VALIDATION.md).

Skills are what make DeerFlow do *almost anything*.

A standard Agent Skill is a structured capability module — a Markdown file that defines a workflow, best practices, and references to supporting resources. DeerFlow ships with built-in skills for research, report generation, slide creation, web pages, image and video generation, and more. But the real power is extensibility: add your own skills, replace the built-in ones, or combine them into compound workflows.

For MiniMax, the [video-generation skill](../../skills/public/video-generation/SKILL.md)
accepts `MINIMAX_VIDEO_RESOLUTION` and `MINIMAX_VIDEO_DURATION` (integer seconds).
Unset overrides use the provider defaults. Invalid duration strings fail before
the script submits a request.

The video-generation skill derives reference-image MIME metadata from `.png`,
`.jpg`, `.jpeg`, `.webp`, and `.gif` filename extensions (case-insensitive). A
submitted reference with a missing or unrecognized extension raises a clear error
before API submission. Filenames must match their contents; image bytes are not
validated or converted, and provider-specific format restrictions still apply.

The [music-generation skill](../../skills/public/music-generation/SKILL.md#output-handling) preserves existing output when the provider returns malformed, empty or unrecognized audio.

The bundled skill-creator trigger evaluator drains CLI output through EOF, so a completed subprocess does not turn a recorded skill trigger into a false negative.
The bundled skill-creator description optimizer reads YAML frontmatter consistently with skill validation, preserving quoted strings and multiline descriptions. Its scripts require PyYAML, as does the skill package validator. Invalid skill metadata is reported on stderr with a nonzero exit status rather than a traceback.

Skills are loaded progressively — only when the task needs them, not all at once. This keeps the context window lean and makes DeerFlow work well even with token-sensitive models.

The bundled video-generation command reports failures on stderr and exits with
status 1, including when the selected provider has no API key. Callers can check
the exit status before presenting an output file.

The bundled podcast-generation command returns a nonzero exit status and writes
diagnostics to stderr when generation fails. Callers can check the status before
presenting audio; an existing MP3 or generated transcript is not proof of success.

The bundled chart-visualization command does the same for an unknown chart tool,
a spec missing `tool`, or a chart-service HTTP failure. Successful chart URLs,
including spreadsheets (`generate_spreadsheet`), stay on stdout. A mixed batch
still prints URLs for the charts that succeeded, then exits with status 1.

When deferred skill discovery is enabled, `describe_skill` ranks installed skills by bounded, Unicode-normalized intent-term coverage across names and descriptions. Natural multi-term requests can therefore find a relevant skill without requiring one exact phrase, while exact `select:` and required-name `+prefix` lookups remain available. Ranked searches use up to 256 characters and return up to five results; exact `select:` lists are not truncated and return all requested catalog matches.

A skill directory is a package boundary: once DeerFlow finds its `SKILL.md`, nested `SKILL.md` files under that package (for example evaluation fixtures) remain supporting data and are not registered as runtime skills. This applies to managed integration packs as well as public and custom skills. Namespace directories without their own `SKILL.md` can still group nested skills.

Discovery follows operator-managed directory symlinks, but skips links back to an ancestor directory so a cyclic namespace does not repeatedly rescan the same tree. Independent links to the same external skill tree remain supported.

Skill Markdown and bundled text resources use UTF-8. Skill-creator CLI and review utilities read and write text explicitly as UTF-8 so localized skills behave consistently across operating systems.

For standalone skill exports, the bundled skill creator's `scripts/package_skill.py` can be run by file path from any directory, or as `python -m scripts.package_skill` from the skill-creator directory. Both entry points validate the skill before writing a `.skill` archive.

Custom-skill writes and security-scan staging preserve submitted line endings
on every platform, so the scanner checks the bytes that will be stored.

Skill-creator benchmark aggregation uses recorded `timing.json` token counts even
when `grading.json` already contains the run duration. Recorded zero counts are
preserved; output character counts remain a legacy proxy only when token data is missing.
Unreadable, non-UTF-8, malformed, or non-object `timing.json` data emits a warning
and is treated as missing measurements. Its token and duration fields accept finite,
non-negative numbers (including zero); invalid fields emit a warning naming the file
and field and use the existing fallback independently, preserving valid measurements
and other runs.

`SKILL.md` YAML frontmatter must open and close with `---` on its own line (trailing spaces or tabs are allowed). A line such as `---suffix` is not a closing delimiter.

Custom skill history preserves Unicode line separators inside saved content and metadata, keeping those revisions readable for history inspection and rollback. Malformed JSON history records are still rejected.

The bundled `github-deep-research` API client also works without `requests`, using
Python's standard-library HTTP client. Its fallback preserves spaces, Unicode, and
reserved characters in search queries and label filters.
File reads accept raw repository-relative paths and preserve spaces, Unicode,
`#`, `?`, and literal percent signs with either HTTP client.
Directory listings ask for the repository's own default branch, so a repository that
uses neither `main` nor `master` reports its current tree instead of a stale branch.
They indicate when GitHub or the local output limit truncates the listing.
The `issues` command excludes pull requests and follows additional pages to fill
its requested issue limit; the `prs` command remains available for pull requests.

Users can explicitly activate an enabled skill for a single turn by starting the request with `/skill-name`, for example `/data-analysis analyze uploads/foo.csv`. DeerFlow loads that skill's `SKILL.md` as hidden current-turn context while leaving the base prompt limited to skill metadata. Slash activation respects disabled skills, custom-agent skill whitelists, and existing channel commands such as `/new` and `/help`.

Data-analysis Markdown exports escape pipes and backslashes in column names and values, and render cell line breaks as `<br>` so multiline data stays within its table cell.

Data-analysis JSON exports require unique result column names. For joins that
return repeated names such as `id`, use SQL aliases (`AS left_id`, `AS right_id`)
before exporting. Duplicate names cause an error before the output file is opened,
preserving any existing file.
The CLI names the repeated columns in a short stderr error and exits nonzero,
so callers can correct their aliases without reading a traceback.
JSON exports likewise reject non-finite numbers (`NaN` and infinities), including
values nested in lists or structs, before opening the destination. Filter them
or replace them with `NULL` in SQL; the CLI reports an error and preserves any
existing output rather than writing invalid JSON.

The **data-analysis** skill preserves each CSV file or Excel sheet when names collide across inputs. [Prepare its Python environment](../../skills/public/data-analysis/SKILL.md#environment-setup) explicitly with DuckDB and openpyxl; missing packages report setup instructions instead of installing themselves during analysis. Use the SQL names printed by `inspect` (such as `report`, `report_1`) for queries and summaries. Its cache follows ordered input basenames and contents, so renaming or reordering inputs rebuilds their table map instead of silently selecting a different source. Cache publication uses complete immutable generations: import writers close before their database and table map become visible together, so overlapping processes can read the same snapshot. Interrupted private builds are removed and damaged entries rebuild; legacy flat caches rebuild once. Complete generations remain available to active readers, so stop analyses before manually clearing `.data-analysis-cache/`. Automatic cache garbage collection is not provided. Quoted original names also resolve without rewriting query text; apostrophes in upload paths and double quotes in column names are preserved through loading, inspection, queries, and summaries. CSV, JSON, and Markdown exports accept bare filenames such as `report.csv` in the current working directory as well as nested relative and absolute paths.

After an answer loads skills, its toolbar includes **Skills used**. Hover over or click the icon to see the skills and their sources; hovering a skill name underlines it. Select a skill to inspect its `SKILL.md` in the resizable side panel (a drawer on mobile). The view uses snapshots captured during successful configured read-tool loads or explicit slash activation, so later edits or removal of a skill do not rewrite its history. Repeated loads appear once per run, in first-load order. Range reads and bounded snapshots are labeled as partial; older conversations without captured evidence do not show this menu. Copy returns the captured Markdown, including YAML frontmatter. Package-relative links and images remain readable references rather than navigating away from the conversation. Skill loads performed through other tools, such as shell commands, are not inferred from answer text.

A skill's `allowed-tools` frontmatter is compatibility metadata carried for interop with other agent frameworks: DeerFlow parses, validates, exports, and describes it, but it never filters model-visible tool schemas, refuses tool calls, or rewrites tool-search promotions. Merely enabling, advertising, or listing a skill in a custom agent or subagent `skills` allowlist never changes an agent's toolset either. Real tool authority lives in Agent configuration and authorization: assembly-time provider filtering, runtime Guardrail enforcement, guardrail allowlists, and the deferred-promotion catalog own the permission ceiling. Skill visibility and activation remain independently enforced: slash activation honors disabled skills and custom-agent whitelists, and the `skill:activate` authorization decision still gates both explicit slash activation and autonomous `SKILL.md` loads.

When you install `.skill` archives through the Gateway, DeerFlow accepts standard space-separated `allowed-tools`, optional frontmatter metadata, and the Claude-compatible `argument-hint` field instead of rejecting otherwise valid external skills. YAML lists remain supported for `allowed-tools` and preserve exact runtime names. Exact portable spellings such as `WebFetch`, `WebSearch`, `Glob`, `Grep`, and `Read` map to DeerFlow's `web_fetch`, `web_search`, `glob`, `grep`, and `read_file` tools; lowercase or otherwise unknown scalar names remain unchanged so custom and MCP tools keep their exact runtime spelling. Parenthesized entries such as `Bash(tvly *)` are tokenized as one literal entry, including spaces, quoted text, and escaped parentheses; such scoped declarations remain literal compatibility metadata and do not authorize or restrict commands — DeerFlow's Agent configuration and authorization, not tool arguments, decide what may run.

Disabling a skill also removes it from the sandbox filesystem view, so shell commands and structured file tools follow the same enabled state. Local, Docker/AIO, hostPath provisioner, and newly created E2B sandboxes source `/mnt/skills` from enabled-only projections that update when public, custom, legacy, or managed integration skills are toggled, edited, created, deleted, or installed. Structured `read_file` calls (including line ranges and read-before-write checks) use the sandbox provider's mount mapping, so the user identity captured when the sandbox was acquired remains authoritative. Managed integration packages remain shared, while their projected filesystem visibility follows each user's enabled state. Multi-worker Gateways re-read on-disk enable state while rebuilding user projections, so a toggle handled by one worker is honored by another worker's next sandbox acquire. Existing E2B sandboxes retain their creation-time snapshot until they are recreated. PVC-backed provisioner skills keep their configured PVC snapshot/layout for now; dynamic PVC materialization is tracked separately.

Chat-specific skill views used by an Agent's skill allowlist verify copied file
contents before sandbox reuse. Edited instructions, missing or injected files,
and changed links are repaired from the canonical skills on the next acquire;
inode and timestamp drift on shared storage does not force a rebuild. Integrity
checks read the projected files, so larger packages increase acquire-time read I/O.

Skill projection manifest saves preserve the original error or interruption even if temporary-file cleanup or its logging also fails. Manifest files retain their private filesystem permissions.

```
# Paths inside the sandbox container
/mnt/skills/public
├── research/SKILL.md
├── report-generation/SKILL.md
├── slide-creation/SKILL.md
├── web-page/SKILL.md
└── image-generation/SKILL.md

/mnt/skills/custom
└── your-custom-skill/SKILL.md      ← yours

/mnt/skills/integrations
└── lark-cli/lark-doc/SKILL.md      ← managed, read-only
```

The built-in `image-generation` skill supports Gemini, MiniMax, and
OpenAI-compatible Images APIs. Select the latter with
`IMAGE_GENERATION_PROVIDER=openai`, then configure
`IMAGE_GENERATION_API_KEY`, `IMAGE_GENERATION_BASE_URL`, and
`IMAGE_GENERATION_MODEL`. For a containerized sandbox or an explicitly enabled
local host shell, expose these variables through `sandbox.environment`; sandbox
commands intentionally do not inherit API keys from the Gateway process.
The local provider uses the resolved configuration values unchanged, and
request-scoped secrets override operator values. Local bash output and command
errors redact credential values while leaving benign settings such as model
names and base URLs readable.

For `LocalSandboxProvider`, this is a managed tool-path boundary rather than host filesystem isolation. Explicit per-Agent skill policies are accepted only while host bash is disabled (the default), because a host subprocess can address canonical paths without using the provider's virtual-path mappings. Use Docker/AIO, the Kubernetes provisioner, or E2B when the filesystem boundary must remain enforceable alongside shell access.

When the local sandbox uses PowerShell, mapped host-path spaces and shell metacharacters are escaped for the caller's quoting context; wildcard expansion is preserved. The public `bash` tool's existing workspace prefix uses `&&` and POSIX path quoting: it requires PowerShell 7 for that separator and does not support workspace paths containing apostrophes. These workspace-prefix limitations are separate from virtual-path mapping.

On Windows, the local sandbox's `cmd.exe` fallback decodes builtin output using
the console output code page, including UTF-8 after `chcp 65001`, independently
of Python's UTF-8 mode. If no console page is available, it uses the system OEM
page, with ANSI as a last resort. Native programs can choose a different output
encoding; configure those programs to match the console page when needed.

Managed integrations install shared read-only skill packs without mixing them
into custom skills. The Lark/Feishu CLI integration is available under
`Capability Center → Plugins → Lark / Feishu`; an administrator installs or
upgrades the official `lark-*` pack once under
`{DEER_FLOW_HOME}/integrations/skills/lark-cli`, and every user discovers that
same pack with an independent enabled state. Each user's app configuration and
OAuth data remain isolated under
`{DEER_FLOW_HOME}/users/{user_id}/integrations/lark-cli/{config,data}`. These
secret directories are restricted to `0700`, regular credential files to
`0600`, and symlinks are rejected.
On Windows, waiting for another process's integration file lock retries for up
to 15 minutes; other file-lock errors are reported immediately.

After installation, users can click **Connect Lark** to open a browser
authorization link; no terminal authorization is required. The same UI can
request additional permission domains such as Calendar, Docs, or Drive, or a
specific OAuth scope reported by `lark-cli`. A cheap status refresh only
inspects the local credential tree, so the UI reports **Credentials configured
(not live-verified)** until an explicit browser completion performs live token
verification. The action then remains **Reconnect Lark** so users can replace
or extend authorization. If an agent hits missing Lark authorization during a
conversation, the managed `lark-shared` guidance points the user back to the
same plugin configuration with `/workspace/capabilities?tab=plugins&plugin=lark`.

Browser authorization continues across polling timeouts; repeated polls share
the same attempt, including when Gateway runs multiple workers. Starting a new
flow or changing the app cancels the previous attempt. If DeerFlow cannot
confirm the outcome of a finished attempt, restart authorization for a new link.

Once configured, **Change Lark app** lets a user point their DeerFlow account at
a different Lark/Feishu app without a reinstall — either by pasting an existing
app's App ID / App Secret or by re-registering an app in the browser. Switching
is per-user (it never touches another user's credentials), validates the new
credentials through the official CLI's live tenant-token probe before replacing
the active app, and revokes/removes the previous app's OAuth tokens. A rejected
credential change does not supersede an in-progress setup or authorization flow.
The previous OAuth data is cleared before the CLI stores the replacement app,
so the new file-backed keychain secret remains available during reconnection.
DeerFlow then immediately opens browser authorization for the newly bound app so
the switch ends in a usable connection.

Installing the Lark skill pack resolves the latest official `larksuite/cli`
release from GitHub and downloads that version's skills at install time, so the
Gateway needs outbound internet access for that step (it falls back to a
bottom-line pinned version if the release lookup fails). The settings page shows
the installed version and, when available, the newest published version so an
admin can reinstall to upgrade. Air-gapped deployments can pre-stage the archive
and point `DEER_FLOW_LARK_CLI_SKILLS_ARCHIVE` at the local file. Integrity does
not depend on a pinned archive byte hash (GitHub does not guarantee stable
source-archive bytes); instead the download is restricted to the official GitHub
host, every archive member passes structural safety guards, and a content hash
of the effective installed skill tree (including DeerFlow's injected shared
guidance) is recorded so content changes are auditable across reinstalls.

When `sandbox.use` selects the AIO provider, the same install also downloads the
official Linux amd64 and arm64 CLI release archives, verifies their published
SHA-256 checksums, safely extracts one executable per architecture, and mounts
the resulting runtime read-only at `/mnt/integrations/lark-cli/runtime`. An
architecture-selecting launcher in that mount makes `lark-cli` available in the
sandbox `PATH`. Air-gapped AIO deployments can pre-stage a symlink-free runtime
tree containing `bin/lark-cli` plus both `linux-{amd64,arm64}/lark-cli` files and
set `DEER_FLOW_LARK_CLI_SANDBOX_RUNTIME_DIR` to that directory.

> **Sandbox trust boundary:** the browser never receives the Lark app secret, but
> agent conversations run `lark-cli` inside the sandbox, so the per-user
> credential directories are mounted into it: `config` (holding the long-lived
> `appSecret`) is mounted **read-only**, its otherwise empty `config/locks`
> subdirectory is over-mounted writable for `lark-cli` coordination files, and
> `data` (refreshable OAuth tokens) is writable. The credential-bearing config
> and data mounts remain *readable* by any process the agent runs there, so code
> reached via prompt injection in a tool result could read them. Treat the
> sandbox as inside the Lark credential trust boundary until the sidecar
> credential-broker follow-up removes these mounts from sandbox execution.

For remote/Kubernetes deployments (the provisioner backend), the sandbox
`lark-cli` runtime can instead be supplied by an optional init container that
copies the binaries into a shared `emptyDir` — no install-time GitHub download and
no hostPath/PVC runtime mount. Publish the image under
[`docker/lark-cli-init`](../../docker/lark-cli-init/README.md) and set
`LARK_CLI_INIT_IMAGE` on the provisioner (with the Helm chart,
`provisioner.larkCliInitImage` / `provisioner.larkCliBrokerImage`); it stays off
(legacy behavior) when unset. The Lark integration status
(`GET /api/integrations/lark/status`) reports `sandbox_runtime_mode`,
`sandbox_runtime_probed`, and `sandbox_runtime_ready`.
`sandbox_runtime_probed` marks whether runtime readiness was actually
evaluated; responses from older backends may omit the flag, in which case the
Settings mutation cache keeps the last probed runtime fields instead of
overwriting them with an unevaluated fallback — so the Settings UI shows
whether `lark-cli` will actually be present in the sandbox at chat time, rather
than a green status hiding a later `command not found`.

The optional [Lark CLI broker image](../../docker/lark-cli-broker/README.md) bundles
its required Python helper modules, so the sidecar runs without a separate
DeerFlow harness installation.

In Lark broker mode, AIO's fresh Bash runs close inherited pipe stdin. Persistent
terminal commands keep their input; the shim ignores terminal stdin. Explicit
pipelines, heredocs, and file redirections still supply input normally, and the
shim forwards that input only after EOF. A stdin idle timeout aborts without
executing the command, and broker execution logs omit argument values. See the
[broker image guide](../../docker/lark-cli-broker/README.md) for timeout settings and
image rebuild requirements.

If a trusted operator manages the configured skills directory through an external mount such as MinIO, NFS, or CSI, an administrator can call `POST /api/skills/reload` after changing files. This invalidates skill prompt caches in the handling Gateway process, waits up to the bounded refresh timeout, and then advances a durable reset marker (`.extensions_config.json.skills-cache-reset.json`) in the writable config directory. Every Gateway worker or Pod mounting that directory notices the marker within about a second of its next prompt build and rescans the latest files, so one call reaches every replica sharing the volume; the response reports `scope: shared_config`, or `scope: process` when no extensions config path is available. Running tasks are unchanged. Skill installs, edits, deletions, rollbacks and enable/disable toggles made through the API publish the same marker, so a change made on one replica takes effect on the others without a restart. A loader-level filesystem failure returns a generic server error and preserves the last successfully loaded process cache rather than publishing an empty catalog. Replicas with independent filesystems are not covered. Direct mount writes bypass the validation, SkillScan, and history applied by DeerFlow's install/edit APIs, so only operator-controlled systems should have write access.

Skill installs and agent-managed skill edits run through **SkillScan**, a native deterministic safety scanner before the LLM-based skill scanner. Phase 1 runs offline with no Semgrep/OpenGrep dependency, blocks high-confidence `CRITICAL` findings such as private keys or shell execution, and passes warning findings to the LLM scanner for contextual review. Code files (anything under `scripts/`, a script suffix such as `.py`, `.sh`, or `.js`, or an extensionless file starting with `#!`) that are not NUL-free UTF-8 text raise a warning and are still analyzed over a lossy decode, so a single stray byte cannot hide them from `CRITICAL` checks. The moderation adapter normalizes both plain-text model responses and LangChain Responses API text blocks before parsing the required JSON decision. Python instance-client exfiltration checks follow a minimal same-scope evidence chain: a simple name bound to a known client constructor, optional name-to-name aliases, and an actual outbound method or context-manager use supported by that constructor. Constructor roots must be proven imports; bare canonical-looking names are not inferred as modules. Nested scopes do not inherit client handles and inherit only constructor import aliases that are never rebound in the enclosing scope. Comprehensions, walrus-bearing statements, annotations, complex binding targets, unsupported operations, and ambiguous branch flows produce no finding from this signal; skipped constructs conservatively invalidate every name they may bind so stale client state cannot create a finding. A deterministic work budget or recursion limit reached by this best-effort analysis does not discard findings already collected for the file. Set `skill_scan.enabled: false` in `config.yaml` to disable only the deterministic analyzers; safe archive extraction and the LLM scanner still run.

Windows scripts (`.bat`, `.cmd`, `.ps1`, `.psm1`, `.js`, `.jse`, `.vbs`, `.vbe`, `.wsf`), HTML applications (`.hta`), and scriptlets (`.sct`) count as code even outside `scripts/`, regardless of filename case. They receive both SkillScan analysis and the installer's executable-code policy.
SkillScan warns about remote downloads piped into common shells, including `env` launchers, sudo, interpreter paths, and shell line continuations. It distinguishes environment dumps from `env` commands, including assignments and GNU split-string escapes. Shell parsing and split expansion are bounded; reaching a limit preserves critical findings already detected. Pipes to non-shell tools such as `jq` and `tee` do not trigger this warning.

SkillScan treats HTTP/HTTPS scheme spellings and HTTP hostnames case-insensitively and recognizes bracketed IPv6
loopback (`[::1]`) hosts as local. Raw brackets in the URL's userinfo make it count as outbound for
exfiltration checks. External IPv6 endpoints still trigger network findings,
and cloud-metadata hostname detection is case-insensitive.

SkillScan recognizes unquoted integer model-usage counters such as `total_tokens` and `input_tokens` in skill examples as measurements. Benchmark token statistics and signed deltas are also recognized; credential fields and other string values remain subject to secret detection.

For Python credential mappings, SkillScan checks literal values while treating ordinary dictionary keys as labels. A mapping such as `tokens = {"access_token": os.getenv("ACCESS_TOKEN")}` does not report a hardcoded credential. Keys matching a recognized cloud or API token format are still checked as embedded credentials.

SkillScan blocks embedded legacy and modern `sk-` API tokens, including OpenAI project, service-account, and admin keys and Anthropic keys, even in Bearer headers without a secret assignment. Token bodies may contain `-` and `_`; finding evidence is fully redacted. Placeholder examples do not suppress detection of later credentials in the same file. Scheduled-task notification summaries also redact these key formats before sending them to external IM platforms.

DeerFlow also ships with **skill-reviewer**, a public skill for read-only skill quality review. It uses the built-in `review_skill_package` tool to inspect installed skills, local packages, archives, or pasted `SKILL.md` content without activating the target skill, binding its secrets, executing its scripts, or installing it. The tool returns a compact, tag-neutralized JSON payload to the model context and keeps the full raw review payload in the tool artifact for programmatic consumers. The deterministic review core reuses DeerFlow parsing and SkillScan facts, emits versioned JSON contracts under `contracts/skill_review/`, and can be run from the backend CLI:

```bash
cd backend
uv run python -m deerflow.skills.review.cli ../skills/public/data-analysis --format text --fail-on error --fail-on-incomplete
```

Public-skill CI waivers are exact, expiring exceptions in `.github/skill-review-waivers.v1.json`. Because only the trusted base manifest can suppress a finding, a file-changing pull request can be preauthorized safely by first merging a manifest-only change that lists the reviewed future full-file SHA-256 in `preapproved_file_sha256s`; the file change can then land in a later pull request.

Tools follow the same philosophy. DeerFlow comes with a core toolset — web search, web fetch, rendered web capture, file operations, bash execution — and supports custom tools via MCP servers and Python functions. The bundled DDG, Brave, Tavily, SearXNG, and Serper search providers accept an optional `time_range` of `day`, `week`, `month`, or `year`; omitting it preserves existing search behavior. For DDG recency searches, DeerFlow excludes DDGS backends that ignore time limits. Swap anything. Add anything.

For DDG web search and DDG image search, `max_results` in `config.yaml` can be a positive integer or an environment-variable reference such as `max_results: $DDG_MAX_RESULTS` with `DDG_MAX_RESULTS=5`. The configured value takes precedence over the tool call's `max_results` argument. Invalid values (for example, `abc`, an empty string, or `3.5`), zero, and negative counts produce a warning and fall back to the default of 5 results. DDG, Brave, and Serper image search share one result-URL screen that omits non-HTTP(S), localhost, cloud-metadata hostnames, and non-public address literals, including multicast and IPv6 spellings embedding private IPv4 addresses. The screen does not resolve DNS; downloaders must validate the resolved address when connecting. A result with neither a safe full image URL nor a safe thumbnail is omitted.

Image result screening also recognizes Unicode hostname separators (`。`, `．`,
`｡`) as dots, matching IDNA client normalization before classifying local/private
hosts. Accepted result URLs retain their original spelling.

DDG image search reports timeouts, rate limits, and setup failures as search errors with the original query. `No images found` is reserved for a returned empty result set. The SDK's `No results found.` exception remains a search error because it can also hide an unfinished backend request; this conservatively includes SDK exceptions from genuinely empty searches whose completion cannot be confirmed.

Stdio MCP servers can set `cwd` in `extensions_config.json` when their entrypoint
or data files depend on a specific working directory. The setting applies to
both discovery and tool calls; see [MCP configuration](../../backend/docs/MCP_SERVER.md#stdio-working-directory).
Omitted, `null`, or empty values keep the default working directories.

Tavily `web_search` also accepts optional `include_domains` and `exclude_domains`
lists in its `config.yaml` tool entry to control search sources. Non-empty
`include_domains` uses Tavily's `filter` mode to restrict results to those domains.
These are deployment settings; the model still supplies only `query` and optional
`time_range`. Omitted filters preserve the existing SDK request; an explicit
empty list is forwarded and imposes no restriction of that kind. See the
[tool configuration example](../../backend/docs/CONFIGURATION.md#tools).

Serper web and image search can use another Serper-compatible provider through
`SERPER_BASE_URL` and that provider's `SERPER_API_KEY`. Each tool can instead set
its own `base_url` and `api_key` in `config.yaml`; each request reads them from
one configuration snapshot. Use an absolute HTTP(S) base URL with a host,
without `/search`, `/images`, a query string or a fragment. Invalid overrides
return a configuration error before HTTP; blank environment values keep
Serper's default unless a tool overrides them. See
[Serper endpoints](../../backend/docs/CONFIGURATION.md#serper-endpoints) for precedence
and how the provider receives the API key.

Serper `web_search` supports deployment-level `include_domains` and
`exclude_domains` too. It checks returned URL hosts (including subdomains), with
exclusion taking precedence. Filters can return fewer results, including zero;
there are no refill requests. This selects sources, not factual accuracy or a
global URL-access policy. The model arguments and image search are unchanged.
See [Serper configuration](../../backend/docs/CONFIGURATION.md#serper-source-filters)
for validation and query-length limits.

Serper web and image search support opt-in transient recovery with
`max_retries: 1` (default `0`, maximum `3`) in each tool's configuration.
`retry_budget_seconds` bounds retry scheduling, not active synchronous requests.
Budget exhaustion is logged separately while the tool returns the last error.
Extra requests may consume quota or incur cost. See
[Serper retries](../../backend/docs/CONFIGURATION.md#serper-retries).

When using Tavily for `web_fetch`, extracted pages without a title use their URL
as the heading; their content remains available to the agent.
For providers that use the shared Readability extractor, Readability.js is
optional. DeerFlow caches an unavailable Node.js toolchain or failed process
launch and uses the existing Python fallback for later fetches instead of
repeatedly starting a missing toolchain. A non-zero extraction exit falls back
only for that document, because malformed or oversized input can fail while
the toolchain remains healthy. The fallback keeps resolved article links in
the returned Markdown.
Chat tool-step titles accept leading blank lines and up to three spaces before
a page's first H1 heading. Indented code, including mixed spaces and tabs, is
not used as a title; the tool step falls back to the URL.
Tavily search and fetch each read `api_key` from their own tool entry in
`config.yaml`, falling back to `TAVILY_API_KEY` when omitted. Fetch does not
reuse the search entry's key, so search can use a different provider. If you
previously configured a shared Tavily key only under `web_search`, also set it
under `web_fetch` or use `TAVILY_API_KEY` for both.

For news-focused research, select **Webz.io News Search** in `make setup`, or
replace the `web_search` tool's `use` with
`deerflow.community.webz.tools:web_search_tool` and set `WEBZ_API_KEY`.
An explicit tool `api_key` takes precedence over the environment variable.
An explicit call's `max_results` overrides the configured default; omission
uses configuration or 5 (clamped to 1–100). Invalid configured counts, including
booleans and fractional numbers, fall back to 5. Results include the matching
passage, title, URL, publication date, and source metadata. The chat search step
displays source titles and links, including after reloading a conversation, and
skips malformed source entries without losing valid links. `returned_results`
counts the returned page, not all matching news articles. Malformed entries are
skipped with a warning while valid entries are retained; invalid responses or
pages with no valid entries return an error. Empty result lists remain valid. The tool accepts
language, country, source-domain, sentiment, category, and publication-date
filters. Its `time_range` maps to a UTC lower date bound of 1, 7, 30, or 365
days; an explicit `published_from` overrides that bound. Webz searches recent
news rather than the general web: date filters cannot extend the provider's
[documented 30-day coverage](https://docs.webz.io/docs/webz/news-search-api-response-format).

## Exporting Custom Skills

Administrators can export their own custom skills from **Capability Center → Skills → My skills → View details → Export**. Review the file list and declared environment requirements, then choose **Download .skill**. The archive contains the currently saved skill, including supporting files and empty directories; disabled skills can also be exported. If the skill changes after preview, refresh the file list before downloading. Import the archive on another DeerFlow instance with **Install .skill**; existing-name conflicts and normal installation security checks still apply.

Account settings, conversations and history outside the skill folder are excluded. Files inside the folder are preserved unchanged, including any credentials an author placed there; filename notices are advisory. Configure dependencies and credentials on the destination. Linked folders/files, hard links, unsupported executable binaries, nested `SKILL.md` files and nonportable paths cannot be exported. Export supports hosts with descriptor-relative no-follow filesystem APIs (Linux/macOS); unsupported hosts fail explicitly. Limits: 4096 ZIP entries, 64 MiB per file, 100 MiB total content/archive and 1 MiB frontmatter. YAML aliases and excessively complex declarations are not supported. Ordinary script executable semantics are preserved on POSIX import, without restoring special permissions. See [the export API contract](../../backend/docs/API.md#export-a-custom-skill).

## Claude Code Integration

The `claude-to-deerflow` skill lets you interact with a running DeerFlow instance directly from [Claude Code](https://docs.anthropic.com/en/docs/claude-code). Send research tasks, check status, manage threads — all without leaving the terminal.

**Install the skill**:

```bash
npx skills add https://github.com/bytedance/deer-flow --skill claude-to-deerflow
```

Then make sure DeerFlow is running (default at `http://localhost:2026`) and use the `/claude-to-deerflow` command in Claude Code.

**What you can do**:
- Send messages to DeerFlow and get streaming responses
- Choose execution modes: flash (fast), standard, pro (planning), ultra (sub-agents)
- Check DeerFlow health, list models/skills/agents
- Manage threads and conversation history
- Upload files for analysis

**Environment variables** (optional, for custom endpoints):

```bash
DEERFLOW_URL=http://localhost:2026            # Unified proxy base URL
DEERFLOW_GATEWAY_URL=http://localhost:2026    # Gateway API
DEERFLOW_LANGGRAPH_URL=http://localhost:2026/api/langgraph  # LangGraph API
```

See [`skills/public/claude-to-deerflow/SKILL.md`](../../skills/public/claude-to-deerflow/SKILL.md) for the full API reference.

## Script workflows (optional extension)

The [script workflows extension](../../examples/deerflow-extension-workflows/README.md)
adds inspectable JavaScript orchestration through full AgentRuns, background launch,
bounded parallel execution, progress, retained results and cancellation. It is
disabled by default and requires a POSIX Gateway and operator-authorized Agent
references. Versioned definitions, retained step outputs, live-process pause/resume
and authenticated human checkpoints support staged inspection reports. Confirmation
binds the exact retained output or captured file version (SHA-256); preview and
downstream reads use the same immutable bytes. Each child retains host-generated
assembly evidence for its resolved instructions, model, tools and Skills.
Cancelling a recoverable workflow continues child cleanup even if the requesting browser disconnects.
After a Gateway restart, sign in and select **Recover workflow** to recover a compatible run using retained results and exact-version approvals. Uncertain child admissions require reconciliation; they are never automatically retried. Recovery requires unchanged runtime/configuration and durable Gateway storage. The optional PostgreSQL mode supports cross-Gateway controls and session-authorized takeover after lease expiry, with fenced child admission and shared limits; see the extension deployment contract. Expired cancellations can be taken over for cleanup even at workflow admission limits. Definitive pre-admission permission/configuration rejection releases child capacity; uncertain admissions retain their reservations. SQLite remains single-Gateway. The [deployed acceptance and delivery boundary](../../examples/deerflow-extension-workflows/README.md#deployed-acceptance-and-delivery-boundary) documents real two-Gateway fault tests, session-authorized takeover, and the still-open reconciliation API/UI. There is no hard monetary budget. Workflow deadlines and child-observation timeouts are
reported separately from uncertain admission. Accepted launches retain their request
identity across inspection refresh failures, with a separate inspection retry action. A runnable example, installation steps
and QuickJS source-build prerequisites for other Python/CPU combinations are included.

## InfoQuest HTTP timeouts

InfoQuest reader, web search, and image search use a 30-second HTTP connect/read
inactivity timeout. The crawl `timeout` and `navigation_timeout` settings remain
separate server-side options; they do not control the local HTTP timeout.
