# Deer-Flow 完整项目代码注释计划

## 📋 项目信息
- **项目名称**: bytedance/deer-flow
- **项目地址**: https://github.com/bytedance/deer-flow
- **分析目标**: 为每个文件添加详细的中文注释，重点强化"设计思路"解读

## 📊 文件统计
| 模块 | 文件数量 |
|------|---------|
| **Backend** | 283 |
| **Frontend** | 256 |
| **Skills** | 79 |
| **Docs** | 63 |
| **Config/Root** | 27 |
| **总计** | **708** |

## 🎯 分析要求
1. **禁止精简** - 每个文件都要详细分析
2. **禁止合并模块** - 保持原有模块结构
3. **禁止限制文档篇数** - 完整覆盖所有文件
4. **禁止省略底层细节** - 深入到底层实现
5. **重点强化设计思路** - 讲清"为什么这么做"，而非只讲"做了什么"

---

## 📁 完整文件清单 (708 files)

- [x] 001. /data/deer-flow-main/backend/AGENTS.md
- [x] 002. /data/deer-flow-main/backend/app/channels/base.py
- [x] 003. /data/deer-flow-main/backend/app/channels/feishu.py
- [x] 004. /data/deer-flow-main/backend/app/channels/__init__.py
- [x] 005. /data/deer-flow-main/backend/app/channels/manager.py
- [x] 006. /data/deer-flow-main/backend/app/channels/message_bus.py
- [x] 007. /data/deer-flow-main/backend/app/channels/service.py
- [x] 008. /data/deer-flow-main/backend/app/channels/slack.py
- [x] 009. /data/deer-flow-main/backend/app/channels/store.py
- [x] 010. /data/deer-flow-main/backend/app/channels/telegram.py
- [x] 011. /data/deer-flow-main/backend/app/gateway/app.py
- [x] 012. /data/deer-flow-main/backend/app/gateway/config.py
- [x] 013. /data/deer-flow-main/backend/app/gateway/deps.py
- [x] 014. /data/deer-flow-main/backend/app/gateway/__init__.py
- [x] 015. /data/deer-flow-main/backend/app/gateway/path_utils.py
- [x] 016. /data/deer-flow-main/backend/app/gateway/routers/agents.py
- [x] 017. /data/deer-flow-main/backend/app/gateway/routers/artifacts.py
- [x] 018. /data/deer-flow-main/backend/app/gateway/routers/assistants_compat.py
- [x] 019. /data/deer-flow-main/backend/app/gateway/routers/channels.py
- [x] 020. /data/deer-flow-main/backend/app/gateway/routers/__init__.py
- [x] 021. /data/deer-flow-main/backend/app/gateway/routers/mcp.py
- [x] 022. /data/deer-flow-main/backend/app/gateway/routers/memory.py
- [x] 023. /data/deer-flow-main/backend/app/gateway/routers/models.py
- [x] 024. /data/deer-flow-main/backend/app/gateway/routers/runs.py
- [x] 025. /data/deer-flow-main/backend/app/gateway/routers/skills.py
- [x] 026. /data/deer-flow-main/backend/app/gateway/routers/suggestions.py
- [x] 027. /data/deer-flow-main/backend/app/gateway/routers/thread_runs.py
- [x] 028. /data/deer-flow-main/backend/app/gateway/routers/threads.py
- [x] 029. /data/deer-flow-main/backend/app/gateway/routers/uploads.py
- [x] 030. /data/deer-flow-main/backend/app/gateway/services.py
- [x] 031. /data/deer-flow-main/backend/app/__init__.py
- [x] 032. /data/deer-flow-main/backend/langgraph.json
- [x] 033. /data/deer-flow-main/backend/CONTRIBUTING.md
- [x] 034. /data/deer-flow-main/backend/debug.py
- [x] 035. /data/deer-flow-main/backend/docs/API.md
- [x] 036. /data/deer-flow-main/backend/docs/APPLE_CONTAINER.md
- [x] 037. /data/deer-flow-main/backend/docs/ARCHITECTURE.md
- [x] 038. /data/deer-flow-main/backend/docs/AUTO_TITLE_GENERATION.md
- [x] 039. /data/deer-flow-main/backend/docs/CONFIGURATION.md
- [x] 040. /data/deer-flow-main/backend/docs/FILE_UPLOAD.md
- [x] 041. /data/deer-flow-main/backend/docs/GUARDRAILS.md
- [x] 042. /data/deer-flow-main/backend/docs/HARNESS_APP_SPLIT.md
- [x] 043. /data/deer-flow-main/backend/docs/MCP_SERVER.md
- [x] 044. /data/deer-flow-main/backend/docs/MEMORY_IMPROVEMENTS.md
- [x] 045. /data/deer-flow-main/backend/docs/MEMORY_IMPROVEMENTS_SUMMARY.md
- [x] 046. /data/deer-flow-main/backend/docs/MEMORY_SETTINGS_REVIEW.md
- [x] 047. /data/deer-flow-main/backend/docs/memory-settings-sample.json
- [x] 048. /data/deer-flow-main/backend/docs/middleware-execution-flow.md
- [x] 049. /data/deer-flow-main/backend/docs/PATH_EXAMPLES.md
- [x] 050. /data/deer-flow-main/backend/docs/plan_mode_usage.md
- [x] 051. /data/deer-flow-main/backend/docs/README.md
- [x] 052. /data/deer-flow-main/backend/docs/rfc-create-deerflow-agent.md
- [x] 053. /data/deer-flow-main/backend/docs/rfc-extract-shared-modules.md
- [x] 054. /data/deer-flow-main/backend/docs/SETUP.md
- [x] 055. /data/deer-flow-main/backend/docs/summarization.md
- [x] 056. /data/deer-flow-main/backend/docs/task_tool_improvements.md
- [x] 057. /data/deer-flow-main/backend/docs/TITLE_GENERATION_IMPLEMENTATION.md
- [x] 058. /data/deer-flow-main/backend/docs/TODO.md
- [x] 059. /data/deer-flow-main/backend/langgraph.json
- [x] 060. /data/deer-flow-main/backend/packages/harness/deerflow/agents/checkpointer/async_provider.py
- [x] 061. /data/deer-flow-main/backend/packages/harness/deerflow/agents/checkpointer/__init__.py
- [x] 062. /data/deer-flow-main/backend/packages/harness/deerflow/agents/checkpointer/provider.py
- [x] 063. /data/deer-flow-main/backend/packages/harness/deerflow/agents/factory.py
- [x] 064. /data/deer-flow-main/backend/packages/harness/deerflow/agents/features.py
- [x] 065. /data/deer-flow-main/backend/packages/harness/deerflow/agents/__init__.py
- [x] 066. /data/deer-flow-main/backend/packages/harness/deerflow/agents/lead_agent/agent.py
- [x] 067. /data/deer-flow-main/backend/packages/harness/deerflow/agents/lead_agent/__init__.py
- [x] 068. /data/deer-flow-main/backend/packages/harness/deerflow/agents/lead_agent/prompt.py
- [x] 069. /data/deer-flow-main/backend/packages/harness/deerflow/agents/memory/__init__.py
- [x] 070. /data/deer-flow-main/backend/packages/harness/deerflow/agents/memory/prompt.py
- [x] 071. /data/deer-flow-main/backend/packages/harness/deerflow/agents/memory/queue.py
- [x] 072. /data/deer-flow-main/backend/packages/harness/deerflow/agents/memory/storage.py
- [x] 073. /data/deer-flow-main/backend/packages/harness/deerflow/agents/memory/updater.py
- [x] 074. /data/deer-flow-main/backend/packages/harness/deerflow/agents/middlewares/clarification_middleware.py
- [x] 075. /data/deer-flow-main/backend/packages/harness/deerflow/agents/middlewares/dangling_tool_call_middleware.py
- [x] 076. /data/deer-flow-main/backend/packages/harness/deerflow/agents/middlewares/deferred_tool_filter_middleware.py
- [x] 077. /data/deer-flow-main/backend/packages/harness/deerflow/agents/middlewares/__init__.py
- [x] 078. /data/deer-flow-main/backend/packages/harness/deerflow/agents/middlewares/loop_detection_middleware.py
- [x] 079. /data/deer-flow-main/backend/packages/harness/deerflow/agents/middlewares/memory_middleware.py
- [x] 080. /data/deer-flow-main/backend/packages/harness/deerflow/agents/middlewares/sandbox_audit_middleware.py
- [x] 081. /data/deer-flow-main/backend/packages/harness/deerflow/agents/middlewares/subagent_limit_middleware.py
- [x] 082. /data/deer-flow-main/backend/packages/harness/deerflow/agents/middlewares/thread_data_middleware.py
- [x] 083. /data/deer-flow-main/backend/packages/harness/deerflow/agents/middlewares/title_middleware.py
- [x] 084. /data/deer-flow-main/backend/packages/harness/deerflow/agents/middlewares/todo_middleware.py
- [x] 085. /data/deer-flow-main/backend/packages/harness/deerflow/agents/middlewares/token_usage_middleware.py
- [x] 086. /data/deer-flow-main/backend/packages/harness/deerflow/agents/middlewares/tool_error_handling_middleware.py
- [x] 087. /data/deer-flow-main/backend/packages/harness/deerflow/agents/middlewares/uploads_middleware.py
- [x] 088. /data/deer-flow-main/backend/packages/harness/deerflow/agents/middlewares/view_image_middleware.py
- [x] 089. /data/deer-flow-main/backend/packages/harness/deerflow/agents/thread_state.py
- [ ] 090. /data/deer-flow-main/backend/packages/harness/deerflow/client.py
- [ ] 091. /data/deer-flow-main/backend/packages/harness/deerflow/community/aio_sandbox/aio_sandbox_provider.py
- [ ] 092. /data/deer-flow-main/backend/packages/harness/deerflow/community/aio_sandbox/aio_sandbox.py
- [ ] 093. /data/deer-flow-main/backend/packages/harness/deerflow/community/aio_sandbox/backend.py
- [ ] 094. /data/deer-flow-main/backend/packages/harness/deerflow/community/aio_sandbox/__init__.py
- [ ] 095. /data/deer-flow-main/backend/packages/harness/deerflow/community/aio_sandbox/local_backend.py
- [ ] 096. /data/deer-flow-main/backend/packages/harness/deerflow/community/aio_sandbox/remote_backend.py
- [ ] 097. /data/deer-flow-main/backend/packages/harness/deerflow/community/aio_sandbox/sandbox_info.py
- [ ] 098. /data/deer-flow-main/backend/packages/harness/deerflow/community/ddg_search/__init__.py
- [ ] 099. /data/deer-flow-main/backend/packages/harness/deerflow/community/ddg_search/tools.py
- [ ] 100. /data/deer-flow-main/backend/packages/harness/deerflow/community/firecrawl/tools.py
- [ ] 101. /data/deer-flow-main/backend/packages/harness/deerflow/community/image_search/__init__.py
- [ ] 102. /data/deer-flow-main/backend/packages/harness/deerflow/community/image_search/tools.py
- [ ] 103. /data/deer-flow-main/backend/packages/harness/deerflow/community/infoquest/infoquest_client.py
- [ ] 104. /data/deer-flow-main/backend/packages/harness/deerflow/community/infoquest/tools.py
- [ ] 105. /data/deer-flow-main/backend/packages/harness/deerflow/community/jina_ai/jina_client.py
- [ ] 106. /data/deer-flow-main/backend/packages/harness/deerflow/community/jina_ai/tools.py
- [ ] 107. /data/deer-flow-main/backend/packages/harness/deerflow/community/tavily/tools.py
- [ ] 108. /data/deer-flow-main/backend/packages/harness/deerflow/config/acp_config.py
- [ ] 109. /data/deer-flow-main/backend/packages/harness/deerflow/config/agents_config.py
- [ ] 110. /data/deer-flow-main/backend/packages/harness/deerflow/config/app_config.py
- [ ] 111. /data/deer-flow-main/backend/packages/harness/deerflow/config/checkpointer_config.py
- [ ] 112. /data/deer-flow-main/backend/packages/harness/deerflow/config/extensions_config.py
- [ ] 113. /data/deer-flow-main/backend/packages/harness/deerflow/config/guardrails_config.py
- [ ] 114. /data/deer-flow-main/backend/packages/harness/deerflow/config/__init__.py
- [ ] 115. /data/deer-flow-main/backend/packages/harness/deerflow/config/memory_config.py
- [ ] 116. /data/deer-flow-main/backend/packages/harness/deerflow/config/model_config.py
- [ ] 117. /data/deer-flow-main/backend/packages/harness/deerflow/config/paths.py
- [ ] 118. /data/deer-flow-main/backend/packages/harness/deerflow/config/sandbox_config.py
- [ ] 119. /data/deer-flow-main/backend/packages/harness/deerflow/config/skills_config.py
- [ ] 120. /data/deer-flow-main/backend/packages/harness/deerflow/config/stream_bridge_config.py
- [ ] 121. /data/deer-flow-main/backend/packages/harness/deerflow/config/subagents_config.py
- [ ] 122. /data/deer-flow-main/backend/packages/harness/deerflow/config/summarization_config.py
- [ ] 123. /data/deer-flow-main/backend/packages/harness/deerflow/config/title_config.py
- [ ] 124. /data/deer-flow-main/backend/packages/harness/deerflow/config/token_usage_config.py
- [ ] 125. /data/deer-flow-main/backend/packages/harness/deerflow/config/tool_config.py
- [ ] 126. /data/deer-flow-main/backend/packages/harness/deerflow/config/tool_search_config.py
- [ ] 127. /data/deer-flow-main/backend/packages/harness/deerflow/config/tracing_config.py
- [ ] 128. /data/deer-flow-main/backend/packages/harness/deerflow/guardrails/builtin.py
- [ ] 129. /data/deer-flow-main/backend/packages/harness/deerflow/guardrails/__init__.py
- [ ] 130. /data/deer-flow-main/backend/packages/harness/deerflow/guardrails/middleware.py
- [ ] 131. /data/deer-flow-main/backend/packages/harness/deerflow/guardrails/provider.py
- [ ] 132. /data/deer-flow-main/backend/packages/harness/deerflow/__init__.py
- [ ] 133. /data/deer-flow-main/backend/packages/harness/deerflow/mcp/cache.py
- [ ] 134. /data/deer-flow-main/backend/packages/harness/deerflow/mcp/client.py
- [ ] 135. /data/deer-flow-main/backend/packages/harness/deerflow/mcp/__init__.py
- [ ] 136. /data/deer-flow-main/backend/packages/harness/deerflow/mcp/oauth.py
- [ ] 137. /data/deer-flow-main/backend/packages/harness/deerflow/mcp/tools.py
- [ ] 138. /data/deer-flow-main/backend/packages/harness/deerflow/models/claude_provider.py
- [ ] 139. /data/deer-flow-main/backend/packages/harness/deerflow/models/credential_loader.py
- [ ] 140. /data/deer-flow-main/backend/packages/harness/deerflow/models/factory.py
- [ ] 141. /data/deer-flow-main/backend/packages/harness/deerflow/models/__init__.py
- [ ] 142. /data/deer-flow-main/backend/packages/harness/deerflow/models/openai_codex_provider.py
- [ ] 143. /data/deer-flow-main/backend/packages/harness/deerflow/models/patched_deepseek.py
- [ ] 144. /data/deer-flow-main/backend/packages/harness/deerflow/models/patched_minimax.py
- [ ] 145. /data/deer-flow-main/backend/packages/harness/deerflow/models/patched_openai.py
- [ ] 146. /data/deer-flow-main/backend/packages/harness/deerflow/reflection/__init__.py
- [ ] 147. /data/deer-flow-main/backend/packages/harness/deerflow/reflection/resolvers.py
- [ ] 148. /data/deer-flow-main/backend/packages/harness/deerflow/runtime/__init__.py
- [ ] 149. /data/deer-flow-main/backend/packages/harness/deerflow/runtime/runs/__init__.py
- [ ] 150. /data/deer-flow-main/backend/packages/harness/deerflow/runtime/runs/manager.py
- [ ] 151. /data/deer-flow-main/backend/packages/harness/deerflow/runtime/runs/schemas.py
- [ ] 152. /data/deer-flow-main/backend/packages/harness/deerflow/runtime/runs/worker.py
- [ ] 153. /data/deer-flow-main/backend/packages/harness/deerflow/runtime/serialization.py
- [ ] 154. /data/deer-flow-main/backend/packages/harness/deerflow/runtime/store/async_provider.py
- [ ] 155. /data/deer-flow-main/backend/packages/harness/deerflow/runtime/store/__init__.py
- [ ] 156. /data/deer-flow-main/backend/packages/harness/deerflow/runtime/store/provider.py
- [ ] 157. /data/deer-flow-main/backend/packages/harness/deerflow/runtime/store/_sqlite_utils.py
- [ ] 158. /data/deer-flow-main/backend/packages/harness/deerflow/runtime/stream_bridge/async_provider.py
- [ ] 159. /data/deer-flow-main/backend/packages/harness/deerflow/runtime/stream_bridge/base.py
- [ ] 160. /data/deer-flow-main/backend/packages/harness/deerflow/runtime/stream_bridge/__init__.py
- [ ] 161. /data/deer-flow-main/backend/packages/harness/deerflow/runtime/stream_bridge/memory.py
- [ ] 162. /data/deer-flow-main/backend/packages/harness/deerflow/sandbox/exceptions.py
- [ ] 163. /data/deer-flow-main/backend/packages/harness/deerflow/sandbox/__init__.py
- [ ] 164. /data/deer-flow-main/backend/packages/harness/deerflow/sandbox/local/__init__.py
- [ ] 165. /data/deer-flow-main/backend/packages/harness/deerflow/sandbox/local/list_dir.py
- [ ] 166. /data/deer-flow-main/backend/packages/harness/deerflow/sandbox/local/local_sandbox_provider.py
- [ ] 167. /data/deer-flow-main/backend/packages/harness/deerflow/sandbox/local/local_sandbox.py
- [ ] 168. /data/deer-flow-main/backend/packages/harness/deerflow/sandbox/middleware.py
- [ ] 169. /data/deer-flow-main/backend/packages/harness/deerflow/sandbox/sandbox_provider.py
- [ ] 170. /data/deer-flow-main/backend/packages/harness/deerflow/sandbox/sandbox.py
- [ ] 171. /data/deer-flow-main/backend/packages/harness/deerflow/sandbox/security.py
- [ ] 172. /data/deer-flow-main/backend/packages/harness/deerflow/sandbox/tools.py
- [ ] 173. /data/deer-flow-main/backend/packages/harness/deerflow/skills/__init__.py
- [ ] 174. /data/deer-flow-main/backend/packages/harness/deerflow/skills/installer.py
- [ ] 175. /data/deer-flow-main/backend/packages/harness/deerflow/skills/loader.py
- [ ] 176. /data/deer-flow-main/backend/packages/harness/deerflow/skills/parser.py
- [ ] 177. /data/deer-flow-main/backend/packages/harness/deerflow/skills/types.py
- [ ] 178. /data/deer-flow-main/backend/packages/harness/deerflow/skills/validation.py
- [ ] 179. /data/deer-flow-main/backend/packages/harness/deerflow/subagents/builtins/bash_agent.py
- [ ] 180. /data/deer-flow-main/backend/packages/harness/deerflow/subagents/builtins/general_purpose.py
- [ ] 181. /data/deer-flow-main/backend/packages/harness/deerflow/subagents/builtins/__init__.py
- [ ] 182. /data/deer-flow-main/backend/packages/harness/deerflow/subagents/config.py
- [ ] 183. /data/deer-flow-main/backend/packages/harness/deerflow/subagents/executor.py
- [ ] 184. /data/deer-flow-main/backend/packages/harness/deerflow/subagents/__init__.py
- [ ] 185. /data/deer-flow-main/backend/packages/harness/deerflow/subagents/registry.py
- [ ] 186. /data/deer-flow-main/backend/packages/harness/deerflow/tools/builtins/clarification_tool.py
- [ ] 187. /data/deer-flow-main/backend/packages/harness/deerflow/tools/builtins/__init__.py
- [ ] 188. /data/deer-flow-main/backend/packages/harness/deerflow/tools/builtins/invoke_acp_agent_tool.py
- [ ] 189. /data/deer-flow-main/backend/packages/harness/deerflow/tools/builtins/present_file_tool.py
- [ ] 190. /data/deer-flow-main/backend/packages/harness/deerflow/tools/builtins/setup_agent_tool.py
- [ ] 191. /data/deer-flow-main/backend/packages/harness/deerflow/tools/builtins/task_tool.py
- [ ] 192. /data/deer-flow-main/backend/packages/harness/deerflow/tools/builtins/tool_search.py
- [ ] 193. /data/deer-flow-main/backend/packages/harness/deerflow/tools/builtins/view_image_tool.py
- [ ] 194. /data/deer-flow-main/backend/packages/harness/deerflow/tools/__init__.py
- [ ] 195. /data/deer-flow-main/backend/packages/harness/deerflow/tools/tools.py
- [ ] 196. /data/deer-flow-main/backend/packages/harness/deerflow/uploads/__init__.py
- [ ] 197. /data/deer-flow-main/backend/packages/harness/deerflow/uploads/manager.py
- [ ] 198. /data/deer-flow-main/backend/packages/harness/deerflow/utils/file_conversion.py
- [ ] 199. /data/deer-flow-main/backend/packages/harness/deerflow/utils/network.py
- [ ] 200. /data/deer-flow-main/backend/packages/harness/deerflow/utils/readability.py
- [ ] 201. /data/deer-flow-main/backend/packages/harness/pyproject.toml
- [ ] 202. /data/deer-flow-main/backend/pyproject.toml
- [ ] 203. /data/deer-flow-main/backend/README.md
- [ ] 204. /data/deer-flow-main/backend/ruff.toml
- [ ] 205. /data/deer-flow-main/backend/tests/conftest.py
- [ ] 206. /data/deer-flow-main/backend/tests/test_acp_config.py
- [ ] 207. /data/deer-flow-main/backend/tests/test_aio_sandbox_provider.py
- [ ] 208. /data/deer-flow-main/backend/tests/test_app_config_reload.py
- [ ] 209. /data/deer-flow-main/backend/tests/test_artifacts_router.py
- [ ] 210. /data/deer-flow-main/backend/tests/test_channel_file_attachments.py
- [ ] 211. /data/deer-flow-main/backend/tests/test_channels.py
- [ ] 212. /data/deer-flow-main/backend/tests/test_checkpointer_none_fix.py
- [ ] 213. /data/deer-flow-main/backend/tests/test_checkpointer.py
- [ ] 214. /data/deer-flow-main/backend/tests/test_claude_provider_oauth_billing.py
- [ ] 215. /data/deer-flow-main/backend/tests/test_cli_auth_providers.py
- [ ] 216. /data/deer-flow-main/backend/tests/test_client_e2e.py
- [ ] 217. /data/deer-flow-main/backend/tests/test_client_live.py
- [ ] 218. /data/deer-flow-main/backend/tests/test_client.py
- [ ] 219. /data/deer-flow-main/backend/tests/test_config_version.py
- [ ] 220. /data/deer-flow-main/backend/tests/test_create_deerflow_agent_live.py
- [ ] 221. /data/deer-flow-main/backend/tests/test_create_deerflow_agent.py
- [ ] 222. /data/deer-flow-main/backend/tests/test_credential_loader.py
- [ ] 223. /data/deer-flow-main/backend/tests/test_custom_agent.py
- [ ] 224. /data/deer-flow-main/backend/tests/test_dangling_tool_call_middleware.py
- [ ] 225. /data/deer-flow-main/backend/tests/test_docker_sandbox_mode_detection.py
- [ ] 226. /data/deer-flow-main/backend/tests/test_feishu_parser.py
- [ ] 227. /data/deer-flow-main/backend/tests/test_gateway_services.py
- [ ] 228. /data/deer-flow-main/backend/tests/test_guardrail_middleware.py
- [ ] 229. /data/deer-flow-main/backend/tests/test_harness_boundary.py
- [ ] 230. /data/deer-flow-main/backend/tests/test_infoquest_client.py
- [ ] 231. /data/deer-flow-main/backend/tests/test_invoke_acp_agent_tool.py
- [ ] 232. /data/deer-flow-main/backend/tests/test_lead_agent_model_resolution.py
- [ ] 233. /data/deer-flow-main/backend/tests/test_local_bash_tool_loading.py
- [ ] 234. /data/deer-flow-main/backend/tests/test_local_sandbox_encoding.py
- [ ] 235. /data/deer-flow-main/backend/tests/test_loop_detection_middleware.py
- [ ] 236. /data/deer-flow-main/backend/tests/test_mcp_client_config.py
- [ ] 237. /data/deer-flow-main/backend/tests/test_mcp_oauth.py
- [ ] 238. /data/deer-flow-main/backend/tests/test_mcp_sync_wrapper.py
- [ ] 239. /data/deer-flow-main/backend/tests/test_memory_prompt_injection.py
- [ ] 240. /data/deer-flow-main/backend/tests/test_memory_router.py
- [ ] 241. /data/deer-flow-main/backend/tests/test_memory_storage.py
- [ ] 242. /data/deer-flow-main/backend/tests/test_memory_updater.py
- [ ] 243. /data/deer-flow-main/backend/tests/test_memory_upload_filtering.py
- [ ] 244. /data/deer-flow-main/backend/tests/test_model_config.py
- [ ] 245. /data/deer-flow-main/backend/tests/test_model_factory.py
- [ ] 246. /data/deer-flow-main/backend/tests/test_patched_minimax.py
- [ ] 247. /data/deer-flow-main/backend/tests/test_patched_openai.py
- [ ] 248. /data/deer-flow-main/backend/tests/test_present_file_tool_core_logic.py
- [ ] 249. /data/deer-flow-main/backend/tests/test_provisioner_kubeconfig.py
- [ ] 250. /data/deer-flow-main/backend/tests/test_readability.py
- [ ] 251. /data/deer-flow-main/backend/tests/test_reflection_resolvers.py
- [ ] 252. /data/deer-flow-main/backend/tests/test_run_manager.py
- [ ] 253. /data/deer-flow-main/backend/tests/test_sandbox_audit_middleware.py
- [ ] 254. /data/deer-flow-main/backend/tests/test_sandbox_tools_security.py
- [ ] 255. /data/deer-flow-main/backend/tests/test_serialization.py
- [ ] 256. /data/deer-flow-main/backend/tests/test_serialize_message_content.py
- [ ] 257. /data/deer-flow-main/backend/tests/test_skills_archive_root.py
- [ ] 258. /data/deer-flow-main/backend/tests/test_skills_installer.py
- [ ] 259. /data/deer-flow-main/backend/tests/test_skills_loader.py
- [ ] 260. /data/deer-flow-main/backend/tests/test_skills_parser.py
- [ ] 261. /data/deer-flow-main/backend/tests/test_skills_validation.py
- [ ] 262. /data/deer-flow-main/backend/tests/test_sse_format.py
- [ ] 263. /data/deer-flow-main/backend/tests/test_stream_bridge.py
- [ ] 264. /data/deer-flow-main/backend/tests/test_subagent_executor.py
- [ ] 265. /data/deer-flow-main/backend/tests/test_subagent_limit_middleware.py
- [ ] 266. /data/deer-flow-main/backend/tests/test_subagent_prompt_security.py
- [ ] 267. /data/deer-flow-main/backend/tests/test_subagent_timeout_config.py
- [ ] 268. /data/deer-flow-main/backend/tests/test_suggestions_router.py
- [ ] 269. /data/deer-flow-main/backend/tests/test_task_tool_core_logic.py
- [ ] 270. /data/deer-flow-main/backend/tests/test_thread_data_middleware.py
- [ ] 271. /data/deer-flow-main/backend/tests/test_threads_router.py
- [ ] 272. /data/deer-flow-main/backend/tests/test_title_generation.py
- [ ] 273. /data/deer-flow-main/backend/tests/test_title_middleware_core_logic.py
- [ ] 274. /data/deer-flow-main/backend/tests/test_todo_middleware.py
- [ ] 275. /data/deer-flow-main/backend/tests/test_token_usage.py
- [ ] 276. /data/deer-flow-main/backend/tests/test_tool_error_handling_middleware.py
- [ ] 277. /data/deer-flow-main/backend/tests/test_tool_search.py
- [ ] 278. /data/deer-flow-main/backend/tests/test_tracing_config.py
- [ ] 279. /data/deer-flow-main/backend/tests/test_uploads_manager.py
- [ ] 280. /data/deer-flow-main/backend/tests/test_uploads_middleware_core_logic.py
- [ ] 281. /data/deer-flow-main/backend/tests/test_uploads_router.py
- [ ] 282. /data/deer-flow-main/backend/.vscode/extensions.json
- [ ] 283. /data/deer-flow-main/backend/.vscode/settings.json
- [ ] 284. /data/deer-flow-main/config.example.yaml
- [ ] 285. /data/deer-flow-main/CONTRIBUTING.md
- [ ] 286. /data/deer-flow-main/docker/docker-compose-dev.yaml
- [ ] 287. /data/deer-flow-main/docker/docker-compose.yaml
- [ ] 288. /data/deer-flow-main/docker/provisioner/app.py
- [ ] 289. /data/deer-flow-main/docker/provisioner/README.md
- [ ] 290. /data/deer-flow-main/docs/00-全集总览与全仓库拓扑架构.md
- [ ] 291. /data/deer-flow-main/docs/01-后端核心引擎架构.md
- [ ] 292. /data/deer-flow-main/docs/01-配置系统.md
- [ ] 293. /data/deer-flow-main/docs/02-中间件系统详解.md
- [ ] 294. /data/deer-flow-main/docs/02-代理系统.md
- [ ] 295. /data/deer-flow-main/docs/03-模型工厂.md
- [ ] 296. /data/deer-flow-main/docs/03-运行时管理系统.md
- [ ] 297. /data/deer-flow-main/docs/04-工具系统.md
- [ ] 298. /data/deer-flow-main/docs/04-模型适配系统.md
- [ ] 299. /data/deer-flow-main/docs/05-工具系统详解.md
- [ ] 300. /data/deer-flow-main/docs/05-技能系统深度解析.md
- [ ] 301. /data/deer-flow-main/docs/06-MCP集成深度解析.md
- [ ] 302. /data/deer-flow-main/docs/06-技能系统详解.md
- [ ] 303. /data/deer-flow-main/docs/07-沙箱执行系统.md
- [ ] 304. /data/deer-flow-main/docs/07-记忆系统深度解析.md
- [ ] 305. /data/deer-flow-main/docs/08-DeerFlow是什么-五分钟看懂AI Agent框架.md
- [ ] 306. /data/deer-flow-main/docs/08-前端架构总览.md
- [ ] 307. /data/deer-flow-main/docs/08-沙箱系统深度解析.md
- [ ] 308. /data/deer-flow-main/docs/09-中间件系统深度解析.md
- [ ] 309. /data/deer-flow-main/docs/09-系统架构全景图-各层如何协作.md
- [ ] 310. /data/deer-flow-main/docs/09-页面路由系统.md
- [ ] 311. /data/deer-flow-main/docs/10-代理系统-Agent到底是什么.md
- [ ] 312. /data/deer-flow-main/docs/10-组件库深度解析.md
- [ ] 313. /data/deer-flow-main/docs/10-运行时管理深度解析.md
- [ ] 314. /data/deer-flow-main/docs/11-子代理系统深度解析.md
- [ ] 315. /data/deer-flow-main/docs/11-核心业务逻辑层.md
- [ ] 316. /data/deer-flow-main/docs/11-记忆系统-AI如何记住对话.md
- [ ] 317. /data/deer-flow-main/docs/12-中间件系统-请求处理的流水线.md
- [ ] 318. /data/deer-flow-main/docs/12-状态管理方案.md
- [ ] 319. /data/deer-flow-main/docs/13-APIClient端设计.md
- [ ] 320. /data/deer-flow-main/docs/13-工具与技能-Agent的手和技能包.md
- [ ] 321. /data/deer-flow-main/docs/14-APi网关架构.md
- [ ] 322. /data/deer-flow-main/docs/14-沙箱系统-安全执行不可信代码.md
- [ ] 323. /data/deer-flow-main/docs/15-IM渠道集成系统.md
- [ ] 324. /data/deer-flow-main/docs/15-检查点与状态管理-如何实现暂停恢复.md
- [ ] 325. /data/deer-flow-main/docs/16-DeerFlow用到的设计模式.md
- [ ] 326. /data/deer-flow-main/docs/16-代理系统深度解析.md
- [ ] 327. /data/deer-flow-main/docs/17-架构设计权衡-没有完美的架构.md
- [ ] 328. /data/deer-flow-main/docs/17-沙箱系统深度解析.md
- [ ] 329. /data/deer-flow-main/docs/18-工具系统深度解析.md
- [ ] 330. /data/deer-flow-main/docs/18-面试高频问题清单.md
- [ ] 331. /data/deer-flow-main/docs/18-面试高频问题清单-基于实际代码整理.md
- [ ] 332. /data/deer-flow-main/docs/19-MCP集成系统深度解析.md
- [ ] 333. /data/deer-flow-main/docs/19-扩展点在哪里-二次开发入门.md
- [ ] 334. /data/deer-flow-main/docs/20-从0到1创建自定义技能-实战指南.md
- [ ] 335. /data/deer-flow-main/docs/20-技能系统深度解析.md
- [ ] 336. /data/deer-flow-main/docs/21-模型工厂与多模型支持系统.md
- [ ] 337. /data/deer-flow-main/docs/22-配置系统深度解析.md
- [ ] 338. /data/deer-flow-main/docs/23-反射系统与动态模块加载.md
- [ ] 339. /data/deer-flow-main/docs/24-记忆系统深度解析.md
- [ ] 340. /data/deer-flow-main/docs/25-标题生成系统深度解析.md
- [ ] 341. /data/deer-flow-main/docs/26-上下文摘要系统深度解析.md
- [ ] 342. /data/deer-flow-main/docs/27-前端架构总览.md
- [ ] 343. /data/deer-flow-main/docs/28-API路由系统详解.md
- [ ] 344. /data/deer-flow-main/docs/29-部署与运维指南.md
- [ ] 345. /data/deer-flow-main/docs/30-完整项目索引与学习路径.md
- [ ] 346. /data/deer-flow-main/docs/31-示例工作流与技能使用指南.md
- [ ] 347. /data/deer-flow-main/docs/32-子代理系统深度解析.md
- [ ] 348. /data/deer-flow-main/docs/33-AIO沙箱系统深度解析.md
- [ ] 349. /data/deer-flow-main/docs/34-InfoQuest集成详解.md
- [ ] 350. /data/deer-flow-main/docs/CODE_CHANGE_SUMMARY_BY_FILE.md
- [ ] 351. /data/deer-flow-main/docs/DeerFlow项目结构总览-下一轮AI任务前置知识.md
- [ ] 352. /data/deer-flow-main/docs/SKILL_NAME_CONFLICT_FIX.md
- [ ] 353. /data/deer-flow-main/extensions_config.example.json
- [ ] 354. /data/deer-flow-main/frontend/AGENTS.md
- [ ] 355. /data/deer-flow-main/frontend/CLAUDE.md
- [ ] 356. /data/deer-flow-main/frontend/components.json
- [ ] 357. /data/deer-flow-main/frontend/eslint.config.js
- [ ] 358. /data/deer-flow-main/frontend/next.config.js
- [ ] 359. /data/deer-flow-main/frontend/package.json
- [ ] 360. /data/deer-flow-main/frontend/pnpm-lock.yaml
- [ ] 361. /data/deer-flow-main/frontend/pnpm-workspace.yaml
- [ ] 362. /data/deer-flow-main/frontend/postcss.config.js
- [ ] 363. /data/deer-flow-main/frontend/prettier.config.js
- [ ] 364. /data/deer-flow-main/frontend/public/demo/threads/21cfea46-34bd-4aa6-9e1f-3009452fbeb9/thread.json
- [ ] 365. /data/deer-flow-main/frontend/public/demo/threads/3823e443-4e2b-4679-b496-a9506eae462b/thread.json
- [ ] 366. /data/deer-flow-main/frontend/public/demo/threads/3823e443-4e2b-4679-b496-a9506eae462b/user-data/outputs/fei-fei-li-podcast-timeline.md
- [ ] 367. /data/deer-flow-main/frontend/public/demo/threads/4f3e55ee-f853-43db-bfb3-7d1a411f03cb/thread.json
- [ ] 368. /data/deer-flow-main/frontend/public/demo/threads/5aa47db1-d0cb-4eb9-aea5-3dac1b371c5a/thread.json
- [ ] 369. /data/deer-flow-main/frontend/public/demo/threads/5aa47db1-d0cb-4eb9-aea5-3dac1b371c5a/user-data/outputs/jiangsu-football/js/data.js
- [ ] 370. /data/deer-flow-main/frontend/public/demo/threads/5aa47db1-d0cb-4eb9-aea5-3dac1b371c5a/user-data/outputs/jiangsu-football/js/main.js
- [ ] 371. /data/deer-flow-main/frontend/public/demo/threads/7cfa5f8f-a2f8-47ad-acbd-da7137baf990/thread.json
- [ ] 372. /data/deer-flow-main/frontend/public/demo/threads/7cfa5f8f-a2f8-47ad-acbd-da7137baf990/user-data/outputs/script.js
- [ ] 373. /data/deer-flow-main/frontend/public/demo/threads/7f9dc56c-e49c-4671-a3d2-c492ff4dce0c/thread.json
- [ ] 374. /data/deer-flow-main/frontend/public/demo/threads/7f9dc56c-e49c-4671-a3d2-c492ff4dce0c/user-data/outputs/leica-master-photography-article.md
- [ ] 375. /data/deer-flow-main/frontend/public/demo/threads/90040b36-7eba-4b97-ba89-02c3ad47a8b9/thread.json
- [ ] 376. /data/deer-flow-main/frontend/public/demo/threads/ad76c455-5bf9-4335-8517-fc03834ab828/thread.json
- [ ] 377. /data/deer-flow-main/frontend/public/demo/threads/b83fbb2a-4e36-4d82-9de0-7b2a02c2092a/thread.json
- [ ] 378. /data/deer-flow-main/frontend/public/demo/threads/c02bb4d5-4202-490e-ae8f-ff4864fc0d2e/thread.json
- [ ] 379. /data/deer-flow-main/frontend/public/demo/threads/c02bb4d5-4202-490e-ae8f-ff4864fc0d2e/user-data/outputs/script.js
- [ ] 380. /data/deer-flow-main/frontend/public/demo/threads/d3e5adaf-084c-4dd5-9d29-94f1d6bccd98/thread.json
- [ ] 381. /data/deer-flow-main/frontend/public/demo/threads/d3e5adaf-084c-4dd5-9d29-94f1d6bccd98/user-data/outputs/diana_hu_research.md
- [ ] 382. /data/deer-flow-main/frontend/public/demo/threads/f4125791-0128-402a-8ca9-50e0947557e4/thread.json
- [ ] 383. /data/deer-flow-main/frontend/public/demo/threads/fe3f7974-1bcb-4a01-a950-79673baafefd/thread.json
- [ ] 384. /data/deer-flow-main/frontend/public/demo/threads/fe3f7974-1bcb-4a01-a950-79673baafefd/user-data/outputs/research_deerflow_20260201.md
- [ ] 385. /data/deer-flow-main/frontend/README.md
- [ ] 386. /data/deer-flow-main/frontend/scripts/save-demo.js
- [ ] 387. /data/deer-flow-main/frontend/src/app/api/auth/[...all]/route.ts
- [ ] 388. /data/deer-flow-main/frontend/src/app/api/memory/[...path]/route.ts
- [ ] 389. /data/deer-flow-main/frontend/src/app/api/memory/route.ts
- [ ] 390. /data/deer-flow-main/frontend/src/app/layout.tsx
- [ ] 391. /data/deer-flow-main/frontend/src/app/mock/api/mcp/config/route.ts
- [ ] 392. /data/deer-flow-main/frontend/src/app/mock/api/models/route.ts
- [ ] 393. /data/deer-flow-main/frontend/src/app/mock/api/skills/route.ts
- [ ] 394. /data/deer-flow-main/frontend/src/app/mock/api/threads/search/route.ts
- [ ] 395. /data/deer-flow-main/frontend/src/app/mock/api/threads/[thread_id]/artifacts/[[...artifact_path]]/route.ts
- [ ] 396. /data/deer-flow-main/frontend/src/app/mock/api/threads/[thread_id]/history/route.ts
- [ ] 397. /data/deer-flow-main/frontend/src/app/page.tsx
- [ ] 398. /data/deer-flow-main/frontend/src/app/workspace/agents/[agent_name]/chats/[thread_id]/layout.tsx
- [ ] 399. /data/deer-flow-main/frontend/src/app/workspace/agents/[agent_name]/chats/[thread_id]/page.tsx
- [ ] 400. /data/deer-flow-main/frontend/src/app/workspace/agents/new/page.tsx
- [ ] 401. /data/deer-flow-main/frontend/src/app/workspace/agents/page.tsx
- [ ] 402. /data/deer-flow-main/frontend/src/app/workspace/chats/page.tsx
- [ ] 403. /data/deer-flow-main/frontend/src/app/workspace/chats/[thread_id]/layout.tsx
- [ ] 404. /data/deer-flow-main/frontend/src/app/workspace/chats/[thread_id]/page.tsx
- [ ] 405. /data/deer-flow-main/frontend/src/app/workspace/layout.tsx
- [ ] 406. /data/deer-flow-main/frontend/src/app/workspace/page.tsx
- [ ] 407. /data/deer-flow-main/frontend/src/components/ai-elements/artifact.tsx
- [ ] 408. /data/deer-flow-main/frontend/src/components/ai-elements/canvas.tsx
- [ ] 409. /data/deer-flow-main/frontend/src/components/ai-elements/chain-of-thought.tsx
- [ ] 410. /data/deer-flow-main/frontend/src/components/ai-elements/checkpoint.tsx
- [ ] 411. /data/deer-flow-main/frontend/src/components/ai-elements/code-block.tsx
- [ ] 412. /data/deer-flow-main/frontend/src/components/ai-elements/connection.tsx
- [ ] 413. /data/deer-flow-main/frontend/src/components/ai-elements/context.tsx
- [ ] 414. /data/deer-flow-main/frontend/src/components/ai-elements/controls.tsx
- [ ] 415. /data/deer-flow-main/frontend/src/components/ai-elements/conversation.tsx
- [ ] 416. /data/deer-flow-main/frontend/src/components/ai-elements/edge.tsx
- [ ] 417. /data/deer-flow-main/frontend/src/components/ai-elements/image.tsx
- [ ] 418. /data/deer-flow-main/frontend/src/components/ai-elements/loader.tsx
- [ ] 419. /data/deer-flow-main/frontend/src/components/ai-elements/message.tsx
- [ ] 420. /data/deer-flow-main/frontend/src/components/ai-elements/model-selector.tsx
- [ ] 421. /data/deer-flow-main/frontend/src/components/ai-elements/node.tsx
- [ ] 422. /data/deer-flow-main/frontend/src/components/ai-elements/open-in-chat.tsx
- [ ] 423. /data/deer-flow-main/frontend/src/components/ai-elements/panel.tsx
- [ ] 424. /data/deer-flow-main/frontend/src/components/ai-elements/plan.tsx
- [ ] 425. /data/deer-flow-main/frontend/src/components/ai-elements/prompt-input.tsx
- [ ] 426. /data/deer-flow-main/frontend/src/components/ai-elements/queue.tsx
- [ ] 427. /data/deer-flow-main/frontend/src/components/ai-elements/reasoning.tsx
- [ ] 428. /data/deer-flow-main/frontend/src/components/ai-elements/shimmer.tsx
- [ ] 429. /data/deer-flow-main/frontend/src/components/ai-elements/sources.tsx
- [ ] 430. /data/deer-flow-main/frontend/src/components/ai-elements/suggestion.tsx
- [ ] 431. /data/deer-flow-main/frontend/src/components/ai-elements/task.tsx
- [ ] 432. /data/deer-flow-main/frontend/src/components/ai-elements/toolbar.tsx
- [ ] 433. /data/deer-flow-main/frontend/src/components/ai-elements/web-preview.tsx
- [ ] 434. /data/deer-flow-main/frontend/src/components/landing/footer.tsx
- [ ] 435. /data/deer-flow-main/frontend/src/components/landing/header.tsx
- [ ] 436. /data/deer-flow-main/frontend/src/components/landing/hero.tsx
- [ ] 437. /data/deer-flow-main/frontend/src/components/landing/progressive-skills-animation.tsx
- [ ] 438. /data/deer-flow-main/frontend/src/components/landing/sections/case-study-section.tsx
- [ ] 439. /data/deer-flow-main/frontend/src/components/landing/sections/community-section.tsx
- [ ] 440. /data/deer-flow-main/frontend/src/components/landing/sections/sandbox-section.tsx
- [ ] 441. /data/deer-flow-main/frontend/src/components/landing/sections/skills-section.tsx
- [ ] 442. /data/deer-flow-main/frontend/src/components/landing/sections/whats-new-section.tsx
- [ ] 443. /data/deer-flow-main/frontend/src/components/landing/section.tsx
- [ ] 444. /data/deer-flow-main/frontend/src/components/theme-provider.tsx
- [ ] 445. /data/deer-flow-main/frontend/src/components/ui/alert.tsx
- [ ] 446. /data/deer-flow-main/frontend/src/components/ui/aurora-text.tsx
- [ ] 447. /data/deer-flow-main/frontend/src/components/ui/avatar.tsx
- [ ] 448. /data/deer-flow-main/frontend/src/components/ui/badge.tsx
- [ ] 449. /data/deer-flow-main/frontend/src/components/ui/breadcrumb.tsx
- [ ] 450. /data/deer-flow-main/frontend/src/components/ui/button-group.tsx
- [ ] 451. /data/deer-flow-main/frontend/src/components/ui/button.tsx
- [ ] 452. /data/deer-flow-main/frontend/src/components/ui/card.tsx
- [ ] 453. /data/deer-flow-main/frontend/src/components/ui/carousel.tsx
- [ ] 454. /data/deer-flow-main/frontend/src/components/ui/collapsible.tsx
- [ ] 455. /data/deer-flow-main/frontend/src/components/ui/command.tsx
- [ ] 456. /data/deer-flow-main/frontend/src/components/ui/confetti-button.tsx
- [ ] 457. /data/deer-flow-main/frontend/src/components/ui/dialog.tsx
- [ ] 458. /data/deer-flow-main/frontend/src/components/ui/dropdown-menu.tsx
- [ ] 459. /data/deer-flow-main/frontend/src/components/ui/empty.tsx
- [ ] 460. /data/deer-flow-main/frontend/src/components/ui/flickering-grid.tsx
- [ ] 461. /data/deer-flow-main/frontend/src/components/ui/galaxy.jsx
- [ ] 462. /data/deer-flow-main/frontend/src/components/ui/hover-card.tsx
- [ ] 463. /data/deer-flow-main/frontend/src/components/ui/input-group.tsx
- [ ] 464. /data/deer-flow-main/frontend/src/components/ui/input.tsx
- [ ] 465. /data/deer-flow-main/frontend/src/components/ui/item.tsx
- [ ] 466. /data/deer-flow-main/frontend/src/components/ui/magic-bento.tsx
- [ ] 467. /data/deer-flow-main/frontend/src/components/ui/number-ticker.tsx
- [ ] 468. /data/deer-flow-main/frontend/src/components/ui/progress.tsx
- [ ] 469. /data/deer-flow-main/frontend/src/components/ui/resizable.tsx
- [ ] 470. /data/deer-flow-main/frontend/src/components/ui/scroll-area.tsx
- [ ] 471. /data/deer-flow-main/frontend/src/components/ui/select.tsx
- [ ] 472. /data/deer-flow-main/frontend/src/components/ui/separator.tsx
- [ ] 473. /data/deer-flow-main/frontend/src/components/ui/sheet.tsx
- [ ] 474. /data/deer-flow-main/frontend/src/components/ui/shine-border.tsx
- [ ] 475. /data/deer-flow-main/frontend/src/components/ui/sidebar.tsx
- [ ] 476. /data/deer-flow-main/frontend/src/components/ui/skeleton.tsx
- [ ] 477. /data/deer-flow-main/frontend/src/components/ui/sonner.tsx
- [ ] 478. /data/deer-flow-main/frontend/src/components/ui/spotlight-card.tsx
- [ ] 479. /data/deer-flow-main/frontend/src/components/ui/switch.tsx
- [ ] 480. /data/deer-flow-main/frontend/src/components/ui/tabs.tsx
- [ ] 481. /data/deer-flow-main/frontend/src/components/ui/terminal.tsx
- [ ] 482. /data/deer-flow-main/frontend/src/components/ui/textarea.tsx
- [ ] 483. /data/deer-flow-main/frontend/src/components/ui/toggle-group.tsx
- [ ] 484. /data/deer-flow-main/frontend/src/components/ui/toggle.tsx
- [ ] 485. /data/deer-flow-main/frontend/src/components/ui/tooltip.tsx
- [ ] 486. /data/deer-flow-main/frontend/src/components/ui/word-rotate.tsx
- [ ] 487. /data/deer-flow-main/frontend/src/components/workspace/agents/agent-card.tsx
- [ ] 488. /data/deer-flow-main/frontend/src/components/workspace/agents/agent-gallery.tsx
- [ ] 489. /data/deer-flow-main/frontend/src/components/workspace/agent-welcome.tsx
- [ ] 490. /data/deer-flow-main/frontend/src/components/workspace/artifacts/artifact-file-detail.tsx
- [ ] 491. /data/deer-flow-main/frontend/src/components/workspace/artifacts/artifact-file-list.tsx
- [ ] 492. /data/deer-flow-main/frontend/src/components/workspace/artifacts/artifact-trigger.tsx
- [ ] 493. /data/deer-flow-main/frontend/src/components/workspace/artifacts/context.tsx
- [ ] 494. /data/deer-flow-main/frontend/src/components/workspace/artifacts/index.ts
- [ ] 495. /data/deer-flow-main/frontend/src/components/workspace/chats/chat-box.tsx
- [ ] 496. /data/deer-flow-main/frontend/src/components/workspace/chats/index.ts
- [ ] 497. /data/deer-flow-main/frontend/src/components/workspace/chats/use-chat-mode.ts
- [ ] 498. /data/deer-flow-main/frontend/src/components/workspace/chats/use-thread-chat.ts
- [ ] 499. /data/deer-flow-main/frontend/src/components/workspace/citations/artifact-link.tsx
- [ ] 500. /data/deer-flow-main/frontend/src/components/workspace/citations/citation-link.tsx
- [ ] 501. /data/deer-flow-main/frontend/src/components/workspace/code-editor.tsx
- [ ] 502. /data/deer-flow-main/frontend/src/components/workspace/command-palette.tsx
- [ ] 503. /data/deer-flow-main/frontend/src/components/workspace/copy-button.tsx
- [ ] 504. /data/deer-flow-main/frontend/src/components/workspace/export-trigger.tsx
- [ ] 505. /data/deer-flow-main/frontend/src/components/workspace/flip-display.tsx
- [ ] 506. /data/deer-flow-main/frontend/src/components/workspace/github-icon.tsx
- [ ] 507. /data/deer-flow-main/frontend/src/components/workspace/input-box.tsx
- [ ] 508. /data/deer-flow-main/frontend/src/components/workspace/messages/context.ts
- [ ] 509. /data/deer-flow-main/frontend/src/components/workspace/messages/index.ts
- [ ] 510. /data/deer-flow-main/frontend/src/components/workspace/messages/markdown-content.tsx
- [ ] 511. /data/deer-flow-main/frontend/src/components/workspace/messages/message-group.tsx
- [ ] 512. /data/deer-flow-main/frontend/src/components/workspace/messages/message-list-item.tsx
- [ ] 513. /data/deer-flow-main/frontend/src/components/workspace/messages/message-list.tsx
- [ ] 514. /data/deer-flow-main/frontend/src/components/workspace/messages/skeleton.tsx
- [ ] 515. /data/deer-flow-main/frontend/src/components/workspace/messages/subtask-card.tsx
- [ ] 516. /data/deer-flow-main/frontend/src/components/workspace/mode-hover-guide.tsx
- [ ] 517. /data/deer-flow-main/frontend/src/components/workspace/overscroll.tsx
- [ ] 518. /data/deer-flow-main/frontend/src/components/workspace/recent-chat-list.tsx
- [ ] 519. /data/deer-flow-main/frontend/src/components/workspace/settings/about-content.ts
- [ ] 520. /data/deer-flow-main/frontend/src/components/workspace/settings/about.md
- [ ] 521. /data/deer-flow-main/frontend/src/components/workspace/settings/about-settings-page.tsx
- [ ] 522. /data/deer-flow-main/frontend/src/components/workspace/settings/appearance-settings-page.tsx
- [ ] 523. /data/deer-flow-main/frontend/src/components/workspace/settings/index.ts
- [ ] 524. /data/deer-flow-main/frontend/src/components/workspace/settings/memory-settings-page.tsx
- [ ] 525. /data/deer-flow-main/frontend/src/components/workspace/settings/notification-settings-page.tsx
- [ ] 526. /data/deer-flow-main/frontend/src/components/workspace/settings/settings-dialog.tsx
- [ ] 527. /data/deer-flow-main/frontend/src/components/workspace/settings/settings-section.tsx
- [ ] 528. /data/deer-flow-main/frontend/src/components/workspace/settings/skill-settings-page.tsx
- [ ] 529. /data/deer-flow-main/frontend/src/components/workspace/settings/tool-settings-page.tsx
- [ ] 530. /data/deer-flow-main/frontend/src/components/workspace/streaming-indicator.tsx
- [ ] 531. /data/deer-flow-main/frontend/src/components/workspace/thread-title.tsx
- [ ] 532. /data/deer-flow-main/frontend/src/components/workspace/todo-list.tsx
- [ ] 533. /data/deer-flow-main/frontend/src/components/workspace/token-usage-indicator.tsx
- [ ] 534. /data/deer-flow-main/frontend/src/components/workspace/tooltip.tsx
- [ ] 535. /data/deer-flow-main/frontend/src/components/workspace/welcome.tsx
- [ ] 536. /data/deer-flow-main/frontend/src/components/workspace/workspace-container.tsx
- [ ] 537. /data/deer-flow-main/frontend/src/components/workspace/workspace-header.tsx
- [ ] 538. /data/deer-flow-main/frontend/src/components/workspace/workspace-nav-chat-list.tsx
- [ ] 539. /data/deer-flow-main/frontend/src/components/workspace/workspace-nav-menu.tsx
- [ ] 540. /data/deer-flow-main/frontend/src/components/workspace/workspace-sidebar.tsx
- [ ] 541. /data/deer-flow-main/frontend/src/core/agents/api.ts
- [ ] 542. /data/deer-flow-main/frontend/src/core/agents/hooks.ts
- [ ] 543. /data/deer-flow-main/frontend/src/core/agents/index.ts
- [ ] 544. /data/deer-flow-main/frontend/src/core/agents/types.ts
- [ ] 545. /data/deer-flow-main/frontend/src/core/api/api-client.ts
- [ ] 546. /data/deer-flow-main/frontend/src/core/api/index.ts
- [ ] 547. /data/deer-flow-main/frontend/src/core/api/stream-mode.test.ts
- [ ] 548. /data/deer-flow-main/frontend/src/core/api/stream-mode.ts
- [ ] 549. /data/deer-flow-main/frontend/src/core/artifacts/hooks.ts
- [ ] 550. /data/deer-flow-main/frontend/src/core/artifacts/index.ts
- [ ] 551. /data/deer-flow-main/frontend/src/core/artifacts/loader.ts
- [ ] 552. /data/deer-flow-main/frontend/src/core/artifacts/utils.ts
- [ ] 553. /data/deer-flow-main/frontend/src/core/config/index.ts
- [ ] 554. /data/deer-flow-main/frontend/src/core/i18n/context.tsx
- [ ] 555. /data/deer-flow-main/frontend/src/core/i18n/cookies.ts
- [ ] 556. /data/deer-flow-main/frontend/src/core/i18n/hooks.ts
- [ ] 557. /data/deer-flow-main/frontend/src/core/i18n/index.ts
- [ ] 558. /data/deer-flow-main/frontend/src/core/i18n/locales/en-US.ts
- [ ] 559. /data/deer-flow-main/frontend/src/core/i18n/locales/index.ts
- [ ] 560. /data/deer-flow-main/frontend/src/core/i18n/locales/types.ts
- [ ] 561. /data/deer-flow-main/frontend/src/core/i18n/locales/zh-CN.ts
- [ ] 562. /data/deer-flow-main/frontend/src/core/i18n/locale.ts
- [ ] 563. /data/deer-flow-main/frontend/src/core/i18n/server.ts
- [ ] 564. /data/deer-flow-main/frontend/src/core/mcp/api.ts
- [ ] 565. /data/deer-flow-main/frontend/src/core/mcp/hooks.ts
- [ ] 566. /data/deer-flow-main/frontend/src/core/mcp/index.ts
- [ ] 567. /data/deer-flow-main/frontend/src/core/mcp/types.ts
- [ ] 568. /data/deer-flow-main/frontend/src/core/memory/api.ts
- [ ] 569. /data/deer-flow-main/frontend/src/core/memory/hooks.ts
- [ ] 570. /data/deer-flow-main/frontend/src/core/memory/index.ts
- [ ] 571. /data/deer-flow-main/frontend/src/core/memory/types.ts
- [ ] 572. /data/deer-flow-main/frontend/src/core/messages/usage.ts
- [ ] 573. /data/deer-flow-main/frontend/src/core/messages/utils.ts
- [ ] 574. /data/deer-flow-main/frontend/src/core/models/api.ts
- [ ] 575. /data/deer-flow-main/frontend/src/core/models/hooks.ts
- [ ] 576. /data/deer-flow-main/frontend/src/core/models/index.ts
- [ ] 577. /data/deer-flow-main/frontend/src/core/models/types.ts
- [ ] 578. /data/deer-flow-main/frontend/src/core/notification/hooks.ts
- [ ] 579. /data/deer-flow-main/frontend/src/core/rehype/index.ts
- [ ] 580. /data/deer-flow-main/frontend/src/core/settings/hooks.ts
- [ ] 581. /data/deer-flow-main/frontend/src/core/settings/index.ts
- [ ] 582. /data/deer-flow-main/frontend/src/core/settings/local.ts
- [ ] 583. /data/deer-flow-main/frontend/src/core/skills/api.ts
- [ ] 584. /data/deer-flow-main/frontend/src/core/skills/hooks.ts
- [ ] 585. /data/deer-flow-main/frontend/src/core/skills/index.ts
- [ ] 586. /data/deer-flow-main/frontend/src/core/skills/type.ts
- [ ] 587. /data/deer-flow-main/frontend/src/core/streamdown/index.ts
- [ ] 588. /data/deer-flow-main/frontend/src/core/streamdown/plugins.ts
- [ ] 589. /data/deer-flow-main/frontend/src/core/tasks/context.tsx
- [ ] 590. /data/deer-flow-main/frontend/src/core/tasks/index.ts
- [ ] 591. /data/deer-flow-main/frontend/src/core/tasks/types.ts
- [ ] 592. /data/deer-flow-main/frontend/src/core/threads/export.ts
- [ ] 593. /data/deer-flow-main/frontend/src/core/threads/hooks.ts
- [ ] 594. /data/deer-flow-main/frontend/src/core/threads/index.ts
- [ ] 595. /data/deer-flow-main/frontend/src/core/threads/types.ts
- [ ] 596. /data/deer-flow-main/frontend/src/core/threads/utils.ts
- [ ] 597. /data/deer-flow-main/frontend/src/core/todos/index.ts
- [ ] 598. /data/deer-flow-main/frontend/src/core/todos/types.ts
- [ ] 599. /data/deer-flow-main/frontend/src/core/tools/utils.ts
- [ ] 600. /data/deer-flow-main/frontend/src/core/uploads/api.ts
- [ ] 601. /data/deer-flow-main/frontend/src/core/uploads/hooks.ts
- [ ] 602. /data/deer-flow-main/frontend/src/core/uploads/index.ts
- [ ] 603. /data/deer-flow-main/frontend/src/core/utils/datetime.ts
- [ ] 604. /data/deer-flow-main/frontend/src/core/utils/files.tsx
- [ ] 605. /data/deer-flow-main/frontend/src/core/utils/json.ts
- [ ] 606. /data/deer-flow-main/frontend/src/core/utils/markdown.ts
- [ ] 607. /data/deer-flow-main/frontend/src/core/utils/uuid.ts
- [ ] 608. /data/deer-flow-main/frontend/src/env.js
- [ ] 609. /data/deer-flow-main/frontend/src/hooks/use-global-shortcuts.ts
- [ ] 610. /data/deer-flow-main/frontend/src/hooks/use-mobile.ts
- [ ] 611. /data/deer-flow-main/frontend/src/lib/ime.ts
- [ ] 612. /data/deer-flow-main/frontend/src/lib/utils.ts
- [ ] 613. /data/deer-flow-main/frontend/src/server/better-auth/client.ts
- [ ] 614. /data/deer-flow-main/frontend/src/server/better-auth/config.ts
- [ ] 615. /data/deer-flow-main/frontend/src/server/better-auth/index.ts
- [ ] 616. /data/deer-flow-main/frontend/src/server/better-auth/server.ts
- [ ] 617. /data/deer-flow-main/frontend/src/typings/md.d.ts
- [ ] 618. /data/deer-flow-main/frontend/tsconfig.json
- [ ] 619. /data/deer-flow-main/frontend/.vscode/settings.json
- [ ] 620. /data/deer-flow-main/.github/copilot-instructions.md
- [ ] 621. /data/deer-flow-main/.github/ISSUE_TEMPLATE/runtime-information.yml
- [ ] 622. /data/deer-flow-main/.github/workflows/backend-unit-tests.yml
- [ ] 623. /data/deer-flow-main/.github/workflows/lint-check.yml
- [ ] 624. /data/deer-flow-main/Install.md
- [ ] 625. /data/deer-flow-main/PLAN.md
- [ ] 626. /data/deer-flow-main/plan/学习路径计划-架构与面试.md
- [ ] 627. /data/deer-flow-main/plan/总分目标与执行计划.md
- [ ] 628. /data/deer-flow-main/README_fr.md
- [ ] 629. /data/deer-flow-main/README_ja.md
- [ ] 630. /data/deer-flow-main/README.md
- [ ] 631. /data/deer-flow-main/README_ru.md
- [ ] 632. /data/deer-flow-main/README_zh.md
- [ ] 633. /data/deer-flow-main/scripts/check.py
- [ ] 634. /data/deer-flow-main/scripts/configure.py
- [ ] 635. /data/deer-flow-main/scripts/export_claude_code_oauth.py
- [ ] 636. /data/deer-flow-main/scripts/load_memory_sample.py
- [ ] 637. /data/deer-flow-main/SECURITY.md
- [ ] 638. /data/deer-flow-main/skills/public/bootstrap/references/conversation-guide.md
- [ ] 639. /data/deer-flow-main/skills/public/bootstrap/SKILL.md
- [ ] 640. /data/deer-flow-main/skills/public/bootstrap/templates/SOUL.template.md
- [ ] 641. /data/deer-flow-main/skills/public/chart-visualization/references/generate_area_chart.md
- [ ] 642. /data/deer-flow-main/skills/public/chart-visualization/references/generate_bar_chart.md
- [ ] 643. /data/deer-flow-main/skills/public/chart-visualization/references/generate_boxplot_chart.md
- [ ] 644. /data/deer-flow-main/skills/public/chart-visualization/references/generate_column_chart.md
- [ ] 645. /data/deer-flow-main/skills/public/chart-visualization/references/generate_district_map.md
- [ ] 646. /data/deer-flow-main/skills/public/chart-visualization/references/generate_dual_axes_chart.md
- [ ] 647. /data/deer-flow-main/skills/public/chart-visualization/references/generate_fishbone_diagram.md
- [ ] 648. /data/deer-flow-main/skills/public/chart-visualization/references/generate_flow_diagram.md
- [ ] 649. /data/deer-flow-main/skills/public/chart-visualization/references/generate_funnel_chart.md
- [ ] 650. /data/deer-flow-main/skills/public/chart-visualization/references/generate_histogram_chart.md
- [ ] 651. /data/deer-flow-main/skills/public/chart-visualization/references/generate_line_chart.md
- [ ] 652. /data/deer-flow-main/skills/public/chart-visualization/references/generate_liquid_chart.md
- [ ] 653. /data/deer-flow-main/skills/public/chart-visualization/references/generate_mind_map.md
- [ ] 654. /data/deer-flow-main/skills/public/chart-visualization/references/generate_network_graph.md
- [ ] 655. /data/deer-flow-main/skills/public/chart-visualization/references/generate_organization_chart.md
- [ ] 656. /data/deer-flow-main/skills/public/chart-visualization/references/generate_path_map.md
- [ ] 657. /data/deer-flow-main/skills/public/chart-visualization/references/generate_pie_chart.md
- [ ] 658. /data/deer-flow-main/skills/public/chart-visualization/references/generate_pin_map.md
- [ ] 659. /data/deer-flow-main/skills/public/chart-visualization/references/generate_radar_chart.md
- [ ] 660. /data/deer-flow-main/skills/public/chart-visualization/references/generate_sankey_chart.md
- [ ] 661. /data/deer-flow-main/skills/public/chart-visualization/references/generate_scatter_chart.md
- [ ] 662. /data/deer-flow-main/skills/public/chart-visualization/references/generate_spreadsheet.md
- [ ] 663. /data/deer-flow-main/skills/public/chart-visualization/references/generate_treemap_chart.md
- [ ] 664. /data/deer-flow-main/skills/public/chart-visualization/references/generate_venn_chart.md
- [ ] 665. /data/deer-flow-main/skills/public/chart-visualization/references/generate_violin_chart.md
- [ ] 666. /data/deer-flow-main/skills/public/chart-visualization/references/generate_word_cloud_chart.md
- [ ] 667. /data/deer-flow-main/skills/public/chart-visualization/scripts/generate.js
- [ ] 668. /data/deer-flow-main/skills/public/chart-visualization/SKILL.md
- [ ] 669. /data/deer-flow-main/skills/public/claude-to-deerflow/SKILL.md
- [ ] 670. /data/deer-flow-main/skills/public/consulting-analysis/SKILL.md
- [ ] 671. /data/deer-flow-main/skills/public/data-analysis/scripts/analyze.py
- [ ] 672. /data/deer-flow-main/skills/public/data-analysis/SKILL.md
- [ ] 673. /data/deer-flow-main/skills/public/deep-research/SKILL.md
- [ ] 674. /data/deer-flow-main/skills/public/find-skills/SKILL.md
- [ ] 675. /data/deer-flow-main/skills/public/frontend-design/SKILL.md
- [ ] 676. /data/deer-flow-main/skills/public/github-deep-research/assets/report_template.md
- [ ] 677. /data/deer-flow-main/skills/public/github-deep-research/scripts/github_api.py
- [ ] 678. /data/deer-flow-main/skills/public/github-deep-research/SKILL.md
- [ ] 679. /data/deer-flow-main/skills/public/image-generation/scripts/generate.py
- [ ] 680. /data/deer-flow-main/skills/public/image-generation/SKILL.md
- [ ] 681. /data/deer-flow-main/skills/public/image-generation/templates/doraemon.md
- [ ] 682. /data/deer-flow-main/skills/public/podcast-generation/scripts/generate.py
- [ ] 683. /data/deer-flow-main/skills/public/podcast-generation/SKILL.md
- [ ] 684. /data/deer-flow-main/skills/public/podcast-generation/templates/tech-explainer.md
- [ ] 685. /data/deer-flow-main/skills/public/ppt-generation/scripts/generate.py
- [ ] 686. /data/deer-flow-main/skills/public/ppt-generation/SKILL.md
- [ ] 687. /data/deer-flow-main/skills/public/skill-creator/agents/analyzer.md
- [ ] 688. /data/deer-flow-main/skills/public/skill-creator/agents/comparator.md
- [ ] 689. /data/deer-flow-main/skills/public/skill-creator/agents/grader.md
- [ ] 690. /data/deer-flow-main/skills/public/skill-creator/eval-viewer/generate_review.py
- [ ] 691. /data/deer-flow-main/skills/public/skill-creator/references/output-patterns.md
- [ ] 692. /data/deer-flow-main/skills/public/skill-creator/references/schemas.md
- [ ] 693. /data/deer-flow-main/skills/public/skill-creator/references/workflows.md
- [ ] 694. /data/deer-flow-main/skills/public/skill-creator/scripts/aggregate_benchmark.py
- [ ] 695. /data/deer-flow-main/skills/public/skill-creator/scripts/generate_report.py
- [ ] 696. /data/deer-flow-main/skills/public/skill-creator/scripts/improve_description.py
- [ ] 697. /data/deer-flow-main/skills/public/skill-creator/scripts/init_skill.py
- [ ] 698. /data/deer-flow-main/skills/public/skill-creator/scripts/package_skill.py
- [ ] 699. /data/deer-flow-main/skills/public/skill-creator/scripts/quick_validate.py
- [ ] 700. /data/deer-flow-main/skills/public/skill-creator/scripts/run_eval.py
- [ ] 701. /data/deer-flow-main/skills/public/skill-creator/scripts/run_loop.py
- [ ] 702. /data/deer-flow-main/skills/public/skill-creator/scripts/utils.py
- [ ] 703. /data/deer-flow-main/skills/public/skill-creator/SKILL.md
- [ ] 704. /data/deer-flow-main/skills/public/surprise-me/SKILL.md
- [ ] 705. /data/deer-flow-main/skills/public/vercel-deploy-claimable/SKILL.md
- [ ] 706. /data/deer-flow-main/skills/public/video-generation/scripts/generate.py
- [ ] 707. /data/deer-flow-main/skills/public/video-generation/SKILL.md
- [ ] 708. /data/deer-flow-main/skills/public/web-design-guidelines/SKILL.md

---

## 📝 任务追踪 (130 Tasks)

### 任务执行状态
- **总任务数**: 130
- **已完成**: 5个任务 (#12-16)
- **进行中**: 125个任务 (#17-21, #22-130)
- **待分配**: 0个任务

### 批次执行状态

#### 批次 1: 文档检查 (已完成 ✅)
- 任务 #12-16: 检查文件053-089
- 状态: 已完成
- 结果: 确认文件已有详细中文注释

#### 批次 2: Client & Sandbox (进行中 🔄)
- 任务 #22-25: 文件090-097
- 状态: 已分配

#### 批次 3: Community Tools (进行中 🔄)
- 任务 #25-28: 文件098-107
- 状态: 已分配

#### 批次 4: Config Modules (进行中 🔄)
- 任务 #27-31: 文件108-127
- 状态: 已分配

#### 批次 5: Guardrails & MCP (进行中 🔄)
- 任务 #29-33: 文件128-140
- 状态: 已分配

#### 批次 6: Models & Runtime (进行中 🔄)
- 任务 #34-37: 文件141-164
- 状态: 已分配

#### 批次 7: Skills & Frontend (进行中 🔄)
- 任务 #39-66: 文件165-325
- 状态: 已分配

#### 批次 8: Tests & Tools (进行中 🔄)
- 任务 #67-81: 文件326-487
- 状态: 已分配

#### 批次 9: Frontend Components (进行中 🔄)
- 任务 #82-99: 文件488-541
- 状态: 已分配

#### 批次 10: Frontend Pages & Types (进行中 🔄)
- 任务 #100-130: 文件542-708
- 状态: 已分配

### 团队工作负载
- **annotator-1**: 26个任务
- **annotator-2**: 26个任务
- **annotator-3**: 26个任务
- **annotator-4**: 26个任务
- **annotator-5: 26个任务

---

## 📝 原任务追踪 (130 Tasks)

### 任务分配状态
- **已创建任务数**: 130
- **总文件数**: 708
- **已完成**: 89个文件 (001-089)
- **进行中**: 619个文件 (090-708)

### 批次概览

#### 批次 1-10: 文档和渠道 (001-089) ✅ 已完成
- 任务 #1-10: 覆盖文件001-089

#### 批次 11-20: Client和Sandbox (090-107)
- 任务 #22-27: Client、AioSandbox和社区工具

#### 批次 21-30: Config模块 (108-127)
- 任务 #28-36: 配置系统

#### 批次 31-40: Guardrails、MCP、Models (128-158)
- 任务 #32-41: 安全防护、模型工厂

#### 批次 41-50: Runtime、Sandbox、Subagents (159-201)
- 任务 #37-50: 运行时和沙箱

#### 批次 51-60: Tools、Skills、Frontend (202-253)
- 任务 #51-60: 工具和技能系统

#### 批次 61-70: Frontend核心 (254-325)
- 任务 #55-66: 前端组件和页面

#### 批次 71-80: 测试模块 (326-409)
- 任务 #67-81: 测试文件

#### 批次 81-90: Community工具 (410-487)
- 任务 #82-99: 社区工具和前端

#### 批次 91-100: Frontend组件和Store (488-541)
- 任务 #94-102: 前端组件和状态管理

#### 批次 101-110: Frontend页面和类型 (542-607)
- 任务 #103-119: 前端页面和Hooks

#### 批次 111-120: 文档和配置 (608-685)
- 任务 #111-122: 文档和配置文件

#### 批次 121-130: 最终文件 (686-708)
- 任务 #123-130: 工具入口和文档

### 团队分配
- **annotator-1**: 26个任务
- **annotator-2**: 26个任务
- **annotator-3**: 26个任务
- **annotator-4**: 26个任务
- **annotator-5**: 26个任务

### 当前进度
```
完成进度: ████████░░░░░░░░░░░░░░░░ 12.5% (89/708)
```
