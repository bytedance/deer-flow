from typing import Protocol, runtime_checkable

from deerflow.domain.feedback.model import Feedback


@runtime_checkable
class FeedbackRepository(Protocol):
    """Output port for feedback persistence.

    Implementations exchange domain objects only and translate storage
    failures into domain errors -- no storage vocabulary (SQL, tables,
    files) may leak through this contract.
    """

    async def save(self, feedback: Feedback) -> Feedback:
        """Store the user's current rating for a run (idempotent upsert).

        Creates the entry if absent; otherwise replaces rating/comment and
        refreshes created_at while keeping the aggregate identity
        (thread_id, run_id, user_id). Returns the stored state.
        """
        ...

    async def latest_per_run_in_thread(self, thread_id: str, *, user_id: str | None) -> dict[str, Feedback]:
        """Return each run's current feedback across a whole thread, keyed by run_id.

        Single bulk read used to badge the message list -- avoids one
        query per run. Ownership filter: a non-None user_id restricts results to the
        user's entries; None means no filtering (no-auth mode).
        """
        ...

    async def latest_for_runs(self, thread_id: str, run_ids: set[str], *, user_id: str | None) -> dict[str, Feedback]:
        """Return current feedback for only the selected runs of a thread.

        Paged variant of latest_per_run_in_thread: the message-list page
        endpoint only needs badges for the runs on the current page.
        Returns an empty mapping when run_ids is empty. Same ownership
        filter as find_for_run.
        """
        ...

    async def remove_for_run(self, thread_id: str, run_id: str, *, user_id: str | None) -> bool:
        """Retract the user's feedback for a run.

        Returns True if an entry was removed, False if none existed.
        Ownership filter: a non-None user_id restricts results to the
        user's entries; None means no filtering (no-auth mode).
        """
        ...


class RunLookup(Protocol):
    """Narrow output port: the only question the feedback context asks
    about runs -- which thread does a run belong to.

    Deliberately not the full run store: depending on this one-method
    contract keeps the feedback context decoupled from the execution
    context's wide repository interface (interface segregation).
    """

    async def thread_of(self, run_id: str) -> str | None:
        """Return the thread_id owning the given run, or None if the run
        does not exist.

        Used by the service to verify run ownership before writing
        feedback (rejects cross-thread run ids as RunNotFoundError).
        """
        ...
