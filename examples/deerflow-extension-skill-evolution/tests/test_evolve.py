"""Tests for annotation-triggered model evolution jobs (Plan B)."""

import asyncio
from contextlib import closing
from types import SimpleNamespace

import pytest
from deerflow_extension_api import ModelInvocationFailed, ModelInvocationRequest, ModelInvocationResult, ModelInvocationUnavailable, ModelUsage

from deerflow_extension_skill_evolution.evolve import AnnotationEvolution, _build_messages, _strip_fences
from deerflow_extension_skill_evolution.evolved import EvolvedSkillStore
from deerflow_extension_skill_evolution.service import CapabilityHandle

USER = "user-1"
OTHER = "user-2"


class _FakeEvolution:
    def __init__(self, content: str = "# Demo\n\nBody.", error: dict | None = None) -> None:
        self.content = content
        self.error = error

    async def read(self, *, user_id: str, source, skill_name) -> dict:
        if self.error is not None:
            return dict(self.error)
        return {"ok": True, "skill": {"name": skill_name, "content": self.content}}


class _FakeInvoker:
    def __init__(self, result: ModelInvocationResult | None = None, error: BaseException | None = None, delay: float = 0.0) -> None:
        self.result = result
        self.error = error
        self.delay = delay
        self.requests: list[ModelInvocationRequest] = []

    async def invoke(self, request: ModelInvocationRequest) -> ModelInvocationResult:
        self.requests.append(request)
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error is not None:
            raise self.error
        assert self.result is not None
        return self.result


def _ctx(user_id: str = USER) -> SimpleNamespace:
    return SimpleNamespace(principal=SimpleNamespace(user_id=user_id))


def _bind(invoker) -> CapabilityHandle:
    handle = CapabilityHandle()
    handle.bind(invoker)
    return handle


def _jobs(tmp_path, invoker=None, *, mode="model", store=True, evolution=None) -> AnnotationEvolution:
    return AnnotationEvolution(
        evolution or _FakeEvolution(),
        EvolvedSkillStore(tmp_path / "store.sqlite") if store else None,
        _bind(invoker) if invoker is not None else CapabilityHandle(),
        mode_reader=lambda: mode,
    )


async def _wait_terminal(jobs: AnnotationEvolution, name: str) -> dict:
    for _ in range(200):
        result = await jobs.status({"skill_name": name}, _ctx())
        job = result.get("job")
        if job is not None and job["status"] != "running":
            return job
        await asyncio.sleep(0.01)
    raise AssertionError("the evolution job never reached a terminal state")


def test_launch_is_unavailable_in_draft_mode_or_without_capabilities(tmp_path) -> None:
    jobs = _jobs(tmp_path, _FakeInvoker(result=ModelInvocationResult(content="# New")), mode="append")
    assert asyncio.run(jobs.launch({"skill_name": "demo-evolution"}, _ctx())) == {"ok": False, "error": {"code": "UNAVAILABLE"}}
    # Agent mode but no store / no model grant.
    without_store = _jobs(tmp_path, _FakeInvoker(result=ModelInvocationResult(content="# New")), store=False)
    assert asyncio.run(without_store.launch({"skill_name": "demo-evolution"}, _ctx())) == {"ok": False, "error": {"code": "UNAVAILABLE"}}
    without_model = _jobs(tmp_path, None)
    assert asyncio.run(without_model.launch({"skill_name": "demo-evolution"}, _ctx())) == {"ok": False, "error": {"code": "UNAVAILABLE"}}


def test_launch_runs_the_model_and_records_the_draft(tmp_path) -> None:
    invoker = _FakeInvoker(result=ModelInvocationResult(content="```markdown\n# Demo\n\nImproved body.\n```", resolved_model="test-model", usage=ModelUsage(input_tokens=10, output_tokens=20)))
    jobs = _jobs(tmp_path, invoker)
    jobs._store.save_annotation(owner=USER, skill_name="demo-evolution", run_id="run-0001", event_id="evt-01", note="Add a step for X")

    async def scenario() -> None:
        launched = await jobs.launch({"skill_name": "demo-evolution"}, _ctx())
        assert launched["ok"] is True
        assert launched["status"] == "running"
        job = await _wait_terminal(jobs, "demo-evolution")
        assert job["status"] == "succeeded"
        # Fences are stripped; the draft is the diffable content.
        assert job["result_content"] == "# Demo\n\nImproved body.\n"
        assert job["base_content"] == "# Demo\n\nBody."
        assert job["resolved_model"] == "test-model"
        assert job["input_tokens"] == 10
        assert job["output_tokens"] == 20
        assert job["feedback_count"] == 1
        # One bounded prompt: policy + current content + the note.
        (request,) = invoker.requests
        assert request.purpose == "skill-evolution-feedback"
        system, user = request.messages
        assert system.role == "system"
        assert "SKILL.md" in system.content
        assert user.role == "user"
        assert "# Demo\n\nBody." in user.content
        assert "Add a step for X" in user.content

    asyncio.run(scenario())


def test_launch_records_a_stable_error_code_on_model_failure(tmp_path) -> None:
    invoker = _FakeInvoker(error=ModelInvocationFailed("provider exploded with /secret/path"))
    jobs = _jobs(tmp_path, invoker)

    async def scenario() -> None:
        launched = await jobs.launch({"skill_name": "demo-evolution"}, _ctx())
        assert launched["ok"] is True
        job = await _wait_terminal(jobs, "demo-evolution")
        assert job["status"] == "failed"
        assert job["error_code"] == "MODEL_FAILED"
        # No provider text and no contents leak into the status view.
        assert "provider exploded" not in repr(job)
        assert "result_content" not in job
        assert "base_content" not in job

    asyncio.run(scenario())


def test_model_unavailable_maps_to_its_own_code(tmp_path) -> None:
    invoker = _FakeInvoker(error=ModelInvocationUnavailable("capability stopped"))
    jobs = _jobs(tmp_path, invoker)

    async def scenario() -> None:
        await jobs.launch({"skill_name": "demo-evolution"}, _ctx())
        job = await _wait_terminal(jobs, "demo-evolution")
        assert job["error_code"] == "MODEL_UNAVAILABLE"

    asyncio.run(scenario())


def test_an_empty_draft_fails_the_job(tmp_path) -> None:
    invoker = _FakeInvoker(result=ModelInvocationResult(content="   "))
    jobs = _jobs(tmp_path, invoker)

    async def scenario() -> None:
        await jobs.launch({"skill_name": "demo-evolution"}, _ctx())
        job = await _wait_terminal(jobs, "demo-evolution")
        assert job["status"] == "failed"
        assert job["error_code"] == "MODEL_FAILED"

    asyncio.run(scenario())


def test_second_launch_while_running_answers_busy(tmp_path) -> None:
    invoker = _FakeInvoker(result=ModelInvocationResult(content="# New"), delay=0.2)
    jobs = _jobs(tmp_path, invoker)

    async def scenario() -> None:
        first = await jobs.launch({"skill_name": "demo-evolution"}, _ctx())
        assert first["ok"] is True
        second = await jobs.launch({"skill_name": "demo-evolution"}, _ctx())
        assert second == {"ok": False, "error": {"code": "BUSY"}}
        job = await _wait_terminal(jobs, "demo-evolution")
        assert job["status"] == "succeeded"

    asyncio.run(scenario())


def test_status_and_jobs_are_scoped_to_the_caller(tmp_path) -> None:
    invoker = _FakeInvoker(result=ModelInvocationResult(content="# New"))
    jobs = _jobs(tmp_path, invoker)

    async def scenario() -> None:
        await jobs.launch({"skill_name": "demo-evolution"}, _ctx())
        await _wait_terminal(jobs, "demo-evolution")
        foreign = await jobs.status({"skill_name": "demo-evolution"}, _ctx(OTHER))
        assert foreign["job"] is None

    asyncio.run(scenario())


def test_status_without_any_job_returns_none(tmp_path) -> None:
    jobs = _jobs(tmp_path, None)
    result = asyncio.run(jobs.status({"skill_name": "demo-evolution"}, _ctx()))
    assert result == {"ok": True, "skill_name": "demo-evolution", "job": None}


def test_discard_deletes_a_finished_job_and_cancels_a_running_one(tmp_path) -> None:
    fast = _jobs(tmp_path, _FakeInvoker(result=ModelInvocationResult(content="# New")))

    async def finished_scenario() -> None:
        await fast.launch({"skill_name": "demo-evolution"}, _ctx())
        job = await _wait_terminal(fast, "demo-evolution")
        discarded = await fast.discard({"skill_name": "demo-evolution", "job_id": job["job_id"]}, _ctx())
        assert discarded["ok"] is True
        result = await fast.status({"skill_name": "demo-evolution"}, _ctx())
        assert result["job"] is None
        missing = await fast.discard({"skill_name": "demo-evolution", "job_id": job["job_id"]}, _ctx())
        assert missing == {"ok": False, "error": {"code": "NOT_FOUND_OR_FORBIDDEN"}}

    asyncio.run(finished_scenario())

    slow = _jobs(tmp_path, _FakeInvoker(result=ModelInvocationResult(content="# New"), delay=5.0))

    async def running_scenario() -> None:
        launched = await slow.launch({"skill_name": "demo-evolution"}, _ctx())
        discarded = await slow.discard({"skill_name": "demo-evolution", "job_id": launched["job_id"]}, _ctx())
        assert discarded["ok"] is True
        # The cancel lands promptly; the store row is gone.
        for _ in range(100):
            await asyncio.sleep(0.01)
            if not slow._tasks:
                break
        result = await slow.status({"skill_name": "demo-evolution"}, _ctx())
        assert result["job"] is None

    asyncio.run(running_scenario())


def test_status_marks_a_committed_draft_as_published(tmp_path) -> None:
    invoker = _FakeInvoker(result=ModelInvocationResult(content="# Improved", resolved_model="m"))
    jobs = _jobs(tmp_path, invoker)

    async def scenario() -> None:
        await jobs.launch({"skill_name": "demo-evolution"}, _ctx())
        job = await _wait_terminal(jobs, "demo-evolution")
        assert job["status"] == "succeeded"
        assert job["published"] is False
        assert job["unchanged"] is False
        # The draft goes through the managed pipeline: stage, then commit
        # records it into the version journal.
        jobs._store.record_stage(owner=USER, proposal_id="prop-1", name="demo-evolution", content="# Improved")
        jobs._store.record_outcome(owner=USER, name="demo-evolution", method="commit", operation_id="op-1", proposal_id="prop-1")
        result = await jobs.status({"skill_name": "demo-evolution"}, _ctx())
        assert result["job"]["published"] is True
        # A different committed version leaves the draft pending again.
        jobs._store.record_stage(owner=USER, proposal_id="prop-2", name="demo-evolution", content="# Edited by hand")
        jobs._store.record_outcome(owner=USER, name="demo-evolution", method="commit", operation_id="op-2", proposal_id="prop-2")
        result = await jobs.status({"skill_name": "demo-evolution"}, _ctx())
        assert result["job"]["published"] is False

    asyncio.run(scenario())


def test_status_reports_an_unchanged_draft(tmp_path) -> None:
    # The rule was already committed before the job ran and the model kept
    # the content: not "published" (nothing new went through the pipeline)
    # but "unchanged" — the panel says so instead of an empty diff.
    invoker = _FakeInvoker(result=ModelInvocationResult(content="# Demo\n\nBody.", resolved_model="m"))
    jobs = _jobs(tmp_path, invoker)

    async def scenario() -> None:
        jobs._store.record_stage(owner=USER, proposal_id="prop-old", name="demo-evolution", content="# Demo\n\nBody.")
        jobs._store.record_outcome(owner=USER, name="demo-evolution", method="commit", operation_id="op-old", proposal_id="prop-old")
        # Backdate the commit: it clearly predates the job (sqlite
        # timestamps share one-second resolution, so same-second ordering
        # is forced here).
        with closing(jobs._store.connect()) as db, db:
            db.execute("UPDATE evolved_history SET updated_at='2000-01-01 00:00:00' WHERE operation_id='op-old'")
        await jobs.launch({"skill_name": "demo-evolution"}, _ctx())
        job = await _wait_terminal(jobs, "demo-evolution")
        assert job["status"] == "succeeded"
        assert job["published"] is False
        assert job["unchanged"] is True
        # Saving a new annotation supersedes the no-change record.
        assert jobs._store.delete_published_job(owner=USER, skill_name="demo-evolution") is True
        result = await jobs.status({"skill_name": "demo-evolution"}, _ctx())
        assert result["job"] is None

    asyncio.run(scenario())


def test_launch_accepts_a_granted_model_role(tmp_path, monkeypatch) -> None:
    invoker = _FakeInvoker(result=ModelInvocationResult(content="# Improved", resolved_model="GLM-5-4"))
    jobs = _jobs(tmp_path, invoker)
    monkeypatch.setattr("deerflow_extension_skill_evolution.evolve.granted_model_roles", lambda: {"default": "GLM-5-3", "GLM-5-4": "GLM-5-4"})

    async def scenario() -> None:
        await jobs.launch({"skill_name": "demo-evolution", "model_role": "GLM-5-4"}, _ctx())
        job = await _wait_terminal(jobs, "demo-evolution")
        assert job["status"] == "succeeded"
        # The chosen role travelled with the invocation request.
        assert invoker.requests[0].model_role == "GLM-5-4"
        # An ungranted role fails fast instead of burning a background job.
        rejected = await jobs.launch({"skill_name": "demo-evolution", "model_role": "not-granted"}, _ctx())
        assert rejected == {"ok": False, "error": {"code": "UNKNOWN_MODEL_ROLE"}}
        # Malformed roles never reach the pipeline either.
        malformed = await jobs.launch({"skill_name": "demo-evolution", "model_role": " "}, _ctx())
        assert malformed == {"ok": False, "error": {"code": "INVALID_REQUEST"}}

    asyncio.run(scenario())


def test_launch_returns_the_pipeline_error_unchanged(tmp_path) -> None:
    error = {"ok": False, "error": {"code": "SOURCE_STALE_OR_GONE"}}
    jobs = _jobs(tmp_path, _FakeInvoker(result=ModelInvocationResult(content="# New")), evolution=_FakeEvolution(error=error))
    result = asyncio.run(jobs.launch({"skill_name": "demo-evolution"}, _ctx()))
    assert result == error


@pytest.mark.parametrize("payload", [{}, {"skill_name": "demo-evolution", "extra": 1}, None, {"skill_name": "Bad Name"}])
def test_launch_rejects_invalid_payloads(tmp_path, payload) -> None:
    jobs = _jobs(tmp_path, _FakeInvoker(result=ModelInvocationResult(content="# New")))
    result = asyncio.run(jobs.launch(payload, _ctx()))
    assert result["ok"] is False
    assert result["error"]["code"] == "INVALID_REQUEST"


@pytest.mark.parametrize("action", ["launch", "status"])
def test_actions_require_an_authenticated_caller(tmp_path, action) -> None:
    jobs = _jobs(tmp_path, None)
    handler = getattr(jobs, action)
    result = asyncio.run(handler({"skill_name": "demo-evolution"}, SimpleNamespace(principal=None)))
    assert result == {"ok": False, "error": {"code": "UNAUTHENTICATED"}}


def test_messages_are_owner_scoped_and_bounded() -> None:
    annotations = [{"run_id": f"run-{i:04d}", "event_id": f"evt-{i:02d}", "note": f"note {i}", "updated_at": f"2026-01-01 00:00:{i:02d}"} for i in range(30)]
    messages = _build_messages("# Demo", annotations)
    assert len(messages) == 2
    user = messages[1].content
    # Bounded: only the newest notes make it into the prompt.
    assert user.count("note ") <= 20
    assert "# Demo" in user


def test_system_prompt_forbids_changelog_sections() -> None:
    # The model once reorganised loose history lines into a "Revision log"
    # section on its own; the prompt must pin that behaviour out.
    messages = _build_messages("# Demo", [{"run_id": "run-1", "event_id": "42", "note": "n", "updated_at": "2026-01-01"}])
    system = messages[0].content
    assert "changelog / revision-log / history sections" in system
    assert "only changes you make are the ones the feedback notes require" in system


def test_strip_fences_unwraps_one_surrounding_fence() -> None:
    assert _strip_fences("```markdown\n# Title\n```") == "# Title\n"
    assert _strip_fences("# Plain") == "# Plain\n"
    assert _strip_fences("  \n# Keep\n  \n") == "# Keep\n"


def test_store_sweeps_stale_running_jobs(tmp_path) -> None:
    store = EvolvedSkillStore(tmp_path / "store.sqlite")
    assert store.start_job(owner=USER, skill_name="demo-evolution", job_id="stale-job", base_content="# Demo", feedback_count=0)
    assert store.start_job(owner=USER, skill_name="demo-evolution", job_id="live-job", base_content="# Demo", feedback_count=0) is False
    with closing(store.connect()) as db, db:
        db.execute("UPDATE evolution_jobs SET updated_at = datetime('now', '-2 hours') WHERE job_id = 'stale-job'")
    swept = store.sweep_stale_jobs(owner=USER, skill_name="demo-evolution")
    assert swept == 1
    # The partial unique index no longer blocks a fresh admission.
    assert store.start_job(owner=USER, skill_name="demo-evolution", job_id="fresh-job", base_content="# Demo", feedback_count=0)


def test_foreign_discard_cannot_cancel_another_users_running_job(tmp_path):
    jobs = _jobs(tmp_path, _FakeInvoker(result=ModelInvocationResult(content="# New"), delay=5))

    async def scenario():
        launched = await jobs.launch({"skill_name": "demo-evolution"}, _ctx())
        task = jobs._tasks[launched["job_id"]]
        await asyncio.sleep(0)
        for caller, skill in [(OTHER, "demo-evolution"), (USER, "different-skill")]:
            result = await jobs.discard({"skill_name": skill, "job_id": launched["job_id"]}, _ctx(caller))
            assert result == {"ok": False, "error": {"code": "NOT_FOUND_OR_FORBIDDEN"}}
            assert task.cancelling() == 0
            assert not task.done()
            assert (await jobs.status({"skill_name": "demo-evolution"}, _ctx()))["job"]["status"] == "running"
        assert (await jobs.discard({"skill_name": "demo-evolution", "job_id": launched["job_id"]}, _ctx()))["ok"]
        await asyncio.gather(task, return_exceptions=True)

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "content",
    [
        "```markdown\nexample one\n```\n\nKeep this instruction.\n\n```python\nprint('two')\n```",
        "```yaml\nname: skill\n```",
    ],
)
def test_strip_fences_preserves_document_code_blocks(content):
    assert _strip_fences(content) == content + "\n"


def test_strip_fences_accepts_a_longer_outer_markdown_wrapper():
    assert _strip_fences("````markdown\n# Skill\n```python\nprint('keep')\n```\n````") == "# Skill\n```python\nprint('keep')\n```\n"


def test_session_can_choose_chat_model_without_plugin_grants(tmp_path):
    invoker = _FakeInvoker(result=ModelInvocationResult(content="# From chat model", resolved_model="GLM-5-2"))
    jobs = _jobs(tmp_path, None)
    ctx = SimpleNamespace(principal=SimpleNamespace(user_id=USER), chat_models=invoker)

    async def scenario():
        launched = await jobs.launch({"skill_name": "demo-evolution", "model_name": "GLM-5-2"}, ctx)
        assert launched["ok"]
        job = await _wait_terminal(jobs, "demo-evolution")
        assert job["status"] == "succeeded"
        assert invoker.requests[0].model_name == "GLM-5-2"
        assert invoker.requests[0].model_role is None

    asyncio.run(scenario())


def test_direct_model_selection_requires_browser_bound_chat_capability(tmp_path):
    jobs = _jobs(tmp_path, _FakeInvoker(result=ModelInvocationResult(content="# Legacy")))
    result = asyncio.run(jobs.launch({"skill_name": "demo-evolution", "model_name": "GLM-5-2"}, _ctx()))
    assert result == {"ok": False, "error": {"code": "CHAT_MODELS_UNAVAILABLE"}}


@pytest.mark.parametrize("model", ["", " ", 123, "x" * 201])
def test_chat_model_selection_validates_name(tmp_path, model):
    jobs = _jobs(tmp_path, None)
    ctx = SimpleNamespace(principal=SimpleNamespace(user_id=USER), chat_models=object())
    result = asyncio.run(jobs.launch({"skill_name": "demo-evolution", "model_name": model}, ctx))
    assert result == {"ok": False, "error": {"code": "INVALID_REQUEST"}}


def test_browser_cannot_fall_back_to_operator_roles(tmp_path):
    legacy = _FakeInvoker(result=ModelInvocationResult(content="# Privileged"))
    jobs = _jobs(tmp_path, legacy)
    chat = _FakeInvoker(result=ModelInvocationResult(content="# Chat"))
    ctx = SimpleNamespace(principal=SimpleNamespace(user_id=USER), interaction="session", chat_models=chat)
    result = asyncio.run(jobs.launch({"skill_name": "demo-evolution", "model_role": "default"}, ctx))
    assert result == {"ok": False, "error": {"code": "INVALID_REQUEST"}}
    assert not legacy.requests and not chat.requests
    ctx.chat_models = None
    result = asyncio.run(jobs.launch({"skill_name": "demo-evolution"}, ctx))
    assert result == {"ok": False, "error": {"code": "CHAT_MODELS_UNAVAILABLE"}}
    assert not legacy.requests
