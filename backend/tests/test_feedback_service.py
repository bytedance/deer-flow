"""FeedbackService tests with injected fakes — zero IO, no engine.

The seam the ports create is what makes these tests possible: the service
is exercised end-to-end against dict-backed doubles.
"""

import pytest
from feedback_fakes import FakeRunLookup, InMemoryFeedbackRepository

from deerflow.domain.feedback import FeedbackService, InvalidRatingError, RunNotFoundError


def _service(runs: dict[str, str] | None = None) -> FeedbackService:
    return FeedbackService(
        repository=InMemoryFeedbackRepository(),
        runs=FakeRunLookup(runs if runs is not None else {"r1": "t1"}),
    )


class TestRateRun:
    @pytest.mark.anyio
    async def test_stores_rating(self):
        svc = _service()
        fb = await svc.rate_run("t1", "r1", rating=1, comment=None, user_id="u1")
        assert fb.rating == 1
        assert fb.user_id == "u1"

    @pytest.mark.anyio
    async def test_idempotent_upsert_keeps_identity(self):
        svc = _service()
        first = await svc.rate_run("t1", "r1", rating=1, comment=None, user_id="u1")
        second = await svc.rate_run("t1", "r1", rating=-1, comment="meh", user_id="u1")
        assert second.feedback_id == first.feedback_id
        assert second.rating == -1

    @pytest.mark.anyio
    async def test_enrich_with_tags(self):
        svc = _service()
        await svc.rate_run("t1", "r1", rating=-1, comment=None, user_id="u1")
        fb = await svc.rate_run("t1", "r1", rating=-1, comment="wrong", user_id="u1", tags=["incorrect"])
        assert fb.tags == ("incorrect",)

    @pytest.mark.anyio
    async def test_unknown_run_rejected(self):
        svc = _service({})
        with pytest.raises(RunNotFoundError):
            await svc.rate_run("t1", "r1", rating=1, comment=None, user_id="u1")

    @pytest.mark.anyio
    async def test_cross_thread_run_rejected(self):
        """A run id belonging to another thread must not be ratable through
        this thread's URL (ownership check)."""
        svc = _service({"r1": "other-thread"})
        with pytest.raises(RunNotFoundError):
            await svc.rate_run("t1", "r1", rating=1, comment=None, user_id="u1")

    @pytest.mark.anyio
    async def test_invalid_rating_rejected_before_run_lookup(self):
        # "unknown-run" is absent from the lookup, so a rating validated after
        # the RunLookup port call would surface RunNotFoundError instead.
        # Expecting InvalidRatingError is what pins validation ahead of I/O.
        svc = _service()
        with pytest.raises(InvalidRatingError):
            await svc.rate_run("t1", "unknown-run", rating=0, comment=None, user_id="u1")


class TestRetractAndReads:
    @pytest.mark.anyio
    async def test_retract(self):
        svc = _service()
        await svc.rate_run("t1", "r1", rating=1, comment=None, user_id="u1")
        assert await svc.retract_run_rating("t1", "r1", user_id="u1") is True
        assert await svc.retract_run_rating("t1", "r1", user_id="u1") is False

    @pytest.mark.anyio
    async def test_latest_per_run_in_thread(self):
        svc = _service({"r1": "t1", "r2": "t1"})
        await svc.rate_run("t1", "r1", rating=1, comment=None, user_id="u1")
        await svc.rate_run("t1", "r2", rating=-1, comment=None, user_id="u1")
        grouped = await svc.latest_per_run_in_thread("t1", user_id="u1")
        assert {run_id: fb.rating for run_id, fb in grouped.items()} == {"r1": 1, "r2": -1}

    @pytest.mark.anyio
    async def test_latest_for_runs(self):
        svc = _service({"r1": "t1", "r2": "t1"})
        await svc.rate_run("t1", "r1", rating=1, comment=None, user_id="u1")
        await svc.rate_run("t1", "r2", rating=-1, comment=None, user_id="u1")
        grouped = await svc.latest_for_runs("t1", {"r2"}, user_id="u1")
        assert set(grouped) == {"r2"}
