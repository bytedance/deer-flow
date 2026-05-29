"""ERP system response → canonical model transforms.

Pure functions that convert ERP API response payloads into frozen
canonical models with source_metadata and provenance attached.
"""

from __future__ import annotations

from typing import Any

from deerflow.integrations.models.erp import (
    InventoryItem,
    SparePart,
    SparePartUsage,
    WorkOrder,
)
from deerflow.integrations.models.provenance import Provenance


def transform_work_orders(
    raw: dict[str, Any],
    provenance: Provenance,
) -> tuple[WorkOrder, ...]:
    """Transform ERP work order API response to WorkOrder tuple."""
    items = raw if isinstance(raw, list) else raw.get("data", raw.get("items", [raw]))
    if isinstance(items, dict):
        items = [items]

    results: list[WorkOrder] = []
    for item in items:
        parts_raw = item.get("parts_used", [])
        parts = tuple(
            SparePartUsage(
                part_id=str(p.get("part_id", "")),
                part_number=str(p.get("part_number", "")),
                name=str(p.get("name", "")),
                quantity=int(p.get("quantity", 0)),
                unit_cost=p.get("unit_cost"),
            )
            for p in parts_raw
        )
        results.append(
            WorkOrder(
                id=str(item.get("id", "")),
                order_number=str(item.get("order_number", "")),
                title=str(item.get("title", "")),
                status=str(item.get("status", "unknown")),
                priority=str(item.get("priority", "medium")),
                description=str(item.get("description", "")),
                asset_id=item.get("asset_id"),
                assigned_to=item.get("assigned_to"),
                created_at=str(item.get("created_at", "")),
                scheduled_at=item.get("scheduled_at"),
                completed_at=item.get("completed_at"),
                parts_used=parts,
                source_metadata={"raw": item},
                provenance=provenance,
            )
        )
    return tuple(results)


def transform_spare_parts(
    raw: dict[str, Any],
    provenance: Provenance,
) -> tuple[SparePart, ...]:
    """Transform ERP spare part API response to SparePart tuple."""
    items = raw if isinstance(raw, list) else raw.get("data", raw.get("items", [raw]))
    if isinstance(items, dict):
        items = [items]

    results: list[SparePart] = []
    for item in items:
        results.append(
            SparePart(
                id=str(item.get("id", "")),
                part_number=str(item.get("part_number", "")),
                name=str(item.get("name", "")),
                category=item.get("category"),
                unit=str(item.get("unit", "piece")),
                stock_quantity=int(item.get("stock_quantity", 0)),
                min_stock=item.get("min_stock"),
                unit_cost=item.get("unit_cost"),
                source_metadata={"raw": item},
                provenance=provenance,
            )
        )
    return tuple(results)


def transform_inventory_items(
    raw: dict[str, Any],
    provenance: Provenance,
) -> tuple[InventoryItem, ...]:
    """Transform ERP inventory API response to InventoryItem tuple."""
    items = raw if isinstance(raw, list) else raw.get("data", raw.get("items", [raw]))
    if isinstance(items, dict):
        items = [items]

    results: list[InventoryItem] = []
    for item in items:
        results.append(
            InventoryItem(
                id=str(item.get("id", "")),
                part_id=str(item.get("part_id", "")),
                warehouse=str(item.get("warehouse", "")),
                quantity=int(item.get("quantity", 0)),
                reserved_quantity=int(item.get("reserved_quantity", 0)),
                last_restocked_at=item.get("last_restocked_at"),
                source_metadata={"raw": item},
                provenance=provenance,
            )
        )
    return tuple(results)
