#!/usr/bin/env python3
"""Query bundled GB50009 wind and snow data by region name."""

from __future__ import annotations

import json
import sys
from pathlib import Path


DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "gb50009_2012_e5_city_wind_snow_temp.jsonl"

SUFFIXES = (
    "特别行政区",
    "维吾尔自治区",
    "壮族自治区",
    "回族自治区",
    "自治区",
    "自治州",
    "自治县",
    "地区",
    "盟",
    "省",
    "市",
    "州",
    "县",
    "区",
    "旗",
)


def _normalize_region(value: str) -> str:
    normalized = "".join(value.split())
    changed = True
    while changed and normalized:
        changed = False
        for suffix in SUFFIXES:
            if normalized.endswith(suffix):
                normalized = normalized[: -len(suffix)]
                changed = True
                break
    return normalized


def _load_records() -> list[dict]:
    records: list[dict] = []
    with DATA_FILE.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            record["_province_normalized"] = _normalize_region(record["province"])
            record["_city_normalized"] = _normalize_region(record["city"])
            records.append(record)
    return records


def _clean_match(record: dict) -> dict:
    return {key: value for key, value in record.items() if not key.startswith("_")}


def _candidates_for_query(records: list[dict], query: str) -> tuple[list[dict], str]:
    query_raw = "".join(query.split())
    query_normalized = _normalize_region(query_raw)
    if not query_raw:
        return [], "empty_query"

    exact_city = [record for record in records if record["city"] == query_raw]
    if exact_city:
        return exact_city, "exact_city"

    normalized_city = [record for record in records if record["_city_normalized"] == query_normalized]
    if normalized_city:
        return normalized_city, "normalized_city"

    containing_city = [
        record
        for record in records
        if record["_city_normalized"] and record["_city_normalized"] in query_normalized
    ]
    if containing_city:
        return containing_city, "query_contains_city"

    normalized_province = [record for record in records if record["_province_normalized"] == query_normalized]
    if len(normalized_province) == 1:
        return normalized_province, "normalized_province"

    return [], "not_found"


def lookup_region(query: str) -> dict:
    records = _load_records()
    candidates, matched_by = _candidates_for_query(records, query)

    if len(candidates) == 1:
        return {
            "status": "found",
            "query": query,
            "matched_by": matched_by,
            "match": _clean_match(candidates[0]),
        }

    if len(candidates) > 1:
        return {
            "status": "ambiguous",
            "query": query,
            "matched_by": matched_by,
            "candidates": [
                {
                    "province": candidate["province"],
                    "city": candidate["city"],
                    "standard": candidate["standard"],
                    "table": candidate["table"],
                }
                for candidate in candidates
            ],
            "next_action": "ask_user_for_more_specific_region",
        }

    return {
        "status": "not_found",
        "query": query,
        "matched_by": matched_by,
        "next_action": "search_web_then_ask_user",
    }


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(
            json.dumps(
                {
                    "status": "error",
                    "message": "usage: python query_wind_snow.py <region>",
                },
                ensure_ascii=False,
            )
        )
        return 1

    result = lookup_region(argv[1])
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
