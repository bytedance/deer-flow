"""Execution-local physical receipts, not a replacement for native authority.

The receiver binds a SQL-adopted Run before its task inherits this observer.
Receipts are private objects, never reconstructed from transport/checkpoints.
A crashed or unobserved acquisition remains unknown and retains its reservation.
"""

import threading
from copy import deepcopy
from dataclasses import asdict


class NativeSandboxCapture:
    def __init__(self, job):
        self.assignment = tuple(job.get(key) for key in ("id", "node_id", "worker_owner", "generation"))
        self.native = deepcopy(job["native"])
        self.record = None
        self._lock = threading.RLock()
        self._handles = {}
        self._attempts = 0
        self._inflight = 0
        self._unknown = False
        self._stop_requested = False

    def validate_assignment(self, job):
        if tuple(job.get(key) for key in ("id", "node_id", "worker_owner", "generation")) != self.assignment or job["native"] != self.native:
            raise RuntimeError("Native physical capture assignment differs")

    def bind_execution(self, record):
        # Called only after the receiver's native pending-owner CAS.
        with self._lock:
            if self.record is not None and self.record is not record:
                raise RuntimeError("Native physical capture cannot move executions")
            if (
                (record.run_id, record.user_id, record.thread_id, record.thread_incarnation) != tuple(self.native.get(key) for key in ("run_id", "user_id", "thread_id", "incarnation"))
                or record.workspace_context is None
                or asdict(record.workspace_context) != self.native.get("workspace_context")
            ):
                raise RuntimeError("Native physical capture differs from adopted Run")
            self.record = record

    def acquire_started(self, thread_id, user_id):
        with self._lock:
            if self._stop_requested:
                raise RuntimeError("Native physical execution no longer accepts acquisition")
            if self.record is None or (thread_id, user_id) != (self.record.thread_id, self.record.user_id):
                self._unknown = True
                raise RuntimeError("Native physical acquisition lacks its adopted Run")
            self._attempts += 1
            self._inflight += 1

    def acquire_failed(self):
        with self._lock:
            self._inflight -= 1
            self._unknown = True

    def acquire_ended(self):
        with self._lock:
            self._inflight -= 1

    def observe(self, provider, sandbox_id, *, acquiring=False):
        with self._lock:
            try:
                if self.record is None:
                    raise RuntimeError("Native physical capture lacks its adopted Run")
                handle = provider.capture_physical(sandbox_id, user_id=self.record.user_id, thread_id=self.record.thread_id)
                key = (id(provider), handle.container_id)
                if self._stop_requested and key not in self._handles and not (acquiring and self._inflight):
                    raise RuntimeError("Native physical execution no longer accepts a new object")
                self._handles[key] = (provider, handle)
            except BaseException:
                self._unknown = True
                raise

    def execution_drained(self, record):
        with self._lock:
            if self.record is not record or record.task is None or not record.task.done() or not record.workspace_execution_closed or self._inflight or self._unknown:
                raise RuntimeError("Native physical execution closure is unconfirmed")
            self._stop_requested = True
            # NoStart is proven only by a drained, bound native task which never
            # entered acquisition/reuse. Absence from provider maps is no proof.
            if not self._handles and self._attempts:
                raise RuntimeError("Native physical acquisition has no receipt")

    def stop(self):
        with self._lock:
            self._stop_requested = True
            handles = tuple(self._handles.values())
            record = self.record
        if record is None:
            raise RuntimeError("Native physical STOP lacks its adopted execution")
        for provider, handle in handles:
            provider.destroy_captured(handle)
        with self._lock:
            if self._unknown or self._inflight or len(handles) != len(self._handles):
                raise RuntimeError("Native physical acquisition remains unknown")
            if not handles:
                self.execution_drained(record)
