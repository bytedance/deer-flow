import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from skill_loader import FakeResp, load  # noqa: E402

vid = load("video-generation")


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for k in ["GEMINI_API_KEY", "MINIMAX_API_KEY", "VIDEO_GENERATION_PROVIDER",
              "MINIMAX_API_HOST", "MINIMAX_VIDEO_MODEL"]:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(vid.time, "sleep", lambda *_: None)


def test_resolve_prefers_gemini():
    assert vid._resolve_provider("VIDEO_GENERATION_PROVIDER", "gemini", True) == "gemini"


def test_resolve_falls_back_to_minimax(monkeypatch):
    monkeypatch.setenv("MINIMAX_API_KEY", "m")
    assert vid._resolve_provider("VIDEO_GENERATION_PROVIDER", "gemini", False) == "minimax"


def test_resolve_override(monkeypatch):
    monkeypatch.setenv("VIDEO_GENERATION_PROVIDER", "minimax")
    assert vid._resolve_provider("VIDEO_GENERATION_PROVIDER", "gemini", True) == "minimax"


def test_unknown_provider_raises(monkeypatch, tmp_path):
    monkeypatch.setenv("VIDEO_GENERATION_PROVIDER", "openai")
    monkeypatch.setenv("GEMINI_API_KEY", "g")
    pf = tmp_path / "p.json"
    pf.write_text("x", encoding="utf-8")
    with pytest.raises(ValueError):
        vid.generate_video(str(pf), [], str(tmp_path / "v.mp4"), "16:9")


def test_minimax_full_flow(monkeypatch, tmp_path):
    monkeypatch.setenv("MINIMAX_API_KEY", "m")
    posts = {}

    def fake_post(url, headers=None, json=None, **kw):
        posts["url"] = url
        posts["json"] = json
        return FakeResp({"task_id": "T1", "base_resp": {"status_code": 0}})

    def fake_get(url, headers=None, params=None, **kw):
        if url.endswith("/v1/query/video_generation"):
            assert params["task_id"] == "T1"
            return FakeResp({"status": "Success", "file_id": "F1",
                             "base_resp": {"status_code": 0}})
        if url.endswith("/v1/files/retrieve"):
            assert params["file_id"] == "F1"
            return FakeResp({"file": {"download_url": "https://dl/v.mp4"},
                             "base_resp": {"status_code": 0}})
        return FakeResp(content=b"MP4DATA")  # the actual download

    monkeypatch.setattr(vid.requests, "post", fake_post)
    monkeypatch.setattr(vid.requests, "get", fake_get)

    out = tmp_path / "v.mp4"
    pf = tmp_path / "p.json"
    pf.write_text("a cat runs", encoding="utf-8")
    msg = vid.generate_video(str(pf), [], str(out), "16:9")

    assert out.read_bytes() == b"MP4DATA"
    assert posts["url"].endswith("/v1/video_generation")
    assert posts["json"]["model"] == "MiniMax-Hailuo-2.3"
    assert "successfully" in msg.lower()


def test_minimax_reference_first_frame(monkeypatch, tmp_path):
    monkeypatch.setenv("MINIMAX_API_KEY", "m")
    posts = {}

    def fake_post(url, headers=None, json=None, **kw):
        posts["json"] = json
        return FakeResp({"task_id": "T1", "base_resp": {"status_code": 0}})

    def fake_get(url, headers=None, params=None, **kw):
        if url.endswith("/v1/query/video_generation"):
            return FakeResp({"status": "Success", "file_id": "F1", "base_resp": {"status_code": 0}})
        if url.endswith("/v1/files/retrieve"):
            return FakeResp({"file": {"download_url": "https://dl/v.mp4"}, "base_resp": {"status_code": 0}})
        return FakeResp(content=b"X")

    monkeypatch.setattr(vid.requests, "post", fake_post)
    monkeypatch.setattr(vid.requests, "get", fake_get)
    ref = tmp_path / "f.jpg"
    ref.write_bytes(b"\xff\xd8img")
    pf = tmp_path / "p.json"
    pf.write_text("x", encoding="utf-8")
    vid.generate_video(str(pf), [str(ref)], str(tmp_path / "v.mp4"), "16:9")
    assert posts["json"]["first_frame_image"].startswith("data:image/jpeg;base64,")


def test_minimax_task_fail(monkeypatch, tmp_path):
    monkeypatch.setenv("MINIMAX_API_KEY", "m")

    def fake_post(url, headers=None, json=None, **kw):
        return FakeResp({"task_id": "T1", "base_resp": {"status_code": 0}})

    def fake_get(url, headers=None, params=None, **kw):
        return FakeResp({"status": "Fail", "base_resp": {"status_code": 1027, "status_msg": "blocked"}})

    monkeypatch.setattr(vid.requests, "post", fake_post)
    monkeypatch.setattr(vid.requests, "get", fake_get)
    pf = tmp_path / "p.json"
    pf.write_text("x", encoding="utf-8")
    with pytest.raises(Exception):
        vid.generate_video(str(pf), [], str(tmp_path / "v.mp4"), "16:9")
