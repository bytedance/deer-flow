from __future__ import annotations

from deerflow.runtime.runs.internal.execution.artifacts import build_run_artifacts


class _Agent:
    pass


def test_build_run_artifacts_uses_store_as_reference_store():
    store = object()

    def agent_factory(*, config):
        return _Agent()

    artifacts = build_run_artifacts(
        thread_id="thread-1",
        run_id="run-1",
        checkpointer=None,
        store=store,
        agent_factory=agent_factory,
        config={},
        bridge=None,  # type: ignore[arg-type]
    )

    assert artifacts.reference_store is store
