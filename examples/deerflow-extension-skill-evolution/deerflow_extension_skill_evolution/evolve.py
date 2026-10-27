"""Annotation-triggered model evolution (Plan B).

When the user selects ``evolution_mode: model`` and grants
``host_access.model_invocation``, confirming trajectory annotations can fire
an immediate, plugin-driven evolution call instead of waiting for the next
agent run to consult ``skill_feedback``:

1. ``annotation_evolve`` reads the skill's current SKILL.md through the
   guarded managed pipeline plus the caller's annotations, admits one
   running job in the plugin-owned ``evolution_jobs`` table (at most one per
   (owner, skill), enforced by a partial unique index), and returns the job
   id immediately — the model call runs as a background task.
2. The task assembles a two-message prompt (system: editing policy; user:
   current content + feedback notes) and invokes the host-granted
   ``ModelInvoker`` — provider-neutral, non-streaming, bounded by the
   operator's concurrency/timeout/size grant. The result (or a stable error
   code, never exception text) is written back to the job.
3. ``evolution_status`` is the page's polling endpoint: running jobs report
   progress without contents; a succeeded job returns both the base content
   and the model's draft so the UI can render a line diff for human review.
4. ``evolution_discard`` deletes the record (and cancels a still-running
   task). Publishing is deliberately *not* automatic: the human stages the
   draft through the existing stage → check → commit pipeline, so every host
   safety boundary around mutations applies unchanged.

Everything here is plugin-side; the only host surfaces used are the granted
capabilities (mutation service, evidence reader, model invoker) — no host
code references this module.
"""

from __future__ import annotations

import asyncio
import logging
import re
import secrets
from collections.abc import Callable, Mapping
from typing import Any

from deerflow_extension_api import (
    ActionContext,
    ModelInvocationFailed,
    ModelInvocationRequest,
    ModelInvocationUnauthorized,
    ModelInvocationUnavailable,
    ModelMessage,
)

from .configure import granted_model_roles
from .drafts import _select_annotations
from .evolved import EvolvedSkillStore
from .modes import MODE_MODEL, read_evolution_mode
from .mutations import ManagedEvolution, _check_skill_name, _error
from .service import CapabilityHandle

logger = logging.getLogger(__name__)

_PURPOSE = "skill-evolution-feedback"

_SYSTEM_PROMPT = """\
You are a skill document editor for DeerFlow. You will receive the current content of one skill's SKILL.md and the user's feedback notes attached to that skill's past runs. Produce the complete, improved SKILL.md.

Rules:
- Keep the overall structure, tone and every instruction that is still correct.
- Incorporate every relevant piece of feedback; ignore notes that contradict each other in favour of the newest.
- Keep the document concise and actionable; do not add filler or meta-commentary.
- Do not add, extend or restructure changelog / revision-log / history sections. The only changes you make are the ones the feedback notes require.
- Output ONLY the new SKILL.md content. No explanations, no surrounding code fences.
"""

_MAX_PROMPT_NOTES = 20


def _build_messages(content: str, annotations: list[dict[str, Any]]) -> list[ModelMessage]:
    selected, _truncated = _select_annotations(annotations[:_MAX_PROMPT_NOTES])
    lines = ["Feedback notes on past runs (oldest first):"]
    for row in selected:
        updated = row.get("updated_at") or ""
        note = str(row.get("note", "")).strip()
        lines.append(f"- [{updated}] {note}")
    user = f"Current SKILL.md:\n\n{content}\n\n{chr(10).join(lines)}\n\nProduce the improved SKILL.md."
    return [
        ModelMessage(role="system", content=_SYSTEM_PROMPT),
        ModelMessage(role="user", content=user),
    ]


def _strip_fences(text: str) -> str:
    """Unwrap one valid Markdown wrapper, preserving document code blocks."""
    stripped = text.strip()
    lines = stripped.splitlines()
    if len(lines) >= 2:
        opening = re.fullmatch(r"(`{3,}|~{3,})(?:markdown|md)?[ \t]*", lines[0], re.IGNORECASE)
        if opening:
            fence = opening.group(1)
            closing = re.compile(r" {0,3}" + re.escape(fence[0]) + "{" + str(len(fence)) + r",}[ \t]*")
            if closing.fullmatch(lines[-1]) and not any(closing.fullmatch(line) for line in lines[1:-1]):
                return "\n".join(lines[1:-1]).rstrip() + "\n"
    return stripped + "\n" if stripped else stripped


def _error_code(exc: BaseException) -> str:
    if isinstance(exc, ModelInvocationUnavailable):
        return "MODEL_UNAVAILABLE"
    if isinstance(exc, ModelInvocationUnauthorized):
        return "MODEL_NOT_ALLOWED"
    if isinstance(exc, ModelInvocationFailed):
        return "MODEL_FAILED"
    return "INTERNAL"


class AnnotationEvolution:
    """Backend actions: launch, poll and discard annotation-triggered jobs."""

    def __init__(self, evolution: ManagedEvolution, store: EvolvedSkillStore | None, model: CapabilityHandle, *, mode_reader: Callable[[], str] = read_evolution_mode) -> None:
        self._evolution = evolution
        self._store = store
        self._model = model
        self._mode_reader = mode_reader
        # Strong references keep abandoned background tasks alive; the
        # discard path uses the map to cancel a still-running job.
        self._tasks: dict[str, asyncio.Task[None]] = {}

    async def launch(self, payload: Any, ctx: ActionContext) -> dict[str, Any]:
        principal = getattr(ctx, "principal", None)
        user_id = getattr(principal, "user_id", None)
        if not isinstance(user_id, str) or not user_id:
            return {"ok": False, "error": {"code": "UNAUTHENTICATED"}}
        if not isinstance(payload, Mapping) or set(payload) - {"skill_name", "model_role", "model_name"} or "skill_name" not in payload:
            return {"ok": False, "error": {"code": "INVALID_REQUEST"}}
        if self._mode_reader() != MODE_MODEL:
            # evolution_mode: append — the deterministic draft path owns
            # annotation-driven evolution.
            return {"ok": False, "error": {"code": "UNAVAILABLE"}}
        if self._store is None:
            return {"ok": False, "error": {"code": "UNAVAILABLE"}}
        model_name = payload.get("model_name")
        model_role = payload.get("model_role")
        if model_name is not None and (not isinstance(model_name, str) or not model_name or len(model_name) > 200 or model_name.strip() != model_name):
            return {"ok": False, "error": {"code": "INVALID_REQUEST"}}
        if model_name is not None and model_role is not None:
            return {"ok": False, "error": {"code": "INVALID_REQUEST"}}
        # Browser requests reuse ordinary chat models and the caller's model
        # permissions. No plugin role grant is needed on this path.
        chat_models = getattr(ctx, "chat_models", None)
        if chat_models is not None and model_role is not None:
            # A browser must not fall back to an operator capability to bypass
            # the caller's ordinary chat-model permissions.
            return {"ok": False, "error": {"code": "INVALID_REQUEST"}}
        if getattr(ctx, "interaction", None) == "session" and chat_models is None:
            return {"ok": False, "error": {"code": "CHAT_MODELS_UNAVAILABLE"}}
        invoker = chat_models if chat_models is not None else self._model.get()
        if model_name is not None and chat_models is None:
            return {"ok": False, "error": {"code": "CHAT_MODELS_UNAVAILABLE"}}
        if invoker is None:
            return {"ok": False, "error": {"code": "UNAVAILABLE"}}
        # Keep explicit role calls compatible for existing non-browser users;
        # those continue through the original operator-granted capability.
        if model_role is not None:
            if not isinstance(model_role, str) or not model_role or len(model_role) > 128 or model_role.strip() != model_role:
                return {"ok": False, "error": {"code": "INVALID_REQUEST"}}
            roles = granted_model_roles()
            if roles is not None and model_role not in roles:
                return {"ok": False, "error": {"code": "UNKNOWN_MODEL_ROLE"}}
        try:
            name = _check_skill_name(payload.get("skill_name"))
            self._store.sweep_stale_jobs(owner=user_id, skill_name=name)
            read = await self._evolution.read(user_id=user_id, source=None, skill_name=name)
        except Exception as exc:
            return _error(exc)
        if not read.get("ok"):
            return read
        content = read.get("skill", {}).get("content")
        if not isinstance(content, str):
            return {"ok": False, "error": {"code": "INTERNAL"}}
        try:
            annotations = list(self._store.list_annotations(owner=user_id, skill_name=name))
        except Exception:
            logger.warning("skill-evolution: failed to load annotations for the %s evolution job", name, exc_info=True)
            annotations = []
        job_id = secrets.token_hex(8)
        try:
            admitted = self._store.start_job(owner=user_id, skill_name=name, job_id=job_id, base_content=content, feedback_count=len(annotations))
        except Exception as exc:
            return _error(exc)
        if not admitted:
            return {"ok": False, "error": {"code": "BUSY"}}
        task = asyncio.create_task(self._run_job(user_id, name, job_id, invoker, content, annotations, model_role, model_name))
        self._tasks[job_id] = task
        task.add_done_callback(lambda _task, key=job_id: self._tasks.pop(key, None))
        return {"ok": True, "job_id": job_id, "skill_name": name, "status": "running"}

    async def _run_job(self, owner: str, name: str, job_id: str, invoker: Any, content: str, annotations: list[dict[str, Any]], model_role: str | None = None, model_name: str | None = None) -> None:
        try:
            request = ModelInvocationRequest(messages=_build_messages(content, annotations), purpose=_PURPOSE, model_role=model_role, **({"model_name": model_name} if model_name is not None else {}))
            result = await invoker.invoke(request)
            draft = _strip_fences(result.content)
            if not draft.strip():
                raise ModelInvocationFailed("empty draft")
            usage = result.usage
            self._store.finish_job(
                owner=owner,
                job_id=job_id,
                status="succeeded",
                result_content=draft,
                resolved_model=result.resolved_model,
                input_tokens=getattr(usage, "input_tokens", None) if usage is not None else None,
                output_tokens=getattr(usage, "output_tokens", None) if usage is not None else None,
            )
        except asyncio.CancelledError:
            # Gateway shutdown or user discard: the row is either already
            # deleted (discard) or swept as stale on the next launch.
            raise
        except Exception as exc:
            logger.warning("skill-evolution: the evolution job for %s failed", name, exc_info=True)
            try:
                self._store.finish_job(owner=owner, job_id=job_id, status="failed", error_code=_error_code(exc))
            except Exception:
                logger.warning("skill-evolution: failed to record the failure of job %s", job_id, exc_info=True)

    def _job_view(self, job: dict[str, Any]) -> dict[str, Any]:
        view = {
            "job_id": job["job_id"],
            "skill_name": job["skill_name"],
            "status": job["status"],
            "feedback_count": job["feedback_count"],
            "resolved_model": job["resolved_model"],
            "input_tokens": job["input_tokens"],
            "output_tokens": job["output_tokens"],
            "error_code": job["error_code"],
            "created_at": job["created_at"],
            "updated_at": job["updated_at"],
        }
        if job["status"] == "succeeded":
            view["base_content"] = job["base_content"]
            view["result_content"] = job["result_content"]
        return view

    async def status(self, payload: Any, ctx: ActionContext) -> dict[str, Any]:
        principal = getattr(ctx, "principal", None)
        user_id = getattr(principal, "user_id", None)
        if not isinstance(user_id, str) or not user_id:
            return {"ok": False, "error": {"code": "UNAUTHENTICATED"}}
        if not isinstance(payload, Mapping) or set(payload) != {"skill_name"}:
            return {"ok": False, "error": {"code": "INVALID_REQUEST"}}
        try:
            name = _check_skill_name(payload.get("skill_name"))
        except Exception as exc:
            return _error(exc)
        if self._store is None:
            return {"ok": True, "skill_name": name, "job": None}
        try:
            job = self._store.latest_job(owner=user_id, skill_name=name)
        except Exception as exc:
            return _error(exc)
        if job is None:
            return {"ok": True, "skill_name": name, "job": None}
        view = self._job_view(job)
        if job["status"] == "succeeded":
            # A draft that has since been committed through the managed
            # pipeline is consumed: derived from the version journal, so no
            # new job state exists and any staging path is covered.
            try:
                view["published"] = self._store.job_is_published(owner=user_id, name=name, job=job)
            except Exception:
                logger.warning("skill-evolution: could not compare the job draft against the version journal", exc_info=True)
                view["published"] = False
            # A draft identical to its input means the model reviewed the
            # annotations and kept the content: report it so the panel can
            # say so instead of showing an empty diff.
            view["unchanged"] = self._store.job_is_unchanged(job)
        return {"ok": True, "skill_name": name, "job": view}

    async def discard(self, payload: Any, ctx: ActionContext) -> dict[str, Any]:
        principal = getattr(ctx, "principal", None)
        user_id = getattr(principal, "user_id", None)
        if not isinstance(user_id, str) or not user_id:
            return {"ok": False, "error": {"code": "UNAUTHENTICATED"}}
        if not isinstance(payload, Mapping) or set(payload) != {"skill_name", "job_id"}:
            return {"ok": False, "error": {"code": "INVALID_REQUEST"}}
        try:
            name = _check_skill_name(payload.get("skill_name"))
            job_id = payload.get("job_id")
            if not isinstance(job_id, str) or not job_id or len(job_id.encode("utf-8")) > 64:
                raise ValueError("job_id")
        except Exception as exc:
            return _error(exc)
        if self._store is None:
            return {"ok": False, "error": {"code": "UNAVAILABLE"}}
        try:
            deleted = self._store.delete_job(owner=user_id, skill_name=name, job_id=job_id)
        except Exception as exc:
            return _error(exc)
        if not deleted:
            return {"ok": False, "error": {"code": "NOT_FOUND_OR_FORBIDDEN"}}
        # Verify and delete the exact caller-owned skill job before touching
        # its task. A guessed foreign ID must never cancel another user's work.
        task = self._tasks.get(job_id)
        if task is not None and not task.done():
            task.cancel()
        return {"ok": True, "skill_name": name}
