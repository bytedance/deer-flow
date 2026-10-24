"""Synthetic platform policy, persistence and management composition regressions."""

import asyncio
from pathlib import Path

import pytest
from deerflow_extension_api.auth import ExtensionPrincipal


@pytest.fixture
def platform(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[2]
    for package in ("knowledge-platform", "knowledge-management"):
        monkeypatch.syspath_prepend(str(root / "examples" / f"deerflow-extension-{package}"))
    from deerflow_extension_knowledge_platform.models import Settings, resource_key
    from deerflow_extension_knowledge_platform.store import Store

    resource = resource_key("weknora", "local", "kb")
    settings = Settings.model_validate(
        {"enabled": True, "storage_path": str(tmp_path / "platform.db"), "connections": [{"id": "local", "provider": "weknora", "provider_config": {}, "resources": [{"base_id": "kb", "dataset_id": "wk1_fixture"}]}]}
    )
    store = Store(settings)
    return store, settings, resource


ADMIN = ExtensionPrincipal("alice", is_admin=True)
MEMBER = ExtensionPrincipal("bob")


def document(resource):
    return {
        "connections": {"local": {}},
        "spaces": {
            "org": {"title": "Organization", "resources": [resource], "members": {"alice": "manager", "bob": "viewer"}},
            "division": {"title": "Division", "parent_id": "org", "processing": {"summary_enabled": True}},
            "team": {"title": "Team", "parent_id": "division", "operations": ["capabilities", "status", "manual"], "processing": {"summary_enabled": False}},
            "project": {"title": "Project", "parent_id": "team"},
        },
    }


def test_four_level_inheritance_and_restart(platform):
    from deerflow_extension_knowledge_platform.store import Store

    store, settings, resource = platform
    result = store.replace(ADMIN, document(resource), 0)
    assert result["revision"] == 1
    effective = Store(settings).effective(ADMIN, "project")
    assert effective["resources"][0]["dataset_id"] == "wk1_fixture"
    assert effective["resources"][0]["processing"] == {"summary_enabled": False}
    assert set(effective["resources"][0]["operations"]) == {"capabilities", "status", "manual"}
    assert effective["role"] == "manager"


def test_members_cannot_edit_or_escalate(platform):
    store, _, resource = platform
    store.replace(ADMIN, document(resource), 0)
    with pytest.raises(PermissionError):
        store.replace(MEMBER, document(resource), 1)
    effective = store.effective(MEMBER, "project")
    assert set(effective["resources"][0]["operations"]) == {"capabilities", "status"}
    with pytest.raises(PermissionError):
        store.effective(ExtensionPrincipal("outsider", is_admin=True), "project")


@pytest.mark.parametrize("change", ["cycle", "missing_parent", "resource_widening", "operation_widening", "role_widening", "unknown_connection"])
def test_invalid_graph_rolls_back(platform, change):
    store, _, resource = platform
    data = document(resource)
    store.replace(ADMIN, data, 0)
    if change == "cycle":
        data["spaces"]["org"]["parent_id"] = "project"
    elif change == "missing_parent":
        data["spaces"]["team"]["parent_id"] = "missing"
    elif change == "resource_widening":
        data["spaces"]["team"]["resources"] = ["unmapped"]
    elif change == "operation_widening":
        data["spaces"]["project"]["operations"] = ["upload"]
    elif change == "role_widening":
        data["spaces"]["project"]["members"] = {"bob": "manager"}
    else:
        data["connections"]["evil"] = {}
    with pytest.raises(ValueError):
        store.replace(ADMIN, data, 1)
    assert store.read(ADMIN)["revision"] == 1


def test_ancestor_revocation_and_connection_disable(platform):
    store, _, resource = platform
    data = document(resource)
    store.replace(ADMIN, data, 0)
    del data["spaces"]["org"]["members"]["bob"]
    store.replace(ADMIN, data, 1)
    with pytest.raises(PermissionError):
        store.effective(MEMBER, "project")
    data["connections"]["local"]["enabled"] = False
    store.replace(ADMIN, data, 2)
    assert store.effective(ADMIN, "project")["resources"] == []


def test_sharing_is_explicit_and_same_named_resources_do_not_alias(platform):
    from deerflow_extension_knowledge_platform.models import resource_key

    store, _, resource = platform
    assert resource != resource_key("weknora", "other", "kb")
    data = document(resource)
    data["spaces"]["other"] = {"title": "Other organization", "resources": [], "members": {"bob": "viewer"}}
    store.replace(ADMIN, data, 0)
    assert store.effective(MEMBER, "other")["resources"] == []
    data["spaces"]["other"]["resources"] = [resource]
    store.replace(ADMIN, data, 1)
    assert store.effective(MEMBER, "other")["resources"][0]["resource_id"] == resource


def test_concurrent_writers_conflict_instead_of_losing_update(platform):
    from concurrent.futures import ThreadPoolExecutor

    from deerflow_extension_knowledge_platform.store import RevisionConflict

    store, _, resource = platform

    def write():
        try:
            store.replace(ADMIN, document(resource), 0)
            return "saved"
        except RevisionConflict:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(lambda _: write(), range(2))) == ["conflict", "saved"]


def _process_writer(settings_data, resource):
    from deerflow_extension_knowledge_platform.models import Settings
    from deerflow_extension_knowledge_platform.store import RevisionConflict, Store

    try:
        Store(Settings.model_validate(settings_data)).replace(ADMIN, document(resource), 0)
        return "saved"
    except RevisionConflict:
        return "conflict"


def test_independent_processes_share_the_sqlite_revision_fence(platform):
    import multiprocessing
    from concurrent.futures import ProcessPoolExecutor

    _, settings, resource = platform
    with ProcessPoolExecutor(max_workers=2, mp_context=multiprocessing.get_context("spawn")) as pool:
        futures = [pool.submit(_process_writer, settings.model_dump(), resource) for _ in range(2)]
        assert sorted(future.result(timeout=30) for future in futures) == ["conflict", "saved"]


@pytest.mark.asyncio
async def test_space_management_preserves_principal_and_applies_defaults(platform):
    from deerflow_extension_knowledge_management.contracts import Capabilities, IngestRequest, ProcessingResult
    from deerflow_extension_knowledge_platform.service import Platform

    store, settings, resource = platform
    data = document(resource)
    store.replace(ADMIN, data, 0)
    calls = []

    class Provider:
        async def capabilities(self, context, connection, base):
            return Capabilities(operations={"capabilities", "manual", "status"}, processing_options={"summary_enabled"}, pipeline={})

        async def ingest(self, context, connection, base, body):
            calls.append((context.principal, connection, base, body.processing))
            return ProcessingResult(provider="weknora", connection_id="local", dataset_id="wk1_fixture", document_id="doc", state="queued", provider_state="pending", searchable=False)

    service = Platform(settings, store, {"local": Provider()})
    body = IngestRequest(kind="manual", title="Synthetic", content="Cedar")
    await service.invoke(ADMIN, "project", resource, "manual", body)
    assert calls[0][:3] == (ADMIN, "local", "kb")
    assert calls[0][3].summary_enabled is False
    for principal, operation in [(MEMBER, "manual"), (ExtensionPrincipal("alice", is_admin=True, is_internal=True), "manual"), (ADMIN, "upload")]:
        with pytest.raises(PermissionError):
            await service.invoke(principal, "project", resource, operation, body)
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_policy_denial_before_any_provider_call(platform):
    from deerflow_extension_knowledge_platform.service import Platform

    store, settings, resource = platform
    store.replace(ADMIN, document(resource), 0)

    class Provider:
        def __getattr__(self, name):
            pytest.fail("Denied request contacted provider")

    service = Platform(settings, store, {"local": Provider()})
    with pytest.raises(PermissionError):
        await service.invoke(ADMIN, "project", "unknown-resource", "status", "doc")


@pytest.mark.asyncio
async def test_http_trusted_auth_and_bounded_input(platform):
    import httpx
    from deerflow_extension_knowledge_platform.router import build_router
    from deerflow_extension_knowledge_platform.service import Platform
    from fastapi import FastAPI

    store, settings, resource = platform
    app = FastAPI()
    app.include_router(build_router(Platform(settings, store, {})))
    principal = ADMIN
    scopes = []
    app.state.deerflow_extension_principal_resolver = lambda request: principal

    async def authorize(request, namespace, scope):
        scopes.append((namespace, scope))
        return True

    app.state.deerflow_extension_plugin_authz_resolver_async = authorize
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.put("/api/extensions/knowledge-platform/policy", json={"revision": 0, "policy": document(resource)})
        assert response.status_code == 200
        response = await client.put("/api/extensions/knowledge-platform/policy", json={"revision": 0, "policy": document(resource)})
        assert response.status_code == 409
        principal = MEMBER
        assert (await client.get("/api/extensions/knowledge-platform/spaces/project")).status_code == 200
        assert (await client.get("/api/extensions/knowledge-platform/policy")).status_code == 403
        assert (await client.post(f"/api/extensions/knowledge-platform/spaces/project/resources/{resource}/documents", json={"user_id": "alice"})).status_code == 403
        principal = ADMIN
        assert (await client.put("/api/extensions/knowledge-platform/policy", content=b"x" * (1024 * 1024 + 1))).status_code == 413
        assert (await client.put("/api/extensions/knowledge-platform/policy", json={"revision": 1, "policy": document(resource), "user_id": "alice"})).status_code == 422
        principal = None
        assert (await client.get("/api/extensions/knowledge-platform/spaces")).status_code == 403
    assert ("knowledge-platform", "write") in scopes


@pytest.mark.asyncio
async def test_platform_database_work_runs_off_loop(platform, monkeypatch):
    from deerflow_extension_knowledge_platform.service import Platform

    store, settings, _ = platform
    original = store.read

    def read(principal):
        with pytest.raises(RuntimeError):
            asyncio.get_running_loop()
        return original(principal)

    monkeypatch.setattr(store, "read", read)
    assert (await Platform(settings, store, {}).policy(ADMIN))["revision"] == 0


@pytest.mark.asyncio
async def test_revocation_during_capability_lookup_prevents_write(platform):
    from deerflow_extension_knowledge_management.contracts import Capabilities, IngestRequest
    from deerflow_extension_knowledge_platform.service import Platform

    store, settings, resource = platform
    data = document(resource)
    store.replace(ADMIN, data, 0)

    class Provider:
        async def capabilities(self, *args):
            data["connections"]["local"]["enabled"] = False
            await asyncio.to_thread(store.replace, ADMIN, data, 1)
            return Capabilities(operations={"manual"}, processing_options={"summary_enabled"}, pipeline={})

        async def ingest(self, *args):
            pytest.fail("Revoked policy submitted an upstream write")

    with pytest.raises(PermissionError):
        await Platform(settings, store, {"local": Provider()}).invoke(ADMIN, "project", resource, "manual", IngestRequest(kind="manual", title="Test", content="Test"))


@pytest.mark.asyncio
async def test_real_management_adapter_composition(platform, monkeypatch):
    import hashlib
    import json

    import httpx
    from deerflow_extension_knowledge_management.contracts import IngestRequest
    from deerflow_extension_knowledge_management.weknora import WeKnoraManagement
    from deerflow_extension_knowledge_platform.service import Platform

    store, settings, resource = platform
    dataset = "wk1_" + hashlib.sha256(json.dumps(["https://weknora.invalid", "1", "kb"], ensure_ascii=False).encode()).hexdigest()
    updated = settings.model_dump()
    updated["connections"][0]["resources"][0]["dataset_id"] = dataset
    from deerflow_extension_knowledge_platform.models import Settings
    from deerflow_extension_knowledge_platform.store import Store

    settings = Settings.model_validate(updated)
    store = Store(settings)
    store.replace(ADMIN, document(resource), 0)
    monkeypatch.setenv("PLATFORM_SYNTHETIC_KEY", "synthetic-secret")
    calls, code = [], [200]

    def handler(request):
        calls.append(request)
        assert request.headers["X-API-Key"] == "synthetic-secret"
        if code[0] != 200:
            return httpx.Response(code[0], text="synthetic-secret")
        if request.url.path == "/api/v1/knowledge-bases/kb":
            data = {"id": "kb", "capabilities": {"wiki": True}, "chunking_config": {"chunk_size": 1024, "chunk_overlap": 128}}
        else:
            data = {"id": "doc", "knowledge_base_id": "kb", "parse_status": "pending", "enable_status": "enabled"}
        return httpx.Response(200, json={"success": True, "data": data})

    provider = WeKnoraManagement(
        {
            "connections": [
                {
                    "id": "local",
                    "base_url": "https://weknora.invalid",
                    "tenant_id": "1",
                    "api_key_env": "PLATFORM_SYNTHETIC_KEY",
                    "grants": [{"user_id": "alice", "knowledge_base_ids": ["kb"], "operations": ["capabilities", "manual", "status"]}],
                }
            ]
        },
        transport=httpx.MockTransport(handler),
    )
    service = Platform(settings, store, {"local": provider})
    body = IngestRequest(kind="manual", title="Synthetic", content="Cedar")
    result = await service.invoke(ADMIN, "project", resource, "manual", body)
    assert result.dataset_id == dataset and result.state == "queued"
    assert json.loads(calls[-1].content)["process_config"]["summary_enabled"] is False
    status = await service.invoke(ADMIN, "project", resource, "status", "doc")
    assert status.document_id == "doc"
    code[0] = 403
    before = len(calls)
    with pytest.raises(PermissionError):
        await service.invoke(ADMIN, "project", resource, "manual", body)
    assert len(calls) == before + 1
    # Correct space policy still cannot bypass the existing provider's exact-user grant.
    data = document(resource)
    data["spaces"]["org"]["members"]["unbound"] = "manager"
    store.replace(ADMIN, data, 1)
    before = len(calls)
    with pytest.raises(PermissionError):
        await service.invoke(ExtensionPrincipal("unbound", is_admin=True), "project", resource, "manual", body)
    assert len(calls) == before


@pytest.mark.asyncio
async def test_mismatched_result_identity_is_not_remapped(platform):
    from deerflow_extension_knowledge_management.contracts import ProcessingResult
    from deerflow_extension_knowledge_platform.service import Platform

    store, settings, resource = platform
    store.replace(ADMIN, document(resource), 0)

    class Provider:
        async def status(self, *args):
            return ProcessingResult(provider="weknora", connection_id="other", dataset_id="wrong", document_id="doc", state="completed", provider_state="completed", searchable=True)

    with pytest.raises(RuntimeError, match="identity"):
        await Platform(settings, store, {"local": Provider()}).invoke(ADMIN, "project", resource, "status", "doc")


def test_connections_and_tools_limit_effective_capabilities(platform):
    store, _, resource = platform
    data = document(resource)
    data["connections"]["local"] = {"operations": ["status"], "tools": ["knowledge_search"], "default_tool": "knowledge_search"}
    store.replace(ADMIN, data, 0)
    item = store.effective(ADMIN, "project")["resources"][0]
    assert item["operations"] == ["status"]
    assert item["tools"] == ["knowledge_search"]
    data["spaces"]["project"]["default_tool"] = "entity_relations_search"
    with pytest.raises(ValueError):
        store.replace(ADMIN, data, 1)


def test_platform_defaults_are_inherited_with_a_permission_ceiling(platform):
    store, _, resource = platform
    data = document(resource)
    data["defaults"] = {"operations": ["capabilities", "status", "manual"], "processing": {"graph_enabled": False}, "tools": ["knowledge_search"], "default_tool": "knowledge_search"}
    store.replace(ADMIN, data, 0)
    item = store.effective(ADMIN, "project")["resources"][0]
    assert item["processing"] == {"graph_enabled": False, "summary_enabled": False}
    assert item["tools"] == ["knowledge_search"]
    assert item["default_tool"] == "knowledge_search"
    assert set(item["operations"]) == {"capabilities", "status", "manual"}


def test_child_can_explicitly_clear_inherited_default_tool(platform):
    store, _, resource = platform
    data = document(resource)
    data["defaults"] = {"default_tool": "knowledge_search"}
    data["spaces"]["project"].update(tools=[], default_tool=None)
    store.replace(ADMIN, data, 0)
    item = store.effective(ADMIN, "project")["resources"][0]
    assert item["tools"] == [] and item["default_tool"] is None
    snapshot = store.read(ADMIN)
    store.replace(ADMIN, snapshot["policy"], 1)
    assert store.effective(ADMIN, "team")["resources"][0]["default_tool"] == "knowledge_search"
    assert store.effective(ADMIN, "project")["resources"][0]["default_tool"] is None


def test_operator_resource_removal_can_be_reconciled_without_global_outage(platform):
    from deerflow_extension_knowledge_platform.models import Settings
    from deerflow_extension_knowledge_platform.store import Store

    store, settings, resource = platform
    data = document(resource)
    data["spaces"]["unrelated"] = {"title": "Unrelated", "resources": [], "members": {"alice": "manager"}}
    store.replace(ADMIN, data, 0)
    changed = settings.model_dump()
    changed["connections"][0]["resources"] = [{"base_id": "replacement", "dataset_id": "wk1_replacement"}]
    store = Store(Settings.model_validate(changed))
    snapshot = store.read(ADMIN)
    assert snapshot["revision"] == 1
    assert store.effective(ADMIN, "unrelated")["resources"] == []
    with pytest.raises(PermissionError):
        store.effective(ADMIN, "project")
    assert [s["space_id"] for s in store.spaces(ADMIN)["items"]] == ["unrelated"]
    data["spaces"]["org"]["resources"] = []
    assert store.replace(ADMIN, data, 1)["revision"] == 2


def test_operator_tool_revocation_cannot_leave_an_invalid_default(platform):
    from deerflow_extension_knowledge_platform.models import Settings
    from deerflow_extension_knowledge_platform.store import Store

    store, settings, resource = platform
    data = document(resource)
    data["defaults"] = {"default_tool": "knowledge_search"}
    store.replace(ADMIN, data, 0)
    changed = settings.model_dump()
    changed["connections"][0]["resources"][0]["tools"] = []
    store = Store(Settings.model_validate(changed))
    assert store.read(ADMIN)["revision"] == 1
    with pytest.raises(PermissionError):
        store.effective(ADMIN, "project")


def test_management_namespace_can_be_registered_without_direct_routes(platform):
    from deerflow_extension_knowledge_management import install

    class Registry:
        plugins, mounted = [], []

        def plugin(self, contribution):
            self.plugins.append(contribution)
            return True

        def routers(self, routes):
            self.mounted.extend(routes)

    registry = Registry()
    install(registry, {"enabled": True, "routes_enabled": False})
    assert len(registry.plugins) == 1
    assert registry.plugins[0].namespace == "knowledge-management"
    assert not registry.mounted


def test_policy_never_serializes_operator_configuration(platform):
    import json

    store, _, _ = platform
    assert "provider_config" not in json.dumps(store.read(ADMIN))


@pytest.mark.asyncio
async def test_dual_namespace_authorization_is_required(platform):
    import httpx
    from deerflow_extension_knowledge_platform.router import build_router
    from deerflow_extension_knowledge_platform.service import Platform
    from fastapi import FastAPI

    store, settings, resource = platform
    store.replace(ADMIN, document(resource), 0)
    app = FastAPI()
    app.include_router(build_router(Platform(settings, store, {})))
    app.state.deerflow_extension_principal_resolver = lambda request: ADMIN

    async def authorize(request, namespace, scope):
        return namespace == "knowledge-platform"

    app.state.deerflow_extension_plugin_authz_resolver_async = authorize
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get(f"/api/extensions/knowledge-platform/spaces/project/resources/{resource}/capabilities")
    assert response.status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["upload", "reprocess", "cancel"])
async def test_remaining_management_operations_preserve_contract(platform, operation):
    from deerflow_extension_knowledge_management.contracts import Capabilities, ProcessingOptions, ProcessingResult
    from deerflow_extension_knowledge_platform.service import Platform

    store, settings, resource = platform
    data = document(resource)
    del data["spaces"]["team"]["operations"]
    store.replace(ADMIN, data, 0)
    calls = []
    result = ProcessingResult(provider="weknora", connection_id="local", dataset_id="wk1_fixture", document_id="doc", state="unknown", provider_state="new_upstream_state", searchable=False)

    class Provider:
        async def capabilities(self, *args):
            return Capabilities(operations={"upload", "reprocess", "cancel"}, processing_options={"summary_enabled"}, pipeline={})

        async def upload(self, context, connection, base, filename, content, options):
            calls.append((filename, content, options.model_dump(exclude_none=True)))
            return result

        async def process(self, context, connection, base, document, action, options):
            calls.append((document, action, options.model_dump(exclude_none=True)))
            return result

    value = await Platform(settings, store, {"local": Provider()}).invoke(ADMIN, "project", resource, operation, ProcessingOptions(), document="doc", filename="guide.txt", content=b"synthetic")
    assert value == result  # No fabricated success for an unknown upstream state.
    assert calls == ([("guide.txt", b"synthetic", {"summary_enabled": False})] if operation == "upload" else [("doc", operation, {})])


@pytest.mark.asyncio
async def test_unsupported_options_do_not_mutate_or_retry(platform):
    from deerflow_extension_knowledge_management.contracts import Capabilities, IngestRequest
    from deerflow_extension_knowledge_platform.service import Platform

    store, settings, resource = platform
    store.replace(ADMIN, document(resource), 0)
    calls = []

    class Provider:
        async def capabilities(self, *args):
            calls.append("capabilities")
            return Capabilities(operations={"manual"}, processing_options=set(), pipeline={})

        async def ingest(self, *args):
            pytest.fail("Unsupported option submitted a write")

    with pytest.raises(NotImplementedError):
        await Platform(settings, store, {"local": Provider()}).invoke(ADMIN, "project", resource, "manual", IngestRequest(kind="manual", title="Synthetic", content="Test"))
    assert calls == ["capabilities"]


def test_install_is_opt_in_and_uses_only_operator_factory(platform, monkeypatch):
    from types import SimpleNamespace

    from deerflow_extension_knowledge_platform import install

    _, settings, _ = platform
    calls = []

    class Registry:
        plugins, mounted = [], []

        def plugin(self, contribution):
            self.plugins.append(contribution)
            return True

        def routers(self, routes):
            self.mounted.extend(routes)

    registry = Registry()
    install(registry, {})
    assert not registry.plugins
    monkeypatch.setattr("deerflow_extension_knowledge_platform.import_module", lambda module: SimpleNamespace(WeKnoraManagement=lambda config: calls.append(config) or object()))
    install(registry, settings.model_dump())
    assert len(registry.plugins) == len(registry.mounted) == len(calls) == 1
    assert registry.plugins[0].namespace == "knowledge-platform"
    assert registry.plugins[0].frontend is None
