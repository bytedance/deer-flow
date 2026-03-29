"""Security helpers for sandbox capability gating."""

from deerflow.config import get_app_config

_LOCAL_SANDBOX_PROVIDER_MARKERS = (
    "deerflow.sandbox.local:LocalSandboxProvider",
    "deerflow.sandbox.local.local_sandbox_provider:LocalSandboxProvider",
)

LOCAL_HOST_BASH_DISABLED_MESSAGE = (
    "Host bash execution is disabled for LocalSandboxProvider because it is not a secure "
    "sandbox boundary. Switch to AioSandboxProvider for isolated bash access, or set "
    "sandbox.allow_host_bash: true only in a fully trusted local environment."
)

LOCAL_BASH_SUBAGENT_DISABLED_MESSAGE = (
    "Bash subagent is disabled for LocalSandboxProvider because host bash execution is not "
    "a secure sandbox boundary. Switch to AioSandboxProvider for isolated bash access, or "
    "set sandbox.allow_host_bash: true only in a fully trusted local environment."
)


def uses_local_sandbox_provider(config=None) -> bool:
    """Return True when the active sandbox provider is the host-local provider."""
    if config is None:
        config = get_app_config()

    sandbox_cfg = getattr(config, "sandbox", None)
    sandbox_use = getattr(sandbox_cfg, "use", "")
    if sandbox_use in _LOCAL_SANDBOX_PROVIDER_MARKERS:
        return True
    return sandbox_use.endswith(":LocalSandboxProvider") and "deerflow.sandbox.local" in sandbox_use


def is_host_bash_allowed(config=None) -> bool:
    """Return whether host bash execution is explicitly allowed."""
    if config is None:
        config = get_app_config()

    sandbox_cfg = getattr(config, "sandbox", None)
    if sandbox_cfg is None:
        return True
    if not uses_local_sandbox_provider(config):
        return True
    return bool(getattr(sandbox_cfg, "allow_host_bash", False))
