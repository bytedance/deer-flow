# src/utils/token_manager.py
import copy
import logging
from typing import List

from langgraph.runtime import Runtime 

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from src.config import load_yaml_config

logger = logging.getLogger(__name__)


def get_search_config():
    config = load_yaml_config("conf.yaml")
    search_config = config.get("MODEL_TOKEN_LIMITS", {})
    return search_config


class ContextManager:
    """Context manager and compression class"""

    def __init__(self, token_limit: int, preserve_prefix_message_count: int = 0):
        """
        Initialize ContextManager

        Args:
            token_limit: Maximum token limit
            preserve_prefix_message_count: Number of messages to preserve at the beginning of the context
        """
        self.token_limit = token_limit
        self.preserve_prefix_message_count = preserve_prefix_message_count

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

    def compress_messages(self, state: dict, runtime: Runtime | None = None) -> dict:
        """
        Compress messages to fit within token limit

        Args:
            state: state with original messages
            runtime: Optional runtime parameter (not used but required for middleware compatibility)

        Returns:
            Compressed state with compressed messages
        """
        # If not set token_limit, return original state
        if self.token_limit is None:
            logger.info("No token_limit set, the context management doesn't work.")
            return state

        if not isinstance(state, dict) or "messages" not in state:
            logger.warning("No messages found in state")
            return state

        messages = state["messages"]

        if not self.is_over_limit(messages):
            logger.debug(f"Messages within limit ({self.count_tokens(messages)} <= {self.token_limit} tokens)")
            return state

        # Compress messages
        original_token_count = self.count_tokens(messages)
        compressed_messages = self._compress_messages(messages)
        compressed_token_count = self.count_tokens(compressed_messages)

        logger.warning(
            f"Message compression executed (Issue #721): {original_token_count} -> {compressed_token_count} tokens "
            f"(limit: {self.token_limit}), {len(messages)} -> {len(compressed_messages)} messages"
        )

        state["messages"] = compressed_messages
        return state

    def _compress_messages(self, messages: List[BaseMessage]) -> List[BaseMessage]:
        """
        Compress compressible messages

        Args:
            messages: List of messages to compress

        Returns:
            Compressed message list
        """

        available_token = self.token_limit
        prefix_messages = []

        # 1. Preserve head messages of specified length to retain system prompts and user input
        for i in range(min(self.preserve_prefix_message_count, len(messages))):
            cur_token_cnt = self._count_message_tokens(messages[i])
            if available_token > 0 and available_token >= cur_token_cnt:
                prefix_messages.append(messages[i])
                available_token -= cur_token_cnt
            elif available_token > 0:
                # Truncate content to fit available tokens
                truncated_message = self._truncate_message_content(
                    messages[i], available_token
                )
                prefix_messages.append(truncated_message)
                return prefix_messages
            else:
                break

        # 2. Compress subsequent messages from the tail, some messages may be discarded
        messages = messages[len(prefix_messages) :]
        suffix_messages = []
        for i in range(len(messages) - 1, -1, -1):
            cur_token_cnt = self._count_message_tokens(messages[i])

            if cur_token_cnt > 0 and available_token >= cur_token_cnt:
                suffix_messages = [messages[i]] + suffix_messages
                available_token -= cur_token_cnt
            elif available_token > 0:
                # Truncate content to fit available tokens
                truncated_message = self._truncate_message_content(
                    messages[i], available_token
                )
                suffix_messages = [truncated_message] + suffix_messages
                return prefix_messages + suffix_messages
            else:
                break

        return prefix_messages + suffix_messages

    def _truncate_message_content(
        self, message: BaseMessage, max_tokens: int
    ) -> BaseMessage:
        """
        Truncate message content while preserving all other attributes by copying the original message
        and only modifying its content attribute.

        Args:
            message: The message to truncate
            max_tokens: Maximum number of tokens to keep

        Returns:
            New message instance with truncated content
        """

        # Create a deep copy of the original message to preserve all attributes
        truncated_message = copy.deepcopy(message)

        # Truncate only the content attribute
        truncated_message.content = message.content[:max_tokens]

        return truncated_message

    def _create_summary_message(self, messages: List[BaseMessage]) -> BaseMessage:
        """
        Create summary for messages

        Args:
            messages: Messages to summarize

        Returns:
            Summary message
        """
        # TODO: summary implementation
        pass


def validate_message_content(messages: List[BaseMessage], max_content_length: int = 100000) -> List[BaseMessage]:
    """
    Validate and fix all messages to ensure they have valid content before sending to LLM.
    
    This function ensures:
    1. All messages have a content field
    2. No message has None or empty string content (except for legitimate empty responses)
    3. Complex objects (lists, dicts) are converted to JSON strings
    4. Content is truncated if too long to prevent token overflow
    
    Args:
        messages: List of messages to validate
        max_content_length: Maximum allowed content length per message (default 100000)
    
    Returns:
        List of validated messages with fixed content
    """
    validated = []
    for i, msg in enumerate(messages):
        try:
            # Check if message has content attribute
            if not hasattr(msg, 'content'):
                logger.warning(f"Message {i} ({type(msg).__name__}) has no content attribute")
                msg.content = ""
            
            # Handle None content
            elif msg.content is None:
                logger.warning(f"Message {i} ({type(msg).__name__}) has None content, setting to empty string")
                msg.content = ""
            
            # Handle complex content types (convert to JSON)
            elif isinstance(msg.content, (list, dict)):
                logger.debug(f"Message {i} ({type(msg).__name__}) has complex content type {type(msg.content).__name__}, converting to JSON")
                msg.content = json.dumps(msg.content, ensure_ascii=False)
            
            # Handle other non-string types
            elif not isinstance(msg.content, str):
                logger.debug(f"Message {i} ({type(msg).__name__}) has non-string content type {type(msg.content).__name__}, converting to string")
                msg.content = str(msg.content)
            
            # Validate content length
            if isinstance(msg.content, str) and len(msg.content) > max_content_length:
                logger.warning(f"Message {i} content truncated from {len(msg.content)} to {max_content_length} chars")
                msg.content = msg.content[:max_content_length].rstrip() + "..."
            
            validated.append(msg)
        except Exception as e:
            logger.error(f"Error validating message {i}: {e}")
            # Create a safe fallback message
            if isinstance(msg, ToolMessage):
                msg.content = json.dumps({"error": str(e)}, ensure_ascii=False)
            else:
                msg.content = f"[Error processing message: {str(e)}]"
            validated.append(msg)
    
    return validated
