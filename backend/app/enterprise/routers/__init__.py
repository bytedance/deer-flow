"""Enterprise HTTP routers (mounted under ``/api/enterprise/`` in M1+).

Each sub-router is mounted conditionally by ``app.gateway.app.create_app``
when ``EnterpriseConfig.enabled`` is true. M1 adds ``rbac``; M2 adds
``audit``; later milestones add ``approval``, ``auth``, and ``dashboard``.
"""

from __future__ import annotations

__all__: list[str] = []
