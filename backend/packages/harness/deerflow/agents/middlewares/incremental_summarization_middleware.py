"""Incremental summarization middleware - only summarize new messages."""
 
import hashlib
import logging
from collections.abc import Callable, Awaitable
from datetime import datetime
 
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelRequest, ModelResponse
 
from src.config.summarization_config import get_summarization_config
from src.models import create_chat_model
 
logger = logging.getLogger(__name__)
 
 
class IncrementalSummarizationMiddleware(AgentMiddleware):
    """
    Incremental summarization that only summarizes new messages.
    
    Features:
    - Only summarizes new messages since last summary
    - Stores summary in state for reuse
    - Recursive compression if summary + messages still too large
    - Configurable force refresh via config file
    - Always keeps recent 20 messages + summary
    """
 
    def __init__(
        self,
        model,
        trigger_tokens: int = 40000,
        keep_messages: int = 20,
        max_tokens_for_model: int = 100000,
        compression_prompt: str = None,
        min_new_messages: int = 5,
    ):
        super().__init__()
        self.model = model
        self.trigger_tokens = trigger_tokens
        self.keep_messages = keep_messages
        self.max_tokens_for_model = max_tokens_for_model
        self.min_new_messages = min_new_messages
        self.compression_prompt = compression_prompt or (
            "Please create a concise summary of the following conversation history. "
            "Focus on key information, decisions, and context needed to continue the conversation. "
            "Keep it brief but comprehensive."
        )
        self.force_refresh = self._check_force_refresh_config()
 
    def _check_force_refresh_config(self) -> bool:
        """Check if force refresh is configured."""
        try:
            from pathlib import Path
            import yaml
            
            config_path = Path("config.yaml")
            if not config_path.exists():
                config_path = Path("config.example.yaml")
            
            if config_path.exists():
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = yaml.safe_load(f)
                
                summarization = config.get('summarization', {})
                return summarization.get('force_refresh', False)
        except Exception as e:
            logger.warning(f"Failed to check force_refresh config: {e}")
        
        return False
 
    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse | AIMessage:
        """Intercept model call and apply incremental summarization."""
        
        state = request.state
        messages = request.messages
        
        # Count total tokens
        total_tokens = self._count_tokens(messages)
        
        logger.info(f"Total tokens in context: {total_tokens}, trigger: {self.trigger_tokens}")
        
        # If under trigger, proceed normally
        if total_tokens <= self.trigger_tokens:
            logger.info("Under token threshold, proceeding without compression")
            return await handler(request)
        
        # Get existing summary from state
        summary_state = state.get('summary', {})
        existing_summary = summary_state.get('summary_text', '')
        last_messages_hash = summary_state.get('last_messages_hash', '')
        
        # Calculate hash of current messages (for detecting changes)
        current_hash = self._calculate_messages_hash(messages)
        
        # Check if we need to update summary
        should_update = self._should_update_summary(
            messages, 
            existing_summary, 
            last_messages_hash, 
            current_hash
        )
        
        if should_update:
            logger.info("Updating summary...")
            new_summary = await self._update_summary(messages, summary_state)
            if new_summary:
                summary_state['summary_text'] = new_summary
                summary_state['summary_generated_at'] = datetime.now().isoformat()
                summary_state['last_messages_hash'] = current_hash
        
        # Prepare context with summary + recent messages
        compressed_context = self._prepare_compressed_context(
            messages, 
            summary_state['summary_text']
        )
        
        # Check if still too large, recursively compress
        compressed_context = await self._ensure_token_limit(
            compressed_context, 
            self.max_tokens_for_model
        )
        
        # Build compressed request
        compressed_request = ModelRequest(
            model=request.model,
            messages=compressed_context,
            state=state,
            runtime=request.runtime,
        )
        
        # Return state update for summary
        state['summary'] = summary_state
        
        return await handler(compressed_request)
 
    def _should_update_summary(
        self, 
        messages: list, 
        existing_summary: str, 
        last_hash: str, 
        current_hash: str
    ) -> bool:
        """Determine if we need to update the summary."""
        
        # Force refresh from config
        if self.force_refresh:
            logger.info("Force refresh enabled, regenerating full summary")
            return True
        
        # No existing summary
        if not existing_summary:
            logger.info("No existing summary, creating new one")
            return True
        
        # Check if messages changed
        if last_hash == current_hash:
            logger.info("Messages unchanged, keeping existing summary")
            return False
        
        # Messages changed, _update_summary will handle detailed logic
        logger.info("Messages changed, passing to update logic")
        return True
 
    async def _update_summary(self, messages: list, summary_state: dict) -> str:
        """Update summary incrementally by combining old summary with new messages."""
        
        try:
            # Get messages to summarize (all except recent keep_messages)
            if len(messages) <= self.keep_messages:
                return summary_state.get('summary_text', '')
            
            # Check if we have previous summary info
            old_summary_messages_count = summary_state.get('summary_messages_count', 0)
            existing_summary = summary_state.get('summary_text', '')
            
            messages_to_summarize = messages[:-self.keep_messages]
            current_messages_count = len(messages_to_summarize)
            
            # Determine new messages
            if existing_summary and old_summary_messages_count > 0:
                # We have existing summary, only summarize new messages
                new_messages_count = current_messages_count - old_summary_messages_count
                
                if new_messages_count <= self.min_new_messages:
                    # Not enough new messages, keep old summary
                    logger.info(f"Only {new_messages_count} new messages (threshold: {self.min_new_messages}), keeping existing summary")
                    return existing_summary
                
                # Summarize only new messages
                new_messages = messages_to_summarize[-new_messages_count:]
                logger.info(f"Incremental update: {new_messages_count} new messages out of {current_messages_count} total")
                
                new_summary = await self._generate_summary(new_messages)
                
                if new_summary:
                    # Combine old summary with new summary
                    combined_summary = await self._combine_summaries(existing_summary, new_summary)
                    summary_state['summary_messages_count'] = current_messages_count
                    return combined_summary
                else:
                    return existing_summary
            else:
                # No existing summary, summarize all messages
                logger.info(f"First-time summary: {current_messages_count} messages")
                summary = await self._generate_summary(messages_to_summarize)
                
                if summary:
                    summary_state['summary_messages_count'] = current_messages_count
                return summary
                
        except Exception as e:
            logger.error(f"Failed to update summary: {e}")
            return summary_state.get('summary_text', '')
        
    async def _combine_summaries(self, old_summary: str, new_summary: str) -> str:
        """Combine old and new summaries."""
        
        combine_prompt = (
            "We have an existing summary of a conversation and a summary of new messages. "
            "Please create a unified summary that integrates the new information into the existing context. "
            "The new summary contains more recent conversation, so prioritize that context.\n\n"
            f"Existing summary:\n{old_summary}\n\n"
            f"New summary:\n{new_summary}\n\n"
            "Please create a unified, concise summary."
        )
        
        try:
            import asyncio
            response = await asyncio.wait_for(
                self.model.ainvoke([HumanMessage(content=combine_prompt)]),
                timeout=60.0
            )
            return response.content if hasattr(response, 'content') else str(response)
        except Exception as e:
            logger.error(f"Failed to combine summaries: {e}")
            # Fallback: concatenate
            return f"{old_summary}\n\nRecent conversation:\n{new_summary}"
 
    async def _generate_summary(self, messages: list) -> str:
        """Generate summary for messages."""
        try:
            # Check if too many messages, need batching
            MAX_MESSAGES_PER_SUMMARY = 50
            
            if len(messages) <= MAX_MESSAGES_PER_SUMMARY:
                return await self._generate_single_summary(messages)
            
            # Batch summarization
            logger.info(f"Large batch ({len(messages)} messages), using multi-stage summarization")
            return await self._generate_multi_stage_summary(messages, MAX_MESSAGES_PER_SUMMARY)
            
        except Exception as e:
            logger.error(f"Failed to generate summary: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return "[Summary generation failed]"
 
    async def _generate_single_summary(self, messages: list) -> str:
        """Generate summary for a single batch."""
        text = self._messages_to_text(messages)
        
        # Limit input size
        MAX_INPUT_CHARS = 50000
        if len(text) > MAX_INPUT_CHARS:
            text = text[-MAX_INPUT_CHARS:] + "\n\n... (earlier content truncated for brevity)"
            logger.warning(f"Truncated summary input to {MAX_INPUT_CHARS} characters")
        
        try:
            import asyncio
            response = await asyncio.wait_for(
                self.model.ainvoke([HumanMessage(content=self.compression_prompt + "\n\n" + text)]),
                timeout=120.0
            )
            return response.content if hasattr(response, 'content') else str(response)
        except Exception as e:
            logger.error(f"Summary generation error: {e}")
            return ""
 
    async def _generate_multi_stage_summary(self, messages: list, batch_size: int) -> str:
        """Generate summary in multiple stages."""
        import asyncio
        
        num_batches = (len(messages) + batch_size - 1) // batch_size
        logger.info(f"Processing {len(messages)} messages in {num_batches} batches")
        
        batch_summaries = []
        
        # Summarize each batch
        for i in range(num_batches):
            start = i * batch_size
            end = min((i + 1) * batch_size, len(messages))
            batch = messages[start:end]
            
            logger.info(f"Summarizing batch {i+1}/{num_batches} ({len(batch)} messages)")
            
            try:
                batch_summary = await asyncio.wait_for(
                    self._generate_single_summary(batch),
                    timeout=120.0
                )
                if batch_summary:
                    batch_summaries.append(batch_summary)
            except asyncio.TimeoutError:
                logger.warning(f"Batch {i+1} timed out")
                batch_summaries.append(f"[Batch {i+1} timeout]")
        
        if not batch_summaries:
            return ""
        
        # Combine and summarize again
        combined = "\n\n".join(
            f"=== Part {i+1} ===\n{summary}"
            for i, summary in enumerate(batch_summaries)
        )
        
        logger.info("Summarizing combined batches...")
        
        final_prompt = (
            "The following is a multi-part summary of a long conversation. "
            "Please create a unified summary capturing key information from all parts.\n\n"
        )
        
        try:
            final_summary = await asyncio.wait_for(
                self.model.ainvoke([HumanMessage(content=final_prompt + combined)]),
                timeout=180.0
            )
            return final_summary.content if hasattr(final_summary, 'content') else str(final_summary)
        except asyncio.TimeoutError:
            logger.warning("Final summary timed out, returning combined summaries")
            return combined
 
    def _prepare_compressed_context(self, messages: list, summary_text: str) -> list:
        """Prepare compressed context with summary + recent messages."""
        
        if not summary_text:
            # No summary, just return original messages
            return messages
        
        # Always keep the most recent messages
        if len(messages) <= self.keep_messages:
            return messages
        
        recent_messages = messages[-self.keep_messages:]
        
        # Build context: summary + recent messages
        summary_message = SystemMessage(
            content=f"Here is a summary of the conversation history:\n\n{summary_text}"
        )
        
        return [summary_message] + recent_messages
 
    async def _ensure_token_limit(self, messages: list, max_tokens: int) -> list:
        """Recursively compress until within token limit."""
        
        current_tokens = self._count_tokens(messages)
        
        if current_tokens <= max_tokens:
            logger.info(f"Context within limit: {current_tokens} tokens")
            return messages
        
        logger.warning(f"Context too large ({current_tokens} tokens), compressing...")
        
        # Find summary message and compress it
        summary_idx = -1
        for i, msg in enumerate(messages):
            if msg.type == "system" and "summary of the conversation" in msg.content:
                summary_idx = i
                break
        
        if summary_idx == -1:
            # No summary, truncate from beginning
            return self._truncate_from_beginning(messages, max_tokens)
        
        # Compress the summary
        summary_message = messages[summary_idx]
        
        # Extract summary content
        summary_content = summary_message.content
        
        # Remove the prefix
        prefix = "Here is a summary of the conversation history:\n\n"
        if summary_content.startswith(prefix):
            summary_content = summary_content[len(prefix):]
        
        # Recursively compress the summary
        compressed_summary = await self._compress_summary(summary_content)
        
        # Rebuild message with compressed summary
        new_summary_message = SystemMessage(
            content=f"Here is a summary of the conversation history:\n\n{compressed_summary}"
        )
        
        messages[summary_idx] = new_summary_message
        
        # Check if still too large
        new_tokens = self._count_tokens(messages)
        
        if new_tokens <= max_tokens:
            logger.info(f"Compressed to {new_tokens} tokens")
            return messages
        
        # Still too large, truncate from beginning
        return self._truncate_from_beginning(messages, max_tokens)
 
    async def _compress_summary(self, summary_text: str) -> str:
        """Compress an existing summary."""
        
        compress_prompt = (
            "The following is a summary that needs to be compressed. "
            "Please make it even more concise while preserving the most important information. "
            "Focus on key context, decisions, and what's needed to continue.\n\n"
        )
        
        try:
            import asyncio
            response = await asyncio.wait_for(
                self.model.ainvoke([HumanMessage(content=compress_prompt + summary_text)]),
                timeout=60.0
            )
            return response.content if hasattr(response, 'content') else str(response)
        except Exception as e:
            logger.error(f"Failed to compress summary: {e}")
            # Fallback: truncate
            MAX_CHARS = 3000
            if len(summary_text) > MAX_CHARS:
                return summary_text[:MAX_CHARS] + "\n\n... (truncated)"
            return summary_text
 
    def _truncate_from_beginning(self, messages: list, max_tokens: int) -> list:
        """Truncate messages from beginning to fit token limit."""
        
        # Keep summary message + as many recent messages as possible
        summary_idx = -1
        for i, msg in enumerate(messages):
            if msg.type == "system" and "summary" in msg.content:
                summary_idx = i
                break
        
        if summary_idx == -1:
            # No summary, just keep recent messages
            return self._keep_recent_only(messages, max_tokens)
        
        # Keep summary + recent messages
        summary_message = messages[summary_idx]
        summary_tokens = self._count_single_message(summary_message)
        
        available_tokens = max_tokens - summary_tokens
        if available_tokens < 0:
            available_tokens = max_tokens * 0.5
        
        recent_messages = []
        current_tokens = 0
        
        for msg in reversed(messages):
            if msg == summary_message:
                continue
            
            msg_tokens = self._count_single_message(msg)
            
            if current_tokens + msg_tokens > available_tokens:
                break
            
            recent_messages.insert(0, msg)
            current_tokens += msg_tokens
        
        return [summary_message] + recent_messages
 
    def _keep_recent_only(self, messages: list, max_tokens: int) -> list:
        """Keep only recent messages to fit token limit."""
        
        available_tokens = max_tokens
        recent_messages = []
        current_tokens = self._count_tokens(messages)
        
        for msg in reversed(messages):
            msg_tokens = self._count_single_message(msg)
            
            if current_tokens + msg_tokens > available_tokens:
                break
            
            recent_messages.insert(0, msg)
        
        return recent_messages
 
    def _calculate_messages_hash(self, messages: list) -> str:
        """Calculate hash of messages for change detection."""
        
        # Simple hash based on message count and last message content
        content = f"{len(messages)}:{messages[-1].content if messages else ''}"
        return hashlib.md5(content.encode()).hexdigest()
 
    def _count_tokens(self, messages: list) -> int:
        """Approximate token counting."""
        return sum(self._count_single_message(msg) for msg in messages)
 
    def _count_single_message(self, message) -> int:
        """Approximate token counting for a single message."""
        content = self._get_message_text(message)
        return len(content) // 3
 
    def _messages_to_text(self, messages: list) -> str:
        """Convert messages to text format."""
        text_parts = []
        for msg in messages:
            role = msg.type
            content = self._get_message_text(msg)
            text_parts.append(f"{role}: {content}")
        return "\n\n".join(text_parts)
 
    def _get_message_text(self, message) -> str:
        """Extract text content from a message."""
        content = message.content
        if isinstance(content, str):
            return content
        elif isinstance(content, list):
            return " ".join(
                item.text if hasattr(item, 'text') else str(item)
                for item in content
            )
        return str(content)
 
 
def create_incremental_summarization_middleware() -> IncrementalSummarizationMiddleware | None:
    """Factory function to create incremental summarization middleware from config."""
    try:
        config = get_summarization_config()
        
        if not config.enabled:
            return None
        
        # Use specified model or default lightweight model
        if config.model_name:
            from src.models.factory import create_chat_model
            model = create_chat_model(name=config.model_name, thinking_enabled=False)
        else:
            from src.models import create_chat_model
            model = create_chat_model(thinking_enabled=False)
        
        # Extract trigger value
        trigger_tokens = 40000
        if config.trigger:
            if isinstance(config.trigger, list):
                for t in config.trigger:
                    if t.type == "tokens":
                        trigger_tokens = int(t.value)
                        break
            elif config.trigger.type == "tokens":
                trigger_tokens = int(config.trigger.value)
        
        # Extract keep value
        keep_messages = 20
        if config.keep and config.keep.type == "messages":
            keep_messages = int(config.keep.value)
        
        # Extract trim value for max tokens for model
        max_tokens_for_model = 100000
        if config.trim_tokens_to_summarize is not None:
            max_tokens_for_model = config.trim_tokens_to_summarize * 3  # Rough conversion
        
        return IncrementalSummarizationMiddleware(
            model=model,
            trigger_tokens=trigger_tokens,
            keep_messages=keep_messages,
            max_tokens_for_model=max_tokens_for_model,
            min_new_messages=5,  # At least 5 new messages to trigger update
        )
    except Exception as e:
        logger.error(f"Failed to create incremental summarization middleware: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return None