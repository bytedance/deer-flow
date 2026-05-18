"""DeerFlow Enterprise app-layer adapters.

This package houses HTTP routers, dependency-injection helpers, and
auth-provider adapters that bridge the harness-layer
``deerflow.enterprise.*`` modules to FastAPI / the gateway runtime.

Boundary: app -> harness is allowed; the reverse is forbidden (see
``backend/tests/test_harness_boundary.py``).

Nothing here loads at import time — every public helper is a lazy
singleton factory so the package can ship without affecting startup for
operators who have not enabled enterprise features.
"""

from __future__ import annotations

__all__: list[str] = []
