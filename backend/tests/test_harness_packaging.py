from __future__ import annotations

import tomllib
from pathlib import Path


def test_boxlite_is_optional_harness_dependency() -> None:
    """BoxLite should not make core harness installs platform-dependent."""
    pyproject_path = Path(__file__).resolve().parents[1] / "packages" / "harness" / "pyproject.toml"
    pyproject = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))

    core_dependencies = pyproject["project"]["dependencies"]
    optional_dependencies = pyproject["project"]["optional-dependencies"]

    assert not any(dep.startswith("boxlite") for dep in core_dependencies)
    assert any(dep.startswith("boxlite>=0.9.7") for dep in optional_dependencies["boxlite"])


def test_opensandbox_is_optional_harness_dependency() -> None:
    """OpenSandbox should be installed only when its provider is selected."""
    pyproject_path = Path(__file__).resolve().parents[1] / "packages" / "harness" / "pyproject.toml"
    pyproject = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))

    core_dependencies = pyproject["project"]["dependencies"]
    optional_dependencies = pyproject["project"]["optional-dependencies"]

    assert not any(dep.startswith("opensandbox") for dep in core_dependencies)
    assert optional_dependencies["opensandbox"] == ["opensandbox>=1.1.0,<2.0.0"]


def test_boxd_is_optional_harness_dependency() -> None:
    """The boxd SDK should be installed only when its provider is selected."""
    pyproject_path = Path(__file__).resolve().parents[1] / "packages" / "harness" / "pyproject.toml"
    pyproject = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))

    core_dependencies = pyproject["project"]["dependencies"]
    optional_dependencies = pyproject["project"]["optional-dependencies"]

    assert not any(dep.startswith("boxd") for dep in core_dependencies)
    assert optional_dependencies["boxd"] == ["boxd>=0.3.2"]
