"""Standalone script for cron-triggered local cache eviction.

Usage:
    uv run python manage_eviction.py
    # or with custom retention:
    ARTIFACT_CACHE_RETENTION_DAYS=14 uv run python manage_eviction.py
"""

import logging
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

if __name__ == "__main__":
    from src.queue.artifact_tasks import evict_stale_threads

    days = int(os.environ.get("ARTIFACT_CACHE_RETENTION_DAYS", "7"))
    result = evict_stale_threads(days)
    print(f"Eviction: {result}")
