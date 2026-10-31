"""Plugin-owned index and version history of pipeline-saved skills.

The host mutation service keeps the authoritative history, revisions and
storage, but its public contract exposes only per-operation lookups and the
host's ``revert`` can only undo the current head operation (CAS-fenced on
``asset.operation_id``) within its rollback window. This store therefore adds
two plugin-owned tables on top of the latest-outcome index:

* ``staged_proposals`` — the content of every candidate staged through the
  extension's managed actions, kept so a later ``commit`` can attach the exact
  bytes that became that version;
* ``evolved_history`` — an append-only journal of published operations with
  the resulting content (commits: the staged bytes; reverts: the content of
  the journal entry preceding the reverted operation, i.e. the restored
  state).

That journal is what lets the status page offer "restore this version": the
host has no way to jump back to an arbitrary old version (head-revert only),
so restoring replays the old bytes through a fresh stage → check → commit.
Content and revision truth still stays host-side; these copies are advisory
and may be missing (``has_content: false``) for older records.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from contextlib import closing
from pathlib import Path
from typing import Any

from deerflow_extension_api import ActionContext

_SCHEMA = """
CREATE TABLE IF NOT EXISTS evolved_skills (
    owner TEXT NOT NULL,
    name TEXT NOT NULL,
    method TEXT NOT NULL,
    operation_id TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (owner, name)
);
CREATE TABLE IF NOT EXISTS staged_proposals (
    proposal_id TEXT PRIMARY KEY,
    owner TEXT NOT NULL,
    name TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS evolved_history (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    owner TEXT NOT NULL,
    name TEXT NOT NULL,
    method TEXT NOT NULL,
    operation_id TEXT NOT NULL UNIQUE,
    proposal_id TEXT,
    content TEXT,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS evolved_history_owner_name ON evolved_history (owner, name, seq);
CREATE TABLE IF NOT EXISTS skill_annotations (
    owner TEXT NOT NULL,
    skill_name TEXT NOT NULL,
    run_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    note TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (owner, skill_name, run_id, event_id)
);
CREATE TABLE IF NOT EXISTS evolution_jobs (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL UNIQUE,
    owner TEXT NOT NULL,
    skill_name TEXT NOT NULL,
    status TEXT NOT NULL,
    base_content TEXT NOT NULL,
    result_content TEXT,
    feedback_count INTEGER NOT NULL DEFAULT 0,
    resolved_model TEXT,
    input_tokens INTEGER,
    output_tokens INTEGER,
    error_code TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS evolution_jobs_owner_skill ON evolution_jobs (owner, skill_name, updated_at);
-- At most one running job per (owner, skill): the partial unique index makes
-- the admission race-free even across concurrent action calls.
CREATE UNIQUE INDEX IF NOT EXISTS evolution_jobs_one_running ON evolution_jobs (owner, skill_name) WHERE status='running';
"""
_METHODS = frozenset({"commit", "revert"})
_MAX_FIELD_BYTES = 128
# Mirrors the host's default max_main_bytes with headroom; the managed pipeline
# already enforces the real per-host limit before staging.
_MAX_CONTENT_BYTES = 262144
_HISTORY_LIMIT = 20
_MAX_NOTE_BYTES = 2000


def _bounded(value: Any) -> str:
    if not isinstance(value, str) or not value or len(value.encode("utf-8")) > _MAX_FIELD_BYTES or any(ord(c) < 32 for c in value):
        raise ValueError("record fields must be non-empty bounded strings")
    return value


def _content(value: Any) -> str:
    if not isinstance(value, str) or not value or len(value.encode("utf-8")) > _MAX_CONTENT_BYTES:
        raise ValueError("content must be a non-empty bounded string")
    return value


class EvolvedSkillStore:
    """Latest pipeline outcome per (owner, skill) plus its version journal."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        if not self.path.is_absolute():
            raise ValueError("storage_path must be an absolute deployment-owned path")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self.connect()) as db, db:
            db.executescript(_SCHEMA)

    def connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        return db

    def _upsert_latest(self, db: sqlite3.Connection, *, owner: str, name: str, method: str, operation_id: str) -> None:
        db.execute(
            "INSERT INTO evolved_skills (owner, name, method, operation_id, updated_at)"
            " VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)"
            " ON CONFLICT(owner, name) DO UPDATE SET"
            " method=excluded.method, operation_id=excluded.operation_id, updated_at=CURRENT_TIMESTAMP",
            (owner, name, method, operation_id),
        )

    def record_stage(self, *, owner: str, proposal_id: str, name: str, content: str) -> None:
        """Remember the bytes of one staged candidate so a later commit can attach them."""
        owner, name, proposal_id = _bounded(owner), _bounded(name), _bounded(proposal_id)
        content = _content(content)
        with closing(self.connect()) as db, db:
            db.execute(
                "INSERT INTO staged_proposals (proposal_id, owner, name, content, created_at) VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP) ON CONFLICT(proposal_id) DO UPDATE SET owner=excluded.owner, name=excluded.name, content=excluded.content",
                (proposal_id, owner, name, content),
            )

    def record_outcome(self, *, owner: str, name: str, method: str, operation_id: str, proposal_id: str | None = None, reverts_operation_id: str | None = None) -> None:
        """Append one published operation to the journal and refresh the latest row.

        Commits take their content from the staged snapshot of the proposal;
        reverts restore the content of the journal entry preceding the reverted
        operation (the state the revert returns to).
        """
        if method not in _METHODS:
            raise ValueError("method must be commit or revert")
        owner, name, operation_id = _bounded(owner), _bounded(name), _bounded(operation_id)
        with closing(self.connect()) as db, db:
            content: str | None = None
            if method == "commit":
                if proposal_id is not None:
                    proposal_id = _bounded(proposal_id)
                    row = db.execute(
                        "SELECT content FROM staged_proposals WHERE proposal_id=? AND owner=?",
                        (proposal_id, owner),
                    ).fetchone()
                    if row is not None:
                        content = row["content"]
                        db.execute("DELETE FROM staged_proposals WHERE proposal_id=?", (proposal_id,))
            elif reverts_operation_id is not None:
                reverts_operation_id = _bounded(reverts_operation_id)
                target = db.execute(
                    "SELECT seq FROM evolved_history WHERE owner=? AND operation_id=?",
                    (owner, reverts_operation_id),
                ).fetchone()
                if target is not None:
                    previous = db.execute(
                        "SELECT content FROM evolved_history WHERE owner=? AND name=? AND seq<? ORDER BY seq DESC LIMIT 1",
                        (owner, name, target["seq"]),
                    ).fetchone()
                    if previous is not None:
                        content = previous["content"]
            db.execute(
                "INSERT INTO evolved_history (owner, name, method, operation_id, proposal_id, content, updated_at) VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP) ON CONFLICT(operation_id) DO NOTHING",
                (owner, name, method, operation_id, proposal_id, content),
            )
            self._upsert_latest(db, owner=owner, name=name, method=method, operation_id=operation_id)

    def get_version(self, *, owner: str, operation_id: str) -> dict[str, Any] | None:
        if not isinstance(owner, str) or not owner or not isinstance(operation_id, str) or not operation_id:
            return None
        with closing(self.connect()) as db:
            row = db.execute(
                "SELECT seq, name, method, operation_id, updated_at, content FROM evolved_history WHERE owner=? AND operation_id=?",
                (owner, operation_id),
            ).fetchone()
        if row is None:
            return None
        return {
            "seq": row["seq"],
            "name": row["name"],
            "method": row["method"],
            "operation_id": row["operation_id"],
            "updated_at": row["updated_at"],
            "content": row["content"],
        }

    def list_skills(self, *, owner: str) -> list[dict[str, Any]]:
        if not isinstance(owner, str) or not owner:
            return []
        with closing(self.connect()) as db:
            rows = db.execute(
                "SELECT name, method, operation_id, updated_at FROM evolved_skills WHERE owner=? ORDER BY updated_at DESC, name",
                (owner,),
            ).fetchall()
            skills = []
            for row in rows:
                history = db.execute(
                    "SELECT seq, method, operation_id, updated_at, content IS NOT NULL AS has_content FROM evolved_history WHERE owner=? AND name=? ORDER BY seq DESC LIMIT ?",
                    (owner, row["name"], _HISTORY_LIMIT),
                ).fetchall()
                skills.append(
                    {
                        "name": row["name"],
                        "method": row["method"],
                        "operation_id": row["operation_id"],
                        "updated_at": row["updated_at"],
                        "history": [
                            {
                                "seq": entry["seq"],
                                "method": entry["method"],
                                "operation_id": entry["operation_id"],
                                "updated_at": entry["updated_at"],
                                "has_content": bool(entry["has_content"]),
                            }
                            for entry in history
                        ],
                    }
                )
        return skills

    def save_annotation(self, *, owner: str, skill_name: str, run_id: str, event_id: str, note: str) -> None:
        """Attach or replace the caller's note on one trajectory event."""
        owner, skill_name, run_id, event_id = _bounded(owner), _bounded(skill_name), _bounded(run_id), _bounded(event_id)
        if not isinstance(note, str) or not note or len(note.encode("utf-8")) > _MAX_NOTE_BYTES:
            raise ValueError("note must be a non-empty bounded string")
        with closing(self.connect()) as db, db:
            db.execute(
                "INSERT INTO skill_annotations (owner, skill_name, run_id, event_id, note, updated_at)"
                " VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)"
                " ON CONFLICT(owner, skill_name, run_id, event_id) DO UPDATE SET"
                " note=excluded.note, updated_at=CURRENT_TIMESTAMP",
                (owner, skill_name, run_id, event_id, note),
            )

    def delete_annotation(self, *, owner: str, skill_name: str, run_id: str, event_id: str) -> bool:
        """Remove one note; returns whether a row was deleted."""
        owner, skill_name, run_id, event_id = _bounded(owner), _bounded(skill_name), _bounded(run_id), _bounded(event_id)
        with closing(self.connect()) as db, db:
            cursor = db.execute(
                "DELETE FROM skill_annotations WHERE owner=? AND skill_name=? AND run_id=? AND event_id=?",
                (owner, skill_name, run_id, event_id),
            )
            return cursor.rowcount > 0

    def list_annotations(self, *, owner: str, skill_name: str) -> list[dict[str, Any]]:
        """All of one caller's notes for a skill, newest change first."""
        if not isinstance(owner, str) or not owner or not isinstance(skill_name, str) or not skill_name:
            return []
        with closing(self.connect()) as db:
            rows = db.execute(
                "SELECT run_id, event_id, note, updated_at FROM skill_annotations WHERE owner=? AND skill_name=? ORDER BY updated_at DESC, run_id, event_id",
                (owner, skill_name),
            ).fetchall()
        return [{"run_id": row["run_id"], "event_id": row["event_id"], "note": row["note"], "updated_at": row["updated_at"]} for row in rows]

    # --- annotation-triggered evolution jobs (Plan B) -----------------------
    #
    # One background model call per job, recorded per (owner, skill) so the
    # page can poll progress and later diff the result against base_content.
    # The partial unique index evolution_jobs_one_running enforces at most one
    # running job per (owner, skill); finish_job is CAS-fenced on status so a
    # stale task can never overwrite a terminal record.

    _JOB_KEEP = 10

    def start_job(self, *, owner: str, skill_name: str, job_id: str, base_content: str, feedback_count: int) -> bool:
        """Admit one running job; ``False`` when one is already running."""
        owner, skill_name, job_id = _bounded(owner), _bounded(skill_name), _bounded(job_id)
        base_content = _content(base_content)
        if not isinstance(feedback_count, int) or feedback_count < 0:
            raise ValueError("feedback_count must be a non-negative integer")
        with closing(self.connect()) as db, db:
            try:
                db.execute(
                    "INSERT INTO evolution_jobs (job_id, owner, skill_name, status, base_content, feedback_count) VALUES (?, ?, ?, 'running', ?, ?)",
                    (job_id, owner, skill_name, base_content, feedback_count),
                )
            except sqlite3.IntegrityError:
                return False
            db.execute(
                "DELETE FROM evolution_jobs WHERE owner=? AND skill_name=? AND job_id NOT IN (SELECT job_id FROM evolution_jobs WHERE owner=? AND skill_name=? ORDER BY seq DESC LIMIT ?)",
                (owner, skill_name, owner, skill_name, self._JOB_KEEP),
            )
            return True

    def finish_job(
        self,
        *,
        owner: str,
        job_id: str,
        status: str,
        result_content: str | None = None,
        resolved_model: str | None = None,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        error_code: str | None = None,
    ) -> bool:
        """Terminal-write one running job; ``False`` when it is not running."""
        if status not in ("succeeded", "failed"):
            raise ValueError("job status must be succeeded or failed")
        owner, job_id = _bounded(owner), _bounded(job_id)
        if resolved_model is not None:
            resolved_model = _bounded(resolved_model)
        if error_code is not None:
            error_code = _bounded(error_code)
        if result_content is not None:
            result_content = _content(result_content)
        with closing(self.connect()) as db, db:
            cursor = db.execute(
                "UPDATE evolution_jobs SET status=?, result_content=?, resolved_model=?, input_tokens=?, output_tokens=?, error_code=?, updated_at=CURRENT_TIMESTAMP WHERE owner=? AND job_id=? AND status='running'",
                (status, result_content, resolved_model, input_tokens, output_tokens, error_code, owner, job_id),
            )
            return cursor.rowcount > 0

    def sweep_stale_jobs(self, *, owner: str, skill_name: str) -> int:
        """Fail jobs stuck running past any plausible grant timeout.

        A task cancelled by Gateway shutdown or a crashed process would
        otherwise block admission for that (owner, skill) forever. The host's
        model-invocation grant caps timeouts at 600s, so 30 minutes is
        safely beyond any live call.
        """
        owner, skill_name = _bounded(owner), _bounded(skill_name)
        with closing(self.connect()) as db, db:
            cursor = db.execute(
                "UPDATE evolution_jobs SET status='failed', error_code='STALE', updated_at=CURRENT_TIMESTAMP WHERE owner=? AND skill_name=? AND status='running' AND updated_at < datetime('now', '-30 minutes')",
                (owner, skill_name),
            )
            return cursor.rowcount

    def _job_view(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "job_id": row["job_id"],
            "skill_name": row["skill_name"],
            "status": row["status"],
            "feedback_count": row["feedback_count"],
            "resolved_model": row["resolved_model"],
            "input_tokens": row["input_tokens"],
            "output_tokens": row["output_tokens"],
            "error_code": row["error_code"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "base_content": row["base_content"],
            "result_content": row["result_content"],
        }

    def latest_job(self, *, owner: str, skill_name: str) -> dict[str, Any] | None:
        """The newest job for one caller and skill (any status), or ``None``."""
        if not isinstance(owner, str) or not owner or not isinstance(skill_name, str) or not skill_name:
            return None
        with closing(self.connect()) as db:
            # seq is the monotonic tiebreak: CURRENT_TIMESTAMP has only second
            # resolution, so rapid jobs would otherwise tie on updated_at.
            row = db.execute(
                "SELECT * FROM evolution_jobs WHERE owner=? AND skill_name=? ORDER BY seq DESC LIMIT 1",
                (owner, skill_name),
            ).fetchone()
        return self._job_view(row) if row is not None else None

    def latest_committed_content(self, *, owner: str, name: str) -> str | None:
        """The content of the newest journal entry for one caller's skill.

        Lets the evolution-job view detect that a model draft has since been
        published through the managed pipeline, without new state: the job
        record itself stays untouched.
        """
        if not isinstance(owner, str) or not owner or not isinstance(name, str) or not name:
            return None
        with closing(self.connect()) as db:
            row = db.execute(
                "SELECT content FROM evolved_history WHERE owner=? AND name=? ORDER BY seq DESC LIMIT 1",
                (owner, name),
            ).fetchone()
        if row is None:
            return None
        content = row["content"]
        return content if isinstance(content, str) and content else None

    def job_is_published(self, *, owner: str, name: str, job: Mapping[str, Any]) -> bool:
        """Whether a succeeded job's draft was committed after the job finished.

        A draft matching an *older* commit is not a publish: that is the model
        returning the input unchanged (the annotations were already covered),
        which ``job_is_unchanged`` reports instead. Trailing whitespace is
        ignored: the draft carries a normalised trailing newline the staged
        editor value may lack.
        """
        if not isinstance(job, Mapping) or job.get("status") != "succeeded":
            return False
        draft = job.get("result_content")
        finished_at = job.get("updated_at")
        if not isinstance(draft, str) or not isinstance(finished_at, str) or not finished_at:
            return False
        if not isinstance(owner, str) or not owner or not isinstance(name, str) or not name:
            return False
        with closing(self.connect()) as db:
            row = db.execute(
                "SELECT content, updated_at FROM evolved_history WHERE owner=? AND name=? ORDER BY seq DESC LIMIT 1",
                (owner, name),
            ).fetchone()
        if row is None:
            return False
        committed = row["content"]
        committed_at = row["updated_at"]
        return isinstance(committed, str) and committed.rstrip() == draft.rstrip() and isinstance(committed_at, str) and committed_at >= finished_at

    @staticmethod
    def job_is_unchanged(job: Mapping[str, Any]) -> bool:
        """Whether a succeeded job returned its input content unchanged.

        The model reviewed the annotations and kept the content as is — there
        is no diff to review, and a later annotation supersedes the record.
        """
        if not isinstance(job, Mapping) or job.get("status") != "succeeded":
            return False
        draft = job.get("result_content")
        base = job.get("base_content")
        return isinstance(draft, str) and isinstance(base, str) and draft.rstrip() == base.rstrip()

    def delete_published_job(self, *, owner: str, skill_name: str) -> bool:
        """Drop the latest job when its outcome needs no further review.

        Both a draft published through the managed pipeline and a no-change
        draft (the model kept the content) are consumed: new or updated
        annotations supersede them and the panel returns to the trigger.
        Pending diffs and failures stay. The version journal is untouched.
        Returns whether a job was deleted.
        """
        job = self.latest_job(owner=owner, skill_name=skill_name)
        if job is None:
            return False
        if not (self.job_is_published(owner=owner, name=skill_name, job=job) or self.job_is_unchanged(job)):
            return False
        return self.delete_job(owner=owner, job_id=job["job_id"])

    def delete_job(self, *, owner: str, job_id: str, skill_name: str | None = None) -> bool:
        """Discard one caller's job record; returns whether a row was deleted."""
        owner, job_id = _bounded(owner), _bounded(job_id)
        with closing(self.connect()) as db, db:
            if skill_name is None:
                cursor = db.execute("DELETE FROM evolution_jobs WHERE owner=? AND job_id=?", (owner, job_id))
            else:
                cursor = db.execute("DELETE FROM evolution_jobs WHERE owner=? AND skill_name=? AND job_id=?", (owner, _bounded(skill_name), job_id))
            return cursor.rowcount > 0


class EvolvedSkills:
    """Read-only backend actions over the caller's pipeline-saved skills.

    The acting owner is always the principal's user id — never a payload
    field — so records stay per-user even though the store is shared.
    """

    def __init__(self, store: EvolvedSkillStore | None) -> None:
        self._store = store

    async def list(self, payload: Any, ctx: ActionContext) -> dict[str, Any]:
        principal = getattr(ctx, "principal", None)
        user_id = getattr(principal, "user_id", None)
        if not isinstance(user_id, str) or not user_id:
            return {"ok": False, "error": {"code": "UNAUTHENTICATED"}}
        if payload is None:
            payload = {}
        if not isinstance(payload, Mapping) or len(payload) != 0:
            return {"ok": False, "error": {"code": "INVALID_REQUEST"}}
        if self._store is None:
            return {"ok": False, "error": {"code": "UNAVAILABLE"}}
        return {"ok": True, "skills": self._store.list_skills(owner=user_id)}

    async def version(self, payload: Any, ctx: ActionContext) -> dict[str, Any]:
        principal = getattr(ctx, "principal", None)
        user_id = getattr(principal, "user_id", None)
        if not isinstance(user_id, str) or not user_id:
            return {"ok": False, "error": {"code": "UNAUTHENTICATED"}}
        if not isinstance(payload, Mapping) or set(payload) != {"operation_id"}:
            return {"ok": False, "error": {"code": "INVALID_REQUEST"}}
        operation_id = payload.get("operation_id")
        if not isinstance(operation_id, str) or not operation_id or len(operation_id.encode("utf-8")) > _MAX_FIELD_BYTES or any(ord(c) < 32 for c in operation_id):
            return {"ok": False, "error": {"code": "INVALID_REQUEST"}}
        if self._store is None:
            return {"ok": False, "error": {"code": "UNAVAILABLE"}}
        entry = self._store.get_version(owner=user_id, operation_id=operation_id)
        if entry is None or entry.get("content") is None:
            # Missing and foreign entries are indistinguishable on purpose.
            return {"ok": False, "error": {"code": "NOT_FOUND_OR_FORBIDDEN"}}
        return {"ok": True, "version": entry}
