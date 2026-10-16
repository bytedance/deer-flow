"""Forward (container→host) resolution must translate every entry of a ``:``-joined list.

The reverse (host→virtual) direction already ends its tail at ``:`` — see
``path_patterns._PATH_TAIL`` — because a tail that ran through a ``:``-joined
list ($PATH, $PYTHONPATH, LD_LIBRARY_PATH) swallowed every later entry under
the same base into one match, and scanning only resumes *after* a match.

The forward direction had the same defect in three copies of the tail:
``LocalSandbox._content_pattern``, ``LocalSandbox._command_pattern`` and
``replace_virtual_paths_in_command``. One match starting at the first virtual
path consumed the ``:`` and the whole rest of the list, so ``pattern.sub``
never rescanned the later entries and
``write_file("/mnt/user-data/workspace/env.sh", 'export PATH="/mnt/user-data/workspace/bin:/mnt/user-data/outputs/bin"')``
persisted ``export PATH="<host_ws>/bin:/mnt/user-data/outputs/bin"`` — a
dangling virtual entry that anything later consuming the file inherits.
``read_file`` masks the mixed line back to the original virtual text, so the
corruption is invisible to the model.
"""

from __future__ import annotations

from pathlib import Path

from deerflow.sandbox.local.local_sandbox import LocalSandbox, PathMapping
from deerflow.sandbox.tools import replace_virtual_paths_in_command

_COLON_LIST_COMMAND = 'export PATH="/mnt/user-data/workspace/bin:/mnt/user-data/outputs/bin"'


def _sandbox_with_workspace_and_outputs(tmp_path: Path) -> LocalSandbox:
    ws = tmp_path / "ws"
    out = tmp_path / "out"
    ws.mkdir()
    out.mkdir()
    return LocalSandbox(
        id="local:colon-list",
        path_mappings=[
            PathMapping(container_path="/mnt/user-data/workspace", local_path=str(ws)),
            PathMapping(container_path="/mnt/user-data/outputs", local_path=str(out)),
        ],
    )


def test_write_file_resolves_every_entry_of_a_colon_joined_list(tmp_path: Path) -> None:
    """``write_file`` must not persist a dangling virtual entry in a PATH-style list."""
    sbx = _sandbox_with_workspace_and_outputs(tmp_path)

    sbx.write_file("/mnt/user-data/workspace/env.sh", _COLON_LIST_COMMAND + "\n")

    written = (tmp_path / "ws" / "env.sh").read_text(encoding="utf-8")
    assert "/mnt/user-data" not in written, f"colon-joined list: write_file left a virtual entry unresolved; host file: {written!r}"


def test_command_resolution_translates_every_entry_of_a_colon_joined_list(tmp_path: Path) -> None:
    """``_resolve_paths_in_command`` must resume at each entry, not swallow the list."""
    sbx = _sandbox_with_workspace_and_outputs(tmp_path)

    resolved = sbx._resolve_paths_in_command(_COLON_LIST_COMMAND)

    assert "/mnt/user-data" not in resolved, f"colon-joined list: _resolve_paths_in_command left a virtual entry unresolved: {resolved!r}"


def test_user_data_command_resolution_translates_every_entry_of_a_colon_joined_list(tmp_path: Path) -> None:
    """``replace_virtual_paths_in_command`` pre-resolves user-data paths the same way."""
    ws_local = str(tmp_path / "ws").replace("\\", "/")
    out_local = str(tmp_path / "out").replace("\\", "/")
    thread_data = {
        "workspace_path": str(tmp_path / "ws"),
        "uploads_path": str(tmp_path / "uploads"),
        "outputs_path": str(tmp_path / "out"),
    }

    replaced = replace_virtual_paths_in_command(_COLON_LIST_COMMAND, thread_data)

    assert replaced == f'export PATH="{ws_local}/bin:{out_local}/bin"', f"colon-joined list: replace_virtual_paths_in_command left a virtual entry unresolved: {replaced!r}"


def test_single_path_list_entry_keeps_its_dollar_path_suffix(tmp_path: Path) -> None:
    """The single-entry PATH-style form must keep translating.

    ``export PATH="<venv>/bin:$PATH"`` is the common shape: the ``:$PATH``
    suffix rides along after the resolved entry and still expands in bash, so
    ending the tail at ``:`` must not stop the entry itself from resolving.
    """
    sbx = _sandbox_with_workspace_and_outputs(tmp_path)
    ws_local = str((tmp_path / "ws").resolve()).replace("\\", "/")

    resolved = sbx._resolve_paths_in_content('export PATH="/mnt/user-data/workspace/venv/bin:$PATH"\n')

    assert resolved == f'export PATH="{ws_local}/venv/bin:$PATH"\n'
