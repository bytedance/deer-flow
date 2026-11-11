"""Configuration for HarnessGuard tool-loop interceptor middleware."""

from __future__ import annotations

from pydantic import BaseModel, Field, ValidationInfo, field_validator

from deerflow.config._boolean_guards import reject_boolean


class HarnessGuardConfig(BaseModel):
    """Configuration for system harness tool-loop interception, optional write-verification,
    and anti-doom-loop mechanisms."""

    enabled: bool = Field(
        default=True,
        description="Whether the HarnessGuard tool-loop interceptor middleware is enabled",
    )
    write_verify_syntax: bool = Field(
        default=False,
        description="Whether to perform pre-execution syntax validation on .py (ast.parse) and .json (json.loads) str_replace edits",
    )
    block_on_syntax_error: bool = Field(
        default=True,
        description="Whether to reject the write immediately if a syntax error is detected",
    )
    targeted_hints_enabled: bool = Field(
        default=True,
        description="Whether to analyze tool error outputs and append actionable targeted hints",
    )
    max_repeated_error_signatures: int = Field(
        default=2,
        ge=1,
        description="Threshold of consecutive identical error signatures before triggering a critical repetition warning",
    )
    detect_alternating_loops: bool = Field(
        default=True,
        description="Whether to detect A -> B -> A -> B alternating failure patterns between different tools",
    )
    max_loop_history: int = Field(
        default=20,
        ge=5,
        description="Sliding window size of recent tool calls tracked for loop and pattern detection",
    )
    max_tracked_scopes: int = Field(
        default=1000,
        ge=10,
        description="Maximum number of tracked thread/run scopes retained in the bounded LRU history cache",
    )

    @field_validator(
        "max_repeated_error_signatures",
        "max_loop_history",
        "max_tracked_scopes",
        mode="before",
    )
    @classmethod
    def _reject_boolean_loop_limits(cls, value: object, info: ValidationInfo) -> object:
        """A boolean here is a typo, not a threshold: ``true`` would coerce to 1.

        ``max_repeated_error_signatures: true`` collapses the repetition warning
        to the first repeat, because the coerced 1 satisfies ``ge=1``. The other
        two only fail by accident (the coerced 1 falls below ``ge=5`` / ``ge=10``),
        but they are guarded too so the module holds the same invariant.
        """
        return reject_boolean(value, info, kind="an integer")
