"""LangGraph-compatible runtime — runs, streaming, and lifecycle management.

Re-exports the public API of :mod:`~deerflow.runtime.runs` and
:mod:`~deerflow.runtime.stream_bridge` so that consumers can import
directly from ``deerflow.runtime``.
"""

from .checkpoint_state import CheckpointStateAccessor, build_state_mutation_graph
from .checkpointer import checkpointer_context, get_checkpointer, make_checkpointer, reset_checkpointer
from .runs import CancelOutcome, ConflictError, DisconnectMode, RunContext, RunManager, RunRecord, RunStatus, UnsupportedStrategyError, run_agent
from .serialization import serialize, serialize_channel_values, serialize_channel_values_for_api, serialize_lc_object, serialize_messages_tuple, strip_data_url_image_blocks
from .store import get_store, make_store, reset_store, store_context

# NOTE: ``RedisStreamBridge`` is intentionally not re-exported — ``redis`` is an
# optional extra and importing it here would load ``redis.asyncio`` in every
# process. Import it from ``deerflow.runtime.stream_bridge.redis`` when needed.
from .stream_bridge import END_SENTINEL, HEARTBEAT_SENTINEL, MemoryStreamBridge, StreamBridge, StreamEvent, make_stream_bridge

__all__ = [
    # checkpoint state
    "CheckpointStateAccessor",
    "build_state_mutation_graph",
    # checkpointer
    "checkpointer_context",
    "get_checkpointer",
    "make_checkpointer",
    "reset_checkpointer",
    # runs
    "CancelOutcome",
    "ConflictError",
    "DisconnectMode",
    "RunContext",
    "RunManager",
    "RunRecord",
    "RunStatus",
    "UnsupportedStrategyError",
    "run_agent",
    # serialization
    "serialize",
    "serialize_channel_values",
    "serialize_channel_values_for_api",
    "serialize_lc_object",
    "serialize_messages_tuple",
    "strip_data_url_image_blocks",
    # store
    "get_store",
    "make_store",
    "reset_store",
    "store_context",
    # stream_bridge
    "END_SENTINEL",
    "HEARTBEAT_SENTINEL",
    "MemoryStreamBridge",
    "StreamBridge",
    "StreamEvent",
    "make_stream_bridge",
]
