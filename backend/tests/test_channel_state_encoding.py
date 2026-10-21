"""Pin the cross-platform byte contract for IM channel JSON state writers."""

import ast
import json
from pathlib import Path

import pytest

CHANNELS = Path(__file__).parents[1] / "app" / "channels"


def _state_io_calls(filename: str, class_name: str, method_name: str, call_name: str) -> list[ast.Call]:
    module = ast.parse((CHANNELS / filename).read_text(encoding="utf-8"))
    owner = next(node for node in module.body if isinstance(node, ast.ClassDef) and node.name == class_name)
    method = next(node for node in owner.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == method_name)
    calls = [node for node in ast.walk(method) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == call_name]
    assert calls, f"{filename}:{class_name}.{method_name} has no {call_name} call"
    return calls


@pytest.mark.parametrize(
    ("filename", "class_name", "method_name", "call_name"),
    [
        ("store.py", "JsonChannelStore", "_save", "NamedTemporaryFile"),
        ("discord.py", "DiscordChannel", "_persist_thread_mappings", "write_text"),
        ("runtime_config_store.py", "ChannelRuntimeConfigStore", "_save", "NamedTemporaryFile"),
        ("buzz_seen_events.py", "BuzzSeenEventStore", "_write_snapshot", "NamedTemporaryFile"),
        ("wechat.py", "WechatChannel", "_save_state", "write_text"),
        ("wechat.py", "WechatChannel", "_save_auth_state", "NamedTemporaryFile"),
    ],
)
def test_json_channel_state_writers_pin_utf8_and_lf(filename: str, class_name: str, method_name: str, call_name: str) -> None:
    for call in _state_io_calls(filename, class_name, method_name, call_name):
        keywords = {keyword.arg: keyword.value for keyword in call.keywords}
        for name, expected in (("encoding", "utf-8"), ("newline", "")):
            value = keywords.get(name)
            assert isinstance(value, ast.Constant) and value.value == expected, f"{filename}:{call.lineno} must pin {name}={expected!r}"


def test_json_channel_store_writes_utf8_lf_bytes(tmp_path: Path) -> None:
    from app.channels.store import JsonChannelStore

    path = tmp_path / "channels" / "store.json"
    store = JsonChannelStore(path)
    store._set_sync("微信:资源", "thread-讨论", "用户")

    text = path.read_bytes().decode("utf-8")
    assert "\r" not in text
    assert "\\u5fae\\u4fe1" in text
    entry = json.loads(text)["微信:资源"]
    assert entry["thread_id"] == "thread-讨论"
    assert entry["user_id"] == "用户"


def test_discord_state_read_is_explicitly_utf8() -> None:
    for call in _state_io_calls("discord.py", "DiscordChannel", "_load_active_threads", "read_text"):
        keywords = {keyword.arg: keyword.value for keyword in call.keywords}
        encoding = keywords.get("encoding")
        assert isinstance(encoding, ast.Constant) and encoding.value == "utf-8"
