"""Exercise the broker image's Python file layout without an installed harness."""

from __future__ import annotations

import json
import shlex
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def image_broker(tmp_path: Path) -> Path:
    dockerfile = REPO_ROOT / "docker/lark-cli-broker/Dockerfile"
    runtime_stage = dockerfile.read_text(encoding="utf-8").replace("\\\n", " ").rsplit("\nFROM ", 1)[1]
    image_root = tmp_path / "image"
    for instruction in runtime_stage.splitlines():
        words = shlex.split(instruction, comments=True)
        if not words or words[0] != "COPY" or words[1].startswith("--from="):
            continue
        for source in words[1:-1]:
            if not source.endswith(".py"):
                continue
            destination = image_root / words[-1].lstrip("/")
            if words[-1].endswith("/"):
                destination /= Path(source).name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(REPO_ROOT / source, destination)
    return image_root / "opt/broker/lark_broker.py"


def run_isolated(broker: Path, code: str, *args: str) -> subprocess.CompletedProcess[str]:
    bootstrap = "import runpy, sys\nfrom pathlib import Path\nbroker = Path(sys.argv.pop(1))\nsys.path.insert(0, str(broker.parent))\n"
    # -I ignores inherited PYTHONPATH and -S skips installed editable packages.
    # Only the image's script directory is added back, matching its entrypoint.
    return subprocess.run(
        [sys.executable, "-I", "-S", "-c", bootstrap + textwrap.dedent(code), str(broker), *args],
        cwd=broker.parent,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )


def test_image_installs_shim_without_harness(image_broker: Path, tmp_path: Path) -> None:
    runtime = tmp_path / "runtime"
    completed = run_isolated(image_broker, 'runpy.run_path(str(broker), run_name="__main__")', "install-shim", str(runtime))

    assert completed.returncode == 0, completed.stderr
    launcher = runtime / "bin/lark-cli"
    shim = runtime / "bin/lark-cli-shim.py"
    assert launcher.read_text(encoding="utf-8").startswith("#!/bin/sh\n")
    assert str(shim) in launcher.read_text(encoding="utf-8")
    assert shim.read_text(encoding="utf-8").startswith("#!/usr/bin/env python3\n")
    assert json.loads((runtime / ".deerflow-lark-cli-runtime.json").read_text(encoding="utf-8"))["kind"] == "shim"


def test_image_serves_health_without_harness(image_broker: Path) -> None:
    completed = run_isolated(
        image_broker,
        """
        import json
        import threading
        from http.client import HTTPConnection

        module = runpy.run_path(str(broker))
        config = module["BrokerConfig"](lark_cli_path=sys.executable, config_dir="config", data_dir="data", port=0)
        with module["serve"](config) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                connection = HTTPConnection(*server.server_address[:2], timeout=5)
                try:
                    connection.request("GET", "/v1/health")
                    response = connection.getresponse()
                    assert response.status == 200
                    assert json.loads(response.read()) == {"ok": True}
                finally:
                    connection.close()
            finally:
                server.shutdown()
                thread.join(timeout=5)
                assert not thread.is_alive()
        """,
    )

    assert completed.returncode == 0, completed.stderr
