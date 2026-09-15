import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.gateway.routers import input_polish
from deerflow.utils import oneshot_llm


def _config(
    *,
    enabled: bool = True,
    max_chars: int = 4000,
    model_name: str | None = None,
):
    return SimpleNamespace(
        input_polish=SimpleNamespace(
            enabled=enabled,
            max_chars=max_chars,
            model_name=model_name,
        ),
    )


def test_clean_rewritten_text_removes_think_and_fence():
    text = "<think>reasoning</think>\n```text\nrewrite this\n```"
    assert input_polish._clean_rewritten_text(text) == "rewrite this"


def test_clean_rewritten_text_keeps_literal_think_tag():
    # A polished draft may legitimately mention the <think> tag. The cleaner
    # must not truncate at the dangling open tag (which would drop the rest of
    # the rewrite and can surface as a spurious 503).
    text = "Explain what the <think> tag does in reasoning models."
    assert input_polish._clean_rewritten_text(text) == "Explain what the <think> tag does in reasoning models."


def test_polish_input_uses_config_model_and_preserves_response(monkeypatch):
    request = input_polish.InputPolishRequest(
        text="/web-dev 做一个页面",
        locale="zh-CN",
        thread_id="thread-1",
    )
    fake_model = MagicMock()
    fake_model.ainvoke = AsyncMock(return_value=MagicMock(content="/web-dev 请设计并实现一个视觉精致的页面。"))

    create_chat_model = MagicMock(return_value=fake_model)
    monkeypatch.setattr(oneshot_llm, "create_chat_model", create_chat_model)
    config = _config(model_name="polish-model")

    result = asyncio.run(
        input_polish.polish_input.__wrapped__(
            request,
            request=None,
            config=config,
        ),
    )

    assert result.rewritten_text == "/web-dev 请设计并实现一个视觉精致的页面。"
    assert result.changed is True
    create_chat_model.assert_called_once_with(
        name="polish-model",
        thinking_enabled=False,
        app_config=config,
    )
    fake_model.ainvoke.assert_awaited_once()
    assert fake_model.ainvoke.await_args.kwargs["config"]["run_name"] == "input_polish"


def test_polish_input_uses_default_model_when_config_model_is_missing(monkeypatch):
    request = input_polish.InputPolishRequest(text="make this clearer")
    fake_model = MagicMock()
    fake_model.ainvoke = AsyncMock(return_value=MagicMock(content="Make this clearer."))

    create_chat_model = MagicMock(return_value=fake_model)
    monkeypatch.setattr(oneshot_llm, "create_chat_model", create_chat_model)

    result = asyncio.run(
        input_polish.polish_input.__wrapped__(
            request,
            request=None,
            config=_config(model_name=None),
        ),
    )

    assert result.rewritten_text == "Make this clearer."
    create_chat_model.assert_called_once()
    assert create_chat_model.call_args.kwargs["name"] is None


def test_polish_input_returns_404_when_disabled(monkeypatch):
    request = input_polish.InputPolishRequest(text="hello")
    fake_model = MagicMock()
    monkeypatch.setattr(oneshot_llm, "create_chat_model", fake_model)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            input_polish.polish_input.__wrapped__(
                request,
                request=None,
                config=_config(enabled=False),
            ),
        )

    assert exc_info.value.status_code == 404
    fake_model.assert_not_called()


def test_polish_input_rejects_empty_or_too_long_input(monkeypatch):
    fake_model = MagicMock()
    monkeypatch.setattr(oneshot_llm, "create_chat_model", fake_model)

    with pytest.raises(HTTPException) as empty_exc:
        asyncio.run(
            input_polish.polish_input.__wrapped__(
                input_polish.InputPolishRequest(text="  "),
                request=None,
                config=_config(),
            ),
        )
    assert empty_exc.value.status_code == 400

    with pytest.raises(HTTPException) as long_exc:
        asyncio.run(
            input_polish.polish_input.__wrapped__(
                input_polish.InputPolishRequest(text="hello"),
                request=None,
                config=_config(max_chars=4),
            ),
        )
    assert long_exc.value.status_code == 400
    fake_model.assert_not_called()


def test_polish_input_returns_503_on_model_error(monkeypatch):
    request = input_polish.InputPolishRequest(text="hello")
    fake_model = MagicMock()
    fake_model.ainvoke = AsyncMock(side_effect=RuntimeError("boom"))
    monkeypatch.setattr(oneshot_llm, "create_chat_model", MagicMock(return_value=fake_model))

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            input_polish.polish_input.__wrapped__(
                request,
                request=None,
                config=_config(),
            ),
        )

    assert exc_info.value.status_code == 503


def test_polish_input_rejects_whitespace_only_draft(monkeypatch):
    # A padded draft that is empty after normalization is rejected as empty,
    # matching the normalized view used for the model input.
    fake_model = MagicMock()
    monkeypatch.setattr(oneshot_llm, "create_chat_model", fake_model)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            input_polish.polish_input.__wrapped__(
                input_polish.InputPolishRequest(text="   \n\t  "),
                request=None,
                config=_config(),
            ),
        )

    assert exc_info.value.status_code == 400
    fake_model.assert_not_called()


def test_polish_input_validates_and_sends_normalized_text(monkeypatch):
    # The length boundary and the model input must agree on one normalized view:
    # a draft whose raw length exceeds max_chars only due to padding is accepted
    # (strip fits), and the model receives the stripped text, not the padding.
    raw_draft = "   summarize report   "  # 22 chars raw, 16 chars stripped
    fake_model = MagicMock()
    fake_model.ainvoke = AsyncMock(return_value=MagicMock(content="Please summarize the report clearly."))
    monkeypatch.setattr(oneshot_llm, "create_chat_model", MagicMock(return_value=fake_model))

    result = asyncio.run(
        input_polish.polish_input.__wrapped__(
            input_polish.InputPolishRequest(text=raw_draft),
            request=None,
            config=_config(max_chars=len(raw_draft.strip())),
        ),
    )

    assert result.rewritten_text == "Please summarize the report clearly."
    messages = fake_model.ainvoke.await_args.args[0]
    human_content = messages[-1].content
    assert "summarize report" in human_content
    assert "   summarize report   " not in human_content
