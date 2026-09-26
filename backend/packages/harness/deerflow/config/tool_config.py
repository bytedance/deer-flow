from typing import Self

from langchain.agents.middleware.human_in_the_loop import DecisionType
from pydantic import BaseModel, ConfigDict, Field, model_validator

# ``ask_clarification`` is DeerFlow's own human-in-the-loop path. It ends the
# turn with ``Command(goto=END)`` and waits for the next HumanMessage, whereas
# tool approval uses a real LangGraph ``interrupt()`` resumed by
# ``Command(resume=...)``. Approving a clarification request would deadlock the
# two mechanisms against each other, so the tool is never approvable.
NON_APPROVABLE_TOOL_NAMES: frozenset[str] = frozenset({"ask_clarification"})


class ToolGroupConfig(BaseModel):
    """Config section for a tool group"""

    name: str = Field(..., description="Unique name for the tool group")
    model_config = ConfigDict(extra="allow")


class InterruptOnConfig(BaseModel):
    """Configuration for an action requiring human in the loop."""

    allowed_decisions: list[DecisionType] = Field(..., description="The decisions that are allowed for this action.")
    description: str | None = Field(default=None, description="The description attached to the request for human input.")
    description_use: str | None = Field(default=None, description="Variable name of the description provider (e.g. my_pkg.my_module:describe_call).")
    when_use: str | None = Field(default=None, description="Variable name of the condition to check if the action requires human input.")

    @model_validator(mode="after")
    def validate_decisions_and_description(self) -> Self:
        """Reject empty decision lists and ambiguous description sources."""
        if not self.allowed_decisions:
            raise ValueError("interrupt_on.allowed_decisions must not be empty; omit interrupt_on to auto-approve the tool")

        duplicates = {decision for decision in self.allowed_decisions if self.allowed_decisions.count(decision) > 1}
        if duplicates:
            raise ValueError(f"interrupt_on.allowed_decisions contains duplicate values: {', '.join(sorted(duplicates))}")

        if self.description is not None and self.description_use is not None:
            raise ValueError("interrupt_on.description and interrupt_on.description_use are mutually exclusive; set only one")

        return self


class ToolConfig(BaseModel):
    """Config section for a tool"""

    name: str = Field(..., description="Unique name for the tool")
    group: str = Field(..., description="Group name for the tool")
    use: str = Field(
        ...,
        description="Variable name of the tool provider(e.g. deerflow.sandbox.tools:bash_tool)",
    )
    interrupt_on: InterruptOnConfig | None = Field(default=None, description="Request human approval before this tool executes.")
    model_config = ConfigDict(extra="allow")

    @model_validator(mode="after")
    def validate_interrupt_on_target(self) -> Self:
        """Keep tool approval off tools whose own contract is a human hand-off."""
        if self.interrupt_on is not None and self.name in NON_APPROVABLE_TOOL_NAMES:
            raise ValueError(f"tool '{self.name}' implements its own human-in-the-loop flow and cannot be combined with interrupt_on")
        return self
