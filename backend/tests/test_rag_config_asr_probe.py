"""The ASR probe (spec 2026-09-28 §3 D7).

D7 asks one question about a *service* before anything is saved: will this
endpoint give us segment-level timestamps we can actually project onto shot
cards? The answer needs a fixture with known speech and a known pause, and two
independent criteria, because "the response has segments" is not enough — a
backend that only received text can synthesise segments by pro-rating the
duration over character counts (spec §5.2).

Nothing here touches the network: the service client's transport is stubbed, so
these tests pin the request shape, the verdict logic, and the degradation
taxonomy without a key or an endpoint.
"""

from __future__ import annotations

import json
import wave
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
import yaml
from _router_auth_helpers import make_authed_test_app
from fastapi.testclient import TestClient

from app.gateway.auth.models import User
from app.gateway.routers import rag_config as rag_config_router
from app.gateway.routers.rag_config import ASR_PROBE_FIXTURE_PATH
from deerflow.config.app_config import reset_app_config

SANDBOX = {"use": "deerflow.sandbox.local:LocalSandboxProvider"}
YAML_RAG = {"qdrant_url": "http://qdrant:6333", "embedding_model": "yaml-embedding", "rerank_model": "yaml-rerank", "video": {"enabled": False, "asr_model": "yaml-asr"}}

_PROBE = "/api/rag/config/probe-asr"
_FAKE_KEY = "sk-probe-must-never-come-back"
_ADDRESS = "https://dashscope.aliyuncs.com"

#: 夹具的真值（Task 0 现造、本文件钉住）：句 A 快读 → 1.32–3.22 s 静音 → 句 B 慢读。
_FIXTURE_SECONDS = 8.965
_FIXTURE_PAUSE_SECONDS = (1.32, 3.22)


@pytest.fixture
def config_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    (tmp_path / "config.yaml").write_text(yaml.safe_dump({"sandbox": SANDBOX, "models": [], "rag": YAML_RAG}), encoding="utf-8")
    (tmp_path / "models_config.json").write_text(json.dumps({"models": []}), encoding="utf-8")
    (tmp_path / "extensions_config.json").write_text(json.dumps({"mcpServers": {}, "skills": {}}), encoding="utf-8")
    (tmp_path / "rag_config.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("DEER_FLOW_CONFIG_PATH", str(tmp_path / "config.yaml"))
    monkeypatch.setenv("DEER_FLOW_MODELS_CONFIG_PATH", str(tmp_path / "models_config.json"))
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(tmp_path / "extensions_config.json"))
    monkeypatch.setenv("DEER_FLOW_RAG_CONFIG_PATH", str(tmp_path / "rag_config.json"))
    for name in ("DASHSCOPE_ASR_API_KEY", "RAG_ASR_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    reset_app_config()
    yield tmp_path
    reset_app_config()


def _client(*, system_role: str = "admin") -> TestClient:
    app = make_authed_test_app(
        user_factory=lambda: User(
            email=f"{system_role}-asr-probe@example.com",
            password_hash="x",
            system_role=system_role,
            id=uuid4(),
        )
    )
    app.include_router(rag_config_router.router)
    return TestClient(app)


def _stub(monkeypatch: pytest.MonkeyPatch, *, json_body: dict | None = None, status: int = 200, exc: Exception | None = None) -> list[httpx.Request]:
    """Answer the service call locally; record what the probe asked for."""
    recorded: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        if exc is not None:
            raise exc
        return httpx.Response(status, json=json_body or {})

    real_client = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: real_client(transport=httpx.MockTransport(handler)))
    return recorded


def _probe(client: TestClient, **overrides: object) -> httpx.Response:
    body = {"asr_provider": "dashscope", "asr_model": "qwen-audio-3.1-asr-flash", "asr_base_url": _ADDRESS, "asr_api_key": _FAKE_KEY, **overrides}
    return client.post(_PROBE, json=body)


def _sentences(*spans: tuple[int, int, str]) -> dict:
    return {"output": {"sentences": [{"begin_time": s, "end_time": e, "text": t} for s, e, t in spans]}}


#: 真分段：A 快读（184 ms/字符）、B 慢读（395 ms/字符），边界落在夹具的静音里。
_REAL = _sentences((0, 1840, "语音识别探针第一句"), (3120, 9040, "第二句慢一些用来检查时间戳"))
#: 合成段（一）：按字符数把**整段时长**等比摊开——边界落在静音之外（funasr-server 那类）。
_SYNTHETIC = _sentences((0, 3586, "语音识别探针第一句"), (3586, 8965, "第二句慢一些用来检查时间戳"))
#: 合成段（二）：只按**语音时长**摊开——边界恰好落进静音（蒙混过第一条判据），
#: 但两段的 ms/字符 只差 1.3×（真分段是 ≈2×）⇒ 必须由"离散度"那条判据拦下。
_EQUAL_RATES = _sentences((0, 3040, "语音识别探针第一句"), (3040, 8965, "第二句慢一些用来检查时间戳"))


# ── the fixture itself ────────────────────────────────────────────────────


def test_the_fixture_is_the_committed_clip():
    """夹具是探针的判据来源，所以它的身份（时长 / 采样率 / 静音窗）也钉在这里。"""
    assert ASR_PROBE_FIXTURE_PATH.exists(), "ASR 探针夹具必须入库（否则 wheel/镜像里没有它）"
    with wave.open(str(ASR_PROBE_FIXTURE_PATH), "rb") as handle:
        assert handle.getnchannels() == 1
        assert handle.getframerate() == 16000
        assert handle.getsampwidth() == 2
        seconds = handle.getnframes() / handle.getframerate()

    assert seconds == pytest.approx(_FIXTURE_SECONDS, abs=0.05)


def test_the_fixture_has_the_pause_the_verdict_relies_on():
    """没有已知静音，"边界必须落在静音处"这条判据就无从谈起。"""
    import numpy as np

    with wave.open(str(ASR_PROBE_FIXTURE_PATH), "rb") as handle:
        rate = handle.getframerate()
        data = np.frombuffer(handle.readframes(handle.getnframes()), dtype=np.int16)

    step = int(rate * 0.02)
    frames = len(data) // step
    rms = np.sqrt((data[: frames * step].reshape(frames, step).astype(np.float64) ** 2).mean(axis=1))

    def window(start: float, end: float) -> float:
        return float(rms[int(start / 0.02) : int(end / 0.02)].max())

    assert window(*_FIXTURE_PAUSE_SECONDS) < 60  # 设计的静音
    assert window(0.4, 1.2) > 500  # 句 A
    assert window(4.0, 4.8) > 500  # 句 B


# ── admin gate / request validation ───────────────────────────────────────


def test_the_probe_requires_admin(config_env: Path):
    with _client(system_role="user") as client:
        assert _probe(client).status_code == 403


def test_an_unknown_provider_is_refused(config_env: Path):
    with _client() as client:
        response = _probe(client, asr_provider="qwen-audio")

    assert response.status_code == 422


def test_an_in_process_engine_has_nothing_to_probe(config_env: Path):
    """D7：探针只挂服务档那几格——进程内引擎没有端点可测。"""
    with _client() as client:
        response = _probe(client, asr_provider="funasr", asr_model="paraformer-zh", asr_base_url=None)

    assert response.status_code == 422
    assert "服务档" in response.json()["detail"]


def test_a_service_row_without_an_address_is_refused(config_env: Path):
    with _client() as client:
        response = _probe(client, asr_base_url=None)

    assert response.status_code == 422
    assert "asr_base_url" in response.json()["detail"]


# ── the four states ───────────────────────────────────────────────────────


def test_a_real_transcript_answers_ok(config_env: Path, monkeypatch: pytest.MonkeyPatch):
    recorded = _stub(monkeypatch, json_body=_REAL)

    with _client() as client:
        response = _probe(client)

    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "ok"
    # 探针发的是夹具本身，且请求形状与运行期一致（format + 分段开关）。
    assert recorded[0].headers["authorization"] == f"Bearer {_FAKE_KEY}"
    payload = json.loads(recorded[0].content)
    assert payload["parameters"]["format"] == "wav"
    assert payload["parameters"]["speaker_diarization_enabled"] is True


def test_synthetic_segments_are_not_an_ok(config_env: Path, monkeypatch: pytest.MonkeyPatch):
    """§5.2 的合成段：按字数等比摊开 ⇒ 边界不在真语音处——卡片上更难发现，探针必须识破。"""
    _stub(monkeypatch, json_body=_SYNTHETIC)

    with _client() as client:
        body = _probe(client).json()

    assert body["status"] == "no_timestamps"


def test_equal_rates_are_not_an_ok(config_env: Path, monkeypatch: pytest.MonkeyPatch):
    """第二条判据单独钉住：边界蒙混进静音了，但段间 ms/字符 太接近（等比摊开的特征）。"""
    _stub(monkeypatch, json_body=_EQUAL_RATES)

    with _client() as client:
        body = _probe(client).json()

    assert body["status"] == "no_timestamps"
    assert "等比" in body["detail"] or "等分" in body["detail"]


def test_a_single_whole_row_is_not_an_ok(config_env: Path, monkeypatch: pytest.MonkeyPatch):
    _stub(monkeypatch, json_body=_sentences((0, 8965, "整段")))

    with _client() as client:
        body = _probe(client).json()

    assert body["status"] == "no_timestamps"


def test_boundaries_outside_the_pause_are_not_an_ok(config_env: Path, monkeypatch: pytest.MonkeyPatch):
    """段数够了但边界不在静音处（例如单位错、或时间轴被整体挪过）⇒ 落不到镜头卡上。"""
    _stub(monkeypatch, json_body=_sentences((0, 400, "语音识别探针第一句"), (400, 8965, "第二句慢一些用来检查时间戳")))

    with _client() as client:
        body = _probe(client).json()

    assert body["status"] == "no_timestamps"


def test_a_refused_key_is_refused(config_env: Path, monkeypatch: pytest.MonkeyPatch):
    _stub(monkeypatch, json_body={"code": "InvalidApiKey", "message": "API-key is blocked"}, status=401)

    with _client() as client:
        body = _probe(client).json()

    assert body["status"] == "refused"


def test_an_unreachable_endpoint_is_unreachable(config_env: Path, monkeypatch: pytest.MonkeyPatch):
    _stub(monkeypatch, exc=httpx.ConnectError("no route"))

    with _client() as client:
        body = _probe(client).json()

    assert body["status"] == "unreachable"


# ── the probe writes nothing and never echoes the key ─────────────────────


def test_the_probe_persists_nothing_and_never_echoes_the_key(config_env: Path, monkeypatch: pytest.MonkeyPatch):
    _stub(monkeypatch, json_body=_REAL)

    with _client() as client:
        response = _probe(client)

    assert _FAKE_KEY not in response.text
    assert json.loads((config_env / "rag_config.json").read_text(encoding="utf-8")) == {}
