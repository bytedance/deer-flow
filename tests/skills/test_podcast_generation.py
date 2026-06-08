import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from skill_loader import FakeResp, load  # noqa: E402

pod = load("podcast-generation")


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for k in ["VOLCENGINE_TTS_APPID", "VOLCENGINE_TTS_ACCESS_TOKEN", "VOLCENGINE_TTS_CLUSTER",
              "MINIMAX_API_KEY", "PODCAST_GENERATION_PROVIDER", "MINIMAX_API_HOST",
              "MINIMAX_TTS_MODEL", "MINIMAX_TTS_VOICE_MALE", "MINIMAX_TTS_VOICE_FEMALE"]:
        monkeypatch.delenv(k, raising=False)


def test_resolve_prefers_volcengine(monkeypatch):
    monkeypatch.setenv("VOLCENGINE_TTS_APPID", "a")
    monkeypatch.setenv("VOLCENGINE_TTS_ACCESS_TOKEN", "t")
    assert pod._resolve_tts_provider() == "volcengine"


def test_resolve_falls_back_to_minimax(monkeypatch):
    monkeypatch.setenv("MINIMAX_API_KEY", "m")
    assert pod._resolve_tts_provider() == "minimax"


def test_resolve_override(monkeypatch):
    monkeypatch.setenv("VOLCENGINE_TTS_APPID", "a")
    monkeypatch.setenv("VOLCENGINE_TTS_ACCESS_TOKEN", "t")
    monkeypatch.setenv("PODCAST_GENERATION_PROVIDER", "minimax")
    assert pod._resolve_tts_provider() == "minimax"


def test_resolve_unknown_raises(monkeypatch):
    monkeypatch.setenv("MINIMAX_API_KEY", "m")
    monkeypatch.setenv("PODCAST_GENERATION_PROVIDER", "openai")
    with pytest.raises(ValueError):
        pod._resolve_tts_provider()


def test_minimax_tts_decodes_hex(monkeypatch):
    monkeypatch.setenv("MINIMAX_API_KEY", "m")
    captured = {}

    def fake_post(url, headers=None, json=None, **kw):
        captured["url"] = url
        captured["json"] = json
        return FakeResp({"data": {"audio": b"audiobytes".hex(), "status": 2},
                         "base_resp": {"status_code": 0}})

    monkeypatch.setattr(pod.requests, "post", fake_post)
    out = pod.text_to_speech_minimax("hello", "male-qn-qingse")
    assert out == b"audiobytes"
    assert captured["url"].endswith("/v1/t2a_v2")
    assert captured["json"]["voice_setting"]["voice_id"] == "male-qn-qingse"
    assert captured["json"]["output_format"] == "hex"


def test_process_line_minimax_voice_mapping(monkeypatch):
    monkeypatch.setenv("MINIMAX_API_KEY", "m")
    seen = {}

    def fake_tts(text, voice_id):
        seen["voice_id"] = voice_id
        return b"x"

    monkeypatch.setattr(pod, "text_to_speech_minimax", fake_tts)
    line = pod.ScriptLine(speaker="female", paragraph="hi")
    idx, audio = pod._process_line((0, line, 1, "minimax"))
    assert audio == b"x"
    assert seen["voice_id"] == "female-tianmei"


def test_generate_podcast_minimax_end_to_end(monkeypatch, tmp_path):
    monkeypatch.setenv("MINIMAX_API_KEY", "m")

    def fake_post(url, headers=None, json=None, **kw):
        return FakeResp({"data": {"audio": b"chunk".hex(), "status": 2},
                         "base_resp": {"status_code": 0}})

    monkeypatch.setattr(pod.requests, "post", fake_post)
    script = tmp_path / "s.json"
    script.write_text(
        '{"title":"T","locale":"en","lines":[{"speaker":"male","paragraph":"a"},'
        '{"speaker":"female","paragraph":"b"}]}',
        encoding="utf-8",
    )
    out = tmp_path / "o.mp3"
    msg = pod.generate_podcast(str(script), str(out), None)
    assert out.read_bytes() == b"chunkchunk"
    assert "Successfully generated podcast" in msg


def test_volcengine_tts_decodes_base64(monkeypatch):
    import base64
    monkeypatch.setenv("VOLCENGINE_TTS_APPID", "a")
    monkeypatch.setenv("VOLCENGINE_TTS_ACCESS_TOKEN", "t")

    def fake_post(url, headers=None, json=None, **kw):
        return FakeResp({"code": 3000, "data": base64.b64encode(b"volcbytes").decode()})

    monkeypatch.setattr(pod.requests, "post", fake_post)
    out = pod.text_to_speech_volcengine("hi", "zh_male_yangguangqingnian_moon_bigtts")
    assert out == b"volcbytes"


def test_volcengine_without_creds_raises(monkeypatch):
    monkeypatch.setenv("PODCAST_GENERATION_PROVIDER", "volcengine")
    script = pod.Script(lines=[pod.ScriptLine("male", "a")])
    with pytest.raises(ValueError):
        pod.tts_node(script)


def test_process_line_minimax_male_and_override(monkeypatch):
    monkeypatch.setenv("MINIMAX_API_KEY", "m")
    seen = []

    def fake_tts(text, voice_id):
        seen.append(voice_id)
        return b"x"

    monkeypatch.setattr(pod, "text_to_speech_minimax", fake_tts)
    male = pod.ScriptLine(speaker="male", paragraph="hi")
    pod._process_line((0, male, 1, "minimax"))
    assert seen[-1] == "male-qn-qingse"
    monkeypatch.setenv("MINIMAX_TTS_VOICE_MALE", "custom-male")
    pod._process_line((0, male, 1, "minimax"))
    assert seen[-1] == "custom-male"
