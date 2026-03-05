"""Entry point for the RQ background worker.

Processes memory update jobs from the Redis 'memory_updates' queue.
Supports delayed job scheduling (debounce) via RQ's built-in scheduler.

Usage:
    uv run python worker.py
    # or via rq CLI:
    uv run rq worker memory_updates --url $REDIS_URL --with-scheduler
"""

import logging
import os
import sys

# Ensure the backend directory is in the Python path
sys.path.insert(0, os.path.dirname(__file__))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

logger = logging.getLogger(__name__)

if __name__ == "__main__":
    from redis import Redis
    from rq import Queue, Worker

    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    logger.info(f"Starting memory update worker, connecting to {redis_url}")

    redis_conn = Redis.from_url(redis_url)
    queues = [
        Queue("memory_updates", connection=redis_conn),
        Queue("artifact_sync", connection=redis_conn),
    ]

    worker = Worker(
        queues,
        connection=redis_conn,
        name=f"memory-worker-{os.getpid()}",
    )
    # with_scheduler enables delayed job processing (used for debounce)
    worker.work(with_scheduler=True)
