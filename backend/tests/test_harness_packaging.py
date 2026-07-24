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
