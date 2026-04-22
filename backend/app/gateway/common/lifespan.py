from collections.abc import Callable
from contextlib import AbstractAsyncContextManager, AsyncExitStack, asynccontextmanager
from typing import Any

from fastapi import FastAPI

LifespanFunc = Callable[[FastAPI], AbstractAsyncContextManager[dict[str, Any] | None]]


class LifespanManager:
    """FastAPI lifespan manager"""

    def __init__(self) -> None:
        self._lifespans: list[LifespanFunc] = []

    def register(self, func: LifespanFunc) -> LifespanFunc:
        """
        Register a lifespan hook.

        :param func: lifespan hook
        :return:
        """
        if func not in self._lifespans:
            self._lifespans.append(func)
        return func

    def build(self) -> LifespanFunc:
        """
        Build the combined lifespan hook.

        :return:
        """

        @asynccontextmanager
        async def combined_lifespan(app: FastAPI):  # noqa: ANN202
            state: dict[str, Any] = {}
            async with AsyncExitStack() as exit_stack:
                for lifespan_fn in self._lifespans:
                    result = await exit_stack.enter_async_context(lifespan_fn(app))
                    if isinstance(result, dict):
                        state.update(result)

                for key, value in state.items():
                    setattr(app.state, key, value)

                yield state or None

        return combined_lifespan


# Singleton lifespan_manager instance
lifespan_manager = LifespanManager()
