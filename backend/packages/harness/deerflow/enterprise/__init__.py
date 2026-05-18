"""DeerFlow Enterprise extension package.

Houses RBAC, audit, approval, OIDC, and the persistence/middleware glue
that wires those features into the DeerFlow harness. Empty by default —
loading this package has no side effects until ``EnterpriseConfig.enabled``
is set to ``True`` in ``config.yaml`` and the gateway lifespan wires the
sub-modules up.

Harness-layer rule (enforced by ``tests/test_harness_boundary.py``):
modules under ``deerflow.enterprise.*`` must NOT import from ``app.*``.
"""
