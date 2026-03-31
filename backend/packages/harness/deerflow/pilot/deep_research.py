"""Lightweight Deep Research pilot wrapper for Sprint 1.

This module intentionally stays outside the core DeerFlow runtime. It adds a
thin adapter around ``DeerFlowClient`` so Sprint 1 can prove value for one
single use case without introducing a larger framework.
"""

from __future__ import annotations

import hashlib
import json
import logging
import mimetypes
import queue
import re
import tempfile
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from deerflow.client import DeerFlowClient, StreamEvent
from deerflow.config.paths import Paths, get_paths

logger = logging.getLogger(__name__)

PILOT_NAME = "deep-research"
DEFAULT_TIMEOUT_SECONDS = 900
DEFAULT_HEARTBEAT_INTERVAL_SECONDS = 45
DEFAULT_HEARTBEAT_START_AFTER_SECONDS = 60
DEFAULT_EXPECTED_OUTPUTS = [
    "Executive brief in Markdown",
    "A concise short summary that can be reused by a presence layer",
]
DEFAULT_OUTPUT_PROFILE = "default"
OUTPUT_PROFILE_INSTRUCTIONS = {
    "default": (
        "- Format the executive brief as a balanced research artifact.\n"
        "- Optimize for a reader who wants fast comprehension plus enough evidence to trust the recommendation."
    ),
    "founder_memo": (
        "- Format the executive brief as a founder memo.\n"
        "- Prioritize decision-ready findings, strategic implications, sharp tradeoffs, and one clear recommendation.\n"
        "- Keep the body concise and avoid long implementation detail unless it changes the decision."
    ),
    "operator_memo": (
        "- Format the executive brief as an operator memo.\n"
        "- Prioritize execution detail, evidence traceability, risks, assumptions, and the next concrete actions.\n"
        "- Make handoff-ready sections explicit so an operator can act without reinterpreting the brief."
    ),
}
INLINE_ATTACHMENT_EXTENSIONS = {".md", ".txt", ".json", ".yaml", ".yml", ".csv"}
INLINE_ATTACHMENT_CHAR_LIMIT = 8000
MARKDOWN_FALLBACK_START = "EXECUTIVE_BRIEF_MARKDOWN_START"
MARKDOWN_FALLBACK_END = "EXECUTIVE_BRIEF_MARKDOWN_END"


class DeepResearchClientLike(Protocol):
    """Small protocol so tests can inject a fake client."""

    def stream(self, message: str, *, thread_id: str | None = None, **kwargs) -> Any:
        """Yield StreamEvent items."""

    def upload_files(self, thread_id: str, files: list[str | Path]) -> dict[str, Any]:
        """Upload request attachments."""

    def list_skills(self, enabled_only: bool = False) -> dict[str, Any]:
        """List available skills."""


@dataclass(slots=True)
class DeepResearchPilotRequest:
    """Input contract for the Sprint 1 deep-research pilot."""

    objective: str
    context_summary: str = ""
    attachments: list[str] = field(default_factory=list)
    expected_outputs: list[str] = field(default_factory=lambda: list(DEFAULT_EXPECTED_OUTPUTS))
    output_profile: str = DEFAULT_OUTPUT_PROFILE
    request_id: str | None = None
    idempotency_key: str | None = None
    thread_id: str | None = None
    model_name: str | None = None
    thinking_enabled: bool = True
    subagent_enabled: bool = True
    plan_mode: bool = True
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
    heartbeat_interval_seconds: int = DEFAULT_HEARTBEAT_INTERVAL_SECONDS
    heartbeat_start_after_seconds: int = DEFAULT_HEARTBEAT_START_AFTER_SECONDS

    def normalized(self) -> "DeepResearchPilotRequest":
        """Return a copy with defaults resolved."""
        objective = (self.objective or "").strip()
        if not objective:
            raise ValueError("objective must not be empty")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than 0")
        if self.heartbeat_interval_seconds <= 0:
            raise ValueError("heartbeat_interval_seconds must be greater than 0")
        if self.heartbeat_start_after_seconds < 0:
            raise ValueError("heartbeat_start_after_seconds must be >= 0")
        output_profile = (self.output_profile or DEFAULT_OUTPUT_PROFILE).strip().lower()
        if output_profile not in OUTPUT_PROFILE_INSTRUCTIONS:
            supported = ", ".join(sorted(OUTPUT_PROFILE_INSTRUCTIONS))
            raise ValueError(f"output_profile must be one of: {supported}")

        request_id = (self.request_id or uuid.uuid4().hex).strip()
        thread_id = (self.thread_id or f"deep-research-{request_id}").strip()
        return DeepResearchPilotRequest(
            objective=objective,
            context_summary=(self.context_summary or "").strip(),
            attachments=[str(Path(path)) for path in self.attachments],
            expected_outputs=[item.strip() for item in self.expected_outputs if item and item.strip()],
            output_profile=output_profile,
            request_id=request_id,
            idempotency_key=(self.idempotency_key or "").strip() or None,
            thread_id=thread_id,
            model_name=self.model_name,
            thinking_enabled=self.thinking_enabled,
            subagent_enabled=self.subagent_enabled,
            plan_mode=self.plan_mode,
            timeout_seconds=self.timeout_seconds,
            heartbeat_interval_seconds=self.heartbeat_interval_seconds,
            heartbeat_start_after_seconds=self.heartbeat_start_after_seconds,
        )


@dataclass(slots=True)
class DeepResearchPilotResult:
    """Top-level adapter contract for Sprint 1."""

    request_id: str
    idempotency_key: str
    thread_id: str
    output_profile: str
    status: str
    short_summary: str
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    partial_result_available: bool = False
    error_code: str | None = None
    error_message: str | None = None
    duration_seconds: float = 0.0
    token_usage: dict[str, int] = field(default_factory=dict)
    operator_paths: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable payload."""
        payload = asdict(self)
        payload["duration_seconds"] = round(self.duration_seconds, 3)
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DeepResearchPilotResult":
        """Hydrate a result from stored JSON."""
        return cls(
            request_id=str(data.get("request_id", "")),
            idempotency_key=str(data.get("idempotency_key", "")),
            thread_id=str(data.get("thread_id", "")),
            output_profile=str(data.get("output_profile", DEFAULT_OUTPUT_PROFILE)),
            status=str(data.get("status", "failed")),
            short_summary=str(data.get("short_summary", "")),
            artifacts=list(data.get("artifacts", [])),
            partial_result_available=bool(data.get("partial_result_available", False)),
            error_code=data.get("error_code"),
            error_message=data.get("error_message"),
            duration_seconds=float(data.get("duration_seconds", 0.0) or 0.0),
            token_usage=dict(data.get("token_usage", {})),
            operator_paths=dict(data.get("operator_paths", {})),
        )


class DeepResearchPilotRunner:
    """Run the Deep Research pilot with tracing and file-based operator state."""

    def __init__(
        self,
        client: DeepResearchClientLike | None = None,
        *,
        base_dir: Path | None = None,
        now_fn=None,
        monotonic_fn=None,
    ) -> None:
        self._client = client or DeerFlowClient(subagent_enabled=True, plan_mode=True)
        self._base_dir = Path(base_dir).resolve() if base_dir is not None else get_paths().base_dir
        self._paths = Paths(self._base_dir)
        self._now_fn = now_fn or (lambda: datetime.now(UTC))
        self._monotonic_fn = monotonic_fn or time.monotonic

    @property
    def pilot_root(self) -> Path:
        return self._base_dir / "pilots" / PILOT_NAME

    @property
    def requests_dir(self) -> Path:
        return self.pilot_root / "requests"

    @property
    def idempotency_dir(self) -> Path:
        return self.pilot_root / "idempotency"

    def request_dir(self, request_id: str) -> Path:
        return self.requests_dir / request_id

    def run(self, request: DeepResearchPilotRequest) -> DeepResearchPilotResult:
        """Execute a single pilot request end-to-end."""
        normalized = request.normalized()
        idempotency_key = normalized.idempotency_key or self._compute_idempotency_key(normalized)
        paths = self._request_files(normalized.request_id)
        paths["request_dir"].mkdir(parents=True, exist_ok=True)
        self.idempotency_dir.mkdir(parents=True, exist_ok=True)

        cached = self._load_cached_result(idempotency_key)
        if cached is not None:
            return cached

        request_payload = self._request_payload(normalized, idempotency_key)
        self._write_json(paths["request"], request_payload)
        self._write_idempotency_record(idempotency_key, normalized.request_id)
        self._write_scorecard_template(paths["scorecard"], normalized, idempotency_key)

        status_payload = {
            "request_id": normalized.request_id,
            "idempotency_key": idempotency_key,
            "thread_id": normalized.thread_id,
            "output_profile": normalized.output_profile,
            "status": "accepted",
            "updated_at": self._iso_now(),
            "partial_result_available": False,
        }
        self._write_json(paths["status"], status_payload)
        self._append_jsonl(paths["events"], {"timestamp": self._iso_now(), "kind": "accepted", "objective": normalized.objective})

        self._paths.ensure_thread_dirs(normalized.thread_id)
        uploads = self._upload_attachments(normalized, paths)
        prompt = self._build_prompt(normalized, uploads)

        state = _PilotState(
            request_id=normalized.request_id,
            idempotency_key=idempotency_key,
            thread_id=normalized.thread_id,
            output_profile=normalized.output_profile,
            started_monotonic=self._monotonic_fn(),
            request_dir=paths["request_dir"],
            scorecard_path=paths["scorecard"],
        )

        self._write_running_status(paths["status"], normalized, idempotency_key, state)

        event_queue: queue.Queue[tuple[str, Any]] = queue.Queue()
        producer = threading.Thread(
            target=self._stream_worker,
            args=(event_queue, prompt, normalized),
            name=f"deep-research-pilot-{normalized.request_id}",
            daemon=True,
        )
        producer.start()

        finished = False
        while not finished:
            elapsed = self._monotonic_fn() - state.started_monotonic
            if elapsed > normalized.timeout_seconds:
                return self._finalize_failure(
                    normalized=normalized,
                    idempotency_key=idempotency_key,
                    state=state,
                    paths=paths,
                    error_code="timeout",
                    error_message=f"Pilot exceeded timeout_seconds={normalized.timeout_seconds}",
                )

            poll_timeout = min(1.0, max(0.2, normalized.heartbeat_interval_seconds / 2))
            try:
                item_type, payload = event_queue.get(timeout=poll_timeout)
            except queue.Empty:
                self._maybe_emit_heartbeat(normalized, state, paths["status"], paths["events"])
                continue

            if item_type == "event":
                self._consume_stream_event(state, payload, paths["status"], paths["events"])
                continue
            if item_type == "error":
                return self._finalize_failure(
                    normalized=normalized,
                    idempotency_key=idempotency_key,
                    state=state,
                    paths=paths,
                    error_code="runtime_error",
                    error_message=str(payload),
                )
            if item_type == "done":
                finished = True

        return self._finalize_success(normalized, idempotency_key, state, paths)

    def load_result(self, request_id: str) -> DeepResearchPilotResult | None:
        """Read a completed result from disk."""
        result_path = self._request_files(request_id)["result"]
        if not result_path.exists():
            return None
        return DeepResearchPilotResult.from_dict(json.loads(result_path.read_text(encoding="utf-8")))

    def load_status(self, request_id: str) -> dict[str, Any] | None:
        """Read the latest operator status payload."""
        status_path = self._request_files(request_id)["status"]
        if not status_path.exists():
            return None
        return json.loads(status_path.read_text(encoding="utf-8"))

    def _request_files(self, request_id: str) -> dict[str, Path]:
        request_dir = self.request_dir(request_id)
        return {
            "request_dir": request_dir,
            "request": request_dir / "request.json",
            "status": request_dir / "status.json",
            "result": request_dir / "result.json",
            "events": request_dir / "events.jsonl",
            "scorecard": request_dir / "pilot-scorecard.md",
        }

    def _request_payload(self, request: DeepResearchPilotRequest, idempotency_key: str) -> dict[str, Any]:
        return {
            "request_id": request.request_id,
            "idempotency_key": idempotency_key,
            "thread_id": request.thread_id,
            "objective": request.objective,
            "context_summary": request.context_summary,
            "attachments": list(request.attachments),
            "expected_outputs": list(request.expected_outputs),
            "output_profile": request.output_profile,
            "model_name": request.model_name,
            "thinking_enabled": request.thinking_enabled,
            "subagent_enabled": request.subagent_enabled,
            "plan_mode": request.plan_mode,
            "timeout_seconds": request.timeout_seconds,
            "heartbeat_interval_seconds": request.heartbeat_interval_seconds,
            "heartbeat_start_after_seconds": request.heartbeat_start_after_seconds,
            "created_at": self._iso_now(),
        }

    def _compute_idempotency_key(self, request: DeepResearchPilotRequest) -> str:
        payload = {
            "objective": request.objective,
            "context_summary": request.context_summary,
            "expected_outputs": request.expected_outputs,
            "model_name": request.model_name,
            "attachments": [self._attachment_fingerprint(path) for path in request.attachments],
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()

    def _attachment_fingerprint(self, path: str) -> dict[str, Any]:
        candidate = Path(path)
        if not candidate.exists():
            return {"path": str(candidate)}
        stat = candidate.stat()
        return {
            "path": str(candidate.resolve()),
            "size": stat.st_size,
            "mtime_ns": stat.st_mtime_ns,
        }

    def _load_cached_result(self, idempotency_key: str) -> DeepResearchPilotResult | None:
        record_path = self.idempotency_dir / f"{idempotency_key}.json"
        if not record_path.exists():
            return None
        record = json.loads(record_path.read_text(encoding="utf-8"))
        request_id = str(record.get("request_id", ""))
        if not request_id:
            return None

        result = self.load_result(request_id)
        if result is not None:
            return result

        status = self.load_status(request_id)
        if not status:
            return None
        return DeepResearchPilotResult(
            request_id=request_id,
            idempotency_key=idempotency_key,
            thread_id=str(status.get("thread_id", "")),
            output_profile=str(status.get("output_profile", DEFAULT_OUTPUT_PROFILE)),
            status=str(status.get("status", "running")),
            short_summary=str(status.get("short_summary", "")),
            artifacts=list(status.get("artifacts", [])),
            partial_result_available=bool(status.get("partial_result_available", False)),
            error_code=status.get("error_code"),
            error_message=status.get("error_message"),
            duration_seconds=float(status.get("duration_seconds", 0.0) or 0.0),
            token_usage=dict(status.get("token_usage", {})),
            operator_paths=self._operator_paths(self._request_files(request_id)),
        )

    def _write_idempotency_record(self, idempotency_key: str, request_id: str) -> None:
        self._write_json(
            self.idempotency_dir / f"{idempotency_key}.json",
            {
                "idempotency_key": idempotency_key,
                "request_id": request_id,
                "updated_at": self._iso_now(),
            },
        )

    def _upload_attachments(self, request: DeepResearchPilotRequest, paths: dict[str, Path]) -> list[dict[str, Any]]:
        if not request.attachments:
            return []
        uploaded = self._client.upload_files(request.thread_id, request.attachments)
        files = list(uploaded.get("files", []))
        self._append_jsonl(
            paths["events"],
            {
                "timestamp": self._iso_now(),
                "kind": "attachments_uploaded",
                "count": len(files),
                "files": [item.get("filename") for item in files],
            },
        )
        return files

    def _build_prompt(self, request: DeepResearchPilotRequest, uploads: list[dict[str, Any]]) -> str:
        output_filename = f"{request.request_id}-executive-brief.md"
        output_virtual_path = f"/mnt/user-data/outputs/{output_filename}"
        uploads_lines = []
        for upload in uploads:
            virtual_path = upload.get("virtual_path")
            markdown_file = upload.get("markdown_file")
            if virtual_path:
                uploads_lines.append(f"- Uploaded file: {virtual_path}")
            if markdown_file:
                uploads_lines.append(f"- Converted Markdown: /mnt/user-data/uploads/{markdown_file}")
        if not uploads_lines:
            uploads_lines.append("- No uploaded files were provided.")

        skill_hint = self._deep_research_skill_hint()
        expected_outputs = "\n".join(f"- {item}" for item in request.expected_outputs)
        inline_context = self._inline_attachment_context(request.attachments)
        output_profile_instructions = OUTPUT_PROFILE_INSTRUCTIONS[request.output_profile]

        return f"""You are running the Sprint 1 Deep Research pilot.

Mission:
- Objective: {request.objective}
- Request ID: {request.request_id}
- Thread ID: {request.thread_id}

Context:
{request.context_summary or "- No additional context provided."}

Available source files:
{chr(10).join(uploads_lines)}

Inline attachment excerpts:
{inline_context}

Research method:
{skill_hint}

Output profile:
- Selected profile: {request.output_profile}
{output_profile_instructions}

Execution rules:
- Start executing immediately.
- Do not greet, introduce yourself, or ask any social/setup question.
- Treat this as a deep research task, not a casual answer.
- Search broadly, then deepen into the most important dimensions.
- Explicitly mark uncertain, incomplete, or weakly sourced findings.
- Do not ask for the user's name, role, or preferred language.
- Do not ask clarifying questions unless the task is impossible to complete safely.
- Default to English when the request does not specify a language.
- Ground claims in the provided context and inline excerpts unless the objective explicitly requires external research.
- Do not introduce extra use cases, roadmap expansions, or implementation scope that are not explicitly requested.
- For Sprint 1 planning tasks, keep `Deep Research` as the only in-scope use case unless the objective explicitly says otherwise.
- If broader items appear in the source documents, mention them only as background or out-of-scope notes.
- Primary delivery contract: return the full executive brief between the fallback markers below. The adapter will persist the artifact at: {output_virtual_path}
- The executive brief must include: objective, key findings, evidence, risks, open questions, and recommendations.
- If you use any external information, clearly label it as external and mark confidence.
- Return the full Markdown brief between these exact markers:
  {MARKDOWN_FALLBACK_START}
  ...markdown brief...
  {MARKDOWN_FALLBACK_END}
- Your final chat response must stay concise and usable as a presence-layer short summary.
- Keep the final chat response under 120 words.

Expected outputs:
{expected_outputs}
"""

    def _inline_attachment_context(self, attachments: list[str]) -> str:
        if not attachments:
            return "- No inline attachment excerpts."

        excerpts: list[str] = []
        for raw_path in attachments:
            path = Path(raw_path)
            if path.suffix.lower() not in INLINE_ATTACHMENT_EXTENSIONS or not path.exists():
                excerpts.append(f"- {path.name}: inline excerpt unavailable; use the uploaded file path if needed.")
                continue
            try:
                content = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                content = path.read_text(encoding="utf-8", errors="ignore")

            cleaned = content.strip()
            if len(cleaned) > INLINE_ATTACHMENT_CHAR_LIMIT:
                cleaned = cleaned[:INLINE_ATTACHMENT_CHAR_LIMIT].rstrip() + "\n...[truncated]"
            excerpts.append(f"- {path.name} excerpt:\n```text\n{cleaned}\n```")

        return "\n".join(excerpts)

    def _deep_research_skill_hint(self) -> str:
        try:
            skills = self._client.list_skills(enabled_only=False)
        except Exception:
            logger.debug("Unable to inspect skills for deep-research hint", exc_info=True)
            skills = {"skills": []}

        deep_research_found = any(item.get("name") == "deep-research" for item in skills.get("skills", []))
        if deep_research_found:
            return (
                "- Use the installed deep-research skill methodology.\n"
                "- Cover broad exploration, targeted deep dives, and validation across multiple source types.\n"
                "- Do not stop at one search query or one source."
            )
        return (
            "- Follow a four-phase deep research flow: broad exploration, targeted deep dive, diversity/validation, synthesis check.\n"
            "- Gather data, examples, expert views, challenges, and current context.\n"
            "- Do not stop at one search query or one source."
        )

    def _stream_worker(
        self,
        event_queue: queue.Queue[tuple[str, Any]],
        prompt: str,
        request: DeepResearchPilotRequest,
    ) -> None:
        try:
            for event in self._client.stream(
                prompt,
                thread_id=request.thread_id,
                model_name=request.model_name,
                thinking_enabled=request.thinking_enabled,
                subagent_enabled=request.subagent_enabled,
                plan_mode=request.plan_mode,
            ):
                event_queue.put(("event", event))
        except Exception as exc:
            event_queue.put(("error", exc))
        finally:
            event_queue.put(("done", None))

    def _consume_stream_event(
        self,
        state: "_PilotState",
        event: StreamEvent,
        status_path: Path,
        events_path: Path,
    ) -> None:
        state.last_activity_monotonic = self._monotonic_fn()
        if event.type == "messages-tuple":
            self._consume_message_tuple(state, event.data)
        elif event.type == "values":
            self._consume_values_snapshot(state, event.data)
        elif event.type == "end":
            state.completed = True
            state.token_usage = dict(event.data.get("usage", {}))

        self._append_jsonl(
            events_path,
            {
                "timestamp": self._iso_now(),
                "kind": "stream_event",
                "event_type": event.type,
                "payload": self._summarize_event_payload(event),
            },
        )
        self._write_running_status(status_path, None, state.idempotency_key, state)

    def _consume_message_tuple(self, state: "_PilotState", payload: dict[str, Any]) -> None:
        payload_type = payload.get("type")
        if payload_type == "ai":
            content = str(payload.get("content", "") or "").strip()
            if content:
                state.ai_segments.append(content)
                state.short_summary = self._summary_from_ai_content(content, state.output_profile)
            for tool_call in payload.get("tool_calls", []) or []:
                if isinstance(tool_call, dict) and tool_call.get("name") == "present_files":
                    filepaths = tool_call.get("args", {}).get("filepaths", [])
                    if isinstance(filepaths, list):
                        state.artifact_paths.update(path for path in filepaths if isinstance(path, str))
            usage = payload.get("usage_metadata")
            if isinstance(usage, dict):
                state.token_usage = {
                    "input_tokens": int(usage.get("input_tokens", 0) or 0),
                    "output_tokens": int(usage.get("output_tokens", 0) or 0),
                    "total_tokens": int(usage.get("total_tokens", 0) or 0),
                }

    def _consume_values_snapshot(self, state: "_PilotState", payload: dict[str, Any]) -> None:
        messages = payload.get("messages", [])
        if isinstance(messages, list):
            for path in self._extract_presented_artifacts(messages):
                state.artifact_paths.add(path)
        artifacts = payload.get("artifacts", [])
        if isinstance(artifacts, list):
            for item in artifacts:
                if isinstance(item, str):
                    state.artifact_paths.add(item)
                elif isinstance(item, dict):
                    path = item.get("path") or item.get("virtual_path")
                    if isinstance(path, str):
                        state.artifact_paths.add(path)

    def _extract_presented_artifacts(self, messages: list[dict[str, Any]]) -> list[str]:
        artifact_paths: list[str] = []
        for msg in messages:
            if not isinstance(msg, dict) or msg.get("type") != "ai":
                continue
            for tool_call in msg.get("tool_calls", []) or []:
                if not isinstance(tool_call, dict) or tool_call.get("name") != "present_files":
                    continue
                filepaths = tool_call.get("args", {}).get("filepaths", [])
                if isinstance(filepaths, list):
                    artifact_paths.extend(path for path in filepaths if isinstance(path, str))
        return artifact_paths

    def _maybe_emit_heartbeat(
        self,
        request: DeepResearchPilotRequest,
        state: "_PilotState",
        status_path: Path,
        events_path: Path,
    ) -> None:
        now_monotonic = self._monotonic_fn()
        elapsed = now_monotonic - state.started_monotonic
        if elapsed < request.heartbeat_start_after_seconds:
            return
        if now_monotonic - state.last_heartbeat_monotonic < request.heartbeat_interval_seconds:
            return

        state.last_heartbeat_monotonic = now_monotonic
        state.heartbeat_count += 1
        payload = {
            "timestamp": self._iso_now(),
            "kind": "heartbeat",
            "heartbeat_count": state.heartbeat_count,
            "elapsed_seconds": round(elapsed, 3),
            "seconds_since_last_activity": round(now_monotonic - state.last_activity_monotonic, 3),
            "short_summary": state.short_summary,
        }
        self._append_jsonl(events_path, payload)
        self._write_running_status(status_path, request, state.idempotency_key, state)

    def _write_running_status(
        self,
        status_path: Path,
        request: DeepResearchPilotRequest | None,
        idempotency_key: str,
        state: "_PilotState",
    ) -> None:
        request_id = request.request_id if request is not None else state.request_id
        thread_id = request.thread_id if request is not None else state.thread_id
        output_profile = request.output_profile if request is not None else state.output_profile
        elapsed = self._monotonic_fn() - state.started_monotonic
        status_payload = {
            "request_id": request_id,
            "idempotency_key": idempotency_key,
            "thread_id": thread_id,
            "output_profile": output_profile,
            "status": "running",
            "updated_at": self._iso_now(),
            "heartbeat_count": state.heartbeat_count,
            "short_summary": state.short_summary,
            "artifacts": self._normalize_artifacts(thread_id, state.artifact_paths),
            "partial_result_available": bool(state.short_summary or state.artifact_paths),
            "duration_seconds": round(elapsed, 3),
            "token_usage": dict(state.token_usage),
        }
        self._write_json(status_path, status_payload)

    def _finalize_success(
        self,
        normalized: DeepResearchPilotRequest,
        idempotency_key: str,
        state: "_PilotState",
        paths: dict[str, Path],
    ) -> DeepResearchPilotResult:
        artifacts = self._materialize_fallback_artifact(normalized, state, paths)
        if not artifacts:
            return self._finalize_failure(
                normalized=normalized,
                idempotency_key=idempotency_key,
                state=state,
                paths=paths,
                error_code="missing_artifact",
                error_message="Pilot completed without a visible artifact in outputs or present_files.",
            )

        result = DeepResearchPilotResult(
            request_id=normalized.request_id,
            idempotency_key=idempotency_key,
            thread_id=normalized.thread_id,
            output_profile=normalized.output_profile,
            status="completed",
            short_summary=self._final_short_summary(state) or "Deep research completed. Review the attached artifact for full details.",
            artifacts=artifacts,
            partial_result_available=False,
            duration_seconds=self._monotonic_fn() - state.started_monotonic,
            token_usage=dict(state.token_usage),
            operator_paths=self._operator_paths(paths),
        )
        self._persist_final_result(result, paths, scorecard_note="Result quality bucket: [usable now | light edits | heavy edits]")
        return result

    def _finalize_failure(
        self,
        *,
        normalized: DeepResearchPilotRequest,
        idempotency_key: str,
        state: "_PilotState",
        paths: dict[str, Path],
        error_code: str,
        error_message: str,
    ) -> DeepResearchPilotResult:
        artifacts = self._materialize_fallback_artifact(normalized, state, paths)
        partial_available = bool(artifacts or state.short_summary)
        result = DeepResearchPilotResult(
            request_id=normalized.request_id,
            idempotency_key=idempotency_key,
            thread_id=normalized.thread_id,
            output_profile=normalized.output_profile,
            status="failed",
            short_summary=self._final_short_summary(state),
            artifacts=artifacts,
            partial_result_available=partial_available,
            error_code=error_code,
            error_message=error_message,
            duration_seconds=self._monotonic_fn() - state.started_monotonic,
            token_usage=dict(state.token_usage),
            operator_paths=self._operator_paths(paths),
        )
        self._persist_final_result(
            result,
            paths,
            scorecard_note="Failure review: capture what remained usable and whether rerun is needed.",
        )
        return result

    def _materialize_fallback_artifact(
        self,
        normalized: DeepResearchPilotRequest,
        state: "_PilotState",
        paths: dict[str, Path],
    ) -> list[dict[str, Any]]:
        artifacts = self._normalize_artifacts(normalized.thread_id, state.artifact_paths)
        if artifacts:
            return artifacts

        markdown = self._extract_markdown_fallback(state.ai_segments)
        if not markdown:
            return artifacts

        virtual_path = f"/mnt/user-data/outputs/{normalized.request_id}-executive-brief.md"
        output_path = self._paths.resolve_virtual_path(normalized.thread_id, virtual_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(markdown, encoding="utf-8")
        state.artifact_paths.add(virtual_path)
        self._append_jsonl(
            paths["events"],
            {
                "timestamp": self._iso_now(),
                "kind": "adapter_fallback_artifact_generated",
                "virtual_path": virtual_path,
            },
        )
        self._append_scorecard_note(
            paths["scorecard"],
            "Adapter generated the artifact from fallback markdown markers because the model did not create the file directly.",
        )
        return self._normalize_artifacts(normalized.thread_id, state.artifact_paths)

    def _extract_markdown_fallback(self, ai_segments: list[str]) -> str:
        combined = "\n\n".join(segment for segment in ai_segments if segment)
        match = re.search(
            rf"{MARKDOWN_FALLBACK_START}\s*(.*?)\s*{MARKDOWN_FALLBACK_END}",
            combined,
            flags=re.DOTALL,
        )
        if not match:
            return ""
        return match.group(1).strip()

    def _persist_final_result(
        self,
        result: DeepResearchPilotResult,
        paths: dict[str, Path],
        *,
        scorecard_note: str,
    ) -> None:
        status_payload = {
            "request_id": result.request_id,
            "idempotency_key": result.idempotency_key,
            "thread_id": result.thread_id,
            "output_profile": result.output_profile,
            "status": result.status,
            "updated_at": self._iso_now(),
            "short_summary": result.short_summary,
            "artifacts": result.artifacts,
            "partial_result_available": result.partial_result_available,
            "error_code": result.error_code,
            "error_message": result.error_message,
            "duration_seconds": round(result.duration_seconds, 3),
            "token_usage": result.token_usage,
        }
        self._write_json(paths["status"], status_payload)
        self._write_json(paths["result"], result.to_dict())
        self._append_jsonl(
            paths["events"],
            {
                "timestamp": self._iso_now(),
                "kind": "finalized",
                "status": result.status,
                "partial_result_available": result.partial_result_available,
                "error_code": result.error_code,
            },
        )
        self._append_scorecard_note(paths["scorecard"], scorecard_note)

    def _normalize_artifacts(self, thread_id: str, artifact_paths: set[str]) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        seen: set[str] = set()
        outputs_dir = self._paths.sandbox_outputs_dir(thread_id)

        for virtual_path in sorted(artifact_paths):
            if not virtual_path:
                continue
            actual = self._resolve_artifact_path(thread_id, virtual_path)
            if actual is None or virtual_path in seen:
                continue
            seen.add(virtual_path)
            normalized.append(self._artifact_descriptor(thread_id, virtual_path, actual))

        if outputs_dir.exists():
            for actual in sorted(path for path in outputs_dir.iterdir() if path.is_file()):
                virtual_path = f"/mnt/user-data/outputs/{actual.name}"
                if virtual_path in seen:
                    continue
                seen.add(virtual_path)
                normalized.append(self._artifact_descriptor(thread_id, virtual_path, actual))

        return normalized

    def _resolve_artifact_path(self, thread_id: str, virtual_path: str) -> Path | None:
        try:
            actual = self._paths.resolve_virtual_path(thread_id, virtual_path)
        except ValueError:
            return None
        if not actual.exists() or not actual.is_file():
            return None
        return actual

    def _artifact_descriptor(self, thread_id: str, virtual_path: str, actual: Path) -> dict[str, Any]:
        mime_type, _ = mimetypes.guess_type(actual.name)
        return {
            "virtual_path": virtual_path,
            "artifact_url": f"/api/threads/{thread_id}/artifacts/{virtual_path.lstrip('/')}",
            "filename": actual.name,
            "size_bytes": actual.stat().st_size,
            "mime_type": mime_type or "application/octet-stream",
        }

    def _operator_paths(self, paths: dict[str, Path]) -> dict[str, str]:
        return {
            "request_dir": str(paths["request_dir"]),
            "status_file": str(paths["status"]),
            "result_file": str(paths["result"]),
            "events_file": str(paths["events"]),
            "scorecard_file": str(paths["scorecard"]),
        }

    def _summarize_event_payload(self, event: StreamEvent) -> dict[str, Any]:
        payload = dict(event.data)
        if payload.get("type") == "ai" and isinstance(payload.get("content"), str):
            payload["content"] = self._truncate(payload["content"], 500)
        if isinstance(payload.get("messages"), list):
            payload["messages"] = f"{len(payload['messages'])} messages"
        return payload

    def _compact_summary(self, text: str) -> str:
        cleaned = " ".join(text.split())
        return self._truncate(cleaned, 280)

    def _summary_from_ai_content(self, content: str, output_profile: str) -> str:
        fallback_markdown = self._extract_markdown_fallback([content])
        if fallback_markdown:
            return self._summary_from_markdown(fallback_markdown, output_profile)
        return self._compact_summary(content)

    def _final_short_summary(self, state: "_PilotState") -> str:
        if state.short_summary and MARKDOWN_FALLBACK_START not in state.short_summary:
            return state.short_summary
        fallback_markdown = self._extract_markdown_fallback(state.ai_segments)
        if fallback_markdown:
            return self._summary_from_markdown(fallback_markdown, state.output_profile)
        return state.short_summary

    def _summary_from_markdown(self, markdown: str, output_profile: str) -> str:
        lines = [line.strip() for line in markdown.splitlines() if line.strip()]
        title = self._first_heading(lines)
        if output_profile == "founder_memo":
            decision = self._extract_section_summary(lines, ("Decision", "Recommendation"))
            rationale = self._extract_section_summary(lines, ("One-line Rationale", "Key Findings"))
            return self._compact_summary(" ".join(part for part in (title, decision, rationale) if part))
        if output_profile == "operator_memo":
            objective = self._extract_section_summary(lines, ("1) Objective", "Objective"))
            next_actions = self._extract_section_summary(lines, ("9) Next Concrete Actions", "Recommendation"))
            return self._compact_summary(" ".join(part for part in (title, objective, next_actions) if part))

        plain_lines = [self._strip_markdown_prefix(line) for line in lines if not self._is_metadata_line(line) and line != "---"]
        return self._compact_summary(" ".join(line for line in plain_lines if line))

    def _first_heading(self, lines: list[str]) -> str:
        for line in lines:
            if line.startswith("#"):
                return self._strip_markdown_prefix(line)
        return ""

    def _extract_section_summary(self, lines: list[str], heading_keywords: tuple[str, ...]) -> str:
        collecting = False
        collected: list[str] = []
        for line in lines:
            stripped = self._strip_markdown_prefix(line)
            lowered = stripped.lower()
            if line.startswith("#") and any(keyword.lower() in lowered for keyword in heading_keywords):
                collecting = True
                continue
            if collecting and line.startswith("#"):
                break
            if not collecting:
                continue
            if line == "---" or self._is_metadata_line(line):
                continue
            collected.append(stripped)
            if len(" ".join(collected)) >= 220:
                break
        return " ".join(collected).strip()

    def _is_metadata_line(self, line: str) -> bool:
        stripped = line.strip()
        if not stripped.startswith("**") or ":**" not in stripped:
            return False
        return True

    def _strip_markdown_prefix(self, line: str) -> str:
        stripped = re.sub(r"^#+\s*", "", line.strip())
        stripped = re.sub(r"^[-*]\s*", "", stripped)
        return stripped.replace("**", "").strip()

    def _truncate(self, text: str, limit: int) -> str:
        if len(text) <= limit:
            return text
        return text[: max(0, limit - 3)].rstrip() + "..."

    def _write_scorecard_template(self, path: Path, request: DeepResearchPilotRequest, idempotency_key: str) -> None:
        content = f"""# Deep Research Pilot Scorecard

## Request Metadata

- Request ID: `{request.request_id}`
- Idempotency Key: `{idempotency_key}`
- Thread ID: `{request.thread_id}`
- Output Profile: `{request.output_profile}`
- Objective: {request.objective}

## Operator Evaluation

- Latency bucket: `[<2m | 2-5m | 5-10m | >10m]`
- Output quality: `[usable now | light edits | heavy edits | unusable]`
- Cost estimate: `[low | medium | high]`
- Duplicate submit prevented: `[yes | no]`
- Partial result still useful if failed: `[yes | no | n/a]`

## Notes

- What worked:
- What broke:
- What should change before Sprint 2:
"""
        self._write_text(path, content)

    def _append_scorecard_note(self, path: Path, note: str) -> None:
        with path.open("a", encoding="utf-8") as handle:
            handle.write("\n")
            handle.write(f"- Auto note ({self._iso_now()}): {note}\n")

    def _write_json(self, path: Path, data: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", dir=path.parent, suffix=".tmp", delete=False, encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, ensure_ascii=False)
            temp_name = handle.name
        Path(temp_name).replace(path)

    def _write_text(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", dir=path.parent, suffix=".tmp", delete=False, encoding="utf-8") as handle:
            handle.write(content)
            temp_name = handle.name
        Path(temp_name).replace(path)

    def _append_jsonl(self, path: Path, data: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(data, ensure_ascii=False))
            handle.write("\n")

    def _iso_now(self) -> str:
        return self._now_fn().astimezone(UTC).isoformat()


@dataclass
class _PilotState:
    """Mutable runtime state for one pilot execution."""

    request_id: str
    idempotency_key: str
    thread_id: str
    output_profile: str
    started_monotonic: float
    request_dir: Path
    scorecard_path: Path
    last_activity_monotonic: float = 0.0
    last_heartbeat_monotonic: float = 0.0
    heartbeat_count: int = 0
    ai_segments: list[str] = field(default_factory=list)
    artifact_paths: set[str] = field(default_factory=set)
    short_summary: str = ""
    token_usage: dict[str, int] = field(default_factory=dict)
    completed: bool = False

    def __post_init__(self) -> None:
        self.last_activity_monotonic = self.started_monotonic
        self.last_heartbeat_monotonic = self.started_monotonic
