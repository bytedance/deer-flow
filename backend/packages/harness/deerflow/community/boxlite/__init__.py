"""BoxLite micro-VM backend for DeerFlow sandboxes.

Integrates `BoxLite <https://github.com/boxlite-ai/boxlite>`_ — a daemonless,
OCI-native micro-VM runtime (libkrun/KVM on Linux, Hypervisor.framework on
macOS) — behind DeerFlow's :class:`Sandbox` / :class:`SandboxProvider` contract.
Each sandbox is a hardware-isolated VM with its own kernel that runs any OCI
image unchanged. See https://github.com/bytedance/deer-flow/issues/3936.

The full contract is implemented: ``execute_command`` plus ``read_file`` /
``write_file`` / ``update_file`` / ``download_file`` / ``list_dir`` / ``glob`` /
``grep`` (file ops run as shell commands inside the box).

Configuration example (``config.yaml``)::

    sandbox:
      use: deerflow.community.boxlite:BoxliteProvider
      image: python:3.12-slim      # any OCI image; runs unchanged
      memory_mib: 1024             # per-box memory cap (optional)
      cpus: 2                      # per-box vCPUs (optional)
      replicas: 3                  # active + warm VM cap per gateway process
      idle_timeout: 600            # warm VM idle seconds before stop; 0 disables
      environment:                 # injected into every command
        PYTHONUNBUFFERED: "1"

Install the optional runtime before selecting this provider::

    pip install "deerflow-harness[boxlite]"

Host requirement: BoxLite boots micro-VMs, so a Linux host needs KVM (nested
virtualization when DeerFlow itself runs inside a cloud VM); macOS uses
Hypervisor.framework.
"""

from .box import BoxliteBox
from .provider import BoxliteProvider

__all__ = [
    "BoxliteBox",
    "BoxliteProvider",
]
