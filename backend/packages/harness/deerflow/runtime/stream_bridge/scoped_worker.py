"""Producer-only view of the native bridge, bound to an admitted Run.

Enqueue prepared frames under the native short IO fence. This is not an SSE
subscriber authorization or a distributed SQL/Redis transaction. End carries
no result payload and uses original live-owner control authority.
"""

from deerflow.persistence.workspaces.sql import WorkspaceAccessDenied
from deerflow.runtime.stream_bridge.base import StreamBridge


class ScopedWorkerBridge(StreamBridge):
    def __init__(self, inner, repository, target):
        super().__init__(heartbeat_interval=inner.heartbeat_interval)
        self._inner = inner
        self._repository = repository
        self._target = target
        self.supports_cross_process = inner.supports_cross_process

    def _run(self, run_id):
        if run_id != self._target.run_id:
            raise WorkspaceAccessDenied("stream producer differs from captured native Run")

    async def publish(self, run_id, event, data):
        self._run(run_id)
        await self._repository.commit_worker_io(self._target, commit=lambda: self._inner.publish(run_id, event, data))

    async def publish_end(self, run_id):
        self._run(run_id)
        # Refused old owners cannot end a successor's lane. No payload is
        # granted by original-owner cleanup after member withdrawal.
        await self._repository.signal_worker_stream_end(self._target, signal=lambda: self._inner.publish_end(run_id))

    def subscribe(self, run_id, *, last_event_id=None, heartbeat_interval=None):
        raise WorkspaceAccessDenied("worker producer does not grant subscription authority")

    async def cleanup(self, run_id, *, delay=0):
        raise WorkspaceAccessDenied("worker producer does not grant bridge deletion authority")
