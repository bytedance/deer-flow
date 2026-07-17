"""Tenki cloud sandbox provider for DeerFlow.

Integrates `Tenki <https://tenki.cloud>`_ cloud sandboxes behind DeerFlow's
:class:`Sandbox` / :class:`SandboxProvider` contract. Each sandbox is an
isolated cloud microVM created from a stock base image; the full contract is
implemented — ``execute_command`` plus ``read_file`` / ``write_file`` /
``update_file`` / ``download_file`` / ``list_dir`` / ``glob`` / ``grep`` (file
ops run as shell commands inside the sandbox).

Configuration example (``config.yaml``)::

    sandbox:
      use: deerflow.community.tenki:TenkiSandboxProvider
      # Tenki-specific options (read via SandboxConfig's ``extra="allow"``):
      api_key: $TENKI_API_KEY          # falls back to TENKI_API_KEY / TENKI_AUTH_TOKEN env var
      base_url: https://tenki.cloud    # optional; SDK default when omitted
      image: my-base-image             # optional; Tenki account default base image when omitted
      project_id: proj_...             # optional; auto-selected if the account has exactly one
      workspace_id: ws_...             # optional; auto-selected if the account has exactly one
      cpu_cores: 2                     # optional per-sandbox vCPUs
      memory_mb: 2048                  # optional per-sandbox memory
      replicas: 3                      # active + warm microVM cap per gateway process
      idle_timeout: 600                # warm microVM idle seconds before terminate; 0 disables
      environment:                     # injected into every command (and as create-time env)
        PYTHONUNBUFFERED: "1"

Install the optional SDK before selecting this provider::

    pip install "deerflow-harness[tenki]"

Only the stable Tenki surface is used — sandbox create/terminate plus
exec/shell/filesystem. Volumes, snapshots, and template builds are intentionally
not used, so no prebaked image or unstable Tenki feature is required.
"""

from .provider import TenkiSandboxProvider
from .sandbox import TenkiSandbox

__all__ = [
    "TenkiSandbox",
    "TenkiSandboxProvider",
]
