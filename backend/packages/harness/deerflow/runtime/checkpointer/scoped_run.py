"""Per-run native saver adapter with captured live SQL execution fencing.

This wraps only checkpoint IO. It neither executes a graph nor adds a second
checkpoint authority. Unsupported sync/destructive operations fail closed;
ordinary rollback needs a separate authorized control protocol.
"""

from langgraph.checkpoint.base import BaseCheckpointSaver

from deerflow.persistence.workspaces.run_control import NativeRunStopTarget
from deerflow.persistence.workspaces.sql import WorkspaceAccessDenied


class ScopedRunSaver(BaseCheckpointSaver):
    def __init__(self, inner, repository, target: NativeRunStopTarget):
        self.serde = inner.serde
        self._inner = inner
        self._repository = repository
        self._target = target

    @property
    def config_specs(self):
        return self._inner.config_specs

    def get_next_version(self, current, channel):
        return self._inner.get_next_version(current, channel)

    def _config(self, config):
        if not isinstance(config, dict) or config.get("configurable", {}).get("thread_id") != self._target.thread_id:
            raise WorkspaceAccessDenied("checkpoint thread differs from captured Run")

    async def _io(self, config, commit):
        self._config(config)
        return await self._repository.commit_worker_checkpoint(self._target, commit=commit)

    async def aget_tuple(self, config):
        return await self._io(config, lambda: self._inner.aget_tuple(config))

    async def aput(self, config, checkpoint, metadata, new_versions):
        return await self._io(config, lambda: self._inner.aput(config, checkpoint, metadata, new_versions))

    async def aput_writes(self, config, writes, task_id, task_path=""):
        return await self._io(config, lambda: self._inner.aput_writes(config, writes, task_id, task_path))

    async def alist(self, config, *, filter=None, before=None, limit=None):
        if before is not None:
            self._config(before)

        self._config(config)
        iterator = self._inner.alist(config, filter=filter, before=before, limit=limit)
        end = object()
        try:
            while True:
                item = await self._io(config, lambda: anext(iterator, end))
                if item is end:
                    break
                yield item
        finally:
            await iterator.aclose()

    async def aget_delta_channel_history(self, *, config, channels):
        return await self._io(config, lambda: self._inner.aget_delta_channel_history(config=config, channels=channels))

    async def adelete_thread(self, thread_id):
        raise WorkspaceAccessDenied("worker checkpoint deletion requires explicit control authority")

    async def adelete_for_runs(self, run_ids):
        raise WorkspaceAccessDenied("worker checkpoint deletion requires explicit control authority")

    async def acopy_thread(self, source_thread_id, target_thread_id):
        raise WorkspaceAccessDenied("worker cannot copy checkpoint authority to another thread")

    async def aprune(self, thread_ids, *, strategy="keep_latest"):
        raise WorkspaceAccessDenied("worker cannot prune private checkpoint history")
