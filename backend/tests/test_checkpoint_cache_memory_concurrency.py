"""Concurrent sync readers share the provider's process-local history cache."""

import asyncio
import threading
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor

import pytest

from deerflow.runtime.checkpoint_cache.base import make_history_key
from deerflow.runtime.checkpoint_cache.memory import MemoryCheckpointHistoryCache


@pytest.mark.parametrize("mutation", ["evict", "purge", "close"])
def test_lookup_survives_concurrent_removal(mutation):
    cache = MemoryCheckpointHistoryCache(max_entries=1)
    key = make_history_key("p", "t1", "", "c1", "messages")
    entry = {"writes": [("task", "messages", "original")], "seed": "seed"}
    cache.set_many({key: entry})
    looked_up = threading.Event()
    release_reader = threading.Event()
    writer_started = threading.Event()
    writer_finished = threading.Event()

    class PausedLookup(OrderedDict):
        def get(self, lookup_key, default=None):
            value = super().get(lookup_key, default)
            if lookup_key == key:
                looked_up.set()
                assert release_reader.wait(5), "reader was not released"
            return value

    # Pause at the actual lookup -> LRU promotion window, not before get_many.
    cache._data = PausedLookup(cache._data)

    def remove():
        writer_started.set()
        try:
            if mutation == "evict":
                cache.set_many({"other": {"writes": []}})
            elif mutation == "purge":
                cache.delete_thread("p", "t1")
            else:
                asyncio.run(cache.aclose())
        finally:
            writer_finished.set()

    with ThreadPoolExecutor(max_workers=2) as pool:
        reader = pool.submit(cache.get_many, [key])
        try:
            assert looked_up.wait(5)
            writer = pool.submit(remove)
            assert writer_started.wait(5)
            # On main the writer removes the key inside the paused lookup;
            # with serialization it waits until the reader has copied its hit.
            writer_finished.wait(0.2)
        finally:
            release_reader.set()
        assert reader.result(timeout=5) == {key: entry}
        writer.result(timeout=5)
    assert cache.get_many([key]) == {}
    assert cache.stats().entries == int(mutation == "evict")


def test_parallel_read_write_keeps_capacity_and_accounting():
    cache = MemoryCheckpointHistoryCache(max_entries=4)
    start = threading.Barrier(8)

    def exercise(worker):
        start.wait(timeout=5)
        for n in range(200):
            key = f"{worker}:{n}"
            cache.set_many({key: {"writes": [("task", "messages", key)]}})
            result = cache.get_many([key])
            if key in result:
                assert result[key]["writes"] == [("task", "messages", key)]

    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(exercise, range(8)))
    stats = cache.stats()
    assert stats.entries == 4
    assert stats.evictions == 8 * 200 - 4
    assert stats.hits + stats.misses == 8 * 200
