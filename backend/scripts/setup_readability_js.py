"""Install Readability.js's npm dependencies for the readabilipy wheel.

The readabilipy wheel ships only ``ExtractArticle.js`` and a ``package.json``
with open-ended ranges (no lockfile), and its own bootstrap probes npm with a
bare ``npm`` name that Windows ``CreateProcess`` never resolves to
``npm.cmd``. Left alone, web fetch therefore silently degrades to pure-Python
extraction on Windows hosts — and on any platform, letting a request-time
path run ``npm install`` against unpinned ranges with lifecycle scripts is a
supply-chain hazard.

This explicit setup step installs the dependencies once, reproducibly:

- a reviewed ``package-lock.json`` (shipped in
  ``deerflow/utils/readability_js/``) is copied next to readabilipy's
  ``package.json`` so ``npm ci`` installs exactly the reviewed tree;
- ``npm ci --ignore-scripts`` never runs dependency lifecycle scripts;
- a Node smoke check requires both packages ``ExtractArticle.js`` imports
  before the installation is declared usable.

Request-time extraction only checks readiness (see
``deerflow.utils.readability._readability_js_ready``) and falls back to the
pure-Python extractor when this step has not been run.
"""

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import readabilipy

import deerflow

LOCKFILE_SOURCE = Path(deerflow.__file__).resolve().parent / "utils" / "readability_js" / "package-lock.json"
NPM_INSTALL_TIMEOUT_SECONDS = 600
MAX_INSTALL_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = (2, 4, 8)
NODE_CHECK_TIMEOUT_SECONDS = 60


def readability_js_dir() -> Path:
    return Path(readabilipy.__file__).resolve().parent / "javascript"


def install_dependencies(js_dir: Path, npm: str, run=None, sleep=time.sleep) -> bool:
    """Copy the reviewed lockfile in and npm ci it, retrying with backoff.

    Transient registry/proxy failures surface as nonzero npm exits rather
    than Python exceptions, so every failure is retried up to
    ``MAX_INSTALL_ATTEMPTS`` times with a bounded backoff before giving up.
    """
    run = run or subprocess.run
    shutil.copyfile(LOCKFILE_SOURCE, js_dir / "package-lock.json")
    for attempt in range(MAX_INSTALL_ATTEMPTS):
        result = run(
            [npm, "ci", "--ignore-scripts", "--no-audit", "--no-fund"],
            cwd=js_dir,
            check=False,
            capture_output=True,
            timeout=NPM_INSTALL_TIMEOUT_SECONDS,
            env={**os.environ, "npm_config_update_notifier": "false"},
        )
        if result.returncode == 0:
            return True
        # npm output is UTF-8 (box-drawing progress, typographic quotes);
        # capture bytes and decode with replacement so a Windows ANSI code
        # page cannot crash the setup step.
        stderr = result.stderr.decode("utf-8", errors="replace").strip()
        print(f"npm ci failed (exit {result.returncode}): {stderr[-800:]}", file=sys.stderr)
        if attempt + 1 < MAX_INSTALL_ATTEMPTS:
            sleep(RETRY_BACKOFF_SECONDS[min(attempt, len(RETRY_BACKOFF_SECONDS) - 1)])
    return False


def node_dependencies_loadable(js_dir: Path, node: str, run=None) -> bool:
    """Node can require the packages ExtractArticle.js imports.

    npm creates package directories before extracting their contents, so
    directory presence alone cannot distinguish a complete install from one
    interrupted mid-extraction; loading them is the real test.
    """
    run = run or subprocess.run
    try:
        probe = run(
            [node, "-e", "require('jsdom'); require('@mozilla/readability');"],
            cwd=js_dir,
            check=False,
            capture_output=True,
            timeout=NODE_CHECK_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return probe.returncode == 0


def main() -> int:
    js_dir = readability_js_dir()
    npm = shutil.which("npm")
    node = shutil.which("node")
    if npm is None or node is None:
        print("error: npm and Node.js are required; web fetch will use pure-Python extraction.", file=sys.stderr)
        return 1
    if node_dependencies_loadable(js_dir, node):
        print("Readability.js dependencies are already installed and loadable.")
        return 0
    print(f"Installing Readability.js dependencies into {js_dir} ...")
    if not install_dependencies(js_dir, npm):
        print("error: npm ci did not succeed; web fetch will use pure-Python extraction.", file=sys.stderr)
        return 1
    if not node_dependencies_loadable(js_dir, node):
        print("error: installed packages failed the load check; web fetch will use pure-Python extraction.", file=sys.stderr)
        return 1
    print("Readability.js dependencies installed and loadable.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
