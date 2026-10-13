"""Shared cache-reset markers for Gateway processes that share one config directory.

``deerflow.config.shared_reset_marker`` is the generic helper behind the MCP
tools-cache reset (``.<extensions config>.mcp-cache-reset.json``) and the skills
prompt-cache reset (``.<extensions config>.skills-cache-reset.json``). A writer
publishes a fresh random generation with an atomic replace; every other process
compares the marker's ``(mtime, size, sha256)`` signature on its next lookup.
These tests drive two trackers side by side to simulate two Gateway processes
sharing one marker file.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from support.symlinks import symlink_or_skip

import deerflow.config.shared_reset_marker as shared_reset_marker_module
from deerflow.config.extensions_config import ExtensionsConfig
from deerflow.config.file_signature import get_config_signature
from deerflow.config.shared_reset_marker import (
    SharedResetChange,
    SharedResetMarker,
    SharedResetMarkerTracker,
    resolve_shared_config_path,
)


class _Clock:
    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture()
def config_path(tmp_path: Path) -> Path:
    path = tmp_path / "extensions_config.json"
    path.write_text(json.dumps({"mcpServers": {}, "skills": {}}), encoding="utf-8")
    return path


def _tracker(marker: SharedResetMarker, config_path: Path | None, clock: _Clock, **kwargs) -> SharedResetMarkerTracker:
    return SharedResetMarkerTracker(marker, resolve_config_path=lambda: config_path, clock=clock, **kwargs)


def test_marker_path_is_hidden_sibling_of_the_config(config_path: Path) -> None:
    marker = SharedResetMarker("skills-cache-reset")

    assert marker.path_for(config_path) == config_path.parent / ".extensions_config.json.skills-cache-reset.json"


def test_marker_path_follows_a_symlinked_config(tmp_path: Path, config_path: Path) -> None:
    link = tmp_path / "linked" / "extensions_config.json"
    link.parent.mkdir()
    symlink_or_skip(link, config_path)

    assert SharedResetMarker("skills-cache-reset").path_for(link) == config_path.parent / ".extensions_config.json.skills-cache-reset.json"


@pytest.mark.parametrize("suffix", ["", "has/slash", "has\\backslash", ".."])
def test_marker_rejects_unsafe_suffixes(suffix: str) -> None:
    with pytest.raises(ValueError):
        SharedResetMarker(suffix)


def test_publish_writes_an_atomic_json_marker(config_path: Path) -> None:
    marker = SharedResetMarker("skills-cache-reset")

    generation = marker.publish(config_path, user_id="alice")

    marker_path = marker.path_for(config_path)
    payload = json.loads(marker_path.read_text(encoding="utf-8"))
    assert payload["version"] == 1
    assert payload["generation"] == generation
    assert payload["previous_generation"] is None
    assert payload["user_id"] == "alice"
    assert payload["published_at"]
    assert not list(config_path.parent.glob(f".{marker_path.name}.*.tmp"))


def test_publish_chains_the_previous_generation_and_omits_user_id_for_global_resets(config_path: Path) -> None:
    marker = SharedResetMarker("skills-cache-reset")

    first = marker.publish(config_path, user_id="alice")
    second = marker.publish(config_path)

    payload = json.loads(marker.path_for(config_path).read_text(encoding="utf-8"))
    assert first != second
    assert payload["generation"] == second
    assert payload["previous_generation"] == first
    assert "user_id" not in payload


def test_read_tolerates_missing_and_malformed_markers(config_path: Path) -> None:
    marker = SharedResetMarker("skills-cache-reset")

    assert marker.read(config_path) == (None, None)
    assert marker.current_signature(config_path) is None
    assert marker.current_signature(None) is None

    marker_path = marker.path_for(config_path)
    marker_path.write_text("{not json", encoding="utf-8")
    payload, signature = marker.read(config_path)
    assert payload is None
    assert signature == get_config_signature(marker_path)


def test_two_processes_share_one_marker(config_path: Path) -> None:
    """Process A publishes; process B sees the invalidation on its next poll."""
    marker = SharedResetMarker("skills-cache-reset")
    clock = _Clock()
    process_a = _tracker(marker, config_path, clock)
    process_b = _tracker(marker, config_path, clock)

    # Both processes adopt the current state (no marker yet) without a reset.
    assert process_a.poll() is None
    assert process_b.poll() is None

    generation = marker.publish(config_path)
    process_a.note_own_publication(generation)
    clock.advance(1.0)

    assert process_a.poll() is None, "the publishing process already refreshed itself"
    change = process_b.poll()
    assert change == SharedResetChange(user_ids=None, generation=generation)
    clock.advance(1.0)
    assert process_b.poll() is None, "an observed generation is not reported twice"


def test_user_scoped_publication_is_reported_with_its_user(config_path: Path) -> None:
    marker = SharedResetMarker("skills-cache-reset")
    clock = _Clock()
    process_b = _tracker(marker, config_path, clock)
    assert process_b.poll() is None

    generation = marker.publish(config_path, user_id="alice")
    clock.advance(1.0)

    assert process_b.poll() == SharedResetChange(user_ids=frozenset({"alice"}), generation=generation)


def test_multiple_publications_between_polls_fall_back_to_a_global_reset(config_path: Path) -> None:
    """Only the latest marker survives, so a skipped generation widens the reset."""
    marker = SharedResetMarker("skills-cache-reset")
    clock = _Clock()
    process_b = _tracker(marker, config_path, clock)
    assert process_b.poll() is None

    marker.publish(config_path, user_id="alice")
    generation = marker.publish(config_path, user_id="bob")
    clock.advance(1.0)

    assert process_b.poll() == SharedResetChange(user_ids=None, generation=generation)


def test_own_publication_with_an_interleaved_foreign_write_still_resets(config_path: Path) -> None:
    marker = SharedResetMarker("skills-cache-reset")
    clock = _Clock()
    process_a = _tracker(marker, config_path, clock)
    assert process_a.poll() is None

    process_a.note_own_publication(marker.publish(config_path, user_id="alice"))
    foreign = marker.publish(config_path, user_id="bob")
    clock.advance(1.0)

    assert process_a.poll() == SharedResetChange(user_ids=None, generation=foreign)


def test_poll_is_throttled_to_one_stat_per_interval(config_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    marker = SharedResetMarker("skills-cache-reset")
    clock = _Clock()
    reads: list[Path] = []
    original = shared_reset_marker_module.read_config_with_signature

    def _counting_read(path: Path):
        reads.append(path)
        return original(path)

    marker.publish(config_path)
    monkeypatch.setattr(shared_reset_marker_module, "read_config_with_signature", _counting_read)
    tracker = _tracker(marker, config_path, clock, poll_interval_seconds=1.0)

    assert tracker.poll() is None
    assert len(reads) == 1
    clock.advance(0.5)
    tracker.poll()
    tracker.poll()
    assert len(reads) == 1, "no repeated stat inside the throttle window"
    clock.advance(0.5)
    tracker.poll()
    assert len(reads) == 2


def test_change_inside_the_throttle_window_is_seen_on_the_next_interval(config_path: Path) -> None:
    marker = SharedResetMarker("skills-cache-reset")
    clock = _Clock()
    tracker = _tracker(marker, config_path, clock)
    assert tracker.poll() is None

    generation = marker.publish(config_path)
    clock.advance(0.2)
    assert tracker.poll() is None, "throttled: the stat is skipped"
    clock.advance(0.8)
    assert tracker.poll() == SharedResetChange(user_ids=None, generation=generation)


def test_tracker_without_a_config_path_never_reports_a_change(config_path: Path) -> None:
    marker = SharedResetMarker("skills-cache-reset")
    clock = _Clock()
    tracker = _tracker(marker, None, clock)

    assert tracker.poll() is None
    marker.publish(config_path)
    clock.advance(1.0)
    assert tracker.poll() is None


def test_marker_deleted_after_adoption_is_a_global_reset(config_path: Path) -> None:
    marker = SharedResetMarker("skills-cache-reset")
    clock = _Clock()
    marker.publish(config_path)
    tracker = _tracker(marker, config_path, clock)
    assert tracker.poll() is None

    marker.path_for(config_path).unlink()
    clock.advance(1.0)

    assert tracker.poll() == SharedResetChange(user_ids=None, generation=None)


def test_malformed_marker_is_a_global_reset(config_path: Path) -> None:
    marker = SharedResetMarker("skills-cache-reset")
    clock = _Clock()
    tracker = _tracker(marker, config_path, clock)
    assert tracker.poll() is None

    marker.path_for(config_path).write_text("{not json", encoding="utf-8")
    clock.advance(1.0)

    assert tracker.poll() == SharedResetChange(user_ids=None, generation=None)


def test_config_path_switch_after_adoption_is_a_global_reset(tmp_path: Path, config_path: Path) -> None:
    marker = SharedResetMarker("skills-cache-reset")
    clock = _Clock()
    current = {"path": None}
    tracker = SharedResetMarkerTracker(marker, resolve_config_path=lambda: current["path"], clock=clock)
    assert tracker.poll() is None

    current["path"] = config_path
    clock.advance(1.0)

    assert tracker.poll() == SharedResetChange(user_ids=None, generation=None)


def test_reset_forgets_the_observed_state(config_path: Path) -> None:
    marker = SharedResetMarker("skills-cache-reset")
    clock = _Clock()
    tracker = _tracker(marker, config_path, clock)
    assert tracker.poll() is None
    marker.publish(config_path)

    tracker.reset()

    assert tracker.poll() is None, "after a reset the first poll adopts silently"
    clock.advance(1.0)
    assert tracker.poll() is None


def test_resolve_shared_config_path_treats_a_missing_explicit_file_as_unconfigured(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    missing = tmp_path / "missing.json"
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(missing))

    with pytest.raises(FileNotFoundError):
        ExtensionsConfig.resolve_config_path()
    assert resolve_shared_config_path() is None


def test_resolve_shared_config_path_returns_the_explicit_file(config_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEER_FLOW_EXTENSIONS_CONFIG_PATH", str(config_path))

    assert resolve_shared_config_path() == config_path
