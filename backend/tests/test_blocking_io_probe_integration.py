from __future__ import annotations

import time

import pytest

ORIGINAL_SLEEP = time.sleep


def replacement_sleep(seconds: float) -> None:
    return None


def test_probe_survives_monkeypatch_teardown(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(time, "sleep", replacement_sleep)
    assert time.sleep is replacement_sleep


@pytest.mark.no_blocking_io_probe
def test_probe_restores_original_after_monkeypatch_teardown() -> None:
    assert time.sleep is ORIGINAL_SLEEP
    assert getattr(time.sleep, "__wrapped__", None) is None
