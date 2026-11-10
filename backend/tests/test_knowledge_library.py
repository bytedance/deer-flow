"""Offline phase-four library integration through real extension admission."""

import asyncio
import hashlib
import json
from pathlib import Path

import httpx
import pytest
from deerflow_extension_api.auth import ExtensionPrincipal


@pytest.fixture
def library(monkeypatch):
    root = Path(__file__).resolve().parents[2]
    for name in ("knowledge-management", "knowledge-platform"):
        monkeypatch.syspath_prepend(str(root / "examples" / f"deerflow-extension-{name}"))
    from deerflow_extension_knowledge_management.library import LIBRARY_OPERATIONS
    from deerflow_extension_knowledge_management.weknora import WeKnoraManagement

    monkeypatch.setenv("LIBRARY_TEST_KEY", "synthetic-secret")
    state = {"base": "kb", "version": 2, "code": 200}
    calls = []
    entry = {"id": "page-1", "knowledge_base_id": "kb", "slug": "concept/cedar", "title": "Cedar", "content": "Current text", "summary": "Summary", "version": 2, "status": "published"}

    def handler(req):
        calls.append(req)
        assert req.headers["X-API-Key"] == "synthetic-secret"
        if req.url.path == "/api/v1/knowledge-bases/kb":
            return httpx.Response(200, json={"success": True, "data": {"id": "kb", "capabilities": {"wiki": True}, "name": "Handbook"}})
        if state["code"] != 200:
            return httpx.Response(state["code"], text="synthetic-secret private")
        data = {**entry, "knowledge_base_id": state["base"], "version": state["version"], **state.get("entry_override", {})}
        if req.url.path.endswith("/knowledge"):
            return httpx.Response(200, json={"success": True, "data": [{"id": "doc", "title": "Guide", "knowledge_base_id": state["base"], "parse_status": "processing", "enable_status": "enabled"}], "total": 1})
        if "/revisions/" in req.url.path:
            old = {**data, "page_id": "page-1", "version": 1, "content": "Old text", "edit_source": "user", "editor_id": "alice", "edited_at": "2026-01-01", **state.get("revision_override", {})}
            return httpx.Response(200, json=old if req.url.params.get("version") else {"revisions": [old], "total": 1, "current_version": 2})
        if req.url.path.endswith("/pages"):
            return httpx.Response(200, json={"pages": [data], "total": 1})
        if req.method == "PUT":
            body = json.loads(req.content)
            assert body["version"] == 2
            data.update(body, version=3)
        return httpx.Response(200, json=data)

    config = {
        "connections": [
            {"id": "local", "base_url": "https://weknora.example", "tenant_id": "1", "api_key_env": "LIBRARY_TEST_KEY", "grants": [{"user_id": "alice", "knowledge_base_ids": ["kb"], "operations": ["capabilities", *LIBRARY_OPERATIONS]}]}
        ]
    }
    provider = WeKnoraManagement(config, transport=httpx.MockTransport(handler))
    return provider, calls, state


@pytest.mark.asyncio
async def test_real_document_directory_and_wiki_history(library):
    from deerflow_extension_knowledge_management.contracts import ManagementContext
    from deerflow_extension_knowledge_management.library import LibraryQuery

    provider, calls, _ = library
    ctx = ManagementContext(ExtensionPrincipal("alice", is_admin=True))
    docs = await provider.library(ctx, "local", "kb", "documents", LibraryQuery(search="Guide", state="processing"))
    assert docs.documents[0].title == "Guide" and docs.documents[0].processing.state == "running"
    assert calls[-1].url.params["parse_status"] == "processing"
    entries = await provider.library(ctx, "local", "kb", "entries", LibraryQuery())
    assert entries.entries[0].key == "concept/cedar"
    snapshot = await provider.library(ctx, "local", "kb", "revision", LibraryQuery(entry="concept/cedar", version=1))
    assert snapshot.entry.content == "Old text" and snapshot.entry.version == 1
    assert all(call.method == "GET" for call in calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["documents", "entries", "entry", "revisions", "revision", "entry_edit", "entry_restore"])
async def test_every_library_operation_requires_exact_grant(library, operation):
    from deerflow_extension_knowledge_management.contracts import ManagementContext
    from deerflow_extension_knowledge_management.library import LibraryQuery

    provider, calls, _ = library
    with pytest.raises(PermissionError):
        await provider.library(ManagementContext(ExtensionPrincipal("bob", is_admin=True)), "local", "kb", operation, LibraryQuery(entry="concept/cedar", version=1))
    assert not calls


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["documents", "entries", "entry", "revision"])
async def test_cross_base_responses_rejected_before_mutation(library, operation):
    from deerflow_extension_knowledge_management.contracts import ManagementContext
    from deerflow_extension_knowledge_management.library import LibraryQuery, RestoreEntry

    provider, calls, state = library
    state["base"] = "other"
    query = RestoreEntry(entry="concept/cedar", version=1, expected_version=2) if operation == "entry_restore" else LibraryQuery(entry="concept/cedar", version=1)
    with pytest.raises(PermissionError):
        await provider.library(ManagementContext(ExtensionPrincipal("alice", is_admin=True)), "local", "kb", operation, query)
    assert all(call.method == "GET" for call in calls)


@pytest.mark.asyncio
async def test_entry_directory_never_discloses_bodies(library):
    from deerflow_extension_knowledge_management.contracts import ManagementContext
    from deerflow_extension_knowledge_management.library import LibraryQuery

    provider, _, _ = library
    grant = provider.settings.connections[0].grants[0]
    object.__setattr__(grant, "operations", frozenset({"entries"}))
    result = await provider.library(ManagementContext(ExtensionPrincipal("alice", is_admin=True)), "local", "kb", "entries", LibraryQuery())
    row = result.model_dump()["entries"][0]
    assert "content" not in row and "summary" not in row
    assert "Current text" not in result.model_dump_json()
    with pytest.raises(PermissionError):
        await provider.library(ManagementContext(ExtensionPrincipal("alice", is_admin=True)), "local", "kb", "entry", LibraryQuery(entry="concept/cedar"))


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["entry_edit", "entry_restore"])
async def test_weknora_083_writes_fail_closed_without_atomic_caller_version(library, operation):
    from deerflow_extension_knowledge_management.contracts import ManagementContext
    from deerflow_extension_knowledge_management.library import EditEntry, RestoreEntry

    provider, calls, _ = library
    ctx = ManagementContext(ExtensionPrincipal("alice", is_admin=True))
    caps = await provider.capabilities(ctx, "local", "kb")
    assert not {"entry_edit", "entry_restore"} & caps.operations
    calls.clear()
    payload = EditEntry(entry="concept/cedar", expected_version=2, title="New", content="New") if operation == "entry_edit" else RestoreEntry(entry="concept/cedar", expected_version=2, version=1)
    with pytest.raises(NotImplementedError):
        await provider.library(ctx, "local", "kb", operation, payload)
    assert not calls


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["title", "content"])
async def test_submitted_credentials_rejected_before_upstream_io(library, field):
    from deerflow_extension_knowledge_management.contracts import ManagementContext
    from deerflow_extension_knowledge_management.library import EditEntry

    provider, calls, _ = library
    payload = dict(entry="concept/cedar", expected_version=2, title="New", content="New")
    payload[field] = "synthetic-secret private"
    with pytest.raises(ValueError):
        await provider.library(ManagementContext(ExtensionPrincipal("alice", is_admin=True)), "local", "kb", "entry_edit", EditEntry(**payload))
    assert not calls


@pytest.mark.asyncio
async def test_omitted_empty_historical_content_is_valid(library):
    from deerflow_extension_knowledge_management.contracts import ManagementContext
    from deerflow_extension_knowledge_management.library import LibraryQuery

    provider, _, _ = library
    original = provider._request

    async def empty_revision(conn, method, path, **kwargs):
        result = await original(conn, method, path, **kwargs)
        if "/revisions/" in path and kwargs.get("params", {}).get("version"):
            result.pop("content", None)
        return result

    provider._request = empty_revision
    result = await provider.library(ManagementContext(ExtensionPrincipal("alice", is_admin=True)), "local", "kb", "revision", LibraryQuery(entry="concept/cedar", version=1))
    assert result.entry.content == "" and result.entry.version == 1

    async def incomplete_current(conn, method, path, **kwargs):
        result = await original(conn, method, path, **kwargs)
        if "/pages/" in path:
            result.pop("content", None)
        return result

    provider._request = incomplete_current
    with pytest.raises(RuntimeError, match="omitted full entry content"):
        await provider.library(ManagementContext(ExtensionPrincipal("alice", is_admin=True)), "local", "kb", "entry", LibraryQuery(entry="concept/cedar"))


@pytest.fixture
def graph_library(library):
    from deerflow_extension_knowledge_management.lightrag import LightRAGLibrary

    response = {"status": "success", "data": {"entities": [], "relationships": [], "chunks": []}}
    config = {"connections": [{"id": "graph", "base_url": "https://graph.example", "api_key_env": "LIBRARY_TEST_KEY", "grants": [{"user_id": "alice", "knowledge_base_ids": ["workspace"], "operations": ["capabilities", "graph"]}]}]}
    provider = LightRAGLibrary(config, transport=httpx.MockTransport(lambda _: httpx.Response(200, json=response)))
    return provider, response


@pytest.mark.asyncio
@pytest.mark.parametrize("message,empty,accepted", [("Query returned empty dataset.", True, True), ("Query returned empty dataset.", False, False), ("Database unavailable", True, False)])
async def test_lightrag_empty_result_is_not_a_provider_failure(graph_library, message, empty, accepted):
    from deerflow_extension_knowledge_management.contracts import ManagementContext
    from deerflow_extension_knowledge_management.library import LibraryQuery

    provider, response = graph_library
    response.update(status="failure", message=message)
    if not empty:
        response["data"]["entities"] = [{"entity_name": "Cedar"}]
    ctx = ManagementContext(ExtensionPrincipal("alice", is_admin=True))
    if accepted:
        result = await provider.library(ctx, "graph", "workspace", "graph", LibraryQuery(search="Cedar"))
        assert not result.graph.entities and not result.graph.relations
    else:
        with pytest.raises(RuntimeError):
            await provider.library(ctx, "graph", "workspace", "graph", LibraryQuery(search="Cedar"))


@pytest.mark.asyncio
@pytest.mark.parametrize("count", [150, 200, 250])
async def test_graph_node_budget_includes_added_endpoints(graph_library, count):
    from deerflow_extension_knowledge_management.contracts import ManagementContext
    from deerflow_extension_knowledge_management.library import LibraryQuery

    provider, response = graph_library
    response["data"]["entities"] = [{"entity_name": f"node-{i}"} for i in range(count)]
    response["data"]["relationships"] = [{"src_id": "node-0", "tgt_id": "node-1"}, *[{"src_id": f"new-{i}", "tgt_id": f"other-{i}"} for i in range(99)]]
    result = await provider.library(ManagementContext(ExtensionPrincipal("alice", is_admin=True)), "graph", "workspace", "graph", LibraryQuery(search="Cedar"))
    assert len(result.graph.entities) == 200
    ids = {node.id for node in result.graph.entities}
    assert result.graph.relations[0].source == "node-0"
    assert all(edge.source in ids and edge.target in ids for edge in result.graph.relations)


@pytest.mark.asyncio
async def test_conflict_never_retries_and_weknora_has_no_entity_api(library):
    from deerflow_extension_knowledge_management.contracts import ManagementContext
    from deerflow_extension_knowledge_management.library import LibraryQuery

    provider, calls, state = library
    ctx = ManagementContext(ExtensionPrincipal("alice", is_admin=True))
    caps = await provider.capabilities(ctx, "local", "kb")
    assert not {"graph", "entry_edit", "entry_restore"} & caps.operations
    with pytest.raises(NotImplementedError):
        await provider.library(ctx, "local", "kb", "graph", LibraryQuery(search="Cedar"))
    state["code"] = 409
    with pytest.raises(FileExistsError):
        await provider.library(ctx, "local", "kb", "entry", LibraryQuery(entry="concept/cedar"))
    assert len([call for call in calls if call.method == "PUT"]) == 0


@pytest.mark.parametrize("entry", ["../secret", "a/../b", "a%2fb", "a?query", "a#frag", "/a", "a//b", "a\\b"])
def test_slug_cannot_escape_upstream_route(library, entry):
    from deerflow_extension_knowledge_management.library import LibraryQuery

    with pytest.raises(ValueError):
        LibraryQuery(entry=entry)


@pytest.mark.asyncio
async def test_platform_default_deny_new_writes_and_policy_recheck(library, tmp_path):
    from deerflow_extension_knowledge_management.library import LIBRARY_OPERATIONS, EditEntry
    from deerflow_extension_knowledge_platform.models import Settings, resource_key
    from deerflow_extension_knowledge_platform.service import Platform
    from deerflow_extension_knowledge_platform.store import RevisionConflict, Store

    provider, calls, _ = library
    dataset = "wk1_" + hashlib.sha256(json.dumps(["https://weknora.example", "1", "kb"]).encode()).hexdigest()
    settings = Settings.model_validate({"storage_path": str(tmp_path / "library.db"), "connections": [{"id": "local", "provider": "weknora", "resources": [{"base_id": "kb", "dataset_id": dataset}]}]})
    store = Store(settings)
    admin = ExtensionPrincipal("alice", is_admin=True)
    key = resource_key("weknora", "local", "kb")
    policy = {"spaces": {"team": {"title": "Team", "resources": [key], "members": {"alice": "manager"}, "operations": ["capabilities", *LIBRARY_OPERATIONS]}}}
    store.replace(admin, policy, 0)
    platform = Platform(settings, store, {"local": provider})
    edit = EditEntry(entry="concept/cedar", expected_version=2, title="New", content="New")
    with pytest.raises(PermissionError):
        await platform.library(admin, "team", key, "entry_edit", edit)
    assert not calls
    config = settings.model_dump()
    config["connections"][0]["resources"][0]["operations"] = ["capabilities", *LIBRARY_OPERATIONS]
    store = Store(Settings.model_validate(config))
    platform.store = store
    original = provider.capabilities

    async def revoke(*args):
        result = await original(*args)
        await asyncio.to_thread(store.replace, admin, {"spaces": {}}, 1)
        return result.model_copy(update={"operations": result.operations | {"entry_edit"}})

    provider.capabilities = revoke
    with pytest.raises((PermissionError, RevisionConflict)):
        await platform.library(admin, "team", key, "entry_edit", edit)
    assert all(call.method == "GET" for call in calls)


@pytest.mark.asyncio
async def test_lightrag_graph_preserves_real_edges_and_evidence(library, monkeypatch):
    from deerflow_extension_knowledge_management.contracts import ManagementContext
    from deerflow_extension_knowledge_management.library import LibraryQuery
    from deerflow_extension_knowledge_management.lightrag import LightRAGLibrary

    calls = []

    def handler(request):
        calls.append(request)
        assert request.url.path == "/query/data" and request.method == "POST"
        assert json.loads(request.content)["query"] == "Cedar"
        return httpx.Response(
            200,
            json={
                "status": "success",
                "data": {
                    "entities": [{"entity_name": "Cedar", "description": "synthetic-secret tree"}],
                    "relationships": [{"src_id": "Cedar", "tgt_id": "Forest", "description": "Part of", "source_id": "chunk-a<SEP>missing"}],
                    "chunks": [{"chunk_id": "chunk-a", "content": "Cedar grows here"}],
                },
            },
        )

    config = {"connections": [{"id": "graph", "base_url": "https://graph.example", "api_key_env": "LIBRARY_TEST_KEY", "grants": [{"user_id": "alice", "knowledge_base_ids": ["workspace"], "operations": ["capabilities", "graph"]}]}]}
    provider = LightRAGLibrary(config, transport=httpx.MockTransport(handler))
    ctx = ManagementContext(ExtensionPrincipal("alice", is_admin=True))
    assert (await provider.capabilities(ctx, "graph", "workspace")).operations == {"capabilities", "graph"}
    result = await provider.library(ctx, "graph", "workspace", "graph", LibraryQuery(search="Cedar"))
    assert len(result.graph.relations) == 1
    assert result.graph.relations[0].evidence_ids == ("chunk-a",)
    assert {entity.id for entity in result.graph.entities} == {"Cedar", "Forest"}
    assert "synthetic-secret" not in result.model_dump_json()
    with pytest.raises(PermissionError):
        await provider.library(ctx, "graph", "other-workspace", "graph", LibraryQuery(search="Cedar"))
    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("override", [{"content": "x" * 500001}, {"summary": "x" * 10001}, {"title": "x" * 501}, {"slug": "synthetic-secret"}, {"content": "synthetic-secret private"}])
async def test_editable_entries_never_silently_truncate_or_rewrite_redactions(library, override):
    from deerflow_extension_knowledge_management.contracts import ManagementContext
    from deerflow_extension_knowledge_management.library import LibraryQuery

    provider, calls, state = library
    ctx = ManagementContext(ExtensionPrincipal("alice", is_admin=True))
    state["entry_override"] = override
    with pytest.raises((RuntimeError, PermissionError)):
        await provider.library(ctx, "local", "kb", "entry", LibraryQuery(entry="concept/cedar"))
    state.pop("entry_override")
    state["revision_override"] = override
    with pytest.raises((RuntimeError, PermissionError)):
        await provider.library(ctx, "local", "kb", "revision", LibraryQuery(entry="concept/cedar", version=1))
    assert all(call.method == "GET" for call in calls)


@pytest.mark.asyncio
async def test_library_routes_validate_queries_and_host_namespace_scopes(library, tmp_path, monkeypatch):
    from deerflow_extension_knowledge_management.library import LIBRARY_OPERATIONS
    from deerflow_extension_knowledge_platform.models import Settings, resource_key
    from deerflow_extension_knowledge_platform.router import build_router
    from deerflow_extension_knowledge_platform.service import Platform
    from deerflow_extension_knowledge_platform.store import Store
    from fastapi import FastAPI

    provider, calls, _ = library
    ctx = ExtensionPrincipal("alice", is_admin=True)
    scopes = []

    async def host(request, namespace, *, scope):
        scopes.append((namespace, scope))
        return ctx

    monkeypatch.setattr("deerflow_extension_knowledge_platform.router.arequire_plugin_management", host)
    dataset = "wk1_" + hashlib.sha256(json.dumps(["https://weknora.example", "1", "kb"]).encode()).hexdigest()
    settings = Settings.model_validate(
        {"storage_path": str(tmp_path / "routes.db"), "connections": [{"id": "local", "provider": "weknora", "resources": [{"base_id": "kb", "dataset_id": dataset, "operations": ["capabilities", *LIBRARY_OPERATIONS]}]}]}
    )
    store = Store(settings)
    key = resource_key("weknora", "local", "kb")
    store.replace(ctx, {"spaces": {"team": {"title": "Team", "resources": [key], "members": {"alice": "manager"}}}}, 0)
    app = FastAPI()
    app.include_router(build_router(Platform(settings, store, {"local": provider})))
    prefix = f"/api/extensions/knowledge-platform/spaces/team/resources/{key}"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        reply = await client.get(prefix + "/library/documents", params={"search": "Guide"})
        assert reply.status_code == 200 and reply.json()["documents"][0]["title"] == "Guide"
        assert scopes[-2:] == [("knowledge-platform", "read"), ("knowledge-management", "read")]
        for params in ({"page_size": 51}, {"entry": "../escape"}, {"state": "invalid"}, {"version": 0}):
            before = len(calls)
            assert (await client.get(prefix + "/library/entries", params=params)).status_code == 422
            assert len(calls) == before
        reply = await client.put(prefix + "/entry", json={"entry": "concept/cedar", "expected_version": 2, "title": "New", "content": "New"})
        assert reply.status_code == 422
        assert not any(call.method == "PUT" for call in calls)
        assert scopes[-2:] == [("knowledge-platform", "write"), ("knowledge-management", "write")]
        for operation, params in (("entry", {}), ("revision", {"entry": "concept/cedar"})):
            assert (await client.get(prefix + "/library/" + operation, params=params)).status_code == 422

        # A different Provider may implement atomic writes; exercise the generic
        # route's byte budget independently of blocked WeKnora mutations.
        from deerflow_extension_knowledge_management.library import Entry, LibraryResult

        original_caps = provider.capabilities

        async def atomic_caps(*args):
            result = await original_caps(*args)
            return result.model_copy(update={"operations": result.operations | {"entry_edit"}})

        received = []

        async def atomic_write(context, connection, base, operation, payload):
            received.append(payload)
            return LibraryResult(provider="weknora", connection_id="local", dataset_id=dataset, entry=Entry(key=payload.entry, title=payload.title, content=payload.content, version=3, status="published"))

        provider.capabilities = atomic_caps
        provider.library = atomic_write
        # Escaped supplementary Unicode needs 12 JSON bytes per character.
        content = chr(0x1F332) * 500000
        request_body = json.dumps({"entry": "concept/cedar", "expected_version": 2, "title": "New", "content": content})
        assert len(request_body) > 4 * 1024 * 1024
        reply = await client.put(prefix + "/entry", content=request_body, headers={"Content-Type": "application/json"})
        assert reply.status_code == 200 and received[-1].content == content
        before = len(received)
        assert (await client.put(prefix + "/entry", content=b" " * (8 * 1024 * 1024 + 1))).status_code == 413
        assert len(received) == before
        assert (await client.put("/api/extensions/knowledge-platform/policy", content=b" " * (1024 * 1024 + 1))).status_code == 413

        async def invalid_response(*args):
            return {"invalid": "response"}

        provider.library = invalid_response
        assert (await client.get(prefix + "/library/documents")).status_code == 502

        async def invalid_input(*args):
            raise ValueError("Invalid query")

        provider.library = invalid_input
        assert (await client.get(prefix + "/library/documents")).status_code == 422


@pytest.mark.parametrize("value", ["a" * 501, "synthetic-secret", ""])
def test_graph_ids_never_truncate_or_redact_into_another_identity(library, value):
    from deerflow_extension_knowledge_management.lightrag import Connection, graph_id

    conn = Connection(id="graph", base_url="https://graph.example", api_key_env="LIBRARY_TEST_KEY", grants=[{"user_id": "alice", "knowledge_base_ids": ["workspace"], "operations": ["graph"]}])
    with pytest.raises(RuntimeError):
        graph_id(conn, value)


@pytest.mark.asyncio
async def test_history_metadata_does_not_grant_current_entry_body(library):
    from deerflow_extension_knowledge_management.contracts import ManagementContext
    from deerflow_extension_knowledge_management.library import LibraryQuery

    provider, _, _ = library
    result = await provider.library(ManagementContext(ExtensionPrincipal("alice", is_admin=True)), "local", "kb", "revisions", LibraryQuery(entry="concept/cedar"))
    assert result.entry is None and result.revisions[0].version == 1
    assert "Current text" not in result.model_dump_json()


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["current", "snapshot", "both"])
async def test_revision_requires_real_page_identity(library, change):
    from deerflow_extension_knowledge_management.contracts import ManagementContext
    from deerflow_extension_knowledge_management.library import LibraryQuery

    provider, calls, state = library
    if change in {"current", "both"}:
        state["entry_override"] = {"id": None}
    if change in {"snapshot", "both"}:
        state["revision_override"] = {"page_id": None}
    with pytest.raises((ValueError, RuntimeError)):
        await provider.library(ManagementContext(ExtensionPrincipal("alice", is_admin=True)), "local", "kb", "revision", LibraryQuery(entry="concept/cedar", version=1))
    assert all(call.method == "GET" for call in calls)
