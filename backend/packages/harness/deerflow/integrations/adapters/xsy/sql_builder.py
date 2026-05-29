"""SQL query builder for Xiaoshouyi (销售易) data query API.

Pure functions that construct SQL query strings from structured query objects.
No HTTP dependencies.

Xiaoshouyi SQL limitationsations:
- SELECT does not support "*"
- ORDER BY only supports "id" field
- WHERE supports: =, !=, like (prefix % only), not in, is null, is not null, >, <, <>, >=, <=, in, between
- Logical operators: AND, OR
- LIMIT: e.g., "limit 0,4" means skip 0, take 4
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from deerflow.integrations.models.queries import OutboundDetailQuery, ServiceEventQuery

# Table names
OUTBOUND_TABLE = "customEntity93__c"
SERVICE_EVENT_TABLE = "customEntity35__c"

# Field mappings: canonical name → Xiaoshouyi field name
OUTBOUND_FIELDS = {
    "id": "id",
    "quantity": "customItem3__c",
    "spec_model": "customItem5__c",
    "created_at": "createdAt",
}

SERVICE_EVENT_FIELDS = {
    "id": "id",
    "unit_name": "customItem4__c",
    "event_name": "customItem6__c",
    "event_time": "customItem8__c",
}


def datetime_to_xsy_timestamp(dt: datetime) -> int:
    """Convert Python datetime to 13-digit millisecond timestamp."""
    return int(dt.timestamp() * 1000)


def build_outbound_query(
    query: OutboundDetailQuery,
    last_id: str | None = None,
) -> str:
    """Build SQL query for outbound details (产品出库明细).

    Args:
        query: Structured query object
        last_id: Last record ID from previous page (for cursor pagination)

    Returns:
        SQL query string
    """
    # SELECT clause
    select_fields = ", ".join(OUTBOUND_FIELDS.values())
    sql_parts = [f"select {select_fields} from {OUTBOUND_TABLE}"]

    # WHERE clause
    conditions = []

    if query.spec_model:
        conditions.append(f"{OUTBOUND_FIELDS['spec_model']} like '{_escape_sql(query.spec_model)}%'")

    if query.min_quantity is not None:
        conditions.append(f"{OUTBOUND_FIELDS['quantity']} >= {query.min_quantity}")

    if query.max_quantity is not None:
        conditions.append(f"{OUTBOUND_FIELDS['quantity']} <= {query.max_quantity}")

    if query.start_time:
        ts = datetime_to_xsy_timestamp(query.start_time)
        conditions.append(f"{OUTBOUND_FIELDS['created_at']} >= {ts}")

    if query.end_time:
        ts = datetime_to_xsy_timestamp(query.end_time)
        conditions.append(f"{OUTBOUND_FIELDS['created_at']} <= {ts}")

    # Cursor pagination
    if last_id:
        conditions.append(f"id > '{_escape_sql(last_id)}'")

    # Extra filters
    for key, value in query.extra_filters.items():
        field_name = OUTBOUND_FIELDS.get(key, key)
        if isinstance(value, str):
            conditions.append(f"{field_name} = '{_escape_sql(value)}'")
        else:
            conditions.append(f"{field_name} = {value}")

    if conditions:
        sql_parts.append("where " + " and ".join(conditions))

    # ORDER BY (only id supported)
    sql_parts.append("order by id")

    # LIMIT
    limit = min(query.limit, 100)  # Xiaoshouyi max 100 per page
    sql_parts.append(f"limit {query.offset},{limit}")

    return " ".join(sql_parts)


def build_service_event_query(
    query: ServiceEventQuery,
    last_id: str | None = None,
) -> str:
    """Build SQL query for service event details (服务事件明细).

    Args:
        query: Structured query object
        last_id: Last record ID from previous page (for cursor pagination)

    Returns:
        SQL query string
    """
    # SELECT clause
    select_fields = ", ".join(SERVICE_EVENT_FIELDS.values())
    sql_parts = [f"select {select_fields} from {SERVICE_EVENT_TABLE}"]

    # WHERE clause
    conditions = []

    if query.unit_name:
        conditions.append(f"{SERVICE_EVENT_FIELDS['unit_name']} like '{_escape_sql(query.unit_name)}%'")

    if query.event_name:
        conditions.append(f"{SERVICE_EVENT_FIELDS['event_name']} like '{_escape_sql(query.event_name)}%'")

    if query.start_time:
        ts = datetime_to_xsy_timestamp(query.start_time)
        conditions.append(f"{SERVICE_EVENT_FIELDS['event_time']} >= {ts}")

    if query.end_time:
        ts = datetime_to_xsy_timestamp(query.end_time)
        conditions.append(f"{SERVICE_EVENT_FIELDS['event_time']} <= {ts}")

    # Cursor pagination
    if last_id:
        conditions.append(f"id > '{_escape_sql(last_id)}'")

    # Extra filters
    for key, value in query.extra_filters.items():
        field_name = SERVICE_EVENT_FIELDS.get(key, key)
        if isinstance(value, str):
            conditions.append(f"{field_name} = '{_escape_sql(value)}'")
        else:
            conditions.append(f"{field_name} = {value}")

    if conditions:
        sql_parts.append("where " + " and ".join(conditions))

    # ORDER BY (only id supported)
    sql_parts.append("order by id")

    # LIMIT
    limit = min(query.limit, 100)  # Xiaoshouyi max 100 per page
    sql_parts.append(f"limit {query.offset},{limit}")

    return " ".join(sql_parts)


def _escape_sql(value: str) -> str:
    """Escape special characters for SQL string literals.

    Xiaoshouyi requires URL encoding for special chars like '%'.
    """
    # Basic SQL escaping: single quotes
    return value.replace("'", "''")
