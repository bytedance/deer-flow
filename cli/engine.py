"""
DeerFlow Production Engine

A production-grade, session-aware runtime engine for DeerFlow AI agents.
Features complete session management, persistence, streaming, and tool integration.

Isolation design
================
Session-level isolation is enforced through two complementary mechanisms:

1. **Per-session DeerFlowClient instances.**  Each session owns an independent
   DeerFlowClient and SQLite checkpointer.  Agent state, runtime settings, and
   conversation history never leak across sessions.

2. **Global shared-resource reset on session switch.**  The deerflow backend
   package holds module-level singletons (MCP session pool, MCP tool cache,
   subagent background tasks, memory queue, etc.) that outlive any single
   client instance.  ``_reset_shared_resources()`` clears every known global
   on each user-initiated session switch.

   This is a *best-effort* reset — it depends on the backend exposing public
   reset functions for every piece of mutable global state.  If a future
   backend version adds new global state without a corresponding reset API,
   it will not be caught here.  For single-user CLI use this trade-off is
   acceptable; a multi-tenant server should spawn a subprocess per session
   for guaranteed isolation (see issue #3292).

All checkpoints are preserved for full model behavior auditing.

Author: heart-scalpel
License: MIT
"""

import os
import time
import re
import uuid
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver
from deerflow.client import DeerFlowClient
from session_store import SessionStore

# Configuration constants
WORK_DIR = Path("./.deer-flow")
SESSIONS_DIR = WORK_DIR / "deerflow_sessions"
ARCHIVE_DIR = SESSIONS_DIR / "archive"


class DeerFlowProductionEngine:
    """
    Production-grade singleton engine for DeerFlow agent execution.

    Manages session lifecycle, persistence, streaming responses, and agent
    configuration.  Each session owns an independent DeerFlowClient and
    SQLite checkpointer so that agent state, runtime settings, and
    conversation history are fully isolated.

    On every user-initiated session switch, ``_reset_shared_resources()``
    clears all known module-level globals in the deerflow backend:
    MCP session pool + tool cache, subagent background tasks + usage cache,
    memory storage cache + update queue.  See that method's docstring for
    the full inventory and the residual risks of this best-effort approach.
    """

    _instance = None
    _initialized = False

    def __new__(cls):
        """Create or return the singleton instance."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        """Initialize the engine if not already initialized."""
        if self._initialized:
            return
        self._initialized = True

        # ------------------------------------------------------------------
        # Session persistence
        # ------------------------------------------------------------------
        self.store = SessionStore(SESSIONS_DIR, ARCHIVE_DIR)

        # ------------------------------------------------------------------
        # Per-session client instances (complete agent state isolation)
        # ------------------------------------------------------------------
        self._clients: dict[str, DeerFlowClient] = {}
        self._checkpointer_cms: dict[str, object] = {}
        self._checkpointers: dict[str, object] = {}

        self.current_session_id = None

        # Runtime settings template — applied to every new client so that
        # user preferences (model, plan mode, subagent, thinking) survive
        # across session switches.
        self._runtime_settings = {
            "model_name": None,
            "plan_mode": False,
            "subagent_enabled": False,
            "thinking_enabled": True,
        }

        # ------------------------------------------------------------------
        # Bootstrap: load existing sessions or create a default
        # ------------------------------------------------------------------
        if not self.store.sessions:
            self._create_default_session()
        else:
            first_session_id = next(iter(self.store.sessions.keys()))
            self._activate_session(first_session_id)

    # ------------------------------------------------------------------
    # Checkpointer paths
    # ------------------------------------------------------------------

    def _get_checkpoint_path(self, session_id: str) -> Path:
        """Get the database path for a specific session."""
        return SESSIONS_DIR / f"{session_id}_checkpoints.db"

    # ------------------------------------------------------------------
    # Client property
    # ------------------------------------------------------------------

    @property
    def client(self) -> DeerFlowClient | None:
        """Return the DeerFlowClient for the current session."""
        if self.current_session_id is None:
            return None
        return self._clients.get(self.current_session_id)

    # ------------------------------------------------------------------
    # Per-session client and checkpointer management
    # ------------------------------------------------------------------

    def _get_or_create_client(self, session_id: str) -> DeerFlowClient:
        """Return (or create) the DeerFlowClient for *session_id*.

        Ensures the session's SQLite checkpointer is open.  Does **not**
        reset shared global resources — use ``_activate_session`` for
        user-initiated switches that require a full reset.
        """
        # Ensure a live checkpointer for this session.
        if session_id not in self._checkpointer_cms:
            db_path = self._get_checkpoint_path(session_id)
            cm = SqliteSaver.from_conn_string(str(db_path))
            self._checkpointer_cms[session_id] = cm
            self._checkpointers[session_id] = cm.__enter__()

        checkpointer = self._checkpointers[session_id]

        # Return existing client after refreshing its checkpointer ref
        # (the old SqliteSaver may have been closed across a switch).
        if session_id in self._clients:
            client = self._clients[session_id]
            client._checkpointer = checkpointer
            return client

        # First time this session is used — create a fresh client.
        client = DeerFlowClient(checkpointer=checkpointer)
        settings = self._runtime_settings
        if settings["model_name"]:
            client._model_name = settings["model_name"]
        client._plan_mode = settings["plan_mode"]
        client._subagent_enabled = settings["subagent_enabled"]
        client._thinking_enabled = settings["thinking_enabled"]

        self._clients[session_id] = client
        return client

    def _activate_session(self, session_id: str):
        """Activate *session_id* for user interaction.

        Closes the previous session's checkpointer (keeping its client
        alive for later reuse), ensures the target session has a live
        client and checkpointer, then resets shared global resources.
        """
        # Close the *previous* session's checkpointer to release the
        # SQLite connection, but leave its client in the dict so runtime
        # settings are preserved.
        if self.current_session_id and self.current_session_id != session_id:
            self._close_checkpointer(self.current_session_id)

        # Ensure target session is ready.
        self._get_or_create_client(session_id)

        # Prevent cross-session contamination from module-level globals.
        self._reset_shared_resources()

        self.current_session_id = session_id

    def _close_checkpointer(self, session_id: str):
        """Close the SQLite checkpointer for *session_id*."""
        cm = self._checkpointer_cms.pop(session_id, None)
        if cm is not None:
            cm.__exit__(None, None, None)
        self._checkpointers.pop(session_id, None)

    def _destroy_client(self, session_id: str):
        """Fully tear down a session's client and checkpointer."""
        self._clients.pop(session_id, None)
        self._close_checkpointer(session_id)

    def _reset_shared_resources(self):
        """Reset all known module-level globals in the deerflow backend.

        This method is the single point of accountability for cross-session
        cleanup.  Every piece of mutable global state discovered in the
        backend audit that has a public reset API is cleared here.

        Resources intentionally NOT reset:
        - ``_isolated_subagent_loop`` — persistent event loop, expensive to
          recreate, carries no session-specific state, atexit-managed.
        - ``_scheduler_pool`` — ThreadPoolExecutor, expensive, stateless.
        - ``_SYNC_TOOL_EXECUTOR``, ``_SYNC_MEMORY_UPDATER_EXECUTOR`` —
          stateless thread pools, atexit-managed.
        - Middleware dicts (todo, loop_detection) — keyed by
          ``(thread_id, run_id)``, naturally scoped; no public reset API.

        Fragility note: if a future backend version adds new global state
        without a corresponding reset function, it will NOT be caught here.
        This is the fundamental limitation of option 2 vs subprocess
        isolation.  For single-user CLI use this trade-off is acceptable.
        """
        # ── MCP layer ───────────────────────────────────────────────
        try:
            from deerflow.mcp.cache import reset_mcp_tools_cache
            reset_mcp_tools_cache()
        except Exception:
            pass

        # ── Subagent layer ──────────────────────────────────────────
        try:
            from deerflow.subagents.executor import (
                _background_tasks,
                _background_tasks_lock,
            )
            with _background_tasks_lock:
                _background_tasks.clear()
        except Exception:
            pass

        try:
            from deerflow.tools.builtins.task_tool import _subagent_usage_cache
            _subagent_usage_cache.clear()
        except Exception:
            pass

        # ── Memory layer ────────────────────────────────────────────
        try:
            from deerflow.agents.memory.storage import get_memory_storage
            storage = get_memory_storage()
            if hasattr(storage, "reload"):
                storage.reload()
        except Exception:
            pass

        try:
            from deerflow.agents.memory.queue import reset_memory_queue
            reset_memory_queue()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    def _create_default_session(self):
        """Create a default session when no sessions exist."""
        return self.create_session(title="New Session")

    def _ensure_current_session(self):
        """Ensure a valid current session exists."""
        if self.current_session_id is None or self.current_session_id not in self.store.sessions:
            if self.store.sessions:
                first_session_id = next(iter(self.store.sessions.keys()))
                self._activate_session(first_session_id)
            else:
                self._create_default_session()

    def shutdown(self):
        """Gracefully shut down the engine and release all resources."""
        print("\n[Engine] Shutting down gracefully...")
        self.store.shutdown()
        for sid in list(self._clients.keys()):
            self._destroy_client(sid)
        for sid in list(self._checkpointer_cms.keys()):
            self._close_checkpointer(sid)
        print("[Engine] Shutdown complete")

    def create_session(self, session_id=None, title=None):
        """
        Create a new conversation session with its own isolated database
        and DeerFlowClient instance.

        Args:
            session_id: Optional custom session ID. Auto-generated if None.
            title: Optional session title. Defaults to "New Session".

        Returns:
            str: The created session ID.
        """
        if session_id is None or not re.fullmatch(r'[\w-]+', session_id):
            session_id = uuid.uuid4().hex
        if session_id in self.store.sessions:
            print(f"[Session] ID already exists: {session_id}")
            return session_id
        self.store.sessions[session_id] = {
            "created_at": time.time(),
            "last_active": time.time(),
            "title": title or "New Session",
            "last_checkpoint_id": None,
        }
        self.store.session_metrics[session_id] = {
            "total_tokens": 0,
            "tool_calls": 0,
            "turns": 0,
        }
        self.store.save_async(session_id)

        self._activate_session(session_id)

        print(f"[Session] Created: {session_id}")
        return session_id

    def switch_session(self, session_id):
        """
        Switch to an existing session with complete state isolation.

        Args:
            session_id: ID of the session to switch to.

        Returns:
            bool: True if switch was successful, False otherwise.
        """
        if session_id not in self.store.sessions:
            print(f"[Error] Session {session_id} not found")
            return False

        self._activate_session(session_id)
        self.store.sessions[session_id]["last_active"] = time.time()
        self.store.save_async(session_id)

        print(f"[Session] Switched to: {session_id}")
        return True

    def delete_session(self, session_id):
        """
        Delete a session and all associated files including its database.

        Args:
            session_id: ID of the session to delete.

        Returns:
            bool: True if deletion was successful, False otherwise.
        """
        if session_id not in self.store.sessions:
            print(f"[Error] Session {session_id} not found")
            return False

        self._destroy_client(session_id)

        self.store.delete_session_files(session_id)
        db_path = self._get_checkpoint_path(session_id)
        if db_path.exists():
            db_path.unlink()

        if self.current_session_id == session_id:
            self.current_session_id = None
            self._ensure_current_session()

        print(f"[Session] Deleted: {session_id}")
        return True

    def rename_session(self, session_id, new_title):
        """
        Rename an existing session.

        Args:
            session_id: ID of the session to rename.
            new_title: New title for the session.

        Returns:
            bool: True if rename was successful, False otherwise.
        """
        if session_id not in self.store.sessions:
            print(f"[Error] Session {session_id} not found")
            return False
        self.store.sessions[session_id]["title"] = new_title
        self.store.save_async(session_id)
        print(f"[Session] Renamed to: {new_title}")
        return True

    def list_sessions(self):
        """Print a list of all active sessions with their metrics."""
        print("\n[Session List]")
        for sid, info in self.store.sessions.items():
            metrics = self.store.session_metrics[sid]
            current = "← Current" if sid == self.current_session_id else ""
            title = info.get("title", "New Session")
            print(
                f"  {sid} | {title} | Turns: {metrics['turns']} | "
                f"Tokens: {metrics['total_tokens']} {current}"
            )
        print()

    # ------------------------------------------------------------------
    # Chat
    # ------------------------------------------------------------------

    def chat(self, message, session_id=None, **kwargs):
        """
        Send a message to the agent and stream the response.

        Args:
            message: The user's input message.
            session_id: ID of the session. Uses current session if None.
            **kwargs: Additional keyword arguments passed to client.stream().

        Yields:
            str: Chunks of the AI response, followed by metrics.
        """
        session_id = session_id or self.current_session_id
        if not session_id or session_id not in self.store.sessions:
            session_id = self.create_session()

        self.store.sessions[session_id]["last_active"] = time.time()
        stream_kwargs = {"thread_id": session_id, **kwargs}

        full_response = ""
        tool_calls = 0
        total_tokens = 0

        client = self._get_or_create_client(session_id)
        for event in client.stream(message, **stream_kwargs):
            if event.type == "messages-tuple":
                d = event.data
                if d.get("type") == "ai" and d.get("content"):
                    content = d["content"]
                    full_response += content
                    yield content
                if d.get("tool_calls"):
                    tool_calls += len(d["tool_calls"])
            elif event.type == "end":
                usage = event.data.get("usage", {})
                total_tokens = usage.get("total_tokens", 0)

        self.store.session_metrics[session_id]["turns"] += 1
        self.store.session_metrics[session_id]["tool_calls"] += tool_calls
        self.store.session_metrics[session_id]["total_tokens"] += total_tokens

        thread_data = client.get_thread(session_id)
        if thread_data["checkpoints"]:
            last_checkpoint_id = thread_data["checkpoints"][-1]["checkpoint_id"]
            self.store.sessions[session_id]["last_checkpoint_id"] = last_checkpoint_id

        if (
            self.store.sessions[session_id].get("title") in (None, "New Session")
            and full_response
        ):
            self.store.sessions[session_id]["title"] = (
                message[:30] + ("..." if len(message) > 30 else "")
            )

        self.store.save_async(session_id)

        yield f"\n\n[Metrics] Tokens: {total_tokens} | Tool Calls: {tool_calls}"
