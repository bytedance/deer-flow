from deerflow.domain.feedback.commands import RateRun, RetractRunRating
from deerflow.domain.feedback.exceptions import RunNotFoundError
from deerflow.domain.feedback.model import Feedback
from deerflow.domain.feedback.ports import FeedbackRepository, RunLookup


class FeedbackService:
    """Input port of the feedback context (application service).

    Orchestrates use cases only: fetch/verify -> apply domain rules ->
    persist through output ports. Holds no business rules itself (those
    live on the Feedback aggregate) and knows nothing about HTTP or
    storage. State-changing use cases take a command object (the handler
    is the method); queries take plain parameters. Resolving the current
    user is the primary adapter's job -- it arrives on the command.
    """

    def __init__(self, repository: FeedbackRepository, runs: RunLookup):
        self._repository = repository
        self._runs = runs

    async def _require_run(self, thread_id: str, run_id: str) -> None:
        """Reject runs that do not exist or belong to another thread."""
        if await self._runs.thread_of(run_id) != thread_id:
            raise RunNotFoundError("Run does not belong to the specified thread")

    async def rate_run(self, cmd: RateRun) -> Feedback:
        """Set the user's current rating for a run (idempotent).

        Backs the PUT endpoint: "my current verdict on this run is X".
        Builds the aggregate first (which validates rating and tags), then
        verifies run ownership, then stores it with upsert-by-identity
        semantics -- repeated calls replace the previous rating.

        Raises:
            InvalidRatingError: rating is not +1 or -1. Raised by the
                aggregate factory before any port call, so a malformed
                rating is reported as such even for an unknown run.
            InvalidTagError: a tag is not a known reason slug (same
                pre-I/O guarantee).
            RunNotFoundError: the run does not exist or does not belong
                to the given thread (cross-thread ids are rejected).
        """
        feedback = Feedback.create(
            run_id=cmd.run_id,
            thread_id=cmd.thread_id,
            rating=cmd.rating,
            user_id=cmd.user_id,
            comment=cmd.comment,
            tags=cmd.tags,
        )
        await self._require_run(cmd.thread_id, cmd.run_id)
        return await self._repository.save(feedback)

    async def retract_run_rating(self, cmd: RetractRunRating) -> bool:
        """Withdraw the user's rating for a run (clicking the active button
        again). Returns False when there was nothing to retract."""
        return await self._repository.remove_for_run(cmd.thread_id, cmd.run_id, user_id=cmd.user_id)

    async def latest_per_run_in_thread(self, thread_id: str, *, user_id: str | None) -> dict[str, Feedback]:
        """Current feedback per run across a thread -- powers the message-list
        thumb badges (full-list path)."""
        return await self._repository.latest_per_run_in_thread(thread_id, user_id=user_id)

    async def latest_for_runs(self, thread_id: str, run_ids: set[str], *, user_id: str | None) -> dict[str, Feedback]:
        """Current feedback for the selected runs only -- powers the paged
        message-list badges."""
        return await self._repository.latest_for_runs(thread_id, run_ids, user_id=user_id)
