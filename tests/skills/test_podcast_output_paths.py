"""Offline regressions for colliding podcast input and output paths."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from skill_loader import load  # noqa: E402

pod = load("podcast-generation")
SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "skills/public/podcast-generation/scripts/generate.py"
)


def _write_script(path):
    path.write_text(
        json.dumps({"lines": [{"speaker": "male", "paragraph": "Hello"}]}),
        encoding="utf-8",
    )


@pytest.mark.parametrize("collision", ["script-audio", "script-transcript", "audio-transcript"])
@pytest.mark.parametrize("relative_alias", [False, True])
def test_colliding_paths_fail_before_tts_or_writes(tmp_path, monkeypatch, collision, relative_alias):
    script = tmp_path / "script.json"
    _write_script(script)
    original_script = script.read_bytes()
    audio = tmp_path / "new" / "episode.mp3"
    transcript = tmp_path / "new" / "episode.md"
    if collision == "script-audio":
        audio = script
    elif collision == "script-transcript":
        transcript = script
    else:
        transcript = audio

    calls = []
    monkeypatch.setattr(pod, "tts_node", lambda value: calls.append(value) or [b"audio"])
    monkeypatch.chdir(tmp_path)
    audio_arg = os.path.relpath(audio) if relative_alias else str(audio)
    transcript_arg = os.path.relpath(transcript) if relative_alias else str(transcript)

    with pytest.raises(ValueError, match="must refer to different files"):
        pod.generate_podcast(str(script), audio_arg, transcript_arg)

    assert calls == []
    assert script.read_bytes() == original_script
    assert not (tmp_path / "new").exists()


@pytest.mark.parametrize("link_kind", ["hard", "symbolic"])
@pytest.mark.parametrize("collision", ["script-audio", "script-transcript", "audio-transcript"])
def test_existing_file_aliases_fail_without_modifying_files(tmp_path, monkeypatch, link_kind, collision):
    script = tmp_path / "script.json"
    _write_script(script)
    audio = tmp_path / "episode.mp3"
    audio.write_bytes(b"previous episode")
    transcript = tmp_path / "episode.md"
    transcript.write_text("previous transcript", encoding="utf-8")
    target = audio if collision == "audio-transcript" else script
    alias = tmp_path / "alias"
    try:
        if link_kind == "hard":
            os.link(target, alias)
        else:
            alias.symlink_to(target)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"{link_kind} links unavailable: {exc}")

    if collision == "script-audio":
        audio = alias
    else:
        transcript = alias
    originals = {path: path.read_bytes() for path in (script, audio, transcript)}
    calls = []
    monkeypatch.setattr(pod, "tts_node", lambda value: calls.append(value) or [b"audio"])

    with pytest.raises(ValueError, match="must refer to different files"):
        pod.generate_podcast(str(script), str(audio), str(transcript))

    assert calls == []
    assert all(path.read_bytes() == content for path, content in originals.items())


def test_distinct_outputs_keep_normal_generation(tmp_path, monkeypatch):
    script = tmp_path / "script.json"
    _write_script(script)
    original_script = script.read_bytes()
    audio = tmp_path / "audio" / "episode.mp3"
    transcript = tmp_path / "text" / "episode.md"
    calls = []
    monkeypatch.setattr(pod, "tts_node", lambda value: calls.append(value) or [b"audio"])

    result = pod.generate_podcast(str(script), str(audio), str(transcript))

    assert len(calls) == 1
    assert script.read_bytes() == original_script
    assert audio.read_bytes() == b"audio"
    assert "**Host (Male)**: Hello" in transcript.read_text(encoding="utf-8")
    assert result.startswith("Successfully generated podcast")


def test_not_yet_created_outputs_with_parent_alias_fail_before_mkdir(tmp_path, monkeypatch):
    script = tmp_path / "script.json"
    _write_script(script)
    audio = tmp_path / "new" / "episode.mp3"
    transcript = tmp_path / "new" / "nested" / ".." / "episode.mp3"
    calls = []
    monkeypatch.setattr(pod, "tts_node", lambda value: calls.append(value) or [b"audio"])

    with pytest.raises(ValueError, match="output_file and transcript_file must refer to different files"):
        pod.generate_podcast(str(script), str(audio), str(transcript))

    assert calls == []
    assert not (tmp_path / "new").exists()


def test_distinct_existing_outputs_with_identical_contents_are_allowed(tmp_path, monkeypatch):
    script = tmp_path / "script.json"
    _write_script(script)
    audio = tmp_path / "episode.mp3"
    transcript = tmp_path / "episode.md"
    audio.write_bytes(b"old output")
    transcript.write_bytes(b"old output")
    monkeypatch.setattr(pod, "tts_node", lambda value: [b"audio"])

    pod.generate_podcast(str(script), str(audio), str(transcript))

    assert audio.read_bytes() == b"audio"
    assert "**Host (Male)**: Hello" in transcript.read_text(encoding="utf-8")


def test_missing_output_alias_through_symlinked_parent_is_rejected(tmp_path, monkeypatch):
    script = tmp_path / "script.json"
    _write_script(script)
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    alias_dir = tmp_path / "alias"
    try:
        alias_dir.symlink_to(output_dir, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"directory symlinks unavailable: {exc}")
    calls = []
    monkeypatch.setattr(pod, "tts_node", lambda value: calls.append(value) or [b"audio"])

    with pytest.raises(ValueError, match="output_file and transcript_file must refer to different files"):
        pod.generate_podcast(
            str(script), str(output_dir / "episode.mp3"), str(alias_dir / "episode.mp3")
        )

    assert calls == []
    assert not (output_dir / "episode.mp3").exists()


def test_cli_rejects_collision_before_missing_provider_credentials(tmp_path):
    script = tmp_path / "script.json"
    _write_script(script)
    original = script.read_bytes()
    env = os.environ.copy()
    for name in ("VOLCENGINE_TTS_APPID", "VOLCENGINE_TTS_ACCESS_TOKEN", "MINIMAX_API_KEY"):
        env.pop(name, None)
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--script-file",
            str(script),
            "--output-file",
            str(tmp_path / "episode.mp3"),
            "--transcript-file",
            str(script),
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )

    assert result.returncode == 1
    assert result.stdout == ""
    assert "script_file and transcript_file must refer to different files" in result.stderr
    assert script.read_bytes() == original
    assert not (tmp_path / "episode.mp3").exists()
