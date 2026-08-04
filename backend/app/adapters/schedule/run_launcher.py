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

**Failed vs indeterminate is the load-bearing distinction** (#4452 / #4504).
``LaunchFailedError`` releases the task's single active slot, so it may only
be raised when no run can possibly have started; everything else has to be
``LaunchIndeterminateError``, which keeps the slot held with the identity
unknown. The split follows HTTP's own semantics: a 4xx means the request was
rejected before doing anything, while a 5xx -- or any other exception, or a
reply whose identity will not decode -- means the launch may already have had
its side effect. Guessing "failed" there is what re-opens duplicate execution.

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

from deerflow.domain.schedule.exceptions import LaunchFailedError, LaunchIndeterminateError, ThreadBusyError
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
            if exc.status_code < 500:
                # Rejected on the way in -- bad argument, unknown thread. The
                # request never got far enough to start anything, which is the
                # only condition under which releasing the slot is safe.
                raise LaunchFailedError(str(exc.detail)) from exc
            # A 5xx is raised from inside the launch path, which may already
            # have created the run before failing.
            raise LaunchIndeterminateError(str(exc.detail)) from exc
        except Exception as exc:
            # Deliberately broad: the port promises the domain that nothing but
            # its three errors escapes. Unclassifiable means we cannot certify
            # that no run started -- a dropped connection after the request was
            # sent looks exactly like this -- so it is indeterminate, never
            # failed. `CancelledError` derives from BaseException and is not
            # caught: shutdown is control flow, not a launch outcome.
            raise LaunchIndeterminateError(str(exc)) from exc

        run_id = result.get("run_id")
        launched_thread_id = result.get("thread_id")
        if not isinstance(run_id, str) or not isinstance(launched_thread_id, str):
            # The launch returned, so a run probably exists -- we just cannot
            # name it. This is the port's indeterminate case by definition
            # (main's `launch_succeeded` is set before unpacking for the same
            # reason); calling it a failure here would release the slot and let
            # the next dispatch start a duplicate.
            raise LaunchIndeterminateError(f"run launch returned no usable identity: {result!r}")
        return LaunchedRun(run_id=run_id, thread_id=launched_thread_id)
