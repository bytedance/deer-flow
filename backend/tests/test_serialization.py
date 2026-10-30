"""Tests for deerflow.runtime.serialization."""

from __future__ import annotations


class _FakePydanticV2:
    """Object with model_dump (Pydantic v2)."""

    def model_dump(self):
        return {"key": "v2"}


class _FakePydanticV1:
    """Object with dict (Pydantic v1)."""

    def dict(self):
        return {"key": "v1"}


class _Unprintable:
    """Object whose str() raises."""

    def __str__(self):
        raise RuntimeError("no str")

    def __repr__(self):
        return "<Unprintable>"


def test_serialize_none():
    from deerflow.runtime.serialization import serialize_lc_object

    assert serialize_lc_object(None) is None


def test_serialize_primitives():
    from deerflow.runtime.serialization import serialize_lc_object

    assert serialize_lc_object("hello") == "hello"
    assert serialize_lc_object(42) == 42
    assert serialize_lc_object(3.14) == 3.14
    assert serialize_lc_object(True) is True


def test_serialize_dict():
    from deerflow.runtime.serialization import serialize_lc_object

    obj = {"a": _FakePydanticV2(), "b": [1, "two"]}
    result = serialize_lc_object(obj)
    assert result == {"a": {"key": "v2"}, "b": [1, "two"]}


def test_serialize_list():
    from deerflow.runtime.serialization import serialize_lc_object

    result = serialize_lc_object([_FakePydanticV1(), 1])
    assert result == [{"key": "v1"}, 1]


def test_serialize_tuple():
    from deerflow.runtime.serialization import serialize_lc_object

    result = serialize_lc_object((_FakePydanticV2(),))
    assert result == [{"key": "v2"}]


def test_serialize_pydantic_v2():
    from deerflow.runtime.serialization import serialize_lc_object

    assert serialize_lc_object(_FakePydanticV2()) == {"key": "v2"}


def test_serialize_pydantic_v1():
    from deerflow.runtime.serialization import serialize_lc_object

    assert serialize_lc_object(_FakePydanticV1()) == {"key": "v1"}


def test_serialize_fallback_str():
    from deerflow.runtime.serialization import serialize_lc_object

    result = serialize_lc_object(object())
    assert isinstance(result, str)


def test_serialize_fallback_repr():
    from deerflow.runtime.serialization import serialize_lc_object

    assert serialize_lc_object(_Unprintable()) == "<Unprintable>"


def test_serialize_channel_values_strips_pregel_keys():
    from deerflow.runtime.serialization import serialize_channel_values

    raw = {
        "messages": ["hello"],
        "__pregel_tasks": "internal",
        "__pregel_resuming": True,
        "__interrupt__": [{"value": "ask_human", "resumable": True}],
        "title": "Test",
    }
    result = serialize_channel_values(raw)
    assert "messages" in result
    assert "title" in result
    assert "__pregel_tasks" not in result
    assert "__pregel_resuming" not in result
    assert "__interrupt__" in result
    assert isinstance(result["__interrupt__"], list)
    assert len(result["__interrupt__"]) == 1
    assert result["__interrupt__"][0]["value"] == "ask_human"


def test_serialize_channel_values_serializes_objects():
    from deerflow.runtime.serialization import serialize_channel_values

    result = serialize_channel_values({"obj": _FakePydanticV2()})
    assert result == {"obj": {"key": "v2"}}


def test_serialize_messages_tuple():
    from deerflow.runtime.serialization import serialize_messages_tuple

    chunk = _FakePydanticV2()
    metadata = {"langgraph_node": "agent"}
    result = serialize_messages_tuple((chunk, metadata))
    assert result == [{"key": "v2"}, {"langgraph_node": "agent"}]


def test_serialize_messages_tuple_non_dict_metadata():
    from deerflow.runtime.serialization import serialize_messages_tuple

    result = serialize_messages_tuple((_FakePydanticV2(), "not-a-dict"))
    assert result == [{"key": "v2"}, {}]


def test_serialize_messages_tuple_fallback():
    from deerflow.runtime.serialization import serialize_messages_tuple

    result = serialize_messages_tuple("not-a-tuple")
    assert result == "not-a-tuple"


def test_serialize_dispatcher_messages_mode():
    from deerflow.runtime.serialization import serialize

    chunk = _FakePydanticV2()
    result = serialize((chunk, {"node": "x"}), mode="messages")
    assert result == [{"key": "v2"}, {"node": "x"}]


def test_serialize_dispatcher_values_mode():
    from deerflow.runtime.serialization import serialize

    result = serialize({"msg": "hi", "__pregel_tasks": "x"}, mode="values")
    assert result == {"msg": "hi"}


def test_serialize_dispatcher_default_mode():
    from deerflow.runtime.serialization import serialize

    result = serialize(_FakePydanticV1())
    assert result == {"key": "v1"}


# ── non-finite float normalization ───────────────────────────────────────────


class _FakePydanticWithNonFinite:
    """Object whose model_dump output carries a nested non-finite float.

    Mirrors a live LangChain message whose ``response_metadata`` holds a
    provider logprob of ``-inf`` for a zero-probability token.
    """

    def model_dump(self):
        return {"response_metadata": {"logprobs": {"token": float("-inf")}}}


def test_serialize_finite_floats_unchanged():
    from deerflow.runtime.serialization import serialize_lc_object

    assert serialize_lc_object(3.14) == 3.14
    assert serialize_lc_object([1.5, {"x": -2.0}]) == [1.5, {"x": -2.0}]


def test_serialize_non_finite_floats_normalized_to_none():
    import math

    from deerflow.runtime.serialization import serialize_lc_object

    assert serialize_lc_object(float("nan")) is None
    assert serialize_lc_object(float("inf")) is None
    assert serialize_lc_object(float("-inf")) is None
    result = serialize_lc_object({"a": float("inf"), "b": [float("nan"), 1.0]})
    assert result == {"a": None, "b": [None, 1.0]}
    assert all(not isinstance(v, float) or math.isfinite(v) for v in _iter_floats(result))


def test_serialize_recurses_into_model_dump_output():
    """A non-finite float inside a model_dump result must also be normalized."""
    from deerflow.runtime.serialization import serialize_lc_object

    result = serialize_lc_object(_FakePydanticWithNonFinite())
    assert result == {"response_metadata": {"logprobs": {"token": None}}}


def test_serialize_channel_values_json_safe_for_both_wires():
    """Serialized channel values must survive a strict (allow_nan=False) encoder."""
    import json

    from deerflow.runtime.serialization import serialize_channel_values_for_api

    raw = {
        "messages": [{"type": "ai", "content": "hi", "response_metadata": {"logprobs": {"t": float("-inf")}}}],
        "some_metric": float("nan"),
    }
    result = serialize_channel_values_for_api(raw)
    # Strict encoding mirrors Starlette's JSONResponse.render (REST path).
    json.dumps(result, allow_nan=False)
    # Strict decoding mirrors the JS useStream / langgraph-sdk SSE parser.
    encoded = json.dumps(result)
    json.loads(encoded, parse_constant=_reject_constant)


def test_serialize_messages_mode_json_safe():
    import json

    from deerflow.runtime.serialization import serialize

    # Both halves of the tuple must be JSON-safe: the chunk carries the
    # non-finite in model_dump output, the metadata in caller-supplied run
    # metadata (merged into messages-mode frames by LangGraph).
    payload = serialize(
        (_FakePydanticWithNonFinite(), {"node": "model", "metric": float("-inf")}),
        mode="messages",
    )
    assert payload[1]["metric"] is None
    json.dumps(payload, allow_nan=False)
    json.loads(json.dumps(payload), parse_constant=_reject_constant)


def test_serialize_messages_tuple_metadata_non_finite_floats_normalized():
    """The metadata half of a messages-mode tuple rides the same wire as the
    chunk: non-finite floats nested there must be normalized too (#7669), not
    emitted as bare ``NaN`` / ``Infinity`` tokens."""
    import json

    from deerflow.runtime.serialization import serialize_messages_tuple

    metadata = {
        "langgraph_node": "agent",
        "langgraph_step": 1,
        "stats": {"score": float("inf"), "delta": float("nan")},
    }
    result = serialize_messages_tuple(({"content": "hi"}, metadata))
    assert result[1] == {
        "langgraph_node": "agent",
        "langgraph_step": 1,
        "stats": {"score": None, "delta": None},
    }
    # Strict encoding mirrors Starlette's JSONResponse; strict decoding
    # mirrors the JS useStream / langgraph-sdk SSE parser.
    json.dumps(result, allow_nan=False)
    json.loads(json.dumps(result), parse_constant=_reject_constant)


def test_serialize_messages_mode_json_safe_metadata():
    """At the dispatcher level metadata gets the same canonical treatment as
    the chunk: tuples become lists (their JSON shape anyway) and nested
    objects are recursively serialized."""
    import json

    from deerflow.runtime.serialization import serialize

    payload = serialize(
        (
            {"content": "hi"},
            {
                "langgraph_node": "agent",
                "langgraph_triggers": ("branch:to:agent",),
                "nested": {"obj": _FakePydanticV2(), "floor": float("-inf")},
            },
        ),
        mode="messages",
    )
    assert payload[1]["langgraph_node"] == "agent"
    assert payload[1]["langgraph_triggers"] == ["branch:to:agent"]
    assert payload[1]["nested"] == {"obj": {"key": "v2"}, "floor": None}
    json.dumps(payload, allow_nan=False)
    json.loads(json.dumps(payload), parse_constant=_reject_constant)


def _reject_constant(token):
    raise ValueError(f"non-finite JSON token: {token}")


def _iter_floats(obj):
    if isinstance(obj, float):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _iter_floats(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from _iter_floats(v)


# ── strip_data_url_image_blocks ──────────────────────────────────────────────


def _make_msg(
    content,
    *,
    hide_from_ui=False,
    msg_type="human",
):
    """Build a serialised-style message dict."""
    msg = {"type": msg_type, "content": content}
    if hide_from_ui:
        msg["additional_kwargs"] = {"hide_from_ui": True}
    return msg


def test_strip_data_url_removes_base64_from_hidden_messages():
    from deerflow.runtime.serialization import strip_data_url_image_blocks

    messages = [
        _make_msg(
            [
                {"type": "text", "text": "Here are the images:"},
                {
                    "type": "image_url",
                    "image_url": {"url": "data:image/png;base64,iVBOR..."},
                },
                {"type": "text", "text": "- file.jpg (image/jpeg)"},
                {
                    "type": "image_url",
                    "image_url": {"url": "data:image/jpeg;base64,/9j/..."},
                },
            ],
            hide_from_ui=True,
        ),
    ]
    result = strip_data_url_image_blocks(messages)
    assert len(result) == 1
    content = result[0]["content"]
    # Only text blocks remain
    assert content == [
        {"type": "text", "text": "Here are the images:"},
        {"type": "text", "text": "- file.jpg (image/jpeg)"},
    ]


def test_strip_data_url_preserves_non_hidden_messages():
    from deerflow.runtime.serialization import strip_data_url_image_blocks

    messages = [
        _make_msg(
            [
                {"type": "text", "text": "Check this out"},
                {
                    "type": "image_url",
                    "image_url": {"url": "data:image/png;base64,iVBOR..."},
                },
            ],
            hide_from_ui=False,
        ),
    ]
    result = strip_data_url_image_blocks(messages)
    assert result == messages


def test_strip_data_url_preserves_https_image_urls():
    from deerflow.runtime.serialization import strip_data_url_image_blocks

    messages = [
        _make_msg(
            [
                {"type": "text", "text": "See image"},
                {
                    "type": "image_url",
                    "image_url": {"url": "https://example.com/img.png"},
                },
            ],
            hide_from_ui=True,
        ),
    ]
    result = strip_data_url_image_blocks(messages)
    assert result == messages


def test_strip_data_url_handles_string_content():
    from deerflow.runtime.serialization import strip_data_url_image_blocks

    messages = [
        _make_msg("plain text content", hide_from_ui=True),
    ]
    result = strip_data_url_image_blocks(messages)
    assert result == messages


def test_strip_data_url_handles_non_dict_messages():
    from deerflow.runtime.serialization import strip_data_url_image_blocks

    result = strip_data_url_image_blocks(["a_string", None, 42])
    assert result == ["a_string", None, 42]


def test_strip_data_url_mixed_messages():
    """A realistic mix: normal user message + hidden image injection + AI reply."""
    from deerflow.runtime.serialization import strip_data_url_image_blocks

    messages = [
        _make_msg("Please analyze this image", hide_from_ui=False),
        _make_msg(
            [
                {"type": "text", "text": "Here are the images:"},
                {
                    "type": "image_url",
                    "image_url": {"url": "data:image/png;base64,AABBCCDD"},
                },
            ],
            hide_from_ui=True,
        ),
        _make_msg("I can see a landscape", msg_type="ai"),
    ]
    result = strip_data_url_image_blocks(messages)
    assert len(result) == 3
    # First message untouched
    assert result[0]["content"] == "Please analyze this image"
    # Hidden message: image_url stripped, text kept
    assert result[1]["content"] == [{"type": "text", "text": "Here are the images:"}]
    # AI message untouched
    assert result[2]["content"] == "I can see a landscape"


def test_serialize_channel_values_for_api_strips_base64():
    from deerflow.runtime.serialization import serialize_channel_values_for_api

    channel_values = {
        "messages": [
            {
                "type": "human",
                "content": "hello",
            },
            {
                "type": "human",
                "content": [
                    {"type": "text", "text": "images:"},
                    {
                        "type": "image_url",
                        "image_url": {"url": "data:image/png;base64,BIGDATA"},
                    },
                ],
                "additional_kwargs": {"hide_from_ui": True},
            },
        ],
        "title": "My thread",
    }
    result = serialize_channel_values_for_api(channel_values)
    assert result["title"] == "My thread"
    assert len(result["messages"]) == 2
    assert result["messages"][0]["content"] == "hello"
    # base64 block stripped, text block kept
    assert result["messages"][1]["content"] == [{"type": "text", "text": "images:"}]


def test_serialize_channel_values_for_api_no_messages():
    """When channel_values has no messages key, returns without error."""
    from deerflow.runtime.serialization import serialize_channel_values_for_api

    result = serialize_channel_values_for_api({"title": "empty"})
    assert result == {"title": "empty"}


def test_serialize_values_mode_strips_base64_from_hidden_messages():
    """The SSE stream emits ``values`` snapshots of the full state, so it must
    strip base64 image data from hide_from_ui messages just like the REST
    endpoints do — otherwise the same payload leaks over the stream."""
    import json

    from deerflow.runtime.serialization import serialize

    state = {
        "messages": [
            _make_msg(
                [
                    {"type": "text", "text": "context"},
                    {
                        "type": "image_url",
                        "image_url": {"url": "data:image/png;base64,iVBOR..."},
                    },
                ],
                hide_from_ui=True,
            ),
        ],
    }
    result = serialize(state, mode="values")
    # the hidden message survives (count/order preserved) but the data: block is gone
    assert len(result["messages"]) == 1
    assert "data:image/png;base64" not in json.dumps(result)
    assert result["messages"][0]["content"] == [{"type": "text", "text": "context"}]
