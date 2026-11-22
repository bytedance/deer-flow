"""boxd machine sandbox provider for DeerFlow.

This package implements DeerFlow's :class:`Sandbox` / :class:`SandboxProvider`
contract on top of `boxd <https://boxd.sh?ref=deer-flow>`_ machines through the
``boxd`` Python SDK. Each sandbox is an isolated Ubuntu microVM.

Configuration example (``config.yaml``)::

    sandbox:
      use: deerflow.community.boxd_sandbox:BoxdSandboxProvider
      # boxd specific options (read via SandboxConfig's ``extra="allow"``):
      boxd_api_key: $BOXD_API_KEY      # falls back to the BOXD_API_KEY env var
      # org: my-org                    # optional; the key's own org when omitted
      # region: fra                    # optional; fra or nyc
      # vcpu: 2                        # optional; 1, 2, 4 or 8 (memory follows: 4G, 8G, 16G, 32G)
      # from_snapshot: my-snapshot     # optional; start machines from a prepared snapshot
      # auto_suspend_timeout: 300      # optional; idle seconds before a machine goes to standby
      # ready_timeout: 120             # seconds to wait for a new machine to boot
      # name_prefix: deer-flow-        # machine names: <prefix><scope>-<suffix>
      # labels:                        # extra machine labels
      #   team: research
      replicas: 3                      # active + warm machine cap per Gateway process
      idle_timeout: 600                # warm seconds before the machine is deleted; 0 disables
      environment:                     # merged into every command's environment
        PYTHONUNBUFFERED: "1"

Install the optional SDK before selecting this provider::

    pip install "deerflow-harness[boxd]"
"""

from .boxd_sandbox import BoxdSandbox
from .boxd_sandbox_provider import BoxdSandboxProvider

__all__ = [
    "BoxdSandbox",
    "BoxdSandboxProvider",
]
