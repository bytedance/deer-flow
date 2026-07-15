from __future__ import annotations

import shutil
from collections.abc import Iterable
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from deerflow.evaluation.schema import WorkspaceSeed


class WorkspaceSeedError(ValueError):
    """Raised when a workspace seed cannot be materialized."""


class WorkspaceRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    suite_name: str
    suite_item_id: str
    sample_index: int
    variant_id: str | None
    workspace_path: str
    seed_source: str | None = None
    seeded_files: list[str] = Field(default_factory=list)


def materialize_workspace_seed(
    seed: WorkspaceSeed | None,
    *,
    suite_path: str | Path,
    workspaces_root: str | Path,
    suite_name: str,
    suite_item_id: str,
    sample_index: int,
    variant_id: str | None,
    clean: bool = True,
) -> WorkspaceRef:
    """Create an isolated item/sample/variant workspace and apply a local fixture seed."""

    workspace_path = workspace_path_for(
        workspaces_root=workspaces_root,
        suite_name=suite_name,
        suite_item_id=suite_item_id,
        sample_index=sample_index,
        variant_id=variant_id,
    )
    if clean and workspace_path.exists():
        shutil.rmtree(workspace_path)
    workspace_path.mkdir(parents=True, exist_ok=True)

    seeded_files: list[str] = []
    seed_source: str | None = None
    if seed is not None:
        source = resolve_fixture_path(seed.path, suite_path=suite_path)
        seed_source = str(source)
        _copy_seed_source(source, workspace_path)
        seeded_files = list(_list_workspace_files(workspace_path))

    return WorkspaceRef(
        suite_name=suite_name,
        suite_item_id=suite_item_id,
        sample_index=sample_index,
        variant_id=variant_id,
        workspace_path=str(workspace_path),
        seed_source=seed_source,
        seeded_files=seeded_files,
    )


def workspace_path_for(
    *,
    workspaces_root: str | Path,
    suite_name: str,
    suite_item_id: str,
    sample_index: int,
    variant_id: str | None,
) -> Path:
    if sample_index < 0:
        raise WorkspaceSeedError("sample_index must be >= 0")
    return (Path(workspaces_root) / _safe_segment(suite_name) / _safe_segment(suite_item_id) / f"sample-{sample_index}" / _safe_segment(variant_id or "default") / "workspace").resolve()


def resolve_fixture_path(path: str, *, suite_path: str | Path) -> Path:
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = Path(suite_path).expanduser().resolve().parent / candidate
    candidate = candidate.resolve()
    if not candidate.exists():
        raise WorkspaceSeedError(f"workspace fixture does not exist: {candidate}")
    return candidate


def _copy_seed_source(source: Path, destination: Path) -> None:
    if _same_or_child(destination, source):
        raise WorkspaceSeedError("workspace destination must not be inside the fixture source")
    if source.is_dir():
        for child in source.iterdir():
            target = destination / child.name
            if child.is_dir():
                shutil.copytree(child, target, dirs_exist_ok=True)
            else:
                shutil.copy2(child, target)
        return
    if source.is_file():
        shutil.copy2(source, destination / source.name)
        return
    raise WorkspaceSeedError(f"workspace fixture must be a file or directory: {source}")


def _list_workspace_files(workspace_path: Path) -> Iterable[str]:
    for path in sorted(workspace_path.rglob("*")):
        if path.is_file():
            yield path.relative_to(workspace_path).as_posix()


def _same_or_child(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _safe_segment(value: str) -> str:
    cleaned = "".join(char if char.isalnum() or char in "._-" else "-" for char in value)
    return cleaned.strip(".-") or "unnamed"
