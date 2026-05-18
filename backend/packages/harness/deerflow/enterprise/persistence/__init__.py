"""Enterprise persistence layer.

**Design decision (plan §2.1, M0-5)**: enterprise ORM models REUSE the
existing :class:`deerflow.persistence.base.Base` declarative_base. We do
NOT create a new ``Base`` here. All enterprise tables (M1 RBAC, M2
audit_events, M3 approval) hang off the same ``Base.metadata`` so the
existing Alembic environment in
``deerflow.persistence.migrations.env`` automatically picks them up via
``target_metadata = Base.metadata``.

Reasoning: RFC §8.1 calls for a single Alembic environment. A single
declarative_base is the simplest way to honour that; merging two
metadata objects at runtime would invite drift.
"""

from __future__ import annotations

from deerflow.enterprise.persistence.database import EnterpriseDatabase

__all__ = ["EnterpriseDatabase"]
