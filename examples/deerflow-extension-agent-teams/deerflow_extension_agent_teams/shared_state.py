"""Bounded, attributed working state independent of the shared message window."""

import hashlib
import json
from datetime import UTC, datetime

from .store import TERMINAL

KINDS = ("objective", "plan", "finding", "question", "requirement")
MAX_ENTRIES = 20
STATE_BYTES = 16000
PUBLIC_FIELDS = ("id", "kind", "title", "content", "status", "revision", "created_by", "updated_by", "created_at", "updated_at", "source")


def fingerprint(*parts):
    return hashlib.sha256(json.dumps(parts).encode()).hexdigest()[:32]


def text(payload, key, limit):
    value = payload.get(key)
    try:
        if isinstance(value, str) and value.strip() and len(value) <= limit and len(value.encode()) <= limit * 2:
            return value.strip()
    except UnicodeError:
        pass
    raise ValueError(f"Invalid {key}")


def snapshot(team, *, include_archived=False):
    state = team.get("public_state", {})
    return {
        "team_id": team["id"],
        "revision": state.get("revision", 0),
        "entries": [{key: entry[key] for key in PUBLIC_FIELDS} for entry in state.get("entries", []) if include_archived or entry["status"] == "active"],
    }


def context_projection(team):
    return {
        "team_id": team["id"],
        "goal": team["goal"],
        "members": [{key: member[key] for key in ("id", "name", "agent")} for member in team["members"]],
        "public_state": snapshot(team),
        "messages": [],
    }


def read(team, payload):
    if set(payload) - {"team_id", "entry_id", "kind", "query", "include_archived"}:
        raise ValueError("Unexpected request fields")
    include_archived = payload.get("include_archived", False)
    if type(include_archived) is not bool:
        raise ValueError("Invalid include_archived flag")
    filters = {key: text(payload, key, limit) if key in payload else None for key, limit in (("entry_id", 64), ("kind", 16), ("query", 128))}
    if filters["kind"] and filters["kind"] not in KINDS:
        raise ValueError("Invalid kind")
    result = snapshot(team, include_archived=include_archived)
    result["entries"] = [
        entry
        for entry in result["entries"]
        if (not filters["entry_id"] or entry["id"] == filters["entry_id"])
        and (not filters["kind"] or entry["kind"] == filters["kind"])
        and (not filters["query"] or filters["query"].casefold() in (entry["title"] + "\n" + entry["content"]).casefold())
    ]
    return result


def actor(team, context):
    member = next((member for member in team["members"] if member["thread_id"] == getattr(context, "thread_id", None)), None)
    if member is None:
        raise ValueError("Not a team member conversation")
    job = next((job for job in team["jobs"] if job["thread_id"] == member["thread_id"] and job["status"] not in TERMINAL), None)
    admitted = job is not None and job["input"] is not None and job["status"] != "waiting_input"
    return member["id"], {"thread_id": member["thread_id"], "job_id": job["id"] if admitted else None}


def check_budget(team):
    if len(json.dumps(snapshot(team, include_archived=True), ensure_ascii=False).encode()) > STATE_BYTES:
        raise ValueError("Team public state exceeds 16,000 UTF-8 JSON bytes; shorten existing entries")
    if len(json.dumps(context_projection(team), ensure_ascii=False).encode()) > 24000:
        raise ValueError("Team public state and goal/roster exceed the shared context budget; shorten entries")


def publish(team, payload, context):
    if set(payload) != {"team_id", "request_id", "kind", "title", "content"}:
        raise ValueError("Unexpected request fields")
    member_id, source = actor(team, context)
    kind, title, content = (text(payload, key, limit) for key, limit in (("kind", 16), ("title", 80), ("content", 1000)))
    if kind not in KINDS:
        raise ValueError("Invalid kind")
    entry_id = fingerprint(team["id"], source["thread_id"], text(payload, "request_id", 128))
    stamp = fingerprint(kind, title, content)
    state = team.setdefault("public_state", {"revision": 0, "entries": []})
    existing = next((entry for entry in state["entries"] if entry["id"] == entry_id), None)
    if existing:
        if existing["_publish"] != stamp:
            raise ValueError("Request ID already used for another publication")
        return {"team_id": team["id"], "revision": state["revision"], "entry": {key: existing[key] for key in PUBLIC_FIELDS}}
    if len(state["entries"]) >= MAX_ENTRIES:
        raise ValueError("Team public state limit reached (20 entries, including archived entries)")
    now = datetime.now(UTC).isoformat()
    entry = {
        "id": entry_id,
        "kind": kind,
        "title": title,
        "content": content,
        "status": "active",
        "revision": 1,
        "created_by": member_id,
        "updated_by": member_id,
        "created_at": now,
        "updated_at": now,
        "source": source,
        "_publish": stamp,
        "_update": None,
    }
    state["entries"].append(entry)
    state["revision"] += 1
    check_budget(team)
    return {"team_id": team["id"], "revision": state["revision"], "entry": {key: entry[key] for key in PUBLIC_FIELDS}}


def update(team, payload, context):
    if set(payload) != {"team_id", "entry_id", "expected_revision", "title", "content", "status"}:
        raise ValueError("Unexpected request fields")
    member_id, source = actor(team, context)
    entry_id, title, content = (text(payload, key, limit) for key, limit in (("entry_id", 64), ("title", 80), ("content", 1000)))
    expected, status = payload["expected_revision"], payload["status"]
    if type(expected) is not int or expected < 1 or status not in ("active", "archived"):
        raise ValueError("Invalid revision or status")
    state = team.get("public_state", {})
    entry = next((entry for entry in state.get("entries", []) if entry["id"] == entry_id), None)
    if entry is None:
        raise ValueError("Public entry unavailable")
    stamp = fingerprint(member_id, expected, title, content, status)
    if entry["_update"] != stamp:
        if entry["revision"] != expected:
            return {"team_id": team["id"], "revision": state["revision"], "updated": False, "conflict": True, "entry": {key: entry[key] for key in PUBLIC_FIELDS}}
        entry.update(title=title, content=content, status=status, revision=expected + 1, updated_by=member_id, updated_at=datetime.now(UTC).isoformat(), source=source, _update=stamp)
        state["revision"] += 1
        check_budget(team)
    return {"team_id": team["id"], "revision": state["revision"], "updated": True, "conflict": False, "entry": {key: entry[key] for key in PUBLIC_FIELDS}}
