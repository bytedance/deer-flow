# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import asyncio
import base64
import json
import logging
import os
import re
from pathlib import Path
from typing import Annotated, Any, List, Optional, cast
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Query, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response, StreamingResponse
from langchain_core.messages import AIMessageChunk, BaseMessage, ToolMessage
from langgraph.checkpoint.mongodb import AsyncMongoDBSaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.store.memory import InMemoryStore
from langgraph.types import Command
from psycopg_pool import AsyncConnectionPool

from src.config.configuration import get_recursion_limit
from src.config.loader import get_bool_env, get_str_env
from src.config.report_style import ReportStyle
from src.config.tools import SELECTED_RAG_PROVIDER
from src.graph.builder import build_graph_with_memory
from src.graph.checkpoint import chat_stream_message
from src.graph.utils import (
    build_clarified_topic_from_history,
    reconstruct_clarification_history,
)
from src.llms.llm import get_configured_llm_models
from src.podcast.graph.builder import build_graph as build_podcast_graph
from src.ppt.graph.builder import build_graph as build_ppt_graph
from src.prompt_enhancer.graph.builder import build_graph as build_prompt_enhancer_graph
from src.prose.graph.builder import build_graph as build_prose_graph
from src.rag.builder import build_retriever
from src.rag.milvus import load_examples as load_milvus_examples
from src.rag.qdrant import load_examples as load_qdrant_examples
from src.rag.retriever import Resource
from src.server.chat_request import (
    ChatRequest,
    EnhancePromptRequest,
    GeneratePodcastRequest,
    GeneratePPTRequest,
    GenerateProseRequest,
    TTSRequest,
)
from src.server.config_request import ConfigResponse
from src.server.mcp_request import MCPServerMetadataRequest, MCPServerMetadataResponse
from src.server.mcp_utils import load_mcp_tools
from src.server.rag_request import (
    RAGConfigResponse,
    RAGResourceRequest,
    RAGResourcesResponse,
    RAGUploadResponse,
)
from src.server.document_request import (
    DocumentInfo,
    DocumentUploadResponse,
    DocumentListResponse,
)
from src.server.document_storage import document_storage
from src.server.document_parser import extract_text_from_document
from src.tools import VolcengineTTS
from src.utils.json_utils import sanitize_args
from src.utils.log_sanitizer import (
    sanitize_agent_name,
    sanitize_log_input,
    sanitize_thread_id,
    sanitize_tool_name,
    sanitize_user_content,
)

logger = logging.getLogger(__name__)

# Configure Windows event loop policy for PostgreSQL compatibility
# On Windows, psycopg requires a selector-based event loop, not the default ProactorEventLoop
if os.name == "nt":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

INTERNAL_SERVER_ERROR_DETAIL = "Internal Server Error"

app = FastAPI(
    title="DeerFlow API",
    description="API for Deer",
    version="0.1.0",
)

# Add CORS middleware
# It's recommended to load the allowed origins from an environment variable
# for better security and flexibility across different environments.
allowed_origins_str = get_str_env("ALLOWED_ORIGINS", "http://localhost:3000")
allowed_origins = [origin.strip() for origin in allowed_origins_str.split(",")]

logger.info(f"Allowed origins: {allowed_origins}")

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,  # Restrict to specific origins
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],  # Use the configured list of methods
    allow_headers=["*"],  # Now allow all headers, but can be restricted further
)
# Load examples into RAG providers if configured
load_milvus_examples()
load_qdrant_examples()

in_memory_store = InMemoryStore()
graph = build_graph_with_memory()


@app.post("/api/chat/stream")
async def chat_stream(request: ChatRequest):
    # Check if MCP server configuration is enabled
    mcp_enabled = get_bool_env("ENABLE_MCP_SERVER_CONFIGURATION", False)

    logger.debug(f"get the request locale : {request.locale}")

    # Validate MCP settings if provided
    if request.mcp_settings and not mcp_enabled:
        raise HTTPException(
            status_code=403,
            detail="MCP server configuration is disabled. Set ENABLE_MCP_SERVER_CONFIGURATION=true to enable MCP features.",
        )

    thread_id = request.thread_id
    if thread_id == "__default__":
        thread_id = str(uuid4())

    return StreamingResponse(
        _astream_workflow_generator(
            request.model_dump()["messages"],
            thread_id,
            request.resources,
            request.max_plan_iterations,
            request.max_step_num,
            request.max_search_results,
            request.auto_accepted_plan,
            request.interrupt_feedback,
            request.mcp_settings if mcp_enabled else {},
            request.enable_background_investigation,
            request.report_style,
            request.enable_deep_thinking,
            request.enable_clarification,
            request.max_clarification_rounds,
            request.locale,
            request.interrupt_before_tools,
        ),
        media_type="text/event-stream",
    )


def _validate_tool_call_chunks(tool_call_chunks):
    """Validate and log tool call chunk structure for debugging."""
    if not tool_call_chunks:
        return
    
    logger.debug(f"Validating tool_call_chunks: count={len(tool_call_chunks)}")
    
    indices_seen = set()
    tool_ids_seen = set()
    
    for i, chunk in enumerate(tool_call_chunks):
        index = chunk.get("index")
        tool_id = chunk.get("id")
        name = chunk.get("name", "")
        has_args = "args" in chunk
        
        logger.debug(
            f"Chunk {i}: index={index}, id={tool_id}, name={name}, "
            f"has_args={has_args}, type={chunk.get('type')}"
        )
        
        if index is not None:
            indices_seen.add(index)
        if tool_id:
            tool_ids_seen.add(tool_id)
    
    if len(indices_seen) > 1:
        logger.debug(
            f"Multiple indices detected: {sorted(indices_seen)} - "
            f"This may indicate consecutive tool calls"
        )


def _process_tool_call_chunks(tool_call_chunks):
    """
    Process tool call chunks with proper index-based grouping.
    
    This function handles the concatenation of tool call chunks that belong
    to the same tool call (same index) while properly segregating chunks
    from different tool calls (different indices).
    
    The issue: In streaming, LangChain's ToolCallChunk concatenates string
    attributes (name, args) when chunks have the same index. We need to:
    1. Group chunks by index
    2. Detect index collisions with different tool names
    3. Accumulate arguments for the same index
    4. Return properly segregated tool calls
    """
    if not tool_call_chunks:
        return []
    
    _validate_tool_call_chunks(tool_call_chunks)
    
    chunks = []
    chunk_by_index = {}  # Group chunks by index to handle streaming accumulation
    
    for chunk in tool_call_chunks:
        index = chunk.get("index")
        chunk_id = chunk.get("id")
        
        if index is not None:
            # Create or update entry for this index
            if index not in chunk_by_index:
                chunk_by_index[index] = {
                    "name": "",
                    "args": "",
                    "id": chunk_id or "",
                    "index": index,
                    "type": chunk.get("type", ""),
                }
            
            # Validate and accumulate tool name
            chunk_name = chunk.get("name", "")
            if chunk_name:
                stored_name = chunk_by_index[index]["name"]
                
                # Check for index collision with different tool names
                if stored_name and stored_name != chunk_name:
                    logger.warning(
                        f"Tool name mismatch detected at index {index}: "
                        f"'{stored_name}' != '{chunk_name}'. "
                        f"This may indicate a streaming artifact or consecutive tool calls "
                        f"with the same index assignment."
                    )
                    # Keep the first name to prevent concatenation
                else:
                    chunk_by_index[index]["name"] = chunk_name
            
            # Update ID if new one provided
            if chunk_id and not chunk_by_index[index]["id"]:
                chunk_by_index[index]["id"] = chunk_id
            
            # Accumulate arguments
            if chunk.get("args"):
                chunk_by_index[index]["args"] += chunk.get("args", "")
        else:
            # Handle chunks without explicit index (edge case)
            logger.debug(f"Chunk without index encountered: {chunk}")
            chunks.append({
                "name": chunk.get("name", ""),
                "args": sanitize_args(chunk.get("args", "")),
                "id": chunk.get("id", ""),
                "index": 0,
                "type": chunk.get("type", ""),
            })
    
    # Convert indexed chunks to list, sorted by index for proper order
    for index in sorted(chunk_by_index.keys()):
        chunk_data = chunk_by_index[index]
        chunk_data["args"] = sanitize_args(chunk_data["args"])
        chunks.append(chunk_data)
        logger.debug(
            f"Processed tool call: index={index}, name={chunk_data['name']}, "
            f"id={chunk_data['id']}"
        )
    
    return chunks


def _get_agent_name(agent, message_metadata):
    """Extract agent name from agent tuple."""
    agent_name = "unknown"
    if agent and len(agent) > 0:
        agent_name = agent[0].split(":")[0] if ":" in agent[0] else agent[0]
    else:
        agent_name = message_metadata.get("langgraph_node", "unknown")
    return agent_name


def _create_event_stream_message(
    message_chunk, message_metadata, thread_id, agent_name
):
    """Create base event stream message."""
    content = message_chunk.content
    if not isinstance(content, str):
        content = json.dumps(content, ensure_ascii=False)

    event_stream_message = {
        "thread_id": thread_id,
        "agent": agent_name,
        "id": message_chunk.id,
        "role": "assistant",
        "checkpoint_ns": message_metadata.get("checkpoint_ns", ""),
        "langgraph_node": message_metadata.get("langgraph_node", ""),
        "langgraph_path": message_metadata.get("langgraph_path", ""),
        "langgraph_step": message_metadata.get("langgraph_step", ""),
        "content": content,
    }

    # Add optional fields
    if message_chunk.additional_kwargs.get("reasoning_content"):
        event_stream_message["reasoning_content"] = message_chunk.additional_kwargs[
            "reasoning_content"
        ]

    if message_chunk.response_metadata.get("finish_reason"):
        event_stream_message["finish_reason"] = message_chunk.response_metadata.get(
            "finish_reason"
        )

    return event_stream_message


def _create_interrupt_event(thread_id, event_data):
    """Create interrupt event."""
    return _make_event(
        "interrupt",
        {
            "thread_id": thread_id,
            "id": event_data["__interrupt__"][0].ns[0],
            "role": "assistant",
            "content": event_data["__interrupt__"][0].value,
            "finish_reason": "interrupt",
            "options": [
                {"text": "Edit plan", "value": "edit_plan"},
                {"text": "Start research", "value": "accepted"},
            ],
        },
    )


def _process_document_references(messages: List[dict]) -> List[dict]:
    """
    处理消息中的文档引用，提取文档内容并添加到消息中
    
    Args:
        messages: 消息列表
        
    Returns:
        处理后的消息列表
    """
    processed_messages = []
    for message in messages:
        if not isinstance(message, dict) or "content" not in message:
            processed_messages.append(message)
            continue
        
        content = message.get("content", "")
        if not isinstance(content, str):
            processed_messages.append(message)
            continue
        
        # 检测文档引用格式：doc://{doc_id} 或 [文档名](doc://{doc_id})
        doc_pattern = r'doc://([a-f0-9-]+)'
        doc_refs = re.findall(doc_pattern, content)
        
        if not doc_refs:
            processed_messages.append(message)
            continue
        
        # 提取所有引用的文档内容
        doc_contents = []
        logger.info(f"Found {len(doc_refs)} document reference(s): {doc_refs}")
        for doc_id in doc_refs:
            try:
                logger.info(f"Processing document reference: {doc_id}")
                doc_info = document_storage.get_document(doc_id)
                if doc_info:
                    logger.info(f"Document info retrieved: {doc_info.get('name')}, path: {doc_info.get('path')}")
                    file_path = Path(doc_info["path"])
                    if file_path.exists():
                        logger.info(f"Document file exists, extracting content...")
                        doc_text = extract_text_from_document(
                            file_path,
                            doc_info.get("metadata", {}).get("content_type")
                        )
                        logger.info(f"Extracted {len(doc_text)} characters from document")
                        doc_contents.append(
                            f"\n\n--- 文档内容: {doc_info['name']} ---\n{doc_text}\n--- 文档结束 ---\n"
                        )
                        logger.info(f"Successfully extracted content from document: {doc_info['name']} ({len(doc_text)} chars)")
                    else:
                        logger.warning(f"Document file not found: {file_path}")
                else:
                    logger.warning(f"Document not found: {doc_id}")
            except Exception as e:
                logger.exception(f"Error processing document {doc_id}: {e}")
                import traceback
                logger.error(f"Traceback: {traceback.format_exc()}")
                doc_contents.append(f"\n\n[处理文档时出错: {str(e)}]\n")
        
        # 将文档内容添加到消息末尾
        if doc_contents:
            new_content = content + "\n" + "\n".join(doc_contents)
            processed_message = message.copy()
            processed_message["content"] = new_content
            logger.info(f"Added document content to message. Original length: {len(content)}, New length: {len(new_content)}")
            logger.debug(f"New message content preview: {new_content[:500]}...")
            processed_messages.append(processed_message)
        else:
            logger.warning("No document content extracted, keeping original message")
            processed_messages.append(message)
    
    return processed_messages


def _process_initial_messages(message, thread_id):
    """Process initial messages and yield formatted events."""
    json_data = json.dumps(
        {
            "thread_id": thread_id,
            "id": "run--" + message.get("id", uuid4().hex),
            "role": "user",
            "content": message.get("content", ""),
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    chat_stream_message(
        thread_id, f"event: message_chunk\ndata: {json_data}\n\n", "none"
    )


async def _process_message_chunk(message_chunk, message_metadata, thread_id, agent):
    """Process a single message chunk and yield appropriate events."""

    agent_name = _get_agent_name(agent, message_metadata)
    safe_agent_name = sanitize_agent_name(agent_name)
    safe_thread_id = sanitize_thread_id(thread_id)
    safe_agent = sanitize_agent_name(agent)
    logger.debug(f"[{safe_thread_id}] _process_message_chunk started for agent={safe_agent_name}")
    logger.debug(f"[{safe_thread_id}] Extracted agent_name: {safe_agent_name}")
    
    event_stream_message = _create_event_stream_message(
        message_chunk, message_metadata, thread_id, agent_name
    )

    if isinstance(message_chunk, ToolMessage):
        # Tool Message - Return the result of the tool call
        logger.debug(f"[{safe_thread_id}] Processing ToolMessage")
        tool_call_id = message_chunk.tool_call_id
        event_stream_message["tool_call_id"] = tool_call_id
        
        # Validate tool_call_id for debugging
        if tool_call_id:
            safe_tool_id = sanitize_log_input(tool_call_id, max_length=100)
            logger.debug(f"[{safe_thread_id}] ToolMessage with tool_call_id: {safe_tool_id}")
        else:
            logger.warning(f"[{safe_thread_id}] ToolMessage received without tool_call_id")
        
        logger.debug(f"[{safe_thread_id}] Yielding tool_call_result event")
        yield _make_event("tool_call_result", event_stream_message)
    elif isinstance(message_chunk, AIMessageChunk):
        # AI Message - Raw message tokens
        has_tool_calls = bool(message_chunk.tool_calls)
        has_chunks = bool(message_chunk.tool_call_chunks)
        logger.debug(f"[{safe_thread_id}] Processing AIMessageChunk, tool_calls={has_tool_calls}, tool_call_chunks={has_chunks}")
        
        if message_chunk.tool_calls:
            # AI Message - Tool Call (complete tool calls)
            safe_tool_names = [sanitize_tool_name(tc.get('name', 'unknown')) for tc in message_chunk.tool_calls]
            logger.debug(f"[{safe_thread_id}] AIMessageChunk has complete tool_calls: {safe_tool_names}")
            event_stream_message["tool_calls"] = message_chunk.tool_calls
            
            # Process tool_call_chunks with proper index-based grouping
            processed_chunks = _process_tool_call_chunks(
                message_chunk.tool_call_chunks
            )
            if processed_chunks:
                event_stream_message["tool_call_chunks"] = processed_chunks
                safe_chunk_names = [sanitize_tool_name(c.get('name')) for c in processed_chunks]
                logger.debug(
                    f"[{safe_thread_id}] Tool calls: {safe_tool_names}, "
                    f"Processed chunks: {len(processed_chunks)}"
                )
            
            logger.debug(f"[{safe_thread_id}] Yielding tool_calls event")
            yield _make_event("tool_calls", event_stream_message)
        elif message_chunk.tool_call_chunks:
            # AI Message - Tool Call Chunks (streaming)
            chunks_count = len(message_chunk.tool_call_chunks)
            logger.debug(f"[{safe_thread_id}] AIMessageChunk has streaming tool_call_chunks: {chunks_count} chunks")
            processed_chunks = _process_tool_call_chunks(
                message_chunk.tool_call_chunks
            )
            
            # Emit separate events for chunks with different indices (tool call boundaries)
            if processed_chunks:
                prev_chunk = None
                for chunk in processed_chunks:
                    current_index = chunk.get("index")
                    
                    # Log index transitions to detect tool call boundaries
                    if prev_chunk is not None and current_index != prev_chunk.get("index"):
                        prev_name = sanitize_tool_name(prev_chunk.get('name'))
                        curr_name = sanitize_tool_name(chunk.get('name'))
                        logger.debug(
                            f"[{safe_thread_id}] Tool call boundary detected: "
                            f"index {prev_chunk.get('index')} ({prev_name}) -> "
                            f"{current_index} ({curr_name})"
                        )
                    
                    prev_chunk = chunk
                
                # Include all processed chunks in the event
                event_stream_message["tool_call_chunks"] = processed_chunks
                safe_chunk_names = [sanitize_tool_name(c.get('name')) for c in processed_chunks]
                logger.debug(
                    f"[{safe_thread_id}] Streamed {len(processed_chunks)} tool call chunk(s): "
                    f"{safe_chunk_names}"
                )
            
            logger.debug(f"[{safe_thread_id}] Yielding tool_call_chunks event")
            yield _make_event("tool_call_chunks", event_stream_message)
        else:
            # AI Message - Raw message tokens
            content_len = len(message_chunk.content) if isinstance(message_chunk.content, str) else 0
            logger.debug(f"[{safe_thread_id}] AIMessageChunk is raw message tokens, content_len={content_len}")
            yield _make_event("message_chunk", event_stream_message)


async def _stream_graph_events(
    graph_instance, workflow_input, workflow_config, thread_id
):
    """Stream events from the graph and process them."""
    safe_thread_id = sanitize_thread_id(thread_id)
    logger.debug(f"[{safe_thread_id}] Starting graph event stream with agent nodes")
    try:
        event_count = 0
        async for agent, _, event_data in graph_instance.astream(
            workflow_input,
            config=workflow_config,
            stream_mode=["messages", "updates"],
            subgraphs=True,
        ):
            event_count += 1
            safe_agent = sanitize_agent_name(agent)
            logger.debug(f"[{safe_thread_id}] Graph event #{event_count} received from agent: {safe_agent}")
            
            if isinstance(event_data, dict):
                if "__interrupt__" in event_data:
                    logger.debug(
                        f"[{safe_thread_id}] Processing interrupt event: "
                        f"ns={getattr(event_data['__interrupt__'][0], 'ns', 'unknown') if isinstance(event_data['__interrupt__'], (list, tuple)) and len(event_data['__interrupt__']) > 0 else 'unknown'}, "
                        f"value_len={len(getattr(event_data['__interrupt__'][0], 'value', '')) if isinstance(event_data['__interrupt__'], (list, tuple)) and len(event_data['__interrupt__']) > 0 and hasattr(event_data['__interrupt__'][0], 'value') and hasattr(event_data['__interrupt__'][0].value, '__len__') else 'unknown'}"
                    )
                    yield _create_interrupt_event(thread_id, event_data)
                logger.debug(f"[{safe_thread_id}] Dict event without interrupt, skipping")
                continue

            message_chunk, message_metadata = cast(
                tuple[BaseMessage, dict[str, Any]], event_data
            )
            
            safe_node = sanitize_agent_name(message_metadata.get('langgraph_node', 'unknown'))
            safe_step = sanitize_log_input(message_metadata.get('langgraph_step', 'unknown'))
            logger.debug(
                f"[{safe_thread_id}] Processing message chunk: "
                f"type={type(message_chunk).__name__}, "
                f"node={safe_node}, "
                f"step={safe_step}"
            )

            async for event in _process_message_chunk(
                message_chunk, message_metadata, thread_id, agent
            ):
                yield event
        
        logger.debug(f"[{safe_thread_id}] Graph event stream completed. Total events: {event_count}")
    except Exception as e:
        logger.exception(f"[{safe_thread_id}] Error during graph execution")
        yield _make_event(
            "error",
            {
                "thread_id": thread_id,
                "error": "Error during graph execution",
            },
        )


async def _astream_workflow_generator(
    messages: List[dict],
    thread_id: str,
    resources: List[Resource],
    max_plan_iterations: int,
    max_step_num: int,
    max_search_results: int,
    auto_accepted_plan: bool,
    interrupt_feedback: str,
    mcp_settings: dict,
    enable_background_investigation: bool,
    report_style: ReportStyle,
    enable_deep_thinking: bool,
    enable_clarification: bool,
    max_clarification_rounds: int,
    locale: str = "en-US",
    interrupt_before_tools: Optional[List[str]] = None,
):
    safe_thread_id = sanitize_thread_id(thread_id)
    safe_feedback = sanitize_log_input(interrupt_feedback) if interrupt_feedback else ""
    logger.debug(
        f"[{safe_thread_id}] _astream_workflow_generator starting: "
        f"messages_count={len(messages)}, "
        f"auto_accepted_plan={auto_accepted_plan}, "
        f"interrupt_feedback={safe_feedback}, "
        f"interrupt_before_tools={interrupt_before_tools}"
    )
    
    # 处理文档引用：检测消息中的文档引用并提取内容
    messages = _process_document_references(messages)
    
    # Process initial messages
    logger.debug(f"[{safe_thread_id}] Processing {len(messages)} initial messages")
    for message in messages:
        if isinstance(message, dict) and "content" in message:
            safe_content = sanitize_user_content(message.get('content', ''))
            logger.debug(f"[{safe_thread_id}] Sending initial message to client: {safe_content}")
            _process_initial_messages(message, thread_id)

    logger.debug(f"[{safe_thread_id}] Reconstructing clarification history")
    clarification_history = reconstruct_clarification_history(messages)

    logger.debug(f"[{safe_thread_id}] Building clarified topic from history")
    clarified_topic, clarification_history = build_clarified_topic_from_history(
        clarification_history
    )
    latest_message_content = messages[-1]["content"] if messages else ""
    # 记录最新消息内容（应该包含文档内容）
    logger.info(f"[{safe_thread_id}] Latest message content length: {len(latest_message_content)}")
    if len(latest_message_content) > 500:
        logger.debug(f"[{safe_thread_id}] Latest message content preview (first 500 chars): {latest_message_content[:500]}...")
        logger.debug(f"[{safe_thread_id}] Latest message content preview (last 500 chars): ...{latest_message_content[-500:]}")
    else:
        logger.debug(f"[{safe_thread_id}] Latest message content: {latest_message_content}")
    
    # 优先使用包含文档内容的完整消息，而不是clarified_topic（可能不包含文档内容）
    # 如果latest_message_content包含文档内容（长度明显大于clarified_topic），使用latest_message_content
    if latest_message_content and len(latest_message_content) > len(clarified_topic) * 2:
        # latest_message_content明显更长，说明包含了文档内容
        clarified_research_topic = latest_message_content
        logger.info(f"[{safe_thread_id}] Using latest_message_content as clarified_research_topic (contains document content, length: {len(latest_message_content)})")
    else:
        # 使用clarified_topic（可能已经是完整的，或者没有文档内容）
        clarified_research_topic = clarified_topic or latest_message_content
        logger.info(f"[{safe_thread_id}] Using clarified_topic as clarified_research_topic (length: {len(clarified_research_topic)})")
    
    safe_topic = sanitize_user_content(clarified_research_topic[:500] if len(clarified_research_topic) > 500 else clarified_research_topic)
    logger.debug(f"[{safe_thread_id}] Clarified research topic preview: {safe_topic}")

    # Prepare workflow input
    logger.debug(f"[{safe_thread_id}] Preparing workflow input")
    # 确保使用处理后的消息（包含文档内容）
    workflow_input = {
        "messages": messages,  # 这里使用的是已经处理过文档引用的消息
        "plan_iterations": 0,
        "final_report": "",
        "current_plan": None,
        "observations": [],
        "auto_accepted_plan": auto_accepted_plan,
        "enable_background_investigation": enable_background_investigation,
        "research_topic": latest_message_content,  # 这里也应该包含文档内容
        "clarification_history": clarification_history,
        "clarified_research_topic": clarified_research_topic,
        "enable_clarification": enable_clarification,
        "max_clarification_rounds": max_clarification_rounds,
        "locale": locale,
    }
    logger.info(f"[{safe_thread_id}] Workflow input prepared. Research topic length: {len(latest_message_content)}")

    if not auto_accepted_plan and interrupt_feedback:
        logger.debug(f"[{safe_thread_id}] Creating resume command with interrupt_feedback: {safe_feedback}")
        resume_msg = f"[{interrupt_feedback}]"
        if messages:
            resume_msg += f" {messages[-1]['content']}"
        workflow_input = Command(resume=resume_msg)

    # Prepare workflow config
    logger.debug(
        f"[{safe_thread_id}] Preparing workflow config: "
        f"max_plan_iterations={max_plan_iterations}, "
        f"max_step_num={max_step_num}, "
        f"report_style={report_style.value}, "
        f"enable_deep_thinking={enable_deep_thinking}"
    )
    workflow_config = {
        "thread_id": thread_id,
        "resources": resources,
        "max_plan_iterations": max_plan_iterations,
        "max_step_num": max_step_num,
        "max_search_results": max_search_results,
        "mcp_settings": mcp_settings,
        "report_style": report_style.value,
        "enable_deep_thinking": enable_deep_thinking,
        "interrupt_before_tools": interrupt_before_tools,
        "recursion_limit": get_recursion_limit(),
    }

    checkpoint_saver = get_bool_env("LANGGRAPH_CHECKPOINT_SAVER", False)
    checkpoint_url = get_str_env("LANGGRAPH_CHECKPOINT_DB_URL", "")
    
    logger.debug(
        f"[{safe_thread_id}] Checkpoint configuration: "
        f"saver_enabled={checkpoint_saver}, "
        f"url_configured={bool(checkpoint_url)}"
    )
    
    # Handle checkpointer if configured
    connection_kwargs = {
        "autocommit": True,
        "row_factory": "dict_row",
        "prepare_threshold": 0,
    }
    if checkpoint_saver and checkpoint_url != "":
        if checkpoint_url.startswith("postgresql://"):
            logger.info(f"[{safe_thread_id}] Starting async postgres checkpointer")
            logger.debug(f"[{safe_thread_id}] Setting up PostgreSQL connection pool")
            async with AsyncConnectionPool(
                checkpoint_url, kwargs=connection_kwargs
            ) as conn:
                logger.debug(f"[{safe_thread_id}] Initializing AsyncPostgresSaver")
                checkpointer = AsyncPostgresSaver(conn)
                await checkpointer.setup()
                logger.debug(f"[{safe_thread_id}] Attaching checkpointer to graph")
                graph.checkpointer = checkpointer
                graph.store = in_memory_store
                logger.debug(f"[{safe_thread_id}] Starting to stream graph events")
                async for event in _stream_graph_events(
                    graph, workflow_input, workflow_config, thread_id
                ):
                    yield event
                logger.debug(f"[{safe_thread_id}] Graph event streaming completed")

        if checkpoint_url.startswith("mongodb://"):
            logger.info(f"[{safe_thread_id}] Starting async mongodb checkpointer")
            logger.debug(f"[{safe_thread_id}] Setting up MongoDB connection")
            async with AsyncMongoDBSaver.from_conn_string(
                checkpoint_url
            ) as checkpointer:
                logger.debug(f"[{safe_thread_id}] Attaching MongoDB checkpointer to graph")
                graph.checkpointer = checkpointer
                graph.store = in_memory_store
                logger.debug(f"[{safe_thread_id}] Starting to stream graph events")
                async for event in _stream_graph_events(
                    graph, workflow_input, workflow_config, thread_id
                ):
                    yield event
                logger.debug(f"[{safe_thread_id}] Graph event streaming completed")
    else:
        logger.debug(f"[{safe_thread_id}] No checkpointer configured, using in-memory graph")
        # Use graph without MongoDB checkpointer
        logger.debug(f"[{safe_thread_id}] Starting to stream graph events")
        async for event in _stream_graph_events(
            graph, workflow_input, workflow_config, thread_id
        ):
            yield event
        logger.debug(f"[{safe_thread_id}] Graph event streaming completed")


def _make_event(event_type: str, data: dict[str, any]):
    if data.get("content") == "":
        data.pop("content")
    # Ensure JSON serialization with proper encoding
    try:
        json_data = json.dumps(data, ensure_ascii=False)

        finish_reason = data.get("finish_reason", "")
        chat_stream_message(
            data.get("thread_id", ""),
            f"event: {event_type}\ndata: {json_data}\n\n",
            finish_reason,
        )

        return f"event: {event_type}\ndata: {json_data}\n\n"
    except (TypeError, ValueError) as e:
        logger.error(f"Error serializing event data: {e}")
        # Return a safe error event
        error_data = json.dumps({"error": "Serialization failed"}, ensure_ascii=False)
        return f"event: error\ndata: {error_data}\n\n"


@app.post("/api/tts")
async def text_to_speech(request: TTSRequest):
    """Convert text to speech using volcengine TTS API."""
    app_id = get_str_env("VOLCENGINE_TTS_APPID", "")
    if not app_id:
        raise HTTPException(status_code=400, detail="VOLCENGINE_TTS_APPID is not set")
    access_token = get_str_env("VOLCENGINE_TTS_ACCESS_TOKEN", "")
    if not access_token:
        raise HTTPException(
            status_code=400, detail="VOLCENGINE_TTS_ACCESS_TOKEN is not set"
        )

    try:
        cluster = get_str_env("VOLCENGINE_TTS_CLUSTER", "volcano_tts")
        voice_type = get_str_env("VOLCENGINE_TTS_VOICE_TYPE", "BV700_V2_streaming")

        tts_client = VolcengineTTS(
            appid=app_id,
            access_token=access_token,
            cluster=cluster,
            voice_type=voice_type,
        )
        # Call the TTS API
        result = tts_client.text_to_speech(
            text=request.text[:1024],
            encoding=request.encoding,
            speed_ratio=request.speed_ratio,
            volume_ratio=request.volume_ratio,
            pitch_ratio=request.pitch_ratio,
            text_type=request.text_type,
            with_frontend=request.with_frontend,
            frontend_type=request.frontend_type,
        )

        if not result["success"]:
            raise HTTPException(status_code=500, detail=str(result["error"]))

        # Decode the base64 audio data
        audio_data = base64.b64decode(result["audio_data"])

        # Return the audio file
        return Response(
            content=audio_data,
            media_type=f"audio/{request.encoding}",
            headers={
                "Content-Disposition": (
                    f"attachment; filename=tts_output.{request.encoding}"
                )
            },
        )

    except Exception as e:
        logger.exception(f"Error in TTS endpoint: {str(e)}")
        raise HTTPException(status_code=500, detail=INTERNAL_SERVER_ERROR_DETAIL)


@app.post("/api/podcast/generate")
async def generate_podcast(request: GeneratePodcastRequest):
    try:
        report_content = request.content
        print(report_content)
        workflow = build_podcast_graph()
        final_state = workflow.invoke({"input": report_content})
        audio_bytes = final_state["output"]
        return Response(content=audio_bytes, media_type="audio/mp3")
    except Exception as e:
        logger.exception(f"Error occurred during podcast generation: {str(e)}")
        raise HTTPException(status_code=500, detail=INTERNAL_SERVER_ERROR_DETAIL)


@app.post("/api/ppt/generate")
async def generate_ppt(request: GeneratePPTRequest):
    try:
        report_content = request.content
        print(report_content)
        workflow = build_ppt_graph()
        final_state = workflow.invoke({"input": report_content})
        generated_file_path = final_state["generated_file_path"]
        with open(generated_file_path, "rb") as f:
            ppt_bytes = f.read()
        return Response(
            content=ppt_bytes,
            media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        )
    except Exception as e:
        logger.exception(f"Error occurred during ppt generation: {str(e)}")
        raise HTTPException(status_code=500, detail=INTERNAL_SERVER_ERROR_DETAIL)


@app.post("/api/prose/generate")
async def generate_prose(request: GenerateProseRequest):
    try:
        sanitized_prompt = request.prompt.replace("\r\n", "").replace("\n", "")
        logger.info(f"Generating prose for prompt: {sanitized_prompt}")
        workflow = build_prose_graph()
        events = workflow.astream(
            {
                "content": request.prompt,
                "option": request.option,
                "command": request.command,
            },
            stream_mode="messages",
            subgraphs=True,
        )
        return StreamingResponse(
            (f"data: {event[0].content}\n\n" async for _, event in events),
            media_type="text/event-stream",
        )
    except Exception as e:
        logger.exception(f"Error occurred during prose generation: {str(e)}")
        raise HTTPException(status_code=500, detail=INTERNAL_SERVER_ERROR_DETAIL)


@app.post("/api/prompt/enhance")
async def enhance_prompt(request: EnhancePromptRequest):
    try:
        sanitized_prompt = request.prompt.replace("\r\n", "").replace("\n", "")
        logger.info(f"Enhancing prompt: {sanitized_prompt}")

        # Convert string report_style to ReportStyle enum
        report_style = None
        if request.report_style:
            try:
                # Handle both uppercase and lowercase input
                style_mapping = {
                    "ACADEMIC": ReportStyle.ACADEMIC,
                    "POPULAR_SCIENCE": ReportStyle.POPULAR_SCIENCE,
                    "NEWS": ReportStyle.NEWS,
                    "SOCIAL_MEDIA": ReportStyle.SOCIAL_MEDIA,
                    "STRATEGIC_INVESTMENT": ReportStyle.STRATEGIC_INVESTMENT,
                }
                report_style = style_mapping.get(
                    request.report_style.upper(), ReportStyle.ACADEMIC
                )
            except Exception:
                # If invalid style, default to ACADEMIC
                report_style = ReportStyle.ACADEMIC
        else:
            report_style = ReportStyle.ACADEMIC

        workflow = build_prompt_enhancer_graph()
        final_state = workflow.invoke(
            {
                "prompt": request.prompt,
                "context": request.context,
                "report_style": report_style,
            }
        )
        return {"result": final_state["output"]}
    except Exception as e:
        logger.exception(f"Error occurred during prompt enhancement: {str(e)}")
        raise HTTPException(status_code=500, detail=INTERNAL_SERVER_ERROR_DETAIL)


@app.post("/api/mcp/server/metadata", response_model=MCPServerMetadataResponse)
async def mcp_server_metadata(request: MCPServerMetadataRequest):
    """Get information about an MCP server."""
    # Check if MCP server configuration is enabled
    if not get_bool_env("ENABLE_MCP_SERVER_CONFIGURATION", False):
        raise HTTPException(
            status_code=403,
            detail="MCP server configuration is disabled. Set ENABLE_MCP_SERVER_CONFIGURATION=true to enable MCP features.",
        )

    try:
        # Set default timeout with a longer value for this endpoint
        timeout = 300  # Default to 300 seconds for this endpoint

        # Use custom timeout from request if provided
        if request.timeout_seconds is not None:
            timeout = request.timeout_seconds

        # Load tools from the MCP server using the utility function
        tools = await load_mcp_tools(
            server_type=request.transport,
            command=request.command,
            args=request.args,
            url=request.url,
            env=request.env,
            headers=request.headers,
            timeout_seconds=timeout,
        )

        # Create the response with tools
        response = MCPServerMetadataResponse(
            transport=request.transport,
            command=request.command,
            args=request.args,
            url=request.url,
            env=request.env,
            headers=request.headers,
            tools=tools,
        )

        return response
    except Exception as e:
        logger.exception(f"Error in MCP server metadata endpoint: {str(e)}")
        raise HTTPException(status_code=500, detail=INTERNAL_SERVER_ERROR_DETAIL)


@app.get("/api/rag/config", response_model=RAGConfigResponse)
async def rag_config():
    """Get the config of the RAG."""
    return RAGConfigResponse(provider=SELECTED_RAG_PROVIDER)


@app.get("/api/rag/resources", response_model=RAGResourcesResponse)
async def rag_resources(request: Annotated[RAGResourceRequest, Query()]):
    """Get the resources of the RAG."""
    retriever = build_retriever()
    if retriever:
        return RAGResourcesResponse(resources=retriever.list_resources(request.query))
    return RAGResourcesResponse(resources=[])


@app.post("/api/rag/upload", response_model=RAGUploadResponse)
async def rag_upload(
    file: UploadFile = File(...),
    dataset_name: str | None = Form(None),
    dataset_id: str | None = Form(None),
):
    """Upload a document to the RAG provider."""
    try:
        retriever = build_retriever()
        if not retriever:
            raise HTTPException(
                status_code=400, detail="RAG provider is not configured"
            )

        # Check if upload is supported (only RAGFlow currently supports upload)
        from src.rag.ragflow import RAGFlowProvider
        
        if not isinstance(retriever, RAGFlowProvider):
            raise HTTPException(
                status_code=400,
                detail=f"Document upload is currently only supported for RAGFlow provider. Current provider: {SELECTED_RAG_PROVIDER or 'not configured'}. Please configure RAG_PROVIDER=ragflow in your .env file.",
            )

        # Read file content
        file_content = await file.read()
        file_name = file.filename or "document"

        # Validate that either dataset_name or dataset_id is provided
        if not dataset_name and not dataset_id:
            raise HTTPException(
                status_code=400,
                detail="Either dataset_name or dataset_id must be provided",
            )

        # Upload document
        resource = retriever.upload_document(
            file_content=file_content,
            file_name=file_name,
            dataset_name=dataset_name,
            dataset_id=dataset_id,
        )

        return RAGUploadResponse(
            success=True,
            resource=resource,
            message=f"Document '{file_name}' uploaded successfully",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error uploading document: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to upload document: {str(e)}")


@app.post("/api/documents/upload", response_model=DocumentUploadResponse)
async def upload_document(
    file: UploadFile = File(...),
):
    """Upload a document to local storage."""
    try:
        # Read file content
        file_content = await file.read()
        file_name = file.filename or "document"
        
        # Validate file size (max 100MB)
        max_size = 100 * 1024 * 1024
        if len(file_content) > max_size:
            raise HTTPException(
                status_code=400,
                detail=f"File too large. Maximum size is 100MB. Current size: {len(file_content) / 1024 / 1024:.2f}MB",
            )
        
        # Save document
        doc_info = document_storage.save_document(
            file_content=file_content,
            file_name=file_name,
            metadata={
                "content_type": file.content_type,
            },
        )
        
        return DocumentUploadResponse(
            success=True,
            document=DocumentInfo(**doc_info),
            message=f"Document '{file_name}' uploaded successfully",
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error uploading document: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to upload document: {str(e)}")


@app.get("/api/documents", response_model=DocumentListResponse)
async def list_documents(
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
):
    """List all uploaded documents."""
    try:
        documents = document_storage.list_documents(limit=limit, offset=offset)
        total = len(document_storage.list_documents(limit=10000))
        
        return DocumentListResponse(
            documents=[DocumentInfo(**doc) for doc in documents],
            total=total,
        )
    except Exception as e:
        logger.exception(f"Error listing documents: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to list documents: {str(e)}")


@app.get("/api/documents/{doc_id}", response_model=DocumentInfo)
async def get_document(doc_id: str):
    """Get document information."""
    try:
        doc_info = document_storage.get_document(doc_id)
        if not doc_info:
            raise HTTPException(status_code=404, detail="Document not found")
        return DocumentInfo(**doc_info)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error getting document: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get document: {str(e)}")


@app.get("/api/documents/{doc_id}/download")
async def download_document(doc_id: str):
    """Download document content."""
    try:
        doc_info = document_storage.get_document(doc_id)
        if not doc_info:
            raise HTTPException(status_code=404, detail="Document not found")
        
        file_content = document_storage.get_document_content(doc_id)
        if not file_content:
            raise HTTPException(status_code=404, detail="Document content not found")
        
        from fastapi.responses import FileResponse
        file_path = Path(doc_info["path"])
        return FileResponse(
            path=file_path,
            filename=doc_info["name"],
            media_type=doc_info.get("metadata", {}).get("content_type", "application/octet-stream"),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error downloading document: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to download document: {str(e)}")


@app.delete("/api/documents/{doc_id}")
async def delete_document(doc_id: str):
    """Delete a document."""
    try:
        success = document_storage.delete_document(doc_id)
        if not success:
            raise HTTPException(status_code=404, detail="Document not found")
        return {"success": True, "message": "Document deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error deleting document: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to delete document: {str(e)}")


@app.get("/api/config", response_model=ConfigResponse)
async def config():
    """Get the config of the server."""
    return ConfigResponse(
        rag=RAGConfigResponse(provider=SELECTED_RAG_PROVIDER),
        models=get_configured_llm_models(),
    )
