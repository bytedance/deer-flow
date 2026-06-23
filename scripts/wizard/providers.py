"""LLM and search provider definitions for the Setup Wizard."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class LLMProvider:
    name: str
    display_name: str
    description: str
    use: str
    models: list[str]
    default_model: str
    env_var: str | None
    package: str | None
    # Optional: some providers use a different field name for the API key in YAML
    api_key_field: str = "api_key"
    # Extra config fields beyond the common ones (merged into YAML)
    extra_config: dict = field(default_factory=dict)
    # Per-model supports_vision overrides for providers whose models differ in
    # capability (e.g. MiniMax M3 supports vision but M2.7 is text-only). The
    # provider-level extra_config holds the default (default_model) capability.
    model_vision_overrides: dict[str, bool] = field(default_factory=dict)
    auth_hint: str | None = None
    base_url_prompt: str | None = None
    model_prompt: str | None = None

    def extra_config_for(self, model_name: str) -> dict:
        """Return extra_config for a selected model, applying per-model overrides.

        Does not mutate the shared provider-level ``extra_config``.
        """
        config = dict(self.extra_config)
        if model_name in self.model_vision_overrides:
            config["supports_vision"] = self.model_vision_overrides[model_name]
        return config


@dataclass
class WebProvider:
    name: str
    display_name: str
    description: str
    use: str
    env_var: str | None  # None = no API key required
    tool_name: str
    extra_config: dict = field(default_factory=dict)


@dataclass
class SearchProvider:
    name: str
    display_name: str
    description: str
    use: str
    env_var: str | None  # None = no API key required
    tool_name: str = "web_search"
    extra_config: dict = field(default_factory=dict)


OPENAI_COMPAT_THINKING_CONFIG = {
    "supports_thinking": True,
    "when_thinking_enabled": {
        "extra_body": {
            "thinking": {
                "type": "enabled",
            }
        }
    },
    "when_thinking_disabled": {
        "extra_body": {
            "thinking": {
                "type": "disabled",
            }
        }
    },
}

ANTHROPIC_THINKING_CONFIG = {
    "supports_thinking": True,
    "when_thinking_enabled": {
        "thinking": {
            "type": "enabled",
            "budget_tokens": 4096,
        }
    },
    "when_thinking_disabled": {
        "thinking": {
            "type": "disabled",
        }
    },
}


LLM_PROVIDERS: list[LLMProvider] = [
    LLMProvider(
        name="volcengine",
        display_name="Volcengine Doubao",
        description="Doubao Seed with thinking support",
        use="deerflow.models.patched_deepseek:PatchedChatDeepSeek",
        models=["doubao-seed-1-8-251228"],
        default_model="doubao-seed-1-8-251228",
        env_var="VOLCENGINE_API_KEY",
        package="langchain-deepseek",
        extra_config={
            "api_base": "https://ark.cn-beijing.volces.com/api/v3",
            "timeout": 600.0,
            "max_retries": 2,
            "supports_vision": True,
            "supports_reasoning_effort": True,
            **OPENAI_COMPAT_THINKING_CONFIG,
        },
    ),
    LLMProvider(
        name="openai",
        display_name="OpenAI",
        description="GPT-5, GPT-4.1, GPT-4o",
        use="langchain_openai:ChatOpenAI",
        models=["gpt-5", "gpt-5-mini", "gpt-4.1", "gpt-4o"],
        default_model="gpt-5",
        env_var="OPENAI_API_KEY",
        package="langchain-openai",
        extra_config={
            "request_timeout": 600.0,
            "max_retries": 2,
            "max_tokens": 4096,
            "temperature": 0.7,
            "supports_vision": True,
        },
    ),
    LLMProvider(
        name="openai_responses",
        display_name="OpenAI Responses API",
        description="GPT-5 via /v1/responses",
        use="langchain_openai:ChatOpenAI",
        models=["gpt-5", "gpt-5-mini"],
        default_model="gpt-5",
        env_var="OPENAI_API_KEY",
        package="langchain-openai",
        extra_config={
            "request_timeout": 600.0,
            "max_retries": 2,
            "use_responses_api": True,
            "output_version": "responses/v1",
            "supports_vision": True,
        },
    ),
    LLMProvider(
        name="anthropic",
        display_name="Anthropic",
        description="Claude Sonnet 4 with extended thinking",
        use="langchain_anthropic:ChatAnthropic",
        models=["claude-sonnet-4-20250514", "claude-opus-4-5", "claude-sonnet-4-5"],
        default_model="claude-sonnet-4-20250514",
        env_var="ANTHROPIC_API_KEY",
        package="langchain-anthropic",
        extra_config={
            "default_request_timeout": 600.0,
            "max_retries": 2,
            "max_tokens": 16000,
            "supports_vision": True,
            **ANTHROPIC_THINKING_CONFIG,
        },
    ),
    LLMProvider(
        name="deepseek",
        display_name="DeepSeek",
        description="DeepSeek Reasoner with thinking support",
        use="deerflow.models.patched_deepseek:PatchedChatDeepSeek",
        models=["deepseek-reasoner", "deepseek-chat"],
        default_model="deepseek-reasoner",
        env_var="DEEPSEEK_API_KEY",
        package="langchain-deepseek",
        extra_config={
            "timeout": 600.0,
            "max_retries": 2,
            "max_tokens": 8192,
            "supports_vision": False,
            **OPENAI_COMPAT_THINKING_CONFIG,
        },
    ),
    LLMProvider(
        name="google",
        display_name="Google Gemini",
        description="Native Gemini SDK, no thinking support",
        use="langchain_google_genai:ChatGoogleGenerativeAI",
        models=["gemini-2.5-pro", "gemini-2.0-flash"],
        default_model="gemini-2.5-pro",
        env_var="GEMINI_API_KEY",
        package="langchain-google-genai",
        api_key_field="gemini_api_key",
        extra_config={
            "timeout": 600.0,
            "max_retries": 2,
            "max_tokens": 8192,
            "supports_vision": True,
        },
    ),
    LLMProvider(
        name="gemini_openai_gateway",
        display_name="Gemini OpenAI-compatible",
        description="Gemini thinking via an OpenAI-compatible gateway",
        use="deerflow.models.patched_openai:PatchedChatOpenAI",
        models=["google/gemini-2.5-pro-preview"],
        default_model="google/gemini-2.5-pro-preview",
        env_var="GEMINI_API_KEY",
        package="langchain-openai",
        extra_config={
            "request_timeout": 600.0,
            "max_retries": 2,
            "max_tokens": 16384,
            "supports_vision": True,
            **OPENAI_COMPAT_THINKING_CONFIG,
        },
        base_url_prompt="Gateway base URL (e.g. https://your-gateway.example/v1)",
    ),
    LLMProvider(
        name="ollama_qwen",
        display_name="Ollama Qwen3",
        description="Native local Ollama provider with thinking support",
        use="langchain_ollama:ChatOllama",
        models=["qwen3:32b"],
        default_model="qwen3:32b",
        env_var=None,
        package="langchain-ollama",
        extra_config={
            "base_url": "http://localhost:11434",
            "num_predict": 8192,
            "temperature": 0.7,
            "reasoning": True,
            "supports_thinking": True,
            "supports_vision": False,
        },
        auth_hint="No API key is required. Ensure Ollama is running and the model is pulled.",
    ),
    LLMProvider(
        name="ollama_gemma",
        display_name="Ollama Gemma",
        description="Native local Ollama provider with vision support",
        use="langchain_ollama:ChatOllama",
        models=["gemma4:27b"],
        default_model="gemma4:27b",
        env_var=None,
        package="langchain-ollama",
        extra_config={
            "base_url": "http://localhost:11434",
            "num_predict": 8192,
            "temperature": 0.7,
            "reasoning": True,
            "supports_thinking": True,
            "supports_vision": True,
        },
        auth_hint="No API key is required. Ensure Ollama is running and the model is pulled.",
    ),
    LLMProvider(
        name="mimo",
        display_name="Xiaomi MiMo",
        description="MiMo thinking models with reasoning replay",
        use="deerflow.models.patched_mimo:PatchedChatMiMo",
        models=["mimo-v2.5-pro", "mimo-v2.5", "mimo-v2-pro", "mimo-v2-omni", "mimo-v2-flash"],
        default_model="mimo-v2.5-pro",
        env_var="MIMO_API_KEY",
        package="langchain-openai",
        extra_config={
            "base_url": "https://api.xiaomimimo.com/v1",
            "request_timeout": 600.0,
            "max_retries": 2,
            "max_tokens": 8192,
            "supports_vision": False,
            **OPENAI_COMPAT_THINKING_CONFIG,
        },
    ),
    LLMProvider(
        name="kimi",
        display_name="Moonshot Kimi",
        description="Kimi K2.5 with thinking support",
        use="deerflow.models.patched_deepseek:PatchedChatDeepSeek",
        models=["kimi-k2.5"],
        default_model="kimi-k2.5",
        env_var="MOONSHOT_API_KEY",
        package="langchain-deepseek",
        extra_config={
            "api_base": "https://api.moonshot.cn/v1",
            "timeout": 600.0,
            "max_retries": 2,
            "max_tokens": 32768,
            "supports_vision": True,
            **OPENAI_COMPAT_THINKING_CONFIG,
        },
    ),
    LLMProvider(
        name="novita",
        display_name="Novita AI",
        description="DeepSeek V3.2 via OpenAI-compatible API",
        use="langchain_openai:ChatOpenAI",
        models=["deepseek/deepseek-v3.2"],
        default_model="deepseek/deepseek-v3.2",
        env_var="NOVITA_API_KEY",
        package="langchain-openai",
        extra_config={
            "base_url": "https://api.novita.ai/openai",
            "request_timeout": 600.0,
            "max_retries": 2,
            "max_tokens": 4096,
            "temperature": 0.7,
            "supports_vision": True,
            **OPENAI_COMPAT_THINKING_CONFIG,
        },
    ),
    LLMProvider(
        name="minimax",
        display_name="MiniMax",
        description="International OpenAI-compatible endpoint",
        use="langchain_openai:ChatOpenAI",
        models=["MiniMax-M3", "MiniMax-M2.7", "MiniMax-M2.7-highspeed"],
        default_model="MiniMax-M3",
        env_var="MINIMAX_API_KEY",
        package="langchain-openai",
        extra_config={
            "base_url": "https://api.minimax.io/v1",
            "request_timeout": 600.0,
            "max_retries": 2,
            "max_tokens": 4096,
            "temperature": 1.0,
            "supports_vision": True,
            "supports_thinking": True,
        },
        model_vision_overrides={
            "MiniMax-M2.7": False,
            "MiniMax-M2.7-highspeed": False,
        },
    ),
    LLMProvider(
        name="minimax_cn",
        display_name="MiniMax CN",
        description="China OpenAI-compatible endpoint",
        use="langchain_openai:ChatOpenAI",
        models=["MiniMax-M3", "MiniMax-M2.7", "MiniMax-M2.7-highspeed"],
        default_model="MiniMax-M3",
        env_var="MINIMAX_API_KEY",
        package="langchain-openai",
        extra_config={
            "base_url": "https://api.minimaxi.com/v1",
            "request_timeout": 600.0,
            "max_retries": 2,
            "max_tokens": 4096,
            "temperature": 1.0,
            "supports_vision": True,
            "supports_thinking": True,
        },
        model_vision_overrides={
            "MiniMax-M2.7": False,
            "MiniMax-M2.7-highspeed": False,
        },
    ),
    LLMProvider(
        name="openrouter",
        display_name="OpenRouter",
        description="OpenAI-compatible gateway with broad model catalog",
        use="langchain_openai:ChatOpenAI",
        models=["google/gemini-2.5-flash-preview", "openai/gpt-5-mini", "anthropic/claude-sonnet-4"],
        default_model="google/gemini-2.5-flash-preview",
        env_var="OPENROUTER_API_KEY",
        package="langchain-openai",
        extra_config={
            "base_url": "https://openrouter.ai/api/v1",
            "request_timeout": 600.0,
            "max_retries": 2,
            "max_tokens": 8192,
            "temperature": 0.7,
        },
    ),
    LLMProvider(
        name="vllm",
        display_name="vLLM",
        description="Self-hosted OpenAI-compatible serving",
        use="deerflow.models.vllm_provider:VllmChatModel",
        models=["Qwen/Qwen3-32B", "Qwen/Qwen2.5-Coder-32B-Instruct"],
        default_model="Qwen/Qwen3-32B",
        env_var="VLLM_API_KEY",
        package=None,
        extra_config={
            "base_url": "http://localhost:8000/v1",
            "request_timeout": 600.0,
            "max_retries": 2,
            "max_tokens": 8192,
            "supports_thinking": True,
            "supports_vision": False,
            "when_thinking_enabled": {
                "extra_body": {
                    "chat_template_kwargs": {
                        "enable_thinking": True,
                    }
                }
            },
            "when_thinking_disabled": {
                "extra_body": {
                    "chat_template_kwargs": {
                        "enable_thinking": False,
                    }
                }
            },
        },
    ),
    LLMProvider(
        name="mindie",
        display_name="MindIE",
        description="Qwen3-Coder on MindIE Engine",
        use="deerflow.models.mindie_provider:MindIEChatModel",
        models=["Qwen3-Coder-480B-A35B-Instruct-Client"],
        default_model="Qwen3-Coder-480B-A35B-Instruct-Client",
        env_var="OPENAI_API_KEY",
        package=None,
        extra_config={
            "base_url": "http://localhost:8989/v1",
            "temperature": 0,
            "max_retries": 1,
            "supports_thinking": False,
            "supports_vision": False,
            "supports_reasoning_effort": False,
            "read_timeout": 900.0,
            "connect_timeout": 30.0,
            "write_timeout": 60.0,
            "pool_timeout": 30.0,
        },
    ),
    LLMProvider(
        name="codex",
        display_name="Codex CLI",
        description="Uses Codex CLI local auth (~/.codex/auth.json)",
        use="deerflow.models.openai_codex_provider:CodexChatModel",
        models=["gpt-5.4", "gpt-5-mini"],
        default_model="gpt-5.4",
        env_var=None,
        package=None,
        api_key_field="api_key",
        extra_config={"supports_thinking": True, "supports_reasoning_effort": True},
        auth_hint="Uses existing Codex CLI auth from ~/.codex/auth.json",
    ),
    LLMProvider(
        name="claude_code",
        display_name="Claude Code OAuth",
        description="Uses Claude Code local OAuth credentials",
        use="deerflow.models.claude_provider:ClaudeChatModel",
        models=["claude-sonnet-4-6", "claude-opus-4-1"],
        default_model="claude-sonnet-4-6",
        env_var=None,
        package=None,
        extra_config={"max_tokens": 4096, "supports_thinking": True},
        auth_hint="Uses Claude Code OAuth credentials from your local machine",
    ),
    LLMProvider(
        name="other",
        display_name="Other OpenAI-compatible",
        description="Custom gateway with base_url and model name",
        use="langchain_openai:ChatOpenAI",
        models=["gpt-4o"],
        default_model="gpt-4o",
        env_var="OPENAI_API_KEY",
        package="langchain-openai",
        base_url_prompt="Base URL (e.g. https://api.openai.com/v1)",
        model_prompt="Model name",
    ),
]

SEARCH_PROVIDERS: list[SearchProvider] = [
    SearchProvider(
        name="ddg",
        display_name="DuckDuckGo (free, no key needed)",
        description="No API key required",
        use="deerflow.community.ddg_search.tools:web_search_tool",
        env_var=None,
        extra_config={"max_results": 5},
    ),
    SearchProvider(
        name="tavily",
        display_name="Tavily",
        description="Recommended, free tier available",
        use="deerflow.community.tavily.tools:web_search_tool",
        env_var="TAVILY_API_KEY",
        extra_config={"max_results": 5},
    ),
    SearchProvider(
        name="infoquest",
        display_name="InfoQuest",
        description="Higher quality vertical search, API key required",
        use="deerflow.community.infoquest.tools:web_search_tool",
        env_var="INFOQUEST_API_KEY",
        extra_config={"search_time_range": 10},
    ),
    SearchProvider(
        name="exa",
        display_name="Exa",
        description="Neural + keyword web search, API key required",
        use="deerflow.community.exa.tools:web_search_tool",
        env_var="EXA_API_KEY",
        extra_config={
            "max_results": 5,
            "search_type": "auto",
            "contents_max_characters": 1000,
        },
    ),
    SearchProvider(
        name="firecrawl",
        display_name="Firecrawl",
        description="Search + crawl via Firecrawl API",
        use="deerflow.community.firecrawl.tools:web_search_tool",
        env_var="FIRECRAWL_API_KEY",
        extra_config={"max_results": 5},
    ),
    SearchProvider(
        name="fastcrw",
        display_name="fastCRW",
        description="Firecrawl-compatible web scraper, single binary, self-host or cloud",
        use="deerflow.community.fastcrw.tools:web_search_tool",
        env_var="CRW_API_KEY",
        extra_config={"max_results": 5},
    ),
    SearchProvider(
        name="brave",
        display_name="Brave Search",
        description="Independent index, official API, API key required",
        use="deerflow.community.brave.tools:web_search_tool",
        env_var="BRAVE_SEARCH_API_KEY",
        extra_config={"max_results": 5},
    ),
    SearchProvider(
        name="groundroute",
        display_name="GroundRoute",
        description="One key across six engines, price-routed with failover, API key required",
        use="deerflow.community.groundroute.tools:web_search_tool",
        env_var="GROUNDROUTE_API_KEY",
        extra_config={"max_results": 5},
    ),
]

WEB_FETCH_PROVIDERS: list[WebProvider] = [
    WebProvider(
        name="jina_ai",
        display_name="Jina AI Reader",
        description="Good default reader, no API key required",
        use="deerflow.community.jina_ai.tools:web_fetch_tool",
        env_var=None,
        tool_name="web_fetch",
        extra_config={"timeout": 10},
    ),
    WebProvider(
        name="exa",
        display_name="Exa",
        description="API key required",
        use="deerflow.community.exa.tools:web_fetch_tool",
        env_var="EXA_API_KEY",
        tool_name="web_fetch",
    ),
    WebProvider(
        name="infoquest",
        display_name="InfoQuest",
        description="API key required",
        use="deerflow.community.infoquest.tools:web_fetch_tool",
        env_var="INFOQUEST_API_KEY",
        tool_name="web_fetch",
        extra_config={"timeout": 10, "fetch_time": 10, "navigation_timeout": 30},
    ),
    WebProvider(
        name="firecrawl",
        display_name="Firecrawl",
        description="Search-grade crawl with markdown output, API key required",
        use="deerflow.community.firecrawl.tools:web_fetch_tool",
        env_var="FIRECRAWL_API_KEY",
        tool_name="web_fetch",
    ),
    WebProvider(
        name="groundroute",
        display_name="GroundRoute",
        description="Page fetch via routed engines, API key required",
        use="deerflow.community.groundroute.tools:web_fetch_tool",
        env_var="GROUNDROUTE_API_KEY",
        tool_name="web_fetch",
    ),
    WebProvider(
        name="fastcrw",
        display_name="fastCRW",
        description="Firecrawl-compatible web scraper with markdown output, self-host or cloud",
        use="deerflow.community.fastcrw.tools:web_fetch_tool",
        env_var="CRW_API_KEY",
        tool_name="web_fetch",
    ),
]
