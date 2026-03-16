"""Custom OpenAI Codex provider using ChatGPT Codex Responses API.

Uses Codex CLI OAuth tokens with chatgpt.com/backend-api/codex/responses endpoint.
This is the same endpoint that the Codex CLI uses internally.

Supports:
- Auto-load credentials from ~/.codex/auth.json
- Responses API format (not Chat Completions)
- Tool calling
- Streaming (required by the endpoint)
- Retry with exponential backoff
"""

import json
import logging
import time
from typing import Any

import httpx
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult

logger = logging.getLogger(__name__)

CODEX_BASE_URL = "https://chatgpt.com/backend-api/codex"
MAX_RETRIES = 3


class CodexChatModel(BaseChatModel):
    """LangChain chat model using ChatGPT Codex Responses API.

    Config example:
        - name: gpt-5.4
          use: deerflow.models.openai_codex_provider:CodexChatModel
          model: gpt-5.4
          max_tokens: 100000
          reasoning_effort: medium
    """

    model: str = "gpt-5.4"
    max_tokens: int = 100000
    reasoning_effort: str = "medium"
    retry_max_attempts: int = MAX_RETRIES
    _access_token: str = ""
    _account_id: str = ""

    model_config = {"arbitrary_types_allowed": True}

    @property
    def _llm_type(self) -> str:
        return "codex-responses"

    def model_post_init(self, __context: Any) -> None:
        """Auto-load Codex CLI credentials."""
        cred_data = self._load_codex_auth()
        if cred_data:
            self._access_token = cred_data["access_token"]
            self._account_id = cred_data["account_id"]
            logger.info(f"Using Codex CLI credential (account: {self._account_id[:8]}...)")
        else:
            logger.warning("No Codex CLI credentials found in ~/.codex/auth.json")

        super().model_post_init(__context)

    def _load_codex_auth(self) -> dict | None:
        """Load access_token and account_id from ~/.codex/auth.json."""
        import json
        from pathlib import Path

        auth_path = Path.home() / ".codex" / "auth.json"
        if not auth_path.exists():
            return None
        try:
            data = json.loads(auth_path.read_text())
            tokens = data.get("tokens", {})
            access_token = tokens.get("access_token", "")
            account_id = tokens.get("account_id", "")
            if not access_token:
                return None
            return {"access_token": access_token, "account_id": account_id}
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Failed to read Codex auth: {e}")
            return None

    def _convert_messages(self, messages: list[BaseMessage]) -> tuple[str, list[dict]]:
        """Convert LangChain messages to Responses API format.

        Returns (instructions, input_items).
        """
        instructions = ""
        input_items = []

        for msg in messages:
            if isinstance(msg, SystemMessage):
                instructions = msg.content if isinstance(msg.content, str) else str(msg.content)
            elif isinstance(msg, HumanMessage):
                content = msg.content if isinstance(msg.content, str) else str(msg.content)
                input_items.append({"role": "user", "content": content})
            elif isinstance(msg, AIMessage):
                if msg.content:
                    content = msg.content if isinstance(msg.content, str) else str(msg.content)
                    input_items.append({"role": "assistant", "content": content})
                if msg.tool_calls:
                    for tc in msg.tool_calls:
                        input_items.append(
                            {
                                "type": "function_call",
                                "name": tc["name"],
                                "arguments": json.dumps(tc["args"]) if isinstance(tc["args"], dict) else tc["args"],
                                "call_id": tc["id"],
                            }
                        )
            elif isinstance(msg, ToolMessage):
                input_items.append(
                    {
                        "type": "function_call_output",
                        "call_id": msg.tool_call_id,
                        "output": msg.content if isinstance(msg.content, str) else str(msg.content),
                    }
                )

        if not instructions:
            instructions = "You are a helpful assistant."

        return instructions, input_items

    def _convert_tools(self, tools: list[dict]) -> list[dict]:
        """Convert LangChain tool format to Responses API format."""
        responses_tools = []
        for tool in tools:
            if tool.get("type") == "function" and "function" in tool:
                fn = tool["function"]
                responses_tools.append(
                    {
                        "type": "function",
                        "name": fn["name"],
                        "description": fn.get("description", ""),
                        "parameters": fn.get("parameters", {}),
                    }
                )
            elif "name" in tool:
                responses_tools.append(
                    {
                        "type": "function",
                        "name": tool["name"],
                        "description": tool.get("description", ""),
                        "parameters": tool.get("parameters", {}),
                    }
                )
        return responses_tools

    def _call_codex_api(self, messages: list[BaseMessage], tools: list[dict] | None = None) -> dict:
        """Call the Codex Responses API and return the completed response."""
        instructions, input_items = self._convert_messages(messages)

        payload = {
            "model": self.model,
            "instructions": instructions,
            "input": input_items,
            "store": False,
            "stream": True,
            "reasoning": {"effort": self.reasoning_effort, "summary": "detailed"} if self.reasoning_effort != "none" else {"effort": "none"},
        }

        if tools:
            payload["tools"] = self._convert_tools(tools)

        headers = {
            "Authorization": f"Bearer {self._access_token}",
            "ChatGPT-Account-ID": self._account_id,
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "originator": "codex_cli_rs",
        }

        last_error = None
        for attempt in range(1, self.retry_max_attempts + 1):
            try:
                return self._stream_response(headers, payload)
            except httpx.HTTPStatusError as e:
                last_error = e
                if e.response.status_code in (429, 500, 529):
                    if attempt >= self.retry_max_attempts:
                        raise
                    wait_ms = 2000 * (1 << (attempt - 1))
                    logger.warning(f"Codex API error {e.response.status_code}, retrying {attempt}/{self.retry_max_attempts} after {wait_ms}ms")
                    time.sleep(wait_ms / 1000)
                else:
                    raise
            except Exception:
                raise

        raise last_error

    def _stream_response(self, headers: dict, payload: dict) -> dict:
        """Stream SSE from Codex API and collect the final response."""
        completed_response = None

        with httpx.Client(timeout=300) as client:
            with client.stream("POST", f"{CODEX_BASE_URL}/responses", headers=headers, json=payload) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if line.startswith("data: "):
                        data = json.loads(line[6:])
                        if data.get("type") == "response.completed":
                            completed_response = data["response"]

        if not completed_response:
            raise RuntimeError("Codex API stream ended without response.completed event")

        return completed_response

    def _parse_response(self, response: dict) -> ChatResult:
        """Parse Codex Responses API response into LangChain ChatResult."""
        content = ""
        tool_calls = []
        reasoning_content = ""

        for output_item in response.get("output", []):
            if output_item.get("type") == "reasoning":
                # Extract reasoning summary text
                for summary_item in output_item.get("summary", []):
                    if isinstance(summary_item, dict) and summary_item.get("type") == "summary_text":
                        reasoning_content += summary_item.get("text", "")
                    elif isinstance(summary_item, str):
                        reasoning_content += summary_item
            elif output_item.get("type") == "message":
                for part in output_item.get("content", []):
                    if part.get("type") == "output_text":
                        content += part.get("text", "")
            elif output_item.get("type") == "function_call":
                tool_calls.append(
                    {
                        "name": output_item["name"],
                        "args": json.loads(output_item.get("arguments", "{}")),
                        "id": output_item.get("call_id", ""),
                        "type": "tool_call",
                    }
                )

        usage = response.get("usage", {})
        additional_kwargs = {}
        if reasoning_content:
            additional_kwargs["reasoning_content"] = reasoning_content

        message = AIMessage(
            content=content,
            tool_calls=tool_calls if tool_calls else [],
            additional_kwargs=additional_kwargs,
            response_metadata={
                "model": response.get("model", self.model),
                "usage": usage,
            },
        )

        return ChatResult(
            generations=[ChatGeneration(message=message)],
            llm_output={
                "token_usage": {
                    "prompt_tokens": usage.get("input_tokens", 0),
                    "completion_tokens": usage.get("output_tokens", 0),
                    "total_tokens": usage.get("total_tokens", 0),
                },
                "model_name": response.get("model", self.model),
            },
        )

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        """Generate a response using Codex Responses API."""
        tools = kwargs.get("tools", None)
        response = self._call_codex_api(messages, tools=tools)
        return self._parse_response(response)

    def bind_tools(self, tools: list, **kwargs: Any) -> Any:
        """Bind tools for function calling."""
        from langchain_core.runnables import RunnableBinding
        from langchain_core.tools import BaseTool
        from langchain_core.utils.function_calling import convert_to_openai_function

        formatted_tools = []
        for tool in tools:
            if isinstance(tool, BaseTool):
                try:
                    fn = convert_to_openai_function(tool)
                    formatted_tools.append(
                        {
                            "type": "function",
                            "name": fn["name"],
                            "description": fn.get("description", ""),
                            "parameters": fn.get("parameters", {}),
                        }
                    )
                except Exception:
                    formatted_tools.append(
                        {
                            "type": "function",
                            "name": tool.name,
                            "description": tool.description,
                            "parameters": {"type": "object", "properties": {}},
                        }
                    )
            elif isinstance(tool, dict):
                if "function" in tool:
                    fn = tool["function"]
                    formatted_tools.append(
                        {
                            "type": "function",
                            "name": fn["name"],
                            "description": fn.get("description", ""),
                            "parameters": fn.get("parameters", {}),
                        }
                    )
                else:
                    formatted_tools.append(tool)

        return RunnableBinding(bound=self, kwargs={"tools": formatted_tools}, **kwargs)
