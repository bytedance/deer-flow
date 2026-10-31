"""Read the tail of the host's oldest-first changed-run metadata feed.

Only a bounded tail is retained; snapshot/event reads happen at the caller.
Metadata pagination must reach the end before that tail can be called recent.
Malformed or continuously growing feeds fail closed within a page budget.
"""

from collections import deque
from typing import Any

from deerflow_extension_api import HostCapabilityError

_MAX_METADATA_PAGES = 200


async def changed_runs(reader: Any, *, page_size: int = 200):
    """Stream metadata without retaining the entire owner-granted run feed."""
    cursor: str | None = None
    seen: set[str] = set()
    for _ in range(_MAX_METADATA_PAGES):
        page = await reader.list_changed_runs(cursor=cursor, limit=page_size)
        for item in page.items:
            yield item
        if not page.has_more:
            return
        next_cursor = page.next_cursor
        if not isinstance(next_cursor, str) or not next_cursor or next_cursor in seen:
            raise HostCapabilityError("UNAVAILABLE")
        seen.add(next_cursor)
        cursor = next_cursor
    raise HostCapabilityError("QUOTA_EXCEEDED")


async def recent_changed_runs(reader: Any, *, limit: int, page_size: int = 200) -> list[Any]:
    recent: deque[Any] = deque(maxlen=limit)
    async for item in changed_runs(reader, page_size=page_size):
        recent.append(item)
    return list(recent)
