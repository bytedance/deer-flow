"""Bounded read-only projections of retained team records."""

import hashlib
import json

from .store import TERMINAL

RESPONSE_BYTES = 24000


def token(*parts):
    return hashlib.sha256(json.dumps(parts).encode()).hexdigest()[:32]


def excerpt(value, limit):
    if value is None:
        return None, False
    encoded = value.encode()
    return encoded[:limit].decode(errors="ignore"), len(encoded) > limit


def options(team, payload, validate_text):
    allowed = {"team_id", "member_id", "job_id", "query", "cursor", "limit"}
    if set(payload) - allowed:
        raise ValueError("Unexpected request fields")
    limit = payload.get("limit", 8)
    if type(limit) is not int or not 1 <= limit <= 20:
        raise ValueError("Invalid limit")
    values = {key: validate_text(payload, key, size) if key in payload else None for key, size in (("member_id", 64), ("job_id", 64), ("query", 128), ("cursor", 80))}
    if values["member_id"] and values["member_id"] not in {member["id"] for member in team["members"]}:
        raise ValueError("Member unavailable")
    return values, limit


def stored_result(team, job):
    if job["status"] == "cancelled":
        return None
    if "result" in job:
        return job["result"]
    return next((message["text"] for message in reversed(team["messages"]) if message["job_id"] == job["id"] and message["kind"] in TERMINAL), None)


def job_record(team, job, *, result_bytes=500):
    member = next((member for member in team["members"] if member["id"] == job["member_id"]), None)
    requester = next((member for member in team["members"] if member["thread_id"] == job["source"]), None)
    request, request_cut = excerpt(job["text"], 500)
    result, result_cut = excerpt(stored_result(team, job), result_bytes)
    return {
        "job_id": job["id"],
        "member_id": job["member_id"],
        "member_name": member["name"] if member else None,
        "requester_member_id": requester["id"] if requester else None,
        "requester_thread_id": job["source"],
        "kind": job["kind"],
        "status": job["status"],
        "parent_id": job.get("parent_id"),
        "created_at": job.get("created_at"),
        "completed_at": job.get("completed_at"),
        "conversation": {"thread_id": job["thread_id"], "run_id": job["run_id"]},
        "request": {"text": request, "truncated": request_cut},
        "result": {
            "available": result is not None,
            "text": result,
            "truncated": None if result is None else True if result_cut else job.get("result_truncated"),
            "reason": None if result is not None else "cancelled" if job["status"] == "cancelled" else "not_retained" if job["status"] in TERMINAL else "not_completed",
        },
    }


def page(team, payload, validate_text, *, results=False):
    values, limit = options(team, payload, validate_text)
    member_id, job_id, query, cursor = (values[key] for key in ("member_id", "job_id", "query", "cursor"))
    query = query.casefold() if query else None
    mode = "results" if results else "history"
    fingerprint = token(team["id"], mode, member_id, job_id, query)
    jobs = {job["id"]: job for job in team["jobs"]}
    members = {member["id"]: member["name"] for member in team["members"]}
    rows = []
    source = team["jobs"] if results else team["messages"]
    for record in reversed(source):
        record_job_id = record["id"] if results else record["job_id"]
        if results and (record["kind"] != "request" or record["status"] not in TERMINAL):
            continue
        if (member_id and record["member_id"] != member_id) or (job_id and record_job_id != job_id):
            continue
        searchable = record["text"] + ("\n" + (stored_result(team, record) or "") if results else "")
        if query and query not in searchable.casefold():
            continue
        anchor = token(record_job_id, record["kind"])
        if results:
            item = job_record(team, record)
        else:
            content, cut = excerpt(record["text"], 6000)
            job = jobs.get(record_job_id)
            item = {
                "job_id": record_job_id,
                "member_id": record["member_id"],
                "member_name": members.get(record["member_id"]),
                "source_thread": record.get("source_thread"),
                "kind": record["kind"],
                "text": content,
                "truncated": True if cut else (job.get("result_truncated") if job else None) if record["kind"] in TERMINAL else False,
                "conversation": {"thread_id": job["thread_id"] if job else record.get("source_thread"), "run_id": record.get("run_id")},
            }
        rows.append((anchor, item))
    response = {
        "team_id": team["id"],
        "items": [],
        "total_matches": len(rows),
        "next_cursor": None,
        "cursor_expired": False,
        **({"request_retention_limit": 100} if results else {"retained_messages": len(team["messages"]), "history_retention_limit": 100}),
    }
    if cursor:
        parts = cursor.split(":")
        if len(parts) != 2 or parts[0] != fingerprint or len(parts[1]) != 32 or any(char not in "0123456789abcdef" for char in parts[1]):
            raise ValueError("Invalid cursor for this query")
        positions = [index for index, (anchor, _) in enumerate(rows) if anchor == parts[1]]
        if len(positions) != 1:
            return {**response, "cursor_expired": True}
        rows = rows[positions[0] + 1 :]
    for index, (anchor, item) in enumerate(rows[:limit]):
        candidate = {**response, "items": [*response["items"], item], "next_cursor": f"{fingerprint}:{anchor}" if index + 1 < len(rows) else None}
        if len(json.dumps(candidate, ensure_ascii=False).encode()) > RESPONSE_BYTES:
            if not response["items"]:
                raise ValueError("Stored record exceeds the response budget; inspect the member conversation")
            break
        response = candidate
    return response


def result(team, job_id):
    job = next((job for job in team["jobs"] if job["id"] == job_id), None)
    if job is None:
        raise ValueError("Request unavailable")
    response = {"team_id": team["id"], **job_record(team, job, result_bytes=6000)}
    if len(json.dumps(response, ensure_ascii=False).encode()) > RESPONSE_BYTES:
        raise ValueError("Stored record exceeds the response budget; inspect the member conversation")
    return response
