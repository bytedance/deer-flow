"""Catalog discovery is read-only; imports validate before encrypted persistence."""

import asyncio
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException
from pydantic import SecretStr

from app.gateway.routers import managed_models as router
from deerflow.config.app_config import AppConfig
from deerflow.config.managed_models import ManagedModel, ManagedModelStore

ADMIN = SimpleNamespace(state=SimpleNamespace(user=SimpleNamespace(system_role="admin")))


@pytest.fixture
def setup(monkeypatch, tmp_path):
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    monkeypatch.setattr(router, "get_app_config", lambda: AppConfig.model_validate({"sandbox": {"use": "test"}}))
    return ManagedModelStore()


def connection(**kw):
    return router.ModelConnection(provider="openai", api_key="catalog-secret", **kw)


@pytest.mark.asyncio
async def test_discovery_uses_saved_key_and_never_writes(setup, monkeypatch):
    saved = setup.save(ManagedModel(provider="openai", model="existing", api_key="catalog-secret"), expected_revision=None)
    before = setup.path.read_bytes()

    async def send(client, request, **kwargs):
        assert str(request.url) == "https://api.openai.com/v1/models"
        assert request.headers["authorization"] == "Bearer catalog-secret"
        return httpx.Response(200, request=request, json={"data": [{"id": "existing"}, {"id": "new"}, {"id": "new"}, {"id": "bad\n"}, {"id": 5}]})

    monkeypatch.setattr(httpx.AsyncClient, "send", send)
    body = router.ModelConnection(provider="openai", saved_model_name=saved.name, expected_revision=saved.revision)
    result = await router.discover_models(ADMIN, body)
    assert result == {"models": [{"id": "existing", "configured": True}, {"id": "new", "configured": False}], "truncated": False}
    assert setup.path.read_bytes() == before
    assert "catalog-secret" not in str(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("status,code", [(401, "authentication_failed"), (403, "authentication_failed"), (404, "discovery_unsupported"), (302, "discovery_failed"), (500, "discovery_failed")])
async def test_discovery_errors_redact_provider_details(setup, monkeypatch, status, code):
    async def send(client, request, **kwargs):
        return httpx.Response(status, request=request, text="catalog-secret", headers={"location": "https://other.invalid"})

    monkeypatch.setattr(httpx.AsyncClient, "send", send)
    with pytest.raises(HTTPException) as exc:
        await router.discover_models(ADMIN, connection())
    assert exc.value.detail["code"] == code
    assert "catalog-secret" not in str(exc.value.detail)


@pytest.mark.asyncio
async def test_non_admin_cannot_discover_or_import(setup):
    member = SimpleNamespace(state=SimpleNamespace(user=SimpleNamespace(system_role="user")))
    for fn, body in [(router.discover_models, connection()), (router.import_model, router.ImportModelRequest(connection=connection(), model="new"))]:
        with pytest.raises(HTTPException) as exc:
            await fn(member, body)
        assert exc.value.status_code == 403
    assert not setup.path.exists()


@pytest.mark.asyncio
async def test_import_only_saves_after_probe_and_retries_do_not_duplicate(setup, monkeypatch):
    calls = []

    async def probe(request, body):
        calls.append(body.config.model)
        return {"ok": body.config.model != "bad", "message": "success" if body.config.model != "bad" else "tool_call_missing"}

    monkeypatch.setattr(router, "test_model", probe)
    bad = await router.import_model(ADMIN, router.ImportModelRequest(connection=connection(), model="bad"))
    assert bad["status"] == "failed"
    assert not setup.path.exists()
    body = router.ImportModelRequest(connection=connection(), model="new")
    results = await asyncio.gather(*(router.import_model(ADMIN, body) for _ in range(3)))
    assert all(r["status"] in {"saved", "existing"} for r in results)
    assert len(setup.list()) == 1
    assert setup.list()[0].api_key == SecretStr("catalog-secret")
    assert b"catalog-secret" not in setup.path.read_bytes()
    again = await router.import_model(ADMIN, body)
    assert again["status"] == "existing"


@pytest.mark.asyncio
async def test_saved_key_cannot_cross_connection_or_revision(setup):
    saved = setup.save(ManagedModel(provider="openai", model="existing", api_key="catalog-secret"), expected_revision=None)
    for overrides in [{"provider": "anthropic"}, {"expected_revision": "stale"}]:
        body = router.ModelConnection(**{"provider": "openai", "saved_model_name": saved.name, "expected_revision": saved.revision, **overrides})
        with pytest.raises(HTTPException):
            await router.discover_models(ADMIN, body)


@pytest.mark.asyncio
async def test_native_pagination_and_auth_headers(setup, monkeypatch):
    requests = []

    async def send(client, request, **kwargs):
        requests.append(request)
        assert request.url.path == "/v1/models"
        assert request.headers["x-api-key"] == "native-secret"
        assert "authorization" not in request.headers
        page = {"data": [{"id": "first"}], "has_more": True, "last_id": "first"} if len(requests) == 1 else {"data": [{"id": "second"}], "has_more": False}
        return httpx.Response(200, request=request, json=page)

    monkeypatch.setattr(httpx.AsyncClient, "send", send)
    result = await router.discover_models(ADMIN, router.ModelConnection(provider="anthropic", api_key="native-secret"))
    assert requests[1].url.params["after_id"] == "first"
    assert [m["id"] for m in result["models"]] == ["first", "second"]


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [{}, {"data": "bad"}, [], {"data": [{"id": "x"}], "has_more": True}])
async def test_malformed_native_catalog_fails_without_writing(setup, monkeypatch, payload):
    async def send(client, request, **kwargs):
        return httpx.Response(200, request=request, json=payload)

    monkeypatch.setattr(httpx.AsyncClient, "send", send)
    with pytest.raises(HTTPException):
        await router.discover_models(ADMIN, router.ModelConnection(provider="anthropic", api_key="test"))
    assert not setup.path.exists()


@pytest.mark.asyncio
async def test_catalog_limits_and_cancellation(setup, monkeypatch):
    from app.gateway import model_discovery as discovery

    monkeypatch.setattr(discovery, "MAX_MODELS", 2)

    async def send(client, request, **kwargs):
        return httpx.Response(200, request=request, json={"data": [{"id": "a"}, {"id": "b"}, {"id": "c"}]})

    monkeypatch.setattr(httpx.AsyncClient, "send", send)
    result = await router.discover_models(ADMIN, connection())
    assert len(result["models"]) == 2 and result["truncated"]
    monkeypatch.setattr(discovery, "MAX_BYTES", 5)
    with pytest.raises(HTTPException) as exc:
        await router.discover_models(ADMIN, connection())
    assert exc.value.detail["code"] == "response_limit"

    async def cancelled(*args, **kwargs):
        raise asyncio.CancelledError

    monkeypatch.setattr(httpx.AsyncClient, "send", cancelled)
    with pytest.raises(asyncio.CancelledError):
        await router.discover_models(ADMIN, connection())
    assert not setup.path.exists()


@pytest.mark.asyncio
async def test_import_reuses_disabled_record_without_enabling_or_overwriting(setup, monkeypatch):
    old = setup.save(ManagedModel(provider="openai", model="old", api_key="catalog-secret", enabled=False, display_name="Keep"), expected_revision=None)

    async def forbidden(*args, **kwargs):
        pytest.fail("Existing imports must not call the provider")

    monkeypatch.setattr(router, "test_model", forbidden)
    result = await router.import_model(ADMIN, router.ImportModelRequest(connection=connection(), model="old"))
    assert result["status"] == "existing"
    assert result["model"]["revision"] == old.revision
    assert not result["model"]["enabled"]
    assert result["model"]["display_name"] == "Keep"


def test_provider_projection_is_metadata_not_an_sdk_argument():
    from app.gateway.routers.models import _model_response
    from deerflow.models.factory import create_chat_model

    profile = ManagedModel(provider="openai", model="gpt-6.1-sol", api_key="secret")
    config = profile.runtime_config()
    assert _model_response(config).provider == "OpenAI"
    assert "_managed_provider" not in config.model_dump()
    app = AppConfig.model_validate({"models": [config], "sandbox": {"use": "test"}})
    client = create_chat_model(config.name, app_config=app, attach_tracing=False)
    assert "_managed_provider" not in client.model_kwargs


@pytest.mark.asyncio
@pytest.mark.parametrize("rotate", [False, True])
@pytest.mark.parametrize("concurrent_import", [False, True])
async def test_import_rechecks_saved_connection_after_probe(setup, monkeypatch, rotate, concurrent_import):
    source = setup.save(ManagedModel(provider="openai", model="source", api_key="old-key"), expected_revision=None)
    before = setup.path.read_bytes()

    async def probe(request, body):
        nonlocal before
        assert body.config.api_key == SecretStr("old-key")
        if concurrent_import:
            setup.save(body.config, expected_revision=None)
        if rotate:
            setup.save(source.model_copy(update={"api_key": SecretStr("new-key")}), expected_revision=source.revision)
            before = setup.path.read_bytes()
        return {"ok": True, "message": "success"}

    monkeypatch.setattr(router, "test_model", probe)
    body = router.ImportModelRequest(connection=router.ModelConnection(provider="openai", saved_model_name=source.name, expected_revision=source.revision), model="new")
    if rotate:
        with pytest.raises(HTTPException) as exc:
            await router.import_model(ADMIN, body)
        assert exc.value.status_code == 409
        assert setup.path.read_bytes() == before
        assert len(setup.list()) == (2 if concurrent_import else 1)
    else:
        assert (await router.import_model(ADMIN, body))["status"] == "saved"
        assert len(setup.list()) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("encoding", ["gzip", "br", "deflate", "identity, gzip"])
async def test_compressed_catalog_is_rejected_before_reading(setup, monkeypatch, encoding):
    reads = []
    encodings = []

    class CompressedStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            import gzip

            reads.append(True)
            yield gzip.compress(b" " * (8 * 1024 * 1024))

    async def send(client, request, **kwargs):
        encodings.append(request.headers["accept-encoding"])
        return httpx.Response(200, request=request, headers={"content-encoding": encoding}, stream=CompressedStream())

    monkeypatch.setattr(httpx.AsyncClient, "send", send)
    with pytest.raises(HTTPException) as exc:
        await router.discover_models(ADMIN, connection())
    assert exc.value.detail["code"] == "discovery_failed"
    assert not reads
    assert encodings == ["identity"]
    assert not setup.path.exists()


def test_import_source_must_still_exist_before_deduplication(setup):
    profile = ManagedModel(provider="openai", model="existing", api_key="key")
    setup.save(profile, expected_revision=None)
    before = setup.path.read_bytes()
    with pytest.raises(FileExistsError):
        setup.save(profile, expected_revision=None, deduplicate=True, expected_source=("deleted-source", "old-revision"))
    assert setup.path.read_bytes() == before
