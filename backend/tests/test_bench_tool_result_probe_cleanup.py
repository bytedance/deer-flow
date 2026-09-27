"""The probe may only clean directories it owns (review finding on #5255).

``--outputs-dir`` is user-supplied and may pre-exist with unrelated files:
on success or failure, the probe must remove only its own per-run
``probe-run-*`` child (plus its unique temp directory), never the requested
directory itself or anything beside it.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


def _load_probe_module() -> object:
    path = Path(__file__).resolve().parents[1] / "scripts" / "benchmark" / "checkpoint" / "bench_tool_result_probe.py"
    spec = importlib.util.spec_from_file_location("bench_tool_result_probe_under_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_successful_run_leaves_unrelated_files_alone(tmp_path: Path) -> None:
    module = _load_probe_module()
    outputs_dir = tmp_path / "outputs"
    outputs_dir.mkdir()
    (outputs_dir / "user-file.txt").write_text("keep me", encoding="utf-8")
    tmp_dir = tmp_path / "scratch"

    report = module.run_probe(20_000, outputs_dir, tmp_dir)

    assert report["verdict"]["raw_content_is_full"] is True
    assert report["verdict"]["wrapped_content_stays_small"] is True
    assert (outputs_dir / "user-file.txt").read_text(encoding="utf-8") == "keep me", "unrelated content must survive"
    assert not list(outputs_dir.glob("probe-run-*")), "the owned child must be removed"
    assert not tmp_dir.exists(), "the owned temp directory must be removed with the run"


def test_failing_run_still_leaves_unrelated_files_alone(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_probe_module()
    outputs_dir = tmp_path / "outputs"
    outputs_dir.mkdir()
    (outputs_dir / "user-file.txt").write_text("keep me", encoding="utf-8")

    def boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("simulated probe failure")

    monkeypatch.setattr(module, "_main", boom)
    with pytest.raises(RuntimeError):
        module.run_probe(20_000, outputs_dir, tmp_path / "scratch")

    assert (outputs_dir / "user-file.txt").read_text(encoding="utf-8") == "keep me", "cleanup on failure must still be scoped to the owned child"
    assert not list(outputs_dir.glob("probe-run-*"))
