"""Closed-loop ticket subsystem.

Domain layer for tracking equipment defects, faults, and remediation items
through a controlled state machine. Used by:

- ``fault-diagnosis*`` agents (create tickets when severity threshold met)
- ``ai-report--*`` agents (register findings as tracking items)
- ``defect-closure`` agent (process, resolve, and verify closure)
- Workspace UI (human dispatch / verification)

The module exposes:

- :mod:`schemas` -- Pydantic DTOs and discriminated metadata schemas
- :mod:`state_machine` -- ``ClosureStatus`` / ``ClosureAction`` enums and
  ``transition()``
- :mod:`repository` -- async CRUD with paginated listing
- :mod:`service` -- high-level API (tenant / permission enforced)
- :mod:`events` -- ``run_event``-channel publisher for ``closure.<action>``
- :mod:`permissions` -- ``CLOSURE_READ`` / ``CLOSURE_WRITE`` / ``CLOSURE_VERIFY``
"""

from deerflow.closed_loop.permissions import (
    CLOSURE_PERMISSIONS,
    CLOSURE_READ,
    CLOSURE_VERIFY,
    CLOSURE_WRITE,
)
from deerflow.closed_loop.schemas import (
    ClosureSourceType,
    CreateTicketRequest,
    ListTicketsFilter,
    TicketEventDTO,
    TicketResponse,
    TransitionRequest,
    UpdateTicketRequest,
)
from deerflow.closed_loop.service_factory import (
    get_default_service,
    reset_default_service,
    set_default_service,
)
from deerflow.closed_loop.state_machine import ClosureAction, ClosureStatus, TransitionError, transition

__all__ = [
    "CLOSURE_PERMISSIONS",
    "CLOSURE_READ",
    "CLOSURE_VERIFY",
    "CLOSURE_WRITE",
    "ClosureAction",
    "ClosureSourceType",
    "ClosureStatus",
    "CreateTicketRequest",
    "ListTicketsFilter",
    "TicketEventDTO",
    "TicketResponse",
    "TransitionError",
    "TransitionRequest",
    "UpdateTicketRequest",
    "get_default_service",
    "reset_default_service",
    "set_default_service",
    "transition",
]
