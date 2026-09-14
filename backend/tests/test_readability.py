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


def test_probe_short_circuits_when_packages_are_present(probe_dir, monkeypatch):
    _plant_packages(probe_dir)

    def _fail(*args, **kwargs):
        raise AssertionError("npm must not be probed or invoked when the packages already exist")

    monkeypatch.setattr(readability_module.shutil, "which", _fail)
    monkeypatch.setattr(readability_module.subprocess, "run", _fail)

    assert readability_module._readability_js_ready() is True


def test_probe_partial_node_modules_is_not_mistaken_for_ready(probe_dir, monkeypatch):
    """An npm run killed mid-install leaves a bare node_modules behind; the
    probe must not cache that as ready."""
    (probe_dir / "node_modules").mkdir()
    runs = []

    def _fake_run(cmd, **kwargs):
        runs.append(cmd)
        _plant_packages(probe_dir)
        return subprocess.CompletedProcess(cmd, returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(readability_module.shutil, "which", lambda name: "npm")
    monkeypatch.setattr(readability_module.subprocess, "run", _fake_run)

    assert readability_module._readability_js_ready() is True
    assert len(runs) == 1  # the partial tree triggered a real install first


def test_probe_missing_npm_is_cached_permanently(probe_dir, monkeypatch):
    which_calls = []
    monkeypatch.setattr(readability_module.shutil, "which", lambda name: which_calls.append(name))

    assert readability_module._readability_js_ready() is False
    assert readability_module._readability_js_ready() is False
    # A missing npm is deterministic: one probe, then the settled False.
    assert which_calls == ["npm"]


def test_probe_failed_install_is_cached_permanently(probe_dir, monkeypatch):
    runs = []

    def _fake_run(cmd, **kwargs):
        runs.append(cmd)
        # npm emits UTF-8 (box-drawing progress, typographic quotes); the
        # probe must decode bytes with replacement, not the strict locale
        # codec, or Windows ANSI code pages crash the first fetch.
        return subprocess.CompletedProcess(cmd, returncode=1, stdout=b"\xe2\x94\x80", stderr=b"\xe2\x94\x80 npm failed \xe2\x80\x9d")

    monkeypatch.setattr(readability_module.shutil, "which", lambda name: "C:/fake/npm.cmd")
    monkeypatch.setattr(readability_module.subprocess, "run", _fake_run)

    assert readability_module._readability_js_ready() is False
    assert readability_module._readability_js_ready() is False
    # Deterministic failure: one install attempt, then the settled False.
    assert runs == [["C:/fake/npm.cmd", "install", "--no-audit", "--no-fund"]]


def test_probe_transient_failure_retries_on_a_later_call(probe_dir, monkeypatch):
    runs = []

    def _fake_run(cmd, **kwargs):
        runs.append(cmd)
        if len(runs) == 1:
            raise subprocess.TimeoutExpired(cmd, timeout=300)
        _plant_packages(probe_dir)
        return subprocess.CompletedProcess(cmd, returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(readability_module.shutil, "which", lambda name: "npm")
    monkeypatch.setattr(readability_module.subprocess, "run", _fake_run)

    # A timeout is transient: not cached, retried on the next call.
    assert readability_module._readability_js_ready() is False
    assert readability_module._readability_js_ready() is True
    assert len(runs) == 2


def test_probe_success_bootstraps_node_modules(probe_dir, monkeypatch):
    def _fake_run(cmd, **kwargs):
        _plant_packages(probe_dir)
        return subprocess.CompletedProcess(cmd, returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(readability_module.shutil, "which", lambda name: "npm")
    monkeypatch.setattr(readability_module.subprocess, "run", _fake_run)

    assert readability_module._readability_js_ready() is True


def test_probe_waiter_never_blocks_on_inflight_bootstrap(probe_dir, monkeypatch):
    """A bootstrap in flight must not park other callers' worker threads:
    async fetches share the default executor, so a waiter that blocks on the
    bootstrap lock for the length of an npm install starves the pool."""
    bootstrap_started = threading.Event()
    release_bootstrap = threading.Event()

    def _fake_run(cmd, **kwargs):
        bootstrap_started.set()
        release_bootstrap.wait(timeout=30)
        _plant_packages(probe_dir)
        return subprocess.CompletedProcess(cmd, returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(readability_module.shutil, "which", lambda name: "npm")
    monkeypatch.setattr(readability_module.subprocess, "run", _fake_run)

    installer = threading.Thread(target=readability_module._readability_js_ready)
    installer.start()
    assert bootstrap_started.wait(timeout=30)

    # The waiter degrades immediately instead of queueing behind the install.
    started = time.perf_counter()
    assert readability_module._readability_js_ready() is False
    assert time.perf_counter() - started < 10

    release_bootstrap.set()
    installer.join(timeout=30)
    assert not installer.is_alive()
    # Once the install lands, later callers see the settled True.
    assert readability_module._readability_js_ready() is True
