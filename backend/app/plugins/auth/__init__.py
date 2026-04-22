"""Auth plugin package.

Level 2 plugin goal:
- Own auth domain logic
- Own auth adapters (router, dependencies, middleware, LangGraph adapter)
- Own auth storage definitions
- Reuse the application's shared persistence/session infrastructure
"""

from app.plugins.auth.authorization.hooks import build_authz_hooks

__all__ = [
    "build_authz_hooks",
]
