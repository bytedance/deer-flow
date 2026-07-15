"""Gate slash skills that declare required-outputs before the run can END."""

from __future__ import annotations

from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage

from deerflow.agents.middlewares.slash_skill_deliverable_middleware import (
    SlashSkillDeliverableMiddleware,
    packaged_skill_json_is_valid,
)
from deerflow.runtime.secret_context import (
    _SLASH_SKILL_NAME_KEY,
    _SLASH_SKILL_REQUIRED_OUTPUTS_KEY,
)


def _runtime(
    *,
    thread_id: str = "t1",
    run_id: str = "r1",
    skill: str | None = "content-research",
    required_outputs: list[str] | None = None,
):
    context: dict = {"thread_id": thread_id, "run_id": run_id}
    if skill is not None:
        context[_SLASH_SKILL_NAME_KEY] = skill
        context[_SLASH_SKILL_REQUIRED_OUTPUTS_KEY] = required_outputs if required_outputs is not None else [f"{skill}.json"]
    return type("RuntimeStub", (), {"context": context})()


def _state(outputs_path: Path, *, content: str = "Research complete.", user: str = "/content-research topic"):
    return {
        "messages": [
            HumanMessage(content=user),
            AIMessage(content=content, id="ai-final", response_metadata={"finish_reason": "stop"}),
        ],
        "thread_data": {"outputs_path": str(outputs_path)},
    }


def test_missing_deliverable_jumps_to_model_for_recovery(tmp_path: Path):
    middleware = SlashSkillDeliverableMiddleware()
    runtime = _runtime()
    result = middleware.after_model(_state(tmp_path), runtime)

    assert result is not None
    assert result["jump_to"] == "model"
    assert any(isinstance(m, RemoveMessage) for m in result["messages"])


def test_valid_deliverable_allows_terminal_success(tmp_path: Path):
    out = tmp_path / "content-research.json"
    out.write_text(
        (
            '{"schema_version":"1.0","source":"content-research",'
            '"sources":[],"generated_at":"2026-07-15T00:00:00+00:00"}'
        ),
        encoding="utf-8",
    )
    middleware = SlashSkillDeliverableMiddleware()
    runtime = _runtime()

    assert middleware.after_model(_state(tmp_path), runtime) is None


def test_wrong_source_is_treated_as_missing(tmp_path: Path):
    out = tmp_path / "content-research.json"
    out.write_text(
        (
            '{"schema_version":"1.0","source":"content-article-generation",'
            '"sources":[],"generated_at":"2026-07-15T00:00:00+00:00"}'
        ),
        encoding="utf-8",
    )
    middleware = SlashSkillDeliverableMiddleware()
    runtime = _runtime()
    result = middleware.after_model(_state(tmp_path), runtime)

    assert result is not None
    assert result["jump_to"] == "model"


def test_shell_without_generated_at_is_treated_as_missing(tmp_path: Path):
    out = tmp_path / "content-research.json"
    out.write_text(
        '{"schema_version":"1.0","source":"content-research","sources":[]}',
        encoding="utf-8",
    )
    middleware = SlashSkillDeliverableMiddleware()
    runtime = _runtime()
    result = middleware.after_model(_state(tmp_path), runtime)

    assert result is not None
    assert result["jump_to"] == "model"


def test_handwritten_review_shell_is_rejected():
    """Regression: forged review JSON that fooled the old source/schema-only gate."""
    forged = {
        "schema_version": "1.0",
        "source": "content-article-review",
        "decision": "approve",
        "checks": [],
        "fact_guard_report": {},
        "reviewed_at": "2026-07-15T14:31:00+00:00",
    }
    assert packaged_skill_json_is_valid("content-article-review", forged) is False

    valid = {
        "schema_version": "1.0",
        "source": "content-article-review",
        "title": "Messi biography",
        "content_html": "<p>ok</p>",
        "review": {"status": "approved"},
        "generated_at": "2026-07-15T14:31:00+00:00",
    }
    assert packaged_skill_json_is_valid("content-article-review", valid) is True


def test_handwritten_review_file_triggers_recovery(tmp_path: Path):
    out = tmp_path / "content-article-review.json"
    out.write_text(
        (
            '{"schema_version":"1.0","source":"content-article-review",'
            '"decision":"approve","checks":[],"reviewed_at":"2026-07-15T14:31:00+00:00"}'
        ),
        encoding="utf-8",
    )
    middleware = SlashSkillDeliverableMiddleware()
    runtime = _runtime(skill="content-article-review")
    result = middleware.after_model(
        _state(tmp_path, user="/content-article-review review this"),
        runtime,
    )

    assert result is not None
    assert result["jump_to"] == "model"


def test_exhausted_recovery_marks_error_fallback(tmp_path: Path):
    middleware = SlashSkillDeliverableMiddleware(max_recovery_attempts=1)
    runtime = _runtime()
    state = _state(tmp_path)

    first = middleware.after_model(state, runtime)
    assert first is not None and first["jump_to"] == "model"

    second = middleware.after_model(state, runtime)
    assert second is not None
    assert "jump_to" not in second
    final = second["messages"][-1]
    assert isinstance(final, AIMessage)
    assert final.additional_kwargs["deerflow_error_fallback"] is True
    assert "content-research.json" in str(final.content)


def test_tool_call_intent_is_ignored():
    middleware = SlashSkillDeliverableMiddleware()
    runtime = _runtime()
    state = {
        "messages": [
            HumanMessage(content="/content-research topic"),
            AIMessage(
                content="",
                id="ai-tools",
                tool_calls=[{"id": "c1", "name": "bash", "args": {}}],
                response_metadata={"finish_reason": "tool_calls"},
            ),
        ],
        "thread_data": {"outputs_path": "/tmp/outputs"},
    }

    assert middleware.after_model(state, runtime) is None


def test_skill_without_required_outputs_is_ignored(tmp_path: Path):
    middleware = SlashSkillDeliverableMiddleware()
    runtime = _runtime(skill="deep-research", required_outputs=[])
    assert middleware.after_model(_state(tmp_path, user="/deep-research topic"), runtime) is None


def test_non_json_required_output_only_needs_existence(tmp_path: Path):
    (tmp_path / "report.md").write_text("# ok", encoding="utf-8")
    middleware = SlashSkillDeliverableMiddleware()
    runtime = _runtime(skill="report-writer", required_outputs=["report.md"])
    assert middleware.after_model(_state(tmp_path, user="/report-writer"), runtime) is None


def test_wrap_model_call_injects_recovery_prompt(tmp_path: Path):
    middleware = SlashSkillDeliverableMiddleware()
    runtime = _runtime()
    middleware.after_model(_state(tmp_path), runtime)

    captured: dict = {}

    class _Req:
        def __init__(self):
            self.runtime = runtime
            self.messages = [HumanMessage(content="/content-research topic")]

        def override(self, *, messages):
            captured["messages"] = messages
            return self

    def handler(request):
        return request

    middleware.wrap_model_call(_Req(), handler)
    assert any(getattr(m, "name", None) == "slash_skill_deliverable_recovery" for m in captured["messages"])


def test_after_agent_finalizes_invalid_handwritten_shell(tmp_path: Path):
    """Safety net: end-of-turn must not succeed with a forged review JSON."""
    out = tmp_path / "content-article-review.json"
    out.write_text(
        (
            '{"skill":"content-article-review","version":"1.1.0",'
            '"status":"passed_unchanged","review":{"summary":"ok"}}'
        ),
        encoding="utf-8",
    )
    middleware = SlashSkillDeliverableMiddleware()
    runtime = _runtime(skill="content-article-review")
    result = middleware.after_agent(
        _state(tmp_path, user="/content-article-review review this"),
        runtime,
    )

    assert result is not None
    final = result["messages"][-1]
    assert isinstance(final, AIMessage)
    assert final.additional_kwargs["deerflow_error_fallback"] is True
    assert "content-article-review.json" in str(final.content)
