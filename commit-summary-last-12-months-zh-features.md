# Deer-Flow 近一年按月 Commit 中文逐条分析（新功能/增强）

> 数据源：`origin/main` 最近12个月。

> 说明：每条 commit 都包含“明确新增内容”，直述新增/增强了什么。

GitHub 提交页：[https://github.com/bytedance/deer-flow/commits/main/](https://github.com/bytedance/deer-flow/commits/main/)

## 2025-06

- 提交数：16 条

#### 1. Add support for self-signed certs from model providers (#276)

- 提交：`[b7373fb](https://github.com/bytedance/deer-flow/commit/b7373fbe701bea278612ab06a1670adf8d6fb553)`
- 日期：2025-06-25
- 明确新增内容：新增了对“self-signed certs from model providers”的支持能力。
- 影响范围：主要涉及 其他模块、文档。
- 改动规模：+31 / -1 行。
- 关键文件：conf.yaml.example；docs/configuration_guide.md；src/llms/llm.py。

#### 2. improve: add abort btn to abort the mcp add request. (#284)

- 提交：`[9c2d472](https://github.com/bytedance/deer-flow/commit/9c2d4724e3ccd80b8e2add1d521b9d9ca1f1eb6a)`
- 日期：2025-06-26
- 明确新增内容：新增了“improve: add abort btn to abort the mcp add request”功能。
- 影响范围：主要涉及 其他模块。
- 改动规模：+25 / -4 行。
- 关键文件：web/src/app/settings/dialogs/add-mcp-server-dialog.tsx；web/src/core/api/mcp.ts。

#### 3. test: add unit tests of the app (#305)

- 提交：`[dcdd728](https://github.com/bytedance/deer-flow/commit/dcdd7288ed0c861551c3c1669c1ebcff8675a849)`
- 日期：2025-06-18
- 明确新增内容：新增了“add unit tests of the app”相关测试覆盖与验证用例。
- 影响范围：主要涉及 其他模块。
- 改动规模：+1113 / -16 行。
- 关键文件：src/server/app.py；src/tools/tts.py；tests/integration/test_tts.py；tests/unit/server/test_app.py；tests/unit/server/test_chat_request.py；tests/unit/server/test_mcp_request.py；tests/unit/server/test_mcp_utils.py。

#### 4. test: add unit tests for graph  (#296)

- 提交：`[c0b04aa](https://github.com/bytedance/deer-flow/commit/c0b04aaba288f6ca6f78c835244084e9319975e2)`
- 日期：2025-06-18
- 明确新增内容：新增了“add unit tests for graph”相关测试覆盖与验证用例。
- 影响范围：主要涉及 其他模块。
- 改动规模：+1436 / -2 行。
- 关键文件：src/graph/nodes.py；tests/integration/test_nodes.py；tests/unit/graph/test_builder.py；uv.lock。

#### 5. test: add test of json_utils (#309)

- 提交：`[4048ca6](https://github.com/bytedance/deer-flow/commit/4048ca67dd4de5b0d0e113979dd42c1db258b6c3)`
- 日期：2025-06-18
- 明确新增内容：新增了“add test of json_utils”相关测试覆盖与验证用例。
- 影响范围：主要涉及 其他模块。
- 改动规模：+110 / -0 行。
- 关键文件：tests/unit/utils/test_json_utils.py。

#### 6. feat: add deep think feature (#311)

- 提交：`[19fa1e9](https://github.com/bytedance/deer-flow/commit/19fa1e97c339e2d70d714706c4e75dc89f241311)`
- 日期：2025-06-14
- 明确新增内容：新增了“deep think feature”功能。
- 影响范围：主要涉及 其他模块、文档。
- 改动规模：+2315 / -1125 行。
- 关键文件：.gitignore；README.md；README_de.md；README_es.md；README_ja.md；README_pt.md；README_ru.md；README_zh.md。

#### 7. feat: append try catch (#280)

- 提交：`[7d38e5f](https://github.com/bytedance/deer-flow/commit/7d38e5f900a31cc47384f573893b4f0b57c1ce8b)`
- 日期：2025-06-12
- 明确新增内容：引入了“append try catch”相关功能改进。
- 影响范围：主要涉及 其他模块。
- 改动规模：+19 / -14 行。
- 关键文件：web/src/core/api/chat.ts。

#### 8. test: add more unit tests of tools (#315)

- 提交：`[4c2fe2e](https://github.com/bytedance/deer-flow/commit/4c2fe2e7f54f6823288e624ef5f739fbc3d71f7c)`
- 日期：2025-06-12
- 明确新增内容：新增了“add more unit tests of tools”相关测试覆盖与验证用例。
- 影响范围：主要涉及 其他模块。
- 改动规模：+1057 / -35 行。
- 关键文件：pyproject.toml；src/rag/**init**.py；src/tools/retriever.py；src/tools/search.py；src/tools/tavily_search/tavily_search_api_wrapper.py；src/tools/tavily_search/tavily_search_results_with_images.py；tests/integration/test_tts.py；tests/unit/tools/test_crawl.py。

#### 9. docs: add VolcEngine introduction. (#314)

- 提交：`[bb7dc6e](https://github.com/bytedance/deer-flow/commit/bb7dc6e98ce82311e48c02b514aeac35484e7816)`
- 日期：2025-06-12
- 明确新增内容：新增了“add VolcEngine introduction”相关文档说明，补齐使用/配置指引。
- 影响范围：主要涉及 文档。
- 改动规模：+7 / -0 行。
- 关键文件：README_zh.md。

#### 10. test: added unit tests for rag (#298)

- 提交：`[ee1af78](https://github.com/bytedance/deer-flow/commit/ee1af787675917f4130cd1826b4d61210e90c6b1)`
- 日期：2025-06-11
- 明确新增内容：新增了“added unit tests for rag”相关测试覆盖与验证用例。
- 影响范围：主要涉及 其他模块。
- 改动规模：+253 / -9 行。
- 关键文件：src/rag/ragflow.py；tests/unit/rag/test_ragflow.py；tests/unit/rag/test_retriever.py。

#### 11. test: add unit tests of llms (#299)

- 提交：`[2554e4b](https://github.com/bytedance/deer-flow/commit/2554e4ba639879e378f0ba94d37661eaad040d4e)`
- 日期：2025-06-11
- 明确新增内容：新增了“add unit tests of llms”相关测试覆盖与验证用例。
- 影响范围：主要涉及 其他模块。
- 改动规模：+70 / -6 行。
- 关键文件：src/llms/llm.py；tests/unit/llms/test_llm.py。

#### 12. feat: added report download button (#78)

- 提交：`[eeff1eb](https://github.com/bytedance/deer-flow/commit/eeff1ebf805822e71dc59079ebd49cc7b5917923)`
- 日期：2025-06-11
- 明确新增内容：新增了“report download button”功能。
- 影响范围：主要涉及 其他模块。
- 改动规模：+38 / -1 行。
- 关键文件：web/src/app/chat/components/research-block.tsx。

#### 13. feat: implement enhance prompt (#294)

- 提交：`[1cd6aa0](https://github.com/bytedance/deer-flow/commit/1cd6aa0ece7a55c9363ff088ac8acbb3a817dd70)`
- 日期：2025-06-08
- 明确新增内容：实现了“implement enhance prompt”这项新能力。
- 影响范围：主要涉及 其他模块。
- 改动规模：+1100 / -4 行。
- 关键文件：src/config/agents.py；src/prompt_enhancer/**init**.py；src/prompt_enhancer/graph/builder.py；src/prompt_enhancer/graph/enhancer_node.py；src/prompt_enhancer/graph/state.py；src/prompts/prompt_enhancer/prompt_enhancer.md；src/server/app.py；src/server/chat_request.py。

#### 14. test:unit tests for configuration (#291)

- 提交：`[8081a14](https://github.com/bytedance/deer-flow/commit/8081a14c215a4661e0cb5266c624126eb2f62a2e)`
- 日期：2025-06-07
- 明确新增内容：新增了“unit tests for configuration”相关测试覆盖与验证用例。
- 影响范围：主要涉及 其他模块。
- 改动规模：+182 / -1 行。
- 关键文件：src/config/loader.py；tests/test_state.py；tests/unit/config/test_configuration.py；tests/unit/config/test_loader.py。

#### 15. test: add unit tests of crawler (#292)

- 提交：`[c6ed423](https://github.com/bytedance/deer-flow/commit/c6ed423021cf3e27b1c5025f65bdd9becb7d9df6)`
- 日期：2025-06-07
- 明确新增内容：新增了“add unit tests of crawler”相关测试覆盖与验证用例。
- 影响范围：主要涉及 其他模块。
- 改动规模：+149 / -14 行。
- 关键文件：src/crawler/**init**.py；src/crawler/crawler.py；tests/unit/crawler/test_article.py；tests/unit/crawler/test_crawler_class.py。

#### 16. feat: support to adjust writing style (#290)

- 提交：`[0e22c37](https://github.com/bytedance/deer-flow/commit/0e22c373af42faa5c3121fac2f4378b7f3eee014)`
- 日期：2025-06-07
- 明确新增内容：新增了对“to adjust writing style”的支持能力。
- 影响范围：主要涉及 其他模块。
- 改动规模：+411 / -7 行。
- 关键文件：src/config/configuration.py；src/config/report_style.py；src/graph/nodes.py；src/prompts/reporter.md；src/server/app.py；src/server/chat_request.py；tests/integration/test_template.py；web/src/app/chat/components/input-box.tsx。

## 2025-07

- 提交数：13 条

#### 1. Feat: Add Wikipedia search engine (#478)

- 提交：`[bedf7d4](https://github.com/bytedance/deer-flow/commit/bedf7d4af2a19f32288387a9519cc91f9fdb0451)`
- 日期：2025-07-29
- 明确新增内容：新增了“Wikipedia search engine”功能。
- 影响范围：主要涉及 其他模块。
- 改动规模：+50 / -13 行。
- 关键文件：pyproject.toml；src/config/tools.py；src/tools/search.py；uv.lock。

#### 2. Feat: Cross-Language Search for RAGFlow (#469)

- 提交：`[f92bf0c](https://github.com/bytedance/deer-flow/commit/f92bf0ca223f51ecc6dccf31f2f4eeae94060af9)`
- 日期：2025-07-24
- 明确新增内容：引入了“Cross-Language Search for RAGFlow”相关功能改进。
- 影响范围：主要涉及 其他模块、文档。
- 改动规模：+20 / -0 行。
- 关键文件：.env.example；README.md；src/rag/ragflow.py；tests/unit/rag/test_ragflow.py。

#### 3. feat: polish the mcp-server configure feature (#447)

- 提交：`[d34f488](https://github.com/bytedance/deer-flow/commit/d34f48819d162fa246b18b8fc6b78e1bbd2b1b4f)`
- 日期：2025-07-19
- 明确新增内容：引入了“polish the mcp-server configure feature”相关功能改进。
- 影响范围：主要涉及 其他模块、文档。
- 改动规模：+94 / -4 行。
- 关键文件：.env.example；docs/mcp_integrations.md；src/server/app.py；tests/unit/server/test_app.py。

#### 4. feat: disable the MCP server configuation by default (#444)

- 提交：`[75ad3e0](https://github.com/bytedance/deer-flow/commit/75ad3e0dc61de2bc38b12a87586bc2643e4f60c2)`
- 日期：2025-07-19
- 明确新增内容：引入了“disable the MCP server configuation by default”相关功能改进。
- 影响范围：主要涉及 其他模块、文档。
- 改动规模：+70 / -1 行。
- 关键文件：.env.example；docs/mcp_integrations.md；src/server/app.py；tests/unit/server/test_app.py。

#### 5. feat: add CORS setting for the backend application (#443)

- 提交：`[933f3bb](https://github.com/bytedance/deer-flow/commit/933f3bb83a80ca51a2566d88fe51afb29f12df0c)`
- 日期：2025-07-18
- 明确新增内容：新增了“CORS setting for the backend application”功能。
- 影响范围：主要涉及 其他模块。
- 改动规模：+13 / -3 行。
- 关键文件：.env.example；src/server/app.py。

#### 6. feat: support AzureChatOpenAI under configuring azure_endpoint or AZURE_OPENAI_ENDPOINT (#237)

- 提交：`[0c46f83](https://github.com/bytedance/deer-flow/commit/0c46f8361b9b5bf830ace3169dfe7d5a341391ee)`
- 日期：2025-07-13
- 明确新增内容：新增了对“AzureChatOpenAI under configuring azure_endpoint or AZURE_OPENAI_ENDPOINT”的支持能力。
- 影响范围：主要涉及 文档、其他模块。
- 改动规模：+21 / -16 行。
- 关键文件：docs/configuration_guide.md；src/llms/llm.py。

#### 7. feat: add the Chinese i8n support on the setting table (#404)

- 提交：`[70b86d8](https://github.com/bytedance/deer-flow/commit/70b86d8464341e1416b71a82372fa5be1f8135b0)`
- 日期：2025-07-12
- 明确新增内容：新增了对“add the Chinese i8n support on the setting table”的支持能力。
- 影响范围：主要涉及 其他模块。
- 改动规模：+126 / -56 行。
- 关键文件：web/messages/en.json；web/messages/zh.json；web/src/app/settings/tabs/about-en.md；web/src/app/settings/tabs/about-tab.tsx；web/src/app/settings/tabs/about-zh.md；web/src/app/settings/tabs/about.md；web/src/app/settings/tabs/mcp-tab.tsx。

#### 8. feat: add i18n support and add Chinese (#372)

- 提交：`[e1187d7](https://github.com/bytedance/deer-flow/commit/e1187d7d02ceacf4db21c0ed7766d04b0c564190)`
- 日期：2025-07-12
- 明确新增内容：新增了对“add i18n support and add Chinese”的支持能力。
- 影响范围：主要涉及 其他模块、配置。
- 改动规模：+917 / -266 行。
- 关键文件：web/messages/en.json；web/messages/zh.json；web/next.config.js；web/package.json；web/pnpm-lock.yaml；web/src/app/chat/components/conversation-starter.tsx；web/src/app/chat/components/input-box.tsx；web/src/app/chat/components/message-list-view.tsx。

#### 9. feat: add the vscode unit test debug settings (#346)

- 提交：`[0d3255c](https://github.com/bytedance/deer-flow/commit/0d3255cdae88e5476e9f36d76e18872f08fc593f)`
- 日期：2025-07-12
- 明确新增内容：新增了“add the vscode unit test debug settings”相关测试覆盖与验证用例。
- 影响范围：主要涉及 其他模块。
- 改动规模：+37 / -0 行。
- 关键文件：.vscode/launch.json；.vscode/settings.json。

#### 10. feat(llm): Add retry mechanism for LLM API calls (#400)

- 提交：`[9f8f060](https://github.com/bytedance/deer-flow/commit/9f8f060506d90d0745494e4da9cd6a0a826d803f)`
- 日期：2025-07-12
- 明确新增内容：新增了“retry mechanism for LLM API calls”功能。
- 影响范围：主要涉及 其他模块。
- 改动规模：+7 / -0 行。
- 关键文件：conf.yaml.example；src/llms/llm.py。

#### 11. feat: add Domain Control Features for Tavily Search Engine (#401)

- 提交：`[dfd4712](https://github.com/bytedance/deer-flow/commit/dfd4712d9fda931a6b9583e151839154868cc829)`
- 日期：2025-07-12
- 明确新增内容：新增了“Domain Control Features for Tavily Search Engine”功能。
- 影响范围：主要涉及 其他模块、文档。
- 改动规模：+57 / -0 行。
- 关键文件：conf.yaml.example；docs/configuration_guide.md；src/tools/search.py。

#### 12. doc: add knowledgebase rag examples in readme (#383)

- 提交：`[859c6e3](https://github.com/bytedance/deer-flow/commit/859c6e3c5d7468702f0f54ed0bdb085c929a77d9)`
- 日期：2025-07-07
- 明确新增内容：新增了“doc: add knowledgebase rag examples in readme”相关文档说明，补齐使用/配置指引。
- 影响范围：主要涉及 文档。
- 改动规模：+47 / -9 行。
- 关键文件：README.md；README_zh.md。

#### 13. feat: integrate VikingDB Knowledge Base into rag retrieving tool (#381)

- 提交：`[be893ea](https://github.com/bytedance/deer-flow/commit/be893eae2bd144c2561433693eaed104fe3190c0)`
- 日期：2025-07-03
- 明确新增内容：引入了“integrate VikingDB Knowledge Base into rag retrieving tool”相关功能改进。
- 影响范围：主要涉及 其他模块。
- 改动规模：+814 / -3 行。
- 关键文件：.env.example；pyproject.toml；src/config/tools.py；src/rag/**init**.py；src/rag/builder.py；src/rag/vikingdb_knowledge_base.py；tests/unit/rag/test_vikingdb_knowledge_base.py；uv.lock。

## 2025-08

- 提交数：4 条

#### 1. feat: add lint check of front-end (#534)

- 提交：`[72f9c59](https://github.com/bytedance/deer-flow/commit/72f9c591953d2871f18bcc78e987c32885d9fe48)`
- 日期：2025-08-22
- 明确新增内容：新增了“lint check of front-end”功能。
- 影响范围：主要涉及 CI/CD、其他模块。
- 改动规模：+41 / -2 行。
- 关键文件：.github/workflows/lint.yaml；Makefile。

#### 2. feat: 1. replace black with ruff for fomatting and sort import (#489)

- 提交：`[3b4e993](https://github.com/bytedance/deer-flow/commit/3b4e993531feb5084f0e382ce4463eb5b8304cef)`
- 日期：2025-08-17
- 明确新增内容：引入了“1. replace black with ruff for fomatting and sort import”相关功能改进。
- 影响范围：主要涉及 其他模块。
- 改动规模：+246 / -229 行。
- 关键文件：Makefile；pyproject.toml；server.py；src/agents/agents.py；src/config/**init**.py；src/config/configuration.py；src/config/loader.py；src/config/tools.py。

#### 3. feat: Enhance chat streaming and tool call processing (#498)

- 提交：`[1bfec3a](https://github.com/bytedance/deer-flow/commit/1bfec3ad0556c3a5f54e1067a11379f5d8ce919c)`
- 日期：2025-08-16
- 明确新增内容：增强了“Enhance chat streaming and tool call processing”相关能力与交互体验。
- 影响范围：主要涉及 其他模块、CI/CD、文档。
- 改动规模：+1559 / -120 行。
- 关键文件：.env.example；.github/workflows/unittest.yaml；README.md；pyproject.toml；server.py；src/config/configuration.py；src/graph/checkpoint.py；src/server/app.py。

#### 4. feat: Add llms to support the latest Open Source SOTA models (#497)

- 提交：`[d65b8f8](https://github.com/bytedance/deer-flow/commit/d65b8f8fcc7efc5e8bd579a996df0181b3160a52)`
- 日期：2025-08-13
- 明确新增内容：新增了对“Add llms to support the latest Open Source SOTA models”的支持能力。
- 影响范围：主要涉及 其他模块、文档。
- 改动规模：+684 / -9 行。
- 关键文件：README.md；docs/configuration_guide.md；src/config/agents.py；src/llms/llm.py；src/llms/providers/dashscope.py；tests/unit/llms/test_dashscope.py。

## 2025-09

- 提交数：12 条

#### 1. feat: add context compress (#590)

- 提交：`[5f4eb38](https://github.com/bytedance/deer-flow/commit/5f4eb38fdbf5ede5b45aca08284f644194143bd7)`
- 日期：2025-09-27
- 明确新增内容：新增了“context compress”功能。
- 影响范围：主要涉及 其他模块、文档。
- 改动规模：+1032 / -7 行。
- 关键文件：docs/configuration_guide.md；src/agents/agents.py；src/graph/nodes.py；src/llms/llm.py；src/tools/search_postprocessor.py；src/tools/tavily_search/tavily_search_api_wrapper.py；src/utils/context_manager.py；tests/unit/tools/test_search_postprocessor.py。

#### 2. feat: add strategic_investment report style (#595)

- 提交：`[c214999](https://github.com/bytedance/deer-flow/commit/c214999606a38d8748ec30ceba4925dbb3693a56)`
- 日期：2025-09-24
- 明确新增内容：新增了“strategic_investment report style”功能。
- 影响范围：主要涉及 其他模块。
- 改动规模：+135 / -22 行。
- 关键文件：src/config/report_style.py；src/prompts/reporter.md；src/rag/**init**.py；src/rag/builder.py；src/rag/moi.py；src/server/app.py；src/tools/search.py；web/messages/en.json。

#### 3. feat: add support for searx/searxng  (#253)

- 提交：`[1c27e0f](https://github.com/bytedance/deer-flow/commit/1c27e0f2aedf49e1b2e4623796df8319eace5416)`
- 日期：2025-09-22
- 明确新增内容：新增了对“searx/searxng”的支持能力。
- 影响范围：主要涉及 文档、其他模块。
- 改动规模：+41 / -1 行。
- 关键文件：.env.example；README.md；README_de.md；README_es.md；README_ja.md；README_pt.md；README_ru.md；README_zh.md。

#### 4. feat:support config tavily search results (#591)

- 提交：`[6bb0b95](https://github.com/bytedance/deer-flow/commit/6bb0b9557917565aa15110924b54b6a55998cbed)`
- 日期：2025-09-22
- 明确新增内容：新增了对“config tavily search results”的支持能力。
- 影响范围：主要涉及 文档、其他模块。
- 改动规模：+15 / -4 行。
- 关键文件：docs/configuration_guide.md；src/tools/search.py。

#### 5. feat: support dify in rag module (#550)

- 提交：`[7694bb5](https://github.com/bytedance/deer-flow/commit/7694bb5d724edea27e0bd3c5beabb9e6f4777815)`
- 日期：2025-09-16
- 明确新增内容：新增了对“dify in rag module”的支持能力。
- 影响范围：主要涉及 其他模块。
- 改动规模：+407 / -87 行。
- 关键文件：.env.example；server.py；src/config/configuration.py；src/config/tools.py；src/graph/checkpoint.py；src/llms/llm.py；src/llms/providers/dashscope.py；src/rag/**init**.py。

#### 6. feat: support for moi in RAG module (#571)

- 提交：`[5085bf8](https://github.com/bytedance/deer-flow/commit/5085bf8ee9f98e658dbf8a06db9af15d2625088f)`
- 日期：2025-09-16
- 明确新增内容：新增了对“for moi in RAG module”的支持能力。
- 影响范围：主要涉及 其他模块、文档。
- 改动规模：+176 / -0 行。
- 关键文件：.env.example；README_zh.md；src/config/tools.py；src/rag/**init**.py；src/rag/builder.py；src/rag/moi.py。

#### 7. feat: add Google AI Studio API support with platform-based detection (#502)

- 提交：`[bbc49a0](https://github.com/bytedance/deer-flow/commit/bbc49a04a6cc1746f58f75bccda032ed5baeddf6)`
- 日期：2025-09-13
- 明确新增内容：新增了对“add Google AI Studio API support with platform-based detection”的支持能力。
- 影响范围：主要涉及 其他模块、文档。
- 改动规模：+215 / -3 行。
- 关键文件：conf.yaml.example；docs/configuration_guide.md；pyproject.toml；src/llms/llm.py；uv.lock。

#### 8. feat: Implement Milvus retriver for RAG (#516)

- 提交：`[dd9af1e](https://github.com/bytedance/deer-flow/commit/dd9af1eb502bf00e2be8a1cc1d8c828c173a7c8d)`
- 日期：2025-09-12
- 明确新增内容：实现了“Implement Milvus retriver for RAG”这项新能力。
- 影响范围：主要涉及 其他模块、文档。
- 改动规模：+1875 / -43 行。
- 关键文件：.env.example；docs/configuration_guide.md；pyproject.toml；src/config/configuration.py；src/config/loader.py；src/config/tools.py；src/graph/checkpoint.py；src/rag/builder.py。

#### 9. refactor(logging): add explicit error log message (#576)

- 提交：`[eec8e4d](https://github.com/bytedance/deer-flow/commit/eec8e4dd606520525f233edb31e2ddbbc43309d2)`
- 日期：2025-09-12
- 明确新增内容：新增了“explicit error log message”功能。
- 影响范围：主要涉及 其他模块。
- 改动规模：+2 / -0 行。
- 关键文件：src/tools/tavily_search/tavily_search_results_with_images.py。

#### 10. docs: add deployment note for Linux servers (#565)

- 提交：`[0057126](https://github.com/bytedance/deer-flow/commit/005712679c542e370b270e1f0f85c4c4eb765b2c)`
- 日期：2025-09-09
- 明确新增内容：新增了“add deployment note for Linux servers”相关文档说明，补齐使用/配置指引。
- 影响范围：主要涉及 文档。
- 改动规模：+6 / -0 行。
- 关键文件：README.md；README_zh.md。

#### 11. feat: creating mogodb and postgres mock instance in checkpoint test (#561)

- 提交：`[4c17d88](https://github.com/bytedance/deer-flow/commit/4c17d880299264bdb6cc0610195dfe2e537ace0d)`
- 日期：2025-09-09
- 明确新增内容：新增了“creating mogodb and postgres mock instance in checkpoint test”相关测试覆盖与验证用例。
- 影响范围：主要涉及 其他模块、CI/CD。
- 改动规模：+470 / -158 行。
- 关键文件：.github/workflows/unittest.yaml；pyproject.toml；src/graph/checkpoint.py；tests/unit/checkpoint/postgres_mock_utils.py；tests/unit/checkpoint/test_checkpoint.py；uv.lock。

#### 12. Add psycopg dependencies instruction for checkpointing (#564)

- 提交：`[7138ba3](https://github.com/bytedance/deer-flow/commit/7138ba36bced4f7c3a5ee70068072ce6e1226bd5)`
- 日期：2025-09-09
- 明确新增内容：新增了“psycopg dependencies instruction for checkpointing”功能。
- 影响范围：主要涉及 其他模块、文档。
- 改动规模：+19 / -1 行。
- 关键文件：Dockerfile；README.md。

## 2025-10

- 提交数：12 条

#### 1. security: add log injection attack prevention with input sanitization  (#667)

- 提交：`[b4c09aa](https://github.com/bytedance/deer-flow/commit/b4c09aa4b1cc0f0edb8b20d876daf38877c6d36c)`
- 日期：2025-10-27
- 明确新增内容：新增了“security: add log injection attack prevention with input sanitization”功能。
- 影响范围：主要涉及 其他模块。
- 改动规模：+585 / -80 行。
- 关键文件：src/agents/agents.py；src/agents/tool_interceptor.py；src/crawler/readability_extractor.py；src/server/app.py；src/utils/log_sanitizer.py；tests/integration/test_tool_interceptor_integration.py；tests/unit/agents/test_tool_interceptor.py；tests/unit/crawler/test_jina_client.py。

#### 2. feat: add comprehensive debug logging for issue #477 hanging/freezing diagnosis (#662)

- 提交：`[83f1334](https://github.com/bytedance/deer-flow/commit/83f1334db08876b7b0d112dbe8f8334d0579babd)`
- 日期：2025-10-27
- 明确新增内容：新增了“comprehensive debug logging for issue #477 hanging/freezing diagnosis”功能。
- 影响范围：主要涉及 其他模块。
- 改动规模：+172 / -28 行。
- 关键文件：server.py；src/agents/agents.py；src/agents/tool_interceptor.py；src/graph/nodes.py；src/server/app.py；tests/integration/test_nodes.py。

#### 3. docs: add tool-specific interrupts configuration to conf.yaml.example (#661)

- 提交：`[e9f0a02](https://github.com/bytedance/deer-flow/commit/e9f0a02f1fa4e1abfb00ed625596be3161f1fe41)`
- 日期：2025-10-27
- 明确新增内容：新增了“add tool-specific interrupts configuration to conf.yaml.example”相关文档说明，补齐使用/配置指引。
- 影响范围：主要涉及 其他模块。
- 改动规模：+17 / -0 行。
- 关键文件：conf.yaml.example。

#### 4. feat: implement tool-specific interrupts for create_react_agent (#572) (#659)

- 提交：`[bcc403e](https://github.com/bytedance/deer-flow/commit/bcc403ecd3d9d9aae082005fc09cafaa80ba6a3c)`
- 日期：2025-10-26
- 明确新增内容：实现了“implement tool-specific interrupts for create_react_agent (#572)”这项新能力。
- 影响范围：主要涉及 其他模块。
- 改动规模：+1163 / -5 行。
- 关键文件：src/agents/agents.py；src/agents/tool_interceptor.py；src/config/configuration.py；src/graph/nodes.py；src/server/app.py；src/server/chat_request.py；tests/integration/test_tool_interceptor_integration.py；tests/unit/agents/test_tool_interceptor.py。

#### 5. feat: Add comprehensive Chinese localization support for issue #412 (#649)

- 提交：`[5eada04](https://github.com/bytedance/deer-flow/commit/5eada04f50a5c16d9ed7cae79485077c36bbce38)`
- 日期：2025-10-24
- 明确新增内容：新增了对“Add comprehensive Chinese localization support for issue #412”的支持能力。
- 影响范围：主要涉及 其他模块。
- 改动规模：+1165 / -15 行。
- 关键文件：src/agents/agents.py；src/graph/nodes.py；src/prompt_enhancer/graph/enhancer_node.py；src/prompts/coder.zh_CN.md；src/prompts/coordinator.zh_CN.md；src/prompts/planner.zh_CN.md；src/prompts/podcast/podcast_script_writer.zh_CN.md；src/prompts/ppt/ppt_composer.zh_CN.md。

#### 6. docs: provide comprehensive API documentation for the backend server (#646)

- 提交：`[c15c480](https://github.com/bytedance/deer-flow/commit/c15c480fe6c747b5324c250554683fad5a936ef4)`
- 日期：2025-10-23
- 明确新增内容：新增了“provide comprehensive API documentation for the backend server”相关文档说明，补齐使用/配置指引。
- 影响范围：主要涉及 文档。
- 改动规模：+1292 / -0 行。
- 关键文件：docs/API.md；docs/openapi.json。

#### 7. Add frontend tests step to frontend lint workflow

- 提交：`[d9f829b](https://github.com/bytedance/deer-flow/commit/d9f829b6086a4532fd68ce474e86023b9df85750)`
- 日期：2025-10-16
- 明确新增内容：新增了“frontend tests step to frontend lint workflow”功能。
- 影响范围：主要涉及 CI/CD。
- 改动规模：+6 / -1 行。
- 关键文件：.github/workflows/lint.yaml。

#### 8. chore: add frontend unit tests to lint-frontend make target

- 提交：`[9b127c5](https://github.com/bytedance/deer-flow/commit/9b127c55f256ce318971a5183650eaa1968104a7)`
- 日期：2025-10-15
- 明确新增内容：新增了“add frontend unit tests to lint-frontend make target”相关测试覆盖与验证用例。
- 影响范围：主要涉及 其他模块。
- 改动规模：+2 / -1 行。
- 关键文件：Makefile。

#### 9. feat: Add intelligent clarification feature in coordinate step for research queries (#613)

- 提交：`[2510cc6](https://github.com/bytedance/deer-flow/commit/2510cc61de76a68d0d98d4b4f5b4490b77fc6a0c)`
- 日期：2025-10-13
- 明确新增内容：新增了“intelligent clarification feature in coordinate step for research queries”功能。
- 影响范围：主要涉及 其他模块、文档。
- 改动规模：+828 / -55 行。
- 关键文件：README.md；README_zh.md；docs/configuration_guide.md；main.py；src/graph/builder.py；src/graph/nodes.py；src/graph/types.py；src/prompts/coordinator.md。

#### 10. feature: clean up the temp file which are generated when running the unit test of milvus (#612)

- 提交：`[81c91dd](https://github.com/bytedance/deer-flow/commit/81c91dda43accb7f10471873ea06a3d50b5566c7)`
- 日期：2025-10-12
- 明确新增内容：新增了“feature: clean up the temp file which are generated when running the unit test of milvus”相关测试覆盖与验证用例。
- 影响范围：主要涉及 其他模块。
- 改动规模：+128 / -28 行。
- 关键文件：tests/unit/rag/test_milvus.py。

#### 11. feature: add formula rander in the markdown (#611)

- 提交：`[2a6455c](https://github.com/bytedance/deer-flow/commit/2a6455c43631d00f9d62174bf61b720d30e9bccc)`
- 日期：2025-10-11
- 明确新增内容：新增了“feature: add formula rander in the markdown”功能。
- 影响范围：主要涉及 其他模块。
- 改动规模：+79 / -3 行。
- 关键文件：web/src/components/deer-flow/markdown.tsx；web/src/core/markdown/katex.ts；web/tests/markdown-katex.test.ts。

#### 12. feature:Add the debug setting on vscode (#606)

- 提交：`[79b9cdb](https://github.com/bytedance/deer-flow/commit/79b9cdb59ab50e31402177f82a184961eff0d8ec)`
- 日期：2025-10-05
- 明确新增内容：新增了“feature:Add the debug setting on vscode”功能。
- 影响范围：主要涉及 其他模块。
- 改动规模：+15 / -1 行。
- 关键文件：.vscode/launch.json。

## 2025-11

- 提交数：8 条

#### 1. feat: add analysis step type for non-code reasoning tasks (#677) (#723)

- 提交：`[2e010a4](https://github.com/bytedance/deer-flow/commit/2e010a46196308e9163cd09b7ce3f1380a1520c2)`
- 日期：2025-11-29
- 明确新增内容：新增了“analysis step type for non-code reasoning tasks (#677)”功能。
- 影响范围：主要涉及 其他模块。
- 改动规模：+266 / -69 行。
- 关键文件：src/config/agents.py；src/graph/builder.py；src/graph/nodes.py；src/prompts/analyst.md；src/prompts/analyst.zh_CN.md；src/prompts/planner.md；src/prompts/planner.zh_CN.md；src/prompts/planner_model.py。

#### 2. Add unit tests for PPT composer locale handling (#696)

- 提交：`[cc9414f](https://github.com/bytedance/deer-flow/commit/cc9414f9782db7f8f3cd7bc74fa72aea67bf11de)`
- 日期：2025-11-22
- 明确新增内容：新增了“Add unit tests for PPT composer locale handling”相关测试覆盖与验证用例。
- 影响范围：主要涉及 其他模块。
- 改动规模：+138 / -0 行。
- 关键文件：.gitignore；tests/test_ppt_localization.py。

#### 3. feat: enable ppt_composer.zh_CN.md with request.locale (#694)

- 提交：`[1bfcf9f](https://github.com/bytedance/deer-flow/commit/1bfcf9f4299a15d65cbc37b0d5dd8556f07352cf)`
- 日期：2025-11-22
- 明确新增内容：引入了“enable ppt_composer.zh_CN.md with request.locale”相关功能改进。
- 影响范围：主要涉及 其他模块。
- 改动规模：+6 / -3 行。
- 关键文件：src/ppt/graph/ppt_composer_node.py；src/ppt/graph/state.py；src/server/app.py；src/server/chat_request.py。

#### 4. feat: be compatible with case: `json_object` is not supported by used model (#673)

- 提交：`[2d1a099](https://github.com/bytedance/deer-flow/commit/2d1a0997eba627301f6bdce5823ff2d675759dfa)`
- 日期：2025-11-21
- 明确新增内容：引入了“be compatible with case: `json_object` is not supported by used model”相关功能改进。
- 影响范围：主要涉及 其他模块。
- 改动规模：+19 / -5 行。
- 关键文件：src/graph/nodes.py。

#### 5. Add GitHub Copilot instructions for repository context (#698)

- 提交：`[b7a4b0f](https://github.com/bytedance/deer-flow/commit/b7a4b0f44610150e1f535dc70e3f57d0d5f56fcd)`
- 日期：2025-11-17
- 明确新增内容：新增了“GitHub Copilot instructions for repository context”功能。
- 影响范围：主要涉及 CI/CD。
- 改动规模：+303 / -0 行。
- 关键文件：.github/copilot-instructions.md。

#### 6. feat: Qdrant Vector Search Support (#684)

- 提交：`[aa027fa](https://github.com/bytedance/deer-flow/commit/aa027faf95d11690db4f3acea5f109c8ffd69543)`
- 日期：2025-11-11
- 明确新增内容：新增了对“Qdrant Vector Search Support”的支持能力。
- 影响范围：主要涉及 其他模块、文档。
- 改动规模：+1010 / -30 行。
- 关键文件：.env.example；README.md；docs/configuration_guide.md；pyproject.toml；src/config/tools.py；src/rag/**init**.py；src/rag/builder.py；src/rag/milvus.py。

#### 7. docs: add comprehensive debugging guide and improve troubleshooting documentation (#688)

- 提交：`[70dbd21](https://github.com/bytedance/deer-flow/commit/70dbd21bdf13cda071e5d2b0de9fd0fe6f38bfbd)`
- 日期：2025-11-10
- 明确新增内容：新增了“add comprehensive debugging guide and improve troubleshooting documentation”相关文档说明，补齐使用/配置指引。
- 影响范围：主要涉及 文档、其他模块。
- 改动规模：+408 / -2 行。
- 关键文件：.env.example；docs/DEBUGGING.md；docs/FAQ.md。

#### 8. feat: add edit and refresh functionality for MCP servers in settings tab (#680)

- 提交：`[a38c858](https://github.com/bytedance/deer-flow/commit/a38c8584d78e4cfabd7a408860a7e7cea4630a11)`
- 日期：2025-11-06
- 明确新增内容：新增了“edit and refresh functionality for MCP servers in settings tab”功能。
- 影响范围：主要涉及 其他模块。
- 改动规模：+351 / -12 行。
- 关键文件：web/messages/en.json；web/messages/zh.json；web/src/app/settings/dialogs/edit-mcp-server-dialog.tsx；web/src/app/settings/tabs/mcp-tab.tsx。

## 2025-12

- 提交数：12 条

#### 1. feat(eval): add report quality evaluation module and UI integration  (#776)

- 提交：`[8d9d767](https://github.com/bytedance/deer-flow/commit/8d9d7670518b4eadbac86de16bd5c08a40dae42a)`
- 日期：2025-12-25
- 明确新增内容：新增了“report quality evaluation module and UI integration”功能。
- 影响范围：主要涉及 其他模块。
- 改动规模：+2103 / -2 行。
- 关键文件：src/eval/**init**.py；src/eval/evaluator.py；src/eval/llm_judge.py；src/eval/metrics.py；src/server/app.py；src/server/eval_request.py；tests/unit/eval/**init**.py；tests/unit/eval/test_evaluator.py。

#### 2. test: add unit tests for global connection pool (Issue #778) (#780)

- 提交：`[fb319aa](https://github.com/bytedance/deer-flow/commit/fb319aaa44b212e3d43f691c943b9e0ed33e1162)`
- 日期：2025-12-23
- 明确新增内容：新增了“add unit tests for global connection pool (Issue #778)”相关测试覆盖与验证用例。
- 影响范围：主要涉及 其他模块。
- 改动规模：+472 / -1 行。
- 关键文件：src/server/app.py；tests/unit/server/test_app.py。

#### 3. feat:Database connections use connection pools (#757)

- 提交：`[83e9d7c](https://github.com/bytedance/deer-flow/commit/83e9d7c9e58fd38e64a00f71e88c098f7c7d32b2)`
- 日期：2025-12-23
- 明确新增内容：引入了“Database connections use connection pools”相关功能改进。
- 影响范围：主要涉及 其他模块。
- 改动规模：+163 / -17 行。
- 关键文件：src/server/app.py。

#### 4. feat: add resource upload support for RAG (#768)

- 提交：`[04296cd](https://github.com/bytedance/deer-flow/commit/04296cdf5a320a2e4a736e7c021eaf9f0b6dafe9)`
- 日期：2025-12-19
- 明确新增内容：新增了对“add resource upload support for RAG”的支持能力。
- 影响范围：主要涉及 其他模块。
- 改动规模：+567 / -2 行。
- 关键文件：src/rag/milvus.py；src/rag/retriever.py；src/server/app.py；tests/unit/server/test_app.py；web/messages/en.json；web/messages/zh.json；web/src/app/settings/tabs/index.tsx；web/src/app/settings/tabs/rag-tab.tsx。

#### 5. feat(web): add enable_web_search frontend UI (#681) (#766)

- 提交：`[3e8f2ce](https://github.com/bytedance/deer-flow/commit/3e8f2ce3ada0116598e95bcd6e093e1f22e9a775)`
- 日期：2025-12-17
- 明确新增内容：新增了“enable_web_search frontend UI (#681)”功能。
- 影响范围：主要涉及 其他模块。
- 改动规模：+44 / -2 行。
- 关键文件：web/messages/en.json；web/messages/zh.json；web/src/app/settings/tabs/general-tab.tsx；web/src/core/api/chat.ts；web/src/core/store/settings-store.ts；web/src/core/store/store.ts。

#### 6. feat(web): add multi-format report export (Markdown, HTML, PDF, Word,… (#756)

- 提交：`[a4f64ab](https://github.com/bytedance/deer-flow/commit/a4f64abd1f442835caedeee93bb591b0ae3dd0c4)`
- 日期：2025-12-16
- 明确新增内容：新增了“multi-format report export (Markdown, HTML, PDF, Word,…”功能。
- 影响范围：主要涉及 其他模块、配置。
- 改动规模：+1079 / -109 行。
- 关键文件：web/messages/en.json；web/messages/zh.json；web/package.json；web/pnpm-lock.yaml；web/src/app/chat/components/research-block.tsx。

#### 7. feat: add Serper search engine support (#762)

- 提交：`[2a97170](https://github.com/bytedance/deer-flow/commit/2a97170b6c6743290780cc77eb2f07781c4da28e)`
- 日期：2025-12-15
- 明确新增内容：新增了对“add Serper search engine support”的支持能力。
- 影响范围：主要涉及 其他模块、文档。
- 改动规模：+47 / -1 行。
- 关键文件：.env.example；docs/configuration_guide.md；src/config/tools.py；src/tools/search.py；tests/unit/tools/test_search.py。

#### 8. feat: add enable_web_search config to disable web search (#681) (#760)

- 提交：`[93d81d4](https://github.com/bytedance/deer-flow/commit/93d81d450dd8dbb95d9aabc63055bdb666914cea)`
- 日期：2025-12-15
- 明确新增内容：新增了“enable_web_search config to disable web search (#681)”功能。
- 影响范围：主要涉及 其他模块、文档。
- 改动规模：+89 / -7 行。
- 关键文件：conf.yaml.example；docs/configuration_guide.md；src/config/configuration.py；src/graph/nodes.py；src/server/app.py；src/server/chat_request.py；tests/unit/server/test_app.py。

#### 9. docs: add more MCP integration examples (#441) (#754)

- 提交：`[4c2592a](https://github.com/bytedance/deer-flow/commit/4c2592ac85d8af7c8eb8c47de6c7208a27254620)`
- 日期：2025-12-11
- 明确新增内容：新增了“add more MCP integration examples (#441)”相关文档说明，补齐使用/配置指引。
- 影响范围：主要涉及 文档。
- 改动规模：+161 / -20 行。
- 关键文件：docs/mcp_integrations.md。

#### 10. Add the InfoQuest banner to the README (#748)

- 提交：`[fde7a69](https://github.com/bytedance/deer-flow/commit/fde7a6956226a010c1c6be6a370b57669555dca2)`
- 日期：2025-12-08
- 明确新增内容：新增了“Add the InfoQuest banner to the README”相关文档说明，补齐使用/配置指引。
- 影响范围：主要涉及 文档。
- 改动规模：+51 / -9 行。
- 关键文件：README.md；README_de.md；README_es.md；README_ja.md；README_pt.md；README_ru.md；README_zh.md。

#### 11. feat:Strip code blocks in plan data. (#738)

- 提交：`[bd6c50d](https://github.com/bytedance/deer-flow/commit/bd6c50de330309e1c10df7f681db53a3d566a4cc)`
- 日期：2025-12-04
- 明确新增内容：引入了“Strip code blocks in plan data”相关功能改进。
- 影响范围：主要涉及 其他模块。
- 改动规模：+2 / -2 行。
- 关键文件：src/graph/nodes.py。

#### 12. feat: support infoquest (#708)

- 提交：`[7ec9e45](https://github.com/bytedance/deer-flow/commit/7ec9e4570220a0d3c0517bd1e7619bda723025bf)`
- 日期：2025-12-02
- 明确新增内容：新增了对“infoquest”的支持能力。
- 影响范围：主要涉及 其他模块、文档。
- 改动规模：+2103 / -94 行。
- 关键文件：.env.example；README.md；README_de.md；README_es.md；README_ja.md；README_pt.md；README_ru.md；README_zh.md。

## 2026-01

- 提交数：370 条

#### 1. docs: rephrasing

- 提交：`[ca83ed0](https://github.com/bytedance/deer-flow/commit/ca83ed00f8829f1ba881a2ab45bd2cb65535b130)`
- 日期：2026-01-31
- 明确新增内容：新增了“rephrasing”相关文档说明，补齐使用/配置指引。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -1 行。
- 关键文件：frontend/src/core/i18n/locales/en-US.ts。

#### 2. docs: rephrasing

- 提交：`[f3d7fea](https://github.com/bytedance/deer-flow/commit/f3d7fea9cec5b3976e52b73601972efd35a37bda)`
- 日期：2026-01-31
- 明确新增内容：新增了“rephrasing”相关文档说明，补齐使用/配置指引。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -1 行。
- 关键文件：frontend/src/core/i18n/locales/en-US.ts。

#### 3. docs: rephrasing

- 提交：`[7d3e7eb](https://github.com/bytedance/deer-flow/commit/7d3e7eb1c9502d008576a479134111f64f87590b)`
- 日期：2026-01-31
- 明确新增内容：新增了“rephrasing”相关文档说明，补齐使用/配置指引。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -1 行。
- 关键文件：frontend/src/core/i18n/locales/en-US.ts。

#### 4. feat: implement create skill

- 提交：`[bdd2e25](https://github.com/bytedance/deer-flow/commit/bdd2e25e1489f874ed153d715a0deb69250c8955)`
- 日期：2026-01-31
- 明确新增内容：实现了“implement create skill”这项新能力。
- 影响范围：主要涉及 前端。
- 改动规模：+49 / -7 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/workspace/input-box.tsx；frontend/src/components/workspace/settings/settings-dialog.tsx；frontend/src/components/workspace/settings/skill-settings-page.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts；frontend/src/core/i18n/locales/zh-CN.ts。

#### 5. feat: implement create skill

- 提交：`[8639dde](https://github.com/bytedance/deer-flow/commit/8639dde3adfdbfd992e8b1d9fced98b7f104e48e)`
- 日期：2026-01-31
- 明确新增内容：实现了“implement create skill”这项新能力。
- 影响范围：主要涉及 前端。
- 改动规模：+49 / -7 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/workspace/input-box.tsx；frontend/src/components/workspace/settings/settings-dialog.tsx；frontend/src/components/workspace/settings/skill-settings-page.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts；frontend/src/core/i18n/locales/zh-CN.ts。

#### 6. feat: implement create skill

- 提交：`[67ec116](https://github.com/bytedance/deer-flow/commit/67ec1162cb7a45667dc392cdcd794f499ed0a2a0)`
- 日期：2026-01-31
- 明确新增内容：实现了“implement create skill”这项新能力。
- 影响范围：主要涉及 前端。
- 改动规模：+49 / -7 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/workspace/input-box.tsx；frontend/src/components/workspace/settings/settings-dialog.tsx；frontend/src/components/workspace/settings/skill-settings-page.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts；frontend/src/core/i18n/locales/zh-CN.ts。

#### 7. feat: add .skill file preview support

- 提交：`[06511f3](https://github.com/bytedance/deer-flow/commit/06511f38e1c208faf0aafd6b3a2e0734d31bb169)`
- 日期：2026-01-31
- 明确新增内容：新增了对“add .skill file preview support”的支持能力。
- 影响范围：主要涉及 前端、后端。
- 改动规模：+79 / -2 行。
- 关键文件：backend/src/gateway/routers/artifacts.py；frontend/src/components/workspace/artifacts/artifact-file-detail.tsx；frontend/src/core/artifacts/hooks.ts；frontend/src/core/artifacts/loader.ts。

#### 8. feat: add .skill file preview support

- 提交：`[f31258d](https://github.com/bytedance/deer-flow/commit/f31258dd1011d8e25513654c1f0f2c1ef54d18f6)`
- 日期：2026-01-31
- 明确新增内容：新增了对“add .skill file preview support”的支持能力。
- 影响范围：主要涉及 前端、后端。
- 改动规模：+79 / -2 行。
- 关键文件：backend/src/gateway/routers/artifacts.py；frontend/src/components/workspace/artifacts/artifact-file-detail.tsx；frontend/src/core/artifacts/hooks.ts；frontend/src/core/artifacts/loader.ts。

#### 9. feat: add .skill file preview support

- 提交：`[41f8b93](https://github.com/bytedance/deer-flow/commit/41f8b931c94ad0b6428c99a364b0711825414625)`
- 日期：2026-01-31
- 明确新增内容：新增了对“add .skill file preview support”的支持能力。
- 影响范围：主要涉及 前端、后端。
- 改动规模：+79 / -2 行。
- 关键文件：backend/src/gateway/routers/artifacts.py；frontend/src/components/workspace/artifacts/artifact-file-detail.tsx；frontend/src/core/artifacts/hooks.ts；frontend/src/core/artifacts/loader.ts。

#### 10. feat: add skill installation API endpoint

- 提交：`[a9e11f6](https://github.com/bytedance/deer-flow/commit/a9e11f63416b3158110fb15f0ae5db47653cc9d1)`
- 日期：2026-01-31
- 明确新增内容：新增了“skill installation API endpoint”功能。
- 影响范围：主要涉及 前端、后端。
- 改动规模：+370 / -28 行。
- 关键文件：backend/src/gateway/routers/skills.py；frontend/src/components/workspace/artifacts/artifact-file-detail.tsx；frontend/src/components/workspace/artifacts/artifact-file-list.tsx；frontend/src/core/skills/api.ts。

#### 11. feat: add skill installation API endpoint

- 提交：`[624f758](https://github.com/bytedance/deer-flow/commit/624f758163b40f251172474482b5d122b3a2452e)`
- 日期：2026-01-31
- 明确新增内容：新增了“skill installation API endpoint”功能。
- 影响范围：主要涉及 前端、后端。
- 改动规模：+370 / -28 行。
- 关键文件：backend/src/gateway/routers/skills.py；frontend/src/components/workspace/artifacts/artifact-file-detail.tsx；frontend/src/components/workspace/artifacts/artifact-file-list.tsx；frontend/src/core/skills/api.ts。

#### 12. feat: add skill installation API endpoint

- 提交：`[5834b15](https://github.com/bytedance/deer-flow/commit/5834b15af729d0b0318c5d59bdbf45934aebe31e)`
- 日期：2026-01-31
- 明确新增内容：新增了“skill installation API endpoint”功能。
- 影响范围：主要涉及 前端、后端。
- 改动规模：+370 / -28 行。
- 关键文件：backend/src/gateway/routers/skills.py；frontend/src/components/workspace/artifacts/artifact-file-detail.tsx；frontend/src/components/workspace/artifacts/artifact-file-list.tsx；frontend/src/core/skills/api.ts。

#### 13. feat: preview the message if possible

- 提交：`[cf96132](https://github.com/bytedance/deer-flow/commit/cf961328a9a187416362d94e5b0e9e9759630c7b)`
- 日期：2026-01-31
- 明确新增内容：引入了“preview the message if possible”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+18 / -2 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx。

#### 14. feat: preview the message if possible

- 提交：`[20a023e](https://github.com/bytedance/deer-flow/commit/20a023ee90ffbfbe5ed47ee3174b77989c2a25c8)`
- 日期：2026-01-31
- 明确新增内容：引入了“preview the message if possible”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+18 / -2 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx。

#### 15. feat: preview the message if possible

- 提交：`[9c3b928](https://github.com/bytedance/deer-flow/commit/9c3b928f1de166a9404c2b958783d7445881e933)`
- 日期：2026-01-31
- 明确新增内容：引入了“preview the message if possible”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+18 / -2 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx。

#### 16. feat: add notification

- 提交：`[5295f5b](https://github.com/bytedance/deer-flow/commit/5295f5b5b9296cdad66fd287f68ae98e29a9fb83)`
- 日期：2026-01-31
- 明确新增内容：新增了“notification”功能。
- 影响范围：主要涉及 前端。
- 改动规模：+482 / -56 行。
- 关键文件：frontend/package.json；frontend/pnpm-lock.yaml；frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/ui/tabs.tsx；frontend/src/components/workspace/artifacts/artifact-file-detail.tsx；frontend/src/components/workspace/artifacts/artifact-file-list.tsx；frontend/src/components/workspace/settings/notification-settings-page.tsx；frontend/src/components/workspace/settings/settings-dialog.tsx。

#### 17. feat: add notification

- 提交：`[47fe2f8](https://github.com/bytedance/deer-flow/commit/47fe2f8195a0d1fc52d88bf304864edb2313fff4)`
- 日期：2026-01-31
- 明确新增内容：新增了“notification”功能。
- 影响范围：主要涉及 前端。
- 改动规模：+482 / -56 行。
- 关键文件：frontend/package.json；frontend/pnpm-lock.yaml；frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/ui/tabs.tsx；frontend/src/components/workspace/artifacts/artifact-file-detail.tsx；frontend/src/components/workspace/artifacts/artifact-file-list.tsx；frontend/src/components/workspace/settings/notification-settings-page.tsx；frontend/src/components/workspace/settings/settings-dialog.tsx。

#### 18. feat: add notification

- 提交：`[c62caf9](https://github.com/bytedance/deer-flow/commit/c62caf95c4f7c5a492dd1a4351d574cc1d2f835a)`
- 日期：2026-01-31
- 明确新增内容：新增了“notification”功能。
- 影响范围：主要涉及 前端。
- 改动规模：+482 / -56 行。
- 关键文件：frontend/package.json；frontend/pnpm-lock.yaml；frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/ui/tabs.tsx；frontend/src/components/workspace/artifacts/artifact-file-detail.tsx；frontend/src/components/workspace/artifacts/artifact-file-list.tsx；frontend/src/components/workspace/settings/notification-settings-page.tsx；frontend/src/components/workspace/settings/settings-dialog.tsx。

#### 19. feat: change email

- 提交：`[835fd4d](https://github.com/bytedance/deer-flow/commit/835fd4d0c78deae8587839496ea2fb14577ae153)`
- 日期：2026-01-30
- 明确新增内容：引入了“change email”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -1 行。
- 关键文件：frontend/src/components/workspace/workspace-nav-menu.tsx。

#### 20. feat: change email

- 提交：`[cb660c2](https://github.com/bytedance/deer-flow/commit/cb660c264306b7cb2880a14f3c6a77aec8b0b7ba)`
- 日期：2026-01-30
- 明确新增内容：引入了“change email”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -1 行。
- 关键文件：frontend/src/components/workspace/workspace-nav-menu.tsx。

#### 21. feat: change email

- 提交：`[4e0571f](https://github.com/bytedance/deer-flow/commit/4e0571f3b3b0eb48f84a2b583ac3ebb43130a402)`
- 日期：2026-01-30
- 明确新增内容：引入了“change email”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -1 行。
- 关键文件：frontend/src/components/workspace/workspace-nav-menu.tsx。

#### 22. feat: support Github Flavored Markdown

- 提交：`[c1182c6](https://github.com/bytedance/deer-flow/commit/c1182c680cab9a2ee5e4c62cf53cc6c5103b7b73)`
- 日期：2026-01-30
- 明确新增内容：新增了对“Github Flavored Markdown”的支持能力。
- 影响范围：主要涉及 前端。
- 改动规模：+108 / -30 行。
- 关键文件：frontend/package.json；frontend/pnpm-lock.yaml；frontend/src/components/workspace/artifacts/artifact-file-detail.tsx；frontend/src/components/workspace/messages/message-list-item.tsx；frontend/src/core/streamdown/index.ts；frontend/src/core/streamdown/plugins.ts。

#### 23. feat: support Github Flavored Markdown

- 提交：`[618b3e1](https://github.com/bytedance/deer-flow/commit/618b3e1e8f95e02c2b7bf8c8a2b137d13ed378ec)`
- 日期：2026-01-30
- 明确新增内容：新增了对“Github Flavored Markdown”的支持能力。
- 影响范围：主要涉及 前端。
- 改动规模：+108 / -30 行。
- 关键文件：frontend/package.json；frontend/pnpm-lock.yaml；frontend/src/components/workspace/artifacts/artifact-file-detail.tsx；frontend/src/components/workspace/messages/message-list-item.tsx；frontend/src/core/streamdown/index.ts；frontend/src/core/streamdown/plugins.ts。

#### 24. feat: support Github Flavored Markdown

- 提交：`[1bb91bb](https://github.com/bytedance/deer-flow/commit/1bb91bb26791fc4a8013d92d92e0594c27bfb0ec)`
- 日期：2026-01-30
- 明确新增内容：新增了对“Github Flavored Markdown”的支持能力。
- 影响范围：主要涉及 前端。
- 改动规模：+108 / -30 行。
- 关键文件：frontend/package.json；frontend/pnpm-lock.yaml；frontend/src/components/workspace/artifacts/artifact-file-detail.tsx；frontend/src/components/workspace/messages/message-list-item.tsx；frontend/src/core/streamdown/index.ts；frontend/src/core/streamdown/plugins.ts。

#### 25. feat: re-arrange icons

- 提交：`[4dffad8](https://github.com/bytedance/deer-flow/commit/4dffad89cae9932727c2085a478050987e3dc10f)`
- 日期：2026-01-29
- 明确新增内容：引入了“re-arrange icons”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+36 / -23 行。
- 关键文件：frontend/src/components/workspace/input-box.tsx。

#### 26. feat: re-arrange icons

- 提交：`[cbcbbbe](https://github.com/bytedance/deer-flow/commit/cbcbbbe0a8f451a8417a4941db8c9f542256a3e6)`
- 日期：2026-01-29
- 明确新增内容：引入了“re-arrange icons”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+36 / -23 行。
- 关键文件：frontend/src/components/workspace/input-box.tsx。

#### 27. feat: re-arrange icons

- 提交：`[939745d](https://github.com/bytedance/deer-flow/commit/939745d027cbbf2f4d83f2dbd27963be031a94c2)`
- 日期：2026-01-29
- 明确新增内容：引入了“re-arrange icons”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+36 / -23 行。
- 关键文件：frontend/src/components/workspace/input-box.tsx。

#### 28. feat: display mode

- 提交：`[a135ddf](https://github.com/bytedance/deer-flow/commit/a135ddfa487568cc45ed8fc295a85a16d7f8de43)`
- 日期：2026-01-29
- 明确新增内容：引入了“display mode”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+16 / -0 行。
- 关键文件：frontend/src/components/workspace/input-box.tsx。

#### 29. feat: display mode

- 提交：`[86ed750](https://github.com/bytedance/deer-flow/commit/86ed750a385d7658793ca0253b37dbc9952b16af)`
- 日期：2026-01-29
- 明确新增内容：引入了“display mode”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+16 / -0 行。
- 关键文件：frontend/src/components/workspace/input-box.tsx。

#### 30. feat: display mode

- 提交：`[79955d2](https://github.com/bytedance/deer-flow/commit/79955d2e6c4883a3aa3840190a32372a0bd001ca)`
- 日期：2026-01-29
- 明确新增内容：引入了“display mode”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+16 / -0 行。
- 关键文件：frontend/src/components/workspace/input-box.tsx。

#### 31. feat: use "mode" instead of "thinking_enabled" and "is_plan_mode"

- 提交：`[62ac3b6](https://github.com/bytedance/deer-flow/commit/62ac3b6b033417c38d46140d912825b5ca9ff16a)`
- 日期：2026-01-29
- 明确新增内容：引入了“use "mode" instead of "thinking_enabled" and "is_plan_mode"”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+46 / -49 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/app/workspace/layout.tsx；frontend/src/components/workspace/input-box.tsx；frontend/src/core/settings/local.ts。

#### 32. feat: use "mode" instead of "thinking_enabled" and "is_plan_mode"

- 提交：`[7bf15cb](https://github.com/bytedance/deer-flow/commit/7bf15cb777dbc5de3ab3a74693d89fd65a823520)`
- 日期：2026-01-29
- 明确新增内容：引入了“use "mode" instead of "thinking_enabled" and "is_plan_mode"”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+46 / -49 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/app/workspace/layout.tsx；frontend/src/components/workspace/input-box.tsx；frontend/src/core/settings/local.ts。

#### 33. feat: use "mode" instead of "thinking_enabled" and "is_plan_mode"

- 提交：`[98e08a8](https://github.com/bytedance/deer-flow/commit/98e08a85c9c28c639098dc215bb931b6c18067ed)`
- 日期：2026-01-29
- 明确新增内容：引入了“use "mode" instead of "thinking_enabled" and "is_plan_mode"”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+46 / -49 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/app/workspace/layout.tsx；frontend/src/components/workspace/input-box.tsx；frontend/src/core/settings/local.ts。

#### 34. feat: add placeholder for image

- 提交：`[9d88943](https://github.com/bytedance/deer-flow/commit/9d889434c4cf920fe35dfb8d61f7c737fac48855)`
- 日期：2026-01-29
- 明确新增内容：新增了“placeholder for image”功能。
- 影响范围：主要涉及 前端。
- 改动规模：+9 / -7 行。
- 关键文件：frontend/src/components/workspace/messages/message-group.tsx。

#### 35. feat: add placeholder for image

- 提交：`[4fc54a7](https://github.com/bytedance/deer-flow/commit/4fc54a740895958562a178c6129853e0a12b5691)`
- 日期：2026-01-29
- 明确新增内容：新增了“placeholder for image”功能。
- 影响范围：主要涉及 前端。
- 改动规模：+9 / -7 行。
- 关键文件：frontend/src/components/workspace/messages/message-group.tsx。

#### 36. feat: add placeholder for image

- 提交：`[16a9626](https://github.com/bytedance/deer-flow/commit/16a9626d54a0a4d4fa508e7e29fa04f3ca22c335)`
- 日期：2026-01-29
- 明确新增内容：新增了“placeholder for image”功能。
- 影响范围：主要涉及 前端。
- 改动规模：+9 / -7 行。
- 关键文件：frontend/src/components/workspace/messages/message-group.tsx。

#### 37. feat: optimize vision tools and image handling

- 提交：`[2c7a56d](https://github.com/bytedance/deer-flow/commit/2c7a56dd3345c782e8b87ba68d52d3729689fbc7)`
- 日期：2026-01-29
- 明确新增内容：引入了“optimize vision tools and image handling”相关功能改进。
- 影响范围：主要涉及 后端、配置、技能体系。
- 改动规模：+59 / -19 行。
- 关键文件：backend/src/agents/lead_agent/agent.py；backend/src/community/image_search/tools.py；backend/src/tools/tools.py；config.example.yaml；skills/public/image-generation/scripts/generate.py。

#### 38. feat: optimize vision tools and image handling

- 提交：`[314ea41](https://github.com/bytedance/deer-flow/commit/314ea4178132e65519eb0036e8367ea7256a719f)`
- 日期：2026-01-29
- 明确新增内容：引入了“optimize vision tools and image handling”相关功能改进。
- 影响范围：主要涉及 后端、配置、技能体系。
- 改动规模：+59 / -19 行。
- 关键文件：backend/src/agents/lead_agent/agent.py；backend/src/community/image_search/tools.py；backend/src/tools/tools.py；config.example.yaml；skills/public/image-generation/scripts/generate.py。

#### 39. feat: optimize vision tools and image handling

- 提交：`[7aa10b9](https://github.com/bytedance/deer-flow/commit/7aa10b980fbb94de1f786a3abfe8fe70ac12cfdd)`
- 日期：2026-01-29
- 明确新增内容：引入了“optimize vision tools and image handling”相关功能改进。
- 影响范围：主要涉及 后端、配置、技能体系。
- 改动规模：+59 / -19 行。
- 关键文件：backend/src/agents/lead_agent/agent.py；backend/src/community/image_search/tools.py；backend/src/tools/tools.py；config.example.yaml；skills/public/image-generation/scripts/generate.py。

#### 40. feat: add view_image tool and optimize web fetch tools

- 提交：`[09d9c18](https://github.com/bytedance/deer-flow/commit/09d9c18a28f677a8053d920a67b0b097c64fea6f)`
- 日期：2026-01-29
- 明确新增内容：新增了“view_image tool and optimize web fetch tools”功能。
- 影响范围：主要涉及 后端、配置。
- 改动规模：+390 / -13 行。
- 关键文件：backend/src/agents/lead_agent/agent.py；backend/src/agents/middlewares/view_image_middleware.py；backend/src/agents/thread_state.py；backend/src/community/firecrawl/tools.py；backend/src/community/jina_ai/tools.py；backend/src/community/tavily/tools.py；backend/src/config/model_config.py；backend/src/models/factory.py。

#### 41. feat: add view_image tool and optimize web fetch tools

- 提交：`[7414947](https://github.com/bytedance/deer-flow/commit/7414947cc67f33615b7b91980a9b487f34a6456c)`
- 日期：2026-01-29
- 明确新增内容：新增了“view_image tool and optimize web fetch tools”功能。
- 影响范围：主要涉及 后端、配置。
- 改动规模：+390 / -13 行。
- 关键文件：backend/src/agents/lead_agent/agent.py；backend/src/agents/middlewares/view_image_middleware.py；backend/src/agents/thread_state.py；backend/src/community/firecrawl/tools.py；backend/src/community/jina_ai/tools.py；backend/src/community/tavily/tools.py；backend/src/config/model_config.py；backend/src/models/factory.py。

#### 42. feat: add view_image tool and optimize web fetch tools

- 提交：`[9dc2405](https://github.com/bytedance/deer-flow/commit/9dc24055550b45445018814ce52584d29cd1c33e)`
- 日期：2026-01-29
- 明确新增内容：新增了“view_image tool and optimize web fetch tools”功能。
- 影响范围：主要涉及 后端、配置。
- 改动规模：+390 / -13 行。
- 关键文件：backend/src/agents/lead_agent/agent.py；backend/src/agents/middlewares/view_image_middleware.py；backend/src/agents/thread_state.py；backend/src/community/firecrawl/tools.py；backend/src/community/jina_ai/tools.py；backend/src/community/tavily/tools.py；backend/src/config/model_config.py；backend/src/models/factory.py。

#### 43. merge: upstream/experimental with citations feature

- 提交：`[588673d](https://github.com/bytedance/deer-flow/commit/588673d0437d84a78183952bfa43ae18bd1e865d)`
- 日期：2026-01-29
- 明确新增内容：引入了“merge: upstream/experimental with citations feature”相关功能改进。
- 影响范围：主要涉及 后端、前端、技能体系。
- 改动规模：+771 / -112 行。
- 关键文件：backend/pyproject.toml；backend/src/agents/lead_agent/prompt.py；backend/src/agents/middlewares/clarification_middleware.py；backend/src/community/image_search/**init**.py；backend/src/community/image_search/tools.py；backend/src/config/sandbox_config.py；backend/src/gateway/routers/mcp.py；backend/src/models/patched_deepseek.py。

#### 44. merge: upstream/experimental with citations feature

- 提交：`[ac283b9](https://github.com/bytedance/deer-flow/commit/ac283b92aab233eba3240f1a3c4deb91cb4abfae)`
- 日期：2026-01-29
- 明确新增内容：引入了“merge: upstream/experimental with citations feature”相关功能改进。
- 影响范围：主要涉及 后端、前端、技能体系。
- 改动规模：+771 / -112 行。
- 关键文件：backend/pyproject.toml；backend/src/agents/lead_agent/prompt.py；backend/src/agents/middlewares/clarification_middleware.py；backend/src/community/image_search/**init**.py；backend/src/community/image_search/tools.py；backend/src/config/sandbox_config.py；backend/src/gateway/routers/mcp.py；backend/src/models/patched_deepseek.py。

#### 45. merge: upstream/experimental with citations feature

- 提交：`[5120022](https://github.com/bytedance/deer-flow/commit/5120022d6d1182be13980b6fdfabcc9851a449d0)`
- 日期：2026-01-29
- 明确新增内容：引入了“merge: upstream/experimental with citations feature”相关功能改进。
- 影响范围：主要涉及 后端、前端、技能体系。
- 改动规模：+771 / -112 行。
- 关键文件：backend/pyproject.toml；backend/src/agents/lead_agent/prompt.py；backend/src/agents/middlewares/clarification_middleware.py；backend/src/community/image_search/**init**.py；backend/src/community/image_search/tools.py；backend/src/config/sandbox_config.py；backend/src/gateway/routers/mcp.py；backend/src/models/patched_deepseek.py。

#### 46. feat: improve file upload message handling and UI

- 提交：`[849cc4d](https://github.com/bytedance/deer-flow/commit/849cc4d771e74938c7b8d919d3e193e6c425b087)`
- 日期：2026-01-29
- 明确新增内容：增强了“improve file upload message handling and UI”相关能力与交互体验。
- 影响范围：主要涉及 前端、后端。
- 改动规模：+102 / -3 行。
- 关键文件：backend/src/agents/middlewares/uploads_middleware.py；frontend/src/components/workspace/messages/message-list-item.tsx；frontend/src/core/threads/hooks.ts。

#### 47. feat: improve file upload message handling and UI

- 提交：`[ce9731c](https://github.com/bytedance/deer-flow/commit/ce9731c10a77a543c7dc58ec88ad41cf89e7857c)`
- 日期：2026-01-29
- 明确新增内容：增强了“improve file upload message handling and UI”相关能力与交互体验。
- 影响范围：主要涉及 前端、后端。
- 改动规模：+102 / -3 行。
- 关键文件：backend/src/agents/middlewares/uploads_middleware.py；frontend/src/components/workspace/messages/message-list-item.tsx；frontend/src/core/threads/hooks.ts。

#### 48. feat: improve file upload message handling and UI

- 提交：`[3413975](https://github.com/bytedance/deer-flow/commit/341397562a82aedd966977ea2131f880949e7ef3)`
- 日期：2026-01-29
- 明确新增内容：增强了“improve file upload message handling and UI”相关能力与交互体验。
- 影响范围：主要涉及 前端、后端。
- 改动规模：+102 / -3 行。
- 关键文件：backend/src/agents/middlewares/uploads_middleware.py；frontend/src/components/workspace/messages/message-list-item.tsx；frontend/src/core/threads/hooks.ts。

#### 49. feat: enable images in content

- 提交：`[eff241f](https://github.com/bytedance/deer-flow/commit/eff241f9f281f3c55dd0d415d2026884af1fe791)`
- 日期：2026-01-29
- 明确新增内容：引入了“enable images in content”相关功能改进。
- 影响范围：主要涉及 前端、后端。
- 改动规模：+3 / -3 行。
- 关键文件：backend/src/agents/lead_agent/prompt.py；frontend/src/components/workspace/messages/message-group.tsx；frontend/src/components/workspace/messages/message-list-item.tsx。

#### 50. feat: enable images in content

- 提交：`[f809b67](https://github.com/bytedance/deer-flow/commit/f809b67c47594d1e9d7f2caa8517036730435fd7)`
- 日期：2026-01-29
- 明确新增内容：引入了“enable images in content”相关功能改进。
- 影响范围：主要涉及 前端、后端。
- 改动规模：+3 / -3 行。
- 关键文件：backend/src/agents/lead_agent/prompt.py；frontend/src/components/workspace/messages/message-group.tsx；frontend/src/components/workspace/messages/message-list-item.tsx。

#### 51. feat: refine citations format and improve content presentation

- 提交：`[c14378a](https://github.com/bytedance/deer-flow/commit/c14378a312c3b616c3866e34a8aa85ad77ec706a)`
- 日期：2026-01-29
- 明确新增内容：增强了“refine citations format and improve content presentation”相关能力与交互体验。
- 影响范围：主要涉及 前端、后端。
- 改动规模：+515 / -185 行。
- 关键文件：backend/src/agents/lead_agent/prompt.py；backend/src/agents/middlewares/uploads_middleware.py；backend/src/gateway/routers/artifacts.py；frontend/package.json；frontend/pnpm-lock.yaml；frontend/src/components/workspace/artifacts/artifact-file-detail.tsx；frontend/src/components/workspace/messages/message-list-item.tsx；frontend/src/core/citations/utils.ts。

#### 52. feat: refine citations format and improve content presentation

- 提交：`[4b63e70](https://github.com/bytedance/deer-flow/commit/4b63e70b7ee7bd292a597585a4aaa819259bcb92)`
- 日期：2026-01-29
- 明确新增内容：增强了“refine citations format and improve content presentation”相关能力与交互体验。
- 影响范围：主要涉及 前端、后端。
- 改动规模：+515 / -185 行。
- 关键文件：backend/src/agents/lead_agent/prompt.py；backend/src/agents/middlewares/uploads_middleware.py；backend/src/gateway/routers/artifacts.py；frontend/package.json；frontend/pnpm-lock.yaml；frontend/src/components/workspace/artifacts/artifact-file-detail.tsx；frontend/src/components/workspace/messages/message-list-item.tsx；frontend/src/core/citations/utils.ts。

#### 53. feat: refine citations format and improve content presentation

- 提交：`[e8a8b5e](https://github.com/bytedance/deer-flow/commit/e8a8b5e56b13970c1a2c0c66875c1c4826aac69f)`
- 日期：2026-01-29
- 明确新增内容：增强了“refine citations format and improve content presentation”相关能力与交互体验。
- 影响范围：主要涉及 前端、后端。
- 改动规模：+515 / -185 行。
- 关键文件：backend/src/agents/lead_agent/prompt.py；backend/src/agents/middlewares/uploads_middleware.py；backend/src/gateway/routers/artifacts.py；frontend/package.json；frontend/pnpm-lock.yaml；frontend/src/components/workspace/artifacts/artifact-file-detail.tsx；frontend/src/components/workspace/messages/message-list-item.tsx；frontend/src/core/citations/utils.ts。

#### 54. feat: add tooltips

- 提交：`[6b030d7](https://github.com/bytedance/deer-flow/commit/6b030d75897eda9b5a680851e2901780d3c59fe7)`
- 日期：2026-01-29
- 明确新增内容：新增了“tooltips”功能。
- 影响范围：主要涉及 前端。
- 改动规模：+18 / -15 行。
- 关键文件：frontend/src/components/workspace/messages/message-group.tsx。

#### 55. feat: add tooltips

- 提交：`[e4d3735](https://github.com/bytedance/deer-flow/commit/e4d373541f9f6a0d800cbe960eb954405289735e)`
- 日期：2026-01-29
- 明确新增内容：新增了“tooltips”功能。
- 影响范围：主要涉及 前端。
- 改动规模：+18 / -15 行。
- 关键文件：frontend/src/components/workspace/messages/message-group.tsx。

#### 56. feat: enhance search_image

- 提交：`[c700bd6](https://github.com/bytedance/deer-flow/commit/c700bd6841cdd74ae882e3870470dafa26a4786d)`
- 日期：2026-01-29
- 明确新增内容：增强了“enhance search_image”相关能力与交互体验。
- 影响范围：主要涉及 前端。
- 改动规模：+23 / -8 行。
- 关键文件：frontend/src/components/workspace/messages/message-group.tsx。

#### 57. feat: enhance search_image

- 提交：`[f7ec116](https://github.com/bytedance/deer-flow/commit/f7ec116c263a905a66c9ad6dec7348b445bee486)`
- 日期：2026-01-29
- 明确新增内容：增强了“enhance search_image”相关能力与交互体验。
- 影响范围：主要涉及 前端。
- 改动规模：+23 / -8 行。
- 关键文件：frontend/src/components/workspace/messages/message-group.tsx。

#### 58. feat: support image_search

- 提交：`[8359d84](https://github.com/bytedance/deer-flow/commit/8359d842b56d009a3d9db9bb0494ced41a25011e)`
- 日期：2026-01-29
- 明确新增内容：新增了对“image_search”的支持能力。
- 影响范围：主要涉及 前端。
- 改动规模：+33 / -0 行。
- 关键文件：frontend/src/components/workspace/messages/message-group.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts；frontend/src/core/i18n/locales/zh-CN.ts。

#### 59. feat: support image_search

- 提交：`[d787b1c](https://github.com/bytedance/deer-flow/commit/d787b1ca5405fbb4360e494957bc1d131461eb8e)`
- 日期：2026-01-29
- 明确新增内容：新增了对“image_search”的支持能力。
- 影响范围：主要涉及 前端。
- 改动规模：+33 / -0 行。
- 关键文件：frontend/src/components/workspace/messages/message-group.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts；frontend/src/core/i18n/locales/zh-CN.ts。

#### 60. feat: add image search builtin tool

- 提交：`[1926c58](https://github.com/bytedance/deer-flow/commit/1926c58cf28926c6b75ac76fe2c9acf3a2ef4e0a)`
- 日期：2026-01-29
- 明确新增内容：新增了“image search builtin tool”功能。
- 影响范围：主要涉及 后端、配置、技能体系。
- 改动规模：+311 / -17 行。
- 关键文件：backend/pyproject.toml；backend/src/community/image_search/**init**.py；backend/src/community/image_search/tools.py；backend/src/config/sandbox_config.py；backend/src/gateway/routers/mcp.py；backend/src/models/patched_deepseek.py；backend/uv.lock；config.example.yaml。

#### 61. feat: add image search builtin tool

- 提交：`[5e62471](https://github.com/bytedance/deer-flow/commit/5e624713123f3ecdf64f423e1fd0597c08904cc5)`
- 日期：2026-01-29
- 明确新增内容：新增了“image search builtin tool”功能。
- 影响范围：主要涉及 后端、配置、技能体系。
- 改动规模：+311 / -17 行。
- 关键文件：backend/pyproject.toml；backend/src/community/image_search/**init**.py；backend/src/community/image_search/tools.py；backend/src/config/sandbox_config.py；backend/src/gateway/routers/mcp.py；backend/src/models/patched_deepseek.py；backend/uv.lock；config.example.yaml。

#### 62. feat: modernize PPT styles and add deep-research skill

- 提交：`[248ffe6](https://github.com/bytedance/deer-flow/commit/248ffe61bcc74d5bc5f3e75ba75463efd62f160d)`
- 日期：2026-01-29
- 明确新增内容：新增了“modernize PPT styles and add deep-research skill”功能。
- 影响范围：主要涉及 技能体系。
- 改动规模：+361 / -80 行。
- 关键文件：skills/public/deep-research/SKILL.md；skills/public/ppt-generation/SKILL.md。

#### 63. feat: modernize PPT styles and add deep-research skill

- 提交：`[af18df4](https://github.com/bytedance/deer-flow/commit/af18df480b6eb015be404f19042b2d2bb5314507)`
- 日期：2026-01-29
- 明确新增内容：新增了“modernize PPT styles and add deep-research skill”功能。
- 影响范围：主要涉及 技能体系。
- 改动规模：+361 / -80 行。
- 关键文件：skills/public/deep-research/SKILL.md；skills/public/ppt-generation/SKILL.md。

#### 64. feat: display ask_clarification tool messages directly in frontend

- 提交：`[d4bfed2](https://github.com/bytedance/deer-flow/commit/d4bfed271b151fa9e65df1a6bdc55bd61fb4a3e1)`
- 日期：2026-01-29
- 明确新增内容：引入了“display ask_clarification tool messages directly in frontend”相关功能改进。
- 影响范围：主要涉及 前端、后端。
- 改动规模：+44 / -12 行。
- 关键文件：backend/src/agents/middlewares/clarification_middleware.py；frontend/src/components/workspace/messages/message-list.tsx；frontend/src/core/messages/utils.ts。

#### 65. feat: display ask_clarification tool messages directly in frontend

- 提交：`[73a1d32](https://github.com/bytedance/deer-flow/commit/73a1d32a5b43686d3ecbb0d75ba8af0246907710)`
- 日期：2026-01-29
- 明确新增内容：引入了“display ask_clarification tool messages directly in frontend”相关功能改进。
- 影响范围：主要涉及 前端、后端。
- 改动规模：+44 / -12 行。
- 关键文件：backend/src/agents/middlewares/clarification_middleware.py；frontend/src/components/workspace/messages/message-list.tsx；frontend/src/core/messages/utils.ts。

#### 66. feat: add inline citations and thread management features

- 提交：`[ad85b72](https://github.com/bytedance/deer-flow/commit/ad85b720644dd3e5bddac1abb671fdf1878cbc38)`
- 日期：2026-01-28
- 明确新增内容：新增了“inline citations and thread management features”功能。
- 影响范围：主要涉及 前端、后端。
- 改动规模：+658 / -66 行。
- 关键文件：backend/src/agents/lead_agent/prompt.py；frontend/src/components/workspace/artifacts/artifact-file-detail.tsx；frontend/src/components/workspace/messages/message-list-item.tsx；frontend/src/components/workspace/recent-chat-list.tsx；frontend/src/core/citations/index.ts；frontend/src/core/citations/utils.ts；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts。

#### 67. feat: add inline citations and thread management features

- 提交：`[33c47e0](https://github.com/bytedance/deer-flow/commit/33c47e0c56e4e93b5d10e58383122886e80e314a)`
- 日期：2026-01-28
- 明确新增内容：新增了“inline citations and thread management features”功能。
- 影响范围：主要涉及 前端、后端。
- 改动规模：+658 / -66 行。
- 关键文件：backend/src/agents/lead_agent/prompt.py；frontend/src/components/workspace/artifacts/artifact-file-detail.tsx；frontend/src/components/workspace/messages/message-list-item.tsx；frontend/src/components/workspace/recent-chat-list.tsx；frontend/src/core/citations/index.ts；frontend/src/core/citations/utils.ts；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts。

#### 68. feat: add inline citations and thread management features

- 提交：`[f8d2d88](https://github.com/bytedance/deer-flow/commit/f8d2d887272d68698e9558e7b49526723643f63d)`
- 日期：2026-01-28
- 明确新增内容：新增了“inline citations and thread management features”功能。
- 影响范围：主要涉及 前端、后端。
- 改动规模：+658 / -66 行。
- 关键文件：backend/src/agents/lead_agent/prompt.py；frontend/src/components/workspace/artifacts/artifact-file-detail.tsx；frontend/src/components/workspace/messages/message-list-item.tsx；frontend/src/components/workspace/recent-chat-list.tsx；frontend/src/core/citations/index.ts；frontend/src/core/citations/utils.ts；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts。

#### 69. feat: update notes

- 提交：`[a010953](https://github.com/bytedance/deer-flow/commit/a010953880e97807c2282e4fb3d359325d62fad2)`
- 日期：2026-01-28
- 明确新增内容：引入了“update notes”相关功能改进。
- 影响范围：主要涉及 后端。
- 改动规模：+1 / -1 行。
- 关键文件：backend/src/tools/builtins/present_file_tool.py。

#### 70. feat: update notes

- 提交：`[453efa1](https://github.com/bytedance/deer-flow/commit/453efa1a1d513553869212defd2c96cde87eee23)`
- 日期：2026-01-28
- 明确新增内容：引入了“update notes”相关功能改进。
- 影响范围：主要涉及 后端。
- 改动规模：+1 / -1 行。
- 关键文件：backend/src/tools/builtins/present_file_tool.py。

#### 71. feat: update a new demo

- 提交：`[dd2c201](https://github.com/bytedance/deer-flow/commit/dd2c2011f153b953f95ac78f2f37cc4b61198eb8)`
- 日期：2026-01-28
- 明确新增内容：引入了“update a new demo”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+1725 / -0 行。
- 关键文件：frontend/public/demo/threads/b83fbb2a-4e36-4d82-9de0-7b2a02c2092a/thread.json；frontend/public/demo/threads/b83fbb2a-4e36-4d82-9de0-7b2a02c2092a/user-data/outputs/caren-hero.jpg；frontend/public/demo/threads/b83fbb2a-4e36-4d82-9de0-7b2a02c2092a/user-data/outputs/caren-ingredients.jpg；frontend/public/demo/threads/b83fbb2a-4e36-4d82-9de0-7b2a02c2092a/user-data/outputs/caren-lifestyle.jpg；frontend/public/demo/threads/b83fbb2a-4e36-4d82-9de0-7b2a02c2092a/user-data/outputs/caren-products.jpg；frontend/public/demo/threads/b83fbb2a-4e36-4d82-9de0-7b2a02c2092a/user-data/outputs/index.html。

#### 72. feat: update a new demo

- 提交：`[c0980bf](https://github.com/bytedance/deer-flow/commit/c0980bfa82e443cd699752f6e0f3765ba0850afe)`
- 日期：2026-01-28
- 明确新增内容：引入了“update a new demo”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+1725 / -0 行。
- 关键文件：frontend/public/demo/threads/b83fbb2a-4e36-4d82-9de0-7b2a02c2092a/thread.json；frontend/public/demo/threads/b83fbb2a-4e36-4d82-9de0-7b2a02c2092a/user-data/outputs/caren-hero.jpg；frontend/public/demo/threads/b83fbb2a-4e36-4d82-9de0-7b2a02c2092a/user-data/outputs/caren-ingredients.jpg；frontend/public/demo/threads/b83fbb2a-4e36-4d82-9de0-7b2a02c2092a/user-data/outputs/caren-lifestyle.jpg；frontend/public/demo/threads/b83fbb2a-4e36-4d82-9de0-7b2a02c2092a/user-data/outputs/caren-products.jpg；frontend/public/demo/threads/b83fbb2a-4e36-4d82-9de0-7b2a02c2092a/user-data/outputs/index.html。

#### 73. feat: modify the config example yaml

- 提交：`[49f6c00](https://github.com/bytedance/deer-flow/commit/49f6c001c3b39f7a04293c103df764740087ba48)`
- 日期：2026-01-28
- 明确新增内容：引入了“modify the config example yaml”相关功能改进。
- 影响范围：主要涉及 配置。
- 改动规模：+4 / -3 行。
- 关键文件：config.example.yaml。

#### 74. feat: modify the config example yaml

- 提交：`[055ab1f](https://github.com/bytedance/deer-flow/commit/055ab1fb040ee3643fbd92b8a3797bcce2949a17)`
- 日期：2026-01-28
- 明确新增内容：引入了“modify the config example yaml”相关功能改进。
- 影响范围：主要涉及 配置。
- 改动规模：+4 / -3 行。
- 关键文件：config.example.yaml。

#### 75. feat: add Leica demo

- 提交：`[d84a34b](https://github.com/bytedance/deer-flow/commit/d84a34b7cdfe6e37f6f00fee1107d8597e296c5f)`
- 日期：2026-01-28
- 明确新增内容：新增了“Leica demo”功能。
- 影响范围：主要涉及 前端。
- 改动规模：+1195 / -0 行。
- 关键文件：frontend/public/demo/threads/7f9dc56c-e49c-4671-a3d2-c492ff4dce0c/thread.json；frontend/public/demo/threads/7f9dc56c-e49c-4671-a3d2-c492ff4dce0c/user-data/outputs/leica-master-photography-article.md；frontend/public/demo/threads/7f9dc56c-e49c-4671-a3d2-c492ff4dce0c/user-data/outputs/leica-nyc-candid.jpg；frontend/public/demo/threads/7f9dc56c-e49c-4671-a3d2-c492ff4dce0c/user-data/outputs/leica-paris-decisive-moment.jpg；frontend/public/demo/threads/7f9dc56c-e49c-4671-a3d2-c492ff4dce0c/user-data/outputs/leica-tokyo-night.jpg。

#### 76. feat: add Leica demo

- 提交：`[486a06d](https://github.com/bytedance/deer-flow/commit/486a06d772da2cf66d354c20c25c01c09d8bdf95)`
- 日期：2026-01-28
- 明确新增内容：新增了“Leica demo”功能。
- 影响范围：主要涉及 前端。
- 改动规模：+1195 / -0 行。
- 关键文件：frontend/public/demo/threads/7f9dc56c-e49c-4671-a3d2-c492ff4dce0c/thread.json；frontend/public/demo/threads/7f9dc56c-e49c-4671-a3d2-c492ff4dce0c/user-data/outputs/leica-master-photography-article.md；frontend/public/demo/threads/7f9dc56c-e49c-4671-a3d2-c492ff4dce0c/user-data/outputs/leica-nyc-candid.jpg；frontend/public/demo/threads/7f9dc56c-e49c-4671-a3d2-c492ff4dce0c/user-data/outputs/leica-paris-decisive-moment.jpg；frontend/public/demo/threads/7f9dc56c-e49c-4671-a3d2-c492ff4dce0c/user-data/outputs/leica-tokyo-night.jpg。

#### 77. feat: fallback to error reporting

- 提交：`[d075e7a](https://github.com/bytedance/deer-flow/commit/d075e7a234345e3c5189ca928340a6e143c2dc90)`
- 日期：2026-01-28
- 明确新增内容：引入了“fallback to error reporting”相关功能改进。
- 影响范围：主要涉及 后端。
- 改动规模：+31 / -25 行。
- 关键文件：backend/src/community/firecrawl/tools.py。

#### 78. feat: fallback to error reporting

- 提交：`[5980bbd](https://github.com/bytedance/deer-flow/commit/5980bbde023062a35cdb8ac25917ed0dace76739)`
- 日期：2026-01-28
- 明确新增内容：引入了“fallback to error reporting”相关功能改进。
- 影响范围：主要涉及 后端。
- 改动规模：+31 / -25 行。
- 关键文件：backend/src/community/firecrawl/tools.py。

#### 79. feat: add another Kimi K2.5 demo

- 提交：`[a249b71](https://github.com/bytedance/deer-flow/commit/a249b7178a32eff9ff569ac27e9858a058e2a36f)`
- 日期：2026-01-28
- 明确新增内容：新增了“another Kimi K2.5 demo”功能。
- 影响范围：主要涉及 前端。
- 改动规模：+1109 / -0 行。
- 关键文件：frontend/public/demo/threads/f4125791-0128-402a-8ca9-50e0947557e4/thread.json；frontend/public/demo/threads/f4125791-0128-402a-8ca9-50e0947557e4/user-data/outputs/index.html。

#### 80. feat: add another Kimi K2.5 demo

- 提交：`[5d5aec4](https://github.com/bytedance/deer-flow/commit/5d5aec43d31f9f3be7c7ba02749fd0abc5e3246b)`
- 日期：2026-01-28
- 明确新增内容：新增了“another Kimi K2.5 demo”功能。
- 影响范围：主要涉及 前端。
- 改动规模：+1109 / -0 行。
- 关键文件：frontend/public/demo/threads/f4125791-0128-402a-8ca9-50e0947557e4/thread.json；frontend/public/demo/threads/f4125791-0128-402a-8ca9-50e0947557e4/user-data/outputs/index.html。

#### 81. feat: add kimi-k2.5 demo with vercel deployment

- 提交：`[e2bcc70](https://github.com/bytedance/deer-flow/commit/e2bcc70a8436eb9411999e2e32550d26ee522db8)`
- 日期：2026-01-28
- 明确新增内容：新增了“kimi-k2.5 demo with vercel deployment”功能。
- 影响范围：主要涉及 前端。
- 改动规模：+2088 / -0 行。
- 关键文件：frontend/public/demo/threads/c02bb4d5-4202-490e-ae8f-ff4864fc0d2e/thread.json；frontend/public/demo/threads/c02bb4d5-4202-490e-ae8f-ff4864fc0d2e/user-data/outputs/index.html；frontend/public/demo/threads/c02bb4d5-4202-490e-ae8f-ff4864fc0d2e/user-data/outputs/script.js；frontend/public/demo/threads/c02bb4d5-4202-490e-ae8f-ff4864fc0d2e/user-data/outputs/styles.css。

#### 82. feat: add kimi-k2.5 demo with vercel deployment

- 提交：`[ade5426](https://github.com/bytedance/deer-flow/commit/ade5426d9e05cb59b867c2ad0766834668ed6fc4)`
- 日期：2026-01-28
- 明确新增内容：新增了“kimi-k2.5 demo with vercel deployment”功能。
- 影响范围：主要涉及 前端。
- 改动规模：+2088 / -0 行。
- 关键文件：frontend/public/demo/threads/c02bb4d5-4202-490e-ae8f-ff4864fc0d2e/thread.json；frontend/public/demo/threads/c02bb4d5-4202-490e-ae8f-ff4864fc0d2e/user-data/outputs/index.html；frontend/public/demo/threads/c02bb4d5-4202-490e-ae8f-ff4864fc0d2e/user-data/outputs/script.js；frontend/public/demo/threads/c02bb4d5-4202-490e-ae8f-ff4864fc0d2e/user-data/outputs/styles.css。

#### 83. feat: fallback to textarea when loading

- 提交：`[dab4093](https://github.com/bytedance/deer-flow/commit/dab4093103aa4798670f263ab9588142b142cca0)`
- 日期：2026-01-28
- 明确新增内容：引入了“fallback to textarea when loading”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+43 / -25 行。
- 关键文件：frontend/src/components/workspace/code-editor.tsx。

#### 84. feat: fallback to textarea when loading

- 提交：`[86c8f1a](https://github.com/bytedance/deer-flow/commit/86c8f1a25eccc9e6dd733a7ca75c1af4796c492c)`
- 日期：2026-01-28
- 明确新增内容：引入了“fallback to textarea when loading”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+43 / -25 行。
- 关键文件：frontend/src/components/workspace/code-editor.tsx。

#### 85. feat: add scroll indicator

- 提交：`[28361ca](https://github.com/bytedance/deer-flow/commit/28361ca03cb7d732ddc1079df5959ff13a20cb22)`
- 日期：2026-01-27
- 明确新增内容：新增了“scroll indicator”功能。
- 影响范围：主要涉及 前端。
- 改动规模：+5 / -5 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/ai-elements/conversation.tsx。

#### 86. feat: add scroll indicator

- 提交：`[7c42fa5](https://github.com/bytedance/deer-flow/commit/7c42fa516285fc4e764fb9d37ab6ed912f8e5613)`
- 日期：2026-01-27
- 明确新增内容：新增了“scroll indicator”功能。
- 影响范围：主要涉及 前端。
- 改动规模：+5 / -5 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/ai-elements/conversation.tsx。

#### 87. feat: Generate a fallback report upon recursion limit hit (#838)

- 提交：`[ee02b9f](https://github.com/bytedance/deer-flow/commit/ee02b9f637aa859943b9ef45bb25e0b0f1bf0a0b)`
- 日期：2026-01-26
- 明确新增内容：引入了“Generate a fallback report upon recursion limit hit”相关功能改进。
- 影响范围：主要涉及 其他模块、文档。
- 改动规模：+895 / -12 行。
- 关键文件：docs/configuration_guide.md；src/config/configuration.py；src/graph/nodes.py；src/prompts/recursion_fallback.md；src/prompts/template.py；tests/integration/test_nodes.py；tests/unit/graph/test_nodes_recursion_limit.py。

#### 88. feat: add firecrawl community package with web_search and web_fetch tools

- 提交：`[b8c33e3](https://github.com/bytedance/deer-flow/commit/b8c33e342b08315237ef5e5cd42ea17dfe822292)`
- 日期：2026-01-26
- 明确新增内容：新增了“firecrawl community package with web_search and web_fetch tools”功能。
- 影响范围：主要涉及 后端、其他模块。
- 改动规模：+571 / -0 行。
- 关键文件：.env.example；backend/pyproject.toml；backend/src/community/firecrawl/tools.py；backend/uv.lock。

#### 89. feat: add firecrawl community package with web_search and web_fetch tools

- 提交：`[ce7f725](https://github.com/bytedance/deer-flow/commit/ce7f7258ba119442161de46d5a2a44ea30bc78ec)`
- 日期：2026-01-26
- 明确新增内容：新增了“firecrawl community package with web_search and web_fetch tools”功能。
- 影响范围：主要涉及 后端、其他模块。
- 改动规模：+571 / -0 行。
- 关键文件：.env.example；backend/pyproject.toml；backend/src/community/firecrawl/tools.py；backend/uv.lock。

#### 90. feat: add ppt-generation skill

- 提交：`[9215c9c](https://github.com/bytedance/deer-flow/commit/9215c9cce7a81e26b7750bfd8663f96cb023cdf7)`
- 日期：2026-01-26
- 明确新增内容：新增了“ppt-generation skill”功能。
- 影响范围：主要涉及 技能体系。
- 改动规模：+511 / -0 行。
- 关键文件：skills/public/ppt-generation/SKILL.md；skills/public/ppt-generation/scripts/generate.py。

#### 91. feat: add ppt-generation skill

- 提交：`[0cc7cc0](https://github.com/bytedance/deer-flow/commit/0cc7cc08e91243b3f11a30f27fe5aab11c247f22)`
- 日期：2026-01-26
- 明确新增内容：新增了“ppt-generation skill”功能。
- 影响范围：主要涉及 技能体系。
- 改动规模：+511 / -0 行。
- 关键文件：skills/public/ppt-generation/SKILL.md；skills/public/ppt-generation/scripts/generate.py。

#### 92. feat: auto select the first model as default model

- 提交：`[3ce4968](https://github.com/bytedance/deer-flow/commit/3ce4968e95cf0e0c8ace2ca0e6282a66fc7cd98f)`
- 日期：2026-01-26
- 明确新增内容：引入了“auto select the first model as default model”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+17 / -8 行。
- 关键文件：frontend/src/components/workspace/input-box.tsx；frontend/src/core/models/hooks.ts；frontend/src/core/settings/local.ts；frontend/src/core/threads/types.ts。

#### 93. feat: auto select the first model as default model

- 提交：`[574dfd2](https://github.com/bytedance/deer-flow/commit/574dfd2b054c2d4854147f54cf181ed793ff5b2c)`
- 日期：2026-01-26
- 明确新增内容：引入了“auto select the first model as default model”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+17 / -8 行。
- 关键文件：frontend/src/components/workspace/input-box.tsx；frontend/src/core/models/hooks.ts；frontend/src/core/settings/local.ts；frontend/src/core/threads/types.ts。

#### 94. feat: add podcast generation skill

- 提交：`[9f5658f](https://github.com/bytedance/deer-flow/commit/9f5658fa0e2f4ab0b017eb73d708c7bda60642f3)`
- 日期：2026-01-25
- 明确新增内容：新增了“podcast generation skill”功能。
- 影响范围：主要涉及 技能体系、其他模块、后端。
- 改动规模：+542 / -1 行。
- 关键文件：.gitignore；backend/src/sandbox/local/local_sandbox.py；skills/public/podcast-generation/SKILL.md；skills/public/podcast-generation/scripts/generate.py；skills/public/podcast-generation/templates/tech-explainer.md。

#### 95. feat: add podcast generation skill

- 提交：`[3fa1646](https://github.com/bytedance/deer-flow/commit/3fa16467a25c690c8e5844ee93178e40efca15d5)`
- 日期：2026-01-25
- 明确新增内容：新增了“podcast generation skill”功能。
- 影响范围：主要涉及 技能体系、其他模块、后端。
- 改动规模：+542 / -1 行。
- 关键文件：.gitignore；backend/src/sandbox/local/local_sandbox.py；skills/public/podcast-generation/SKILL.md；skills/public/podcast-generation/scripts/generate.py；skills/public/podcast-generation/templates/tech-explainer.md。

#### 96. feat: adjust button

- 提交：`[f629e13](https://github.com/bytedance/deer-flow/commit/f629e134d4e28a70dbdeb1d8e7a3326fb2ef9e9e)`
- 日期：2026-01-25
- 明确新增内容：引入了“adjust button”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+17 / -13 行。
- 关键文件：frontend/src/components/landing/progressive-skills-animation.tsx。

#### 97. feat: adjust button

- 提交：`[044e38a](https://github.com/bytedance/deer-flow/commit/044e38aec65a9b67e59c6e11f9e398c7762ec66d)`
- 日期：2026-01-25
- 明确新增内容：引入了“adjust button”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+17 / -13 行。
- 关键文件：frontend/src/components/landing/progressive-skills-animation.tsx。

#### 98. feat: add image and video generation skills

- 提交：`[ae0e7de](https://github.com/bytedance/deer-flow/commit/ae0e7de3b71f70e0754eeafd8353329a37837ddc)`
- 日期：2026-01-25
- 明确新增内容：新增了“image and video generation skills”功能。
- 影响范围：主要涉及 技能体系。
- 改动规模：+630 / -169 行。
- 关键文件：skills/public/doraemon-comic-aigc/SKILL.md；skills/public/doraemon-comic-aigc/scripts/generate.py；skills/public/image-generation/SKILL.md；skills/public/image-generation/scripts/generate.py；skills/public/image-generation/templates/doraemon.md；skills/public/video-generation/SKILL.md；skills/public/video-generation/scripts/generate.py。

#### 99. feat: add image and video generation skills

- 提交：`[b53a2ea](https://github.com/bytedance/deer-flow/commit/b53a2ea5e1301fcf4e9a104db3724c6b09a66b27)`
- 日期：2026-01-25
- 明确新增内容：新增了“image and video generation skills”功能。
- 影响范围：主要涉及 技能体系。
- 改动规模：+630 / -169 行。
- 关键文件：skills/public/doraemon-comic-aigc/SKILL.md；skills/public/doraemon-comic-aigc/scripts/generate.py；skills/public/image-generation/SKILL.md；skills/public/image-generation/scripts/generate.py；skills/public/image-generation/templates/doraemon.md；skills/public/video-generation/SKILL.md；skills/public/video-generation/scripts/generate.py。

#### 100. feat: update demo

- 提交：`[af4fc80](https://github.com/bytedance/deer-flow/commit/af4fc800ee540a7d93dbef059b6dd874b72f93f7)`
- 日期：2026-01-25
- 明确新增内容：引入了“update demo”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+2043 / -1117 行。
- 关键文件：frontend/public/demo/threads/21cfea46-34bd-4aa6-9e1f-3009452fbeb9/thread.json；frontend/public/demo/threads/21cfea46-34bd-4aa6-9e1f-3009452fbeb9/user-data/outputs/doraemon-moe-comic.jpg；frontend/public/demo/threads/4f3e55ee-f853-43db-bfb3-7d1a411f03cb/thread.json；frontend/public/demo/threads/4f3e55ee-f853-43db-bfb3-7d1a411f03cb/user-data/outputs/darcy-proposal-reference.jpg；frontend/public/demo/threads/4f3e55ee-f853-43db-bfb3-7d1a411f03cb/user-data/outputs/darcy-proposal-video.mp4；frontend/public/demo/threads/85ee6ae5-bd68-4359-b17f-9f78c234d63c/thread.json；frontend/public/demo/threads/85ee6ae5-bd68-4359-b17f-9f78c234d63c/user-data/outputs/doraemon-moe.jpg；frontend/public/demo/threads/85ee6ae5-bd68-4359-b17f-9f78c234d63c/user-data/outputs/prompt.json。

#### 101. feat: update demo

- 提交：`[90c30c8](https://github.com/bytedance/deer-flow/commit/90c30c8485ae5f1477086347f3363314cff40876)`
- 日期：2026-01-25
- 明确新增内容：引入了“update demo”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+2043 / -1117 行。
- 关键文件：frontend/public/demo/threads/21cfea46-34bd-4aa6-9e1f-3009452fbeb9/thread.json；frontend/public/demo/threads/21cfea46-34bd-4aa6-9e1f-3009452fbeb9/user-data/outputs/doraemon-moe-comic.jpg；frontend/public/demo/threads/4f3e55ee-f853-43db-bfb3-7d1a411f03cb/thread.json；frontend/public/demo/threads/4f3e55ee-f853-43db-bfb3-7d1a411f03cb/user-data/outputs/darcy-proposal-reference.jpg；frontend/public/demo/threads/4f3e55ee-f853-43db-bfb3-7d1a411f03cb/user-data/outputs/darcy-proposal-video.mp4；frontend/public/demo/threads/85ee6ae5-bd68-4359-b17f-9f78c234d63c/thread.json；frontend/public/demo/threads/85ee6ae5-bd68-4359-b17f-9f78c234d63c/user-data/outputs/doraemon-moe.jpg；frontend/public/demo/threads/85ee6ae5-bd68-4359-b17f-9f78c234d63c/user-data/outputs/prompt.json。

#### 102. feat: update translations

- 提交：`[87200d1](https://github.com/bytedance/deer-flow/commit/87200d1ad12bd1a7a5fc7278e65c2598e869cd35)`
- 日期：2026-01-25
- 明确新增内容：引入了“update translations”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+9 / -8 行。
- 关键文件：frontend/src/components/landing/sections/skills-section.tsx；frontend/src/components/workspace/settings/skill-settings-page.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/zh-CN.ts。

#### 103. feat: update translations

- 提交：`[e6cac2c](https://github.com/bytedance/deer-flow/commit/e6cac2cae4eb0fe28c8fe5d5a2c092a27c5d0fb0)`
- 日期：2026-01-25
- 明确新增内容：引入了“update translations”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+9 / -8 行。
- 关键文件：frontend/src/components/landing/sections/skills-section.tsx；frontend/src/components/workspace/settings/skill-settings-page.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/zh-CN.ts。

#### 104. feat: update demos

- 提交：`[74dd09b](https://github.com/bytedance/deer-flow/commit/74dd09b364a1e14074dc7ae480178d2b4f482308)`
- 日期：2026-01-25
- 明确新增内容：引入了“update demos”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+2910 / -537 行。
- 关键文件：frontend/public/demo/threads/3823e443-4e2b-4679-b496-a9506eae462b/thread.json；frontend/public/demo/threads/3823e443-4e2b-4679-b496-a9506eae462b/user-data/outputs/fei-fei-li-podcast-timeline.md；frontend/public/demo/threads/d3e5adaf-084c-4dd5-9d29-94f1d6bccd98/thread.json；frontend/public/demo/threads/d3e5adaf-084c-4dd5-9d29-94f1d6bccd98/user-data/outputs/diana_hu_research.md；frontend/public/demo/threads/e05bea79-5b98-4e79-bc5f-c624be86ff7f/thread.json。

#### 105. feat: update demos

- 提交：`[e84fb70](https://github.com/bytedance/deer-flow/commit/e84fb705ce5d484b6f2ae6c5132c217a314ac947)`
- 日期：2026-01-25
- 明确新增内容：引入了“update demos”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+2910 / -537 行。
- 关键文件：frontend/public/demo/threads/3823e443-4e2b-4679-b496-a9506eae462b/thread.json；frontend/public/demo/threads/3823e443-4e2b-4679-b496-a9506eae462b/user-data/outputs/fei-fei-li-podcast-timeline.md；frontend/public/demo/threads/d3e5adaf-084c-4dd5-9d29-94f1d6bccd98/thread.json；frontend/public/demo/threads/d3e5adaf-084c-4dd5-9d29-94f1d6bccd98/user-data/outputs/diana_hu_research.md；frontend/public/demo/threads/e05bea79-5b98-4e79-bc5f-c624be86ff7f/thread.json。

#### 106. feat: add Titanic ADA demo

- 提交：`[78bba47](https://github.com/bytedance/deer-flow/commit/78bba477698802afdddbc6df7ed8a606ab3d92a9)`
- 日期：2026-01-25
- 明确新增内容：新增了“Titanic ADA demo”功能。
- 影响范围：主要涉及 前端。
- 改动规模：+1527 / -5 行。
- 关键文件：frontend/public/demo/threads/ad76c455-5bf9-4335-8517-fc03834ab828/thread.json；frontend/public/demo/threads/ad76c455-5bf9-4335-8517-fc03834ab828/user-data/outputs/titanic_summary.txt；frontend/public/demo/threads/ad76c455-5bf9-4335-8517-fc03834ab828/user-data/outputs/visualizations/class_gender_survival.png；frontend/public/demo/threads/ad76c455-5bf9-4335-8517-fc03834ab828/user-data/outputs/visualizations/correlation_heatmap.png；frontend/public/demo/threads/ad76c455-5bf9-4335-8517-fc03834ab828/user-data/outputs/visualizations/family_size_analysis.png；frontend/public/demo/threads/ad76c455-5bf9-4335-8517-fc03834ab828/user-data/outputs/visualizations/fare_analysis.png；frontend/public/demo/threads/ad76c455-5bf9-4335-8517-fc03834ab828/user-data/outputs/visualizations/survival_by_age.png；frontend/public/demo/threads/ad76c455-5bf9-4335-8517-fc03834ab828/user-data/outputs/visualizations/survival_by_class.png。

#### 107. feat: add Titanic ADA demo

- 提交：`[c6dbd9f](https://github.com/bytedance/deer-flow/commit/c6dbd9fbf42f04a47d316f95ff08adefbcb80aad)`
- 日期：2026-01-25
- 明确新增内容：新增了“Titanic ADA demo”功能。
- 影响范围：主要涉及 前端。
- 改动规模：+1527 / -5 行。
- 关键文件：frontend/public/demo/threads/ad76c455-5bf9-4335-8517-fc03834ab828/thread.json；frontend/public/demo/threads/ad76c455-5bf9-4335-8517-fc03834ab828/user-data/outputs/titanic_summary.txt；frontend/public/demo/threads/ad76c455-5bf9-4335-8517-fc03834ab828/user-data/outputs/visualizations/class_gender_survival.png；frontend/public/demo/threads/ad76c455-5bf9-4335-8517-fc03834ab828/user-data/outputs/visualizations/correlation_heatmap.png；frontend/public/demo/threads/ad76c455-5bf9-4335-8517-fc03834ab828/user-data/outputs/visualizations/family_size_analysis.png；frontend/public/demo/threads/ad76c455-5bf9-4335-8517-fc03834ab828/user-data/outputs/visualizations/fare_analysis.png；frontend/public/demo/threads/ad76c455-5bf9-4335-8517-fc03834ab828/user-data/outputs/visualizations/survival_by_age.png；frontend/public/demo/threads/ad76c455-5bf9-4335-8517-fc03834ab828/user-data/outputs/visualizations/survival_by_class.png。

#### 108. feat: add new demo

- 提交：`[35f2aea](https://github.com/bytedance/deer-flow/commit/35f2aea510e05c13f0a4ad646ceebf3ff8c156a8)`
- 日期：2026-01-24
- 明确新增内容：新增了“new demo”功能。
- 影响范围：主要涉及 前端。
- 改动规模：+3089 / -0 行。
- 关键文件：frontend/public/demo/threads/7cfa5f8f-a2f8-47ad-acbd-da7137baf990/thread.json；frontend/public/demo/threads/7cfa5f8f-a2f8-47ad-acbd-da7137baf990/user-data/outputs/index.html；frontend/public/demo/threads/7cfa5f8f-a2f8-47ad-acbd-da7137baf990/user-data/outputs/script.js；frontend/public/demo/threads/7cfa5f8f-a2f8-47ad-acbd-da7137baf990/user-data/outputs/style.css。

#### 109. feat: add new demo

- 提交：`[03311d4](https://github.com/bytedance/deer-flow/commit/03311d43dabbbbfd5e30b8aaf07816fbe5053de2)`
- 日期：2026-01-24
- 明确新增内容：新增了“new demo”功能。
- 影响范围：主要涉及 前端。
- 改动规模：+3089 / -0 行。
- 关键文件：frontend/public/demo/threads/7cfa5f8f-a2f8-47ad-acbd-da7137baf990/thread.json；frontend/public/demo/threads/7cfa5f8f-a2f8-47ad-acbd-da7137baf990/user-data/outputs/index.html；frontend/public/demo/threads/7cfa5f8f-a2f8-47ad-acbd-da7137baf990/user-data/outputs/script.js；frontend/public/demo/threads/7cfa5f8f-a2f8-47ad-acbd-da7137baf990/user-data/outputs/style.css。

#### 110. feat: auto expand in demo mode

- 提交：`[a83e5e2](https://github.com/bytedance/deer-flow/commit/a83e5e238d84c49f07d572b6b877230d6182558a)`
- 日期：2026-01-24
- 明确新增内容：引入了“auto expand in demo mode”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+34 / -5 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/workspace/artifacts/artifact-file-detail.tsx；frontend/src/components/workspace/artifacts/context.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts；frontend/src/core/i18n/locales/zh-CN.ts。

#### 111. feat: auto expand in demo mode

- 提交：`[099fb72](https://github.com/bytedance/deer-flow/commit/099fb727ccc04df964a208f8a89a8101e62ba9d0)`
- 日期：2026-01-24
- 明确新增内容：引入了“auto expand in demo mode”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+34 / -5 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/workspace/artifacts/artifact-file-detail.tsx；frontend/src/components/workspace/artifacts/context.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts；frontend/src/core/i18n/locales/zh-CN.ts。

#### 112. feat: add environment variable injection for Docker sandbox

- 提交：`[6e147a7](https://github.com/bytedance/deer-flow/commit/6e147a772e8fc61c341a606b9637c60c1d40ced3)`
- 日期：2026-01-24
- 明确新增内容：新增了“environment variable injection for Docker sandbox”功能。
- 影响范围：主要涉及 后端、前端、技能体系。
- 改动规模：+72 / -18 行。
- 关键文件：.env.example；backend/src/community/aio_sandbox/aio_sandbox_provider.py；backend/src/config/sandbox_config.py；config.example.yaml；frontend/src/core/mcp/api.ts；frontend/src/core/skills/api.ts；skills/public/doraemon-comic-aigc/SKILL.md；skills/public/doraemon-comic-aigc/scripts/generate.py。

#### 113. feat: add environment variable injection for Docker sandbox

- 提交：`[5671642](https://github.com/bytedance/deer-flow/commit/5671642dbe3d5ad343f19ed295f036b8a1fd1293)`
- 日期：2026-01-24
- 明确新增内容：新增了“environment variable injection for Docker sandbox”功能。
- 影响范围：主要涉及 后端、前端、技能体系。
- 改动规模：+72 / -18 行。
- 关键文件：.env.example；backend/src/community/aio_sandbox/aio_sandbox_provider.py；backend/src/config/sandbox_config.py；config.example.yaml；frontend/src/core/mcp/api.ts；frontend/src/core/skills/api.ts；skills/public/doraemon-comic-aigc/SKILL.md；skills/public/doraemon-comic-aigc/scripts/generate.py。

#### 114. feat: add i18n

- 提交：`[869af57](https://github.com/bytedance/deer-flow/commit/869af570c93b0dbcae01fc73c4be8789b1cffcc4)`
- 日期：2026-01-24
- 明确新增内容：新增了“i18n”功能。
- 影响范围：主要涉及 前端。
- 改动规模：+5 / -2 行。
- 关键文件：frontend/src/components/workspace/settings/skill-settings-page.tsx；frontend/src/components/workspace/settings/tool-settings-page.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts；frontend/src/core/i18n/locales/zh-CN.ts。

#### 115. feat: add i18n

- 提交：`[48b5428](https://github.com/bytedance/deer-flow/commit/48b5428000b36414e1c24452cf0b79b4600c04fd)`
- 日期：2026-01-24
- 明确新增内容：新增了“i18n”功能。
- 影响范围：主要涉及 前端。
- 改动规模：+5 / -2 行。
- 关键文件：frontend/src/components/workspace/settings/skill-settings-page.tsx；frontend/src/components/workspace/settings/tool-settings-page.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts；frontend/src/core/i18n/locales/zh-CN.ts。

#### 116. feat: expand by default in demo mode

- 提交：`[5a27a3b](https://github.com/bytedance/deer-flow/commit/5a27a3beeba81876b560c4c6259303d2ab885950)`
- 日期：2026-01-24
- 明确新增内容：引入了“expand by default in demo mode”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+7 / -2 行。
- 关键文件：frontend/src/components/workspace/messages/message-group.tsx。

#### 117. feat: expand by default in demo mode

- 提交：`[56b21e0](https://github.com/bytedance/deer-flow/commit/56b21e00bffbf69ff61f5fabef111ce7c2068e7a)`
- 日期：2026-01-24
- 明确新增内容：引入了“expand by default in demo mode”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+7 / -2 行。
- 关键文件：frontend/src/components/workspace/messages/message-group.tsx。

#### 118. feat: adds docker-based dev environment (#18)

- 提交：`[3808130](https://github.com/bytedance/deer-flow/commit/38081306feec1d231a4211398b826ebf9d4453a0)`
- 日期：2026-01-24
- 明确新增内容：新增了“adds docker-based dev environment”功能。
- 影响范围：主要涉及 其他模块、容器部署、文档。
- 改动规模：+1074 / -285 行。
- 关键文件：.gitignore；CONTRIBUTING.md；Makefile；README.md；backend/Dockerfile；docker/docker-compose-dev.yaml；docker/nginx/nginx.conf；docker/nginx/nginx.local.conf。

#### 119. feat: adds docker-based dev environment (#18)

- 提交：`[400349c](https://github.com/bytedance/deer-flow/commit/400349c3e0e65c47e9cb8e0ac09721a09a2ace42)`
- 日期：2026-01-24
- 明确新增内容：新增了“adds docker-based dev environment”功能。
- 影响范围：主要涉及 其他模块、容器部署、文档。
- 改动规模：+1074 / -285 行。
- 关键文件：.gitignore；CONTRIBUTING.md；Makefile；README.md；backend/Dockerfile；docker/docker-compose-dev.yaml；docker/nginx/nginx.conf；docker/nginx/nginx.local.conf。

#### 120. feat: add Doraemon Skill

- 提交：`[c468381](https://github.com/bytedance/deer-flow/commit/c46838106442cb25c740e03995eaf269ac701e02)`
- 日期：2026-01-24
- 明确新增内容：新增了“Doraemon Skill”功能。
- 影响范围：主要涉及 技能体系。
- 改动规模：+165 / -0 行。
- 关键文件：skills/public/doraemon-comic-aigc/SKILL.md；skills/public/doraemon-comic-aigc/scripts/generate.py。

#### 121. feat: add Doraemon Skill

- 提交：`[ee9950d](https://github.com/bytedance/deer-flow/commit/ee9950d6aa7ac72ab54cd668fda14d30d2e33743)`
- 日期：2026-01-24
- 明确新增内容：新增了“Doraemon Skill”功能。
- 影响范围：主要涉及 技能体系。
- 改动规模：+165 / -0 行。
- 关键文件：skills/public/doraemon-comic-aigc/SKILL.md；skills/public/doraemon-comic-aigc/scripts/generate.py。

#### 122. feat: remove over-scroll

- 提交：`[cae7e67](https://github.com/bytedance/deer-flow/commit/cae7e67a1f36e5c34d728843bd92db527842f8af)`
- 日期：2026-01-24
- 明确新增内容：引入了“remove over-scroll”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+0 / -1 行。
- 关键文件：frontend/src/app/workspace/layout.tsx。

#### 123. feat: remove over-scroll

- 提交：`[291b899](https://github.com/bytedance/deer-flow/commit/291b899486ba127645e0b727f6b2af05170ddb3b)`
- 日期：2026-01-24
- 明确新增内容：引入了“remove over-scroll”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+0 / -1 行。
- 关键文件：frontend/src/app/workspace/layout.tsx。

#### 124. feat: add new demo

- 提交：`[72e0f3d](https://github.com/bytedance/deer-flow/commit/72e0f3d08196787f52e46f26d7301b7e15026c52)`
- 日期：2026-01-24
- 明确新增内容：新增了“new demo”功能。
- 影响范围：主要涉及 前端。
- 改动规模：+1117 / -0 行。
- 关键文件：frontend/public/demo/threads/85ee6ae5-bd68-4359-b17f-9f78c234d63c/thread.json；frontend/public/demo/threads/85ee6ae5-bd68-4359-b17f-9f78c234d63c/user-data/outputs/doraemon-moe.jpg；frontend/public/demo/threads/85ee6ae5-bd68-4359-b17f-9f78c234d63c/user-data/outputs/prompt.json。

#### 125. feat: add new demo

- 提交：`[2c2a177](https://github.com/bytedance/deer-flow/commit/2c2a177186fc3c675e8545206155ba2cc1d43bcc)`
- 日期：2026-01-24
- 明确新增内容：新增了“new demo”功能。
- 影响范围：主要涉及 前端。
- 改动规模：+1117 / -0 行。
- 关键文件：frontend/public/demo/threads/85ee6ae5-bd68-4359-b17f-9f78c234d63c/thread.json；frontend/public/demo/threads/85ee6ae5-bd68-4359-b17f-9f78c234d63c/user-data/outputs/doraemon-moe.jpg；frontend/public/demo/threads/85ee6ae5-bd68-4359-b17f-9f78c234d63c/user-data/outputs/prompt.json。

#### 126. feat: support absolute path as image src

- 提交：`[08f1af0](https://github.com/bytedance/deer-flow/commit/08f1af00b66b1333bf0bbd0eaef30a1adee978c1)`
- 日期：2026-01-24
- 明确新增内容：新增了对“absolute path as image src”的支持能力。
- 影响范围：主要涉及 前端。
- 改动规模：+37 / -1 行。
- 关键文件：frontend/src/components/workspace/messages/message-list-item.tsx；frontend/src/core/artifacts/utils.ts。

#### 127. feat: support absolute path as image src

- 提交：`[4aef821](https://github.com/bytedance/deer-flow/commit/4aef8213441c5f3f214c781d554e19fda56db681)`
- 日期：2026-01-24
- 明确新增内容：新增了对“absolute path as image src”的支持能力。
- 影响范围：主要涉及 前端。
- 改动规模：+37 / -1 行。
- 关键文件：frontend/src/components/workspace/messages/message-list-item.tsx；frontend/src/core/artifacts/utils.ts。

#### 128. chore: add new demo

- 提交：`[6485ed2](https://github.com/bytedance/deer-flow/commit/6485ed2a50254859cdf40412b3c5e282a3bafe6a)`
- 日期：2026-01-24
- 明确新增内容：新增了“new demo”功能。
- 影响范围：主要涉及 前端。
- 改动规模：+5161 / -0 行。
- 关键文件：frontend/public/demo/threads/090898a7-1b1e-4937-ba03-764dbaafa27b/thread.json；frontend/public/demo/threads/090898a7-1b1e-4937-ba03-764dbaafa27b/user-data/outputs/nie-weiping-memorial/index.html；frontend/public/demo/threads/090898a7-1b1e-4937-ba03-764dbaafa27b/user-data/outputs/nie-weiping-memorial/script.js；frontend/public/demo/threads/090898a7-1b1e-4937-ba03-764dbaafa27b/user-data/outputs/nie-weiping-memorial/style.css。

#### 129. chore: add new demo

- 提交：`[cced422](https://github.com/bytedance/deer-flow/commit/cced422e9d404c3dfdc7f85563af82b5d2105712)`
- 日期：2026-01-24
- 明确新增内容：新增了“new demo”功能。
- 影响范围：主要涉及 前端。
- 改动规模：+5161 / -0 行。
- 关键文件：frontend/public/demo/threads/090898a7-1b1e-4937-ba03-764dbaafa27b/thread.json；frontend/public/demo/threads/090898a7-1b1e-4937-ba03-764dbaafa27b/user-data/outputs/nie-weiping-memorial/index.html；frontend/public/demo/threads/090898a7-1b1e-4937-ba03-764dbaafa27b/user-data/outputs/nie-weiping-memorial/script.js；frontend/public/demo/threads/090898a7-1b1e-4937-ba03-764dbaafa27b/user-data/outputs/nie-weiping-memorial/style.css。

#### 130. feat: add new demo

- 提交：`[72e3ba9](https://github.com/bytedance/deer-flow/commit/72e3ba9b79c57e731b27dbd383d94870a4d4221e)`
- 日期：2026-01-24
- 明确新增内容：新增了“new demo”功能。
- 影响范围：主要涉及 前端。
- 改动规模：+5119 / -0 行。
- 关键文件：frontend/public/demo/threads/090898a7-1b1e-4937-ba03-764dbaafa27b/thread.json；frontend/public/demo/threads/090898a7-1b1e-4937-ba03-764dbaafa27b/user-data/outputs/nie-weiping-memorial/index.html；frontend/public/demo/threads/090898a7-1b1e-4937-ba03-764dbaafa27b/user-data/outputs/nie-weiping-memorial/script.js；frontend/public/demo/threads/090898a7-1b1e-4937-ba03-764dbaafa27b/user-data/outputs/nie-weiping-memorial/style.css。

#### 131. feat: add new demo

- 提交：`[373fe0c](https://github.com/bytedance/deer-flow/commit/373fe0cd3c5496a119e5d7895d650f33191f54d9)`
- 日期：2026-01-24
- 明确新增内容：新增了“new demo”功能。
- 影响范围：主要涉及 前端。
- 改动规模：+5119 / -0 行。
- 关键文件：frontend/public/demo/threads/090898a7-1b1e-4937-ba03-764dbaafa27b/thread.json；frontend/public/demo/threads/090898a7-1b1e-4937-ba03-764dbaafa27b/user-data/outputs/nie-weiping-memorial/index.html；frontend/public/demo/threads/090898a7-1b1e-4937-ba03-764dbaafa27b/user-data/outputs/nie-weiping-memorial/script.js；frontend/public/demo/threads/090898a7-1b1e-4937-ba03-764dbaafa27b/user-data/outputs/nie-weiping-memorial/style.css。

#### 132. feat: add uploads

- 提交：`[27df1b5](https://github.com/bytedance/deer-flow/commit/27df1b5f73d830574d1e60e5284c9a9dc4617056)`
- 日期：2026-01-24
- 明确新增内容：新增了“uploads”功能。
- 影响范围：主要涉及 前端。
- 改动规模：+8 / -3 行。
- 关键文件：frontend/scripts/save-demo.js。

#### 133. feat: add uploads

- 提交：`[1f4591a](https://github.com/bytedance/deer-flow/commit/1f4591a4d145212b4781308456adeab406f4f2f1)`
- 日期：2026-01-24
- 明确新增内容：新增了“uploads”功能。
- 影响范围：主要涉及 前端。
- 改动规模：+8 / -3 行。
- 关键文件：frontend/scripts/save-demo.js。

#### 134. chore: add new demo

- 提交：`[a3eb03b](https://github.com/bytedance/deer-flow/commit/a3eb03b1056c5638ed1eb0c9c896a2ba93a14762)`
- 日期：2026-01-24
- 明确新增内容：新增了“new demo”功能。
- 影响范围：主要涉及 前端。
- 改动规模：+537 / -0 行。
- 关键文件：frontend/public/demo/threads/e05bea79-5b98-4e79-bc5f-c624be86ff7f/thread.json。

#### 135. chore: add new demo

- 提交：`[db27ca4](https://github.com/bytedance/deer-flow/commit/db27ca4ae093b59aaef2df2fab28c00ecc313466)`
- 日期：2026-01-24
- 明确新增内容：新增了“new demo”功能。
- 影响范围：主要涉及 前端。
- 改动规模：+537 / -0 行。
- 关键文件：frontend/public/demo/threads/e05bea79-5b98-4e79-bc5f-c624be86ff7f/thread.json。

#### 136. feat: remove background

- 提交：`[930e6bd](https://github.com/bytedance/deer-flow/commit/930e6bd46fb0b0246fab4ccc335826ae263cfd5e)`
- 日期：2026-01-24
- 明确新增内容：引入了“remove background”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -39 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/layout.tsx。

#### 137. feat: remove background

- 提交：`[0f1bfc3](https://github.com/bytedance/deer-flow/commit/0f1bfc3403ef5e4473e412cf73ee9d83d67aa76c)`
- 日期：2026-01-24
- 明确新增内容：引入了“remove background”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -39 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/layout.tsx。

#### 138. feat: update save-demo

- 提交：`[6f24a71](https://github.com/bytedance/deer-flow/commit/6f24a71e1ec7d9c1fa6ea87fdda4ad9a97ea1312)`
- 日期：2026-01-24
- 明确新增内容：引入了“update save-demo”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+7 / -4 行。
- 关键文件：frontend/scripts/save-demo.js。

#### 139. feat: update save-demo

- 提交：`[3ea1dca](https://github.com/bytedance/deer-flow/commit/3ea1dcac111966ac6cc3ad200e7477ad1374aded)`
- 日期：2026-01-24
- 明确新增内容：引入了“update save-demo”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+7 / -4 行。
- 关键文件：frontend/scripts/save-demo.js。

#### 140. feat: add more links

- 提交：`[584c88f](https://github.com/bytedance/deer-flow/commit/584c88f0dd9a69710327926789bd15b5a733de2a)`
- 日期：2026-01-24
- 明确新增内容：新增了“more links”功能。
- 影响范围：主要涉及 前端。
- 改动规模：+22 / -5 行。
- 关键文件：frontend/src/components/workspace/workspace-nav-menu.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts；frontend/src/core/i18n/locales/zh-CN.ts。

#### 141. feat: add more links

- 提交：`[3c40446](https://github.com/bytedance/deer-flow/commit/3c40446ade311fb8e7e13031ae93afc870b7345b)`
- 日期：2026-01-24
- 明确新增内容：新增了“more links”功能。
- 影响范围：主要涉及 前端。
- 改动规模：+22 / -5 行。
- 关键文件：frontend/src/components/workspace/workspace-nav-menu.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts；frontend/src/core/i18n/locales/zh-CN.ts。

#### 142. feat: support static website

- 提交：`[cd63f41](https://github.com/bytedance/deer-flow/commit/cd63f41b4c7aa7c8c8440d3c6242ff9a2cb1655b)`
- 日期：2026-01-24
- 明确新增内容：新增了对“static website”的支持能力。
- 影响范围：主要涉及 前端。
- 改动规模：+5535 / -738 行。
- 关键文件：frontend/package.json；frontend/pnpm-lock.yaml；frontend/public/demo/threads/5aa47db1-d0cb-4eb9-aea5-3dac1b371c5a/thread.json；frontend/public/demo/threads/5aa47db1-d0cb-4eb9-aea5-3dac1b371c5a/user-data/outputs/jiangsu-football/css/style.css；frontend/public/demo/threads/5aa47db1-d0cb-4eb9-aea5-3dac1b371c5a/user-data/outputs/jiangsu-football/favicon.html；frontend/public/demo/threads/5aa47db1-d0cb-4eb9-aea5-3dac1b371c5a/user-data/outputs/jiangsu-football/index.html；frontend/public/demo/threads/5aa47db1-d0cb-4eb9-aea5-3dac1b371c5a/user-data/outputs/jiangsu-football/js/data.js；frontend/public/demo/threads/5aa47db1-d0cb-4eb9-aea5-3dac1b371c5a/user-data/outputs/jiangsu-football/js/main.js。

#### 143. feat: support static website

- 提交：`[ebda30c](https://github.com/bytedance/deer-flow/commit/ebda30c7cf5ba61ba6885e0cab3b017bf7d6710d)`
- 日期：2026-01-24
- 明确新增内容：新增了对“static website”的支持能力。
- 影响范围：主要涉及 前端。
- 改动规模：+5535 / -738 行。
- 关键文件：frontend/package.json；frontend/pnpm-lock.yaml；frontend/public/demo/threads/5aa47db1-d0cb-4eb9-aea5-3dac1b371c5a/thread.json；frontend/public/demo/threads/5aa47db1-d0cb-4eb9-aea5-3dac1b371c5a/user-data/outputs/jiangsu-football/css/style.css；frontend/public/demo/threads/5aa47db1-d0cb-4eb9-aea5-3dac1b371c5a/user-data/outputs/jiangsu-football/favicon.html；frontend/public/demo/threads/5aa47db1-d0cb-4eb9-aea5-3dac1b371c5a/user-data/outputs/jiangsu-football/index.html；frontend/public/demo/threads/5aa47db1-d0cb-4eb9-aea5-3dac1b371c5a/user-data/outputs/jiangsu-football/js/data.js；frontend/public/demo/threads/5aa47db1-d0cb-4eb9-aea5-3dac1b371c5a/user-data/outputs/jiangsu-football/js/main.js。

#### 144. feat: add citation support in research report block and markdown

- 提交：`[b7f0f54](https://github.com/bytedance/deer-flow/commit/b7f0f54aa0243e28563c160ab7eb3ebfbb11a339)`
- 日期：2026-01-24
- 明确新增内容：新增了对“add citation support in research report block and markdown”的支持能力。
- 影响范围：主要涉及 其他模块、配置。
- 改动规模：+2125 / -29 行。
- 关键文件：src/citations/**init**.py；src/citations/collector.py；src/citations/extractor.py；src/citations/formatter.py；src/citations/models.py；src/graph/nodes.py；src/graph/types.py；src/prompts/reporter.md。

#### 145. feat(server): add MCP server configuration validation (#830)

- 提交：`[612bddd](https://github.com/bytedance/deer-flow/commit/612bddd3fb14e8fdb51ac33f6709b707fc8934b4)`
- 日期：2026-01-24
- 明确新增内容：新增了“MCP server configuration validation”功能。
- 影响范围：主要涉及 其他模块。
- 改动规模：+1072 / -19 行。
- 关键文件：src/server/mcp_request.py；src/server/mcp_utils.py；src/server/mcp_validators.py；tests/unit/server/test_app.py；tests/unit/server/test_chat_request.py；tests/unit/server/test_mcp_utils.py；tests/unit/server/test_mcp_validators.py。

#### 146. feat: implement file upload feature

- 提交：`[f6a20a6](https://github.com/bytedance/deer-flow/commit/f6a20a69e34e1802d5fed3319f351fc7c67f9f9a)`
- 日期：2026-01-23
- 明确新增内容：实现了“implement file upload feature”这项新能力。
- 影响范围：主要涉及 后端、前端、其他模块。
- 改动规模：+1880 / -11 行。
- 关键文件：backend/docs/FILE_UPLOAD.md；backend/docs/PATH_EXAMPLES.md；backend/pyproject.toml；backend/src/agents/lead_agent/agent.py；backend/src/agents/lead_agent/prompt.py；backend/src/agents/middlewares/uploads_middleware.py；backend/src/agents/thread_state.py；backend/src/gateway/app.py。

#### 147. feat: implement file upload feature

- 提交：`[1fe37fd](https://github.com/bytedance/deer-flow/commit/1fe37fdb6c112aca5ed5fc7d51fa1f78bb5e14e6)`
- 日期：2026-01-23
- 明确新增内容：实现了“implement file upload feature”这项新能力。
- 影响范围：主要涉及 后端、前端、其他模块。
- 改动规模：+1880 / -11 行。
- 关键文件：backend/docs/FILE_UPLOAD.md；backend/docs/PATH_EXAMPLES.md；backend/pyproject.toml；backend/src/agents/lead_agent/agent.py；backend/src/agents/lead_agent/prompt.py；backend/src/agents/middlewares/uploads_middleware.py；backend/src/agents/thread_state.py；backend/src/gateway/app.py。

#### 148. feat: implement the first version of landing page

- 提交：`[3f4bcd9](https://github.com/bytedance/deer-flow/commit/3f4bcd943396480d786cbcbc9812cf9d5b0ece94)`
- 日期：2026-01-23
- 明确新增内容：实现了“implement the first version of landing page”这项新能力。
- 影响范围：主要涉及 前端。
- 改动规模：+2950 / -615 行。
- 关键文件：frontend/package.json；frontend/pnpm-lock.yaml；frontend/src/app/page.tsx；frontend/src/components/Galaxy.css；frontend/src/components/Galaxy.jsx；frontend/src/components/landing/components/progressive-skills-animation.tsx；frontend/src/components/landing/footer.tsx；frontend/src/components/landing/header.tsx。

#### 149. feat: implement the first version of landing page

- 提交：`[0908127](https://github.com/bytedance/deer-flow/commit/0908127bd774c878ddcea065f786f2c81540fab8)`
- 日期：2026-01-23
- 明确新增内容：实现了“implement the first version of landing page”这项新能力。
- 影响范围：主要涉及 前端。
- 改动规模：+2950 / -615 行。
- 关键文件：frontend/package.json；frontend/pnpm-lock.yaml；frontend/src/app/page.tsx；frontend/src/components/Galaxy.css；frontend/src/components/Galaxy.jsx；frontend/src/components/landing/components/progressive-skills-animation.tsx；frontend/src/components/landing/footer.tsx；frontend/src/components/landing/header.tsx。

#### 150. feat(context): decrease token in web_search AIMessage (#827)

- 提交：`[c0849af](https://github.com/bytedance/deer-flow/commit/c0849af37eef547d2da1224e03d65ed70fa5c171)`
- 日期：2026-01-23
- 明确新增内容：引入了“decrease token in web_search AIMessage”相关功能改进。
- 影响范围：主要涉及 其他模块。
- 改动规模：+124 / -89 行。
- 关键文件：src/tools/crawl.py；src/tools/search.py；src/utils/context_manager.py；tests/unit/tools/test_search.py；tests/unit/utils/test_context_manager.py。

#### 151. feat: implement the first section of landing page

- 提交：`[307972f](https://github.com/bytedance/deer-flow/commit/307972f93ed05d5e8ddd9e1e8b3fbdc662614574)`
- 日期：2026-01-23
- 明确新增内容：实现了“implement the first section of landing page”这项新能力。
- 影响范围：主要涉及 前端。
- 改动规模：+757 / -7 行。
- 关键文件：frontend/components.json；frontend/package.json；frontend/pnpm-lock.yaml；frontend/src/app/layout.tsx；frontend/src/app/page.tsx；frontend/src/components/Galaxy.css；frontend/src/components/Galaxy.jsx；frontend/src/components/landing/jumbotron.tsx。

#### 152. feat: implement the first section of landing page

- 提交：`[b69c13a](https://github.com/bytedance/deer-flow/commit/b69c13a3e5ad4ea87ccc539e8c88592c6db062f8)`
- 日期：2026-01-23
- 明确新增内容：实现了“implement the first section of landing page”这项新能力。
- 影响范围：主要涉及 前端。
- 改动规模：+757 / -7 行。
- 关键文件：frontend/components.json；frontend/package.json；frontend/pnpm-lock.yaml；frontend/src/app/layout.tsx；frontend/src/app/page.tsx；frontend/src/components/Galaxy.css；frontend/src/components/Galaxy.jsx；frontend/src/components/landing/jumbotron.tsx。

#### 153. docs: add notes for v2.0 (#828)

- 提交：`[65cdc18](https://github.com/bytedance/deer-flow/commit/65cdc182d3a4aee84843705183186809f13f2644)`
- 日期：2026-01-22
- 明确新增内容：新增了“add notes for v2.0”相关文档说明，补齐使用/配置指引。
- 影响范围：主要涉及 文档。
- 改动规模：+4 / -1 行。
- 关键文件：README.md。

#### 154. feat: adjust styles

- 提交：`[e9ab427](https://github.com/bytedance/deer-flow/commit/e9ab427326dc62bdb6ac549224ed2a241f14e2ab)`
- 日期：2026-01-22
- 明确新增内容：引入了“adjust styles”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+7 / -1 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/ui/input-group.tsx；frontend/src/components/workspace/input-box.tsx。

#### 155. feat: adjust styles

- 提交：`[dc9d280](https://github.com/bytedance/deer-flow/commit/dc9d28018ce41198d5ad5f1e928a9fa1b2b1e94d)`
- 日期：2026-01-22
- 明确新增内容：引入了“adjust styles”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+7 / -1 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/ui/input-group.tsx；frontend/src/components/workspace/input-box.tsx。

#### 156. docs: rewording

- 提交：`[c48a3f4](https://github.com/bytedance/deer-flow/commit/c48a3f499d0d00f4d7f8f18f6b357f25d56d7b71)`
- 日期：2026-01-22
- 明确新增内容：新增了“rewording”相关文档说明，补齐使用/配置指引。
- 影响范围：主要涉及 前端。
- 改动规模：+2 / -2 行。
- 关键文件：frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/zh-CN.ts。

#### 157. docs: rewording

- 提交：`[9df5629](https://github.com/bytedance/deer-flow/commit/9df56299c16261902e6db392f6cf0d658bbe9e35)`
- 日期：2026-01-22
- 明确新增内容：新增了“rewording”相关文档说明，补齐使用/配置指引。
- 影响范围：主要涉及 前端。
- 改动规模：+2 / -2 行。
- 关键文件：frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/zh-CN.ts。

#### 158. feat: add main menu

- 提交：`[e0f491d](https://github.com/bytedance/deer-flow/commit/e0f491dcdb0ad97827b64a87a75ca627004af01d)`
- 日期：2026-01-22
- 明确新增内容：新增了“main menu”功能。
- 影响范围：主要涉及 前端。
- 改动规模：+232 / -48 行。
- 关键文件：frontend/package.json；frontend/pnpm-lock.yaml；frontend/src/components/ui/avatar.tsx；frontend/src/components/workspace/workspace-nav-chat-list.tsx；frontend/src/components/workspace/workspace-nav-menu.tsx；frontend/src/components/workspace/workspace-sidebar.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts。

#### 159. feat: add main menu

- 提交：`[e137812](https://github.com/bytedance/deer-flow/commit/e1378123f5be00be9c2a9d4af261f9684d78312d)`
- 日期：2026-01-22
- 明确新增内容：新增了“main menu”功能。
- 影响范围：主要涉及 前端。
- 改动规模：+232 / -48 行。
- 关键文件：frontend/package.json；frontend/pnpm-lock.yaml；frontend/src/components/ui/avatar.tsx；frontend/src/components/workspace/workspace-nav-chat-list.tsx；frontend/src/components/workspace/workspace-nav-menu.tsx；frontend/src/components/workspace/workspace-sidebar.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts。

#### 160. feat: update opacities

- 提交：`[80b07bc](https://github.com/bytedance/deer-flow/commit/80b07bcac04bc06532045ba2365f558fd593b456)`
- 日期：2026-01-22
- 明确新增内容：引入了“update opacities”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+2 / -2 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/layout.tsx。

#### 161. feat: update opacities

- 提交：`[cb996f0](https://github.com/bytedance/deer-flow/commit/cb996f0858b7760ca6bc64490c6e31df98448c9a)`
- 日期：2026-01-22
- 明确新增内容：引入了“update opacities”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+2 / -2 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/layout.tsx。

#### 162. feat: make `reasoning` mode as default

- 提交：`[8c99429](https://github.com/bytedance/deer-flow/commit/8c994293a82865e3fb66f87864a0df8fd27ff76e)`
- 日期：2026-01-22
- 明确新增内容：引入了“make `reasoning` mode as default”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -1 行。
- 关键文件：frontend/src/core/settings/local.ts。

#### 163. feat: make `reasoning` mode as default

- 提交：`[99eb247](https://github.com/bytedance/deer-flow/commit/99eb2474b3882ceed82691191cf94965a841894c)`
- 日期：2026-01-22
- 明确新增内容：引入了“make `reasoning` mode as default”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -1 行。
- 关键文件：frontend/src/core/settings/local.ts。

#### 164. docs: update description

- 提交：`[ec4b3a0](https://github.com/bytedance/deer-flow/commit/ec4b3a0ead43a977a1bcedd52782316dff98874f)`
- 日期：2026-01-22
- 明确新增内容：新增了“update description”相关文档说明，补齐使用/配置指引。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -1 行。
- 关键文件：frontend/src/core/i18n/locales/en-US.ts。

#### 165. docs: update description

- 提交：`[b938f40](https://github.com/bytedance/deer-flow/commit/b938f40e4cec88c10c8037595e36b2e74d1a8a33)`
- 日期：2026-01-22
- 明确新增内容：新增了“update description”相关文档说明，补齐使用/配置指引。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -1 行。
- 关键文件：frontend/src/core/i18n/locales/en-US.ts。

#### 166. feat: put all options into '+'

- 提交：`[7d4d706](https://github.com/bytedance/deer-flow/commit/7d4d70673811bebfa07b5e0ed884d2149d1024b1)`
- 日期：2026-01-22
- 明确新增内容：引入了“put all options into '+'”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+197 / -141 行。
- 关键文件：frontend/src/app/layout.tsx；frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/ai-elements/prompt-input.tsx；frontend/src/components/workspace/input-box.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts；frontend/src/core/i18n/locales/zh-CN.ts。

#### 167. feat: put all options into '+'

- 提交：`[8ef89b3](https://github.com/bytedance/deer-flow/commit/8ef89b3004c454021aa7e4db9c4550f27227ac1a)`
- 日期：2026-01-22
- 明确新增内容：引入了“put all options into '+'”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+197 / -141 行。
- 关键文件：frontend/src/app/layout.tsx；frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/ai-elements/prompt-input.tsx；frontend/src/components/workspace/input-box.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts；frontend/src/core/i18n/locales/zh-CN.ts。

#### 168. feat: add unified development environment with nginx proxy

- 提交：`[31bf499](https://github.com/bytedance/deer-flow/commit/31bf49917c63cf5340db0598e1672360079ceac9)`
- 日期：2026-01-22
- 明确新增内容：新增了“unified development environment with nginx proxy”功能。
- 影响范围：主要涉及 其他模块、后端、前端。
- 改动规模：+376 / -69 行。
- 关键文件：.gitignore；Makefile；README.md；backend/CLAUDE.md；backend/Makefile；frontend/.env.example；frontend/src/core/config/index.ts；nginx.conf。

#### 169. feat: add unified development environment with nginx proxy

- 提交：`[2fac726](https://github.com/bytedance/deer-flow/commit/2fac72601eb638e2ed27de4a3cba18b00b51e4b4)`
- 日期：2026-01-22
- 明确新增内容：新增了“unified development environment with nginx proxy”功能。
- 影响范围：主要涉及 其他模块、后端、前端。
- 改动规模：+376 / -69 行。
- 关键文件：.gitignore；Makefile；README.md；backend/CLAUDE.md；backend/Makefile；frontend/.env.example；frontend/src/core/config/index.ts；nginx.conf。

#### 170. feat: show `in-progress`

- 提交：`[16a4991](https://github.com/bytedance/deer-flow/commit/16a499190bcd8b174ea4cb4acee9614038be920f)`
- 日期：2026-01-22
- 明确新增内容：引入了“show `in-progress`”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+12 / -2 行。
- 关键文件：frontend/src/components/workspace/todo-list.tsx。

#### 171. feat: show `in-progress`

- 提交：`[93f7089](https://github.com/bytedance/deer-flow/commit/93f70893fc8aa96675e3af74c5b9f205adeae1ae)`
- 日期：2026-01-22
- 明确新增内容：引入了“show `in-progress`”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+12 / -2 行。
- 关键文件：frontend/src/components/workspace/todo-list.tsx。

#### 172. feat: adjust input background in light mode

- 提交：`[aa7436d](https://github.com/bytedance/deer-flow/commit/aa7436db2fa67f32643fd6fb0b105982e93d73f7)`
- 日期：2026-01-22
- 明确新增内容：引入了“adjust input background in light mode”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -1 行。
- 关键文件：frontend/src/components/ui/input-group.tsx。

#### 173. feat: adjust input background in light mode

- 提交：`[4f71286](https://github.com/bytedance/deer-flow/commit/4f712861a31fa46d8cb00ac1a83b6eaec3ba021b)`
- 日期：2026-01-22
- 明确新增内容：引入了“adjust input background in light mode”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -1 行。
- 关键文件：frontend/src/components/ui/input-group.tsx。

#### 174. feat: adjust styles

- 提交：`[93842e8](https://github.com/bytedance/deer-flow/commit/93842e81a4bfbad6e67833d31b957c900d6bcbed)`
- 日期：2026-01-22
- 明确新增内容：引入了“adjust styles”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+13 / -6 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/workspace/todo-list.tsx。

#### 175. feat: adjust styles

- 提交：`[aed2f7c](https://github.com/bytedance/deer-flow/commit/aed2f7ce67211f5ca0078728753d19694ea30734)`
- 日期：2026-01-22
- 明确新增内容：引入了“adjust styles”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+13 / -6 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/workspace/todo-list.tsx。

#### 176. docs: remove '/'

- 提交：`[5471096](https://github.com/bytedance/deer-flow/commit/54710960cbbf9fcec10684c2215b137fcaaed1a1)`
- 日期：2026-01-22
- 明确新增内容：新增了“remove '/'”相关文档说明，补齐使用/配置指引。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -1 行。
- 关键文件：frontend/src/components/workspace/settings/skill-settings-page.tsx。

#### 177. docs: remove '/'

- 提交：`[3774d04](https://github.com/bytedance/deer-flow/commit/3774d0453c2064aca6e61f6bda33b5ea115c6ecb)`
- 日期：2026-01-22
- 明确新增内容：新增了“remove '/'”相关文档说明，补齐使用/配置指引。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -1 行。
- 关键文件：frontend/src/components/workspace/settings/skill-settings-page.tsx。

#### 178. feat: add animations

- 提交：`[e8e522c](https://github.com/bytedance/deer-flow/commit/e8e522c2fe4fd923913ce1edce2ca3937684030e)`
- 日期：2026-01-22
- 明确新增内容：新增了“animations”功能。
- 影响范围：主要涉及 前端。
- 改动规模：+22 / -23 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/workspace/input-box.tsx；frontend/src/components/workspace/todo-list.tsx。

#### 179. feat: add animations

- 提交：`[9e72dc4](https://github.com/bytedance/deer-flow/commit/9e72dc4f6387d60c26b7da918657632bc1a6bce8)`
- 日期：2026-01-22
- 明确新增内容：新增了“animations”功能。
- 影响范围：主要涉及 前端。
- 改动规模：+22 / -23 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/workspace/input-box.tsx；frontend/src/components/workspace/todo-list.tsx。

#### 180. feat: update skill settings

- 提交：`[37e2c3d](https://github.com/bytedance/deer-flow/commit/37e2c3d3c937cfbf7d980fa35c0d0a5251b2981f)`
- 日期：2026-01-22
- 明确新增内容：引入了“update skill settings”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+75 / -25 行。
- 关键文件：frontend/TODO.md；frontend/src/components/workspace/input-box.tsx；frontend/src/components/workspace/settings/skill-settings-page.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts；frontend/src/core/i18n/locales/zh-CN.ts。

#### 181. feat: update skill settings

- 提交：`[b630e18](https://github.com/bytedance/deer-flow/commit/b630e1846a1bae16dd2ecfed0d75d2e1caa703b6)`
- 日期：2026-01-22
- 明确新增内容：引入了“update skill settings”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+75 / -25 行。
- 关键文件：frontend/TODO.md；frontend/src/components/workspace/input-box.tsx；frontend/src/components/workspace/settings/skill-settings-page.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts；frontend/src/core/i18n/locales/zh-CN.ts。

#### 182. feat: add Todos

- 提交：`[1e4e51a](https://github.com/bytedance/deer-flow/commit/1e4e51a80cfa837a0983092e05cd3af4e37e012d)`
- 日期：2026-01-22
- 明确新增内容：新增了“Todos”功能。
- 影响范围：主要涉及 前端。
- 改动规模：+230 / -70 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/layout.tsx；frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/ai-elements/prompt-input.tsx；frontend/src/components/workspace/artifacts/context.tsx；frontend/src/components/workspace/input-box.tsx；frontend/src/components/workspace/messages/message-group.tsx；frontend/src/components/workspace/messages/message-list.tsx；frontend/src/components/workspace/todo-list.tsx。

#### 183. feat: add Todos

- 提交：`[44850d9](https://github.com/bytedance/deer-flow/commit/44850d9a618f80e65236640ac2dd3b291649a679)`
- 日期：2026-01-22
- 明确新增内容：新增了“Todos”功能。
- 影响范围：主要涉及 前端。
- 改动规模：+230 / -70 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/layout.tsx；frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/ai-elements/prompt-input.tsx；frontend/src/components/workspace/artifacts/context.tsx；frontend/src/components/workspace/input-box.tsx；frontend/src/components/workspace/messages/message-group.tsx；frontend/src/components/workspace/messages/message-list.tsx；frontend/src/components/workspace/todo-list.tsx。

#### 184. feat: add SSE and HTTP transport support for MCP servers

- 提交：`[5a45b9c](https://github.com/bytedance/deer-flow/commit/5a45b9c1311b2a934c281304fc6f36eb0344d9a0)`
- 日期：2026-01-21
- 明确新增内容：新增了对“add SSE and HTTP transport support for MCP servers”的支持能力。
- 影响范围：主要涉及 后端、其他模块、技能体系。
- 改动规模：+99 / -15 行。
- 关键文件：backend/debug.py；backend/src/agents/thread_state.py；backend/src/config/extensions_config.py；backend/src/gateway/routers/mcp.py；backend/src/mcp/client.py；backend/src/tools/tools.py；extensions_config.example.json；skills/public/frontend-design/SKILL.md。

#### 185. feat: add SSE and HTTP transport support for MCP servers

- 提交：`[87752ca](https://github.com/bytedance/deer-flow/commit/87752cafac610b14bf8e7db09ec23aaed381758a)`
- 日期：2026-01-21
- 明确新增内容：新增了对“add SSE and HTTP transport support for MCP servers”的支持能力。
- 影响范围：主要涉及 后端、其他模块、技能体系。
- 改动规模：+99 / -15 行。
- 关键文件：backend/debug.py；backend/src/agents/thread_state.py；backend/src/config/extensions_config.py；backend/src/gateway/routers/mcp.py；backend/src/mcp/client.py；backend/src/tools/tools.py；extensions_config.example.json；skills/public/frontend-design/SKILL.md。

#### 186. feat: use `resolvedTheme` instead of `systemTheme`

- 提交：`[fbe4d27](https://github.com/bytedance/deer-flow/commit/fbe4d27ddd76798975819d4cd57ea030ed42b3a0)`
- 日期：2026-01-21
- 明确新增内容：引入了“use `resolvedTheme` instead of `systemTheme`”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+10 / -12 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/layout.tsx；frontend/src/components/workspace/settings/appearance-settings-page.tsx。

#### 187. feat: use `resolvedTheme` instead of `systemTheme`

- 提交：`[68b8083](https://github.com/bytedance/deer-flow/commit/68b80838260a4a1c4fb6905092de81e95d852ffa)`
- 日期：2026-01-21
- 明确新增内容：引入了“use `resolvedTheme` instead of `systemTheme`”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+10 / -12 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/layout.tsx；frontend/src/components/workspace/settings/appearance-settings-page.tsx。

#### 188. docs: rewording

- 提交：`[54d29e2](https://github.com/bytedance/deer-flow/commit/54d29e254fde96280aeda2d984db9e31391996bf)`
- 日期：2026-01-21
- 明确新增内容：新增了“rewording”相关文档说明，补齐使用/配置指引。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -1 行。
- 关键文件：frontend/src/core/i18n/locales/zh-CN.ts。

#### 189. docs: rewording

- 提交：`[f907f8a](https://github.com/bytedance/deer-flow/commit/f907f8ac16a7be0be813308b19354b8829d6bec8)`
- 日期：2026-01-21
- 明确新增内容：新增了“rewording”相关文档说明，补齐使用/配置指引。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -1 行。
- 关键文件：frontend/src/core/i18n/locales/zh-CN.ts。

#### 190. feat: adjust colors

- 提交：`[e3d5b49](https://github.com/bytedance/deer-flow/commit/e3d5b4960f202289d475af1e84afb6c2b5265149)`
- 日期：2026-01-21
- 明确新增内容：引入了“adjust colors”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+8 / -4 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/layout.tsx。

#### 191. feat: adjust colors

- 提交：`[ce4aa1e](https://github.com/bytedance/deer-flow/commit/ce4aa1e1548622e60746e40e7099e69fd5c1fb70)`
- 日期：2026-01-21
- 明确新增内容：引入了“adjust colors”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+8 / -4 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/layout.tsx。

#### 192. feat: bring back the deer

- 提交：`[26587ee](https://github.com/bytedance/deer-flow/commit/26587ee970053c9ebc3ca0f2337edb5d877f1f73)`
- 日期：2026-01-21
- 明确新增内容：引入了“bring back the deer”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+266 / -11 行。
- 关键文件：frontend/components.json；frontend/public/images/deer.svg；frontend/src/app/workspace/chats/[thread_id]/layout.tsx；frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/ui/flickering-grid.tsx；frontend/src/components/workspace/input-box.tsx。

#### 193. feat: bring back the deer

- 提交：`[1372dbe](https://github.com/bytedance/deer-flow/commit/1372dbefb27ca7ffb084b74f9fc88df74f9956e9)`
- 日期：2026-01-21
- 明确新增内容：引入了“bring back the deer”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+266 / -11 行。
- 关键文件：frontend/components.json；frontend/public/images/deer.svg；frontend/src/app/workspace/chats/[thread_id]/layout.tsx；frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/ui/flickering-grid.tsx；frontend/src/components/workspace/input-box.tsx。

#### 194. feat: auto open artifact

- 提交：`[220fc1c](https://github.com/bytedance/deer-flow/commit/220fc1c48956b7e6a206f27bf33e5a38e2351368)`
- 日期：2026-01-21
- 明确新增内容：引入了“auto open artifact”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+22 / -2 行。
- 关键文件：frontend/src/components/workspace/artifacts/context.tsx；frontend/src/components/workspace/messages/message-group.tsx。

#### 195. feat: auto open artifact

- 提交：`[4467b18](https://github.com/bytedance/deer-flow/commit/4467b1860f8ece2b4eebd7ad34a9634d2f21e617)`
- 日期：2026-01-21
- 明确新增内容：引入了“auto open artifact”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+22 / -2 行。
- 关键文件：frontend/src/components/workspace/artifacts/context.tsx；frontend/src/components/workspace/messages/message-group.tsx。

#### 196. feat: add code editor

- 提交：`[48742d1](https://github.com/bytedance/deer-flow/commit/48742d1b59f5e7164a3f1ff82e931d764937b725)`
- 日期：2026-01-21
- 明确新增内容：新增了“code editor”功能。
- 影响范围：主要涉及 前端。
- 改动规模：+759 / -3 行。
- 关键文件：frontend/package.json；frontend/pnpm-lock.yaml；frontend/src/components/ai-elements/code-editor.tsx；frontend/src/components/workspace/artifacts/artifact-file-detail.tsx。

#### 197. feat: add code editor

- 提交：`[6e024d6](https://github.com/bytedance/deer-flow/commit/6e024d6c8f716be47d79172e13f495f623087201)`
- 日期：2026-01-21
- 明确新增内容：新增了“code editor”功能。
- 影响范围：主要涉及 前端。
- 改动规模：+759 / -3 行。
- 关键文件：frontend/package.json；frontend/pnpm-lock.yaml；frontend/src/components/ai-elements/code-editor.tsx；frontend/src/components/workspace/artifacts/artifact-file-detail.tsx。

#### 198. feat: enlarge shadow

- 提交：`[7c6eb4c](https://github.com/bytedance/deer-flow/commit/7c6eb4cc8b39dc27a062b3771a502f9df27fef37)`
- 日期：2026-01-21
- 明确新增内容：引入了“enlarge shadow”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -1 行。
- 关键文件：frontend/src/components/ai-elements/artifact.tsx。

#### 199. feat: enlarge shadow

- 提交：`[4b7ee2b](https://github.com/bytedance/deer-flow/commit/4b7ee2bee2e8799a77f8f2f6f6abe5eb634b5fad)`
- 日期：2026-01-21
- 明确新增内容：引入了“enlarge shadow”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -1 行。
- 关键文件：frontend/src/components/ai-elements/artifact.tsx。

#### 200. feat: make artifact "floating"

- 提交：`[d77b992](https://github.com/bytedance/deer-flow/commit/d77b9922a608ff5b554415e3b8f0af42b04b595c)`
- 日期：2026-01-21
- 明确新增内容：引入了“make artifact "floating"”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+5 / -4 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/workspace/artifacts/artifact-file-detail.tsx。

#### 201. feat: make artifact "floating"

- 提交：`[28d724d](https://github.com/bytedance/deer-flow/commit/28d724d55ac75a7b45546608734f5369af877c6c)`
- 日期：2026-01-21
- 明确新增内容：引入了“make artifact "floating"”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+5 / -4 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/workspace/artifacts/artifact-file-detail.tsx。

#### 202. feat: change color themes

- 提交：`[a2ca682](https://github.com/bytedance/deer-flow/commit/a2ca682b0c77b2440301071f01629f8c40d07370)`
- 日期：2026-01-21
- 明确新增内容：引入了“change color themes”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -1 行。
- 关键文件：frontend/src/components/workspace/settings/settings-dialog.tsx。

#### 203. feat: change color themes

- 提交：`[adfce3c](https://github.com/bytedance/deer-flow/commit/adfce3c79c452cdba249dc09908c962f6cfa3e61)`
- 日期：2026-01-21
- 明确新增内容：引入了“change color themes”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -1 行。
- 关键文件：frontend/src/components/workspace/settings/settings-dialog.tsx。

#### 204. feat: support settings

- 提交：`[10d253f](https://github.com/bytedance/deer-flow/commit/10d253f46105ee4026cedbba97c2431540fc6a4f)`
- 日期：2026-01-20
- 明确新增内容：新增了对“settings”的支持能力。
- 影响范围：主要涉及 前端。
- 改动规模：+1355 / -217 行。
- 关键文件：frontend/package.json；frontend/pnpm-lock.yaml；frontend/src/components/ui/empty.tsx；frontend/src/components/ui/item.tsx；frontend/src/components/ui/switch.tsx；frontend/src/components/workspace/settings/acknowledge-page.tsx；frontend/src/components/workspace/settings/appearance-settings-page.tsx；frontend/src/components/workspace/settings/index.ts。

#### 205. feat: support settings

- 提交：`[1b70e00](https://github.com/bytedance/deer-flow/commit/1b70e0064209818612ff60bc67be733a3e4a7f0e)`
- 日期：2026-01-20
- 明确新增内容：新增了对“settings”的支持能力。
- 影响范围：主要涉及 前端。
- 改动规模：+1355 / -217 行。
- 关键文件：frontend/package.json；frontend/pnpm-lock.yaml；frontend/src/components/ui/empty.tsx；frontend/src/components/ui/item.tsx；frontend/src/components/ui/switch.tsx；frontend/src/components/workspace/settings/acknowledge-page.tsx；frontend/src/components/workspace/settings/appearance-settings-page.tsx；frontend/src/components/workspace/settings/index.ts。

#### 206. feat: integrate todo middleware

- 提交：`[3191a38](https://github.com/bytedance/deer-flow/commit/3191a3845f21fbef0cadac807ef21d1fe7fe212c)`
- 日期：2026-01-20
- 明确新增内容：引入了“integrate todo middleware”相关功能改进。
- 影响范围：主要涉及 后端。
- 改动规模：+339 / -4 行。
- 关键文件：backend/docs/plan_mode_usage.md；backend/src/agents/lead_agent/agent.py。

#### 207. feat: integrate todo middleware

- 提交：`[7ead7c9](https://github.com/bytedance/deer-flow/commit/7ead7c93f8cfd90b6c2b77f77ee8b87ae477157e)`
- 日期：2026-01-20
- 明确新增内容：引入了“integrate todo middleware”相关功能改进。
- 影响范围：主要涉及 后端。
- 改动规模：+339 / -4 行。
- 关键文件：backend/docs/plan_mode_usage.md；backend/src/agents/lead_agent/agent.py。

#### 208. feat: enable public skills by default

- 提交：`[abc6c21](https://github.com/bytedance/deer-flow/commit/abc6c21b11bb49f709707def024226dbe90df0ec)`
- 日期：2026-01-20
- 明确新增内容：引入了“enable public skills by default”相关功能改进。
- 影响范围：主要涉及 后端、其他模块。
- 改动规模：+15 / -5 行。
- 关键文件：.gitignore；backend/Makefile；backend/src/config/extensions_config.py；backend/src/skills/loader.py。

#### 209. feat: enable public skills by default

- 提交：`[2d93110](https://github.com/bytedance/deer-flow/commit/2d931105d5bd1bc8161d6b164ec970b82690828d)`
- 日期：2026-01-20
- 明确新增内容：引入了“enable public skills by default”相关功能改进。
- 影响范围：主要涉及 后端、其他模块。
- 改动规模：+15 / -5 行。
- 关键文件：.gitignore；backend/Makefile；backend/src/config/extensions_config.py；backend/src/skills/loader.py。

#### 210. feat: save locale in cookies

- 提交：`[faba278](https://github.com/bytedance/deer-flow/commit/faba2784e1683ada212d5fda3088d1cf3018f888)`
- 日期：2026-01-20
- 明确新增内容：引入了“save locale in cookies”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+131 / -38 行。
- 关键文件：frontend/src/app/layout.tsx；frontend/src/components/workspace/workspace-sidebar.tsx；frontend/src/core/i18n/context.tsx；frontend/src/core/i18n/cookies.ts；frontend/src/core/i18n/hooks.ts；frontend/src/core/i18n/index.ts；frontend/src/core/i18n/server.ts。

#### 211. feat: save locale in cookies

- 提交：`[dc8c1f4](https://github.com/bytedance/deer-flow/commit/dc8c1f4ed69e715485c1677630556c443663530f)`
- 日期：2026-01-20
- 明确新增内容：引入了“save locale in cookies”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+131 / -38 行。
- 关键文件：frontend/src/app/layout.tsx；frontend/src/components/workspace/workspace-sidebar.tsx；frontend/src/core/i18n/context.tsx；frontend/src/core/i18n/cookies.ts；frontend/src/core/i18n/hooks.ts；frontend/src/core/i18n/index.ts；frontend/src/core/i18n/server.ts。

#### 212. feat: implement i18n

- 提交：`[32a45eb](https://github.com/bytedance/deer-flow/commit/32a45eb043e2f0023d2b18bf21a448e4a363dbe4)`
- 日期：2026-01-20
- 明确新增内容：实现了“implement i18n”这项新能力。
- 影响范围：主要涉及 前端。
- 改动规模：+455 / -69 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/app/workspace/chats/page.tsx；frontend/src/components/workspace/artifacts/artifact-file-detail.tsx；frontend/src/components/workspace/artifacts/artifact-file-list.tsx；frontend/src/components/workspace/copy-button.tsx；frontend/src/components/workspace/input-box.tsx；frontend/src/components/workspace/messages/message-group.tsx；frontend/src/components/workspace/recent-chat-list.tsx。

#### 213. feat: implement i18n

- 提交：`[ac9ef30](https://github.com/bytedance/deer-flow/commit/ac9ef30780fb6819c40b231938d9f024ad2ffa32)`
- 日期：2026-01-20
- 明确新增内容：实现了“implement i18n”这项新能力。
- 影响范围：主要涉及 前端。
- 改动规模：+455 / -69 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/app/workspace/chats/page.tsx；frontend/src/components/workspace/artifacts/artifact-file-detail.tsx；frontend/src/components/workspace/artifacts/artifact-file-list.tsx；frontend/src/components/workspace/copy-button.tsx；frontend/src/components/workspace/input-box.tsx；frontend/src/components/workspace/messages/message-group.tsx；frontend/src/components/workspace/recent-chat-list.tsx。

#### 214. feat: add skills api

- 提交：`[50810c8](https://github.com/bytedance/deer-flow/commit/50810c8212e122e3f5822ca23777e11747c3fa9d)`
- 日期：2026-01-20
- 明确新增内容：新增了“skills api”功能。
- 影响范围：主要涉及 后端、其他模块、技能体系。
- 改动规模：+586 / -543 行。
- 关键文件：.gitignore；MCP_SETUP.md；backend/CLAUDE.md；backend/src/agents/lead_agent/prompt.py；backend/src/config/**init**.py；backend/src/config/app_config.py；backend/src/config/extensions_config.py；backend/src/config/mcp_config.py。

#### 215. feat: add skills api

- 提交：`[66df9b5](https://github.com/bytedance/deer-flow/commit/66df9b592771d40c908188a410df46bb6f6de814)`
- 日期：2026-01-20
- 明确新增内容：新增了“skills api”功能。
- 影响范围：主要涉及 后端、其他模块、技能体系。
- 改动规模：+586 / -543 行。
- 关键文件：.gitignore；MCP_SETUP.md；backend/CLAUDE.md；backend/src/agents/lead_agent/prompt.py；backend/src/config/**init**.py；backend/src/config/app_config.py；backend/src/config/extensions_config.py；backend/src/config/mcp_config.py。

#### 216. feat: add MCP API endpoint and enhance API documentation

- 提交：`[8434cf4](https://github.com/bytedance/deer-flow/commit/8434cf4c605653d8149b766cd66d31952550af98)`
- 日期：2026-01-20
- 明确新增内容：新增了“MCP API endpoint and enhance API documentation”功能。
- 影响范围：主要涉及 后端、其他模块。
- 改动规模：+307 / -11 行。
- 关键文件：backend/src/gateway/app.py；backend/src/gateway/routers/**init**.py；backend/src/gateway/routers/artifacts.py；backend/src/gateway/routers/mcp.py；backend/src/gateway/routers/models.py；nginx.conf。

#### 217. feat: add MCP API endpoint and enhance API documentation

- 提交：`[411d9d5](https://github.com/bytedance/deer-flow/commit/411d9d57c3024e4625b9fd89b3a210af5ed5807a)`
- 日期：2026-01-20
- 明确新增内容：新增了“MCP API endpoint and enhance API documentation”功能。
- 影响范围：主要涉及 后端、其他模块。
- 改动规模：+307 / -11 行。
- 关键文件：backend/src/gateway/app.py；backend/src/gateway/routers/**init**.py；backend/src/gateway/routers/artifacts.py；backend/src/gateway/routers/mcp.py；backend/src/gateway/routers/models.py；nginx.conf。

#### 218. docs: rewording

- 提交：`[a18f377](https://github.com/bytedance/deer-flow/commit/a18f37779e6f2e1c4c71f63021730f3820b7ff48)`
- 日期：2026-01-20
- 明确新增内容：新增了“rewording”相关文档说明，补齐使用/配置指引。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -1 行。
- 关键文件：frontend/src/components/workspace/recent-chat-list.tsx。

#### 219. docs: rewording

- 提交：`[b791b28](https://github.com/bytedance/deer-flow/commit/b791b28afafa115b948f5f14bc4bc632b634e90b)`
- 日期：2026-01-20
- 明确新增内容：新增了“rewording”相关文档说明，补齐使用/配置指引。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -1 行。
- 关键文件：frontend/src/components/workspace/recent-chat-list.tsx。

#### 220. feat: add nginx reversed proxy (#15)

- 提交：`[513332b](https://github.com/bytedance/deer-flow/commit/513332b746bb1b356e947c6bcda6eb4803a084a8)`
- 日期：2026-01-19
- 明确新增内容：新增了“nginx reversed proxy”功能。
- 影响范围：主要涉及 后端、文档、其他模块。
- 改动规模：+177 / -202 行。
- 关键文件：README.md；backend/Makefile；backend/src/gateway/app.py；backend/src/gateway/config.py；backend/src/gateway/routers/proxy.py；nginx.conf。

#### 221. feat: add nginx reversed proxy (#15)

- 提交：`[7978e05](https://github.com/bytedance/deer-flow/commit/7978e05dc1709ba28a82740799efc145b5925a9d)`
- 日期：2026-01-19
- 明确新增内容：新增了“nginx reversed proxy”功能。
- 影响范围：主要涉及 后端、文档、其他模块。
- 改动规模：+177 / -202 行。
- 关键文件：README.md；backend/Makefile；backend/src/gateway/app.py；backend/src/gateway/config.py；backend/src/gateway/routers/proxy.py；nginx.conf。

#### 222. feat: use code block to display bash commands

- 提交：`[b8f9678](https://github.com/bytedance/deer-flow/commit/b8f9678d074fb382d308aa257a446f339dfaff8b)`
- 日期：2026-01-19
- 明确新增内容：引入了“use code block to display bash commands”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+9 / -3 行。
- 关键文件：frontend/src/components/ai-elements/code-block.tsx；frontend/src/components/workspace/messages/message-group.tsx。

#### 223. feat: use code block to display bash commands

- 提交：`[5d6162d](https://github.com/bytedance/deer-flow/commit/5d6162d0061a9db93bea4a1e93753f23a6b822c8)`
- 日期：2026-01-19
- 明确新增内容：引入了“use code block to display bash commands”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+9 / -3 行。
- 关键文件：frontend/src/components/ai-elements/code-block.tsx；frontend/src/components/workspace/messages/message-group.tsx。

#### 224. feat: support NEXT_PUBLIC_LANGGRAPH_BASE_URL

- 提交：`[fb265f2](https://github.com/bytedance/deer-flow/commit/fb265f2b1f970122883e538d0967a844462d336c)`
- 日期：2026-01-19
- 明确新增内容：新增了对“NEXT_PUBLIC_LANGGRAPH_BASE_URL”的支持能力。
- 影响范围：主要涉及 前端。
- 改动规模：+12 / -2 行。
- 关键文件：frontend/src/core/api/api-client.ts；frontend/src/core/config/index.ts；frontend/src/env.js。

#### 225. feat: support NEXT_PUBLIC_LANGGRAPH_BASE_URL

- 提交：`[58b5c2f](https://github.com/bytedance/deer-flow/commit/58b5c2fcd553ab58f717d0abc8e605519b172172)`
- 日期：2026-01-19
- 明确新增内容：新增了对“NEXT_PUBLIC_LANGGRAPH_BASE_URL”的支持能力。
- 影响范围：主要涉及 前端。
- 改动规模：+12 / -2 行。
- 关键文件：frontend/src/core/api/api-client.ts；frontend/src/core/config/index.ts；frontend/src/env.js。

#### 226. feat: add ToggleGroup

- 提交：`[d7dfffa](https://github.com/bytedance/deer-flow/commit/d7dfffad9044609900af7beb0fc2dd4bb6750a8d)`
- 日期：2026-01-19
- 明确新增内容：新增了“ToggleGroup”功能。
- 影响范围：主要涉及 前端。
- 改动规模：+316 / -103 行。
- 关键文件：frontend/package.json；frontend/pnpm-lock.yaml；frontend/src/components/ui/toggle-group.tsx；frontend/src/components/ui/toggle.tsx；frontend/src/components/workspace/artifacts/artifact-file-detail.tsx；frontend/src/components/workspace/artifacts/file-viewer.tsx；frontend/src/core/artifacts/hooks.ts；frontend/src/core/artifacts/loader.ts。

#### 227. feat: add ToggleGroup

- 提交：`[24ca87d](https://github.com/bytedance/deer-flow/commit/24ca87d650073890a8a1b5759587e79b1dd9b913)`
- 日期：2026-01-19
- 明确新增内容：新增了“ToggleGroup”功能。
- 影响范围：主要涉及 前端。
- 改动规模：+316 / -103 行。
- 关键文件：frontend/package.json；frontend/pnpm-lock.yaml；frontend/src/components/ui/toggle-group.tsx；frontend/src/components/ui/toggle.tsx；frontend/src/components/workspace/artifacts/artifact-file-detail.tsx；frontend/src/components/workspace/artifacts/file-viewer.tsx；frontend/src/core/artifacts/hooks.ts；frontend/src/core/artifacts/loader.ts。

#### 228. feat: add MCP (Model Context Protocol) support

- 提交：`[1171598](https://github.com/bytedance/deer-flow/commit/1171598b2f93a467d834dcebe1529c951c4c486a)`
- 日期：2026-01-19
- 明确新增内容：新增了对“add MCP (Model Context Protocol) support”的支持能力。
- 影响范围：主要涉及 后端、其他模块、文档。
- 改动规模：+1044 / -5 行。
- 关键文件：.gitignore；MCP_SETUP.md；README.md；backend/CLAUDE.md；backend/debug.py；backend/pyproject.toml；backend/src/agents/middlewares/clarification_middleware.py；backend/src/config/**init**.py。

#### 229. feat: add MCP (Model Context Protocol) support

- 提交：`[74d4a16](https://github.com/bytedance/deer-flow/commit/74d4a16492a6523f2b6eb47d2a98898f7b398e3e)`
- 日期：2026-01-19
- 明确新增内容：新增了对“add MCP (Model Context Protocol) support”的支持能力。
- 影响范围：主要涉及 后端、其他模块、文档。
- 改动规模：+1044 / -5 行。
- 关键文件：.gitignore；MCP_SETUP.md；README.md；backend/CLAUDE.md；backend/debug.py；backend/pyproject.toml；backend/src/agents/middlewares/clarification_middleware.py；backend/src/config/**init**.py。

#### 230. feat: support dynamic loading models

- 提交：`[541586d](https://github.com/bytedance/deer-flow/commit/541586dc66041a518f1af469bd4e28ffd7113f0f)`
- 日期：2026-01-19
- 明确新增内容：新增了对“dynamic loading models”的支持能力。
- 影响范围：主要涉及 前端。
- 改动规模：+49 / -23 行。
- 关键文件：frontend/src/components/workspace/input-box.tsx；frontend/src/core/models/api.ts；frontend/src/core/models/hooks.ts；frontend/src/core/models/index.ts；frontend/src/core/models/types.ts。

#### 231. feat: support dynamic loading models

- 提交：`[21f35b1](https://github.com/bytedance/deer-flow/commit/21f35b1d3c4dd227a65a728f6fcb1b072b7adf96)`
- 日期：2026-01-19
- 明确新增内容：新增了对“dynamic loading models”的支持能力。
- 影响范围：主要涉及 前端。
- 改动规模：+49 / -23 行。
- 关键文件：frontend/src/components/workspace/input-box.tsx；frontend/src/core/models/api.ts；frontend/src/core/models/hooks.ts；frontend/src/core/models/index.ts；frontend/src/core/models/types.ts。

#### 232. feat: implement summarization (#14)

- 提交：`[9a3eaea](https://github.com/bytedance/deer-flow/commit/9a3eaea54ef5e0d7c0c0b56e417b13a8ee5f7d89)`
- 日期：2026-01-19
- 明确新增内容：实现了“implement summarization”这项新能力。
- 影响范围：主要涉及 后端、配置。
- 改动规模：+555 / -5 行。
- 关键文件：backend/CLAUDE.md；backend/docs/TODO.md；backend/docs/summarization.md；backend/src/agents/lead_agent/agent.py；backend/src/agents/lead_agent/prompt.py；backend/src/config/app_config.py；backend/src/config/summarization_config.py；config.example.yaml。

#### 233. feat: implement summarization (#14)

- 提交：`[f0a2381](https://github.com/bytedance/deer-flow/commit/f0a2381bd5f42972362ffe3f32349b6b78ef229b)`
- 日期：2026-01-19
- 明确新增内容：实现了“implement summarization”这项新能力。
- 影响范围：主要涉及 后端、配置。
- 改动规模：+555 / -5 行。
- 关键文件：backend/CLAUDE.md；backend/docs/TODO.md；backend/docs/summarization.md；backend/src/agents/lead_agent/agent.py；backend/src/agents/lead_agent/prompt.py；backend/src/config/app_config.py；backend/src/config/summarization_config.py；config.example.yaml。

#### 234. feat: add NEXT_PUBLIC_BACKEND_BASE_URL

- 提交：`[f3f66ee](https://github.com/bytedance/deer-flow/commit/f3f66ee9248e832cc9e76fa12e70113731ca33f5)`
- 日期：2026-01-19
- 明确新增内容：新增了“NEXT_PUBLIC_BACKEND_BASE_URL”功能。
- 影响范围：主要涉及 前端。
- 改动规模：+19 / -10 行。
- 关键文件：frontend/.env.example；frontend/src/core/api/api-client.ts；frontend/src/core/artifacts/utils.ts；frontend/src/core/config/index.ts；frontend/src/env.js。

#### 235. feat: add NEXT_PUBLIC_BACKEND_BASE_URL

- 提交：`[9d18e4e](https://github.com/bytedance/deer-flow/commit/9d18e4e12dd1c3762dfc3c0a28fd203b026892ed)`
- 日期：2026-01-19
- 明确新增内容：新增了“NEXT_PUBLIC_BACKEND_BASE_URL”功能。
- 影响范围：主要涉及 前端。
- 改动规模：+19 / -10 行。
- 关键文件：frontend/.env.example；frontend/src/core/api/api-client.ts；frontend/src/core/artifacts/utils.ts；frontend/src/core/config/index.ts；frontend/src/env.js。

#### 236. feat: make `new chat` always on top

- 提交：`[d8391ca](https://github.com/bytedance/deer-flow/commit/d8391ca3ea0534698a3eec5c7e412f1e69edfaae)`
- 日期：2026-01-19
- 明确新增内容：引入了“make `new chat` always on top”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+48 / -35 行。
- 关键文件：frontend/src/components/workspace/workspace-header.tsx；frontend/src/components/workspace/workspace-nav-menu.tsx。

#### 237. feat: make `new chat` always on top

- 提交：`[b431567](https://github.com/bytedance/deer-flow/commit/b4315676667b4ccbb81c06bd2e52e0fe7540aa43)`
- 日期：2026-01-19
- 明确新增内容：引入了“make `new chat` always on top”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+48 / -35 行。
- 关键文件：frontend/src/components/workspace/workspace-header.tsx；frontend/src/components/workspace/workspace-nav-menu.tsx。

#### 238. feat: support clarification tool

- 提交：`[dc04042](https://github.com/bytedance/deer-flow/commit/dc04042b53aa104ffb990f6a03a00ba6cc45ac56)`
- 日期：2026-01-18
- 明确新增内容：新增了对“clarification tool”的支持能力。
- 影响范围：主要涉及 前端。
- 改动规模：+11 / -1 行。
- 关键文件：frontend/src/components/workspace/messages/message-group.tsx。

#### 239. feat: support clarification tool

- 提交：`[5624b0c](https://github.com/bytedance/deer-flow/commit/5624b0cd382f391696f3534caba24a1030a29c10)`
- 日期：2026-01-18
- 明确新增内容：新增了对“clarification tool”的支持能力。
- 影响范围：主要涉及 前端。
- 改动规模：+11 / -1 行。
- 关键文件：frontend/src/components/workspace/messages/message-group.tsx。

#### 240. feat: re-implement message group

- 提交：`[69b2250](https://github.com/bytedance/deer-flow/commit/69b225082b9c1490a826bd973df83f0aa7f383a6)`
- 日期：2026-01-18
- 明确新增内容：实现了“re-implement message group”这项新能力。
- 影响范围：主要涉及 前端。
- 改动规模：+131 / -105 行。
- 关键文件：frontend/src/components/ai-elements/chain-of-thought.tsx；frontend/src/components/ai-elements/code-block.tsx；frontend/src/components/workspace/flip-display.tsx；frontend/src/components/workspace/messages/message-group.tsx。

#### 241. feat: re-implement message group

- 提交：`[aa44566](https://github.com/bytedance/deer-flow/commit/aa44566fefa5c267cec5c0c00a9daf6915211ee1)`
- 日期：2026-01-18
- 明确新增内容：实现了“re-implement message group”这项新能力。
- 影响范围：主要涉及 前端。
- 改动规模：+131 / -105 行。
- 关键文件：frontend/src/components/ai-elements/chain-of-thought.tsx；frontend/src/components/ai-elements/code-block.tsx；frontend/src/components/workspace/flip-display.tsx；frontend/src/components/workspace/messages/message-group.tsx。

#### 242. feat: add clarification feature (#13)

- 提交：`[645923c](https://github.com/bytedance/deer-flow/commit/645923c3bcd01cbccd2e05ac70c1b862ec65f349)`
- 日期：2026-01-18
- 明确新增内容：新增了“clarification feature”功能。
- 影响范围：主要涉及 后端。
- 改动规模：+416 / -9 行。
- 关键文件：backend/src/agents/lead_agent/agent.py；backend/src/agents/lead_agent/prompt.py；backend/src/agents/middlewares/clarification_middleware.py；backend/src/gateway/app.py；backend/src/sandbox/local/local_sandbox.py；backend/src/tools/builtins/**init**.py；backend/src/tools/builtins/clarification_tool.py；backend/src/tools/tools.py。

#### 243. feat: add clarification feature (#13)

- 提交：`[e1a8d54](https://github.com/bytedance/deer-flow/commit/e1a8d544b630430fbab852efb4f9ade63fc4af6f)`
- 日期：2026-01-18
- 明确新增内容：新增了“clarification feature”功能。
- 影响范围：主要涉及 后端。
- 改动规模：+416 / -9 行。
- 关键文件：backend/src/agents/lead_agent/agent.py；backend/src/agents/lead_agent/prompt.py；backend/src/agents/middlewares/clarification_middleware.py；backend/src/gateway/app.py；backend/src/sandbox/local/local_sandbox.py；backend/src/tools/builtins/**init**.py；backend/src/tools/builtins/clarification_tool.py；backend/src/tools/tools.py。

#### 244. feat: support SSE write_file(0

- 提交：`[dd80348](https://github.com/bytedance/deer-flow/commit/dd80348b7640193ac87eb5b26757db52f4797239)`
- 日期：2026-01-18
- 明确新增内容：新增了对“SSE write_file(0”的支持能力。
- 影响范围：主要涉及 前端。
- 改动规模：+293 / -178 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/app/workspace/layout.tsx；frontend/src/components/ai-elements/artifact.tsx；frontend/src/components/ai-elements/code-block.tsx；frontend/src/components/workspace/artifacts/artifact-file-detail.tsx；frontend/src/components/workspace/artifacts/file-viewer.tsx；frontend/src/components/workspace/messages/context.ts；frontend/src/components/workspace/messages/message-group.tsx。

#### 245. feat: support SSE write_file(0

- 提交：`[ec1964c](https://github.com/bytedance/deer-flow/commit/ec1964c82912d6e8166c0799910761fe78094eda)`
- 日期：2026-01-18
- 明确新增内容：新增了对“SSE write_file(0”的支持能力。
- 影响范围：主要涉及 前端。
- 改动规模：+293 / -178 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/app/workspace/layout.tsx；frontend/src/components/ai-elements/artifact.tsx；frontend/src/components/ai-elements/code-block.tsx；frontend/src/components/workspace/artifacts/artifact-file-detail.tsx；frontend/src/components/workspace/artifacts/file-viewer.tsx；frontend/src/components/workspace/messages/context.ts；frontend/src/components/workspace/messages/message-group.tsx。

#### 246. feat: implement lazy sandbox and thread data initialization (#11)

- 提交：`[1397f30](https://github.com/bytedance/deer-flow/commit/1397f30f2499d136bbbd9e9d5c597b2dad8912f5)`
- 日期：2026-01-18
- 明确新增内容：实现了“implement lazy sandbox and thread data initialization”这项新能力。
- 影响范围：主要涉及 后端。
- 改动规模：+104 / -13 行。
- 关键文件：backend/src/agents/middlewares/thread_data_middleware.py；backend/src/community/aio_sandbox/aio_sandbox_provider.py；backend/src/sandbox/middleware.py；backend/src/sandbox/tools.py。

#### 247. feat: implement lazy sandbox and thread data initialization (#11)

- 提交：`[5f4c58a](https://github.com/bytedance/deer-flow/commit/5f4c58aa8231aaf55cd32f141058f2670bb7bb13)`
- 日期：2026-01-18
- 明确新增内容：实现了“implement lazy sandbox and thread data initialization”这项新能力。
- 影响范围：主要涉及 后端。
- 改动规模：+104 / -13 行。
- 关键文件：backend/src/agents/middlewares/thread_data_middleware.py；backend/src/community/aio_sandbox/aio_sandbox_provider.py；backend/src/sandbox/middleware.py；backend/src/sandbox/tools.py。

#### 248. feat: add recursion_limit

- 提交：`[8f0bd82](https://github.com/bytedance/deer-flow/commit/8f0bd828d5cc99d692e23de8d9441a74c65e362e)`
- 日期：2026-01-18
- 明确新增内容：新增了“recursion_limit”功能。
- 影响范围：主要涉及 前端。
- 改动规模：+3 / -0 行。
- 关键文件：frontend/src/core/threads/hooks.ts。

#### 249. feat: add recursion_limit

- 提交：`[41a22fd](https://github.com/bytedance/deer-flow/commit/41a22fde9107c1ec263ebf48a95ccbcde15ca4ea)`
- 日期：2026-01-18
- 明确新增内容：新增了“recursion_limit”功能。
- 影响范围：主要涉及 前端。
- 改动规模：+3 / -0 行。
- 关键文件：frontend/src/core/threads/hooks.ts。

#### 250. feat: enhance message display

- 提交：`[23dc64f](https://github.com/bytedance/deer-flow/commit/23dc64fab12c1b632c1608f684b013b88864d06e)`
- 日期：2026-01-18
- 明确新增内容：增强了“enhance message display”相关能力与交互体验。
- 影响范围：主要涉及 前端。
- 改动规模：+115 / -66 行。
- 关键文件：frontend/src/components/workspace/messages/message-list-item.tsx；frontend/src/components/workspace/messages/message-list.tsx；frontend/src/core/messages/utils.ts。

#### 251. feat: enhance message display

- 提交：`[9605cec](https://github.com/bytedance/deer-flow/commit/9605cec6d379514feb42c7164ce1a730ddd58cbc)`
- 日期：2026-01-18
- 明确新增内容：增强了“enhance message display”相关能力与交互体验。
- 影响范围：主要涉及 前端。
- 改动规模：+115 / -66 行。
- 关键文件：frontend/src/components/workspace/messages/message-list-item.tsx；frontend/src/components/workspace/messages/message-list.tsx；frontend/src/core/messages/utils.ts。

#### 252. feat: dim the placeholder

- 提交：`[59683fc](https://github.com/bytedance/deer-flow/commit/59683fc12e5dc408405cef7b278e31846f3efdc8)`
- 日期：2026-01-18
- 明确新增内容：引入了“dim the placeholder”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+6 / -6 行。
- 关键文件：frontend/src/components/ui/textarea.tsx。

#### 253. feat: dim the placeholder

- 提交：`[f924272](https://github.com/bytedance/deer-flow/commit/f9242727c75360319d8e5c786de82a0ee79a057a)`
- 日期：2026-01-18
- 明确新增内容：引入了“dim the placeholder”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+6 / -6 行。
- 关键文件：frontend/src/components/ui/textarea.tsx。

#### 254. feat: remove model icon

- 提交：`[92fc19a](https://github.com/bytedance/deer-flow/commit/92fc19a3aa50a9f31642e8a405e506de598886d4)`
- 日期：2026-01-18
- 明确新增内容：引入了“remove model icon”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+8 / -9 行。
- 关键文件：frontend/src/components/ai-elements/model-selector.tsx；frontend/src/components/ai-elements/prompt-input.tsx；frontend/src/components/workspace/input-box.tsx。

#### 255. feat: remove model icon

- 提交：`[449f04f](https://github.com/bytedance/deer-flow/commit/449f04fc4404ab63ef084102f561b9a6dbddcdf0)`
- 日期：2026-01-18
- 明确新增内容：引入了“remove model icon”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+8 / -9 行。
- 关键文件：frontend/src/components/ai-elements/model-selector.tsx；frontend/src/components/ai-elements/prompt-input.tsx；frontend/src/components/workspace/input-box.tsx。

#### 256. feat: change back to 60px height

- 提交：`[3f1f6af](https://github.com/bytedance/deer-flow/commit/3f1f6af30c1d989f04b47e38dd189784cf8821f6)`
- 日期：2026-01-17
- 明确新增内容：引入了“change back to 60px height”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+2 / -2 行。
- 关键文件：frontend/src/components/workspace/workspace-header.tsx。

#### 257. feat: change back to 60px height

- 提交：`[fa07e9e](https://github.com/bytedance/deer-flow/commit/fa07e9e903777cedc149820648caaef51e1af841)`
- 日期：2026-01-17
- 明确新增内容：引入了“change back to 60px height”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+2 / -2 行。
- 关键文件：frontend/src/components/workspace/workspace-header.tsx。

#### 258. feat: use default sidebar width

- 提交：`[7ea7a78](https://github.com/bytedance/deer-flow/commit/7ea7a7864ec2099356d901017b4921a1583f6757)`
- 日期：2026-01-17
- 明确新增内容：引入了“use default sidebar width”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+0 / -5 行。
- 关键文件：frontend/src/app/workspace/layout.tsx。

#### 259. feat: use default sidebar width

- 提交：`[d0988b3](https://github.com/bytedance/deer-flow/commit/d0988b3cf01f4a4bb1a3df3582e58f47cf4c61e7)`
- 日期：2026-01-17
- 明确新增内容：引入了“use default sidebar width”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+0 / -5 行。
- 关键文件：frontend/src/app/workspace/layout.tsx。

#### 260. feat: refine theme

- 提交：`[5cda2b9](https://github.com/bytedance/deer-flow/commit/5cda2b90fcb5640d64d5513fd594b86ea716f4a3)`
- 日期：2026-01-17
- 明确新增内容：引入了“refine theme”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+6 / -6 行。
- 关键文件：frontend/src/components/workspace/input-box.tsx；frontend/src/styles/globals.css。

#### 261. feat: refine theme

- 提交：`[36b7ac0](https://github.com/bytedance/deer-flow/commit/36b7ac0ce49f8cadf605fc93f36e548729d87933)`
- 日期：2026-01-17
- 明确新增内容：引入了“refine theme”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+6 / -6 行。
- 关键文件：frontend/src/components/workspace/input-box.tsx；frontend/src/styles/globals.css。

#### 262. feat: adjust dark theme

- 提交：`[70cd664](https://github.com/bytedance/deer-flow/commit/70cd664d3fdeac4860b570a0be547dd0cf39fd04)`
- 日期：2026-01-17
- 明确新增内容：引入了“adjust dark theme”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+3 / -3 行。
- 关键文件：frontend/src/styles/globals.css。

#### 263. feat: adjust dark theme

- 提交：`[00fc705](https://github.com/bytedance/deer-flow/commit/00fc70536ee9910f539ccc96d5d59fb522fe0c11)`
- 日期：2026-01-17
- 明确新增内容：引入了“adjust dark theme”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+3 / -3 行。
- 关键文件：frontend/src/styles/globals.css。

#### 264. feat: the DeerFlow theme is back

- 提交：`[32a77cc](https://github.com/bytedance/deer-flow/commit/32a77cce8425cb79dcaf6a665eae7b0e2fd6dcbf)`
- 日期：2026-01-17
- 明确新增内容：引入了“the DeerFlow theme is back”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+22 / -22 行。
- 关键文件：frontend/src/styles/globals.css。

#### 265. feat: the DeerFlow theme is back

- 提交：`[6c9b0f2](https://github.com/bytedance/deer-flow/commit/6c9b0f275b86f3fbd0549c7b708dbad515f9c126)`
- 日期：2026-01-17
- 明确新增内容：引入了“the DeerFlow theme is back”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+22 / -22 行。
- 关键文件：frontend/src/styles/globals.css。

#### 266. feat: change light theme

- 提交：`[094553e](https://github.com/bytedance/deer-flow/commit/094553ea42dc18a807fcc248ef7008c2e964936c)`
- 日期：2026-01-17
- 明确新增内容：引入了“change light theme”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+10 / -10 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/ui/input-group.tsx；frontend/src/components/ui/tooltip.tsx；frontend/src/components/workspace/artifacts/artifact-file-detail.tsx；frontend/src/styles/globals.css。

#### 267. feat: change light theme

- 提交：`[79d87de](https://github.com/bytedance/deer-flow/commit/79d87de5237c566288439260ec19375728eccd4e)`
- 日期：2026-01-17
- 明确新增内容：引入了“change light theme”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+10 / -10 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/ui/input-group.tsx；frontend/src/components/ui/tooltip.tsx；frontend/src/components/workspace/artifacts/artifact-file-detail.tsx；frontend/src/styles/globals.css。

#### 268. feat: welcome, again

- 提交：`[2bc5f30](https://github.com/bytedance/deer-flow/commit/2bc5f30c4dbdf4412bf5a622cd3131cd5c242138)`
- 日期：2026-01-17
- 明确新增内容：引入了“welcome, again”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+54 / -10 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/workspace/input-box.tsx；frontend/src/components/workspace/welcome.tsx。

#### 269. feat: welcome, again

- 提交：`[a6e5ebe](https://github.com/bytedance/deer-flow/commit/a6e5ebe8985f8e625e8c4cffb0766b5ada3056c8)`
- 日期：2026-01-17
- 明确新增内容：引入了“welcome, again”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+54 / -10 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/workspace/input-box.tsx；frontend/src/components/workspace/welcome.tsx。

#### 270. feat: add reasoning check to message list item rendering

- 提交：`[06068dd](https://github.com/bytedance/deer-flow/commit/06068dd07b50408b8207386abec89e544deee36f)`
- 日期：2026-01-17
- 明确新增内容：新增了“reasoning check to message list item rendering”功能。
- 影响范围：主要涉及 前端。
- 改动规模：+8 / -4 行。
- 关键文件：frontend/src/components/workspace/messages/message-list-item.tsx；frontend/src/core/messages/utils.ts。

#### 271. feat: add reasoning check to message list item rendering

- 提交：`[0ea448a](https://github.com/bytedance/deer-flow/commit/0ea448a220356f94da24a3e1acbc1603b42fa19c)`
- 日期：2026-01-17
- 明确新增内容：新增了“reasoning check to message list item rendering”功能。
- 影响范围：主要涉及 前端。
- 改动规模：+8 / -4 行。
- 关键文件：frontend/src/components/workspace/messages/message-list-item.tsx；frontend/src/core/messages/utils.ts。

#### 272. feat: pull up the input box when creating new thread

- 提交：`[b705a44](https://github.com/bytedance/deer-flow/commit/b705a44f3c9f562c49d3887e04e8504471fa2757)`
- 日期：2026-01-17
- 明确新增内容：引入了“pull up the input box when creating new thread”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+4 / -1 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx。

#### 273. feat: pull up the input box when creating new thread

- 提交：`[cb54b5d](https://github.com/bytedance/deer-flow/commit/cb54b5dffa70011822e23b64c4eeeddda0b73649)`
- 日期：2026-01-17
- 明确新增内容：引入了“pull up the input box when creating new thread”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+4 / -1 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx。

#### 274. feat:enhance  focus status

- 提交：`[85d9baf](https://github.com/bytedance/deer-flow/commit/85d9baf2b14bf7452d79540ea24758442e66eed3)`
- 日期：2026-01-17
- 明确新增内容：增强了“enhance  focus status”相关能力与交互体验。
- 影响范围：主要涉及 前端。
- 改动规模：+26 / -26 行。
- 关键文件：frontend/src/components/ui/input-group.tsx。

#### 275. feat:enhance  focus status

- 提交：`[9bfa49a](https://github.com/bytedance/deer-flow/commit/9bfa49ae0751865604726fd4e1e3e02dbb054a0b)`
- 日期：2026-01-17
- 明确新增内容：增强了“enhance  focus status”相关能力与交互体验。
- 影响范围：主要涉及 前端。
- 改动规模：+26 / -26 行。
- 关键文件：frontend/src/components/ui/input-group.tsx。

#### 276. feat: redesign step counter

- 提交：`[a64b0d2](https://github.com/bytedance/deer-flow/commit/a64b0d226bab3e8c565df4df0c5db8f34508207d)`
- 日期：2026-01-17
- 明确新增内容：引入了“redesign step counter”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+10 / -8 行。
- 关键文件：frontend/src/components/workspace/messages/message-group.tsx。

#### 277. feat: redesign step counter

- 提交：`[62921ec](https://github.com/bytedance/deer-flow/commit/62921ec96a20635f611e774ade74c9149dcd32e1)`
- 日期：2026-01-17
- 明确新增内容：引入了“redesign step counter”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+10 / -8 行。
- 关键文件：frontend/src/components/workspace/messages/message-group.tsx。

#### 278. feat: extract ThreadTitle component

- 提交：`[d8f0f91](https://github.com/bytedance/deer-flow/commit/d8f0f912383eded63738a7e5c74b18f9b89019af)`
- 日期：2026-01-17
- 明确新增内容：引入了“extract ThreadTitle component”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+15 / -7 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/workspace/thread-title.tsx。

#### 279. feat: extract ThreadTitle component

- 提交：`[7b33214](https://github.com/bytedance/deer-flow/commit/7b33214a0526152262a419f1249fa2910d4dd245)`
- 日期：2026-01-17
- 明确新增内容：引入了“extract ThreadTitle component”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+15 / -7 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/workspace/thread-title.tsx。

#### 280. feat: integrated with artifacts in states

- 提交：`[f1c6991](https://github.com/bytedance/deer-flow/commit/f1c6991194ed9d89c1e2bc575bc0e3bf1a192e85)`
- 日期：2026-01-17
- 明确新增内容：引入了“integrated with artifacts in states”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+118 / -70 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/ai-elements/artifact.tsx；frontend/src/components/ui/select.tsx；frontend/src/components/workspace/artifacts/artifact-file-detail.tsx；frontend/src/components/workspace/artifacts/artifact-file-list.tsx；frontend/src/components/workspace/artifacts/context.tsx；frontend/src/core/artifacts/utils.ts；frontend/src/core/threads/types.ts。

#### 281. feat: integrated with artifacts in states

- 提交：`[9a3f728](https://github.com/bytedance/deer-flow/commit/9a3f72869c31d598adad600b05486ebd50dd74c1)`
- 日期：2026-01-17
- 明确新增内容：引入了“integrated with artifacts in states”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+118 / -70 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/ai-elements/artifact.tsx；frontend/src/components/ui/select.tsx；frontend/src/components/workspace/artifacts/artifact-file-detail.tsx；frontend/src/components/workspace/artifacts/artifact-file-list.tsx；frontend/src/components/workspace/artifacts/context.tsx；frontend/src/core/artifacts/utils.ts；frontend/src/core/threads/types.ts。

#### 282. feat: remove ring

- 提交：`[384353d](https://github.com/bytedance/deer-flow/commit/384353d613b2a9edc5657b50615f8d4951583747)`
- 日期：2026-01-17
- 明确新增内容：引入了“remove ring”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+2 / -2 行。
- 关键文件：frontend/src/styles/globals.css。

#### 283. feat: remove ring

- 提交：`[ab65ab3](https://github.com/bytedance/deer-flow/commit/ab65ab3af28e6f8775de6ab3586e2985785a142f)`
- 日期：2026-01-17
- 明确新增内容：引入了“remove ring”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+2 / -2 行。
- 关键文件：frontend/src/styles/globals.css。

#### 284. chore: add TODO for checking duplicate files in state.artifacts

- 提交：`[a66d515](https://github.com/bytedance/deer-flow/commit/a66d5152145b13e5559bb854e4135a2858c8dd06)`
- 日期：2026-01-17
- 明确新增内容：新增了“TODO for checking duplicate files in state.artifacts”功能。
- 影响范围：主要涉及 后端。
- 改动规模：+1 / -0 行。
- 关键文件：backend/TODO.md。

#### 285. chore: add TODO for checking duplicate files in state.artifacts

- 提交：`[d603771](https://github.com/bytedance/deer-flow/commit/d6037712912d4e59cb7e095e0f2b975bfc484e43)`
- 日期：2026-01-17
- 明确新增内容：新增了“TODO for checking duplicate files in state.artifacts”功能。
- 影响范围：主要涉及 后端。
- 改动规模：+1 / -0 行。
- 关键文件：backend/TODO.md。

#### 286. feat: merge the last thinking with the previous group

- 提交：`[a663bcc](https://github.com/bytedance/deer-flow/commit/a663bcc37be426408cec6269d2be9d5e4b2cfff1)`
- 日期：2026-01-17
- 明确新增内容：引入了“merge the last thinking with the previous group”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+15 / -22 行。
- 关键文件：frontend/src/components/workspace/messages/message-list-item.tsx；frontend/src/core/messages/utils.ts。

#### 287. feat: merge the last thinking with the previous group

- 提交：`[1a3b70a](https://github.com/bytedance/deer-flow/commit/1a3b70ac43d2dec839f13b76d059b784fc9919cd)`
- 日期：2026-01-17
- 明确新增内容：引入了“merge the last thinking with the previous group”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+15 / -22 行。
- 关键文件：frontend/src/components/workspace/messages/message-list-item.tsx；frontend/src/core/messages/utils.ts。

#### 288. feat: implement '/chats'

- 提交：`[56da1c9](https://github.com/bytedance/deer-flow/commit/56da1c990aad453481badf51e6d215a3834da081)`
- 日期：2026-01-17
- 明确新增内容：实现了“implement '/chats'”这项新能力。
- 影响范围：主要涉及 前端。
- 改动规模：+48 / -1 行。
- 关键文件：frontend/src/app/workspace/chats/page.tsx。

#### 289. feat: implement '/chats'

- 提交：`[e2d0246](https://github.com/bytedance/deer-flow/commit/e2d02468272e2a14f72fc601bde6ea8bf6b50fef)`
- 日期：2026-01-17
- 明确新增内容：实现了“implement '/chats'”这项新能力。
- 影响范围：主要涉及 前端。
- 改动规模：+48 / -1 行。
- 关键文件：frontend/src/app/workspace/chats/page.tsx。

#### 290. feat: add date time util

- 提交：`[228ec49](https://github.com/bytedance/deer-flow/commit/228ec49f70373b1c862ab6bd1c2053b9ef8caded)`
- 日期：2026-01-17
- 明确新增内容：新增了“date time util”功能。
- 影响范围：主要涉及 前端。
- 改动规模：+16 / -0 行。
- 关键文件：frontend/package.json；frontend/pnpm-lock.yaml；frontend/src/core/utils/datetime.ts。

#### 291. feat: add date time util

- 提交：`[c38dfdf](https://github.com/bytedance/deer-flow/commit/c38dfdf0e0ef08be723fa2651f29a220362fd660)`
- 日期：2026-01-17
- 明确新增内容：新增了“date time util”功能。
- 影响范围：主要涉及 前端。
- 改动规模：+16 / -0 行。
- 关键文件：frontend/package.json；frontend/pnpm-lock.yaml；frontend/src/core/utils/datetime.ts。

#### 292. feat: shrink card size

- 提交：`[0e8fdf6](https://github.com/bytedance/deer-flow/commit/0e8fdf6234c36b772ce2e01302f2a6257e38d407)`
- 日期：2026-01-17
- 明确新增内容：引入了“shrink card size”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+3 / -3 行。
- 关键文件：frontend/src/components/workspace/artifacts/artifact-file-list.tsx。

#### 293. feat: shrink card size

- 提交：`[3151087](https://github.com/bytedance/deer-flow/commit/31510879f2617d3abcff70ff4891313fc3684b93)`
- 日期：2026-01-17
- 明确新增内容：引入了“shrink card size”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+3 / -3 行。
- 关键文件：frontend/src/components/workspace/artifacts/artifact-file-list.tsx。

#### 294. feat: add `open in new window`

- 提交：`[5dc40a9](https://github.com/bytedance/deer-flow/commit/5dc40a9adeac285c8e954cb4d581471919b00989)`
- 日期：2026-01-17
- 明确新增内容：新增了“`open in new window`”功能。
- 影响范围：主要涉及 前端。
- 改动规模：+13 / -1 行。
- 关键文件：frontend/src/components/workspace/artifacts/artifact-file-detail.tsx。

#### 295. feat: add `open in new window`

- 提交：`[aa2677e](https://github.com/bytedance/deer-flow/commit/aa2677e9fd9b046825d32426a771e016db6c4684)`
- 日期：2026-01-17
- 明确新增内容：新增了“`open in new window`”功能。
- 影响范围：主要涉及 前端。
- 改动规模：+13 / -1 行。
- 关键文件：frontend/src/components/workspace/artifacts/artifact-file-detail.tsx。

#### 296. feat: support artifact preview

- 提交：`[962d8f0](https://github.com/bytedance/deer-flow/commit/962d8f04ec93cee36516dc9d9cb45199a8ba1e29)`
- 日期：2026-01-17
- 明确新增内容：新增了对“artifact preview”的支持能力。
- 影响范围：主要涉及 前端、后端。
- 改动规模：+482 / -42 行。
- 关键文件：backend/src/gateway/app.py；backend/src/gateway/routers/artifacts.py；frontend/package.json；frontend/pnpm-lock.yaml；frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/app/workspace/layout.tsx；frontend/src/components/ui/sonner.tsx；frontend/src/components/workspace/artifacts/artifact-file-detail.tsx。

#### 297. feat: support artifact preview

- 提交：`[0c6f835](https://github.com/bytedance/deer-flow/commit/0c6f8353bf54b413cd1ef70bd3df97a0d163f781)`
- 日期：2026-01-17
- 明确新增内容：新增了对“artifact preview”的支持能力。
- 影响范围：主要涉及 前端、后端。
- 改动规模：+482 / -42 行。
- 关键文件：backend/src/gateway/app.py；backend/src/gateway/routers/artifacts.py；frontend/package.json；frontend/pnpm-lock.yaml；frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/app/workspace/layout.tsx；frontend/src/components/ui/sonner.tsx；frontend/src/components/workspace/artifacts/artifact-file-detail.tsx。

#### 298. feat: set artifacts layout

- 提交：`[ec5bbf6](https://github.com/bytedance/deer-flow/commit/ec5bbf6b513fb573f07a2d9e23336c74054232bf)`
- 日期：2026-01-17
- 明确新增内容：引入了“set artifacts layout”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+150 / -84 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/layout.tsx；frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/app/workspace/layout.tsx；frontend/src/components/workspace/artifacts/artifact-file-detail.tsx；frontend/src/components/workspace/artifacts/context.tsx；frontend/src/components/workspace/messages/message-list.tsx。

#### 299. feat: set artifacts layout

- 提交：`[80c928f](https://github.com/bytedance/deer-flow/commit/80c928fcf556d6b4c56e17312f63a8705a311b0e)`
- 日期：2026-01-17
- 明确新增内容：引入了“set artifacts layout”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+150 / -84 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/layout.tsx；frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/app/workspace/layout.tsx；frontend/src/components/workspace/artifacts/artifact-file-detail.tsx；frontend/src/components/workspace/artifacts/context.tsx；frontend/src/components/workspace/messages/message-list.tsx。

#### 300. feat: make BETTER_AUTH_* optional

- 提交：`[4e7256a](https://github.com/bytedance/deer-flow/commit/4e7256a9d860209dd2153d0f355f9fdf3c440e59)`
- 日期：2026-01-17
- 明确新增内容：引入了“make BETTER_AUTH_* optional”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+2 / -2 行。
- 关键文件：frontend/src/env.js。

#### 301. feat: make BETTER_AUTH_* optional

- 提交：`[9a4cb61](https://github.com/bytedance/deer-flow/commit/9a4cb616c9554800ab8499f29f248684417f6e1c)`
- 日期：2026-01-17
- 明确新增内容：引入了“make BETTER_AUTH_* optional”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+2 / -2 行。
- 关键文件：frontend/src/env.js。

#### 302. feat: ignore components from 3rd parties

- 提交：`[bb92dec](https://github.com/bytedance/deer-flow/commit/bb92dec8d5751aef5260245d8373b26b28eaf456)`
- 日期：2026-01-17
- 明确新增内容：引入了“ignore components from 3rd parties”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -1 行。
- 关键文件：frontend/eslint.config.js。

#### 303. feat: ignore components from 3rd parties

- 提交：`[1a99ae9](https://github.com/bytedance/deer-flow/commit/1a99ae9c36fc584d522b3707f76e32b7974152ef)`
- 日期：2026-01-17
- 明确新增内容：引入了“ignore components from 3rd parties”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -1 行。
- 关键文件：frontend/eslint.config.js。

#### 304. feat: integrated with artifacts

- 提交：`[9d64c7e](https://github.com/bytedance/deer-flow/commit/9d64c7e076000f1c6e6d385a7dd400526bf4ec5b)`
- 日期：2026-01-17
- 明确新增内容：引入了“integrated with artifacts”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+203 / -68 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/workspace/artifacts/artifact-file-detail.tsx；frontend/src/components/workspace/artifacts/artifact-file-list.tsx；frontend/src/components/workspace/artifacts/context.tsx；frontend/src/components/workspace/artifacts/index.ts；frontend/src/components/workspace/message-list/message-list.tsx；frontend/src/components/workspace/message-list/present-file-list.tsx。

#### 305. feat: integrated with artifacts

- 提交：`[e5050c6](https://github.com/bytedance/deer-flow/commit/e5050c6c1e5cd7fbd1218ac7421909cbe438a129)`
- 日期：2026-01-17
- 明确新增内容：引入了“integrated with artifacts”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+203 / -68 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/workspace/artifacts/artifact-file-detail.tsx；frontend/src/components/workspace/artifacts/artifact-file-list.tsx；frontend/src/components/workspace/artifacts/context.tsx；frontend/src/components/workspace/artifacts/index.ts；frontend/src/components/workspace/message-list/message-list.tsx；frontend/src/components/workspace/message-list/present-file-list.tsx。

#### 306. feat: add artifacts logic (#8)

- 提交：`[facde64](https://github.com/bytedance/deer-flow/commit/facde645d7693234bb09fb01a72d29594d4107df)`
- 日期：2026-01-16
- 明确新增内容：新增了“artifacts logic”功能。
- 影响范围：主要涉及 后端。
- 改动规模：+129 / -7 行。
- 关键文件：backend/src/agents/thread_state.py；backend/src/community/aio_sandbox/aio_sandbox_provider.py；backend/src/gateway/app.py；backend/src/gateway/routers/**init**.py；backend/src/gateway/routers/artifacts.py；backend/src/tools/builtins/present_file_tool.py。

#### 307. feat: add artifacts logic (#8)

- 提交：`[d5b3052](https://github.com/bytedance/deer-flow/commit/d5b3052cdad69b71aadb3a6b577d3dbe43c85553)`
- 日期：2026-01-16
- 明确新增内容：新增了“artifacts logic”功能。
- 影响范围：主要涉及 后端。
- 改动规模：+129 / -7 行。
- 关键文件：backend/src/agents/thread_state.py；backend/src/community/aio_sandbox/aio_sandbox_provider.py；backend/src/gateway/app.py；backend/src/gateway/routers/**init**.py；backend/src/gateway/routers/artifacts.py；backend/src/tools/builtins/present_file_tool.py。

#### 308. feat: remember sidebar state

- 提交：`[6464a67](https://github.com/bytedance/deer-flow/commit/6464a6723018e8c44dd8019800ca9dd42012e05a)`
- 日期：2026-01-16
- 明确新增内容：引入了“remember sidebar state”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+59 / -34 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/app/workspace/layout.tsx；frontend/src/core/settings/hooks.ts；frontend/src/core/settings/local.ts。

#### 309. feat: remember sidebar state

- 提交：`[0d11b21](https://github.com/bytedance/deer-flow/commit/0d11b21c84a7aaffcdd536374422971169ae12c9)`
- 日期：2026-01-16
- 明确新增内容：引入了“remember sidebar state”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+59 / -34 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/app/workspace/layout.tsx；frontend/src/core/settings/hooks.ts；frontend/src/core/settings/local.ts。

#### 310. feat: support basic file presenting

- 提交：`[f9853f0](https://github.com/bytedance/deer-flow/commit/f9853f037c52c397d1fb394b5c47612dcb754110)`
- 日期：2026-01-16
- 明确新增内容：新增了对“basic file presenting”的支持能力。
- 影响范围：主要涉及 前端。
- 改动规模：+102 / -4 行。
- 关键文件：frontend/src/components/workspace/message-list/message-list.tsx；frontend/src/components/workspace/message-list/present-file-list.tsx；frontend/src/core/messages/utils.ts；frontend/src/core/utils/files.ts。

#### 311. feat: support basic file presenting

- 提交：`[83f367b](https://github.com/bytedance/deer-flow/commit/83f367b98a74137bc8337531b6b814991b0d4b00)`
- 日期：2026-01-16
- 明确新增内容：新增了对“basic file presenting”的支持能力。
- 影响范围：主要涉及 前端。
- 改动规模：+102 / -4 行。
- 关键文件：frontend/src/components/workspace/message-list/message-list.tsx；frontend/src/components/workspace/message-list/present-file-list.tsx；frontend/src/core/messages/utils.ts；frontend/src/core/utils/files.ts。

#### 312. feat: add thread-safety and graceful shutdown to AioSandboxProvider (#7)

- 提交：`[4b69aed](https://github.com/bytedance/deer-flow/commit/4b69aed47b3c0afb3f6469a4d42f368df208882d)`
- 日期：2026-01-16
- 明确新增内容：新增了“thread-safety and graceful shutdown to AioSandboxProvider”功能。
- 影响范围：主要涉及 后端。
- 改动规模：+238 / -38 行。
- 关键文件：backend/src/community/aio_sandbox/aio_sandbox_provider.py；backend/src/utils/network.py。

#### 313. feat: add thread-safety and graceful shutdown to AioSandboxProvider (#7)

- 提交：`[50a1e40](https://github.com/bytedance/deer-flow/commit/50a1e407cfb00075e06ed7f91ea2cbc67ed18f67)`
- 日期：2026-01-16
- 明确新增内容：新增了“thread-safety and graceful shutdown to AioSandboxProvider”功能。
- 影响范围：主要涉及 后端。
- 改动规模：+238 / -38 行。
- 关键文件：backend/src/community/aio_sandbox/aio_sandbox_provider.py；backend/src/utils/network.py。

#### 314. docs: rewording

- 提交：`[c0e63c5](https://github.com/bytedance/deer-flow/commit/c0e63c5308b3d9fda113473d93c5e58fb9fb521c)`
- 日期：2026-01-16
- 明确新增内容：新增了“rewording”相关文档说明，补齐使用/配置指引。
- 影响范围：主要涉及 后端。
- 改动规模：+5 / -4 行。
- 关键文件：backend/src/tools/builtins/present_file_tool.py。

#### 315. docs: rewording

- 提交：`[d2845f6](https://github.com/bytedance/deer-flow/commit/d2845f658f6ef8e7445e74322eb7f607440e1414)`
- 日期：2026-01-16
- 明确新增内容：新增了“rewording”相关文档说明，补齐使用/配置指引。
- 影响范围：主要涉及 后端。
- 改动规模：+5 / -4 行。
- 关键文件：backend/src/tools/builtins/present_file_tool.py。

#### 316. feat: integrated with artifact resizable

- 提交：`[93a231c](https://github.com/bytedance/deer-flow/commit/93a231cfb1aba3edefe114fb5d2f0a4d6b350750)`
- 日期：2026-01-16
- 明确新增内容：引入了“integrated with artifact resizable”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+43 / -33 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/workspace/message-list/message-group.tsx；frontend/src/components/workspace/workspace-container.tsx。

#### 317. feat: integrated with artifact resizable

- 提交：`[ca70e2d](https://github.com/bytedance/deer-flow/commit/ca70e2dcf7c473062faef6eeac4c0147e0babf87)`
- 日期：2026-01-16
- 明确新增内容：引入了“integrated with artifact resizable”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+43 / -33 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/workspace/message-list/message-group.tsx；frontend/src/components/workspace/workspace-container.tsx。

#### 318. chore: add resizable

- 提交：`[68fbf53](https://github.com/bytedance/deer-flow/commit/68fbf53fb2966fa3a1a6e3658e9f335d23a0482d)`
- 日期：2026-01-16
- 明确新增内容：新增了“resizable”功能。
- 影响范围：主要涉及 前端。
- 改动规模：+103 / -0 行。
- 关键文件：frontend/package.json；frontend/pnpm-lock.yaml；frontend/src/components/ui/resizable.tsx。

#### 319. chore: add resizable

- 提交：`[e1ddb1e](https://github.com/bytedance/deer-flow/commit/e1ddb1ee422a8bb7b6e7144c622313444c30b8d0)`
- 日期：2026-01-16
- 明确新增内容：新增了“resizable”功能。
- 影响范围：主要涉及 前端。
- 改动规模：+103 / -0 行。
- 关键文件：frontend/package.json；frontend/pnpm-lock.yaml；frontend/src/components/ui/resizable.tsx。

#### 320. feat: add present_file tool

- 提交：`[1517e86](https://github.com/bytedance/deer-flow/commit/1517e8675d5c876eb92b13bafaae3e4c71f55d08)`
- 日期：2026-01-16
- 明确新增内容：新增了“present_file tool”功能。
- 影响范围：主要涉及 后端。
- 改动规模：+34 / -1 行。
- 关键文件：backend/src/tools/builtins/**init**.py；backend/src/tools/builtins/present_file_tool.py；backend/src/tools/tools.py。

#### 321. feat: add present_file tool

- 提交：`[56b26c0](https://github.com/bytedance/deer-flow/commit/56b26c060e27b0c12454cce9c3445a05cfe72a3c)`
- 日期：2026-01-16
- 明确新增内容：新增了“present_file tool”功能。
- 影响范围：主要涉及 后端。
- 改动规模：+34 / -1 行。
- 关键文件：backend/src/tools/builtins/**init**.py；backend/src/tools/builtins/present_file_tool.py；backend/src/tools/tools.py。

#### 322. feat: add flip display effect

- 提交：`[91eff99](https://github.com/bytedance/deer-flow/commit/91eff99f01831c3dd1ed5d65e43a922647889a3e)`
- 日期：2026-01-16
- 明确新增内容：新增了“flip display effect”功能。
- 影响范围：主要涉及 前端。
- 改动规模：+41 / -7 行。
- 关键文件：frontend/src/components/workspace/flip-display.tsx；frontend/src/components/workspace/message-list/message-group.tsx；frontend/src/components/workspace/message-list/message-list.tsx。

#### 323. feat: add flip display effect

- 提交：`[e37be40](https://github.com/bytedance/deer-flow/commit/e37be407732f328576ca4aed34b7e2cece1e7da4)`
- 日期：2026-01-16
- 明确新增内容：新增了“flip display effect”功能。
- 影响范围：主要涉及 前端。
- 改动规模：+41 / -7 行。
- 关键文件：frontend/src/components/workspace/flip-display.tsx；frontend/src/components/workspace/message-list/message-group.tsx；frontend/src/components/workspace/message-list/message-list.tsx。

#### 324. feat: adjust layout

- 提交：`[c265734](https://github.com/bytedance/deer-flow/commit/c265734c6e9c76aaf5303418be9a3b3d3f6e1f91)`
- 日期：2026-01-16
- 明确新增内容：引入了“adjust layout”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+5 / -4 行。
- 关键文件：frontend/src/components/workspace/message-list/message-list-item.tsx；frontend/src/components/workspace/message-list/message-list.tsx。

#### 325. feat: adjust layout

- 提交：`[6e5dab7](https://github.com/bytedance/deer-flow/commit/6e5dab76ccda4af0083b889f4ecad1d5505bd427)`
- 日期：2026-01-16
- 明确新增内容：引入了“adjust layout”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+5 / -4 行。
- 关键文件：frontend/src/components/workspace/message-list/message-list-item.tsx；frontend/src/components/workspace/message-list/message-list.tsx。

#### 326. feat: adjust layout and style of tooltip

- 提交：`[7066a3b](https://github.com/bytedance/deer-flow/commit/7066a3b6910752a70a692389a78ca0e061bc39d1)`
- 日期：2026-01-16
- 明确新增内容：引入了“adjust layout and style of tooltip”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+13 / -14 行。
- 关键文件：frontend/src/components/ui/tooltip.tsx；frontend/src/components/workspace/tooltip.tsx。

#### 327. feat: adjust layout and style of tooltip

- 提交：`[f6c20db](https://github.com/bytedance/deer-flow/commit/f6c20dbcfe2e34a0a353030c99aca061f36a9d4d)`
- 日期：2026-01-16
- 明确新增内容：引入了“adjust layout and style of tooltip”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+13 / -14 行。
- 关键文件：frontend/src/components/ui/tooltip.tsx；frontend/src/components/workspace/tooltip.tsx。

#### 328. feat: add copy button

- 提交：`[df396fc](https://github.com/bytedance/deer-flow/commit/df396fc24651aa92d6c281879d365f5dc8818386)`
- 日期：2026-01-16
- 明确新增内容：新增了“copy button”功能。
- 影响范围：主要涉及 前端。
- 改动规模：+37 / -0 行。
- 关键文件：frontend/src/components/workspace/copy-button.tsx。

#### 329. feat: add copy button

- 提交：`[574b7e5](https://github.com/bytedance/deer-flow/commit/574b7e59cef6f29e4e95dca443c3a81f65f7bf5a)`
- 日期：2026-01-16
- 明确新增内容：新增了“copy button”功能。
- 影响范围：主要涉及 前端。
- 改动规模：+37 / -0 行。
- 关键文件：frontend/src/components/workspace/copy-button.tsx。

#### 330. feat: add skills system for specialized agent workflows (#6)

- 提交：`[9f755ec](https://github.com/bytedance/deer-flow/commit/9f755ecc30691fcdc713239dbf5c8d5ff3cb1355)`
- 日期：2026-01-16
- 明确新增内容：新增了“skills system for specialized agent workflows”功能。
- 影响范围：主要涉及 后端、技能体系、文档。
- 改动规模：+2959 / -51 行。
- 关键文件：README.md；backend/CLAUDE.md；backend/SETUP.md；backend/docs/CONFIGURATION.md；backend/src/agents/lead_agent/prompt.py；backend/src/community/aio_sandbox/aio_sandbox_provider.py；backend/src/config/**init**.py；backend/src/config/app_config.py。

#### 331. feat: add skills system for specialized agent workflows (#6)

- 提交：`[cfa97f7](https://github.com/bytedance/deer-flow/commit/cfa97f7a960d6f05cc156c68f56062e36b17c2ae)`
- 日期：2026-01-16
- 明确新增内容：新增了“skills system for specialized agent workflows”功能。
- 影响范围：主要涉及 后端、技能体系、文档。
- 改动规模：+2959 / -51 行。
- 关键文件：README.md；backend/CLAUDE.md；backend/SETUP.md；backend/docs/CONFIGURATION.md；backend/src/agents/lead_agent/prompt.py；backend/src/community/aio_sandbox/aio_sandbox_provider.py；backend/src/config/**init**.py；backend/src/config/app_config.py。

#### 332. feat: remove scroll button

- 提交：`[52b9d0c](https://github.com/bytedance/deer-flow/commit/52b9d0cffc8c5e64bca510a946e9521bfb253038)`
- 日期：2026-01-16
- 明确新增内容：引入了“remove scroll button”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+0 / -2 行。
- 关键文件：frontend/src/components/workspace/message-list/message-list.tsx。

#### 333. feat: remove scroll button

- 提交：`[a589fb3](https://github.com/bytedance/deer-flow/commit/a589fb3daedd66f2616d49e2198c413e4e813804)`
- 日期：2026-01-16
- 明确新增内容：引入了“remove scroll button”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+0 / -2 行。
- 关键文件：frontend/src/components/workspace/message-list/message-list.tsx。

#### 334. feat: rename 'model' to 'model_name'

- 提交：`[faf80bb](https://github.com/bytedance/deer-flow/commit/faf80bb4297198787167c3c440965581a93ccb17)`
- 日期：2026-01-16
- 明确新增内容：引入了“rename 'model' to 'model_name'”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+163 / -105 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/ui/input.tsx；frontend/src/components/workspace/input-box.tsx；frontend/src/components/workspace/recent-chat-list.tsx；frontend/src/core/api/api-client.ts；frontend/src/core/api/client.ts；frontend/src/core/api/hooks.ts；frontend/src/core/api/index.ts。

#### 335. feat: rename 'model' to 'model_name'

- 提交：`[ac07547](https://github.com/bytedance/deer-flow/commit/ac075477a0b10f52cf71516db2252691b05e1bfa)`
- 日期：2026-01-16
- 明确新增内容：引入了“rename 'model' to 'model_name'”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+163 / -105 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/ui/input.tsx；frontend/src/components/workspace/input-box.tsx；frontend/src/components/workspace/recent-chat-list.tsx；frontend/src/core/api/api-client.ts；frontend/src/core/api/client.ts；frontend/src/core/api/hooks.ts；frontend/src/core/api/index.ts。

#### 336. feat: add gateway module with FastAPI server (#5)

- 提交：`[7284eb1](https://github.com/bytedance/deer-flow/commit/7284eb15f1632ce417c1ec7c120cc3f932d0c82b)`
- 日期：2026-01-16
- 明确新增内容：新增了“gateway module with FastAPI server”功能。
- 影响范围：主要涉及 后端、前端、其他模块。
- 改动规模：+1125 / -41 行。
- 关键文件：.gitignore；backend/Makefile；backend/pyproject.toml；backend/src/agents/lead_agent/agent.py；backend/src/gateway/**init**.py；backend/src/gateway/app.py；backend/src/gateway/config.py；backend/src/gateway/routers/**init**.py。

#### 337. feat: add gateway module with FastAPI server (#5)

- 提交：`[fb92a47](https://github.com/bytedance/deer-flow/commit/fb92a472e2b918532e32f383be2d4b11e5758e16)`
- 日期：2026-01-16
- 明确新增内容：新增了“gateway module with FastAPI server”功能。
- 影响范围：主要涉及 后端、前端、其他模块。
- 改动规模：+1125 / -41 行。
- 关键文件：.gitignore；backend/Makefile；backend/pyproject.toml；backend/src/agents/lead_agent/agent.py；backend/src/gateway/**init**.py；backend/src/gateway/app.py；backend/src/gateway/config.py；backend/src/gateway/routers/**init**.py。

#### 338. feat: link to home page

- 提交：`[7c61896](https://github.com/bytedance/deer-flow/commit/7c6189668c38f0a211c78a60f4b8aa2e09a96588)`
- 日期：2026-01-16
- 明确新增内容：引入了“link to home page”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+24 / -20 行。
- 关键文件：frontend/src/components/workspace/workspace-header.tsx。

#### 339. feat: link to home page

- 提交：`[5fa98bf](https://github.com/bytedance/deer-flow/commit/5fa98bf6cd9e1c36dbd54bb35afb7bb58c7f79d2)`
- 日期：2026-01-16
- 明确新增内容：引入了“link to home page”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+24 / -20 行。
- 关键文件：frontend/src/components/workspace/workspace-header.tsx。

#### 340. feat: store the local settings

- 提交：`[028f402](https://github.com/bytedance/deer-flow/commit/028f402ff523924200a8949c40bf391f2e7f05a6)`
- 日期：2026-01-16
- 明确新增内容：引入了“store the local settings”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+86 / -12 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/workspace/input-box.tsx；frontend/src/core/settings/hooks.ts；frontend/src/core/settings/index.ts；frontend/src/core/settings/local.ts。

#### 341. feat: store the local settings

- 提交：`[3a62deb](https://github.com/bytedance/deer-flow/commit/3a62deb3fd023d088f57fa668287a114725889c3)`
- 日期：2026-01-16
- 明确新增内容：引入了“store the local settings”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+86 / -12 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/workspace/input-box.tsx；frontend/src/core/settings/hooks.ts；frontend/src/core/settings/index.ts；frontend/src/core/settings/local.ts。

#### 342. feat: enable edit context options

- 提交：`[3f2bfde](https://github.com/bytedance/deer-flow/commit/3f2bfded418368b3c08cf36f7fe58dc1e328c59a)`
- 日期：2026-01-16
- 明确新增内容：引入了“enable edit context options”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+113 / -5 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/workspace/input-box.tsx。

#### 343. feat: enable edit context options

- 提交：`[cad1206](https://github.com/bytedance/deer-flow/commit/cad12068efa47a8056b0c0dcd1eaf71c71325fef)`
- 日期：2026-01-16
- 明确新增内容：引入了“enable edit context options”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+113 / -5 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/workspace/input-box.tsx。

#### 344. feat: adjust message group layout

- 提交：`[6149962](https://github.com/bytedance/deer-flow/commit/61499624a09aceb014777c46c019266cfbc0fe39)`
- 日期：2026-01-15
- 明确新增内容：引入了“adjust message group layout”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+4 / -4 行。
- 关键文件：frontend/src/components/ai-elements/chain-of-thought.tsx；frontend/src/components/workspace/message-list/message-group.tsx。

#### 345. feat: adjust message group layout

- 提交：`[7680a5a](https://github.com/bytedance/deer-flow/commit/7680a5adbaadb9e99ab6c36d04465513b6a73efa)`
- 日期：2026-01-15
- 明确新增内容：引入了“adjust message group layout”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+4 / -4 行。
- 关键文件：frontend/src/components/ai-elements/chain-of-thought.tsx；frontend/src/components/workspace/message-list/message-group.tsx。

#### 346. feat: enhance label

- 提交：`[00ad420](https://github.com/bytedance/deer-flow/commit/00ad4206c4379dd9116e78a7a9dd66dfa430500e)`
- 日期：2026-01-15
- 明确新增内容：增强了“enhance label”相关能力与交互体验。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -1 行。
- 关键文件：frontend/src/components/workspace/message-list/message-group.tsx。

#### 347. feat: enhance label

- 提交：`[f353831](https://github.com/bytedance/deer-flow/commit/f353831ac964b396af96a54d75e29b4fc674e64d)`
- 日期：2026-01-15
- 明确新增内容：增强了“enhance label”相关能力与交互体验。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -1 行。
- 关键文件：frontend/src/components/workspace/message-list/message-group.tsx。

#### 348. feat: remove max-w-

- 提交：`[c3cb4c3](https://github.com/bytedance/deer-flow/commit/c3cb4c348de637ab5a7ea1866147d11c25fbc7fc)`
- 日期：2026-01-15
- 明确新增内容：引入了“remove max-w-”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -4 行。
- 关键文件：frontend/src/components/ai-elements/chain-of-thought.tsx。

#### 349. feat: remove max-w-

- 提交：`[d45f48a](https://github.com/bytedance/deer-flow/commit/d45f48addef42f04625267523825d335ec73e4da)`
- 日期：2026-01-15
- 明确新增内容：引入了“remove max-w-”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -4 行。
- 关键文件：frontend/src/components/ai-elements/chain-of-thought.tsx。

#### 350. feat: implement basic web app

- 提交：`[9f2b94e](https://github.com/bytedance/deer-flow/commit/9f2b94ed52c6771aba17cc662e12a465b24460e5)`
- 日期：2026-01-15
- 明确新增内容：实现了“implement basic web app”这项新能力。
- 影响范围：主要涉及 前端。
- 改动规模：+4144 / -628 行。
- 关键文件：frontend/package.json；frontend/pnpm-lock.yaml；frontend/src/app/api/langgraph/[...path]/route.ts；frontend/src/app/layout.tsx；frontend/src/app/page.tsx；frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/app/workspace/chats/page.tsx；frontend/src/app/workspace/layout.tsx。

#### 351. feat: implement basic web app

- 提交：`[cecc684](https://github.com/bytedance/deer-flow/commit/cecc684de1a2bd9921152f4acc3929ac8beb5a9f)`
- 日期：2026-01-15
- 明确新增内容：实现了“implement basic web app”这项新能力。
- 影响范围：主要涉及 前端。
- 改动规模：+4144 / -628 行。
- 关键文件：frontend/package.json；frontend/pnpm-lock.yaml；frontend/src/app/api/langgraph/[...path]/route.ts；frontend/src/app/layout.tsx；frontend/src/app/page.tsx；frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/app/workspace/chats/page.tsx；frontend/src/app/workspace/layout.tsx。

#### 352. feat: support function factory (#4)

- 提交：`[b44144d](https://github.com/bytedance/deer-flow/commit/b44144dd2c10dd1911c5fd86b4b3ff5cb246f357)`
- 日期：2026-01-15
- 明确新增内容：新增了对“function factory”的支持能力。
- 影响范围：主要涉及 后端、其他模块。
- 改动规模：+133 / -22 行。
- 关键文件：backend/debug.py；backend/langgraph.json；backend/src/agents/**init**.py；backend/src/agents/lead_agent/**init**.py；backend/src/agents/lead_agent/agent.py；backend/src/agents/lead_agent/prompt.py；backend/src/agents/middlewares/thread_data_middleware.py；backend/src/sandbox/tools.py。

#### 353. feat: support function factory (#4)

- 提交：`[c7d68c6](https://github.com/bytedance/deer-flow/commit/c7d68c6d3f85b14f8c90735201049b340c9ac320)`
- 日期：2026-01-15
- 明确新增内容：新增了对“function factory”的支持能力。
- 影响范围：主要涉及 后端、其他模块。
- 改动规模：+133 / -22 行。
- 关键文件：backend/debug.py；backend/langgraph.json；backend/src/agents/**init**.py；backend/src/agents/lead_agent/**init**.py；backend/src/agents/lead_agent/agent.py；backend/src/agents/lead_agent/prompt.py；backend/src/agents/middlewares/thread_data_middleware.py；backend/src/sandbox/tools.py。

#### 354. feat: add thread data middleware (#2)

- 提交：`[c92eedc](https://github.com/bytedance/deer-flow/commit/c92eedc57264fa566e6eb47a06dfc3b34798c6fb)`
- 日期：2026-01-15
- 明确新增内容：新增了“thread data middleware”功能。
- 影响范围：主要涉及 后端、配置。
- 改动规模：+181 / -14 行。
- 关键文件：backend/src/agents/lead_agent/agent.py；backend/src/agents/middlewares/thread_data_middleware.py；backend/src/agents/thread_state.py；backend/src/community/aio_sandbox/aio_sandbox_provider.py；backend/src/sandbox/local/local_sandbox_provider.py；backend/src/sandbox/middleware.py；backend/src/sandbox/sandbox_provider.py；config.example.yaml。

#### 355. feat: add thread data middleware (#2)

- 提交：`[41442cc](https://github.com/bytedance/deer-flow/commit/41442ccc2f70422314c3c24843fb0e6f371807aa)`
- 日期：2026-01-15
- 明确新增内容：新增了“thread data middleware”功能。
- 影响范围：主要涉及 后端、配置。
- 改动规模：+181 / -14 行。
- 关键文件：backend/src/agents/lead_agent/agent.py；backend/src/agents/middlewares/thread_data_middleware.py；backend/src/agents/thread_state.py；backend/src/community/aio_sandbox/aio_sandbox_provider.py；backend/src/sandbox/local/local_sandbox_provider.py；backend/src/sandbox/middleware.py；backend/src/sandbox/sandbox_provider.py；config.example.yaml。

#### 356. feat: add AIO sandbox provider and auto title generation (#1)

- 提交：`[ab42773](https://github.com/bytedance/deer-flow/commit/ab427731dc10549d2b00e606c2a0445af57b5af6)`
- 日期：2026-01-14
- 明确新增内容：新增了“AIO sandbox provider and auto title generation”功能。
- 影响范围：主要涉及 后端。
- 改动规模：+1479 / -13 行。
- 关键文件：backend/.claude/settings.local.json；backend/AGENTS.md；backend/CLAUDE.md；backend/Makefile；backend/docs/AUTO_TITLE_GENERATION.md；backend/docs/BACKEND_TODO.md；backend/docs/TITLE_GENERATION_IMPLEMENTATION.md；backend/pyproject.toml。

#### 357. feat: add AIO sandbox provider and auto title generation (#1)

- 提交：`[b2abfec](https://github.com/bytedance/deer-flow/commit/b2abfecf675324e4d016004a92d589c50bd948b8)`
- 日期：2026-01-14
- 明确新增内容：新增了“AIO sandbox provider and auto title generation”功能。
- 影响范围：主要涉及 后端。
- 改动规模：+1479 / -13 行。
- 关键文件：backend/.claude/settings.local.json；backend/AGENTS.md；backend/CLAUDE.md；backend/Makefile；backend/docs/AUTO_TITLE_GENERATION.md；backend/docs/BACKEND_TODO.md；backend/docs/TITLE_GENERATION_IMPLEMENTATION.md；backend/pyproject.toml。

#### 358. feat: integrated with sandbox

- 提交：`[de2d185](https://github.com/bytedance/deer-flow/commit/de2d18561adcb2bbab94246815bdca4dd151ebf8)`
- 日期：2026-01-14
- 明确新增内容：引入了“integrated with sandbox”相关功能改进。
- 影响范围：主要涉及 后端。
- 改动规模：+103 / -34 行。
- 关键文件：backend/src/agents/**init**.py；backend/src/agents/lead_agent/agent.py；backend/src/agents/thread_state.py；backend/src/config/app_config.py；backend/src/sandbox/local/local_sandbox_provider.py；backend/src/sandbox/middleware.py；backend/src/sandbox/sandbox_provider.py；backend/src/sandbox/tools.py。

#### 359. chore: add `lint` and `format`

- 提交：`[421488a](https://github.com/bytedance/deer-flow/commit/421488a991aee32bb60d3e6cc91ed17abfdc6d51)`
- 日期：2026-01-14
- 明确新增内容：新增了“`lint` and `format`”功能。
- 影响范围：主要涉及 后端。
- 改动规模：+6 / -0 行。
- 关键文件：backend/Makefile。

#### 360. docs: update tool docs

- 提交：`[e5c69cb](https://github.com/bytedance/deer-flow/commit/e5c69cb7eefcdb725d3dc2b3613c0c297f91cf57)`
- 日期：2026-01-14
- 明确新增内容：新增了“update tool docs”相关文档说明，补齐使用/配置指引。
- 影响范围：主要涉及 后端。
- 改动规模：+5 / -6 行。
- 关键文件：backend/src/agents/lead_agent/prompt.py；backend/src/sandbox/tools.py。

#### 361. feat: add agents

- 提交：`[7dc063b](https://github.com/bytedance/deer-flow/commit/7dc063ba25b9be9ffcb23f6ffc944e591dbdeedf)`
- 日期：2026-01-14
- 明确新增内容：新增了“agents”功能。
- 影响范围：主要涉及 后端。
- 改动规模：+93 / -0 行。
- 关键文件：backend/src/agents/**init**.py；backend/src/agents/lead_agent/**init**.py；backend/src/agents/lead_agent/agent.py；backend/src/agents/lead_agent/prompt.py。

#### 362. feat: add tools

- 提交：`[cbbbac0](https://github.com/bytedance/deer-flow/commit/cbbbac0c2b9f09ac7917df8b410ce7a4d28ce8b2)`
- 日期：2026-01-14
- 明确新增内容：新增了“tools”功能。
- 影响范围：主要涉及 后端。
- 改动规模：+17 / -0 行。
- 关键文件：backend/src/tools/**init**.py；backend/src/tools/tools.py。

#### 363. feat: add sandbox and local impl

- 提交：`[57a02ac](https://github.com/bytedance/deer-flow/commit/57a02acb596566bb54d7b3b97151ceaef2b90eed)`
- 日期：2026-01-14
- 明确新增内容：新增了“sandbox and local impl”功能。
- 影响范围：主要涉及 后端。
- 改动规模：+432 / -0 行。
- 关键文件：backend/src/sandbox/**init**.py；backend/src/sandbox/local/**init**.py；backend/src/sandbox/local/list_dir.py；backend/src/sandbox/local/local_sandbox.py；backend/src/sandbox/local/local_sandbox_provider.py；backend/src/sandbox/sandbox.py；backend/src/sandbox/sandbox_provider.py；backend/src/sandbox/tools.py。

#### 364. feat: integrated with Tavily and Jina AI

- 提交：`[4b5f529](https://github.com/bytedance/deer-flow/commit/4b5f5299037ffee397fcad67fc4bd27671cebe1d)`
- 日期：2026-01-14
- 明确新增内容：引入了“integrated with Tavily and Jina AI”相关功能改进。
- 影响范围：主要涉及 后端。
- 改动规模：+190 / -0 行。
- 关键文件：backend/src/community/jina_ai/jina_client.py；backend/src/community/jina_ai/tools.py；backend/src/community/tavily/tools.py；backend/src/utils/readability.py。

#### 365. feat: add model modules

- 提交：`[83bd7e4](https://github.com/bytedance/deer-flow/commit/83bd7e43096a50e842e50dd90fd3923910bdeb52)`
- 日期：2026-01-14
- 明确新增内容：新增了“model modules”功能。
- 影响范围：主要涉及 后端。
- 改动规模：+46 / -0 行。
- 关键文件：backend/src/models/**init**.py；backend/src/models/factory.py。

#### 366. chore: add an empty **init**.py

- 提交：`[721b26a](https://github.com/bytedance/deer-flow/commit/721b26a32ff4d9c8dd749537a7942fbfa0ede7b0)`
- 日期：2026-01-14
- 明确新增内容：新增了“an empty **init**.py”功能。
- 影响范围：主要涉及 后端。
- 改动规模：+0 / -0 行。
- 关键文件：backend/src/**init**.py。

#### 367. feat: add reflection modules

- 提交：`[86524a6](https://github.com/bytedance/deer-flow/commit/86524a65f6fa64bf9afc1ec9d248879eaab2ffe5)`
- 日期：2026-01-14
- 明确新增内容：新增了“reflection modules”功能。
- 影响范围：主要涉及 后端。
- 改动规模：+84 / -0 行。
- 关键文件：backend/src/reflection/**init**.py；backend/src/reflection/resolvers.py。

#### 368. feat: add config modules

- 提交：`[88ed384](https://github.com/bytedance/deer-flow/commit/88ed3841c7f29b784bbaa9cbf3ce03098fbd521e)`
- 日期：2026-01-14
- 明确新增内容：新增了“config modules”功能。
- 影响范围：主要涉及 后端。
- 改动规模：+202 / -0 行。
- 关键文件：backend/src/config/**init**.py；backend/src/config/app_config.py；backend/src/config/model_config.py；backend/src/config/sandbox_config.py；backend/src/config/tool_config.py。

#### 369. chore: add Python and LangGraph stuff

- 提交：`[c2a62a2](https://github.com/bytedance/deer-flow/commit/c2a62a2266e0756b5e69f7fc6054626f233da07c)`
- 日期：2026-01-14
- 明确新增内容：新增了“Python and LangGraph stuff”功能。
- 影响范围：主要涉及 后端。
- 改动规模：+1239 / -0 行。
- 关键文件：backend/.python-version；backend/Makefile；backend/langgraph.json；backend/pyproject.toml；backend/uv.lock。

#### 370. chore: add .gitignore for Python project

- 提交：`[81bd4da](https://github.com/bytedance/deer-flow/commit/81bd4dafa84893e20005325d6d74f239adc4b2ac)`
- 日期：2026-01-14
- 明确新增内容：新增了“.gitignore for Python project”功能。
- 影响范围：主要涉及 后端。
- 改动规模：+21 / -0 行。
- 关键文件：backend/.gitignore。

## 2026-02

- 提交数：241 条

#### 1. docs: #1 on GitHub Trending (#932)

- 提交：`[f2123ef](https://github.com/bytedance/deer-flow/commit/f2123efdb998d8e98f077740050d33a7c8e85fa7)`
- 日期：2026-02-28
- 明确新增内容：新增了“#1 on GitHub Trending”相关文档说明，补齐使用/配置指引。
- 影响范围：主要涉及 文档。
- 改动规模：+3 / -0 行。
- 关键文件：README.md。

#### 2. test: add Gateway conformance tests for DeerFlowClient (#931)

- 提交：`[30d9487](https://github.com/bytedance/deer-flow/commit/30d948711fc55c37237cec83ae3348503177b3b3)`
- 日期：2026-02-28
- 明确新增内容：新增了“add Gateway conformance tests for DeerFlowClient”相关测试覆盖与验证用例。
- 影响范围：主要涉及 后端、文档。
- 改动规模：+625 / -232 行。
- 关键文件：README.md；backend/CLAUDE.md；backend/src/client.py；backend/tests/test_client.py；backend/tests/test_client_live.py。

#### 3. feat: add DeerFlowClient for embedded programmatic access (#926)

- 提交：`[9d48c42](https://github.com/bytedance/deer-flow/commit/9d48c42a20c6e41e8132dcd67753d356b85a338c)`
- 日期：2026-02-28
- 明确新增内容：新增了“DeerFlowClient for embedded programmatic access”功能。
- 影响范围：主要涉及 后端、其他模块、文档。
- 改动规模：+2450 / -2 行。
- 关键文件：.gitignore；README.md；backend/.gitignore；backend/CLAUDE.md；backend/src/client.py；backend/tests/test_client.py；backend/tests/test_client_live.py。

#### 4. feat: add Novita AI as optional LLM provider (#910)

- 提交：`[e62b3d4](https://github.com/bytedance/deer-flow/commit/e62b3d41679c5d6306d07220f9cb601c0b271a2c)`
- 日期：2026-02-27
- 明确新增内容：新增了“Novita AI as optional LLM provider”功能。
- 影响范围：主要涉及 其他模块、文档、后端。
- 改动规模：+39 / -1 行。
- 关键文件：.env.example；README.md；backend/docs/CONFIGURATION.md；config.example.yaml。

#### 5. feat(subagents): make subagent timeout configurable via config.yaml (#897)

- 提交：`[faa4220](https://github.com/bytedance/deer-flow/commit/faa422072c0df116ad24d87ca6fcb6d7e5a276ca)`
- 日期：2026-02-25
- 明确新增内容：引入了“make subagent timeout configurable via config.yaml”相关功能改进。
- 影响范围：主要涉及 后端、CI/CD、配置。
- 改动规模：+554 / -40 行。
- 关键文件：.github/workflows/backend-unit-tests.yml；backend/CLAUDE.md；backend/Makefile；backend/src/agents/lead_agent/agent.py；backend/src/community/aio_sandbox/remote_backend.py；backend/src/config/app_config.py；backend/src/config/subagents_config.py；backend/src/config/tracing_config.py。

#### 6. docs(config):updated the configuration of deepseek-v3 (#885)

- 提交：`[b5c11ba](https://github.com/bytedance/deer-flow/commit/b5c11baece3491bed6f1443f8d7d9e031573e9b9)`
- 日期：2026-02-21
- 明确新增内容：新增了“updated the configuration of deepseek-v3”相关文档说明，补齐使用/配置指引。
- 影响范围：主要涉及 配置。
- 改动规模：+2 / -2 行。
- 关键文件：config.example.yaml。

#### 7. feat: add LangSmith tracing integration (#878)

- 提交：`[85af540](https://github.com/bytedance/deer-flow/commit/85af540076922adb5a869013015837feed983d2c)`
- 日期：2026-02-21
- 明确新增内容：新增了“LangSmith tracing integration”功能。
- 影响范围：主要涉及 后端。
- 改动规模：+84 / -1 行。
- 关键文件：backend/src/agents/lead_agent/agent.py；backend/src/config/**init**.py；backend/src/config/tracing_config.py；backend/src/models/factory.py。

#### 8. docs: make README easier to follow and update related docs (#884)

- 提交：`[75226b2](https://github.com/bytedance/deer-flow/commit/75226b2fe668d1925ce6dcfe04f4c0c5279c4e26)`
- 日期：2026-02-21
- 明确新增内容：新增了“make README easier to follow and update related docs”相关文档说明，补齐使用/配置指引。
- 影响范围：主要涉及 后端、其他模块、文档。
- 改动规模：+130 / -99 行。
- 关键文件：CONTRIBUTING.md；Makefile；README.md；backend/CONTRIBUTING.md；backend/README.md；backend/docs/CONFIGURATION.md；backend/docs/MCP_SERVER.md；config.example.yaml。

#### 9. chore: add a Makefile command to create all required local configuration files (#883)

- 提交：`[0d7c082](https://github.com/bytedance/deer-flow/commit/0d7c0826f0226ccdec16c26ca78c2dcaa237c150)`
- 日期：2026-02-19
- 明确新增内容：新增了“a Makefile command to create all required local configuration files”功能。
- 影响范围：主要涉及 其他模块、文档。
- 改动规模：+18 / -6 行。
- 关键文件：Makefile；README.md。

#### 10. docs: Update Quick Start instructions in README (#881)

- 提交：`[ea4e013](https://github.com/bytedance/deer-flow/commit/ea4e0139af24de3e2bde2483fcaac7da91bbe9c0)`
- 日期：2026-02-18
- 明确新增内容：新增了“Update Quick Start instructions in README”相关文档说明，补齐使用/配置指引。
- 影响范围：主要涉及 文档。
- 改动规模：+6 / -2 行。
- 关键文件：README.md。

#### 11. docs: add videos and official website (#865)

- 提交：`[2d3a22a](https://github.com/bytedance/deer-flow/commit/2d3a22aeb09a1fa570656d724d8d22e9840fed2d)`
- 日期：2026-02-14
- 明确新增内容：新增了“add videos and official website”相关文档说明，补齐使用/配置指引。
- 影响范围：主要涉及 文档。
- 改动规模：+10 / -0 行。
- 关键文件：README.md。

#### 12. docs:Add security policy documentation (#864)

- 提交：`[d796c5a](https://github.com/bytedance/deer-flow/commit/d796c5a32829303b1a3ff9cfa0a6429b15524c83)`
- 日期：2026-02-14
- 明确新增内容：新增了“Add security policy documentation”相关文档说明，补齐使用/配置指引。
- 影响范围：主要涉及 其他模块。
- 改动规模：+12 / -0 行。
- 关键文件：SECURITY.md。

#### 13. docs:Update README.md (#863)

- 提交：`[8039da2](https://github.com/bytedance/deer-flow/commit/8039da2fc4caeabf3387ec73243151203499527a)`
- 日期：2026-02-14
- 明确新增内容：新增了“Update README.md”相关文档说明，补齐使用/配置指引。
- 影响范围：主要涉及 文档。
- 改动规模：+1 / -1 行。
- 关键文件：README.md。

#### 14. docs: clarify .env configuration for Docker Compose deployment (#858)

- 提交：`[c95b271](https://github.com/bytedance/deer-flow/commit/c95b2711c39fc8fc6e9cfd3feb048c4571e5c935)`
- 日期：2026-02-14
- 明确新增内容：新增了“clarify .env configuration for Docker Compose deployment”相关文档说明，补齐使用/配置指引。
- 影响范围：主要涉及 文档、其他模块。
- 改动规模：+64 / -4 行。
- 关键文件：.env.example；README.md；README_zh.md。

#### 15. docs: update LICENSE

- 提交：`[88e8992](https://github.com/bytedance/deer-flow/commit/88e89921b9d91d6ecad19e83ad103e2f38b2e59b)`
- 日期：2026-02-13
- 明确新增内容：新增了“update LICENSE”相关文档说明，补齐使用/配置指引。
- 影响范围：主要涉及 其他模块。
- 改动规模：+2 / -1 行。
- 关键文件：LICENSE。

#### 16. feat(tool): Adding license header check and apply tool (#857)

- 提交：`[56b8c3a](https://github.com/bytedance/deer-flow/commit/56b8c3a496988dd095402d611cd9bca49dfd8487)`
- 日期：2026-02-13
- 明确新增内容：新增了“Adding license header check and apply tool”功能。
- 影响范围：主要涉及 其他模块、文档、脚本工具。
- 改动规模：+475 / -1 行。
- 关键文件：LICENSE_HEADER；LICENSE_HEADER_TS；Makefile；docs/LICENSE_HEADERS.md；pre-commit；scripts/license_header.py。

#### 17. docs: update README.md

- 提交：`[8f44ca5](https://github.com/bytedance/deer-flow/commit/8f44ca595b161a91e9e4abb679992ffb6526c248)`
- 日期：2026-02-13
- 明确新增内容：新增了“update README.md”相关文档说明，补齐使用/配置指引。
- 影响范围：主要涉及 文档、前端。
- 改动规模：+14 / -4 行。
- 关键文件：README.md；frontend/src/components/workspace/settings/about-content.ts。

#### 18. docs: update README.md

- 提交：`[15df224](https://github.com/bytedance/deer-flow/commit/15df224856f7821ff595f3d213b454630d6caf79)`
- 日期：2026-02-13
- 明确新增内容：新增了“update README.md”相关文档说明，补齐使用/配置指引。
- 影响范围：主要涉及 文档。
- 改动规模：+102 / -15 行。
- 关键文件：README.md。

#### 19. docs(ppt-generation): enforce sequential slide image generation

- 提交：`[e87fd74](https://github.com/bytedance/deer-flow/commit/e87fd74e175506df7f4a9de575b68df4d98c4108)`
- 日期：2026-02-11
- 明确新增内容：新增了“enforce sequential slide image generation”相关文档说明，补齐使用/配置指引。
- 影响范围：主要涉及 技能体系。
- 改动规模：+2 / -1 行。
- 关键文件：skills/public/ppt-generation/SKILL.md。

#### 20. feat: make max concurrent subagents configurable via runtime config

- 提交：`[770d92f](https://github.com/bytedance/deer-flow/commit/770d92fe364240d485b1db33730bf14908dc9580)`
- 日期：2026-02-11
- 明确新增内容：引入了“make max concurrent subagents configurable via runtime config”相关功能改进。
- 影响范围：主要涉及 后端。
- 改动规模：+75 / -52 行。
- 关键文件：backend/debug.py；backend/src/agents/lead_agent/agent.py；backend/src/agents/lead_agent/prompt.py；backend/src/agents/middlewares/subagent_limit_middleware.py；backend/src/subagents/executor.py。

#### 21. feat: enable skills support for subagents

- 提交：`[4a85c5d](https://github.com/bytedance/deer-flow/commit/4a85c5de7bccf30e21702c7889b7e49af8f0135d)`
- 日期：2026-02-11
- 明确新增内容：新增了对“enable skills support for subagents”的支持能力。
- 影响范围：主要涉及 后端。
- 改动规模：+61 / -42 行。
- 关键文件：backend/src/agents/lead_agent/prompt.py；backend/src/tools/builtins/task_tool.py。

#### 22. chore: add pnpm-workspace.yaml

- 提交：`[ebf4ec2](https://github.com/bytedance/deer-flow/commit/ebf4ec2786786d25cfdb817317dad4d34714447c)`
- 日期：2026-02-10
- 明确新增内容：新增了“pnpm-workspace.yaml”功能。
- 影响范围：主要涉及 前端。
- 改动规模：+2 / -0 行。
- 关键文件：frontend/pnpm-workspace.yaml。

#### 23. chore: add .npmrc back

- 提交：`[eb287f0](https://github.com/bytedance/deer-flow/commit/eb287f095af421c1f82a283da48aac6ba9ce9fe7)`
- 日期：2026-02-10
- 明确新增内容：新增了“.npmrc back”功能。
- 影响范围：主要涉及 前端。
- 改动规模：+2 / -0 行。
- 关键文件：frontend/.npmrc。

#### 24. docs: 添加技能名称冲突修复的详细文档

- 提交：`[c8f7bc2](https://github.com/bytedance/deer-flow/commit/c8f7bc28e16b7848eea23a4c18dbbfacc1c6b7a0)`
- 日期：2026-02-10
- 明确新增内容：新增了“添加技能名称冲突修复的详细文档”相关文档说明，补齐使用/配置指引。
- 影响范围：主要涉及 文档。
- 改动规模：+865 / -0 行。
- 关键文件：docs/SKILL_NAME_CONFLICT_FIX.md。

#### 25. feat: 改进设置页面UI和国际化支持 / Improve settings pages UI and i18n support

- 提交：`[f87d567](https://github.com/bytedance/deer-flow/commit/f87d5678f3bd000e1e4d16e14f52cfe1fbfb1eaa)`
- 日期：2026-02-10
- 明确新增内容：新增了对“改进设置页面UI和国际化支持 / Improve settings pages UI and i18n support”的支持能力。
- 影响范围：主要涉及 前端。
- 改动规模：+82 / -49 行。
- 关键文件：frontend/package.json；frontend/pnpm-lock.yaml；frontend/src/components/workspace/settings/memory-settings-page.tsx；frontend/src/components/workspace/settings/skill-settings-page.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts；frontend/src/core/i18n/locales/zh-CN.ts；frontend/src/core/streamdown/plugins.ts。

#### 26. Merge branch 'experimental' of github.com:hetaoBackend/deer-flow into feat/citations

- 提交：`[d51e6e2](https://github.com/bytedance/deer-flow/commit/d51e6e2f435fd3096e03aa045978060a018eb560)`
- 日期：2026-02-09
- 明确新增内容：引入了“Merge branch 'experimental' of github.com:hetaoBackend/deer-flow into feat/citations”相关功能改进。
- 影响范围：主要涉及 容器部署、后端、其他模块。
- 改动规模：+981 / -94 行。
- 关键文件：.dockerignore；CONTRIBUTING.md；Makefile；README.md；backend/Dockerfile；backend/langgraph.json；backend/pyproject.toml；backend/src/agents/lead_agent/agent.py。

#### 27. Merge branch 'experimental' of github.com:hetaoBackend/deer-flow into feat/citations

- 提交：`[1af14bf](https://github.com/bytedance/deer-flow/commit/1af14bf7e4e46d7fc45ebccd3ae69b30f28e445b)`
- 日期：2026-02-09
- 明确新增内容：引入了“Merge branch 'experimental' of github.com:hetaoBackend/deer-flow into feat/citations”相关功能改进。
- 影响范围：主要涉及 容器部署、后端、其他模块。
- 改动规模：+981 / -94 行。
- 关键文件：.dockerignore；CONTRIBUTING.md；Makefile；README.md；backend/Dockerfile；backend/langgraph.json；backend/pyproject.toml；backend/src/agents/lead_agent/agent.py。

#### 28. Add Kubernetes-based sandbox provider for multi-instance support (#19)

- 提交：`[7b7e32f](https://github.com/bytedance/deer-flow/commit/7b7e32f2625421392b8a95b4cad4cb765e52e481)`
- 日期：2026-02-09
- 明确新增内容：新增了对“Add Kubernetes-based sandbox provider for multi-instance support”的支持能力。
- 影响范围：主要涉及 容器部署、后端、其他模块。
- 改动规模：+981 / -94 行。
- 关键文件：.dockerignore；CONTRIBUTING.md；Makefile；README.md；backend/Dockerfile；backend/langgraph.json；backend/pyproject.toml；backend/src/agents/lead_agent/agent.py。

#### 29. Add Kubernetes-based sandbox provider for multi-instance support (#19)

- 提交：`[b6da3a2](https://github.com/bytedance/deer-flow/commit/b6da3a219e30c64682058e3440e4322644e3ff77)`
- 日期：2026-02-09
- 明确新增内容：新增了对“Add Kubernetes-based sandbox provider for multi-instance support”的支持能力。
- 影响范围：主要涉及 容器部署、后端、其他模块。
- 改动规模：+981 / -94 行。
- 关键文件：.dockerignore；CONTRIBUTING.md；Makefile；README.md；backend/Dockerfile；backend/langgraph.json；backend/pyproject.toml；backend/src/agents/lead_agent/agent.py。

#### 30. Merge upstream/experimental: resolve conflicts (keep feat/citations)

- 提交：`[c89bd9e](https://github.com/bytedance/deer-flow/commit/c89bd9edc9c4f8953a5b01304f8709eba1c073cc)`
- 日期：2026-02-09
- 明确新增内容：引入了“Merge upstream/experimental: resolve conflicts (keep feat/citations)”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+78 / -32 行。
- 关键文件：frontend/src/components/workspace/artifacts/artifact-file-detail.tsx；frontend/src/components/workspace/messages/message-list-item.tsx；frontend/src/components/workspace/messages/subtask-card.tsx。

#### 31. Merge upstream/experimental: resolve conflicts (keep feat/citations)

- 提交：`[8a2cac7](https://github.com/bytedance/deer-flow/commit/8a2cac7b5a9a3cbdc2283b78d9deead85edea5ff)`
- 日期：2026-02-09
- 明确新增内容：引入了“Merge upstream/experimental: resolve conflicts (keep feat/citations)”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+78 / -32 行。
- 关键文件：frontend/src/components/workspace/artifacts/artifact-file-detail.tsx；frontend/src/components/workspace/messages/message-list-item.tsx；frontend/src/components/workspace/messages/subtask-card.tsx。

#### 32. feat(citations): inline citation links with [citation:Title](URL)

- 提交：`[2f50e5d](https://github.com/bytedance/deer-flow/commit/2f50e5d96946859127a202d26b625ef3ba624487)`
- 日期：2026-02-09
- 明确新增内容：引入了“inline citation links with [citation:Title](URL)”相关功能改进。
- 影响范围：主要涉及 前端、后端。
- 改动规模：+133 / -27 行。
- 关键文件：backend/src/agents/lead_agent/prompt.py；backend/src/subagents/builtins/general_purpose.py；frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/workspace/artifacts/artifact-file-detail.tsx；frontend/src/components/workspace/citations/citation-link.tsx；frontend/src/components/workspace/messages/markdown-content.tsx；frontend/src/components/workspace/messages/message-group.tsx；frontend/src/components/workspace/messages/message-list-item.tsx。

#### 33. feat: basic implmenetation

- 提交：`[69c8b41](https://github.com/bytedance/deer-flow/commit/69c8b411866bdafd82b48caf7c9c3fb34ba454f6)`
- 日期：2026-02-09
- 明确新增内容：引入了“basic implmenetation”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+110 / -34 行。
- 关键文件：frontend/src/components/workspace/messages/markdown-content.tsx；frontend/src/components/workspace/messages/message-list-item.tsx；frontend/src/components/workspace/messages/message-list.tsx。

#### 34. feat: basic implmenetation

- 提交：`[554ec7a](https://github.com/bytedance/deer-flow/commit/554ec7a91e56e454058baf8bb67fb8951fbb4e82)`
- 日期：2026-02-09
- 明确新增内容：引入了“basic implmenetation”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+110 / -34 行。
- 关键文件：frontend/src/components/workspace/messages/markdown-content.tsx；frontend/src/components/workspace/messages/message-list-item.tsx；frontend/src/components/workspace/messages/message-list.tsx。

#### 35. feat: update translations

- 提交：`[cbe0f3b](https://github.com/bytedance/deer-flow/commit/cbe0f3b32fed02386114365c5385f49451d8ebd6)`
- 日期：2026-02-09
- 明确新增内容：引入了“update translations”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+2 / -2 行。
- 关键文件：frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/zh-CN.ts。

#### 36. feat: update translations

- 提交：`[738c509](https://github.com/bytedance/deer-flow/commit/738c509c7e256ea5ef2a5e3545fb9f32a2f57484)`
- 日期：2026-02-09
- 明确新增内容：引入了“update translations”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+2 / -2 行。
- 关键文件：frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/zh-CN.ts。

#### 37. feat: enforce subagent concurrency limit of 3 per turn with batch execution

- 提交：`[f68b3c2](https://github.com/bytedance/deer-flow/commit/f68b3c26c35b677bef45d8ae20a034c130672182)`
- 日期：2026-02-09
- 明确新增内容：引入了“enforce subagent concurrency limit of 3 per turn with batch execution”相关功能改进。
- 影响范围：主要涉及 后端、前端。
- 改动规模：+1321 / -1894 行。
- 关键文件：backend/src/agents/lead_agent/prompt.py；frontend/pnpm-lock.yaml。

#### 38. feat: enforce subagent concurrency limit of 3 per turn with batch execution

- 提交：`[3aa45ff](https://github.com/bytedance/deer-flow/commit/3aa45ff035d7c1a8cc7722b12672a0534c90107a)`
- 日期：2026-02-09
- 明确新增内容：引入了“enforce subagent concurrency limit of 3 per turn with batch execution”相关功能改进。
- 影响范围：主要涉及 后端、前端。
- 改动规模：+1321 / -1894 行。
- 关键文件：backend/src/agents/lead_agent/prompt.py；frontend/pnpm-lock.yaml。

#### 39. chore: add pre-commit hook to reject *@bytedance.com author/committer email

- 提交：`[804d988](https://github.com/bytedance/deer-flow/commit/804d988002d6598399c997c62c902bd87a3e38ca)`
- 日期：2026-02-09
- 明确新增内容：新增了“pre-commit hook to reject *@bytedance.com author/committer email”功能。
- 影响范围：主要涉及 其他模块。
- 改动规模：+29 / -0 行。
- 关键文件：.githooks/pre-commit。

#### 40. chore: add pre-commit hook to reject *@bytedance.com author/committer email

- 提交：`[79c85d6](https://github.com/bytedance/deer-flow/commit/79c85d641054799c864a2d5cc3e0d34b6e7355b2)`
- 日期：2026-02-09
- 明确新增内容：新增了“pre-commit hook to reject *@bytedance.com author/committer email”功能。
- 影响范围：主要涉及 其他模块。
- 改动规模：+29 / -0 行。
- 关键文件：.githooks/pre-commit。

#### 41. feat: add DanglingToolCallMiddleware and SubagentLimitMiddleware

- 提交：`[caf12da](https://github.com/bytedance/deer-flow/commit/caf12da0f2062a8cd81a76df07585eba27d5077d)`
- 日期：2026-02-09
- 明确新增内容：新增了“DanglingToolCallMiddleware and SubagentLimitMiddleware”功能。
- 影响范围：主要涉及 后端。
- 改动规模：+155 / -32 行。
- 关键文件：backend/CLAUDE.md；backend/src/agents/lead_agent/agent.py；backend/src/agents/middlewares/dangling_tool_call_middleware.py；backend/src/agents/middlewares/subagent_limit_middleware.py；backend/src/subagents/executor.py；backend/src/tools/builtins/task_tool.py。

#### 42. feat: add DanglingToolCallMiddleware and SubagentLimitMiddleware

- 提交：`[48e3039](https://github.com/bytedance/deer-flow/commit/48e303905567576ee9939ca02420688e8d532c91)`
- 日期：2026-02-09
- 明确新增内容：新增了“DanglingToolCallMiddleware and SubagentLimitMiddleware”功能。
- 影响范围：主要涉及 后端。
- 改动规模：+155 / -32 行。
- 关键文件：backend/CLAUDE.md；backend/src/agents/lead_agent/agent.py；backend/src/agents/middlewares/dangling_tool_call_middleware.py；backend/src/agents/middlewares/subagent_limit_middleware.py；backend/src/subagents/executor.py；backend/src/tools/builtins/task_tool.py。

#### 43. feat: citations prompts, path_utils, and citation code cleanup

- 提交：`[2a39947](https://github.com/bytedance/deer-flow/commit/2a399478307bdd827632bdeddf5baf11c1412d22)`
- 日期：2026-02-09
- 明确新增内容：引入了“citations prompts, path_utils, and citation code cleanup”相关功能改进。
- 影响范围：主要涉及 后端、前端。
- 改动规模：+103 / -174 行。
- 关键文件：backend/src/agents/lead_agent/prompt.py；backend/src/gateway/path_utils.py；backend/src/gateway/routers/artifacts.py；backend/src/gateway/routers/skills.py；backend/src/subagents/builtins/general_purpose.py；frontend/src/core/citations/utils.ts。

#### 44. feat: citations prompts, path_utils, and citation code cleanup

- 提交：`[eb5782b](https://github.com/bytedance/deer-flow/commit/eb5782b93bc36a600c6b2e1713310f829c9b981d)`
- 日期：2026-02-09
- 明确新增内容：引入了“citations prompts, path_utils, and citation code cleanup”相关功能改进。
- 影响范围：主要涉及 后端、前端。
- 改动规模：+103 / -174 行。
- 关键文件：backend/src/agents/lead_agent/prompt.py；backend/src/gateway/path_utils.py；backend/src/gateway/routers/artifacts.py；backend/src/gateway/routers/skills.py；backend/src/subagents/builtins/general_purpose.py；frontend/src/core/citations/utils.ts。

#### 45. feat(frontend): add mode hover guide and adjust mode i18n

- 提交：`[d265bdb](https://github.com/bytedance/deer-flow/commit/d265bdb24519e313ee97d615b58fdb6fa7dc4e22)`
- 日期：2026-02-09
- 明确新增内容：新增了“add mode hover guide and adjust mode i18n”相关文档说明，补齐使用/配置指引。
- 影响范围：主要涉及 前端。
- 改动规模：+101 / -29 行。
- 关键文件：frontend/src/components/workspace/input-box.tsx；frontend/src/components/workspace/mode-hover-guide.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/zh-CN.ts。

#### 46. feat(frontend): add mode hover guide and adjust mode i18n

- 提交：`[5e000f1](https://github.com/bytedance/deer-flow/commit/5e000f1a99128e9cf289ebd0e31bda1716252879)`
- 日期：2026-02-09
- 明确新增内容：新增了“add mode hover guide and adjust mode i18n”相关文档说明，补齐使用/配置指引。
- 影响范围：主要涉及 前端。
- 改动规模：+101 / -29 行。
- 关键文件：frontend/src/components/workspace/input-box.tsx；frontend/src/components/workspace/mode-hover-guide.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/zh-CN.ts。

#### 47. feat: update workspace header to conditionally render title based on environment variable

- 提交：`[8b053a4](https://github.com/bytedance/deer-flow/commit/8b053a4415e8a9ac007e4769f62eb5d9da499175)`
- 日期：2026-02-09
- 明确新增内容：引入了“update workspace header to conditionally render title based on environment variable”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+10 / -3 行。
- 关键文件：frontend/src/components/workspace/workspace-header.tsx。

#### 48. feat: update workspace header to conditionally render title based on environment variable

- 提交：`[fd4f6c6](https://github.com/bytedance/deer-flow/commit/fd4f6c679aeb384daf2f008d036ebf7579786b92)`
- 日期：2026-02-09
- 明确新增内容：引入了“update workspace header to conditionally render title based on environment variable”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+10 / -3 行。
- 关键文件：frontend/src/components/workspace/workspace-header.tsx。

#### 49. feat: update workspace header to conditionally render title based on environment variable

- 提交：`[3ad2cd9](https://github.com/bytedance/deer-flow/commit/3ad2cd936fd0b47b310f9eddfe98ec5b1056b220)`
- 日期：2026-02-09
- 明确新增内容：引入了“update workspace header to conditionally render title based on environment variable”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+10 / -3 行。
- 关键文件：frontend/src/components/workspace/workspace-header.tsx。

#### 50. feat: make it golden

- 提交：`[305e896](https://github.com/bytedance/deer-flow/commit/305e8969ef63cda3085221dc36ecae6cc72b571c)`
- 日期：2026-02-09
- 明确新增内容：引入了“make it golden”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+3 / -1 行。
- 关键文件：frontend/src/components/ui/word-rotate.tsx。

#### 51. feat: make it golden

- 提交：`[189fcab](https://github.com/bytedance/deer-flow/commit/189fcab4c59b30c0b53a8f398bf2b324634e01ad)`
- 日期：2026-02-09
- 明确新增内容：引入了“make it golden”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+3 / -1 行。
- 关键文件：frontend/src/components/ui/word-rotate.tsx。

#### 52. feat: make it golden

- 提交：`[e626146](https://github.com/bytedance/deer-flow/commit/e6261469efec11db8fd62159074d79a91f132e68)`
- 日期：2026-02-09
- 明确新增内容：引入了“make it golden”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+3 / -1 行。
- 关键文件：frontend/src/components/ui/word-rotate.tsx。

#### 53. feat: make the title golden in Ultra mode

- 提交：`[ddbda4e](https://github.com/bytedance/deer-flow/commit/ddbda4e38f9d90c5e07ac24420ecec92c6debc40)`
- 日期：2026-02-09
- 明确新增内容：引入了“make the title golden in Ultra mode”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+13 / -6 行。
- 关键文件：frontend/src/components/workspace/welcome.tsx；frontend/src/core/i18n/locales/zh-CN.ts。

#### 54. feat: make the title golden in Ultra mode

- 提交：`[db79ab2](https://github.com/bytedance/deer-flow/commit/db79ab27f4ba15a79aa89c8a6d833f5fb90ab623)`
- 日期：2026-02-09
- 明确新增内容：引入了“make the title golden in Ultra mode”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+13 / -6 行。
- 关键文件：frontend/src/components/workspace/welcome.tsx；frontend/src/core/i18n/locales/zh-CN.ts。

#### 55. feat: make the title golden in Ultra mode

- 提交：`[76cdb0e](https://github.com/bytedance/deer-flow/commit/76cdb0e16eb5f0e242894b8e623218f3684bf2bd)`
- 日期：2026-02-09
- 明确新增内容：引入了“make the title golden in Ultra mode”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+13 / -6 行。
- 关键文件：frontend/src/components/workspace/welcome.tsx；frontend/src/core/i18n/locales/zh-CN.ts。

#### 56. feat: add mode in welcome

- 提交：`[cebf259](https://github.com/bytedance/deer-flow/commit/cebf2599c9bd518c31c5762f84cc8b77f5fb7ec4)`
- 日期：2026-02-09
- 明确新增内容：新增了“mode in welcome”功能。
- 影响范围：主要涉及 前端。
- 改动规模：+13 / -3 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/workspace/welcome.tsx。

#### 57. feat: add mode in welcome

- 提交：`[143f9f1](https://github.com/bytedance/deer-flow/commit/143f9f1f4dcd60d23755422140a7cd85dc96daea)`
- 日期：2026-02-09
- 明确新增内容：新增了“mode in welcome”功能。
- 影响范围：主要涉及 前端。
- 改动规模：+13 / -3 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/workspace/welcome.tsx。

#### 58. feat: add mode in welcome

- 提交：`[d197ee8](https://github.com/bytedance/deer-flow/commit/d197ee8f288cf33e854aa90a4c201b49d6c23b63)`
- 日期：2026-02-09
- 明确新增内容：新增了“mode in welcome”功能。
- 影响范围：主要涉及 前端。
- 改动规模：+13 / -3 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/workspace/welcome.tsx。

#### 59. feat: set golden color for ultra

- 提交：`[25b60e7](https://github.com/bytedance/deer-flow/commit/25b60e732f2a3c6a38f6fdcf91cc86f9f44e8c0b)`
- 日期：2026-02-09
- 明确新增内容：引入了“set golden color for ultra”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+27 / -7 行。
- 关键文件：frontend/src/components/workspace/input-box.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/styles/globals.css。

#### 60. feat: set golden color for ultra

- 提交：`[9da3a1d](https://github.com/bytedance/deer-flow/commit/9da3a1dcb255b7dce2e99428d24960cbc32f80ce)`
- 日期：2026-02-09
- 明确新增内容：引入了“set golden color for ultra”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+27 / -7 行。
- 关键文件：frontend/src/components/workspace/input-box.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/styles/globals.css。

#### 61. feat: set golden color for ultra

- 提交：`[d9b6077](https://github.com/bytedance/deer-flow/commit/d9b60778a95005f95ca255b6be72d97053c611ae)`
- 日期：2026-02-09
- 明确新增内容：引入了“set golden color for ultra”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+27 / -7 行。
- 关键文件：frontend/src/components/workspace/input-box.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/styles/globals.css。

#### 62. feat: rewording

- 提交：`[f146e35](https://github.com/bytedance/deer-flow/commit/f146e35ee77b00cc33190624bafdb888b1b12f3d)`
- 日期：2026-02-08
- 明确新增内容：引入了“rewording”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+12 / -13 行。
- 关键文件：frontend/src/components/workspace/messages/message-list.tsx；frontend/src/components/workspace/messages/subtask-card.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/zh-CN.ts。

#### 63. feat: rewording

- 提交：`[a4e1e1a](https://github.com/bytedance/deer-flow/commit/a4e1e1a95e6746e4671256dbed4db83a4aa11802)`
- 日期：2026-02-08
- 明确新增内容：引入了“rewording”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+12 / -13 行。
- 关键文件：frontend/src/components/workspace/messages/message-list.tsx；frontend/src/components/workspace/messages/subtask-card.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/zh-CN.ts。

#### 64. feat: rewording

- 提交：`[eb9af00](https://github.com/bytedance/deer-flow/commit/eb9af00d1d9c0c9004a3b8450e023093d8770c7d)`
- 日期：2026-02-08
- 明确新增内容：引入了“rewording”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+12 / -13 行。
- 关键文件：frontend/src/components/workspace/messages/message-list.tsx；frontend/src/components/workspace/messages/subtask-card.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/zh-CN.ts。

#### 65. feat: disallow present_files tool in subagents and add market-analysis skill

- 提交：`[6eb4cdd](https://github.com/bytedance/deer-flow/commit/6eb4cdd3ecf63f738e47f1b3edec5bb8d8df28b5)`
- 日期：2026-02-08
- 明确新增内容：新增了“disallow present_files tool in subagents and add market-analysis skill”功能。
- 影响范围：主要涉及 后端、技能体系。
- 改动规模：+210 / -2 行。
- 关键文件：backend/src/subagents/builtins/bash_agent.py；backend/src/subagents/builtins/general_purpose.py；skills/public/market-analysis/SKILL.md。

#### 66. feat: disallow present_files tool in subagents and add market-analysis skill

- 提交：`[f9b769b](https://github.com/bytedance/deer-flow/commit/f9b769b5c3d50b0f6fc2f56e316c04564de4f295)`
- 日期：2026-02-08
- 明确新增内容：新增了“disallow present_files tool in subagents and add market-analysis skill”功能。
- 影响范围：主要涉及 后端、技能体系。
- 改动规模：+210 / -2 行。
- 关键文件：backend/src/subagents/builtins/bash_agent.py；backend/src/subagents/builtins/general_purpose.py；skills/public/market-analysis/SKILL.md。

#### 67. feat: disallow present_files tool in subagents and add market-analysis skill

- 提交：`[54f2f1b](https://github.com/bytedance/deer-flow/commit/54f2f1bd3aed3ae98468e8d665481faad321ad95)`
- 日期：2026-02-08
- 明确新增内容：新增了“disallow present_files tool in subagents and add market-analysis skill”功能。
- 影响范围：主要涉及 后端、技能体系。
- 改动规模：+210 / -2 行。
- 关键文件：backend/src/subagents/builtins/bash_agent.py；backend/src/subagents/builtins/general_purpose.py；skills/public/market-analysis/SKILL.md。

#### 68. feat: add special effect for Ultra mode

- 提交：`[8a23515](https://github.com/bytedance/deer-flow/commit/8a2351593cd9609f0ef5177ffe18c62c1b838183)`
- 日期：2026-02-08
- 明确新增内容：新增了“special effect for Ultra mode”功能。
- 影响范围：主要涉及 前端。
- 改动规模：+115 / -90 行。
- 关键文件：frontend/src/components/workspace/messages/subtask-card.tsx；frontend/src/styles/globals.css。

#### 69. feat: add special effect for Ultra mode

- 提交：`[d36fbcd](https://github.com/bytedance/deer-flow/commit/d36fbcdfc1d2710fd0e41ca0b9af210a34a77bd7)`
- 日期：2026-02-08
- 明确新增内容：新增了“special effect for Ultra mode”功能。
- 影响范围：主要涉及 前端。
- 改动规模：+115 / -90 行。
- 关键文件：frontend/src/components/workspace/messages/subtask-card.tsx；frontend/src/styles/globals.css。

#### 70. feat: add special effect for Ultra mode

- 提交：`[0d55230](https://github.com/bytedance/deer-flow/commit/0d55230016476d536e03ed25a162224160b5f64f)`
- 日期：2026-02-08
- 明确新增内容：新增了“special effect for Ultra mode”功能。
- 影响范围：主要涉及 前端。
- 改动规模：+115 / -90 行。
- 关键文件：frontend/src/components/workspace/messages/subtask-card.tsx；frontend/src/styles/globals.css。

#### 71. docs: revise backend README and CLAUDE.md to reflect full architecture

- 提交：`[2703eb0](https://github.com/bytedance/deer-flow/commit/2703eb0b22f92b655fb4dc0cafa257d1e11a56ea)`
- 日期：2026-02-08
- 明确新增内容：新增了“revise backend README and CLAUDE.md to reflect full architecture”相关文档说明，补齐使用/配置指引。
- 影响范围：主要涉及 后端、文档。
- 改动规模：+403 / -379 行。
- 关键文件：README.md；backend/CLAUDE.md；backend/README.md。

#### 72. docs: revise backend README and CLAUDE.md to reflect full architecture

- 提交：`[fdd25c1](https://github.com/bytedance/deer-flow/commit/fdd25c1bb872de20ef27966a38fff7607e8ae949)`
- 日期：2026-02-08
- 明确新增内容：新增了“revise backend README and CLAUDE.md to reflect full architecture”相关文档说明，补齐使用/配置指引。
- 影响范围：主要涉及 后端、文档。
- 改动规模：+403 / -379 行。
- 关键文件：README.md；backend/CLAUDE.md；backend/README.md。

#### 73. docs: revise backend README and CLAUDE.md to reflect full architecture

- 提交：`[d891a8a](https://github.com/bytedance/deer-flow/commit/d891a8a37ce1d4c15c4bf5842e43fc876065ae02)`
- 日期：2026-02-08
- 明确新增内容：新增了“revise backend README and CLAUDE.md to reflect full architecture”相关文档说明，补齐使用/配置指引。
- 影响范围：主要涉及 后端、文档。
- 改动规模：+403 / -379 行。
- 关键文件：README.md；backend/CLAUDE.md；backend/README.md。

#### 74. feat: add realtime subagent status report

- 提交：`[010aba1](https://github.com/bytedance/deer-flow/commit/010aba1e282c032a1b9f0257d7c79620021248b1)`
- 日期：2026-02-08
- 明确新增内容：新增了“realtime subagent status report”功能。
- 影响范围：主要涉及 前端。
- 改动规模：+91 / -10 行。
- 关键文件：frontend/src/components/workspace/messages/subtask-card.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts；frontend/src/core/i18n/locales/zh-CN.ts；frontend/src/core/tasks/context.tsx；frontend/src/core/tasks/types.ts；frontend/src/core/threads/hooks.ts；frontend/src/core/tools/utils.ts。

#### 75. feat: add realtime subagent status report

- 提交：`[7ed1be3](https://github.com/bytedance/deer-flow/commit/7ed1be32fd86399ee198a817d24ff1515acd9ab8)`
- 日期：2026-02-08
- 明确新增内容：新增了“realtime subagent status report”功能。
- 影响范围：主要涉及 前端。
- 改动规模：+91 / -10 行。
- 关键文件：frontend/src/components/workspace/messages/subtask-card.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts；frontend/src/core/i18n/locales/zh-CN.ts；frontend/src/core/tasks/context.tsx；frontend/src/core/tasks/types.ts；frontend/src/core/threads/hooks.ts；frontend/src/core/tools/utils.ts。

#### 76. feat: add realtime subagent status report

- 提交：`[7d4b5eb](https://github.com/bytedance/deer-flow/commit/7d4b5eb3cae5da2f3baadeb5f97d63adc741a8d4)`
- 日期：2026-02-08
- 明确新增内容：新增了“realtime subagent status report”功能。
- 影响范围：主要涉及 前端。
- 改动规模：+91 / -10 行。
- 关键文件：frontend/src/components/workspace/messages/subtask-card.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts；frontend/src/core/i18n/locales/zh-CN.ts；frontend/src/core/tasks/context.tsx；frontend/src/core/tasks/types.ts；frontend/src/core/threads/hooks.ts；frontend/src/core/tools/utils.ts。

#### 77. feat: limit concurrent subagents to 3 per turn

- 提交：`[808e028](https://github.com/bytedance/deer-flow/commit/808e02833858a3494cc075d1a261806853fc5f85)`
- 日期：2026-02-08
- 明确新增内容：引入了“limit concurrent subagents to 3 per turn”相关功能改进。
- 影响范围：主要涉及 后端。
- 改动规模：+51 / -35 行。
- 关键文件：backend/src/agents/lead_agent/prompt.py；backend/src/subagents/executor.py；backend/src/tools/builtins/task_tool.py。

#### 78. feat: limit concurrent subagents to 3 per turn

- 提交：`[9e2b3f1](https://github.com/bytedance/deer-flow/commit/9e2b3f1f3973a6b64d3dcb5ce29d4250a1ae1f33)`
- 日期：2026-02-08
- 明确新增内容：引入了“limit concurrent subagents to 3 per turn”相关功能改进。
- 影响范围：主要涉及 后端。
- 改动规模：+51 / -35 行。
- 关键文件：backend/src/agents/lead_agent/prompt.py；backend/src/subagents/executor.py；backend/src/tools/builtins/task_tool.py。

#### 79. feat: limit concurrent subagents to 3 per turn

- 提交：`[faa327b](https://github.com/bytedance/deer-flow/commit/faa327b3cd04cc75f309e0c6987f9919133a2539)`
- 日期：2026-02-08
- 明确新增内容：引入了“limit concurrent subagents to 3 per turn”相关功能改进。
- 影响范围：主要涉及 后端。
- 改动规模：+51 / -35 行。
- 关键文件：backend/src/agents/lead_agent/prompt.py；backend/src/subagents/executor.py；backend/src/tools/builtins/task_tool.py。

#### 80. feat: add real-time streaming of subagent AI messages

- 提交：`[96bace7](https://github.com/bytedance/deer-flow/commit/96bace7ab6d68d148ebb58b85918edcd57790ee9)`
- 日期：2026-02-08
- 明确新增内容：新增了“real-time streaming of subagent AI messages”功能。
- 影响范围：主要涉及 后端。
- 改动规模：+107 / -51 行。
- 关键文件：backend/src/subagents/executor.py；backend/src/tools/builtins/task_tool.py。

#### 81. feat: add real-time streaming of subagent AI messages

- 提交：`[0a27a75](https://github.com/bytedance/deer-flow/commit/0a27a7561af88783563b37945c1ce98f49fb4094)`
- 日期：2026-02-08
- 明确新增内容：新增了“real-time streaming of subagent AI messages”功能。
- 影响范围：主要涉及 后端。
- 改动规模：+107 / -51 行。
- 关键文件：backend/src/subagents/executor.py；backend/src/tools/builtins/task_tool.py。

#### 82. feat: add real-time streaming of subagent AI messages

- 提交：`[5477294](https://github.com/bytedance/deer-flow/commit/54772947cbee69521fac263a26f705f6a8d906d6)`
- 日期：2026-02-08
- 明确新增内容：新增了“real-time streaming of subagent AI messages”功能。
- 影响范围：主要涉及 后端。
- 改动规模：+107 / -51 行。
- 关键文件：backend/src/subagents/executor.py；backend/src/tools/builtins/task_tool.py。

#### 83. feat: rewording and add initial animation

- 提交：`[0355493](https://github.com/bytedance/deer-flow/commit/0355493a1604ad7df1b564ec3091986f351a8a1a)`
- 日期：2026-02-08
- 明确新增内容：新增了“rewording and add initial animation”功能。
- 影响范围：主要涉及 前端。
- 改动规模：+45 / -12 行。
- 关键文件：frontend/src/components/landing/hero.tsx；frontend/src/components/landing/sections/whats-new-section.tsx；frontend/src/components/workspace/welcome.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts；frontend/src/core/i18n/locales/zh-CN.ts；frontend/src/styles/globals.css。

#### 84. feat: rewording and add initial animation

- 提交：`[2b3dc96](https://github.com/bytedance/deer-flow/commit/2b3dc96e400607877b9bd878d5b3f83887de432d)`
- 日期：2026-02-08
- 明确新增内容：新增了“rewording and add initial animation”功能。
- 影响范围：主要涉及 前端。
- 改动规模：+45 / -12 行。
- 关键文件：frontend/src/components/landing/hero.tsx；frontend/src/components/landing/sections/whats-new-section.tsx；frontend/src/components/workspace/welcome.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts；frontend/src/core/i18n/locales/zh-CN.ts；frontend/src/styles/globals.css。

#### 85. feat: rewording and add initial animation

- 提交：`[ff7437f](https://github.com/bytedance/deer-flow/commit/ff7437f83015cf75d36c982fae2d2c95827731d6)`
- 日期：2026-02-08
- 明确新增内容：新增了“rewording and add initial animation”功能。
- 影响范围：主要涉及 前端。
- 改动规模：+45 / -12 行。
- 关键文件：frontend/src/components/landing/hero.tsx；frontend/src/components/landing/sections/whats-new-section.tsx；frontend/src/components/workspace/welcome.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts；frontend/src/core/i18n/locales/zh-CN.ts；frontend/src/styles/globals.css。

#### 86. feat: add ambilight

- 提交：`[de8ff9d](https://github.com/bytedance/deer-flow/commit/de8ff9d33675e4c90f38762611bde97a9687ad4e)`
- 日期：2026-02-07
- 明确新增内容：新增了“ambilight”功能。
- 影响范围：主要涉及 前端。
- 改动规模：+44 / -0 行。
- 关键文件：frontend/src/styles/globals.css。

#### 87. feat: add ambilight

- 提交：`[01aa035](https://github.com/bytedance/deer-flow/commit/01aa0359056564f41470832740a91aae539ecebe)`
- 日期：2026-02-07
- 明确新增内容：新增了“ambilight”功能。
- 影响范围：主要涉及 前端。
- 改动规模：+44 / -0 行。
- 关键文件：frontend/src/styles/globals.css。

#### 88. feat: add ambilight

- 提交：`[a4e89cc](https://github.com/bytedance/deer-flow/commit/a4e89cc96bf45d3f09aad45d7d3075f140fa1bc1)`
- 日期：2026-02-07
- 明确新增内容：新增了“ambilight”功能。
- 影响范围：主要涉及 前端。
- 改动规模：+44 / -0 行。
- 关键文件：frontend/src/styles/globals.css。

#### 89. feat: add handling for task timeout and enhance Streamdown plugin for word animation

- 提交：`[d9a52f0](https://github.com/bytedance/deer-flow/commit/d9a52f07e7fd3a86bcc17b8bd8feafc9c23dafa7)`
- 日期：2026-02-07
- 明确新增内容：新增了“handling for task timeout and enhance Streamdown plugin for word animation”功能。
- 影响范围：主要涉及 前端。
- 改动规模：+26 / -2 行。
- 关键文件：frontend/src/components/workspace/messages/message-list.tsx；frontend/src/components/workspace/messages/subtask-card.tsx；frontend/src/core/streamdown/plugins.ts。

#### 90. feat: add handling for task timeout and enhance Streamdown plugin for word animation

- 提交：`[99e8f22](https://github.com/bytedance/deer-flow/commit/99e8f22d1de1b97e679c7256e4e7cd13849b0f38)`
- 日期：2026-02-07
- 明确新增内容：新增了“handling for task timeout and enhance Streamdown plugin for word animation”功能。
- 影响范围：主要涉及 前端。
- 改动规模：+26 / -2 行。
- 关键文件：frontend/src/components/workspace/messages/message-list.tsx；frontend/src/components/workspace/messages/subtask-card.tsx；frontend/src/core/streamdown/plugins.ts。

#### 91. feat: add handling for task timeout and enhance Streamdown plugin for word animation

- 提交：`[0810917](https://github.com/bytedance/deer-flow/commit/0810917b69834b96e7ba3f22d2da1ee18164c0d4)`
- 日期：2026-02-07
- 明确新增内容：新增了“handling for task timeout and enhance Streamdown plugin for word animation”功能。
- 影响范围：主要涉及 前端。
- 改动规模：+26 / -2 行。
- 关键文件：frontend/src/components/workspace/messages/message-list.tsx；frontend/src/components/workspace/messages/subtask-card.tsx；frontend/src/core/streamdown/plugins.ts。

#### 92. feat: adjust position

- 提交：`[260953f](https://github.com/bytedance/deer-flow/commit/260953fb8120e606e8e9a00e377a1750af783730)`
- 日期：2026-02-07
- 明确新增内容：引入了“adjust position”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+2 / -2 行。
- 关键文件：frontend/src/components/workspace/input-box.tsx。

#### 93. feat: adjust position

- 提交：`[dce82c1](https://github.com/bytedance/deer-flow/commit/dce82c1db434a4ffbcd069cc885bd32a1dd58deb)`
- 日期：2026-02-07
- 明确新增内容：引入了“adjust position”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+2 / -2 行。
- 关键文件：frontend/src/components/workspace/input-box.tsx。

#### 94. feat: adjust position

- 提交：`[4dc3cda](https://github.com/bytedance/deer-flow/commit/4dc3cdac48e099db05c3386497df6c1785b45074)`
- 日期：2026-02-07
- 明确新增内容：引入了“adjust position”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+2 / -2 行。
- 关键文件：frontend/src/components/workspace/input-box.tsx。

#### 95. refactor: optimize task tool parameter order and improve task tracking

- 提交：`[f41d9b3](https://github.com/bytedance/deer-flow/commit/f41d9b3be586174eb9b4efc06cd3f5f2635d4ffa)`
- 日期：2026-02-07
- 明确新增内容：增强了“optimize task tool parameter order and improve task tracking”相关能力与交互体验。
- 影响范围：主要涉及 后端。
- 改动规模：+30 / -24 行。
- 关键文件：backend/src/agents/lead_agent/prompt.py；backend/src/subagents/executor.py；backend/src/tools/builtins/task_tool.py。

#### 96. refactor: optimize task tool parameter order and improve task tracking

- 提交：`[1425294](https://github.com/bytedance/deer-flow/commit/1425294f9b81eae47fb72cd927a44a9e8289b770)`
- 日期：2026-02-07
- 明确新增内容：增强了“optimize task tool parameter order and improve task tracking”相关能力与交互体验。
- 影响范围：主要涉及 后端。
- 改动规模：+30 / -24 行。
- 关键文件：backend/src/agents/lead_agent/prompt.py；backend/src/subagents/executor.py；backend/src/tools/builtins/task_tool.py。

#### 97. refactor: optimize task tool parameter order and improve task tracking

- 提交：`[a6db74b](https://github.com/bytedance/deer-flow/commit/a6db74baba0c4cff77d312831eac5621260c7ae8)`
- 日期：2026-02-07
- 明确新增内容：增强了“optimize task tool parameter order and improve task tracking”相关能力与交互体验。
- 影响范围：主要涉及 后端。
- 改动规模：+30 / -24 行。
- 关键文件：backend/src/agents/lead_agent/prompt.py；backend/src/subagents/executor.py；backend/src/tools/builtins/task_tool.py。

#### 98. feat: support subtasks

- 提交：`[3e2883e](https://github.com/bytedance/deer-flow/commit/3e2883e2a36fd0b81577df0dab18dcd6a7d966fd)`
- 日期：2026-02-07
- 明确新增内容：新增了对“subtasks”的支持能力。
- 影响范围：主要涉及 前端。
- 改动规模：+433 / -109 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/layout.tsx；frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/ui/shine-border.tsx；frontend/src/components/workspace/artifacts/artifact-file-list.tsx；frontend/src/components/workspace/input-box.tsx；frontend/src/components/workspace/messages/message-group.tsx；frontend/src/components/workspace/messages/message-list.tsx；frontend/src/components/workspace/messages/subtask-card.tsx。

#### 99. feat: support subtasks

- 提交：`[a016332](https://github.com/bytedance/deer-flow/commit/a016332a37d72f273bffcef9791e16b557630f09)`
- 日期：2026-02-07
- 明确新增内容：新增了对“subtasks”的支持能力。
- 影响范围：主要涉及 前端。
- 改动规模：+433 / -109 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/layout.tsx；frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/ui/shine-border.tsx；frontend/src/components/workspace/artifacts/artifact-file-list.tsx；frontend/src/components/workspace/input-box.tsx；frontend/src/components/workspace/messages/message-group.tsx；frontend/src/components/workspace/messages/message-list.tsx；frontend/src/components/workspace/messages/subtask-card.tsx。

#### 100. feat: support subtasks

- 提交：`[46798c0](https://github.com/bytedance/deer-flow/commit/46798c093195b0c37415de6cc5df955117a13add)`
- 日期：2026-02-07
- 明确新增内容：新增了对“subtasks”的支持能力。
- 影响范围：主要涉及 前端。
- 改动规模：+433 / -109 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/layout.tsx；frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/ui/shine-border.tsx；frontend/src/components/workspace/artifacts/artifact-file-list.tsx；frontend/src/components/workspace/input-box.tsx；frontend/src/components/workspace/messages/message-group.tsx；frontend/src/components/workspace/messages/message-list.tsx；frontend/src/components/workspace/messages/subtask-card.tsx。

#### 101. Merge pull request #25 from LofiSu/feat/citations

- 提交：`[e4eb4a6](https://github.com/bytedance/deer-flow/commit/e4eb4a65cf1595bd71cc3b6ed3b9d3f69b1c7229)`
- 日期：2026-02-07
- 明确新增内容：引入了“Merge pull request #25 from LofiSu/feat/citations”相关功能改进。
- 影响范围：主要涉及 前端、后端。
- 改动规模：+580 / -501 行。
- 关键文件：backend/src/agents/lead_agent/prompt.py；backend/src/gateway/routers/artifacts.py；frontend/src/components/ai-elements/inline-citation.tsx；frontend/src/components/workspace/artifacts/artifact-file-detail.tsx；frontend/src/components/workspace/messages/message-group.tsx；frontend/src/components/workspace/messages/message-list-item.tsx；frontend/src/components/workspace/settings/memory-settings-page.tsx；frontend/src/core/citations/index.ts。

#### 102. Merge pull request #25 from LofiSu/feat/citations

- 提交：`[afb7a36](https://github.com/bytedance/deer-flow/commit/afb7a367391abaacd4735ba52613be7c21d82030)`
- 日期：2026-02-07
- 明确新增内容：引入了“Merge pull request #25 from LofiSu/feat/citations”相关功能改进。
- 影响范围：主要涉及 前端、后端。
- 改动规模：+580 / -501 行。
- 关键文件：backend/src/agents/lead_agent/prompt.py；backend/src/gateway/routers/artifacts.py；frontend/src/components/ai-elements/inline-citation.tsx；frontend/src/components/workspace/artifacts/artifact-file-detail.tsx；frontend/src/components/workspace/messages/message-group.tsx；frontend/src/components/workspace/messages/message-list-item.tsx；frontend/src/components/workspace/settings/memory-settings-page.tsx；frontend/src/core/citations/index.ts。

#### 103. Merge pull request #25 from LofiSu/feat/citations

- 提交：`[9f8d9e4](https://github.com/bytedance/deer-flow/commit/9f8d9e4da217975e77c56a4041cfb96f9f1b9d23)`
- 日期：2026-02-07
- 明确新增内容：引入了“Merge pull request #25 from LofiSu/feat/citations”相关功能改进。
- 影响范围：主要涉及 前端、后端。
- 改动规模：+580 / -501 行。
- 关键文件：backend/src/agents/lead_agent/prompt.py；backend/src/gateway/routers/artifacts.py；frontend/src/components/ai-elements/inline-citation.tsx；frontend/src/components/workspace/artifacts/artifact-file-detail.tsx；frontend/src/components/workspace/messages/message-group.tsx；frontend/src/components/workspace/messages/message-list-item.tsx；frontend/src/components/workspace/settings/memory-settings-page.tsx；frontend/src/core/citations/index.ts。

#### 104. feat: enhance workspace navigation menu with conditional rendering and mounted state

- 提交：`[91a05ac](https://github.com/bytedance/deer-flow/commit/91a05acdf8463ccc5e6a58829e10da5943a57619)`
- 日期：2026-02-07
- 明确新增内容：增强了“enhance workspace navigation menu with conditional rendering and mounted state”相关能力与交互体验。
- 影响范围：主要涉及 前端。
- 改动规模：+101 / -79 行。
- 关键文件：frontend/src/components/workspace/workspace-nav-menu.tsx。

#### 105. feat: enhance workspace navigation menu with conditional rendering and mounted state

- 提交：`[4ac637a](https://github.com/bytedance/deer-flow/commit/4ac637a0eb8db54be78bb17abf5c1ebfe6bbc9c3)`
- 日期：2026-02-07
- 明确新增内容：增强了“enhance workspace navigation menu with conditional rendering and mounted state”相关能力与交互体验。
- 影响范围：主要涉及 前端。
- 改动规模：+101 / -79 行。
- 关键文件：frontend/src/components/workspace/workspace-nav-menu.tsx。

#### 106. feat: enhance workspace navigation menu with conditional rendering and mounted state

- 提交：`[e7cd528](https://github.com/bytedance/deer-flow/commit/e7cd5287f1ee0aa42a5a2fb034e74cd028ea85cd)`
- 日期：2026-02-07
- 明确新增内容：增强了“enhance workspace navigation menu with conditional rendering and mounted state”相关能力与交互体验。
- 影响范围：主要涉及 前端。
- 改动规模：+101 / -79 行。
- 关键文件：frontend/src/components/workspace/workspace-nav-menu.tsx。

#### 107. docs: update description for surprise-me skill to enhance clarity

- 提交：`[60be7ee](https://github.com/bytedance/deer-flow/commit/60be7ee20de3552aa04bdb5ebbbde092cfabf75f)`
- 日期：2026-02-07
- 明确新增内容：新增了“update description for surprise-me skill to enhance clarity”相关文档说明，补齐使用/配置指引。
- 影响范围：主要涉及 技能体系。
- 改动规模：+1 / -1 行。
- 关键文件：skills/public/surprise-me/SKILL.md。

#### 108. docs: update description for surprise-me skill to enhance clarity

- 提交：`[86ad92a](https://github.com/bytedance/deer-flow/commit/86ad92a1a6ec3f3d1b9ccb6b6b3e964c56286974)`
- 日期：2026-02-07
- 明确新增内容：新增了“update description for surprise-me skill to enhance clarity”相关文档说明，补齐使用/配置指引。
- 影响范围：主要涉及 技能体系。
- 改动规模：+1 / -1 行。
- 关键文件：skills/public/surprise-me/SKILL.md。

#### 109. docs: update description for surprise-me skill to enhance clarity

- 提交：`[85767c8](https://github.com/bytedance/deer-flow/commit/85767c8470178c08efc3a27d97c6ba7a507cf361)`
- 日期：2026-02-07
- 明确新增内容：新增了“update description for surprise-me skill to enhance clarity”相关文档说明，补齐使用/配置指引。
- 影响范围：主要涉及 技能体系。
- 改动规模：+1 / -1 行。
- 关键文件：skills/public/surprise-me/SKILL.md。

#### 110. feat: add animations

- 提交：`[a122f76](https://github.com/bytedance/deer-flow/commit/a122f76e3661f70c84c44747597342fbb7cb60fb)`
- 日期：2026-02-07
- 明确新增内容：新增了“animations”功能。
- 影响范围：主要涉及 前端。
- 改动规模：+67 / -43 行。
- 关键文件：frontend/src/components/ai-elements/suggestion.tsx；frontend/src/styles/globals.css。

#### 111. feat: add animations

- 提交：`[a2af464](https://github.com/bytedance/deer-flow/commit/a2af464a6fdbdc798d0f9b81f1e73078d1b5caaa)`
- 日期：2026-02-07
- 明确新增内容：新增了“animations”功能。
- 影响范围：主要涉及 前端。
- 改动规模：+67 / -43 行。
- 关键文件：frontend/src/components/ai-elements/suggestion.tsx；frontend/src/styles/globals.css。

#### 112. feat: add animations

- 提交：`[fc543a9](https://github.com/bytedance/deer-flow/commit/fc543a9b30acce8a305ca6bff693025e2eaae212)`
- 日期：2026-02-07
- 明确新增内容：新增了“animations”功能。
- 影响范围：主要涉及 前端。
- 改动规模：+67 / -43 行。
- 关键文件：frontend/src/components/ai-elements/suggestion.tsx；frontend/src/styles/globals.css。

#### 113. Merge upstream/experimental into feat/citations

- 提交：`[f0075e0](https://github.com/bytedance/deer-flow/commit/f0075e0d64860040394a6f4fe3f8f90ed8a2077c)`
- 日期：2026-02-07
- 明确新增内容：引入了“Merge upstream/experimental into feat/citations”相关功能改进。
- 影响范围：主要涉及 前端、后端、技能体系。
- 改动规模：+3491 / -5322 行。
- 关键文件：Makefile；README.md；backend/CLAUDE.md；backend/debug.py；backend/docs/APPLE_CONTAINER.md；backend/docs/MEMORY_IMPROVEMENTS.md；backend/docs/MEMORY_IMPROVEMENTS_SUMMARY.md；backend/docs/SETUP.md。

#### 114. Merge upstream/experimental into feat/citations

- 提交：`[2331c67](https://github.com/bytedance/deer-flow/commit/2331c674468c626beb7553e8a5140441162bb54e)`
- 日期：2026-02-07
- 明确新增内容：引入了“Merge upstream/experimental into feat/citations”相关功能改进。
- 影响范围：主要涉及 前端、后端、技能体系。
- 改动规模：+3491 / -5322 行。
- 关键文件：Makefile；README.md；backend/CLAUDE.md；backend/debug.py；backend/docs/APPLE_CONTAINER.md；backend/docs/MEMORY_IMPROVEMENTS.md；backend/docs/MEMORY_IMPROVEMENTS_SUMMARY.md；backend/docs/SETUP.md。

#### 115. Merge upstream/experimental into feat/citations

- 提交：`[ea543ce](https://github.com/bytedance/deer-flow/commit/ea543ce1f437f31b0a870c8b7d8adc1d19b5d0af)`
- 日期：2026-02-07
- 明确新增内容：引入了“Merge upstream/experimental into feat/citations”相关功能改进。
- 影响范围：主要涉及 前端、后端、技能体系。
- 改动规模：+3491 / -5322 行。
- 关键文件：Makefile；README.md；backend/CLAUDE.md；backend/debug.py；backend/docs/APPLE_CONTAINER.md；backend/docs/MEMORY_IMPROVEMENTS.md；backend/docs/MEMORY_IMPROVEMENTS_SUMMARY.md；backend/docs/SETUP.md。

#### 116. feat: send custom event

- 提交：`[9bf3a12](https://github.com/bytedance/deer-flow/commit/9bf3a12c30abaea3e897f82c55116e7cc1d8b4db)`
- 日期：2026-02-06
- 明确新增内容：引入了“send custom event”相关功能改进。
- 影响范围：主要涉及 后端、前端、脚本工具。
- 改动规模：+80 / -127 行。
- 关键文件：backend/src/community/aio_sandbox/aio_sandbox_provider.py；backend/src/sandbox/tools.py；backend/src/subagents/executor.py；backend/src/tools/builtins/task_tool.py；frontend/src/components/workspace/subagent-card.tsx；frontend/src/core/threads/hooks.ts；scripts/cleanup-containers.sh。

#### 117. feat: send custom event

- 提交：`[1728137](https://github.com/bytedance/deer-flow/commit/172813720a02e5168c11da232064f16b578a6126)`
- 日期：2026-02-06
- 明确新增内容：引入了“send custom event”相关功能改进。
- 影响范围：主要涉及 后端、前端、脚本工具。
- 改动规模：+80 / -127 行。
- 关键文件：backend/src/community/aio_sandbox/aio_sandbox_provider.py；backend/src/sandbox/tools.py；backend/src/subagents/executor.py；backend/src/tools/builtins/task_tool.py；frontend/src/components/workspace/subagent-card.tsx；frontend/src/core/threads/hooks.ts；scripts/cleanup-containers.sh。

#### 118. feat: send custom event

- 提交：`[4f15670](https://github.com/bytedance/deer-flow/commit/4f156704557cc20f735d43cfb37d086028984cc6)`
- 日期：2026-02-06
- 明确新增内容：引入了“send custom event”相关功能改进。
- 影响范围：主要涉及 后端、前端、脚本工具。
- 改动规模：+80 / -127 行。
- 关键文件：backend/src/community/aio_sandbox/aio_sandbox_provider.py；backend/src/sandbox/tools.py；backend/src/subagents/executor.py；backend/src/tools/builtins/task_tool.py；frontend/src/components/workspace/subagent-card.tsx；frontend/src/core/threads/hooks.ts；scripts/cleanup-containers.sh。

#### 119. feat: add ultra mode

- 提交：`[449ffba](https://github.com/bytedance/deer-flow/commit/449ffbad7539b2341c6ae3e0ae6f95486ea0936f)`
- 日期：2026-02-06
- 明确新增内容：新增了“ultra mode”功能。
- 影响范围：主要涉及 前端、后端、配置。
- 改动规模：+272 / -41 行。
- 关键文件：backend/src/agents/lead_agent/agent.py；backend/src/agents/lead_agent/prompt.py；backend/src/config/app_config.py；backend/src/config/subagents_config.py；backend/src/tools/builtins/task_tool.py；backend/src/tools/tools.py；config.example.yaml；frontend/src/app/workspace/chats/[thread_id]/page.tsx。

#### 120. feat: add ultra mode

- 提交：`[926c322](https://github.com/bytedance/deer-flow/commit/926c322c3693ccef3ad8a0a1d7dfece5fffb86df)`
- 日期：2026-02-06
- 明确新增内容：新增了“ultra mode”功能。
- 影响范围：主要涉及 前端、后端、配置。
- 改动规模：+272 / -41 行。
- 关键文件：backend/src/agents/lead_agent/agent.py；backend/src/agents/lead_agent/prompt.py；backend/src/config/app_config.py；backend/src/config/subagents_config.py；backend/src/tools/builtins/task_tool.py；backend/src/tools/tools.py；config.example.yaml；frontend/src/app/workspace/chats/[thread_id]/page.tsx。

#### 121. feat: add ultra mode

- 提交：`[96baab1](https://github.com/bytedance/deer-flow/commit/96baab12a2a2174d0ecd9cd07ad4ef29eaf73e7e)`
- 日期：2026-02-06
- 明确新增内容：新增了“ultra mode”功能。
- 影响范围：主要涉及 前端、后端、配置。
- 改动规模：+272 / -41 行。
- 关键文件：backend/src/agents/lead_agent/agent.py；backend/src/agents/lead_agent/prompt.py；backend/src/config/app_config.py；backend/src/config/subagents_config.py；backend/src/tools/builtins/task_tool.py；backend/src/tools/tools.py；config.example.yaml；frontend/src/app/workspace/chats/[thread_id]/page.tsx。

#### 122. feat: add 'about' page

- 提交：`[70989a9](https://github.com/bytedance/deer-flow/commit/70989a949e93d341bf2a87052d80003451bfbd8a)`
- 日期：2026-02-06
- 明确新增内容：新增了“'about' page”功能。
- 影响范围：主要涉及 前端。
- 改动规模：+675 / -22 行。
- 关键文件：frontend/next.config.js；frontend/package.json；frontend/pnpm-lock.yaml；frontend/src/components/workspace/settings/about-settings-page.tsx；frontend/src/components/workspace/settings/about.md；frontend/src/components/workspace/settings/acknowledge-page.tsx；frontend/src/components/workspace/settings/memory-settings-page.tsx；frontend/src/components/workspace/settings/settings-dialog.tsx。

#### 123. feat: add 'about' page

- 提交：`[44742c6](https://github.com/bytedance/deer-flow/commit/44742c63531a950ff83d650c1deda9a9c8bf7d9a)`
- 日期：2026-02-06
- 明确新增内容：新增了“'about' page”功能。
- 影响范围：主要涉及 前端。
- 改动规模：+675 / -22 行。
- 关键文件：frontend/next.config.js；frontend/package.json；frontend/pnpm-lock.yaml；frontend/src/components/workspace/settings/about-settings-page.tsx；frontend/src/components/workspace/settings/about.md；frontend/src/components/workspace/settings/acknowledge-page.tsx；frontend/src/components/workspace/settings/memory-settings-page.tsx；frontend/src/components/workspace/settings/settings-dialog.tsx。

#### 124. feat: add 'about' page

- 提交：`[f981167](https://github.com/bytedance/deer-flow/commit/f9811671d8a442ce777367170792cc0d42f3d37a)`
- 日期：2026-02-06
- 明确新增内容：新增了“'about' page”功能。
- 影响范围：主要涉及 前端。
- 改动规模：+675 / -22 行。
- 关键文件：frontend/next.config.js；frontend/package.json；frontend/pnpm-lock.yaml；frontend/src/components/workspace/settings/about-settings-page.tsx；frontend/src/components/workspace/settings/about.md；frontend/src/components/workspace/settings/acknowledge-page.tsx；frontend/src/components/workspace/settings/memory-settings-page.tsx；frontend/src/components/workspace/settings/settings-dialog.tsx。

#### 125. docs: rewording

- 提交：`[bc7837e](https://github.com/bytedance/deer-flow/commit/bc7837ed6f7e00309b6512b74476ce16062ba36f)`
- 日期：2026-02-06
- 明确新增内容：新增了“rewording”相关文档说明，补齐使用/配置指引。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -2 行。
- 关键文件：frontend/src/components/landing/hero.tsx。

#### 126. docs: rewording

- 提交：`[dd4a7aa](https://github.com/bytedance/deer-flow/commit/dd4a7aae36d08a3cb321609c603c57bcfe3dd7ef)`
- 日期：2026-02-06
- 明确新增内容：新增了“rewording”相关文档说明，补齐使用/配置指引。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -2 行。
- 关键文件：frontend/src/components/landing/hero.tsx。

#### 127. docs: rewording

- 提交：`[ee41324](https://github.com/bytedance/deer-flow/commit/ee4132488734d6da0cd88ac06bc629c090d66509)`
- 日期：2026-02-06
- 明确新增内容：新增了“rewording”相关文档说明，补齐使用/配置指引。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -2 行。
- 关键文件：frontend/src/components/landing/hero.tsx。

#### 128. docs: add CLAUDE.md

- 提交：`[23c082f](https://github.com/bytedance/deer-flow/commit/23c082f05dad509aa8d01357f21416245807614d)`
- 日期：2026-02-06
- 明确新增内容：新增了“add CLAUDE.md”相关文档说明，补齐使用/配置指引。
- 影响范围：主要涉及 前端。
- 改动规模：+89 / -0 行。
- 关键文件：frontend/CLAUDE.md。

#### 129. docs: add CLAUDE.md

- 提交：`[a711c5f](https://github.com/bytedance/deer-flow/commit/a711c5f3104dfd4ab7e4058ac1a0ce42a50da0a5)`
- 日期：2026-02-06
- 明确新增内容：新增了“add CLAUDE.md”相关文档说明，补齐使用/配置指引。
- 影响范围：主要涉及 前端。
- 改动规模：+89 / -0 行。
- 关键文件：frontend/CLAUDE.md。

#### 130. docs: add CLAUDE.md

- 提交：`[8bd20ab](https://github.com/bytedance/deer-flow/commit/8bd20ab4e645e4aa5b0c908aa14955354516071e)`
- 日期：2026-02-06
- 明确新增内容：新增了“add CLAUDE.md”相关文档说明，补齐使用/配置指引。
- 影响范围：主要涉及 前端。
- 改动规模：+89 / -0 行。
- 关键文件：frontend/CLAUDE.md。

#### 131. docs: add AGENTS.md

- 提交：`[78b6164](https://github.com/bytedance/deer-flow/commit/78b6164770db512ad98cf45bed97a043cd3646da)`
- 日期：2026-02-06
- 明确新增内容：新增了“add AGENTS.md”相关文档说明，补齐使用/配置指引。
- 影响范围：主要涉及 前端。
- 改动规模：+100 / -0 行。
- 关键文件：frontend/AGENTS.md。

#### 132. docs: add AGENTS.md

- 提交：`[5b33a62](https://github.com/bytedance/deer-flow/commit/5b33a62f05c0297a9a163d6ef2e9f01145e45915)`
- 日期：2026-02-06
- 明确新增内容：新增了“add AGENTS.md”相关文档说明，补齐使用/配置指引。
- 影响范围：主要涉及 前端。
- 改动规模：+100 / -0 行。
- 关键文件：frontend/AGENTS.md。

#### 133. docs: add AGENTS.md

- 提交：`[30cd238](https://github.com/bytedance/deer-flow/commit/30cd2387f28df2b37ae02ef59bed664f68c73302)`
- 日期：2026-02-06
- 明确新增内容：新增了“add AGENTS.md”相关文档说明，补齐使用/配置指引。
- 影响范围：主要涉及 前端。
- 改动规模：+100 / -0 行。
- 关键文件：frontend/AGENTS.md。

#### 134. feat: update surprise-me functionality with localization support

- 提交：`[b74cf65](https://github.com/bytedance/deer-flow/commit/b74cf6527523c451001d7667f33ea077f3edb444)`
- 日期：2026-02-06
- 明确新增内容：新增了对“update surprise-me functionality with localization support”的支持能力。
- 影响范围：主要涉及 前端。
- 改动规模：+8 / -2 行。
- 关键文件：frontend/src/components/workspace/input-box.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts；frontend/src/core/i18n/locales/zh-CN.ts。

#### 135. feat: update surprise-me functionality with localization support

- 提交：`[765e35f](https://github.com/bytedance/deer-flow/commit/765e35fc70c7a6465e9bb575c4b88d24bbedb0bf)`
- 日期：2026-02-06
- 明确新增内容：新增了对“update surprise-me functionality with localization support”的支持能力。
- 影响范围：主要涉及 前端。
- 改动规模：+8 / -2 行。
- 关键文件：frontend/src/components/workspace/input-box.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts；frontend/src/core/i18n/locales/zh-CN.ts。

#### 136. feat: update surprise-me functionality with localization support

- 提交：`[bbb1a73](https://github.com/bytedance/deer-flow/commit/bbb1a731a530ef377c06cbe20c9ef894e39db6ce)`
- 日期：2026-02-06
- 明确新增内容：新增了对“update surprise-me functionality with localization support”的支持能力。
- 影响范围：主要涉及 前端。
- 改动规模：+8 / -2 行。
- 关键文件：frontend/src/components/workspace/input-box.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts；frontend/src/core/i18n/locales/zh-CN.ts。

#### 137. feat: add surprise-me

- 提交：`[22dea3f](https://github.com/bytedance/deer-flow/commit/22dea3fd433c7f1403cf0a3f372cfd7875452c0d)`
- 日期：2026-02-06
- 明确新增内容：新增了“surprise-me”功能。
- 影响范围：主要涉及 前端、技能体系。
- 改动规模：+122 / -0 行。
- 关键文件：frontend/package.json；frontend/pnpm-lock.yaml；frontend/src/components/ui/confetti-button.tsx；frontend/src/components/workspace/input-box.tsx；skills/public/surprise-me/SKILL.md。

#### 138. feat: add surprise-me

- 提交：`[26e078d](https://github.com/bytedance/deer-flow/commit/26e078df7d6dd87a3fc02cd6ba685c3f6a1ff92c)`
- 日期：2026-02-06
- 明确新增内容：新增了“surprise-me”功能。
- 影响范围：主要涉及 前端、技能体系。
- 改动规模：+122 / -0 行。
- 关键文件：frontend/package.json；frontend/pnpm-lock.yaml；frontend/src/components/ui/confetti-button.tsx；frontend/src/components/workspace/input-box.tsx；skills/public/surprise-me/SKILL.md。

#### 139. feat: add surprise-me

- 提交：`[697ea8e](https://github.com/bytedance/deer-flow/commit/697ea8e845a9ae27eb164c5a3ba1160c46298afd)`
- 日期：2026-02-06
- 明确新增内容：新增了“surprise-me”功能。
- 影响范围：主要涉及 前端、技能体系。
- 改动规模：+122 / -0 行。
- 关键文件：frontend/package.json；frontend/pnpm-lock.yaml；frontend/src/components/ui/confetti-button.tsx；frontend/src/components/workspace/input-box.tsx；skills/public/surprise-me/SKILL.md。

#### 140. feat: adjust position

- 提交：`[f391060](https://github.com/bytedance/deer-flow/commit/f3910605737f56a5a2a664f9e844e8dfe79cb204)`
- 日期：2026-02-06
- 明确新增内容：引入了“adjust position”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -1 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx。

#### 141. feat: adjust position

- 提交：`[254efe7](https://github.com/bytedance/deer-flow/commit/254efe739197448cb36c5a4edd61cce6fce46888)`
- 日期：2026-02-06
- 明确新增内容：引入了“adjust position”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -1 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx。

#### 142. feat: adjust position

- 提交：`[dedfa1b](https://github.com/bytedance/deer-flow/commit/dedfa1bfb503f3b0c8259c6b128d3a550110e9d7)`
- 日期：2026-02-06
- 明确新增内容：引入了“adjust position”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -1 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx。

#### 143. feat: add configuration to enable/disable subagents

- 提交：`[85128f5](https://github.com/bytedance/deer-flow/commit/85128f5f147ff09f6c1537abb21c177056684d2a)`
- 日期：2026-02-05
- 明确新增内容：新增了“configuration to enable/disable subagents”功能。
- 影响范围：主要涉及 后端、配置。
- 改动规模：+105 / -63 行。
- 关键文件：backend/CLAUDE.md；backend/src/agents/lead_agent/prompt.py；backend/src/config/app_config.py；backend/src/config/subagents_config.py；backend/src/tools/tools.py；config.example.yaml。

#### 144. feat: add configuration to enable/disable subagents

- 提交：`[b7bf027](https://github.com/bytedance/deer-flow/commit/b7bf027aa5a463b08487c363516ff8340dda88d0)`
- 日期：2026-02-05
- 明确新增内容：新增了“configuration to enable/disable subagents”功能。
- 影响范围：主要涉及 后端、配置。
- 改动规模：+105 / -63 行。
- 关键文件：backend/CLAUDE.md；backend/src/agents/lead_agent/prompt.py；backend/src/config/app_config.py；backend/src/config/subagents_config.py；backend/src/tools/tools.py；config.example.yaml。

#### 145. feat: add configuration to enable/disable subagents

- 提交：`[b7ba237](https://github.com/bytedance/deer-flow/commit/b7ba237c3656d8ddb2520fa3d7af4b26fca3ad77)`
- 日期：2026-02-05
- 明确新增内容：新增了“configuration to enable/disable subagents”功能。
- 影响范围：主要涉及 后端、配置。
- 改动规模：+105 / -63 行。
- 关键文件：backend/CLAUDE.md；backend/src/agents/lead_agent/prompt.py；backend/src/config/app_config.py；backend/src/config/subagents_config.py；backend/src/tools/tools.py；config.example.yaml。

#### 146. feat: support sub agent mechanism

- 提交：`[ef379a3](https://github.com/bytedance/deer-flow/commit/ef379a310058f3e1771c89ff65e79e708b28ba35)`
- 日期：2026-02-05
- 明确新增内容：新增了对“sub agent mechanism”的支持能力。
- 影响范围：主要涉及 后端、其他模块。
- 改动规模：+775 / -33 行。
- 关键文件：Makefile；backend/debug.py；backend/src/agents/lead_agent/prompt.py；backend/src/agents/memory/updater.py；backend/src/agents/middlewares/uploads_middleware.py；backend/src/community/aio_sandbox/aio_sandbox_provider.py；backend/src/config/extensions_config.py；backend/src/gateway/routers/artifacts.py。

#### 147. feat: support sub agent mechanism

- 提交：`[cbd2fe6](https://github.com/bytedance/deer-flow/commit/cbd2fe66dedee6335415dffdd97c111d6127b011)`
- 日期：2026-02-05
- 明确新增内容：新增了对“sub agent mechanism”的支持能力。
- 影响范围：主要涉及 后端、其他模块。
- 改动规模：+775 / -33 行。
- 关键文件：Makefile；backend/debug.py；backend/src/agents/lead_agent/prompt.py；backend/src/agents/memory/updater.py；backend/src/agents/middlewares/uploads_middleware.py；backend/src/community/aio_sandbox/aio_sandbox_provider.py；backend/src/config/extensions_config.py；backend/src/gateway/routers/artifacts.py。

#### 148. feat: support sub agent mechanism

- 提交：`[6e3f43c](https://github.com/bytedance/deer-flow/commit/6e3f43c9431589a0aa652090db77c8b4218b8963)`
- 日期：2026-02-05
- 明确新增内容：新增了对“sub agent mechanism”的支持能力。
- 影响范围：主要涉及 后端、其他模块。
- 改动规模：+775 / -33 行。
- 关键文件：Makefile；backend/debug.py；backend/src/agents/lead_agent/prompt.py；backend/src/agents/memory/updater.py；backend/src/agents/middlewares/uploads_middleware.py；backend/src/community/aio_sandbox/aio_sandbox_provider.py；backend/src/config/extensions_config.py；backend/src/gateway/routers/artifacts.py。

#### 149. feat: remove demo

- 提交：`[43ebce3](https://github.com/bytedance/deer-flow/commit/43ebce3b3744b2db38f97c57fad1ea169043c401)`
- 日期：2026-02-05
- 明确新增内容：引入了“remove demo”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+7 / -5166 行。
- 关键文件：frontend/public/demo/threads/090898a7-1b1e-4937-ba03-764dbaafa27b/thread.json；frontend/public/demo/threads/090898a7-1b1e-4937-ba03-764dbaafa27b/user-data/outputs/nie-weiping-memorial/index.html；frontend/public/demo/threads/090898a7-1b1e-4937-ba03-764dbaafa27b/user-data/outputs/nie-weiping-memorial/script.js；frontend/public/demo/threads/090898a7-1b1e-4937-ba03-764dbaafa27b/user-data/outputs/nie-weiping-memorial/style.css；frontend/src/components/workspace/messages/message-group.tsx。

#### 150. feat: remove demo

- 提交：`[c31175d](https://github.com/bytedance/deer-flow/commit/c31175defdd1042865cfaf725429495a14d5e17c)`
- 日期：2026-02-05
- 明确新增内容：引入了“remove demo”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+7 / -5166 行。
- 关键文件：frontend/public/demo/threads/090898a7-1b1e-4937-ba03-764dbaafa27b/thread.json；frontend/public/demo/threads/090898a7-1b1e-4937-ba03-764dbaafa27b/user-data/outputs/nie-weiping-memorial/index.html；frontend/public/demo/threads/090898a7-1b1e-4937-ba03-764dbaafa27b/user-data/outputs/nie-weiping-memorial/script.js；frontend/public/demo/threads/090898a7-1b1e-4937-ba03-764dbaafa27b/user-data/outputs/nie-weiping-memorial/style.css；frontend/src/components/workspace/messages/message-group.tsx。

#### 151. feat: remove demo

- 提交：`[118fc00](https://github.com/bytedance/deer-flow/commit/118fc0036850072f08f195064c47ac2a1839c378)`
- 日期：2026-02-05
- 明确新增内容：引入了“remove demo”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+7 / -5166 行。
- 关键文件：frontend/public/demo/threads/090898a7-1b1e-4937-ba03-764dbaafa27b/thread.json；frontend/public/demo/threads/090898a7-1b1e-4937-ba03-764dbaafa27b/user-data/outputs/nie-weiping-memorial/index.html；frontend/public/demo/threads/090898a7-1b1e-4937-ba03-764dbaafa27b/user-data/outputs/nie-weiping-memorial/script.js；frontend/public/demo/threads/090898a7-1b1e-4937-ba03-764dbaafa27b/user-data/outputs/nie-weiping-memorial/style.css；frontend/src/components/workspace/messages/message-group.tsx。

#### 152. feat: enhance memory system with tiktoken and improved prompt guidelines

- 提交：`[db04611](https://github.com/bytedance/deer-flow/commit/db0461142ebed5f4555c6e59fda286cc68879559)`
- 日期：2026-02-04
- 明确新增内容：新增了“enhance memory system with tiktoken and improved prompt guidelines”相关文档说明，补齐使用/配置指引。
- 影响范围：主要涉及 后端、技能体系。
- 改动规模：+659 / -50 行。
- 关键文件：backend/docs/MEMORY_IMPROVEMENTS.md；backend/docs/MEMORY_IMPROVEMENTS_SUMMARY.md；backend/pyproject.toml；backend/src/agents/memory/prompt.py；backend/uv.lock；skills/public/deep-research/SKILL.md。

#### 153. feat: enhance memory system with tiktoken and improved prompt guidelines

- 提交：`[0d245d6](https://github.com/bytedance/deer-flow/commit/0d245d6e31d9ebbc58365584e3b46eca68429356)`
- 日期：2026-02-04
- 明确新增内容：新增了“enhance memory system with tiktoken and improved prompt guidelines”相关文档说明，补齐使用/配置指引。
- 影响范围：主要涉及 后端、技能体系。
- 改动规模：+659 / -50 行。
- 关键文件：backend/docs/MEMORY_IMPROVEMENTS.md；backend/docs/MEMORY_IMPROVEMENTS_SUMMARY.md；backend/pyproject.toml；backend/src/agents/memory/prompt.py；backend/uv.lock；skills/public/deep-research/SKILL.md。

#### 154. feat: enhance memory system with tiktoken and improved prompt guidelines

- 提交：`[df1191c](https://github.com/bytedance/deer-flow/commit/df1191c90ac886596c37c285d1bd97afed5e1790)`
- 日期：2026-02-04
- 明确新增内容：新增了“enhance memory system with tiktoken and improved prompt guidelines”相关文档说明，补齐使用/配置指引。
- 影响范围：主要涉及 后端、技能体系。
- 改动规模：+659 / -50 行。
- 关键文件：backend/docs/MEMORY_IMPROVEMENTS.md；backend/docs/MEMORY_IMPROVEMENTS_SUMMARY.md；backend/pyproject.toml；backend/src/agents/memory/prompt.py；backend/uv.lock；skills/public/deep-research/SKILL.md。

#### 155. feat(citations): add shared citation components and optimize code

- 提交：`[644229f](https://github.com/bytedance/deer-flow/commit/644229f968dc824cb7c2ec5b6f3e07d971bdde3c)`
- 日期：2026-02-04
- 明确新增内容：新增了“shared citation components and optimize code”功能。
- 影响范围：主要涉及 前端、后端。
- 改动规模：+519 / -465 行。
- 关键文件：backend/src/gateway/routers/artifacts.py；frontend/src/components/ai-elements/inline-citation.tsx；frontend/src/components/workspace/artifacts/artifact-file-detail.tsx；frontend/src/components/workspace/messages/message-group.tsx；frontend/src/components/workspace/messages/message-list-item.tsx；frontend/src/components/workspace/settings/memory-settings-page.tsx；frontend/src/core/citations/index.ts；frontend/src/core/citations/utils.ts。

#### 156. feat(citations): add shared citation components and optimize code

- 提交：`[c67f1af](https://github.com/bytedance/deer-flow/commit/c67f1af889b290b09c484a8ef3827134dfba115a)`
- 日期：2026-02-04
- 明确新增内容：新增了“shared citation components and optimize code”功能。
- 影响范围：主要涉及 前端、后端。
- 改动规模：+519 / -465 行。
- 关键文件：backend/src/gateway/routers/artifacts.py；frontend/src/components/ai-elements/inline-citation.tsx；frontend/src/components/workspace/artifacts/artifact-file-detail.tsx；frontend/src/components/workspace/messages/message-group.tsx；frontend/src/components/workspace/messages/message-list-item.tsx；frontend/src/components/workspace/settings/memory-settings-page.tsx；frontend/src/core/citations/index.ts；frontend/src/core/citations/utils.ts。

#### 157. feat(citations): add shared citation components and optimize code

- 提交：`[1e2675b](https://github.com/bytedance/deer-flow/commit/1e2675beb35dab1f640b987118a5a6a6d9354596)`
- 日期：2026-02-04
- 明确新增内容：新增了“shared citation components and optimize code”功能。
- 影响范围：主要涉及 前端、后端。
- 改动规模：+519 / -465 行。
- 关键文件：backend/src/gateway/routers/artifacts.py；frontend/src/components/ai-elements/inline-citation.tsx；frontend/src/components/workspace/artifacts/artifact-file-detail.tsx；frontend/src/components/workspace/messages/message-group.tsx；frontend/src/components/workspace/messages/message-list-item.tsx；frontend/src/components/workspace/settings/memory-settings-page.tsx；frontend/src/core/citations/index.ts；frontend/src/core/citations/utils.ts。

#### 158. feat: add Apple Container support with comprehensive documentation and dev tools

- 提交：`[5959ef8](https://github.com/bytedance/deer-flow/commit/5959ef87b8b06479f144560cb48cb8523f69de2d)`
- 日期：2026-02-03
- 明确新增内容：新增了对“add Apple Container support with comprehensive documentation and dev tools”的支持能力。
- 影响范围：主要涉及 后端、其他模块、文档。
- 改动规模：+556 / -30 行。
- 关键文件：Makefile；README.md；backend/CLAUDE.md；backend/docs/APPLE_CONTAINER.md；backend/docs/SETUP.md；backend/src/community/aio_sandbox/aio_sandbox_provider.py；config.example.yaml；scripts/cleanup-containers.sh。

#### 159. feat: add Apple Container support with comprehensive documentation and dev tools

- 提交：`[70a27b4](https://github.com/bytedance/deer-flow/commit/70a27b49c0d3e3306be6f53a283f08403e527de8)`
- 日期：2026-02-03
- 明确新增内容：新增了对“add Apple Container support with comprehensive documentation and dev tools”的支持能力。
- 影响范围：主要涉及 后端、其他模块、文档。
- 改动规模：+556 / -30 行。
- 关键文件：Makefile；README.md；backend/CLAUDE.md；backend/docs/APPLE_CONTAINER.md；backend/docs/SETUP.md；backend/src/community/aio_sandbox/aio_sandbox_provider.py；config.example.yaml；scripts/cleanup-containers.sh。

#### 160. feat: add Apple Container support with comprehensive documentation and dev tools

- 提交：`[ef10f3b](https://github.com/bytedance/deer-flow/commit/ef10f3ba413f926ced88ee2f44c4ecec91306817)`
- 日期：2026-02-03
- 明确新增内容：新增了对“add Apple Container support with comprehensive documentation and dev tools”的支持能力。
- 影响范围：主要涉及 后端、其他模块、文档。
- 改动规模：+556 / -30 行。
- 关键文件：Makefile；README.md；backend/CLAUDE.md；backend/docs/APPLE_CONTAINER.md；backend/docs/SETUP.md；backend/src/community/aio_sandbox/aio_sandbox_provider.py；config.example.yaml；scripts/cleanup-containers.sh。

#### 161. feat: add memory settings page

- 提交：`[6b53456](https://github.com/bytedance/deer-flow/commit/6b53456b3909bbe84507ec22b7be2e1e27c085ff)`
- 日期：2026-02-03
- 明确新增内容：新增了“memory settings page”功能。
- 影响范围：主要涉及 前端、后端。
- 改动规模：+411 / -17 行。
- 关键文件：backend/README.md；frontend/src/components/landing/hero.tsx；frontend/src/components/landing/sections/whats-new-section.tsx；frontend/src/components/workspace/settings/memory-settings-page.tsx；frontend/src/components/workspace/settings/settings-dialog.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts；frontend/src/core/i18n/locales/zh-CN.ts。

#### 162. feat: add memory settings page

- 提交：`[94acb15](https://github.com/bytedance/deer-flow/commit/94acb15c0c7cd84c290ea73b429c6da4dc8526b8)`
- 日期：2026-02-03
- 明确新增内容：新增了“memory settings page”功能。
- 影响范围：主要涉及 前端、后端。
- 改动规模：+411 / -17 行。
- 关键文件：backend/README.md；frontend/src/components/landing/hero.tsx；frontend/src/components/landing/sections/whats-new-section.tsx；frontend/src/components/workspace/settings/memory-settings-page.tsx；frontend/src/components/workspace/settings/settings-dialog.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts；frontend/src/core/i18n/locales/zh-CN.ts。

#### 163. feat: add memory settings page

- 提交：`[552d1c3](https://github.com/bytedance/deer-flow/commit/552d1c3a9aae49081347bd7f2ecd8820acb97f66)`
- 日期：2026-02-03
- 明确新增内容：新增了“memory settings page”功能。
- 影响范围：主要涉及 前端、后端。
- 改动规模：+411 / -17 行。
- 关键文件：backend/README.md；frontend/src/components/landing/hero.tsx；frontend/src/components/landing/sections/whats-new-section.tsx；frontend/src/components/workspace/settings/memory-settings-page.tsx；frontend/src/components/workspace/settings/settings-dialog.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts；frontend/src/core/i18n/locales/zh-CN.ts。

#### 164. chore: add /api/memory

- 提交：`[4d650f3](https://github.com/bytedance/deer-flow/commit/4d650f35f8887fbc1c4c5142513376e6281b1840)`
- 日期：2026-02-03
- 明确新增内容：新增了“/api/memory”功能。
- 影响范围：主要涉及 容器部署。
- 改动规模：+20 / -0 行。
- 关键文件：docker/nginx/nginx.conf；docker/nginx/nginx.local.conf。

#### 165. chore: add /api/memory

- 提交：`[b8c325e](https://github.com/bytedance/deer-flow/commit/b8c325eb3a7b44cd1450347a8d96d05844ee0e00)`
- 日期：2026-02-03
- 明确新增内容：新增了“/api/memory”功能。
- 影响范围：主要涉及 容器部署。
- 改动规模：+20 / -0 行。
- 关键文件：docker/nginx/nginx.conf；docker/nginx/nginx.local.conf。

#### 166. chore: add /api/memory

- 提交：`[1cf0811](https://github.com/bytedance/deer-flow/commit/1cf081120e3f288448e211de685818ca43bc3cc9)`
- 日期：2026-02-03
- 明确新增内容：新增了“/api/memory”功能。
- 影响范围：主要涉及 容器部署。
- 改动规模：+20 / -0 行。
- 关键文件：docker/nginx/nginx.conf；docker/nginx/nginx.local.conf。

#### 167. feat: add memory API and optimize memory middleware

- 提交：`[3b30913](https://github.com/bytedance/deer-flow/commit/3b30913e100c7411084feb76a78a3b68e376278e)`
- 日期：2026-02-03
- 明确新增内容：新增了“memory API and optimize memory middleware”功能。
- 影响范围：主要涉及 后端、配置。
- 改动规模：+267 / -8 行。
- 关键文件：backend/src/agents/middlewares/memory_middleware.py；backend/src/gateway/app.py；backend/src/gateway/routers/memory.py；config.example.yaml。

#### 168. feat: add memory API and optimize memory middleware

- 提交：`[7b7a7ab](https://github.com/bytedance/deer-flow/commit/7b7a7abaf2faa4d0e6a3f136ee0d737ee3e6d646)`
- 日期：2026-02-03
- 明确新增内容：新增了“memory API and optimize memory middleware”功能。
- 影响范围：主要涉及 后端、配置。
- 改动规模：+267 / -8 行。
- 关键文件：backend/src/agents/middlewares/memory_middleware.py；backend/src/gateway/app.py；backend/src/gateway/routers/memory.py；config.example.yaml。

#### 169. feat: add memory API and optimize memory middleware

- 提交：`[74d47ad](https://github.com/bytedance/deer-flow/commit/74d47ad87f1464f50d5956e5aff5e1b821b2c7c1)`
- 日期：2026-02-03
- 明确新增内容：新增了“memory API and optimize memory middleware”功能。
- 影响范围：主要涉及 后端、配置。
- 改动规模：+267 / -8 行。
- 关键文件：backend/src/agents/middlewares/memory_middleware.py；backend/src/gateway/app.py；backend/src/gateway/routers/memory.py；config.example.yaml。

#### 170. feat: add global memory mechanism for personalized conversations

- 提交：`[0ea666e](https://github.com/bytedance/deer-flow/commit/0ea666e0cfe08aeadb7c66b88bcaca98c03b6466)`
- 日期：2026-02-03
- 明确新增内容：新增了“global memory mechanism for personalized conversations”功能。
- 影响范围：主要涉及 后端。
- 改动规模：+929 / -3 行。
- 关键文件：backend/src/agents/lead_agent/agent.py；backend/src/agents/lead_agent/prompt.py；backend/src/agents/memory/**init**.py；backend/src/agents/memory/prompt.py；backend/src/agents/memory/queue.py；backend/src/agents/memory/updater.py；backend/src/agents/middlewares/memory_middleware.py；backend/src/config/**init**.py。

#### 171. feat: add global memory mechanism for personalized conversations

- 提交：`[18d85ab](https://github.com/bytedance/deer-flow/commit/18d85ab6e501df6a0f8110554a70ce8525a28eed)`
- 日期：2026-02-03
- 明确新增内容：新增了“global memory mechanism for personalized conversations”功能。
- 影响范围：主要涉及 后端。
- 改动规模：+929 / -3 行。
- 关键文件：backend/src/agents/lead_agent/agent.py；backend/src/agents/lead_agent/prompt.py；backend/src/agents/memory/**init**.py；backend/src/agents/memory/prompt.py；backend/src/agents/memory/queue.py；backend/src/agents/memory/updater.py；backend/src/agents/middlewares/memory_middleware.py；backend/src/config/**init**.py。

#### 172. feat: add global memory mechanism for personalized conversations

- 提交：`[ffd07bb](https://github.com/bytedance/deer-flow/commit/ffd07bbafeef6e0424c56475c031edd91dc34b02)`
- 日期：2026-02-03
- 明确新增内容：新增了“global memory mechanism for personalized conversations”功能。
- 影响范围：主要涉及 后端。
- 改动规模：+929 / -3 行。
- 关键文件：backend/src/agents/lead_agent/agent.py；backend/src/agents/lead_agent/prompt.py；backend/src/agents/memory/**init**.py；backend/src/agents/memory/prompt.py；backend/src/agents/memory/queue.py；backend/src/agents/memory/updater.py；backend/src/agents/middlewares/memory_middleware.py；backend/src/config/**init**.py。

#### 173. docs: add README.md

- 提交：`[8625551](https://github.com/bytedance/deer-flow/commit/86255511e1530702c46cf292cebffa5aa27fd196)`
- 日期：2026-02-02
- 明确新增内容：新增了“add README.md”相关文档说明，补齐使用/配置指引。
- 影响范围：主要涉及 前端。
- 改动规模：+131 / -8 行。
- 关键文件：frontend/.env.example；frontend/README.md。

#### 174. docs: add README.md

- 提交：`[0baa8a7](https://github.com/bytedance/deer-flow/commit/0baa8a733a77b17a6455d1a5ddc817ce4d847a6b)`
- 日期：2026-02-02
- 明确新增内容：新增了“add README.md”相关文档说明，补齐使用/配置指引。
- 影响范围：主要涉及 前端。
- 改动规模：+131 / -8 行。
- 关键文件：frontend/.env.example；frontend/README.md。

#### 175. docs: add README.md

- 提交：`[4fd9a2d](https://github.com/bytedance/deer-flow/commit/4fd9a2de8e797fe1e734b03ec3fad76a513144cb)`
- 日期：2026-02-02
- 明确新增内容：新增了“add README.md”相关文档说明，补齐使用/配置指引。
- 影响范围：主要涉及 前端。
- 改动规模：+131 / -8 行。
- 关键文件：frontend/.env.example；frontend/README.md。

#### 176. feat: enhance welcome component and input box with skill mode handling and localization updates

- 提交：`[f4f16bf](https://github.com/bytedance/deer-flow/commit/f4f16bfa5c3ced67e7c397b9cc776bc21d8a22fc)`
- 日期：2026-02-02
- 明确新增内容：增强了“enhance welcome component and input box with skill mode handling and localization updates”相关能力与交互体验。
- 影响范围：主要涉及 前端。
- 改动规模：+33 / -9 行。
- 关键文件：frontend/src/components/workspace/input-box.tsx；frontend/src/components/workspace/welcome.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts；frontend/src/core/i18n/locales/zh-CN.ts。

#### 177. feat: enhance welcome component and input box with skill mode handling and localization updates

- 提交：`[010eade](https://github.com/bytedance/deer-flow/commit/010eadecca3568baa64de94a91dc3deace6978b5)`
- 日期：2026-02-02
- 明确新增内容：增强了“enhance welcome component and input box with skill mode handling and localization updates”相关能力与交互体验。
- 影响范围：主要涉及 前端。
- 改动规模：+33 / -9 行。
- 关键文件：frontend/src/components/workspace/input-box.tsx；frontend/src/components/workspace/welcome.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts；frontend/src/core/i18n/locales/zh-CN.ts。

#### 178. feat: enhance welcome component and input box with skill mode handling and localization updates

- 提交：`[26acd6f](https://github.com/bytedance/deer-flow/commit/26acd6f3ad73cb06ad0f774d23476d3771869c8c)`
- 日期：2026-02-02
- 明确新增内容：增强了“enhance welcome component and input box with skill mode handling and localization updates”相关能力与交互体验。
- 影响范围：主要涉及 前端。
- 改动规模：+33 / -9 行。
- 关键文件：frontend/src/components/workspace/input-box.tsx；frontend/src/components/workspace/welcome.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts；frontend/src/core/i18n/locales/zh-CN.ts。

#### 179. feat: update button in skill settings to include icon

- 提交：`[ccf2123](https://github.com/bytedance/deer-flow/commit/ccf21238afe33216a20dc95b25491ec2ad25e893)`
- 日期：2026-02-02
- 明确新增内容：引入了“update button in skill settings to include icon”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+2 / -1 行。
- 关键文件：frontend/src/components/workspace/settings/skill-settings-page.tsx。

#### 180. feat: update button in skill settings to include icon

- 提交：`[67451df](https://github.com/bytedance/deer-flow/commit/67451df910f0978b040924b520a215388985f3e9)`
- 日期：2026-02-02
- 明确新增内容：引入了“update button in skill settings to include icon”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+2 / -1 行。
- 关键文件：frontend/src/components/workspace/settings/skill-settings-page.tsx。

#### 181. feat: update button in skill settings to include icon

- 提交：`[9cc4113](https://github.com/bytedance/deer-flow/commit/9cc41139cbddef32df8ba95201e00875df004bc6)`
- 日期：2026-02-02
- 明确新增内容：引入了“update button in skill settings to include icon”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+2 / -1 行。
- 关键文件：frontend/src/components/workspace/settings/skill-settings-page.tsx。

#### 182. feat: use list of links

- 提交：`[efd56fd](https://github.com/bytedance/deer-flow/commit/efd56fdf512667095a6ddeb737c7d953ef91bcf2)`
- 日期：2026-02-02
- 明确新增内容：引入了“use list of links”相关功能改进。
- 影响范围：主要涉及 技能体系。
- 改动规模：+2 / -2 行。
- 关键文件：skills/public/vercel-deploy-claimable/SKILL.md。

#### 183. feat: use list of links

- 提交：`[a5a0222](https://github.com/bytedance/deer-flow/commit/a5a02229633f0a48ab5c02d3301ed7d8964157ab)`
- 日期：2026-02-02
- 明确新增内容：引入了“use list of links”相关功能改进。
- 影响范围：主要涉及 技能体系。
- 改动规模：+2 / -2 行。
- 关键文件：skills/public/vercel-deploy-claimable/SKILL.md。

#### 184. feat: use list of links

- 提交：`[207cb2b](https://github.com/bytedance/deer-flow/commit/207cb2b98d31ce258335ef33d685e0cf0424a663)`
- 日期：2026-02-02
- 明确新增内容：引入了“use list of links”相关功能改进。
- 影响范围：主要涉及 技能体系。
- 改动规模：+2 / -2 行。
- 关键文件：skills/public/vercel-deploy-claimable/SKILL.md。

#### 185. feat: update button styling for artifacts tooltip

- 提交：`[b7c9bf5](https://github.com/bytedance/deer-flow/commit/b7c9bf557b19909f175a4fa1bf7480fe29eb01ed)`
- 日期：2026-02-02
- 明确新增内容：引入了“update button styling for artifacts tooltip”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -0 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx。

#### 186. feat: update button styling for artifacts tooltip

- 提交：`[44daeaf](https://github.com/bytedance/deer-flow/commit/44daeaf37dbba05cff681aaa4011d8c6efffa52b)`
- 日期：2026-02-02
- 明确新增内容：引入了“update button styling for artifacts tooltip”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -0 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx。

#### 187. feat: update button styling for artifacts tooltip

- 提交：`[b5e9eee](https://github.com/bytedance/deer-flow/commit/b5e9eeea9984d4248e161157c70c69a6c90c42d7)`
- 日期：2026-02-02
- 明确新增内容：引入了“update button styling for artifacts tooltip”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -0 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx。

#### 188. feat: add suggestions

- 提交：`[3067f8d](https://github.com/bytedance/deer-flow/commit/3067f8dd03a102ad153ba5b3f664b36ed6722bd8)`
- 日期：2026-02-02
- 明确新增内容：新增了“suggestions”功能。
- 影响范围：主要涉及 前端。
- 改动规模：+229 / -10 行。
- 关键文件：frontend/src/components/ai-elements/suggestion.tsx；frontend/src/components/workspace/input-box.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts；frontend/src/core/i18n/locales/zh-CN.ts。

#### 189. feat: add suggestions

- 提交：`[154fbb0](https://github.com/bytedance/deer-flow/commit/154fbb0ba364d756339c5273f11fcba417c3ed7e)`
- 日期：2026-02-02
- 明确新增内容：新增了“suggestions”功能。
- 影响范围：主要涉及 前端。
- 改动规模：+229 / -10 行。
- 关键文件：frontend/src/components/ai-elements/suggestion.tsx；frontend/src/components/workspace/input-box.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts；frontend/src/core/i18n/locales/zh-CN.ts。

#### 190. feat: add suggestions

- 提交：`[e673405](https://github.com/bytedance/deer-flow/commit/e673405c00adf261c79ed48c4ae40c3debee64cc)`
- 日期：2026-02-02
- 明确新增内容：新增了“suggestions”功能。
- 影响范围：主要涉及 前端。
- 改动规模：+229 / -10 行。
- 关键文件：frontend/src/components/ai-elements/suggestion.tsx；frontend/src/components/workspace/input-box.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts；frontend/src/core/i18n/locales/zh-CN.ts。

#### 191. feat: integrate PromptInputProvider into ChatLayout and utilize prompt input controller in ChatPage

- 提交：`[6c0e5ff](https://github.com/bytedance/deer-flow/commit/6c0e5fffd07997dfef80bbcd92fa235a3bfb56ec)`
- 日期：2026-02-02
- 明确新增内容：引入了“integrate PromptInputProvider into ChatLayout and utilize prompt input controller in ChatPage”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+10 / -3 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/layout.tsx；frontend/src/app/workspace/chats/[thread_id]/page.tsx。

#### 192. feat: integrate PromptInputProvider into ChatLayout and utilize prompt input controller in ChatPage

- 提交：`[f287022](https://github.com/bytedance/deer-flow/commit/f287022ac053946176eec79ae92551bdd8c48b75)`
- 日期：2026-02-02
- 明确新增内容：引入了“integrate PromptInputProvider into ChatLayout and utilize prompt input controller in ChatPage”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+10 / -3 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/layout.tsx；frontend/src/app/workspace/chats/[thread_id]/page.tsx。

#### 193. feat: integrate PromptInputProvider into ChatLayout and utilize prompt input controller in ChatPage

- 提交：`[b1227bb](https://github.com/bytedance/deer-flow/commit/b1227bb9117b53a440568657fedcbb590fead8ad)`
- 日期：2026-02-02
- 明确新增内容：引入了“integrate PromptInputProvider into ChatLayout and utilize prompt input controller in ChatPage”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+10 / -3 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/layout.tsx；frontend/src/app/workspace/chats/[thread_id]/page.tsx。

#### 194. feat: add file icons

- 提交：`[867749d](https://github.com/bytedance/deer-flow/commit/867749d7a35896bbcd2670e9cd07615a90377024)`
- 日期：2026-02-02
- 明确新增内容：新增了“file icons”功能。
- 影响范围：主要涉及 前端。
- 改动规模：+23 / -6 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/ai-elements/chain-of-thought.tsx；frontend/src/components/workspace/artifacts/artifact-file-list.tsx；frontend/src/components/workspace/artifacts/context.tsx；frontend/src/core/utils/files.tsx。

#### 195. feat: add file icons

- 提交：`[c587460](https://github.com/bytedance/deer-flow/commit/c587460dbcc6cf6d94d5f2581fa3710308b78e7f)`
- 日期：2026-02-02
- 明确新增内容：新增了“file icons”功能。
- 影响范围：主要涉及 前端。
- 改动规模：+23 / -6 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/ai-elements/chain-of-thought.tsx；frontend/src/components/workspace/artifacts/artifact-file-list.tsx；frontend/src/components/workspace/artifacts/context.tsx；frontend/src/core/utils/files.tsx。

#### 196. feat: add file icons

- 提交：`[f1db301](https://github.com/bytedance/deer-flow/commit/f1db301d775e8295c65297cafca31595a1e2f351)`
- 日期：2026-02-02
- 明确新增内容：新增了“file icons”功能。
- 影响范围：主要涉及 前端。
- 改动规模：+23 / -6 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/ai-elements/chain-of-thought.tsx；frontend/src/components/workspace/artifacts/artifact-file-list.tsx；frontend/src/components/workspace/artifacts/context.tsx；frontend/src/core/utils/files.tsx。

#### 197. feat: add file icon

- 提交：`[37dcee4](https://github.com/bytedance/deer-flow/commit/37dcee41c01a19942926bf11bd9632cdccbafc88)`
- 日期：2026-02-02
- 明确新增内容：新增了“file icon”功能。
- 影响范围：主要涉及 前端。
- 改动规模：+236 / -186 行。
- 关键文件：frontend/src/components/workspace/artifacts/artifact-file-list.tsx；frontend/src/core/utils/files.ts；frontend/src/core/utils/files.tsx。

#### 198. feat: add file icon

- 提交：`[8bb4c35](https://github.com/bytedance/deer-flow/commit/8bb4c35416ba1d48b0d919171fb2fa95802cea2b)`
- 日期：2026-02-02
- 明确新增内容：新增了“file icon”功能。
- 影响范围：主要涉及 前端。
- 改动规模：+236 / -186 行。
- 关键文件：frontend/src/components/workspace/artifacts/artifact-file-list.tsx；frontend/src/core/utils/files.ts；frontend/src/core/utils/files.tsx。

#### 199. feat: add file icon

- 提交：`[02400e0](https://github.com/bytedance/deer-flow/commit/02400e0e8c3049e87ad19895ecc39cdb2d376fd5)`
- 日期：2026-02-02
- 明确新增内容：新增了“file icon”功能。
- 影响范围：主要涉及 前端。
- 改动规模：+236 / -186 行。
- 关键文件：frontend/src/components/workspace/artifacts/artifact-file-list.tsx；frontend/src/core/utils/files.ts；frontend/src/core/utils/files.tsx。

#### 200. feat: adjust tooltips

- 提交：`[51b4ed3](https://github.com/bytedance/deer-flow/commit/51b4ed3124dbdff29453074c9cf0d497791e8faf)`
- 日期：2026-02-02
- 明确新增内容：引入了“adjust tooltips”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+16 / -3 行。
- 关键文件：frontend/src/components/ui/tooltip.tsx；frontend/src/components/workspace/messages/message-group.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts；frontend/src/core/i18n/locales/zh-CN.ts。

#### 201. feat: adjust tooltips

- 提交：`[7274f9a](https://github.com/bytedance/deer-flow/commit/7274f9a6ae06fe9f5e89998509ebb17d4ce8160c)`
- 日期：2026-02-02
- 明确新增内容：引入了“adjust tooltips”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+16 / -3 行。
- 关键文件：frontend/src/components/ui/tooltip.tsx；frontend/src/components/workspace/messages/message-group.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts；frontend/src/core/i18n/locales/zh-CN.ts。

#### 202. feat: adjust tooltips

- 提交：`[0091da1](https://github.com/bytedance/deer-flow/commit/0091da1aeec6ca2109307e3998b330e17a048a92)`
- 日期：2026-02-02
- 明确新增内容：引入了“adjust tooltips”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+16 / -3 行。
- 关键文件：frontend/src/components/ui/tooltip.tsx；frontend/src/components/workspace/messages/message-group.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts；frontend/src/core/i18n/locales/zh-CN.ts。

#### 203. feat: wrap path and command in Tooltip for enhanced user experience

- 提交：`[6d31c1c](https://github.com/bytedance/deer-flow/commit/6d31c1c5cf8bd87781fecbbe2685ff3047d919c2)`
- 日期：2026-02-02
- 明确新增内容：增强了“wrap path and command in Tooltip for enhanced user experience”相关能力与交互体验。
- 影响范围：主要涉及 前端。
- 改动规模：+24 / -12 行。
- 关键文件：frontend/src/components/workspace/messages/message-group.tsx。

#### 204. feat: wrap path and command in Tooltip for enhanced user experience

- 提交：`[cb494fe](https://github.com/bytedance/deer-flow/commit/cb494fe4dfa19522f32af19c2bbdb99767793173)`
- 日期：2026-02-02
- 明确新增内容：增强了“wrap path and command in Tooltip for enhanced user experience”相关能力与交互体验。
- 影响范围：主要涉及 前端。
- 改动规模：+24 / -12 行。
- 关键文件：frontend/src/components/workspace/messages/message-group.tsx。

#### 205. feat: wrap path and command in Tooltip for enhanced user experience

- 提交：`[076c1f0](https://github.com/bytedance/deer-flow/commit/076c1f0985b6d8e40024e534df208fa117ecba54)`
- 日期：2026-02-02
- 明确新增内容：增强了“wrap path and command in Tooltip for enhanced user experience”相关能力与交互体验。
- 影响范围：主要涉及 前端。
- 改动规模：+24 / -12 行。
- 关键文件：frontend/src/components/workspace/messages/message-group.tsx。

#### 206. docs: add comments

- 提交：`[9010429](https://github.com/bytedance/deer-flow/commit/90104291ae14b3c12413e8e63b9ff715e1070bcf)`
- 日期：2026-02-02
- 明确新增内容：新增了“add comments”相关文档说明，补齐使用/配置指引。
- 影响范围：主要涉及 前端。
- 改动规模：+10 / -0 行。
- 关键文件：frontend/src/components/workspace/input-box.tsx。

#### 207. docs: add comments

- 提交：`[68df848](https://github.com/bytedance/deer-flow/commit/68df848b82442e79d5b616e65b164afc33a8f4ec)`
- 日期：2026-02-02
- 明确新增内容：新增了“add comments”相关文档说明，补齐使用/配置指引。
- 影响范围：主要涉及 前端。
- 改动规模：+10 / -0 行。
- 关键文件：frontend/src/components/workspace/input-box.tsx。

#### 208. docs: add comments

- 提交：`[ac16a73](https://github.com/bytedance/deer-flow/commit/ac16a73a474a578208905fe78cc14a26525a651e)`
- 日期：2026-02-02
- 明确新增内容：新增了“add comments”相关文档说明，补齐使用/配置指引。
- 影响范围：主要涉及 前端。
- 改动规模：+10 / -0 行。
- 关键文件：frontend/src/components/workspace/input-box.tsx。

#### 209. feat: add skeleton

- 提交：`[54277b9](https://github.com/bytedance/deer-flow/commit/54277b9d9ea6e21f2c1438e9dc08774d90b66cc2)`
- 日期：2026-02-02
- 明确新增内容：新增了“skeleton”功能。
- 影响范围：主要涉及 前端。
- 改动规模：+89 / -2 行。
- 关键文件：frontend/src/components/workspace/messages/skeleton.tsx；frontend/src/styles/globals.css。

#### 210. feat: add skeleton

- 提交：`[b797ef8](https://github.com/bytedance/deer-flow/commit/b797ef816831c80023c2fb83f7b18c5aa62e739a)`
- 日期：2026-02-02
- 明确新增内容：新增了“skeleton”功能。
- 影响范围：主要涉及 前端。
- 改动规模：+89 / -2 行。
- 关键文件：frontend/src/components/workspace/messages/skeleton.tsx；frontend/src/styles/globals.css。

#### 211. feat: add skeleton

- 提交：`[7da0a03](https://github.com/bytedance/deer-flow/commit/7da0a03dd0b200bcf1c6de599ca5a352efb15a52)`
- 日期：2026-02-02
- 明确新增内容：新增了“skeleton”功能。
- 影响范围：主要涉及 前端。
- 改动规模：+89 / -2 行。
- 关键文件：frontend/src/components/workspace/messages/skeleton.tsx；frontend/src/styles/globals.css。

#### 212. feat: dynamic title

- 提交：`[a0a3a3f](https://github.com/bytedance/deer-flow/commit/a0a3a3fc0225aeae5d462cb4fe021783a82e80f7)`
- 日期：2026-02-02
- 明确新增内容：引入了“dynamic title”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+51 / -2 行。
- 关键文件：frontend/src/app/layout.tsx；frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/app/workspace/chats/page.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts；frontend/src/core/i18n/locales/zh-CN.ts。

#### 213. feat: dynamic title

- 提交：`[be65130](https://github.com/bytedance/deer-flow/commit/be65130a062ab3eba98234a2574eaa5130fe0409)`
- 日期：2026-02-02
- 明确新增内容：引入了“dynamic title”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+51 / -2 行。
- 关键文件：frontend/src/app/layout.tsx；frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/app/workspace/chats/page.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts；frontend/src/core/i18n/locales/zh-CN.ts。

#### 214. feat: dynamic title

- 提交：`[1eb4da6](https://github.com/bytedance/deer-flow/commit/1eb4da6c75d59d0e1162b2f289582a111676e5bc)`
- 日期：2026-02-02
- 明确新增内容：引入了“dynamic title”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+51 / -2 行。
- 关键文件：frontend/src/app/layout.tsx；frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/app/workspace/chats/page.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts；frontend/src/core/i18n/locales/zh-CN.ts。

#### 215. feat: use `create skill` as title

- 提交：`[b540ad4](https://github.com/bytedance/deer-flow/commit/b540ad45052da2449482010095cdd8eebaf61fdd)`
- 日期：2026-02-02
- 明确新增内容：引入了“use `create skill` as title”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+8 / -1 行。
- 关键文件：frontend/src/components/workspace/welcome.tsx。

#### 216. feat: use `create skill` as title

- 提交：`[dc1190b](https://github.com/bytedance/deer-flow/commit/dc1190b228e679ada786d20584fecb2fa31174d5)`
- 日期：2026-02-02
- 明确新增内容：引入了“use `create skill` as title”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+8 / -1 行。
- 关键文件：frontend/src/components/workspace/welcome.tsx。

#### 217. feat: use `create skill` as title

- 提交：`[b50fbf8](https://github.com/bytedance/deer-flow/commit/b50fbf83d0b1570eae77c0e58531b9f177adf694)`
- 日期：2026-02-02
- 明确新增内容：引入了“use `create skill` as title”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+8 / -1 行。
- 关键文件：frontend/src/components/workspace/welcome.tsx。

#### 218. feat: add find-skills skill for discovering agent skills

- 提交：`[f082ef3](https://github.com/bytedance/deer-flow/commit/f082ef3d87903ba078a36c7cc524d5a362a211ad)`
- 日期：2026-02-01
- 明确新增内容：新增了“find-skills skill for discovering agent skills”功能。
- 影响范围：主要涉及 技能体系。
- 改动规模：+200 / -0 行。
- 关键文件：skills/public/find-skills/SKILL.md；skills/public/find-skills/scripts/install-skill.sh。

#### 219. feat: add find-skills skill for discovering agent skills

- 提交：`[e493921](https://github.com/bytedance/deer-flow/commit/e4939216fd8261d3773e6898276a5afc7c9cfac0)`
- 日期：2026-02-01
- 明确新增内容：新增了“find-skills skill for discovering agent skills”功能。
- 影响范围：主要涉及 技能体系。
- 改动规模：+200 / -0 行。
- 关键文件：skills/public/find-skills/SKILL.md；skills/public/find-skills/scripts/install-skill.sh。

#### 220. feat: add find-skills skill for discovering agent skills

- 提交：`[7fd5ba2](https://github.com/bytedance/deer-flow/commit/7fd5ba258d0ce585da05aad8cd78ae15b962bc86)`
- 日期：2026-02-01
- 明确新增内容：新增了“find-skills skill for discovering agent skills”功能。
- 影响范围：主要涉及 技能体系。
- 改动规模：+200 / -0 行。
- 关键文件：skills/public/find-skills/SKILL.md；skills/public/find-skills/scripts/install-skill.sh。

#### 221. docs: add comprehensive backend documentation

- 提交：`[9043c96](https://github.com/bytedance/deer-flow/commit/9043c964cac4267aaa2bf59c6f8779cfd4ab3d33)`
- 日期：2026-02-01
- 明确新增内容：新增了“add comprehensive backend documentation”相关文档说明，补齐使用/配置指引。
- 影响范围：主要涉及 后端。
- 改动规模：+1966 / -57 行。
- 关键文件：backend/CLAUDE.md；backend/CONTRIBUTING.md；backend/README.md；backend/docs/API.md；backend/docs/ARCHITECTURE.md；backend/docs/README.md；backend/docs/TODO.md；backend/pyproject.toml。

#### 222. docs: add comprehensive backend documentation

- 提交：`[68c3e33](https://github.com/bytedance/deer-flow/commit/68c3e3341a74f17d67efcf7d77b4938acf6d2c84)`
- 日期：2026-02-01
- 明确新增内容：新增了“add comprehensive backend documentation”相关文档说明，补齐使用/配置指引。
- 影响范围：主要涉及 后端。
- 改动规模：+1966 / -57 行。
- 关键文件：backend/CLAUDE.md；backend/CONTRIBUTING.md；backend/README.md；backend/docs/API.md；backend/docs/ARCHITECTURE.md；backend/docs/README.md；backend/docs/TODO.md；backend/pyproject.toml。

#### 223. docs: add comprehensive backend documentation

- 提交：`[4f4b7cd](https://github.com/bytedance/deer-flow/commit/4f4b7cde2e6efc5a2dc19227be0ec165eef0b1e7)`
- 日期：2026-02-01
- 明确新增内容：新增了“add comprehensive backend documentation”相关文档说明，补齐使用/配置指引。
- 影响范围：主要涉及 后端。
- 改动规模：+1966 / -57 行。
- 关键文件：backend/CLAUDE.md；backend/CONTRIBUTING.md；backend/README.md；backend/docs/API.md；backend/docs/ARCHITECTURE.md；backend/docs/README.md；backend/docs/TODO.md；backend/pyproject.toml。

#### 224. feat: update skills

- 提交：`[9b77070](https://github.com/bytedance/deer-flow/commit/9b770704067659ff5f615ef4ebb5b7105479ebda)`
- 日期：2026-02-01
- 明确新增内容：引入了“update skills”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+35 / -19 行。
- 关键文件：frontend/src/app/mock/api/skills/route.ts。

#### 225. feat: update skills

- 提交：`[7e11f28](https://github.com/bytedance/deer-flow/commit/7e11f28d55eb6d0cdafcef55e2fb5975d62cae25)`
- 日期：2026-02-01
- 明确新增内容：引入了“update skills”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+35 / -19 行。
- 关键文件：frontend/src/app/mock/api/skills/route.ts。

#### 226. feat: update skills

- 提交：`[890a837](https://github.com/bytedance/deer-flow/commit/890a8379ce4327d2974df554607f3419f9140e5f)`
- 日期：2026-02-01
- 明确新增内容：引入了“update skills”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+35 / -19 行。
- 关键文件：frontend/src/app/mock/api/skills/route.ts。

#### 227. docs: update artifacts

- 提交：`[ec444e1](https://github.com/bytedance/deer-flow/commit/ec444e1f8b7725b98e7b4fb5ba583d8e4a72b8d0)`
- 日期：2026-02-01
- 明确新增内容：新增了“update artifacts”相关文档说明，补齐使用/配置指引。
- 影响范围：主要涉及 前端。
- 改动规模：+2 / -2 行。
- 关键文件：frontend/public/demo/threads/fe3f7974-1bcb-4a01-a950-79673baafefd/thread.json。

#### 228. docs: update artifacts

- 提交：`[37e9810](https://github.com/bytedance/deer-flow/commit/37e9810191e8d55559e28221b0d6d25fb5a48321)`
- 日期：2026-02-01
- 明确新增内容：新增了“update artifacts”相关文档说明，补齐使用/配置指引。
- 影响范围：主要涉及 前端。
- 改动规模：+2 / -2 行。
- 关键文件：frontend/public/demo/threads/fe3f7974-1bcb-4a01-a950-79673baafefd/thread.json。

#### 229. docs: update artifacts

- 提交：`[e28d5d2](https://github.com/bytedance/deer-flow/commit/e28d5d2cf9d94f54d34393dca8a7e1801c04eeec)`
- 日期：2026-02-01
- 明确新增内容：新增了“update artifacts”相关文档说明，补齐使用/配置指引。
- 影响范围：主要涉及 前端。
- 改动规模：+2 / -2 行。
- 关键文件：frontend/public/demo/threads/fe3f7974-1bcb-4a01-a950-79673baafefd/thread.json。

#### 230. feat: add new demo

- 提交：`[22ef5fb](https://github.com/bytedance/deer-flow/commit/22ef5fb5ba069b96f6f23b3237ad057acd692e02)`
- 日期：2026-02-01
- 明确新增内容：新增了“new demo”功能。
- 影响范围：主要涉及 前端。
- 改动规模：+3255 / -0 行。
- 关键文件：frontend/public/demo/threads/fe3f7974-1bcb-4a01-a950-79673baafefd/thread.json；frontend/public/demo/threads/fe3f7974-1bcb-4a01-a950-79673baafefd/user-data/outputs/index.html；frontend/public/demo/threads/fe3f7974-1bcb-4a01-a950-79673baafefd/user-data/outputs/research_deerflow_20260201.md。

#### 231. feat: add new demo

- 提交：`[d131a49](https://github.com/bytedance/deer-flow/commit/d131a497d70ae58bcc17d96e0db794c175d614f7)`
- 日期：2026-02-01
- 明确新增内容：新增了“new demo”功能。
- 影响范围：主要涉及 前端。
- 改动规模：+3255 / -0 行。
- 关键文件：frontend/public/demo/threads/fe3f7974-1bcb-4a01-a950-79673baafefd/thread.json；frontend/public/demo/threads/fe3f7974-1bcb-4a01-a950-79673baafefd/user-data/outputs/index.html；frontend/public/demo/threads/fe3f7974-1bcb-4a01-a950-79673baafefd/user-data/outputs/research_deerflow_20260201.md。

#### 232. feat: add new demo

- 提交：`[88e1c7c](https://github.com/bytedance/deer-flow/commit/88e1c7c0b35fe985c16af54b8847b67127aad002)`
- 日期：2026-02-01
- 明确新增内容：新增了“new demo”功能。
- 影响范围：主要涉及 前端。
- 改动规模：+3255 / -0 行。
- 关键文件：frontend/public/demo/threads/fe3f7974-1bcb-4a01-a950-79673baafefd/thread.json；frontend/public/demo/threads/fe3f7974-1bcb-4a01-a950-79673baafefd/user-data/outputs/index.html；frontend/public/demo/threads/fe3f7974-1bcb-4a01-a950-79673baafefd/user-data/outputs/research_deerflow_20260201.md。

#### 233. feat: update github-deep-research skill

- 提交：`[f206a57](https://github.com/bytedance/deer-flow/commit/f206a574c5bc3238919d698961ecb12dc0fcc793)`
- 日期：2026-02-01
- 明确新增内容：引入了“update github-deep-research skill”相关功能改进。
- 影响范围：主要涉及 技能体系。
- 改动规模：+39 / -39 行。
- 关键文件：skills/public/github-deep-research/SKILL.md；skills/public/github-deep-research/assets/report_template.md。

#### 234. feat: update github-deep-research skill

- 提交：`[8c37c9c](https://github.com/bytedance/deer-flow/commit/8c37c9c7554a565e11023646e6f7633dac509785)`
- 日期：2026-02-01
- 明确新增内容：引入了“update github-deep-research skill”相关功能改进。
- 影响范围：主要涉及 技能体系。
- 改动规模：+39 / -39 行。
- 关键文件：skills/public/github-deep-research/SKILL.md；skills/public/github-deep-research/assets/report_template.md。

#### 235. feat: update github-deep-research skill

- 提交：`[f656fd0](https://github.com/bytedance/deer-flow/commit/f656fd076893acb312e21dd45d834344f473d526)`
- 日期：2026-02-01
- 明确新增内容：引入了“update github-deep-research skill”相关功能改进。
- 影响范围：主要涉及 技能体系。
- 改动规模：+39 / -39 行。
- 关键文件：skills/public/github-deep-research/SKILL.md；skills/public/github-deep-research/assets/report_template.md。

#### 236. feat: add tooltip for installation

- 提交：`[e1ecf62](https://github.com/bytedance/deer-flow/commit/e1ecf62afa0b18120fae771fdc8a2e05da841019)`
- 日期：2026-02-01
- 明确新增内容：新增了“tooltip for installation”功能。
- 影响范围：主要涉及 前端。
- 改动规模：+19 / -8 行。
- 关键文件：frontend/src/components/workspace/artifacts/artifact-file-detail.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts；frontend/src/core/i18n/locales/zh-CN.ts。

#### 237. feat: add tooltip for installation

- 提交：`[4721f1a](https://github.com/bytedance/deer-flow/commit/4721f1a890e24a1803079a41a287fb11d0ef6415)`
- 日期：2026-02-01
- 明确新增内容：新增了“tooltip for installation”功能。
- 影响范围：主要涉及 前端。
- 改动规模：+19 / -8 行。
- 关键文件：frontend/src/components/workspace/artifacts/artifact-file-detail.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts；frontend/src/core/i18n/locales/zh-CN.ts。

#### 238. feat: add tooltip for installation

- 提交：`[a126787](https://github.com/bytedance/deer-flow/commit/a1267875fac97c8397794ac952b5b62faf1a31eb)`
- 日期：2026-02-01
- 明确新增内容：新增了“tooltip for installation”功能。
- 影响范围：主要涉及 前端。
- 改动规模：+19 / -8 行。
- 关键文件：frontend/src/components/workspace/artifacts/artifact-file-detail.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts；frontend/src/core/i18n/locales/zh-CN.ts。

#### 239. feat: add github-deep-research skill

- 提交：`[46feff6](https://github.com/bytedance/deer-flow/commit/46feff6c16ecda1e4a0219ba5aac3b0fa59264af)`
- 日期：2026-02-01
- 明确新增内容：新增了“github-deep-research skill”功能。
- 影响范围：主要涉及 技能体系。
- 改动规模：+666 / -0 行。
- 关键文件：skills/public/github-deep-research/SKILL.md；skills/public/github-deep-research/assets/report_template.md；skills/public/github-deep-research/scripts/github_api.py。

#### 240. feat: add github-deep-research skill

- 提交：`[16122dd](https://github.com/bytedance/deer-flow/commit/16122dd92d599b8077395ddc0724f74dd765a3c5)`
- 日期：2026-02-01
- 明确新增内容：新增了“github-deep-research skill”功能。
- 影响范围：主要涉及 技能体系。
- 改动规模：+666 / -0 行。
- 关键文件：skills/public/github-deep-research/SKILL.md；skills/public/github-deep-research/assets/report_template.md；skills/public/github-deep-research/scripts/github_api.py。

#### 241. feat: add github-deep-research skill

- 提交：`[469e044](https://github.com/bytedance/deer-flow/commit/469e0449350c8c00408caf4cc26f127447ab6df3)`
- 日期：2026-02-01
- 明确新增内容：新增了“github-deep-research skill”功能。
- 影响范围：主要涉及 技能体系。
- 改动规模：+666 / -0 行。
- 关键文件：skills/public/github-deep-research/SKILL.md；skills/public/github-deep-research/assets/report_template.md；skills/public/github-deep-research/scripts/github_api.py。

## 2026-03

- 提交数：79 条

#### 1. feat: support memory import and export (#1521)

- 提交：`[9a55775](https://github.com/bytedance/deer-flow/commit/9a557751d618bf3c5d2c30f80233e940837f0599)`
- 日期：2026-03-30
- 明确新增内容：新增了对“memory import and export”的支持能力。
- 影响范围：主要涉及 前端、后端。
- 改动规模：+604 / -27 行。
- 关键文件：backend/app/gateway/routers/memory.py；backend/packages/harness/deerflow/agents/memory/updater.py；backend/packages/harness/deerflow/client.py；backend/tests/test_client.py；backend/tests/test_memory_router.py；backend/tests/test_memory_updater.py；frontend/src/app/api/memory/[...path]/route.ts；frontend/src/app/api/memory/route.ts。

#### 2. feat(gateway): implement LangGraph Platform API in Gateway, replace langgraph-cli (#1403)

- 提交：`[34e835b](https://github.com/bytedance/deer-flow/commit/34e835bc33d6d2b6c235abf76577e4383f318b86)`
- 日期：2026-03-30
- 明确新增内容：实现了“implement LangGraph Platform API in Gateway, replace langgraph-cli”这项新能力。
- 影响范围：主要涉及 后端、容器部署、前端。
- 改动规模：+3492 / -66 行。
- 关键文件：backend/app/gateway/app.py；backend/app/gateway/deps.py；backend/app/gateway/routers/**init**.py；backend/app/gateway/routers/assistants_compat.py；backend/app/gateway/routers/runs.py；backend/app/gateway/routers/thread_runs.py；backend/app/gateway/routers/threads.py；backend/app/gateway/services.py。

#### 3. feat(feishu): add configurable domain for Lark international support (#1535)

- 提交：`[7db9592](https://github.com/bytedance/deer-flow/commit/7db95926b08626ab688400562977d2996078ae36)`
- 日期：2026-03-30
- 明确新增内容：新增了对“add configurable domain for Lark international support”的支持能力。
- 影响范围：主要涉及 文档、后端、配置。
- 改动规模：+18 / -3 行。
- 关键文件：README.md；README_fr.md；README_ja.md；README_ru.md；README_zh.md；backend/app/channels/feishu.py；config.example.yaml。

#### 4. feat(sandbox): add SandboxAuditMiddleware for bash command security auditing (#1532)

- 提交：`[9aa3ff7](https://github.com/bytedance/deer-flow/commit/9aa3ff7c48434f84bafab8972bb517f4157ac042)`
- 日期：2026-03-30
- 明确新增内容：新增了“SandboxAuditMiddleware for bash command security auditing”功能。
- 影响范围：主要涉及 后端。
- 改动规模：+578 / -0 行。
- 关键文件：backend/packages/harness/deerflow/agents/middlewares/sandbox_audit_middleware.py；backend/packages/harness/deerflow/agents/middlewares/tool_error_handling_middleware.py；backend/tests/test_sandbox_audit_middleware.py。

#### 5. feat: support manual add and edit for memory facts (#1538)

- 提交：`[fc7de7f](https://github.com/bytedance/deer-flow/commit/fc7de7fffe3e9cd229d16dbfa4dd6a61251242ad)`
- 日期：2026-03-29
- 明确新增内容：新增了对“manual add and edit for memory facts”的支持能力。
- 影响范围：主要涉及 后端、前端。
- 改动规模：+978 / -53 行。
- 关键文件：backend/app/gateway/routers/memory.py；backend/docs/MEMORY_SETTINGS_REVIEW.md；backend/docs/memory-settings-sample.json；backend/packages/harness/deerflow/agents/memory/updater.py；backend/packages/harness/deerflow/client.py；backend/tests/test_client.py；backend/tests/test_memory_router.py；backend/tests/test_memory_updater.py。

#### 6. docs(config): add timeout and max_retries examples for model providers (#1549)

- 提交：`[6091ba8](https://github.com/bytedance/deer-flow/commit/6091ba83c45c47cb40e94fb2e4e5dc1a7b041126)`
- 日期：2026-03-29
- 明确新增内容：新增了“add timeout and max_retries examples for model providers”相关文档说明，补齐使用/配置指引。
- 影响范围：主要涉及 配置。
- 改动规模：+28 / -0 行。
- 关键文件：config.example.yaml。

#### 7. docs: add format step to contributing workflow (#1552)

- 提交：`[70e9f2d](https://github.com/bytedance/deer-flow/commit/70e9f2dd2c1a429bba1277823d579d71e5da1976)`
- 日期：2026-03-29
- 明确新增内容：新增了“add format step to contributing workflow”相关文档说明，补齐使用/配置指引。
- 影响范围：主要涉及 其他模块。
- 改动规模：+17 / -5 行。
- 关键文件：CONTRIBUTING.md。

#### 8. style: format unformatted files and add .omc/ to prettierignore (#1539)

- 提交：`[25df82c](https://github.com/bytedance/deer-flow/commit/25df82cbfdd521ef5fea7e4e6c7979a160856471)`
- 日期：2026-03-29
- 明确新增内容：新增了“style: format unformatted files and add .omc/ to prettierignore”功能。
- 影响范围：主要涉及 后端、前端。
- 改动规模：+19 / -33 行。
- 关键文件：backend/packages/harness/deerflow/agents/factory.py；backend/tests/test_create_deerflow_agent.py；frontend/.prettierignore。

#### 9. feat: add create_deerflow_agent SDK entry point (Phase 1) (#1203)

- 提交：`[06a623f](https://github.com/bytedance/deer-flow/commit/06a623f9c82ee93e0dc69ba9fc4b98aeac132ae3)`
- 日期：2026-03-29
- 明确新增内容：新增了“create_deerflow_agent SDK entry point (Phase 1)”功能。
- 影响范围：主要涉及 后端。
- 改动规模：+2225 / -3 行。
- 关键文件：backend/docs/middleware-execution-flow.md；backend/docs/rfc-create-deerflow-agent.md；backend/packages/harness/deerflow/agents/**init**.py；backend/packages/harness/deerflow/agents/factory.py；backend/packages/harness/deerflow/agents/features.py；backend/packages/harness/deerflow/agents/middlewares/**init**.py；backend/tests/test_client_e2e.py；backend/tests/test_client_live.py。

#### 10. feat: add memory management actions and local filters in memory settings (#1467)

- 提交：`[7eb3a15](https://github.com/bytedance/deer-flow/commit/7eb3a150b5f3f3824515417685e49f00a6acd2fd)`
- 日期：2026-03-29
- 明确新增内容：新增了“memory management actions and local filters in memory settings”功能。
- 影响范围：主要涉及 后端、前端、文档。
- 改动规模：+1025 / -130 行。
- 关键文件：README.md；backend/app/gateway/routers/memory.py；backend/docs/MEMORY_SETTINGS_REVIEW.md；backend/docs/memory-settings-sample.json；backend/packages/harness/deerflow/agents/memory/**init**.py；backend/packages/harness/deerflow/agents/memory/updater.py；backend/packages/harness/deerflow/client.py；backend/tests/test_client.py。

#### 11. feat(client): support custom middleware injection (#1520)

- 提交：`[481494b](https://github.com/bytedance/deer-flow/commit/481494b9c0e679876c73f48dc834b8d3e8cb3dd9)`
- 日期：2026-03-29
- 明确新增内容：新增了对“custom middleware injection”的支持能力。
- 影响范围：主要涉及 后端。
- 改动规模：+56 / -5 行。
- 关键文件：backend/packages/harness/deerflow/agents/lead_agent/agent.py；backend/packages/harness/deerflow/client.py；backend/tests/test_client.py；backend/tests/test_lead_agent_model_resolution.py。

#### 12. docs(frontend): update better-auth README notes (#1487)

- 提交：`[9a4e8f4](https://github.com/bytedance/deer-flow/commit/9a4e8f438ab5ce4d4157893aab9da32f24a4acfd)`
- 日期：2026-03-27
- 明确新增内容：新增了“update better-auth README notes”相关文档说明，补齐使用/配置指引。
- 影响范围：主要涉及 前端。
- 改动规模：+2 / -2 行。
- 关键文件：frontend/README.md。

#### 13. docs(README): add missing cross-language README links (#1479)

- 提交：`[6bf23ba](https://github.com/bytedance/deer-flow/commit/6bf23ba0a310803a5b7b4bd905a1ed04c3aab73e)`
- 日期：2026-03-27
- 明确新增内容：新增了“add missing cross-language README links”相关文档说明，补齐使用/配置指引。
- 影响范围：主要涉及 文档。
- 改动规模：+4 / -4 行。
- 关键文件：README_fr.md；README_ja.md；README_ru.md；README_zh.md。

#### 14. test: add unit tests for skill frontmatter validation (#1309)

- 提交：`[50f50d7](https://github.com/bytedance/deer-flow/commit/50f50d7654a030affbcd41b97e180db6d66a1782)`
- 日期：2026-03-27
- 明确新增内容：新增了“add unit tests for skill frontmatter validation”相关测试覆盖与验证用例。
- 影响范围：主要涉及 后端。
- 改动规模：+180 / -88 行。
- 关键文件：backend/tests/test_skills_router.py；backend/tests/test_skills_validation.py。

#### 15. feat(acp): add env field to ACPAgentConfig for subprocess env injection (#1447)

- 提交：`[8590249](https://github.com/bytedance/deer-flow/commit/8590249db41474c97de6eeb60190f006c962de6b)`
- 日期：2026-03-27
- 明确新增内容：新增了“env field to ACPAgentConfig for subprocess env injection”功能。
- 影响范围：主要涉及 后端、配置。
- 改动规模：+215 / -3 行。
- 关键文件：backend/packages/harness/deerflow/config/acp_config.py；backend/packages/harness/deerflow/tools/builtins/invoke_acp_agent_tool.py；backend/tests/test_acp_config.py；backend/tests/test_invoke_acp_agent_tool.py；config.example.yaml。

#### 16. docs: add LangSmith tracing configuration and documentation (#1414)

- 提交：`[a4e4bb2](https://github.com/bytedance/deer-flow/commit/a4e4bb21e3f0843a1de2e03ea00864379fa6bb8a)`
- 日期：2026-03-27
- 明确新增内容：新增了“add LangSmith tracing configuration and documentation”相关文档说明，补齐使用/配置指引。
- 影响范围：主要涉及 文档、其他模块、后端。
- 改动规模：+111 / -4 行。
- 关键文件：.env.example；README.md；README_fr.md；README_ja.md；README_ru.md；README_zh.md；backend/README.md；docker/docker-compose.yaml。

#### 17. feat: Support gitHub PAT configuration for higher github API accessing rate. (#1374)

- 提交：`[6b13f5c](https://github.com/bytedance/deer-flow/commit/6b13f5c9fb052b2efee1e76edc5af91b9244a74d)`
- 日期：2026-03-27
- 明确新增内容：新增了对“gitHub PAT configuration for higher github API accessing rate”的支持能力。
- 影响范围：主要涉及 其他模块、后端、技能体系。
- 改动规模：+17 / -3 行。
- 关键文件：.env.example；backend/docs/CONFIGURATION.md；skills/public/github-deep-research/scripts/github_api.py。

#### 18. Implement DuckDuckGo search (#1432)

- 提交：`[c137933](https://github.com/bytedance/deer-flow/commit/c13793386fbf8c1bbccbdef1c8802daf40a58d0c)`
- 日期：2026-03-26
- 明确新增内容：实现了“Implement DuckDuckGo search”这项新能力。
- 影响范围：主要涉及 后端、配置。
- 改动规模：+107 / -3 行。
- 关键文件：backend/packages/harness/deerflow/community/ddg_search/**init**.py；backend/packages/harness/deerflow/community/ddg_search/tools.py；config.example.yaml。

#### 19. feat(memory): Introduce configurable memory storage abstraction (#1353)

- 提交：`[1c542ab](https://github.com/bytedance/deer-flow/commit/1c542ab7f1524f6248412e6ba004d985a549c10b)`
- 日期：2026-03-27
- 明确新增内容：引入了“Introduce configurable memory storage abstraction”相关功能改进。
- 影响范围：主要涉及 后端。
- 改动规模：+442 / -177 行。
- 关键文件：backend/packages/harness/deerflow/agents/memory/**init**.py；backend/packages/harness/deerflow/agents/memory/storage.py；backend/packages/harness/deerflow/agents/memory/updater.py；backend/packages/harness/deerflow/config/memory_config.py；backend/tests/test_custom_agent.py；backend/tests/test_memory_storage.py；backend/tests/test_memory_updater.py。

#### 20. docs: add install.md agent setup guide (#1402)

- 提交：`[e1853df](https://github.com/bytedance/deer-flow/commit/e1853df06aa2aefb10750834802cce10af79b936)`
- 日期：2026-03-26
- 明确新增内容：新增了“add install.md agent setup guide”相关文档说明，补齐使用/配置指引。
- 影响范围：主要涉及 文档、其他模块。
- 改动规模：+142 / -0 行。
- 关键文件：Install.md；README.md；README_fr.md；README_ja.md；README_ru.md；README_zh.md。

#### 21. Add security alerts to documents (#1413)

- 提交：`[f80d174](https://github.com/bytedance/deer-flow/commit/f80d1743ab035f5041a5a6e371853ae0de30cf1e)`
- 日期：2026-03-26
- 明确新增内容：新增了“security alerts to documents”功能。
- 影响范围：主要涉及 文档。
- 改动规模：+95 / -0 行。
- 关键文件：README.md；README_fr.md；README_ja.md；README_ru.md；README_zh.md。

#### 22. feat: hide model ID for safety reason, only show the display_name (#1410)

- 提交：`[227967d](https://github.com/bytedance/deer-flow/commit/227967df3d048d93bc8576e099a405f9bc559533)`
- 日期：2026-03-26
- 明确新增内容：引入了“hide model ID for safety reason, only show the display_name”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+287 / -275 行。
- 关键文件：frontend/src/components/workspace/input-box.tsx。

#### 23. Add packages section to pnpm-workspace.yaml (#1382)

- 提交：`[c0a6b81](https://github.com/bytedance/deer-flow/commit/c0a6b81852b091d9f1187b5d035d58607b80b0b1)`
- 日期：2026-03-26
- 明确新增内容：新增了“packages section to pnpm-workspace.yaml”功能。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -0 行。
- 关键文件：frontend/pnpm-workspace.yaml。

#### 24. feat(harness): integration ACP agent tool (#1344)

- 提交：`[d119214](https://github.com/bytedance/deer-flow/commit/d119214fee616408adbe1a1d42398aa5e1d1fe20)`
- 日期：2026-03-26
- 明确新增内容：引入了“integration ACP agent tool”相关功能改进。
- 影响范围：主要涉及 后端、文档、配置。
- 改动规模：+1566 / -219 行。
- 关键文件：README.md；backend/CLAUDE.md；backend/app/channels/feishu.py；backend/app/gateway/routers/uploads.py；backend/packages/harness/deerflow/agents/lead_agent/prompt.py；backend/packages/harness/deerflow/agents/memory/prompt.py；backend/packages/harness/deerflow/agents/memory/updater.py；backend/packages/harness/deerflow/agents/middlewares/loop_detection_middleware.py。

#### 25. test: add unit tests for TodoMiddleware (#1307)

- 提交：`[ac97dc6](https://github.com/bytedance/deer-flow/commit/ac97dc6d426c92efeefa018cea4471c0bbd6834f)`
- 日期：2026-03-25
- 明确新增内容：新增了“add unit tests for TodoMiddleware”相关测试覆盖与验证用例。
- 影响范围：主要涉及 后端。
- 改动规模：+156 / -0 行。
- 关键文件：backend/tests/test_todo_middleware.py。

#### 26. test: add unit tests for DanglingToolCallMiddleware (#1305)

- 提交：`[1f0ae64](https://github.com/bytedance/deer-flow/commit/1f0ae64e0218f04f3f524e118718d9bb7fb2c7b3)`
- 日期：2026-03-25
- 明确新增内容：新增了“add unit tests for DanglingToolCallMiddleware”相关测试覆盖与验证用例。
- 影响范围：主要涉及 后端。
- 改动规模：+190 / -0 行。
- 关键文件：backend/tests/test_dangling_tool_call_middleware.py。

#### 27. Add user configuration template for China region (#1337)

- 提交：`[fdfe08d](https://github.com/bytedance/deer-flow/commit/fdfe08d4aad3d3da8d15ba1a5af4151c052acfa2)`
- 日期：2026-03-25
- 明确新增内容：新增了“user configuration template for China region”功能。
- 影响范围：主要涉及 配置。
- 改动规模：+25 / -1 行。
- 关键文件：config.example.yaml。

#### 28. docs: add domestic link of coding plan (#1340)

- 提交：`[1287566](https://github.com/bytedance/deer-flow/commit/12875664f11058329bb71d6c05dbb5dc7a0cc989)`
- 日期：2026-03-25
- 明确新增内容：新增了“add domestic link of coding plan”相关文档说明，补齐使用/配置指引。
- 影响范围：主要涉及 文档。
- 改动规模：+1 / -1 行。
- 关键文件：README_zh.md。

#### 29. test: add unit tests for SubagentLimitMiddleware (#1306)

- 提交：`[ec46ae0](https://github.com/bytedance/deer-flow/commit/ec46ae075d8f91fbff9b0d227f76180e3ab64e49)`
- 日期：2026-03-24
- 明确新增内容：新增了“add unit tests for SubagentLimitMiddleware”相关测试覆盖与验证用例。
- 影响范围：主要涉及 后端。
- 改动规模：+140 / -0 行。
- 关键文件：backend/tests/test_subagent_limit_middleware.py。

#### 30. test: add unit tests for skills parser (#1308)

- 提交：`[afb0f66](https://github.com/bytedance/deer-flow/commit/afb0f66c737d878add6c011ce383b59206097065)`
- 日期：2026-03-24
- 明确新增内容：新增了“add unit tests for skills parser”相关测试覆盖与验证用例。
- 影响范围：主要涉及 后端。
- 改动规模：+98 / -0 行。
- 关键文件：backend/tests/test_skills_parser.py。

#### 31. docs: add Russian README translation (#1311)

- 提交：`[f499f37](https://github.com/bytedance/deer-flow/commit/f499f37e94fee02e49e00d4e1e25239d6f05ab72)`
- 日期：2026-03-25
- 明确新增内容：新增了“add Russian README translation”相关文档说明，补齐使用/配置指引。
- 影响范围：主要涉及 文档。
- 改动规模：+442 / -1 行。
- 关键文件：README.md；README_ru.md。

#### 32. docs: add French translation of README (#1303)

- 提交：`[21febe1](https://github.com/bytedance/deer-flow/commit/21febe1cc960d4346a6c14d516b828039832c887)`
- 日期：2026-03-25
- 明确新增内容：新增了“add French translation of README”相关文档说明，补齐使用/配置指引。
- 影响范围：主要涉及 文档。
- 改动规模：+565 / -3 行。
- 关键文件：README.md；README_fr.md；README_ja.md；README_zh.md。

#### 33. feat: add configurable log level and token usage tracking (#1301)

- 提交：`[16ed797](https://github.com/bytedance/deer-flow/commit/16ed797e0efc537a2215b3c7c59f9839edf22d21)`
- 日期：2026-03-25
- 明确新增内容：新增了“configurable log level and token usage tracking”功能。
- 影响范围：主要涉及 后端、其他模块、配置。
- 改动规模：+74 / -3 行。
- 关键文件：.gitignore；backend/packages/harness/deerflow/agents/lead_agent/agent.py；backend/packages/harness/deerflow/agents/middlewares/token_usage_middleware.py；backend/packages/harness/deerflow/config/app_config.py；backend/packages/harness/deerflow/config/token_usage_config.py；config.example.yaml；scripts/serve.sh。

#### 34. feat(frontend): display token usage per conversation turn (#1229)

- 提交：`[b40b05f](https://github.com/bytedance/deer-flow/commit/b40b05f62347818aac71b064573e360ef644188d)`
- 日期：2026-03-23
- 明确新增内容：引入了“display token usage per conversation turn”相关功能改进。
- 影响范围：主要涉及 前端。
- 改动规模：+159 / -1 行。
- 关键文件：frontend/src/app/workspace/agents/[agent_name]/chats/[thread_id]/page.tsx；frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/workspace/token-usage-indicator.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts；frontend/src/core/i18n/locales/zh-CN.ts；frontend/src/core/messages/usage.ts。

#### 35. feat(frontend): add Cmd+K command palette and keyboard shortcuts (#1230)

- 提交：`[48031e5](https://github.com/bytedance/deer-flow/commit/48031e506b1a6222b3b887347f379ab867c905d2)`
- 日期：2026-03-23
- 明确新增内容：新增了“Cmd+K command palette and keyboard shortcuts”功能。
- 影响范围：主要涉及 前端。
- 改动规模：+213 / -0 行。
- 关键文件：frontend/src/app/workspace/layout.tsx；frontend/src/components/workspace/command-palette.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts；frontend/src/core/i18n/locales/zh-CN.ts；frontend/src/hooks/use-global-shortcuts.ts。

#### 36. feat(guardrails): add pre-tool-call authorization middleware with pluggable providers (#1240)

- 提交：`[a29134d](https://github.com/bytedance/deer-flow/commit/a29134d7c9e704e2e1f960ec92417b65bf383b4f)`
- 日期：2026-03-23
- 明确新增内容：新增了“pre-tool-call authorization middleware with pluggable providers”功能。
- 影响范围：主要涉及 后端、配置。
- 改动规模：+1041 / -7 行。
- 关键文件：backend/CLAUDE.md；backend/docs/GUARDRAILS.md；backend/packages/harness/deerflow/agents/middlewares/tool_error_handling_middleware.py；backend/packages/harness/deerflow/config/app_config.py；backend/packages/harness/deerflow/config/guardrails_config.py；backend/packages/harness/deerflow/guardrails/**init**.py；backend/packages/harness/deerflow/guardrails/builtin.py；backend/packages/harness/deerflow/guardrails/middleware.py。

#### 37. feat(client): support agent_name injection to enable isolated memory and custom prompts (#1253)

- 提交：`[fe75cb3](https://github.com/bytedance/deer-flow/commit/fe75cb35caa428e7ef60205c59c44c88492ac7b4)`
- 日期：2026-03-23
- 明确新增内容：新增了对“agent_name injection to enable isolated memory and custom prompts”的支持能力。
- 影响范围：主要涉及 后端。
- 改动规模：+47 / -4 行。
- 关键文件：backend/packages/harness/deerflow/client.py；backend/tests/test_client.py。

#### 38. feat(web): add conversation export as Markdown and JSON (#1002)

- 提交：`[38ace61](https://github.com/bytedance/deer-flow/commit/38ace61617c9d2393a76ee4e2dd6404109d7ee32)`
- 日期：2026-03-23
- 明确新增内容：新增了“conversation export as Markdown and JSON”功能。
- 影响范围：主要涉及 前端。
- 改动规模：+308 / -2 行。
- 关键文件：frontend/src/app/workspace/agents/[agent_name]/chats/[thread_id]/page.tsx；frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/workspace/export-trigger.tsx；frontend/src/components/workspace/recent-chat-list.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts；frontend/src/core/i18n/locales/zh-CN.ts；frontend/src/core/threads/export.ts。

#### 39. feat: add Claude Code OAuth and Codex CLI as LLM providers (#1166)

- 提交：`[835ba04](https://github.com/bytedance/deer-flow/commit/835ba041f8e5eb7faa59aa7192a231a02f2a798e)`
- 日期：2026-03-22
- 明确新增内容：新增了“Claude Code OAuth and Codex CLI as LLM providers”功能。
- 影响范围：主要涉及 后端、文档、容器部署。
- 改动规模：+1546 / -0 行。
- 关键文件：README.md；backend/docs/CONFIGURATION.md；backend/packages/harness/deerflow/models/claude_provider.py；backend/packages/harness/deerflow/models/credential_loader.py；backend/packages/harness/deerflow/models/factory.py；backend/packages/harness/deerflow/models/openai_codex_provider.py；backend/tests/test_cli_auth_providers.py；backend/tests/test_credential_loader.py。

#### 40. feat(codex): support explicit OpenAI Responses API config (#1235)

- 提交：`[e119dc7](https://github.com/bytedance/deer-flow/commit/e119dc74ae869d2dfd2898301f71e9e5306c7d5a)`
- 日期：2026-03-22
- 明确新增内容：新增了对“explicit OpenAI Responses API config”的支持能力。
- 影响范围：主要涉及 后端、文档、配置。
- 改动规模：+113 / -1 行。
- 关键文件：README.md；backend/CLAUDE.md；backend/README.md；backend/docs/CONFIGURATION.md；backend/packages/harness/deerflow/config/model_config.py；backend/tests/test_model_config.py；backend/tests/test_model_factory.py；config.example.yaml。

#### 41. docs: add Japanese README (#1209)

- 提交：`[9dbcca5](https://github.com/bytedance/deer-flow/commit/9dbcca579dff84eaafac8d2629097e5f9bd739a2)`
- 日期：2026-03-21
- 明确新增内容：新增了“add Japanese README”相关文档说明，补齐使用/配置指引。
- 影响范围：主要涉及 文档。
- 改动规模：+517 / -2 行。
- 关键文件：README.md；README_ja.md；README_zh.md。

#### 42. feat: track token usage per conversation turn (#1218)

- 提交：`[06cba21](https://github.com/bytedance/deer-flow/commit/06cba217c332b103e4bbe7edc031cfbc7455c168)`
- 日期：2026-03-21
- 明确新增内容：引入了“track token usage per conversation turn”相关功能改进。
- 影响范围：主要涉及 后端。
- 改动规模：+327 / -6 行。
- 关键文件：backend/packages/harness/deerflow/client.py；backend/tests/test_token_usage.py。

#### 43. refactor: add channel-based streaming capability check (#1214)

- 提交：`[e69dc29](https://github.com/bytedance/deer-flow/commit/e69dc2961f4650d107234bf1b7a28654a02ec8fa)`
- 日期：2026-03-20
- 明确新增内容：新增了“channel-based streaming capability check”功能。
- 影响范围：主要涉及 后端。
- 改动规模：+11 / -1 行。
- 关键文件：backend/app/channels/manager.py。

#### 44. feat(tools): add tool_search for deferred MCP tool loading (#1176)

- 提交：`[0091d9f](https://github.com/bytedance/deer-flow/commit/0091d9f0714763eaad3c8450e5eadfd7555cba11)`
- 日期：2026-03-17
- 明确新增内容：新增了“tool_search for deferred MCP tool loading”功能。
- 影响范围：主要涉及 后端、配置。
- 改动规模：+718 / -23 行。
- 关键文件：backend/packages/harness/deerflow/agents/lead_agent/agent.py；backend/packages/harness/deerflow/agents/lead_agent/prompt.py；backend/packages/harness/deerflow/agents/middlewares/deferred_tool_filter_middleware.py；backend/packages/harness/deerflow/config/app_config.py；backend/packages/harness/deerflow/config/tool_search_config.py；backend/packages/harness/deerflow/mcp/tools.py；backend/packages/harness/deerflow/tools/builtins/tool_search.py；backend/packages/harness/deerflow/tools/tools.py。

#### 45. docs: add coding plan from ByteDance Volcengine (#1174)

- 提交：`[f29db80](https://github.com/bytedance/deer-flow/commit/f29db80be7516c13e33dab2e10279a91aebd17e1)`
- 日期：2026-03-17
- 明确新增内容：新增了“add coding plan from ByteDance Volcengine”相关文档说明，补齐使用/配置指引。
- 影响范围：主要涉及 文档。
- 改动规模：+20 / -4 行。
- 关键文件：README.md；README_zh.md。

#### 46. docs: add README in Chinese (#1172)

- 提交：`[cb4cae4](https://github.com/bytedance/deer-flow/commit/cb4cae4064b90770681dc332874b0bb7bde3b3fb)`
- 日期：2026-03-17
- 明确新增内容：新增了“add README in Chinese”相关文档说明，补齐使用/配置指引。
- 影响范围：主要涉及 文档。
- 改动规模：+499 / -2 行。
- 关键文件：README.md；README_zh.md。

#### 47. feat: add citation/reference support to deep research reports (#1143)

- 提交：`[9809af1](https://github.com/bytedance/deer-flow/commit/9809af1f26982f73532296ddeb35a0875836ab52)`
- 日期：2026-03-17
- 明确新增内容：新增了对“add citation/reference support to deep research reports”的支持能力。
- 影响范围：主要涉及 前端、技能体系、后端。
- 改动规模：+128 / -10 行。
- 关键文件：backend/packages/harness/deerflow/agents/lead_agent/prompt.py；frontend/src/components/workspace/artifacts/artifact-file-detail.tsx；frontend/src/components/workspace/citations/artifact-link.tsx；frontend/src/components/workspace/messages/markdown-content.tsx；skills/public/github-deep-research/SKILL.md；skills/public/github-deep-research/assets/report_template.md。

#### 48. feat(feishu): stream updates on a single card (#1031)

- 提交：`[9b49a80](https://github.com/bytedance/deer-flow/commit/9b49a80ddafc0826e808f35677d153d9e310ff40)`
- 日期：2026-03-14
- 明确新增内容：引入了“stream updates on a single card”相关功能改进。
- 影响范围：主要涉及 后端。
- 改动规模：+716 / -55 行。
- 关键文件：backend/CLAUDE.md；backend/README.md；backend/src/channels/feishu.py；backend/src/channels/manager.py；backend/src/channels/service.py；backend/tests/test_channels.py。

#### 49. feat: add LoopDetectionMiddleware to break repetitive tool call loops (#1056)

- 提交：`[d18a9ae](https://github.com/bytedance/deer-flow/commit/d18a9ae5aaf579d367b321f07130857faaf75214)`
- 日期：2026-03-14
- 明确新增内容：新增了“LoopDetectionMiddleware to break repetitive tool call loops”功能。
- 影响范围：主要涉及 后端。
- 改动规模：+462 / -0 行。
- 关键文件：backend/src/agents/lead_agent/agent.py；backend/src/agents/middlewares/loop_detection_middleware.py；backend/tests/test_loop_detection_middleware.py。

#### 50. Add MiniMax as an OpenAI-compatible model provider (#1120)

- 提交：`[bbd87df](https://github.com/bytedance/deer-flow/commit/bbd87df6ebccb74c010fce96456d5a3d3095359a)`
- 日期：2026-03-14
- 明确新增内容：新增了“MiniMax as an OpenAI-compatible model provider”功能。
- 影响范围：主要涉及 后端、其他模块、配置。
- 改动规模：+131 / -0 行。
- 关键文件：.env.example；backend/docs/CONFIGURATION.md；backend/tests/test_model_factory.py；config.example.yaml。

#### 51. feat(sandbox): harden local file access and mask host paths (#983)

- 提交：`[253fe4d](https://github.com/bytedance/deer-flow/commit/253fe4d87fb8128c5e5633c3a7ee81f99fb32b71)`
- 日期：2026-03-13
- 明确新增内容：引入了“harden local file access and mask host paths”相关功能改进。
- 影响范围：主要涉及 后端。
- 改动规模：+282 / -39 行。
- 关键文件：backend/src/sandbox/tools.py；backend/tests/test_sandbox_tools_security.py。

#### 52. docs: clarify OpenRouter configuration (#1123)

- 提交：`[918ba6b](https://github.com/bytedance/deer-flow/commit/918ba6b5bfafc34c6ccc6b0660d746b82670008e)`
- 日期：2026-03-13
- 明确新增内容：新增了“clarify OpenRouter configuration”相关文档说明，补齐使用/配置指引。
- 影响范围：主要涉及 文档、后端、配置。
- 改动规模：+31 / -2 行。
- 关键文件：README.md；backend/docs/CONFIGURATION.md；config.example.yaml。

#### 53. feat: enhance Docker support with production setup and deployment script (#1086)

- 提交：`[08ea9d3](https://github.com/bytedance/deer-flow/commit/08ea9d3038e2663fdb35555f733deb58bf2c7ae1)`
- 日期：2026-03-12
- 明确新增内容：新增了对“enhance Docker support with production setup and deployment script”的支持能力。
- 影响范围：主要涉及 后端、其他模块、容器部署。
- 改动规模：+444 / -24 行。
- 关键文件：.gitignore；Makefile；README.md；backend/Dockerfile；backend/langgraph.json；backend/uv.lock；docker/docker-compose-dev.yaml；docker/docker-compose.yaml。

#### 54. feat: add dev-daemon target for background development mode (#1047)

- 提交：`[a0c38a5](https://github.com/bytedance/deer-flow/commit/a0c38a5cf307f4ae9c638770f67d13e2e314c954)`
- 日期：2026-03-11
- 明确新增内容：新增了“dev-daemon target for background development mode”功能。
- 影响范围：主要涉及 其他模块、脚本工具。
- 改动规模：+135 / -1 行。
- 关键文件：Makefile；scripts/start-daemon.sh。

#### 55. feat: add `make start` command for local previewing (#1078)

- 提交：`[2e7964d](https://github.com/bytedance/deer-flow/commit/2e7964d0aaa294cae69c53dcc70a254a287f35e6)`
- 日期：2026-03-11
- 明确新增内容：新增了“`make start` command for local previewing”功能。
- 影响范围：主要涉及 脚本工具、其他模块。
- 改动规模：+280 / -220 行。
- 关键文件：Makefile；scripts/check.sh；scripts/serve.sh；scripts/start.sh。

#### 56. chore(docker): Refactor sandbox state management and improve Docker integration (#1068)

- 提交：`[f836d8e](https://github.com/bytedance/deer-flow/commit/f836d8e17c83eb8610cb599925af5558e2138582)`
- 日期：2026-03-11
- 明确新增内容：增强了“Refactor sandbox state management and improve Docker integration”相关能力与交互体验。
- 影响范围：主要涉及 后端、脚本工具、配置。
- 改动规模：+454 / -383 行。
- 关键文件：backend/Dockerfile；backend/src/community/aio_sandbox/**init**.py；backend/src/community/aio_sandbox/aio_sandbox_provider.py；backend/src/community/aio_sandbox/file_state_store.py；backend/src/community/aio_sandbox/local_backend.py；backend/src/community/aio_sandbox/state_store.py；backend/src/config/extensions_config.py；backend/src/config/paths.py。

#### 57. feat(middleware): introduce TodoMiddleware for context-loss detection in todo management (#1041)

- 提交：`[f5bd691](https://github.com/bytedance/deer-flow/commit/f5bd691172ecd07dfe70af30fca5a123492a679c)`
- 日期：2026-03-10
- 明确新增内容：引入了“introduce TodoMiddleware for context-loss detection in todo management”相关功能改进。
- 影响范围：主要涉及 后端、前端。
- 改动规模：+125 / -19 行。
- 关键文件：backend/src/agents/lead_agent/agent.py；backend/src/agents/middlewares/todo_middleware.py；backend/src/gateway/routers/suggestions.py；backend/src/models/factory.py；backend/src/sandbox/tools.py；frontend/src/components/workspace/chats/chat-box.tsx；frontend/src/core/messages/utils.ts；frontend/src/core/threads/hooks.ts。

#### 58. feat(channels): upload file attachments via IM channels (Slack, Telegram, Feishu) (#1040)

- 提交：`[33f086b](https://github.com/bytedance/deer-flow/commit/33f086b6120e265ba2f0190667d4c7afdc902375)`
- 日期：2026-03-10
- 明确新增内容：引入了“upload file attachments via IM channels (Slack, Telegram, Feishu)”相关功能改进。
- 影响范围：主要涉及 后端、文档。
- 改动规模：+720 / -15 行。
- 关键文件：README.md；backend/src/channels/base.py；backend/src/channels/feishu.py；backend/src/channels/manager.py；backend/src/channels/message_bus.py；backend/src/channels/slack.py；backend/src/channels/telegram.py；backend/tests/test_channel_file_attachments.py。

#### 59. feat(dev): refactor service startup to use dedicated start script (#1042)

- 提交：`[f6508e0](https://github.com/bytedance/deer-flow/commit/f6508e06774799342717b237e08e76f583090f28)`
- 日期：2026-03-10
- 明确新增内容：引入了“refactor service startup to use dedicated start script”相关功能改进。
- 影响范围：主要涉及 脚本工具、其他模块。
- 改动规模：+171 / -92 行。
- 关键文件：Makefile；scripts/start.sh；scripts/wait-for-port.sh。

#### 60. Revert "feat(threads): paginate full history via summaries endpoint (#1022)" (#1037)

- 提交：`[46918f0](https://github.com/bytedance/deer-flow/commit/46918f07864fc327e8e69e939a6496bdfe3881dd)`
- 日期：2026-03-09
- 明确新增内容：引入了“Revert "feat(threads): paginate full history via summaries endpoint (#1022)"”相关功能改进。
- 影响范围：主要涉及 后端、前端。
- 改动规模：+24 / -361 行。
- 关键文件：backend/src/gateway/app.py；backend/src/gateway/routers/**init**.py；backend/src/gateway/routers/threads.py；backend/tests/test_threads_router.py；frontend/src/core/threads/hooks.ts；frontend/src/core/threads/types.ts；frontend/src/core/threads/utils.ts。

#### 61. feat(threads): paginate full history via summaries endpoint (#1022)

- 提交：`[2f47f1c](https://github.com/bytedance/deer-flow/commit/2f47f1ced216a257bc56fd06a2dec578be36e15d)`
- 日期：2026-03-09
- 明确新增内容：引入了“paginate full history via summaries endpoint”相关功能改进。
- 影响范围：主要涉及 后端、前端。
- 改动规模：+361 / -24 行。
- 关键文件：backend/src/gateway/app.py；backend/src/gateway/routers/**init**.py；backend/src/gateway/routers/threads.py；backend/tests/test_threads_router.py；frontend/src/core/threads/hooks.ts；frontend/src/core/threads/types.ts；frontend/src/core/threads/utils.ts。

#### 62. feat(channels): make mobile session settings configurable by channel and user (#1021)

- 提交：`[ac1e191](https://github.com/bytedance/deer-flow/commit/ac1e1915efc098db27ff2b95a2a81a9be2d31904)`
- 日期：2026-03-08
- 明确新增内容：引入了“make mobile session settings configurable by channel and user”相关功能改进。
- 影响范围：主要涉及 后端、文档、配置。
- 改动规模：+252 / -8 行。
- 关键文件：README.md；backend/src/channels/manager.py；backend/src/channels/service.py；backend/tests/test_channels.py；config.example.yaml。

#### 63. feat: add claude-to-deerflow skill for DeerFlow API integration (#1024)

- 提交：`[8871fca](https://github.com/bytedance/deer-flow/commit/8871fca5cbe2d4f9b68139d549b7c2b7f7313a63)`
- 日期：2026-03-08
- 明确新增内容：新增了“claude-to-deerflow skill for DeerFlow API integration”功能。
- 影响范围：主要涉及 技能体系、文档、后端。
- 改动规模：+597 / -3 行。
- 关键文件：README.md；backend/src/channels/telegram.py；skills/public/claude-to-deerflow/SKILL.md；skills/public/claude-to-deerflow/scripts/chat.sh；skills/public/claude-to-deerflow/scripts/status.sh。

#### 64. Update Nginx configuration for uploads and improve thread ID handling (#1023)

- 提交：`[3721c82](https://github.com/bytedance/deer-flow/commit/3721c82ba838d59c4e3ad70b4e2466293bb275af)`
- 日期：2026-03-08
- 明确新增内容：增强了“Update Nginx configuration for uploads and improve thread ID handling”相关能力与交互体验。
- 影响范围：主要涉及 容器部署、前端。
- 改动规模：+42 / -28 行。
- 关键文件：docker/nginx/nginx.conf；docker/nginx/nginx.local.conf；frontend/src/core/threads/hooks.ts。

#### 65. Enhance chat UI and compatible anthropic thinking messages (#1018)

- 提交：`[cf9af1f](https://github.com/bytedance/deer-flow/commit/cf9af1fe75fd1d3e216286afb57354486cded64a)`
- 日期：2026-03-08
- 明确新增内容：增强了“Enhance chat UI and compatible anthropic thinking messages”相关能力与交互体验。
- 影响范围：主要涉及 前端、后端。
- 改动规模：+213 / -129 行。
- 关键文件：backend/src/agents/middlewares/title_middleware.py；backend/src/sandbox/local/local_sandbox.py；backend/tests/test_title_middleware_core_logic.py；frontend/src/components/workspace/artifacts/context.tsx；frontend/src/components/workspace/chats/chat-box.tsx；frontend/src/components/workspace/messages/message-list.tsx；frontend/src/components/workspace/thread-title.tsx；frontend/src/core/messages/utils.ts。

#### 66. feat: add thinking settings to compatible anthropic api (#1017)

- 提交：`[3512279](https://github.com/bytedance/deer-flow/commit/3512279ce3be0d30d52160879dac21fef9c40bce)`
- 日期：2026-03-08
- 明确新增内容：新增了“thinking settings to compatible anthropic api”功能。
- 影响范围：主要涉及 后端、配置。
- 改动规模：+443 / -6 行。
- 关键文件：backend/src/config/model_config.py；backend/src/models/factory.py；backend/tests/test_model_factory.py；config.example.yaml。

#### 67. feat: add IM channels for Feishu, Slack, and Telegram (#1010)

- 提交：`[75b7302](https://github.com/bytedance/deer-flow/commit/75b7302000c066bf2ff1ba362ee6a6337d6bfc47)`
- 日期：2026-03-08
- 明确新增内容：新增了“IM channels for Feishu, Slack, and Telegram”功能。
- 影响范围：主要涉及 后端、技能体系、其他模块。
- 改动规模：+8326 / -339 行。
- 关键文件：.env.example；README.md；backend/CLAUDE.md；backend/docs/TODO.md；backend/pyproject.toml；backend/src/agents/memory/prompt.py；backend/src/agents/memory/updater.py；backend/src/agents/middlewares/memory_middleware.py。

#### 68. feat: may_ask (#981)

- 提交：`[9d2144d](https://github.com/bytedance/deer-flow/commit/9d2144d431a81960936fb9ae313a34f698c4d236)`
- 日期：2026-03-06
- 明确新增内容：引入了“may_ask”相关功能改进。
- 影响范围：主要涉及 前端、后端。
- 改动规模：+462 / -35 行。
- 关键文件：backend/src/gateway/app.py；backend/src/gateway/routers/**init**.py；backend/src/gateway/routers/suggestions.py；backend/tests/test_suggestions_router.py；frontend/src/app/workspace/agents/[agent_name]/chats/[thread_id]/page.tsx；frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/workspace/input-box.tsx；frontend/src/core/i18n/locales/en-US.ts。

#### 69. chore(ci):add copilot instructions file (#996)

- 提交：`[cfae751](https://github.com/bytedance/deer-flow/commit/cfae7519022e7e8958a990cd9d92876fa9e83b09)`
- 日期：2026-03-06
- 明确新增内容：新增了“copilot instructions file”功能。
- 影响范围：主要涉及 CI/CD。
- 改动规模：+213 / -0 行。
- 关键文件：.github/copilot-instructions.md。

#### 70. Implement optimistic UI for file uploads and enhance message handling (#967)

- 提交：`[b17c087](https://github.com/bytedance/deer-flow/commit/b17c087174cc5999392fe6160ba2fe3692acefa1)`
- 日期：2026-03-05
- 明确新增内容：实现了“Implement optimistic UI for file uploads and enhance message handling”这项新能力。
- 影响范围：主要涉及 前端、后端。
- 改动规模：+787 / -255 行。
- 关键文件：backend/src/agents/middlewares/uploads_middleware.py；backend/tests/test_uploads_middleware_core_logic.py；frontend/src/components/workspace/messages/message-list-item.tsx；frontend/src/components/workspace/thread-title.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts；frontend/src/core/i18n/locales/zh-CN.ts；frontend/src/core/messages/utils.ts。

#### 71. Add CORS_ORIGINS to .env.example for custom frontend port support (#969)

- 提交：`[7149f0c](https://github.com/bytedance/deer-flow/commit/7149f0c9b56b8de32e11a7606b4cdcd2ae93a818)`
- 日期：2026-03-04
- 明确新增内容：新增了对“Add CORS_ORIGINS to .env.example for custom frontend port support”的支持能力。
- 影响范围：主要涉及 其他模块。
- 改动规模：+3 / -0 行。
- 关键文件：.env.example。

#### 72. docs: add make install step before local dev (#955) (#963)

- 提交：`[4525952](https://github.com/bytedance/deer-flow/commit/452595255e99c7c62fe91b210920670cb533d606)`
- 日期：2026-03-04
- 明确新增内容：新增了“add make install step before local dev (#955)”相关文档说明，补齐使用/配置指引。
- 影响范围：主要涉及 文档。
- 改动规模：+8 / -3 行。
- 关键文件：README.md。

#### 73. Refactor hooks and improve error handling in chat functionality (#962)

- 提交：`[14d1e01](https://github.com/bytedance/deer-flow/commit/14d1e01149177ac4f15dc0c9c936f7ee8790ace3)`
- 日期：2026-03-04
- 明确新增内容：增强了“Refactor hooks and improve error handling in chat functionality”相关能力与交互体验。
- 影响范围：主要涉及 前端、后端。
- 改动规模：+46 / -37 行。
- 关键文件：backend/src/agents/lead_agent/agent.py；frontend/src/app/workspace/agents/[agent_name]/chats/[thread_id]/page.tsx；frontend/src/app/workspace/agents/new/page.tsx；frontend/src/components/workspace/artifacts/artifact-trigger.tsx；frontend/src/components/workspace/chats/use-thread-chat.ts；frontend/src/core/threads/hooks.ts。

#### 74. feat(agent):Supports custom agent and chat experience with refactoring (#957)

- 提交：`[7de9439](https://github.com/bytedance/deer-flow/commit/7de94394d4295182701ffb47e938e7c39b963091)`
- 日期：2026-03-03
- 明确新增内容：新增了对“Supports custom agent and chat experience with refactoring”的支持能力。
- 影响范围：主要涉及 前端、后端、技能体系。
- 改动规模：+3001 / -502 行。
- 关键文件：Makefile；backend/src/agents/lead_agent/agent.py；backend/src/agents/lead_agent/prompt.py；backend/src/agents/memory/queue.py；backend/src/agents/memory/updater.py；backend/src/agents/middlewares/memory_middleware.py；backend/src/config/agents_config.py；backend/src/config/paths.py。

#### 75. feat(skills): support recursive nested skill loading (#950)

- 提交：`[7754c49](https://github.com/bytedance/deer-flow/commit/7754c49217bb111ab528e87f8570c6e6725dc05c)`
- 日期：2026-03-02
- 明确新增内容：新增了对“recursive nested skill loading”的支持能力。
- 影响范围：主要涉及 后端。
- 改动规模：+79 / -13 行。
- 关键文件：backend/CLAUDE.md；backend/README.md；backend/src/skills/loader.py；backend/src/skills/parser.py；backend/src/skills/types.py；backend/tests/test_skills_loader.py。

#### 76. feat: add reasoning_effort configuration support for Doubao/GPT-5 models (#947)

- 提交：`[a138d53](https://github.com/bytedance/deer-flow/commit/a138d5388ab807b85d6f03c20d2ba59a764d84cf)`
- 日期：2026-03-02
- 明确新增内容：新增了对“add reasoning_effort configuration support for Doubao/GPT-5 models”的支持能力。
- 影响范围：主要涉及 后端、前端、其他模块。
- 改动规模：+212 / -33 行。
- 关键文件：.gitignore；backend/src/agents/lead_agent/agent.py；backend/src/client.py；backend/src/config/app_config.py；backend/src/config/extensions_config.py；backend/src/config/model_config.py；backend/src/gateway/routers/models.py；backend/src/models/factory.py。

#### 77. refactor(frontend): optimize network queries and improve code readability (#919)

- 提交：`[72df234](https://github.com/bytedance/deer-flow/commit/72df234636ed8199ab7169e01f435d4f0518124e)`
- 日期：2026-03-02
- 明确新增内容：增强了“optimize network queries and improve code readability”相关能力与交互体验。
- 影响范围：主要涉及 前端。
- 改动规模：+15 / -29 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/core/models/api.ts；frontend/src/core/models/hooks.ts；frontend/src/core/threads/hooks.ts；frontend/src/core/threads/utils.ts。

#### 78. feat(mcp): add OAuth support for HTTP/SSE MCP servers (#908)

- 提交：`[a2f91c7](https://github.com/bytedance/deer-flow/commit/a2f91c75946a2e8eccb86127f89a34aa5fe4655d)`
- 日期：2026-03-01
- 明确新增内容：新增了对“add OAuth support for HTTP/SSE MCP servers”的支持能力。
- 影响范围：主要涉及 后端、文档、其他模块。
- 改动规模：+497 / -20 行。
- 关键文件：README.md；backend/CLAUDE.md；backend/README.md；backend/docs/API.md；backend/docs/MCP_SERVER.md；backend/src/config/extensions_config.py；backend/src/gateway/routers/mcp.py；backend/src/mcp/oauth.py。

#### 79. test(backend): add core logic unit tests for task/title/mcp (#936)

- 提交：`[3d3ea84](https://github.com/bytedance/deer-flow/commit/3d3ea84a5796c7c2558c1ada50cad60a8595a573)`
- 日期：2026-03-01
- 明确新增内容：新增了“add core logic unit tests for task/title/mcp”相关测试覆盖与验证用例。
- 影响范围：主要涉及 后端。
- 改动规模：+460 / -6 行。
- 关键文件：backend/tests/test_client.py；backend/tests/test_client_live.py；backend/tests/test_mcp_client_config.py；backend/tests/test_task_tool_core_logic.py；backend/tests/test_title_middleware_core_logic.py。

## 2026-04

- 提交数：68 条

#### 1. feat(channels): add DingTalk channel integration (#2628)

- 提交：`[08afdcb](https://github.com/bytedance/deer-flow/commit/08afdcb907f149312f31827aa1a96eeaa67b85f9)`
- 日期：2026-04-30
- 明确新增内容：新增了“DingTalk channel integration”功能。
- 影响范围：主要涉及 后端、文档、其他模块。
- 改动规模：+2544 / -7 行。
- 关键文件：.env.example；README.md；README_fr.md；README_ja.md；README_ru.md；README_zh.md；backend/CLAUDE.md；backend/app/channels/base.py。

#### 2. chore(adpator):Adapt MindIE engine model and improve testing and fixes (#2523)

- 提交：`[395c143](https://github.com/bytedance/deer-flow/commit/395c14357b60926a63af2142ac96bbb670ecb768)`
- 日期：2026-04-28
- 明确新增内容：增强了“Adapt MindIE engine model and improve testing and fixes”相关能力与交互体验。
- 影响范围：主要涉及 后端。
- 改动规模：+100 / -7 行。
- 关键文件：backend/packages/harness/deerflow/models/mindie_provider.py；backend/tests/test_mindie_provider.py。

#### 3. feat: implement process-local internal authentication for Gateway and enhance CSRF handling

- 提交：`[da174df](https://github.com/bytedance/deer-flow/commit/da174dfd4d65bb23613d1185c61ddf3e8846a91d)`
- 日期：2026-04-26
- 明确新增内容：实现了“implement process-local internal authentication for Gateway and enhance CSRF handling”这项新能力。
- 影响范围：主要涉及 后端、文档。
- 改动规模：+134 / -26 行。
- 关键文件：README.md；backend/CLAUDE.md；backend/app/channels/manager.py；backend/app/gateway/app.py；backend/app/gateway/auth_middleware.py；backend/app/gateway/internal_auth.py；backend/packages/harness/deerflow/agents/memory/queue.py；backend/packages/harness/deerflow/agents/memory/storage.py。

#### 4. feat: add default database configuration for AppConfig and update example config

- 提交：`[35ef8b7](https://github.com/bytedance/deer-flow/commit/35ef8b7c136a61d47a300e2413800f257217feca)`
- 日期：2026-04-26
- 明确新增内容：新增了“default database configuration for AppConfig and update example config”功能。
- 影响范围：主要涉及 后端、配置。
- 改动规模：+61 / -2 行。
- 关键文件：backend/packages/harness/deerflow/config/app_config.py；backend/tests/test_app_config_reload.py；config.example.yaml。

#### 5. feat: add request parameter to generate_suggestions endpoint for enhanced context

- 提交：`[3b71e2d](https://github.com/bytedance/deer-flow/commit/3b71e2d37793233862b3701d99bb579da2407c82)`
- 日期：2026-04-26
- 明确新增内容：新增了“request parameter to generate_suggestions endpoint for enhanced context”功能。
- 影响范围：主要涉及 后端。
- 改动规模：+1 / -1 行。
- 关键文件：backend/app/gateway/routers/suggestions.py。

#### 6. feat: enhance chat history loading with new hooks and UI components (#2338)

- 提交：`[db5ad86](https://github.com/bytedance/deer-flow/commit/db5ad86381159d7d7f57de499b01515dba350803)`
- 日期：2026-04-19
- 明确新增内容：增强了“enhance chat history loading with new hooks and UI components”相关能力与交互体验。
- 影响范围：主要涉及 前端、后端。
- 改动规模：+746 / -1438 行。
- 关键文件：backend/app/gateway/deps.py；backend/app/gateway/routers/runs.py；backend/app/gateway/routers/thread_runs.py；backend/app/gateway/routers/uploads.py；backend/app/gateway/services.py；backend/packages/harness/deerflow/agents/middlewares/loop_detection_middleware.py；backend/packages/harness/deerflow/agents/middlewares/summarization_middleware.py；backend/packages/harness/deerflow/agents/middlewares/thread_data_middleware.py。

#### 7. feat(persistence): per-user filesystem isolation, run-scoped APIs, and state/history simplification (#2153)

- 提交：`[2e05f38](https://github.com/bytedance/deer-flow/commit/2e05f380c4c01398f0077923b1d792dcd9b4d3b3)`
- 日期：2026-04-12
- 明确新增内容：引入了“per-user filesystem isolation, run-scoped APIs, and state/history simplification”相关功能改进。
- 影响范围：主要涉及 后端。
- 改动规模：+1630 / -783 行。
- 关键文件：backend/CLAUDE.md；backend/app/channels/feishu.py；backend/app/channels/manager.py；backend/app/gateway/path_utils.py；backend/app/gateway/routers/memory.py；backend/app/gateway/routers/runs.py；backend/app/gateway/routers/thread_runs.py；backend/app/gateway/routers/threads.py。

#### 8. feat: Add metadata and descriptions to various documentation pages in Chinese

- 提交：`[44d9953](https://github.com/bytedance/deer-flow/commit/44d9953e2e2f4f2993660ecb191be86ed89e608a)`
- 日期：2026-04-12
- 明确新增内容：新增了“metadata and descriptions to various documentation pages in Chinese”功能。
- 影响范围：主要涉及 前端、其他模块。
- 改动规模：+516 / -1015 行。
- 关键文件：deer-flow.code-workspace；frontend/src/app/[lang]/docs/layout.tsx；frontend/src/components/landing/footer.tsx；frontend/src/content/en/_meta.ts；frontend/src/content/en/application/agents-and-threads.mdx；frontend/src/content/en/application/configuration.mdx；frontend/src/content/en/application/deployment-guide.mdx；frontend/src/content/en/application/index.mdx。

#### 9. feat(persistence):Unified persistence layer with event store, feedback, and rebase cleanup (#2134)

- 提交：`[56d5fa3](https://github.com/bytedance/deer-flow/commit/56d5fa3337cb6ecf54620c2fe09379aedffaa5e7)`
- 日期：2026-04-12
- 明确新增内容：引入了“Unified persistence layer with event store, feedback, and rebase cleanup”相关功能改进。
- 影响范围：主要涉及 后端、前端、文档。
- 改动规模：+3036 / -799 行。
- 关键文件：backend/app/gateway/app.py；backend/app/gateway/authz.py；backend/app/gateway/deps.py；backend/app/gateway/langgraph_auth.py；backend/app/gateway/routers/feedback.py；backend/app/gateway/routers/thread_runs.py；backend/app/gateway/routers/threads.py；backend/app/gateway/services.py。

#### 10. docs: fill all TBD documentation pages and add new harness module pages

- 提交：`[88f822a](https://github.com/bytedance/deer-flow/commit/88f822a8b3150d845395c3fa10adf74ee5cc9b73)`
- 日期：2026-04-11
- 明确新增内容：新增了“fill all TBD documentation pages and add new harness module pages”相关文档说明，补齐使用/配置指引。
- 影响范围：主要涉及 前端。
- 改动规模：+2449 / -17 行。
- 关键文件：frontend/src/content/en/application/agents-and-threads.mdx；frontend/src/content/en/application/configuration.mdx；frontend/src/content/en/application/deployment-guide.mdx；frontend/src/content/en/application/index.mdx；frontend/src/content/en/application/operations-and-troubleshooting.mdx；frontend/src/content/en/application/quick-start.mdx；frontend/src/content/en/application/workspace-usage.mdx；frontend/src/content/en/harness/_meta.ts。

#### 11. docs: complete all English and Chinese documentation pages

- 提交：`[814a488](https://github.com/bytedance/deer-flow/commit/814a488bcbf7bbbd54a969148a29173809ff6f7e)`
- 日期：2026-04-11
- 明确新增内容：新增了“complete all English and Chinese documentation pages”相关文档说明，补齐使用/配置指引。
- 影响范围：主要涉及 前端。
- 改动规模：+4890 / -37 行。
- 关键文件：frontend/src/content/en/harness/customization.mdx；frontend/src/content/en/harness/integration-guide.mdx；frontend/src/content/en/harness/quick-start.mdx；frontend/src/content/en/reference/api-gateway-reference.mdx；frontend/src/content/en/reference/concepts-glossary.mdx；frontend/src/content/en/reference/configuration-reference.mdx；frontend/src/content/en/reference/runtime-flags-and-modes.mdx；frontend/src/content/en/reference/source-map.mdx。

#### 12. feat(dependencies): add langchain-ollama and ollama packages with optional dependencies

- 提交：`[7ff9077](https://github.com/bytedance/deer-flow/commit/7ff90770749132219b729095466da194f9f61371)`
- 日期：2026-04-11
- 明确新增内容：新增了“langchain-ollama and ollama packages with optional dependencies”功能。
- 影响范围：主要涉及 后端。
- 改动规模：+7 / -0 行。
- 关键文件：backend/uv.lock。

#### 13. feat: replace auto-admin creation with secure interactive first-boot setup (#2063)

- 提交：`[848ace9](https://github.com/bytedance/deer-flow/commit/848ace98cb0ca54735f6003b711d0bbb21eecab8)`
- 日期：2026-04-11
- 明确新增内容：引入了“replace auto-admin creation with secure interactive first-boot setup”相关功能改进。
- 影响范围：主要涉及 后端、前端。
- 改动规模：+793 / -205 行。
- 关键文件：backend/app/gateway/app.py；backend/app/gateway/auth/errors.py；backend/app/gateway/auth/local_provider.py；backend/app/gateway/auth/repositories/base.py；backend/app/gateway/auth/repositories/sqlite.py；backend/app/gateway/auth_middleware.py；backend/app/gateway/csrf_middleware.py；backend/app/gateway/routers/auth.py。

#### 14. feat(auth): release-validation pass for 2.0-rc — 12 blockers + simplify follow-ups (#2008)

- 提交：`[94eee95](https://github.com/bytedance/deer-flow/commit/94eee95fe0a10f3b46eaff4860ff388a058d7582)`
- 日期：2026-04-09
- 明确新增内容：引入了“release-validation pass for 2.0-rc — 12 blockers + simplify follow-ups”相关功能改进。
- 影响范围：主要涉及 后端、前端、容器部署。
- 改动规模：+9144 / -431 行。
- 关键文件：backend/app/gateway/app.py；backend/app/gateway/auth/**init**.py；backend/app/gateway/auth/config.py；backend/app/gateway/auth/credential_file.py；backend/app/gateway/auth/errors.py；backend/app/gateway/auth/jwt.py；backend/app/gateway/auth/local_provider.py；backend/app/gateway/auth/models.py。

#### 15. feat(persistence): add unified persistence layer with event store, token tracking, and feedback (#1930)

- 提交：`[d8ecaf4](https://github.com/bytedance/deer-flow/commit/d8ecaf46c977513c1b6f51954ffffea631966df8)`
- 日期：2026-04-07
- 明确新增内容：新增了“unified persistence layer with event store, token tracking, and feedback”功能。
- 影响范围：主要涉及 后端、其他模块、配置。
- 改动规模：+6451 / -463 行。
- 关键文件：.env.example；backend/Dockerfile；backend/app/gateway/app.py；backend/app/gateway/deps.py；backend/app/gateway/routers/feedback.py；backend/app/gateway/routers/thread_runs.py；backend/app/gateway/routers/threads.py；backend/app/gateway/services.py。

#### 16. feat(dev): add pre-commit hooks for ruff, eslint, and prettier (#2525)

- 提交：`[8a04414](https://github.com/bytedance/deer-flow/commit/8a044142cbf86ffa6bd445db7d129f9ac051d608)`
- 日期：2026-04-26
- 明确新增内容：新增了“pre-commit hooks for ruff, eslint, and prettier”功能。
- 影响范围：主要涉及 其他模块、配置、文档。
- 改动规模：+38 / -3 行。
- 关键文件：.pre-commit-config.yaml；CONTRIBUTING.md；Makefile；README.md。

#### 17. feat(mcp): support custom tool interceptors via extensions_config.json (#2451)

- 提交：`[f394c0d](https://github.com/bytedance/deer-flow/commit/f394c0d8c8de8821ac6a5becc73f5a9587a03e42)`
- 日期：2026-04-25
- 明确新增内容：新增了对“custom tool interceptors via extensions_config.json”的支持能力。
- 影响范围：主要涉及 后端、其他模块。
- 改动规模：+334 / -0 行。
- 关键文件：backend/docs/MCP_SERVER.md；backend/packages/harness/deerflow/mcp/tools.py；backend/tests/test_mcp_custom_interceptors.py；extensions_config.example.json。

#### 18. feat(models): Provider for MindIE model engine (#2483)

- 提交：`[2bb1a2d](https://github.com/bytedance/deer-flow/commit/2bb1a2dfa28fb79a308b5f980fabd44693bcd0f7)`
- 日期：2026-04-25
- 明确新增内容：引入了“Provider for MindIE model engine”相关功能改进。
- 影响范围：主要涉及 后端、配置。
- 改动规模：+682 / -1 行。
- 关键文件：backend/packages/harness/deerflow/models/factory.py；backend/packages/harness/deerflow/models/mindie_provider.py；backend/pyproject.toml；backend/tests/test_mindie_provider.py；backend/uv.lock；config.example.yaml。

#### 19. feat(trace):Add run_name to the trace info for system agents. (#2492)

- 提交：`[11f557a](https://github.com/bytedance/deer-flow/commit/11f557a2c691bf77be76e5b1d914c1ddb55fde05)`
- 日期：2026-04-24
- 明确新增内容：新增了“run_name to the trace info for system agents”功能。
- 影响范围：主要涉及 后端。
- 改动规模：+34 / -4 行。
- 关键文件：backend/app/gateway/routers/suggestions.py；backend/packages/harness/deerflow/agents/memory/updater.py；backend/packages/harness/deerflow/agents/middlewares/title_middleware.py；backend/packages/harness/deerflow/skills/security_scanner.py；backend/tests/test_memory_updater.py；backend/tests/test_security_scanner.py；backend/tests/test_suggestions_router.py；backend/tests/test_title_middleware_core_logic.py。

#### 20. feat(subagents): support per-subagent skill loading and custom subagent types (#2253)

- 提交：`[30d619d](https://github.com/bytedance/deer-flow/commit/30d619de08291fe5657559c00bf0a389c9ea74a6)`
- 日期：2026-04-23
- 明确新增内容：新增了对“per-subagent skill loading and custom subagent types”的支持能力。
- 影响范围：主要涉及 后端、前端、配置。
- 改动规模：+962 / -72 行。
- 关键文件：backend/app/gateway/routers/agents.py；backend/packages/harness/deerflow/agents/lead_agent/prompt.py；backend/packages/harness/deerflow/config/subagents_config.py；backend/packages/harness/deerflow/subagents/config.py；backend/packages/harness/deerflow/subagents/executor.py；backend/packages/harness/deerflow/subagents/registry.py；backend/packages/harness/deerflow/tools/builtins/setup_agent_tool.py；backend/packages/harness/deerflow/tools/builtins/task_tool.py。

#### 21. feat: add optional prompt-toolkit support to debug.py (#2461)

- 提交：`[c42ae3a](https://github.com/bytedance/deer-flow/commit/c42ae3af79430c7637277118838dbf6cfd3ae881)`
- 日期：2026-04-23
- 明确新增内容：新增了对“add optional prompt-toolkit support to debug.py”的支持能力。
- 影响范围：主要涉及 后端。
- 改动规模：+19 / -4 行。
- 关键文件：backend/debug.py；backend/pyproject.toml。

#### 22. feat(frontend): add Playwright E2E tests with CI workflow (#2279)

- 提交：`[c6b0423](https://github.com/bytedance/deer-flow/commit/c6b0423558cafb603b01148bbc999a0b883b315e)`
- 日期：2026-04-18
- 明确新增内容：新增了“add Playwright E2E tests with CI workflow”相关测试覆盖与验证用例。
- 影响范围：主要涉及 前端、其他模块、CI/CD。
- 改动规模：+671 / -14 行。
- 关键文件：.github/workflows/e2e-tests.yml；.gitignore；CONTRIBUTING.md；frontend/AGENTS.md；frontend/CLAUDE.md；frontend/Makefile；frontend/README.md；frontend/package.json。

#### 23. feat: show token usage per assistant response (#2270)

- 提交：`[105db00](https://github.com/bytedance/deer-flow/commit/105db0098784ed3c44158420938052c51b1691f3)`
- 日期：2026-04-16
- 明确新增内容：引入了“show token usage per assistant response”相关功能改进。
- 影响范围：主要涉及 前端、后端、配置。
- 改动规模：+271 / -50 行。
- 关键文件：backend/app/gateway/routers/models.py；backend/packages/harness/deerflow/client.py；backend/tests/test_client.py；config.example.yaml；frontend/src/app/workspace/agents/[agent_name]/chats/[thread_id]/page.tsx；frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/workspace/messages/message-list-item.tsx；frontend/src/components/workspace/messages/message-list.tsx。

#### 24. test: add unit tests for ViewImageMiddleware (#2256)

- 提交：`[8e35913](https://github.com/bytedance/deer-flow/commit/8e3591312afcbda911881c2fa1b932aa0295b531)`
- 日期：2026-04-15
- 明确新增内容：新增了“add unit tests for ViewImageMiddleware”相关测试覆盖与验证用例。
- 影响范围：主要涉及 后端。
- 改动规模：+398 / -0 行。
- 关键文件：backend/tests/test_view_image_middleware.py。

#### 25. feat: flush memory before summarization (#2176)

- 提交：`[4ba3167](https://github.com/bytedance/deer-flow/commit/4ba3167f48b212605203c35cb5883e5520e53fa6)`
- 日期：2026-04-14
- 明确新增内容：引入了“flush memory before summarization”相关功能改进。
- 影响范围：主要涉及 后端。
- 改动规模：+666 / -188 行。
- 关键文件：backend/packages/harness/deerflow/agents/lead_agent/agent.py；backend/packages/harness/deerflow/agents/memory/message_processing.py；backend/packages/harness/deerflow/agents/memory/queue.py；backend/packages/harness/deerflow/agents/memory/summarization_hook.py；backend/packages/harness/deerflow/agents/middlewares/memory_middleware.py；backend/packages/harness/deerflow/agents/middlewares/summarization_middleware.py；backend/tests/test_lead_agent_model_resolution.py；backend/tests/test_memory_queue.py。

#### 26.  feat: switch memory updater to async LLM calls (#2138)

- 提交：`[07fc25d](https://github.com/bytedance/deer-flow/commit/07fc25d2857ea25b46dc635c9059eba8f8ce6dfe)`
- 日期：2026-04-14
- 明确新增内容：引入了“switch memory updater to async LLM calls”相关功能改进。
- 影响范围：主要涉及 后端。
- 改动规模：+278 / -82 行。
- 关键文件：backend/docs/TODO.md；backend/packages/harness/deerflow/agents/memory/updater.py；backend/tests/test_memory_updater.py。

#### 27. feat(frontend): set up Vitest frontend testing infrastructure with CI workflow (#2147)

- 提交：`[4efc8d4](https://github.com/bytedance/deer-flow/commit/4efc8d404fad850664e7f74657303b0ea409d6ee)`
- 日期：2026-04-12
- 明确新增内容：引入了“set up Vitest frontend testing infrastructure with CI workflow”相关功能改进。
- 影响范围：主要涉及 前端、CI/CD、其他模块。
- 改动规模：+632 / -336 行。
- 关键文件：.github/workflows/frontend-unit-tests.yml；CONTRIBUTING.md；frontend/AGENTS.md；frontend/CLAUDE.md；frontend/Makefile；frontend/README.md；frontend/package.json；frontend/pnpm-lock.yaml。

#### 28. docs: move completed async migration to Completed Features (#2146)

- 提交：`[979a461](https://github.com/bytedance/deer-flow/commit/979a461af5bd4e61ec1654c99f3ec9589a2edbb3)`
- 日期：2026-04-12
- 明确新增内容：新增了“move completed async migration to Completed Features”相关文档说明，补齐使用/配置指引。
- 影响范围：主要涉及 后端。
- 改动规模：+2 / -2 行。
- 关键文件：backend/docs/TODO.md。

#### 29. feat(subagents): allow model override per subagent in config.yaml (#2064)

- 提交：`[ac04f27](https://github.com/bytedance/deer-flow/commit/ac04f2704f933dcb1b22369ea7ee2b4f89740caa)`
- 日期：2026-04-12
- 明确新增内容：引入了“allow model override per subagent in config.yaml”相关功能改进。
- 影响范围：主要涉及 后端、配置。
- 改动规模：+196 / -2 行。
- 关键文件：backend/packages/harness/deerflow/config/subagents_config.py；backend/packages/harness/deerflow/subagents/registry.py；backend/tests/test_subagent_timeout_config.py；config.example.yaml。

#### 30. feat(channels): add Discord channel integration (#1806)

- 提交：`[c4d273a](https://github.com/bytedance/deer-flow/commit/c4d273a68a6b72bf2dec75c0b230f3fba68bc212)`
- 日期：2026-04-11
- 明确新增内容：新增了“Discord channel integration”功能。
- 影响范围：主要涉及 后端、其他模块。
- 改动规模：+299 / -0 行。
- 关键文件：.env.example；backend/app/channels/discord.py；backend/app/channels/manager.py；backend/app/channels/service.py；backend/tests/test_discord_channel.py。

#### 31. Add Contributor Covenant Code of Conduct

- 提交：`[679ca65](https://github.com/bytedance/deer-flow/commit/679ca657ee09af1e09d32ab06f3ef27ddf75d8bb)`
- 日期：2026-04-10
- 明确新增内容：新增了“Contributor Covenant Code of Conduct”功能。
- 影响范围：主要涉及 其他模块。
- 改动规模：+128 / -0 行。
- 关键文件：CODE_OF_CONDUCT.md。

#### 32. feat: add WeChat channel integration (#1869)

- 提交：`[fa96acd](https://github.com/bytedance/deer-flow/commit/fa96acdf4b20e45229c25974a00fe397c5f46c89)`
- 日期：2026-04-10
- 明确新增内容：新增了“WeChat channel integration”功能。
- 影响范围：主要涉及 后端、文档、配置。
- 改动规模：+2699 / -0 行。
- 关键文件：README.md；backend/app/channels/manager.py；backend/app/channels/service.py；backend/app/channels/wechat.py；backend/tests/test_wechat_channel.py；config.example.yaml。

#### 33. feat(provisioner): add optional PVC support for sandbox volumes  (#2020)

- 提交：`[90299e2](https://github.com/bytedance/deer-flow/commit/90299e2710bf82079e6db5c88e227f75e75913fb)`
- 日期：2026-04-10
- 明确新增内容：新增了对“add optional PVC support for sandbox volumes”的支持能力。
- 影响范围：主要涉及 后端、容器部署。
- 改动规模：+255 / -55 行。
- 关键文件：backend/tests/conftest.py；backend/tests/test_provisioner_kubeconfig.py；backend/tests/test_provisioner_pvc_volumes.py；docker/docker-compose-dev.yaml；docker/provisioner/README.md；docker/provisioner/app.py。

#### 34. feat(blog): implement blog structure with post listing, tagging, and layout enhancements (#1962)

- 提交：`[7dc0c7d](https://github.com/bytedance/deer-flow/commit/7dc0c7d01f3719dc40ca1f7ebdd4cc9f16ca83e8)`
- 日期：2026-04-10
- 明确新增内容：实现了“implement blog structure with post listing, tagging, and layout enhancements”这项新能力。
- 影响范围：主要涉及 前端。
- 改动规模：+868 / -11 行。
- 关键文件：frontend/src/app/[lang]/docs/layout.tsx；frontend/src/app/blog/[[...mdxPath]]/page.tsx；frontend/src/app/blog/layout.tsx；frontend/src/app/blog/posts/page.tsx；frontend/src/app/blog/tags/[tag]/page.tsx；frontend/src/components/landing/header.tsx；frontend/src/components/landing/post-list.tsx；frontend/src/content/en/_meta.ts。

#### 35. Add TypeScript SDK path to code-workspace settings (#2052)

- 提交：`[809b341](https://github.com/bytedance/deer-flow/commit/809b341350f493bb20e59be3bd96fb72ba35615c)`
- 日期：2026-04-10
- 明确新增内容：新增了“TypeScript SDK path to code-workspace settings”功能。
- 影响范围：主要涉及 其他模块。
- 改动规模：+1 / -0 行。
- 关键文件：deer-flow.code-workspace。

#### 36. test(skills): add evaluation + trigger analysis for systematic-literature-review (#2061)

- 提交：`[654354c](https://github.com/bytedance/deer-flow/commit/654354c624bfc84ecbb60f1394ca4806590bcbdf)`
- 日期：2026-04-10
- 明确新增内容：新增了“add evaluation + trigger analysis for systematic-literature-review”相关测试覆盖与验证用例。
- 影响范围：主要涉及 技能体系。
- 改动规模：+182 / -1 行。
- 关键文件：skills/public/systematic-literature-review/SKILL.md；skills/public/systematic-literature-review/evals/evals.json；skills/public/systematic-literature-review/evals/trigger_eval_set.json。

#### 37. feat(dx): Setup Wizard + doctor command — closes #2030 (#2034)

- 提交：`[eef0a6e](https://github.com/bytedance/deer-flow/commit/eef0a6e2dadefd360a74ffbc19c5fb6d0bb7d426)`
- 日期：2026-04-10
- 明确新增内容：引入了“Setup Wizard + doctor command — closes #2030”相关功能改进。
- 影响范围：主要涉及 脚本工具、后端、其他模块。
- 改动规模：+2809 / -68 行。
- 关键文件：Makefile；README.md；backend/docs/CONFIGURATION.md；backend/packages/harness/deerflow/agents/lead_agent/agent.py；backend/packages/harness/deerflow/community/firecrawl/tools.py；backend/tests/conftest.py；backend/tests/test_doctor.py；backend/tests/test_firecrawl_tools.py。

#### 38. docs(api): document recursion_limit for LangGraph API runs (#1929)

- 提交：`[b107444](https://github.com/bytedance/deer-flow/commit/b107444878b077517c4fef8df915446a8d21d176)`
- 日期：2026-04-10
- 明确新增内容：新增了“document recursion_limit for LangGraph API runs”相关文档说明，补齐使用/配置指引。
- 影响范围：主要涉及 后端。
- 改动规模：+25 / -1 行。
- 关键文件：backend/docs/API.md。

#### 39. feat(skills): add systematic-literature-review skill for multi-paper SLR workflows (#2032)

- 提交：`[16aa51c](https://github.com/bytedance/deer-flow/commit/16aa51c9b33f14163582ddfae468b97c6c1c2c4a)`
- 日期：2026-04-10
- 明确新增内容：新增了“systematic-literature-review skill for multi-paper SLR workflows”功能。
- 影响范围：主要涉及 技能体系。
- 改动规模：+949 / -0 行。
- 关键文件：skills/public/systematic-literature-review/SKILL.md；skills/public/systematic-literature-review/scripts/arxiv_search.py；skills/public/systematic-literature-review/templates/apa.md；skills/public/systematic-literature-review/templates/bibtex.md；skills/public/systematic-literature-review/templates/ieee.md。

#### 40. feat(models): add langchain-ollama for native Ollama thinking support (#2062)

- 提交：`[133ffe7](https://github.com/bytedance/deer-flow/commit/133ffe7174182814e16d20a69bc98b5d47d744b3)`
- 日期：2026-04-10
- 明确新增内容：新增了对“add langchain-ollama for native Ollama thinking support”的支持能力。
- 影响范围：主要涉及 后端、配置。
- 改动规模：+36 / -0 行。
- 关键文件：backend/packages/harness/pyproject.toml；config.example.yaml。

#### 41. feat(smoke-test): add smoke test skill (#1947)

- 提交：`[6572fa5](https://github.com/bytedance/deer-flow/commit/6572fa5b75e96a15aa0a0bfc601346b8d4cf22d4)`
- 日期：2026-04-09
- 明确新增内容：新增了“add smoke test skill”相关测试覆盖与验证用例。
- 影响范围：主要涉及 其他模块。
- 改动规模：+2155 / -0 行。
- 关键文件：.agent/skills/smoke-test/SKILL.md；.agent/skills/smoke-test/references/SOP.md；.agent/skills/smoke-test/references/troubleshooting.md；.agent/skills/smoke-test/scripts/check_docker.sh；.agent/skills/smoke-test/scripts/check_local_env.sh；.agent/skills/smoke-test/scripts/deploy_docker.sh；.agent/skills/smoke-test/scripts/deploy_local.sh；.agent/skills/smoke-test/scripts/frontend_check.sh。

#### 42. feat(config): add when_thinking_disabled support for model configs (#1970)

- 提交：`[194bab4](https://github.com/bytedance/deer-flow/commit/194bab469143f5dc370513144800705d3c4467ab)`
- 日期：2026-04-09
- 明确新增内容：新增了对“add when_thinking_disabled support for model configs”的支持能力。
- 影响范围：主要涉及 后端、配置。
- 改动规模：+168 / -5 行。
- 关键文件：backend/packages/harness/deerflow/config/model_config.py；backend/packages/harness/deerflow/models/factory.py；backend/tests/test_model_factory.py；config.example.yaml。

#### 43. feat: implement full checkpoint rollback on user cancellation (#1867)

- 提交：`[35f141f](https://github.com/bytedance/deer-flow/commit/35f141fc48ff0ae70ebfb97d8c8ccd9565187b52)`
- 日期：2026-04-09
- 明确新增内容：实现了“implement full checkpoint rollback on user cancellation”这项新能力。
- 影响范围：主要涉及 后端。
- 改动规模：+356 / -19 行。
- 关键文件：backend/packages/harness/deerflow/runtime/runs/worker.py；backend/tests/test_run_worker_rollback.py。

#### 44. feat(client): add thread query methods `list_threads` and `get_thread` (#1609)

- 提交：`[31a3c9a](https://github.com/bytedance/deer-flow/commit/31a3c9a3dec4e855b9054a3db02d6edf6fd11d7e)`
- 日期：2026-04-09
- 明确新增内容：新增了“thread query methods `list_threads` and `get_thread`”功能。
- 影响范围：主要涉及 后端。
- 改动规模：+243 / -0 行。
- 关键文件：backend/packages/harness/deerflow/client.py；backend/tests/test_client.py。

#### 45. feat(community): add Exa search as community tool provider (#1357)

- 提交：`[5350b2f](https://github.com/bytedance/deer-flow/commit/5350b2fb24b3bdb98729cc20b4544658fb8dfaa9)`
- 日期：2026-04-08
- 明确新增内容：新增了“Exa search as community tool provider”功能。
- 影响范围：主要涉及 后端、配置。
- 改动规模：+377 / -0 行。
- 关键文件：backend/packages/harness/deerflow/community/exa/tools.py；backend/packages/harness/pyproject.toml；backend/tests/test_exa_tools.py；backend/uv.lock；config.example.yaml。

#### 46. docs: clarify deployment sizing guidance (#1963)

- 提交：`[722a9c4](https://github.com/bytedance/deer-flow/commit/722a9c4753c229c11763dc81a722d6f174a638d1)`
- 日期：2026-04-08
- 明确新增内容：新增了“clarify deployment sizing guidance”相关文档说明，补齐使用/配置指引。
- 影响范围：主要涉及 文档、其他模块。
- 改动规模：+42 / -0 行。
- 关键文件：CONTRIBUTING.md；README.md；README_zh.md。

#### 47. feat(sandbox): strengthen bash command auditing with compound splitting and expanded patterns (#1881)

- 提交：`[3b3e8e1](https://github.com/bytedance/deer-flow/commit/3b3e8e1b0ba1831008e8cefdf115215c8b10731c)`
- 日期：2026-04-07
- 明确新增内容：引入了“strengthen bash command auditing with compound splitting and expanded patterns”相关功能改进。
- 影响范围：主要涉及 后端。
- 改动规模：+327 / -9 行。
- 关键文件：backend/packages/harness/deerflow/agents/middlewares/sandbox_audit_middleware.py；backend/tests/test_sandbox_audit_middleware.py。

#### 48. feat: add BytePlus logo (#1948)

- 提交：`[f467e61](https://github.com/bytedance/deer-flow/commit/f467e613b6173253bc2d217f15bb434c8113d52f)`
- 日期：2026-04-07
- 明确新增内容：新增了“BytePlus logo”功能。
- 影响范围：主要涉及 前端。
- 改动规模：+59 / -0 行。
- 关键文件：frontend/src/components/landing/hero.tsx。

#### 49. Feature/feishu receive file (#1608)

- 提交：`[88e5352](https://github.com/bytedance/deer-flow/commit/88e535269ec1b4ec06ee3ad7f6143ddea27305ab)`
- 日期：2026-04-06
- 明确新增内容：引入了“Feature/feishu receive file”相关功能改进。
- 影响范围：主要涉及 后端。
- 改动规模：+331 / -5 行。
- 关键文件：backend/app/channels/base.py；backend/app/channels/feishu.py；backend/app/channels/manager.py；backend/app/channels/service.py；backend/tests/test_channel_file_attachments.py；backend/tests/test_channels.py；backend/tests/test_feishu_parser.py。

#### 50. Implement skill self-evolution and skill_manage flow (#1874)

- 提交：`[888f7bf](https://github.com/bytedance/deer-flow/commit/888f7bfb9d1d2eb4570d51aec4dfe62ddac15e05)`
- 日期：2026-04-06
- 明确新增内容：实现了“Implement skill self-evolution and skill_manage flow”这项新能力。
- 影响范围：主要涉及 后端、文档、其他模块。
- 改动规模：+1163 / -58 行。
- 关键文件：.gitignore；backend/app/gateway/routers/skills.py；backend/packages/harness/deerflow/agents/lead_agent/prompt.py；backend/packages/harness/deerflow/config/**init**.py；backend/packages/harness/deerflow/config/app_config.py；backend/packages/harness/deerflow/config/skill_evolution_config.py；backend/packages/harness/deerflow/skills/loader.py；backend/packages/harness/deerflow/skills/manager.py。

#### 51. feat(models): add vLLM provider support (#1860)

- 提交：`[dd30e60](https://github.com/bytedance/deer-flow/commit/dd30e609f7b50fa1398c6fa3654b9c0be3fb7c7c)`
- 日期：2026-04-06
- 明确新增内容：新增了对“add vLLM provider support”的支持能力。
- 影响范围：主要涉及 后端、其他模块、文档。
- 改动规模：+534 / -5 行。
- 关键文件：.env.example；README.md；backend/CLAUDE.md；backend/packages/harness/deerflow/models/factory.py；backend/packages/harness/deerflow/models/vllm_provider.py；backend/tests/test_model_factory.py；backend/tests/test_vllm_provider.py；config.example.yaml。

#### 52. feat: unified serve.sh with gateway mode support (#1847)

- 提交：`[ca2fb95](https://github.com/bytedance/deer-flow/commit/ca2fb95ee6bae08073ad058ecaecbf180c32a50c)`
- 日期：2026-04-05
- 明确新增内容：新增了对“unified serve.sh with gateway mode support”的支持能力。
- 影响范围：主要涉及 容器部署、脚本工具、其他模块。
- 改动规模：+551 / -376 行。
- 关键文件：Makefile；README.md；backend/CLAUDE.md；docker/docker-compose-dev.yaml；docker/docker-compose.yaml；docker/nginx/nginx.conf；docker/provisioner/Dockerfile；scripts/deploy.sh。

#### 53. feat(skills): add academic-paper-review, code-documentation, and newsletter-generation skills (#1861)

- 提交：`[8bb14fa](https://github.com/bytedance/deer-flow/commit/8bb14fa1a7bf7e6ee0631db4db9168962edbc31f)`
- 日期：2026-04-05
- 明确新增内容：新增了“academic-paper-review, code-documentation, and newsletter-generation skills”功能。
- 影响范围：主要涉及 技能体系。
- 改动规模：+1047 / -0 行。
- 关键文件：skills/public/academic-paper-review/SKILL.md；skills/public/code-documentation/SKILL.md；skills/public/newsletter-generation/SKILL.md。

#### 54. feat: support wecom channel (#1390)

- 提交：`[1980980](https://github.com/bytedance/deer-flow/commit/19809800f14f1869dd2b01f521d9312b7cde940d)`
- 日期：2026-04-04
- 明确新增内容：新增了对“wecom channel”的支持能力。
- 影响范围：主要涉及 后端、文档、其他模块。
- 改动规模：+771 / -3 行。
- 关键文件：.env.example；README.md；README_zh.md；backend/app/channels/manager.py；backend/app/channels/service.py；backend/app/channels/wecom.py；backend/pyproject.toml；backend/tests/test_channels.py。

#### 55. feat(uploads): guide agent using agentic search for uploaded documents (#1816)

- 提交：`[bbd0866](https://github.com/bytedance/deer-flow/commit/bbd0866374332c01889b5c597674b9a3efc50364)`
- 日期：2026-04-04
- 明确新增内容：新增了“guide agent using agentic search for uploaded documents”相关文档说明，补齐使用/配置指引。
- 影响范围：主要涉及 后端。
- 改动规模：+7 / -1 行。
- 关键文件：backend/packages/harness/deerflow/agents/middlewares/uploads_middleware.py。

#### 56. feat(uploads): add pymupdf4llm PDF converter with auto-fallback and async offload (#1727)

- 提交：`[ddfc988](https://github.com/bytedance/deer-flow/commit/ddfc988bef96456a87103d2cb0bef785d552e281)`
- 日期：2026-04-03
- 明确新增内容：新增了“pymupdf4llm PDF converter with auto-fallback and async offload”功能。
- 影响范围：主要涉及 后端、配置。
- 改动规模：+461 / -14 行。
- 关键文件：backend/packages/harness/deerflow/config/app_config.py；backend/packages/harness/deerflow/utils/file_conversion.py；backend/packages/harness/pyproject.toml；backend/tests/test_file_conversion.py；config.example.yaml。

#### 57. feat(uploads): inject document outline into agent context for converted files (#1738)

- 提交：`[5ff230e](https://github.com/bytedance/deer-flow/commit/5ff230eafd29fd6dad8dd3ece58b3f3aba478ff9)`
- 日期：2026-04-03
- 明确新增内容：引入了“inject document outline into agent context for converted files”相关功能改进。
- 影响范围：主要涉及 后端。
- 改动规模：+354 / -10 行。
- 关键文件：backend/packages/harness/deerflow/agents/middlewares/uploads_middleware.py；backend/packages/harness/deerflow/utils/file_conversion.py；backend/tests/test_file_conversion.py；backend/tests/test_uploads_middleware_core_logic.py。

#### 58. Add explicit save action for agent creation (#1798)

- 提交：`[3d4f9a8](https://github.com/bytedance/deer-flow/commit/3d4f9a88feaff07b14fcaba69c3c727390eee993)`
- 日期：2026-04-03
- 明确新增内容：新增了“explicit save action for agent creation”功能。
- 影响范围：主要涉及 前端。
- 改动规模：+219 / -52 行。
- 关键文件：frontend/src/app/workspace/agents/new/page.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts；frontend/src/core/i18n/locales/zh-CN.ts；frontend/src/core/messages/utils.ts；frontend/src/core/threads/hooks.ts。

#### 59. feat(sandbox): add read-only support for local sandbox path mappings (#1808)

- 提交：`[1694c61](https://github.com/bytedance/deer-flow/commit/1694c616ef3e48be10862f5ce66ece1bd224dfaf)`
- 日期：2026-04-03
- 明确新增内容：新增了对“add read-only support for local sandbox path mappings”的支持能力。
- 影响范围：主要涉及 后端、配置。
- 改动规模：+768 / -33 行。
- 关键文件：backend/packages/harness/deerflow/sandbox/local/local_sandbox.py；backend/packages/harness/deerflow/sandbox/local/local_sandbox_provider.py；backend/packages/harness/deerflow/sandbox/tools.py；backend/tests/test_local_sandbox_provider_mounts.py；backend/tests/test_sandbox_tools_security.py；config.example.yaml。

#### 60. feat(sandbox): add built-in grep and glob tools (#1784)

- 提交：`[c6cdf20](https://github.com/bytedance/deer-flow/commit/c6cdf200ceae043d9c14982d1da1549fc3fb806b)`
- 日期：2026-04-03
- 明确新增内容：新增了“built-in grep and glob tools”功能。
- 影响范围：主要涉及 后端、其他模块、配置。
- 改动规模：+1388 / -69 行。
- 关键文件：.gitignore；backend/docs/rfc-grep-glob-tools.md；backend/packages/harness/deerflow/community/aio_sandbox/aio_sandbox.py；backend/packages/harness/deerflow/sandbox/local/list_dir.py；backend/packages/harness/deerflow/sandbox/local/local_sandbox.py；backend/packages/harness/deerflow/sandbox/sandbox.py；backend/packages/harness/deerflow/sandbox/search.py；backend/packages/harness/deerflow/sandbox/tools.py。

#### 61. feat(client): add `available_skills` parameter to DeerFlowClient (#1779)

- 提交：`[76fad8b](https://github.com/bytedance/deer-flow/commit/76fad8b08de23c41ab1799e54b26bc59273d5ab9)`
- 日期：2026-04-03
- 明确新增内容：新增了“`available_skills` parameter to DeerFlowClient”功能。
- 影响范围：主要涉及 后端。
- 改动规模：+17 / -2 行。
- 关键文件：backend/packages/harness/deerflow/client.py；backend/tests/test_client.py。

#### 62. Improve Python reliability in channel retries and thread typing (#1776)

- 提交：`[6de9c7b](https://github.com/bytedance/deer-flow/commit/6de9c7b43f5802ce7b84f87719a9402cd495f41b)`
- 日期：2026-04-03
- 明确新增内容：增强了“Improve Python reliability in channel retries and thread typing”相关能力与交互体验。
- 影响范围：主要涉及 后端。
- 改动规模：+60 / -7 行。
- 关键文件：backend/app/channels/feishu.py；backend/app/channels/slack.py；backend/app/channels/telegram.py；backend/app/gateway/routers/threads.py；backend/tests/test_channels.py。

#### 63. Add documents site (#1767)

- 提交：`[c1366cf](https://github.com/bytedance/deer-flow/commit/c1366cf559b7edd2831a727effda5d701a0b0440)`
- 日期：2026-04-03
- 明确新增内容：新增了“documents site”功能。
- 影响范围：主要涉及 前端、其他模块、容器部署。
- 改动规模：+2249 / -33 行。
- 关键文件：.gitignore；docker/nginx/nginx.local.conf；frontend/next.config.js；frontend/package.json；frontend/pnpm-lock.yaml；frontend/src/app/[lang]/docs/[[...mdxPath]]/page.tsx；frontend/src/app/[lang]/docs/layout.tsx；frontend/src/components/landing/header.tsx。

#### 64. docs: sync README table of contents with current sections (#1774)

- 提交：`[ef711a4](https://github.com/bytedance/deer-flow/commit/ef711a48b347e29ca40843d9c4614f34524b0537)`
- 日期：2026-04-02
- 明确新增内容：新增了“sync README table of contents with current sections”相关文档说明，补齐使用/配置指引。
- 影响范围：主要涉及 文档。
- 改动规模：+3 / -0 行。
- 关键文件：README.md。

#### 65. feat/per agent skill filter (#1650)

- 提交：`[f8fb8d6](https://github.com/bytedance/deer-flow/commit/f8fb8d6fb129a38049e0e86dd099093a45498a37)`
- 日期：2026-04-02
- 明确新增内容：引入了“feat/per agent skill filter”相关功能改进。
- 影响范围：主要涉及 后端、配置。
- 改动规模：+142 / -1 行。
- 关键文件：backend/docs/CONFIGURATION.md；backend/packages/harness/deerflow/agents/lead_agent/agent.py；backend/packages/harness/deerflow/agents/lead_agent/prompt.py；backend/packages/harness/deerflow/config/agents_config.py；backend/tests/test_custom_agent.py；backend/tests/test_lead_agent_skills.py；config.example.yaml。

#### 66. feat(tracing): add optional Langfuse support (#1717)

- 提交：`[2d1f90d](https://github.com/bytedance/deer-flow/commit/2d1f90d5dc0b0c992cb421428d33b431be5a5a17)`
- 日期：2026-04-02
- 明确新增内容：新增了对“add optional Langfuse support”的支持能力。
- 影响范围：主要涉及 后端、文档。
- 改动规模：+667 / -67 行。
- 关键文件：README.md；backend/README.md；backend/packages/harness/deerflow/config/**init**.py；backend/packages/harness/deerflow/config/tracing_config.py；backend/packages/harness/deerflow/models/factory.py；backend/packages/harness/deerflow/tracing/**init**.py；backend/packages/harness/deerflow/tracing/factory.py；backend/packages/harness/pyproject.toml。

#### 67. feat(sandbox): truncate oversized bash and read_file tool outputs (#1677)

- 提交：`[df5339b](https://github.com/bytedance/deer-flow/commit/df5339b5d076fc71dd4e54d3f69c396fc2d63944)`
- 日期：2026-04-02
- 明确新增内容：引入了“truncate oversized bash and read_file tool outputs”相关功能改进。
- 影响范围：主要涉及 后端、配置。
- 改动规模：+257 / -4 行。
- 关键文件：backend/packages/harness/deerflow/config/sandbox_config.py；backend/packages/harness/deerflow/sandbox/tools.py；backend/tests/test_tool_output_truncation.py；config.example.yaml。

#### 68. feat(memory): structured reflection + correction detection in MemoryMiddleware (#1620) (#1668)

- 提交：`[0cdecf7](https://github.com/bytedance/deer-flow/commit/0cdecf7b30bf5d369f4b6b24ab6fba4093955ee2)`
- 日期：2026-04-01
- 明确新增内容：引入了“structured reflection + correction detection in MemoryMiddleware (#1620)”相关功能改进。
- 影响范围：主要涉及 后端。
- 改动规模：+436 / -21 行。
- 关键文件：backend/app/gateway/routers/memory.py；backend/packages/harness/deerflow/agents/memory/prompt.py；backend/packages/harness/deerflow/agents/memory/queue.py；backend/packages/harness/deerflow/agents/memory/updater.py；backend/packages/harness/deerflow/agents/middlewares/memory_middleware.py；backend/tests/test_memory_prompt_injection.py；backend/tests/test_memory_queue.py；backend/tests/test_memory_router.py。

## 2026-05

- 提交数：4 条

#### 1. feat(agent): add custom-agent self-updates with user isolation (#2713)

- 提交：`[59c4a3f](https://github.com/bytedance/deer-flow/commit/59c4a3f0a48904d1eada5b1934ca32a9c7d6dea7)`
- 日期：2026-05-05
- 明确新增内容：新增了“custom-agent self-updates with user isolation”功能。
- 影响范围：主要涉及 后端、前端。
- 改动规模：+956 / -61 行。
- 关键文件：backend/CLAUDE.md；backend/app/gateway/routers/agents.py；backend/packages/harness/deerflow/agents/lead_agent/agent.py；backend/packages/harness/deerflow/agents/lead_agent/prompt.py；backend/packages/harness/deerflow/config/agents_config.py；backend/packages/harness/deerflow/config/paths.py；backend/packages/harness/deerflow/tools/builtins/**init**.py；backend/packages/harness/deerflow/tools/builtins/setup_agent_tool.py。

#### 2. feat(github): Added container push workflow (#2709)

- 提交：`[b10eb7b](https://github.com/bytedance/deer-flow/commit/b10eb7bafcf0e95023fc1c8b2a563bf6c8e03860)`
- 日期：2026-05-04
- 明确新增内容：新增了“container push workflow”功能。
- 影响范围：主要涉及 CI/CD。
- 改动规模：+101 / -0 行。
- 关键文件：.github/workflows/container.yaml。

#### 3. feat: refine token usage display modes (#2329)

- 提交：`[d02f762](https://github.com/bytedance/deer-flow/commit/d02f762ab031da715273fc742f2e00d114ae5325)`
- 日期：2026-05-04
- 明确新增内容：引入了“refine token usage display modes”相关功能改进。
- 影响范围：主要涉及 前端、后端。
- 改动规模：+2346 / -222 行。
- 关键文件：backend/packages/harness/deerflow/agents/middlewares/token_usage_middleware.py；backend/packages/harness/deerflow/client.py；backend/tests/test_client.py；backend/tests/test_client_message_serialization.py；backend/tests/test_token_usage_middleware.py；frontend/src/app/workspace/agents/[agent_name]/chats/[thread_id]/page.tsx；frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/workspace/messages/message-group.tsx。

#### 4. feat(community): add Serper web search provider (#2630)

- 提交：`[44ab21f](https://github.com/bytedance/deer-flow/commit/44ab21fc44981eb2de9e4c0bccd2039c5195715c)`
- 日期：2026-05-02
- 明确新增内容：新增了“Serper web search provider”功能。
- 影响范围：主要涉及 后端、其他模块、配置。
- 改动规模：+419 / -0 行。
- 关键文件：.env.example；backend/packages/harness/deerflow/community/serper/**init**.py；backend/packages/harness/deerflow/community/serper/tools.py；backend/tests/test_serper_tools.py；config.example.yaml。

