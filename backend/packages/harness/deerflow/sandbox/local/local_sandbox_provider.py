import logging
from pathlib import Path

from deerflow.sandbox.local.local_sandbox import LocalSandbox, PathMapping
from deerflow.sandbox.sandbox import Sandbox
from deerflow.sandbox.sandbox_provider import SandboxProvider

logger = logging.getLogger(__name__)

# Module-level alias kept for backward compatibility with older callers/tests
# that reach into ``local_sandbox_provider._singleton`` directly. New code reads
# the provider instance attributes (``_generic_sandbox`` / ``_thread_sandboxes``)
# instead.
_singleton: LocalSandbox | None = None

# Virtual prefixes that must be reserved by the per-thread mappings created in
# ``acquire`` — custom mounts from ``config.yaml`` may not overlap with these.
_USER_DATA_VIRTUAL_PREFIX = "/mnt/user-data"
_ACP_WORKSPACE_VIRTUAL_PREFIX = "/mnt/acp-workspace"


class LocalSandboxProvider(SandboxProvider):
    """Local-filesystem sandbox provider with per-thread path scoping.

    Earlier revisions of this provider returned a single process-wide
    ``LocalSandbox`` keyed by the literal id ``"local"``. That singleton could
    not honour the documented ``/mnt/user-data/...`` contract at the public
    ``Sandbox`` API boundary because the corresponding host directory is
    per-thread (``{base_dir}/users/{user_id}/threads/{thread_id}/user-data/``).

    The provider now produces a fresh ``LocalSandbox`` per ``thread_id`` whose
    ``path_mappings`` include thread-scoped entries for
    ``/mnt/user-data/{workspace,uploads,outputs}`` and ``/mnt/acp-workspace``,
    mirroring how :class:`AioSandboxProvider` bind-mounts those paths into its
    docker container. The legacy ``acquire()`` / ``acquire(None)`` call still
    returns a generic singleton with id ``"local"`` for callers (and tests)
    that do not have a thread context.
    """

    uses_thread_data_mounts = True

    def __init__(self):
        """Initialize the local sandbox provider with static path mappings."""
        self._path_mappings = self._setup_path_mappings()
        self._generic_sandbox: LocalSandbox | None = None
        self._thread_sandboxes: dict[str, LocalSandbox] = {}

    def _setup_path_mappings(self) -> list[PathMapping]:
        """
        Setup static path mappings shared by every sandbox this provider yields.

        Static mappings cover the skills directory and any custom mounts from
        ``config.yaml`` — both are process-wide and identical for every thread.
        Per-thread ``/mnt/user-data/...`` and ``/mnt/acp-workspace`` mappings
        are appended inside :meth:`acquire` because they depend on
        ``thread_id`` and the effective ``user_id``.

        Returns:
            List of static path mappings
        """
        mappings: list[PathMapping] = []

        # Map skills container path to local skills directory
        try:
            from deerflow.config import get_app_config

            config = get_app_config()
            skills_path = config.skills.get_skills_path()
            container_path = config.skills.container_path

            # Only add mapping if skills directory exists
            if skills_path.exists():
                mappings.append(
                    PathMapping(
                        container_path=container_path,
                        local_path=str(skills_path),
                        read_only=True,  # Skills directory is always read-only
                    )
                )

            # Map custom mounts from sandbox config
            _RESERVED_CONTAINER_PREFIXES = [
                container_path,
                _ACP_WORKSPACE_VIRTUAL_PREFIX,
                _USER_DATA_VIRTUAL_PREFIX,
            ]
            sandbox_config = config.sandbox
            if sandbox_config and sandbox_config.mounts:
                for mount in sandbox_config.mounts:
                    host_path = Path(mount.host_path)
                    container_path = mount.container_path.rstrip("/") or "/"

                    if not host_path.is_absolute():
                        logger.warning(
                            "Mount host_path must be absolute, skipping: %s -> %s",
                            mount.host_path,
                            mount.container_path,
                        )
                        continue

                    if not container_path.startswith("/"):
                        logger.warning(
                            "Mount container_path must be absolute, skipping: %s -> %s",
                            mount.host_path,
                            mount.container_path,
                        )
                        continue

                    # Reject mounts that conflict with reserved container paths
                    if any(container_path == p or container_path.startswith(p + "/") for p in _RESERVED_CONTAINER_PREFIXES):
                        logger.warning(
                            "Mount container_path conflicts with reserved prefix, skipping: %s",
                            mount.container_path,
                        )
                        continue
                    # Ensure the host path exists before adding mapping
                    if host_path.exists():
                        mappings.append(
                            PathMapping(
                                container_path=container_path,
                                local_path=str(host_path.resolve()),
                                read_only=mount.read_only,
                            )
                        )
                    else:
                        logger.warning(
                            "Mount host_path does not exist, skipping: %s -> %s",
                            mount.host_path,
                            mount.container_path,
                        )
        except Exception as e:
            # Log but don't fail if config loading fails
            logger.warning("Could not setup path mappings: %s", e, exc_info=True)

        return mappings

    @staticmethod
    def _build_thread_path_mappings(thread_id: str) -> list[PathMapping]:
        """Build per-thread path mappings for /mnt/user-data and /mnt/acp-workspace.

        Resolves ``user_id`` via :func:`get_effective_user_id` (the same path
        :class:`AioSandboxProvider` uses) and ensures the backing host
        directories exist before they are mapped into the sandbox view.
        """
        from deerflow.config.paths import get_paths
        from deerflow.runtime.user_context import get_effective_user_id

        paths = get_paths()
        user_id = get_effective_user_id()
        paths.ensure_thread_dirs(thread_id, user_id=user_id)

        return [
            # Aggregate parent mapping so ``ls /mnt/user-data`` and other
            # parent-level operations behave the same as inside AIO (where the
            # parent directory is real and contains the three subdirs). Longer
            # subpath mappings below still win for ``/mnt/user-data/workspace/...``
            # because ``_find_path_mapping`` sorts by container_path length.
            PathMapping(
                container_path=_USER_DATA_VIRTUAL_PREFIX,
                local_path=str(paths.sandbox_user_data_dir(thread_id, user_id=user_id)),
                read_only=False,
            ),
            PathMapping(
                container_path=f"{_USER_DATA_VIRTUAL_PREFIX}/workspace",
                local_path=str(paths.sandbox_work_dir(thread_id, user_id=user_id)),
                read_only=False,
            ),
            PathMapping(
                container_path=f"{_USER_DATA_VIRTUAL_PREFIX}/uploads",
                local_path=str(paths.sandbox_uploads_dir(thread_id, user_id=user_id)),
                read_only=False,
            ),
            PathMapping(
                container_path=f"{_USER_DATA_VIRTUAL_PREFIX}/outputs",
                local_path=str(paths.sandbox_outputs_dir(thread_id, user_id=user_id)),
                read_only=False,
            ),
            PathMapping(
                container_path=_ACP_WORKSPACE_VIRTUAL_PREFIX,
                local_path=str(paths.acp_workspace_dir(thread_id, user_id=user_id)),
                read_only=False,
            ),
        ]

    def acquire(self, thread_id: str | None = None) -> str:
        """Return a sandbox id scoped to *thread_id* (or the generic singleton).

        - ``thread_id=None`` keeps the legacy singleton with id ``"local"`` for
          callers that have no thread context (e.g. legacy tests, scripts).
        - ``thread_id="abc"`` yields a per-thread ``LocalSandbox`` with id
          ``"local:abc"`` whose ``path_mappings`` resolve ``/mnt/user-data/...``
          to that thread's host directories.
        """
        global _singleton

        if thread_id is None:
            if self._generic_sandbox is None:
                self._generic_sandbox = LocalSandbox("local", path_mappings=list(self._path_mappings))
                _singleton = self._generic_sandbox
            return self._generic_sandbox.id

        cached = self._thread_sandboxes.get(thread_id)
        if cached is None:
            mappings = list(self._path_mappings) + self._build_thread_path_mappings(thread_id)
            cached = LocalSandbox(f"local:{thread_id}", path_mappings=mappings)
            self._thread_sandboxes[thread_id] = cached
        return cached.id

    def get(self, sandbox_id: str) -> Sandbox | None:
        if sandbox_id == "local":
            if self._generic_sandbox is None:
                self.acquire()
            return self._generic_sandbox
        if isinstance(sandbox_id, str) and sandbox_id.startswith("local:"):
            return self._thread_sandboxes.get(sandbox_id[len("local:") :])
        return None

    def release(self, sandbox_id: str) -> None:
        # LocalSandbox has no resources to release; keep the cached instance so
        # that ``_agent_written_paths`` (used to reverse-resolve agent-authored
        # file contents on read) survives between turns. Cache eviction happens
        # in ``reset()`` / ``shutdown()``.
        #
        # Note: This method is intentionally not called by SandboxMiddleware
        # to allow sandbox reuse across multiple turns in a thread.
        pass

    def reset(self) -> None:
        """Drop all cached LocalSandbox instances.

        ``reset_sandbox_provider()`` calls this to ensure config / mount
        changes take effect on the next ``acquire()``. We also reset the
        module-level ``_singleton`` alias so older callers/tests that reach
        into it see a fresh state.
        """
        global _singleton
        self._generic_sandbox = None
        self._thread_sandboxes.clear()
        _singleton = None

    def shutdown(self) -> None:
        # LocalSandboxProvider has no extra resources beyond the cached
        # ``LocalSandbox`` instances, so shutdown uses the same cleanup path
        # as ``reset``.
        self.reset()
