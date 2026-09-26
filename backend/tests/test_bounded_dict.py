"""Tests for ``BoundedDict`` — the shared LRU-evicting ordered dict used by
guard middlewares (TokenBudgetMiddleware, LoopDetectionMiddleware)."""

from deerflow.agents.middlewares._bounded_dict import BoundedDict


class TestBoundedDict:
    def test_basic_eviction_fifo_when_no_updates(self):
        """Without updates, oldest key is evicted first (FIFO)."""
        bd = BoundedDict(maxsize=2)
        bd["a"] = 1
        bd["b"] = 2
        bd["c"] = 3
        assert "a" not in bd
        assert "b" in bd
        assert "c" in bd

    def test_update_refreshes_recency(self):
        """Writing an existing key moves it to the end (LRU), so it survives
        eviction when the dict fills up."""
        bd = BoundedDict(maxsize=2)
        bd["a"] = 1
        bd["b"] = 2
        bd["a"] = 10  # refresh recency — a is now youngest
        bd["c"] = 3  # triggers eviction — b (oldest) is dropped
        assert "a" in bd, "updated key 'a' should survive eviction (LRU)"
        assert "b" not in bd, "never-updated key 'b' should be evicted (LRU)"
        assert "c" in bd
        assert bd["a"] == 10

    def test_update_single_entry_at_capacity(self):
        """Updating the only entry at capacity=1 must not trigger erroneous
        self-eviction."""
        bd = BoundedDict(maxsize=1)
        bd["a"] = 1
        bd["a"] = 2
        assert "a" in bd
        assert bd["a"] == 2
        assert len(bd) == 1

    def test_updated_key_is_the_oldest_before_eviction(self):
        """Edge case: the key being updated is also the one that would have
        been evicted next (the oldest). Updating it must refresh recency and
        evict the next-oldest key instead."""
        bd = BoundedDict(maxsize=3)
        bd["a"] = 1
        bd["b"] = 2
        bd["c"] = 3
        # "a" is oldest. Update it — now "b" is oldest.
        bd["a"] = 10
        bd["d"] = 4  # triggers eviction → drops "b", not "a"
        assert "a" in bd, "updated oldest key should survive"
        assert "b" not in bd, "next-oldest should be evicted"
        assert "c" in bd
        assert "d" in bd

    def test_len_respects_maxsize(self):
        bd = BoundedDict(maxsize=3)
        for i in range(10):
            bd[f"k{i}"] = i
        assert len(bd) == 3
