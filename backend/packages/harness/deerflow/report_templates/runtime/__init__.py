"""Phase 4 runtime helpers — pure functions that LLM-driven tools call.

Each module is a thin building block reused by ``tools/builtins/report_template_runtime_tools.py``:

  - ``state.py``           — status.json read/write + state machine guards
  - ``data_runner.py``     — execute script descriptors with arg substitution
  - ``step_renderer.py``   — DSL form_step → GenUI block payload
  - ``step_submitter.py``  — accept form submission, advance state
  - ``payload_builder.py`` — assemble ``report_payload.json`` from sections
  - ``report_renderer.py`` — push GenUI blocks for a finished payload
  - ``exporter.py``        — Markdown (required) + PDF (optional) export

The runtime never imports from ``app.*``. It only consumes things the
``report_templates`` package already exports (validator, registry, push_block).
"""

from deerflow.report_templates.runtime.state import (
    RuntimeState,
    RuntimeStateError,
    StateNotFoundError,
    StateTransitionError,
    expect_status,
    mark_failed,
    read_state,
    transition,
    write_state,
)

__all__ = [
    "RuntimeState",
    "RuntimeStateError",
    "StateNotFoundError",
    "StateTransitionError",
    "expect_status",
    "mark_failed",
    "read_state",
    "transition",
    "write_state",
]
