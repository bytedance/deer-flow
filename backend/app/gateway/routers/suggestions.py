import json
import logging

from fastapi import APIRouter, Depends, Request
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from app.gateway.authz import require_permission
from app.gateway.deps import get_config
from deerflow.config.app_config import AppConfig
from deerflow.models import create_chat_model

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


def _strip_markdown_code_fence(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if len(lines) >= 3 and lines[0].startswith("```") and lines[-1].startswith("```"):
        return "\n".join(lines[1:-1]).strip()
    return stripped


def _parse_json_string_list(text: str) -> list[str] | None:
    candidate = _strip_markdown_code_fence(text)
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


def _extract_response_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") in {"text", "output_text"}:
                text = block.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(parts) if parts else ""
    if content is None:
        return ""
    return str(content)


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
        response = await model.ainvoke([SystemMessage(content=system_instruction), HumanMessage(content=user_content)], config={"run_name": "suggest_agent"})
        raw = _extract_response_text(response.content)
        suggestions = _parse_json_string_list(raw) or []
        cleaned = [s.replace("\n", " ").strip() for s in suggestions if s.strip()]
        cleaned = cleaned[:n]
        return SuggestionsResponse(suggestions=cleaned)
    except Exception as exc:
        logger.exception("Failed to generate suggestions: thread_id=%s err=%s", thread_id, exc)
        return SuggestionsResponse(suggestions=[])
