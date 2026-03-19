from typing import Literal

from langchain.tools import tool


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
) -> str:
    """Ask the 用户 for clarification when you need more information to proceed.

    Use this 工具 when you encounter situations where you cannot proceed without 用户 输入:

    - **Missing information**: Required details not provided (e.g., 文件 paths, URLs, specific requirements)
    - **Ambiguous requirements**: Multiple 有效 interpretations exist
    - **Approach choices**: Several 有效 approaches exist and you need 用户 preference
    - **Risky operations**: Destructive actions that need explicit confirmation (e.g., deleting files, modifying production)
    - **Suggestions**: You have a recommendation but want 用户 approval before proceeding

    The execution will be interrupted and the question will be presented to the 用户.
    Wait for the 用户's 响应 before continuing.

    When to use ask_clarification:
    - You need information that wasn't provided in the 用户's 请求
    - The requirement can be interpreted in multiple ways
    - Multiple 有效 implementation approaches exist
    - You're about to perform a potentially dangerous operation
    - You have a recommendation but need 用户 approval

    Best practices:
    - Ask ONE clarification at a time for clarity
    - Be specific and clear in your question
    - Don't make assumptions when clarification is needed
    - For risky operations, ALWAYS ask for confirmation
    - After calling this 工具, execution will be interrupted automatically

    Args:
        question: The clarification question to ask the 用户. Be specific and clear.
        clarification_type: The 类型 of clarification needed (missing_info, ambiguous_requirement, approach_choice, risk_confirmation, suggestion).
        context: Optional context explaining why clarification is needed. Helps the 用户 understand the situation.
        options: Optional 列表 of choices (for approach_choice or suggestion types). Present clear options for the 用户 to choose from.
    """
    #    This is a placeholder implementation


    #    The actual logic is handled by ClarificationMiddleware which intercepts this 工具 call


    #    and interrupts execution to present the question to the 用户


    return "Clarification request processed by middleware"
