from deerflow.persistence.base import Base
from deerflow.persistence.models import EvalItemAttemptRow, EvalRunItemRow, EvalRunRow


def test_evaluation_models_registered_with_metadata() -> None:
    assert EvalRunRow.__tablename__ == "eval_runs"
    assert EvalRunItemRow.__tablename__ == "eval_run_items"
    assert EvalItemAttemptRow.__tablename__ == "eval_item_attempts"
    assert {"eval_runs", "eval_run_items", "eval_item_attempts"} <= set(Base.metadata.tables)


def test_evaluation_model_constraints_are_named() -> None:
    eval_runs_constraints = {constraint.name for constraint in EvalRunRow.__table__.constraints}
    eval_items_constraints = {constraint.name for constraint in EvalRunItemRow.__table__.constraints}
    eval_attempts_constraints = {constraint.name for constraint in EvalItemAttemptRow.__table__.constraints}

    assert "uq_eval_runs_owner_idempotency_key" in eval_runs_constraints
    assert "uq_eval_items_run_suite_variant_sample" in eval_items_constraints
    assert "uq_eval_items_run_execution_key" in eval_items_constraints
    assert "uq_eval_attempts_item_attempt_index" in eval_attempts_constraints
