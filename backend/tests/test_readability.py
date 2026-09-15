"""Tests for readability extraction fallback behavior."""

import subprocess
import threading
import time

import pytest

from deerflow.utils import readability as readability_module
from deerflow.utils.readability import ReadabilityExtractor


@pytest.fixture
def probe_dir(monkeypatch, tmp_path):
    """Isolate the bootstrap probe: an empty javascript dir and a cleared cache."""
    monkeypatch.setattr(readability_module, "_READABILITY_JS_DIR", tmp_path)
    monkeypatch.setattr(readability_module, "_readability_js_state", None)
    return tmp_path


def _plant_packages(js_dir):
    """Materialise the two packages ExtractArticle.js imports."""
    (js_dir / "node_modules" / "jsdom").mkdir(parents=True)
    (js_dir / "node_modules" / "@mozilla" / "readability").mkdir(parents=True)


def _pin_probe_ready(monkeypatch):
    """Extractor stubs must stay hermetic: the probe must not touch the
    filesystem or spawn npm on hosts where node_modules is absent."""
    monkeypatch.setattr(readability_module, "_readability_js_state", True)


def test_extract_article_falls_back_when_readability_js_fails(monkeypatch):
    """When Node-based readability fails, extraction should fall back to Python mode."""
    _pin_probe_ready(monkeypatch)

    calls: list[bool] = []

    def _fake_simple_json_from_html_string(html: str, use_readability: bool = False):
        calls.append(use_readability)
        if use_readability:
            raise subprocess.CalledProcessError(
                returncode=1,
                cmd=["node", "ExtractArticle.js"],
                stderr="boom",
            )
        return {"title": "Fallback Title", "content": "<p>Fallback Content</p>"}

    monkeypatch.setattr(
        "deerflow.utils.readability.simple_json_from_html_string",
        _fake_simple_json_from_html_string,
    )

    article = ReadabilityExtractor().extract_article("<html><body>test</body></html>")

    assert calls == [True, False]
    assert article.title == "Fallback Title"
    assert article.html_content == "<p>Fallback Content</p>"


def test_extract_article_re_raises_unexpected_exception(monkeypatch):
    """Unexpected errors should be surfaced instead of silently falling back."""
    _pin_probe_ready(monkeypatch)

    calls: list[bool] = []

    def _fake_simple_json_from_html_string(html: str, use_readability: bool = False):
        calls.append(use_readability)
        if use_readability:
            raise RuntimeError("unexpected parser failure")
        return {"title": "Should Not Reach Fallback", "content": "<p>Fallback</p>"}

    monkeypatch.setattr(
        "deerflow.utils.readability.simple_json_from_html_string",
        _fake_simple_json_from_html_string,
    )

    with pytest.raises(RuntimeError, match="unexpected parser failure"):
        ReadabilityExtractor().extract_article("<html><body>test</body></html>")
    assert calls == [True]


def test_probe_ready_when_packages_present_and_loadable(probe_dir, monkeypatch):
    _plant_packages(probe_dir)
    monkeypatch.setattr(readability_module, "_node_dependencies_loadable", lambda: True)

    def _fail(*args, **kwargs):
        raise AssertionError("the request-time probe must never spawn npm — installing is scripts/setup_readability_js.py's job")

    monkeypatch.setattr(readability_module.shutil, "which", _fail)
    monkeypatch.setattr(readability_module.subprocess, "run", _fail)

    assert readability_module._readability_js_ready() is True


def test_probe_not_ready_when_packages_missing(probe_dir, monkeypatch):
    load_checks = []
    monkeypatch.setattr(
        readability_module,
        "_node_dependencies_loadable",
        lambda: load_checks.append(1),
    )

    assert readability_module._readability_js_ready() is False
    assert readability_module._readability_js_ready() is False
    # Directory absence settles False without even trying to load: there is
    # nothing to require, and the setup step is the repair path.
    assert load_checks == []


def test_probe_not_ready_when_packages_cannot_load(probe_dir, monkeypatch):
    """npm creates package directories before extracting their contents, so a
    timeout mid-extraction leaves both dirs present but unloadable; the probe
    must settle False instead of trusting the tree."""
    _plant_packages(probe_dir)
    monkeypatch.setattr(readability_module, "_node_dependencies_loadable", lambda: False)

    assert readability_module._readability_js_ready() is False
    assert readability_module._readability_js_ready() is False


def test_probe_waiter_never_blocks_on_inflight_verification(probe_dir, monkeypatch):
    """A verification in flight must not park other callers' worker threads:
    async fetches share the default executor, so a waiter that blocks on the
    probe lock starves the pool."""
    verification_started = threading.Event()
    release_verification = threading.Event()

    def _slow_loadable():
        verification_started.set()
        release_verification.wait(timeout=30)
        return True

    monkeypatch.setattr(readability_module, "_node_dependencies_loadable", _slow_loadable)
    _plant_packages(probe_dir)

    verifier = threading.Thread(target=readability_module._readability_js_ready)
    verifier.start()
    assert verification_started.wait(timeout=30)

    # The waiter degrades immediately instead of queueing behind the check.
    started = time.perf_counter()
    assert readability_module._readability_js_ready() is False
    assert time.perf_counter() - started < 10

    release_verification.set()
    verifier.join(timeout=30)
    assert not verifier.is_alive()
    # Once the verification lands, later callers see the settled True.
    assert readability_module._readability_js_ready() is True
