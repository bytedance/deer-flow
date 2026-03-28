from unittest.mock import Mock

from deerflow.agents.middlewares.summarization_middleware import (
    DeerFlowSummarizationMiddleware,
)


def test_summary_message_is_tagged_for_frontend_detection():
    middleware = DeerFlowSummarizationMiddleware(model=Mock())

    messages = middleware._build_new_messages("A short summary")

    assert len(messages) == 1
    message = messages[0]
    assert message.name == "conversation_summary"
    assert message.additional_kwargs == {"summary_message": True}
    assert "Here is a summary of the conversation to date:" in message.content
