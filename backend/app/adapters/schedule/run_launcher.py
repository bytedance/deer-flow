"""Secondary adapter (anti-corruption layer) -- starting a run through Gateway.

Implements ``RunLauncher`` from ``deerflow.domain.schedule.ports``. This context
owns no part of the run lifecycle: it asks the Gateway to start one and
translates whatever comes back into the two outcomes the domain distinguishes.

That translation is the reason this file exists. The Gateway signals a busy
thread two different ways -- ``ConflictError`` from the run manager, or an
``HTTPException(409)`` from the route-level path -- and the legacy scheduler
service therefore imported ``fastapi`` to tell them apart. Both are the same
domain fact, and saying so here is what keeps the web framework and the run
runtime out of the inner ring.

TODO(hexagonal): this depends on ``launch_scheduled_thread_run``, a Gateway
service function returning an untyped dict, rather than on a contract published
by the run context -- that context has not been through a hexagonal slice yet.
When it publishes one (a DTO, not its aggregate and not its repository),
replace the body of this class. The ``RunLauncher`` port does not move.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from fastapi import HTTPException

from deerflow.domain.schedule.model import LaunchFailedError, ThreadBusyError
from deerflow.domain.schedule.ports import LaunchedRun, RunLauncher
from deerflow.runtime import ConflictError

LaunchRun = Callable[..., Awaitable[Mapping[str, Any]]]


class GatewayRunLauncher(RunLauncher):
    """Adapts the Gateway's scheduled-run launch path to the ``RunLauncher`` port.

    Takes the launch callable rather than importing it, because the production
    one is bound to the FastAPI app (``launch_scheduled_thread_run(app=app,
    ...)``) and that binding belongs to the composition root.

    Explicit inheritance is a readability aid only: a misspelled method would
    still instantiate fine and silently inherit the Protocol's ``...`` body,
    so the contract tests must call every port method and assert on what it
    returns.
    """

    def __init__(self, launch_run: LaunchRun) -> None:
        self._launch_run = launch_run

    async def launch(
        self,
        *,
        thread_id: str,
        assistant_id: str | None,
        prompt: str,
        owner_user_id: str | None,
        metadata: dict[str, str],
    ) -> LaunchedRun:
        try:
            result = await self._launch_run(
                thread_id=thread_id,
                assistant_id=assistant_id,
                prompt=prompt,
                owner_user_id=owner_user_id,
                metadata=metadata,
            )
        except ConflictError as exc:
            raise ThreadBusyError(str(exc)) from exc
        except HTTPException as exc:
            if exc.status_code == 409:
                raise ThreadBusyError(str(exc.detail)) from exc
            raise LaunchFailedError(str(exc.detail)) from exc
        except Exception as exc:
            # Deliberately broad: the port promises the domain that nothing but
            # its two errors escapes, so an unclassifiable failure has to become
            # the "genuine failure" branch rather than unwinding the poll loop.
            # `CancelledError` derives from BaseException and is not caught --
            # shutdown is control flow, not a launch outcome.
            raise LaunchFailedError(str(exc)) from exc

        run_id = result.get("run_id")
        launched_thread_id = result.get("thread_id")
        if not isinstance(run_id, str) or not isinstance(launched_thread_id, str):
            # The run path broke its own contract. Reporting it as a failure
            # keeps the task's bookkeeping honest instead of recording a launch
            # whose run can never be traced.
            raise LaunchFailedError(f"run launch returned no usable identity: {result!r}")
        return LaunchedRun(run_id=run_id, thread_id=launched_thread_id)
