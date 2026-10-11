"""Dependency-free goal objective validation shared by admission and execution."""

MAX_GOAL_OBJECTIVE_CHARS = 4000


def normalize_goal_objective(objective: str) -> str:
    """Normalize and validate user-provided goal text."""
    normalized = " ".join(objective.strip().split())
    if not normalized:
        raise ValueError("Goal objective must not be empty.")
    if len(normalized) > MAX_GOAL_OBJECTIVE_CHARS:
        raise ValueError(f"Goal objective must be at most {MAX_GOAL_OBJECTIVE_CHARS} characters.")
    return normalized
