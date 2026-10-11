"""Cache parsed JSON and its own signature, including timestamp-preserving restores."""

import json
import shutil
from pathlib import Path

import pytest

import deerflow.config.extensions_config as extensions
from deerflow.config.file_signature import read_config_with_signature


def payload(argument):
    return {"mcpServers": {"example": {"type": "stdio", "command": "echo", "args": [argument]}}}


@pytest.mark.parametrize("load_mode", ["first-load", "explicit-reload", "automatic-reload"])
@pytest.mark.parametrize("race_phase", ["before-parse", "before-read"])
def test_cache_signature_identifies_the_parsed_revision(tmp_path: Path, monkeypatch, load_mode, race_phase):
    path = tmp_path / "extensions.json"
    backup = tmp_path / "backup.json"
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(path))
    extensions.reset_extensions_config()
    try:
        if load_mode == "automatic-reload":
            extensions.atomic_write_extensions_config(path, payload("initial"))
            extensions.get_extensions_config()
        extensions.atomic_write_extensions_config(path, payload("alpha"))
        shutil.copy2(path, backup)
        original_load, original_loads = json.load, json.loads
        original_signature = extensions.get_config_signature
        edited = False

        def peer_edit():
            nonlocal edited
            if not edited:
                edited = True
                # Real I/O at the parser boundary: legacy json.load reads the
                # replacement; a parser handed already-read bytes retains alpha.
                path.write_text(json.dumps(payload("beta")), encoding="utf-8")

        def load_after_peer_edit(*args, **kwargs):
            peer_edit()
            return original_load(*args, **kwargs)

        def loads_after_peer_edit(*args, **kwargs):
            peer_edit()
            return original_loads(*args, **kwargs)

        def signature_before_peer_edit(selected_path):
            signature = original_signature(selected_path)
            peer_edit()
            return signature

        def signed_read_after_peer_edit(selected_path):
            peer_edit()
            return read_config_with_signature(selected_path)

        with monkeypatch.context() as race:
            if race_phase == "before-parse":
                race.setattr(json, "load", load_after_peer_edit)
                race.setattr(json, "loads", loads_after_peer_edit)
            else:
                race.setattr(extensions, "get_config_signature", signature_before_peer_edit)
                race.setattr(extensions, "read_config_with_signature", signed_read_after_peer_edit, raising=False)
            if load_mode == "explicit-reload":
                extensions.reload_extensions_config()
            else:
                extensions.get_extensions_config()
        assert edited and json.loads(path.read_text(encoding="utf-8"))["mcpServers"]["example"]["args"] == ["beta"]

        # Restore both bytes and metadata, as cp -p/backup restoration can do.
        shutil.copy2(backup, path)
        assert path.read_bytes() == backup.read_bytes()
        assert path.stat().st_mtime_ns == backup.stat().st_mtime_ns
        for _ in range(3):
            assert extensions.get_extensions_config().mcp_servers["example"].args == ["alpha"]
    finally:
        extensions.reset_extensions_config()
