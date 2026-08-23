"""Neutral message-provenance metadata.

The host stamps which component produced an injected or rewritten message.
An observer cannot reconstruct this after the fact: by the time a message
reaches the model-call boundary, its producer is no longer recoverable.
"""

from deerflow_extension_api import (
    MESSAGE_CONTENT_KIND_KEY,
    MESSAGE_PRODUCER_ENTITY_ID_KEY,
    MESSAGE_PRODUCER_KIND_KEY,
    PROVENANCE_KEYS,
    ContentKind,
    provenance_kwargs,
    read_provenance,
)
from langchain_core.messages import HumanMessage, SystemMessage


def test_kwargs_round_trip_through_a_message():
    message = SystemMessage(
        content="reminder",
        additional_kwargs=provenance_kwargs(ContentKind.MIDDLEWARE_INJECTION, "dynamic_context"),
    )
    provenance = read_provenance(message)
    assert provenance is not None
    assert provenance.content_kind == "middleware_injection"
    assert provenance.producer_kind == "dynamic_context"
    assert provenance.producer_entity_id is None


def test_optional_fields_are_omitted_rather_than_written_as_none():
    kwargs = provenance_kwargs(ContentKind.MEMORY, "dynamic_context_memory")
    assert MESSAGE_PRODUCER_ENTITY_ID_KEY not in kwargs


def test_optional_fields_round_trip_when_supplied():
    message = HumanMessage(
        content="a durable-context data block",
        additional_kwargs=provenance_kwargs(
            ContentKind.DURABLE_CONTEXT,
            "durable_context_data",
            producer_entity_id="run-7",
        ),
    )
    provenance = read_provenance(message)
    assert provenance.producer_entity_id == "run-7"


def test_read_returns_none_for_an_unstamped_message():
    assert read_provenance(HumanMessage(content="hi")) is None


def test_read_returns_none_when_the_required_pair_is_incomplete():
    message = HumanMessage(content="hi", additional_kwargs={MESSAGE_CONTENT_KIND_KEY: "memory"})
    assert read_provenance(message) is None


def test_read_ignores_non_string_values_rather_than_raising():
    message = HumanMessage(
        content="hi",
        additional_kwargs={MESSAGE_CONTENT_KIND_KEY: 1, MESSAGE_PRODUCER_KIND_KEY: "x"},
    )
    assert read_provenance(message) is None


def test_every_key_is_declared_in_the_exported_set():
    assert PROVENANCE_KEYS == {
        MESSAGE_CONTENT_KIND_KEY,
        MESSAGE_PRODUCER_KIND_KEY,
        MESSAGE_PRODUCER_ENTITY_ID_KEY,
    }


def test_gateway_treats_every_provenance_key_as_server_owned():
    """A caller must not be able to forge provenance on an inbound message."""
    from app.gateway.services import _SERVER_OWNED_MESSAGE_METADATA_KEYS

    assert PROVENANCE_KEYS <= _SERVER_OWNED_MESSAGE_METADATA_KEYS


class TestDynamicContextStamping:
    """The date reminder and the recalled-memory block are distinct producers."""

    def _inject(self):
        from langchain_core.messages import HumanMessage

        from deerflow.agents.middlewares.dynamic_context_middleware import DynamicContextMiddleware

        middleware = DynamicContextMiddleware()
        return middleware._inject({"messages": [HumanMessage(content="hello", id="u1")]})

    def test_the_date_reminder_is_stamped_as_a_middleware_injection(self):
        messages = self._inject()["messages"]
        reminders = [m for m in messages if read_provenance(m) and read_provenance(m).content_kind == "middleware_injection"]
        assert reminders, "expected the date reminder to carry provenance"
        assert read_provenance(reminders[0]).producer_kind == "dynamic_context"

    def test_the_users_own_message_is_never_stamped(self):
        messages = self._inject()["messages"]
        user_messages = [m for m in messages if m.content == "hello"]
        assert user_messages
        assert all(read_provenance(m) is None for m in user_messages)


class TestDynamicContextMemoryStamping:
    """The recalled-memory block is a distinct producer from the date reminder."""

    def test_the_memory_block_is_stamped_as_memory(self, monkeypatch):
        from langchain_core.messages import HumanMessage

        from deerflow.agents.middlewares import dynamic_context_middleware as module

        monkeypatch.setattr(module.DynamicContextMiddleware, "_build_full_reminder", lambda self, runtime=None: ("<system-reminder></system-reminder>", "some recalled memory"))
        middleware = module.DynamicContextMiddleware()
        result = middleware._inject({"messages": [HumanMessage(content="hello", id="u1")]})
        memory_messages = [m for m in result["messages"] if str(m.id or "").endswith("__memory")]
        assert memory_messages, "expected a memory block message"
        provenance = read_provenance(memory_messages[0])
        assert provenance is not None
        assert provenance.content_kind == "memory"
        assert provenance.producer_kind == "dynamic_context_memory"


class TestDurableContextStamping:
    """The authority contract and the data block are distinct producers."""

    def _inject(self, *, summary_text: str = "a compacted summary"):
        from types import SimpleNamespace

        from langchain.agents.middleware.types import ModelRequest

        from deerflow.agents.middlewares.durable_context_middleware import DurableContextMiddleware

        middleware = DurableContextMiddleware()
        request = ModelRequest(
            model=SimpleNamespace(),
            messages=[],
            state={"summary_text": summary_text, "delegations": [], "skill_context": []},
        )
        return middleware._inject(request)

    def test_the_authority_contract_is_stamped_as_a_middleware_injection(self):
        from langchain_core.messages import SystemMessage

        result = self._inject()
        system_messages = [m for m in result.messages if isinstance(m, SystemMessage)]
        assert system_messages, "expected the authority-contract SystemMessage"
        provenance = read_provenance(system_messages[0])
        assert provenance is not None
        assert provenance.content_kind == "middleware_injection"
        assert provenance.producer_kind == "durable_context"

    def test_the_data_block_is_stamped_as_durable_context(self):
        result = self._inject()
        data_messages = [m for m in result.messages if "durable_context_data" in (m.additional_kwargs or {})]
        assert data_messages, "expected the durable-context data block"
        provenance = read_provenance(data_messages[0])
        assert provenance is not None
        assert provenance.content_kind == "durable_context"
        assert provenance.producer_kind == "durable_context_data"


class TestSystemMessageCoalescingStamping:
    """The coalesced leading SystemMessage is stamped as a middleware injection."""

    def test_the_coalesced_system_message_is_stamped(self):
        from types import SimpleNamespace

        from langchain.agents.middleware.types import ModelRequest
        from langchain_core.messages import SystemMessage

        from deerflow.agents.middlewares.system_message_coalescing_middleware import _coalesce_request

        request = ModelRequest(
            model=SimpleNamespace(),
            messages=[SystemMessage(content="extra system block")],
            system_message=SystemMessage(content="base system prompt"),
        )
        coalesced = _coalesce_request(request)
        assert coalesced is not None
        provenance = read_provenance(coalesced.system_message)
        assert provenance is not None
        assert provenance.content_kind == "middleware_injection"
        assert provenance.producer_kind == "system_coalescing"


class TestViewImageStamping:
    """The hidden image-details message is stamped as an image payload."""

    def test_the_image_context_message_is_stamped(self):
        from deerflow.agents.middlewares.view_image_middleware import ViewImageMiddleware

        message = ViewImageMiddleware._create_image_context_message(["some image content"])
        provenance = read_provenance(message)
        assert provenance is not None
        assert provenance.content_kind == "image_payload"
        assert provenance.producer_kind == "view_image"


class TestSkillActivationStamping:
    """The hidden slash-skill activation reminder is stamped as a skill body."""

    def test_the_activation_message_is_stamped(self):
        from langchain_core.messages import HumanMessage

        from deerflow.agents.middlewares.skill_activation_middleware import SkillActivationMiddleware

        target = HumanMessage(content="/some-skill do the thing", id="u1")
        message = SkillActivationMiddleware._make_activation_message(target, "activation reminder text")
        provenance = read_provenance(message)
        assert provenance is not None
        assert provenance.content_kind == "skill_body"
        assert provenance.producer_kind == "skill_activation"


class TestStateWritesCannotForgeServerOwnedMetadata:
    """The run path strips these inside ``normalize_input``.

    ``POST /threads/{id}/state`` writes its values straight into a checkpoint,
    so without the same treatment an authenticated client can persist forged
    provenance and transform trails — and these keys exist precisely so a later
    reader can treat them as facts about what the host did. Membership of the
    key in a frozenset proves nothing on its own; these drive the stripper.
    """

    @staticmethod
    def _forged() -> dict:
        from deerflow.agents.middlewares.tool_transform_meta import TOOL_TRANSFORMS_KEY

        return {
            MESSAGE_CONTENT_KIND_KEY: "memory",
            MESSAGE_PRODUCER_KIND_KEY: "dynamic_context_memory",
            TOOL_TRANSFORMS_KEY: [{"kind": "sanitized", "by": "ToolResultSanitizationMiddleware", "version": "1"}],
            "hide_from_ui": True,
        }

    def test_a_forged_message_object_is_stripped(self):
        from langchain_core.messages import HumanMessage

        from app.gateway.services import strip_server_owned_state_metadata

        values = {"messages": [HumanMessage(content="looks recalled", additional_kwargs=self._forged())]}
        cleaned = strip_server_owned_state_metadata(values)["messages"][0]

        assert not (PROVENANCE_KEYS & set(cleaned.additional_kwargs))
        assert "deerflow_tool_transforms" not in cleaned.additional_kwargs
        # Caller-owned keys must survive — this strips forgeries, not payload.
        assert cleaned.additional_kwargs["hide_from_ui"] is True
        assert cleaned.content == "looks recalled"

    def test_a_forged_raw_dict_is_stripped(self):
        """The route forwards whatever the caller sent; it is not always coerced."""
        from app.gateway.services import strip_server_owned_state_metadata

        values = {"messages": [{"type": "human", "content": "looks recalled", "additional_kwargs": self._forged()}]}
        cleaned = strip_server_owned_state_metadata(values)["messages"][0]

        assert not (PROVENANCE_KEYS & set(cleaned["additional_kwargs"]))
        assert "deerflow_tool_transforms" not in cleaned["additional_kwargs"]
        assert cleaned["additional_kwargs"]["hide_from_ui"] is True

    def test_unrelated_channels_pass_through_unchanged(self):
        from app.gateway.services import strip_server_owned_state_metadata

        values = {"title": "a thread", "todos": [{"content": "x", "status": "pending"}]}
        assert strip_server_owned_state_metadata(values) == values

    def test_the_state_route_actually_calls_the_stripper(self):
        """A stripper nothing calls is the same defect in a new place."""
        import ast
        from pathlib import Path

        route = Path(__file__).resolve().parents[1] / "app/gateway/routers/threads.py"
        called = {node.func.id for node in ast.walk(ast.parse(route.read_text(encoding="utf-8"))) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}

        assert "strip_server_owned_state_metadata" in called
