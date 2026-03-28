from langchain.agents.middleware import SummarizationMiddleware
from langchain_core.messages import HumanMessage


class DeerFlowSummarizationMiddleware(SummarizationMiddleware):
    """Wrap LangChain's summarization middleware so injected summary messages
    can be distinguished from ordinary user-authored HumanMessage entries.
    """

    def _build_new_messages(self, summary: str) -> list[HumanMessage]:
        return [
            HumanMessage(
                content=f"Here is a summary of the conversation to date:\n\n{summary}",
                name="conversation_summary",
                additional_kwargs={"summary_message": True},
            )
        ]
