import json
import logging
import os

from fastapi import APIRouter, Depends, Request
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

import deerflow.utils.llm_text as llm_text
from app.gateway.authz import require_permission
from app.gateway.deps import get_config
from deerflow.config.app_config import AppConfig
from deerflow.models import create_chat_model
from deerflow.runtime.user_context import get_effective_user_id
from deerflow.tracing import inject_langfuse_metadata

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["suggestions"])


class SuggestionMessage(BaseModel):
    role: str = Field(..., description="Message role: user|assistant")
    content: str = Field(..., description="Message content as plain text")


class SuggestionsRequest(BaseModel):
    messages: list[SuggestionMessage] = Field(..., description="Recent conversation messages")
    n: int = Field(default=3, ge=1, le=5, description="Number of suggestions to generate")
    model_name: str | None = Field(default=None, description="Optional model override")


class SuggestionsResponse(BaseModel):
    suggestions: list[str] = Field(default_factory=list, description="Suggested follow-up questions")


class SuggestionsConfigResponse(BaseModel):
    enabled: bool = Field(..., description="Whether follow-up suggestions are enabled globally")


_extract_response_text = llm_text.extract_response_text
_strip_markdown_code_fence = llm_text.strip_markdown_code_fence
_strip_think_blocks = llm_text.strip_think_blocks


def _parse_json_string_list(text: str) -> list[str] | None:
    candidate = _strip_think_blocks(text)
    candidate = _strip_markdown_code_fence(candidate)
    start = candidate.find("[")
    end = candidate.rfind("]")
    if start == -1 or end == -1 or end <= start:
        return None
    candidate = candidate[start : end + 1]
    try:
        data = json.loads(candidate)
    except Exception:
        return None
    if not isinstance(data, list):
        return None
    out: list[str] = []
    for item in data:
        if not isinstance(item, str):
            continue
        s = item.strip()
        if not s:
            continue
        out.append(s)
    return out


def _format_conversation(messages: list[SuggestionMessage]) -> str:
    parts: list[str] = []
    for m in messages:
        role = m.role.strip().lower()
        if role in ("user", "human"):
            parts.append(f"User: {m.content.strip()}")
        elif role in ("assistant", "ai"):
            parts.append(f"Assistant: {m.content.strip()}")
        else:
            parts.append(f"{m.role}: {m.content.strip()}")
    return "\n".join(parts).strip()


@router.get(
    "/suggestions/config",
    response_model=SuggestionsConfigResponse,
    summary="Get Suggestions Configuration",
    description="Returns the global configuration for follow-up suggestions.",
)
async def get_suggestions_config(
    config: AppConfig = Depends(get_config),
) -> SuggestionsConfigResponse:
    return SuggestionsConfigResponse(enabled=config.suggestions.enabled)


@router.post(
    "/threads/{thread_id}/suggestions",
    response_model=SuggestionsResponse,
    summary="Generate Follow-up Questions",
    description="Generate short follow-up questions a user might ask next, based on recent conversation context.",
)
@require_permission("threads", "read", owner_check=True)
async def generate_suggestions(
    thread_id: str,
    body: SuggestionsRequest,
    request: Request,
    config: AppConfig = Depends(get_config),
) -> SuggestionsResponse:
    if not config.suggestions.enabled:
        return SuggestionsResponse(suggestions=[])
    if not body.messages:
        return SuggestionsResponse(suggestions=[])

    n = body.n
    conversation = _format_conversation(body.messages)
    if not conversation:
        return SuggestionsResponse(suggestions=[])

    system_instruction = (
        "You are generating follow-up questions to help the user continue the conversation.\n"
        f"Based on the conversation below, produce EXACTLY {n} short questions the user might ask next.\n"
        "Requirements:\n"
        "- Questions must be relevant to the preceding conversation.\n"
        "- Questions must be written in the same language as the user.\n"
        "- Keep each question concise (ideally <= 20 words / <= 40 Chinese characters).\n"
        "- Do NOT include numbering, markdown, or any extra text.\n"
        "- Output MUST be a JSON array of strings only.\n"
    )
    user_content = f"Conversation Context:\n{conversation}\n\nGenerate {n} follow-up questions"

    try:
        model = create_chat_model(name=body.model_name, thinking_enabled=False, app_config=config)
        invoke_config: dict = {"run_name": "suggest_agent"}
        inject_langfuse_metadata(
            invoke_config,
            thread_id=thread_id,
            user_id=get_effective_user_id(),
            assistant_id="suggest_agent",
            model_name=body.model_name,
            environment=os.environ.get("DEER_FLOW_ENV") or os.environ.get("ENVIRONMENT"),
        )
        response = await model.ainvoke([SystemMessage(content=system_instruction), HumanMessage(content=user_content)], config=invoke_config)
        raw = _extract_response_text(response.content)
        suggestions = _parse_json_string_list(raw) or []
        cleaned = [s.replace("\n", " ").strip() for s in suggestions if s.strip()]
        cleaned = cleaned[:n]
        return SuggestionsResponse(suggestions=cleaned)
    except Exception as exc:
        logger.exception("Failed to generate suggestions: thread_id=%s err=%s", thread_id, exc)
        return SuggestionsResponse(suggestions=[])
