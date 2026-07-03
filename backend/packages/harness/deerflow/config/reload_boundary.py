"""Single source of truth for the config hot-reload boundary.

Bytedance/deer-flow issue #3144: gateway request dependencies resolve
``AppConfig`` through ``get_app_config()`` on every request, so per-run
fields take effect on the next message without restarting the gateway.
The fields listed in this module are the **infrastructure** subset that
the gateway captures once at startup — engines, singletons, IM clients,
the logging handler — and that therefore require a process restart to
change at runtime.

The registry covers two kinds of entries:

- Top-level ``AppConfig`` fields (``database``, ``checkpointer``,
  ``run_events``, ``stream_bridge``, ``sandbox``, ``log_level``). For
  these, :func:`format_field_description` produces the standardised
  ``"startup-only: ..."`` prefix that the matching Pydantic
  ``Field(description=...)`` carries, so the boundary surfaces in IDE
  hover next to the field itself.
- Top-level ``config.yaml`` sections that are not part of the
  ``AppConfig`` schema (``channels``). These cannot be standardised at
  the schema level, so the registry is their only canonical location.

Any future "needs restart" scanner — operator tooling, lint hooks, doc
generators — should drive off this registry rather than re-parsing
prose.
"""

from __future__ import annotations

from collections.abc import Iterator

#: The standardised prefix every restart-required field description starts
#: with. ``test_reload_boundary`` enforces both directions: registered
#: fields must use this prefix in the schema, and any schema field using
#: this prefix must be in the registry.
STARTUP_ONLY_PREFIX = "startup-only:"


#: Restart-required field paths mapped to the human-readable reason.
#:
#: The reason text is what surfaces in ``Field(description=...)``, so it
#: must explain *what* code captures the snapshot — not just that the
#: field is restart-required — so an operator changing the value knows
#: which subsystem to restart.
STARTUP_ONLY_FIELDS: dict[str, str] = {
    "database": ("init_engine_from_config() runs once during langgraph_runtime() startup; the SQLAlchemy engine holds the connection pool and is not rebuilt on config.yaml edits."),
    "checkpointer": ("make_checkpointer() binds the persistent checkpointer once at startup, including SQLite WAL / busy_timeout settings."),
    "run_events": ("make_run_event_store() picks the memory- vs SQL-backed implementation at startup and is frozen onto app.state.run_events_config to stay paired with the underlying event store."),
    "stream_bridge": ("make_stream_bridge() constructs the stream-bridge singleton once during startup."),
    "sandbox": ("get_sandbox_provider() caches the provider singleton (``_default_sandbox_provider``); a different ``sandbox.use`` class path only takes effect on next process start."),
    "log_level": (
        "apply_logging_level() runs only during app.py startup; it sets the deerflow/app logger levels and may lower root handler thresholds so configured messages can propagate. A freshly reloaded AppConfig does not retrigger it."
    ),
    "logging": (
        "configure_logging() runs only during app.py startup; it installs/removes the trace-context filter and the enhanced formatter on root handlers, "
        "and TraceMiddleware captures logging.enhance.enabled once at startup so response X-Trace-Id headers, log trace_id fields, and Langfuse "
        "deerflow_trace_id stay coherent. A freshly reloaded AppConfig does not retrigger any of this."
    ),
    # Not part of the AppConfig Pydantic schema — channel credentials are
    # consumed directly by ``start_channel_service()`` once at lifespan
    # startup and the live channel clients are not rebuilt on
    # config.yaml edits.
    "channels": ("start_channel_service() is invoked once during startup; the live IM channel clients (Feishu, Slack, Telegram, DingTalk) are not rebuilt when channels.* changes."),
    "channel_connections": (
        "start_channel_service() wires the connection repository and channel workers once at startup, and the channel-connections router caches the merged provider config on app.state; channel_connections.* edits need a restart."
    ),
}


def iter_startup_only_field_paths() -> Iterator[str]:
    """Yield every registered restart-required field path."""
    return iter(STARTUP_ONLY_FIELDS)


def is_startup_only_field(field_path: str) -> bool:
    """Return ``True`` when *field_path* is registered as restart-required.

    Accepts only top-level paths (``"database"``, ``"sandbox"`` etc.);
    nested keys like ``"database.url"`` are not modelled here because the
    boundary is per-section, not per-leaf.
    """
    return field_path in STARTUP_ONLY_FIELDS


def format_field_description(field_path: str, *, field_doc: str | None = None) -> str:
    """Build the standardised description for a registered field.

    Used inside ``AppConfig`` ``Field(description=...)`` so the hover
    text in IDEs matches the registry and the drift tests can pin one
    side against the other.

    Args:
        field_path: A registered top-level field path (e.g. ``"log_level"``).
        field_doc: Optional human-facing description for the field itself
            (allowed values, semantics, etc.). When supplied, it is
            appended after the ``startup-only:`` marker block separated by
            a blank line so IDE hover shows both the restart-required
            reason *and* the field's normal documentation. Composition
            keeps the marker as the leading token machine-readable tooling
            pivots on while restoring the prose that ``Field(description=)``
            used to carry before the registry took over.

    Raises:
        KeyError: when *field_path* is not registered. This is deliberate
            — silently returning a placeholder would let a typo bypass
            the drift coverage.
    """
    reason = STARTUP_ONLY_FIELDS[field_path]
    header = f"{STARTUP_ONLY_PREFIX} {reason}"
    if field_doc is None:
        return header
    return f"{header}\n\n{field_doc.strip()}"
