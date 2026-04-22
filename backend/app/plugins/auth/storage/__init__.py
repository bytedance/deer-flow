"""Auth plugin storage package.

This package owns auth-specific ORM models and repositories while
continuing to use the application's shared persistence infrastructure.
"""

from app.plugins.auth.storage.contracts import User, UserCreate, UserRepositoryProtocol
from app.plugins.auth.storage.models import User as UserModel
from app.plugins.auth.storage.repositories import DbUserRepository

__all__ = [
    "DbUserRepository",
    "User",
    "UserCreate",
    "UserModel",
    "UserRepositoryProtocol",
]
