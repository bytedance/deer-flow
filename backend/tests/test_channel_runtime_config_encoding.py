"""Runtime channel configuration must round-trip independently of host locale."""

import json

import pytest

from app.channels import runtime_config_store


@pytest.mark.parametrize(
    ("locale_encoding", "relay_url"),
    [
        ("cp1252", "wss://relay.example/caf\u00e9"),
        ("gbk", "wss://relay.example/\u804a\u5929"),
        ("cp1252", "wss://relay.example/\u804a\u5929"),
    ],
)
def test_runtime_config_round_trips_non_ascii_with_legacy_locale(tmp_path, monkeypatch, locale_encoding, relay_url):
    named_temporary_file = runtime_config_store.tempfile.NamedTemporaryFile

    def locale_temporary_file(*args, **kwargs):
        # Simulate a legacy host default only when the writer omits encoding.
        kwargs.setdefault("encoding", locale_encoding)
        return named_temporary_file(*args, **kwargs)

    monkeypatch.setattr(runtime_config_store.tempfile, "NamedTemporaryFile", locale_temporary_file)
    path = tmp_path / "channels" / "runtime-config.json"
    config = {"enabled": True, "relay_url": relay_url}
    store = runtime_config_store.ChannelRuntimeConfigStore(path)

    store.set_provider_config("buzz", config)

    assert json.loads(path.read_text(encoding="utf-8")) == {"buzz": config}
    reloaded = runtime_config_store.ChannelRuntimeConfigStore(path)
    assert reloaded.get_provider_config("buzz") == config
