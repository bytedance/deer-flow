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
import json
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
            "recursion_limit": 1000,
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

    def _get_archive_checkpoint_path(self, session_id: str) -> Path:
        """Get the archived database path for a specific session."""
        return ARCHIVE_DIR / f"{session_id}_checkpoints.db"

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
        # Closes all persistent MCP sessions, clears _mcp_tools_cache,
        # resets _pool singleton, resets _cache_initialized / _config_mtime.
        try:
            from deerflow.mcp.cache import (
                reset_mcp_tools_cache,
            )

            reset_mcp_tools_cache()
        except Exception:
            pass

        # ── Subagent layer ──────────────────────────────────────────
        # _background_tasks: dict of SubagentResult keyed by task_id.
        # Without clearing, list_background_tasks() exposes stale results
        # from the previous session.
        try:
            from deerflow.subagents.executor import (
                _background_tasks,
                _background_tasks_lock,
            )

            with _background_tasks_lock:
                _background_tasks.clear()
        except Exception:
            pass

        # _subagent_usage_cache: dict of token usage keyed by tool_call_id.
        # Stale entries from completed/abandoned sessions persist until
        # explicitly cleared.
        try:
            from deerflow.tools.builtins.task_tool import (
                _subagent_usage_cache,
            )

            _subagent_usage_cache.clear()
        except Exception:
            pass

        # ── Memory layer ────────────────────────────────────────────
        # _storage_instance (FileMemoryStorage) holds an in-memory cache
        # of facts keyed by (user_id, agent_name).  reload() re-reads
        # from disk so the next session picks up any file-system changes.
        try:
            from deerflow.agents.memory.storage import get_memory_storage

            storage = get_memory_storage()
            if hasattr(storage, "reload"):
                storage.reload()
        except Exception:
            pass

        # _memory_queue batches ConversationContext objects across
        # sessions.  reset_memory_queue() drains the queue and replaces
        # the singleton so queued contexts from the old session are not
        # flushed into the new one.
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

        Closes the previous session's checkpointer, activates the target
        session's client, and resets shared global resources (MCP pool,
        subagent background tasks).

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

    def archive_session(self, session_id):
        """
        Archive a session, moving all files including its database to the
        archive directory.

        Args:
            session_id: ID of the session to archive.

        Returns:
            bool: True if archiving was successful, False otherwise.
        """
        if session_id not in self.store.sessions:
            print(f"[Error] Session {session_id} not found")
            return False

        self._destroy_client(session_id)

        self.store.archive_session_files(session_id)
        db_path = self._get_checkpoint_path(session_id)
        archive_db_path = self._get_archive_checkpoint_path(session_id)
        if db_path.exists():
            db_path.rename(archive_db_path)

        if self.current_session_id == session_id:
            self.current_session_id = None
            self._ensure_current_session()

        print(f"[Session] Archived: {session_id}")
        return True

    def list_archives(self):
        """Print a list of all archived sessions."""
        print("\n[Archived Sessions]")
        archives = list(ARCHIVE_DIR.glob("*.json"))
        if not archives:
            print("  No archived sessions")
        else:
            for f in archives:
                print(f"  {f.stem}")
        print()

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
    # Read-only session introspection (no global reset)
    # ------------------------------------------------------------------

    def _extract_steps(self, session_id: str):
        """Extract structured steps from a session's checkpoint history.

        Returns a list of step dicts without switching the active session.
        """
        client = self._get_or_create_client(session_id)
        thread_data = client.get_thread(session_id)
        checkpoints = thread_data.get("checkpoints", [])
        if not checkpoints:
            return []

        seen_message_ids: set[str] = set()
        steps: list[dict] = []
        current_step = None

        for cp_idx, cp in enumerate(checkpoints):
            messages = cp["values"].get("messages", [])

            for msg in messages:
                msg_id = msg.get("id")
                if msg_id is None:
                    msg_id = f"__no_id__:{msg.get('type', '')}:{msg.get('content', '')}"
                is_duplicate = msg_id in seen_message_ids

                if not is_duplicate:
                    seen_message_ids.add(msg_id)

                    if msg["type"] == "human":
                        if current_step:
                            steps.append(current_step)
                        current_step = {
                            "step": len(steps) + 1,
                            "checkpoint_id": cp.get("checkpoint_id"),
                            "parent_checkpoint_id": cp.get("parent_checkpoint_id"),
                            "ts": cp.get("ts"),
                            "total_tokens": cp["values"].get("total_tokens"),
                            "user_input": msg["content"],
                            "user_files": msg.get("metadata", {}).get("files", []),
                            "ai_response": "",
                            "tool_calls": [],
                            "ai_response_metadata": {},
                            "duplicate_messages": [],
                        }
                    elif msg["type"] == "ai" and current_step:
                        current_step["ai_response"] += msg.get("content", "")
                        current_step["ai_response_metadata"] = msg.get(
                            "response_metadata", {}
                        )
                        if msg.get("tool_calls"):
                            for tc in msg["tool_calls"]:
                                current_step["tool_calls"].append({
                                    "id": tc["id"],
                                    "name": tc["name"],
                                    "args": tc["args"],
                                    "result": "",
                                    "is_duplicate": False,
                                })
                    elif msg["type"] == "tool" and current_step:
                        for tc in current_step["tool_calls"]:
                            if tc["id"] == msg["tool_call_id"]:
                                tc["result"] = msg.get("content", "")
                                break
                else:
                    if current_step:
                        current_step["duplicate_messages"].append({
                            "type": msg["type"],
                            "checkpoint_id": cp.get("checkpoint_id"),
                            "checkpoint_index": cp_idx,
                        })

        if current_step:
            steps.append(current_step)

        # Mark duplicate tool calls
        seen_tool_call_ids: set[str] = set()
        for step in steps:
            for tc in step["tool_calls"]:
                if tc["id"] in seen_tool_call_ids:
                    tc["is_duplicate"] = True
                else:
                    seen_tool_call_ids.add(tc["id"])

        return steps

    def get_session_steps(self, session_id=None):
        """
        Get structured conversation steps with duplicate detection.

        Uses the per-session client directly — no global session switch,
        so shared resources are left untouched.

        Args:
            session_id: ID of the session. Uses current session if None.

        Returns:
            list: List of step dictionaries containing conversation data.
        """
        session_id = session_id or self.current_session_id
        if not session_id:
            return []
        return self._extract_steps(session_id)

    def get_all_checkpoint_steps(self, session_id=None):
        """
        Get a list of all checkpoints as individual steps.

        Only messages newly appearing in each checkpoint are shown
        (duplicates hidden).  Every checkpoint is preserved for precise
        rollback and auditing.

        Uses the per-session client directly — no global session switch.

        Args:
            session_id: Session ID, uses current session if None.

        Returns:
            list[dict]: Each element represents a checkpoint.
        """
        session_id = session_id or self.current_session_id
        if not session_id:
            return []

        client = self._get_or_create_client(session_id)
        thread_data = client.get_thread(session_id)
        checkpoints = thread_data.get("checkpoints", [])
        if not checkpoints:
            return []

        seen_message_ids: set[str] = set()
        checkpoint_steps: list[dict] = []

        for cp in checkpoints:
            messages = cp["values"].get("messages", [])
            new_msgs = []
            for msg in messages:
                msg_id = msg.get("id")
                if msg_id is None:
                    msg_id = (
                        f"__no_id__:{msg.get('type', '')}:{msg.get('content', '')}"
                    )
                if msg_id not in seen_message_ids:
                    seen_message_ids.add(msg_id)
                    new_msgs.append(msg)

            checkpoint_steps.append({
                "checkpoint_id": cp.get("checkpoint_id"),
                "parent_checkpoint_id": cp.get("parent_checkpoint_id"),
                "ts": cp.get("ts"),
                "new_messages": new_msgs,
                "has_new_content": len(new_msgs) > 0,
            })

        return checkpoint_steps

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def export_session_markdown(self, session_id=None):
        """
        Export a session to a formatted Markdown file.

        Args:
            session_id: ID of the session. Uses current session if None.

        Returns:
            str: Path to the exported Markdown file, or None on failure.
        """
        session_id = session_id or self.current_session_id
        if not session_id or session_id not in self.store.sessions:
            print("[Error] No active session")
            return None

        steps = self.get_session_steps(session_id)
        info = self.store.sessions[session_id]
        title = info.get("title", "Session Export")

        md = f"# {title}\n\n"
        md += f"Session ID: {session_id}\n"
        md += f"Created: {time.ctime(info['created_at'])}\n"
        md += f"Last Active: {time.ctime(info['last_active'])}\n"
        md += f"Total Turns: {len(steps)}\n"
        md += f"Total Tokens: {self.store.session_metrics[session_id]['total_tokens']}\n\n"
        md += "---\n\n"

        for step in steps:
            md += f"## Turn {step['step']}\n\n"
            md += f"**User**: {step['user_input']}\n\n"
            md += f"**AI**: {step['ai_response']}\n\n"

            if step["tool_calls"]:
                md += "**Tool Calls**\n\n"
                for tc in step["tool_calls"]:
                    if tc["is_duplicate"]:
                        md += f"### {tc['name']} ⚠️ Duplicate\n"
                    else:
                        md += f"### {tc['name']}\n"

                    md += "**Parameters**:\n"
                    md += f"```json\n{json.dumps(tc['args'], ensure_ascii=False, indent=2)}\n```\n"

                    if tc["result"]:
                        md += "**Result**:\n"
                        try:
                            if isinstance(tc["result"], str):
                                result_json = json.loads(tc["result"])
                                md += f"```json\n{json.dumps(result_json, ensure_ascii=False, indent=2)}\n```\n"
                            else:
                                md += f"```json\n{json.dumps(tc['result'], ensure_ascii=False, indent=2)}\n```\n"
                        except (json.JSONDecodeError, TypeError):
                            md += f"```\n{tc['result']}\n```\n"
                    md += "\n"

            if step.get("duplicate_messages"):
                duplicate_count = len(step["duplicate_messages"])
                md += (
                    f"⚠️ **Note**: {duplicate_count} duplicate messages detected "
                    "across checkpoints (not shown)\n\n"
                )

            md += "---\n\n"

        session_dir = SESSIONS_DIR / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        timestamp = int(time.time())
        filename = session_dir / f"export_{timestamp}.md"

        with open(filename, "w", encoding="utf-8") as f:
            f.write(md)

        print(f"[Export] Session exported to: {filename}")
        return str(filename)

    def export_all_checkpoints(self, session_id=None):
        """
        Export all checkpoints to a Markdown file.

        Duplicate messages are hidden but every checkpoint round is listed.
        Checkpoints with no new messages are still included for full
        traceability.

        Args:
            session_id: Session ID, uses current session if None.

        Returns:
            str: Path to the exported Markdown file, or None on failure.
        """
        session_id = session_id or self.current_session_id
        if not session_id or session_id not in self.store.sessions:
            print("[Error] No active session")
            return None

        all_steps = self.get_all_checkpoint_steps(session_id)
        info = self.store.sessions[session_id]
        title = info.get("title", "Session Export All")

        md = f"# {title} (All Checkpoints)\n\n"
        md += f"Session ID: {session_id}\n"
        md += f"Created: {time.ctime(info['created_at'])}\n"
        md += f"Last Active: {time.ctime(info['last_active'])}\n"
        md += f"Total Checkpoints: {len(all_steps)}\n"
        md += f"Total Tokens: {self.store.session_metrics[session_id]['total_tokens']}\n\n"
        md += "---\n\n"

        for idx, step in enumerate(all_steps, 1):
            ts_display = str(step["ts"]) if step["ts"] is not None else "Unknown"
            md += f"## Checkpoint {idx}\n\n"
            md += f"- **ID**: `{step['checkpoint_id']}`\n"
            md += f"- **Parent ID**: `{step['parent_checkpoint_id']}`\n"
            md += f"- **Time**: {ts_display}\n\n"

            if not step["has_new_content"]:
                md += (
                    "⚠️ This checkpoint introduced no new messages "
                    "(content identical to previous checkpoint).\n\n"
                )
            else:
                for msg in step["new_messages"]:
                    if msg["type"] == "human":
                        md += f"### [User]\n\n{msg['content']}\n\n"
                    elif msg["type"] == "ai":
                        content = msg.get("content", "")
                        if content:
                            md += f"### [AI]\n\n{content}\n\n"
                        if msg.get("tool_calls"):
                            for tc in msg["tool_calls"]:
                                md += f"#### [Tool Call: {tc['name']}]\n\n"
                                md += f"```json\n{json.dumps(tc['args'], ensure_ascii=False, indent=2)}\n```\n\n"
                    elif msg["type"] == "tool":
                        result = msg.get("content", "")
                        md += "#### [Tool Result]\n\n"
                        try:
                            result_json = json.loads(result)
                            md += f"```json\n{json.dumps(result_json, ensure_ascii=False, indent=2)}\n```\n\n"
                        except (json.JSONDecodeError, TypeError):
                            md += f"```\n{result}\n```\n\n"
            md += "---\n\n"

        session_dir = SESSIONS_DIR / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        timestamp = int(time.time())
        filename = session_dir / f"export_all_checkpoints_{timestamp}.md"

        with open(filename, "w", encoding="utf-8") as f:
            f.write(md)

        print(f"[Export] All checkpoints exported to: {filename}")
        return str(filename)

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search_sessions(self, keyword):
        """
        Search all active sessions for a keyword in user inputs or AI
        responses.  Uses each session's own client directly — no global
        session switch, so shared resources are untouched.

        Args:
            keyword: The keyword to search for (case-insensitive).
        """
        print(f"\n[Search Results for: {keyword}]")
        found = False

        for sid in self.store.sessions:
            steps = self.get_session_steps(sid)
            for step in steps:
                if (
                    keyword.lower() in step["user_input"].lower()
                    or keyword.lower() in step["ai_response"].lower()
                ):
                    title = self.store.sessions[sid].get("title", "New Session")
                    print(f"  Session: {sid} | {title} | Turn {step['step']}")
                    print(f"    User: {step['user_input'][:80]}...")
                    found = True
                    break

        if not found:
            print("  No matching sessions found")
        print()

    # ------------------------------------------------------------------
    # Archive restore
    # ------------------------------------------------------------------

    def restore_archive(self, session_id, switch=True):
        """
        Restore an archived session including its database file.

        Args:
            session_id: ID of the archived session to restore.
            switch: Whether to switch to the restored session (default True).

        Returns:
            bool: True if restoration was successful, False otherwise.
        """
        archive_path = ARCHIVE_DIR / f"{session_id}.json"
        archive_db_path = self._get_archive_checkpoint_path(session_id)

        if not archive_path.exists():
            print(f"[Error] Archive {session_id} not found")
            return False
        if session_id in self.store.sessions:
            print(f"[Error] Session {session_id} already active")
            return False

        with open(archive_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        self.store.sessions[session_id] = data["info"]
        self.store.session_metrics[session_id] = data["metrics"]

        active_path = SESSIONS_DIR / f"{session_id}.json"
        archive_path.rename(active_path)

        if archive_db_path.exists():
            active_db_path = self._get_checkpoint_path(session_id)
            archive_db_path.rename(active_db_path)

        if switch:
            self._activate_session(session_id)

        self.store.save_async(session_id)
        print(f"[Session] Restored from archive: {session_id}")
        return True

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
        # Use runtime setting for recursion_limit if not specified
        if "recursion_limit" not in kwargs:
            kwargs["recursion_limit"] = self._runtime_settings.get("recursion_limit", 1000)
        stream_kwargs = {"thread_id": session_id, **kwargs}

        full_response = ""
        tool_calls = 0
        total_tokens = 0

        tool_call_history: list[dict] = []

        client = self._get_or_create_client(session_id)
        try:
            for event in client.stream(message, **stream_kwargs):
                if event.type == "messages-tuple":
                    d = event.data
                    if d.get("type") == "ai" and d.get("content"):
                        content = d["content"]
                        full_response += content
                        yield content
                    if d.get("tool_calls"):
                        tool_calls += len(d["tool_calls"])
                        for tc in d["tool_calls"]:
                            tool_call_history.append({
                                "name": tc.get("name"),
                                "args": tc.get("args"),
                                "id": tc.get("id"),
                            })
                elif event.type == "end":
                    usage = event.data.get("usage", {})
                    total_tokens = usage.get("total_tokens", 0)
        except Exception as stream_error:
            print(f"\n\n[Stream Error | 流错误] {type(stream_error).__name__}: {stream_error}")
            print(f"\n[Tool Call Summary | 工具调用摘要]")
            print(f"  Total tool calls: {len(tool_call_history)}")
            from collections import Counter
            tool_counts = Counter(tc["name"] for tc in tool_call_history)
            for tool_name, count in tool_counts.most_common():
                print(f"    {tool_name}: {count} calls")
            print(f"\n[Tool Call History | 工具调用历史] (最近5次)")
            for tc in tool_call_history[-5:]:
                print(f"  - {tc['name']}: {tc.get('args', {})}")
            raise

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

        # Check checkpoint count and warn if approaching recursion limit
        if thread_data and thread_data.get("checkpoints"):
            checkpoint_count = len(thread_data["checkpoints"])
            recursion_limit = self._runtime_settings.get("recursion_limit", 1000)
            warning_threshold = int(recursion_limit * 0.8)  # Warn at 80% of limit
            critical_threshold = int(recursion_limit * 0.9)  # Critical warning at 90%

            if checkpoint_count >= critical_threshold:
                yield f"\n\n⚠️  [CRITICAL] Checkpoints: {checkpoint_count}/{recursion_limit} - Approaching recursion limit!"
                client = self._get_or_create_client(session_id)
                if hasattr(client, '_subagent_enabled') and client._subagent_enabled:
                    yield f" Subagent is enabled - consider disabling with: !subagent off"
            elif checkpoint_count >= warning_threshold:
                yield f"\n\n[WARNING] Checkpoints: {checkpoint_count}/{recursion_limit} - Getting close to limit"

    # ------------------------------------------------------------------
    # File upload
    # ------------------------------------------------------------------

    def upload_file(self, file_path, session_id=None):
        """
        Upload a file to the current session.

        Args:
            file_path: Path to the file to upload.
            session_id: ID of the session. Uses current session if None.

        Returns:
            dict: Upload result from the client, or None on failure.
        """
        session_id = session_id or self.current_session_id
        if not session_id:
            print("[Error] No active session")
            return None
        if not os.path.exists(file_path):
            print(f"[Error] File not found: {file_path}")
            return None
        client = self._get_or_create_client(session_id)
        result = client.upload_files(session_id, [file_path])
        print(f"[Upload] Success: {result['message']}")
        return result

    def list_uploads(self, session_id=None):
        """
        List all files uploaded to a session.

        Args:
            session_id: ID of the session. Uses current session if None.

        Returns:
            dict: List of uploaded files, or None if no active session.
        """
        session_id = session_id or self.current_session_id
        if not session_id:
            print("[Error] No active session")
            return None
        client = self._get_or_create_client(session_id)
        return client.list_uploads(session_id)

    def delete_upload(self, filename, session_id=None):
        """
        Delete an uploaded file from a session.

        Args:
            filename: Name of the file to delete.
            session_id: ID of the session. Uses current session if None.

        Returns:
            dict: Deletion result from the client, or None on failure.
        """
        session_id = session_id or self.current_session_id
        if not session_id:
            print("[Error] No active session")
            return None
        client = self._get_or_create_client(session_id)
        return client.delete_upload(session_id, filename)

    # ------------------------------------------------------------------
    # Runtime controls (apply to current client + persist for new sessions)
    # ------------------------------------------------------------------

    def enable_skill(self, skill_name):
        """
        Enable a skill for the agent.

        Args:
            skill_name: Name of the skill to enable.

        Returns:
            bool: True if skill was enabled successfully.
        """
        client = self.client
        if client is None:
            return False
        try:
            client.update_skill(skill_name, enabled=True)
            print(f"[Skill] Enabled: {skill_name}")
            return True
        except Exception as e:
            print(f"[Error] Failed to enable skill: {e}")
            return False

    def disable_skill(self, skill_name):
        """
        Disable a skill for the agent.

        Args:
            skill_name: Name of the skill to disable.

        Returns:
            bool: True if skill was disabled successfully.
        """
        client = self.client
        if client is None:
            return False
        try:
            client.update_skill(skill_name, enabled=False)
            print(f"[Skill] Disabled: {skill_name}")
            return True
        except Exception as e:
            print(f"[Error] Failed to disable skill: {e}")
            return False

    def switch_model(self, model_name):
        """
        Switch the agent to use a different model.

        The choice is persisted to ``_runtime_settings`` so that newly
        created sessions inherit it.

        Args:
            model_name: Name of the model to use.

        Returns:
            bool: True if model was switched successfully.
        """
        client = self.client
        if client is None:
            return False
        models = client.list_models()["models"]
        if not any(m["name"] == model_name for m in models):
            print(f"[Error] Model {model_name} not found")
            return False
        client._model_name = model_name
        self._runtime_settings["model_name"] = model_name
        print(f"[Model] Switched to: {model_name}")
        return True

    # ------------------------------------------------------------------
    # Runtime controls (apply to current client + persist for new sessions)
    # ------------------------------------------------------------------

    def show_status(self):
        """Display current session status and runtime settings."""
        client = self.client
        if client is None:
            print("[Error] No active session")
            return

        print(f"\n[Session Status | 会话状态]")
        print(f"  Session ID: {self.current_session_id}")

        # Get client runtime settings
        model_name = getattr(client, '_model_name', None) or self._runtime_settings.get("model_name")
        plan_mode = getattr(client, '_plan_mode', None) if hasattr(client, '_plan_mode') else self._runtime_settings.get("plan_mode")
        subagent_enabled = getattr(client, '_subagent_enabled', None) if hasattr(client, '_subagent_enabled') else self._runtime_settings.get("subagent_enabled")
        thinking_enabled = getattr(client, '_thinking_enabled', None) if hasattr(client, '_thinking_enabled') else self._runtime_settings.get("thinking_enabled")

        print(f"\n[Runtime Settings | 运行时配置]")
        print(f"  Model: {model_name or 'default'}")
        print(f"  Subagent: {'✓ Enabled' if subagent_enabled else '✗ Disabled'}")
        print(f"  Plan Mode: {'✓ Enabled' if plan_mode else '✗ Disabled'}")
        print(f"  Thinking: {'✓ Enabled' if thinking_enabled else '✗ Disabled'}")

        # Get checkpoint info
        thread_data = client.get_thread(self.current_session_id)
        checkpoints = thread_data.get("checkpoints", [])
        print(f"\n[Session Metrics | 会话指标]")
        print(f"  Checkpoints: {len(checkpoints)}")
        recursion_limit = self._runtime_settings.get("recursion_limit", 1000)
        print(f"  Recursion Limit: {recursion_limit}")
        if len(checkpoints) > int(recursion_limit * 0.8):
            print(f"  ⚠️  Approaching recursion limit ({len(checkpoints)}/{recursion_limit})")
        print()

    def enable_plan_mode(self):
        """Enable plan mode for the agent and persist the setting."""
        client = self.client
        if client is None:
            return
        client._plan_mode = True
        self._runtime_settings["plan_mode"] = True
        print("[Mode] Plan mode enabled")

    def disable_plan_mode(self):
        """Disable plan mode for the agent and persist the setting."""
        client = self.client
        if client is None:
            return
        client._plan_mode = False
        self._runtime_settings["plan_mode"] = False
        print("[Mode] Plan mode disabled")

    def enable_subagent(self):
        """Enable subagent delegation and persist the setting."""
        client = self.client
        if client is None:
            return
        client._subagent_enabled = True
        self._runtime_settings["subagent_enabled"] = True
        print("[Mode] Subagent delegation enabled")

    def disable_subagent(self):
        """Disable subagent delegation and persist the setting."""
        client = self.client
        if client is None:
            return
        client._subagent_enabled = False
        self._runtime_settings["subagent_enabled"] = False
        print("[Mode] Subagent delegation disabled")

    def set_recursion_limit(self, limit: int):
        """
        Set the recursion limit for agent execution and persist the setting.

        Args:
            limit: Maximum number of graph steps LangGraph will execute.

        Returns:
            bool: True if limit was set successfully.
        """
        if not isinstance(limit, int) or limit < 1:
            print("[Error] Recursion limit must be a positive integer")
            return False

        self._runtime_settings["recursion_limit"] = limit
        print(f"[Config] Recursion limit set to: {limit}")
        return True

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def diagnose_tool_calls(self, session_id=None):
        """
        Analyze tool call patterns from checkpoint history to identify loops.

        Args:
            session_id: Session ID, uses current session if None.
        """
        session_id = session_id or self.current_session_id
        if not session_id:
            print("[Error] No active session")
            return

        from collections import Counter

        client = self._get_or_create_client(session_id)
        thread_data = client.get_thread(session_id)
        checkpoints = thread_data.get("checkpoints", [])

        if not checkpoints:
            print("[Diagnostics] No checkpoints found")
            return

        print(f"\n[Tool Call Diagnostics | 工具调用诊断]")
        print(f"  Session: {session_id}")
        print(f"  Total checkpoints: {len(checkpoints)}")
        print()

        # Collect tool calls - both WITH and WITHOUT deduplication for comparison
        # Each checkpoint's messages contain full history, so we need to track seen IDs

        # 1. Raw collection (WITH duplicates - counts every occurrence across checkpoints)
        raw_tool_calls: list[dict] = []
        for cp in checkpoints:
            messages = cp["values"].get("messages", [])
            for msg in messages:
                if msg.get("type") == "ai" and msg.get("tool_calls"):
                    for tc in msg["tool_calls"]:
                        raw_tool_calls.append({
                            "name": tc.get("name"),
                            "args": tc.get("args"),
                            "checkpoint_id": cp.get("checkpoint_id"),
                            "tool_call_id": tc.get("id"),
                        })

        # 2. Deduplicated collection (unique tool calls only)
        seen_message_ids: set[str] = set()
        unique_tool_calls: list[dict] = []
        for cp in checkpoints:
            messages = cp["values"].get("messages", [])
            for msg in messages:
                msg_id = msg.get("id")
                # Generate fallback id if message has no id
                if msg_id is None:
                    msg_id = f"__no_id__:{msg.get('type', '')}:{str(msg.get('content', ''))[:100]}"
                # Only process new messages
                if msg_id not in seen_message_ids:
                    seen_message_ids.add(msg_id)
                    if msg.get("type") == "ai" and msg.get("tool_calls"):
                        for tc in msg["tool_calls"]:
                            unique_tool_calls.append({
                                "name": tc.get("name"),
                                "args": tc.get("args"),
                                "checkpoint_id": cp.get("checkpoint_id"),
                                "tool_call_id": tc.get("id"),
                            })

        if not unique_tool_calls:
            print("  No tool calls found in history")
            return

        # Comparison: Raw (with duplicates) vs Unique (deduplicated)
        raw_counts = Counter(tc["name"] for tc in raw_tool_calls)
        unique_counts = Counter(tc["name"] for tc in unique_tool_calls)

        print(f"[Tool Call Frequency Comparison | 工具调用频率对比]")
        print(f"  {'Tool Name':<40} | {'Unique':<8} | {'Raw (with dup)':<15} | {'Ratio':<8}")
        print(f"  {'-'*40}-+-{'-'*8}-+-{'-'*15}-+-{'-'*8}")

        all_tool_names = set(raw_counts.keys()) | set(unique_counts.keys())
        for tool_name in sorted(all_tool_names, key=lambda x: -unique_counts[x]):
            unique_cnt = unique_counts.get(tool_name, 0)
            raw_cnt = raw_counts.get(tool_name, 0)
            ratio = raw_cnt / unique_cnt if unique_cnt > 0 else 0
            ratio_str = f"{ratio:.1f}x"
            print(f"  {tool_name:<40} | {unique_cnt:<8} | {raw_cnt:<15} | {ratio_str:<8}")
        print()

        # Checkpoint density analysis
        print(f"[Checkpoint Density Analysis | 检查点密度分析]")
        print(f"  Unique tool calls: {len(unique_tool_calls)}")
        print(f"  Raw occurrences across all checkpoints: {len(raw_tool_calls)}")
        if len(checkpoints) > 0:
            density = len(raw_tool_calls) / max(len(unique_tool_calls), 1)
            print(f"  Average duplications per unique call: {density:.1f}x")
            if density > 3:
                print(f"  ⚠️  High duplication - each tool call appears in many checkpoints")
                print(f"      This is normal for long-running sessions with subagents")
        print()

        # Detect potential loops - consecutive same-tool calls (using unique data)
        print(f"[Potential Loop Detection | 潜在循环检测]")
        consecutive_count: dict[str, int] = {}
        current_tool = None
        current_count = 0

        for tc in unique_tool_calls:
            tool_name = tc["name"]
            if tool_name == current_tool:
                current_count += 1
            else:
                if current_tool:
                    consecutive_count[current_tool] = max(consecutive_count.get(current_tool, 0), current_count)
                current_tool = tool_name
                current_count = 1
        if current_tool:
            consecutive_count[current_tool] = max(consecutive_count.get(current_tool, 0), current_count)

        for tool_name, count in sorted(consecutive_count.items(), key=lambda x: -x[1]):
            if count > 2:
                print(f"  ⚠️  {tool_name}: {count} consecutive calls (potential loop)")

        print()
        print(f"[Recent Tool Call History | 最近工具调用历史] (last 10 unique)")
        for tc in unique_tool_calls[-10:]:
            args_preview = str(tc.get("args", {}))[:60]
            print(f"  - {tc['name']}: {args_preview}...")
        print()