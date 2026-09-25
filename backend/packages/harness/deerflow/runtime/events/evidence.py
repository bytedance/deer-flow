"""Internal durable journal drain acknowledgement; not an extension write API."""

from dataclasses import dataclass


@dataclass(frozen=True)
class JournalSealReceipt:
    run_id: str
    thread_id: str
    upper_event_seq: int
    event_count: int
    retention_revision: int
    session_factory: object
