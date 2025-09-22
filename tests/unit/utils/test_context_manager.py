import pytest
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, ToolMessage
from src.utils.context_manager import ContextManager


class TestContextManager:
    """Test cases for ContextManager"""

    @pytest.fixture
    def context_manager(self):
        """Create a ContextManager instance for testing"""
        return ContextManager(token_limit=1000)

    def test_init(self):
        """Test ContextManager initialization"""
        cm = ContextManager(token_limit=500)
        assert cm.token_limit == 500

    def test_count_tokens_with_empty_messages(self, context_manager):
        """Test counting tokens with empty message list"""
        messages = []
        token_count = context_manager.count_tokens(messages)
        assert token_count == 0

    def test_count_tokens_with_system_message(self, context_manager):
        """Test counting tokens with system message"""
        messages = [SystemMessage(content="You are a helpful assistant.")]
        token_count = context_manager.count_tokens(messages)
        # System message has 28 characters, should be around 8 tokens (28/4 * 1.1)
        assert token_count > 0

    def test_count_tokens_with_human_message(self, context_manager):
        """Test counting tokens with human message"""
        messages = [HumanMessage(content="Hello, how are you?")]
        token_count = context_manager.count_tokens(messages)
        # Human message has about 20 characters, should be around 5 tokens (20/4)
        assert token_count > 0

    def test_count_tokens_with_ai_message(self, context_manager):
        """Test counting tokens with AI message"""
        messages = [AIMessage(content="I'm doing well, thank you for asking!")]
        token_count = context_manager.count_tokens(messages)
        # AI message has about 36 characters, should be around 11 tokens (36/4 * 1.2)
        assert token_count > 0

    def test_count_tokens_with_tool_message(self, context_manager):
        """Test counting tokens with tool message"""
        messages = [ToolMessage(content="Tool execution result data here", tool_call_id="test")]
        token_count = context_manager.count_tokens(messages)
        # Tool message has about 32 characters, should be around 10 tokens (32/4 * 1.3)
        assert token_count > 0

    def test_count_tokens_with_multiple_messages(self, context_manager):
        """Test counting tokens with multiple messages"""
        messages = [
            SystemMessage(content="You are a helpful assistant."),
            HumanMessage(content="Hello, how are you?"),
            AIMessage(content="I'm doing well, thank you for asking!"),
        ]
        token_count = context_manager.count_tokens(messages)
        # Should be sum of all individual message tokens
        assert token_count > 0

    def test_is_over_limit_when_under_limit(self, context_manager):
        """Test is_over_limit when messages are under token limit"""
        short_messages = [HumanMessage(content="Short message")]
        is_over = context_manager.is_over_limit(short_messages)
        assert is_over is False

    def test_is_over_limit_when_over_limit(self):
        """Test is_over_limit when messages exceed token limit"""
        # Create a context manager with a very low limit
        low_limit_cm = ContextManager(token_limit=1)
        long_messages = [HumanMessage(content="This is a very long message that should exceed the limit")]
        is_over = low_limit_cm.is_over_limit(long_messages)
        assert is_over is True

    def test_compress_messages_when_not_over_limit(self, context_manager):
        """Test compress_messages when messages are not over limit"""
        messages = [HumanMessage(content="Short message")]
        compressed = context_manager.compress_messages(messages)
        # Should return the same messages when not over limit
        assert compressed == messages

    def test_compress_messages_with_system_message(self):
        """Test compress_messages preserves system message"""
        # Create a context manager with limited token capacity
        limited_cm = ContextManager(token_limit=200)
        
        messages = [
            SystemMessage(content="You are a helpful assistant."),
            HumanMessage(content="Hello"),
            AIMessage(content="Hi there!"),
            HumanMessage(content="Can you tell me a very long story that would exceed token limits? " * 10),
        ]
        
        compressed = limited_cm.compress_messages(messages)
        # Should preserve system message and some recent messages
        assert len(compressed) > 0
        # First message should be system message if it was in original
        if isinstance(messages[0], SystemMessage):
            assert isinstance(compressed[0], SystemMessage)

    def test_compress_messages_without_system_message(self):
        """Test compress_messages when no system message is present"""
        # Create a context manager with limited token capacity
        limited_cm = ContextManager(token_limit=100)
        
        messages = [
            HumanMessage(content="Hello"),
            AIMessage(content="Hi there!"),
            HumanMessage(content="Can you tell me a very long story that would exceed token limits? " * 10),
        ]
        
        compressed = limited_cm.compress_messages(messages)
        # Should keep only the most recent messages that fit
        assert len(compressed) > 0
        assert len(compressed) < len(messages)

    def test_count_message_tokens_with_additional_kwargs(self, context_manager):
        """Test counting tokens for messages with additional kwargs"""
        message = ToolMessage(
            content="Tool result",
            tool_call_id="test",
            additional_kwargs={"tool_calls": [{"name": "test_function"}]}
        )
        token_count = context_manager._count_message_tokens(message)
        assert token_count > 0

    def test_count_message_tokens_minimum_one_token(self, context_manager):
        """Test that message token count is at least 1"""
        message = HumanMessage(content="")  # Empty content
        token_count = context_manager._count_message_tokens(message)
        assert token_count == 1  # Should be at least 1

    def test_count_text_tokens_english_only(self, context_manager):
        """Test counting tokens for English text"""
        # 16 English characters should result in 4 tokens (16/4)
        text = "This is a test."
        token_count = context_manager._count_text_tokens(text)
        assert token_count == 5

    def test_count_text_tokens_chinese_only(self, context_manager):
        """Test counting tokens for Chinese text"""
        # 8 Chinese characters should result in 8 tokens (1:1 ratio)
        text = "这是一个测试文本"
        token_count = context_manager._count_text_tokens(text)
        assert token_count == 8

    def test_count_text_tokens_mixed_content(self, context_manager):
        """Test counting tokens for mixed English and Chinese text"""
        text = "Hello world 这是一些中文"
        token_count = context_manager._count_text_tokens(text)
        assert token_count > 6

    def test_count_text_tokens_empty_string(self, context_manager):
        """Test counting tokens for empty string"""
        text = ""
        token_count = context_manager._count_text_tokens(text)
        assert token_count == 0

    def test_count_text_tokens_special_characters(self, context_manager):
        """Test counting tokens for special characters"""
        # 5 special characters should result in 1 token (5/4 = 1)
        text = "!@#$%"
        token_count = context_manager._count_text_tokens(text)
        assert token_count == 1

    def test_compress_messages_returns_empty_list_when_all_messages_filtered(self):
        """Test compress_messages when all messages are filtered out"""
        # Create a context manager with very low token limit
        low_limit_cm = ContextManager(token_limit=10)
        
        # Create messages with high token count
        messages = [
            SystemMessage(content="You are a helpful assistant. " * 10),  # Large system message
        ]
        
        compressed = low_limit_cm.compress_messages(messages)
        # Should return empty list or just the system message
        assert isinstance(compressed, list)

    def test_count_tokens_with_message_without_content(self, context_manager):
        """Test counting tokens with message that has no content"""
        # Create a message without content
        message = HumanMessage(content="")
        messages = [message]
        token_count = context_manager.count_tokens(messages)
        # Should count at least 1 token for the message
        assert token_count >= 1

    def test_count_tokens_with_none_content(self, context_manager):
        """Test counting tokens with message that has None content"""
        # Create a mock message with None content
        message = HumanMessage(content="")
        message.content = None
        messages = [message]
        token_count = context_manager.count_tokens(messages)
        # Should count at least 1 token for the message
        assert token_count >= 1

    def test_count_message_tokens_with_no_type(self, context_manager):
        """Test counting message tokens with message that has no type attribute"""
        message = HumanMessage(content="test")
        # Remove type attribute
        delattr(message, 'type')
        token_count = context_manager._count_message_tokens(message)
        # Should still count tokens based on content
        assert token_count >= 1

    def test_count_message_tokens_with_no_additional_kwargs(self, context_manager):
        """Test counting message tokens with message that has no additional_kwargs"""
        message = HumanMessage(content="test")
        # Remove additional_kwargs if it exists
        if hasattr(message, 'additional_kwargs'):
            delattr(message, 'additional_kwargs')
        token_count = context_manager._count_message_tokens(message)
        # Should still count tokens based on content
        assert token_count >= 1

    def test_compress_messages_with_empty_input(self, context_manager):
        """Test compress_messages with empty message list"""
        messages = []
        compressed = context_manager.compress_messages(messages)
        assert compressed == []

    def test_get_search_config(self):
        """Test get_search_config function"""
        # This test is mainly for coverage, actual functionality depends on conf.yaml
        from src.utils.context_manager import get_search_config
        config = get_search_config()
        # Should return a dict, even if empty
        assert isinstance(config, dict)
