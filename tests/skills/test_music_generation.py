import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from skill_loader import FakeResp, load  # noqa: E402

mus = load("music-generation")

# Synthetic payloads exercise signatures, not complete audio decoding.
_ID3_AUDIO = b"ID3\x04\x00\x00\x00\x00\x00\x00\xff\xfb\x90\x64synthetic MP3 bytes"


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for k in ["MINIMAX_API_KEY", "MINIMAX_API_HOST", "MINIMAX_MUSIC_MODEL"]:
        monkeypatch.delenv(k, raising=False)


def _post_ok(captured):
    def fake_post(url, headers=None, json=None, **kw):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        return FakeResp(
            {
                "data": {"audio": _ID3_AUDIO.hex(), "status": 2},
                "base_resp": {"status_code": 0},
            }
        )

    return fake_post


def test_with_lyrics_payload_and_writes(monkeypatch, tmp_path):
    monkeypatch.setenv("MINIMAX_API_KEY", "m")
    captured = {}
    monkeypatch.setattr(mus.requests, "post", _post_ok(captured))
    spec = tmp_path / "s.json"
    spec.write_text(
        '{"title":"X","prompt":"pop, happy","lyrics":"[verse]\\nla la"}',
        encoding="utf-8",
    )
    out = tmp_path / "o.mp3"
    msg = mus.generate_music(str(spec), str(out))
    assert out.read_bytes() == _ID3_AUDIO
    assert captured["url"].endswith("/v1/music_generation")
    assert captured["headers"]["Authorization"] == "Bearer m"
    assert captured["json"]["model"] == "music-2.6-free"
    assert captured["json"]["lyrics"] == "[verse]\nla la"
    assert captured["json"]["output_format"] == "hex"
    assert "Successfully generated music" in msg


def test_instrumental_sets_flag(monkeypatch, tmp_path):
    monkeypatch.setenv("MINIMAX_API_KEY", "m")
    captured = {}
    monkeypatch.setattr(mus.requests, "post", _post_ok(captured))
    spec = tmp_path / "s.json"
    spec.write_text('{"prompt":"lofi beats","is_instrumental":true}', encoding="utf-8")
    mus.generate_music(str(spec), str(tmp_path / "o.mp3"))
    assert captured["json"]["is_instrumental"] is True
    assert "lyrics" not in captured["json"]
    assert "lyrics_optimizer" not in captured["json"]


@pytest.mark.parametrize("fields", [{}, {"is_instrumental": False}])
def test_no_lyrics_uses_optimizer(monkeypatch, tmp_path, fields):
    monkeypatch.setenv("MINIMAX_API_KEY", "m")
    captured = {}
    monkeypatch.setattr(mus.requests, "post", _post_ok(captured))
    spec = tmp_path / "s.json"
    spec.write_text(json.dumps({"prompt": "sad ballad", **fields}), encoding="utf-8")
    mus.generate_music(str(spec), str(tmp_path / "o.mp3"))
    assert captured["json"]["lyrics_optimizer"] is True
    assert "lyrics" not in captured["json"]


def test_model_override(monkeypatch, tmp_path):
    monkeypatch.setenv("MINIMAX_API_KEY", "m")
    monkeypatch.setenv("MINIMAX_MUSIC_MODEL", "music-2.6")
    captured = {}
    monkeypatch.setattr(mus.requests, "post", _post_ok(captured))
    spec = tmp_path / "s.json"
    spec.write_text('{"prompt":"jazz","lyrics":"[verse]\\nhi"}', encoding="utf-8")
    mus.generate_music(str(spec), str(tmp_path / "o.mp3"))
    assert captured["json"]["model"] == "music-2.6"


def test_raises_on_base_resp_error(monkeypatch, tmp_path):
    monkeypatch.setenv("MINIMAX_API_KEY", "m")

    def fake_post(url, headers=None, json=None, **kw):
        return FakeResp(
            {"base_resp": {"status_code": 1008, "status_msg": "no balance"}}
        )

    monkeypatch.setattr(mus.requests, "post", fake_post)
    spec = tmp_path / "s.json"
    spec.write_text('{"prompt":"x","lyrics":"[verse]\\ny"}', encoding="utf-8")
    with pytest.raises(Exception) as e:
        mus.generate_music(str(spec), str(tmp_path / "o.mp3"))
    assert "1008" in str(e.value)


def test_missing_api_key_returns_message(monkeypatch, tmp_path):
    spec = tmp_path / "s.json"
    spec.write_text('{"prompt":"x"}', encoding="utf-8")
    msg = mus.generate_music(str(spec), str(tmp_path / "o.mp3"))
    assert "MINIMAX_API_KEY" in msg


def test_raises_on_missing_audio_data(monkeypatch, tmp_path):
    monkeypatch.setenv("MINIMAX_API_KEY", "m")

    def fake_post(url, headers=None, json=None, **kw):
        return FakeResp({"base_resp": {"status_code": 0}})  # no "data" key

    monkeypatch.setattr(mus.requests, "post", fake_post)
    spec = tmp_path / "s.json"
    spec.write_text('{"prompt":"x"}', encoding="utf-8")
    with pytest.raises(Exception, match="no audio data"):
        mus.generate_music(str(spec), str(tmp_path / "o.mp3"))


@pytest.mark.parametrize(
    ("fields", "error_type", "field"),
    [
        ({"title": "X", "lyrics": "la la"}, ValueError, "prompt"),
        (
            {"prompt": "ballad", "is_instrumental": "false"},
            TypeError,
            "is_instrumental",
        ),
        ({"prompt": "ballad", "is_instrumental": 1}, TypeError, "is_instrumental"),
        ({"prompt": "ballad", "is_instrumental": None}, TypeError, "is_instrumental"),
    ],
)
def test_invalid_spec_raises_before_request(
    monkeypatch, tmp_path, fields, error_type, field
):
    monkeypatch.setenv("MINIMAX_API_KEY", "m")

    def fake_post(url, headers=None, json=None, **kw):  # pragma: no cover
        raise AssertionError("must not call the API for an invalid spec")

    monkeypatch.setattr(mus.requests, "post", fake_post)
    spec = tmp_path / "s.json"
    spec.write_text(json.dumps(fields), encoding="utf-8")
    with pytest.raises(error_type, match=field):
        mus.generate_music(str(spec), str(tmp_path / "o.mp3"))


@pytest.mark.parametrize("api_key", ["test-key", ""], ids=["configured", "missing"])
def test_cli_rejects_invalid_instrumental_flag(monkeypatch, tmp_path, api_key):
    monkeypatch.setenv("MINIMAX_API_KEY", api_key)
    monkeypatch.setenv("PYTHONPATH", str(tmp_path))
    (tmp_path / "requests.py").write_text(
        "def post(*args, **kwargs):\n"
        "    raise AssertionError('must not call the API for an invalid spec')\n",
        encoding="utf-8",
    )
    spec = tmp_path / "spec.json"
    spec.write_text('{"prompt":"ballad","is_instrumental":"false"}', encoding="utf-8")
    out = tmp_path / "song.mp3"
    out.write_bytes(_ID3_AUDIO)

    result = subprocess.run(
        [
            sys.executable,
            mus.__file__,
            "--prompt-file",
            str(spec),
            "--output-file",
            str(out),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )

    assert result.returncode == 1, (result.stdout, result.stderr)
    assert result.stdout == ""
    assert "`is_instrumental` must be a JSON boolean" in result.stderr
    assert out.read_bytes() == _ID3_AUDIO


def test_empty_lyrics_falls_back_to_optimizer(monkeypatch, tmp_path):
    monkeypatch.setenv("MINIMAX_API_KEY", "m")
    captured = {}
    monkeypatch.setattr(mus.requests, "post", _post_ok(captured))
    spec = tmp_path / "s.json"
    spec.write_text('{"prompt":"x","lyrics":""}', encoding="utf-8")
    mus.generate_music(str(spec), str(tmp_path / "o.mp3"))
    assert captured["json"]["lyrics_optimizer"] is True
    assert "lyrics" not in captured["json"]


@pytest.mark.parametrize(
    "audio_hex",
    [
        pytest.param("not-hex", id="invalid-hex"),
        pytest.param("0", id="odd-length-hex"),
        pytest.param(" \t\n", id="empty-bytes"),
        pytest.param(["61"], id="non-string"),
        pytest.param(b"<html>provider failure</html>".hex(), id="html"),
        pytest.param(b'{"error":"provider failed"}'.hex(), id="json"),
        pytest.param(b"arbitrary bytes".hex(), id="non-audio"),
        pytest.param(b"ID3".hex(), id="truncated-id3"),
        pytest.param(b"\xff\xfb".hex(), id="truncated-frame"),
        pytest.param(b"\xff\x00\x90\x64".hex(), id="invalid-sync"),
    ],
)
@pytest.mark.parametrize("existing", [False, True])
def test_invalid_audio_does_not_touch_output(
    monkeypatch, tmp_path, audio_hex, existing
):
    monkeypatch.setenv("MINIMAX_API_KEY", "m")
    monkeypatch.setattr(
        mus.requests,
        "post",
        lambda *args, **kwargs: FakeResp(
            {"base_resp": {"status_code": 0}, "data": {"audio": audio_hex}}
        ),
    )
    spec = tmp_path / "s.json"
    spec.write_text('{"prompt":"jazz"}', encoding="utf-8")
    out = tmp_path / "new-directory" / "song.mp3"
    if existing:
        out.parent.mkdir()
        out.write_bytes(b"previous song")

    with pytest.raises((ValueError, TypeError)):
        mus.generate_music(str(spec), str(out))

    if existing:
        assert out.read_bytes() == b"previous song"
    else:
        assert not out.exists()
        assert not out.parent.exists()


@pytest.mark.parametrize(
    "audio",
    [
        _ID3_AUDIO,
        b"\xff\xfb\x90\x64test",
        b"\xff\xf3\x80\x64test",
        b"\xff\xe3\x80\x64test",
    ],
    ids=["id3", "mpeg-1", "mpeg-2", "mpeg-2.5"],
)
@pytest.mark.parametrize("existing", [False, True])
def test_valid_spaced_hex_replaces_output(monkeypatch, tmp_path, audio, existing):
    monkeypatch.setenv("MINIMAX_API_KEY", "m")
    monkeypatch.setattr(
        mus.requests,
        "post",
        lambda *args, **kwargs: FakeResp(
            {
                "base_resp": {"status_code": 0},
                "data": {"audio": " \n".join(f"{byte:02x}" for byte in audio)},
            }
        ),
    )
    spec = tmp_path / "s.json"
    spec.write_text('{"prompt":"jazz"}', encoding="utf-8")
    out = tmp_path / "output" / "song.mp3"
    if existing:
        out.parent.mkdir()
        out.write_bytes(b"previous song")

    assert "Successfully generated music" in mus.generate_music(str(spec), str(out))
    assert out.read_bytes() == audio


def test_decoded_empty_audio_has_distinct_diagnostic(monkeypatch, tmp_path):
    monkeypatch.setenv("MINIMAX_API_KEY", "m")
    monkeypatch.setattr(
        mus.requests,
        "post",
        lambda *args, **kwargs: FakeResp(
            {"base_resp": {"status_code": 0}, "data": {"audio": " \t\n"}}
        ),
    )
    spec = tmp_path / "s.json"
    spec.write_text('{"prompt":"jazz"}', encoding="utf-8")
    with pytest.raises(ValueError, match="^MiniMax audio decoded to empty bytes$"):
        mus.generate_music(str(spec), str(tmp_path / "song.mp3"))
