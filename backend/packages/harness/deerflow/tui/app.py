"""The Textual application — a terminal workbench over the embedded harness.

The app keeps a single immutable :class:`ViewState` and re-renders it through the
pure renderers. Agent runs execute on a worker *thread* (``DeerFlowClient.stream``
is a synchronous generator); each yielded action is marshalled back onto the UI
thread via ``call_from_thread`` and folded into the reducer.
"""

from __future__ import annotations

import uuid
from functools import partial

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Input, Label, OptionList, Static
from textual.widgets.option_list import Option

from .input_history import InputHistory
from .render import render_header, render_status, render_transcript
from .runtime import stream_actions
from .theme import SYMBOLS, THEME
from .view_state import (
    ClearRows,
    RunEnded,
    RunStarted,
    SystemMessage,
    ThreadTitle,
    UserSubmitted,
    initial_state,
    reduce,
)
from .widgets.composer import ComposerInput

_HELP_TEXT = "Commands:  /new  /threads  /model  /skills  /tools  /mcp  /memory  /usage  /config  /quit\nKeys:  Enter send · Ctrl+C interrupt or quit · Ctrl+L redraw · / commands · Esc close overlay"


class SelectScreen(ModalScreen):
    """A centered modal that returns the id of the chosen option (or None)."""

    BINDINGS = [Binding("escape", "cancel", "Close")]

    def __init__(self, title: str, options: list[tuple[str, str]]) -> None:
        super().__init__()
        self._title = title
        self._options = options

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label(self._title, id="dialog-title")
            yield OptionList(*[Option(label, id=oid) for oid, label in self._options], id="dialog-list")

    def on_mount(self) -> None:
        self.query_one(OptionList).focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(event.option_id)

    def action_cancel(self) -> None:
        self.dismiss(None)


class DeerFlowTUI(App):
    CSS = f"""
    Screen {{
        background: {THEME.bg};
        color: {THEME.text};
    }}
    #header {{
        height: 1;
        padding: 0 1;
        background: {THEME.panel};
    }}
    #scroll {{
        height: 1fr;
        padding: 1 2;
        background: {THEME.bg};
        scrollbar-size-vertical: 1;
    }}
    #transcript {{
        width: 100%;
        height: auto;
    }}
    #status {{
        height: 1;
        padding: 0 1;
        background: {THEME.panel};
        color: {THEME.muted};
    }}
    #palette {{
        height: auto;
        max-height: 10;
        margin: 0 1;
        padding: 0 1;
        background: {THEME.panel};
        border: round {THEME.border};
        display: none;
    }}
    #palette.open {{
        display: block;
    }}
    #composer {{
        height: 3;
        margin: 0 1 1 1;
        border: round {THEME.border};
        background: {THEME.panel};
    }}
    #composer:focus {{
        border: round {THEME.primary};
    }}
    SelectScreen {{
        align: center middle;
    }}
    SelectScreen #dialog {{
        width: 72;
        max-width: 90%;
        height: auto;
        max-height: 80%;
        padding: 1 2;
        background: {THEME.panel};
        border: round {THEME.primary};
    }}
    SelectScreen #dialog-title {{
        color: {THEME.primary};
        text-style: bold;
        padding: 0 0 1 0;
    }}
    SelectScreen OptionList {{
        background: {THEME.panel};
        border: none;
        height: auto;
        max-height: 20;
    }}
    SelectScreen OptionList > .option-list--option-highlighted {{
        background: {THEME.primary};
        color: {THEME.bg};
    }}
    """

    BINDINGS = [
        Binding("ctrl+c", "interrupt", "Interrupt / Quit", priority=True, show=True),
        Binding("ctrl+l", "redraw", "Redraw", show=False),
        Binding("ctrl+u", "clear_composer", "Clear input", show=False),
        # Up/Down drive the palette when it's open, otherwise input history.
        # Tab/Enter/Esc only act when the palette is open. check_action gates all
        # of these so they never steal keys from a modal overlay or the composer.
        Binding("down", "nav_down", show=False, priority=True),
        Binding("up", "nav_up", show=False, priority=True),
        Binding("tab", "palette_complete", show=False, priority=True),
        Binding("escape", "escape", show=False, priority=True),
        Binding("enter", "palette_accept", show=False, priority=True),
    ]

    def __init__(self, session, plan) -> None:
        super().__init__()
        self.session = session
        self.plan = plan
        self.state = initial_state()
        self._conv_thread_id: str | None = None
        self._model = ""
        self._skill_names: list[str] = []
        self._skills = 0
        self._spinner_idx = 0
        self._streaming = False
        self._cancelled = False
        self._skills_meta: list[dict] = []
        self._model_override: str | None = None
        self._palette_open = False
        self._palette_items: list = []
        self._palette_index = 0
        self._history = InputHistory()
        self._transcript_dirty = False

    # ----- composition --------------------------------------------------- #

    def compose(self) -> ComposeResult:
        yield Static(id="header")
        with VerticalScroll(id="scroll"):
            yield Static(id="transcript")
        yield Static(id="status")
        yield Static(id="palette")
        yield ComposerInput(placeholder="Message DeerFlow…   ( / for commands )", id="composer")

    def on_mount(self) -> None:
        self._load_session_info()
        self._refresh_all()
        self.set_interval(0.1, self._tick_spinner)
        self.set_interval(0.06, self._flush_transcript)  # coalesce streaming re-renders
        self.query_one("#composer", Input).focus()
        if self.plan and getattr(self.plan, "message", None):
            self._send_to_agent(self.plan.message)

    # ----- session info -------------------------------------------------- #

    def _load_session_info(self) -> None:
        self._conv_thread_id = self.session.resolve_thread(self.plan) if self.plan else None
        client = self.session.client
        try:
            models = client.list_models().get("models", [])
            self._model = next((m.get("display_name") or m.get("name") for m in models if m.get("name")), "")
        except Exception:  # noqa: BLE001 - header is best-effort
            self._model = ""
        try:
            skills = client.list_skills(enabled_only=True).get("skills", [])
            self._skills_meta = [s for s in skills if s.get("name")]
            self._skill_names = [s["name"] for s in self._skills_meta]
            self._skills = len(self._skill_names)
        except Exception:  # noqa: BLE001
            self._skills_meta = []
            self._skill_names = []
            self._skills = 0

    # ----- input --------------------------------------------------------- #

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        event.input.value = ""
        self._close_palette()
        if not text:
            return
        self._history.add(text)
        self._handle_submit(text)

    def on_input_changed(self, event: Input.Changed) -> None:
        value = event.value
        if value.startswith("/") and " " not in value:
            from .command_registry import build_registry, filter_commands

            items = filter_commands(build_registry(self._skills_meta), value[1:])
            # The candidate set changed, so the previous highlight index is stale —
            # reset to the top rather than clamping to a now-different command.
            self._palette_index = 0
            self._open_palette(items)
        else:
            self._close_palette()

    # ----- slash command palette ----------------------------------------- #

    def check_action(self, action: str, parameters):  # noqa: D401 - Textual hook
        custom = {"nav_up", "nav_down", "palette_complete", "palette_accept", "escape"}
        if action in custom:
            # A modal overlay (e.g. the model/thread picker) is on top — never
            # intercept its keys; let the overlay handle them natively.
            if len(self.screen_stack) > 1:
                return None
            # nav (history), Tab and Esc are always consumed (Tab can't move focus
            # off the composer; Esc closes the palette or interrupts a run). Enter
            # falls through to the Input when the palette is closed so it submits.
            if action in {"nav_up", "nav_down", "palette_complete", "escape"}:
                return True
            return True if self._palette_open else None
        return True

    def action_nav_up(self) -> None:
        if self._palette_open:
            self.action_palette_up()
        else:
            self._history_move(self._history.up(self.query_one("#composer", Input).value))

    def action_nav_down(self) -> None:
        if self._palette_open:
            self.action_palette_down()
        else:
            self._history_move(self._history.down())

    def _history_move(self, value: str) -> None:
        composer = self.query_one("#composer", Input)
        composer.value = value
        composer.cursor_position = len(value)

    def _open_palette(self, items: list) -> None:
        if not items:
            self._close_palette()
            return
        self._palette_items = items
        self._palette_index = min(self._palette_index, len(items) - 1)
        self._palette_open = True
        palette = self.query_one("#palette", Static)
        palette.add_class("open")
        self._render_palette()

    def _close_palette(self) -> None:
        if not self._palette_open and not self._palette_items:
            return
        self._palette_open = False
        self._palette_items = []
        self._palette_index = 0
        self.query_one("#palette", Static).remove_class("open")

    def _render_palette(self) -> None:
        from .render import render_palette

        self.query_one("#palette", Static).update(render_palette(self._palette_items, self._palette_index))

    def _current_palette_item(self):
        if 0 <= self._palette_index < len(self._palette_items):
            return self._palette_items[self._palette_index]
        return None

    def action_palette_down(self) -> None:
        if self._palette_items:
            self._palette_index = min(self._palette_index + 1, len(self._palette_items) - 1)
            self._render_palette()

    def action_palette_up(self) -> None:
        if self._palette_items:
            self._palette_index = max(self._palette_index - 1, 0)
            self._render_palette()

    def action_palette_complete(self) -> None:
        # When the palette is open, Tab completes the highlighted command.
        # When it's closed, Tab is a no-op here (consumed) so focus stays in the
        # composer instead of moving to the scroll region.
        if self._palette_open:
            self._fill_from_palette()

    def action_palette_accept(self) -> None:
        item = self._current_palette_item()
        if item is None:
            return
        if getattr(item, "category", "") == "skill":
            # Skills need a task argument; fill and let the user keep typing.
            self._fill_from_palette()
            return
        self._close_palette()
        self.query_one("#composer", Input).value = ""
        self._handle_submit(f"/{item.name}")

    def _fill_from_palette(self) -> None:
        item = self._current_palette_item()
        if item is None:
            return
        composer = self.query_one("#composer", Input)
        composer.value = f"/{item.name} "
        composer.cursor_position = len(composer.value)
        self._close_palette()

    def _handle_submit(self, text: str) -> None:
        from .command_registry import resolve

        res = resolve(text, skills=self._skill_names)
        if res.kind == "builtin":
            self._handle_builtin(res.name, res.args)
            return
        if res.kind == "unknown":
            self._dispatch(SystemMessage(f"Unknown command /{res.name}. Try /help.", tone="error"))
            return
        # plain message or skill activation (/skill task) both go to the agent,
        # which applies skill-activation semantics on the raw text.
        self._send_to_agent(text)

    def _handle_builtin(self, name: str, args: str) -> None:
        if name == "quit":
            self.exit()
        elif name == "help":
            self._dispatch(SystemMessage(_HELP_TEXT))
        elif name == "new":
            self._conv_thread_id = None
            self.state = initial_state()
            self._dispatch(SystemMessage("Started a new thread."))
        elif name == "clear":
            self._dispatch(ClearRows())
        elif name == "model":
            self._open_model_picker()
        elif name in {"threads", "switch"}:
            self._open_thread_switcher()
        elif name == "resume":
            self._resume_thread(args)
        elif name == "skills":
            self._show_skills()
        elif name == "mcp":
            self._show_mcp()
        elif name == "memory":
            self._show_memory()
        elif name == "usage":
            self._show_usage()
        elif name == "config":
            self._show_config()
        elif name == "tools":
            self._dispatch(SystemMessage("Tools are listed in the agent's runtime; use /mcp for MCP servers."))
        elif name == "uploads":
            self._show_uploads()
        elif name == "artifacts":
            self._dispatch(SystemMessage("Artifacts appear inline as the agent writes them.", tone="info"))
        elif name == "details":
            self._dispatch(SystemMessage("Verbose activity is always shown in this build.", tone="info"))
        else:
            self._dispatch(SystemMessage(f"/{name} is not available yet.", tone="info"))

    # ----- overlays + info commands -------------------------------------- #

    def _open_model_picker(self) -> None:
        try:
            models = self.session.client.list_models().get("models", [])
        except Exception:  # noqa: BLE001
            models = []
        options = [(m["name"], (m.get("display_name") or m["name"])) for m in models if m.get("name")]
        if not options:
            self._dispatch(SystemMessage("No models configured.", tone="error"))
            return

        def on_choice(choice: str | None) -> None:
            if choice:
                self._model_override = choice
                self._model = choice
                self._dispatch(SystemMessage(f"Model set to {choice}."))
                self._refresh_header()

        self.push_screen(SelectScreen("Select model", options), on_choice)

    def _open_thread_switcher(self) -> None:
        try:
            threads = self.session.recent_threads(limit=20)
        except Exception:  # noqa: BLE001
            threads = []
        options: list[tuple[str, str]] = []
        for thread in threads:
            tid = thread.get("thread_id")
            if not tid:
                continue
            title = thread.get("title") or "untitled"
            options.append((tid, f"{title}   ·   {tid[:8]}"))
        if not options:
            self._dispatch(SystemMessage("No saved threads yet."))
            return

        def on_choice(choice: str | None) -> None:
            if choice:
                self._switch_to_thread(choice)

        self.push_screen(SelectScreen("Resume thread", options), on_choice)

    def _resume_thread(self, ref: str) -> None:
        """/resume [id-or-title]: switch to a thread, or open the picker if blank."""
        ref = ref.strip()
        if not ref:
            self._open_thread_switcher()
            return
        self._switch_to_thread(self.session.resolve_ref(ref))

    def _switch_to_thread(self, thread_id: str) -> None:
        self._conv_thread_id = thread_id
        self.state = initial_state()
        self._dispatch(SystemMessage(f"Resumed thread {thread_id[:8]}."))
        self._refresh_header()

    def _show_skills(self) -> None:
        names = ", ".join(self._skill_names) or "none"
        self._dispatch(SystemMessage(f"Enabled skills ({self._skills}): {names}"))

    def _show_mcp(self) -> None:
        try:
            servers = self.session.client.get_mcp_config().get("mcp_servers", {})
        except Exception:  # noqa: BLE001
            self._dispatch(SystemMessage("Could not read MCP config.", tone="error"))
            return
        if not servers:
            self._dispatch(SystemMessage("No MCP servers configured."))
            return
        lines = [f"{name}: {'on' if cfg.get('enabled') else 'off'}" for name, cfg in servers.items()]
        self._dispatch(SystemMessage("MCP servers — " + "  ·  ".join(lines)))

    def _show_memory(self) -> None:
        try:
            data = self.session.client.get_memory()
        except Exception:  # noqa: BLE001
            self._dispatch(SystemMessage("Could not read memory.", tone="error"))
            return
        facts = data.get("facts", []) if isinstance(data, dict) else []
        top = (data.get("topOfMind") if isinstance(data, dict) else "") or "—"
        self._dispatch(SystemMessage(f"Memory: {len(facts)} facts · top of mind: {top}"))

    def _show_usage(self) -> None:
        usage = self.state.usage or {}
        if not usage:
            self._dispatch(SystemMessage("No token usage recorded yet."))
            return
        parts = ", ".join(f"{k}={v}" for k, v in usage.items())
        self._dispatch(SystemMessage(f"Token usage — {parts}"))

    def _show_config(self) -> None:
        import os

        self._dispatch(SystemMessage(f"cwd: {os.getcwd()}   model: {self._model or 'default'}"))

    def _show_uploads(self) -> None:
        if not self._conv_thread_id:
            self._dispatch(SystemMessage("Start a thread before listing uploads."))
            return
        try:
            uploads = self.session.client.list_uploads(self._conv_thread_id).get("files", [])
        except Exception:  # noqa: BLE001
            self._dispatch(SystemMessage("Could not list uploads.", tone="error"))
            return
        if not uploads:
            self._dispatch(SystemMessage("No uploads in this thread."))
            return
        names = ", ".join(f.get("filename", "?") for f in uploads)
        self._dispatch(SystemMessage(f"Uploads ({len(uploads)}): {names}"))

    # ----- agent run ----------------------------------------------------- #

    def _send_to_agent(self, text: str) -> None:
        if self._streaming:
            self._dispatch(SystemMessage("Still working — wait for the current run to finish.", tone="info"))
            return
        if self._conv_thread_id is None:
            self._conv_thread_id = str(uuid.uuid4())
        self._cancelled = False
        self._dispatch(UserSubmitted(text))
        self.run_worker(
            partial(self._stream_worker, text, self._conv_thread_id),
            thread=True,
            exclusive=True,
            group="agent",
        )

    def _stream_worker(self, text: str, thread_id: str) -> None:
        kwargs: dict = {}
        if self._model_override:
            kwargs["model_name"] = self._model_override

        writer = getattr(self.session, "writer", None)
        if writer is not None:
            # Make this terminal session visible in the Web UI sidebar by writing a
            # threads_meta row under the local default user (best-effort, no-op on
            # memory backends). Done on this worker thread to keep the UI responsive.
            writer.ensure_created(thread_id, assistant_id="lead-agent", metadata={"source": "tui"})

        latest_title: str | None = None
        for action in stream_actions(self.session.client, text, thread_id=thread_id, **kwargs):
            if self._cancelled:
                break
            if isinstance(action, ThreadTitle):
                latest_title = action.title
            self.call_from_thread(self._on_action, action)

        # Only persist a title for a run that completed normally — an interrupted
        # run may only have emitted the title middleware's first, truncated guess.
        if writer is not None and latest_title and not self._cancelled:
            writer.set_title(thread_id, latest_title)

    def _on_action(self, action) -> None:
        self.state = reduce(self.state, action)
        if isinstance(action, RunStarted):
            self._streaming = True
            self._transcript_dirty = True
        elif isinstance(action, RunEnded):
            self._streaming = False
            # Flush now so the finished message snaps to its Markdown rendering.
            self._transcript_dirty = False
            self._refresh_transcript()
        else:
            # Coalesce rapid streaming deltas; _flush_transcript renders them.
            self._transcript_dirty = True
        self._refresh_status()

    def _flush_transcript(self) -> None:
        if self._transcript_dirty:
            self._transcript_dirty = False
            self._refresh_transcript()

    # ----- key actions --------------------------------------------------- #

    def action_interrupt(self) -> None:
        if self._streaming:
            self._interrupt_run()
        else:
            self.exit()

    def action_escape(self) -> None:
        if self._palette_open:
            self._close_palette()
        elif self._streaming:
            self._interrupt_run()

    def _interrupt_run(self) -> None:
        self._cancelled = True
        self.workers.cancel_group(self, "agent")
        self._streaming = False
        self.state = reduce(self.state, RunEnded())
        self._dispatch(SystemMessage("Interrupted.", tone="info"))

    def action_redraw(self) -> None:
        self.refresh(layout=True)
        self._refresh_all()

    def action_clear_composer(self) -> None:
        self.query_one("#composer", Input).value = ""

    # ----- rendering ----------------------------------------------------- #

    def _dispatch(self, action) -> None:
        self.state = reduce(self.state, action)
        self._refresh_transcript()
        self._refresh_status()

    def _tick_spinner(self) -> None:
        if self._streaming:
            self._spinner_idx = (self._spinner_idx + 1) % len(SYMBOLS["spinner"])
            self._refresh_status()

    def _thread_label(self) -> str:
        if not self._conv_thread_id:
            return "new thread"
        return f"thread {self._conv_thread_id[:8]}"

    def _refresh_all(self) -> None:
        self._refresh_header()
        self._refresh_transcript()
        self._refresh_status()

    def _refresh_header(self) -> None:
        import os

        self.query_one("#header", Static).update(
            render_header(
                model=self._model,
                thread_label=self._thread_label(),
                cwd=os.getcwd(),
                skills=self._skills,
            )
        )

    def _refresh_transcript(self) -> None:
        self.query_one("#transcript", Static).update(render_transcript(self.state))
        self.query_one("#scroll", VerticalScroll).scroll_end(animate=False)

    def _refresh_status(self) -> None:
        spinner = SYMBOLS["spinner"][self._spinner_idx] if self._streaming else ""
        self.query_one("#status", Static).update(render_status(self.state, model=self._model, thread_label=self._thread_label(), spinner=spinner))


def run_tui(plan) -> int:
    """Construct the embedded session and run the app. Returns a process exit code."""
    from .session import open_session

    session = open_session()
    app = DeerFlowTUI(session, plan)
    try:
        app.run()
    finally:
        # Stop the background DB loop + dispose the engine so repeated run_tui
        # calls in one process don't leak loops / connection pools.
        session.close()
    return 0
