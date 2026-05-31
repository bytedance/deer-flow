"""
DeerFlow Production Engine

A production-grade, session-aware runtime engine for DeerFlow AI agents.
Features complete session management, persistence, streaming, and tool integration.

This implementation uses per-session SQLite databases for perfect isolation,
eliminating all global lock issues and state contamination problems.
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
    
    Manages session lifecycle, persistence, streaming responses, and agent configuration.
    Implements per-session database isolation for perfect state separation and no lock contention.
    All checkpoints are preserved for complete model behavior auditing and debugging.
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

        # Initialize session storage
        self.store = SessionStore(SESSIONS_DIR, ARCHIVE_DIR)

        # Checkpointer management (per-session isolation)
        self._current_checkpointer_cm = None
        self.checkpointer = None
        self.client = None

        self.current_session_id = None

        # Initialize default session if no sessions exist
        if not self.store.sessions:
            self._create_default_session()
        else:
            first_session_id = next(iter(self.store.sessions.keys()))
            self._switch_checkpointer(first_session_id)
            self.current_session_id = first_session_id

        # Preload agent to reduce first response latency
        # self._preload_agent()

    def _get_checkpoint_path(self, session_id: str) -> Path:
        """Get the database path for a specific session."""
        return SESSIONS_DIR / f"{session_id}_checkpoints.db"

    def _get_archive_checkpoint_path(self, session_id: str) -> Path:
        """Get the archived database path for a specific session."""
        return ARCHIVE_DIR / f"{session_id}_checkpoints.db"

    def _switch_checkpointer(self, session_id: str):
        """
        Switch to the checkpointer for the specified session.
        Properly closes the previous checkpointer to release all resources.
        Reuses the existing DeerFlowClient so runtime settings survive the switch.
        """
        # 1) Tear down the old checkpointer (agent holds a ref via the client).
        if self._current_checkpointer_cm is not None:
            self._current_checkpointer_cm.__exit__(None, None, None)
            self._current_checkpointer_cm = None
            self.checkpointer = None

        # 2) Create a new, completely isolated checkpointer for the target session.
        db_path = self._get_checkpoint_path(session_id)
        self._current_checkpointer_cm = SqliteSaver.from_conn_string(str(db_path))
        self.checkpointer = self._current_checkpointer_cm.__enter__()

        # 3) Swap the checkpointer on the existing client, preserving runtime
        #    settings (model, plan mode, subagent, skills, etc.).
        if self.client is not None:
            self.client._checkpointer = self.checkpointer
            self.client.reset_agent()
        else:
            self.client = DeerFlowClient(checkpointer=self.checkpointer)

    def _create_default_session(self):
        """Create a default session when no sessions exist."""
        session_id = self.create_session(title="New Session")
        return session_id

    def _ensure_current_session(self):
        """Ensure a valid current session exists."""
        if self.current_session_id is None or self.current_session_id not in self.store.sessions:
            if self.store.sessions:
                first_session_id = next(iter(self.store.sessions.keys()))
                self._switch_checkpointer(first_session_id)
                self.current_session_id = first_session_id
            else:
                self._create_default_session()

    def _preload_agent(self):
        """Warm up the agent instance to reduce first response time."""
        print("[Engine] Preloading agent...")
        start = time.time()
        try:
            # Send a ping request to initialize the agent
            list(self.client.stream("ping", thread_id="preload-warmup"))
        except Exception:
            pass
        print(f"[Engine] Agent preloaded in {time.time()-start:.2f}s")

    def shutdown(self):
        """Gracefully shut down the engine and release all resources."""
        print("\n[Engine] Shutting down gracefully...")
        self.store.shutdown()
        if self.client is not None:
            self.client = None
        if self._current_checkpointer_cm is not None:
            self._current_checkpointer_cm.__exit__(None, None, None)
            self._current_checkpointer_cm = None
            self.checkpointer = None
        print("[Engine] Shutdown complete")

    def create_session(self, session_id=None, title=None):
        """
        Create a new conversation session with its own isolated database.
        
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
        self.store.session_metrics[session_id] = {"total_tokens": 0, "tool_calls": 0, "turns": 0}
        self.store.save_async(session_id)
        
        # Switch to the new session's checkpointer
        self._switch_checkpointer(session_id)
        self.current_session_id = session_id
        
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
        
        # Switch checkpointer first - this ensures clean state
        self._switch_checkpointer(session_id)
        self.current_session_id = session_id
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
        
        # Delete session files and database
        self.store.delete_session_files(session_id)
        db_path = self._get_checkpoint_path(session_id)
        if db_path.exists():
            db_path.unlink()
        
        # Switch to another session if we deleted the current one
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
        Archive a session, moving all files including its database to archive directory.
        
        Args:
            session_id: ID of the session to archive.
            
        Returns:
            bool: True if archiving was successful, False otherwise.
        """
        if session_id not in self.store.sessions:
            print(f"[Error] Session {session_id} not found")
            return False
        
        # Archive session files and database
        self.store.archive_session_files(session_id)
        db_path = self._get_checkpoint_path(session_id)
        archive_db_path = self._get_archive_checkpoint_path(session_id)
        if db_path.exists():
            db_path.rename(archive_db_path)
        
        # Switch to another session if we archived the current one
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
            print(f"  {sid} | {title} | Turns: {metrics['turns']} | Tokens: {metrics['total_tokens']} {current}")
        print()

    def get_session_steps(self, session_id=None):
        """
        Get structured conversation steps with duplicate detection and marking.
        Preserves all checkpoints for full model behavior auditing.
        
        Extracts messages from all checkpoints, identifies duplicates,
        and returns a clean list with duplicate markers.
        
        Args:
            session_id: ID of the session. Uses current session if None.
            
        Returns:
            list: List of step dictionaries containing conversation data.
        """
        session_id = session_id or self.current_session_id
        if not session_id:
            return []
        
        # Temporarily switch to the target session's checkpointer if needed
        original_session_id = self.current_session_id
        if session_id != original_session_id:
            self._switch_checkpointer(session_id)
        
        try:
            thread_data = self.client.get_thread(session_id)
            checkpoints = thread_data.get("checkpoints", [])
            if not checkpoints:
                return []
            
            # Track seen message IDs to detect duplicates across checkpoints
            seen_message_ids = set()
            steps = []
            current_step = None
            
            # Process all checkpoints to preserve full execution history
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
                                "duplicate_messages": []
                            }
                        elif msg["type"] == "ai" and current_step:
                            current_step["ai_response"] += msg.get("content", "")
                            current_step["ai_response_metadata"] = msg.get("response_metadata", {})
                            if msg.get("tool_calls"):
                                for tc in msg["tool_calls"]:
                                    current_step["tool_calls"].append({
                                        "id": tc["id"],
                                        "name": tc["name"],
                                        "args": tc["args"],
                                        "result": "",
                                        "is_duplicate": False
                                    })
                        elif msg["type"] == "tool" and current_step:
                            for tc in current_step["tool_calls"]:
                                if tc["id"] == msg["tool_call_id"]:
                                    tc["result"] = msg.get("content", "")
                                    break
                    else:
                        # Record duplicate messages for auditing
                        if current_step:
                            current_step["duplicate_messages"].append({
                                "type": msg["type"],
                                "checkpoint_id": cp.get("checkpoint_id"),
                                "checkpoint_index": cp_idx
                            })
            
            # Add the last step if it exists
            if current_step:
                steps.append(current_step)
            
            # Mark duplicate tool calls
            seen_tool_call_ids = set()
            for step in steps:
                for tc in step["tool_calls"]:
                    if tc["id"] in seen_tool_call_ids:
                        tc["is_duplicate"] = True
                    else:
                        seen_tool_call_ids.add(tc["id"])
            
            return steps
        
        finally:
            # Switch back to original session
            if session_id != original_session_id:
                self._switch_checkpointer(original_session_id)

    def export_session_markdown(self, session_id=None):
        """
        Export a session to a formatted Markdown file with duplicate handling.
        Shows clean de-duplicated content with markers for duplicate entries.
        Preserves all original checkpoint information for auditing.
        
        Args:
            session_id: ID of the session to export. Uses current session if None.
            
        Returns:
            str: Path to the exported Markdown file, or None if export failed.
        """
        session_id = session_id or self.current_session_id
        if not session_id or session_id not in self.store.sessions:
            print("[Error] No active session")
            return None
        
        steps = self.get_session_steps(session_id)
        info = self.store.sessions[session_id]
        title = info.get("title", "Session Export")
        
        # Build Markdown content
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
                            # Auto-format JSON results for better readability
                            if isinstance(tc["result"], str):
                                result_json = json.loads(tc["result"])
                                md += f"```json\n{json.dumps(result_json, ensure_ascii=False, indent=2)}\n```\n"
                            else:
                                md += f"```json\n{json.dumps(tc['result'], ensure_ascii=False, indent=2)}\n```\n"
                        except (json.JSONDecodeError, TypeError):
                            # Fallback to plain text for non-JSON results
                            md += f"```\n{tc['result']}\n```\n"
                    md += "\n"
            
            # Add duplicate message notice if any
            if step.get("duplicate_messages"):
                duplicate_count = len(step["duplicate_messages"])
                md += f"⚠️ **Note**: {duplicate_count} duplicate messages detected across checkpoints (not shown)\n\n"
            
            md += "---\n\n"

        # Write to file under SESSIONS_DIR/<session_id>/
        session_dir = SESSIONS_DIR / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        timestamp = int(time.time())
        filename = session_dir / f"export_{timestamp}.md"
        
        with open(filename, "w", encoding="utf-8") as f:
            f.write(md)
        
        print(f"[Export] Session exported to: {filename}")
        return str(filename)

    def search_sessions(self, keyword):
        """
        Search all active sessions for a keyword in user inputs or AI responses.
        
        Args:
            keyword: The keyword to search for (case-insensitive).
        """
        print(f"\n[Search Results for: {keyword}]")
        found = False
        original_session_id = self.current_session_id
        
        for sid in self.store.sessions:
            # Temporarily switch to each session's checkpointer
            self._switch_checkpointer(sid)
            steps = self.get_session_steps(sid)
            
            for step in steps:
                if keyword.lower() in step["user_input"].lower() or keyword.lower() in step["ai_response"].lower():
                    title = self.store.sessions[sid].get("title", "New Session")
                    print(f"  Session: {sid} | {title} | Turn {step['step']}")
                    print(f"    User: {step['user_input'][:80]}...")
                    found = True
                    break
        
        # Switch back to original session
        self._switch_checkpointer(original_session_id)
        
        if not found:
            print("  No matching sessions found")
        print()

    def restore_archive(self, session_id, switch=True):
        """
        Restore an archived session including its database file.
        
        Args:
            session_id: ID of the archived session to restore.
            switch: Whether to switch to the restored session. Defaults to True.
            
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

        # Restore session metadata
        with open(archive_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        self.store.sessions[session_id] = data["info"]
        self.store.session_metrics[session_id] = data["metrics"]

        active_path = SESSIONS_DIR / f"{session_id}.json"
        archive_path.rename(active_path)
        
        # Restore database file
        if archive_db_path.exists():
            active_db_path = self._get_checkpoint_path(session_id)
            archive_db_path.rename(active_db_path)

        if switch:
            self._switch_checkpointer(session_id)
            self.current_session_id = session_id

        self.store.save_async(session_id)
        print(f"[Session] Restored from archive: {session_id}")
        return True

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
        # TODO: checkpoint_id is accepted but DeerFlowClient._get_runnable_config
        # does not forward it into configurable["checkpoint_id"].  Rollback will
        # take effect once the client is patched to include it.
        # if checkpoint_id:
        #     stream_kwargs["checkpoint_id"] = checkpoint_id

        full_response = ""
        tool_calls = 0
        total_tokens = 0

        # Stream the response
        for event in self.client.stream(message, **stream_kwargs):
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

        # Update session metrics
        self.store.session_metrics[session_id]["turns"] += 1
        self.store.session_metrics[session_id]["tool_calls"] += tool_calls
        self.store.session_metrics[session_id]["total_tokens"] += total_tokens

        # Get correct checkpoint ID from the latest checkpoint
        thread_data = self.client.get_thread(session_id)
        if thread_data["checkpoints"]:
            last_checkpoint_id = thread_data["checkpoints"][-1]["checkpoint_id"]
            self.store.sessions[session_id]["last_checkpoint_id"] = last_checkpoint_id

        # Auto-set session title from the first user message
        if self.store.sessions[session_id].get("title") in (None, "New Session") and full_response:
            self.store.sessions[session_id]["title"] = message[:30] + ("..." if len(message) > 30 else "")

        self.store.save_async(session_id)

        # Return final metrics
        yield f"\n\n[Metrics] Tokens: {total_tokens} | Tool Calls: {tool_calls}"

    def upload_file(self, file_path, session_id=None):
        """
        Upload a file to the current session.
        
        Args:
            file_path: Path to the file to upload.
            session_id: ID of the session. Uses current session if None.
            
        Returns:
            dict: Upload result from the client, or None if upload failed.
        """
        session_id = session_id or self.current_session_id
        if not session_id:
            print("[Error] No active session")
            return None
        if not os.path.exists(file_path):
            print(f"[Error] File not found: {file_path}")
            return None
        result = self.client.upload_files(session_id, [file_path])
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
        return self.client.list_uploads(session_id)

    def delete_upload(self, filename, session_id=None):
        """
        Delete an uploaded file from a session.
        
        Args:
            filename: Name of the file to delete.
            session_id: ID of the session. Uses current session if None.
            
        Returns:
            dict: Deletion result from the client, or None if deletion failed.
        """
        session_id = session_id or self.current_session_id
        if not session_id:
            print("[Error] No active session")
            return None
        return self.client.delete_upload(session_id, filename)

    def enable_skill(self, skill_name):
        """
        Enable a skill for the agent.
        
        Args:
            skill_name: Name of the skill to enable.
            
        Returns:
            bool: True if skill was enabled successfully, False otherwise.
        """
        try:
            self.client.update_skill(skill_name, enabled=True)
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
            bool: True if skill was disabled successfully, False otherwise.
        """
        try:
            self.client.update_skill(skill_name, enabled=False)
            print(f"[Skill] Disabled: {skill_name}")
            return True
        except Exception as e:
            print(f"[Error] Failed to disable skill: {e}")
            return False

    def switch_model(self, model_name):
        """
        Switch the agent to use a different model.
        
        Args:
            model_name: Name of the model to use.
            
        Returns:
            bool: True if model was switched successfully, False otherwise.
        """
        models = self.client.list_models()["models"]
        if not any(m["name"] == model_name for m in models):
            print(f"[Error] Model {model_name} not found")
            return False
        self.client._model_name = model_name
        print(f"[Model] Switched to: {model_name}")
        return True

    def enable_plan_mode(self):
        """Enable plan mode for the agent."""
        self.client._plan_mode = True
        print("[Mode] Plan mode enabled")

    def disable_plan_mode(self):
        """Disable plan mode for the agent."""
        self.client._plan_mode = False
        print("[Mode] Plan mode disabled")

    def enable_subagent(self):
        """Enable subagent delegation for the agent."""
        self.client._subagent_enabled = True
        print("[Mode] Subagent delegation enabled")

    def disable_subagent(self):
        """Disable subagent delegation for the agent."""
        self.client._subagent_enabled = False
        print("[Mode] Subagent delegation disabled")

    def get_all_checkpoint_steps(self, session_id=None):
        """
        Get a list of all checkpoints as individual steps.
        Only messages newly appearing in each checkpoint are shown (duplicates hidden).
        Every checkpoint is preserved for precise rollback and auditing.

        Args:
            session_id: Session ID, uses current session if None.

        Returns:
            list[dict]: Each element represents a checkpoint with:
                - checkpoint_id
                - parent_checkpoint_id
                - ts (timestamp)
                - new_messages: messages that first appeared in this checkpoint
                - has_new_content: whether this checkpoint introduced any new message
        """
        session_id = session_id or self.current_session_id
        if not session_id:
            return []

        original_session_id = self.current_session_id
        if session_id != original_session_id:
            self._switch_checkpointer(session_id)

        try:
            thread_data = self.client.get_thread(session_id)
            checkpoints = thread_data.get("checkpoints", [])
            if not checkpoints:
                return []

            seen_message_ids = set()
            checkpoint_steps = []

            for cp in checkpoints:
                messages = cp["values"].get("messages", [])
                new_msgs = []
                for msg in messages:
                    msg_id = msg.get("id")
                    if msg_id is None:
                        msg_id = f"__no_id__:{msg.get('type', '')}:{msg.get('content', '')}"
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

        finally:
            if session_id != original_session_id:
                self._switch_checkpointer(original_session_id)

    def export_all_checkpoints(self, session_id=None):
        """
        Export all checkpoints to a Markdown file.
        Duplicate messages are hidden but every checkpoint round is listed.
        Checkpoints with no new messages are still included for full traceability.

        Args:
            session_id: Session ID, uses current session if None.

        Returns:
            str: Path to the exported Markdown file, or None if export failed.
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
                md += "⚠️ This checkpoint introduced no new messages (content identical to previous checkpoint).\n\n"
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
                        md += f"#### [Tool Result]\n\n"
                        try:
                            result_json = json.loads(result)
                            md += f"```json\n{json.dumps(result_json, ensure_ascii=False, indent=2)}\n```\n\n"
                        except (json.JSONDecodeError, TypeError):
                            md += f"```\n{result}\n```\n\n"
            md += "---\n\n"

        # Write to file
        session_dir = SESSIONS_DIR / session_id
        session_dir.mkdir(parents=True, exist_ok=True)
        timestamp = int(time.time())
        filename = session_dir / f"export_all_checkpoints_{timestamp}.md"

        with open(filename, "w", encoding="utf-8") as f:
            f.write(md)

        print(f"[Export] All checkpoints exported to: {filename}")
        return str(filename)