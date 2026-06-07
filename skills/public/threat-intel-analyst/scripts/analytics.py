"""Aggregations over the FEDERATED intel view (one or many SQLite DBs).

Each function takes an ``IntelFederation`` and runs a query whose FROM target
is the unioned ``{view}`` across all registered source DBs. Identical logic
works for a single local db or many teammates' DBs — federation is transparent
here. ``source_platform`` filtering lets you slice one source out of the union.
"""

from __future__ import annotations

import json
from collections import Counter
from typing import Optional


def _filter_clause(day_from, day_to, source_platform) -> tuple[str, list]:
    cond, params = [], []
    if day_from:
        cond.append("day >= ?"); params.append(day_from)
    if day_to:
        cond.append("day <= ?"); params.append(day_to)
    if source_platform:
        cond.append("source_platform = ?"); params.append(source_platform)
    clause = (" WHERE " + " AND ".join(cond)) if cond else ""
    return clause, params


def trends(fed, *, day_from=None, day_to=None, source_platform=None) -> dict:
    clause, params = _filter_clause(day_from, day_to, source_platform)
    by_day = fed.query(
        f"SELECT day, risk_level, COUNT(*) AS n FROM {{view}}{clause} "
        f"GROUP BY day, risk_level ORDER BY day DESC, risk_level", tuple(params))
    by_platform = fed.query(
        f"SELECT source_platform, COUNT(*) AS n FROM {{view}}{clause} "
        f"GROUP BY source_platform", tuple(params))
    by_db = fed.query(
        f"SELECT __db, COUNT(*) AS n FROM {{view}}{clause} GROUP BY __db", tuple(params))
    by_risk = fed.query(
        f"SELECT risk_level, COUNT(*) AS n FROM {{view}}{clause} "
        f"GROUP BY risk_level", tuple(params))
    total = sum(r["n"] for r in by_risk)
    return {"total": int(total), "by_day": by_day, "by_platform": by_platform,
            "by_db": by_db, "by_risk": by_risk}


def top_groups(fed, *, day_from=None, day_to=None, source_platform=None, limit=15) -> list[dict]:
    clause, params = _filter_clause(day_from, day_to, source_platform)
    return fed.query(
        f"SELECT source_group, source_platform, COUNT(*) AS total, "
        f"SUM(CASE WHEN risk_level='high' THEN 1 ELSE 0 END) AS high "
        f"FROM {{view}}{clause} GROUP BY source_group, source_platform "
        f"ORDER BY high DESC, total DESC LIMIT ?", (*params, limit))


def keyword_heat(fed, *, day_from=None, day_to=None, source_platform=None, limit=20) -> list[dict]:
    clause, params = _filter_clause(day_from, day_to, source_platform)
    return fed.query(
        f"SELECT risk_type, COUNT(*) AS n FROM {{view}}{clause} "
        f"GROUP BY risk_type ORDER BY n DESC LIMIT ?", (*params, limit))


def top_entities(fed, *, day_from=None, day_to=None, source_platform=None, limit=20) -> dict:
    clause, params = _filter_clause(day_from, day_to, source_platform)
    rows = fed.query(f"SELECT entities FROM {{view}}{clause}", tuple(params))
    buckets = {"accounts": Counter(), "contacts": Counter(), "links": Counter(),
               "tools": Counter(), "prices": Counter()}
    for r in rows:
        ent_json = r.get("entities")
        try:
            ent = json.loads(ent_json) if ent_json else {}
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(ent, dict):
            continue
        for key in buckets:
            vals = ent.get(key) or []
            if isinstance(vals, str):
                vals = [vals]
            for v in vals:
                if v:
                    buckets[key][str(v).strip()] += 1
    return {k: [{"value": v, "count": c} for v, c in cnt.most_common(limit)]
            for k, cnt in buckets.items()}


def query_records(fed, *, day=None, risk_level=None, source_platform=None, limit=50) -> dict:
    cond, params = [], []
    if day:
        cond.append("day = ?"); params.append(day)
    if risk_level:
        cond.append("risk_level = ?"); params.append(risk_level)
    if source_platform:
        cond.append("source_platform = ?"); params.append(source_platform)
    clause = (" WHERE " + " AND ".join(cond)) if cond else ""
    records = fed.query(
        f"SELECT __db, day, id, source_platform, source_group, risk_type, "
        f"risk_level, summary, source_url FROM {{view}}{clause} "
        f"ORDER BY day DESC LIMIT ?", (*params, limit))
    total_rows = fed.query(f"SELECT COUNT(*) AS n FROM {{view}}{clause}", tuple(params))
    total = total_rows[0]["n"] if total_rows else 0
    return {"total_matched": int(total), "returned": len(records), "records": records}


def gather_all(fed, *, day_from=None, day_to=None, source_platform=None) -> dict:
    return {
        "scope": {"day_from": day_from, "day_to": day_to, "source_platform": source_platform},
        "sources": fed.databases,
        "trends": trends(fed, day_from=day_from, day_to=day_to, source_platform=source_platform),
        "top_groups": top_groups(fed, day_from=day_from, day_to=day_to, source_platform=source_platform),
        "keyword_heat": keyword_heat(fed, day_from=day_from, day_to=day_to, source_platform=source_platform),
        "top_entities": top_entities(fed, day_from=day_from, day_to=day_to, source_platform=source_platform),
    }
