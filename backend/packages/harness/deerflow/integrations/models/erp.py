"""ERP canonical models for enterprise resource planning integrations.

Defines frozen dataclasses for ERP domain entities following the same
conventions as Ins/Sms canonical models (frozen, source_metadata, provenance).

Capability keys:
- maintenance.get_work_orders: fetch work orders by asset, status, or date range
- maintenance.get_work_order_detail: fetch single work order with parts usage
- inventory.get_parts: search spare parts by category, name, or part number
- inventory.get_part_detail: fetch spare part with inventory levels
- inventory.check_availability: check part availability across warehouses
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from deerflow.integrations.models.provenance import Provenance


@dataclass(frozen=True)
class SparePartUsage:
    """Spare part consumed during a work order."""

    part_id: str
    part_number: str
    name: str
    quantity: int
    unit_cost: float | None = None


@dataclass(frozen=True)
class WorkOrder:
    """Maintenance work order from ERP system."""

    id: str
    order_number: str
    title: str
    status: str
    priority: str
    description: str = ""
    asset_id: str | None = None
    assigned_to: str | None = None
    created_at: str = ""
    scheduled_at: str | None = None
    completed_at: str | None = None
    parts_used: tuple[SparePartUsage, ...] = ()
    source_metadata: dict[str, Any] = field(default_factory=dict)
    provenance: Provenance | None = None


@dataclass(frozen=True)
class SparePart:
    """Spare part catalog entry from ERP system."""

    id: str
    part_number: str
    name: str
    category: str | None = None
    unit: str = "piece"
    stock_quantity: int = 0
    min_stock: int | None = None
    unit_cost: float | None = None
    source_metadata: dict[str, Any] = field(default_factory=dict)
    provenance: Provenance | None = None


@dataclass(frozen=True)
class InventoryItem:
    """Inventory level for a spare part at a specific warehouse."""

    id: str
    part_id: str
    warehouse: str
    quantity: int
    reserved_quantity: int = 0
    last_restocked_at: str | None = None
    source_metadata: dict[str, Any] = field(default_factory=dict)
    provenance: Provenance | None = None
