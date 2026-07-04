"""BoxLite micro-VM sandbox provider for DeerFlow.

This package implements DeerFlow's :class:`Sandbox` / :class:`SandboxProvider`
contract on top of `BoxLite <https://github.com/boxlite-ai/boxlite>`_ — a
daemonless, OCI-native micro-VM runtime (libkrun/KVM on Linux,
Hypervisor.framework on macOS). Each sandbox is a hardware-isolated VM with its
own kernel that runs any OCI image unchanged.

STATUS — scaffold / request-for-comments (see
https://github.com/bytedance/deer-flow/issues/3936). ``execute_command`` (the
bash path) is wired end to end; the remaining ``Sandbox`` methods are stubbed
pending agreement on approach, host requirements, and in-tree vs. external
packaging. Not yet benchmarked against the AIO sandbox.

Configuration example (``config.yaml``)::

    sandbox:
      use: deerflow.community.boxlite_sandbox:BoxliteSandboxProvider
      image: python:3.12-slim      # any OCI image; runs unchanged
      memory_mib: 1024             # per-box memory cap (optional)
      cpus: 2                      # per-box vCPUs (optional)
      environment:                 # injected into every command
        PYTHONUNBUFFERED: "1"

Install the runtime (an optional ``[boxlite]`` extra + lockfile update will
follow once the approach lands)::

    pip install boxlite

Host requirement: BoxLite boots micro-VMs, so a Linux host needs KVM (nested
virtualization when DeerFlow itself runs inside a cloud VM); macOS uses
Hypervisor.framework.
"""

from .boxlite_provider import BoxliteSandboxProvider
from .boxlite_sandbox import BoxliteSandbox

__all__ = [
    "BoxliteSandbox",
    "BoxliteSandboxProvider",
]
