"""Runtime path resolution for standalone harness usage."""

import os
from pathlib import Path


def project_root() -> Path:
    """Return the caller project root for runtime-owned files."""
    if env_root := os.getenv("DEER_FLOW_PROJECT_ROOT"):
        return Path(env_root).resolve()
    return Path.cwd().resolve()


def runtime_home() -> Path:
    """Return the writable DeerFlow state directory."""
    if env_home := os.getenv("DEER_FLOW_HOME"):
        return Path(env_home).resolve()
    return project_root() / ".deer-flow"


def resolve_path(value: str | os.PathLike[str], *, base: Path | None = None) -> Path:
    """Resolve absolute paths as-is and relative paths against the project root."""
    path = Path(value)
    if not path.is_absolute():
        path = (base or project_root()) / path
    return path.resolve()


def existing_project_file(names: tuple[str, ...]) -> Path | None:
    """Return the first existing named file under the project root."""
    root = project_root()
    for name in names:
        candidate = root / name
        if candidate.is_file():
            return candidate
    return None
