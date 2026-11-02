"""Verified against WeKnora v0.8.3, commit 3e22822. No invented endpoints."""

import hashlib
import json
import os
from urllib.parse import quote

from .library import LIBRARY_OPERATIONS, Document, EditEntry, Entry, LibraryQuery, LibraryResult, RestoreEntry, Revision
from .weknora import resource_id


def rows(value, limit):
    if value is None:
        return []  # Go nil slices
    if not isinstance(value, list) or len(value) > limit or any(not isinstance(item, dict) for item in value):
        raise RuntimeError("Invalid provider directory")
    return value


def text(conn, value, limit):
    key = os.environ.get(conn.api_key_env, "").strip()
    value = value if isinstance(value, str) else ""
    return (value.replace(key, "[REDACTED]") if key else value)[:limit]


def entry(conn, base, data, slug=None, *, complete=False):
    if data.get("knowledge_base_id") != base or (slug is not None and data.get("slug") != slug):
        raise PermissionError("Provider returned an entry outside the requested resource")
    key = os.environ.get(conn.api_key_env, "").strip()
    if not isinstance(data.get("slug"), str) or (key and key in data["slug"]):
        raise RuntimeError("Invalid provider entry identity")
    # These values can be written back. Never truncate or replace a substring
    # in an editable document: even a title-only save would destroy its body.
    for name, limit in (("title", 500), ("content", 500_000), ("summary", 10000), ("status", 32)):
        value = data.get(name, "")
        if not isinstance(value, str) or len(value) > limit or (key and key in value):
            raise RuntimeError("Provider entry cannot be safely represented")
    if complete and "content" not in data:
        raise RuntimeError("Provider omitted full entry content")
    try:
        native = resource_id(data.get("id"))
        if key and key in native:
            raise ValueError("Invalid page identity")
        return Entry(
            key=data.get("slug"),
            title=data.get("title", ""),
            content=data.get("content", ""),
            summary=data.get("summary", ""),
            version=data.get("version"),
            status=text(conn, data.get("status"), 32),
        )
    except ValueError:
        raise RuntimeError("Invalid provider entry") from None


async def invoke(provider, context, connection, base, operation, query):
    if operation == "graph":
        raise NotImplementedError("WeKnora v0.8.3 has no stored entity relation query API")
    if operation not in LIBRARY_OPERATIONS:
        raise ValueError("Unknown library operation")
    conn = provider._authorize(context, connection, base, operation)
    model = EditEntry if operation == "entry_edit" else RestoreEntry if operation == "entry_restore" else LibraryQuery
    query = model.model_validate(query)
    info = await provider._base(conn, base)
    identity = [str(conn.base_url).rstrip("/"), conn.tenant_id, base]
    result = dict(provider="weknora", connection_id=conn.id, dataset_id="wk1_" + hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode()).hexdigest(), title=text(conn, info.get("name"), 500))
    if operation == "documents":
        payload = await provider._request(conn, "GET", f"/api/v1/knowledge-bases/{base}/knowledge", envelope="list", params={"page": query.page, "page_size": query.page_size, "keyword": query.search, "parse_status": query.state})
        docs = [Document(title=text(conn, row.get("title") or row.get("file_name"), 500), processing=provider._result(conn, base, row)) for row in rows(payload.get("data"), query.page_size)]
        return LibraryResult(**result, documents=docs, total=payload.get("total"), page=query.page, page_size=query.page_size)
    if not isinstance(info.get("capabilities"), dict) or info["capabilities"].get("wiki") is not True:
        raise NotImplementedError("Wiki is unavailable for this base")
    prefix = f"/api/v1/knowledgebase/{base}/wiki"
    if operation == "entries":
        payload = await provider._request(conn, "GET", prefix + "/pages", envelope=None, params={"page": query.page, "page_size": query.page_size, "query": query.search})
        items = [entry(conn, base, row) for row in rows(payload.get("pages"), query.page_size)]
        return LibraryResult(**result, entries=items, total=payload.get("total"), page=query.page, page_size=query.page_size)
    if not query.entry:
        raise ValueError("Entry key is required")
    path = "/" + quote(query.entry, safe="/")
    current = await provider._request(conn, "GET", prefix + "/pages" + path, envelope=None)
    existing = entry(conn, base, current, query.entry, complete=True)
    if operation == "entry":
        return LibraryResult(**result, entry=existing)
    if operation == "revisions":
        payload = await provider._request(conn, "GET", prefix + "/revisions" + path, envelope=None, params={"limit": query.page_size, "offset": (query.page - 1) * query.page_size})
        revisions = []
        for row in rows(payload.get("revisions"), query.page_size):
            entry(conn, base, row, query.entry)
            if resource_id(row.get("page_id")) != current["id"]:
                raise PermissionError("Provider returned a revision of a different page")
            revisions.append(Revision(version=row.get("version"), editor=text(conn, row.get("editor_id"), 256), source=text(conn, row.get("edit_source"), 64), edited_at=text(conn, row.get("edited_at"), 64)))
        return LibraryResult(**result, revisions=revisions, total=payload.get("total"), page=query.page, page_size=query.page_size)
    if operation in {"revision", "entry_restore"}:
        if query.version is None:
            raise ValueError("Revision is required")
        payload = await provider._request(conn, "GET", prefix + "/revisions" + path, envelope=None, params={"version": query.version})
        if resource_id(payload.get("page_id")) != current["id"]:
            raise PermissionError("Provider returned a revision of a different page")
        snapshot = entry(conn, base, payload, query.entry, complete=True)
        if snapshot.version != query.version:
            raise RuntimeError("Provider returned another revision")
        if operation == "revision":
            return LibraryResult(**result, entry=snapshot)
    if query.expected_version != existing.version:
        raise FileExistsError("Entry changed; refresh before retrying")
    if operation == "entry_restore":
        # v0.8.3 /revert has no caller-supplied concurrency guard. Use the
        # guarded update API to restore title/content/summary as a new version.
        body = {"version": query.expected_version, "title": snapshot.title, "content": snapshot.content, "summary": snapshot.summary}
    else:
        body = {"version": query.expected_version, "title": query.title, "content": query.content}
    updated = await provider._request(conn, "PUT", prefix + "/pages" + path, envelope=None, json=body)
    return LibraryResult(**result, entry=entry(conn, base, updated, query.entry, complete=True))
