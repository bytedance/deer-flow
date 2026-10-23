"""Offline management contract and upstream authorization regressions."""

import json
from pathlib import Path

import httpx
import pytest
from deerflow_extension_api.auth import ExtensionPrincipal


@pytest.fixture
def management(monkeypatch):
    root = Path(__file__).resolve().parents[2]
    monkeypatch.syspath_prepend(str(root / "examples/deerflow-extension-knowledge-management"))
    from deerflow_extension_knowledge_management.weknora import WeKnoraManagement

    monkeypatch.setenv("MANAGEMENT_TEST_KEY", "synthetic-secret")
    calls = []
    state = {"status": "pending", "base": "kb-1", "code": 200}

    def handler(request):
        calls.append(request)
        assert request.headers["X-API-Key"] == "synthetic-secret"
        if state["code"] != 200:
            return httpx.Response(state["code"], text="synthetic-secret private error")
        if request.url.path == "/api/v1/knowledge-bases/kb-1":
            data = {"id": "kb-1", "capabilities": {"wiki": True, "graph": True, "vector": True}, "chunking_config": state.get("chunking_config", {"chunk_size": 1024, "chunk_overlap": 128})}
        else:
            data = {"id": "doc-1", "knowledge_base_id": state["base"], "parse_status": state["status"], "enable_status": "enabled"}
        return httpx.Response(201 if request.url.path.endswith(("/file", "/url")) else 200, json={"success": True, "data": data})

    config = {
        "connections": [
            {
                "id": "local",
                "base_url": "https://weknora.example",
                "tenant_id": "1",
                "api_key_env": "MANAGEMENT_TEST_KEY",
                "grants": [{"user_id": "alice", "knowledge_base_ids": ["kb-1"], "operations": ["capabilities", "status", "upload", "url", "manual", "reprocess", "cancel"]}],
            }
        ]
    }
    return WeKnoraManagement(config, transport=httpx.MockTransport(handler)), calls, state


@pytest.mark.asyncio
async def test_manual_ingestion_status_and_retrieval_identity(management):
    from deerflow_extension_knowledge_management.contracts import IngestRequest, ManagementContext

    provider, calls, state = management
    context = ManagementContext(principal=ExtensionPrincipal("alice", is_admin=True))
    result = await provider.ingest(context, "local", "kb-1", IngestRequest(kind="manual", title="Guide", content="Cedar evidence"))
    assert result.document_id == "doc-1" and result.state == "queued"
    assert result.dataset_id.startswith("wk1_") and not result.searchable
    assert json.loads(calls[-1].content)["status"] == "publish"
    state["status"] = "completed"
    result = await provider.status(context, "local", "kb-1", "doc-1")
    assert result.state == "completed" and result.searchable


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "principal,base", [(ExtensionPrincipal("alice"), "kb-1"), (ExtensionPrincipal("bob", is_admin=True), "kb-1"), (ExtensionPrincipal("alice", is_admin=True), "other"), (ExtensionPrincipal("alice", is_admin=True, is_internal=True), "kb-1")]
)
async def test_denials_make_no_upstream_requests(management, principal, base):
    from deerflow_extension_knowledge_management.contracts import ManagementContext

    provider, calls, _ = management
    with pytest.raises(PermissionError):
        await provider.status(ManagementContext(principal=principal), "local", base, "doc-1")
    assert not calls


@pytest.mark.asyncio
async def test_cross_base_document_cannot_be_reprocessed(management):
    from deerflow_extension_knowledge_management.contracts import ManagementContext, ProcessingOptions

    provider, calls, state = management
    state["base"] = "other"
    with pytest.raises(PermissionError):
        await provider.process(ManagementContext(principal=ExtensionPrincipal("alice", is_admin=True)), "local", "kb-1", "doc-1", "reprocess", ProcessingOptions())
    assert all(call.method == "GET" for call in calls)


@pytest.mark.asyncio
async def test_upstream_auth_failure_never_retries_or_leaks(management):
    from deerflow_extension_knowledge_management.contracts import ManagementContext

    provider, calls, state = management
    state["code"] = 403
    with pytest.raises(PermissionError, match="denied") as error:
        await provider.status(ManagementContext(principal=ExtensionPrincipal("alice", is_admin=True)), "local", "kb-1", "doc-1")
    assert len(calls) == 1 and "synthetic-secret" not in str(error.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["file", "url"])
async def test_ingestion_accepts_created_and_preserves_options(management, kind):
    from deerflow_extension_knowledge_management.contracts import IngestRequest, ManagementContext, ProcessingOptions

    provider, calls, _ = management
    context = ManagementContext(ExtensionPrincipal("alice", is_admin=True))
    options = ProcessingOptions(chunk_size=512, chunk_overlap=64, graph_enabled=True)
    if kind == "file":
        result = await provider.upload(context, "local", "kb-1", "guide.txt", b"Cedar evidence", options)
        assert b'"chunk_size": 512' in calls[-1].content
        assert b"Cedar evidence" in calls[-1].content
    else:
        result = await provider.ingest(context, "local", "kb-1", IngestRequest(kind="url", url="https://example.com/guide", processing=options))
        assert json.loads(calls[-1].content)["process_config"]["chunking_config"] == {"chunk_size": 512, "chunk_overlap": 64}
    assert result.state == "queued"
    assert calls[-1].url.path.endswith("/" + kind)


@pytest.mark.asyncio
async def test_reprocess_and_cancel_keep_original_processing_policy(management):
    from deerflow_extension_knowledge_management.contracts import ManagementContext, ProcessingOptions

    provider, calls, _ = management
    context = ManagementContext(ExtensionPrincipal("alice", is_admin=True))
    for operation, path in [("reprocess", "reparse"), ("cancel", "cancel-parse")]:
        await provider.process(context, "local", "kb-1", "doc-1", operation, ProcessingOptions())
        assert calls[-1].url.path.endswith("/" + path)
        assert calls[-1].content == b""


@pytest.mark.asyncio
async def test_capabilities_are_provider_and_grant_specific(management):
    from deerflow_extension_knowledge_management.contracts import ManagementContext

    provider, _, _ = management
    result = await provider.capabilities(ManagementContext(ExtensionPrincipal("alice", is_admin=True)), "local", "kb-1")
    assert result.pipeline["entries"] == "provider_managed"
    assert result.pipeline["entity_relations"] == "provider_managed"
    assert "upload" in result.operations
    assert "delete" not in result.operations


@pytest.mark.asyncio
async def test_unknown_state_is_not_completed(management):
    from deerflow_extension_knowledge_management.contracts import ManagementContext

    provider, _, state = management
    state["status"] = "new_upstream_state"
    result = await provider.status(ManagementContext(ExtensionPrincipal("alice", is_admin=True)), "local", "kb-1", "doc-1")
    assert result.state == "unknown" and not result.searchable


@pytest.mark.parametrize("payload", [{"chunk_size": 200}, {"chunk_overlap": 50}, {"chunk_size": 100, "chunk_overlap": 100}, {"graph_enabled": "true"}, {"parser_api_key": "secret"}, {"wiki_enabled": True}])
def test_processing_rejects_unsupported_or_invalid_options(management, payload):
    from deerflow_extension_knowledge_management.contracts import ProcessingOptions

    with pytest.raises(ValueError):
        ProcessingOptions.model_validate(payload)


@pytest.mark.asyncio
async def test_unsupported_graph_rejected_before_mutation(management):
    from deerflow_extension_knowledge_management.contracts import ProcessingOptions

    provider, calls, _ = management
    with pytest.raises(NotImplementedError):
        provider._options(ProcessingOptions(graph_enabled=True), {"capabilities": {"graph": False}})
    assert not calls


@pytest.mark.asyncio
@pytest.mark.parametrize("filename,content", [("../guide.txt", b"text"), ("guide\n.txt", b"text"), ("guide.txt", b""), pytest.param("guide.txt", b"x" * (16 * 1024 * 1024 + 1), id="oversized")])
async def test_invalid_upload_never_reaches_provider(management, filename, content):
    from deerflow_extension_knowledge_management.contracts import ManagementContext, ProcessingOptions

    provider, calls, _ = management
    with pytest.raises(ValueError):
        await provider.upload(ManagementContext(ExtensionPrincipal("alice", is_admin=True)), "local", "kb-1", filename, content, ProcessingOptions())
    assert not calls


@pytest.fixture
def api(management):
    from deerflow_extension_api.auth import EXTENSION_PLUGIN_AUTHZ_RESOLVER_ASYNC_KEY, EXTENSION_PRINCIPAL_RESOLVER_KEY
    from deerflow_extension_knowledge_management.router import build_router
    from fastapi import FastAPI

    provider, calls, state = management
    app = FastAPI()
    principal = {"value": ExtensionPrincipal("alice", is_admin=True), "allowed": True}
    setattr(app.state, EXTENSION_PRINCIPAL_RESOLVER_KEY, lambda request: principal["value"])

    async def authorize(request, namespace, scope):
        assert namespace == "knowledge-management"
        assert scope == ("read" if request.method == "GET" else "write")
        return principal["allowed"]

    setattr(app.state, EXTENSION_PLUGIN_AUTHZ_RESOLVER_ASYNC_KEY, authorize)
    app.include_router(build_router(provider))
    return app, principal, calls, state


API_BASE = "/api/extensions/knowledge-management/connections/local/bases/kb-1"


@pytest.mark.asyncio
async def test_router_enforces_host_policy_and_ignores_no_client_identity(api):
    app, principal, calls, _ = api
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        principal["allowed"] = False
        response = await client.post(API_BASE + "/documents", json={"kind": "manual", "title": "Guide", "content": "Text"})
        assert response.status_code == 403 and not calls
        principal["allowed"] = True
        response = await client.post(API_BASE + "/documents", json={"kind": "manual", "title": "Guide", "content": "Text", "user_id": "admin"})
        assert response.status_code == 422 and not calls
        response = await client.post(API_BASE + "/documents", json={"kind": "manual", "title": "Guide", "content": "Text"})
        assert response.status_code == 202 and response.json()["state"] == "queued"


@pytest.mark.asyncio
async def test_router_upload_is_bounded_and_errors_are_sanitized(api, monkeypatch):
    import deerflow_extension_knowledge_management.router as router

    app, _, calls, state = api
    monkeypatch.setattr(router, "MAX_UPLOAD_BYTES", 8)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(API_BASE + "/files?filename=guide.txt", content=b"123456789", headers={"content-type": "application/octet-stream"})
        assert response.status_code == 413 and not calls
        state["code"] = 500
        response = await client.get(API_BASE + "/documents/doc-1")
        assert response.status_code == 502
        assert "synthetic-secret" not in response.text
        assert len(calls) == 1


@pytest.mark.asyncio
async def test_router_fails_closed_without_host_resolver(api):
    from deerflow_extension_api.auth import EXTENSION_PRINCIPAL_RESOLVER_KEY

    app, _, calls, _ = api
    delattr(app.state, EXTENSION_PRINCIPAL_RESOLVER_KEY)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(API_BASE + "/capabilities")
        assert response.status_code == 403 and not calls


def test_install_is_opt_in_and_registers_generic_extension_points(management):
    from deerflow_extension_knowledge_management import install

    class Registry:
        plugins = []
        routes = []

        def plugin(self, value):
            self.plugins.append(value)
            return True

        def routers(self, value):
            self.routes.extend(value)

    registry = Registry()
    install(registry, {})
    assert registry.plugins == registry.routes == []
    provider, _, _ = management
    install(registry, {"enabled": True, "provider_config": provider.settings.model_dump(mode="json")})
    assert registry.plugins[0].namespace == "knowledge-management"
    assert len(registry.routes) == 1


@pytest.mark.asyncio
async def test_ingested_document_flows_through_existing_scope_and_citations(management, monkeypatch):
    from deerflow_extension_knowledge_management.contracts import IngestRequest, ManagementContext

    from deerflow.knowledge import KnowledgeRequestContext, format_result, sources_from_messages

    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / "examples/deerflow-extension-weknora"))
    from deerflow_extension_weknora import WeKnoraProvider

    provider, _, state = management
    result = await provider.ingest(ManagementContext(ExtensionPrincipal("alice", is_admin=True)), "local", "kb-1", IngestRequest(kind="manual", title="Guide", content="Cedar evidence"))
    state["status"] = "completed"
    result = await provider.status(ManagementContext(ExtensionPrincipal("alice", is_admin=True)), "local", "kb-1", result.document_id)
    assert result.searchable

    def read_handler(request):
        path = request.url.path
        if path == "/api/v1/knowledge-bases":
            data = [{"id": "kb-1", "name": "Guide"}]
        elif path.endswith("hybrid-search"):
            assert json.loads(request.content)["knowledge_ids"] == [result.document_id]
            data = [{"knowledge_id": result.document_id, "content": "Cedar evidence", "knowledge_title": "Guide", "score": 0.8}]
        else:
            data = {"id": result.document_id, "knowledge_base_id": "kb-1", "parse_status": "completed", "enable_status": "enabled", "title": "Guide"}
        return httpx.Response(200, json={"success": True, "data": data})

    retrieval = WeKnoraProvider({"spaces": [{"base_url": "https://weknora.example", "tenant_id": "1", "api_key_env": "MANAGEMENT_TEST_KEY", "user_ids": ["alice"]}]}, transport=httpx.MockTransport(read_handler))
    scope = {"version": 1, "mode": "selected", "dataset_ids": [result.dataset_id], "document_filters": [{"dataset_id": result.dataset_id, "document_ids": [result.document_id]}]}
    found = await retrieval.search_scoped("Cedar", context=KnowledgeRequestContext("alice", "lead_agent", scope))
    content, artifact = format_result(found)
    replay = json.loads(json.dumps({"type": "tool", "content": content, "artifact": artifact}))
    sources = sources_from_messages([replay])
    assert len(sources) == 1 and sources[0].provider == "weknora"
    assert sources[0].excerpt == "Cedar evidence"


@pytest.mark.asyncio
async def test_generic_router_supports_non_weknora_provider(api):
    from deerflow_extension_api.auth import EXTENSION_PLUGIN_AUTHZ_RESOLVER_ASYNC_KEY, EXTENSION_PRINCIPAL_RESOLVER_KEY
    from deerflow_extension_knowledge_management.contracts import Capabilities
    from deerflow_extension_knowledge_management.router import build_router
    from fastapi import FastAPI

    class SearchOnly:
        async def capabilities(self, context, connection, base):
            assert context.principal.user_id == "alice"
            return Capabilities(operations=frozenset({"capabilities"}), processing_options=frozenset(), pipeline={"parse": "unsupported"})

        async def ingest(self, *args):
            raise NotImplementedError

    original, _, _, _ = api
    app = FastAPI()
    for key in (EXTENSION_PRINCIPAL_RESOLVER_KEY, EXTENSION_PLUGIN_AUTHZ_RESOLVER_ASYNC_KEY):
        setattr(app.state, key, getattr(original.state, key))
    app.include_router(build_router(SearchOnly()))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(API_BASE + "/capabilities")
        assert response.status_code == 200 and response.json()["operations"] == ["capabilities"]
        response = await client.post(API_BASE + "/documents", json={"kind": "manual", "title": "Guide", "content": "Text"})
        assert response.status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize("code,expected", [(302, 502), (401, 403), (403, 403), (404, 404), (409, 409), (500, 502)])
async def test_http_provider_failures_do_not_retry(api, code, expected):
    app, _, calls, state = api
    state["code"] = code
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(API_BASE + "/documents", json={"kind": "manual", "title": "Guide", "content": "Text"})
        assert response.status_code == expected and len(calls) == 1
        assert "synthetic-secret" not in response.text


@pytest.mark.asyncio
async def test_json_size_limit_precedes_provider_calls(api):
    app, _, calls, _ = api
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(API_BASE + "/documents", content=b" " * (2 * 1024 * 1024 + 1), headers={"content-type": "application/json"})
        assert response.status_code == 413 and not calls


@pytest.mark.parametrize(
    "payload",
    [{"kind": "url", "url": "https://user:password@example.com"}, {"kind": "manual", "title": "Guide", "content": " "}, {"kind": "url", "url": "file:///etc/passwd"}, {"kind": "url", "url": "https://example.com", "content": "unexpected"}],
)
def test_ingest_contract_rejects_unsafe_or_ambiguous_payloads(management, payload):
    from deerflow_extension_knowledge_management.contracts import IngestRequest

    with pytest.raises(ValueError):
        IngestRequest.model_validate(payload)


@pytest.mark.asyncio
async def test_poll_rechecks_grants_and_never_caches_authorization(management):
    from deerflow_extension_knowledge_management.contracts import ManagementContext

    provider, calls, _ = management
    await provider.status(ManagementContext(ExtensionPrincipal("alice", is_admin=True)), "local", "kb-1", "doc-1")
    count = len(calls)
    with pytest.raises(PermissionError):
        await provider.status(ManagementContext(ExtensionPrincipal("mallory", is_admin=True)), "local", "kb-1", "doc-1")
    assert len(calls) == count


@pytest.mark.asyncio
async def test_missing_credential_never_uses_another_connection(management, monkeypatch):
    from deerflow_extension_knowledge_management.contracts import ManagementContext

    provider, calls, _ = management
    monkeypatch.delenv("MANAGEMENT_TEST_KEY")
    with pytest.raises(RuntimeError, match="credential"):
        await provider.status(ManagementContext(ExtensionPrincipal("alice", is_admin=True)), "local", "kb-1", "doc-1")
    assert not calls


@pytest.mark.asyncio
async def test_declared_optional_operations_fail_closed(management):
    from deerflow_extension_knowledge_management.contracts import ManagementContext, ManagementProvider, ProcessingOptions

    class CatalogOnly(ManagementProvider):
        pass

    with pytest.raises(NotImplementedError):
        await CatalogOnly().upload(ManagementContext(ExtensionPrincipal("alice", is_admin=True)), "connection", "base", "file.txt", b"text", ProcessingOptions())


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["manual", "url", "upload", "reprocess"])
async def test_parent_child_chunk_overrides_rejected_before_mutation(management, operation):
    from deerflow_extension_knowledge_management.contracts import IngestRequest, ManagementContext, ProcessingOptions

    provider, calls, state = management
    state["chunking_config"] = {"chunk_size": 1024, "chunk_overlap": 128, "enable_parent_child": True, "parent_chunk_size": 4096, "child_chunk_size": 384}
    context = ManagementContext(ExtensionPrincipal("alice", is_admin=True))
    options = ProcessingOptions(chunk_size=512, chunk_overlap=64)
    with pytest.raises(NotImplementedError, match="parent-child"):
        if operation == "upload":
            await provider.upload(context, "local", "kb-1", "guide.txt", b"text", options)
        elif operation == "reprocess":
            await provider.process(context, "local", "kb-1", "doc-1", operation, options)
        else:
            body = {"kind": operation, "title": "Guide", "processing": options}
            body.update({"content": "text"} if operation == "manual" else {"url": "https://example.com"})
            await provider.ingest(context, "local", "kb-1", IngestRequest(**body))
    assert calls and all(call.method == "GET" for call in calls)
    assert state["chunking_config"]["parent_chunk_size"] == 4096


def test_parent_child_without_chunk_overrides_preserves_policy(management):
    from deerflow_extension_knowledge_management.contracts import ProcessingOptions

    provider, _, _ = management
    base = {"chunking_config": {"enable_parent_child": True, "parent_chunk_size": 4096, "child_chunk_size": 384}}
    assert provider._options(ProcessingOptions(), base) == {}
    assert provider._options(ProcessingOptions(summary_enabled=False), base) == {"summary_enabled": False}


def test_weknora_zero_overlap_override_is_not_silently_ignored(management):
    from deerflow_extension_knowledge_management.contracts import ProcessingOptions

    provider, _, _ = management
    with pytest.raises(NotImplementedError):
        provider._options(ProcessingOptions(chunk_size=512, chunk_overlap=0), {"chunking_config": {"chunk_overlap": 128}})


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["timeout", "connect", "json", "envelope", "status"])
async def test_provider_failure_diagnostics_are_sanitized(management, caplog, failure):
    from deerflow_extension_knowledge_management.contracts import ManagementContext
    from deerflow_extension_knowledge_management.router import _invoke
    from fastapi import HTTPException

    provider, _, _ = management
    secret = "synthetic-secret private-payload https://private.example/token"

    def fail(request):
        if failure == "timeout":
            raise httpx.ReadTimeout(secret, request=request)
        if failure == "connect":
            raise httpx.ConnectError(secret, request=request)
        if failure == "json":
            return httpx.Response(200, text=secret)
        if failure == "envelope":
            return httpx.Response(200, json={"error": secret})
        return httpx.Response(503, text=secret)

    provider.transport = httpx.MockTransport(fail)
    with caplog.at_level("WARNING"), pytest.raises(HTTPException) as caught:
        await _invoke(provider.status(ManagementContext(ExtensionPrincipal("alice", is_admin=True)), "local", "kb-1", "doc-1"))
    assert caught.value.status_code == 502
    expected = {"timeout": "ReadTimeout", "connect": "ConnectError", "json": "JSONDecodeError", "envelope": "invalid_envelope", "status": "status=503"}[failure]
    assert expected in caplog.text
    assert "RuntimeError" in caplog.text
    for text in (caplog.text, str(caught.value.detail)):
        assert "synthetic-secret" not in text and "private-payload" not in text and "private.example" not in text
    assert all(record.exc_info is None for record in caplog.records)


@pytest.mark.asyncio
async def test_custom_provider_exception_text_is_not_logged(management, caplog):
    from deerflow_extension_knowledge_management.router import _invoke
    from fastapi import HTTPException

    async def fail():
        raise RuntimeError("synthetic-secret private document")

    with caplog.at_level("WARNING"), pytest.raises(HTTPException):
        await _invoke(fail())
    assert "RuntimeError" in caplog.text
    assert "synthetic-secret" not in caplog.text and "private document" not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)


@pytest.mark.asyncio
@pytest.mark.parametrize("chunking,graph,expected", [({"enable_parent_child": True}, False, {"summary_enabled"}), (None, True, {"summary_enabled", "graph_enabled"}), ({}, False, {"summary_enabled", "chunk_size", "chunk_overlap"})])
async def test_capability_options_reflect_base_support(management, chunking, graph, expected):
    from deerflow_extension_knowledge_management.contracts import ManagementContext

    provider, _, _ = management
    provider.transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"success": True, "data": {"id": "kb-1", "chunking_config": chunking, "capabilities": {"graph": graph}}}))
    result = await provider.capabilities(ManagementContext(ExtensionPrincipal("alice", is_admin=True)), "local", "kb-1")
    assert result.processing_options == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("credential", [None, "", "invalid secret", "非ASCII"])
async def test_unavailable_credential_is_local_service_failure(api, monkeypatch, caplog, credential):
    app, _, calls, _ = api
    if credential is None:
        monkeypatch.delenv("MANAGEMENT_TEST_KEY")
    else:
        monkeypatch.setenv("MANAGEMENT_TEST_KEY", credential)
    with caplog.at_level("WARNING"):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.get(API_BASE + "/capabilities")
    assert response.status_code == 503
    assert response.json()["detail"] == "Management credential is not configured"
    assert not calls
    assert "ManagementCredentialUnavailable" in caplog.text
    assert "reconcile" not in response.text
    if credential:
        assert credential not in caplog.text + response.text
