"""Pin the cross-platform byte contract for IM channel JSON state writers."""

from pathlib import Path

CHANNELS = Path(__file__).parents[1] / "app" / "channels"


def test_json_channel_state_writers_pin_utf8_and_lf() -> None:
    sources = {
        "store.py": CHANNELS / "store.py",
        "discord.py": CHANNELS / "discord.py",
        "runtime_config_store.py": CHANNELS / "runtime_config_store.py",
        "buzz_seen_events.py": CHANNELS / "buzz_seen_events.py",
        "wechat.py": CHANNELS / "wechat.py",
    }
    for name, path in sources.items():
        source = path.read_text(encoding="utf-8")
        assert 'encoding="utf-8"' in source, name
        assert 'newline=""' in source, name


def test_json_channel_store_writes_utf8_lf_bytes(tmp_path) -> None:
    from app.channels.store import JsonChannelStore

    path = tmp_path / "channels" / "store.json"
    store = JsonChannelStore(path)
    store._set_sync("微信:资源", "thread-讨论", "用户")

    raw = path.read_bytes()
    assert raw == raw.decode("utf-8").encode("utf-8")
    assert b"\r\n" not in raw
    assert "\\u5fae\\u4fe1" in raw.decode("utf-8")


def test_discord_state_read_is_explicitly_utf8() -> None:
    source = (CHANNELS / "discord.py").read_text(encoding="utf-8")
    assert 'read_text(encoding="utf-8")' in source
