"""Scheduled jobs application layer.

Wires the harness-level ``Scheduler`` to deer-flow's application-layer
concerns: user-context setup, ``DeerFlowClient`` invocation, run-record
persistence, and result delivery.

This module is the bridge between:

- ``deerflow.scheduler`` (harness, app-agnostic, owns the tick loop)
- ``app.gateway`` (HTTP API surface for /scheduled_jobs endpoints)
- ``app.channels`` (IM delivery, reused via MessageBus)

Public surface:

- ``AgentJobExecutor``: the ``JobExecutor`` implementation injected into
  ``Scheduler`` at lifespan startup.
- ``start_scheduler(app)`` / ``stop_scheduler()``: lifespan hooks.
- ``CronUser``: minimal ``CurrentUser`` shim used by the executor to
  set ``ContextVar`` user identity per job.

Design note: this module is the *only* place where the harness
``Scheduler`` is instantiated. The Gateway lifespan calls
``start_scheduler(app)``; everything else is internal.
"""

from app.scheduled_jobs.executor import AgentJobExecutor, CronUser
from app.scheduled_jobs.lifecycle import start_scheduler, stop_scheduler

__all__ = ["AgentJobExecutor", "CronUser", "start_scheduler", "stop_scheduler"]
