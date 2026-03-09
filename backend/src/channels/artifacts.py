"""Helpers for resolving channel-sendable agent artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from src.config.paths import VIRTUAL_PATH_PREFIX, get_paths

OUTPUTS_VIRTUAL_PREFIX = f"{VIRTUAL_PATH_PREFIX}/outputs"


@dataclass(frozen=True)
class ResolvedArtifact:
    """A validated artifact ready to be uploaded by a channel."""

    virtual_path: str
    file_path: Path
    file_name: str


def _is_outputs_virtual_path(virtual_path: str) -> bool:
    stripped = virtual_path.lstrip("/")
    prefix = OUTPUTS_VIRTUAL_PREFIX.lstrip("/")
    return stripped == prefix or stripped.startswith(prefix + "/")


def resolve_channel_artifact(thread_id: str, virtual_path: str) -> ResolvedArtifact:
    """Resolve a channel artifact path to a concrete file under thread outputs.

    Only files under ``/mnt/user-data/outputs/*`` for the current thread are
    accepted. Non-file paths, missing files, and traversals are rejected.
    """

    if not thread_id:
        raise ValueError("thread_id is required to resolve channel artifacts")

    if not _is_outputs_virtual_path(virtual_path):
        raise ValueError(f"Artifact path must stay under {OUTPUTS_VIRTUAL_PREFIX}")

    paths = get_paths()
    actual_path = paths.resolve_virtual_path(thread_id, virtual_path)
    outputs_dir = paths.sandbox_outputs_dir(thread_id).resolve()

    try:
        actual_path.relative_to(outputs_dir)
    except ValueError as exc:
        raise ValueError(f"Artifact path must stay under {OUTPUTS_VIRTUAL_PREFIX}") from exc

    if not actual_path.exists():
        raise FileNotFoundError(f"Artifact file does not exist: {virtual_path}")

    if not actual_path.is_file():
        raise ValueError(f"Artifact path must point to a file: {virtual_path}")

    return ResolvedArtifact(
        virtual_path=virtual_path,
        file_path=actual_path,
        file_name=actual_path.name,
    )
