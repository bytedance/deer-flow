"""Exercise the authenticated route and real HTTPX multipart encoding offline."""

from pathlib import Path
from shutil import copyfile
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError
from starlette.requests import Request

from app.gateway import deps
from app.gateway.auth.models import User
from app.gateway.authz import AuthContext
from app.gateway.deps import get_config
from app.gateway.routers import features, voice_input
from deerflow.config.app_config import AppConfig
from deerflow.config.voice_input_config import VoiceInputConfig


def settings(**overrides):
    return VoiceInputConfig(base_url="https://speech.example/v1", model="stt-test", **overrides)


@pytest.fixture
def upstream(monkeypatch):
    state = SimpleNamespace(requests=[], response=httpx.Response(200, json={"text": "  Spoken task  "}), error=None)

    async def handle(_transport, request):
        await request.aread()
        state.requests.append(request)
        if state.error:
            raise state.error
        return state.response

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", handle)
    return state


def client_for(config, *, authenticated=True, permitted=True, use_config_loader=False):
    app = FastAPI()
    app.include_router(voice_input.router)
    if not use_config_loader:
        app.dependency_overrides[get_config] = lambda: SimpleNamespace(voice_input=config)

    @app.middleware("http")
    async def auth(request, call_next):
        request.state.auth = AuthContext(user=User(email="tester@example.com") if authenticated else None, permissions=["runs:create"] if permitted else [])
        return await call_next(request)

    return TestClient(app)


def test_recording_is_forwarded_as_multipart_using_server_config(upstream):
    with client_for(settings(api_key="synthetic-key", language="zh")) as client:
        response = client.post("/api/voice-input/transcribe?model=untrusted&base_url=https://other.example", content=b"encoded audio", headers={"Content-Type": "audio/webm;codecs=opus"})
    assert response.status_code == 200
    assert response.json() == {"text": "Spoken task"}
    assert len(upstream.requests) == 1
    request = upstream.requests[0]
    assert str(request.url) == "https://speech.example/v1/audio/transcriptions"
    assert request.headers["authorization"] == "Bearer synthetic-key"
    assert request.headers["accept-encoding"] == "identity"
    assert request.headers["content-type"].startswith("multipart/form-data; boundary=")
    for value in (b'name="model"\r\n\r\nstt-test', b'name="language"\r\n\r\nzh', b'name="response_format"\r\n\r\njson', b'filename="recording.webm"', b"Content-Type: audio/webm", b"encoded audio"):
        assert value in request.content
    assert b"untrusted" not in request.content


@pytest.mark.parametrize("mime,extension", [("audio/mp4", "mp4"), ("audio/ogg;codecs=opus", "ogg")])
def test_other_browser_recording_formats_and_no_key(upstream, mime, extension):
    with client_for(settings()) as client:
        assert client.post("/api/voice-input/transcribe", content=b"audio", headers={"Content-Type": mime}).status_code == 200
    assert "authorization" not in upstream.requests[0].headers
    assert f'filename="recording.{extension}"'.encode() in upstream.requests[0].content
    assert b'name="language"' not in upstream.requests[0].content


@pytest.mark.parametrize("authenticated,permitted,status", [(False, False, 401), (True, False, 403)])
def test_permission_required(upstream, authenticated, permitted, status):
    with client_for(settings(), authenticated=authenticated, permitted=permitted) as client:
        response = client.post("/api/voice-input/transcribe", content=b"audio", headers={"Content-Type": "audio/webm"})
    assert response.status_code == status
    assert not upstream.requests


@pytest.mark.parametrize("config,content,mime,status", [(None, b"audio", "audio/webm", 404), (settings(), b"", "audio/webm", 400), (settings(), b"audio", "text/plain", 415), (settings(max_audio_bytes=1024), b"a" * 1025, "audio/webm", 413)])
def test_disabled_invalid_and_oversized_requests_never_contact_provider(upstream, config, content, mime, status):
    with client_for(config) as client:
        response = client.post("/api/voice-input/transcribe", content=content, headers={"Content-Type": mime})
    assert response.status_code == status
    assert not upstream.requests


@pytest.mark.parametrize(
    "provider,status",
    [
        (httpx.Response(401, text="private provider error synthetic-key"), 502),
        (httpx.Response(302, headers={"Location": "https://other.example/secret"}), 502),
        (httpx.Response(200, text="not json synthetic-key"), 502),
        (httpx.Response(200, json=[]), 502),
        (httpx.Response(200, json={"text": 1}), 502),
        (httpx.Response(200, content=rb'{"text":"\ud800"}'), 502),
        (httpx.Response(200, json={"text": " "}), 422),
        (httpx.Response(200, text="x" * (1024 * 1024 + 1)), 502),
    ],
)
def test_provider_failures_are_bounded_and_redacted(upstream, provider, status):
    upstream.response = provider
    with client_for(settings(api_key="synthetic-key")) as client:
        response = client.post("/api/voice-input/transcribe", content=b"audio", headers={"Content-Type": "audio/webm"})
    assert response.status_code == status
    assert len(upstream.requests) == 1
    assert "synthetic-key" not in response.text
    assert "speech.example" not in response.text


def test_invalid_voice_key_is_hidden_in_config_errors(monkeypatch, caplog, upstream):
    secret_marker = "synthetic-invalid-voice-key"
    voice = {"base_url": "https://speech.example/v1", "model": "stt-test", "api_key": f"{secret_marker}\n"}

    with pytest.raises(ValidationError) as direct_error:
        VoiceInputConfig.model_validate(voice)
    assert secret_marker not in str(direct_error.value)

    def load_invalid_config():
        return AppConfig.model_validate({"config_version": 67, "sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"}, "voice_input": voice})

    monkeypatch.setattr(deps, "get_app_config", load_invalid_config)
    with client_for(None, use_config_loader=True) as client:
        response = client.post("/api/voice-input/transcribe", content=b"audio", headers={"Content-Type": "audio/webm"})

    assert response.status_code == 503
    assert "voice_input.api_key" in caplog.text
    assert secret_marker not in caplog.text
    assert not upstream.requests


def test_provider_timeout_is_sanitized(upstream):
    upstream.error = httpx.ReadTimeout("https://speech.example/secret")
    with client_for(settings()) as client:
        response = client.post("/api/voice-input/transcribe", content=b"audio", headers={"Content-Type": "audio/webm"})
    assert response.status_code == 504
    assert "speech.example" not in response.text


@pytest.mark.parametrize("encoding", ["gzip", "br", "identity, gzip"])
def test_encoded_provider_response_is_rejected_before_reading(upstream, encoding):
    class Body(httpx.AsyncByteStream):
        async def __aiter__(self):
            pytest.fail("encoded provider body was read")
            yield b""

        async def aclose(self):
            self.closed = True

    body = Body()
    upstream.response = httpx.Response(200, headers={"Content-Encoding": encoding}, stream=body)
    with client_for(settings()) as client:
        response = client.post("/api/voice-input/transcribe", content=b"audio", headers={"Content-Type": "audio/webm"})
    assert response.status_code == 502
    assert body.closed


@pytest.mark.asyncio
@pytest.mark.parametrize("declared", [None, "1"])
async def test_stream_size_is_enforced_without_trusting_content_length(declared, upstream):
    chunks = iter([b"a" * 800, b"b" * 800])
    headers = [(b"content-type", b"audio/webm")]
    if declared:
        headers.append((b"content-length", declared.encode()))

    async def receive():
        return {"type": "http.request", "body": next(chunks), "more_body": True}

    request = Request({"type": "http", "method": "POST", "headers": headers}, receive)
    request.state.auth = AuthContext(user=User(email="tester@example.com"), permissions=["runs:create"])
    with pytest.raises(HTTPException) as error:
        await voice_input.transcribe_audio(request, config=SimpleNamespace(voice_input=settings(max_audio_bytes=1024)))
    assert error.value.status_code == 413
    assert not upstream.requests


@pytest.mark.asyncio
@pytest.mark.parametrize("authenticated", [False, True])
async def test_auth_precedes_reading_the_audio(authenticated):
    async def receive():
        pytest.fail("unauthorized request body was consumed")

    request = Request({"type": "http", "method": "POST", "headers": [(b"content-type", b"audio/webm")]}, receive)
    request.state.auth = AuthContext(user=User(email="tester@example.com") if authenticated else None)
    with pytest.raises(HTTPException) as error:
        await voice_input.transcribe_audio(request, config=SimpleNamespace(voice_input=settings()))
    assert error.value.status_code == (403 if authenticated else 401)


@pytest.mark.parametrize(
    "override",
    [
        {"base_url": "file:///tmp/model"},
        {"base_url": "https://user:key@speech.example/v1"},
        {"base_url": "https://speech.example/v1?key=secret"},
        {"base_url": " "},
        {"model": " "},
        {"api_key": ""},
        {"max_audio_bytes": True},
        {"timeout_seconds": 121},
    ],
)
def test_invalid_config_is_rejected(override):
    with pytest.raises(ValidationError):
        VoiceInputConfig.model_validate({"base_url": "https://speech.example/v1", "model": "stt-test", **override})


def test_unconfigured_and_null_sections_disable_voice_input():
    base = {"sandbox": {"use": "deerflow.sandbox.local:LocalSandboxProvider"}}
    assert AppConfig.model_validate(base).voice_input is None
    assert AppConfig.model_validate({**base, "voice_input": None}).voice_input is None
    with pytest.raises(ValidationError):
        AppConfig.model_validate({**base, "voice_input": {}})


def test_existing_config_warns_about_the_voice_input_schema(tmp_path, caplog):
    example = Path(__file__).resolve().parents[2] / "config.example.yaml"
    copyfile(example, tmp_path / example.name)
    path = tmp_path / "config.yaml"
    path.write_text("config_version: 66\nsandbox:\n  use: deerflow.sandbox.local:LocalSandboxProvider\n", encoding="utf-8")
    assert AppConfig.from_file(str(path)).voice_input is None
    assert "Your config.yaml (version 66) is outdated" in caplog.text


def test_config_resolves_environment_once_and_does_not_expose_secrets(monkeypatch, tmp_path):
    monkeypatch.setenv("TEST_VOICE_KEY", "$literal-dollar-key")
    path = tmp_path / "config.yaml"
    path.write_text("config_version: 66\nsandbox:\n  use: deerflow.sandbox.local:LocalSandboxProvider\nvoice_input:\n  base_url: http://localhost:9000/v1/\n  model: stt-test\n  api_key: $TEST_VOICE_KEY\n")
    config = AppConfig.from_file(str(path))
    assert config.voice_input.api_key.get_secret_value() == "$literal-dollar-key"
    assert config.voice_input.base_url == "http://localhost:9000/v1"
    assert "literal-dollar-key" not in repr(config.voice_input)
    app = FastAPI()
    app.include_router(features.router)
    app.dependency_overrides[get_config] = lambda: config
    with TestClient(app) as client:
        response = client.get("/api/features")
        assert response.status_code == 200
        assert response.json()["voice_input"] == {"enabled": True, "max_audio_bytes": 10485760, "max_duration_seconds": 120}
        assert "literal-dollar-key" not in response.text
        assert "localhost:9000" not in response.text
        assert "stt-test" not in response.text
        config.voice_input = None
        assert client.get("/api/features").json()["voice_input"]["enabled"] is False


@pytest.mark.parametrize("field,value", [("max_audio_bytes", 4096), ("max_duration_seconds", 30), ("timeout_seconds", 15)])
def test_numeric_settings_accept_resolved_environment_strings_and_reject_booleans(monkeypatch, field, value):
    monkeypatch.setenv("TEST_VOICE_LIMIT", str(value))
    raw = AppConfig.resolve_env_variables({"base_url": "https://speech.example/v1", "model": "stt", field: "$TEST_VOICE_LIMIT"})
    assert getattr(VoiceInputConfig.model_validate(raw), field) == value
    with pytest.raises(ValidationError):
        VoiceInputConfig.model_validate({**raw, field: True})
