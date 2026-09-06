import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

import deerflow.utils.llm_text as llm_text
from app.gateway.authz import require_permission
from app.gateway.deps import get_config
from deerflow.config.app_config import AppConfig
from deerflow.utils.oneshot_llm import run_oneshot_llm

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["input-polish"])


class InputPolishRequest(BaseModel):
    text: str = Field(..., description="Draft text currently shown in the composer")
    locale: str | None = Field(default=None, description="Optional UI locale hint")
    thread_id: str | None = Field(default=None, description="Optional thread id for tracing only")


class InputPolishResponse(BaseModel):
    rewritten_text: str = Field(..., description="Polished draft text")
    changed: bool = Field(..., description="Whether the model changed the original draft")


def _clean_rewritten_text(text: str) -> str:
    # The polished draft may legitimately contain a literal "<think>" substring
    # (e.g. a draft that asks about the tag), so do NOT truncate at a dangling
    # open tag here — that would silently drop the rest of a valid rewrite and
    # can produce a spurious 503. Complete <think>...</think> blocks are still
    # removed.
    candidate = llm_text.strip_think_blocks(text, truncate_unclosed=False)
    candidate = llm_text.strip_markdown_code_fence(candidate)
    return candidate.strip()


def _build_system_instruction() -> str:
    return (
        "You are DeerFlow's pre-send prompt optimizer.\n"
        "Rewrite the user's rough draft into a clearer instruction for an AI agent before it is sent.\n"
        "Do not answer the task.\n"
        "Preserve the user's language, intent, entities, file paths, URLs, code blocks, and any leading slash command prefix exactly.\n"
        "Improve the draft by making the goal, scope, constraints, and desired output explicit when they are implied by the draft.\n"
        "For vague quality words such as 'better', 'good-looking', or 'polished', translate them into concrete but generic quality criteria.\n"
        "Do not invent facts, business context, tools, file names, dates, metrics, or user preferences that are not implied.\n"
        "Prefer one concise paragraph or a short bullet list. Keep it under 180 words unless the original draft is longer.\n"
        "Output only the rewritten draft, with no markdown wrapper, explanation, or alternatives."
    )


def _build_user_content(text: str, locale: str | None) -> str:
    locale_hint = locale.strip() if locale else "same language as the draft"
    return f"Locale hint: {locale_hint}\n\nRewrite this draft while preserving its intent:\n<draft>\n{text}\n</draft>"


@router.post(
    "/input-polish",
    response_model=InputPolishResponse,
    summary="Polish Composer Input",
    description="Rewrite a draft message before it is sent. This does not create a thread run or persist any message.",
)
@require_permission("runs", "create")
async def polish_input(
    body: InputPolishRequest,
    request: Request,
    config: AppConfig = Depends(get_config),
) -> InputPolishResponse:
    del request  # Required by the auth decorator.

    if not config.input_polish.enabled:
        raise HTTPException(status_code=404, detail="Input polishing is disabled")

    # Validate the same normalized view of the input that we send to the model,
    # so the user-facing length boundary and the model input cannot disagree
    # (e.g. a padded draft passing the check but arriving with stray whitespace).
    text = body.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="Input text is required")

    max_chars = config.input_polish.max_chars
    if len(text) > max_chars:
        raise HTTPException(status_code=400, detail=f"Input text exceeds {max_chars} characters")

    model_name = config.input_polish.model_name
    try:
        raw = await run_oneshot_llm(
            system_instruction=_build_system_instruction(),
            user_content=_build_user_content(text, body.locale),
            run_name="input_polish",
            app_config=config,
            model_name=model_name,
            thread_id=body.thread_id,
        )
        rewritten = _clean_rewritten_text(raw)
    except Exception as exc:
        logger.exception("Failed to polish input: thread_id=%s err=%s", body.thread_id, exc)
        raise HTTPException(status_code=503, detail="Failed to polish input") from exc

    if not rewritten:
        raise HTTPException(status_code=503, detail="Failed to polish input")

    return InputPolishResponse(
        rewritten_text=rewritten,
        changed=rewritten != text,
    )
