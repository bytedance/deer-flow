"""CRM system response → canonical model transforms.

Pure functions that convert CRM API response payloads into frozen
canonical models with source_metadata and provenance attached.
"""

from __future__ import annotations

from typing import Any

from deerflow.integrations.models.crm import Contract, CustomerProfile, ServiceObject
from deerflow.integrations.models.provenance import Provenance


def transform_customer_profile(
    raw: dict[str, Any],
    provenance: Provenance,
) -> tuple[CustomerProfile, ...]:
    """Transform CRM customer API response to CustomerProfile tuple."""
    items = raw if isinstance(raw, list) else raw.get("data", raw.get("items", [raw]))
    if isinstance(items, dict):
        items = [items]

    results: list[CustomerProfile] = []
    for item in items:
        results.append(
            CustomerProfile(
                id=str(item.get("id", "")),
                name=str(item.get("name", "")),
                display_name=str(item.get("display_name", item.get("name", ""))),
                industry=item.get("industry"),
                region=item.get("region"),
                contact_name=item.get("contact_name"),
                contact_phone=item.get("contact_phone"),
                contract_count=int(item.get("contract_count", 0)),
                service_object_count=int(item.get("service_object_count", 0)),
                source_metadata={"raw": item},
                provenance=provenance,
            )
        )
    return tuple(results)


def transform_contract(
    raw: dict[str, Any],
    provenance: Provenance,
) -> tuple[Contract, ...]:
    """Transform CRM contract API response to Contract tuple."""
    items = raw if isinstance(raw, list) else raw.get("data", raw.get("items", [raw]))
    if isinstance(items, dict):
        items = [items]

    results: list[Contract] = []
    for item in items:
        covered = item.get("covered_assets", [])
        results.append(
            Contract(
                id=str(item.get("id", "")),
                customer_id=str(item.get("customer_id", "")),
                contract_number=str(item.get("contract_number", "")),
                title=str(item.get("title", "")),
                status=str(item.get("status", "unknown")),
                start_date=str(item.get("start_date", "")),
                end_date=item.get("end_date"),
                service_level=item.get("service_level"),
                covered_assets=tuple(str(a) for a in covered),
                source_metadata={"raw": item},
                provenance=provenance,
            )
        )
    return tuple(results)


def transform_service_object(
    raw: dict[str, Any],
    provenance: Provenance,
) -> tuple[ServiceObject, ...]:
    """Transform CRM service object API response to ServiceObject tuple."""
    items = raw if isinstance(raw, list) else raw.get("data", raw.get("items", [raw]))
    if isinstance(items, dict):
        items = [items]

    results: list[ServiceObject] = []
    for item in items:
        results.append(
            ServiceObject(
                id=str(item.get("id", "")),
                customer_id=str(item.get("customer_id", "")),
                asset_id=item.get("asset_id"),
                object_type=str(item.get("object_type", "")),
                model_number=item.get("model_number"),
                serial_number=item.get("serial_number"),
                installation_date=item.get("installation_date"),
                warranty_end_date=item.get("warranty_end_date"),
                source_metadata={"raw": item},
                provenance=provenance,
            )
        )
    return tuple(results)
