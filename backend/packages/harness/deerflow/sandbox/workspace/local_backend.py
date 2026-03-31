"""LocalWorkspaceBackend — uses the local filesystem as the persistent workspace store.

Workspace path: {base_dir}/depts/{dept_id}/users/{user_id}/agents/{agent_name}/workspace/
For legacy (no identity): {base_dir}/agents/{agent_name}/workspace/
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import TYPE_CHECKING

from deerflow.sandbox.workspace import WorkspaceBackend

if TYPE_CHECKING:
    from deerflow.identity.agent_identity import AgentIdentity


class LocalWorkspaceBackend(WorkspaceBackend):
    """Filesystem-based persistent workspace.

    sync_down copies persistent → thread-local.
    sync_up copies thread-local → persistent (overwrite).
    """

    async def sync_down(self, identity: "AgentIdentity", local_dir: Path) -> None:
        """Copy persistent workspace to *local_dir* (no-op if workspace doesn't exist yet)."""
        from deerflow.config.paths import get_paths

        workspace = get_paths().identity_workspace_dir(identity)
        if workspace is None or not workspace.exists():
            return

        local_dir.mkdir(parents=True, exist_ok=True)
        _copy_tree(workspace, local_dir)

    async def sync_up(self, identity: "AgentIdentity", local_dir: Path) -> None:
        """Copy *local_dir* back to persistent workspace."""
        from deerflow.config.paths import get_paths

        workspace = get_paths().identity_workspace_dir(identity)
        if workspace is None:
            return

        workspace.mkdir(parents=True, exist_ok=True)
        _copy_tree(local_dir, workspace)


def _copy_tree(src: Path, dst: Path) -> None:
    """Recursively copy *src* → *dst*, overwriting existing files."""
    if not src.exists():
        return
    dst.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        dest_item = dst / item.name
        if item.is_dir():
            _copy_tree(item, dest_item)
        else:
            shutil.copy2(item, dest_item)
