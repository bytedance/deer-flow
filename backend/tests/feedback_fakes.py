"""Shared zero-IO doubles for the feedback context.

Lives in its own module rather than inside a test file so both the port
contract suite (``test_feedback.py``) and the service tests
(``test_feedback_service.py``) can import it as an ordinary module, without
relying on the tests directory happening to be on ``sys.path``.
"""

from dataclasses import replace

from deerflow.domain.feedback import Feedback


class InMemoryFeedbackRepository:
    """Zero-IO fake keyed by aggregate identity (thread, run, user)."""

    def __init__(self) -> None:
        self._rows: dict[tuple[str, str, str | None], Feedback] = {}

    async def save(self, feedback: Feedback) -> Feedback:
        key = (feedback.thread_id, feedback.run_id, feedback.user_id)
        existing = self._rows.get(key)
        if existing is not None:
            feedback = replace(feedback, feedback_id=existing.feedback_id)
        self._rows[key] = feedback
        return feedback

    async def latest_per_run_in_thread(self, thread_id: str, *, user_id: str | None) -> dict[str, Feedback]:
        return {fb.run_id: fb for (thread, _run, user), fb in self._rows.items() if thread == thread_id and (user_id is None or user == user_id)}

    async def latest_for_runs(self, thread_id: str, run_ids: set[str], *, user_id: str | None) -> dict[str, Feedback]:
        if not run_ids:
            return {}
        per_run = await self.latest_per_run_in_thread(thread_id, user_id=user_id)
        return {run_id: fb for run_id, fb in per_run.items() if run_id in run_ids}

    async def remove_for_run(self, thread_id: str, run_id: str, *, user_id: str | None) -> bool:
        return self._rows.pop((thread_id, run_id, user_id), None) is not None


class FakeRunLookup:
    """RunLookup double backed by a run_id -> thread_id mapping."""

    def __init__(self, runs: dict[str, str]):
        self._runs = runs

    async def thread_of(self, run_id: str) -> str | None:
        return self._runs.get(run_id)
