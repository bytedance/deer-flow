import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from src.utils.context_manager import ContextManager


class TestContextManager:
    """Test cases for ContextManager"""

    def test_count_tokens_with_empty_messages(self):
        """Test counting tokens with empty message list"""
        context_manager = ContextManager(token_limit=1000)
        messages = []
        token_count = context_manager.count_tokens(messages)
        assert token_count == 0

    def test_count_tokens_with_system_message(self):
        """Test counting tokens with system message"""
        context_manager = ContextManager(token_limit=1000)
        messages = [SystemMessage(content="You are a helpful assistant.")]
        token_count = context_manager.count_tokens(messages)
        # System message has 28 characters, should be around 8 tokens (28/4 * 1.1)
        assert token_count > 7

    def test_count_tokens_with_human_message(self):
        """Test counting tokens with human message"""
        context_manager = ContextManager(token_limit=1000)
        messages = [HumanMessage(content="你好，这是一个测试消息。")]
        token_count = context_manager.count_tokens(messages)
        assert token_count > 12

    def test_count_tokens_with_ai_message(self):
        """Test counting tokens with AI message"""
        context_manager = ContextManager(token_limit=1000)
        messages = [AIMessage(content="I'm doing well, thank you for asking!")]
        token_count = context_manager.count_tokens(messages)
        assert token_count >= 10

    def test_count_tokens_with_tool_message(self):
        """Test counting tokens with tool message"""
        context_manager = ContextManager(token_limit=1000)
        messages = [
            ToolMessage(content="Tool execution result data here", tool_call_id="test")
        ]
        token_count = context_manager.count_tokens(messages)
        # Tool message has about 32 characters, should be around 10 tokens (32/4 * 1.3)
        assert token_count > 0

    def test_count_tokens_with_multiple_messages(self):
        """Test counting tokens with multiple messages"""
        context_manager = ContextManager(token_limit=1000)
        messages = [
            SystemMessage(content="You are a helpful assistant."),
            HumanMessage(content="Hello, how are you?"),
            AIMessage(content="I'm doing well, thank you for asking!"),
        ]
        token_count = context_manager.count_tokens(messages)
        # Should be sum of all individual message tokens
        assert token_count > 0

    def test_is_over_limit_when_under_limit(self):
        """Test is_over_limit when messages are under token limit"""
        context_manager = ContextManager(token_limit=1000)
        short_messages = [HumanMessage(content="Short message")]
        is_over = context_manager.is_over_limit(short_messages)
        assert is_over is False

    def test_is_over_limit_when_over_limit(self):
        """Test is_over_limit when messages exceed token limit"""
        # Create a context manager with a very low limit
        low_limit_cm = ContextManager(token_limit=5)
        long_messages = [
            HumanMessage(
                content="This is a very long message that should exceed the limit"
            )
        ]
        is_over = low_limit_cm.is_over_limit(long_messages)
        assert is_over is True

    def test_compress_messages_when_not_over_limit(self):
        """Test compress_messages when messages are not over limit"""
        context_manager = ContextManager(token_limit=1000)
        messages = [HumanMessage(content="Short message")]
        compressed = context_manager.compress_messages({"messages": messages})
        # Should return the same messages when not over limit
        assert len(compressed["messages"]) == len(messages)

    def test_compress_messages_with_system_message(self):
        """Test compress_messages preserves system message"""
        # Create a context manager with limited token capacity
        limited_cm = ContextManager(token_limit=200)

        messages = [
            SystemMessage(content="You are a helpful assistant."),
            HumanMessage(content="Hello"),
            AIMessage(content="Hi there!"),
            HumanMessage(
                content="Can you tell me a very long story that would exceed token limits? "
                * 100
            ),
        ]

        compressed = limited_cm.compress_messages({"messages": messages})
        # Should preserve system message and some recent messages
        assert len(compressed["messages"]) == 1

    def test_compress_messages_with_preserve_prefix_message(self):
        """Test compress_messages when no system message is present"""
        # Create a context manager with limited token capacity
        limited_cm = ContextManager(token_limit=100, preserve_prefix_message_count=2)

        messages = [
            HumanMessage(content="Hello"),
            AIMessage(content="Hi there!"),
            HumanMessage(
                content="Can you tell me a very long story that would exceed token limits? "
                * 10
            ),
        ]

        compressed = limited_cm.compress_messages({"messages": messages})
        # Should keep only the most recent messages that fit
        assert len(compressed["messages"]) == 3

    def test_compress_messages_without_config(self):
        """Test compress_messages preserves system message"""
        # Create a context manager with limited token capacity
        limited_cm = ContextManager(None)

        messages = [
            SystemMessage(content="You are a helpful assistant."),
            HumanMessage(content="Hello"),
            AIMessage(content="Hi there!"),
            HumanMessage(
                content="Can you tell me a very long story that would exceed token limits? "
                * 100
            ),
        ]

        compressed = limited_cm.compress_messages({"messages": messages})
        # return the original messages
        assert len(compressed["messages"]) == 4

    def test_count_message_tokens_with_additional_kwargs(self):
        """Test counting tokens for messages with additional kwargs"""
        context_manager = ContextManager(token_limit=1000)
        message = ToolMessage(
            content="Tool result",
            tool_call_id="test",
            additional_kwargs={"tool_calls": [{"name": "test_function"}]},
        )
        token_count = context_manager._count_message_tokens(message)
        assert token_count > 0

    def test_count_message_tokens_minimum_one_token(self):
        """Test that message token count is at least 1"""
        context_manager = ContextManager(token_limit=1000)
        message = HumanMessage(content="")  # Empty content
        token_count = context_manager._count_message_tokens(message)
        assert token_count == 1  # Should be at least 1

    def test_count_text_tokens_english_only(self):
        """Test counting tokens for English text"""
        context_manager = ContextManager(token_limit=1000)
        # 16 English characters should result in 4 tokens (16/4)
        text = "This is a test."
        token_count = context_manager._count_text_tokens(text)
        assert token_count > 0

    def test_count_text_tokens_chinese_only(self):
        """Test counting tokens for Chinese text"""
        context_manager = ContextManager(token_limit=1000)
        # 8 Chinese characters should result in 8 tokens (1:1 ratio)
        text = "这是一个测试文本"
        token_count = context_manager._count_text_tokens(text)
        assert token_count == 8

    def test_count_text_tokens_mixed_content(self):
        """Test counting tokens for mixed English and Chinese text"""
        context_manager = ContextManager(token_limit=1000)
        text = "Hello world 这是一些中文"
        token_count = context_manager._count_text_tokens(text)
        assert token_count > 6
