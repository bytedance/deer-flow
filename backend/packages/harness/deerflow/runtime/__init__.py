"""LangGraph-compatible runtime public API.

Exports are resolved lazily so lightweight submodules (for example
``deerflow.runtime.user_context``) do not pull the full runtime stack into
every import path.
"""

from importlib import import_module

_RUNTIME_EXPORTS = {
    "checkpointer_context": ".checkpointer",
    "get_checkpointer": ".checkpointer",
    "make_checkpointer": ".checkpointer",
    "reset_checkpointer": ".checkpointer",
    "ConflictError": ".runs",
    "DisconnectMode": ".runs",
    "RunContext": ".runs",
    "RunManager": ".runs",
    "RunRecord": ".runs",
    "RunStatus": ".runs",
    "UnsupportedStrategyError": ".runs",
    "run_agent": ".runs",
    "serialize": ".serialization",
    "serialize_channel_values": ".serialization",
    "serialize_lc_object": ".serialization",
    "serialize_messages_tuple": ".serialization",
    "get_store": ".store",
    "make_store": ".store",
    "reset_store": ".store",
    "store_context": ".store",
    "END_SENTINEL": ".stream_bridge",
    "HEARTBEAT_SENTINEL": ".stream_bridge",
    "MemoryStreamBridge": ".stream_bridge",
    "StreamBridge": ".stream_bridge",
    "StreamEvent": ".stream_bridge",
    "make_stream_bridge": ".stream_bridge",
}

__all__ = list(_RUNTIME_EXPORTS)


def __getattr__(name: str):
    module_path = _RUNTIME_EXPORTS.get(name)
    if module_path is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module = import_module(f"{__name__}{module_path}")
    value = getattr(module, name)
    globals()[name] = value
    return value
