"""Regression coverage for sandbox image selection before pulling."""

import os
import shutil
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


@pytest.mark.skipif(os.name == "nt", reason="isolated POSIX PATH simulates macOS runtime discovery")
@pytest.mark.parametrize(
    ("apple_exit", "docker_available", "configured", "expected_exit", "expected_engines"),
    [
        pytest.param(0, False, True, 0, ["container"], id="apple-only-success"),
        pytest.param(0, False, False, 0, ["container"], id="apple-only-default-image-note"),
        pytest.param(1, True, True, 0, ["container", "docker"], id="apple-failure-docker-fallback"),
        pytest.param(None, False, True, 1, [], id="no-engines"),
        pytest.param(0, True, True, 0, ["container", "docker"], id="both-engines"),
    ],
)
def test_setup_sandbox_runtime_selection(tmp_path, apple_exit, docker_available, configured, expected_exit, expected_engines):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    # Do not inherit the host PATH: an installed Docker must not mask the bug
    # or be invoked by a test. All engine commands below are local stubs.
    (bin_dir / "bash").symlink_to(BASH)
    for tool in ("sed", "grep", "awk", "head"):
        executable = shutil.which(tool)
        if executable is None:
            pytest.skip(f"shell-script test requires {tool}")
        (bin_dir / tool).symlink_to(executable)
    scripts = {"uname": "#!/usr/bin/env bash\nprintf 'Darwin\\n'\n"}
    if apple_exit is not None:
        scripts["container"] = f'#!/usr/bin/env bash\nprintf "%s\\n" container "$@" >> "$CAPTURE_ENGINE_ARGS"\nexit {apple_exit}\n'
    if docker_available:
        scripts["docker"] = '#!/usr/bin/env bash\nprintf "%s\\n" docker "$@" >> "$CAPTURE_ENGINE_ARGS"\n'
    for name, script in scripts.items():
        path = bin_dir / name
        path.write_text(script, encoding="utf-8")
        path.chmod(0o755)

    image = "example.invalid/custom-sandbox:review"
    if configured:
        (tmp_path / "config.yaml").write_text(f"sandbox:\n  image: {image}\n", encoding="utf-8")
    else:
        image = "enterprise-public-cn-beijing.cr.volces.com/vefaas-public/all-in-one-sandbox:1.11.0"
    capture = tmp_path / "engine-args.txt"
    env = {**os.environ, "PATH": str(bin_dir), "CAPTURE_ENGINE_ARGS": str(capture)}
    result = subprocess.run([BASH, str(REPO_ROOT / "scripts/setup-sandbox.sh")], cwd=tmp_path, env=env, capture_output=True, text=True, check=False)

    assert result.returncode == expected_exit, result.stdout + result.stderr
    args = capture.read_text(encoding="utf-8").splitlines() if capture.exists() else []
    expected_args = []
    for engine in expected_engines:
        expected_args.extend([engine, "image", "pull", image] if engine == "container" else [engine, "pull", image])
    assert args == expected_args
    if expected_exit == 0:
        assert "Sandbox image pulled successfully" in result.stdout
        assert "Neither Docker nor Apple Container is available" not in result.stdout
    else:
        assert "Neither Docker nor Apple Container is available" in result.stdout
    if not configured:
        assert "NOTE: pulling this image does not make the sandbox use it." in result.stdout
