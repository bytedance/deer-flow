"""Novel tags API for scanning book directories."""

import logging
import time

from fastapi import APIRouter

from deerflow.config.paths import get_paths

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/novel-tags", tags=["novel-tags"])

# Simple cache with 5-minute TTL
_novel_tags_cache = {
    "tags": [],
    "last_updated": 0,
    "ttl": 300,  # 5 minutes
}


@router.get("/")
async def get_novel_tags():
    """
    Get all available novel tags.

    Scans all threads' workspace/book directories and returns
    all novel folder names as tag enum values.
    """
    current_time = time.time()

    # Check cache validity
    if _novel_tags_cache["tags"] and current_time - _novel_tags_cache["last_updated"] < _novel_tags_cache["ttl"]:
        return {"tags": _novel_tags_cache["tags"]}

    try:
        paths = get_paths()
        base_dir = paths.base_dir
        threads_dir = base_dir / "threads"

        if not threads_dir.exists():
            return {"tags": []}

        tags = set()

        # Iterate through all thread directories
        for thread_dir in threads_dir.iterdir():
            if not thread_dir.is_dir():
                continue

            # Check book directory
            book_dir = thread_dir / "user-data" / "workspace" / "book"

            if book_dir.exists() and book_dir.is_dir():
                # Collect all first-level folder names
                for item in book_dir.iterdir():
                    if item.is_dir():
                        tags.add(item.name)

        sorted_tags = sorted(list(tags))

        # Update cache
        _novel_tags_cache["tags"] = sorted_tags
        _novel_tags_cache["last_updated"] = current_time

        return {"tags": sorted_tags}

    except Exception as e:
        logger.error(f"Failed to get novel tags: {e}")
        # Return cached data if available, otherwise empty list
        return {"tags": _novel_tags_cache["tags"]}
