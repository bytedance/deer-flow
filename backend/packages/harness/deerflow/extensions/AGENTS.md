# Python extensions (`deerflow/extensions/`)

Loads operator-installed Python extensions and composes what they contribute:
middleware, lifecycle observers, Gateway services and routers, knowledge providers
and full-stack plugins. `ExtensionManager` (behind `deerflow extensions ...`)
installs, upgrades and removes them. The public contract is the separate
`deerflow_extension_api` package. Related docs:
[full-stack plugins](../../../../../docs/full-stack-plugins.md),
[extension Agent runs](../../../../docs/extension-agent-runs.md),
[model invocation](../../../../docs/extension-model-invocation.md),
[knowledge contract](../../../../docs/KNOWLEDGE.md). Authoring guide:
`examples/README.md`.

## Verify

```bash
cd backend
python -m pytest tests -q -k "extension or plugin"
make test-blocking-io
```

Manager tests create temporary Git repositories with an empty repository-local
hook directory, so they never run a developer's or CI's Git hooks.

## Trust model

- **Extension code runs with Gateway privileges.** It is trusted, not sandboxed.
  For that reason the `plugins:` list in `config.yaml` is read at startup only and
  has no online write API. Everything a Gateway API can edit lives elsewhere.
- **Source checks prevent accidents, not attacks.** Snapshot filters (credential
  files, Git metadata) and source-form rules protect an operator from a packaging
  mistake. They do not make an untrusted source safe.
- **A required plugin that cannot load stops startup.** An optional one fails open
  with a diagnostic that names the extension. `required` is an explicit operator
  opt-in.
- **Unsupported registration returns False.** An old host must tell the extension
  that a contribution kind is unknown. Silently ignoring it hides a missing
  feature.

## Install, upgrade, remove

- **One transaction over four things.** The manager changes `pyproject.toml`,
  `uv.lock`, the managed `plugins:` block and the source snapshot together under
  `.deer-flow/extension-manager.lock`. A failure restores all of them, including
  file permission bits, and resynchronizes the environment.
- **A cleanup error never replaces the original error.** This includes
  interruptions during rollback.
- **Stop on a concurrent external edit.** When recovery finds that someone else
  changed the dependency files or the config, it reports that and does not
  overwrite the edit.
- **Local directories are installed as snapshots** under
  `backend/extensions/sources/`, not as editable links. The production image must
  be able to rebuild from the repository alone, so a source that only exists on
  the operator's machine (local wheel, `file://`, a path outside the project) is
  rejected, and the lock is audited for such references after every change.
- **Only the manager updates `backend/uv.lock` for extensions.** Production
  container startup never resolves or installs an extension.
- **The uv version is pinned in one place** (`UV_IMAGE` in `backend/Dockerfile`),
  and CI uses the same version. A newer uv elsewhere can write a lock that the
  production image cannot read.
- **Every mutation needs a Gateway restart**, because plugins load once at startup.
- **The `plugins:` block is rewritten in place.** Its boundaries come from the YAML
  parser, not from a text pattern, so that a neighbouring section with an unusual
  key is never replaced. A config with duplicate top-level `plugins:` keys is
  rejected.

## Composition

- **`extensions/` sits below `agents/` in the import graph.** Do not import the
  middleware layer here at module level. Resolve middleware classes at composition
  time.
- **`extensions/ordering.py` owns the ordering invariants** and validates the final
  composed chain. Contributed middleware declares a semantic placement; it is
  composed at one final point.
- **A failing extension does not fail the run.** Contributed middleware is wrapped
  by `IsolatedMiddleware`, and observer failures are contained per observer.
- **Cancellation is the exception.** A genuine cancellation of the run propagates
  through a contributor. A `CancelledError` that the contributor raised for its own
  reasons is contained like any other failure.
- **One extension snapshot per run.** The run worker loads the extension set once
  and passes that same object to the task store and to delegated subagents, so a
  run never mixes two extension generations.
- **The assembly descriptor is the record of what was built.** It fingerprints the
  resolved model, prompt hash, tool list, middleware order and policies. A wrapper
  that hides a contribution's policy parameters makes two different assemblies
  look identical.
- **Shutdown stops accepting detached observations before the memory flush**, so an
  accepted observation is never registered after shutdown began.

## Full-stack plugins and host access

- **Browser fields are allowlisted** and plugin JavaScript is served by content
  hash. Plugin actions require an authenticated session.
- **Agent run control goes through the `AgentRuns` handle.** The Gateway binds the
  principal, caps the permissions and revokes the handle before shutdown. Do not
  give an extension the global `RunManager`, a `ModelInvoker` as a substitute, or a
  user ID that the caller supplied.
- **Handles are scoped per plugin namespace**, so idempotency keys of two plugins
  cannot collide.
- **`configuration_revision` never exposes raw configuration.** It returns an HMAC.
  Sets hash the same way across process hash seeds; ordered lists keep their order.

## Extension-first exceptions

A feature that ships in core although an extension hook could express it is
recorded here with the reason.

- **Project-shelf summaries** (`projects/summaries.py`). The summary column, the
  `<documents>` index and the shelf tool output are core-owned, and a split design
  would have to enforce the sanitization invariants across a public write
  interface.
