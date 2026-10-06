"""Per-leg thinking toggles: checked legs follow chat's treatment (spec 2026-10-03).

Each RAG leg reads its own ``rag.<role>_thinking`` flag and hands it to the shared
``create_rag_chat_model`` wrapper, which mirrors the lead-agent entry gate (an entry that
declares no thinking support is pressed back to non-thinking with a warning). The caption
legs are raw HTTP, so they mirror the same gate at the outbound door instead. Defaults are
all False: an unchecked leg builds exactly the request it builds today.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

import httpx
import pytest

from deerflow.config.app_config import AppConfig

SANDBOX = {"use": "deerflow.sandbox.local:LocalSandboxProvider"}

ENABLED_SHAPE = {"extra_body": {"thinking": {"type": "enabled"}}}
DISABLED_SHAPE = {"extra_body": {"thinking": {"type": "disabled"}}}

#: A thinking-capable entry with both spellings declared (the D3 shape he configured).
THINKING_ENTRY = {
    "name": "think-entry",
    "use": "langchain_openai:ChatOpenAI",
    "model": "wire-think",
    "base_url": "https://think.example/v1",
    "api_key": "sk-think",
    "supports_thinking": True,
    "when_thinking_enabled": ENABLED_SHAPE,
    "when_thinking_disabled": DISABLED_SHAPE,
}

#: Same spellings, but the entry declares no thinking support — the gate's case.
UNSUPPORTED_ENTRY = {
    **THINKING_ENTRY,
    "name": "plain-entry",
    "model": "wire-plain",
    "supports_thinking": False,
}


def _config(models: list[dict] | None = None, rag: dict | None = None) -> AppConfig:
    return AppConfig.model_validate({"sandbox": SANDBOX, "models": models or [THINKING_ENTRY], "rag": rag or {}})


@pytest.fixture()
def factory_capture(monkeypatch):
    """Record what every leg hands the model factory, keyword by keyword."""
    import deerflow.models.factory as models_factory

    calls: list[tuple[str | None, dict]] = []

    def _fake(name=None, **kwargs):
        calls.append((name, kwargs))
        return object()

    monkeypatch.setattr(models_factory, "create_chat_model", _fake)
    return calls


def _build_extract(cfg):
    from deerflow.knowledge.graph.extractor import get_extract_llm

    return get_extract_llm(cfg)


def _build_wiki(cfg):
    from deerflow.knowledge.wiki.generator import _default_llm

    return _default_llm()


def _build_judge(cfg):
    from deerflow.knowledge.eval.factory import build_judge_llm

    return build_judge_llm(None, config=cfg)


def _build_synthesis(cfg):
    from deerflow.knowledge.eval.synthesis import _default_llm_factory

    return _default_llm_factory()


LEG_BUILDERS = [_build_extract, _build_wiki, _build_judge, _build_synthesis]
LEG_IDS = ["extract", "wiki", "judge", "synthesis"]


def _patch_app_config(monkeypatch, cfg):
    monkeypatch.setattr("deerflow.config.app_config.get_app_config", lambda: cfg)


# ── the five legs' call points ─────────────────────────────────────────────


@pytest.mark.parametrize("build", LEG_BUILDERS, ids=LEG_IDS)
def test_checked_leg_asks_the_factory_for_thinking(build, factory_capture, monkeypatch):
    cfg = _config(rag={f"{role}_thinking": True for role in ("extract", "wiki", "judge", "synthesis", "vlm")})
    _patch_app_config(monkeypatch, cfg)

    build(cfg)

    assert factory_capture[-1][1]["thinking_enabled"] is True


@pytest.mark.parametrize("build", LEG_BUILDERS, ids=LEG_IDS)
def test_unchecked_leg_stays_non_thinking(build, factory_capture, monkeypatch):
    cfg = _config()
    _patch_app_config(monkeypatch, cfg)

    build(cfg)

    assert factory_capture[-1][1]["thinking_enabled"] is False


@pytest.mark.asyncio
async def test_checked_wiki_worker_asks_the_factory_for_thinking(factory_capture, monkeypatch):
    """The worker's inline construction site (``worker.py``) is the wiki leg's second door."""
    from deerflow.knowledge import worker as worker_module

    cfg = _config(rag={"wiki_thinking": True})
    _patch_app_config(monkeypatch, cfg)

    async def _ready(*args, **kwargs):
        return True

    async def _no_generate(*args, **kwargs):
        return None

    async def _no_entries(*args, **kwargs):
        return []

    monkeypatch.setattr(worker_module, "wiki_trigger_ready", _ready)
    monkeypatch.setattr(worker_module, "generate_wiki", _no_generate)
    stub = SimpleNamespace(_main_llm=None, _wiki_store=SimpleNamespace(list_entries=_no_entries), _store=None, _graph_store=None, _vector_store=None)

    await worker_module.KnowledgeIndexWorker._maybe_generate_wiki(stub, "kb-1", None)

    assert factory_capture[-1][1]["thinking_enabled"] is True


# ── the entry gate, mirrored from the lead agent ───────────────────────────


def test_checked_leg_on_an_unsupported_entry_downgrades_with_a_warning(factory_capture, monkeypatch, caplog):
    cfg = _config(models=[UNSUPPORTED_ENTRY], rag={"extract_thinking": True})
    _patch_app_config(monkeypatch, cfg)

    with caplog.at_level(logging.WARNING):
        _build_extract(cfg)

    assert factory_capture[-1][1]["thinking_enabled"] is False
    assert "plain-entry" in caplog.text and "does not support" in caplog.text


# ── the caption legs mirror the same gate at the outbound door ─────────────


def _vlm_target(cfg, name: str):
    from deerflow.knowledge.vlm_target import resolve_vlm_target

    return resolve_vlm_target(cfg, name)


def _caption_body(target, **kwargs):
    from deerflow.knowledge.caption_client import _openai_request

    return _openai_request(target, "Describe.", [(b"jpeg", "image/jpeg")], max_tokens=1024, temperature=0.15, **kwargs)[0]


def test_caption_checked_sends_the_declared_enable_shape():
    target = _vlm_target(_config([THINKING_ENTRY]), "think-entry")

    body = _caption_body(target, thinking=True)

    assert body["thinking"] == {"type": "enabled"}
    assert "reasoning_effort" not in body


def test_caption_checked_without_a_declared_shape_adds_nothing():
    bare = {key: value for key, value in THINKING_ENTRY.items() if not key.startswith("when_thinking") and key != "supports_thinking"}
    target = _vlm_target(_config([bare]), "think-entry")

    body = _caption_body(target, thinking=True)

    assert "thinking" not in body and "reasoning_effort" not in body


def test_caption_default_still_sends_the_disable_shape():
    target = _vlm_target(_config([THINKING_ENTRY]), "think-entry")

    body = _caption_body(target)

    assert body["thinking"] == {"type": "disabled"}


@pytest.mark.asyncio
async def test_caption_checked_but_the_entry_declares_no_support_downgrades_with_a_warning(caplog):
    from deerflow.knowledge.caption_client import request_caption

    target = _vlm_target(_config([UNSUPPORTED_ENTRY]), "plain-entry")
    recorded: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "一张图"}}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with caplog.at_level(logging.WARNING):
            await request_caption(client, target=target, prompt="Describe.", images=[(b"jpeg", "image/jpeg")], max_tokens=1024, temperature=0.15, thinking=True)

    import json as _json

    body = _json.loads(recorded[0].content)
    assert body["thinking"] == {"type": "disabled"}  # pressed back to the off spelling
    # The caption door names the wire model (VlmTarget carries no entry name).
    assert "wire-plain" in caplog.text and "does not support" in caplog.text


# ── D2=甲: the output budget rises while thinking is on ───────────────────
#
# Thinking tokens draw from the same output budget (the truncation post-mortem), so the
# effective budget gets a 4096 floor when thinking is on — never cutting a higher user
# value, and never rising once the entry gate has pressed thinking back off.


async def _sent_max_tokens(entry_name: str, *, thinking: bool, user_budget: int) -> int:
    import json as _json

    from deerflow.knowledge.caption_client import request_caption

    target = _vlm_target(_config([THINKING_ENTRY if entry_name == "think-entry" else UNSUPPORTED_ENTRY]), entry_name)
    recorded: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "x"}}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        await request_caption(client, target=target, prompt="p", images=[(b"jpeg", "image/jpeg")], max_tokens=user_budget, temperature=0.15, thinking=thinking)
    return _json.loads(recorded[0].content)["max_tokens"]


@pytest.mark.asyncio
async def test_checked_caption_raises_the_budget_to_at_least_4096():
    assert await _sent_max_tokens("think-entry", thinking=True, user_budget=1024) == 4096


@pytest.mark.asyncio
async def test_checked_caption_keeps_a_higher_user_budget():
    assert await _sent_max_tokens("think-entry", thinking=True, user_budget=8192) == 8192


@pytest.mark.asyncio
async def test_unchecked_caption_keeps_the_user_budget():
    assert await _sent_max_tokens("think-entry", thinking=False, user_budget=1024) == 1024


@pytest.mark.asyncio
async def test_downgraded_caption_keeps_the_user_budget():
    """Ordering pin: the gate runs first, so a pressed-back request never earns the floor."""
    assert await _sent_max_tokens("plain-entry", thinking=True, user_budget=1024) == 1024
