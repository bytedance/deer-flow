from __future__ import annotations

import functools
import http.server
import os
import re
import shutil
import subprocess
import threading
import tomllib
import zipfile
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path

import pytest
import yaml

from deerflow.extensions.cli import find_project_root
from deerflow.extensions.loader import ExtensionSpec
from deerflow.extensions.manager import (
    ExtensionManager,
    _controlled_uv_environment,
    _detect_extra_flags,
    _retry_until_locked,
    _validate_locked_local_sources,
    _validate_remote_source,
)
from deerflow.tui.cli import main as deerflow_main


def _write_local_extension(
    source: Path,
    *,
    with_entry_point: bool = True,
    distribution: str = "deerflow-extension-demo",
    entry_target: str = "demo_extension:install",
) -> None:
    package = source / "demo_extension"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text(
        "def install(registry, config):\n    return None\n",
        encoding="utf-8",
    )
    entry_point = (
        f"""\
[project.entry-points."deerflow.extensions"]
demo = "{entry_target}"
"""
        if with_entry_point
        else ""
    )
    (source / "pyproject.toml").write_text(
        f"""\
[project]
name = "{distribution}"
version = "1.0.0"
requires-python = ">=3.12"

{entry_point}

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["demo_extension"]
""",
        encoding="utf-8",
    )


def _write_host_project(root: Path) -> None:
    backend = root / "backend"
    backend.mkdir()
    (backend / "pyproject.toml").write_text(
        """\
[project]
name = "extension-manager-test-host"
version = "0.0.0"
requires-python = ">=3.12"
dependencies = []

[dependency-groups]
extensions = []

[tool.uv]
default-groups = ["extensions"]
""",
        encoding="utf-8",
    )
    (root / "config.yaml").write_text("config_version: 1\n", encoding="utf-8")


def _commit_local_extension(source: Path) -> str:
    subprocess.run(["git", "init", "-q"], cwd=source, check=True)
    subprocess.run(["git", "config", "user.name", "Extension Test"], cwd=source, check=True)
    subprocess.run(["git", "config", "user.email", "extension-test@example.com"], cwd=source, check=True)
    subprocess.run(["git", "add", "."], cwd=source, check=True)
    subprocess.run(["git", "commit", "-qm", "initial extension"], cwd=source, check=True)
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=source,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


class _QuietFileHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, _format: str, *args: object) -> None:
        return


@contextmanager
def _serve_directory(directory: Path) -> Iterator[str]:
    handler = functools.partial(_QuietFileHandler, directory=str(directory))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address[:2]
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _assert_demo_entry_point_loads(backend: Path) -> None:
    completed = subprocess.run(
        [
            str(backend / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")),
            "-c",
            "from importlib.metadata import entry_points; eps=entry_points(group='deerflow.extensions'); assert [(e.name, e.value) for e in eps] == [('demo', 'demo_extension:install')]; assert callable(next(iter(eps)).load())",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr


def _write_demo_wheel(directory: Path) -> Path:
    directory.mkdir()
    wheel = directory / "deerflow_extension_demo-1.0.0-py3-none-any.whl"
    dist_info = "deerflow_extension_demo-1.0.0.dist-info"
    records = {
        "demo_extension/__init__.py": "def install(registry, config):\n    return None\n",
        f"{dist_info}/METADATA": ("Metadata-Version: 2.1\nName: deerflow-extension-demo\nVersion: 1.0.0\nRequires-Python: >=3.12\n"),
        f"{dist_info}/WHEEL": ("Wheel-Version: 1.0\nGenerator: deerflow-extension-test\nRoot-Is-Purelib: true\nTag: py3-none-any\n"),
        f"{dist_info}/entry_points.txt": ("[deerflow.extensions]\ndemo = demo_extension:install\n"),
    }
    records[f"{dist_info}/RECORD"] = "".join(f"{name},,\n" for name in (*records, f"{dist_info}/RECORD"))
    with zipfile.ZipFile(wheel, "w") as archive:
        for name, content in records.items():
            archive.writestr(name, content)
    return wheel


def test_install_local_directory_makes_it_deployable_and_enabled(tmp_path: Path) -> None:
    root = tmp_path / "deer-flow"
    source = tmp_path / "demo-source"
    root.mkdir()
    source.mkdir()
    _write_host_project(root)
    _write_local_extension(source)

    result = ExtensionManager(root).install(str(source), yes=True)

    assert result.name == "demo"
    assert result.distribution == "deerflow-extension-demo"
    assert result.use == "demo_extension:install"

    managed_source = root / "backend" / "extensions" / "sources" / "deerflow-extension-demo"
    assert (managed_source / "demo_extension" / "__init__.py").is_file()
    project = tomllib.loads((root / "backend" / "pyproject.toml").read_text(encoding="utf-8"))
    assert project["dependency-groups"]["extensions"] == ["deerflow-extension-demo"]
    assert project["tool"]["uv"]["sources"]["deerflow-extension-demo"] == {"path": "extensions/sources/deerflow-extension-demo"}
    assert "workspace" not in project["tool"]["uv"]

    config = yaml.safe_load((root / "config.yaml").read_text(encoding="utf-8"))
    assert config["plugins"] == [
        {
            "name": "demo",
            "package": "deerflow-extension-demo",
            "use": "demo_extension:install",
            "enabled": True,
            "required": False,
            "config": {},
        }
    ]

    _assert_demo_entry_point_loads(root / "backend")


def test_install_defaults_to_a_fail_open_plugin_record(tmp_path: Path) -> None:
    """A managed install must not silently choose the fail-closed side: with
    `required: true`, a later broken extension aborts Gateway startup entirely,
    and recovery needs shell access to run `extensions disable`."""
    root = tmp_path / "deer-flow"
    source = tmp_path / "demo-source"
    root.mkdir()
    source.mkdir()
    _write_host_project(root)
    _write_local_extension(source)

    ExtensionManager(root).install(str(source), yes=True)

    config = yaml.safe_load((root / "config.yaml").read_text(encoding="utf-8"))
    assert config["plugins"][0]["required"] is False


def test_install_records_required_when_the_operator_opts_in(tmp_path: Path) -> None:
    root = tmp_path / "deer-flow"
    source = tmp_path / "demo-source"
    root.mkdir()
    source.mkdir()
    _write_host_project(root)
    _write_local_extension(source)

    ExtensionManager(root).install(str(source), yes=True, required=True)

    config = yaml.safe_load((root / "config.yaml").read_text(encoding="utf-8"))
    assert config["plugins"][0]["required"] is True


def test_cli_install_exposes_the_required_opt_in(tmp_path: Path, monkeypatch, capsys) -> None:
    root = tmp_path / "deer-flow"
    source = tmp_path / "demo-source"
    root.mkdir()
    source.mkdir()
    _write_host_project(root)
    _write_local_extension(source)
    monkeypatch.setenv("DEER_FLOW_PROJECT_ROOT", str(root))

    assert deerflow_main(["extensions", "install", str(source), "--yes", "--required"]) == 0

    capsys.readouterr()
    config = yaml.safe_load((root / "config.yaml").read_text(encoding="utf-8"))
    assert config["plugins"][0]["required"] is True


def test_contended_lock_waits_instead_of_failing() -> None:
    """Windows' blocking lock mode gives up after ~10 seconds, far shorter than
    a real `uv add` + `uv sync`, so the manager retries a non-blocking
    acquisition rather than turning contention into an error."""
    attempts: list[int] = []
    delays: list[float] = []

    def _acquire() -> None:
        attempts.append(len(attempts))
        if len(attempts) < 3:
            raise OSError(13, "Permission denied")

    _retry_until_locked(_acquire, sleep=delays.append)

    assert len(attempts) == 3
    assert len(delays) == 2
    assert all(delay > 0 for delay in delays)


def test_mutating_operations_are_serialized_for_one_checkout(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "deer-flow"
    root.mkdir()
    first_entered = threading.Event()
    release_first = threading.Event()
    second_entered = threading.Event()

    def _fake_install(self, source: str, *, yes: bool, required: bool):
        if source == "first":
            first_entered.set()
            assert release_first.wait(timeout=5)
        else:
            second_entered.set()
        return source

    monkeypatch.setattr(ExtensionManager, "_install", _fake_install)
    first_manager = ExtensionManager(root)
    second_manager = ExtensionManager(root)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(first_manager.install, "first", yes=True)
        assert first_entered.wait(timeout=5)
        second = pool.submit(second_manager.install, "second", yes=True)
        assert not second_entered.wait(timeout=0.2)
        release_first.set()
        assert first.result(timeout=5) == "first"
        assert second.result(timeout=5) == "second"

    assert second_entered.is_set()


def test_deerflow_extensions_install_exposes_the_local_install_flow(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    root = tmp_path / "deer-flow"
    source = tmp_path / "demo-source"
    root.mkdir()
    source.mkdir()
    _write_host_project(root)
    _write_local_extension(source)
    monkeypatch.setenv("DEER_FLOW_PROJECT_ROOT", str(root))

    exit_code = deerflow_main(["extensions", "install", str(source), "--yes"])

    assert exit_code == 0
    assert "Installed and enabled demo" in capsys.readouterr().out
    config = yaml.safe_load((root / "config.yaml").read_text(encoding="utf-8"))
    assert config["plugins"][0]["use"] == "demo_extension:install"


def test_hidden_source_env_option_reads_the_install_source_outside_the_shell_recipe(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = tmp_path / "deer-flow"
    source = tmp_path / "demo-source"
    root.mkdir()
    source.mkdir()
    _write_host_project(root)
    _write_local_extension(source)
    monkeypatch.setenv("DEER_FLOW_PROJECT_ROOT", str(root))
    monkeypatch.setenv("DEER_FLOW_EXTENSION_SOURCE", str(source))

    exit_code = deerflow_main(
        [
            "extensions",
            "install",
            "--source-env",
            "__deerflow_extension_source__",
            "--yes",
        ]
    )

    assert exit_code == 0
    config = yaml.safe_load((root / "config.yaml").read_text(encoding="utf-8"))
    assert config["plugins"][0]["name"] == "demo"


def test_explicit_invalid_project_root_does_not_fall_back_to_current_checkout(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("DEER_FLOW_PROJECT_ROOT", str(tmp_path / "not-a-checkout"))
    monkeypatch.chdir(Path(__file__).resolve().parents[2])

    with pytest.raises(FileNotFoundError, match="DEER_FLOW_PROJECT_ROOT"):
        find_project_root()


def test_install_git_source_discovers_and_enables_its_packaging_entry_point(tmp_path: Path) -> None:
    root = tmp_path / "deer-flow"
    source = tmp_path / "demo-git-source"
    root.mkdir()
    source.mkdir()
    _write_host_project(root)
    _write_local_extension(source)
    revision = _commit_local_extension(source)
    bare_repository = tmp_path / "demo.git"
    subprocess.run(["git", "clone", "-q", "--bare", str(source), str(bare_repository)], check=True)
    subprocess.run(["git", "--git-dir", str(bare_repository), "update-server-info"], check=True)

    with _serve_directory(tmp_path) as base_url:
        result = ExtensionManager(root).install(f"git+{base_url}/demo.git@{revision}", yes=True)

        shutil.rmtree(root / "backend" / ".venv")
        subprocess.run(["uv", "sync", "--locked"], cwd=root / "backend", check=True)
        _assert_demo_entry_point_loads(root / "backend")

    assert result == result.__class__(
        name="demo",
        distribution="deerflow-extension-demo",
        use="demo_extension:install",
    )
    assert not (root / "backend" / "extensions" / "sources" / "deerflow-extension-demo").exists()
    assert revision in (root / "backend" / "uv.lock").read_text(encoding="utf-8")
    config = yaml.safe_load((root / "config.yaml").read_text(encoding="utf-8"))
    assert config["plugins"][0]["name"] == "demo"


def test_install_rejects_a_pypi_requirement_resolved_from_an_external_local_wheel(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = tmp_path / "deer-flow"
    wheels = tmp_path / "wheels"
    root.mkdir()
    _write_host_project(root)
    _write_demo_wheel(wheels)
    monkeypatch.setenv("UV_FIND_LINKS", str(wheels))
    monkeypatch.setenv("UV_NO_INDEX", "1")
    pyproject_path = root / "backend" / "pyproject.toml"
    config_path = root / "config.yaml"
    before = (pyproject_path.read_bytes(), config_path.read_bytes())

    with pytest.raises(ValueError, match="build context"):
        ExtensionManager(root).install("deerflow-extension-demo==1.0.0", yes=True)

    assert (pyproject_path.read_bytes(), config_path.read_bytes()) == before
    assert not (root / "backend" / "uv.lock").exists()


@pytest.mark.parametrize("relative_wheels", ["wheels", "packages/harness/wheels"])
def test_install_rejects_a_local_wheel_directory_ignored_by_the_docker_context(
    tmp_path: Path,
    monkeypatch,
    relative_wheels: str,
) -> None:
    root = tmp_path / "deer-flow"
    root.mkdir()
    _write_host_project(root)
    wheels = root / "backend" / relative_wheels
    wheels.parent.mkdir(parents=True, exist_ok=True)
    _write_demo_wheel(wheels)
    monkeypatch.setenv("UV_FIND_LINKS", str(wheels))
    monkeypatch.setenv("UV_NO_INDEX", "1")
    pyproject_path = root / "backend" / "pyproject.toml"
    config_path = root / "config.yaml"
    before = (pyproject_path.read_bytes(), config_path.read_bytes())

    with pytest.raises(ValueError, match="build context"):
        ExtensionManager(root).install("deerflow-extension-demo==1.0.0", yes=True)

    assert (pyproject_path.read_bytes(), config_path.read_bytes()) == before
    assert not (root / "backend" / "uv.lock").exists()


def test_install_rejects_a_relative_find_links_wheelhouse_outside_the_build_context(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = tmp_path / "deer-flow"
    root.mkdir()
    _write_host_project(root)
    _write_demo_wheel(root / "backend" / "wheelhouse")
    # uv resolves a relative UV_FIND_LINKS against its working directory (the
    # backend project), so the lock records a relative registry that only
    # exists on this host.
    monkeypatch.setenv("UV_FIND_LINKS", "wheelhouse")
    monkeypatch.setenv("UV_NO_INDEX", "1")
    pyproject_path = root / "backend" / "pyproject.toml"
    config_path = root / "config.yaml"
    before = (pyproject_path.read_bytes(), config_path.read_bytes())

    with pytest.raises(ValueError, match="build context"):
        ExtensionManager(root).install("deerflow-extension-demo==1.0.0", yes=True)

    assert (pyproject_path.read_bytes(), config_path.read_bytes()) == before
    assert not (root / "backend" / "uv.lock").exists()


def _write_audit_host(backend: Path) -> None:
    (backend / "packages" / "harness").mkdir(parents=True)
    (backend / "packages" / "extension-api").mkdir(parents=True)
    (backend / "extensions" / "sources" / "deerflow-extension-demo").mkdir(parents=True)
    (backend / "pyproject.toml").write_text(
        '[tool.uv.workspace]\nmembers = ["packages/harness", "packages/extension-api"]\n',
        encoding="utf-8",
    )


def test_locked_local_source_audit_accepts_deployable_relative_references(tmp_path: Path) -> None:
    backend = tmp_path / "backend"
    backend.mkdir()
    _write_audit_host(backend)
    lock_path = backend / "uv.lock"
    lock_path.write_text(
        """\
version = 1
requires-python = ">=3.12"

[[package]]
name = "host"
version = "0.0.0"
source = { virtual = "." }

[package.metadata.requires-dev]
extensions = [{ name = "deerflow-extension-demo", directory = "extensions/sources/deerflow-extension-demo" }]

[[package]]
name = "deerflow-harness"
version = "0.0.0"
source = { editable = "packages/harness" }

[[package]]
name = "deerflow-extension-api"
version = "0.0.0"
source = { editable = "packages/extension-api" }

[[package]]
name = "deerflow-extension-demo"
version = "1.0.0"
source = { directory = "extensions/sources/deerflow-extension-demo" }

[[package]]
name = "git-extension"
version = "1.0.0"
source = { git = "https://github.com/acme/git-extension.git?rev=0123456789012345678901234567890123456789#0123456789012345678901234567890123456789" }

[[package]]
name = "requests"
version = "2.32.3"
source = { registry = "https://pypi.org/simple" }
sdist = { url = "https://files.pythonhosted.org/packages/requests-2.32.3.tar.gz", hash = "sha256:aaaa" }
wheels = [
    { url = "https://files.pythonhosted.org/packages/requests-2.32.3-py3-none-any.whl", hash = "sha256:bbbb" },
]
""",
        encoding="utf-8",
    )

    _validate_locked_local_sources(lock_path, backend)


@pytest.mark.parametrize(
    "source_line",
    [
        'source = { registry = "wheels" }',
        'source = { registry = "packages/harness/wheels" }',
        'source = { registry = "/srv/wheels" }',
        'source = { registry = "file:///srv/wheels" }',
        'source = { registry = "C:/srv/wheels" }',
        'source = { path = "vendor/demo.whl" }',
        'source = { directory = "../outside" }',
        'source = { editable = "packages/harness/../extension-api/../../wheels" }',
    ],
    ids=[
        "relative-wheelhouse",
        "wheelhouse-inside-a-workspace-member",
        "absolute-wheelhouse",
        "file-url-wheelhouse",
        "windows-absolute-wheelhouse",
        "direct-wheel-path",
        "escaping-directory",
        "dotdot-through-a-workspace-member",
    ],
)
def test_locked_local_source_audit_rejects_non_deployable_local_references(
    tmp_path: Path,
    source_line: str,
) -> None:
    backend = tmp_path / "backend"
    backend.mkdir()
    _write_audit_host(backend)
    lock_path = backend / "uv.lock"
    lock_path.write_text(
        f"""\
version = 1
requires-python = ">=3.12"

[[package]]
name = "host"
version = "0.0.0"
source = {{ virtual = "." }}

[[package]]
name = "smuggled"
version = "1.0.0"
{source_line}
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="build context"):
        _validate_locked_local_sources(lock_path, backend)


@pytest.mark.parametrize(
    "source_line",
    [
        'source = { registry = "http://127.0.0.1:8000/simple" }',
        'source = { registry = "http://localhost:8000/simple" }',
        'source = { url = "http://[::1]:8000/demo-1.0-py3-none-any.whl" }',
        'source = { git = "http://127.0.0.1:9418/demo.git?rev=0123456789012345678901234567890123456789" }',
    ],
    ids=[
        "loopback-ipv4-registry",
        "localhost-registry",
        "loopback-ipv6-wheel-url",
        "loopback-git-remote",
    ],
)
def test_locked_local_source_audit_warns_about_loopback_references(
    tmp_path: Path,
    source_line: str,
    caplog,
) -> None:
    """`_validate_remote_source` allows loopback HTTP for local tooling, so a
    loopback URL can legitimately land in the lock — but inside the backend
    image build `127.0.0.1` is a different machine. Unlike an environment-driven
    wheelhouse resolution, this is an explicit operator choice, so it warns
    instead of failing the transaction."""
    backend = tmp_path / "backend"
    backend.mkdir()
    _write_audit_host(backend)
    lock_path = backend / "uv.lock"
    lock_path.write_text(
        f"""\
version = 1
requires-python = ">=3.12"

[[package]]
name = "host"
version = "0.0.0"
source = {{ virtual = "." }}

[[package]]
name = "smuggled"
version = "1.0.0"
{source_line}
""",
        encoding="utf-8",
    )

    with caplog.at_level("WARNING", logger="deerflow.extensions.manager"):
        _validate_locked_local_sources(lock_path, backend)

    assert "loopback" in caplog.text


def test_locked_local_source_audit_allows_a_private_network_index(tmp_path: Path, caplog) -> None:
    """A builder on the same network can reach a private index host, so only
    loopback is rejected — blocking RFC1918 would break internal mirrors."""
    backend = tmp_path / "backend"
    backend.mkdir()
    _write_audit_host(backend)
    lock_path = backend / "uv.lock"
    lock_path.write_text(
        """\
version = 1
requires-python = ">=3.12"

[[package]]
name = "host"
version = "0.0.0"
source = { virtual = "." }

[[package]]
name = "internal"
version = "1.0.0"
source = { registry = "https://10.0.0.5/simple" }
wheels = [
    { url = "https://10.0.0.5/packages/internal-1.0.0-py3-none-any.whl", hash = "sha256:bbbb" },
]
""",
        encoding="utf-8",
    )

    with caplog.at_level("WARNING", logger="deerflow.extensions.manager"):
        _validate_locked_local_sources(lock_path, backend)

    assert caplog.text == ""


def test_locked_local_source_audit_rejects_absolute_paths_even_inside_allowed_roots(tmp_path: Path) -> None:
    backend = tmp_path / "backend"
    backend.mkdir()
    _write_audit_host(backend)
    lock_path = backend / "uv.lock"
    workspace_member = backend.resolve() / "packages" / "harness"
    lock_path.write_text(
        f"""\
version = 1
requires-python = ">=3.12"

[[package]]
name = "host"
version = "0.0.0"
source = {{ virtual = "." }}

[[package]]
name = "deerflow-harness"
version = "0.0.0"
source = {{ editable = "{workspace_member.as_posix()}" }}
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="build context"):
        _validate_locked_local_sources(lock_path, backend)


def test_file_urls_are_rejected_because_they_cannot_enter_the_docker_build_context(tmp_path: Path) -> None:
    root = tmp_path / "deer-flow"
    root.mkdir()
    _write_host_project(root)

    with pytest.raises(ValueError, match="local directory"):
        ExtensionManager(root).install("git+file:///outside/demo.git@deadbeef", yes=True)


def test_install_rolls_back_when_the_declared_entry_point_cannot_be_imported(tmp_path: Path) -> None:
    root = tmp_path / "deer-flow"
    source = tmp_path / "demo-source"
    root.mkdir()
    source.mkdir()
    _write_host_project(root)
    _write_local_extension(source, entry_target="missing_demo_extension:install")
    pyproject = root / "backend" / "pyproject.toml"
    original = pyproject.read_bytes()

    with pytest.raises(ValueError, match="could not be loaded"):
        ExtensionManager(root).install(str(source), yes=True)

    assert pyproject.read_bytes() == original
    assert not (root / "backend" / "uv.lock").exists()
    assert not (root / "backend" / "extensions" / "sources" / "deerflow-extension-demo").exists()
    assert yaml.safe_load((root / "config.yaml").read_text(encoding="utf-8")).get("plugins") is None


@pytest.mark.parametrize(
    "source",
    [
        "deerflow-extension-demo @ ../outside",
        "../outside/deerflow-extension-demo",
        "deerflow-extension-demo @ /outside/demo.whl",
    ],
)
def test_relative_or_absolute_direct_paths_must_use_the_managed_directory_snapshot(
    tmp_path: Path,
    source: str,
) -> None:
    root = tmp_path / "deer-flow"
    root.mkdir()
    _write_host_project(root)
    pyproject = root / "backend" / "pyproject.toml"
    original = pyproject.read_bytes()

    with pytest.raises(ValueError, match="local directory"):
        ExtensionManager(root).install(source, yes=True)

    assert pyproject.read_bytes() == original
    assert not (root / "backend" / "uv.lock").exists()


def test_install_preserves_unrelated_config_comments_and_layout(tmp_path: Path) -> None:
    root = tmp_path / "deer-flow"
    source = tmp_path / "demo-source"
    root.mkdir()
    source.mkdir()
    _write_host_project(root)
    _write_local_extension(source)
    config_path = root / "config.yaml"
    config_path.write_text(
        """\
# operator notes must survive extension management
config_version: 1

models:
  # keep the carefully documented model
  - name: demo-model
    use: provider:model

database:
  url: sqlite:///data.db
""",
        encoding="utf-8",
    )

    ExtensionManager(root).install(str(source), yes=True)

    updated = config_path.read_text(encoding="utf-8")
    assert "# operator notes must survive extension management" in updated
    assert "  # keep the carefully documented model" in updated
    assert "models:\n  # keep the carefully documented model\n  - name: demo-model\n    use: provider:model" in updated
    assert "database:\n  url: sqlite:///data.db" in updated


def test_toggle_preserves_the_next_section_header_and_crlf_style(tmp_path: Path) -> None:
    root = tmp_path / "deer-flow"
    root.mkdir()
    _write_host_project(root)
    config_path = root / "config.yaml"
    config_path.write_bytes(
        b"config_version: 1\r\n"
        b"plugins:\r\n"
        b"  - name: demo\r\n"
        b"    package: deerflow-extension-demo\r\n"
        b"    use: demo_extension:install\r\n"
        b"    enabled: true\r\n"
        b"    config:\r\n"
        b"      label: 'keep value'\r\n"
        b"\r\n"
        b"# Database settings must stay with the next section.\r\n"
        b"database:\r\n"
        b"  url: sqlite:///data.db\r\n"
    )

    ExtensionManager(root).set_enabled("demo", enabled=False)

    updated = config_path.read_bytes()
    assert b"# Database settings must stay with the next section.\r\n" in updated
    assert b"database:\r\n  url: sqlite:///data.db\r\n" in updated
    assert b"\n" not in updated.replace(b"\r\n", b"")
    parsed = yaml.safe_load(updated)
    assert parsed["plugins"][0]["config"] == {"label": "keep value"}
    assert parsed["plugins"][0]["enabled"] is False


def test_deerflow_extensions_disable_keeps_the_plugin_configuration(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    root = tmp_path / "deer-flow"
    root.mkdir()
    _write_host_project(root)
    config_path = root / "config.yaml"
    config_path.write_text(
        """\
# keep me
config_version: 1
plugins:
  - name: demo
    package: deerflow-extension-demo
    use: demo_extension:install
    enabled: true
    required: true
    config:
      label: production
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("DEER_FLOW_PROJECT_ROOT", str(root))

    exit_code = deerflow_main(["extensions", "disable", "demo"])

    assert exit_code == 0
    assert "Disabled demo" in capsys.readouterr().out
    updated = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert updated["plugins"] == [
        {
            "name": "demo",
            "package": "deerflow-extension-demo",
            "use": "demo_extension:install",
            "enabled": False,
            "required": True,
            "config": {"label": "production"},
        }
    ]
    assert "# keep me" in config_path.read_text(encoding="utf-8")


def test_hidden_name_env_option_reads_the_extension_name_outside_the_shell_recipe(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = tmp_path / "deer-flow"
    root.mkdir()
    _write_host_project(root)
    config_path = root / "config.yaml"
    config_path.write_text(
        "plugins:\n  - name: demo\n    package: deerflow-extension-demo\n    use: demo_extension:install\n    enabled: true\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("DEER_FLOW_PROJECT_ROOT", str(root))
    monkeypatch.setenv("DEER_FLOW_EXTENSION_NAME", "demo")

    exit_code = deerflow_main(
        [
            "extensions",
            "disable",
            "--name-env",
            "__deerflow_extension_name__",
        ]
    )

    assert exit_code == 0
    assert yaml.safe_load(config_path.read_text(encoding="utf-8"))["plugins"][0]["enabled"] is False


def test_deerflow_extensions_enable_reactivates_a_configured_plugin(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    root = tmp_path / "deer-flow"
    root.mkdir()
    _write_host_project(root)
    config_path = root / "config.yaml"
    config_path.write_text(
        """\
config_version: 1
plugins:
  - name: demo
    package: deerflow-extension-demo
    use: demo_extension:install
    enabled: false
    required: true
    config: {}
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("DEER_FLOW_PROJECT_ROOT", str(root))

    exit_code = deerflow_main(["extensions", "enable", "demo"])

    assert exit_code == 0
    assert "Enabled demo" in capsys.readouterr().out
    updated = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert updated["plugins"][0]["enabled"] is True


def test_distribution_identifier_uses_pep_503_normalization(tmp_path: Path) -> None:
    root = tmp_path / "deer-flow"
    root.mkdir()
    _write_host_project(root)
    config_path = root / "config.yaml"
    config_path.write_text(
        "plugins:\n  - name: demo\n    package: DeerFlow_Extension.Demo\n    use: demo_extension:install\n    enabled: true\n",
        encoding="utf-8",
    )

    ExtensionManager(root).set_enabled("deerflow-extension-demo", enabled=False)

    assert yaml.safe_load(config_path.read_text(encoding="utf-8"))["plugins"][0]["enabled"] is False


def test_deerflow_extensions_list_reports_activation_and_package(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    root = tmp_path / "deer-flow"
    root.mkdir()
    _write_host_project(root)
    (root / "config.yaml").write_text(
        """\
config_version: 1
plugins:
  - name: demo
    package: deerflow-extension-demo
    use: demo_extension:install
    enabled: true
    required: true
    config: {}
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("DEER_FLOW_PROJECT_ROOT", str(root))

    exit_code = deerflow_main(["extensions", "list"])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "demo" in output
    assert "enabled" in output
    assert "deerflow-extension-demo" in output
    assert "demo_extension:install" in output


def test_cli_reports_invalid_config_without_a_traceback(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    root = tmp_path / "deer-flow"
    root.mkdir()
    _write_host_project(root)
    (root / "config.yaml").write_text("plugins: [\n", encoding="utf-8")
    monkeypatch.setenv("DEER_FLOW_PROJECT_ROOT", str(root))

    exit_code = deerflow_main(["extensions", "list"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "invalid DeerFlow config YAML" in captured.err
    assert "Traceback" not in captured.err


@pytest.mark.parametrize(
    "malformed_plugin",
    [42, {"name": "missing-use"}],
    ids=["non-mapping", "missing-use"],
)
def test_deerflow_extensions_list_rejects_entries_the_runtime_schema_rejects(
    tmp_path: Path,
    monkeypatch,
    capsys,
    malformed_plugin: object,
) -> None:
    root = tmp_path / "deer-flow"
    root.mkdir()
    _write_host_project(root)
    (root / "config.yaml").write_text(
        yaml.safe_dump({"config_version": 1, "plugins": [malformed_plugin]}, sort_keys=False),
        encoding="utf-8",
    )
    monkeypatch.setenv("DEER_FLOW_PROJECT_ROOT", str(root))

    exit_code = deerflow_main(["extensions", "list"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "NAME\tSTATE\tPACKAGE\tENTRY POINT" not in captured.out
    assert "extension command failed:" in captured.err
    assert "Traceback" not in captured.err


def test_deerflow_extensions_remove_uninstalls_dependency_source_and_activation(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    root = tmp_path / "deer-flow"
    source = tmp_path / "demo-source"
    root.mkdir()
    source.mkdir()
    _write_host_project(root)
    _write_local_extension(source)
    ExtensionManager(root).install(str(source), yes=True)
    monkeypatch.setenv("DEER_FLOW_PROJECT_ROOT", str(root))

    exit_code = deerflow_main(["extensions", "remove", "demo"])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert "Removed demo" in output
    assert "Restart DeerFlow" in output
    config = yaml.safe_load((root / "config.yaml").read_text(encoding="utf-8"))
    assert config["plugins"] == []
    assert not (root / "backend" / "extensions" / "sources" / "deerflow-extension-demo").exists()
    pyproject = (root / "backend" / "pyproject.toml").read_text(encoding="utf-8")
    assert "deerflow-extension-demo" not in pyproject


def test_remove_one_configured_instance_keeps_its_shared_distribution_runnable(
    tmp_path: Path,
) -> None:
    root = tmp_path / "deer-flow"
    source = tmp_path / "demo-source"
    root.mkdir()
    source.mkdir()
    _write_host_project(root)
    _write_local_extension(source)
    manager = ExtensionManager(root)
    manager.install(str(source), yes=True)
    config_path = root / "config.yaml"
    installed = yaml.safe_load(config_path.read_text(encoding="utf-8"))["plugins"][0]
    first = {**installed, "name": "first", "config": {"instance": 1}}
    second = {
        **installed,
        "name": "second",
        "package": "DeerFlow_Extension.Demo",
        "config": {"instance": 2},
    }
    config_path.write_text(
        yaml.safe_dump({"config_version": 1, "plugins": [first, second]}, sort_keys=False),
        encoding="utf-8",
    )
    pyproject_path = root / "backend" / "pyproject.toml"
    lock_path = root / "backend" / "uv.lock"
    dependency_files_before = (pyproject_path.read_bytes(), lock_path.read_bytes())

    removed = manager.remove("first")

    assert removed == "first"
    assert yaml.safe_load(config_path.read_text(encoding="utf-8"))["plugins"] == [second]
    assert (pyproject_path.read_bytes(), lock_path.read_bytes()) == dependency_files_before
    assert (root / "backend" / "extensions" / "sources" / "deerflow-extension-demo").is_dir()
    _assert_demo_entry_point_loads(root / "backend")


def test_install_prompts_for_trust_when_yes_is_not_supplied(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    root = tmp_path / "deer-flow"
    source = tmp_path / "demo-source"
    root.mkdir()
    source.mkdir()
    _write_host_project(root)
    _write_local_extension(source)
    monkeypatch.setenv("DEER_FLOW_PROJECT_ROOT", str(root))
    monkeypatch.setattr("builtins.input", lambda _prompt: "yes")

    exit_code = deerflow_main(["extensions", "install", str(source)])

    assert exit_code == 0
    assert "executes code with Gateway privileges" in capsys.readouterr().out


def test_failed_entry_point_discovery_rolls_back_dependency_and_lock(tmp_path: Path) -> None:
    root = tmp_path / "deer-flow"
    source = tmp_path / "broken-git-source"
    root.mkdir()
    source.mkdir()
    _write_host_project(root)
    _write_local_extension(source, with_entry_point=False)
    revision = _commit_local_extension(source)
    bare_repository = tmp_path / "broken.git"
    subprocess.run(["git", "clone", "-q", "--bare", str(source), str(bare_repository)], check=True)
    subprocess.run(["git", "--git-dir", str(bare_repository), "update-server-info"], check=True)
    pyproject_path = root / "backend" / "pyproject.toml"
    config_path = root / "config.yaml"
    original_pyproject = pyproject_path.read_bytes()
    original_config = config_path.read_bytes()

    with _serve_directory(tmp_path) as base_url:
        with pytest.raises(ValueError, match="exactly one"):
            ExtensionManager(root).install(f"git+{base_url}/broken.git@{revision}", yes=True)

    assert pyproject_path.read_bytes() == original_pyproject
    assert config_path.read_bytes() == original_config
    assert not (root / "backend" / "uv.lock").exists()
    absent = subprocess.run(
        [
            str(root / "backend" / ".venv" / "bin" / "python"),
            "-c",
            "from importlib.metadata import PackageNotFoundError, version; \ntry: version('deerflow-extension-demo')\nexcept PackageNotFoundError: raise SystemExit(0)\nraise SystemExit(1)",
        ],
        check=False,
    )
    assert absent.returncode == 0


def test_failed_install_does_not_overwrite_a_concurrent_operator_config_edit(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = tmp_path / "deer-flow"
    source = tmp_path / "demo-source"
    root.mkdir()
    source.mkdir()
    _write_host_project(root)
    _write_local_extension(source)
    config_path = root / "config.yaml"
    operator_edit = "config_version: 1\nlog_level: debug # edited during install\n"
    from deerflow.extensions import manager as manager_module

    original_sync = manager_module._sync_environment
    calls = 0

    def _fail_after_operator_edit(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            config_path.write_text(operator_edit, encoding="utf-8")
            raise RuntimeError("simulated dependency sync failure")
        return original_sync(*args, **kwargs)

    monkeypatch.setattr("deerflow.extensions.manager._sync_environment", _fail_after_operator_edit)

    with pytest.raises(RuntimeError, match="sync failure"):
        ExtensionManager(root).install(str(source), yes=True)

    assert config_path.read_text(encoding="utf-8") == operator_edit


def test_failed_install_preserves_a_concurrent_dependency_file_edit(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = tmp_path / "deer-flow"
    source = tmp_path / "demo-source"
    root.mkdir()
    source.mkdir()
    _write_host_project(root)
    _write_local_extension(source)
    pyproject_path = root / "backend" / "pyproject.toml"

    def _fail_after_operator_edit(*_args, **_kwargs):
        pyproject_path.write_text(
            pyproject_path.read_text(encoding="utf-8") + "\n# operator edit during install\n",
            encoding="utf-8",
        )
        raise RuntimeError("simulated dependency sync failure")

    monkeypatch.setattr("deerflow.extensions.manager._sync_environment", _fail_after_operator_edit)

    with pytest.raises(RuntimeError, match="recovery.*dependency"):
        ExtensionManager(root).install(str(source), yes=True)

    assert "# operator edit during install" in pyproject_path.read_text(encoding="utf-8")
    assert (root / "backend" / "extensions" / "sources" / "deerflow-extension-demo").is_dir()


def test_uv_add_partial_writes_are_rolled_back_when_the_command_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = tmp_path / "deer-flow"
    source = tmp_path / "demo-source"
    root.mkdir()
    source.mkdir()
    _write_host_project(root)
    _write_local_extension(source)
    pyproject_path = root / "backend" / "pyproject.toml"
    lock_path = root / "backend" / "uv.lock"
    config_path = root / "config.yaml"
    before = (pyproject_path.read_bytes(), config_path.read_bytes())
    uv_commands: list[str] = []

    def _partially_write_then_fail(command, _backend_dir):
        uv_commands.append(command[1])
        if command[1] == "add":
            pyproject_path.write_text(
                pyproject_path.read_text(encoding="utf-8") + "\n# partial uv add write\n",
                encoding="utf-8",
            )
            lock_path.write_text("partial uv lock write\n", encoding="utf-8")
            raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr("deerflow.extensions.manager._run_uv", _partially_write_then_fail)

    with pytest.raises(subprocess.CalledProcessError):
        ExtensionManager(root).install(str(source), yes=True)

    assert (pyproject_path.read_bytes(), config_path.read_bytes()) == before
    assert not lock_path.exists()
    assert not (root / "backend" / "extensions" / "sources" / "deerflow-extension-demo").exists()
    assert uv_commands == ["add", "sync"]


def test_local_install_rejects_symlinks_before_copying_or_resolving(tmp_path: Path) -> None:
    root = tmp_path / "deer-flow"
    source = tmp_path / "demo-source"
    root.mkdir()
    source.mkdir()
    _write_host_project(root)
    _write_local_extension(source)
    outside = tmp_path / "operator-secret.txt"
    outside.write_text("do not vendor me", encoding="utf-8")
    (source / "linked-secret.txt").symlink_to(outside)
    original_pyproject = (root / "backend" / "pyproject.toml").read_bytes()

    with pytest.raises(ValueError, match="symbolic links"):
        ExtensionManager(root).install(str(source), yes=True)

    assert (root / "backend" / "pyproject.toml").read_bytes() == original_pyproject
    assert not (root / "backend" / "extensions").exists()


@pytest.mark.skipif(os.name == "nt", reason="named pipes are POSIX-specific")
def test_local_install_rejects_special_files_before_snapshotting(tmp_path: Path) -> None:
    root = tmp_path / "deer-flow"
    source = tmp_path / "demo-source"
    root.mkdir()
    source.mkdir()
    _write_host_project(root)
    _write_local_extension(source)
    os.mkfifo(source / "runtime.pipe")

    with pytest.raises(ValueError, match="regular files"):
        ExtensionManager(root).install(str(source), yes=True)

    assert not (root / "backend" / "extensions").exists()


@pytest.mark.parametrize(
    "secret_name",
    [".env.local", "deploy.pem", "credentials.json", ".npmrc", ".pypirc"],
)
def test_local_install_rejects_likely_secret_files(
    tmp_path: Path,
    secret_name: str,
) -> None:
    root = tmp_path / "deer-flow"
    source = tmp_path / "demo-source"
    root.mkdir()
    source.mkdir()
    _write_host_project(root)
    _write_local_extension(source)
    (source / secret_name).write_text("credential", encoding="utf-8")

    with pytest.raises(ValueError, match="sensitive file"):
        ExtensionManager(root).install(str(source), yes=True)

    assert not (root / "backend" / "extensions").exists()


@pytest.mark.parametrize("distribution", ["../outside", "/tmp/outside", "C:/outside"])
def test_local_install_rejects_distribution_names_that_escape_the_managed_root(
    tmp_path: Path,
    distribution: str,
) -> None:
    root = tmp_path / "deer-flow"
    source = tmp_path / "demo-source"
    root.mkdir()
    source.mkdir()
    _write_host_project(root)
    _write_local_extension(source, distribution=distribution)

    with pytest.raises(ValueError, match="distribution name"):
        ExtensionManager(root).install(str(source), yes=True)

    assert not (root / "backend" / "extensions").exists()


def test_install_adopts_an_existing_manual_plugin_instead_of_loading_it_twice(tmp_path: Path) -> None:
    root = tmp_path / "deer-flow"
    source = tmp_path / "demo-source"
    root.mkdir()
    source.mkdir()
    _write_host_project(root)
    _write_local_extension(source)
    config_path = root / "config.yaml"
    config_path.write_text(
        """\
config_version: 1
plugins:
  - use: demo_extension:install
    required: false
    config:
      label: keep-this
""",
        encoding="utf-8",
    )

    ExtensionManager(root).install(str(source), yes=True)

    plugins = yaml.safe_load(config_path.read_text(encoding="utf-8"))["plugins"]
    assert plugins == [
        {
            "use": "demo_extension:install",
            "required": False,
            "config": {"label": "keep-this"},
            "name": "demo",
            "package": "deerflow-extension-demo",
            "enabled": True,
        }
    ]


@pytest.mark.parametrize(
    "configured_plugin",
    [
        {
            "name": "demo",
            "use": "other_extension:install",
            "config": {"keep": True},
        },
        {
            "package": "deerflow-extension-demo",
            "use": "other_extension:install",
            "config": {"keep": True},
        },
        {
            "package": "deerflow_extension.demo",
            "use": "other_extension:install",
            "config": {"keep": True},
        },
    ],
)
def test_install_rejects_identity_collisions_with_a_different_entry_point(
    tmp_path: Path,
    configured_plugin: dict[str, object],
) -> None:
    root = tmp_path / "deer-flow"
    source = tmp_path / "demo-source"
    root.mkdir()
    source.mkdir()
    _write_host_project(root)
    _write_local_extension(source)
    config_path = root / "config.yaml"
    original = yaml.safe_dump(
        {"config_version": 1, "plugins": [configured_plugin]},
        sort_keys=False,
    )
    config_path.write_text(original, encoding="utf-8")

    with pytest.raises(ValueError, match="conflict"):
        ExtensionManager(root).install(str(source), yes=True)

    assert config_path.read_text(encoding="utf-8") == original
    assert not (root / "backend" / "extensions" / "sources" / "deerflow-extension-demo").exists()
    assert "deerflow-extension-demo" not in (root / "backend" / "pyproject.toml").read_text(encoding="utf-8")


def test_install_replaces_inline_empty_plugins_with_one_schema_valid_block(tmp_path: Path) -> None:
    root = tmp_path / "deer-flow"
    source = tmp_path / "demo-source"
    root.mkdir()
    source.mkdir()
    _write_host_project(root)
    _write_local_extension(source)
    config_path = root / "config.yaml"
    config_path.write_text(
        "config_version: 1\nplugins: [] # managed plugins\nlog_level: info\n",
        encoding="utf-8",
    )

    ExtensionManager(root).install(str(source), yes=True)

    updated = config_path.read_text(encoding="utf-8")
    assert updated.count("plugins:") == 1
    config = yaml.safe_load(updated)
    assert config["log_level"] == "info"
    parsed = ExtensionSpec.model_validate(config["plugins"][0])
    assert parsed.name == "demo"
    assert parsed.package == "deerflow-extension-demo"
    assert parsed.enabled is True


@pytest.mark.parametrize(
    "plugins_key",
    ["plugins", '"plugins"', "'plugins'"],
)
def test_disable_replaces_nonempty_flow_style_plugins_without_duplicate_key(
    tmp_path: Path,
    plugins_key: str,
) -> None:
    root = tmp_path / "deer-flow"
    root.mkdir()
    _write_host_project(root)
    config_path = root / "config.yaml"
    config_path.write_text(
        f'{plugins_key}: [{{name: demo, package: deerflow-extension-demo, use: "demo_extension:install", enabled: true}}]\nlog_level: info\n',
        encoding="utf-8",
    )

    ExtensionManager(root).set_enabled("demo", enabled=False)

    updated = config_path.read_text(encoding="utf-8")
    assert len(re.findall(r"(?m)^(?:plugins|[\'\"]plugins[\'\"])[ \t]*:", updated)) == 1
    config = yaml.safe_load(updated)
    assert config["plugins"][0]["enabled"] is False
    assert config["log_level"] == "info"


def test_toggle_rejects_duplicate_top_level_plugins_keys_without_mutating_config(
    tmp_path: Path,
) -> None:
    root = tmp_path / "deer-flow"
    root.mkdir()
    _write_host_project(root)
    config_path = root / "config.yaml"
    original = """\
plugins: []
log_level: info
"plugins":
  - name: demo
    package: deerflow-extension-demo
    use: demo_extension:install
    enabled: true
"""
    config_path.write_text(original, encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate top-level plugins"):
        ExtensionManager(root).set_enabled("demo", enabled=False)

    assert config_path.read_text(encoding="utf-8") == original


@pytest.mark.parametrize("next_key", ["log_level", '"log_level"', "'log_level'"])
def test_plugins_rewrite_preserves_the_next_quoted_or_plain_top_level_section(
    tmp_path: Path,
    next_key: str,
) -> None:
    root = tmp_path / "deer-flow"
    root.mkdir()
    _write_host_project(root)
    config_path = root / "config.yaml"
    config_path.write_text(
        f'plugins: [{{name: demo, use: "demo_extension:install", enabled: true}}]\n{next_key}: info\n',
        encoding="utf-8",
    )

    ExtensionManager(root).set_enabled("demo", enabled=False)

    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert config["plugins"][0]["enabled"] is False
    assert config["log_level"] == "info"


@pytest.mark.parametrize("next_key", ["my.key", "2fa", "$schema", "日本", "my key"])
def test_plugins_rewrite_preserves_a_following_section_with_an_unconventional_key(
    tmp_path: Path,
    next_key: str,
) -> None:
    """`AppConfig` allows extra top-level keys, so the managed rewrite must not
    assume the next section is named like a Python identifier."""
    root = tmp_path / "deer-flow"
    root.mkdir()
    _write_host_project(root)
    config_path = root / "config.yaml"
    config_path.write_text(
        f'plugins: [{{name: demo, use: "demo_extension:install", enabled: true}}]\n{next_key}:\n  nested: keep-me\n',
        encoding="utf-8",
    )

    ExtensionManager(root).set_enabled("demo", enabled=False)

    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert config["plugins"][0]["enabled"] is False
    assert config[next_key] == {"nested": "keep-me"}


def test_plugins_rewrite_preserves_trailing_content_below_a_final_plugins_block(tmp_path: Path) -> None:
    """The manager appends `plugins:` at end of file, so the steady-state shape
    has no following key; trailing operator notes still must survive a toggle."""
    root = tmp_path / "deer-flow"
    root.mkdir()
    _write_host_project(root)
    config_path = root / "config.yaml"
    config_path.write_text(
        'log_level: info\nplugins: [{name: demo, use: "demo_extension:install", enabled: true}]\n\n# operator note kept below the managed block\n',
        encoding="utf-8",
    )

    ExtensionManager(root).set_enabled("demo", enabled=False)

    updated = config_path.read_text(encoding="utf-8")
    assert "# operator note kept below the managed block" in updated
    config = yaml.safe_load(updated)
    assert config["plugins"][0]["enabled"] is False
    assert config["log_level"] == "info"


def test_null_plugins_is_treated_as_the_runtime_default_and_can_be_managed(tmp_path: Path) -> None:
    root = tmp_path / "deer-flow"
    root.mkdir()
    _write_host_project(root)
    config_path = root / "config.yaml"
    config_path.write_text("plugins: # no extensions yet\nlog_level: info\n", encoding="utf-8")
    manager = ExtensionManager(root)

    assert manager.list_configured() == ()


def test_list_uses_the_same_boolean_coercion_as_the_runtime_loader(tmp_path: Path) -> None:
    root = tmp_path / "deer-flow"
    root.mkdir()
    _write_host_project(root)
    (root / "config.yaml").write_text(
        """\
plugins:
  - name: numeric
    package: deerflow-extension-numeric
    use: numeric_extension:install
    enabled: 0
    required: 1
  - name: yaml-booleans
    package: deerflow-extension-yaml-booleans
    use: yaml_boolean_extension:install
    enabled: yes
    required: no
""",
        encoding="utf-8",
    )

    configured = ExtensionManager(root).list_configured()

    assert [(item.enabled, item.required) for item in configured] == [
        (False, True),
        (True, False),
    ]


def test_cli_install_updates_the_runtime_selected_config_file(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = tmp_path / "deer-flow"
    source = tmp_path / "demo-source"
    runtime_config = tmp_path / "deployment.yaml"
    root.mkdir()
    source.mkdir()
    _write_host_project(root)
    _write_local_extension(source)
    root_config = root / "config.yaml"
    original_root_config = root_config.read_bytes()
    runtime_config.write_text("config_version: 1\n", encoding="utf-8")
    monkeypatch.setenv("DEER_FLOW_PROJECT_ROOT", str(root))
    monkeypatch.setenv("DEER_FLOW_CONFIG_PATH", str(runtime_config))

    assert deerflow_main(["extensions", "install", str(source), "--yes"]) == 0

    assert root_config.read_bytes() == original_root_config
    runtime = yaml.safe_load(runtime_config.read_text(encoding="utf-8"))
    assert runtime["plugins"][0]["name"] == "demo"


def test_manager_falls_back_to_the_legacy_backend_config_path(tmp_path: Path) -> None:
    root = tmp_path / "deer-flow"
    root.mkdir()
    _write_host_project(root)
    (root / "config.yaml").unlink()
    backend_config = root / "backend" / "config.yaml"
    backend_config.write_text("config_version: 1\nplugins: []\n", encoding="utf-8")

    assert ExtensionManager(root).list_configured() == ()


def test_remove_rolls_back_package_lock_config_source_and_environment_when_config_write_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = tmp_path / "deer-flow"
    source = tmp_path / "demo-source"
    root.mkdir()
    source.mkdir()
    _write_host_project(root)
    _write_local_extension(source)
    manager = ExtensionManager(root)
    manager.install(str(source), yes=True)
    pyproject_path = root / "backend" / "pyproject.toml"
    lock_path = root / "backend" / "uv.lock"
    config_path = root / "config.yaml"
    managed_source = root / "backend" / "extensions" / "sources" / "deerflow-extension-demo"
    before = (
        pyproject_path.read_bytes(),
        lock_path.read_bytes(),
        config_path.read_bytes(),
    )

    def _fail_replace(_source, _target):
        raise OSError("simulated config replacement failure")

    monkeypatch.setattr("deerflow.extensions.manager.os.replace", _fail_replace)

    with pytest.raises(OSError, match="replacement failure"):
        manager.remove("demo")

    assert (pyproject_path.read_bytes(), lock_path.read_bytes(), config_path.read_bytes()) == before
    assert managed_source.is_dir()
    present = subprocess.run(
        [
            str(root / "backend" / ".venv" / "bin" / "python"),
            "-c",
            "from importlib.metadata import version; assert version('deerflow-extension-demo') == '1.0.0'",
        ],
        check=False,
    )
    assert present.returncode == 0


def test_failed_remove_preserves_a_concurrent_operator_config_edit(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = tmp_path / "deer-flow"
    source = tmp_path / "demo-source"
    root.mkdir()
    source.mkdir()
    _write_host_project(root)
    _write_local_extension(source)
    manager = ExtensionManager(root)
    manager.install(str(source), yes=True)
    config_path = root / "config.yaml"
    operator_edit = "config_version: 1\nplugins: []\nlog_level: debug # edited during remove\n"
    from deerflow.extensions import manager as manager_module

    original_sync = manager_module._sync_environment
    calls = 0

    def _fail_after_operator_edit(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            config_path.write_text(operator_edit, encoding="utf-8")
            raise RuntimeError("simulated dependency sync failure")
        return original_sync(*args, **kwargs)

    monkeypatch.setattr("deerflow.extensions.manager._sync_environment", _fail_after_operator_edit)

    with pytest.raises(
        RuntimeError,
        match="recovery.*config",
    ):
        manager.remove("demo")

    assert config_path.read_text(encoding="utf-8") == operator_edit
    assert (root / "backend" / "extensions" / "sources" / "deerflow-extension-demo").is_dir()


def test_failed_remove_preserves_a_concurrent_dependency_file_edit(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = tmp_path / "deer-flow"
    source = tmp_path / "demo-source"
    root.mkdir()
    source.mkdir()
    _write_host_project(root)
    _write_local_extension(source)
    manager = ExtensionManager(root)
    manager.install(str(source), yes=True)
    pyproject_path = root / "backend" / "pyproject.toml"

    def _fail_after_operator_edit(*_args, **_kwargs):
        pyproject_path.write_text(
            pyproject_path.read_text(encoding="utf-8") + "\n# operator edit during remove\n",
            encoding="utf-8",
        )
        raise RuntimeError("simulated dependency sync failure")

    monkeypatch.setattr("deerflow.extensions.manager._sync_environment", _fail_after_operator_edit)

    with pytest.raises(RuntimeError, match="recovery.*dependency"):
        manager.remove("demo")

    assert "# operator edit during remove" in pyproject_path.read_text(encoding="utf-8")
    assert (root / "backend" / "extensions" / "sources" / "deerflow-extension-demo").is_dir()
    assert yaml.safe_load((root / "config.yaml").read_text(encoding="utf-8"))["plugins"] == []


def test_uv_remove_partial_writes_are_rolled_back_when_the_command_fails(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = tmp_path / "deer-flow"
    source = tmp_path / "demo-source"
    root.mkdir()
    source.mkdir()
    _write_host_project(root)
    _write_local_extension(source)
    manager = ExtensionManager(root)
    manager.install(str(source), yes=True)
    pyproject_path = root / "backend" / "pyproject.toml"
    lock_path = root / "backend" / "uv.lock"
    config_path = root / "config.yaml"
    managed_source = root / "backend" / "extensions" / "sources" / "deerflow-extension-demo"
    before = (pyproject_path.read_bytes(), lock_path.read_bytes(), config_path.read_bytes())
    uv_commands: list[str] = []

    def _partially_write_then_fail(command, _backend_dir):
        uv_commands.append(command[1])
        if command[1] == "remove":
            pyproject_path.write_text(
                pyproject_path.read_text(encoding="utf-8") + "\n# partial uv remove write\n",
                encoding="utf-8",
            )
            lock_path.write_text(
                lock_path.read_text(encoding="utf-8") + "\n# partial uv remove lock write\n",
                encoding="utf-8",
            )
            raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr("deerflow.extensions.manager._run_uv", _partially_write_then_fail)

    with pytest.raises(subprocess.CalledProcessError):
        manager.remove("demo")

    assert (pyproject_path.read_bytes(), lock_path.read_bytes(), config_path.read_bytes()) == before
    assert managed_source.is_dir()
    assert uv_commands == ["remove", "sync"]


def test_cli_reports_uv_install_failure_without_traceback_or_partial_state(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    root = tmp_path / "deer-flow"
    root.mkdir()
    _write_host_project(root)
    pyproject_path = root / "backend" / "pyproject.toml"
    config_path = root / "config.yaml"
    original = (pyproject_path.read_bytes(), config_path.read_bytes())
    monkeypatch.setenv("DEER_FLOW_PROJECT_ROOT", str(root))

    exit_code = deerflow_main(["extensions", "install", "not a valid @ requirement @@", "--yes"])

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "extension command failed" in captured.err
    assert "Traceback" not in captured.err
    assert (pyproject_path.read_bytes(), config_path.read_bytes()) == original


@pytest.mark.parametrize(
    "source",
    [
        "git+https://token@example.com/acme/demo.git@0123456789012345678901234567890123456789",
        "https://user:password@example.com/demo.whl",
        "deerflow-extension-demo @ https://user:password@example.com/demo.whl",
    ],
)
def test_remote_sources_with_embedded_credentials_are_rejected_before_uv(
    tmp_path: Path,
    source: str,
) -> None:
    root = tmp_path / "deer-flow"
    root.mkdir()
    _write_host_project(root)
    original = (root / "backend" / "pyproject.toml").read_bytes()

    with pytest.raises(ValueError, match="credentials"):
        ExtensionManager(root).install(source, yes=True)

    assert (root / "backend" / "pyproject.toml").read_bytes() == original


@pytest.mark.parametrize(
    "source",
    [
        "https://packages.example/demo.whl?token=do-not-store",
        "demo @ https://packages.example/demo.whl?X-Amz-Signature=do-not-store",
        "https://packages.example/demo.whl#api_key=do-not-store",
        "https://packages.example/demo.whl?authToken=do-not-store",
        "https://packages.example/demo.whl?clientSecret=do-not-store",
        "https://packages.example/demo.whl?AWSAccessKeyId=do-not-store",
        "https://packages.example/demo.whl?Authorization=Bearer-do-not-store",
        "https://packages.example/demo.whl?X-Authorization=Bearer-do-not-store",
    ],
)
def test_remote_sources_with_secret_query_parameters_are_rejected(source: str) -> None:
    with pytest.raises(ValueError, match="credential"):
        _validate_remote_source(source)


@pytest.mark.parametrize(
    "source",
    [
        "https://packages.example/demo.whl?accesstoken=do-not-store",
        "https://packages.example/demo.whl?ACCESSTOKEN=do-not-store",
        "https://packages.example/demo.whl?apikey=do-not-store",
        "https://packages.example/demo.whl?key=do-not-store",
        "https://packages.example/demo.whl?pw=do-not-store",
        "https://packages.example/demo.whl?sas=do-not-store",
        "https://packages.example/demo.whl?code=do-not-store",
    ],
)
def test_run_together_secret_query_parameters_are_rejected(source: str) -> None:
    """The camel-case splitter only fires on case transitions, so run-together
    and all-caps spellings need to be recognized directly."""
    with pytest.raises(ValueError, match="credential"):
        _validate_remote_source(source)


@pytest.mark.parametrize(
    "source",
    [
        "git+https://github.com/acme/demo.git@main#subdirectory=packages/demo",
        "https://packages.example/demo.whl?keyword=demo",
        "https://packages.example/demo.whl?monkeypatch=1",
        "https://packages.example/demo.whl?rev=0123456789",
    ],
)
def test_benign_query_parameters_remain_installable(source: str) -> None:
    _validate_remote_source(source)


@pytest.mark.parametrize(
    "source",
    [
        "git+ssh://git@github.com/acme/deerflow-extension-demo.git@main",
        "deerflow-extension-demo @ git+ssh://git@github.com/acme/deerflow-extension-demo.git@main",
        "ssh://git@github.com/acme/deerflow-extension-demo.git@main",
    ],
)
def test_remote_git_ssh_sources_are_rejected_before_uv(
    tmp_path: Path,
    source: str,
) -> None:
    root = tmp_path / "deer-flow"
    root.mkdir()
    _write_host_project(root)
    pyproject_path = root / "backend" / "pyproject.toml"
    original = pyproject_path.read_bytes()

    with pytest.raises(ValueError, match="public HTTPS"):
        ExtensionManager(root).install(source, yes=True)

    assert pyproject_path.read_bytes() == original
    assert not (root / "backend" / "uv.lock").exists()


@pytest.mark.parametrize(
    "source",
    [
        "git@github.com:acme/deerflow-extension-demo.git",
        "git+git@github.com:acme/deerflow-extension-demo.git",
        "deerflow-extension-demo @ git+git@github.com:acme/deerflow-extension-demo.git",
        "deploy@internal.example:acme/deerflow-extension-demo.git",
    ],
)
def test_git_ssh_shorthand_points_at_the_https_correction(source: str) -> None:
    """SCP-like shorthand carries no scheme, so it reaches validation looking
    like a bare path. The operator asked for a remote source, so the actionable
    correction is the HTTPS spelling, not a local directory snapshot."""
    with pytest.raises(ValueError, match="public HTTPS") as excinfo:
        _validate_remote_source(source)

    message = str(excinfo.value)
    assert "git+https://" in message
    assert "snapshot" not in message


def test_cli_rejects_git_ssh_without_traceback_or_partial_state(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    root = tmp_path / "deer-flow"
    root.mkdir()
    _write_host_project(root)
    pyproject_path = root / "backend" / "pyproject.toml"
    original = pyproject_path.read_bytes()
    monkeypatch.setenv("DEER_FLOW_PROJECT_ROOT", str(root))

    exit_code = deerflow_main(
        [
            "extensions",
            "install",
            "git+ssh://git@github.com/acme/deerflow-extension-demo.git@main",
            "--yes",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "public HTTPS" in captured.err
    assert "Traceback" not in captured.err
    assert pyproject_path.read_bytes() == original
    assert not (root / "backend" / "uv.lock").exists()


@pytest.mark.parametrize(
    "source",
    [
        "git+https://github.com/acme/deerflow-extension-demo.git@0123456789012345678901234567890123456789",
        "deerflow-extension-demo @ git+https://github.com/acme/deerflow-extension-demo.git@0123456789012345678901234567890123456789",
    ],
)
def test_public_git_https_sources_remain_allowed(source: str) -> None:
    _validate_remote_source(source)


@pytest.mark.parametrize(
    "source",
    [
        "http://packages.example/demo.whl",
        "git+git://github.com/acme/deerflow-extension-demo.git@main",
        "ftp://packages.example/demo.whl",
    ],
)
def test_remote_sources_require_https(source: str) -> None:
    with pytest.raises(ValueError, match="HTTPS"):
        _validate_remote_source(source)


def test_cli_never_echoes_rejected_source_credentials(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    root = tmp_path / "deer-flow"
    root.mkdir()
    _write_host_project(root)
    monkeypatch.setenv("DEER_FLOW_PROJECT_ROOT", str(root))
    source = "https://operator:super-secret@example.com/extension.whl"

    assert deerflow_main(["extensions", "install", source, "--yes"]) == 1

    output = capsys.readouterr()
    assert "super-secret" not in output.out
    assert "super-secret" not in output.err
    assert "embedded credentials" in output.err


def test_install_uses_one_controlled_uv_project_and_deferred_sync(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = tmp_path / "deer-flow"
    source = tmp_path / "demo-source"
    root.mkdir()
    source.mkdir()
    _write_host_project(root)
    _write_local_extension(source)
    for key in ("UV_PROJECT", "UV_WORKING_DIR", "UV_NO_SYNC", "UV_FROZEN", "UV_LOCKED"):
        monkeypatch.setenv(key, "must-not-reach-uv")
    monkeypatch.setenv("UV_INDEX_URL", "https://packages.example/simple")
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.example:8080")
    uv_calls: list[tuple[list[str], dict[str, object]]] = []

    def _record_run(command, **kwargs):
        if command[:2] == ["uv", "--version"]:
            return subprocess.CompletedProcess(command, 0, stdout="uv 0.11.1\n")
        if command[0] == "uv":
            uv_calls.append((list(command), kwargs))
            if command[1] == "add":
                (root / "backend" / "uv.lock").write_text('version = 1\nrequires-python = ">=3.12"\n', encoding="utf-8")
            return subprocess.CompletedProcess(command, 0)
        return subprocess.CompletedProcess(command, 0, stdout='[["demo", "demo_extension:install"]]\n')

    monkeypatch.setattr("deerflow.extensions.manager.subprocess.run", _record_run)

    ExtensionManager(root).install(str(source), yes=True)

    assert [command[1] for command, _ in uv_calls] == ["add", "sync"]
    backend = str(root / "backend")
    add, sync = (uv_calls[0][0], uv_calls[1][0])
    assert ["--project", backend] == add[add.index("--project") : add.index("--project") + 2]
    assert "--no-sync" in add
    assert "--no-workspace" in add
    assert add[-2:] == ["--", "extensions/sources/deerflow-extension-demo"]
    assert ["--project", backend] == sync[sync.index("--project") : sync.index("--project") + 2]
    assert "--locked" in sync
    assert "--no-sync" not in sync
    for _, kwargs in uv_calls:
        child_env = kwargs["env"]
        assert isinstance(child_env, dict)
        assert not {
            "UV_PROJECT",
            "UV_WORKING_DIR",
            "UV_NO_SYNC",
            "UV_FROZEN",
            "UV_LOCKED",
        }.intersection(child_env)
        assert child_env["UV_INDEX_URL"] == "https://packages.example/simple"
        assert child_env["HTTPS_PROXY"] == "http://proxy.example:8080"


@pytest.mark.parametrize(
    "variable",
    ["UV_PYTHON", "UV_INSECURE_HOST", "UV_CONSTRAINT", "UV_NO_BUILD_ISOLATION"],
)
def test_controlled_uv_environment_drops_interpreter_and_trust_overrides(monkeypatch, variable: str) -> None:
    """These redirect the target environment rather than index/proxy/cache
    settings: `UV_PYTHON` swaps the interpreter that later loads the extension
    entry point, and `UV_INSECURE_HOST` removes the TLS validation that the
    HTTPS-only source rule depends on."""
    monkeypatch.setenv(variable, "must-not-reach-uv")

    assert variable not in _controlled_uv_environment()


@pytest.mark.parametrize(
    ("config_text", "expected_error", "message"),
    [
        (
            'plugins: []\nlog_level: info\n"plugins":\n  - use: demo_extension:install\n',
            ValueError,
            "duplicate top-level plugins",
        ),
        (None, FileNotFoundError, "config not found"),
        ("- not-a-mapping\n", ValueError, "must be a mapping"),
    ],
    ids=["duplicate-plugins-keys", "missing-config", "non-mapping-root"],
)
def test_install_validates_the_config_before_running_third_party_build_hooks(
    tmp_path: Path,
    monkeypatch,
    config_text: str | None,
    expected_error: type[Exception],
    message: str,
) -> None:
    """`uv add`/`uv sync` execute the package's build backend, so a config the
    manager can never write to must be rejected before that code runs — not
    after it, via rollback."""
    root = tmp_path / "deer-flow"
    source = tmp_path / "demo-source"
    root.mkdir()
    source.mkdir()
    _write_host_project(root)
    _write_local_extension(source)
    config_path = root / "config.yaml"
    if config_text is None:
        config_path.unlink()
    else:
        config_path.write_text(config_text, encoding="utf-8")
    commands: list[list[str]] = []

    def _record(command, **_kwargs):
        commands.append(list(command))
        return subprocess.CompletedProcess(command, 0, stdout="uv 0.11.1\n")

    monkeypatch.setattr("deerflow.extensions.manager.subprocess.run", _record)

    with pytest.raises(expected_error, match=message):
        ExtensionManager(root).install(str(source), yes=True)

    assert commands == []
    assert not (root / "backend" / "extensions").exists()


def test_failed_recovery_sync_still_restores_the_dependency_files(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """The recovery `uv sync` runs without `--locked` when the checkout had no
    lock, so uv writes one while resolving. If that sync then fails, the
    operator must not be left holding a lock file they never had."""
    root = tmp_path / "deer-flow"
    source = tmp_path / "demo-source"
    root.mkdir()
    source.mkdir()
    _write_host_project(root)
    _write_local_extension(source)
    backend = root / "backend"
    pyproject_path = backend / "pyproject.toml"
    lock_path = backend / "uv.lock"
    original_pyproject = pyproject_path.read_text(encoding="utf-8")

    def _run(command, **_kwargs):
        if command[:2] == ["uv", "--version"]:
            return subprocess.CompletedProcess(command, 0, stdout="uv 0.11.1\n")
        if command[0] != "uv":
            return subprocess.CompletedProcess(command, 0, stdout='[["demo", "demo_extension:install"]]\n')
        if command[1] == "add":
            pyproject_path.write_text(
                original_pyproject.replace("extensions = []", 'extensions = ["deerflow-extension-demo"]'),
                encoding="utf-8",
            )
            lock_path.write_text('version = 1\nrequires-python = ">=3.12"\n', encoding="utf-8")
            return subprocess.CompletedProcess(command, 0)
        if "--locked" not in command:
            lock_path.write_text("version = 1\n# written by the recovery resolve\n", encoding="utf-8")
        raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr("deerflow.extensions.manager.subprocess.run", _run)

    with pytest.raises(RuntimeError, match="original failure"):
        ExtensionManager(root).install(str(source), yes=True)

    assert not lock_path.exists()
    assert pyproject_path.read_text(encoding="utf-8") == original_pyproject


def test_interrupt_during_install_restores_files_without_a_recovery_resolve(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """Ctrl-C must not be answered by blocking on a full dependency resolve: a
    second interrupt during that sync would escape the handler and strand the
    checkout mid-transaction."""
    root = tmp_path / "deer-flow"
    source = tmp_path / "demo-source"
    root.mkdir()
    source.mkdir()
    _write_host_project(root)
    _write_local_extension(source)
    backend = root / "backend"
    pyproject_path = backend / "pyproject.toml"
    lock_path = backend / "uv.lock"
    original_pyproject = pyproject_path.read_text(encoding="utf-8")
    syncs: list[list[str]] = []

    def _run(command, **_kwargs):
        if command[:2] == ["uv", "--version"]:
            return subprocess.CompletedProcess(command, 0, stdout="uv 0.11.1\n")
        if command[0] != "uv":
            return subprocess.CompletedProcess(command, 0, stdout='[["demo", "demo_extension:install"]]\n')
        if command[1] == "add":
            pyproject_path.write_text(
                original_pyproject.replace("extensions = []", 'extensions = ["deerflow-extension-demo"]'),
                encoding="utf-8",
            )
            lock_path.write_text('version = 1\nrequires-python = ">=3.12"\n', encoding="utf-8")
            return subprocess.CompletedProcess(command, 0)
        syncs.append(list(command))
        raise KeyboardInterrupt

    monkeypatch.setattr("deerflow.extensions.manager.subprocess.run", _run)

    with pytest.raises(KeyboardInterrupt):
        ExtensionManager(root).install(str(source), yes=True)

    assert len(syncs) == 1
    assert not lock_path.exists()
    assert pyproject_path.read_text(encoding="utf-8") == original_pyproject
    assert not (backend / "extensions" / "sources" / "deerflow-extension-demo").exists()


def test_entry_point_discovery_tolerates_interpreter_startup_output(
    tmp_path: Path,
    monkeypatch,
) -> None:
    """A `sitecustomize`/`.pth` banner on the child interpreter's stdout must
    not roll back an otherwise-successful install with a JSON parse error."""
    root = tmp_path / "deer-flow"
    source = tmp_path / "demo-source"
    root.mkdir()
    source.mkdir()
    _write_host_project(root)
    _write_local_extension(source)

    def _run(command, **_kwargs):
        if command[:2] == ["uv", "--version"]:
            return subprocess.CompletedProcess(command, 0, stdout="uv 0.11.1\n")
        if command[0] == "uv":
            if command[1] == "add":
                (root / "backend" / "uv.lock").write_text('version = 1\nrequires-python = ">=3.12"\n', encoding="utf-8")
            return subprocess.CompletedProcess(command, 0)
        return subprocess.CompletedProcess(
            command,
            0,
            stdout='vendor sitecustomize loaded\n[["demo", "demo_extension:install"]]\n',
        )

    monkeypatch.setattr("deerflow.extensions.manager.subprocess.run", _run)

    result = ExtensionManager(root).install(str(source), yes=True)

    assert (result.name, result.use) == ("demo", "demo_extension:install")


def test_install_rejects_uv_versions_without_no_workspace_support(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = tmp_path / "deer-flow"
    source = tmp_path / "demo-source"
    root.mkdir()
    source.mkdir()
    _write_host_project(root)
    _write_local_extension(source)
    commands: list[list[str]] = []

    def _old_uv(command, **_kwargs):
        commands.append(list(command))
        if command[:2] == ["uv", "--version"]:
            return subprocess.CompletedProcess(command, 0, stdout="uv 0.7.20\n")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr("deerflow.extensions.manager.subprocess.run", _old_uv)

    with pytest.raises(RuntimeError, match="uv 0.8.0 or newer"):
        ExtensionManager(root).install(str(source), yes=True)

    assert commands == [["uv", "--version"]]
    assert not (root / "backend" / "extensions").exists()


def test_remove_uses_deferred_uv_mutation_then_the_same_controlled_sync(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = tmp_path / "deer-flow"
    root.mkdir()
    _write_host_project(root)
    (root / "config.yaml").write_text(
        """\
config_version: 1
plugins:
  - name: demo
    package: deerflow-extension-demo
    use: demo_extension:install
    enabled: true
    required: true
    config: {}
""",
        encoding="utf-8",
    )
    for key in ("UV_PROJECT", "UV_WORKING_DIR", "UV_NO_SYNC", "UV_FROZEN", "UV_LOCKED"):
        monkeypatch.setenv(key, "must-not-reach-uv")
    monkeypatch.setenv("UV_DEFAULT_INDEX", "https://packages.example/simple")
    monkeypatch.setenv("HTTP_PROXY", "http://proxy.example:8080")
    uv_calls: list[tuple[list[str], dict[str, object]]] = []

    def _record_run(command, **kwargs):
        if command[0] == "uv":
            uv_calls.append((list(command), kwargs))
            if command[1] == "remove":
                (root / "backend" / "uv.lock").write_text('version = 1\nrequires-python = ">=3.12"\n', encoding="utf-8")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr("deerflow.extensions.manager.subprocess.run", _record_run)

    ExtensionManager(root).remove("demo")

    assert [command[1] for command, _ in uv_calls] == ["remove", "sync"]
    backend = str(root / "backend")
    remove, sync = (uv_calls[0][0], uv_calls[1][0])
    assert ["--project", backend] == remove[remove.index("--project") : remove.index("--project") + 2]
    assert "--no-sync" in remove
    assert remove[-2:] == ["--", "deerflow-extension-demo"]
    assert ["--project", backend] == sync[sync.index("--project") : sync.index("--project") + 2]
    assert "--locked" in sync
    assert "--no-sync" not in sync
    for _, kwargs in uv_calls:
        child_env = kwargs["env"]
        assert isinstance(child_env, dict)
        assert not {
            "UV_PROJECT",
            "UV_WORKING_DIR",
            "UV_NO_SYNC",
            "UV_FROZEN",
            "UV_LOCKED",
        }.intersection(child_env)
        assert child_env["UV_DEFAULT_INDEX"] == "https://packages.example/simple"
        assert child_env["HTTP_PROXY"] == "http://proxy.example:8080"


def test_dependency_sync_uses_the_same_configured_optional_extras_as_startup(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repository_root = Path(__file__).resolve().parents[2]
    config_path = tmp_path / "deployment.yaml"
    config_path.write_text(
        "database:\n  backend: postgres\ntools:\n  - name: browser_navigate\n",
        encoding="utf-8",
    )
    monkeypatch.delenv("UV_EXTRAS", raising=False)
    monkeypatch.delenv("DEER_FLOW_STREAM_BRIDGE_REDIS_URL", raising=False)
    monkeypatch.delenv("DEER_FLOW_SANDBOX_OWNERSHIP_REDIS_URL", raising=False)

    assert _detect_extra_flags(repository_root, config_path) == [
        "--extra",
        "browser",
        "--extra",
        "postgres",
    ]
