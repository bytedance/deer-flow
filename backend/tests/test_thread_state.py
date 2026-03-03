"""Tests for ThreadState reducers: merge_artifacts, merge_viewed_images, merge_token_usage."""

from __future__ import annotations

from src.agents.thread_state import (
    ThreadState,
    merge_artifacts,
    merge_token_usage,
    merge_viewed_images,
)


# ---------------------------------------------------------------------------
# merge_artifacts
# ---------------------------------------------------------------------------
class TestMergeArtifacts:
    """Tests for the merge_artifacts reducer."""

    def test_none_existing_returns_new(self) -> None:
        assert merge_artifacts(None, ["a", "b"]) == ["a", "b"]

    def test_none_new_returns_existing(self) -> None:
        assert merge_artifacts(["a"], None) == ["a"]

    def test_both_none_returns_empty(self) -> None:
        assert merge_artifacts(None, None) == []

    def test_deduplicates(self) -> None:
        result = merge_artifacts(["a", "b"], ["b", "c"])
        assert result == ["a", "b", "c"]

    def test_preserves_order(self) -> None:
        result = merge_artifacts(["c", "a"], ["b", "d"])
        assert result == ["c", "a", "b", "d"]

    def test_all_duplicates(self) -> None:
        result = merge_artifacts(["a", "b"], ["a", "b"])
        assert result == ["a", "b"]

    def test_empty_existing(self) -> None:
        result = merge_artifacts([], ["x"])
        assert result == ["x"]

    def test_empty_new(self) -> None:
        result = merge_artifacts(["x"], [])
        assert result == ["x"]

    def test_both_empty(self) -> None:
        result = merge_artifacts([], [])
        assert result == []


# ---------------------------------------------------------------------------
# merge_viewed_images
# ---------------------------------------------------------------------------
class TestMergeViewedImages:
    """Tests for the merge_viewed_images reducer."""

    def test_none_existing_returns_new(self) -> None:
        new = {"img.png": {"base64": "abc", "mime_type": "image/png"}}
        assert merge_viewed_images(None, new) == new

    def test_none_new_returns_existing(self) -> None:
        existing = {"img.png": {"base64": "abc", "mime_type": "image/png"}}
        assert merge_viewed_images(existing, None) == existing

    def test_both_none_returns_empty(self) -> None:
        assert merge_viewed_images(None, None) == {}

    def test_empty_dict_clears_all(self) -> None:
        existing = {"img.png": {"base64": "abc", "mime_type": "image/png"}}
        assert merge_viewed_images(existing, {}) == {}

    def test_merges_new_overrides_existing(self) -> None:
        existing = {"a.png": {"base64": "old", "mime_type": "image/png"}}
        new = {"a.png": {"base64": "new", "mime_type": "image/png"}}
        result = merge_viewed_images(existing, new)
        assert result["a.png"]["base64"] == "new"

    def test_merges_adds_new_keys(self) -> None:
        existing = {"a.png": {"base64": "a", "mime_type": "image/png"}}
        new = {"b.png": {"base64": "b", "mime_type": "image/jpeg"}}
        result = merge_viewed_images(existing, new)
        assert len(result) == 2
        assert "a.png" in result
        assert "b.png" in result


# ---------------------------------------------------------------------------
# merge_token_usage
# ---------------------------------------------------------------------------
class TestMergeTokenUsage:
    """Tests for the merge_token_usage reducer."""

    def test_none_existing_returns_new(self) -> None:
        new = {"input_tokens": 10, "output_tokens": 20}
        assert merge_token_usage(None, new) == new

    def test_none_new_returns_existing(self) -> None:
        existing = {"input_tokens": 10, "output_tokens": 20}
        assert merge_token_usage(existing, None) == existing

    def test_both_none_returns_zeros(self) -> None:
        result = merge_token_usage(None, None)
        assert result == {"input_tokens": 0, "output_tokens": 0}

    def test_accumulates_input_tokens(self) -> None:
        existing = {"input_tokens": 100, "output_tokens": 50}
        new = {"input_tokens": 200, "output_tokens": 0}
        result = merge_token_usage(existing, new)
        assert result["input_tokens"] == 300

    def test_accumulates_output_tokens(self) -> None:
        existing = {"input_tokens": 0, "output_tokens": 50}
        new = {"input_tokens": 0, "output_tokens": 100}
        result = merge_token_usage(existing, new)
        assert result["output_tokens"] == 150

    def test_accumulates_both(self) -> None:
        existing = {"input_tokens": 10, "output_tokens": 20}
        new = {"input_tokens": 30, "output_tokens": 40}
        result = merge_token_usage(existing, new)
        assert result == {"input_tokens": 40, "output_tokens": 60}

    def test_missing_keys_default_to_zero(self) -> None:
        existing = {}
        new = {"input_tokens": 5, "output_tokens": 10}
        result = merge_token_usage(existing, new)
        assert result == {"input_tokens": 5, "output_tokens": 10}


# ---------------------------------------------------------------------------
# ThreadState type annotation checks
# ---------------------------------------------------------------------------
class TestThreadStateAnnotations:
    """Verify ThreadState has all expected fields."""

    def test_has_expected_annotations(self) -> None:
        annotations = ThreadState.__annotations__
        assert "sandbox" in annotations
        assert "thread_data" in annotations
        assert "title" in annotations
        assert "artifacts" in annotations
        assert "todos" in annotations
        assert "uploaded_files" in annotations
        assert "viewed_images" in annotations
        assert "token_usage" in annotations
