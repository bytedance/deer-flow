# General Index

## Root

- `Makefile` - Top-level development, docker and deployment commands [BUILD]

## backend/

- `debug.py` - Interactive CLI debug script to run the lead_agent with breakpoints and manual input.. Key: `main` [CLI]

## backend/app/channels/

- `__init__.py` - Channel package exports for IM channel integration. Key: `Channel`, `InboundMessage`, `MessageBus`, `OutboundMessage` [SOURCE_CODE]
- `base.py` - Abstract base class for instant‑messaging channel implementations. Key: `Channel`, `_make_inbound`, `_on_outbound`, `receive_file` [SOURCE_CODE]
- `commands.py` - Canonical set of known chat commands across IM channels. Key: `KNOWN_CHANNEL_COMMANDS` [SOURCE_CODE]
- `feishu.py` - WebSocket-based Feishu/Lark IM channel implementation that handles inbound/outbound messages, attachments, and running-status cards.. Key: `_is_feishu_command`, `FeishuChannel`, `FeishuChannel.start`, `FeishuChannel._run_ws`, `FeishuChannel.stop` [SOURCE_CODE]
- `manager.py` - Bridges inbound IM messages to the DeerFlow lead agent (LangGraph) and handles file ingestion, streaming, and artifact delivery.. Key: `DEFAULT_LANGGRAPH_URL`, `DEFAULT_GATEWAY_URL`, `DEFAULT_ASSISTANT_ID`, `CHANNEL_CAPABILITIES`, `INBOUND_FILE_READERS` [SOURCE_CODE]
- `message_bus.py` - Async pub/sub hub connecting channels and the agent dispatcher. Key: `InboundMessageType`, `InboundMessage`, `ResolvedAttachment`, `OutboundMessage`, `MessageBus` [SOURCE_CODE]
- `service.py` - Service that instantiates, starts, stops and reports status for configured IM channels.. Key: `_CHANNEL_REGISTRY`, `_CHANNELS_LANGGRAPH_URL_ENV`, `_CHANNELS_GATEWAY_URL_ENV`, `_resolve_service_url`, `ChannelService` [SOURCE_CODE]
- `slack.py` - Slack Socket Mode integration channel for inbound/outbound messages. Key: `SlackChannel`, `_slack_md_converter`, `_on_socket_event` [SOURCE_CODE]
- `store.py` - JSON-backed persistent mapping of IM chats to DeerFlow threads. Key: `ChannelStore`, `_key`, `_load`, `_save` [SOURCE_CODE]
- `telegram.py` - Telegram long-polling channel integration for inbound/outbound messages. Key: `TelegramChannel`, `_run_polling`, `_process_incoming_with_reply` [SOURCE_CODE]
- `wecom.py` - WeCom (WeChat Work) WebSocket channel adapter for inbound/outbound messages. Key: `WeComChannel`, `_publish_ws_inbound`, `_send_ws`, `_upload_media_ws`, `_send_ws_upload_command` [SOURCE_CODE]

## backend/app/gateway/

- `__init__.py` - Gateway package exports (app and config accessors). Key: `app`, `create_app`, `GatewayConfig`, `get_gateway_config` [SOURCE_CODE]
- `app.py` - FastAPI application factory and lifespan for the DeerFlow API Gateway. Key: `lifespan`, `create_app`, `app` [SOURCE_CODE]
- `config.py` - Pydantic model and loader for gateway host/port/CORS settings. Key: `GatewayConfig`, `get_gateway_config`, `_gateway_config` [SOURCE_CODE]
- `deps.py` - FastAPI dependency providers for LangGraph runtime singletons. Key: `langgraph_runtime`, `get_stream_bridge`, `get_run_manager`, `get_checkpointer`, `get_store` [SOURCE_CODE]
- `path_utils.py` - Resolve sandbox virtual thread paths to actual filesystem paths. Key: `resolve_thread_virtual_path` [SOURCE_CODE]
- `services.py` - Run lifecycle and SSE formatting service layer for Gateway endpoints. Key: `format_sse`, `normalize_stream_modes`, `normalize_input`, `_DEFAULT_ASSISTANT_ID`, `resolve_agent_factory` [SOURCE_CODE]

## backend/app/gateway/routers/

- `__init__.py` - Router package exports for gateway API modules. Key: `__all__` [SOURCE_CODE]
- `agents.py` - FastAPI router for CRUD operations on custom agents and user profile. Key: `AgentResponse`, `AgentCreateRequest`, `list_agents`, `create_agent_endpoint`, `delete_agent` [SOURCE_CODE]
- `artifacts.py` - Artifact file retrieval and safe serving endpoints. Key: `get_artifact`, `_extract_file_from_skill_archive`, `is_text_file_by_content`, `ACTIVE_CONTENT_MIME_TYPES` [SOURCE_CODE]
- `assistants_compat.py` - Compatibility API exposing minimal assistants endpoints for the frontend. Key: `AssistantResponse`, `AssistantSearchRequest`, `_list_assistants`, `search_assistants`, `get_assistant_compat` [SOURCE_CODE]
- `channels.py` - API router for IM channel status and restart operations. Key: `ChannelStatusResponse`, `ChannelRestartResponse`, `get_channels_status`, `restart_channel` [SOURCE_CODE]
- `mcp.py` - FastAPI router to view and update MCP server configurations. Key: `McpOAuthConfigResponse`, `McpServerConfigResponse`, `McpConfigResponse`, `get_mcp_configuration`, `update_mcp_configuration` [SOURCE_CODE]
- `memory.py` - FastAPI router exposing HTTP endpoints to view and manage the global memory snapshot and configuration.. Key: `ContextSection`, `UserContext`, `HistoryContext`, `Fact`, `MemoryResponse` [SOURCE_CODE]
- `models.py` - API endpoints to list and fetch configured AI models. Key: `ModelResponse`, `ModelsListResponse`, `list_models`, `get_model` [SOURCE_CODE]
- `runs.py` - Stateless run endpoints for streaming and blocking run creation. Key: `_resolve_thread_id`, `stateless_stream`, `stateless_wait` [SOURCE_CODE]
- `skills.py` - FastAPI router exposing skill management endpoints (list/install/custom edit/history/rollback/update).. Key: `_skill_to_response`, `list_skills`, `install_skill`, `list_custom_skills`, `get_custom_skill` [SOURCE_CODE]
- `suggestions.py` - API endpoint to generate follow-up question suggestions from conversation. Key: `SuggestionMessage`, `SuggestionsRequest`, `SuggestionsResponse`, `generate_suggestions`, `_parse_json_string_list` [SOURCE_CODE]
- `thread_runs.py` - Run lifecycle endpoints: create, stream, wait, cancel, join. Key: `RunCreateRequest`, `RunResponse`, `create_run`, `stream_run`, `cancel_run` [SOURCE_CODE]
- `threads.py` - Thread CRUD, state and history management endpoints. Key: `create_thread`, `delete_thread_data`, `search_threads`, `_derive_thread_status` [SOURCE_CODE]
- `uploads.py` - FastAPI router that handles thread-scoped file uploads, listings, and deletions with sandbox syncing.. Key: `UploadResponse`, `_make_file_sandbox_writable`, `upload_files`, `list_uploaded_files`, `delete_uploaded_file` [SOURCE_CODE]

## backend/packages/harness/deerflow/

- `client.py` - An embedded Python client that constructs and invokes an in-process DeerFlow agent (LangGraph/LangChain) and exposes convenience APIs (chat/stream/config queries/uploads/memory).. Key: `StreamEvent`, `DeerFlowClient`, `_atomic_write_json`, `_get_runnable_config`, `_ensure_agent` [SOURCE_CODE]

## backend/packages/harness/deerflow/agents/

- `__init__.py` - Public agent package exports and import-time initialization. Key: `prime_enabled_skills_cache`, `make_lead_agent`, `SandboxState`, `ThreadState` [SOURCE_CODE]
- `factory.py` - SDK factory to assemble DeerFlow agents with middleware and tools. Key: `create_deerflow_agent`, `_assemble_from_features`, `_insert_extra`, `_TODO_SYSTEM_PROMPT` [SOURCE_CODE]
- `features.py` - Declarative runtime feature flags and middleware positioning helpers. Key: `RuntimeFeatures`, `Next`, `Prev` [SOURCE_CODE]
- `thread_state.py` - Typed thread/agent state schema and reducers for artifacts/images. Key: `ThreadState`, `merge_artifacts`, `merge_viewed_images`, `SandboxState` [SOURCE_CODE]

## backend/packages/harness/deerflow/agents/checkpointer/

- `__init__.py` - Package initializer exposing checkpointer factory and context helpers. Key: `make_checkpointer`, `checkpointer_context`, `get_checkpointer`, `reset_checkpointer` [SOURCE_CODE]
- `async_provider.py` - Async factory providing a checkpointer context manager. Key: `_async_checkpointer`, `make_checkpointer` [SOURCE_CODE]
- `provider.py` - Sync checkpointer singleton and context manager. Key: `_sync_checkpointer_cm`, `get_checkpointer`, `reset_checkpointer`, `checkpointer_context`, `SQLITE_INSTALL` [SOURCE_CODE]

## backend/packages/harness/deerflow/agents/lead_agent/

- `agent.py` - Factory and middleware assembly for the lead LangChain agent (runtime model & middleware orchestration). Key: `_resolve_model_name`, `_create_summarization_middleware`, `_create_todo_list_middleware`, `_build_middlewares`, `make_lead_agent` [SOURCE_CODE]
- `prompt.py` - Builds the lead agent's system prompt and manages a background cache of enabled skills for prompt injection. Key: `_load_enabled_skills_sync`, `_start_enabled_skills_refresh_thread`, `_refresh_enabled_skills_cache_worker`, `_ensure_enabled_skills_cache`, `_invalidate_enabled_skills_cache` [SOURCE_CODE]

## backend/packages/harness/deerflow/agents/memory/

- `__init__.py` - Memory subsystem public exports and helpers. Key: `MEMORY_UPDATE_PROMPT`, `FACT_EXTRACTION_PROMPT`, `MemoryUpdateQueue`, `MemoryStorage`, `MemoryUpdater` [SOURCE_CODE]
- `prompt.py` - Prompt templates and formatting helpers for memory extraction/injection. Key: `MEMORY_UPDATE_PROMPT`, `FACT_EXTRACTION_PROMPT`, `format_memory_for_injection`, `format_conversation_for_update`, `_count_tokens` [SOURCE_CODE]
- `queue.py` - Debounced memory update queue for batching conversation contexts. Key: `ConversationContext`, `MemoryUpdateQueue`, `get_memory_queue` [SOURCE_CODE]
- `storage.py` - Memory storage implementations and factory. Key: `create_empty_memory`, `MemoryStorage`, `FileMemoryStorage`, `get_memory_storage` [SOURCE_CODE]
- `updater.py` - LLM-driven memory updater and helpers for CRUD and persistence of 'facts' and summaries. Key: `_create_empty_memory`, `_save_memory_to_file`, `get_memory_data`, `reload_memory_data`, `import_memory_data` [SOURCE_CODE]

## backend/packages/harness/deerflow/agents/middlewares/

- `clarification_middleware.py` - Middleware to intercept clarification tool calls and present questions. Key: `ClarificationMiddlewareState`, `ClarificationMiddleware`, `_format_clarification_message`, `_handle_clarification` [SOURCE_CODE]
- `dangling_tool_call_middleware.py` - Middleware that injects placeholder ToolMessages for interrupted tool calls. Key: `DanglingToolCallMiddleware`, `_build_patched_messages`, `wrap_model_call`, `awrap_model_call` [SOURCE_CODE]
- `deferred_tool_filter_middleware.py` - Middleware that filters deferred tool schemas from model binding. Key: `DeferredToolFilterMiddleware`, `_filter_tools`, `wrap_model_call`, `awrap_model_call` [SOURCE_CODE]
- `llm_error_handling_middleware.py` - Middleware that retries/translates LLM errors into user-friendly messages. Key: `LLMErrorHandlingMiddleware`, `_classify_error`, `_build_retry_delay_ms`, `wrap_model_call`, `awrap_model_call` [SOURCE_CODE]
- `loop_detection_middleware.py` - Agent middleware that detects repetitive tool-call loops and injects warnings or forces a hard stop.. Key: `_DEFAULT_WARN_THRESHOLD`, `_DEFAULT_HARD_LIMIT`, `_DEFAULT_WINDOW_SIZE`, `_DEFAULT_MAX_TRACKED_THREADS`, `_normalize_tool_call_args` [SOURCE_CODE]
- `memory_middleware.py` - Middleware that filters conversation and queues memory updates with correction/reinforcement signals.. Key: `_UPLOAD_BLOCK_RE`, `_CORRECTION_PATTERNS`, `_REINFORCEMENT_PATTERNS`, `MemoryMiddlewareState`, `_extract_message_text` [SOURCE_CODE]
- `sandbox_audit_middleware.py` - Middleware to audit and classify bash commands for security. Key: `SandboxAuditMiddleware`, `_classify_command`, `_split_compound_command`, `_HIGH_RISK_PATTERNS`, `_MEDIUM_RISK_PATTERNS` [SOURCE_CODE]
- `subagent_limit_middleware.py` - Middleware to cap concurrent subagent task tool calls per response. Key: `MIN_SUBAGENT_LIMIT`, `MAX_SUBAGENT_LIMIT`, `_clamp_subagent_limit`, `SubagentLimitMiddleware`, `_truncate_task_calls` [SOURCE_CODE]
- `thread_data_middleware.py` - Middleware that exposes per-thread filesystem paths for runs. Key: `ThreadDataMiddlewareState`, `ThreadDataMiddleware`, `_get_thread_paths` [SOURCE_CODE]
- `title_middleware.py` - Middleware that auto-generates thread titles after first exchange. Key: `TitleMiddlewareState`, `TitleMiddleware`, `_build_title_prompt` [SOURCE_CODE]
- `todo_middleware.py` - Todo middleware that injects reminders when todo context is lost. Key: `TodoMiddleware`, `_todos_in_messages`, `_reminder_in_messages`, `_format_todos` [SOURCE_CODE]
- `token_usage_middleware.py` - Middleware that logs LLM token usage metadata. Key: `TokenUsageMiddleware`, `_log_usage` [SOURCE_CODE]
- `tool_error_handling_middleware.py` - Middleware that converts tool exceptions into error ToolMessages and builds runtime middleware sets. Key: `ToolErrorHandlingMiddleware`, `_build_runtime_middlewares`, `build_lead_runtime_middlewares`, `build_subagent_runtime_middlewares` [SOURCE_CODE]
- `uploads_middleware.py` - Middleware that injects uploaded-file metadata, outlines and previews into the last human message.. Key: `_OUTLINE_PREVIEW_LINES`, `_extract_outline_for_file`, `UploadsMiddlewareState`, `UploadsMiddleware`, `_files_from_kwargs` [SOURCE_CODE]
- `view_image_middleware.py` - Middleware that injects viewed image details into the conversation before LLM calls. Key: `ViewImageMiddlewareState`, `ViewImageMiddleware`, `_all_tools_completed` [SOURCE_CODE]

## backend/packages/harness/deerflow/community/aio_sandbox/

- `__init__.py` - Package exports for aio_sandbox community sandbox components. Key: `AioSandbox`, `AioSandboxProvider`, `SandboxBackend`, `LocalContainerBackend`, `RemoteSandboxBackend` [SOURCE_CODE]
- `aio_sandbox.py` - AIO Docker-backed sandbox client for remote file/exec ops. Key: `AioSandbox`, `execute_command`, `grep`, `_ERROR_OBSERVATION_SIGNATURE` [SOURCE_CODE]
- `aio_sandbox_provider.py` - Manages lifecycle and pooling of AIO sandbox containers/backends. Key: `AioSandboxProvider`, `_deterministic_sandbox_id`, `_get_thread_mounts`, `_discover_or_create_with_lock`, `_cleanup_idle_sandboxes` [SOURCE_CODE]
- `backend.py` - Abstract base and readiness helper for sandbox backends. Key: `SandboxBackend`, `wait_for_sandbox_ready`, `SandboxInfo` [SOURCE_CODE]
- `local_backend.py` - Local container backend for provisioning sandbox containers. Key: `_format_container_mount`, `LocalContainerBackend`, `_start_container`, `_get_container_port` [SOURCE_CODE]
- `remote_backend.py` - Remote sandbox backend using a provisioner HTTP API. Key: `RemoteSandboxBackend`, `_provisioner_create`, `_provisioner_destroy`, `_provisioner_is_alive`, `_provisioner_discover` [SOURCE_CODE]
- `sandbox_info.py` - Dataclass storing sandbox metadata for discovery and persistence. Key: `SandboxInfo`, `to_dict`, `from_dict` [SOURCE_CODE]

## backend/packages/harness/deerflow/community/ddg_search/

- `tools.py` - DuckDuckGo-based web search tool for use by agents. Key: `_search_text`, `web_search_tool` [SOURCE_CODE]

## backend/packages/harness/deerflow/community/firecrawl/

- `tools.py` - Firecrawl-based web search and fetch tools for agents. Key: `_get_firecrawl_client`, `web_search_tool`, `web_fetch_tool` [SOURCE_CODE]

## backend/packages/harness/deerflow/community/image_search/

- `tools.py` - DuckDuckGo image search tool returning image URLs and metadata. Key: `_search_images`, `image_search_tool` [SOURCE_CODE]

## backend/packages/harness/deerflow/community/infoquest/

- `infoquest_client.py` - Client wrapper for InfoQuest search and fetch APIs. Key: `InfoQuestClient`, `fetch`, `web_search`, `clean_results` [SOURCE_CODE]
- `tools.py` - InfoQuest community tools: web_search, web_fetch, image_search. Key: `_get_infoquest_client`, `web_search_tool`, `web_fetch_tool`, `image_search_tool`, `readability_extractor` [SOURCE_CODE]

## backend/packages/harness/deerflow/community/jina_ai/

- `jina_client.py` - Async wrapper for Jina r.jina.ai crawl API. Key: `JinaClient`, `crawl` [SOURCE_CODE]
- `tools.py` - LangChain tool for web fetching using Jina and readability extraction. Key: `readability_extractor`, `web_fetch_tool` [SOURCE_CODE]

## backend/packages/harness/deerflow/community/tavily/

- `tools.py` - Tavily-backed web_search and web_fetch tools. Key: `_get_tavily_client`, `web_search_tool`, `web_fetch_tool` [SOURCE_CODE]

## backend/packages/harness/deerflow/config/

- `__init__.py` - Config accessors and exported config types. Key: `get_app_config`, `get_paths`, `get_memory_config` [SOURCE_CODE]
- `acp_config.py` - ACP agent configuration model and loader. Key: `ACPAgentConfig`, `load_acp_config_from_dict`, `get_acp_agents` [SOURCE_CODE]
- `agents_config.py` - Load and list custom agent configs and SOUL files. Key: `AgentConfig`, `load_agent_config`, `load_agent_soul`, `list_custom_agents` [SOURCE_CODE]
- `app_config.py` - Application configuration loader, cache, and runtime override utilities for DeerFlow. Key: `AppConfig`, `_default_config_candidates`, `resolve_config_path`, `from_file`, `_check_config_version` [SOURCE_CODE]
- `checkpointer_config.py` - Pydantic config model and global accessor for checkpointer settings. Key: `CheckpointerConfig`, `_checkpointer_config`, `get_checkpointer_config`, `set_checkpointer_config`, `load_checkpointer_config_from_dict` [SOURCE_CODE]
- `extensions_config.py` - Extensions configuration loader for MCP servers and skill toggles. Key: `McpOAuthConfig`, `McpServerConfig`, `ExtensionsConfig`, `get_extensions_config`, `resolve_env_variables` [SOURCE_CODE]
- `guardrails_config.py` - Global guardrail (pre-tool-call auth) configuration. Key: `GuardrailProviderConfig`, `GuardrailsConfig`, `get_guardrails_config`, `load_guardrails_config_from_dict`, `reset_guardrails_config` [SOURCE_CODE]
- `memory_config.py` - Memory subsystem configuration model and loader. Key: `MemoryConfig`, `get_memory_config`, `set_memory_config`, `load_memory_config_from_dict` [SOURCE_CODE]
- `model_config.py` - Pydantic model describing LLM model configuration. Key: `ModelConfig` [SOURCE_CODE]
- `paths.py` - Centralized filesystem path utilities and sandbox thread directory management. Key: `VIRTUAL_PATH_PREFIX`, `Paths`, `get_paths`, `resolve_path`, `_join_host_path` [SOURCE_CODE]
- `sandbox_config.py` - Pydantic models for sandbox provider and mount configuration. Key: `VolumeMountConfig`, `SandboxConfig` [SOURCE_CODE]
- `skill_evolution_config.py` - Config for agent-managed skill evolution. Key: `SkillEvolutionConfig` [SOURCE_CODE]
- `skills_config.py` - Configuration helper for locating and mounting skills. Key: `SkillsConfig`, `_default_repo_root`, `get_skills_path`, `get_skill_container_path` [SOURCE_CODE]
- `stream_bridge_config.py` - Stream bridge backend configuration (memory or redis). Key: `StreamBridgeConfig`, `get_stream_bridge_config`, `set_stream_bridge_config`, `load_stream_bridge_config_from_dict` [SOURCE_CODE]
- `subagents_config.py` - Configuration and overrides for subagent timeouts and turns. Key: `SubagentOverrideConfig`, `SubagentsAppConfig`, `load_subagents_config_from_dict`, `get_subagents_app_config` [SOURCE_CODE]
- `summarization_config.py` - Conversation summarization configuration and context sizing. Key: `ContextSize`, `SummarizationConfig`, `get_summarization_config`, `set_summarization_config`, `load_summarization_config_from_dict` [SOURCE_CODE]
- `title_config.py` - Config for automatic conversation title generation. Key: `TitleConfig`, `get_title_config`, `set_title_config`, `load_title_config_from_dict` [SOURCE_CODE]
- `token_usage_config.py` - Toggle for token usage tracking middleware. Key: `TokenUsageConfig` [SOURCE_CODE]
- `tool_config.py` - Tool and tool-group configuration models. Key: `ToolGroupConfig`, `ToolConfig` [SOURCE_CODE]
- `tool_search_config.py` - Config for deferred MCP tool loading (tool_search). Key: `ToolSearchConfig`, `get_tool_search_config`, `load_tool_search_config_from_dict` [SOURCE_CODE]
- `tracing_config.py` - Env-driven tracing configuration for LangSmith and Langfuse. Key: `LangSmithTracingConfig`, `LangfuseTracingConfig`, `TracingConfig`, `get_tracing_config`, `validate_enabled_tracing_providers` [SOURCE_CODE]

## backend/packages/harness/deerflow/guardrails/

- `__init__.py` - Guardrails package exports (providers, middleware, types). Key: `AllowlistProvider`, `GuardrailMiddleware`, `GuardrailProvider` [SOURCE_CODE]
- `builtin.py` - Built-in allowlist/denylist guardrail provider. Key: `AllowlistProvider`, `evaluate`, `aevaluate` [SOURCE_CODE]
- `middleware.py` - Middleware that enforces guardrail decisions on tool calls. Key: `GuardrailMiddleware`, `_build_request`, `_build_denied_message`, `wrap_tool_call`, `awrap_tool_call` [SOURCE_CODE]
- `provider.py` - Guardrail provider protocol and data types. Key: `GuardrailRequest`, `GuardrailReason`, `GuardrailDecision`, `GuardrailProvider` [SOURCE_CODE]

## backend/packages/harness/deerflow/mcp/

- `__init__.py` - MCP utilities export (tools cache, client builders). Key: `get_cached_mcp_tools`, `initialize_mcp_tools`, `build_server_params` [SOURCE_CODE]
- `cache.py` - Lazy cache and initializer for MCP tools. Key: `_mcp_tools_cache`, `initialize_mcp_tools`, `get_cached_mcp_tools`, `reset_mcp_tools_cache` [SOURCE_CODE]
- `client.py` - Builds MCP server parameter and servers config. Key: `build_server_params`, `build_servers_config` [SOURCE_CODE]
- `oauth.py` - Acquire, cache and refresh OAuth tokens and inject Authorization headers. Key: `_OAuthToken`, `OAuthTokenManager`, `build_oauth_tool_interceptor`, `get_initial_oauth_headers` [SOURCE_CODE]
- `tools.py` - Loader for MCP tools with sync wrappers and OAuth interceptors. Key: `get_mcp_tools`, `_make_sync_tool_wrapper`, `_SYNC_TOOL_EXECUTOR` [SOURCE_CODE]

## backend/packages/harness/deerflow/models/

- `claude_provider.py` - Custom Claude chat model with OAuth support, prompt caching, and retries. Key: `ClaudeChatModel`, `OAUTH_BILLING_HEADER`, `THINKING_BUDGET_RATIO` [SOURCE_CODE]
- `credential_loader.py` - Auto-loads Claude Code and Codex CLI credentials from env/files. Key: `ClaudeCodeCredential`, `CodexCliCredential`, `load_claude_code_credential`, `load_codex_cli_credential`, `_read_secret_from_file_descriptor` [SOURCE_CODE]
- `factory.py` - Factory to construct chat model instances from app config. Key: `create_chat_model`, `_deep_merge_dicts`, `_vllm_disable_chat_template_kwargs` [SOURCE_CODE]
- `openai_codex_provider.py` - LangChain chat model adapter for ChatGPT Codex Responses API. Key: `CodexChatModel`, `_convert_messages`, `_stream_response`, `_parse_response`, `bind_tools` [SOURCE_CODE]
- `patched_deepseek.py` - Patched ChatDeepSeek adapter that preserves reasoning_content across turns. Key: `PatchedChatDeepSeek`, `_get_request_payload` [SOURCE_CODE]
- `patched_minimax.py` - Adapter preserving MiniMax reasoning output into LangChain messages. Key: `PatchedChatMiniMax`, `_extract_reasoning_text`, `_strip_inline_think_tags`, `_with_reasoning_content` [SOURCE_CODE]
- `patched_openai.py` - Patched ChatOpenAI to preserve thought_signature for tool calls. Key: `PatchedChatOpenAI`, `_restore_tool_call_signatures` [SOURCE_CODE]
- `vllm_provider.py` - vLLM-compatible ChatOpenAI wrapper preserving reasoning fields and streaming deltas. Key: `VllmChatModel`, `_convert_delta_to_message_chunk_with_reasoning`, `_create_chat_result`, `_normalize_vllm_chat_template_kwargs`, `_reasoning_to_text` [SOURCE_CODE]

## backend/packages/harness/deerflow/reflection/

- `__init__.py` - Re-exports reflection resolver utilities. Key: `resolve_class`, `resolve_variable` [SOURCE_CODE]
- `resolvers.py` - Resolve classes/variables by module path with helpful missing-dependency hints. Key: `MODULE_TO_PACKAGE_HINTS`, `_build_missing_dependency_hint`, `resolve_variable`, `resolve_class` [SOURCE_CODE]

## backend/packages/harness/deerflow/runtime/

- `__init__.py` - Re-exports the runtime public API for runs and streaming. Key: `run_agent`, `RunManager`, `serialize`, `make_stream_bridge` [SOURCE_CODE]
- `serialization.py` - Canonical serialization utilities for LangChain/LangGraph objects. Key: `serialize_lc_object`, `serialize_channel_values`, `serialize_messages_tuple`, `serialize` [SOURCE_CODE]

## backend/packages/harness/deerflow/runtime/runs/

- `__init__.py` - Exports run lifecycle manager, schemas, and worker runner. Key: `RunManager`, `RunRecord`, `RunStatus`, `DisconnectMode`, `run_agent` [SOURCE_CODE]
- `manager.py` - Async-safe in-memory run registry and lifecycle manager. Key: `RunRecord`, `RunManager`, `create_or_reject`, `ConflictError` [SOURCE_CODE]
- `schemas.py` - Enums for run status and disconnect behavior. Key: `RunStatus`, `DisconnectMode` [SOURCE_CODE]
- `worker.py` - Async worker that runs agents and streams LangGraph events. Key: `run_agent`, `_unpack_stream_item`, `_lg_mode_to_sse_event` [SOURCE_CODE]

## backend/packages/harness/deerflow/runtime/store/

- `__init__.py` - Re-exports async and sync store factories for the runtime. Key: `make_store`, `get_store`, `store_context` [SOURCE_CODE]
- `_sqlite_utils.py` - SQLite connection string and parent-dir helpers. Key: `resolve_sqlite_conn_str`, `ensure_sqlite_parent_dir` [SOURCE_CODE]
- `async_provider.py` - Async store factory that mirrors the configured checkpointer. Key: `_async_store`, `make_store` [SOURCE_CODE]
- `provider.py` - Sync store singleton and context manager for CLI/embedded use. Key: `_sync_store_cm`, `get_store`, `store_context` [SOURCE_CODE]

## backend/packages/harness/deerflow/runtime/stream_bridge/

- `__init__.py` - Re-exports stream bridge protocol and memory implementation. Key: `make_stream_bridge`, `StreamBridge`, `MemoryStreamBridge` [SOURCE_CODE]
- `async_provider.py` - Async factory for creating a stream bridge instance. Key: `make_stream_bridge` [SOURCE_CODE]
- `base.py` - Abstract StreamBridge protocol and event model. Key: `StreamEvent`, `HEARTBEAT_SENTINEL`, `StreamBridge` [SOURCE_CODE]
- `memory.py` - In-memory per-run event stream bridge for SSE/streaming. Key: `MemoryStreamBridge`, `_RunStream`, `_next_id` [SOURCE_CODE]

## backend/packages/harness/deerflow/sandbox/

- `__init__.py` - Sandbox API re-exports. Key: `Sandbox`, `SandboxProvider`, `get_sandbox_provider` [SOURCE_CODE]
- `exceptions.py` - Structured exceptions for sandbox operations. Key: `SandboxError`, `SandboxNotFoundError`, `SandboxCommandError`, `SandboxFileError` [SOURCE_CODE]
- `file_operation_lock.py` - Per-sandbox per-path file operation locking utilities. Key: `_FILE_OPERATION_LOCKS`, `get_file_operation_lock_key`, `get_file_operation_lock` [SOURCE_CODE]
- `middleware.py` - Middleware to allocate and release sandboxes per agent/thread. Key: `SandboxMiddlewareState`, `SandboxMiddleware`, `_acquire_sandbox`, `before_agent`, `after_agent` [SOURCE_CODE]
- `sandbox.py` - Abstract Sandbox interface for file and command operations. Key: `Sandbox` [SOURCE_CODE]
- `sandbox_provider.py` - Sandbox provider singleton management and abstract provider interface. Key: `SandboxProvider`, `get_sandbox_provider`, `reset_sandbox_provider`, `shutdown_sandbox_provider`, `set_sandbox_provider` [SOURCE_CODE]
- `search.py` - Filesystem glob and grep utilities with ignore patterns and size limits. Key: `GrepMatch`, `find_glob_matches`, `find_grep_matches`, `IGNORE_PATTERNS` [SOURCE_CODE]
- `security.py` - Policy helpers that gate sandbox host-bash capabilities. Key: `uses_local_sandbox_provider`, `is_host_bash_allowed`, `LOCAL_HOST_BASH_DISABLED_MESSAGE` [SOURCE_CODE]
- `tools.py` - Sandbox-related file-path, command validation and built-in sandbox tools (bash, glob, grep, read/write).. Key: `_get_skills_container_path`, `_get_skills_host_path`, `_is_skills_path`, `_resolve_skills_path`, `_is_acp_workspace_path` [SOURCE_CODE]

## backend/packages/harness/deerflow/sandbox/local/

- `list_dir.py` - Directory lister with depth and ignore patterns for sandbox. Key: `list_dir` [SOURCE_CODE]
- `local_sandbox.py` - Local sandbox implementation that maps container-style paths to host paths and enforces read-only mounts.. Key: `PathMapping`, `LocalSandbox`, `_resolve_path`, `_reverse_resolve_path`, `_is_read_only_path` [SOURCE_CODE]
- `local_sandbox_provider.py` - Local sandbox provider that maps container paths to host paths. Key: `LocalSandboxProvider`, `_setup_path_mappings`, `_singleton` [SOURCE_CODE]

## backend/packages/harness/deerflow/skills/

- `__init__.py` - Skills package exports for loader/installer/types and validation. Key: `__all__` [SOURCE_CODE]
- `installer.py` - Safe installation logic for .skill archive packages. Key: `SkillAlreadyExistsError`, `is_unsafe_zip_member`, `safe_extract_skill_archive`, `resolve_skill_dir_from_archive`, `install_skill_from_archive` [SOURCE_CODE]
- `loader.py` - Discovers and loads skills from public/custom directories. Key: `get_skills_root_path`, `load_skills` [SOURCE_CODE]
- `manager.py` - Utilities for managing custom skills, validation and history. Key: `validate_skill_name`, `ensure_safe_support_path`, `validate_skill_markdown_content`, `atomic_write`, `append_history` [SOURCE_CODE]
- `parser.py` - Parse SKILL.md front matter into Skill objects. Key: `parse_skill_file` [SOURCE_CODE]
- `security_scanner.py` - AI-driven security scanner for skill content before disk writes. Key: `ScanResult`, `_extract_json_object`, `scan_skill_content` [SOURCE_CODE]
- `types.py` - Dataclass representing a skill and helpers for its filesystem/container paths. Key: `Skill`, `Skill.skill_path`, `Skill.get_container_path`, `Skill.get_container_file_path` [SOURCE_CODE]
- `validation.py` - Validation utilities for SKILL.md frontmatter. Key: `ALLOWED_FRONTMATTER_PROPERTIES`, `_validate_skill_frontmatter` [SOURCE_CODE]

## backend/packages/harness/deerflow/subagents/

- `__init__.py` - Subagents package exports. Key: `__all__` [SOURCE_CODE]
- `config.py` - Dataclass for configuring subagent behavior and limits. Key: `SubagentConfig` [SOURCE_CODE]
- `executor.py` - Engine for running subagents synchronously or in background threads. Key: `SubagentStatus`, `SubagentResult`, `_filter_tools`, `SubagentExecutor`, `execute_async` [SOURCE_CODE]
- `registry.py` - Registry and access helpers for built-in subagent configurations. Key: `get_subagent_config`, `list_subagents`, `get_subagent_names`, `get_available_subagent_names` [SOURCE_CODE]

## backend/packages/harness/deerflow/subagents/builtins/

- `__init__.py` - Registry of built-in subagent configurations. Key: `BUILTIN_SUBAGENTS`, `GENERAL_PURPOSE_CONFIG`, `BASH_AGENT_CONFIG` [SOURCE_CODE]
- `bash_agent.py` - Subagent configuration for bash command specialist. Key: `BASH_AGENT_CONFIG` [SOURCE_CODE]
- `general_purpose.py` - Configuration for general-purpose subagent. Key: `GENERAL_PURPOSE_CONFIG` [SOURCE_CODE]

## backend/packages/harness/deerflow/tools/

- `__init__.py` - Tools package entry with lazy export for skill management tool. Key: `get_available_tools`, `__getattr__` [SOURCE_CODE]
- `skill_manage_tool.py` - Tool implementation to create/edit/patch/delete custom skills. Key: `skill_manage_tool`, `_skill_manage_impl`, `_scan_or_raise`, `_get_lock`, `skill_manage_tool.func` [SOURCE_CODE]
- `tools.py` - Compute and load available LLM tools based on config and runtime flags. Key: `get_available_tools`, `BUILTIN_TOOLS`, `SUBAGENT_TOOLS`, `_is_host_bash_tool` [SOURCE_CODE]

## backend/packages/harness/deerflow/tools/builtins/

- `__init__.py` - Re-exports built-in agent tools. Key: `ask_clarification_tool`, `present_file_tool`, `task_tool` [SOURCE_CODE]
- `clarification_tool.py` - Clarification tool stub invoked to request user input. Key: `ask_clarification_tool` [SOURCE_CODE]
- `invoke_acp_agent_tool.py` - Tool builder to invoke external ACP-compatible agents. Key: `_InvokeACPAgentInput`, `build_invoke_acp_agent_tool`, `_invoke`, `_get_work_dir` [SOURCE_CODE]
- `present_file_tool.py` - Tool to mark sandbox output files as user-visible artifacts. Key: `OUTPUTS_VIRTUAL_PREFIX`, `_normalize_presented_filepath`, `present_file_tool` [SOURCE_CODE]
- `setup_agent_tool.py` - Tool that creates a custom DeerFlow agent directory and writes SOUL/config files. Key: `setup_agent` [SOURCE_CODE]
- `task_tool.py` - Async LangChain tool that delegates work to background subagents and streams lifecycle events.. Key: `task_tool`, `cleanup_when_done`, `log_cleanup_failure` [SOURCE_CODE]
- `tool_search.py` - Deferred tool discovery and runtime tool schema fetcher. Key: `DeferredToolRegistry`, `DeferredToolEntry`, `tool_search`, `get_deferred_registry / set_deferred_registry / reset_deferred_registry` [SOURCE_CODE]
- `view_image_tool.py` - Tool to read an image file, encode as base64 and publish to run state. Key: `view_image_tool` [SOURCE_CODE]

## backend/packages/harness/deerflow/tracing/

- `factory.py` - Factory to build tracing callback handlers for enabled providers. Key: `build_tracing_callbacks`, `_create_langsmith_tracer`, `_create_langfuse_handler` [SOURCE_CODE]

## backend/packages/harness/deerflow/uploads/

- `__init__.py` - Re-exports uploads manager utilities and exceptions. Key: `get_uploads_dir`, `ensure_uploads_dir`, `claim_unique_filename`, `PathTraversalError` [SOURCE_CODE]
- `manager.py` - Upload file management, validation and listing utilities. Key: `PathTraversalError`, `validate_thread_id`, `normalize_filename`, `list_files_in_dir`, `delete_file_safe` [SOURCE_CODE]

## backend/packages/harness/deerflow/utils/

- `file_conversion.py` - Utilities for converting documents to Markdown and extracting outlines. Key: `convert_file_to_markdown`, `extract_outline`, `_pymupdf_output_too_sparse` [SOURCE_CODE]
- `network.py` - Thread-safe port allocator and convenience port utilities. Key: `PortAllocator`, `get_free_port`, `release_port`, `_global_port_allocator` [SOURCE_CODE]
- `readability.py` - Extracts readable article content from HTML and converts to markdown/messages. Key: `Article`, `ReadabilityExtractor`, `Article.to_markdown`, `Article.to_message` [SOURCE_CODE]

## backend/tests/

- `test_channels.py` - Unit tests for the channels subsystem: MessageBus, ChannelStore, Channel base, response extraction, and ChannelManager.. Key: `_run`, `_wait_for`, `TestMessageBus`, `TestChannelStore`, `DummyChannel` [TEST]
- `test_checkpointer.py` - Unit tests for checkpointer config, factory, and client fallback. Key: `TestCheckpointerConfig`, `TestGetCheckpointer`, `TestAsyncCheckpointer`, `TestClientCheckpointerFallback` [TEST]
- `test_client.py` - Unit tests verifying DeerFlowClient behavior: construction, configuration queries, streaming/chat semantics, and message serialization.. Key: `mock_app_config`, `client`, `TestClientInit`, `TestConfigQueries`, `TestStream` [TEST]
- `test_client_live.py` - Live integration tests for DeerFlowClient using real API and sandbox. Key: `client`, `thread_tmp`, `TestLiveBasicChat`, `TestLiveToolUse`, `TestLiveFileUpload` [TEST]
- `test_custom_agent.py` - Unit tests for custom agent configuration, filesystem and API endpoints. Key: `_make_paths`, `_write_agent`, `TestPaths`, `TestLoadAgentConfig`, `TestAgentsAPI` [TEST]
- `test_docker_sandbox_mode_detection.py` - Regression tests for detect_sandbox_mode logic in docker.sh. Key: `_detect_mode_with_config`, `test_detect_mode_defaults_to_local_when_config_missing` [TEST]
- `test_infoquest_client.py` - Tests for InfoQuest web client and its tooling wrappers. Key: `TestInfoQuestClient`, `TestImageSearch` [TEST]
- `test_lead_agent_model_resolution.py` - Unit tests for lead agent model resolution and middleware assembly behavior. Key: `test_resolve_model_name_falls_back_to_default`, `test_make_lead_agent_disables_thinking_when_model_does_not_support_it`, `test_create_summarization_middleware_uses_configured_model_alias` [TEST]
- `test_lead_agent_prompt.py` - Unit tests validating prompt generation and background skills cache behavior (mounts, warming, invalidation, concurrency). Key: `test_build_custom_mounts_section_returns_empty_when_no_mounts`, `test_build_custom_mounts_section_lists_configured_mounts`, `test_apply_prompt_template_includes_custom_mounts`, `test_refresh_skills_system_prompt_cache_async_reloads_immediately`, `test_clear_cache_does_not_spawn_parallel_refresh_workers` [TEST]
- `test_lead_agent_skills.py` - Unit tests for skill section rendering and skill selection propagation into make_lead_agent. Key: `_make_skill`, `test_get_skills_prompt_section_returns_empty_when_no_skills_match`, `test_get_skills_prompt_section_returns_all_when_available_skills_is_none`, `test_get_skills_prompt_section_cache_respects_skill_evolution_toggle`, `test_make_lead_agent_empty_skills_passed_correctly` [TEST]
- `test_local_sandbox_provider_mounts.py` - Unit tests for LocalSandbox path mappings, read-only semantics, command substitution, and LocalSandboxProvider mapping setup.. Key: `TestPathMapping`, `TestLocalSandboxPathResolution`, `TestReadOnlyPath`, `TestMultipleMounts`, `TestLocalSandboxProviderMounts` [TEST]
- `test_loop_detection_middleware.py` - Unit tests covering hashing, normalization, and enforcement logic of LoopDetectionMiddleware.. Key: `_make_runtime`, `_make_state`, `_bash_call`, `TestHashToolCalls`, `TestLoopDetection` [TEST]
- `test_memory_prompt_injection.py` - Unit tests for memory formatting and confidence coercion. Key: `test_format_memory_includes_facts_section`, `test_coerce_confidence_nan_falls_back_to_default` [TEST]
- `test_memory_queue.py` - Unit tests for memory update queue behavior and flag propagation to MemoryUpdater. Key: `test_queue_add_preserves_existing_correction_flag_for_same_thread`, `test_process_queue_forwards_correction_flag_to_updater`, `test_queue_add_preserves_existing_reinforcement_flag_for_same_thread`, `test_process_queue_forwards_reinforcement_flag_to_updater` [TEST]
- `test_memory_router.py` - Unit tests for the memory Gateway router verifying import/export and CRUD behaviors and error mappings.. Key: `_sample_memory`, `test_export_memory_route_returns_current_memory`, `test_import_memory_route_returns_imported_memory`, `test_export_memory_route_preserves_source_error`, `test_clear_memory_route_returns_cleared_memory` [TEST]
- `test_memory_updater.py` - Unit tests for memory updater CRUD, merging, deduplication and LLM response normalization. Key: `test_apply_updates_skips_existing_duplicate_and_preserves_removals`, `test_apply_updates_skips_same_batch_duplicates_and_keeps_source_metadata`, `test_apply_updates_preserves_threshold_and_max_facts_trimming`, `test_apply_updates_preserves_source_error`, `TestExtractText::test_list_string_chunks_join_without_separator` [TEST]
- `test_memory_upload_filtering.py` - Unit tests that verify upload-block filtering and correction/reinforcement signal detection for memory middleware/updater.. Key: `_UPLOAD_BLOCK`, `_human`, `_ai`, `TestFilterMessagesForMemory::test_upload_only_turn_is_excluded`, `TestDetectCorrection::test_detects_english_correction_signal` [TEST]
- `test_model_factory.py` - Unit tests for chat model factory behavior and thinking toggles. Key: `FakeChatModel`, `_patch_factory`, `test_thinking_enabled_merges_when_thinking_enabled`, `test_thinking_disabled_openai_gateway_format` [TEST]
- `test_sandbox_search_tools.py` - Unit tests for sandbox search utilities and glob/grep tool wrappers.. Key: `test_glob_tool_returns_virtual_paths_and_ignores_common_dirs`, `test_grep_tool_filters_by_glob_and_skips_binary_files`, `test_grep_tool_truncates_results`, `test_aio_sandbox_grep_parses_json`, `test_find_glob_matches_raises_not_a_directory` [TEST]
- `test_sandbox_tools_security.py` - Unit tests for sandbox path validation, command validation, mapping and masking security behaviors.. Key: `test_replace_virtual_path_maps_virtual_root_and_subpaths`, `test_replace_virtual_path_preserves_trailing_slash`, `test_replace_virtual_path_preserves_trailing_slash_windows_style`, `test_mask_local_paths_in_output_hides_host_paths`, `test_validate_local_tool_path_rejects_non_virtual_path` [TEST]
- `test_skills_custom_router.py` - Unit tests for custom skill management endpoints on the skills router.. Key: `_skill_content`, `_async_scan`, `_make_skill`, `test_custom_skills_router_lifecycle`, `test_custom_skill_rollback_blocked_by_scanner` [TEST]
- `test_sse_format.py` - Unit tests verifying SSE frame formatting produced by format_sse. Key: `_format_sse`, `test_sse_end_event_data_null`, `test_sse_metadata_event`, `test_sse_error_format` [TEST]
- `test_stream_bridge.py` - Unit tests for the in-memory StreamBridge implementation and replay/trim/END semantics. Key: `bridge`, `test_publish_subscribe`, `test_heartbeat`, `test_cleanup`, `test_history_is_bounded` [TEST]
- `test_suggestions_router.py` - Unit tests for suggestions parsing and model integration. Key: `test_strip_markdown_code_fence_removes_wrapping`, `test_parse_json_string_list_filters_invalid_items`, `test_generate_suggestions_parses_and_limits`, `test_generate_suggestions_returns_empty_on_model_error` [TEST]
- `test_task_tool_core_logic.py` - Unit tests covering core orchestration, polling and cancellation behavior of the task tool.. Key: `FakeSubagentStatus`, `_make_runtime`, `_run_task_tool`, `test_task_tool_emits_running_and_completed_events` [TEST]
- `test_title_middleware_core_logic.py` - Unit tests for TitleMiddleware title generation logic. Key: `TestTitleMiddlewareCoreLogic`, `_set_test_title_config`, `TitleMiddleware` [TEST]
- `test_uploads_manager.py` - Unit tests for shared upload manager helpers: normalization, path traversal, listing, and safe deletion.. Key: `TestNormalizeFilename`, `TestDeduplicateFilename`, `TestValidatePathTraversal`, `TestListFilesInDir`, `TestDeleteFileSafe` [TEST]
- `test_uploads_middleware_core_logic.py` - Unit tests validating parsing, formatting and injection logic of UploadsMiddleware.. Key: `_middleware`, `_runtime`, `_uploads_dir`, `_human`, `TestFilesFromKwargs` [TEST]
- `test_uploads_router.py` - Unit tests for the Gateway uploads router covering local vs non-local sandbox syncing, permission changes, conversion, and deletion.. Key: `test_upload_files_writes_thread_storage_and_skips_local_sandbox_sync`, `test_upload_files_syncs_non_local_sandbox_and_marks_markdown_file`, `test_upload_files_makes_non_local_files_sandbox_writable`, `test_upload_files_does_not_adjust_permissions_for_local_sandbox`, `test_make_file_sandbox_writable_adds_write_bits_for_regular_files` [TEST]

## docker/provisioner/

- `app.py` - A FastAPI-based service that provisions per-sandbox Kubernetes Pods and NodePort Services for DeerFlow sandboxes.. Key: `join_host_path`, `_validate_thread_id`, `KUBECONFIG_PATH`, `_init_k8s_client`, `_wait_for_kubeconfig` [SOURCE_CODE]

## frontend/

- `eslint.config.js` - Custom ESLint flat config for the frontend TypeScript codebase [CONFIG]
- `next.config.js` - Next.js configuration with internal service rewrites and i18n [CONFIG]
- `prettier.config.js` - Prettier configuration enabling Tailwind plugin [CONFIG]

## frontend/scripts/

- `save-demo.js` - CLI script to download and save a thread demo with assets [CLI]

## frontend/src/

- `env.js` - Environment schema and runtime environment loader/validator. Key: `env` [SOURCE_CODE]
- `mdx-components.ts` - MDX components wrapper that merges theme components. Key: `useMDXComponents` [SOURCE_CODE]

## frontend/src/app/

- `layout.tsx` - Next.js root layout with theme and i18n providers. Key: `metadata`, `RootLayout` [SOURCE_CODE]
- `page.tsx` - Next.js landing page component composing landing sections. Key: `LandingPage` [SOURCE_CODE]

## frontend/src/app/[lang]/docs/

- `layout.tsx` - Nextra docs layout that applies localization and page routing prefixes. Key: `DocLayout`, `formatPageRoute` [SOURCE_CODE]

## frontend/src/app/[lang]/docs/[[...mdxPath]]/

- `page.tsx` - Nextra MDX page wrapper that renders localized documentation. Key: `generateStaticParams`, `generateMetadata`, `default` [SOURCE_CODE]

## frontend/src/app/workspace/

- `layout.tsx` - Workspace layout wrapper providing sidebar and global providers. Key: `WorkspaceLayout`, `parseSidebarOpenCookie` [SOURCE_CODE]
- `page.tsx` - Workspace route that redirects to demo thread or new chat. Key: `WorkspacePage` [SOURCE_CODE]

## frontend/src/app/workspace/agents/

- `page.tsx` - Workspace page that renders the agent gallery. Key: `AgentsPage` [SOURCE_CODE]

## frontend/src/app/workspace/agents/[agent_name]/chats/[thread_id]/

- `page.tsx` - Client React page that renders an agent-scoped chat UI for a specific thread. Key: `AgentChatPage`, `handleSubmit`, `handleStop` [SOURCE_CODE]

## frontend/src/app/workspace/agents/new/

- `page.tsx` - UI page to create a new agent: name validation, bootstrap chat, and explicit save flow. Key: `NAME_RE`, `SAVE_HINT_STORAGE_KEY`, `AGENT_READ_RETRY_DELAYS_MS`, `wait`, `getAgentWithRetry` [SOURCE_CODE]

## frontend/src/app/workspace/chats/[thread_id]/

- `layout.tsx` - Chat route layout that provides workspace context providers. Key: `ChatLayout` [SOURCE_CODE]
- `page.tsx` - Client-side React page that mounts the generic chat interface for a thread. Key: `ChatPage`, `MESSAGE_LIST_DEFAULT_PADDING_BOTTOM`, `useThreadStream`, `useThreadSettings` [SOURCE_CODE]

## frontend/src/components/

- `query-client-provider.tsx` - React Query client provider component. Key: `queryClient`, `QueryClientProvider` [SOURCE_CODE]
- `theme-provider.tsx` - Theme provider that forces dark theme on the root path. Key: `ThemeProvider` [SOURCE_CODE]

## frontend/src/components/ai-elements/

- `artifact.tsx` - Composable Artifact UI primitives for displaying artifacts. Key: `Artifact`, `ArtifactAction`, `ArtifactHeader` [SOURCE_CODE]
- `canvas.tsx` - ReactFlow-based canvas wrapper for graph editing. Key: `Canvas` [SOURCE_CODE]
- `chain-of-thought.tsx` - Collapsible chain-of-thought UI components for reasoning steps. Key: `ChainOfThought`, `ChainOfThoughtHeader`, `ChainOfThoughtStep` [SOURCE_CODE]
- `checkpoint.tsx` - Small UI primitives for checkpoint display, icon, and trigger with tooltip. Key: `Checkpoint`, `CheckpointIcon`, `CheckpointTrigger` [SOURCE_CODE]
- `code-block.tsx` - Client-side code highlighter and copyable code block component. Key: `highlightCode`, `CodeBlock`, `CodeBlockCopyButton`, `CodeBlockContext`, `lineNumberTransformer` [SOURCE_CODE]
- `connection.tsx` - SVG connection line renderer for graph nodes. Key: `Connection` [SOURCE_CODE]
- `context.tsx` - Hovercard UI showing model context usage and cost breakdown. Key: `ContextContext`, `Context`, `ContextTrigger`, `ContextContentHeader`, `ContextContentFooter` [SOURCE_CODE]
- `controls.tsx` - Styled wrapper around Controls primitive for toolbar groups. Key: `Controls` [SOURCE_CODE]
- `conversation.tsx` - Conversation container, content and scroll controls. Key: `Conversation`, `ConversationContent`, `ConversationEmptyState`, `ConversationScrollButton` [SOURCE_CODE]
- `edge.tsx` - Custom edge components for graph visualization with animation and temporary style. Key: `Temporary`, `Animated`, `getHandleCoordsByPosition`, `getEdgeParams` [SOURCE_CODE]
- `image.tsx` - Image component that renders base64/uint8 generated images inline. Key: `Image` [SOURCE_CODE]
- `loader.tsx` - Spinner loader icon and wrapper component. Key: `LoaderIcon`, `Loader` [SOURCE_CODE]
- `message.tsx` - Comprehensive messaging UI primitives with branching and attachments. Key: `Message`, `MessageBranch`, `MessageBranchContent`, `MessageResponse`, `MessageAttachment` [SOURCE_CODE]
- `model-selector.tsx` - Model selection dialog and UI primitives. Key: `ModelSelector`, `ModelSelectorContent`, `ModelSelectorLogo`, `ModelSelectorDialog` [SOURCE_CODE]
- `node.tsx` - Graph node UI primitives with connection handles. Key: `Node`, `NodeHeader`, `NodeContent`, `NodeFooter` [SOURCE_CODE]
- `open-in-chat.tsx` - Dropdown UI to open a query in various external chat providers. Key: `providers`, `OpenIn`, `OpenInTrigger`, `OpenInChatGPT` [SOURCE_CODE]
- `panel.tsx` - Styled Panel wrapper around the xyflow Panel primitive. Key: `Panel` [SOURCE_CODE]
- `plan.tsx` - Collapsible plan UI with streaming-aware shimmer. Key: `Plan`, `PlanContext`, `PlanTitle`, `PlanDescription`, `PlanTrigger` [SOURCE_CODE]
- `prompt-input.tsx` - React prompt input component with attachment, drag/drop, IME, and speech handling. Key: `PromptInputProvider`, `PromptInputController`, `ProviderAttachmentsContext`, `usePromptInputAttachments`, `PromptInputAttachment` [SOURCE_CODE]
- `queue.tsx` - UI primitives for rendering a message/todo queue with collapsible sections. Key: `QueueItem`, `QueueItemIndicator`, `QueueList`, `QueueSection`, `QueueItemFile` [SOURCE_CODE]
- `reasoning.tsx` - Collapsible reasoning UI with streaming-aware state and duration tracking. Key: `Reasoning`, `useReasoning`, `ReasoningTrigger`, `ReasoningContent`, `AUTO_CLOSE_DELAY` [SOURCE_CODE]
- `shimmer.tsx` - Animated text shimmer component using motion for skeleton/placeholder text. Key: `Shimmer`, `TextShimmerProps`, `MotionComponent` [SOURCE_CODE]
- `sources.tsx` - React UI components for displaying collapsible source links. Key: `Sources`, `SourcesTrigger`, `SourcesContent`, `Source` [SOURCE_CODE]
- `suggestion.tsx` - React client components for rendering compact suggestion chips with staggered animation and optional icons. Key: `STAGGER_DELAY_MS`, `STAGGER_DELAY_MS_OFFSET`, `Suggestions`, `SuggestionsProps`, `Suggestion` [SOURCE_CODE]
- `task.tsx` - Collapsible task UI elements for displaying task metadata and content. Key: `Task`, `TaskTrigger`, `TaskContent`, `TaskItemFile` [SOURCE_CODE]
- `toolbar.tsx` - Styled toolbar wrapper for node-based UI with positioning. Key: `Toolbar` [SOURCE_CODE]
- `web-preview.tsx` - Web preview panel with URL input, iframe body and collapsible console. Key: `WebPreview`, `useWebPreview`, `WebPreviewUrl`, `WebPreviewBody`, `WebPreviewConsole` [SOURCE_CODE]

## frontend/src/components/landing/

- `footer.tsx` - Landing page footer with license and copyright. Key: `Footer` [SOURCE_CODE]
- `header.tsx` - Landing page header with navigation and GitHub star button. Key: `Header`, `StarCounter` [SOURCE_CODE]
- `hero.tsx` - Landing page hero section with animated visuals and CTA [SOURCE_CODE]
- `progressive-skills-animation.tsx` - Interactive animated demo showcasing skill discovery and deploy flow. Key: `ProgressiveSkillsAnimation`, `ANIMATION_DELAYS`, `getFileTree`, `FileItem` [SOURCE_CODE]
- `section.tsx` - Landing section wrapper with title and subtitle. Key: `Section` [SOURCE_CODE]

## frontend/src/components/landing/sections/

- `case-study-section.tsx` - Landing section displaying predefined case study cards. Key: `CaseStudySection` [SOURCE_CODE]
- `community-section.tsx` - Landing page section encouraging community contributions. Key: `CommunitySection` [SOURCE_CODE]
- `whats-new-section.tsx` - Landing page 'What's New' section with feature cards. Key: `WhatsNewSection`, `features`, `COLOR` [SOURCE_CODE]

## frontend/src/components/ui/

- `alert.tsx` - Alert component with title and description variants. Key: `Alert`, `alertVariants`, `AlertTitle`, `AlertDescription` [SOURCE_CODE]
- `aurora-text.tsx` - Animated aurora gradient text component. Key: `AuroraText` [SOURCE_CODE]
- `avatar.tsx` - Accessible avatar primitives (root, image, fallback). Key: `Avatar`, `AvatarImage`, `AvatarFallback` [SOURCE_CODE]
- `badge.tsx` - Small status/label badge component with variants. Key: `Badge`, `badgeVariants` [SOURCE_CODE]
- `breadcrumb.tsx` - Breadcrumb navigation primitives with separators and ellipsis. Key: `Breadcrumb`, `BreadcrumbList`, `BreadcrumbItem`, `BreadcrumbSeparator` [SOURCE_CODE]
- `button-group.tsx` - Grouped button layout with orientation and separators. Key: `ButtonGroup`, `buttonGroupVariants`, `ButtonGroupSeparator` [SOURCE_CODE]
- `button.tsx` - Versatile button component with size and variant tokens. Key: `Button`, `buttonVariants` [SOURCE_CODE]
- `card.tsx` - Card layout primitives (header, content, footer, title, action). Key: `Card`, `CardHeader`, `CardContent`, `CardFooter` [SOURCE_CODE]
- `carousel.tsx` - Carousel wrapper using embla-carousel with navigation controls. Key: `Carousel`, `useCarousel`, `CarouselContent`, `CarouselPrevious`, `CarouselNext` [SOURCE_CODE]
- `collapsible.tsx` - Radix-based collapsible wrapper components. Key: `Collapsible`, `CollapsibleTrigger`, `CollapsibleContent` [SOURCE_CODE]
- `command.tsx` - Command palette components built on cmdk with dialog integration. Key: `CommandDialog`, `CommandInput`, `Command`, `CommandItem`, `CommandList` [SOURCE_CODE]
- `confetti-button.tsx` - Button that triggers canvas confetti on click. Key: `ConfettiButton` [SOURCE_CODE]
- `dialog.tsx` - Reusable Radix-based dialog primitives with styling and close button. Key: `Dialog`, `DialogContent`, `DialogOverlay`, `DialogTrigger`, `DialogClose` [SOURCE_CODE]
- `dropdown-menu.tsx` - Styled Radix dropdown menu primitives and variants. Key: `DropdownMenu`, `DropdownMenuContent`, `DropdownMenuItem`, `DropdownMenuCheckboxItem`, `DropdownMenuRadioItem` [SOURCE_CODE]
- `empty.tsx` - Composable 'empty state' UI primitives with variants. Key: `Empty`, `EmptyHeader`, `EmptyMedia`, `EmptyTitle`, `EmptyDescription` [SOURCE_CODE]
- `flickering-grid.tsx` - Canvas-based flickering grid background animation. Key: `FlickeringGrid`, `setupCanvas`, `updateSquares`, `drawGrid` [SOURCE_CODE]
- `galaxy.jsx` - WebGL shader-driven galaxy background component. Key: `Galaxy`, `vertexShader`, `fragmentShader` [SOURCE_CODE]
- `hover-card.tsx` - Hover-card primitives wrapping Radix with styling and animations. Key: `HoverCard`, `HoverCardTrigger`, `HoverCardContent` [SOURCE_CODE]
- `input-group.tsx` - Composable input group primitives with addons and buttons. Key: `InputGroup`, `InputGroupAddon`, `InputGroupButton`, `InputGroupInput`, `InputGroupTextarea` [SOURCE_CODE]
- `input.tsx` - Styled single-line input component. Key: `Input` [SOURCE_CODE]
- `item.tsx` - Composable list/item UI primitives with media, title, description. Key: `Item`, `ItemMedia`, `ItemContent`, `ItemTitle`, `ItemDescription` [SOURCE_CODE]
- `magic-bento.tsx` - Interactive bento-style card grid with particle and glow effects. Key: `ParticleCard`, `GlobalSpotlight`, `createParticleElement`, `BentoCardGrid` [SOURCE_CODE]
- `progress.tsx` - Animated progress bar component using Radix primitive. Key: `Progress` [SOURCE_CODE]
- `scroll-area.tsx` - Custom scroll area with styled scrollbars using Radix primitives. Key: `ScrollArea`, `ScrollBar` [SOURCE_CODE]
- `separator.tsx` - Simple separator component wrapping Radix separator with styles. Key: `Separator` [SOURCE_CODE]
- `sheet.tsx` - Slide-in sheet components built on Radix dialog primitives. Key: `Sheet`, `SheetContent`, `SheetOverlay`, `SheetTrigger`, `SheetClose` [SOURCE_CODE]
- `shine-border.tsx` - Animated shine border component for UI elements. Key: `ShineBorder` [SOURCE_CODE]
- `skeleton.tsx` - Simple skeleton loading placeholder component. Key: `Skeleton` [SOURCE_CODE]
- `sonner.tsx` - Themed toast provider using sonner with custom icons/styles. Key: `Toaster` [SOURCE_CODE]
- `switch.tsx` - Accessible toggle switch component wrapping Radix switch. Key: `Switch` [SOURCE_CODE]
- `tabs.tsx` - Tabs primitives with styled list, triggers and content variants. Key: `Tabs`, `TabsList`, `TabsTrigger`, `TabsContent`, `tabsListVariants` [SOURCE_CODE]
- `toggle.tsx` - Toggle button primitive with variant and size variants. Key: `Toggle`, `toggleVariants` [SOURCE_CODE]
- `word-rotate.tsx` - Animated rotating word display component. Key: `WordRotate` [SOURCE_CODE]

## frontend/src/components/workspace/

- `agent-welcome.tsx` - Displays a welcome card for an agent with name and description. Key: `AgentWelcome` [SOURCE_CODE]
- `command-palette.tsx` - Client-side React component that provides a global command palette and keyboard-shortcuts overlay.. Key: `CommandPalette`, `handleNewChat`, `handleOpenSettings`, `handleShowShortcuts`, `shortcuts` [SOURCE_CODE]
- `export-trigger.tsx` - Dropdown trigger to export a thread as JSON or Markdown. Key: `ExportTrigger`, `handleExport` [SOURCE_CODE]
- `input-box.tsx` - React InputBox component for the chat workspace that manages model/mode selection, prompt input, and follow-up suggestions.. Key: `InputBox`, `getResolvedMode` [SOURCE_CODE]
- `mode-hover-guide.tsx` - Tooltip helper that explains agent modes on hover. Key: `ModeHoverGuide`, `getModeLabelKey`, `getModeDescriptionKey` [SOURCE_CODE]
- `recent-chat-list.tsx` - Sidebar component listing recent chat threads with actions. Key: `RecentChatList`, `handleDelete`, `handleExport`, `handleShare` [SOURCE_CODE]
- `thread-title.tsx` - Document title updater and display for thread titles. Key: `ThreadTitle` [SOURCE_CODE]
- `todo-list.tsx` - Collapsible to-do list UI showing task statuses. Key: `TodoList` [SOURCE_CODE]
- `token-usage-indicator.tsx` - Tooltip button showing token usage summary for messages. Key: `TokenUsageIndicator`, `TokenUsageIndicatorProps` [SOURCE_CODE]
- `welcome.tsx` - React client component that renders the workspace welcome/greeting UI with mode-specific variants and simple animation.. Key: `waved`, `Welcome` [SOURCE_CODE]
- `workspace-header.tsx` - Workspace sidebar header with brand and new-chat link. Key: `WorkspaceHeader` [SOURCE_CODE]
- `workspace-nav-chat-list.tsx` - Sidebar links for chats and agents in workspace navigation. Key: `WorkspaceNavChatList` [SOURCE_CODE]

## frontend/src/components/workspace/agents/

- `agent-card.tsx` - UI card showing an agent with actions like chat and delete. Key: `AgentCard`, `handleChat`, `handleDelete` [SOURCE_CODE]
- `agent-gallery.tsx` - Agents gallery listing with empty and loading states. Key: `AgentGallery`, `handleNewAgent` [SOURCE_CODE]

## frontend/src/components/workspace/artifacts/

- `artifact-file-detail.tsx` - React UI to view, preview, and act on a single artifact/file in the workspace.. Key: `ArtifactFileDetail`, `ArtifactFilePreview`, `isWriteFile`, `useArtifactContent`, `handleInstallSkill` [SOURCE_CODE]
- `artifact-file-list.tsx` - React component listing thread artifacts with download/install actions. Key: `ArtifactFileList` [SOURCE_CODE]
- `artifact-trigger.tsx` - Button trigger to open the artifacts panel. Key: `ArtifactTrigger` [SOURCE_CODE]
- `context.tsx` - Artifacts React context and provider for workspace state. Key: `ArtifactsProvider`, `useArtifacts`, `ArtifactsContextType` [SOURCE_CODE]

## frontend/src/components/workspace/chats/

- `chat-box.tsx` - Resizable chat panel with artifacts sidebar and selection handling. Key: `ChatBox`, `CLOSE_MODE`, `OPEN_MODE` [SOURCE_CODE]

## frontend/src/components/workspace/citations/

- `artifact-link.tsx` - Renderer for artifact links and citation-prefixed links. Key: `ArtifactLink`, `isExternalUrl` [SOURCE_CODE]
- `citation-link.tsx` - Reusable citation link component with hover preview. Key: `CitationLink`, `extractDomain` [SOURCE_CODE]

## frontend/src/components/workspace/messages/

- `markdown-content.tsx` - Client-side React component that renders Markdown content with custom link/citation handling.. Key: `isExternalUrl`, `MarkdownContentProps`, `MarkdownContent` [SOURCE_CODE]
- `message-group.tsx` - Converts a sequence of messages into a chain-of-thought UI with tool-call steps and previews.. Key: `MessageGroup`, `ToolCall`, `convertToSteps`, `convertToSteps:CoTToolCallStep`, `useRehypeSplitWordsIntoSpans` [SOURCE_CODE]
- `message-list-item.tsx` - React component that renders a single chat message with rich handling for files, images, reasoning and upload-state.. Key: `MessageListItem`, `MessageImage`, `MessageContent_`, `getFileExt`, `FILE_TYPE_MAP` [SOURCE_CODE]
- `message-list.tsx` - Renders a threaded, grouped view of messages and special assistant groups (files, subtasks, clarifications). Key: `MESSAGE_LIST_DEFAULT_PADDING_BOTTOM`, `MESSAGE_LIST_FOLLOWUPS_EXTRA_PADDING_BOTTOM`, `MessageList` [SOURCE_CODE]
- `subtask-card.tsx` - React component that renders a collapsible card view for a subtask with status, prompt, and result.. Key: `SubtaskCard` [SOURCE_CODE]

## frontend/src/components/workspace/settings/

- `about-settings-page.tsx` - Client React component that renders the app's About text using the Streamdown markdown renderer.. Key: `AboutSettingsPage`, `Streamdown`, `aboutMarkdown` [SOURCE_CODE]
- `appearance-settings-page.tsx` - Appearance settings page to change theme and language. Key: `AppearanceSettingsPage`, `ThemePreviewCard` [SOURCE_CODE]
- `memory-settings-page.tsx` - Memory settings UI for viewing, editing, importing, exporting memory. Key: `MemorySettingsPage`, `isImportedMemory`, `buildMemorySectionGroups`, `summariesToMarkdown` [SOURCE_CODE]
- `skill-settings-page.tsx` - Settings UI to list and enable/disable skills. Key: `SkillSettingsPage`, `SkillSettingsList`, `EmptySkill` [SOURCE_CODE]

## frontend/src/core/tasks/

- `context.tsx` - React context for managing subtasks/subagent state. Key: `SubtaskContext`, `SubtasksProvider`, `useSubtaskContext`, `useUpdateSubtask` [SOURCE_CODE]

## frontend/src/hooks/

- `use-global-shortcuts.ts` - Hook to register global keyboard shortcuts with input suppression. Key: `useGlobalShortcuts`, `Shortcut` [SOURCE_CODE]
- `use-mobile.ts` - Hook to detect mobile viewport breakpoint. Key: `useIsMobile` [SOURCE_CODE]

## frontend/src/lib/

- `ime.ts` - Utility to detect IME composition in keyboard events. Key: `isIMEComposing` [SOURCE_CODE]
- `utils.ts` - Class name merging utility and shared link styles. Key: `cn`, `externalLinkClass`, `externalLinkClassNoUnderline` [SOURCE_CODE]

## scripts/

- `check.py` - Cross-platform CLI that verifies presence and versions of local dev dependencies.. Key: `configure_stdio`, `run_command`, `find_pnpm_command`, `parse_node_major`, `main` [CLI]
- `check.sh` - Check required developer dependencies (node, pnpm, uv, nginx) [CLI]
- `cleanup-containers.sh` - Stop and cleanup sandbox containers for Docker and Apple Container runtimes [CLI]
- `config-upgrade.sh` - Upgrade and merge user config.yaml with the example template [CLI]
- `configure.py` - Bootstrap config files from templates if missing [CLI]
- `deploy.sh` - Build, start, or stop production Docker Compose services [CLI]
- `docker.sh` - Manage Docker development environment: init, start, logs, stop [CLI]
- `export_claude_code_oauth.py` - macOS Keychain exporter for Claude Code OAuth credentials [CLI]
- `load_memory_sample.py` - CLI to copy a memory-settings sample into local runtime memory.json [CLI]
- `serve.sh` - Unified local service launcher for dev/prod: LangGraph, Gateway, Frontend, Nginx [CLI]
- `start-daemon.sh` - Backward-compatible wrapper to start DeerFlow in daemon mode [CLI]
- `tool-error-degradation-detection.sh` - Test that tool failures are downgraded and do not abort agent flows. Key: `TOOL_CALLS`, `_make_ssl_error`, `_sync_handler`, `_async_handler`, `_compose_sync` [TEST]
- `wait-for-port.sh` - Block until a TCP port becomes available (healthcheck) [CLI]

## skills/public/data-analysis/scripts/

- `analyze.py` - CLI script to analyze CSV/Excel files with DuckDB [CLI]

## skills/public/github-deep-research/scripts/

- `github_api.py` - Small GitHub API client used by deep-research skill [CLI]

## skills/public/image-generation/scripts/

- `generate.py` - Generate an image using Gemini image API with optional references [CLI]

## skills/public/podcast-generation/scripts/

- `generate.py` - Generate podcast audio from a script using Volcengine TTS [CLI]

## skills/public/ppt-generation/scripts/

- `generate.py` - Create a PowerPoint presentation from slide images and a plan [CLI]

## skills/public/skill-creator/

- `generate_report.py` - Generate an HTML report visualizing run_loop outputs [CLI]

## skills/public/skill-creator/eval-viewer/

- `generate_review.py` - Serve or write a standalone eval review HTML viewer for workspace runs [CLI]

## skills/public/skill-creator/scripts/

- `aggregate_benchmark.py` - CLI to aggregate benchmark run grading into summary and markdown [CLI]
- `improve_description.py` - Call Claude to propose improved skill descriptions from eval results [CLI]
- `package_skill.py` - Package a skill folder into a .skill ZIP archive [CLI]
- `quick_validate.py` - Minimal SKILL.md frontmatter validator [CLI]
- `run_eval.py` - Evaluate whether a skill description triggers for queries using claude -p [CLI]
- `run_loop.py` - Iteratively evaluate and improve a skill description until criteria met [CLI]
- `utils.py` - Parse SKILL.md frontmatter and return skill metadata. Key: `parse_skill_md` [SOURCE_CODE]

## skills/public/video-generation/scripts/

- `generate.py` - CLI script to generate videos via Google Gemini LLM API [CLI]


---
*This knowledge base was extracted by [Codeset](https://codeset.ai) and is available via `python .codex/docs/get_context.py <file_or_folder>`*
