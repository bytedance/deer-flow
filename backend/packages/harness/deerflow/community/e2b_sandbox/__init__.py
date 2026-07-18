"""E2B cloud sandbox provider for DeerFlow.

This package implements DeerFlow's :class:`Sandbox` / :class:`SandboxProvider`
contract on top of the `e2b` / `e2b_code_interpreter` cloud sandbox SDK.

Configuration example (``config.yaml``)::

    sandbox:
      use: deerflow.community.e2b_sandbox:E2BSandboxProvider
      # E2B specific options (read via SandboxConfig's ``extra="allow"``):
      api_key: $E2B_API_KEY            # falls back to E2B_API_KEY env var
      template: code-interpreter-v1     # e2b template id; defaults to e2b code-interpreter
      domain: e2b.dev                  # optional e2b domain (e.g. self-hosted)
      idle_timeout: 600                # forwarded to e2b ``set_timeout`` (seconds)
      replicas: 3                      # max concurrent sandboxes (LRU eviction beyond)
      mounts:                          # one-shot upload of host files into the sandbox
        - host_path: /path/on/host
          container_path: /path/in/sandbox
          read_only: false
      environment:                      # forwarded as e2b ``envs`` on create
        OPENAI_API_KEY: $OPENAI_API_KEY
"""

from .e2b_sandbox import E2BSandbox
from .e2b_sandbox_provider import E2BSandboxProvider

__all__ = [
    "E2BSandbox",
    "E2BSandboxProvider",
]
