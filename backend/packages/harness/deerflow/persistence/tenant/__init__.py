"""Tenant persistence — ORM model and async repository."""

from .model import TenantRow
from .repository import TenantRepository

__all__ = ["TenantRepository", "TenantRow"]
