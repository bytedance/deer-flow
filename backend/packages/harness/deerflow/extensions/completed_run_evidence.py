"""Owner-bound durable run evidence, with fixed boundaries and bounded reads."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
from dataclasses import asdict, replace
from datetime import UTC, datetime
from time import monotonic
from uuid import uuid4

from deerflow_extension_api.completed_run_evidence import CompletedRunEvent, CompletedRunEventPage, CompletedRunSnapshot, EvidenceLimits
from deerflow_extension_api.host_capabilities import HostCapabilityError
from deerflow_extension_api.run_evidence import RunPage, RunStatusView
from sqlalchemy import LargeBinary, Text, and_, cast, func, or_, select, text

from deerflow.persistence.models.run_event import RunEventRow
from deerflow.persistence.run.model import CompletedRunSnapshotRow, RunRow
from deerflow.persistence.run.sql import RunRepository
from deerflow.runtime.events.store.db import DbRunEventStore
from deerflow.runtime.secret_context import redact_metadata_secrets
from deerflow.utils.time import coerce_iso


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _size(value) -> int:
    return len(_json(asdict(value)).encode("utf-8"))


def _snapshot(payload: dict) -> CompletedRunSnapshot:
    return CompletedRunSnapshot(**{**payload, "coverage_limits": tuple(payload["coverage_limits"]), "skill_observations": tuple(payload["skill_observations"])})


class HostCompletedRunEvidenceReader:
    """Bindings come from trusted installation grants, never call arguments.

    This is a supported capability boundary for trusted in-process plugins,
    not a sandbox against code holding a raw database session factory.

    New events carry an ingestion digest. Legacy digest computation has a
    cumulative per-page cap of 1 MiB, 64 SQL chunks, and 2 seconds (including
    query waits). Above those caps we raise LIMIT_EXCEEDED, never invent a hash
    or trust a digest supplied in event metadata.
    """

    def __init__(self, run_store, event_store, *, plugin_id: str, owner_ids) -> None:
        if not isinstance(plugin_id, str) or not plugin_id.strip():
            raise ValueError("a stable plugin identity is required")
        if not owner_ids or isinstance(owner_ids, (str, bytes)) or any(not isinstance(owner, str) or not owner.strip() or owner == "*" for owner in owner_ids):
            raise ValueError("an explicit nonempty owner allowlist is required")
        self._owners = frozenset(owner_ids)
        self._scope = hashlib.sha256(_json([plugin_id, sorted(self._owners)]).encode()).hexdigest()
        self._sf = run_store._sf if isinstance(run_store, RunRepository) and isinstance(event_store, DbRunEventStore) and run_store._sf is event_store._sf else None

    def _supported(self) -> None:
        if self._sf is None:
            raise HostCapabilityError("UNSUPPORTED", "completed evidence requires durable run and event stores on the same database")

    def _cursor(self, kind: str, position, reference: str = "") -> str:
        return base64.urlsafe_b64encode(_json([1, self._scope, kind, reference, position]).encode()).decode().rstrip("=")

    def _position(self, cursor: str | None, kind: str, reference: str = ""):
        if cursor is None:
            return None
        try:
            if not isinstance(cursor, str) or len(cursor) > 2048:
                raise ValueError
            value = json.loads(base64.b64decode(cursor + "=" * (-len(cursor) % 4), altchars=b"-_", validate=True))
            if not isinstance(value, list) or len(value) != 5 or value[:4] != [1, self._scope, kind, reference]:
                raise ValueError
            position = value[4]
            if kind == "runs":
                if not isinstance(position, list) or len(position) != 2 or type(position[0]) is not int or position[0] < 0 or not isinstance(position[1], str):
                    raise ValueError
            elif type(position) is not int or position < 0:
                raise ValueError
            return position
        except (ValueError, TypeError, UnicodeDecodeError) as exc:
            raise HostCapabilityError("INVALID_CURSOR", "cursor does not match this plugin, scope, version, or snapshot") from exc

    async def list_changed_runs(self, *, cursor: str | None = None, limit: int = 200) -> RunPage:
        self._supported()
        EvidenceLimits(max_events=limit)
        seq, run_id = self._position(cursor, "runs") or (-1, "")
        stmt = (
            select(RunRow.thread_id, RunRow.run_id, RunRow.status, RunRow.created_at, RunRow.updated_at, RunRow.stop_reason, RunRow.change_seq)
            .where(
                RunRow.user_id.in_(self._owners),
                RunRow.operation_kind == "run",
                or_(RunRow.change_seq > seq, and_(RunRow.change_seq == seq, RunRow.run_id > run_id)),
            )
            .order_by(RunRow.change_seq, RunRow.run_id)
            .limit(limit + 1)
        )
        async with self._sf() as session:
            rows = (await session.execute(stmt)).all()
        items = []
        next_cursor = cursor
        for row in rows[:limit]:
            item = RunStatusView(thread_id=row.thread_id, run_id=row.run_id, status=row.status, created_at=coerce_iso(row.created_at), updated_at=coerce_iso(row.updated_at), stop_reason=row.stop_reason)
            candidate_cursor = self._cursor("runs", [row.change_seq, row.run_id])
            if _size(RunPage(tuple([*items, item]), candidate_cursor, True)) > 1024 * 1024:
                break
            items.append(item)
            next_cursor = candidate_cursor
        return RunPage(tuple(items), next_cursor, len(rows) > len(items))

    async def _begin_read(self, session) -> None:
        # sqlite's legacy transaction mode does not BEGIN on SELECT. Explicitly
        # start a transaction so owner/revision checks and content share a snapshot.
        if session.bind.dialect.name == "sqlite":
            await session.execute(text("BEGIN"))

    async def _run(self, session, thread_id: str, run_id: str, *, write: bool = False):
        columns = [
            RunRow.thread_id,
            RunRow.run_id,
            RunRow.user_id,
            RunRow.assistant_id,
            RunRow.status,
            RunRow.stop_reason,
            RunRow.created_at,
            RunRow.evidence_origin,
            RunRow.evidence_agent_id,
            RunRow.evidence_seal_state,
            RunRow.evidence_seal_error,
            RunRow.evidence_revision,
            RunRow.evidence_upper_seq,
            RunRow.evidence_event_count,
            RunRow.evidence_retention_revision,
            RunRow.lease_expires_at,
        ]
        stmt = select(*columns).where(RunRow.thread_id == thread_id, RunRow.run_id == run_id, RunRow.user_id.in_(self._owners), RunRow.operation_kind == "run").with_for_update(read=not write)
        row = (await session.execute(stmt)).one_or_none()
        if row is None:
            raise HostCapabilityError("NOT_FOUND", "run or snapshot is unavailable in this scope")
        return row

    @staticmethod
    def _seal_state(run) -> str:
        seal = run.evidence_seal_state or "partial"
        if seal == "pending" and run.status not in ("pending", "running"):
            lease = run.lease_expires_at
            if lease is None or lease.replace(tzinfo=UTC) <= datetime.now(UTC):
                return "partial"
        return seal

    @classmethod
    def _revision(cls, run) -> str:
        # Include lifecycle transitions before a seal exists. Otherwise a
        # pending snapshot could hide the subsequent terminal/partial record.
        return hashlib.sha256(_json([run.evidence_revision, run.run_id, coerce_iso(run.created_at), run.status, cls._seal_state(run)]).encode()).hexdigest()

    @staticmethod
    def _event_conditions(run):
        return [RunEventRow.thread_id == run.thread_id, RunEventRow.run_id == run.run_id, or_(RunEventRow.user_id == run.user_id, RunEventRow.user_id.is_(None))]

    async def get_snapshot(self, *, thread_id: str, run_id: str, limits: EvidenceLimits = EvidenceLimits()) -> CompletedRunSnapshot:
        self._supported()
        if not isinstance(limits, EvidenceLimits):
            raise ValueError("limits must be EvidenceLimits")
        async with self._sf() as session:
            if session.bind.dialect.name == "sqlite":
                await session.execute(text("BEGIN IMMEDIATE"))
            run = await self._run(session, thread_id, run_id, write=True)
            revision = self._revision(run)
            existing = await session.scalar(
                select(CompletedRunSnapshotRow).where(
                    CompletedRunSnapshotRow.run_id == run_id,
                    CompletedRunSnapshotRow.scope_digest == self._scope,
                    CompletedRunSnapshotRow.evidence_revision == revision,
                    CompletedRunSnapshotRow.retention_revision == run.evidence_retention_revision,
                )
            )
            if existing is not None:
                snap = _snapshot(existing.snapshot_json)
                if _size(snap) > limits.max_bytes:
                    raise HostCapabilityError("LIMIT_EXCEEDED", "snapshot envelope exceeds byte budget")
                return snap
            seal = self._seal_state(run)
            if seal == "sealed":
                upper, count = run.evidence_upper_seq, run.evidence_event_count
                if upper is None or count is None:
                    seal = "partial"
            if seal != "sealed":
                upper, count = (await session.execute(select(func.max(RunEventRow.seq), func.count()).where(*self._event_conditions(run)))).one()
            snap = CompletedRunSnapshot(
                snapshot_ref=uuid4().hex,
                evidence_revision=revision,
                retention_revision=run.evidence_retention_revision,
                thread_id=thread_id,
                run_id=run_id,
                owner_id=run.user_id,
                agent_id=run.evidence_agent_id,
                origin=run.evidence_origin or "unknown",
                status=run.status,
                stop_reason=run.stop_reason,
                seal_state=seal,
                seal_error=run.evidence_seal_error,
                upper_event_seq=upper or 0,
                event_count=count or 0,
            )
            if _size(snap) > limits.max_bytes:
                raise HostCapabilityError("LIMIT_EXCEEDED", "snapshot envelope exceeds byte budget")
            session.add(CompletedRunSnapshotRow(snapshot_ref=snap.snapshot_ref, run_id=run_id, scope_digest=self._scope, evidence_revision=revision, retention_revision=snap.retention_revision, snapshot_json=asdict(snap)))
            await session.commit()
            return snap

    @staticmethod
    def _content_bytes(session):
        if session.bind.dialect.name == "postgresql":
            return func.convert_to(RunEventRow.content, "UTF8")
        return cast(RunEventRow.content, LargeBinary)

    async def _content_hash(self, session, event_id: int, size: int, budget: dict, raw: bytes | None = None) -> str:
        chunks = (size + 16383) // 16384 if raw is None else 0
        remaining_time = budget["deadline"] - monotonic()
        if size > budget["bytes"] or chunks > budget["queries"] or remaining_time <= 0:
            raise HostCapabilityError("LIMIT_EXCEEDED", "legacy event digest exceeds the per-page verification budget")
        budget["bytes"] -= size
        budget["queries"] -= chunks
        if raw is not None:
            return hashlib.sha256(raw).hexdigest()
        digest = hashlib.sha256()
        try:
            async with asyncio.timeout(remaining_time):
                for start in range(1, size + 1, 16384):
                    chunk = await session.scalar(select(func.substr(self._content_bytes(session), start, 16384)).where(RunEventRow.id == event_id))
                    digest.update(chunk or b"")
        except TimeoutError as exc:
            raise HostCapabilityError("LIMIT_EXCEEDED", "legacy event digest verification deadline exceeded") from exc
        return digest.hexdigest()

    async def _resolve_snapshot(self, session, snapshot_ref: str):
        stored = await session.scalar(select(CompletedRunSnapshotRow).where(CompletedRunSnapshotRow.snapshot_ref == snapshot_ref, CompletedRunSnapshotRow.scope_digest == self._scope))
        if stored is None:
            raise HostCapabilityError("NOT_FOUND", "snapshot is unavailable in this scope")
        snap = _snapshot(stored.snapshot_json)
        run = await self._run(session, snap.thread_id, snap.run_id)
        if run.user_id != snap.owner_id or run.evidence_retention_revision != snap.retention_revision or self._revision(run) != snap.evidence_revision:
            raise HostCapabilityError("EVIDENCE_EXPIRED", "snapshot revision was replaced or its events were removed")
        return snap, run

    async def resolve_snapshot(self, snapshot_ref: str) -> CompletedRunSnapshot:
        """Internal host composition hook; authorization is checked anew per call."""
        self._supported()
        async with self._sf() as session:
            await self._begin_read(session)
            snap, _run = await self._resolve_snapshot(session, snapshot_ref)
            return snap

    async def read_events(self, *, snapshot_ref: str, cursor: str | None = None, limits: EvidenceLimits = EvidenceLimits()) -> CompletedRunEventPage:
        self._supported()
        if not isinstance(limits, EvidenceLimits):
            raise ValueError("limits must be EvidenceLimits")
        after = self._position(cursor, "events", snapshot_ref) or 0
        legacy_budget = {"bytes": 1024 * 1024, "queries": 64, "deadline": monotonic() + 2}
        async with self._sf() as session:
            await self._begin_read(session)
            snap, run = await self._resolve_snapshot(session, snapshot_ref)
            conditions = [*self._event_conditions(run), RunEventRow.seq > after, RunEventRow.seq <= snap.upper_event_seq]
            length = (lambda col: func.octet_length(col)) if session.bind.dialect.name == "postgresql" else (lambda col: func.length(cast(col, LargeBinary)))
            metadata_text = cast(RunEventRow.event_metadata, Text)
            # Metadata and body lengths are projected separately; ORM never
            # hydrates all rows (or an entire giant event) for a bounded page.
            rows = (
                await session.execute(
                    select(RunEventRow.id, RunEventRow.seq, RunEventRow.event_type, RunEventRow.category, RunEventRow.content_sha256, length(RunEventRow.content).label("body_size"), length(metadata_text).label("meta_size"))
                    .where(*conditions)
                    .order_by(RunEventRow.seq)
                    .limit(limits.max_events + 1)
                )
            ).all()
            items = []
            next_cursor = cursor
            for row in rows[: limits.max_events]:
                remaining = limits.max_bytes - _size(CompletedRunEventPage(tuple(items), next_cursor, True))
                oversized = (row.body_size or 0) + (row.meta_size or 0) > max(0, remaining - 700) // 2
                body_limit = 128 if oversized else limits.max_bytes
                raw_bytes, raw_meta = (await session.execute(select(func.substr(self._content_bytes(session), 1, body_limit), func.substr(metadata_text, 1, 2 if oversized else limits.max_bytes)).where(RunEventRow.id == row.id))).one()
                raw = (raw_bytes or b"").decode("utf-8", errors="ignore" if oversized else "strict")
                metadata = {} if oversized else json.loads(raw_meta or "{}")
                content = raw or ""
                if not oversized and (metadata.get("content_is_json") or metadata.get("content_is_dict")):
                    try:
                        content = json.loads(content)
                    except ValueError:
                        pass
                digest = row.content_sha256 or await self._content_hash(session, row.id, row.body_size or 0, legacy_budget, None if oversized else raw_bytes or b"")
                item = CompletedRunEvent(
                    event_id=str(row.id),
                    seq=row.seq,
                    event_type=row.event_type,
                    category=row.category,
                    content_json=_json(content),
                    metadata_json=_json(redact_metadata_secrets(metadata)),
                    content_bytes=row.body_size or 0,
                    content_sha256=digest,
                    truncated=oversized,
                )
                candidate_cursor = self._cursor("events", row.seq, snapshot_ref)
                candidate = CompletedRunEventPage(tuple([*items, item]), candidate_cursor, True)
                if _size(candidate) > limits.max_bytes:
                    if items:
                        break
                    item = replace(item, content_json='""', metadata_json="{}", truncated=True)
                    candidate = CompletedRunEventPage((item,), candidate_cursor, True)
                    if _size(candidate) > limits.max_bytes:
                        raise HostCapabilityError("LIMIT_EXCEEDED", "event identity envelope exceeds byte budget")
                items.append(item)
                next_cursor = candidate_cursor
            return CompletedRunEventPage(tuple(items), next_cursor, len(rows) > len(items))
