"""Custom middleware for context compression without modifying stored history."""
 
import logging
from collections.abc import Callable, Awaitable
from typing import Any
 
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from langchain.agents.middleware import AgentMiddleware
from langchain_core.language_models import BaseChatModel
from langchain.agents.middleware.types import ModelRequest, ModelResponse
 
from src.config.summarization_config import get_summarization_config
from src.models import create_chat_model
 
logger = logging.getLogger(__name__)
 
 
class ContextCompressionMiddleware(AgentMiddleware):
    """
    Compresses context before model calls without modifying stored history.
    
    This middleware:
    - Compresses historical messages when thresholds are met
    - Passes compressed context to the model
    - Does NOT modify state["messages"] - keeps full history intact
    - Frontend receives full history from checkpoint
    - Supports batch summarization for very large contexts
    """
 
    def __init__(
        self,
        model: BaseChatModel,
        trigger_tokens: int = 65536,
        keep_messages: int = 10,
        trim_tokens_to_summarize: int | None = None,
        compression_prompt: str = None,
        batch_size: int = 50,
        max_summary_input_tokens: int = 50000,
    ):
        super().__init__()
        self.model = model
        self.trigger_tokens = trigger_tokens
        self.keep_messages = keep_messages
        self.trim_tokens_to_summarize = trim_tokens_to_summarize
        self.batch_size = batch_size
        self.max_summary_input_tokens = max_summary_input_tokens
        self.compression_prompt = compression_prompt or (
            "Please create a concise summary of the following conversation history. "
            "Focus on key information, decisions, and context needed to continue the conversation. "
            "Keep it brief but comprehensive."
        )
 
    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse | AIMessage:
        """Intercept model call and compress context if needed."""
        
        messages = request.messages
        
        # Count tokens in messages
        total_tokens = self._count_tokens(messages)
        
        logger.info(f"Total tokens in context: {total_tokens}, trigger: {self.trigger_tokens}")
        
        if total_tokens <= self.trigger_tokens:
            # No compression needed, proceed with original request
            return await handler(request)
        
        logger.info("Compressing context...")
        
        # Check if we have enough messages
        if len(messages) <= self.keep_messages:
            return await handler(request)
        
        messages_to_summarize = messages[:-self.keep_messages]
        recent_messages = messages[-self.keep_messages:]
        
        # Apply trim_tokens_to_summarize if configured
        if self.trim_tokens_to_summarize is not None:
            messages_to_summarize = self._trim_messages(
                messages_to_summarize, 
                self.trim_tokens_to_summarize
            )
            trimmed_tokens = self._count_tokens(messages_to_summarize)
            logger.info(f"Trimmed messages to summarize: {trimmed_tokens} tokens ({len(messages_to_summarize)} messages)")
        
        # Generate summary using batch processing if needed
        summary = await self._generate_summary(messages_to_summarize)
        
        # If summary generation failed, proceed with original request
        if summary == "[Summary generation failed]" or not summary or len(summary) < 10:
            logger.warning("Summary generation failed or returned empty, proceeding with original messages")
            return await handler(request)
        
        # Create compressed context
        summary_message = SystemMessage(
            content=f"Here is a summary of the conversation history:\n\n{summary}"
        )
        
        compressed_messages = [summary_message] + recent_messages
        
        # Calculate final compressed token count
        compressed_tokens = self._count_tokens(compressed_messages)
        logger.info(f"Final compressed context: {compressed_tokens} tokens (vs original {total_tokens})")
        
        # Create modified request with compressed messages
        compressed_request = ModelRequest(
            model=request.model,
            messages=compressed_messages,
            state=request.state,
            runtime=request.runtime,
        )
        
        # Call model with compressed context
        return await handler(compressed_request)
 
    def _trim_messages(self, messages: list, max_tokens: int) -> list:
        """Trim messages to stay within token limit."""
        if not messages:
            return []
        
        trimmed = []
        current_tokens = 0
        
        for msg in reversed(messages):
            msg_tokens = self._count_single_message(msg)
            
            if current_tokens + msg_tokens > max_tokens:
                break
            
            trimmed.insert(0, msg)
            current_tokens += msg_tokens
        
        logger.info(f"_trim_messages: kept {len(trimmed)}/{len(messages)} messages, "
                   f"{current_tokens}/{self._count_tokens(messages)} tokens")
        
        return trimmed
 
    async def _generate_summary(self, messages: list) -> str:
        """Generate summary with batch processing for large contexts."""
        try:
            if not messages:
                return ""
            
            # Check if we need batch processing
            if len(messages) <= self.batch_size:
                logger.info("Generating single-batch summary")
                return await self._generate_single_summary(messages)
            
            # Use batch processing for large message sets
            logger.info(f"Large context ({len(messages)} messages), using batch summarization")
            return await self._generate_batch_summary(messages)
            
        except Exception as e:
            logger.error(f"Failed to generate summary: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return "[Summary generation failed]"
 
    async def _generate_single_summary(self, messages: list) -> str:
        """Generate summary for a single batch of messages."""
        text_to_summarize = self._messages_to_text(messages)
        
        # Limit the length to avoid model limits
        if len(text_to_summarize) > self.max_summary_input_tokens:
            # Truncate from the beginning (keep recent content)
            text_to_summarize = text_to_summarize[-self.max_summary_input_tokens:]
            logger.warning(f"Truncated summary input to {self.max_summary_input_tokens} characters")
        
        response = await self.model.ainvoke(
            [HumanMessage(content=self.compression_prompt + "\n\n" + text_to_summarize)]
        )
        
        return response.content if hasattr(response, 'content') else str(response)
 
    async def _generate_batch_summary(self, messages: list) -> str:
        """Generate summary by processing messages in batches and then summarizing the summaries."""
        try:
            # Split messages into batches
            num_batches = (len(messages) + self.batch_size - 1) // self.batch_size
            logger.info(f"Splitting {len(messages)} messages into {num_batches} batches of ~{self.batch_size}")
            
            batch_summaries = []
            
            # Process each batch
            for batch_idx in range(num_batches):
                start_idx = batch_idx * self.batch_size
                end_idx = min((batch_idx + 1) * self.batch_size, len(messages))
                batch_messages = messages[start_idx:end_idx]
                
                logger.info(f"Processing batch {batch_idx + 1}/{num_batches} ({len(batch_messages)} messages)")
                
                # Generate summary for this batch
                batch_summary = await self._generate_single_summary(batch_messages)
                batch_summaries.append(batch_summary)
            
            logger.info("All batches summarized, now combining summaries")
            
            # Combine batch summaries into a single summary
            combined_summaries_text = "\n\n".join(
                f"=== Conversation Part {i+1} of {len(batch_summaries)} ===\n{summary}"
                for i, summary in enumerate(batch_summaries)
            )
            
            # Generate final summary of all batch summaries
            final_summary_prompt = (
                "The following is a combined summary of a long conversation, split into parts. "
                "Please create a unified, concise summary that captures the key information from all parts. "
                "Focus on the most important context, decisions, and information needed to continue the conversation.\n\n"
            )
            
            # Limit the combined summaries length
            MAX_COMBINED_LENGTH = 40000  # characters
            if len(combined_summaries_text) > MAX_COMBINED_LENGTH:
                # Take from the end (more recent) and beginning
                combined_summaries_text = (
                    combined_summaries_text[:MAX_COMBINED_LENGTH//2] + 
                    "\n\n... (middle parts omitted) ...\n\n" +
                    combined_summaries_text[-MAX_COMBINED_LENGTH//2:]
                )
                logger.warning(f"Truncated combined summaries to {MAX_COMBINED_LENGTH} characters")
            
            final_summary = await self.model.ainvoke(
                [HumanMessage(content=final_summary_prompt + combined_summaries_text)]
            )
            
            final_summary_text = final_summary.content if hasattr(final_summary, 'content') else str(final_summary)
            logger.info(f"Final summary generated, length: {len(final_summary_text)} characters")
            
            return final_summary_text
            
        except Exception as e:
            logger.error(f"Failed to generate batch summary: {e}")
            import traceback
            logger.error(traceback.format_exc())
            # Fallback: try to summarize first and last batches only
            try:
                logger.warning("Falling back to summarizing only first and last batches")
                first_batch = messages[:self.batch_size]
                last_batch = messages[-self.batch_size:]
                
                first_summary = await self._generate_single_summary(first_batch)
                last_summary = await self._generate_single_summary(last_batch)
                
                combined = f"Early conversation:\n{first_summary}\n\nRecent conversation:\n{last_summary}"
                return combined
            except Exception as fallback_error:
                logger.error(f"Fallback summary also failed: {fallback_error}")
                return "[Summary generation failed]"
 
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
 
 
def create_context_compression_middleware() -> ContextCompressionMiddleware | None:
    """Factory function to create context compression middleware from config."""
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
        trigger_tokens = 65536
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
        
        # Extract trim_tokens_to_summarize value
        trim_tokens_to_summarize = config.trim_tokens_to_summarize
        
        # Create middleware with batch summarization support
        return ContextCompressionMiddleware(
            model=model,
            trigger_tokens=trigger_tokens,
            keep_messages=keep_messages,
            trim_tokens_to_summarize=trim_tokens_to_summarize,
            batch_size=30,  # Process 30 messages per batch
            max_summary_input_tokens=262144,  # Max 256K chars per summary call
        )
    except Exception as e:
        logger.error(f"Failed to create context compression middleware: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return None