"""Commands of the schedule context.

One frozen dataclass per HTTP-driven state-changing use case -- the named
carrier of "the information required to perform an operation on the domain"
(AWS hexagonal guidance). Commands are dumb data on purpose: business
validation stays on the aggregate (``ScheduledTask``'s factory and
transitions), and structural validation stays on the primary adapter's api
model, so error attribution (a malformed schedule reported before an unknown
thread) is owned by the handler's construction order.

Two groups of use cases are deliberately NOT commands:

- **Queries** (``list_tasks``, ``get_task``, ``list_task_runs``, ...) keep
  plain parameters -- a command expresses an intent to change state, and
  wrapping reads would be pure boilerplate.
- **Clock- and callback-driven writes** (``run_once``, ``dispatch_task``,
  ``handle_run_completion``, ``reconcile_on_startup``). Those drivers have no
  wire shape to translate (spec §5.3): the poller hands the service a claimed
  aggregate and a clock reading, and the completion hook hands it an already
  domain-typed ``RunOutcome``. A command would re-wrap domain vocabulary in
  more domain vocabulary.

``now`` is not a command field: it is the server's clock reading, passed
explicitly to the handler (``now=``) like every other rule input, not part of
the client's intent.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from deerflow.domain.schedule.model import ContextMode, ScheduleSpec


@dataclass(frozen=True)
class ContextChange:
    """A requested change of execution context.

    The mode and the thread always move together -- ``with_context`` takes
    both, and clearing the thread is what switching to a fresh-thread mode
    means. Packaging them keeps ``None`` unambiguous everywhere else: the one
    field for which ``None`` is a meaningful value travels inside this object.
    """

    context_mode: str | ContextMode
    thread_id: str | None = None


@dataclass(frozen=True)
class CreateScheduledTask:
    """Register a new standing instruction to run a prompt on time."""

    user_id: str
    title: str
    prompt: str
    schedule: ScheduleSpec
    context_mode: str | ContextMode
    thread_id: str | None = None


@dataclass(frozen=True)
class UpdateScheduledTask:
    """Partially update a task; ``None`` means "not supplied".

    ``None`` can double as the absence marker ONLY because every field here
    is non-nullable as a business value -- there is no "set the title to
    null". Keep it that way: a future field whose ``None`` is meaningful
    must travel inside a small change object instead, the way the nullable
    ``thread_id`` already rides inside ``ContextChange``.
    """

    task_id: str
    user_id: str
    title: str | None = None
    prompt: str | None = None
    schedule: ScheduleSpec | None = None
    context: ContextChange | None = None


@dataclass(frozen=True)
class PauseTask:
    """Stop claiming this task until it is resumed."""

    task_id: str
    user_id: str


@dataclass(frozen=True)
class ResumeTask:
    """Re-admit this task to claiming."""

    task_id: str
    user_id: str


@dataclass(frozen=True)
class DeleteTask:
    """Remove the task; its execution history rows go with it."""

    task_id: str
    user_id: str


@dataclass(frozen=True)
class TriggerTask:
    """Dispatch a task on demand, even while it is paused."""

    task_id: str
    user_id: str
