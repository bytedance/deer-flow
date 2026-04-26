import ast
import html
import json
import re
import uuid
from collections.abc import Iterator

import httpx
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGenerationChunk, ChatResult
from langchain_openai import ChatOpenAI


def _fix_messages(messages: list) -> list:
    """Sanitize incoming messages for MindIE compatibility.

    MindIE's chat template may fail to parse LangChain's native tool_calls
    or ToolMessage roles, resulting in 0-token generation errors. This function
    flattens multi-modal list contents into strings and converts tool-related
    messages into raw text with XML tags expected by the underlying model.
    """
    fixed = []
    for msg in messages:
        # Flatten content if it's a list of blocks
        if isinstance(msg.content, list):
            parts = []
            for block in msg.content:
                if isinstance(block, str):
                    parts.append(block)
                elif isinstance(block, dict) and block.get("type") == "text":
                    parts.append(block.get("text", ""))
            text = "".join(parts)
        else:
            text = msg.content or ""

        # Convert AIMessage with tool_calls to raw XML text format
        if isinstance(msg, AIMessage) and getattr(msg, "tool_calls", []):
            xml_parts = []
            for tool in msg.tool_calls:
                args_xml = " ".join(f"<parameter={html.escape(str(k), quote=False)}>{html.escape(v if isinstance(v, str) else json.dumps(v, ensure_ascii=False), quote=False)}</parameter>" for k, v in tool.get("args", {}).items())
                xml_parts.append(f"<tool_call> <function={html.escape(str(tool['name']), quote=False)}> {args_xml} </function> </tool_call>")
            full_text = f"{text}\n" + "\n".join(xml_parts) if text else "\n".join(xml_parts)
            fixed.append(AIMessage(content=full_text.strip() or " "))
            continue

        # Wrap tool execution results in XML tags and convert to HumanMessage
        if isinstance(msg, ToolMessage):
            tool_result_text = f"<tool_response>\n{text}\n</tool_response>"
            fixed.append(HumanMessage(content=tool_result_text))
            continue

        # Fallback to prevent completely empty message content
        if not text.strip():
            text = " "

        fixed.append(msg.model_copy(update={"content": text}))

    return fixed


def _parse_xml_tool_call_to_dict(content: str) -> tuple[str, list[dict]]:
    """Parse XML-style tool calls from model output into LangChain dicts.

    Args:
        content: The raw text output from the model.

    Returns:
        A tuple containing the cleaned text (with XML blocks removed) and
        a list of tool call dictionaries formatted for LangChain.
    """
    if not isinstance(content, str) or "<tool_call>" not in content:
        return content, []

    tool_calls = []
    clean_parts: list[str] = []
    cursor = 0
    for start, end, inner_content in _iter_tool_call_blocks(content):
        clean_parts.append(content[cursor:start])
        cursor = end

        func_match = re.search(r"<function=([^>]+)>", inner_content)
        if not func_match:
            continue
        function_name = html.unescape(func_match.group(1).strip())

        # Ignore nested tool blocks when extracting parameters for this call.
        # Nested `<tool_call>` sections represent separate invocations and
        # their `<parameter>` tags must not leak into the current call args.
        param_source_parts: list[str] = []
        nested_cursor = 0
        for nested_start, nested_end, _ in _iter_tool_call_blocks(inner_content):
            param_source_parts.append(inner_content[nested_cursor:nested_start])
            nested_cursor = nested_end
        param_source_parts.append(inner_content[nested_cursor:])
        param_source = "".join(param_source_parts)

        args = {}
        param_pattern = re.compile(r"<parameter=([^>]+)>(.*?)</parameter>", re.DOTALL)
        for param_match in param_pattern.finditer(param_source):
            key = html.unescape(param_match.group(1).strip())
            raw_value = html.unescape(param_match.group(2).strip())

            # Attempt to deserialize string values into native Python types
            # to satisfy downstream Pydantic validation.
            parsed_value = raw_value
            if raw_value.startswith(("[", "{")) or raw_value in ("true", "false", "null") or raw_value.isdigit():
                try:
                    parsed_value = json.loads(raw_value)
                except json.JSONDecodeError:
                    try:
                        parsed_value = ast.literal_eval(raw_value)
                    except (ValueError, SyntaxError):
                        pass

            args[key] = parsed_value

        tool_calls.append({"name": function_name, "args": args, "id": f"call_{uuid.uuid4().hex[:10]}"})
    clean_parts.append(content[cursor:])

    return "".join(clean_parts).strip(), tool_calls


def _iter_tool_call_blocks(content: str) -> Iterator[tuple[int, int, str]]:
    """Iterate `<tool_call>...</tool_call>` blocks and tolerate nesting."""
    token_pattern = re.compile(r"</?tool_call>")
    depth = 0
    block_start = -1

    for match in token_pattern.finditer(content):
        token = match.group(0)
        if token == "<tool_call>":
            if depth == 0:
                block_start = match.start()
            depth += 1
            continue

        if depth == 0:
            continue

        depth -= 1
        if depth == 0 and block_start != -1:
            block_end = match.end()
            inner_start = block_start + len("<tool_call>")
            inner_end = match.start()
            yield block_start, block_end, content[inner_start:inner_end]
            block_start = -1


def _decode_escaped_newlines_outside_fences(content: str) -> str:
    """Decode literal `\\n` outside fenced code blocks."""
    if "\\n" not in content:
        return content

    parts = re.split(r"(```[\s\S]*?```)", content)
    for idx, part in enumerate(parts):
        if part.startswith("```"):
            continue
        parts[idx] = part.replace("\\n", "\n")
    return "".join(parts)


class MindIEChatModel(ChatOpenAI):
    """Chat model adapter for MindIE engine.

    Addresses compatibility issues including:
    - Flattening multimodal list contents to strings.
    - Intercepting and parsing hardcoded XML tool calls into LangChain standard.
    - Handling stream=True dropping choices when tools are present by falling back
      to non-streaming generation and yielding simulated chunks.
    - Fixing over-escaped newline characters from gateway responses.
    """

    def __init__(self, **kwargs):
        """Normalize timeout kwargs without creating long-lived clients."""
        connect_timeout = kwargs.pop("connect_timeout", 30.0)
        read_timeout = kwargs.pop("read_timeout", 900.0)
        write_timeout = kwargs.pop("write_timeout", 60.0)
        pool_timeout = kwargs.pop("pool_timeout", 30.0)

        kwargs.setdefault(
            "timeout",
            httpx.Timeout(
                connect=connect_timeout,
                read=read_timeout,
                write=write_timeout,
                pool=pool_timeout,
            ),
        )
        super().__init__(**kwargs)

    def _patch_result_with_tools(self, result: ChatResult) -> ChatResult:
        """Apply post-generation fixes to the model result."""
        for gen in result.generations:
            msg = gen.message

            if isinstance(msg.content, str):
                # Keep escaped newlines inside fenced code blocks untouched.
                msg.content = _decode_escaped_newlines_outside_fences(msg.content)

                if "<tool_call>" in msg.content:
                    clean_content, extracted_tools = _parse_xml_tool_call_to_dict(msg.content)

                    if extracted_tools:
                        msg.content = clean_content
                        if getattr(msg, "tool_calls", None) is None:
                            msg.tool_calls = []
                        msg.tool_calls.extend(extracted_tools)
        return result

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        result = super()._generate(_fix_messages(messages), stop=stop, run_manager=run_manager, **kwargs)
        return self._patch_result_with_tools(result)

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        result = await super()._agenerate(_fix_messages(messages), stop=stop, run_manager=run_manager, **kwargs)
        return self._patch_result_with_tools(result)

    async def _astream(self, messages, stop=None, run_manager=None, **kwargs):
        # Route standard queries to native streaming for lower TTFB
        if not kwargs.get("tools"):
            async for chunk in super()._astream(_fix_messages(messages), stop=stop, run_manager=run_manager, **kwargs):
                if isinstance(chunk.message.content, str):
                    chunk.message.content = _decode_escaped_newlines_outside_fences(chunk.message.content)
                yield chunk
            return

        # Fallback for tool-enabled requests:
        # MindIE currently drops choices when stream=True and tools are present.
        # We await the full generation and yield chunks to simulate streaming.
        result = await self._agenerate(messages, stop=stop, run_manager=run_manager, **kwargs)

        for gen in result.generations:
            msg = gen.message
            content = msg.content
            standard_tool_calls = getattr(msg, "tool_calls", [])

            # Yield text in chunks to allow downstream UI/Markdown parsers to render smoothly
            if isinstance(content, str) and content:
                chunk_size = 15
                for i in range(0, len(content), chunk_size):
                    chunk_text = content[i : i + chunk_size]
                    chunk_msg = AIMessageChunk(content=chunk_text, id=msg.id, response_metadata=msg.response_metadata if i == 0 else {})
                    yield ChatGenerationChunk(message=chunk_msg, generation_info=gen.generation_info if i == 0 else None)

                if standard_tool_calls:
                    yield ChatGenerationChunk(message=AIMessageChunk(content="", id=msg.id, tool_calls=standard_tool_calls, invalid_tool_calls=getattr(msg, "invalid_tool_calls", [])))
            else:
                chunk_msg = AIMessageChunk(content=content, id=msg.id, tool_calls=standard_tool_calls, invalid_tool_calls=getattr(msg, "invalid_tool_calls", []))
                yield ChatGenerationChunk(message=chunk_msg, generation_info=gen.generation_info)
