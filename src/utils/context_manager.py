# src/utils/token_manager.py
from typing import List
from langchain_core.messages import (
    BaseMessage,
    HumanMessage,
    AIMessage,
    ToolMessage,
    SystemMessage,
)
import logging

from src.config import load_yaml_config

logger = logging.getLogger(__name__)


def get_search_config():
    config = load_yaml_config("conf.yaml")
    search_config = config.get("MODEL_TOKEN_LIMITS", {})
    return search_config


class ContextManager:
    """Context manager and compression class"""

    def __init__(self, token_limit: int):
        """
        Initialize ContextManager

        Args:
            token_limit: Maximum token limit
        """
        self.token_limit = token_limit

    def count_tokens(self, messages: List[BaseMessage]) -> int:
        """
        Count tokens in message list

        Args:
            messages: List of messages

        Returns:
            Number of tokens
        """
        total_tokens = 0
        for message in messages:
            total_tokens += self._count_message_tokens(message)
        return total_tokens

    def _count_message_tokens(self, message: BaseMessage) -> int:
        """
        Count tokens in a single message

        Args:
            message: Message object

        Returns:
            Number of tokens
        """
        # Estimate token count based on character length (different calculation for English and non-English)
        token_count = 0

        # Count tokens in content field
        if hasattr(message, "content") and message.content:
            # Handle different content types
            if isinstance(message.content, str):
                token_count += self._count_text_tokens(message.content)

        # Count role-related tokens
        if hasattr(message, "type"):
            token_count += self._count_text_tokens(message.type)

        # Special handling for different message types
        if isinstance(message, SystemMessage):
            # System messages are usually short but important, slightly increase estimate
            token_count = int(token_count * 1.1)
        elif isinstance(message, HumanMessage):
            # Human messages use normal estimation
            pass
        elif isinstance(message, AIMessage):
            # AI messages may contain reasoning content, slightly increase estimate
            token_count = int(token_count * 1.2)
        elif isinstance(message, ToolMessage):
            # Tool messages may contain large amounts of structured data, increase estimate
            token_count = int(token_count * 1.3)

        # Process additional information in additional_kwargs
        if hasattr(message, "additional_kwargs") and message.additional_kwargs:
            # Simple estimation of extra field tokens
            extra_str = str(message.additional_kwargs)
            token_count += self._count_text_tokens(extra_str)

            # If there are tool_calls, add estimation
            if "tool_calls" in message.additional_kwargs:
                token_count += 50  # Add estimation for function call information

        # Ensure at least 1 token
        return max(1, token_count)

    def _count_text_tokens(self, text: str) -> int:
        """
        Count tokens in text with different calculations for English and non-English characters.
        English characters: 4 characters ≈ 1 token
        Non-English characters (e.g., Chinese): 1 character ≈ 1 token

        Args:
            text: Text to count tokens for

        Returns:
            Number of tokens
        """
        if not text:
            return 0

        english_chars = 0
        non_english_chars = 0

        for char in text:
            # Check if character is ASCII (English letters, digits, punctuation)
            if ord(char) < 128:
                english_chars += 1
            else:
                non_english_chars += 1

        # Calculate tokens: English at 4 chars/token, others at 1 char/token
        english_tokens = english_chars // 4
        non_english_tokens = non_english_chars

        return english_tokens + non_english_tokens

    def is_over_limit(self, messages: List[BaseMessage]) -> bool:
        """
        Check if messages exceed token limit

        Args:
            messages: List of messages

        Returns:
            Whether limit is exceeded
        """
        return self.count_tokens(messages) > self.token_limit

    def compress_messages(self, messages: List[BaseMessage]) -> List[BaseMessage]:
        """
        Compress messages to fit within token limit

        Args:
            messages: Original message list

        Returns:
            Compressed message list
        """
        if not self.is_over_limit(messages):
            return messages

        # 2. Compress messages
        compressed_messages = self._compress_messages(messages)

        logger.info(
            f"Message compression completed: {self.count_tokens(messages)} -> {self.count_tokens(compressed_messages)} tokens"
        )
        return compressed_messages

    def _compress_messages(self, messages: List[BaseMessage]) -> List[BaseMessage]:
        """
        Compress compressible messages

        Args:
            messages: List of messages to compress

        Returns:
            Compressed message list
        """
        # 1. Protect system message
        if messages and isinstance(messages[0], SystemMessage):
            sys_msg = messages[0]
            available_token = self.token_limit - self._count_message_tokens(sys_msg)
        else:
            available_token = self.token_limit

        # 2. Keep messages from newest to oldest
        new_messages = []
        for i in range(len(messages) - 1, -1, -1):
            # Fixed logical error: should check if current message is system message, not first message
            if isinstance(messages[i], SystemMessage):
                continue

            cur_token_cnt = self._count_message_tokens(messages[i])

            if cur_token_cnt <= available_token:
                new_messages = [messages[i]] + new_messages
                available_token -= cur_token_cnt
            else:
                # TODO: summary message
                break

        return new_messages

    def _create_summary_message(self, messages: List[BaseMessage]) -> BaseMessage:
        """
        Create summary for messages

        Args:
            messages: Messages to summarize

        Returns:
            Summary message
        """
        # Simple summary implementation
        pass