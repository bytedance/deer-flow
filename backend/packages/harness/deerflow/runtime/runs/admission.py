"""Fatal outcomes a host admission hook can report.

``RunContext.on_run_admitted`` is deliberately best-effort for bookkeeping: a
host hook must not strand an admitted run on a transient cleanup failure. One
class of hook work is not bookkeeping, though: deciding whether the run may
write to durable storage at all. When the host cannot establish that verdict,
continuing would silently run under the wrong persistence policy. Raising
:class:`RunAdmissionRejected` tells the worker to fail the run instead of
swallowing the hook error.
"""

from __future__ import annotations


class RunAdmissionRejected(RuntimeError):
    """A host admission precondition could not be verified; the run must fail."""
