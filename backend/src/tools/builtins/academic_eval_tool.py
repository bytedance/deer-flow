from typing import Annotated, Any

from langchain.tools import InjectedToolCallId, ToolRuntime, tool
from langchain_core.messages import ToolMessage
from langgraph.config import get_config
from langgraph.types import Command
from langgraph.typing import ContextT

from src.agents.thread_state import ThreadState
from src.config.paths import get_paths
from src.evals.academic.loader import load_builtin_eval_cases, load_eval_cases
from src.evals.academic.schemas import AcademicEvalCase
from src.research_writing.runtime_service import evaluate_academic_and_persist


def _resolve_thread_id(runtime: ToolRuntime[ContextT, ThreadState]) -> str | None:
    ctx = runtime.context
    thread_id = ctx.get("thread_id") if (ctx is not None and hasattr(ctx, "get")) else None
    if thread_id:
        return thread_id
    try:
        return get_config().get("configurable", {}).get("thread_id")
    except RuntimeError:
        return None


@tool("academic_eval", parse_docstring=True)
def academic_eval_tool(
    runtime: ToolRuntime[ContextT, ThreadState],
    tool_call_id: Annotated[str, InjectedToolCallId],
    cases: list[dict[str, Any]] | None = None,
    dataset_path: str | None = None,
    dataset_name: str | None = None,
    artifact_name: str = "academic-eval-tool",
) -> Command:
    """Run academic quality evaluation on generated writing outputs.

    Evaluates groundedness dimensions:
    - citation_fidelity
    - claim_grounding
    - abstract_body_consistency
    - reviewer_rebuttal_completeness
    - venue_fit
    - cross_modality_synthesis
    - long_horizon_consistency

    Args:
        cases: Optional inline eval-case list (each item follows AcademicEvalCase schema).
        dataset_path: Optional virtual path to a JSON dataset file.
        dataset_name: Optional built-in dataset name in `src/evals/academic/datasets` (without `.json`).
        artifact_name: Output artifact basename.
    """
    thread_id = _resolve_thread_id(runtime)
    if not thread_id:
        return Command(update={"messages": [ToolMessage("Error: thread_id is not available in runtime context", tool_call_id=tool_call_id)]})

    try:
        if cases is not None:
            parsed = [AcademicEvalCase.model_validate(item) for item in cases]
        elif dataset_name:
            parsed = load_builtin_eval_cases(dataset_name)
        elif dataset_path:
            dataset_file = get_paths().resolve_virtual_path(thread_id, dataset_path)
            parsed = load_eval_cases(dataset_file)
        else:
            raise ValueError("Either cases, dataset_path, or dataset_name must be provided")

        summary = evaluate_academic_and_persist(thread_id, cases=parsed, name=artifact_name)
    except Exception as exc:
        return Command(update={"messages": [ToolMessage(f"Error: academic_eval failed: {exc}", tool_call_id=tool_call_id)]})

    msg = f"academic_eval completed: case_count={summary.get('case_count')}, overall={summary.get('average_overall_score'):.4f}"
    return Command(update={"artifacts": [summary["artifact_path"]], "messages": [ToolMessage(msg, tool_call_id=tool_call_id)]})
