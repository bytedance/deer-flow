# DeerFlow TUI - Product and Engineering Spec

**Date**: 2026-06-13
**Status**: Draft, ready for RFC discussion
**Scope**: Hermes-like terminal UI for the DeerFlow 2.0 harness

**Revision 2026-06-24**: Reworked runtime ownership and session persistence after RFC #3540 feedback. The TUI runs embedded but reuses the same session/persistence layer (`ThreadMetaStore`) so terminal sessions are visible in the Web UI without running the Gateway. See [Runtime and Session Persistence](#runtime-and-session-persistence).

---

## Problem Statement

DeerFlow has a capable embedded Python client and a full Gateway/Web UI, but no first-class terminal workbench. A plain command set would help scripts, but it would not cover the interactive developer experience we actually want: a persistent, keyboard-driven TUI where users can chat, switch threads, inspect tools, manage files, view live execution, trigger slash commands, and keep context without opening the browser.

Hermes Agent's TUI is a useful reference point: the terminal UI is a modern interactive surface backed by the same runtime as the classic CLI, shares sessions and slash commands, supports modal overlays, non-blocking input, live session switching, status indicators, and a TTY-aware fallback path.

DeerFlow needs the same product shape:

1. A terminal-native primary interface for users who live in the shell.
2. The same agent behavior, memory, skills, MCP tools, sandbox behavior, and thread persistence as the web app and embedded client, converging on one shared session/persistence layer rather than a per-surface copy.
3. A richer interactive surface than one-shot commands can provide.
4. Scriptable headless commands for automation, but not as the center of the product.

## Solution

Build a first-party `deerflow` TUI backed by `DeerFlowClient`.

The default interactive path should be:

```bash
deerflow
deerflow --tui
deerflow chat
deerflow --continue
deerflow --resume THREAD_ID
```

The headless path should remain available for scripts:

```bash
deerflow chat --print "summarize this repo"
deerflow models list --json
deerflow threads list --json
```

The v1 TUI should run in embedded mode only. It should not require Gateway, frontend, nginx, or Docker services to be running, though it must honor the same `config.yaml`, `extensions_config.json`, runtime paths, sandbox configuration, tracing configuration, skills, memory, and checkpointer settings used by the rest of DeerFlow.

Remote HTTP/Gateway mode can be added later as a transport option. The first implementation should ship a dependable local terminal workbench.

## Runtime and Session Persistence

This is the most load-bearing decision in the spec, and the RFC discussion (#3540) surfaced two facts about the current codebase that the original draft glossed over:

1. **There is no single runtime today — there are two run paths that share only the agent factory.** The Web/Gateway surface executes runs through `run_agent()` (async `astream` + `StreamBridge` for SSE). `DeerFlowClient.stream()` executes runs synchronously and in-process. Both build the agent through the same `make_lead_agent` / `create_agent()` factory, but the run, streaming, and persistence orchestration around that factory is implemented twice and is not shared.
2. **Web UI session visibility is driven by `ThreadMetaStore`, not the checkpointer.** The Web UI lists conversations via `GET /api/threads/search`, which reads the `thread_meta` SQL table filtered by `user_id`. The Gateway creates a `thread_meta` row (with the authenticated `user_id`) on the first run of a thread. `DeerFlowClient` writes only to the checkpointer and never creates a `thread_meta` row, so a thread created from the TUI is invisible in the Web UI sidebar by default — even though both surfaces can load the same checkpoint if they already know the `thread_id`.

### v1 decision

The TUI stays **embedded** (no Gateway, frontend, nginx, or Docker dependency) but **reuses the same persistence layer** instead of a private copy:

1. The embedded run path writes `thread_meta` to the same store the Web UI reads, so terminal sessions appear in the Web UI sidebar **without the Gateway process running**. Web UI visibility requires the shared `thread_meta` store and a `user_id` — it does **not** require the Gateway HTTP API.
2. Because the embedded process has no authenticated user, v1 attributes embedded `thread_meta` rows to a single **local default user identity** resolved from config. Full multi-user auth/session switching stays out of scope.
3. `thread_meta` creation, token-usage tracking, and thread-title sync are factored into one shared module used by **both** `run_agent()` and `DeerFlowClient`, so the two run paths cannot drift on session bookkeeping. This converges "single runtime" from the agent-factory layer down to the session/persistence layer, which is where multi-surface consistency actually lives.
4. Reusing the Gateway HTTP API as the TUI transport was considered and deferred: it would give Web UI visibility and user scoping "for free" but requires a running service stack and an auth token, which defeats the standalone local-workbench goal. It remains a later transport option, not the v1 path.

## Reference Behavior From Hermes

The DeerFlow TUI should borrow product ideas, not implementation details, from Hermes:

1. Bare command launches an interactive terminal interface.
2. TUI is backed by the same runtime as non-interactive commands.
3. Sessions/threads are shared between TUI and headless invocations.
4. Slash commands work the same way across surfaces.
5. Input remains usable while the runtime initializes or while a run is active.
6. Model picker, thread picker, clarification prompts, and approvals render as overlays.
7. Tool and skill initialization appears progressively instead of blocking startup.
8. Alternate-screen rendering avoids scrollback clutter and flicker.
9. TTY detection falls back to single-query/headless behavior when interactive rendering is unavailable.
10. Interrupts can stop or redirect the active run without corrupting persisted thread state.

## User Stories

1. As a DeerFlow user, I want `deerflow` to open an interactive terminal UI, so that I can work without a browser.
2. As a DeerFlow user, I want to continue the most recent thread, so that I can resume work quickly.
3. As a DeerFlow user, I want to resume a specific thread by id or title, so that I can return to older work.
4. As a DeerFlow user, I want a fixed composer with multiline editing, so that long prompts are comfortable to write.
5. As a DeerFlow user, I want slash-command autocomplete, so that skills and commands are discoverable.
6. As a DeerFlow user, I want `/model` to open a model picker, so that model switching is not a fragile text-only workflow.
7. As a DeerFlow user, I want `/threads` or `/switch` to open a live thread switcher, so that I can move between active conversations.
8. As a DeerFlow user, I want `/skills` to browse enabled and available skills, so that I can understand what the agent can do.
9. As a DeerFlow user, I want tool calls and results to stream into a collapsible activity panel, so that I can inspect execution without losing the main answer.
10. As a DeerFlow user, I want uploads and generated artifacts visible in a side panel, so that file-heavy workflows stay manageable.
11. As a DeerFlow user, I want memory status and relevant injected facts visible on demand, so that persistent context is not mysterious.
12. As a DeerFlow user, I want MCP servers and built-in tools visible on demand, so that tool availability is clear.
13. As a DeerFlow user, I want status-line indicators for model, thread, token usage, run state, and sandbox mode, so that I know what environment I am driving.
14. As a DeerFlow user, I want to interrupt a running agent with `Ctrl+C` or a new message, so that I can redirect work without restarting the TUI.
15. As a DeerFlow user, I want clarification prompts to appear as focused overlays, so that I can answer them quickly.
16. As a DeerFlow user, I want file path paste handling, so that pasted paths can become uploads or prompt text intentionally.
17. As a DeerFlow user, I want command history and prompt drafts to survive transient UI redraws, so that I do not lose work.
18. As an automation author, I want headless `--print` and `--json` modes, so that TUI work does not remove scriptability.
19. As a maintainer, I want TUI tests at the UI-driver boundary, so that layout refactors do not silently break command behavior.
20. As a package consumer, I want an installed `deerflow` binary to launch the TUI, so that the harness feels like a product, not only a library.

## TUI Surface

### Launch Modes

| Command | Behavior |
|---|---|
| `deerflow` | Launch TUI when stdin/stdout are TTYs. |
| `deerflow --tui` | Force TUI and fail with a clear diagnostic if unavailable. |
| `deerflow --cli` | Force headless/classic command mode for one invocation. |
| `deerflow chat` | Launch the same TUI conversation surface. |
| `deerflow chat --print MESSAGE` | Single-query headless mode. |
| `deerflow --continue` | Resume most recent thread. |
| `deerflow --resume THREAD_ID_OR_TITLE` | Resume a specific thread. |
| `DEER_FLOW_TUI=1 deerflow` | Force TUI through environment. |

If TUI dependencies or a TTY are missing, bare `deerflow` should print a diagnostic and fall back to headless guidance rather than hanging or crashing.

### Layout

The TUI should use a predictable terminal workbench layout:

1. Header/banner: project root, active model, sandbox mode, memory state, enabled tool groups, enabled skills, MCP server summary.
2. Main transcript: user messages, streamed assistant deltas, final answers, and compact summaries of tool activity.
3. Activity panel: collapsible tool calls, tool results, subagent status, uploads, artifact writes, and custom stream events.
4. Side/session panel: current thread title/id, recent threads, live threads, uploaded files, generated artifacts.
5. Composer: multiline input, slash-command autocomplete, file attach affordances, paste handling.
6. Status line: run state, model, token usage, elapsed time, thread id/title, pending uploads, active tool/subagent count.

### Slash Commands

Slash commands should be TUI-owned affordances over existing DeerFlow capabilities:

| Command | TUI behavior |
|---|---|
| `/help` | Overlay with categorized commands and keybindings. |
| `/new` | Start a fresh thread. |
| `/resume THREAD` | Resume a thread. |
| `/threads` or `/switch` | Open thread switcher. |
| `/model` | Open model picker. |
| `/skills` | Open skill browser. |
| `/<skill-name> ...` | Activate a skill for the current turn, preserving existing slash-skill semantics. |
| `/tools` | Show built-in, MCP, sandbox, and community tool availability. |
| `/mcp` | Show MCP server status. |
| `/memory` | Show memory status and injected facts. |
| `/uploads` | Show uploaded files for the current thread. |
| `/artifacts` | Show generated artifacts and save/open actions. |
| `/details` | Toggle verbose activity rendering. |
| `/usage` | Open token usage/context panel. |
| `/config` | Show resolved config paths and active overrides. |
| `/quit` | Exit the TUI. |

### Keybindings

Initial keybindings:

| Key | Behavior |
|---|---|
| `Enter` | Send current prompt when composer is single-line or submit is explicit. |
| `Shift+Enter` / terminal-supported equivalent | Insert newline. |
| `Ctrl+C` | Interrupt active run; when idle, ask to quit or clear composer. |
| `Esc` | Close overlay or cancel current selection. |
| `Ctrl+L` | Redraw UI. |
| `Ctrl+R` | Open thread/session switcher. |
| `Ctrl+O` | Open file attach picker. |
| `Ctrl+D` | Toggle details/activity panel. |
| `Ctrl+U` | Clear composer. |
| `Ctrl+P` / `Ctrl+N` | Navigate history/autocomplete. |

Keybindings should be documented in `/help` and must degrade gracefully across terminals.

## Headless Command Surface

The TUI is the primary product, but scriptable commands should remain:

1. `deerflow chat --print MESSAGE`
2. `deerflow chat --stdin --print`
3. `deerflow chat --json MESSAGE`
4. `deerflow models list|get`
5. `deerflow skills list|get|enable|disable|install`
6. `deerflow mcp list|export|apply`
7. `deerflow memory status|show|export|import|clear|fact add|fact update|fact delete`
8. `deerflow uploads add|list|delete`
9. `deerflow artifacts get`
10. `deerflow threads list|get`

Headless JSON streaming should preserve `StreamEvent` semantics as newline-delimited JSON.

## Implementation Decisions

1. The console script name is `deerflow`.
2. The TUI is the default interactive surface for TTY sessions.
3. The TUI is backed by the embedded `DeerFlowClient` run path, not a new third runtime. Today `DeerFlowClient` and the Gateway's `run_agent()` share only the agent factory; v1 converges them on a shared session/persistence layer (see [Runtime and Session Persistence](#runtime-and-session-persistence)) instead of adding another divergent copy.
4. Thread persistence, streaming semantics, uploads, artifacts, skills, MCP, memory, and cache invalidation remain owned by `DeerFlowClient` and existing harness modules. Session indexing (`thread_meta`) plus token-usage and title bookkeeping move into one shared module so the embedded TUI writes the same session records the Web UI reads, attributed to a single local default `user_id`. Web UI visibility therefore needs the shared store, not the Gateway process.
5. The first TUI should prefer a Python-native TUI stack unless a prototype proves a Node/React terminal stack is materially better for DeerFlow. Python-native keeps packaging and runtime closer to the harness.
6. If a Node TUI is chosen, it must be launched by the Python `deerflow` command and communicate through a narrow local protocol so `DeerFlowClient` remains the runtime owner.
7. The TUI should support alternate-screen rendering, but headless mode and non-TTY fallback must remain available.
8. The TUI should render tool activity as first-class UI state rather than mixing every event into the transcript.
9. The implementation should avoid adding a Gateway dependency to local TUI mode.
10. The implementation must update user-facing README usage and backend development guidance when code lands.

## Testing Decisions

Good TUI tests should validate behavior at the highest practical seam:

1. Headless parser/dispatcher tests through `main(argv)`.
2. TUI app state tests using a mocked `DeerFlowClient` and synthetic `StreamEvent` objects.
3. Snapshot-like tests for layout state, not brittle terminal screenshots, for core panels and overlays.
4. Keybinding tests for send, interrupt, overlay close, thread switch, details toggle, and file attach.
5. Slash-command tests for command routing, autocomplete, and skill activation handoff.
6. JSON contract tests for headless mode.
7. Error tests for missing TTY, missing optional TUI dependency, invalid config, missing model, upload failures, and artifact path errors.
8. Packaging smoke test proving the console entry point launches the correct surface.

Optional live tests:

1. A skipped-by-default live TUI smoke test can run only when a valid local config and credentials are present.
2. Live tests should not be required in CI.

## Risks

1. Terminal compatibility: keybindings, paste handling, mouse support, and alternate screen differ across terminal emulators.
2. Streaming complexity: a pleasant UI needs careful state management for transcript, tool events, uploads, artifacts, and run lifecycle.
3. Config timing: global overrides must be applied before modules cache configuration.
4. Dependency footprint: a full TUI stack may add runtime dependencies that need packaging scrutiny.
5. Scope creep: a TUI can easily become a second web UI. V1 should focus on chat, threads, model/skill/tool visibility, uploads, artifacts, and interruptibility.
6. Run-path divergence: `run_agent()` and `DeerFlowClient` orchestrate runs separately. Factoring session indexing and bookkeeping into a shared module is required to keep terminal and web sessions consistent; skipping it reintroduces the visibility gap and silent drift.

## Out of Scope

1. Replacing the web UI.
2. Running or supervising Gateway/frontend/nginx services.
3. Remote HTTP transport to an already-running DeerFlow server.
4. Full desktop app.
5. Voice mode.
6. Shell completion generation.
7. Native Windows `cmd.exe` support beyond what the chosen TUI stack can reasonably support.
8. Multi-user auth/session switching.
9. Direct raw sandbox shell commands outside normal agent tool execution.
10. Reimplementing setup wizard or doctor checks before their logic is made reusable.

## Documentation Requirements

When implementation lands, update:

1. Quick Start docs with `deerflow`, `deerflow --tui`, `deerflow --continue`, and `deerflow chat --print`.
2. Backend development docs with the TUI architecture, module ownership, and test command.
3. Embedded client docs to explain that the TUI is a front-end over `DeerFlowClient`.
4. Any package/install docs that mention available console scripts.

## Further Notes

The core product decision is TUI-first, CLI-second. `deerflow` should feel like a terminal workbench for the DeerFlow harness. Headless commands still matter, but they support automation rather than define the interactive product.

The most important technical decision is runtime ownership. The TUI should be a UI shell over the existing embedded harness. It should not fork agent behavior away from `DeerFlowClient`, because that would split tests, persistence, streaming semantics, and tool behavior across surfaces. Concretely, v1 closes the existing split by moving session indexing and run bookkeeping into a layer shared by both `run_agent()` and `DeerFlowClient`, so terminal and web sessions stay consistent (see [Runtime and Session Persistence](#runtime-and-session-persistence)).
