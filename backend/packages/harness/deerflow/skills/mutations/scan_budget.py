"""Cross-worker scan leases and hourly cost accounting, including reverts."""

import time

from deerflow_extension_api.host_capabilities import HostCapabilityError
from sqlalchemy import func, select, text

from deerflow.persistence.skill_mutations.model import SkillScanAttemptRow


def reserve_scan(session, *, plugin_id, owner_id, subject, token):
    # Called before other statements in this short transaction. The global
    # admission mutex guards count+insert on different owners and processes.
    if session.bind.dialect.name == "sqlite":
        session.execute(text("BEGIN IMMEDIATE"))
    elif session.bind.dialect.name == "postgresql":
        session.execute(text("SELECT pg_advisory_xact_lock(731129850451)"))
    now = time.time()

    def count(*conditions):
        return session.scalar(select(func.count()).select_from(SkillScanAttemptRow).where(*conditions))

    live = SkillScanAttemptRow.lease_until > now
    plugin = SkillScanAttemptRow.plugin_id == plugin_id
    owner = SkillScanAttemptRow.owner_id == owner_id
    if count(live) >= 4 or count(live, plugin, owner) >= 2 or count(live, plugin, owner, SkillScanAttemptRow.subject == subject):
        raise HostCapabilityError("BUSY", retry_after=1)
    recent = SkillScanAttemptRow.started_at > now - 3600
    if count(plugin, owner, recent) >= 20:
        raise HostCapabilityError("QUOTA_EXCEEDED")
    session.add(SkillScanAttemptRow(token=token, plugin_id=plugin_id, owner_id=owner_id, subject=subject, started_at=now, lease_until=now + 130))


def release_scan(repository, token):
    with repository.sessions.begin() as session:
        row = session.get(SkillScanAttemptRow, token)
        if row is not None:
            row.lease_until = 0
