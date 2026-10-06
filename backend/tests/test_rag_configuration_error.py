"""A configuration-class refusal reaches the caller readably (spec 2026-09-16 §3 D4).

``build_embedder``'s refusals used to surface as a bare ``500 Internal Server Error``: the
gateway registers no handler for plain ``ValueError``, so the actionable Chinese message stayed
in the server log and the admin got nothing. One dedicated type plus one handler fixes that for
every HTTP path — including the ones that only build an embedder when a request arrives — and
deliberately does **not** turn unrelated ``ValueError``\\ s into 400s.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from deerflow.knowledge.embedder import RagConfigurationError, SparseHalfMissingError

_MESSAGE = "嵌入 provider 'openai-compatible' 只输出稠密向量 ⇒ 请改为「独立稀疏服务」或「本地 BM25」。"


def test_the_refusal_type_is_a_value_error():
    """Callers that already catch ``ValueError`` keep working, and so do the existing tests."""
    assert issubclass(RagConfigurationError, ValueError)


@pytest.fixture(scope="module")
def gateway_handlers():
    from app.gateway.app import create_app

    return create_app().exception_handlers


def test_the_gateway_registers_a_handler_for_this_type_and_nothing_broader(gateway_handlers):
    assert RagConfigurationError in gateway_handlers
    # The narrowness is the point: a handler for the base class would report every unrelated
    # programming error as a client-side 400.
    assert ValueError not in gateway_handlers


def test_the_registered_handler_answers_400_with_the_message(gateway_handlers):
    """Exercised over real HTTP, on a bare app carrying the gateway's own handler.

    A live gateway route cannot trigger this without a knowledge base fixture, so the app here
    is minimal on purpose: what is under test is that the registered callable maps the type to a
    readable 400, not the route that happens to raise it.
    """
    probe = FastAPI()
    probe.add_exception_handler(RagConfigurationError, gateway_handlers[RagConfigurationError])

    @probe.get("/boom")
    def _boom() -> None:
        raise RagConfigurationError(_MESSAGE)

    with TestClient(probe) as client:
        response = client.get("/boom")

    assert response.status_code == 400
    assert response.json()["detail"] == _MESSAGE


def test_the_empty_sparse_refusal_inherits_that_mapping(gateway_handlers):
    """The run-time guard's narrower type is answered the same way, with no second registration."""
    probe = FastAPI()
    probe.add_exception_handler(RagConfigurationError, gateway_handlers[RagConfigurationError])

    @probe.get("/boom")
    def _boom() -> None:
        raise SparseHalfMissingError(_MESSAGE)

    with TestClient(probe) as client:
        response = client.get("/boom")

    assert response.status_code == 400
    assert response.json()["detail"] == _MESSAGE


# ── C-1: one copy strategy, both languages (spec 2026-09-30 D2, ② 已裁＝乙) ────


def test_the_bilingual_helper_is_the_one_copy_shape():
    """Every configuration-class refusal carries both languages, joined by ` / ` — the admin
    reads one line whichever locale they work in (the frontend renders `detail` verbatim)."""
    from deerflow.knowledge.messages import bilingual

    assert bilingual("中文", "English") == "中文 / English"


def test_the_previously_english_members_gained_a_chinese_half():
    """The audit-② resolution: `Model … not found in config` used to be English-only, so the
    family stayed mixed even after the Chinese members were made readable."""
    from deerflow.knowledge.model_target import model_not_found_message

    assert model_not_found_message("ghost-entry") == "配置里没有模型「ghost-entry」 / Model ghost-entry not found in config"
