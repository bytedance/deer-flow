from __future__ import annotations

from collections.abc import Awaitable, Callable


AsyncCloser = Callable[[], Awaitable[None]]


async def close_in_order(*closers: AsyncCloser) -> None:
    """
    Run async closers in order and raise the first error, if any.

    Notes
    -----
    - Used to keep driver-specific close logic readable.
    - We intentionally do not stop at first failure, so later resources
      still get a chance to close.
    """
    first_error: Exception | None = None

    for closer in closers:
        try:
            await closer()
        except Exception as exc:
            if first_error is None:
                first_error = exc

    if first_error is not None:
        raise first_error
