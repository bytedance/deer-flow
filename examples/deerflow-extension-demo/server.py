#!/usr/bin/env python3
"""DeerFlow MySQL 助手 FastAPI 服务。

提供 REST API 接口访问自定义 MySQL 助手 Agent。
"""

import os
import sys
import uuid
import warnings
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

import uvicorn
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage
from pydantic import BaseModel

# 忽略 Pydantic 序列化警告
warnings.filterwarnings("ignore", message="Pydantic serializer warnings")

# 设置 API Key
os.environ["DEEPSEEK_API_KEY"] = "sk-fb8ee523da134a109264669d05536b78"

# 设置配置文件路径
BASE_DIR = Path(__file__).parent
os.environ["DEER_FLOW_CONFIG_PATH"] = str(BASE_DIR / "config.yaml")
os.environ["DEER_FLOW_EXTENSIONS_CONFIG_PATH"] = str(BASE_DIR / "extensions_config.json")

# 设置 DEER_FLOW_HOME，让 DeerFlow 能找到自定义 agent
os.environ["DEER_FLOW_HOME"] = str(BASE_DIR)

# 添加当前目录到 Python 路径（确保能找到 mysql_tools）
sys.path.insert(0, str(Path(__file__).parent))

# 全局状态
agent = None
agent_config = None


def create_agent_config(subagent_enabled: bool = True):
    """创建 agent 配置。"""
    from deerflow.config import get_app_config

    app_config = get_app_config()
    model_name = app_config.models[0].name if app_config.models else None

    return {
        "configurable": {
            "model_name": model_name,
            "thinking_enabled": True,
            "is_plan_mode": False,
            "subagent_enabled": subagent_enabled,
            "agent_name": "mysql-helper",
        },
        "recursion_limit": 100,
    }


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理。"""
    global agent, agent_config
    from deerflow.agents.lead_agent.agent import make_lead_agent

    # 创建 agent 配置
    agent_config = create_agent_config(subagent_enabled=True)

    # 创建 agent
    agent = make_lead_agent(agent_config)
    print("✅ DeerFlow MySQL 助手已启动（支持 subagent）")

    yield

    # 关闭时清理
    agent = None
    agent_config = None
    print("👋 DeerFlow MySQL 助手已关闭")


app = FastAPI(
    title="DeerFlow MySQL 助手",
    description="MySQL 数据库操作助手 API，支持自定义工具和 Prompt，支持 Subagent",
    version="1.0.0",
    lifespan=lifespan,
)


# ============================================================================
# 请求/响应模型
# ============================================================================


class ChatRequest(BaseModel):
    """聊天请求。"""

    message: str
    thread_id: str | None = None


class ChatResponse(BaseModel):
    """聊天响应。"""

    response: str
    thread_id: str


# ============================================================================
# API 路由
# ============================================================================


@app.get("/health")
async def health_check():
    """健康检查。"""
    return {
        "status": "ok",
        "agent": "mysql-helper",
        "subagent_enabled": agent_config["configurable"]["subagent_enabled"],
    }


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """
    发送消息并获取完整响应。

    适合简单的问答场景，返回最终的 AI 文本响应。
    """
    thread_id = request.thread_id or str(uuid.uuid4())

    # 使用异步流式处理
    last_ai_content = ""
    async for event in stream_agent_events(request.message, thread_id):
        if event.get("type") == "ai" and event.get("content"):
            last_ai_content = event["content"]

    return ChatResponse(response=last_ai_content, thread_id=thread_id)


@app.post("/stream")
async def stream(request: ChatRequest):
    """
    流式返回对话事件。

    适合需要实时反馈的场景，支持 subagent 事件。
    返回 Server-Sent Events (SSE) 格式。
    """
    thread_id = request.thread_id or str(uuid.uuid4())

    async def event_generator() -> AsyncGenerator[str, None]:
        """生成 SSE 事件流。"""
        async for event in stream_agent_events(request.message, thread_id):
            yield f"data: {event}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


async def stream_agent_events(message: str, thread_id: str):
    """异步流式处理 agent 事件。"""
    context = {
        "thread_id": thread_id,
        "agent_name": "mysql-helper",
    }
    state = {"messages": [HumanMessage(content=message)]}

    seen_ids: set[str] = set()

    # 使用异步流式处理
    async for chunk in agent.astream(state, config=agent_config, context=context, stream_mode=["values", "custom"]):
        # 处理自定义事件（如 subagent 事件）
        if isinstance(chunk, tuple) and len(chunk) == 2:
            mode, data = chunk
            if mode == "custom":
                event_type = data.get("type")
                if event_type == "task_started":
                    description = data.get("description", "")
                    yield {"type": "task_started", "message": f"🚀 开始子任务: {description}"}
                elif event_type == "task_running":
                    msg = data.get("message", {})
                    content = msg.get("content", "")
                    if content:
                        yield {"type": "task_running", "message": f"   {content}"}
                elif event_type == "task_completed":
                    result = data.get("result", "")
                    yield {"type": "task_completed", "message": f"✅ 子任务完成" + (f": {result}" if result else "")}
                elif event_type == "task_failed":
                    error = data.get("error", "")
                    yield {"type": "task_failed", "message": f"❌ 子任务失败: {error}"}
                elif event_type == "task_timed_out":
                    yield {"type": "task_timed_out", "message": "⏰ 子任务超时"}
                continue

        # 处理 values 事件
        messages = chunk.get("messages", [])
        for msg in messages:
            msg_id = getattr(msg, "id", None)
            if msg_id and msg_id in seen_ids:
                continue
            if msg_id:
                seen_ids.add(msg_id)

            # AI 消息
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                for tc in msg.tool_calls:
                    yield {"type": "tool_call", "message": f"🔧 调用工具: {tc['name']}"}

            # 提取文本内容
            content = extract_text(msg.content) if hasattr(msg, "content") else ""
            if content and hasattr(msg, "tool_calls") and not msg.tool_calls:
                yield {"type": "ai", "content": content}

            # 工具结果
            if hasattr(msg, "name") and msg.name:
                yield {"type": "tool_result", "message": f"📤 工具结果: {msg.name}"}


def extract_text(content) -> str:
    """提取文本内容。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        pieces = []
        for block in content:
            if isinstance(block, str):
                pieces.append(block)
            elif isinstance(block, dict):
                text = block.get("text")
                if text:
                    pieces.append(text)
        return "\n".join(pieces)
    return str(content)


# ============================================================================
# 主入口
# ============================================================================

if __name__ == "__main__":
    uvicorn.run(
        "server:app",
        host="0.0.0.0",
        port=8100,
        reload=True,
    )
