"""CRM canonical models for customer relationship management integrations.

Defines frozen dataclasses for CRM domain entities following the same
conventions as Ins/Sms canonical models (frozen, source_metadata, provenance).

Capability keys:
- customer.get_profile: fetch customer profile by ID or search criteria
- customer.search: search customers by name, industry, region
- contract.get_detail: fetch contract details by contract ID
- contract.list_by_customer: list all contracts for a customer
- service_object.get_detail: fetch service object details
- service_object.list_by_customer: list service objects for a customer
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from deerflow.integrations.models.provenance import Provenance


@dataclass(frozen=True)
class CustomerProfile:
    """Customer profile from CRM system."""

    id: str
    name: str
    display_name: str
    industry: str | None = None
    region: str | None = None
    contact_name: str | None = None
    contact_phone: str | None = None
    contract_count: int = 0
    service_object_count: int = 0
    source_metadata: dict[str, Any] = field(default_factory=dict)
    provenance: Provenance | None = None


@dataclass(frozen=True)
class Contract:
    """Service contract from CRM system."""

    id: str
    customer_id: str
    contract_number: str
    title: str
    status: str
    start_date: str
    end_date: str | None = None
    service_level: str | None = None
    covered_assets: tuple[str, ...] = ()
    source_metadata: dict[str, Any] = field(default_factory=dict)
    provenance: Provenance | None = None


@dataclass(frozen=True)
class ServiceObject:
    """Installed service object (equipment under contract)."""

    id: str
    customer_id: str
    asset_id: str | None = None
    object_type: str = ""
    model_number: str | None = None
    serial_number: str | None = None
    installation_date: str | None = None
    warranty_end_date: str | None = None
    source_metadata: dict[str, Any] = field(default_factory=dict)
    provenance: Provenance | None = None
