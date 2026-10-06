"""Caption VLM resolution: a `models:` entry reference is the single source.

The caption legs are raw HTTP calls, so they need a (wire model, endpoint, key) triple and
the protocol to speak. Naming a configured `models:` entry is the only way to get one — that
is what lets the settings UI offer a plain model picker with no endpoint/key boxes, and the
entry's `use:` class decides the dialect (spec 2026-09-18). A value that names no entry is a
configuration error since spec 2026-09-23 D10.3 (the legacy bare-id path and the RAG-side
endpoint/key fields are retired), and an entry's address is its own or the one its SDK ships
(D10.2).
"""

from __future__ import annotations

import base64
import json

import httpx
import pytest

from deerflow.config.app_config import AppConfig

SANDBOX = {"use": "deerflow.sandbox.local:LocalSandboxProvider"}

#: A configured vision model whose entry carries everything the caption call needs.
VL_ENTRY = {
    "name": "vl-entry",
    "use": "langchain_openai:ChatOpenAI",
    "model": "qwen3.7-flash",
    "base_url": "https://dashscope.example/compatible-mode/v1",
    "api_key": "sk-entry",
    "supports_vision": True,
}

#: The same triple, a different protocol: the entry's `use:` says Messages, not chat.
ANTHROPIC_ENTRY = {
    "name": "claude-entry",
    "use": "langchain_anthropic:ChatAnthropic",
    "model": "claude-x",
    "base_url": "https://anthropic.example",
    "api_key": "sk-anthropic",
    "supports_vision": True,
}

#: A deployment's own class: not on the provider allowlist, so the dialect cannot be read
#: off `use:` — and an unrecognized class is not evidence of a third shape.
CUSTOM_ENTRY = {
    "name": "custom-entry",
    "use": "mycompany.vlm:MyVlmClient",
    "model": "my-vlm",
    "base_url": "https://custom.example/v1",
    "api_key": "sk-custom",
    "supports_vision": True,
}


def _config(models: list[dict] | None = None, rag: dict | None = None) -> AppConfig:
    return AppConfig.model_validate({"sandbox": SANDBOX, "models": models or [], "rag": rag or {}})


# ── resolution ────────────────────────────────────────────────────────────


def test_entry_reference_supplies_model_endpoint_and_key():
    from deerflow.knowledge.vlm_target import resolve_vlm_target

    config = _config([VL_ENTRY])

    target = resolve_vlm_target(config, "vl-entry")

    assert target.model == "qwen3.7-flash"  # provider-side id from the entry
    assert target.base_url == "https://dashscope.example/compatible-mode/v1"
    assert target.api_key == "sk-entry"
    assert target.source == "model_entry"


def test_entry_without_endpoint_does_not_borrow_a_rag_side_field():
    """Reversed (spec 2026-09-23 R1/D10.2): the RAG-side caption endpoint is retired.

    An entry that declares no address now borrows its own SDK's default — and the one cell
    without such a default is refused rather than pointed at a cloud nobody named, which is
    what the `rag.vlm_base_url` field used to supply.
    """
    from deerflow.knowledge.embedder import RagConfigurationError
    from deerflow.knowledge.vlm_target import resolve_vlm_target

    entry = {key: value for key, value in VL_ENTRY.items() if key != "base_url"}
    config = _config([entry])

    with pytest.raises(RagConfigurationError) as excinfo:
        resolve_vlm_target(config, "vl-entry")

    assert "base_url" in str(excinfo.value)


def test_entry_without_key_has_no_fallback_left():
    """Reversed (R14/D10.3): the entry must carry the key — the RAG field and the environment
    are both gone, and this is what the strict target rule keys off."""
    from deerflow.knowledge.vlm_target import resolve_vlm_target

    entry = {key: value for key, value in VL_ENTRY.items() if key != "api_key"}

    assert resolve_vlm_target(_config([entry]), "vl-entry").api_key is None


def test_a_value_naming_no_entry_is_a_configuration_error():
    """Reversed (D10.3): the bare-id path is gone, so this reports instead of dialing."""
    from deerflow.knowledge.embedder import RagConfigurationError
    from deerflow.knowledge.vlm_target import resolve_vlm_target

    config = _config([VL_ENTRY])

    with pytest.raises(RagConfigurationError) as excinfo:
        resolve_vlm_target(config, "qwen3.7-flash-not-an-entry")

    assert "Model qwen3.7-flash-not-an-entry not found in config" in str(excinfo.value)


def test_defaults_to_the_configured_vlm_model():
    """Reversed (D10.3): `rag.vlm_model` names an entry now; its old literal default is gone.

    The fixture's entry name, wire id and the RAG default are three different strings, so
    "which level answered" is visible in the result.
    """
    from deerflow.knowledge.vlm_target import resolve_vlm_target

    config = _config([VL_ENTRY], {"vlm_model": "vl-entry"})

    target = resolve_vlm_target(config, None)

    assert target.model == "qwen3.7-flash"  # the entry's wire id, not the entry name
    assert target.source == "model_entry"
    assert config.rag.vlm_model == "vl-entry" != target.model


# ── the two caption legs actually use it ──────────────────────────────────


def _recording_transport(recorded: list[httpx.Request]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "一张架构图"}}]})

    return httpx.MockTransport(handler)


@pytest.mark.asyncio
async def test_image_caption_posts_to_the_selected_entry(monkeypatch):
    from deerflow.knowledge import captioner as captioner_module
    from deerflow.knowledge.captioner import caption_images
    from deerflow.knowledge.parser import ParsedImage

    monkeypatch.setattr(captioner_module, "get_app_config", lambda: _config([VL_ENTRY]))
    recorded: list[httpx.Request] = []

    outcome = await caption_images(
        [ParsedImage(ref="images/p1.jpg", content=b"jpeg", media_type="image/jpeg")],
        client=httpx.AsyncClient(transport=_recording_transport(recorded)),
        model="vl-entry",
    )

    assert outcome.captions == {"images/p1.jpg": "一张架构图"}
    request = recorded[0]
    assert str(request.url) == "https://dashscope.example/compatible-mode/v1/chat/completions"
    assert request.headers["Authorization"] == "Bearer sk-entry"


@pytest.mark.asyncio
async def test_shot_caption_posts_to_the_selected_entry(monkeypatch):
    from deerflow.knowledge.video import captioner as video_captioner_module
    from deerflow.knowledge.video.captioner import caption_shots

    monkeypatch.setattr(video_captioner_module, "get_app_config", lambda: _config([VL_ENTRY]))
    recorded: list[httpx.Request] = []

    outcome = await caption_shots({0: [b"frame"]}, client=httpx.AsyncClient(transport=_recording_transport(recorded)), model="vl-entry")

    assert outcome.captions == {0: "一张架构图"}
    request = recorded[0]
    assert str(request.url) == "https://dashscope.example/compatible-mode/v1/chat/completions"
    assert request.headers["Authorization"] == "Bearer sk-entry"


# ── both caption legs read one target (spec 2026-09-23 D3/D7, R18) ─────────
#
# `video.caption_model` is retired: the video leg keeps no layer of its own, so both legs
# resolve the same way. The fixture deliberately points the retired field at a *different*
# entry — naming the same model in both fields would make the two layers indistinguishable,
# and the assertion would hold even with the old precedence restored.

VIDEO_ENTRY = {
    "name": "video-entry",
    "use": "langchain_openai:ChatOpenAI",
    "model": "wire-video",
    "base_url": "https://video.example/v1",
    "api_key": "sk-video",
    "supports_vision": True,
}
ROLE_ENTRY = {
    "name": "role-entry",
    "use": "langchain_openai:ChatOpenAI",
    "model": "wire-role",
    "base_url": "https://role.example/v1",
    "api_key": "sk-role",
    "supports_vision": True,
}


def _two_leg_config() -> AppConfig:
    return _config(
        models=[VIDEO_ENTRY, ROLE_ENTRY],
        rag={"vlm_model": "role-entry"},
    )


@pytest.mark.asyncio
async def test_both_caption_legs_read_the_same_target(monkeypatch):
    from deerflow.knowledge import captioner as captioner_module
    from deerflow.knowledge.captioner import caption_images
    from deerflow.knowledge.parser import ParsedImage
    from deerflow.knowledge.video import captioner as video_captioner_module
    from deerflow.knowledge.video.captioner import caption_shots

    image_requests: list[httpx.Request] = []
    video_requests: list[httpx.Request] = []
    monkeypatch.setattr(captioner_module, "get_app_config", _two_leg_config)
    monkeypatch.setattr(video_captioner_module, "get_app_config", _two_leg_config)

    await caption_images(
        [ParsedImage(ref="images/p1.jpg", content=b"jpeg", media_type="image/jpeg")],
        client=httpx.AsyncClient(transport=_recording_transport(image_requests)),
    )
    await caption_shots({0: [b"frame"]}, client=httpx.AsyncClient(transport=_recording_transport(video_requests)))

    # Same entry ⇒ same endpoint and same key: the video field above is not consulted.
    assert str(image_requests[0].url) == "https://role.example/v1/chat/completions"
    assert str(video_requests[0].url) == str(image_requests[0].url)
    assert video_requests[0].headers["Authorization"] == image_requests[0].headers["Authorization"] == "Bearer sk-role"


# ── dialect dispatch (spec 2026-09-18) ────────────────────────────────────


def _anthropic_transport(recorded: list[httpx.Request], *, content: list[dict] | None = None) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        return httpx.Response(200, json={"content": [{"type": "text", "text": "一张架构图"}] if content is None else content})

    return httpx.MockTransport(handler)


def test_dialect_is_read_off_the_entrys_use_class():
    from deerflow.knowledge.vlm_target import resolve_vlm_target

    assert resolve_vlm_target(_config([ANTHROPIC_ENTRY]), "claude-entry").dialect == "anthropic"
    assert resolve_vlm_target(_config([VL_ENTRY]), "vl-entry").dialect == "openai"
    # An unrecognized class path is not evidence of a third shape — keep OpenAI.
    assert resolve_vlm_target(_config([CUSTOM_ENTRY]), "custom-entry").dialect == "openai"


@pytest.mark.asyncio
async def test_anthropic_image_caption_speaks_the_messages_protocol(monkeypatch):
    from deerflow.knowledge import captioner as captioner_module
    from deerflow.knowledge.captioner import caption_images
    from deerflow.knowledge.parser import ParsedImage

    monkeypatch.setattr(captioner_module, "get_app_config", lambda: _config([ANTHROPIC_ENTRY]))
    recorded: list[httpx.Request] = []

    outcome = await caption_images(
        [ParsedImage(ref="images/p1.jpg", content=b"jpeg", media_type="image/jpeg")],
        client=httpx.AsyncClient(transport=_anthropic_transport(recorded)),
        model="claude-entry",
    )

    assert outcome.captions == {"images/p1.jpg": "一张架构图"}
    request = recorded[0]
    assert str(request.url) == "https://anthropic.example/v1/messages"
    assert request.headers["X-Api-Key"] == "sk-anthropic"
    assert request.headers["anthropic-version"] == "2023-06-01"
    assert "Authorization" not in request.headers
    body = json.loads(request.content)
    assert body["model"] == "claude-x"
    assert body["max_tokens"] > 0
    content = body["messages"][0]["content"]
    assert content[0] == {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": "image/jpeg",
            "data": base64.b64encode(b"jpeg").decode("ascii"),
        },
    }
    assert content[-1]["type"] == "text"


@pytest.mark.asyncio
async def test_anthropic_shot_caption_puts_every_frame_before_the_text(monkeypatch):
    from deerflow.knowledge.video import captioner as video_captioner_module
    from deerflow.knowledge.video.captioner import caption_shots

    monkeypatch.setattr(video_captioner_module, "get_app_config", lambda: _config([ANTHROPIC_ENTRY]))
    recorded: list[httpx.Request] = []

    outcome = await caption_shots(
        {0: [b"f1", b"f2", b"f3"]},
        client=httpx.AsyncClient(transport=_anthropic_transport(recorded)),
        model="claude-entry",
    )

    assert outcome.captions == {0: "一张架构图"}
    assert len(recorded) == 1  # one shot, one call — framing never multiplies requests
    body = json.loads(recorded[0].content)
    content = body["messages"][0]["content"]
    assert [block["type"] for block in content] == ["image", "image", "image", "text"]
    assert [block["source"]["media_type"] for block in content[:3]] == ["image/jpeg"] * 3


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("declared", "expected"),
    [
        ("https://api.anthropic.com", "https://api.anthropic.com/v1/messages"),
        ("https://api.anthropic.com/", "https://api.anthropic.com/v1/messages"),
        ("https://api.anthropic.com/v1", "https://api.anthropic.com/v1/v1/messages"),
        ("https://api.anthropic.com/v1/", "https://api.anthropic.com/v1/v1/messages"),
    ],
)
async def test_anthropic_endpoint_join_mirrors_the_chat_leg(monkeypatch, declared, expected):
    """Same entry, same URL on both legs — including the spelling that doubles.

    The chat leg hands the entry's ``base_url`` straight to the SDK, which joins by raw
    path concatenation (`anthropic/_base_client.py:482`), so a trailing `/v1` yields
    `/v1/v1/messages`. We reproduce that byte for byte instead of "helpfully" stripping
    `/v1`: stripping would make an entry the graph extractor cannot reach work for
    captioning, which is the asymmetry this line exists to remove.
    """
    from deerflow.knowledge import captioner as captioner_module
    from deerflow.knowledge.captioner import caption_images
    from deerflow.knowledge.parser import ParsedImage

    entry = {**ANTHROPIC_ENTRY, "base_url": declared}
    monkeypatch.setattr(captioner_module, "get_app_config", lambda: _config([entry]))
    recorded: list[httpx.Request] = []

    await caption_images(
        [ParsedImage(ref="images/p1.jpg", content=b"jpeg", media_type="image/jpeg")],
        client=httpx.AsyncClient(transport=_anthropic_transport(recorded)),
        model="claude-entry",
    )

    assert str(recorded[0].url) == expected


@pytest.mark.asyncio
async def test_anthropic_reply_keeps_the_text_blocks_and_ignores_the_rest(monkeypatch):
    from deerflow.knowledge import captioner as captioner_module
    from deerflow.knowledge.captioner import caption_images
    from deerflow.knowledge.parser import ParsedImage

    monkeypatch.setattr(captioner_module, "get_app_config", lambda: _config([ANTHROPIC_ENTRY]))
    recorded: list[httpx.Request] = []

    outcome = await caption_images(
        [ParsedImage(ref="images/p1.jpg", content=b"jpeg", media_type="image/jpeg")],
        client=httpx.AsyncClient(
            transport=_anthropic_transport(
                recorded,
                content=[{"type": "thinking", "thinking": "..."}, {"type": "text", "text": "X"}],
            )
        ),
        model="claude-entry",
    )

    assert outcome.captions == {"images/p1.jpg": "X"}


@pytest.mark.asyncio
async def test_unrecognized_entry_still_posts_the_openai_shape(monkeypatch):
    from deerflow.knowledge import captioner as captioner_module
    from deerflow.knowledge.captioner import caption_images
    from deerflow.knowledge.parser import ParsedImage

    monkeypatch.setattr(captioner_module, "get_app_config", lambda: _config([CUSTOM_ENTRY]))
    recorded: list[httpx.Request] = []

    outcome = await caption_images(
        [ParsedImage(ref="images/p1.jpg", content=b"jpeg", media_type="image/jpeg")],
        client=httpx.AsyncClient(transport=_recording_transport(recorded)),
        model="custom-entry",
    )

    assert outcome.captions == {"images/p1.jpg": "一张架构图"}
    request = recorded[0]
    assert str(request.url) == "https://custom.example/v1/chat/completions"
    assert request.headers["Authorization"] == "Bearer sk-custom"


# ── the RAG default joins the chain (spec 2026-09-23 D3/D7) ───────────────
#
# Four distinct targets, so a case can tell which level answered. The caption legs and the
# extraction/judge roles now share one resolver shape: explicit argument → the role field
# → the RAG default → the first configured model.


def _chain() -> list[dict]:
    return [
        {**VL_ENTRY, "name": "first-model", "model": "wire-first"},
        {**VL_ENTRY, "name": "default-model", "model": "wire-default"},
        {**VL_ENTRY, "name": "role-model", "model": "wire-role"},
        {**VL_ENTRY, "name": "explicit-model", "model": "wire-explicit"},
    ]


def test_explicit_argument_still_wins():
    from deerflow.knowledge.vlm_target import resolve_vlm_target

    target = resolve_vlm_target(_config(models=_chain(), rag={"vlm_model": "role-model", "default_model": "default-model"}), "explicit-model")

    assert target.model == "wire-explicit"


def test_vlm_model_beats_the_rag_default():
    from deerflow.knowledge.vlm_target import resolve_vlm_target

    target = resolve_vlm_target(_config(models=_chain(), rag={"vlm_model": "role-model", "default_model": "default-model"}))

    assert target.model == "wire-role"


def test_rag_default_answers_when_the_role_is_empty():
    # `rag.vlm_model` carries a code-level literal default until Task 9 retires it, so the
    # lower levels of the chain are only reachable from an isolated configuration.
    from deerflow.knowledge.vlm_target import resolve_vlm_target

    target = resolve_vlm_target(_config(models=_chain(), rag={"vlm_model": "", "default_model": "default-model"}))

    assert target.model == "wire-default"


def test_first_model_answers_when_nothing_declares_a_target():
    from deerflow.knowledge.vlm_target import resolve_vlm_target

    target = resolve_vlm_target(_config(models=_chain(), rag={"vlm_model": ""}))

    assert target.model == "wire-first"


def test_a_stale_default_falls_back_to_the_first_model_and_is_named(caplog):
    import logging

    from deerflow.knowledge.vlm_target import resolve_vlm_target

    with caplog.at_level(logging.WARNING, logger="deerflow.knowledge.model_target"):
        target = resolve_vlm_target(_config(models=_chain(), rag={"vlm_model": "", "default_model": "gone-model"}))

    assert target.model == "wire-first"
    assert "gone-model" in caplog.text


def test_no_models_at_all_refuses_instead_of_sending_an_empty_model():
    """A caption call with an empty ``model`` is a request the endpoint would refuse anyway."""
    from deerflow.knowledge.embedder import RagConfigurationError
    from deerflow.knowledge.vlm_target import resolve_vlm_target

    with pytest.raises(RagConfigurationError):
        resolve_vlm_target(_config(models=[], rag={"vlm_model": ""}))


# ── the declared caption target must be usable (spec 2026-09-23 D10.1/§4.10) ──
# The caption legs share this one entrance, so refusing here covers both. Only a *declared*
# target is refused: a blank role falling back to the first model keeps today's behaviour and
# fails (or degrades) at request time, which is R2's other half.


def _ui_config(*entries: dict, vlm_model: str | None = None):
    """A real AppConfig whose entries are UI-managed: the strict rule's scope."""
    config = _config(models=list(entries), rag={"vlm_model": vlm_model})
    config._ui_model_names = {entry["name"] for entry in entries}
    return config


def test_a_declared_ui_caption_target_without_a_key_is_refused():
    from deerflow.knowledge.embedder import RagConfigurationError
    from deerflow.knowledge.vlm_target import resolve_vlm_target

    config = _ui_config({**VL_ENTRY, "api_key": None}, vlm_model="vl-entry")

    with pytest.raises(RagConfigurationError) as excinfo:
        resolve_vlm_target(config)

    assert "vl-entry" in str(excinfo.value) and "api_key" in str(excinfo.value)


def test_a_fallback_caption_target_is_not_refused():
    """Blank role, keyless first model: still today's degradation path, not a hard error."""
    from deerflow.knowledge.vlm_target import resolve_vlm_target

    config = _ui_config({**VL_ENTRY, "api_key": None}, vlm_model="")

    target = resolve_vlm_target(config)

    assert target.model == "qwen3.7-flash"  # the entry supplies the wire id; the missing key shows up later


# ── the address boundary (spec 2026-09-23 D10.2/R1) ───────────────────────
# A vendor entry that declares no address borrows the address its own SDK ships — read
# lazily from that SDK, never copied here — while the OpenAI-compatible cell has no such
# default to borrow, so a blank address there is a refusal. The equality assertions are the
# point: they compare the RAG side against the SDK's own value, so an SDK that changes its
# default keeps them green only if the borrow is real (a copied URL literal would drift).


def test_an_anthropic_entry_without_an_address_borrows_the_sdks_own_default():
    from langchain_anthropic import ChatAnthropic

    from deerflow.knowledge.vlm_target import resolve_vlm_target

    config = _config([{**ANTHROPIC_ENTRY, "base_url": None}])
    target = resolve_vlm_target(config, "claude-entry")

    sdk_default = ChatAnthropic.model_fields["anthropic_api_url"].default_factory()
    assert target.base_url == sdk_default
    assert target.api_key == "sk-anthropic"  # the entry still supplies the key


def test_a_deepseek_entry_without_an_address_borrows_the_sdks_own_default():
    from langchain_deepseek.chat_models import DEFAULT_API_BASE

    from deerflow.knowledge.vlm_target import resolve_vlm_target

    entry = {"name": "ds-entry", "use": "deerflow.models.patched_deepseek:PatchedChatDeepSeek", "model": "ds-wire", "api_key": "sk-ds", "supports_vision": True}
    config = _config([entry])
    target = resolve_vlm_target(config, "ds-entry")

    assert target.base_url == DEFAULT_API_BASE


def test_an_explicit_address_wins_in_every_cell():
    from deerflow.knowledge.vlm_target import resolve_vlm_target

    entries = [
        {**VL_ENTRY, "base_url": "https://explicit.example/v1"},
        {**ANTHROPIC_ENTRY, "base_url": "https://explicit-anthropic.example"},
        {"name": "ds-entry", "use": "deerflow.models.patched_deepseek:PatchedChatDeepSeek", "model": "ds-wire", "api_key": "sk-ds", "api_base": "https://explicit-ds.example/v1"},
    ]
    for entry in entries:
        target = resolve_vlm_target(_config([entry]), entry["name"])
        assert target.base_url in entry.values(), entry["name"]


def test_an_openai_compatible_entry_without_an_address_is_refused_at_the_entrance():
    """No SDK default to borrow (its blank would mean OpenAI's public cloud): refuse."""
    from deerflow.knowledge.embedder import RagConfigurationError
    from deerflow.knowledge.vlm_target import resolve_vlm_target

    config = _config([{**VL_ENTRY, "base_url": None}])

    with pytest.raises(RagConfigurationError) as excinfo:
        resolve_vlm_target(config, "vl-entry")

    assert "base_url" in str(excinfo.value)


def test_resolving_borrows_no_client_and_no_network(monkeypatch):
    """Purity pin: reading an SDK's default address must not build a client or dial out."""
    import httpx

    from deerflow.knowledge.vlm_target import resolve_vlm_target

    def _explode(*args, **kwargs):
        raise AssertionError("resolving a target must not construct a client")

    monkeypatch.setattr(httpx, "AsyncClient", _explode)
    monkeypatch.setattr(httpx, "Client", _explode)

    target = resolve_vlm_target(_config([{**ANTHROPIC_ENTRY, "base_url": None}]), "claude-entry")

    assert target.base_url


def test_the_rag_side_carries_no_vendor_url_literal():
    """The borrow is read from the SDK, so no default address may be copied into this repo."""
    from pathlib import Path

    from deerflow.knowledge import vlm_target as module

    source = Path(module.__file__).read_text(encoding="utf-8")

    assert "anthropic.com" not in source
    assert "deepseek.com" not in source
    assert "dashscope.aliyuncs.com" not in source


# ── the thinking-off declarations ride along (spec 2026-10-02 D1=甲′) ──────
# The caption request body's "thinking off" spelling is the entry's declaration read here,
# so both must arrive on the target: the declared `when_thinking_disabled` shape and whether
# the entry takes `reasoning_effort` at all. Undeclared means not sent.


def test_the_entrys_thinking_declarations_reach_the_target():
    from deerflow.knowledge.vlm_target import resolve_vlm_target

    entry = {
        **VL_ENTRY,
        "supports_reasoning_effort": True,
        "when_thinking_disabled": {"extra_body": {"chat_template_kwargs": {"enable_thinking": False}}},
    }

    target = resolve_vlm_target(_config([entry]), "vl-entry")

    assert target.supports_reasoning_effort is True
    assert target.disable_shape == {"extra_body": {"chat_template_kwargs": {"enable_thinking": False}}}


def test_an_entry_declaring_nothing_carries_no_thinking_declarations():
    from deerflow.knowledge.vlm_target import resolve_vlm_target

    target = resolve_vlm_target(_config([VL_ENTRY]), "vl-entry")

    assert target.supports_reasoning_effort is False
    assert target.disable_shape is None
