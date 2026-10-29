"""PostgreSQL enforcement and offline activation of Run producer fencing."""

from __future__ import annotations

from sqlalchemy import func, inspect, select, text


def install_event_guard(connection) -> None:
    """Used by both Alembic and metadata bootstrap; never manufacture authority."""
    if connection.dialect.name != "postgresql":
        return
    inspector = inspect(connection)
    if not all(inspector.has_table(name) for name in ("runs", "run_events", "run_producer_policy")):
        return
    if "run_incarnation" not in {column["name"] for column in inspector.get_columns("runs")}:
        return
    schema = connection.scalar(text("SELECT current_schema()"))
    quoted = connection.dialect.identifier_preparer.quote(schema)
    connection.execute(
        text(f"""
CREATE OR REPLACE FUNCTION {quoted}.run_event_producer_guard() RETURNS trigger
LANGUAGE plpgsql VOLATILE SET search_path TO {quoted}, pg_catalog AS $guard$
DECLARE r record; t record; a jsonb; strict_mode boolean; seed_prefix text;
BEGIN
    SELECT strict INTO strict_mode FROM run_producer_policy WHERE id=1;
    IF NOT coalesce(strict_mode, false) THEN
        -- A retained snapshot cannot observe activation after waiting. Never
        -- let it bypass strict enforcement using an old off/missing policy.
        IF current_setting('transaction_isolation') NOT IN ('read committed', 'read uncommitted') THEN
            RAISE EXCEPTION 'Off-mode run events require READ COMMITTED isolation' USING ERRCODE='0A000';
        END IF;
        PERFORM pg_advisory_xact_lock_shared(hashtext('deerflow.event_fence/' || current_schema())::bigint);
        SELECT strict INTO strict_mode FROM run_producer_policy WHERE id=1;
        IF coalesce(strict_mode, false) THEN
            -- Do not acquire earlier Thread/Run locks while holding this gate.
            RAISE EXCEPTION 'Producer policy changed; retry the transaction' USING ERRCODE='40001';
        END IF;
        RETURN NEW;
    END IF;
    PERFORM pg_advisory_xact_lock(hashtext(NEW.thread_id)::bigint);
    a := nullif(current_setting('deerflow.event_authority', true), '')::jsonb;
    IF a->>'source'='history_seed' THEN
        SELECT * INTO r FROM runs WHERE run_id=a->>'reservation_id' FOR UPDATE;
        SELECT * INTO t FROM threads_meta WHERE thread_id=NEW.thread_id FOR UPDATE;
    ELSE
        SELECT * INTO r FROM runs WHERE run_id=NEW.run_id FOR UPDATE;
    END IF;
    -- Cutover takes only this final lock, never a Clock/Thread/Run lock.
    PERFORM pg_advisory_xact_lock_shared(hashtext('deerflow.event_fence/' || current_schema())::bigint);
    SELECT strict INTO strict_mode FROM run_producer_policy WHERE id=1;
    IF NOT coalesce(strict_mode, false) THEN RETURN NEW; END IF;
    IF a->>'source'='history_seed' THEN
        seed_prefix := (a->>'seed_kind') || '-seed-' || NEW.thread_id || '-';
        IF r.run_id IS NULL OR t.thread_id IS NULL
           OR r.operation_kind <> 'checkpoint_write' OR r.status <> 'pending' OR r.producer_state IS DISTINCT FROM 'open'
           OR r.thread_id IS DISTINCT FROM NEW.thread_id
           OR r.user_id IS DISTINCT FROM NEW.user_id
           OR a->>'thread_id' IS DISTINCT FROM NEW.thread_id
           OR a->>'user_id' IS DISTINCT FROM NEW.user_id
           OR r.run_incarnation IS NULL OR a->>'reservation_incarnation' IS DISTINCT FROM r.run_incarnation
           OR r.producer_epoch IS NULL OR a->>'producer_epoch' IS DISTINCT FROM r.producer_epoch
           OR r.owner_worker_id IS NULL OR a->>'owner_worker_id' IS DISTINCT FROM r.owner_worker_id
           OR (a->>'retention_revision')::bigint IS DISTINCT FROM r.evidence_retention_revision
           OR NOT (a ? 'thread_incarnation') OR a->>'thread_incarnation' IS DISTINCT FROM t.incarnation
           OR NOT (a ? 'thread_user_id') OR a->>'thread_user_id' IS DISTINCT FROM t.user_id
           OR (t.user_id IS NOT NULL AND t.user_id IS DISTINCT FROM NEW.user_id)
           OR (r.lease_expires_at IS NOT NULL AND r.lease_expires_at <= clock_timestamp())
           OR a->>'seed_kind' IS NULL OR a->>'seed_kind' NOT IN ('checkpoint','branch')
           OR left(NEW.run_id, length(seed_prefix)) IS DISTINCT FROM seed_prefix
           OR substring(NEW.run_id FROM length(seed_prefix)+1) !~ '^(0|[1-9][0-9]*)$'
           OR NEW.category <> 'message' OR NEW.event_type NOT IN ('llm.human.input','llm.ai.response','llm.tool.result') THEN
            RAISE EXCEPTION 'History seed authority is missing, stale or outside the host grant' USING ERRCODE='42501';
        END IF;
        RETURN NEW;
    END IF;
    IF a IS NULL OR r.run_id IS NULL OR r.operation_kind <> 'run'
       OR a->>'run_id' IS DISTINCT FROM NEW.run_id
       OR a->>'thread_id' IS DISTINCT FROM NEW.thread_id
       OR a->>'user_id' IS DISTINCT FROM NEW.user_id
       OR r.thread_id IS DISTINCT FROM NEW.thread_id
       OR r.user_id IS DISTINCT FROM NEW.user_id
       OR r.run_incarnation IS NULL
       OR a->>'run_incarnation' IS DISTINCT FROM r.run_incarnation
       OR (a->>'retention_revision')::bigint IS DISTINCT FROM r.evidence_retention_revision THEN
        RAISE EXCEPTION 'Run event producer authority is missing or stale' USING ERRCODE='42501';
    END IF;
    IF a->>'source' IN ('producer', 'publisher') THEN
        IF a->>'producer_epoch' IS DISTINCT FROM r.producer_epoch
           OR a->>'owner_worker_id' IS DISTINCT FROM r.owner_worker_id
           OR r.producer_state NOT IN ('open', 'closed')
           OR (a->>'source'='producer' AND (r.producer_state <> 'open' OR NEW.event_type IN ('run.terminal','run.delivery'))) THEN
            RAISE EXCEPTION 'Run event producer was revoked or closed' USING ERRCODE='42501';
        END IF;
    ELSIF a->>'source'='takeover' THEN
        IF r.status <> 'error' OR r.producer_state <> 'revoked' OR NEW.event_type NOT IN ('run.terminal','run.delivery') THEN
            RAISE EXCEPTION 'Invalid takeover event authority' USING ERRCODE='42501';
        END IF;
    ELSIF a->>'source'='audit' THEN
        IF NEW.event_type NOT LIKE 'audit.%' THEN
            RAISE EXCEPTION 'Invalid audit event authority' USING ERRCODE='42501';
        END IF;
    ELSE
        RAISE EXCEPTION 'Invalid event authority source' USING ERRCODE='42501';
    END IF;
    IF a->>'source' <> 'producer' AND NOT coalesce((a->'event_types') ? NEW.event_type, false) THEN
        RAISE EXCEPTION 'Event is outside the host grant' USING ERRCODE='42501';
    END IF;
    RETURN NEW;
END $guard$
""")
    )
    connection.execute(text("DROP TRIGGER IF EXISTS run_event_producer_guard ON run_events"))
    connection.execute(text(f"CREATE TRIGGER run_event_producer_guard BEFORE INSERT ON run_events FOR EACH ROW EXECUTE FUNCTION {quoted}.run_event_producer_guard()"))


async def activate_producer_fencing(session_factory, *, cutover_id: str) -> None:
    """Offline-only, monotonic activation; callers must stop every Gateway."""
    from deerflow.persistence.run.model import RunProducerPolicyRow, RunRow

    if not cutover_id or len(cutover_id) > 64:
        raise ValueError("A cutover ID of 1 to 64 characters is required")
    async with session_factory() as session, session.begin():
        if session.get_bind().dialect.name != "postgresql":
            raise RuntimeError("Strict producer fencing requires PostgreSQL")
        others = await session.scalar(text("SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND pid<>pg_backend_pid() AND backend_type='client backend'"))
        if others:
            raise RuntimeError("Stop all Gateway/database client sessions before producer cutover")
        await session.execute(text("SELECT pg_advisory_xact_lock(hashtext('deerflow.event_fence/' || current_schema())::bigint)"))
        if await session.scalar(select(func.count()).select_from(RunRow).where(RunRow.status.in_(("pending", "running")))):
            raise RuntimeError("Drain active Run admissions before producer cutover")
        guard = await session.scalar(text("SELECT count(*) FROM pg_trigger WHERE tgrelid='run_events'::regclass AND tgname='run_event_producer_guard' AND tgenabled='O'"))
        if not guard:
            raise RuntimeError("The producer fencing database migration/guard is missing")
        policy = await session.get(RunProducerPolicyRow, 1)
        if policy is not None and policy.strict and policy.cutover_id != cutover_id:
            raise RuntimeError("Producer fencing is already activated under another cutover ID")
        if policy is None:
            session.add(RunProducerPolicyRow(id=1, strict=True, cutover_id=cutover_id))
        else:
            policy.strict = True
            policy.cutover_id = cutover_id


async def validate_producer_fencing(session_factory, *, mode: str, cutover_id: str | None) -> None:
    from deerflow.persistence.run.model import RunProducerPolicyRow

    async with session_factory() as session:
        if session.get_bind().dialect.name != "postgresql":
            if mode != "off":
                raise RuntimeError("Strict producer fencing requires PostgreSQL RunStore + DB EventStore")
            return
        policy = await session.get(RunProducerPolicyRow, 1)
        if mode == "strict":
            if policy is None or not policy.strict or not cutover_id or policy.cutover_id != cutover_id:
                raise RuntimeError("Strict producer fencing requires the matching offline cutover")
            guard = await session.scalar(text("SELECT count(*) FROM pg_trigger WHERE tgrelid='run_events'::regclass AND tgname='run_event_producer_guard' AND tgenabled='O'"))
            if not guard:
                raise RuntimeError("Strict producer fencing database guard is unavailable")
        elif policy is not None and policy.strict:
            raise RuntimeError("Producer fencing is activated; refusing an unfenced Gateway")
