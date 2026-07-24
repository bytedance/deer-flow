from typing import Literal, Required, TypedDict

from langchain.tools import tool


class ClarificationFormField(TypedDict, total=False):
    """One form field definition for a structured clarification card.

    The model-visible schema documents the item shape; runtime validation
    still happens defensively in ``ClarificationMiddleware`` because the
    middleware intercepts the call before tool execution.
    """

    name: Required[str]
    label: str
    type: Literal["text", "textarea", "number", "select", "multi_select", "checkbox", "date"]
    required: bool
    options: list[str]
    placeholder: str


@tool("ask_clarification", parse_docstring=True, return_direct=True)
def ask_clarification_tool(
    question: str,
    clarification_type: Literal[
        "missing_info",
        "ambiguous_requirement",
        "approach_choice",
        "risk_confirmation",
        "suggestion",
    ],
    context: str | None = None,
    options: list[str] | None = None,
    fields: list[ClarificationFormField] | None = None,
) -> str:
    """Ask the user for clarification when you need more information to proceed.

    Use this tool when you encounter situations where you cannot proceed without user input:

    - **Missing information**: Required details not provided (e.g., file paths, URLs, specific requirements)
    - **Ambiguous requirements**: Multiple valid interpretations exist
    - **Approach choices**: Several valid approaches exist and you need user preference
    - **Risky operations**: Destructive actions that need explicit confirmation (e.g., deleting files, modifying production)
    - **Suggestions**: You have a recommendation but want user approval before proceeding

    The execution will be interrupted and the question will be presented to the user.
    Wait for the user's response before continuing.

    When to use ask_clarification:
    - You need information that wasn't provided in the user's request
    - The requirement can be interpreted in multiple ways
    - Multiple valid implementation approaches exist
    - You're about to perform a potentially dangerous operation
    - You have a recommendation but need user approval

    Choosing the interaction shape:
    - One open question -> just `question` (free text input)
    - Pick exactly one option -> `options`
    - Pick several options -> a single `fields` entry of type `multi_select`
    - Collect several values at once (e.g. a set of parameters for one action) ->
      `fields`, which renders a single structured form instead of several
      sequential questions. Prefer one form over asking field-by-field.

    Best practices:
    - Ask ONE clarification at a time for clarity; a form with several fields
      still counts as one clarification
    - Be specific and clear in your question
    - Don't make assumptions when clarification is needed
    - For risky operations, ALWAYS ask for confirmation
    - If a skill provides a predefined field template, pass it through `fields`
      unchanged instead of redesigning it
    - After calling this tool, execution will be interrupted automatically

    Args:
        question: The clarification question to ask the user. Be specific and clear.
        clarification_type: The type of clarification needed (missing_info, ambiguous_requirement, approach_choice, risk_confirmation, suggestion).
        context: Optional context explaining why clarification is needed. Helps the user understand the situation.
        options: Optional list of choices (for approach_choice or suggestion types). Present clear options for the user to choose from.
        fields: Optional form field definitions for collecting multiple values in one card; takes precedence over `options`.
            Each field is an object with `name` (unique identifier, required; avoid JavaScript prototype names like
            `constructor` or `toString`), `label` (display text, defaults to name), `type` (one of: text, textarea,
            number, select, multi_select, checkbox, date; defaults to text), `required` (boolean, defaults to false),
            `options` (list of strings, required for select/multi_select types), and `placeholder` (optional hint text).
            A `checkbox` field is a boolean that defaults to "no"; set `required` on a checkbox only for
            must-agree/consent semantics (the user has to tick it to submit). Keep forms bounded: at most 16 fields,
            24 options per field, and 200 characters per name/label/option/placeholder — exceeding a limit degrades
            the whole request to a plain-text question.
    """
    # This is a placeholder implementation
    # The actual logic is handled by ClarificationMiddleware which intercepts this tool call
    # and interrupts execution to present the question to the user
    return "Clarification request processed by middleware"
