"""Regression coverage for sandbox image selection before pulling."""

import os
import subprocess
from pathlib import Path

import pytest
from support.shell import find_script_bash

REPO_ROOT = Path(__file__).resolve().parents[2]
BASH = find_script_bash()
pytestmark = pytest.mark.skipif(BASH is None, reason="repo shell-script tests need Git Bash on Windows")


@pytest.mark.parametrize("newline", ["\n", "\r\n"], ids=["lf", "crlf"])
@pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig"])
@pytest.mark.parametrize("configured", [True, False], ids=["configured", "commented"])
def test_setup_sandbox_image_selection(tmp_path, encoding, configured, newline):
    image = "example.invalid/custom-sandbox:review"
    config = f"sandbox:\n  image: {image}\n" if configured else f"# sandbox:\n#   image: {image}\n"
    (tmp_path / "config.yaml").write_bytes(config.replace("\n", newline).encode(encoding))
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    capture = tmp_path / "docker-args.txt"
    # Stub both container engines so the test never pulls a real image.
    for name, script in {
        "docker": '#!/usr/bin/env bash\nprintf "%s\\n" "$@" >> "$CAPTURE_DOCKER_ARGS"\n',
        "container": "#!/usr/bin/env bash\nexit 0\n",
    }.items():
        path = bin_dir / name
        path.write_text(script, encoding="utf-8")
        path.chmod(0o755)
    env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}", "CAPTURE_DOCKER_ARGS": str(capture)}
    result = subprocess.run([BASH, str(REPO_ROOT / "scripts/setup-sandbox.sh")], cwd=tmp_path, env=env, capture_output=True, text=True, check=True)
    # Preserve carriage returns in arguments instead of normalizing them away.
    args = capture.read_bytes().decode("utf-8").split("\n")[:-1]
    assert args[0] == "pull"
    assert len(args) == 2
    if configured:
        assert args[1] == image
        assert f"Using configured image: {image}" in result.stdout
        assert "Using default image:" not in result.stdout
    else:
        assert args[1] != image
        assert f"Using default image: {args[1]}" in result.stdout
