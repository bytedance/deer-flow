# Proposal: Per-User Persistent Home Mount (`/mnt/user-home/`)

**Status**: Draft (pre-brainstorming)
**Author**: raidery
**Date**: 2026-06-16
**Target milestone**: TBD (upstream 2.1.0 has related issue #2905)

---

## 1. Problem

DeerFlow's per-thread sandbox isolation is **too aggressive** for files that should
belong to a *user*, not a *thread*. Today, everything an agent (or a skill) writes
under `/mnt/user-data/{workspace,uploads,outputs}` lives inside
`backend/.deer-flow/users/{user_id}/threads/{thread_id}/user-data/` and disappears
the moment the thread is closed or the user starts a new chat.

### Concrete pain points (observed locally)

A user installing a custom skill (`skills/custom/obsidian-skills`) and asking the
agent to bootstrap a vault runs into this:

| Item | Where the agent put it | Survives new session? |
|------|------------------------|-----------------------|
| `SKILL.md` definition | `skills/custom/obsidian-skills/SKILL.md` (host disk) | ✅ Yes |
| `obsidian.tar.gz`, `notesmd-cli` binary | `threads/{tid}/user-data/workspace/` | ❌ No |
| `vault/` (Obsidian notes) | `threads/{tid}/user-data/{workspace,outputs}/vault/` | ❌ No |
| `diary.md`, `2026-06-16.md` | `threads/{tid}/user-data/outputs/` | ❌ No |

The new session's `/mnt/user-data/workspace/` is empty. The agent has **no
mechanism** to discover or reuse files from prior threads.

### Adjacent pain points (from upstream issues)

- **#2905** (open, milestone 2.1.0) — A user-created skill (via `skill-creator`)
  lands in `/app/project` (a custom mount), not in `DEER_FLOW_HOST_SKILLS_PATH`,
  so the lead agent in a new chat can't see it. The reporter asks for skills to
  be auto-mounted to the sandbox from a per-user directory.
- **#3597** (open) — `playwright/mcp` writes files that DeerFlow can't read,
  because of per-user isolation plus sandbox path translation. The fix in
  **#3600** migrates MCP-produced files into the sandbox `outputs/`.
- **#1978** (open) — Production deployments still default to `hostPath` for
  `user-data` and `skills`, with PVC as an opt-in. Data loss risk acknowledged.
- **#3539** (open) — IM channel files need to be scoped to the connection owner,
  a different angle on the same "per-user persistent storage" theme.
- **#3087** (open PR) — Adds regression tests for *existing* per-user
  isolation in `LocalSandboxProvider`. Confirms upstream takes per-user scoping
  seriously, but only for `user-data/`.

### Root cause (architectural)

There is **no first-class per-user persistent mount**. The existing layered
isolation is:

| Scope | Lifetime | Where |
|-------|----------|-------|
| Sandbox container | Per-thread, ephemeral | Docker / AIO container |
| `/mnt/user-data` | Per-thread | `users/{uid}/threads/{tid}/user-data/` |
| `/mnt/skills` | Per-user, but **read-only** | `deer-flow/skills/` |
| `memory.json`, `USER.md`, custom agents | Per-user, persistent, **metadata only** | `users/{uid}/{memory.json,USER.md,agents/}` |

The per-user *file* layer is missing. Skills are read-only by design, memory is
text, custom agents are template-only — none of them give the agent a writable,
generic, cross-thread home directory.

---

## 2. Goals

**G1.** Add a per-user, persistent, **writable** directory mounted into the
sandbox at a stable virtual path (proposed: `/mnt/user-home/`).

**G2.** Survival semantics: files in `/mnt/user-home/` outlive thread cleanup,
sandbox container restart, and gateway restart.

**G3.** Backwards compatible: existing `/mnt/user-data/...` behavior is
unchanged. The new mount is additive.

**G4.** Sandbox security model preserved: the mount is still scoped to a single
`user_id`; cross-user leakage is still impossible.

**G5.** Minimal blast radius: only config + sandbox + middleware + tools change.
No change to `ThreadState` semantics, no change to `memory.json` schema, no
required user config.

## 3. Non-Goals

- **NG1.** Not replacing `/mnt/user-data/...`. Thread isolation stays.
- **NG2.** Not changing the per-user `skills/` mount semantics. That stays
  read-only.
- **NG3.** Not introducing a new database table. Filesystem-backed only.
- **NG4.** Not solving the PVC / `hostPath` debate from #1978. The host path
  layout is what it is; PVC opt-in can be addressed in a follow-up.
- **NG5.** Not introducing cross-host synchronization. If the user runs two
  gateways on different machines, both pointing at the same NFS, they get
  whatever NFS gives them — that's #1978's territory.

---

## 4. Design Space (3 approaches)

### Approach A — Single flat directory at `/mnt/user-home/`

```
backend/.deer-flow/users/{user_id}/home/  →  /mnt/user-home/  (rw)
```

- Pros: simplest model, one mount, one path rule, no nested structure
  decisions. Matches "drop files here" mental model. The Obsidian vault, an
  installed CLI, and a `projects/` subdir all live side-by-side.
- Cons: junk-drawer risk over time. No "this is a tool, this is data"
  separation.

### Approach B — Linux `$HOME` style (XDG dirs)

```
backend/.deer-flow/users/{user_id}/home/  →  /mnt/user-home/  (rw, container's $HOME)
├── .config/    →  /mnt/user-home/.config/    (XDG_CONFIG_HOME)
├── .local/     →  /mnt/user-home/.local/     (XDG_DATA_HOME / XDG_BIN_HOME)
└── .cache/     →  /mnt/user-home/.cache/     (XDG_CACHE_HOME)
```

- Pros: Unix-standard. Many CLIs (rustup, npm with `--prefix`, pip user
  installs) work without env-var tricks. Tool/data separation is automatic.
  Easier to add size limits per category later.
- Cons: Hidden dirs confuse agents that don't know XDG. `$HOME` rewiring in the
  sandbox is non-trivial. The Obsidian vault placement is awkward (not in
  XDG). Most existing skills would need updates.

### Approach C — Hybrid: flat top-level + symlink `$HOME`

```
/mnt/user-home/  (flat, rw)
├── vault/
├── bin/notesmd-cli
└── projects/
$HOME  →  /mnt/user-home/   (symlink or env var)
```

- Pros: agents use simple paths; Unix tools that read `$HOME` work
  transparently. Best of both worlds.
- Cons: more wiring (env injection in sandbox, careful Docker
  bind-mount semantics). Two paradigms coexisting can confuse model
  reasoning about where files live.

### Recommendation: **Approach A** (flat)

Justification:
- The user's stated use case (Obsidian vault + installed CLI) is exactly the
  "drop files here" pattern.
- Upstream's existing skill mount (`/mnt/skills`) is already flat. Following
  the same convention reduces cognitive load.
- YAGNI: XDG structure is a v2 problem once we have evidence users are
  actually running Unix tools that need it.
- Approach C is too clever for the current user base. We can add a `$HOME`
  symlink later as a non-breaking enhancement.

---

## 5. Upstream Research Summary

| Issue / PR | State | Relevance |
|------------|-------|-----------|
| [#2905](https://github.com/bytedance/deer-flow/issues/2905) | Open, **milestone 2.1.0** | **Closest match** — asks for user-level mount, but scoped to skills only. Comment from `pangzhili` suggests moving to SQLite/Postgres for distributed (we disagree: filesystem is fine for v1). |
| [#1978](https://github.com/bytedance/deer-flow/issues/1978) | Open | Production data-loss risk with hostPath. PVC is opt-in. Our proposal is orthogonal — we just choose hostPath layout; PVC adoption is a follow-up. |
| [#3597](https://github.com/bytedance/deer-flow/issues/3597) + [#3600](https://github.com/bytedance/deer-flow/pull/3600) | Open | Playwright/MCP can't share paths with DeerFlow. The current fix migrates MCP files into `outputs/`. **Our proposal complements this**: MCP can write to `/mnt/user-home/` instead, surviving thread cleanup. |
| [#3087](https://github.com/bytedance/deer-flow/pull/3087) | Open PR | Hardens per-user isolation in `LocalSandboxProvider`. **Precedent for our pattern**: regression tests for path scoping exist, we should extend them. |
| [#2480](https://github.com/bytedance/deer-flow/issues/2480), [#2487](https://github.com/bytedance/deer-flow/pull/2487), [#2486](https://github.com/bytedance/deer-flow/pull/2486) | Open | `extra_mounts` support in k8s provisioner. **Good news**: AIO backend already accepts `extra_mounts` (see `community/aio_sandbox/local_backend.py:262, 570`). We just pass one more tuple. |
| [#1657](https://github.com/bytedance/deer-flow/pull/1657), [#1638](https://github.com/bytedance/deer-flow/pull/1638), [#3250](https://github.com/bytedance/deer-flow/pull/3250) | Merged | Sandbox mounts work end-to-end. The mechanism we're adding slots into the existing pipeline. |

**No existing PR or proposal for a first-class `/mnt/user-home/`**. This is
greenfield.

---

## 6. Proposed Approach (high level)

### Path layout

```
backend/.deer-flow/users/{user_id}/home/    ← host
                                            ↓ bind mount
/mnt/user-home/                              ← sandbox
```

### Files to change

| File | Change |
|------|--------|
| `backend/packages/harness/deerflow/config/paths.py` | Add `user_home_dir(user_id)` and `host_user_home_dir(user_id)` methods. |
| `backend/packages/harness/deerflow/agents/middlewares/thread_data_middleware.py` | Inject `user_home_path` into `ThreadDataState`. |
| `backend/packages/harness/deerflow/sandbox/local/local_sandbox_provider.py` | Add `/mnt/user-home` mapping in `_build_thread_path_mappings` (line 189). |
| `backend/packages/harness/deerflow/sandbox/tools.py` | Extend `replace_virtual_paths_in_command` and path validators to recognize `/mnt/user-home/*`. |
| `backend/packages/harness/deerflow/community/aio_sandbox/local_backend.py` | Pass `extra_mounts=(user_home_host, /mnt/user-home, False)` in `create()` and `_start_container()`. |
| `backend/packages/harness/deerflow/community/aio_sandbox/remote_backend.py` | Relay the new mount in the create payload (parallel to #2486/#2281). |
| `config.example.yaml` | Optional `sandbox.user_home.container_path` field with default `/mnt/user-home`. Bump `config_version`. |
| `backend/tests/test_sandbox_tools_security.py` | New tests: `/mnt/user-home` path validation, traversal rejection, ACL. |
| `backend/tests/test_local_sandbox_virtual_path_contract.py` | New section: per-user home mapping, isolation between users. |
| `scripts/migrate_user_isolation.py` | Ensure existing users get an empty `home/` subdir. |

### Lifecycle rules

- `home/` is created lazily on first access (like `workspace/` is).
- `home/` is **never** deleted by `delete_thread_dir`.
- A new `delete_user_dir(user_id)` method is added for explicit user-data
  removal (e.g., GDPR-style), called manually, never automatically.
- The mount is read-write by default. A future opt-in `read_only: true` per
  user is possible but out of scope.

### Permission model

`/mnt/user-home/` inherits the existing `/mnt/user-data/` permission story:
mode `0o777` so the sandbox container (potentially a different UID) can write.
The sandbox user can read/write freely; the host can read/write freely.

### Backwards compatibility

- No existing virtual path changes. `/mnt/user-data/...` keeps current behavior.
- No required config change. If the `home/` directory doesn't exist for a
  user, the mount is skipped silently (degraded mode, like the per-thread
  workspaces are lazily created).
- Existing threads are unaffected. New threads get the new mount automatically.

---

## 7. Open Questions (need user input before design)

These are the questions that block the design doc. Per the brainstorming skill
they need user answers one at a time.

1. **Q1 — Directory shape** (Approach A / B / C). *Asking first.*
2. **Q2 — Write semantics**: read-write vs read-only-with-explicit-elevation.
3. **Q3 — Cleanup behavior**: when does `home/` get deleted? Never? On user
   removal only? Configurable?
4. **Q4 — Migration**: should we auto-backfill empty `home/` for the 24
   existing users? Or only on first access?
5. **Q5 — Path naming**: `/mnt/user-home/` vs `/mnt/persistent/` vs
   `$HOME` vs something else?
6. **Q6 — `$HOME` integration**: should the sandbox container's `$HOME` env
   point at `/mnt/user-home/`? (Helps Unix tools; hurts a tiny bit of
   clarity.)
7. **Q7 — Quotas / size limits**: is a runaway vault a real concern at this
   stage? (Defer if not.)
8. **Q8 — Interaction with `USER.md` and custom agents**: does `/mnt/user-home/`
   replace any existing per-user storage, or strictly complement?

---

## 8. Risks

- **R1.** Filesystem bloat — a user could fill the host disk. Mitigation: out
  of scope for v1; document a follow-up size-limit task.
- **R2.** Permission drift between host and container UIDs. Mitigation: same
  `0o777` pattern as `user-data/`; covered by existing tests.
- **R3.** Cross-mount confusion in agent reasoning. Mitigation: name it
  `user-home` so the model understands the semantic. The mount shows up in
  the agent's system prompt as `/mnt/user-home/`.
- **R4.** Breaking change to skill contracts. Mitigation: this is purely
  additive; no skill needs to change. Optional follow-up: update skills that
  currently copy to workspace to *also* persist to `user-home/`.

---

## 9. Success Criteria

- A user can put a file in `/mnt/user-home/vault/notes.md` in session N and
  read it from `/mnt/user-home/vault/notes.md` in session N+1.
- A user can install a CLI binary to `/mnt/user-home/bin/foo` and it remains
  executable in the next session.
- A new thread's `home/` is automatically created and mounted, with no
  manual config.
- `delete_thread_dir` does not touch `home/`.
- Two users on the same `thread_id` (impossible in practice, but tested) get
  isolated `home/` directories.
- All existing tests pass. New tests cover path validation, ACL, and
  cross-user isolation.

---

## 10. Out of Scope (deferred)

- PVC / distributed storage (#1978)
- Cross-host sync
- `$HOME` rewiring (could be added in v2 if XDG-style CLIs become a real
  pain)
- Size limits / quotas
- Per-file encryption
- Backup integration

---

## Next Step

Proceed to design-doc stage (`docs/superpowers/specs/2026-06-16-user-home-mount-design.md`)
once Q1–Q8 are answered.
