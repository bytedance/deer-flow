import importlib.util
from pathlib import Path
from types import SimpleNamespace

_MODULE_PATH = Path(__file__).resolve().parents[1] / "src" / "gateway" / "routers" / "threads.py"
_SPEC = importlib.util.spec_from_file_location("deerflow_threads_router", _MODULE_PATH)
assert _SPEC and _SPEC.loader
threads = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(threads)


def test_pick_title_prefers_values_title():
    assert threads._pick_title({"title": "  Hello Title  "}) == "  Hello Title  "


def test_pick_title_falls_back_to_untitled():
    assert threads._pick_title({}) == "Untitled"
    assert threads._pick_title({"title": ""}) == "Untitled"
    assert threads._pick_title(None) == "Untitled"


def test_to_thread_summary_returns_compact_payload():
    row = {
        "thread_id": "t-1",
        "updated_at": "2026-03-08T00:00:00Z",
        "values": {
            "title": "Roadmap",
            "messages": ["very", "large", "content"],
        },
        "other": "ignored",
    }
    summary = threads._to_thread_summary(row)
    assert summary is not None
    assert summary.thread_id == "t-1"
    assert summary.updated_at == "2026-03-08T00:00:00Z"
    assert summary.values == {"title": "Roadmap"}


def test_to_thread_summary_rejects_missing_thread_id():
    assert threads._to_thread_summary({"updated_at": "x"}) is None
    assert threads._to_thread_summary({"thread_id": ""}) is None


def test_resolve_langgraph_url_prefers_channels_config(monkeypatch):
    fake_cfg = SimpleNamespace(model_extra={"channels": {"langgraph_url": "http://langgraph.internal:2024"}})
    monkeypatch.setattr(threads, "get_app_config", lambda: fake_cfg)
    assert threads._resolve_langgraph_url() == "http://langgraph.internal:2024"


def test_resolve_langgraph_url_falls_back_default(monkeypatch):
    fake_cfg = SimpleNamespace(model_extra={})
    monkeypatch.setattr(threads, "get_app_config", lambda: fake_cfg)
    assert threads._resolve_langgraph_url() == "http://localhost:2024"
