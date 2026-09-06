"""Shared lifecycle-safe synchronization for inbound channel attachments."""

from __future__ import annotations

from deerflow.sandbox.lease import acquire_sandbox_client_lease


async def sync_file_to_thread_sandbox(
    sandbox_provider,
    *,
    thread_id: str,
    user_id: str,
    virtual_path: str,
    content: bytes,
    owner_prefix: str,
) -> bool:
    """Copy one attachment while holding a non-releasing sandbox client lease.

    Thread-data mount providers already see the persisted upload. Other
    providers need a unique holder so a parallel run cannot close their client
    during ``update_file``. The blocking transport worker is drained even when
    the channel handler is repeatedly cancelled, and only then is the holder
    released.
    """
    if getattr(sandbox_provider, "uses_thread_data_mounts", False):
        return True

    lease = await acquire_sandbox_client_lease(
        sandbox_provider,
        thread_id,
        user_id=user_id,
        owner_prefix=owner_prefix,
        release_on_last=False,
    )
    try:
        if lease.sandbox_id == "local" or lease.sandbox_id.startswith("local:"):
            return True
        if lease.sandbox is None:
            return False
        await lease.run_sync(lease.sandbox.update_file, virtual_path, content)
        return True
    finally:
        await lease.release()
