"""Exercise the real child-process pipe, without running Claude or an API."""

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SKILL_ROOT = Path(__file__).resolve().parents[2] / "skills/public/skill-creator"


def _load_evaluator(skill_root):
    spec = importlib.util.spec_from_file_location("skill_creator_run_eval", skill_root / "scripts/run_eval.py")
    module = importlib.util.module_from_spec(spec)
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    return module


@pytest.fixture
def evaluator(monkeypatch):
    monkeypatch.syspath_prepend(str(SKILL_ROOT))
    return _load_evaluator(SKILL_ROOT)


@pytest.mark.skipif(os.name == "nt", reason="The evaluator currently uses POSIX select on subprocess pipes")
@pytest.mark.parametrize("event_kind", ["assistant", "stream"])
@pytest.mark.parametrize("newline", [True, False])
@pytest.mark.parametrize("matches", [True, False])
def test_drains_completed_child_output(evaluator, monkeypatch, tmp_path, event_kind, newline, matches):
    real_popen = subprocess.Popen
    children = []

    def completed_child(cmd, **kwargs):
        command = next((tmp_path / ".claude/commands").glob("*.md")).stem
        target = command if matches else "another-skill"
        if event_kind == "assistant":
            events = [{"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Skill", "input": {"skill": target}}]}}]
        else:
            events = [
                {"type": "stream_event", "event": {"type": "content_block_start", "content_block": {"type": "tool_use", "name": "Read"}}},
                {"type": "stream_event", "event": {"type": "content_block_delta", "delta": {"type": "input_json_delta", "partial_json": json.dumps({"file_path": target + ".md"})}}},
                {"type": "stream_event", "event": {"type": "content_block_stop"}},
            ]
        payload = "not-json\n" + "\n".join(json.dumps(event) for event in events) + ("\n" if newline else "")
        child = real_popen([sys.executable, "-c", "import sys; sys.stdout.write(sys.argv[1])", payload], **kwargs)
        children.append(child)
        # Force the real-world race deterministically: process exit precedes poll.
        child.wait(timeout=5)
        return child

    monkeypatch.setattr(evaluator.subprocess, "Popen", completed_child)
    assert evaluator.run_single_query("query", "example", "description", 5, str(tmp_path)) is matches
    assert not list((tmp_path / ".claude/commands").glob("*.md"))
    for child in children:
        child.stdout.close()


def test_evaluator_import_preserves_bytecode_setting(monkeypatch, tmp_path):
    isolated = tmp_path / "skill"
    shutil.copytree(SKILL_ROOT, isolated, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    monkeypatch.syspath_prepend(str(isolated))
    monkeypatch.setattr(sys, "dont_write_bytecode", False)
    monkeypatch.delitem(sys.modules, "scripts.utils", raising=False)
    monkeypatch.delitem(sys.modules, "scripts", raising=False)
    _load_evaluator(isolated)
    assert not list(isolated.rglob("*.pyc"))
    assert sys.dont_write_bytecode is False
