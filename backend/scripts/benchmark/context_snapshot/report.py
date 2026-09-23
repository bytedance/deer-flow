"""Metadata-only accounting; failures remain in denominators and token totals."""

import statistics


def usage(calls):
    totals = dict.fromkeys(("prompt_tokens", "completion_tokens", "total_tokens", "cached_tokens"), 0)
    complete = True
    for call in calls:
        item = call.get("usage") or {}
        complete &= all(isinstance(item.get(key), int) for key in ("prompt_tokens", "completion_tokens", "total_tokens"))
        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            totals[key] += item.get(key, 0) or 0
        totals["cached_tokens"] += (item.get("prompt_tokens_details") or {}).get("cached_tokens", 0) or 0
    return dict(totals, requests=len(calls), complete=complete)


def clean_success(row):
    return bool(row["artifact_correct"] and row["fresh_public_check"] and row["executor_status"] == "completed" and not row["stop_reason"] and not row.get("error_type"))


def summarize(rows):
    result = {}
    for arm in sorted({row["arm"] for row in rows}):
        subset = [row for row in rows if row["arm"] == arm]
        complete = all(row["usage"]["complete"] for row in subset)
        observed = sum(row["usage"]["total_tokens"] for row in subset)
        result[arm] = {
            "n": len(subset),
            "artifact_correct": sum(row["artifact_correct"] for row in subset),
            "clean_success": sum(clean_success(row) for row in subset),
            "observed_total_tokens": observed,
            "usage_complete": complete,
            "mean_total_tokens": observed / len(subset) if complete else None,
            "mean_seconds": statistics.mean(row["seconds"] for row in subset),
            "median_seconds": statistics.median(row["seconds"] for row in subset),
            "requests": sum(row["usage"]["requests"] for row in subset),
        }
    return result
