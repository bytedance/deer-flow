import asyncio
import importlib.util
import sys
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


def test_list_thread_summaries_uses_row_count_for_next_offset(monkeypatch):
    fake_cfg = SimpleNamespace(model_extra={})
    monkeypatch.setattr(threads, "get_app_config", lambda: fake_cfg)

    rows = [
        {
            "thread_id": "t-1",
            "updated_at": "2026-03-08T00:00:00Z",
            "values": {"title": "Roadmap"},
        },
        {
            "thread_id": "",
            "updated_at": "2026-03-08T00:01:00Z",
            "values": {"title": "Broken row"},
        },
    ]

    class FakeThreadsClient:
        async def search(self, payload):
            assert payload["limit"] == 2
            assert payload["offset"] == 4
            assert payload["sortBy"] == "updated_at"
            assert payload["sortOrder"] == "desc"
            return rows

    class FakeClient:
        threads = FakeThreadsClient()

    fake_module = SimpleNamespace(get_client=lambda url: FakeClient())
    monkeypatch.setitem(sys.modules, "langgraph_sdk", fake_module)

    response = asyncio.run(threads.list_thread_summaries(limit=2, offset=4, sort_by="updated_at", sort_order="desc"))

    assert [summary.thread_id for summary in response.threads] == ["t-1"]
    assert response.next_offset == 6


def test_list_thread_summaries_returns_none_when_last_page(monkeypatch):
    fake_cfg = SimpleNamespace(model_extra={})
    monkeypatch.setattr(threads, "get_app_config", lambda: fake_cfg)

    rows = [
        {
            "thread_id": "t-1",
            "updated_at": "2026-03-08T00:00:00Z",
            "values": {"title": "Roadmap"},
        }
    ]

    class FakeThreadsClient:
        async def search(self, payload):
            assert payload["limit"] == 2
            return rows

    class FakeClient:
        threads = FakeThreadsClient()

    fake_module = SimpleNamespace(get_client=lambda url: FakeClient())
    monkeypatch.setitem(sys.modules, "langgraph_sdk", fake_module)

    response = asyncio.run(threads.list_thread_summaries(limit=2, offset=0, sort_by="updated_at", sort_order="desc"))

    assert response.next_offset is None
