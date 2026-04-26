"""
Unit tests for MindIEChatModel adapter.
"""

from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult

# ── Import the module under test ──────────────────────────────────────────────
from deerflow.models.mindie_provider import (
    MindIEChatModel,
    _fix_messages,
    _parse_xml_tool_call_to_dict,
)

# ═════════════════════════════════════════════════════════════════════════════
# Helpers
# ═════════════════════════════════════════════════════════════════════════════


def _make_chat_result(content: str, tool_calls=None) -> ChatResult:
    msg = AIMessage(content=content)
    if tool_calls:
        msg.tool_calls = tool_calls
    gen = ChatGeneration(message=msg)
    return ChatResult(generations=[gen])


# ═════════════════════════════════════════════════════════════════════════════
# 1.  _fix_messages
# ═════════════════════════════════════════════════════════════════════════════


class TestFixMessages:
    # ── list content → str ────────────────────────────────────────────────────

    def test_list_content_extracted_to_str(self):
        msg = HumanMessage(
            content=[
                {"type": "text", "text": "Hello"},
                {"type": "text", "text": " world"},
            ]
        )
        result = _fix_messages([msg])
        assert result[0].content == "Hello world"

    def test_list_content_ignores_non_text_blocks(self):
        msg = HumanMessage(
            content=[
                {"type": "image_url", "image_url": "http://x.com/img.png"},
                {"type": "text", "text": "caption"},
            ]
        )
        result = _fix_messages([msg])
        assert result[0].content == "caption"

    def test_empty_list_content_becomes_space(self):
        msg = HumanMessage(content=[])
        result = _fix_messages([msg])
        assert result[0].content == " "

    # ── plain str content ─────────────────────────────────────────────────────

    def test_plain_string_content_preserved(self):
        msg = HumanMessage(content="hi there")
        result = _fix_messages([msg])
        assert result[0].content == "hi there"

    def test_empty_string_content_becomes_space(self):
        msg = HumanMessage(content="")
        result = _fix_messages([msg])
        assert result[0].content == " "

    # ── AIMessage with tool_calls → XML ───────────────────────────────────────

    def test_ai_message_with_tool_calls_serialised_to_xml(self):
        msg = AIMessage(
            content="Sure",
            tool_calls=[
                {
                    "name": "get_weather",
                    "args": {"city": "London"},
                    "id": "call_abc",
                }
            ],
        )
        result = _fix_messages([msg])
        out = result[0]
        assert isinstance(out, AIMessage)
        assert "<tool_call>" in out.content
        assert "<function=get_weather>" in out.content
        assert "<parameter=city>London</parameter>" in out.content
        assert not getattr(out, "tool_calls", [])

    def test_ai_message_text_preserved_before_xml(self):
        msg = AIMessage(
            content="Here you go",
            tool_calls=[{"name": "search", "args": {"q": "pytest"}, "id": "x"}],
        )
        result = _fix_messages([msg])
        assert result[0].content.startswith("Here you go")

    def test_ai_message_multiple_tool_calls(self):
        msg = AIMessage(
            content="",
            tool_calls=[
                {"name": "tool_a", "args": {"x": 1}, "id": "id1"},
                {"name": "tool_b", "args": {"y": 2}, "id": "id2"},
            ],
        )
        result = _fix_messages([msg])
        content = result[0].content
        assert content.count("<tool_call>") == 2
        assert "<function=tool_a>" in content
        assert "<function=tool_b>" in content

    def test_ai_message_tool_args_are_xml_escaped(self):
        msg = AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "fn<&>",
                    "args": {"k<&>": "v<&>"},
                    "id": "id1",
                }
            ],
        )
        result = _fix_messages([msg])
        content = result[0].content
        assert "<function=fn&lt;&amp;&gt;>" in content
        assert "<parameter=k&lt;&amp;&gt;>v&lt;&amp;&gt;</parameter>" in content

    # ── ToolMessage → HumanMessage ────────────────────────────────────────────

    def test_tool_message_becomes_human_message(self):
        msg = ToolMessage(content="42 degrees", tool_call_id="call_abc")
        result = _fix_messages([msg])
        out = result[0]
        assert isinstance(out, HumanMessage)
        assert "<tool_response>" in out.content
        assert "42 degrees" in out.content

    def test_tool_message_with_list_content(self):
        msg = ToolMessage(
            content=[{"type": "text", "text": "result"}],
            tool_call_id="call_xyz",
        )
        result = _fix_messages([msg])
        assert isinstance(result[0], HumanMessage)
        assert "result" in result[0].content

    # ── Mixed message list ────────────────────────────────────────────────────

    def test_mixed_message_types_ordering_preserved(self):
        msgs = [
            HumanMessage(content="q"),
            AIMessage(content="a"),
            ToolMessage(content="tool out", tool_call_id="c1"),
            HumanMessage(content="follow up"),
        ]
        result = _fix_messages(msgs)
        assert len(result) == 4
        assert isinstance(result[2], HumanMessage)
        assert result[3].content == "follow up"

    # ── SystemMessage pass-through ────────────────────────────────────────────

    def test_system_message_passed_through_unchanged(self):
        msg = SystemMessage(content="You are helpful.")
        result = _fix_messages([msg])
        assert result[0].content == "You are helpful."


# ═════════════════════════════════════════════════════════════════════════════
# 2.  _parse_xml_tool_call_to_dict
# ═════════════════════════════════════════════════════════════════════════════


class TestParseXmlToolCalls:
    def test_no_tool_call_returns_original(self):
        content = "Just a normal reply."
        clean, calls = _parse_xml_tool_call_to_dict(content)
        assert clean == content
        assert calls == []

    def test_single_tool_call_parsed(self):
        content = "<tool_call> <function=search> <parameter=query>pytest</parameter> </function> </tool_call>"
        clean, calls = _parse_xml_tool_call_to_dict(content)
        assert clean == ""
        assert len(calls) == 1
        assert calls[0]["name"] == "search"
        assert calls[0]["args"]["query"] == "pytest"
        assert calls[0]["id"].startswith("call_")

    def test_multiple_tool_calls_parsed(self):
        content = "<tool_call><function=a><parameter=x>1</parameter></function></tool_call><tool_call><function=b><parameter=y>2</parameter></function></tool_call>"
        _, calls = _parse_xml_tool_call_to_dict(content)
        assert len(calls) == 2
        assert calls[0]["name"] == "a"
        assert calls[1]["name"] == "b"

    def test_nested_tool_call_blocks_do_not_break_parsing(self):
        content = "<tool_call><function=outer><parameter=q>1</parameter><tool_call><function=inner><parameter=x>2</parameter></function></tool_call></function></tool_call>"
        clean, calls = _parse_xml_tool_call_to_dict(content)
        assert clean == ""
        assert len(calls) == 1
        assert calls[0]["name"] == "outer"
        assert calls[0]["args"] == {"q": 1}
        assert "x" not in calls[0]["args"]

    def test_text_before_tool_call_preserved(self):
        content = "Here is the answer.\n<tool_call><function=f><parameter=k>v</parameter></function></tool_call>"
        clean, calls = _parse_xml_tool_call_to_dict(content)
        assert clean == "Here is the answer."
        assert len(calls) == 1

    def test_integer_param_deserialised(self):
        content = "<tool_call><function=f><parameter=n>42</parameter></function></tool_call>"
        _, calls = _parse_xml_tool_call_to_dict(content)
        assert calls[0]["args"]["n"] == 42

    def test_list_param_deserialised(self):
        content = '<tool_call><function=f><parameter=lst>["a","b"]</parameter></function></tool_call>'
        _, calls = _parse_xml_tool_call_to_dict(content)
        assert calls[0]["args"]["lst"] == ["a", "b"]

    def test_dict_param_deserialised(self):
        content = '<tool_call><function=f><parameter=d>{"k": 1}</parameter></function></tool_call>'
        _, calls = _parse_xml_tool_call_to_dict(content)
        assert calls[0]["args"]["d"] == {"k": 1}

    def test_bool_param_deserialised(self):
        content = "<tool_call><function=f><parameter=flag>true</parameter></function></tool_call>"
        _, calls = _parse_xml_tool_call_to_dict(content)
        assert calls[0]["args"]["flag"] is True

    def test_malformed_param_stays_string(self):
        content = "<tool_call><function=f><parameter=bad>{broken json</parameter></function></tool_call>"
        _, calls = _parse_xml_tool_call_to_dict(content)
        assert calls[0]["args"]["bad"] == "{broken json"

    def test_non_string_input_returned_as_is(self):
        result = _parse_xml_tool_call_to_dict(None)
        assert result == (None, [])

    def test_unique_ids_generated(self):
        block = "<tool_call><function=f><parameter=k>v</parameter></function></tool_call>"
        _, c1 = _parse_xml_tool_call_to_dict(block)
        _, c2 = _parse_xml_tool_call_to_dict(block)
        assert c1[0]["id"] != c2[0]["id"]

    def test_escaped_entities_are_unescaped(self):
        content = "<tool_call><function=fn&lt;&amp;&gt;><parameter=k&lt;&amp;&gt;>v&lt;&amp;&gt;</parameter></function></tool_call>"
        _, calls = _parse_xml_tool_call_to_dict(content)
        assert calls[0]["name"] == "fn<&>"
        assert calls[0]["args"]["k<&>"] == "v<&>"


# ═════════════════════════════════════════════════════════════════════════════
# 3.  MindIEChatModel._patch_result_with_tools
# ═════════════════════════════════════════════════════════════════════════════


class TestPatchResult:
    def _model(self):
        with patch.object(MindIEChatModel, "__init__", return_value=None):
            m = MindIEChatModel.__new__(MindIEChatModel)
        return m

    def test_escaped_newlines_fixed(self):
        model = self._model()
        result = _make_chat_result("line1\\nline2")
        patched = model._patch_result_with_tools(result)
        assert patched.generations[0].message.content == "line1\nline2"

    def test_escaped_newlines_inside_code_fence_preserved(self):
        model = self._model()
        result = _make_chat_result('text\\n```json\n{"k":"a\\\\nb"}\n```\\nend')
        patched = model._patch_result_with_tools(result)
        assert patched.generations[0].message.content == 'text\n```json\n{"k":"a\\\\nb"}\n```\nend'

    def test_xml_tool_calls_extracted(self):
        model = self._model()
        content = "<tool_call><function=calc><parameter=expr>1+1</parameter></function></tool_call>"
        result = _make_chat_result(content)
        patched = model._patch_result_with_tools(result)
        msg = patched.generations[0].message
        assert msg.content == ""
        assert len(msg.tool_calls) == 1
        assert msg.tool_calls[0]["name"] == "calc"

    def test_patch_result_appends_to_existing_tool_calls(self):
        model = self._model()
        existing = [{"name": "existing", "args": {}, "id": "e1"}]
        content = "<tool_call><function=new_tool><parameter=k>v</parameter></function></tool_call>"
        result = _make_chat_result(content, tool_calls=existing)
        patched = model._patch_result_with_tools(result)
        msg = patched.generations[0].message
        assert len(msg.tool_calls) == 2
        names = [tc["name"] for tc in msg.tool_calls]
        assert "existing" in names
        assert "new_tool" in names

    def test_no_tool_call_content_unchanged(self):
        model = self._model()
        result = _make_chat_result("plain reply")
        patched = model._patch_result_with_tools(result)
        assert patched.generations[0].message.content == "plain reply"

    def test_non_string_content_skipped(self):
        model = self._model()
        msg = AIMessage(content=[{"type": "text", "text": "hi"}])
        gen = ChatGeneration(message=msg)
        result = ChatResult(generations=[gen])
        patched = model._patch_result_with_tools(result)
        assert patched is not None


class TestMindIEInit:
    def test_timeout_kwargs_are_normalized(self):
        captured = {}

        def fake_init(self, **kwargs):
            captured.update(kwargs)

        with patch("deerflow.models.mindie_provider.ChatOpenAI.__init__", new=fake_init):
            MindIEChatModel(
                model="mindie-test",
                api_key="test-key",
                connect_timeout=1.0,
                read_timeout=2.0,
                write_timeout=3.0,
                pool_timeout=4.0,
            )

        timeout = captured.get("timeout")
        assert timeout is not None
        assert timeout.connect == 1.0
        assert timeout.read == 2.0
        assert timeout.write == 3.0
        assert timeout.pool == 4.0

    def test_explicit_timeout_takes_precedence(self):
        captured = {}

        def fake_init(self, **kwargs):
            captured.update(kwargs)

        with patch("deerflow.models.mindie_provider.ChatOpenAI.__init__", new=fake_init):
            MindIEChatModel(
                model="mindie-test",
                api_key="test-key",
                timeout=9.0,
                connect_timeout=1.0,
                read_timeout=2.0,
                write_timeout=3.0,
                pool_timeout=4.0,
            )

        assert captured.get("timeout") == 9.0


# ═════════════════════════════════════════════════════════════════════════════
# 4.  MindIEChatModel._generate  (sync)
# ═════════════════════════════════════════════════════════════════════════════


class TestGenerate:
    def test_generate_calls_fix_messages_and_patch(self):
        with patch("deerflow.models.mindie_provider.ChatOpenAI._generate") as mock_super_gen, patch.object(MindIEChatModel, "__init__", return_value=None):
            mock_super_gen.return_value = _make_chat_result("hello")
            model = MindIEChatModel.__new__(MindIEChatModel)

            msgs = [HumanMessage(content="ping")]
            result = model._generate(msgs)

            assert mock_super_gen.called
            called_msgs = mock_super_gen.call_args[0][0]
            assert all(isinstance(m.content, str) for m in called_msgs)
            assert result.generations[0].message.content == "hello"


# ═════════════════════════════════════════════════════════════════════════════
# 5.  MindIEChatModel._agenerate  (async)
# ═════════════════════════════════════════════════════════════════════════════


class TestAGenerate:
    @pytest.mark.asyncio
    async def test_agenerate_patches_result(self):
        with patch("deerflow.models.mindie_provider.ChatOpenAI._agenerate", new_callable=AsyncMock) as mock_ag, patch.object(MindIEChatModel, "__init__", return_value=None):
            mock_ag.return_value = _make_chat_result("world\\nfoo")
            model = MindIEChatModel.__new__(MindIEChatModel)

            result = await model._agenerate([HumanMessage(content="hi")])
            assert result.generations[0].message.content == "world\nfoo"


# ═════════════════════════════════════════════════════════════════════════════
# 6.  MindIEChatModel._astream  (async generator)
# ═════════════════════════════════════════════════════════════════════════════


class TestAStream:
    async def _collect(self, gen):
        chunks = []
        async for chunk in gen:
            chunks.append(chunk)
        return chunks

    @pytest.mark.asyncio
    async def test_no_tools_uses_real_stream(self):
        from langchain_core.messages import AIMessageChunk
        from langchain_core.outputs import ChatGenerationChunk

        async def fake_stream(*args, **kwargs):
            for char in ["hel", "lo"]:
                yield ChatGenerationChunk(message=AIMessageChunk(content=char))

        with patch("deerflow.models.mindie_provider.ChatOpenAI._astream", side_effect=fake_stream), patch.object(MindIEChatModel, "__init__", return_value=None):
            model = MindIEChatModel.__new__(MindIEChatModel)
            chunks = await self._collect(model._astream([HumanMessage(content="hi")]))

        assert "".join(c.message.content for c in chunks) == "hello"

    @pytest.mark.asyncio
    async def test_no_tools_fixes_escaped_newlines_in_stream(self):
        from langchain_core.messages import AIMessageChunk
        from langchain_core.outputs import ChatGenerationChunk

        async def fake_stream(*args, **kwargs):
            yield ChatGenerationChunk(message=AIMessageChunk(content="a\\nb"))

        with patch("deerflow.models.mindie_provider.ChatOpenAI._astream", side_effect=fake_stream), patch.object(MindIEChatModel, "__init__", return_value=None):
            model = MindIEChatModel.__new__(MindIEChatModel)
            chunks = await self._collect(model._astream([HumanMessage(content="x")]))

        assert chunks[0].message.content == "a\nb"

    @pytest.mark.asyncio
    async def test_with_tools_fake_streams_text_in_chunks(self):
        with patch.object(MindIEChatModel, "_agenerate", new_callable=AsyncMock) as mock_ag, patch.object(MindIEChatModel, "__init__", return_value=None):
            long_text = "A" * 50
            mock_ag.return_value = _make_chat_result(long_text)
            model = MindIEChatModel.__new__(MindIEChatModel)

            chunks = await self._collect(model._astream([HumanMessage(content="q")], tools=[{"type": "function", "function": {"name": "dummy"}}]))

        full = "".join(c.message.content for c in chunks)
        assert full == long_text
        assert len(chunks) > 1

    @pytest.mark.asyncio
    async def test_with_tools_emits_tool_call_chunk(self):

        tool_calls = [{"name": "fn", "args": {}, "id": "c1"}]
        with patch.object(MindIEChatModel, "_agenerate", new_callable=AsyncMock) as mock_ag, patch.object(MindIEChatModel, "__init__", return_value=None):
            mock_ag.return_value = _make_chat_result("ok", tool_calls=tool_calls)
            model = MindIEChatModel.__new__(MindIEChatModel)

            chunks = await self._collect(model._astream([HumanMessage(content="q")], tools=[{"type": "function", "function": {"name": "fn"}}]))

        tool_chunks = [c for c in chunks if getattr(c.message, "tool_calls", [])]
        assert tool_chunks, "No chunk carried tool_calls"
        assert tool_chunks[-1].message.tool_calls[0]["name"] == "fn"

    @pytest.mark.asyncio
    async def test_with_tools_empty_text_still_emits_tool_chunk(self):
        tool_calls = [{"name": "x", "args": {}, "id": "c2"}]
        with patch.object(MindIEChatModel, "_agenerate", new_callable=AsyncMock) as mock_ag, patch.object(MindIEChatModel, "__init__", return_value=None):
            mock_ag.return_value = _make_chat_result("", tool_calls=tool_calls)
            model = MindIEChatModel.__new__(MindIEChatModel)

            chunks = await self._collect(model._astream([HumanMessage(content="q")], tools=[{"type": "function", "function": {"name": "x"}}]))

        assert any(getattr(c.message, "tool_calls", []) for c in chunks)
