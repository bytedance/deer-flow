"""Tests for thread-safe singleton initialization in checkpointer and store providers."""

import threading

import pytest

import deerflow.config.app_config as app_config_module
from deerflow.agents.checkpointer import get_checkpointer, reset_checkpointer
from deerflow.config.checkpointer_config import set_checkpointer_config
from deerflow.runtime.store.provider import get_store, reset_store


@pytest.fixture(autouse=True)
def _reset_singletons():
    app_config_module._app_config = None
    set_checkpointer_config(None)
    reset_checkpointer()
    reset_store()
    yield
    app_config_module._app_config = None
    set_checkpointer_config(None)
    reset_checkpointer()
    reset_store()


class TestCheckpointerSingletonConcurrency:
    def test_concurrent_get_returns_same_instance(self):
        set_checkpointer_config(None)
        results = []
        barrier = threading.Barrier(8)

        def worker():
            barrier.wait()
            results.append(id(get_checkpointer()))

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(results) == 8
        assert len(set(results)) == 1

    def test_reset_during_init_is_serialized(self):
        set_checkpointer_config(None)
        errors = []

        def init_worker():
            try:
                get_checkpointer()
            except Exception as e:
                errors.append(e)

        def reset_worker():
            try:
                reset_checkpointer()
            except Exception as e:
                errors.append(e)

        threads = []
        for _ in range(4):
            threads.append(threading.Thread(target=init_worker))
            threads.append(threading.Thread(target=reset_worker))

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []

    def test_get_after_reset_returns_valid_instance(self):
        set_checkpointer_config(None)
        first = get_checkpointer()
        reset_checkpointer()
        second = get_checkpointer()
        assert first is not None
        assert second is not None


class TestStoreSingletonConcurrency:
    def test_concurrent_get_returns_same_instance(self):
        set_checkpointer_config(None)
        results = []
        barrier = threading.Barrier(8)

        def worker():
            barrier.wait()
            results.append(id(get_store()))

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(results) == 8
        assert len(set(results)) == 1

    def test_reset_during_init_is_serialized(self):
        set_checkpointer_config(None)
        errors = []

        def init_worker():
            try:
                get_store()
            except Exception as e:
                errors.append(e)

        def reset_worker():
            try:
                reset_store()
            except Exception as e:
                errors.append(e)

        threads = []
        for _ in range(4):
            threads.append(threading.Thread(target=init_worker))
            threads.append(threading.Thread(target=reset_worker))

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == []

    def test_get_after_reset_returns_valid_instance(self):
        set_checkpointer_config(None)
        first = get_store()
        reset_store()
        second = get_store()
        assert first is not None
        assert second is not None
