# Deer-Flow 近一年按月 Commit 中文逐条分析（功能 & 修复）

> 数据源：`origin/main` 最近12个月。

> 说明：仅纳入“新功能/增强”与“Bug 修复”相关提交；每条包含做了什么、影响模块、改动规模、核心文件。

GitHub 提交页：[https://github.com/bytedance/deer-flow/commits/main/](https://github.com/bytedance/deer-flow/commits/main/)

## 2025-06

- 新功能/增强：14 条
- Bug 修复：18 条

### 新功能 / 增强

#### 1. Add support for self-signed certs from model providers (#276)

- 提交：`[b7373fb](https://github.com/bytedance/deer-flow/commit/b7373fbe701bea278612ab06a1670adf8d6fb553)`
- 日期：2025-06-25
- 做了什么：新增或增强功能，主题是“Add support for self-signed certs from model providers (#276)”。
- 影响范围：主要涉及 其他模块、文档。
- 改动规模：+31 / -1 行。
- 关键文件：conf.yaml.example；docs/configuration_guide.md；src/llms/llm.py。

#### 2. improve: add abort btn to abort the mcp add request. (#284)

- 提交：`[9c2d472](https://github.com/bytedance/deer-flow/commit/9c2d4724e3ccd80b8e2add1d521b9d9ca1f1eb6a)`
- 日期：2025-06-26
- 做了什么：新增或增强功能，主题是“improve: add abort btn to abort the mcp add request. (#284)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+25 / -4 行。
- 关键文件：web/src/app/settings/dialogs/add-mcp-server-dialog.tsx；web/src/core/api/mcp.ts。

#### 3. test: add unit tests of the app (#305)

- 提交：`[dcdd728](https://github.com/bytedance/deer-flow/commit/dcdd7288ed0c861551c3c1669c1ebcff8675a849)`
- 日期：2025-06-18
- 做了什么：补充/增强测试体系，主题是“add unit tests of the app (#305)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+1113 / -16 行。
- 关键文件：src/server/app.py；src/tools/tts.py；tests/integration/test_tts.py；tests/unit/server/test_app.py；tests/unit/server/test_chat_request.py；tests/unit/server/test_mcp_request.py；tests/unit/server/test_mcp_utils.py。

#### 4. test: add unit tests for graph  (#296)

- 提交：`[c0b04aa](https://github.com/bytedance/deer-flow/commit/c0b04aaba288f6ca6f78c835244084e9319975e2)`
- 日期：2025-06-18
- 做了什么：补充/增强测试体系，主题是“add unit tests for graph  (#296)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+1436 / -2 行。
- 关键文件：src/graph/nodes.py；tests/integration/test_nodes.py；tests/unit/graph/test_builder.py；uv.lock。

#### 5. test: add test of json_utils (#309)

- 提交：`[4048ca6](https://github.com/bytedance/deer-flow/commit/4048ca67dd4de5b0d0e113979dd42c1db258b6c3)`
- 日期：2025-06-18
- 做了什么：补充/增强测试体系，主题是“add test of json_utils (#309)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+110 / -0 行。
- 关键文件：tests/unit/utils/test_json_utils.py。

#### 6. feat: add deep think feature (#311)

- 提交：`[19fa1e9](https://github.com/bytedance/deer-flow/commit/19fa1e97c339e2d70d714706c4e75dc89f241311)`
- 日期：2025-06-14
- 做了什么：新增或增强功能，主题是“add deep think feature (#311)”。
- 影响范围：主要涉及 其他模块、文档。
- 改动规模：+2315 / -1125 行。
- 关键文件：.gitignore；README.md；README_de.md；README_es.md；README_ja.md；README_pt.md；README_ru.md；README_zh.md。

#### 7. feat: append try catch (#280)

- 提交：`[7d38e5f](https://github.com/bytedance/deer-flow/commit/7d38e5f900a31cc47384f573893b4f0b57c1ce8b)`
- 日期：2025-06-12
- 做了什么：新增或增强功能，主题是“append try catch (#280)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+19 / -14 行。
- 关键文件：web/src/core/api/chat.ts。

#### 8. test: add more unit tests of tools (#315)

- 提交：`[4c2fe2e](https://github.com/bytedance/deer-flow/commit/4c2fe2e7f54f6823288e624ef5f739fbc3d71f7c)`
- 日期：2025-06-12
- 做了什么：补充/增强测试体系，主题是“add more unit tests of tools (#315)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+1057 / -35 行。
- 关键文件：pyproject.toml；src/rag/**init**.py；src/tools/retriever.py；src/tools/search.py；src/tools/tavily_search/tavily_search_api_wrapper.py；src/tools/tavily_search/tavily_search_results_with_images.py；tests/integration/test_tts.py；tests/unit/tools/test_crawl.py。

#### 9. docs: add VolcEngine introduction. (#314)

- 提交：`[bb7dc6e](https://github.com/bytedance/deer-flow/commit/bb7dc6e98ce82311e48c02b514aeac35484e7816)`
- 日期：2025-06-12
- 做了什么：补充文档能力，主题是“add VolcEngine introduction. (#314)”。
- 影响范围：主要涉及 文档。
- 改动规模：+7 / -0 行。
- 关键文件：README_zh.md。

#### 10. test: add unit tests of llms (#299)

- 提交：`[2554e4b](https://github.com/bytedance/deer-flow/commit/2554e4ba639879e378f0ba94d37661eaad040d4e)`
- 日期：2025-06-11
- 做了什么：补充/增强测试体系，主题是“add unit tests of llms (#299)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+70 / -6 行。
- 关键文件：src/llms/llm.py；tests/unit/llms/test_llm.py。

#### 11. feat: added report download button (#78)

- 提交：`[eeff1eb](https://github.com/bytedance/deer-flow/commit/eeff1ebf805822e71dc59079ebd49cc7b5917923)`
- 日期：2025-06-11
- 做了什么：新增或增强功能，主题是“added report download button (#78)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+38 / -1 行。
- 关键文件：web/src/app/chat/components/research-block.tsx。

#### 12. feat: implement enhance prompt (#294)

- 提交：`[1cd6aa0](https://github.com/bytedance/deer-flow/commit/1cd6aa0ece7a55c9363ff088ac8acbb3a817dd70)`
- 日期：2025-06-08
- 做了什么：新增或增强功能，主题是“implement enhance prompt (#294)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+1100 / -4 行。
- 关键文件：src/config/agents.py；src/prompt_enhancer/**init**.py；src/prompt_enhancer/graph/builder.py；src/prompt_enhancer/graph/enhancer_node.py；src/prompt_enhancer/graph/state.py；src/prompts/prompt_enhancer/prompt_enhancer.md；src/server/app.py；src/server/chat_request.py。

#### 13. test: add unit tests of crawler (#292)

- 提交：`[c6ed423](https://github.com/bytedance/deer-flow/commit/c6ed423021cf3e27b1c5025f65bdd9becb7d9df6)`
- 日期：2025-06-07
- 做了什么：补充/增强测试体系，主题是“add unit tests of crawler (#292)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+149 / -14 行。
- 关键文件：src/crawler/**init**.py；src/crawler/crawler.py；tests/unit/crawler/test_article.py；tests/unit/crawler/test_crawler_class.py。

#### 14. feat: support to adjust writing style (#290)

- 提交：`[0e22c37](https://github.com/bytedance/deer-flow/commit/0e22c373af42faa5c3121fac2f4378b7f3eee014)`
- 日期：2025-06-07
- 做了什么：新增或增强功能，主题是“support to adjust writing style (#290)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+411 / -7 行。
- 关键文件：src/config/configuration.py；src/config/report_style.py；src/graph/nodes.py；src/prompts/reporter.md；src/server/app.py；src/server/chat_request.py；tests/integration/test_template.py；web/src/app/chat/components/input-box.tsx。

### Bug 修复

#### 1. fix: next server fetch error (#374)

- 提交：`[52dfdd8](https://github.com/bytedance/deer-flow/commit/52dfdd83aea8f0ba554d535f6a90aa3313e05be1)`
- 日期：2025-06-27
- 做了什么：修复缺陷或回归问题，主题是“next server fetch error (#374)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+37 / -45 行。
- 关键文件：web/src/app/chat/components/input-box.tsx；web/src/app/layout.tsx；web/src/components/deer-flow/message-input.tsx；web/src/core/api/config.ts；web/src/core/api/hooks.ts。

#### 2. fix: the lint error of llm.py (#369)

- 提交：`[f27c96e](https://github.com/bytedance/deer-flow/commit/f27c96e692ac9a8ebf6379a5d1ecb6f32fbcc3db)`
- 日期：2025-06-26
- 做了什么：修复缺陷或回归问题，主题是“the lint error of llm.py (#369)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+1 / -2 行。
- 关键文件：src/llms/llm.py。

#### 3. fix: replace json before js fence (#344)

- 提交：`[aa06cd6](https://github.com/bytedance/deer-flow/commit/aa06cd6fb64c63d47d8c7033e13689f0491cbf33)`
- 日期：2025-06-26
- 做了什么：修复缺陷或回归问题，主题是“replace json before js fence (#344)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+1 / -1 行。
- 关键文件：web/src/core/utils/json.ts。

#### 4. fix: settings tab display name (#250)

- 提交：`[82e1b65](https://github.com/bytedance/deer-flow/commit/82e1b65792c5a663b61c2b94a417824a893ea8fb)`
- 日期：2025-06-19
- 做了什么：修复缺陷或回归问题，主题是“settings tab display name (#250)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+1 / -0 行。
- 关键文件：web/src/app/settings/tabs/mcp-tab.tsx。

#### 5. Fix: the test errors of test_nodes (#345)

- 提交：`[89f3d73](https://github.com/bytedance/deer-flow/commit/89f3d731c94e7e8618573c5328bf65e1885c9874)`
- 日期：2025-06-18
- 做了什么：修复缺陷或回归问题，主题是“the test errors of test_nodes (#345)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+3 / -2 行。
- 关键文件：tests/integration/test_nodes.py。

#### 6. fix: update several links related to volcengine in Readme (#333)

- 提交：`[30a189c](https://github.com/bytedance/deer-flow/commit/30a189cf26836f87574b3efdcc9b3265a91946ea)`
- 日期：2025-06-17
- 做了什么：修复缺陷或回归问题，主题是“update several links related to volcengine in Readme (#333)”。
- 影响范围：主要涉及 文档。
- 改动规模：+3 / -9 行。
- 关键文件：README.md；README_zh.md。

#### 7. fix: add line breaks to mcp edit dialog (#313)

- 提交：`[8823ffd](https://github.com/bytedance/deer-flow/commit/8823ffdb6ab33572708ff5924c889fda96428e43)`
- 日期：2025-06-17
- 做了什么：修复缺陷或回归问题，主题是“add line breaks to mcp edit dialog (#313)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+1 / -1 行。
- 关键文件：web/src/app/settings/dialogs/add-mcp-server-dialog.tsx。

#### 8. fix(web): priority displayName for settings name error (#336)

- 提交：`[4fe4315](https://github.com/bytedance/deer-flow/commit/4fe43153b147069cc47c9c99299c879002f99974)`
- 日期：2025-06-17
- 做了什么：修复缺陷或回归问题，主题是“priority displayName for settings name error (#336)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+4 / -2 行。
- 关键文件：web/src/app/settings/tabs/about-tab.tsx；web/src/app/settings/tabs/general-tab.tsx；web/src/app/settings/tabs/index.tsx；web/src/app/settings/tabs/mcp-tab.tsx。

#### 9. Revert "fix: solves the malformed json output and pydantic validation error p…" (#325)

- 提交：`[4fb053b](https://github.com/bytedance/deer-flow/commit/4fb053b6d22f3960dc79141f05dc3220f6d2afd9)`
- 日期：2025-06-14
- 做了什么：修复缺陷或回归问题，主题是“Revert "fix: solves the malformed json output and pydantic validation error p…" (#325)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+1 / -2 行。
- 关键文件：src/graph/nodes.py。

#### 10. fix: solves the malformed json output and pydantic validation error produced by the 'planner' node by forcing the llm response to strictly comply with the pydantic 'Plan' model (#322)

- 提交：`[a7315b4](https://github.com/bytedance/deer-flow/commit/a7315b46df1ecf7a59b1b8c80dd7cf2adc8552ad)`
- 日期：2025-06-13
- 做了什么：修复缺陷或回归问题，主题是“solves the malformed json output and pydantic validation error produced by the 'planner' node by forcing the llm response to strictly comply with the pydantic 'Plan' model (#322)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+2 / -1 行。
- 关键文件：src/graph/nodes.py。

#### 11. fix: mcp config styles (#320)

- 提交：`[03e6a1a](https://github.com/bytedance/deer-flow/commit/03e6a1a6e799ad20a25b8dc741541d5015ebcfb3)`
- 日期：2025-06-13
- 做了什么：修复缺陷或回归问题，主题是“mcp config styles (#320)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+3 / -1 行。
- 关键文件：web/src/app/settings/dialogs/add-mcp-server-dialog.tsx；web/src/components/deer-flow/link.tsx。

#### 12. fix: input text not clear when click submit button (#303)

- 提交：`[397ac57](https://github.com/bytedance/deer-flow/commit/397ac572358fce6ec65d343a855b1bd34350e435)`
- 日期：2025-06-11
- 做了什么：修复缺陷或回归问题，主题是“input text not clear when click submit button (#303)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+1 / -0 行。
- 关键文件：web/src/components/deer-flow/message-input.tsx。

#### 13. fix: enable proxy support in aiohttp by adding trust_env=True (#289)

- 提交：`[cda3870](https://github.com/bytedance/deer-flow/commit/cda3870adddfdc77a379bf553dc33222996a7cc2)`
- 日期：2025-06-07
- 做了什么：修复缺陷或回归问题，主题是“enable proxy support in aiohttp by adding trust_env=True (#289)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+1 / -1 行。
- 关键文件：src/tools/tavily_search/tavily_search_api_wrapper.py。

#### 14. fix: web start with dotenv (#282)

- 提交：`[73ac8ae](https://github.com/bytedance/deer-flow/commit/73ac8ae45a2f0a5caf35b45d601d080af6abf91f)`
- 日期：2025-06-05
- 做了什么：修复缺陷或回归问题，主题是“web start with dotenv (#282)”。
- 影响范围：主要涉及 其他模块、配置。
- 改动规模：+29 / -2 行。
- 关键文件：web/package.json；web/pnpm-lock.yaml。

#### 15. fix: correct placeholder for API key in configuration guide (#278)

- 提交：`[91648c4](https://github.com/bytedance/deer-flow/commit/91648c42102fb2dcddebf0fabbdd2d76312b03a6)`
- 日期：2025-06-05
- 做了什么：修复缺陷或回归问题，主题是“correct placeholder for API key in configuration guide (#278)”。
- 影响范围：主要涉及 文档。
- 改动规模：+1 / -1 行。
- 关键文件：docs/configuration_guide.md。

#### 16. fix: do not return the server side exception to client (#277)

- 提交：`[9525780](https://github.com/bytedance/deer-flow/commit/95257800d204eae24379c976760f5cc6dc24dbc8)`
- 日期：2025-06-05
- 做了什么：修复缺陷或回归问题，主题是“do not return the server side exception to client (#277)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+7 / -5 行。
- 关键文件：src/server/app.py。

#### 17. fix:added sanitizing check on the log message (#272)

- 提交：`[45568ca](https://github.com/bytedance/deer-flow/commit/45568ca95b33717d85a7a967a462430a094720aa)`
- 日期：2025-06-03
- 做了什么：修复缺陷或回归问题，主题是“added sanitizing check on the log message (#272)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+4 / -2 行。
- 关键文件：src/server/app.py；src/tools/tts.py。

#### 18. fix: added permissions setting in the workflow (#273)

- 提交：`[db3e746](https://github.com/bytedance/deer-flow/commit/db3e74629f52003ceb0cc029c01db5a400abc491)`
- 日期：2025-06-03
- 做了什么：修复缺陷或回归问题，主题是“added permissions setting in the workflow (#273)”。
- 影响范围：主要涉及 CI/CD、其他模块。
- 改动规模：+9 / -1 行。
- 关键文件：.github/workflows/lint.yaml；.github/workflows/unittest.yaml；src/tools/retriever.py。

## 2025-07

- 新功能/增强：13 条
- Bug 修复：30 条

### 新功能 / 增强

#### 1. Feat: Add Wikipedia search engine (#478)

- 提交：`[bedf7d4](https://github.com/bytedance/deer-flow/commit/bedf7d4af2a19f32288387a9519cc91f9fdb0451)`
- 日期：2025-07-29
- 做了什么：新增或增强功能，主题是“Add Wikipedia search engine (#478)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+50 / -13 行。
- 关键文件：pyproject.toml；src/config/tools.py；src/tools/search.py；uv.lock。

#### 2. Feat: Cross-Language Search for RAGFlow (#469)

- 提交：`[f92bf0c](https://github.com/bytedance/deer-flow/commit/f92bf0ca223f51ecc6dccf31f2f4eeae94060af9)`
- 日期：2025-07-24
- 做了什么：新增或增强功能，主题是“Cross-Language Search for RAGFlow (#469)”。
- 影响范围：主要涉及 其他模块、文档。
- 改动规模：+20 / -0 行。
- 关键文件：.env.example；README.md；src/rag/ragflow.py；tests/unit/rag/test_ragflow.py。

#### 3. feat: polish the mcp-server configure feature (#447)

- 提交：`[d34f488](https://github.com/bytedance/deer-flow/commit/d34f48819d162fa246b18b8fc6b78e1bbd2b1b4f)`
- 日期：2025-07-19
- 做了什么：新增或增强功能，主题是“polish the mcp-server configure feature (#447)”。
- 影响范围：主要涉及 其他模块、文档。
- 改动规模：+94 / -4 行。
- 关键文件：.env.example；docs/mcp_integrations.md；src/server/app.py；tests/unit/server/test_app.py。

#### 4. feat: disable the MCP server configuation by default (#444)

- 提交：`[75ad3e0](https://github.com/bytedance/deer-flow/commit/75ad3e0dc61de2bc38b12a87586bc2643e4f60c2)`
- 日期：2025-07-19
- 做了什么：新增或增强功能，主题是“disable the MCP server configuation by default (#444)”。
- 影响范围：主要涉及 其他模块、文档。
- 改动规模：+70 / -1 行。
- 关键文件：.env.example；docs/mcp_integrations.md；src/server/app.py；tests/unit/server/test_app.py。

#### 5. feat: add CORS setting for the backend application (#443)

- 提交：`[933f3bb](https://github.com/bytedance/deer-flow/commit/933f3bb83a80ca51a2566d88fe51afb29f12df0c)`
- 日期：2025-07-18
- 做了什么：新增或增强功能，主题是“add CORS setting for the backend application (#443)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+13 / -3 行。
- 关键文件：.env.example；src/server/app.py。

#### 6. feat: support AzureChatOpenAI under configuring azure_endpoint or AZURE_OPENAI_ENDPOINT (#237)

- 提交：`[0c46f83](https://github.com/bytedance/deer-flow/commit/0c46f8361b9b5bf830ace3169dfe7d5a341391ee)`
- 日期：2025-07-13
- 做了什么：新增或增强功能，主题是“support AzureChatOpenAI under configuring azure_endpoint or AZURE_OPENAI_ENDPOINT (#237)”。
- 影响范围：主要涉及 文档、其他模块。
- 改动规模：+21 / -16 行。
- 关键文件：docs/configuration_guide.md；src/llms/llm.py。

#### 7. feat: add the Chinese i8n support on the setting table (#404)

- 提交：`[70b86d8](https://github.com/bytedance/deer-flow/commit/70b86d8464341e1416b71a82372fa5be1f8135b0)`
- 日期：2025-07-12
- 做了什么：新增或增强功能，主题是“add the Chinese i8n support on the setting table (#404)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+126 / -56 行。
- 关键文件：web/messages/en.json；web/messages/zh.json；web/src/app/settings/tabs/about-en.md；web/src/app/settings/tabs/about-tab.tsx；web/src/app/settings/tabs/about-zh.md；web/src/app/settings/tabs/about.md；web/src/app/settings/tabs/mcp-tab.tsx。

#### 8. feat: add i18n support and add Chinese (#372)

- 提交：`[e1187d7](https://github.com/bytedance/deer-flow/commit/e1187d7d02ceacf4db21c0ed7766d04b0c564190)`
- 日期：2025-07-12
- 做了什么：新增或增强功能，主题是“add i18n support and add Chinese (#372)”。
- 影响范围：主要涉及 其他模块、配置。
- 改动规模：+917 / -266 行。
- 关键文件：web/messages/en.json；web/messages/zh.json；web/next.config.js；web/package.json；web/pnpm-lock.yaml；web/src/app/chat/components/conversation-starter.tsx；web/src/app/chat/components/input-box.tsx；web/src/app/chat/components/message-list-view.tsx。

#### 9. feat: add the vscode unit test debug settings (#346)

- 提交：`[0d3255c](https://github.com/bytedance/deer-flow/commit/0d3255cdae88e5476e9f36d76e18872f08fc593f)`
- 日期：2025-07-12
- 做了什么：补充/增强测试体系，主题是“add the vscode unit test debug settings (#346)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+37 / -0 行。
- 关键文件：.vscode/launch.json；.vscode/settings.json。

#### 10. feat(llm): Add retry mechanism for LLM API calls (#400)

- 提交：`[9f8f060](https://github.com/bytedance/deer-flow/commit/9f8f060506d90d0745494e4da9cd6a0a826d803f)`
- 日期：2025-07-12
- 做了什么：新增或增强功能，主题是“Add retry mechanism for LLM API calls (#400)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+7 / -0 行。
- 关键文件：conf.yaml.example；src/llms/llm.py。

#### 11. feat: add Domain Control Features for Tavily Search Engine (#401)

- 提交：`[dfd4712](https://github.com/bytedance/deer-flow/commit/dfd4712d9fda931a6b9583e151839154868cc829)`
- 日期：2025-07-12
- 做了什么：新增或增强功能，主题是“add Domain Control Features for Tavily Search Engine (#401)”。
- 影响范围：主要涉及 其他模块、文档。
- 改动规模：+57 / -0 行。
- 关键文件：conf.yaml.example；docs/configuration_guide.md；src/tools/search.py。

#### 12. doc: add knowledgebase rag examples in readme (#383)

- 提交：`[859c6e3](https://github.com/bytedance/deer-flow/commit/859c6e3c5d7468702f0f54ed0bdb085c929a77d9)`
- 日期：2025-07-07
- 做了什么：补充文档能力，主题是“doc: add knowledgebase rag examples in readme (#383)”。
- 影响范围：主要涉及 文档。
- 改动规模：+47 / -9 行。
- 关键文件：README.md；README_zh.md。

#### 13. feat: integrate VikingDB Knowledge Base into rag retrieving tool (#381)

- 提交：`[be893ea](https://github.com/bytedance/deer-flow/commit/be893eae2bd144c2561433693eaed104fe3190c0)`
- 日期：2025-07-03
- 做了什么：新增或增强功能，主题是“integrate VikingDB Knowledge Base into rag retrieving tool (#381)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+814 / -3 行。
- 关键文件：.env.example；pyproject.toml；src/config/tools.py；src/rag/**init**.py；src/rag/builder.py；src/rag/vikingdb_knowledge_base.py；tests/unit/rag/test_vikingdb_knowledge_base.py；uv.lock。

### Bug 修复

#### 1. fix: build of the web (#492)

- 提交：`[ba7509d](https://github.com/bytedance/deer-flow/commit/ba7509d9ae10158a6e241fc15b154a29788fe467)`
- 日期：2025-07-31
- 做了什么：修复缺陷或回归问题，主题是“build of the web (#492)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+6 / -5 行。
- 关键文件：web/src/core/mcp/types.ts；web/src/core/store/settings-store.ts。

#### 2. fix:try to fix the docker build of front-end (#487)

- 提交：`[aca9dcf](https://github.com/bytedance/deer-flow/commit/aca9dcf643c49bc970a404d519ff3260d6086753)`
- 日期：2025-07-30
- 做了什么：修复缺陷或回归问题，主题是“try to fix the docker build of front-end (#487)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+3 / -3 行。
- 关键文件：web/src/core/store/settings-store.ts。

#### 3. fix: docker build with uv.lock updated (#486)

- 提交：`[98ef913](https://github.com/bytedance/deer-flow/commit/98ef913b881c2fc172c51017802d2911f979ae6c)`
- 日期：2025-07-29
- 做了什么：修复缺陷或回归问题，主题是“docker build with uv.lock updated (#486)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+40 / -11 行。
- 关键文件：uv.lock。

#### 4. fix: Add streamable MCP server support (#468)

- 提交：`[e178483](https://github.com/bytedance/deer-flow/commit/e178483971a7c98c6c1b782df973a5d0d25adf9a)`
- 日期：2025-07-29
- 做了什么：修复缺陷或回归问题，主题是“Add streamable MCP server support (#468)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+27 / -6 行。
- 关键文件：pyproject.toml；src/server/mcp_utils.py；tests/unit/server/test_mcp_utils.py；web/src/app/settings/dialogs/add-mcp-server-dialog.tsx；web/src/core/mcp/schema.ts；web/src/core/mcp/types.ts。

#### 5. fix: dotenv flags error (#472)

- 提交：`[89c1b68](https://github.com/bytedance/deer-flow/commit/89c1b689dce49fe9854e46175bdcd277093fe82a)`
- 日期：2025-07-24
- 做了什么：修复缺陷或回归问题，主题是“dotenv flags error (#472)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+2 / -2 行。
- 关键文件：web/package.json。

#### 6. fix:env AGENT_RECURSION_LIMIT not work (#453)

- 提交：`[32d8e51](https://github.com/bytedance/deer-flow/commit/32d8e514e1ed17d6dd3fd977d2816a898bdb0a89)`
- 日期：2025-07-22
- 做了什么：修复缺陷或回归问题，主题是“env AGENT_RECURSION_LIMIT not work (#453)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+84 / -1 行。
- 关键文件：src/config/configuration.py；src/server/app.py；src/workflow.py；tests/unit/config/test_configuration.py。

#### 7. Fix empty tuple agent (#458)

- 提交：`[b197b0f](https://github.com/bytedance/deer-flow/commit/b197b0f4cb46adcf5e1bc26355d3d1aafac37178)`
- 日期：2025-07-22
- 做了什么：修复缺陷或回归问题，主题是“Fix empty tuple agent (#458)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+1 / -1 行。
- 关键文件：src/server/app.py。

#### 8. fix: JSON parse error in link.tsx (#448)

- 提交：`[e6ba1fc](https://github.com/bytedance/deer-flow/commit/e6ba1fcd82d67f6deaa42f2e870df04bb694fa65)`
- 日期：2025-07-20
- 做了什么：修复缺陷或回归问题，主题是“JSON parse error in link.tsx (#448)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+2 / -1 行。
- 关键文件：web/src/components/deer-flow/link.tsx。

#### 9. fix: keep applying quick fix for #446 (#450)

- 提交：`[4d65d20](https://github.com/bytedance/deer-flow/commit/4d65d20f011f20cfa4376b8251aa533917c0ae75)`
- 日期：2025-07-20
- 做了什么：修复缺陷或回归问题，主题是“keep applying quick fix for #446 (#450)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+3 / -5 行。
- 关键文件：.env.example；src/server/app.py。

#### 10. fix: the Backend returns 400 error (#449)

- 提交：`[ff67366](https://github.com/bytedance/deer-flow/commit/ff67366c5c508e8c0be2ada8d40f3544cd86dcfe)`
- 日期：2025-07-20
- 做了什么：修复缺陷或回归问题，主题是“the Backend returns 400 error (#449)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+8 / -4 行。
- 关键文件：.env.example；src/server/app.py。

#### 11. fix: fix the bug introduced by coordinator messages update (#445)

- 提交：`[dbb24d7](https://github.com/bytedance/deer-flow/commit/dbb24d7d146470613227ab99519a1e3c2905433d)`
- 日期：2025-07-18
- 做了什么：修复缺陷或回归问题，主题是“fix the bug introduced by coordinator messages update (#445)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+4 / -8 行。
- 关键文件：src/graph/nodes.py。

#### 12. fix:planner AttributeError 'list' object has no attribute 'get' (#436)

- 提交：`[f17b06f](https://github.com/bytedance/deer-flow/commit/f17b06f2060f2ca371a9c016516a603173e62f2a)`
- 日期：2025-07-18
- 做了什么：修复缺陷或回归问题，主题是“planner AttributeError 'list' object has no attribute 'get' (#436)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+1 / -1 行。
- 关键文件：src/graph/nodes.py。

#### 13. fix:The console UI directly throws an error when user input is empty (#438)

- 提交：`[c14c548](https://github.com/bytedance/deer-flow/commit/c14c548e0c28b25d02aa42b731788546d691b093)`
- 日期：2025-07-17
- 做了什么：修复缺陷或回归问题，主题是“The console UI directly throws an error when user input is empty (#438)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+5 / -1 行。
- 关键文件：main.py。

#### 14. fix: fix the coordinator's forgetting of its own messages. (#433)

- 提交：`[c89b358](https://github.com/bytedance/deer-flow/commit/c89b35805d01555b6a150bc09155cfa49f78a511)`
- 日期：2025-07-17
- 做了什么：修复缺陷或回归问题，主题是“fix the coordinator's forgetting of its own messages. (#433)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+8 / -1 行。
- 关键文件：src/graph/nodes.py。

#### 15. fix: fix unit test cases for prompt enhancer (#431)

- 提交：`[774473c](https://github.com/bytedance/deer-flow/commit/774473cc184fde0971b76dd67985674e4752eff8)`
- 日期：2025-07-16
- 做了什么：修复缺陷或回归问题，主题是“fix unit test cases for prompt enhancer (#431)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+307 / -1 行。
- 关键文件：tests/unit/prompt_enhancer/graph/test_enhancer_node.py。

#### 16. fix: handle empty agent tuple in streaming workflow (#427)

- 提交：`[b04225b](https://github.com/bytedance/deer-flow/commit/b04225b7c83e5635f91f17d691b34d6244a90b1e)`
- 日期：2025-07-16
- 做了什么：修复缺陷或回归问题，主题是“handle empty agent tuple in streaming workflow (#427)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+5 / -1 行。
- 关键文件：src/server/app.py。

#### 17. fix: clean up the builder code (#417)

- 提交：`[0f118fd](https://github.com/bytedance/deer-flow/commit/0f118fda924a09ea6059da3a764307329b29eb1c)`
- 日期：2025-07-15
- 做了什么：修复缺陷或回归问题，主题是“clean up the builder code (#417)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+22 / -2 行。
- 关键文件：src/graph/builder.py；tests/unit/graph/test_builder.py。

#### 18. fix: missing i18n message (#410)

- 提交：`[8bdc6bf](https://github.com/bytedance/deer-flow/commit/8bdc6bfa2d4fd00c99808ddadb035c42401a09b5)`
- 日期：2025-07-14
- 做了什么：修复缺陷或回归问题，主题是“missing i18n message (#410)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+1 / -1 行。
- 关键文件：web/messages/en.json。

#### 19. fix: add missing translation for chat.page (#409)

- 提交：`[afbcdd6](https://github.com/bytedance/deer-flow/commit/afbcdd68d8c455d84e6a7fe8be0023f451511818)`
- 日期：2025-07-14
- 做了什么：修复缺陷或回归问题，主题是“add missing translation for chat.page (#409)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+5 / -0 行。
- 关键文件：web/messages/en.json。

#### 20. fix: main build fix for the merge #237 (#407)

- 提交：`[bf3bcee](https://github.com/bytedance/deer-flow/commit/bf3bcee8e3010c83575ec38e215f7c159d95d53a)`
- 日期：2025-07-13
- 做了什么：修复缺陷或回归问题，主题是“main build fix for the merge #237 (#407)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+3 / -5 行。
- 关键文件：src/llms/llm.py。

#### 21. fix: update the reasoning model url in conf.yaml.example (#406)

- 提交：`[86a89ac](https://github.com/bytedance/deer-flow/commit/86a89acac3c39e3860a0448d839cbece383b3bff)`
- 日期：2025-07-13
- 做了什么：修复缺陷或回归问题，主题是“update the reasoning model url in conf.yaml.example (#406)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+1 / -1 行。
- 关键文件：conf.yaml.example。

#### 22. fix:catch toolCalls doesn't return validate json (#405)

- 提交：`[2121510](https://github.com/bytedance/deer-flow/commit/2121510f63365e4a0f6089759cb95dd2e6ba11c8)`
- 日期：2025-07-12
- 做了什么：修复缺陷或回归问题，主题是“catch toolCalls doesn't return validate json (#405)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+14 / -6 行。
- 关键文件：web/src/components/deer-flow/link.tsx。

#### 23. fix: repair_json_output cannot process msgs that do not starts with {, [ or ``` (#384)

- 提交：`[0dc6c16](https://github.com/bytedance/deer-flow/commit/0dc6c16c423c1774f7122ef5472ccbb4c2a13b74)`
- 日期：2025-07-12
- 做了什么：修复缺陷或回归问题，主题是“repair_json_output cannot process msgs that do not starts with {, [ or ``` (#384)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+13 / -17 行。
- 关键文件：src/utils/json_utils.py。

#### 24. fix: correctly remove outermost code block markers in model responses (fix markdown rendering issue) (#386)

- 提交：`[5abf8c1](https://github.com/bytedance/deer-flow/commit/5abf8c1f5ed7b2ebe4c1757606067ae1d73e7712)`
- 日期：2025-07-12
- 做了什么：修复缺陷或回归问题，主题是“correctly remove outermost code block markers in model responses (fix markdown rendering issue) (#386)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+44 / -8 行。
- 关键文件：web/src/components/deer-flow/markdown.tsx。

#### 25. fix:upgrade uv version to avoid the big change of uv.lock (#402)

- 提交：`[136f7ea](https://github.com/bytedance/deer-flow/commit/136f7eaa4ea289d8dcf2145156a49b6682b39a79)`
- 日期：2025-07-12
- 做了什么：修复缺陷或回归问题，主题是“upgrade uv version to avoid the big change of uv.lock (#402)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+3 / -0 行。
- 关键文件：pyproject.toml。

#### 26. fix: fix the lint check errors of the main branch (#403)

- 提交：`[3c46201](https://github.com/bytedance/deer-flow/commit/3c46201ff0f74e3df9403c1a3edb77cced67e7c4)`
- 日期：2025-07-12
- 做了什么：修复缺陷或回归问题，主题是“fix the lint check errors of the main branch (#403)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+21 / -128 行。
- 关键文件：src/config/**init**.py；src/crawler/crawler.py；src/llms/llm.py；src/prompt_enhancer/graph/enhancer_node.py；src/rag/vikingdb_knowledge_base.py；src/tools/search.py；tests/integration/test_nodes.py；tests/test_state.py。

#### 27. fix: some lint fix using tools (#98)

- 提交：`[2363b21](https://github.com/bytedance/deer-flow/commit/2363b21447869d758b361909493eb9d1e24a51a8)`
- 日期：2025-07-12
- 做了什么：修复缺陷或回归问题，主题是“some lint fix using tools (#98)”。
- 影响范围：主要涉及 其他模块、文档。
- 改动规模：+206 / -137 行。
- 关键文件：CONTRIBUTING；Makefile；README.md；README_de.md；README_es.md；README_ja.md；README_pt.md；README_ru.md。

#### 28. fix: the typo of setup-uv action (#393)

- 提交：`[d801680](https://github.com/bytedance/deer-flow/commit/d8016809b279b43f2c22b99ade26b12b3c218ea0)`
- 日期：2025-07-07
- 做了什么：修复缺陷或回归问题，主题是“the typo of setup-uv action (#393)”。
- 影响范围：主要涉及 CI/CD。
- 改动规模：+2 / -2 行。
- 关键文件：.github/workflows/lint.yaml；.github/workflows/unittest.yaml。

#### 29. fix: spine the github hash on the third party actions (#392)

- 提交：`[6c254c0](https://github.com/bytedance/deer-flow/commit/6c254c0783111894652b2e92866a00cb94881a18)`
- 日期：2025-07-07
- 做了什么：修复缺陷或回归问题，主题是“spine the github hash on the third party actions (#392)”。
- 影响范围：主要涉及 CI/CD。
- 改动规模：+5 / -5 行。
- 关键文件：.github/workflows/container.yaml；.github/workflows/lint.yaml；.github/workflows/unittest.yaml。

#### 30. fix: docker build (#385)

- 提交：`[d4fbc86](https://github.com/bytedance/deer-flow/commit/d4fbc86b285205f0d0793461a4e7d5a4fa46e545)`
- 日期：2025-07-05
- 做了什么：修复缺陷或回归问题，主题是“docker build (#385)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+1 / -1 行。
- 关键文件：Dockerfile。

## 2025-08

- 新功能/增强：4 条
- Bug 修复：11 条

### 新功能 / 增强

#### 1. feat: add lint check of front-end (#534)

- 提交：`[72f9c59](https://github.com/bytedance/deer-flow/commit/72f9c591953d2871f18bcc78e987c32885d9fe48)`
- 日期：2025-08-22
- 做了什么：新增或增强功能，主题是“add lint check of front-end (#534)”。
- 影响范围：主要涉及 CI/CD、其他模块。
- 改动规模：+41 / -2 行。
- 关键文件：.github/workflows/lint.yaml；Makefile。

#### 2. feat: 1. replace black with ruff for fomatting and sort import (#489)

- 提交：`[3b4e993](https://github.com/bytedance/deer-flow/commit/3b4e993531feb5084f0e382ce4463eb5b8304cef)`
- 日期：2025-08-17
- 做了什么：新增或增强功能，主题是“1. replace black with ruff for fomatting and sort import (#489)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+246 / -229 行。
- 关键文件：Makefile；pyproject.toml；server.py；src/agents/agents.py；src/config/**init**.py；src/config/configuration.py；src/config/loader.py；src/config/tools.py。

#### 3. feat: Enhance chat streaming and tool call processing (#498)

- 提交：`[1bfec3a](https://github.com/bytedance/deer-flow/commit/1bfec3ad0556c3a5f54e1067a11379f5d8ce919c)`
- 日期：2025-08-16
- 做了什么：新增或增强功能，主题是“Enhance chat streaming and tool call processing (#498)”。
- 影响范围：主要涉及 其他模块、CI/CD、文档。
- 改动规模：+1559 / -120 行。
- 关键文件：.env.example；.github/workflows/unittest.yaml；README.md；pyproject.toml；server.py；src/config/configuration.py；src/graph/checkpoint.py；src/server/app.py。

#### 4. feat: Add llms to support the latest Open Source SOTA models (#497)

- 提交：`[d65b8f8](https://github.com/bytedance/deer-flow/commit/d65b8f8fcc7efc5e8bd579a996df0181b3160a52)`
- 日期：2025-08-13
- 做了什么：新增或增强功能，主题是“Add llms to support the latest Open Source SOTA models (#497)”。
- 影响范围：主要涉及 其他模块、文档。
- 改动规模：+684 / -9 行。
- 关键文件：README.md；docs/configuration_guide.md；src/config/agents.py；src/llms/llm.py；src/llms/providers/dashscope.py；tests/unit/llms/test_dashscope.py。

### Bug 修复

#### 1. Fix: build of font end of #466 (#530)

- 提交：`[0a02843](https://github.com/bytedance/deer-flow/commit/0a02843666d8f795ef60b8235163ea4bccb07656)`
- 日期：2025-08-21
- 做了什么：修复缺陷或回归问题，主题是“build of font end of #466 (#530)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+17 / -1 行。
- 关键文件：web/src/app/chat/components/message-list-view.tsx。

#### 2. FIX/Adapt message box to handle long text in frontend (#466)

- 提交：`[f17e5bd](https://github.com/bytedance/deer-flow/commit/f17e5bd6c84acb3781430af6dc61bf1d8d6d6ed0)`
- 日期：2025-08-21
- 做了什么：修复缺陷或回归问题，主题是“FIX/Adapt message box to handle long text in frontend (#466)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+53 / -24 行。
- 关键文件：web/src/app/chat/components/message-list-view.tsx；web/src/components/deer-flow/message-input.tsx；web/src/styles/prosemirror.css。

#### 3. fix: update TavilySearchWithImages to inherit from TavilySearchResults (#522)

- 提交：`[db6c1bf](https://github.com/bytedance/deer-flow/commit/db6c1bf7cb18d65f08109551ae0a026ab02907c4)`
- 日期：2025-08-21
- 做了什么：修复缺陷或回归问题，主题是“update TavilySearchWithImages to inherit from TavilySearchResults (#522)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+4 / -2 行。
- 关键文件：src/tools/tavily_search/tavily_search_results_with_images.py。

#### 4. fix: env parameters exception when configuring SSE or HTTP MCP server (#513)

- 提交：`[270d8c3](https://github.com/bytedance/deer-flow/commit/270d8c3712aa7933fb0b41d88bb7dbf5994a344e)`
- 日期：2025-08-20
- 做了什么：修复缺陷或回归问题，主题是“env parameters exception when configuring SSE or HTTP MCP server (#513)”。
- 影响范围：主要涉及 其他模块、文档。
- 改动规模：+54 / -16 行。
- 关键文件：docs/mcp_integrations.md；src/graph/nodes.py；src/server/app.py；src/server/mcp_request.py；src/server/mcp_utils.py；tests/unit/server/test_mcp_utils.py；web/src/core/mcp/types.ts；web/src/core/store/settings-store.ts。

#### 5. fix: GitHub workflow action version warning  (#520)

- 提交：`[b08e9ad](https://github.com/bytedance/deer-flow/commit/b08e9ad3ac12ad60b2c8488f1796da49224a6828)`
- 日期：2025-08-20
- 做了什么：修复缺陷或回归问题，主题是“GitHub workflow action version warning  (#520)”。
- 影响范围：主要涉及 CI/CD。
- 改动规模：+1 / -1 行。
- 关键文件：.github/workflows/unittest.yaml。

#### 6. fix: using commit hash as the action version (#519)

- 提交：`[c6d152a](https://github.com/bytedance/deer-flow/commit/c6d152a07438eee83e29349108dd7e3ba9c6ba16)`
- 日期：2025-08-20
- 做了什么：修复缺陷或回归问题，主题是“using commit hash as the action version (#519)”。
- 影响范围：主要涉及 CI/CD。
- 改动规模：+4 / -4 行。
- 关键文件：.github/workflows/container.yaml；.github/workflows/lint.yaml。

#### 7. fix: polish the makefile to provide help command (#518)

- 提交：`[44d328f](https://github.com/bytedance/deer-flow/commit/44d328f6966a5081ecb1d66cd2e111ef26fb85bd)`
- 日期：2025-08-20
- 做了什么：修复缺陷或回归问题，主题是“polish the makefile to provide help command (#518)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+17 / -9 行。
- 关键文件：.gitignore；Makefile。

#### 8. fix: backend server docker instance only listen to localhost (#508)

- 提交：`[ea17e82](https://github.com/bytedance/deer-flow/commit/ea17e82514a82e12df31db0a4397ce2a7cbfdaa8)`
- 日期：2025-08-11
- 做了什么：修复缺陷或回归问题，主题是“backend server docker instance only listen to localhost (#508)”。
- 影响范围：主要涉及 文档、配置。
- 改动规模：+15 / -9 行。
- 关键文件：README.md；README_de.md；README_es.md；README_ja.md；README_pt.md；README_ru.md；README_zh.md；docker-compose.yml。

#### 9. fix: tool name mismatch issue (#506)

- 提交：`[a4d6171](https://github.com/bytedance/deer-flow/commit/a4d6171c17e5a87403d3ded409a02fa056f49cfb)`
- 日期：2025-08-08
- 做了什么：修复缺陷或回归问题，主题是“tool name mismatch issue (#506)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+2 / -2 行。
- 关键文件：src/prompts/researcher.md。

#### 10. fix: added configuration of python_repl (#503)

- 提交：`[9e691ec](https://github.com/bytedance/deer-flow/commit/9e691ecf204221fc534d79ae232cf12565298c88)`
- 日期：2025-08-06
- 做了什么：修复缺陷或回归问题，主题是“added configuration of python_repl (#503)”。
- 影响范围：主要涉及 文档、其他模块。
- 改动规模：+194 / -77 行。
- 关键文件：.env.example；README.md；README_de.md；README_es.md；README_ja.md；README_pt.md；README_ru.md；README_zh.md。

#### 11. fix: langchain-mcp-adapters version conflict (#500)

- 提交：`[4218cdd](https://github.com/bytedance/deer-flow/commit/4218cddab5e4995434b44b209625a1224394850d)`
- 日期：2025-08-04
- 做了什么：修复缺陷或回归问题，主题是“langchain-mcp-adapters version conflict (#500)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+13 / -12 行。
- 关键文件：src/graph/nodes.py；tests/integration/test_nodes.py。

## 2025-09

- 新功能/增强：12 条
- Bug 修复：10 条

### 新功能 / 增强

#### 1. feat: add context compress (#590)

- 提交：`[5f4eb38](https://github.com/bytedance/deer-flow/commit/5f4eb38fdbf5ede5b45aca08284f644194143bd7)`
- 日期：2025-09-27
- 做了什么：新增或增强功能，主题是“add context compress (#590)”。
- 影响范围：主要涉及 其他模块、文档。
- 改动规模：+1032 / -7 行。
- 关键文件：docs/configuration_guide.md；src/agents/agents.py；src/graph/nodes.py；src/llms/llm.py；src/tools/search_postprocessor.py；src/tools/tavily_search/tavily_search_api_wrapper.py；src/utils/context_manager.py；tests/unit/tools/test_search_postprocessor.py。

#### 2. feat: add strategic_investment report style (#595)

- 提交：`[c214999](https://github.com/bytedance/deer-flow/commit/c214999606a38d8748ec30ceba4925dbb3693a56)`
- 日期：2025-09-24
- 做了什么：新增或增强功能，主题是“add strategic_investment report style (#595)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+135 / -22 行。
- 关键文件：src/config/report_style.py；src/prompts/reporter.md；src/rag/**init**.py；src/rag/builder.py；src/rag/moi.py；src/server/app.py；src/tools/search.py；web/messages/en.json。

#### 3. feat: add support for searx/searxng  (#253)

- 提交：`[1c27e0f](https://github.com/bytedance/deer-flow/commit/1c27e0f2aedf49e1b2e4623796df8319eace5416)`
- 日期：2025-09-22
- 做了什么：新增或增强功能，主题是“add support for searx/searxng  (#253)”。
- 影响范围：主要涉及 文档、其他模块。
- 改动规模：+41 / -1 行。
- 关键文件：.env.example；README.md；README_de.md；README_es.md；README_ja.md；README_pt.md；README_ru.md；README_zh.md。

#### 4. feat:support config tavily search results (#591)

- 提交：`[6bb0b95](https://github.com/bytedance/deer-flow/commit/6bb0b9557917565aa15110924b54b6a55998cbed)`
- 日期：2025-09-22
- 做了什么：新增或增强功能，主题是“support config tavily search results (#591)”。
- 影响范围：主要涉及 文档、其他模块。
- 改动规模：+15 / -4 行。
- 关键文件：docs/configuration_guide.md；src/tools/search.py。

#### 5. feat: support dify in rag module (#550)

- 提交：`[7694bb5](https://github.com/bytedance/deer-flow/commit/7694bb5d724edea27e0bd3c5beabb9e6f4777815)`
- 日期：2025-09-16
- 做了什么：新增或增强功能，主题是“support dify in rag module (#550)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+407 / -87 行。
- 关键文件：.env.example；server.py；src/config/configuration.py；src/config/tools.py；src/graph/checkpoint.py；src/llms/llm.py；src/llms/providers/dashscope.py；src/rag/**init**.py。

#### 6. feat: support for moi in RAG module (#571)

- 提交：`[5085bf8](https://github.com/bytedance/deer-flow/commit/5085bf8ee9f98e658dbf8a06db9af15d2625088f)`
- 日期：2025-09-16
- 做了什么：新增或增强功能，主题是“support for moi in RAG module (#571)”。
- 影响范围：主要涉及 其他模块、文档。
- 改动规模：+176 / -0 行。
- 关键文件：.env.example；README_zh.md；src/config/tools.py；src/rag/**init**.py；src/rag/builder.py；src/rag/moi.py。

#### 7. feat: add Google AI Studio API support with platform-based detection (#502)

- 提交：`[bbc49a0](https://github.com/bytedance/deer-flow/commit/bbc49a04a6cc1746f58f75bccda032ed5baeddf6)`
- 日期：2025-09-13
- 做了什么：新增或增强功能，主题是“add Google AI Studio API support with platform-based detection (#502)”。
- 影响范围：主要涉及 其他模块、文档。
- 改动规模：+215 / -3 行。
- 关键文件：conf.yaml.example；docs/configuration_guide.md；pyproject.toml；src/llms/llm.py；uv.lock。

#### 8. feat: Implement Milvus retriver for RAG (#516)

- 提交：`[dd9af1e](https://github.com/bytedance/deer-flow/commit/dd9af1eb502bf00e2be8a1cc1d8c828c173a7c8d)`
- 日期：2025-09-12
- 做了什么：新增或增强功能，主题是“Implement Milvus retriver for RAG (#516)”。
- 影响范围：主要涉及 其他模块、文档。
- 改动规模：+1875 / -43 行。
- 关键文件：.env.example；docs/configuration_guide.md；pyproject.toml；src/config/configuration.py；src/config/loader.py；src/config/tools.py；src/graph/checkpoint.py；src/rag/builder.py。

#### 9. refactor(logging): add explicit error log message (#576)

- 提交：`[eec8e4d](https://github.com/bytedance/deer-flow/commit/eec8e4dd606520525f233edb31e2ddbbc43309d2)`
- 日期：2025-09-12
- 做了什么：新增或增强功能，主题是“add explicit error log message (#576)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+2 / -0 行。
- 关键文件：src/tools/tavily_search/tavily_search_results_with_images.py。

#### 10. docs: add deployment note for Linux servers (#565)

- 提交：`[0057126](https://github.com/bytedance/deer-flow/commit/005712679c542e370b270e1f0f85c4c4eb765b2c)`
- 日期：2025-09-09
- 做了什么：补充文档能力，主题是“add deployment note for Linux servers (#565)”。
- 影响范围：主要涉及 文档。
- 改动规模：+6 / -0 行。
- 关键文件：README.md；README_zh.md。

#### 11. feat: creating mogodb and postgres mock instance in checkpoint test (#561)

- 提交：`[4c17d88](https://github.com/bytedance/deer-flow/commit/4c17d880299264bdb6cc0610195dfe2e537ace0d)`
- 日期：2025-09-09
- 做了什么：补充/增强测试体系，主题是“creating mogodb and postgres mock instance in checkpoint test (#561)”。
- 影响范围：主要涉及 其他模块、CI/CD。
- 改动规模：+470 / -158 行。
- 关键文件：.github/workflows/unittest.yaml；pyproject.toml；src/graph/checkpoint.py；tests/unit/checkpoint/postgres_mock_utils.py；tests/unit/checkpoint/test_checkpoint.py；uv.lock。

#### 12. Add psycopg dependencies instruction for checkpointing (#564)

- 提交：`[7138ba3](https://github.com/bytedance/deer-flow/commit/7138ba36bced4f7c3a5ee70068072ce6e1226bd5)`
- 日期：2025-09-09
- 做了什么：新增或增强功能，主题是“Add psycopg dependencies instruction for checkpointing (#564)”。
- 影响范围：主要涉及 其他模块、文档。
- 改动规模：+19 / -1 行。
- 关键文件：Dockerfile；README.md。

### Bug 修复

#### 1. fix: support local models by making thought field optional in Plan model (#601)

- 提交：`[24f6905](https://github.com/bytedance/deer-flow/commit/24f6905c18d3d154d88bcd34d32a3726ea518110)`
- 日期：2025-09-27
- 做了什么：修复缺陷或回归问题，主题是“support local models by making thought field optional in Plan model (#601)”。
- 影响范围：主要涉及 其他模块、文档。
- 改动规模：+43 / -2 行。
- 关键文件：README.md；conf.yaml.example；docs/configuration_guide.md；src/prompts/planner.md；src/prompts/planner_model.py。

#### 2. fix: don't expose internal application error to client (#585)

- 提交：`[ea0fe62](https://github.com/bytedance/deer-flow/commit/ea0fe62971d5ce317514669e28ee3a3a3e3b2351)`
- 日期：2025-09-16
- 做了什么：修复缺陷或回归问题，主题是“don't expose internal application error to client (#585)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+1 / -1 行。
- 关键文件：src/server/app.py。

#### 3. fix: log the exception of graph execution (#577)

- 提交：`[79ab736](https://github.com/bytedance/deer-flow/commit/79ab7365c06cf1c14279155092334109a56b1d20)`
- 日期：2025-09-14
- 做了什么：修复缺陷或回归问题，主题是“log the exception of graph execution (#577)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+29 / -18 行。
- 关键文件：src/server/app.py。

#### 4. fix: frontend supports chinese for listing datasets in RAG (#582)

- 提交：`[26a587c](https://github.com/bytedance/deer-flow/commit/26a587c24e1f33f84eada25d878273609645026f)`
- 日期：2025-09-14
- 做了什么：修复缺陷或回归问题，主题是“frontend supports chinese for listing datasets in RAG (#582)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+34 / -13 行。
- 关键文件：web/src/components/deer-flow/message-input.tsx；web/src/components/deer-flow/resource-suggestion.tsx。

#### 5. fix: Remove duplicate assignment operations for the tool_call_chunks field (#575)

- 提交：`[6d1d7f2](https://github.com/bytedance/deer-flow/commit/6d1d7f2d9e21d950dc1144e31557aa5fef9a0656)`
- 日期：2025-09-12
- 做了什么：修复缺陷或回归问题，主题是“Remove duplicate assignment operations for the tool_call_chunks field (#575)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+0 / -1 行。
- 关键文件：src/server/app.py。

#### 6. fix: the stdio and sse mcp server loading issue (#566)

- 提交：`[317acdf](https://github.com/bytedance/deer-flow/commit/317acdffadbaf99ccb644bdad38e44aa4e09c31f)`
- 日期：2025-09-09
- 做了什么：修复缺陷或回归问题，主题是“the stdio and sse mcp server loading issue (#566)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+6 / -1 行。
- 关键文件：src/server/mcp_utils.py。

#### 7. fix: correct typo in MongoDB connection string within .env.example (#560)

- 提交：`[38ff2f7](https://github.com/bytedance/deer-flow/commit/38ff2f7276d0330b76bbb4bec023fcb0761d8c15)`
- 日期：2025-09-08
- 做了什么：修复缺陷或回归问题，主题是“correct typo in MongoDB connection string within .env.example (#560)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+2 / -2 行。
- 关键文件：.env.example。

#### 8. fix: the search content return tuple issue (#555)

- 提交：`[a41ced1](https://github.com/bytedance/deer-flow/commit/a41ced13459d67122604ccdb170779f50fc841a8)`
- 日期：2025-09-04
- 做了什么：修复缺陷或回归问题，主题是“the search content return tuple issue (#555)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+3 / -0 行。
- 关键文件：src/graph/nodes.py。

#### 9. Fixed the deepseek v3 planning issue #545 (#554)

- 提交：`[8f127df](https://github.com/bytedance/deer-flow/commit/8f127df9489272d7069bf6f247cb3242fb1b3160)`
- 日期：2025-09-04
- 做了什么：修复缺陷或回归问题，主题是“Fixed the deepseek v3 planning issue #545 (#554)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+1 / -1 行。
- 关键文件：src/graph/nodes.py。

#### 10. fix deer-flow/src/prompts/prose/prose_zap.md (#553)

- 提交：`[5f1981a](https://github.com/bytedance/deer-flow/commit/5f1981ac9b361936844997503087756d12e19fe1)`
- 日期：2025-09-03
- 做了什么：修复缺陷或回归问题，主题是“fix deer-flow/src/prompts/prose/prose_zap.md (#553)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+1 / -1 行。
- 关键文件：src/prompts/prose/prose_zap.md。

## 2025-10

- 新功能/增强：11 条
- Bug 修复：34 条

### 新功能 / 增强

#### 1. security: add log injection attack prevention with input sanitization  (#667)

- 提交：`[b4c09aa](https://github.com/bytedance/deer-flow/commit/b4c09aa4b1cc0f0edb8b20d876daf38877c6d36c)`
- 日期：2025-10-27
- 做了什么：新增或增强功能，主题是“security: add log injection attack prevention with input sanitization  (#667)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+585 / -80 行。
- 关键文件：src/agents/agents.py；src/agents/tool_interceptor.py；src/crawler/readability_extractor.py；src/server/app.py；src/utils/log_sanitizer.py；tests/integration/test_tool_interceptor_integration.py；tests/unit/agents/test_tool_interceptor.py；tests/unit/crawler/test_jina_client.py。

#### 2. feat: add comprehensive debug logging for issue #477 hanging/freezing diagnosis (#662)

- 提交：`[83f1334](https://github.com/bytedance/deer-flow/commit/83f1334db08876b7b0d112dbe8f8334d0579babd)`
- 日期：2025-10-27
- 做了什么：新增或增强功能，主题是“add comprehensive debug logging for issue #477 hanging/freezing diagnosis (#662)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+172 / -28 行。
- 关键文件：server.py；src/agents/agents.py；src/agents/tool_interceptor.py；src/graph/nodes.py；src/server/app.py；tests/integration/test_nodes.py。

#### 3. docs: add tool-specific interrupts configuration to conf.yaml.example (#661)

- 提交：`[e9f0a02](https://github.com/bytedance/deer-flow/commit/e9f0a02f1fa4e1abfb00ed625596be3161f1fe41)`
- 日期：2025-10-27
- 做了什么：补充文档能力，主题是“add tool-specific interrupts configuration to conf.yaml.example (#661)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+17 / -0 行。
- 关键文件：conf.yaml.example。

#### 4. feat: implement tool-specific interrupts for create_react_agent (#572) (#659)

- 提交：`[bcc403e](https://github.com/bytedance/deer-flow/commit/bcc403ecd3d9d9aae082005fc09cafaa80ba6a3c)`
- 日期：2025-10-26
- 做了什么：新增或增强功能，主题是“implement tool-specific interrupts for create_react_agent (#572) (#659)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+1163 / -5 行。
- 关键文件：src/agents/agents.py；src/agents/tool_interceptor.py；src/config/configuration.py；src/graph/nodes.py；src/server/app.py；src/server/chat_request.py；tests/integration/test_tool_interceptor_integration.py；tests/unit/agents/test_tool_interceptor.py。

#### 5. feat: Add comprehensive Chinese localization support for issue #412 (#649)

- 提交：`[5eada04](https://github.com/bytedance/deer-flow/commit/5eada04f50a5c16d9ed7cae79485077c36bbce38)`
- 日期：2025-10-24
- 做了什么：新增或增强功能，主题是“Add comprehensive Chinese localization support for issue #412 (#649)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+1165 / -15 行。
- 关键文件：src/agents/agents.py；src/graph/nodes.py；src/prompt_enhancer/graph/enhancer_node.py；src/prompts/coder.zh_CN.md；src/prompts/coordinator.zh_CN.md；src/prompts/planner.zh_CN.md；src/prompts/podcast/podcast_script_writer.zh_CN.md；src/prompts/ppt/ppt_composer.zh_CN.md。

#### 6. Add frontend tests step to frontend lint workflow

- 提交：`[d9f829b](https://github.com/bytedance/deer-flow/commit/d9f829b6086a4532fd68ce474e86023b9df85750)`
- 日期：2025-10-16
- 做了什么：新增或增强功能，主题是“Add frontend tests step to frontend lint workflow”。
- 影响范围：主要涉及 CI/CD。
- 改动规模：+6 / -1 行。
- 关键文件：.github/workflows/lint.yaml。

#### 7. chore: add frontend unit tests to lint-frontend make target

- 提交：`[9b127c5](https://github.com/bytedance/deer-flow/commit/9b127c55f256ce318971a5183650eaa1968104a7)`
- 日期：2025-10-15
- 做了什么：新增或增强功能，主题是“add frontend unit tests to lint-frontend make target”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+2 / -1 行。
- 关键文件：Makefile。

#### 8. feat: Add intelligent clarification feature in coordinate step for research queries (#613)

- 提交：`[2510cc6](https://github.com/bytedance/deer-flow/commit/2510cc61de76a68d0d98d4b4f5b4490b77fc6a0c)`
- 日期：2025-10-13
- 做了什么：新增或增强功能，主题是“Add intelligent clarification feature in coordinate step for research queries (#613)”。
- 影响范围：主要涉及 其他模块、文档。
- 改动规模：+828 / -55 行。
- 关键文件：README.md；README_zh.md；docs/configuration_guide.md；main.py；src/graph/builder.py；src/graph/nodes.py；src/graph/types.py；src/prompts/coordinator.md。

#### 9. feature: clean up the temp file which are generated when running the unit test of milvus (#612)

- 提交：`[81c91dd](https://github.com/bytedance/deer-flow/commit/81c91dda43accb7f10471873ea06a3d50b5566c7)`
- 日期：2025-10-12
- 做了什么：补充/增强测试体系，主题是“feature: clean up the temp file which are generated when running the unit test of milvus (#612)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+128 / -28 行。
- 关键文件：tests/unit/rag/test_milvus.py。

#### 10. feature: add formula rander in the markdown (#611)

- 提交：`[2a6455c](https://github.com/bytedance/deer-flow/commit/2a6455c43631d00f9d62174bf61b720d30e9bccc)`
- 日期：2025-10-11
- 做了什么：新增或增强功能，主题是“feature: add formula rander in the markdown (#611)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+79 / -3 行。
- 关键文件：web/src/components/deer-flow/markdown.tsx；web/src/core/markdown/katex.ts；web/tests/markdown-katex.test.ts。

#### 11. feature:Add the debug setting on vscode (#606)

- 提交：`[79b9cdb](https://github.com/bytedance/deer-flow/commit/79b9cdb59ab50e31402177f82a184961eff0d8ec)`
- 日期：2025-10-05
- 做了什么：新增或增强功能，主题是“feature:Add the debug setting on vscode (#606)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+15 / -1 行。
- 关键文件：.vscode/launch.json。

### Bug 修复

#### 1. fix: prevent DOM error when removing temporary download link (#675) (#676)

- 提交：`[fea585a](https://github.com/bytedance/deer-flow/commit/fea585ae3dbb4e4e6bcc43cab6e6018edfeb6272)`
- 日期：2025-10-31
- 做了什么：修复缺陷或回归问题，主题是“prevent DOM error when removing temporary download link (#675) (#676)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+7 / -2 行。
- 关键文件：web/src/app/chat/components/research-block.tsx。

#### 2. fix: remove the unnessary conditional edge. (#671)

- 提交：`[6ae4bc5](https://github.com/bytedance/deer-flow/commit/6ae4bc588a0022d067c61da21f16d50980519d4a)`
- 日期：2025-10-29
- 做了什么：修复缺陷或回归问题，主题是“remove the unnessary conditional edge. (#671)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+2 / -8 行。
- 关键文件：src/graph/builder.py；tests/unit/graph/test_builder.py。

#### 3. fix: presever the local setting between frontend and backend (#670)

- 提交：`[0415f62](https://github.com/bytedance/deer-flow/commit/0415f622da4ab010c140d6a9630b5df5d5fa8b7e)`
- 日期：2025-10-28
- 做了什么：修复缺陷或回归问题，主题是“presever the local setting between frontend and backend (#670)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+994 / -21 行。
- 关键文件：src/graph/nodes.py；src/server/app.py；tests/integration/test_nodes.py；tests/unit/graph/test_agent_locale_restoration.py；tests/unit/graph/test_human_feedback_locale_fix.py；tests/unit/graph/test_state_preservation.py。

#### 4. fix: pass the locale through the frontend chat (#668)

- 提交：`[eb4c3b8](https://github.com/bytedance/deer-flow/commit/eb4c3b8ef60378b6db667fc7a201d36fceb5ded6)`
- 日期：2025-10-28
- 做了什么：修复缺陷或回归问题，主题是“pass the locale through the frontend chat (#668)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+27 / -0 行。
- 关键文件：web/src/core/api/chat.ts。

#### 5. fix: make SSE buffer size configurable to prevent overflow during multi-round searches (#664) (#665)

- 提交：`[ccd7535](https://github.com/bytedance/deer-flow/commit/ccd75350720ad8c5163d2df3364b90bdd422da8c)`
- 日期：2025-10-27
- 做了什么：修复缺陷或回归问题，主题是“make SSE buffer size configurable to prevent overflow during multi-round searches (#664) (#665)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+25 / -2 行。
- 关键文件：web/.env.example；web/src/core/sse/fetch-stream.ts；web/src/env.js。

#### 6. fix: handle escaped curly braces in LaTeX formulas (#608) (#660)

- 提交：`[6ded818](https://github.com/bytedance/deer-flow/commit/6ded818f62fb198516688cef383ec9dd586debe1)`
- 日期：2025-10-26
- 做了什么：修复缺陷或回归问题，主题是“handle escaped curly braces in LaTeX formulas (#608) (#660)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+32 / -0 行。
- 关键文件：web/src/core/utils/markdown.ts；web/tests/markdown-math-editor.test.ts。

#### 7. fix: improve config loading resilience for non-localhost access (#510) (#658)

- 提交：`[0441038](https://github.com/bytedance/deer-flow/commit/04410386722276244e0be729439e5915433efe90)`
- 日期：2025-10-26
- 做了什么：修复缺陷或回归问题，主题是“improve config loading resilience for non-localhost access (#510) (#658)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+80 / -16 行。
- 关键文件：web/.env.example；web/src/app/chat/components/input-box.tsx；web/src/core/api/hooks.ts。

#### 8. fix: parsed json with extra tokens issue (#656)

- 提交：`[c7a82b8](https://github.com/bytedance/deer-flow/commit/c7a82b82b4e28e0bd0af237088a64cf69812a536)`
- 日期：2025-10-26
- 做了什么：修复缺陷或回归问题，主题是“parsed json with extra tokens issue (#656)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+779 / -7 行。
- 关键文件：src/graph/nodes.py；src/utils/context_manager.py；src/utils/json_utils.py；tests/unit/utils/test_json_utils.py；web/src/app/chat/components/research-activities-block.tsx；web/src/core/utils/json.ts；web/tests/json.test.ts。

#### 9. fix: handle [ACCEPTED] feedback gracefully without TypeError in plan review  (#657)

- 提交：`[fd5a9ae](https://github.com/bytedance/deer-flow/commit/fd5a9aeae46c627764912b826af283f15dfbc255)`
- 日期：2025-10-25
- 做了什么：修复缺陷或回归问题，主题是“handle [ACCEPTED] feedback gracefully without TypeError in plan review  (#657)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+41 / -6 行。
- 关键文件：src/graph/nodes.py；tests/integration/test_nodes.py。

#### 10. fix: react key warnings from duplicate message IDs + establish jest testing framework (#655)

- 提交：`[1d71f89](https://github.com/bytedance/deer-flow/commit/1d71f8910e35a3c19d66fcca8fe53e1ce071ad49)`
- 日期：2025-10-25
- 做了什么：修复缺陷或回归问题，主题是“react key warnings from duplicate message IDs + establish jest testing framework (#655)”。
- 影响范围：主要涉及 其他模块、CI/CD、配置。
- 改动规模：+4127 / -151 行。
- 关键文件：.github/workflows/lint.yaml；Makefile；web/jest.config.mjs；web/jest.setup.js；web/package.json；web/pnpm-lock.yaml；web/src/app/chat/components/message-list-view.tsx；web/src/core/store/store.ts。

#### 11. fix: prevent tool name concatenation in consecutive tool calls to fix #523 (#654)

- 提交：`[f2be4d6](https://github.com/bytedance/deer-flow/commit/f2be4d6af16ba63196fbfd238151c7dfee71cee3)`
- 日期：2025-10-24
- 做了什么：修复缺陷或回归问题，主题是“prevent tool name concatenation in consecutive tool calls to fix #523 (#654)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+470 / -10 行。
- 关键文件：src/server/app.py；tests/unit/server/test_tool_call_chunks.py。

#### 12. fix: repair missing step_type fields in Plan validation (#653)

- 提交：`[36bf5c9](https://github.com/bytedance/deer-flow/commit/36bf5c9ccda0d4a742700044b212133424a57129)`
- 日期：2025-10-24
- 做了什么：修复缺陷或回归问题，主题是“repair missing step_type fields in Plan validation (#653)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+794 / -6 行。
- 关键文件：src/graph/nodes.py；src/prompts/planner.md；src/prompts/planner.zh_CN.md；tests/integration/test_nodes.py；tests/unit/graph/test_plan_validation.py。

#### 13. fix: resolve issue #651 - crawl error with None content handling (#652)

- 提交：`[975b344](https://github.com/bytedance/deer-flow/commit/975b344ca7f894765c6644d6b60bda47cab1e4ec)`
- 日期：2025-10-24
- 做了什么：修复缺陷或回归问题，主题是“resolve issue #651 - crawl error with None content handling (#652)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+329 / -10 行。
- 关键文件：src/crawler/article.py；src/crawler/crawler.py；src/crawler/jina_client.py；src/crawler/readability_extractor.py；tests/unit/crawler/test_article.py；tests/unit/crawler/test_jina_client.py；tests/unit/crawler/test_readability_extractor.py；tests/unit/tools/test_crawl.py。

#### 14. Fix: clarification bugs - max rounds, locale passing, and over-clarification (#647)

- 提交：`[2001a7c](https://github.com/bytedance/deer-flow/commit/2001a7c223886eef6177a6c5177ecef7846289dc)`
- 日期：2025-10-24
- 做了什么：修复缺陷或回归问题，主题是“clarification bugs - max rounds, locale passing, and over-clarification (#647)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+119 / -40 行。
- 关键文件：src/graph/nodes.py；src/graph/types.py；src/prompts/coordinator.md；src/tools/search.py；tests/integration/test_nodes.py；tests/unit/tools/test_search.py。

#### 15. fix: resolve issue #467 - message content validation and Tavily search error handling (#645)

- 提交：`[052490b](https://github.com/bytedance/deer-flow/commit/052490b116b5e916509378b12de5ade07fa62655)`
- 日期：2025-10-23
- 做了什么：修复缺陷或回归问题，主题是“resolve issue #467 - message content validation and Tavily search error handling (#645)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+114 / -14 行。
- 关键文件：src/graph/nodes.py；src/tools/tavily_search/tavily_search_results_with_images.py；src/utils/context_manager.py；tests/integration/test_nodes.py；tests/unit/tools/test_tavily_search_results_with_images.py。

#### 16. fix: Optimize the performance of stream data processing and add anti-… (#642)

- 提交：`[829cb39](https://github.com/bytedance/deer-flow/commit/829cb39b251078725555d5116ef6f763f38dac6e)`
- 日期：2025-10-22
- 做了什么：修复缺陷或回归问题，主题是“Optimize the performance of stream data processing and add anti-… (#642)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+81 / -17 行。
- 关键文件：web/src/components/editor/generative/ai-selector.tsx；web/src/core/sse/fetch-stream.ts；web/src/core/store/store.ts。

#### 17. fix: support additional Tavily search parameters via configuration to fix #548 (#643)

- 提交：`[9ece3fd](https://github.com/bytedance/deer-flow/commit/9ece3fd9c31ce3f983c9cf465b0b1e26c1c49579)`
- 日期：2025-10-22
- 做了什么：修复缺陷或回归问题，主题是“support additional Tavily search parameters via configuration to fix #548 (#643)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+245 / -5 行。
- 关键文件：conf.yaml.example；src/tools/search.py；tests/unit/tools/test_search.py。

#### 18. fix: Refine clarification workflow state handling (#641)

- 提交：`[003f081](https://github.com/bytedance/deer-flow/commit/003f081a7b2d2c35a9de0ba3f1672017989ef60a)`
- 日期：2025-10-22
- 做了什么：修复缺陷或回归问题，主题是“Refine clarification workflow state handling (#641)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+615 / -117 行。
- 关键文件：src/config/configuration.py；src/graph/nodes.py；src/graph/types.py；src/graph/utils.py；src/server/app.py；src/tools/search_postprocessor.py；src/workflow.py；tests/integration/test_nodes.py。

#### 19. fix: ensure web search is performed for research plans to fix #535 (#640)

- 提交：`[add0a70](https://github.com/bytedance/deer-flow/commit/add0a701f46050bcc0133d26a4a26ec7e12189b0)`
- 日期：2025-10-22
- 做了什么：修复缺陷或回归问题，主题是“ensure web search is performed for research plans to fix #535 (#640)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+95 / -8 行。
- 关键文件：src/config/configuration.py；src/graph/nodes.py；src/prompts/coordinator.md；src/prompts/planner.md；tests/integration/test_nodes.py。

#### 20. fix: unescape markdown-escaped characters in math formulas to fix #608 (#637)

- 提交：`[1a16677](https://github.com/bytedance/deer-flow/commit/1a16677d1a9540752a25bdeaf2d25ce135c088a2)`
- 日期：2025-10-21
- 做了什么：修复缺陷或回归问题，主题是“unescape markdown-escaped characters in math formulas to fix #608 (#637)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+127 / -3 行。
- 关键文件：web/src/components/editor/index.tsx；web/src/core/utils/markdown.ts；web/tests/markdown-math-editor.test.ts。

#### 21. fix: convert crawl_tool dict return to JSON string for type consistency (#636)

- 提交：`[d30c4d0](https://github.com/bytedance/deer-flow/commit/d30c4d00d3bef0e85fd2e92d1deb0ac4c696d6c5)`
- 日期：2025-10-21
- 做了什么：修复缺陷或回归问题，主题是“convert crawl_tool dict return to JSON string for type consistency (#636)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+10 / -6 行。
- 关键文件：src/tools/crawl.py；tests/unit/tools/test_crawl.py。

#### 22. fix: correct image result format for OpenAI compatibility to fix #632 (#634)

- 提交：`[e2ff765](https://github.com/bytedance/deer-flow/commit/e2ff765460164c8bfd659c2512fc02d5935b3c8c)`
- 日期：2025-10-20
- 做了什么：修复缺陷或回归问题，主题是“correct image result format for OpenAI compatibility to fix #632 (#634)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+12 / -5 行。
- 关键文件：src/tools/search_postprocessor.py；src/tools/tavily_search/tavily_search_api_wrapper.py；tests/unit/tools/test_tavily_search_api_wrapper.py。

#### 23. fix: handle non-string tool results to fix #631 (#633)

- 提交：`[3689bc0](https://github.com/bytedance/deer-flow/commit/3689bc0e69dc6fd6404863ec208f362d2acbb689)`
- 日期：2025-10-20
- 做了什么：修复缺陷或回归问题，主题是“handle non-string tool results to fix #631 (#633)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+6 / -2 行。
- 关键文件：src/server/app.py；web/src/app/chat/components/research-activities-block.tsx。

#### 24. fix: optimize animations to prevent browser freeze with many research steps (#630)

- 提交：`[984aa69](https://github.com/bytedance/deer-flow/commit/984aa69acfb81b8cf51a700d31e02208d2f473b6)`
- 日期：2025-10-19
- 做了什么：修复缺陷或回归问题，主题是“optimize animations to prevent browser freeze with many research steps (#630)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+92 / -65 行。
- 关键文件：web/src/app/chat/components/research-activities-block.tsx。

#### 25. fix: add missing RunnableConfig parameter to human_feedback_node (#629)

- 提交：`[5af036f](https://github.com/bytedance/deer-flow/commit/5af036f19fe3712546e5ca94f449dd01bf23d357)`
- 日期：2025-10-19
- 做了什么：修复缺陷或回归问题，主题是“add missing RunnableConfig parameter to human_feedback_node (#629)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+15 / -15 行。
- 关键文件：src/graph/nodes.py；tests/integration/test_nodes.py。

#### 26. fix: improve error handling in researcher and coder nodes (#596)

- 提交：`[57c9c2d](https://github.com/bytedance/deer-flow/commit/57c9c2dcd52c82a78d7a212de897698019f110df)`
- 日期：2025-10-19
- 做了什么：修复缺陷或回归问题，主题是“improve error handling in researcher and coder nodes (#596)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+26 / -3 行。
- 关键文件：src/graph/nodes.py。

#### 27. fix:the formual display error after report editing (#627)

- 提交：`[497a2a3](https://github.com/bytedance/deer-flow/commit/497a2a39cf02a6be9a2b60c7a332f9a7542882b1)`
- 日期：2025-10-17
- 做了什么：修复缺陷或回归问题，主题是“the formual display error after report editing (#627)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+46 / -0 行。
- 关键文件：web/src/core/utils/markdown.ts；web/tests/markdown-math-editor.test.ts。

#### 28. fix: prevent repeated content animation during thinking streaming (#614) (#623)

- 提交：`[c6348e7](https://github.com/bytedance/deer-flow/commit/c6348e70c6745f9d6f94d88059474c2494773fcf)`
- 日期：2025-10-16
- 做了什么：修复缺陷或回归问题，主题是“prevent repeated content animation during thinking streaming (#614) (#623)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+46 / -13 行。
- 关键文件：web/src/app/chat/components/message-list-view.tsx。

#### 29. fix: add unique key prop to conversation starter list items (#619)

- 提交：`[025ea6b](https://github.com/bytedance/deer-flow/commit/025ea6b94e742c4f5ae98bd9b5ee5d7cd3130c5e)`
- 日期：2025-10-16
- 做了什么：修复缺陷或回归问题，主题是“add unique key prop to conversation starter list items (#619)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+1 / -1 行。
- 关键文件：web/src/app/chat/components/conversation-starter.tsx。

#### 30. fix: configure Windows event loop policy for PostgreSQL async compatibility (#618)

- 提交：`[120fcfb](https://github.com/bytedance/deer-flow/commit/120fcfb316bdba35e0382e1e9170c89ba7ae0928)`
- 日期：2025-10-16
- 做了什么：修复缺陷或回归问题，主题是“configure Windows event loop policy for PostgreSQL async compatibility (#618)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+7 / -0 行。
- 关键文件：src/server/app.py。

#### 31. fix: exclude test files from TypeScript type checking

- 提交：`[779de40](https://github.com/bytedance/deer-flow/commit/779de40f106e9e2042ee47b1b7e9d481d35759d5)`
- 日期：2025-10-15
- 做了什么：修复缺陷或回归问题，主题是“exclude test files from TypeScript type checking”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+1 / -1 行。
- 关键文件：web/tsconfig.json。

#### 32. fix: resolve math formula display abnormal after editing report

- 提交：`[58c1743](https://github.com/bytedance/deer-flow/commit/58c1743ed59dfd87a9542ec2ab84caed601f18dd)`
- 日期：2025-10-15
- 做了什么：修复缺陷或回归问题，主题是“resolve math formula display abnormal after editing report”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+208 / -19 行。
- 关键文件：web/src/components/deer-flow/markdown.tsx；web/src/components/editor/extensions.tsx；web/src/components/editor/index.tsx；web/src/components/editor/math-serializer.ts；web/src/core/utils/markdown.ts；web/tests/markdown-katex.test.ts；web/tests/markdown-math-editor.test.ts。

#### 33. fix: add max_clarification_rounds parameter passing from frontend to backend (#616)

- 提交：`[24e2d86](https://github.com/bytedance/deer-flow/commit/24e2d86f7b1eaf05af0ba6aeb88d6a458fc2786b)`
- 日期：2025-10-14
- 做了什么：修复缺陷或回归问题，主题是“add max_clarification_rounds parameter passing from frontend to backend (#616)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+2 / -0 行。
- 关键文件：web/src/core/api/chat.ts；web/src/core/store/store.ts。

#### 34. chore: fix incorrect filename in conf.yaml.example comments (#609)

- 提交：`[f80af8e](https://github.com/bytedance/deer-flow/commit/f80af8e1320c58d944ebdd50b8054baae48ed00b)`
- 日期：2025-10-11
- 做了什么：修复缺陷或回归问题，主题是“fix incorrect filename in conf.yaml.example comments (#609)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+1 / -1 行。
- 关键文件：conf.yaml.example。

## 2025-11

- 新功能/增强：8 条
- Bug 修复：10 条

### 新功能 / 增强

#### 1. feat: add analysis step type for non-code reasoning tasks (#677) (#723)

- 提交：`[2e010a4](https://github.com/bytedance/deer-flow/commit/2e010a46196308e9163cd09b7ce3f1380a1520c2)`
- 日期：2025-11-29
- 做了什么：新增或增强功能，主题是“add analysis step type for non-code reasoning tasks (#677) (#723)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+266 / -69 行。
- 关键文件：src/config/agents.py；src/graph/builder.py；src/graph/nodes.py；src/prompts/analyst.md；src/prompts/analyst.zh_CN.md；src/prompts/planner.md；src/prompts/planner.zh_CN.md；src/prompts/planner_model.py。

#### 2. Add unit tests for PPT composer locale handling (#696)

- 提交：`[cc9414f](https://github.com/bytedance/deer-flow/commit/cc9414f9782db7f8f3cd7bc74fa72aea67bf11de)`
- 日期：2025-11-22
- 做了什么：新增或增强功能，主题是“Add unit tests for PPT composer locale handling (#696)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+138 / -0 行。
- 关键文件：.gitignore；tests/test_ppt_localization.py。

#### 3. feat: enable ppt_composer.zh_CN.md with request.locale (#694)

- 提交：`[1bfcf9f](https://github.com/bytedance/deer-flow/commit/1bfcf9f4299a15d65cbc37b0d5dd8556f07352cf)`
- 日期：2025-11-22
- 做了什么：新增或增强功能，主题是“enable ppt_composer.zh_CN.md with request.locale (#694)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+6 / -3 行。
- 关键文件：src/ppt/graph/ppt_composer_node.py；src/ppt/graph/state.py；src/server/app.py；src/server/chat_request.py。

#### 4. feat: be compatible with case: `json_object` is not supported by used model (#673)

- 提交：`[2d1a099](https://github.com/bytedance/deer-flow/commit/2d1a0997eba627301f6bdce5823ff2d675759dfa)`
- 日期：2025-11-21
- 做了什么：新增或增强功能，主题是“be compatible with case: `json_object` is not supported by used model (#673)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+19 / -5 行。
- 关键文件：src/graph/nodes.py。

#### 5. Add GitHub Copilot instructions for repository context (#698)

- 提交：`[b7a4b0f](https://github.com/bytedance/deer-flow/commit/b7a4b0f44610150e1f535dc70e3f57d0d5f56fcd)`
- 日期：2025-11-17
- 做了什么：新增或增强功能，主题是“Add GitHub Copilot instructions for repository context (#698)”。
- 影响范围：主要涉及 CI/CD。
- 改动规模：+303 / -0 行。
- 关键文件：.github/copilot-instructions.md。

#### 6. feat: Qdrant Vector Search Support (#684)

- 提交：`[aa027fa](https://github.com/bytedance/deer-flow/commit/aa027faf95d11690db4f3acea5f109c8ffd69543)`
- 日期：2025-11-11
- 做了什么：新增或增强功能，主题是“Qdrant Vector Search Support (#684)”。
- 影响范围：主要涉及 其他模块、文档。
- 改动规模：+1010 / -30 行。
- 关键文件：.env.example；README.md；docs/configuration_guide.md；pyproject.toml；src/config/tools.py；src/rag/**init**.py；src/rag/builder.py；src/rag/milvus.py。

#### 7. docs: add comprehensive debugging guide and improve troubleshooting documentation (#688)

- 提交：`[70dbd21](https://github.com/bytedance/deer-flow/commit/70dbd21bdf13cda071e5d2b0de9fd0fe6f38bfbd)`
- 日期：2025-11-10
- 做了什么：补充文档能力，主题是“add comprehensive debugging guide and improve troubleshooting documentation (#688)”。
- 影响范围：主要涉及 文档、其他模块。
- 改动规模：+408 / -2 行。
- 关键文件：.env.example；docs/DEBUGGING.md；docs/FAQ.md。

#### 8. feat: add edit and refresh functionality for MCP servers in settings tab (#680)

- 提交：`[a38c858](https://github.com/bytedance/deer-flow/commit/a38c8584d78e4cfabd7a408860a7e7cea4630a11)`
- 日期：2025-11-06
- 做了什么：新增或增强功能，主题是“add edit and refresh functionality for MCP servers in settings tab (#680)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+351 / -12 行。
- 关键文件：web/messages/en.json；web/messages/zh.json；web/src/app/settings/dialogs/edit-mcp-server-dialog.tsx；web/src/app/settings/tabs/mcp-tab.tsx。

### Bug 修复

#### 1. fix(web): handle incomplete JSON in MCP tool call arguments (#528) (#727)

- 提交：`[e179fb1](https://github.com/bytedance/deer-flow/commit/e179fb163274d0cace4ce14044f091d4bbf643eb)`
- 日期：2025-11-29
- 做了什么：修复缺陷或回归问题，主题是“handle incomplete JSON in MCP tool call arguments (#528) (#727)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+364 / -1 行。
- 关键文件：web/src/core/messages/merge-message.ts；web/tests/merge-message.test.ts。

#### 2. fix(llm): filter unexpected config keys to prevent LangChain warnings (#411) (#726)

- 提交：`[4a78cfe](https://github.com/bytedance/deer-flow/commit/4a78cfe12a6efa37524317e43cfb36a0f709cea3)`
- 日期：2025-11-29
- 做了什么：修复缺陷或回归问题，主题是“filter unexpected config keys to prevent LangChain warnings (#411) (#726)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+101 / -0 行。
- 关键文件：src/llms/llm.py；tests/unit/llms/test_llm.py。

#### 3. fix: apply context compression to prevent token overflow (Issue #721) (#722)

- 提交：`[b24f4d3](https://github.com/bytedance/deer-flow/commit/b24f4d3f38d45403b7525537de3ba7112c0a8835)`
- 日期：2025-11-28
- 做了什么：修复缺陷或回归问题，主题是“apply context compression to prevent token overflow (Issue #721) (#722)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+110 / -8 行。
- 关键文件：conf.yaml.example；src/graph/nodes.py；src/llms/llm.py；src/utils/context_manager.py。

#### 4. fix: the frontend error when cancle the research plan (#719)

- 提交：`[223ec57](https://github.com/bytedance/deer-flow/commit/223ec57fe4d9039836b6259458cd207d9994a262)`
- 日期：2025-11-28
- 做了什么：修复缺陷或回归问题，主题是“the frontend error when cancle the research plan (#719)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+5 / -0 行。
- 关键文件：src/server/app.py。

#### 5. fix: revert the part of patch of issue-710 to extract the content from the plan (#718)

- 提交：`[4559197](https://github.com/bytedance/deer-flow/commit/4559197505cede4c5fee5f8c41129052b44b5589)`
- 日期：2025-11-27
- 做了什么：修复缺陷或回归问题，主题是“revert the part of patch of issue-710 to extract the content from the plan (#718)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+10 / -176 行。
- 关键文件：src/graph/nodes.py；tests/unit/graph/test_plan_validation.py。

#### 6. fix: multiple web_search ToolMessages only showing last result (#717)

- 提交：`[ca4ada5](https://github.com/bytedance/deer-flow/commit/ca4ada5aa774fdecbe674791a4b8dd6a6d0fc30b)`
- 日期：2025-11-27
- 做了什么：修复缺陷或回归问题，主题是“multiple web_search ToolMessages only showing last result (#717)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+275 / -6 行。
- 关键文件：src/graph/nodes.py；tests/integration/test_nodes.py。

#### 7. fix: the exception of plan validation (#714)

- 提交：`[6679169](https://github.com/bytedance/deer-flow/commit/667916959b0a8a611d20b03175836c1a3f4154bd)`
- 日期：2025-11-27
- 做了什么：修复缺陷或回归问题，主题是“the exception of plan validation (#714)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+228 / -12 行。
- 关键文件：src/graph/nodes.py；tests/integration/test_nodes.py；tests/unit/graph/test_plan_validation.py。

#### 8. fix: the crawling error when encountering PDF URLs (#707)

- 提交：`[bec97f0](https://github.com/bytedance/deer-flow/commit/bec97f02ae596fc84e02e02d913fc5872a181eab)`
- 日期：2025-11-25
- 做了什么：修复缺陷或回归问题，主题是“the crawling error when encountering PDF URLs (#707)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+484 / -3 行。
- 关键文件：src/crawler/crawler.py；src/tools/crawl.py；tests/unit/crawler/test_crawler_class.py；tests/unit/tools/test_crawl.py。

#### 9. fix: the validation Error with qwen-max-latest Model (#706)

- 提交：`[da51433](https://github.com/bytedance/deer-flow/commit/da514337da8e57398870f223c81cab6964e7497a)`
- 日期：2025-11-24
- 做了什么：修复缺陷或回归问题，主题是“the validation Error with qwen-max-latest Model (#706)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+187 / -4 行。
- 关键文件：src/graph/nodes.py；tests/integration/test_nodes.py。

#### 10. fix: ensure researcher agent uses web search tool instead of generating URLs (#702) (#704)

- 提交：`[478291d](https://github.com/bytedance/deer-flow/commit/478291df0781b7fe60a05abade18808bc27e4f7d)`
- 日期：2025-11-24
- 做了什么：修复缺陷或回归问题，主题是“ensure researcher agent uses web search tool instead of generating URLs (#702) (#704)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+84 / -11 行。
- 关键文件：src/config/configuration.py；src/graph/nodes.py；src/prompts/researcher.md；src/prompts/researcher.zh_CN.md；src/rag/qdrant.py；tests/integration/test_nodes.py。

## 2025-12

- 新功能/增强：12 条
- Bug 修复：14 条

### 新功能 / 增强

#### 1. feat(eval): add report quality evaluation module and UI integration  (#776)

- 提交：`[8d9d767](https://github.com/bytedance/deer-flow/commit/8d9d7670518b4eadbac86de16bd5c08a40dae42a)`
- 日期：2025-12-25
- 做了什么：新增或增强功能，主题是“add report quality evaluation module and UI integration  (#776)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+2103 / -2 行。
- 关键文件：src/eval/**init**.py；src/eval/evaluator.py；src/eval/llm_judge.py；src/eval/metrics.py；src/server/app.py；src/server/eval_request.py；tests/unit/eval/**init**.py；tests/unit/eval/test_evaluator.py。

#### 2. test: add unit tests for global connection pool (Issue #778) (#780)

- 提交：`[fb319aa](https://github.com/bytedance/deer-flow/commit/fb319aaa44b212e3d43f691c943b9e0ed33e1162)`
- 日期：2025-12-23
- 做了什么：补充/增强测试体系，主题是“add unit tests for global connection pool (Issue #778) (#780)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+472 / -1 行。
- 关键文件：src/server/app.py；tests/unit/server/test_app.py。

#### 3. feat:Database connections use connection pools (#757)

- 提交：`[83e9d7c](https://github.com/bytedance/deer-flow/commit/83e9d7c9e58fd38e64a00f71e88c098f7c7d32b2)`
- 日期：2025-12-23
- 做了什么：新增或增强功能，主题是“Database connections use connection pools (#757)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+163 / -17 行。
- 关键文件：src/server/app.py。

#### 4. feat: add resource upload support for RAG (#768)

- 提交：`[04296cd](https://github.com/bytedance/deer-flow/commit/04296cdf5a320a2e4a736e7c021eaf9f0b6dafe9)`
- 日期：2025-12-19
- 做了什么：新增或增强功能，主题是“add resource upload support for RAG (#768)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+567 / -2 行。
- 关键文件：src/rag/milvus.py；src/rag/retriever.py；src/server/app.py；tests/unit/server/test_app.py；web/messages/en.json；web/messages/zh.json；web/src/app/settings/tabs/index.tsx；web/src/app/settings/tabs/rag-tab.tsx。

#### 5. feat(web): add enable_web_search frontend UI (#681) (#766)

- 提交：`[3e8f2ce](https://github.com/bytedance/deer-flow/commit/3e8f2ce3ada0116598e95bcd6e093e1f22e9a775)`
- 日期：2025-12-17
- 做了什么：新增或增强功能，主题是“add enable_web_search frontend UI (#681) (#766)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+44 / -2 行。
- 关键文件：web/messages/en.json；web/messages/zh.json；web/src/app/settings/tabs/general-tab.tsx；web/src/core/api/chat.ts；web/src/core/store/settings-store.ts；web/src/core/store/store.ts。

#### 6. feat(web): add multi-format report export (Markdown, HTML, PDF, Word,… (#756)

- 提交：`[a4f64ab](https://github.com/bytedance/deer-flow/commit/a4f64abd1f442835caedeee93bb591b0ae3dd0c4)`
- 日期：2025-12-16
- 做了什么：新增或增强功能，主题是“add multi-format report export (Markdown, HTML, PDF, Word,… (#756)”。
- 影响范围：主要涉及 其他模块、配置。
- 改动规模：+1079 / -109 行。
- 关键文件：web/messages/en.json；web/messages/zh.json；web/package.json；web/pnpm-lock.yaml；web/src/app/chat/components/research-block.tsx。

#### 7. feat: add Serper search engine support (#762)

- 提交：`[2a97170](https://github.com/bytedance/deer-flow/commit/2a97170b6c6743290780cc77eb2f07781c4da28e)`
- 日期：2025-12-15
- 做了什么：新增或增强功能，主题是“add Serper search engine support (#762)”。
- 影响范围：主要涉及 其他模块、文档。
- 改动规模：+47 / -1 行。
- 关键文件：.env.example；docs/configuration_guide.md；src/config/tools.py；src/tools/search.py；tests/unit/tools/test_search.py。

#### 8. feat: add enable_web_search config to disable web search (#681) (#760)

- 提交：`[93d81d4](https://github.com/bytedance/deer-flow/commit/93d81d450dd8dbb95d9aabc63055bdb666914cea)`
- 日期：2025-12-15
- 做了什么：新增或增强功能，主题是“add enable_web_search config to disable web search (#681) (#760)”。
- 影响范围：主要涉及 其他模块、文档。
- 改动规模：+89 / -7 行。
- 关键文件：conf.yaml.example；docs/configuration_guide.md；src/config/configuration.py；src/graph/nodes.py；src/server/app.py；src/server/chat_request.py；tests/unit/server/test_app.py。

#### 9. docs: add more MCP integration examples (#441) (#754)

- 提交：`[4c2592a](https://github.com/bytedance/deer-flow/commit/4c2592ac85d8af7c8eb8c47de6c7208a27254620)`
- 日期：2025-12-11
- 做了什么：补充文档能力，主题是“add more MCP integration examples (#441) (#754)”。
- 影响范围：主要涉及 文档。
- 改动规模：+161 / -20 行。
- 关键文件：docs/mcp_integrations.md。

#### 10. Add the InfoQuest banner to the README (#748)

- 提交：`[fde7a69](https://github.com/bytedance/deer-flow/commit/fde7a6956226a010c1c6be6a370b57669555dca2)`
- 日期：2025-12-08
- 做了什么：补充文档能力，主题是“Add the InfoQuest banner to the README (#748)”。
- 影响范围：主要涉及 文档。
- 改动规模：+51 / -9 行。
- 关键文件：README.md；README_de.md；README_es.md；README_ja.md；README_pt.md；README_ru.md；README_zh.md。

#### 11. feat:Strip code blocks in plan data. (#738)

- 提交：`[bd6c50d](https://github.com/bytedance/deer-flow/commit/bd6c50de330309e1c10df7f681db53a3d566a4cc)`
- 日期：2025-12-04
- 做了什么：新增或增强功能，主题是“Strip code blocks in plan data. (#738)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+2 / -2 行。
- 关键文件：src/graph/nodes.py。

#### 12. feat: support infoquest (#708)

- 提交：`[7ec9e45](https://github.com/bytedance/deer-flow/commit/7ec9e4570220a0d3c0517bd1e7619bda723025bf)`
- 日期：2025-12-02
- 做了什么：新增或增强功能，主题是“support infoquest (#708)”。
- 影响范围：主要涉及 其他模块、文档。
- 改动规模：+2103 / -94 行。
- 关键文件：.env.example；README.md；README_de.md；README_es.md；README_ja.md；README_pt.md；README_ru.md；README_zh.md。

### Bug 修复

#### 1. fix(main): Passing the local parameter from the main interactive mode (#791)

- 提交：`[a71b6bc](https://github.com/bytedance/deer-flow/commit/a71b6bc41fd80667381a9a790ecdcc99197c29cf)`
- 日期：2025-12-30
- 做了什么：修复缺陷或回归问题，主题是“Passing the local parameter from the main interactive mode (#791)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+13 / -0 行。
- 关键文件：main.py；src/workflow.py。

#### 2. fix(workflow): resolve locale hardcoding in src/workflow.py for interactive mode (#789)

- 提交：`[893ff82](https://github.com/bytedance/deer-flow/commit/893ff82a7f818aa6a35a4e43b153d2c90f556c0e)`
- 日期：2025-12-30
- 做了什么：修复缺陷或回归问题，主题是“resolve locale hardcoding in src/workflow.py for interactive mode (#789)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+6 / -8 行。
- 关键文件：src/workflow.py。

#### 3. fix(deps): update langchain-core to 1.2.5 to resolve CVE-2025-68664 (#787)

- 提交：`[5087d50](https://github.com/bytedance/deer-flow/commit/5087d5012f60aee82b8c722a26afbe04092973e0)`
- 日期：2025-12-27
- 做了什么：修复缺陷或回归问题，主题是“update langchain-core to 1.2.5 to resolve CVE-2025-68664 (#787)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+28 / -5 行。
- 关键文件：pyproject.toml；uv.lock。

#### 4. fix(podcast): add fallback for models without json_object support (#747) (#785)

- 提交：`[bab60e6](https://github.com/bytedance/deer-flow/commit/bab60e6e3d166a166b5b4f3bf33c1995d025697e)`
- 日期：2025-12-26
- 做了什么：修复缺陷或回归问题，主题是“add fallback for models without json_object support (#747) (#785)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+254 / -10 行。
- 关键文件：src/podcast/graph/script_writer_node.py；tests/unit/podcast/**init**.py；tests/unit/podcast/test_script_writer_node.py。

#### 5. fix(metrics): update the polynomial regular expression used on uncontrolled data (#784)

- 提交：`[5a79f89](https://github.com/bytedance/deer-flow/commit/5a79f896c4aeb5ff981619188dc59038dee760aa)`
- 日期：2025-12-26
- 做了什么：修复缺陷或回归问题，主题是“update the polynomial regular expression used on uncontrolled data (#784)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+2 / -2 行。
- 关键文件：src/eval/metrics.py。

#### 6. fix(web): enable runtime API URL detection for cross-machine access (#777) (#783)

- 提交：`[cd5c487](https://github.com/bytedance/deer-flow/commit/cd5c4877f34d001742db17f4a87bd815dbee4e16)`
- 日期：2025-12-25
- 做了什么：修复缺陷或回归问题，主题是“enable runtime API URL detection for cross-machine access (#777) (#783)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+18 / -1 行。
- 关键文件：web/src/core/api/resolve-service-url.ts。

#### 7. Fix typo in vulnerability reporting instructions (#772)

- 提交：`[1f403a9](https://github.com/bytedance/deer-flow/commit/1f403a9f797c0b37d382bd56e3a7050800739388)`
- 日期：2025-12-21
- 做了什么：修复缺陷或回归问题，主题是“Fix typo in vulnerability reporting instructions (#772)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+1 / -1 行。
- 关键文件：SECURITY.md。

#### 8. fix: display direct_response message in frontend (#763) (#764)

- 提交：`[b85130b](https://github.com/bytedance/deer-flow/commit/b85130b8490b0057f9407f95f204e7a6090f7a4b)`
- 日期：2025-12-17
- 做了什么：修复缺陷或回归问题，主题是“display direct_response message in frontend (#763) (#764)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+5 / -0 行。
- 关键文件：web/src/core/messages/merge-message.ts。

#### 9. fix: handle greetings without triggering research workflow (#755)

- 提交：`[c686ab7](https://github.com/bytedance/deer-flow/commit/c686ab70162a87de28f673357751d121a9b5f00e)`
- 日期：2025-12-13
- 做了什么：修复缺陷或回归问题，主题是“handle greetings without triggering research workflow (#755)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+64 / -36 行。
- 关键文件：src/graph/nodes.py；src/prompts/coordinator.md；src/prompts/coordinator.zh_CN.md；tests/integration/test_nodes.py。

#### 10. fix(agents): patch _run in ToolInterceptor to ensure interrupt triggering (#753)

- 提交：`[ec99338](https://github.com/bytedance/deer-flow/commit/ec99338c9a164c168b735a89a197fc189350783e)`
- 日期：2025-12-10
- 做了什么：修复缺陷或回归问题，主题是“patch _run in ToolInterceptor to ensure interrupt triggering (#753)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+76 / -0 行。
- 关键文件：src/agents/tool_interceptor.py；tests/unit/agents/test_tool_interceptor_fix.py。

#### 11. fix(checkpoint): clear in-memory store after successful persistence (#751)

- 提交：`[84c449c](https://github.com/bytedance/deer-flow/commit/84c449cf7945b27d82f41a80013691b682c29dc3)`
- 日期：2025-12-09
- 做了什么：修复缺陷或回归问题，主题是“clear in-memory store after successful persistence (#751)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+60 / -2 行。
- 关键文件：src/graph/checkpoint.py；tests/unit/checkpoint/test_memory_leak.py。

#### 12. fix: setup WindowsSelectorEventLoopPolicy in the first place #741 (#742)

- 提交：`[3bf4e1d](https://github.com/bytedance/deer-flow/commit/3bf4e1defb88373c5020b7ac10991ae69f77b5c4)`
- 日期：2025-12-06
- 做了什么：修复缺陷或回归问题，主题是“setup WindowsSelectorEventLoopPolicy in the first place #741 (#742)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+9 / -0 行。
- 关键文件：src/**init**.py。

#### 13. fix: passing the locale to create_react_agent (#745)

- 提交：`[3191e81](https://github.com/bytedance/deer-flow/commit/3191e819397a56a4827692535fd6ac8cd7a7ffba)`
- 日期：2025-12-06
- 做了什么：修复缺陷或回归问题，主题是“passing the locale to create_react_agent (#745)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+14 / -3 行。
- 关键文件：src/agents/agents.py；src/graph/nodes.py。

#### 14. fix: update Interrupt object attribute access for LangGraph 1.0+ (#730) (#731)

- 提交：`[c36ab39](https://github.com/bytedance/deer-flow/commit/c36ab393f1d1a878dcce0ef16fbeecd31f8ccaad)`
- 日期：2025-12-02
- 做了什么：修复缺陷或回归问题，主题是“update Interrupt object attribute access for LangGraph 1.0+ (#730) (#731)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+105 / -6 行。
- 关键文件：src/server/app.py；tests/unit/server/test_app.py。

## 2026-01

- 新功能/增强：356 条
- Bug 修复：117 条

### 新功能 / 增强

#### 1. feat: implement create skill

- 提交：`[bdd2e25](https://github.com/bytedance/deer-flow/commit/bdd2e25e1489f874ed153d715a0deb69250c8955)`
- 日期：2026-01-31
- 做了什么：新增或增强功能，主题是“implement create skill”。
- 影响范围：主要涉及 前端。
- 改动规模：+49 / -7 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/workspace/input-box.tsx；frontend/src/components/workspace/settings/settings-dialog.tsx；frontend/src/components/workspace/settings/skill-settings-page.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts；frontend/src/core/i18n/locales/zh-CN.ts。

#### 2. feat: implement create skill

- 提交：`[8639dde](https://github.com/bytedance/deer-flow/commit/8639dde3adfdbfd992e8b1d9fced98b7f104e48e)`
- 日期：2026-01-31
- 做了什么：新增或增强功能，主题是“implement create skill”。
- 影响范围：主要涉及 前端。
- 改动规模：+49 / -7 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/workspace/input-box.tsx；frontend/src/components/workspace/settings/settings-dialog.tsx；frontend/src/components/workspace/settings/skill-settings-page.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts；frontend/src/core/i18n/locales/zh-CN.ts。

#### 3. feat: implement create skill

- 提交：`[67ec116](https://github.com/bytedance/deer-flow/commit/67ec1162cb7a45667dc392cdcd794f499ed0a2a0)`
- 日期：2026-01-31
- 做了什么：新增或增强功能，主题是“implement create skill”。
- 影响范围：主要涉及 前端。
- 改动规模：+49 / -7 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/workspace/input-box.tsx；frontend/src/components/workspace/settings/settings-dialog.tsx；frontend/src/components/workspace/settings/skill-settings-page.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts；frontend/src/core/i18n/locales/zh-CN.ts。

#### 4. feat: add .skill file preview support

- 提交：`[06511f3](https://github.com/bytedance/deer-flow/commit/06511f38e1c208faf0aafd6b3a2e0734d31bb169)`
- 日期：2026-01-31
- 做了什么：新增或增强功能，主题是“add .skill file preview support”。
- 影响范围：主要涉及 前端、后端。
- 改动规模：+79 / -2 行。
- 关键文件：backend/src/gateway/routers/artifacts.py；frontend/src/components/workspace/artifacts/artifact-file-detail.tsx；frontend/src/core/artifacts/hooks.ts；frontend/src/core/artifacts/loader.ts。

#### 5. feat: add .skill file preview support

- 提交：`[f31258d](https://github.com/bytedance/deer-flow/commit/f31258dd1011d8e25513654c1f0f2c1ef54d18f6)`
- 日期：2026-01-31
- 做了什么：新增或增强功能，主题是“add .skill file preview support”。
- 影响范围：主要涉及 前端、后端。
- 改动规模：+79 / -2 行。
- 关键文件：backend/src/gateway/routers/artifacts.py；frontend/src/components/workspace/artifacts/artifact-file-detail.tsx；frontend/src/core/artifacts/hooks.ts；frontend/src/core/artifacts/loader.ts。

#### 6. feat: add .skill file preview support

- 提交：`[41f8b93](https://github.com/bytedance/deer-flow/commit/41f8b931c94ad0b6428c99a364b0711825414625)`
- 日期：2026-01-31
- 做了什么：新增或增强功能，主题是“add .skill file preview support”。
- 影响范围：主要涉及 前端、后端。
- 改动规模：+79 / -2 行。
- 关键文件：backend/src/gateway/routers/artifacts.py；frontend/src/components/workspace/artifacts/artifact-file-detail.tsx；frontend/src/core/artifacts/hooks.ts；frontend/src/core/artifacts/loader.ts。

#### 7. feat: add skill installation API endpoint

- 提交：`[a9e11f6](https://github.com/bytedance/deer-flow/commit/a9e11f63416b3158110fb15f0ae5db47653cc9d1)`
- 日期：2026-01-31
- 做了什么：新增或增强功能，主题是“add skill installation API endpoint”。
- 影响范围：主要涉及 前端、后端。
- 改动规模：+370 / -28 行。
- 关键文件：backend/src/gateway/routers/skills.py；frontend/src/components/workspace/artifacts/artifact-file-detail.tsx；frontend/src/components/workspace/artifacts/artifact-file-list.tsx；frontend/src/core/skills/api.ts。

#### 8. feat: add skill installation API endpoint

- 提交：`[624f758](https://github.com/bytedance/deer-flow/commit/624f758163b40f251172474482b5d122b3a2452e)`
- 日期：2026-01-31
- 做了什么：新增或增强功能，主题是“add skill installation API endpoint”。
- 影响范围：主要涉及 前端、后端。
- 改动规模：+370 / -28 行。
- 关键文件：backend/src/gateway/routers/skills.py；frontend/src/components/workspace/artifacts/artifact-file-detail.tsx；frontend/src/components/workspace/artifacts/artifact-file-list.tsx；frontend/src/core/skills/api.ts。

#### 9. feat: add skill installation API endpoint

- 提交：`[5834b15](https://github.com/bytedance/deer-flow/commit/5834b15af729d0b0318c5d59bdbf45934aebe31e)`
- 日期：2026-01-31
- 做了什么：新增或增强功能，主题是“add skill installation API endpoint”。
- 影响范围：主要涉及 前端、后端。
- 改动规模：+370 / -28 行。
- 关键文件：backend/src/gateway/routers/skills.py；frontend/src/components/workspace/artifacts/artifact-file-detail.tsx；frontend/src/components/workspace/artifacts/artifact-file-list.tsx；frontend/src/core/skills/api.ts。

#### 10. feat: preview the message if possible

- 提交：`[cf96132](https://github.com/bytedance/deer-flow/commit/cf961328a9a187416362d94e5b0e9e9759630c7b)`
- 日期：2026-01-31
- 做了什么：新增或增强功能，主题是“preview the message if possible”。
- 影响范围：主要涉及 前端。
- 改动规模：+18 / -2 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx。

#### 11. feat: preview the message if possible

- 提交：`[20a023e](https://github.com/bytedance/deer-flow/commit/20a023ee90ffbfbe5ed47ee3174b77989c2a25c8)`
- 日期：2026-01-31
- 做了什么：新增或增强功能，主题是“preview the message if possible”。
- 影响范围：主要涉及 前端。
- 改动规模：+18 / -2 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx。

#### 12. feat: preview the message if possible

- 提交：`[9c3b928](https://github.com/bytedance/deer-flow/commit/9c3b928f1de166a9404c2b958783d7445881e933)`
- 日期：2026-01-31
- 做了什么：新增或增强功能，主题是“preview the message if possible”。
- 影响范围：主要涉及 前端。
- 改动规模：+18 / -2 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx。

#### 13. feat: add notification

- 提交：`[5295f5b](https://github.com/bytedance/deer-flow/commit/5295f5b5b9296cdad66fd287f68ae98e29a9fb83)`
- 日期：2026-01-31
- 做了什么：新增或增强功能，主题是“add notification”。
- 影响范围：主要涉及 前端。
- 改动规模：+482 / -56 行。
- 关键文件：frontend/package.json；frontend/pnpm-lock.yaml；frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/ui/tabs.tsx；frontend/src/components/workspace/artifacts/artifact-file-detail.tsx；frontend/src/components/workspace/artifacts/artifact-file-list.tsx；frontend/src/components/workspace/settings/notification-settings-page.tsx；frontend/src/components/workspace/settings/settings-dialog.tsx。

#### 14. feat: add notification

- 提交：`[47fe2f8](https://github.com/bytedance/deer-flow/commit/47fe2f8195a0d1fc52d88bf304864edb2313fff4)`
- 日期：2026-01-31
- 做了什么：新增或增强功能，主题是“add notification”。
- 影响范围：主要涉及 前端。
- 改动规模：+482 / -56 行。
- 关键文件：frontend/package.json；frontend/pnpm-lock.yaml；frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/ui/tabs.tsx；frontend/src/components/workspace/artifacts/artifact-file-detail.tsx；frontend/src/components/workspace/artifacts/artifact-file-list.tsx；frontend/src/components/workspace/settings/notification-settings-page.tsx；frontend/src/components/workspace/settings/settings-dialog.tsx。

#### 15. feat: add notification

- 提交：`[c62caf9](https://github.com/bytedance/deer-flow/commit/c62caf95c4f7c5a492dd1a4351d574cc1d2f835a)`
- 日期：2026-01-31
- 做了什么：新增或增强功能，主题是“add notification”。
- 影响范围：主要涉及 前端。
- 改动规模：+482 / -56 行。
- 关键文件：frontend/package.json；frontend/pnpm-lock.yaml；frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/ui/tabs.tsx；frontend/src/components/workspace/artifacts/artifact-file-detail.tsx；frontend/src/components/workspace/artifacts/artifact-file-list.tsx；frontend/src/components/workspace/settings/notification-settings-page.tsx；frontend/src/components/workspace/settings/settings-dialog.tsx。

#### 16. feat: change email

- 提交：`[835fd4d](https://github.com/bytedance/deer-flow/commit/835fd4d0c78deae8587839496ea2fb14577ae153)`
- 日期：2026-01-30
- 做了什么：新增或增强功能，主题是“change email”。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -1 行。
- 关键文件：frontend/src/components/workspace/workspace-nav-menu.tsx。

#### 17. feat: change email

- 提交：`[cb660c2](https://github.com/bytedance/deer-flow/commit/cb660c264306b7cb2880a14f3c6a77aec8b0b7ba)`
- 日期：2026-01-30
- 做了什么：新增或增强功能，主题是“change email”。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -1 行。
- 关键文件：frontend/src/components/workspace/workspace-nav-menu.tsx。

#### 18. feat: change email

- 提交：`[4e0571f](https://github.com/bytedance/deer-flow/commit/4e0571f3b3b0eb48f84a2b583ac3ebb43130a402)`
- 日期：2026-01-30
- 做了什么：新增或增强功能，主题是“change email”。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -1 行。
- 关键文件：frontend/src/components/workspace/workspace-nav-menu.tsx。

#### 19. feat: support Github Flavored Markdown

- 提交：`[c1182c6](https://github.com/bytedance/deer-flow/commit/c1182c680cab9a2ee5e4c62cf53cc6c5103b7b73)`
- 日期：2026-01-30
- 做了什么：新增或增强功能，主题是“support Github Flavored Markdown”。
- 影响范围：主要涉及 前端。
- 改动规模：+108 / -30 行。
- 关键文件：frontend/package.json；frontend/pnpm-lock.yaml；frontend/src/components/workspace/artifacts/artifact-file-detail.tsx；frontend/src/components/workspace/messages/message-list-item.tsx；frontend/src/core/streamdown/index.ts；frontend/src/core/streamdown/plugins.ts。

#### 20. feat: support Github Flavored Markdown

- 提交：`[618b3e1](https://github.com/bytedance/deer-flow/commit/618b3e1e8f95e02c2b7bf8c8a2b137d13ed378ec)`
- 日期：2026-01-30
- 做了什么：新增或增强功能，主题是“support Github Flavored Markdown”。
- 影响范围：主要涉及 前端。
- 改动规模：+108 / -30 行。
- 关键文件：frontend/package.json；frontend/pnpm-lock.yaml；frontend/src/components/workspace/artifacts/artifact-file-detail.tsx；frontend/src/components/workspace/messages/message-list-item.tsx；frontend/src/core/streamdown/index.ts；frontend/src/core/streamdown/plugins.ts。

#### 21. feat: support Github Flavored Markdown

- 提交：`[1bb91bb](https://github.com/bytedance/deer-flow/commit/1bb91bb26791fc4a8013d92d92e0594c27bfb0ec)`
- 日期：2026-01-30
- 做了什么：新增或增强功能，主题是“support Github Flavored Markdown”。
- 影响范围：主要涉及 前端。
- 改动规模：+108 / -30 行。
- 关键文件：frontend/package.json；frontend/pnpm-lock.yaml；frontend/src/components/workspace/artifacts/artifact-file-detail.tsx；frontend/src/components/workspace/messages/message-list-item.tsx；frontend/src/core/streamdown/index.ts；frontend/src/core/streamdown/plugins.ts。

#### 22. feat: re-arrange icons

- 提交：`[4dffad8](https://github.com/bytedance/deer-flow/commit/4dffad89cae9932727c2085a478050987e3dc10f)`
- 日期：2026-01-29
- 做了什么：新增或增强功能，主题是“re-arrange icons”。
- 影响范围：主要涉及 前端。
- 改动规模：+36 / -23 行。
- 关键文件：frontend/src/components/workspace/input-box.tsx。

#### 23. feat: re-arrange icons

- 提交：`[cbcbbbe](https://github.com/bytedance/deer-flow/commit/cbcbbbe0a8f451a8417a4941db8c9f542256a3e6)`
- 日期：2026-01-29
- 做了什么：新增或增强功能，主题是“re-arrange icons”。
- 影响范围：主要涉及 前端。
- 改动规模：+36 / -23 行。
- 关键文件：frontend/src/components/workspace/input-box.tsx。

#### 24. feat: re-arrange icons

- 提交：`[939745d](https://github.com/bytedance/deer-flow/commit/939745d027cbbf2f4d83f2dbd27963be031a94c2)`
- 日期：2026-01-29
- 做了什么：新增或增强功能，主题是“re-arrange icons”。
- 影响范围：主要涉及 前端。
- 改动规模：+36 / -23 行。
- 关键文件：frontend/src/components/workspace/input-box.tsx。

#### 25. feat: display mode

- 提交：`[a135ddf](https://github.com/bytedance/deer-flow/commit/a135ddfa487568cc45ed8fc295a85a16d7f8de43)`
- 日期：2026-01-29
- 做了什么：新增或增强功能，主题是“display mode”。
- 影响范围：主要涉及 前端。
- 改动规模：+16 / -0 行。
- 关键文件：frontend/src/components/workspace/input-box.tsx。

#### 26. feat: display mode

- 提交：`[86ed750](https://github.com/bytedance/deer-flow/commit/86ed750a385d7658793ca0253b37dbc9952b16af)`
- 日期：2026-01-29
- 做了什么：新增或增强功能，主题是“display mode”。
- 影响范围：主要涉及 前端。
- 改动规模：+16 / -0 行。
- 关键文件：frontend/src/components/workspace/input-box.tsx。

#### 27. feat: display mode

- 提交：`[79955d2](https://github.com/bytedance/deer-flow/commit/79955d2e6c4883a3aa3840190a32372a0bd001ca)`
- 日期：2026-01-29
- 做了什么：新增或增强功能，主题是“display mode”。
- 影响范围：主要涉及 前端。
- 改动规模：+16 / -0 行。
- 关键文件：frontend/src/components/workspace/input-box.tsx。

#### 28. feat: use "mode" instead of "thinking_enabled" and "is_plan_mode"

- 提交：`[62ac3b6](https://github.com/bytedance/deer-flow/commit/62ac3b6b033417c38d46140d912825b5ca9ff16a)`
- 日期：2026-01-29
- 做了什么：新增或增强功能，主题是“use "mode" instead of "thinking_enabled" and "is_plan_mode"”。
- 影响范围：主要涉及 前端。
- 改动规模：+46 / -49 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/app/workspace/layout.tsx；frontend/src/components/workspace/input-box.tsx；frontend/src/core/settings/local.ts。

#### 29. feat: use "mode" instead of "thinking_enabled" and "is_plan_mode"

- 提交：`[7bf15cb](https://github.com/bytedance/deer-flow/commit/7bf15cb777dbc5de3ab3a74693d89fd65a823520)`
- 日期：2026-01-29
- 做了什么：新增或增强功能，主题是“use "mode" instead of "thinking_enabled" and "is_plan_mode"”。
- 影响范围：主要涉及 前端。
- 改动规模：+46 / -49 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/app/workspace/layout.tsx；frontend/src/components/workspace/input-box.tsx；frontend/src/core/settings/local.ts。

#### 30. feat: use "mode" instead of "thinking_enabled" and "is_plan_mode"

- 提交：`[98e08a8](https://github.com/bytedance/deer-flow/commit/98e08a85c9c28c639098dc215bb931b6c18067ed)`
- 日期：2026-01-29
- 做了什么：新增或增强功能，主题是“use "mode" instead of "thinking_enabled" and "is_plan_mode"”。
- 影响范围：主要涉及 前端。
- 改动规模：+46 / -49 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/app/workspace/layout.tsx；frontend/src/components/workspace/input-box.tsx；frontend/src/core/settings/local.ts。

#### 31. feat: add placeholder for image

- 提交：`[9d88943](https://github.com/bytedance/deer-flow/commit/9d889434c4cf920fe35dfb8d61f7c737fac48855)`
- 日期：2026-01-29
- 做了什么：新增或增强功能，主题是“add placeholder for image”。
- 影响范围：主要涉及 前端。
- 改动规模：+9 / -7 行。
- 关键文件：frontend/src/components/workspace/messages/message-group.tsx。

#### 32. feat: add placeholder for image

- 提交：`[4fc54a7](https://github.com/bytedance/deer-flow/commit/4fc54a740895958562a178c6129853e0a12b5691)`
- 日期：2026-01-29
- 做了什么：新增或增强功能，主题是“add placeholder for image”。
- 影响范围：主要涉及 前端。
- 改动规模：+9 / -7 行。
- 关键文件：frontend/src/components/workspace/messages/message-group.tsx。

#### 33. feat: add placeholder for image

- 提交：`[16a9626](https://github.com/bytedance/deer-flow/commit/16a9626d54a0a4d4fa508e7e29fa04f3ca22c335)`
- 日期：2026-01-29
- 做了什么：新增或增强功能，主题是“add placeholder for image”。
- 影响范围：主要涉及 前端。
- 改动规模：+9 / -7 行。
- 关键文件：frontend/src/components/workspace/messages/message-group.tsx。

#### 34. feat: optimize vision tools and image handling

- 提交：`[2c7a56d](https://github.com/bytedance/deer-flow/commit/2c7a56dd3345c782e8b87ba68d52d3729689fbc7)`
- 日期：2026-01-29
- 做了什么：新增或增强功能，主题是“optimize vision tools and image handling”。
- 影响范围：主要涉及 后端、配置、技能体系。
- 改动规模：+59 / -19 行。
- 关键文件：backend/src/agents/lead_agent/agent.py；backend/src/community/image_search/tools.py；backend/src/tools/tools.py；config.example.yaml；skills/public/image-generation/scripts/generate.py。

#### 35. feat: optimize vision tools and image handling

- 提交：`[314ea41](https://github.com/bytedance/deer-flow/commit/314ea4178132e65519eb0036e8367ea7256a719f)`
- 日期：2026-01-29
- 做了什么：新增或增强功能，主题是“optimize vision tools and image handling”。
- 影响范围：主要涉及 后端、配置、技能体系。
- 改动规模：+59 / -19 行。
- 关键文件：backend/src/agents/lead_agent/agent.py；backend/src/community/image_search/tools.py；backend/src/tools/tools.py；config.example.yaml；skills/public/image-generation/scripts/generate.py。

#### 36. feat: optimize vision tools and image handling

- 提交：`[7aa10b9](https://github.com/bytedance/deer-flow/commit/7aa10b980fbb94de1f786a3abfe8fe70ac12cfdd)`
- 日期：2026-01-29
- 做了什么：新增或增强功能，主题是“optimize vision tools and image handling”。
- 影响范围：主要涉及 后端、配置、技能体系。
- 改动规模：+59 / -19 行。
- 关键文件：backend/src/agents/lead_agent/agent.py；backend/src/community/image_search/tools.py；backend/src/tools/tools.py；config.example.yaml；skills/public/image-generation/scripts/generate.py。

#### 37. feat: add view_image tool and optimize web fetch tools

- 提交：`[09d9c18](https://github.com/bytedance/deer-flow/commit/09d9c18a28f677a8053d920a67b0b097c64fea6f)`
- 日期：2026-01-29
- 做了什么：新增或增强功能，主题是“add view_image tool and optimize web fetch tools”。
- 影响范围：主要涉及 后端、配置。
- 改动规模：+390 / -13 行。
- 关键文件：backend/src/agents/lead_agent/agent.py；backend/src/agents/middlewares/view_image_middleware.py；backend/src/agents/thread_state.py；backend/src/community/firecrawl/tools.py；backend/src/community/jina_ai/tools.py；backend/src/community/tavily/tools.py；backend/src/config/model_config.py；backend/src/models/factory.py。

#### 38. feat: add view_image tool and optimize web fetch tools

- 提交：`[7414947](https://github.com/bytedance/deer-flow/commit/7414947cc67f33615b7b91980a9b487f34a6456c)`
- 日期：2026-01-29
- 做了什么：新增或增强功能，主题是“add view_image tool and optimize web fetch tools”。
- 影响范围：主要涉及 后端、配置。
- 改动规模：+390 / -13 行。
- 关键文件：backend/src/agents/lead_agent/agent.py；backend/src/agents/middlewares/view_image_middleware.py；backend/src/agents/thread_state.py；backend/src/community/firecrawl/tools.py；backend/src/community/jina_ai/tools.py；backend/src/community/tavily/tools.py；backend/src/config/model_config.py；backend/src/models/factory.py。

#### 39. feat: add view_image tool and optimize web fetch tools

- 提交：`[9dc2405](https://github.com/bytedance/deer-flow/commit/9dc24055550b45445018814ce52584d29cd1c33e)`
- 日期：2026-01-29
- 做了什么：新增或增强功能，主题是“add view_image tool and optimize web fetch tools”。
- 影响范围：主要涉及 后端、配置。
- 改动规模：+390 / -13 行。
- 关键文件：backend/src/agents/lead_agent/agent.py；backend/src/agents/middlewares/view_image_middleware.py；backend/src/agents/thread_state.py；backend/src/community/firecrawl/tools.py；backend/src/community/jina_ai/tools.py；backend/src/community/tavily/tools.py；backend/src/config/model_config.py；backend/src/models/factory.py。

#### 40. merge: upstream/experimental with citations feature

- 提交：`[588673d](https://github.com/bytedance/deer-flow/commit/588673d0437d84a78183952bfa43ae18bd1e865d)`
- 日期：2026-01-29
- 做了什么：新增或增强功能，主题是“merge: upstream/experimental with citations feature”。
- 影响范围：主要涉及 后端、前端、技能体系。
- 改动规模：+771 / -112 行。
- 关键文件：backend/pyproject.toml；backend/src/agents/lead_agent/prompt.py；backend/src/agents/middlewares/clarification_middleware.py；backend/src/community/image_search/**init**.py；backend/src/community/image_search/tools.py；backend/src/config/sandbox_config.py；backend/src/gateway/routers/mcp.py；backend/src/models/patched_deepseek.py。

#### 41. merge: upstream/experimental with citations feature

- 提交：`[ac283b9](https://github.com/bytedance/deer-flow/commit/ac283b92aab233eba3240f1a3c4deb91cb4abfae)`
- 日期：2026-01-29
- 做了什么：新增或增强功能，主题是“merge: upstream/experimental with citations feature”。
- 影响范围：主要涉及 后端、前端、技能体系。
- 改动规模：+771 / -112 行。
- 关键文件：backend/pyproject.toml；backend/src/agents/lead_agent/prompt.py；backend/src/agents/middlewares/clarification_middleware.py；backend/src/community/image_search/**init**.py；backend/src/community/image_search/tools.py；backend/src/config/sandbox_config.py；backend/src/gateway/routers/mcp.py；backend/src/models/patched_deepseek.py。

#### 42. merge: upstream/experimental with citations feature

- 提交：`[5120022](https://github.com/bytedance/deer-flow/commit/5120022d6d1182be13980b6fdfabcc9851a449d0)`
- 日期：2026-01-29
- 做了什么：新增或增强功能，主题是“merge: upstream/experimental with citations feature”。
- 影响范围：主要涉及 后端、前端、技能体系。
- 改动规模：+771 / -112 行。
- 关键文件：backend/pyproject.toml；backend/src/agents/lead_agent/prompt.py；backend/src/agents/middlewares/clarification_middleware.py；backend/src/community/image_search/**init**.py；backend/src/community/image_search/tools.py；backend/src/config/sandbox_config.py；backend/src/gateway/routers/mcp.py；backend/src/models/patched_deepseek.py。

#### 43. feat: improve file upload message handling and UI

- 提交：`[849cc4d](https://github.com/bytedance/deer-flow/commit/849cc4d771e74938c7b8d919d3e193e6c425b087)`
- 日期：2026-01-29
- 做了什么：新增或增强功能，主题是“improve file upload message handling and UI”。
- 影响范围：主要涉及 前端、后端。
- 改动规模：+102 / -3 行。
- 关键文件：backend/src/agents/middlewares/uploads_middleware.py；frontend/src/components/workspace/messages/message-list-item.tsx；frontend/src/core/threads/hooks.ts。

#### 44. feat: improve file upload message handling and UI

- 提交：`[ce9731c](https://github.com/bytedance/deer-flow/commit/ce9731c10a77a543c7dc58ec88ad41cf89e7857c)`
- 日期：2026-01-29
- 做了什么：新增或增强功能，主题是“improve file upload message handling and UI”。
- 影响范围：主要涉及 前端、后端。
- 改动规模：+102 / -3 行。
- 关键文件：backend/src/agents/middlewares/uploads_middleware.py；frontend/src/components/workspace/messages/message-list-item.tsx；frontend/src/core/threads/hooks.ts。

#### 45. feat: improve file upload message handling and UI

- 提交：`[3413975](https://github.com/bytedance/deer-flow/commit/341397562a82aedd966977ea2131f880949e7ef3)`
- 日期：2026-01-29
- 做了什么：新增或增强功能，主题是“improve file upload message handling and UI”。
- 影响范围：主要涉及 前端、后端。
- 改动规模：+102 / -3 行。
- 关键文件：backend/src/agents/middlewares/uploads_middleware.py；frontend/src/components/workspace/messages/message-list-item.tsx；frontend/src/core/threads/hooks.ts。

#### 46. feat: enable images in content

- 提交：`[eff241f](https://github.com/bytedance/deer-flow/commit/eff241f9f281f3c55dd0d415d2026884af1fe791)`
- 日期：2026-01-29
- 做了什么：新增或增强功能，主题是“enable images in content”。
- 影响范围：主要涉及 前端、后端。
- 改动规模：+3 / -3 行。
- 关键文件：backend/src/agents/lead_agent/prompt.py；frontend/src/components/workspace/messages/message-group.tsx；frontend/src/components/workspace/messages/message-list-item.tsx。

#### 47. feat: enable images in content

- 提交：`[f809b67](https://github.com/bytedance/deer-flow/commit/f809b67c47594d1e9d7f2caa8517036730435fd7)`
- 日期：2026-01-29
- 做了什么：新增或增强功能，主题是“enable images in content”。
- 影响范围：主要涉及 前端、后端。
- 改动规模：+3 / -3 行。
- 关键文件：backend/src/agents/lead_agent/prompt.py；frontend/src/components/workspace/messages/message-group.tsx；frontend/src/components/workspace/messages/message-list-item.tsx。

#### 48. feat: refine citations format and improve content presentation

- 提交：`[c14378a](https://github.com/bytedance/deer-flow/commit/c14378a312c3b616c3866e34a8aa85ad77ec706a)`
- 日期：2026-01-29
- 做了什么：新增或增强功能，主题是“refine citations format and improve content presentation”。
- 影响范围：主要涉及 前端、后端。
- 改动规模：+515 / -185 行。
- 关键文件：backend/src/agents/lead_agent/prompt.py；backend/src/agents/middlewares/uploads_middleware.py；backend/src/gateway/routers/artifacts.py；frontend/package.json；frontend/pnpm-lock.yaml；frontend/src/components/workspace/artifacts/artifact-file-detail.tsx；frontend/src/components/workspace/messages/message-list-item.tsx；frontend/src/core/citations/utils.ts。

#### 49. feat: refine citations format and improve content presentation

- 提交：`[4b63e70](https://github.com/bytedance/deer-flow/commit/4b63e70b7ee7bd292a597585a4aaa819259bcb92)`
- 日期：2026-01-29
- 做了什么：新增或增强功能，主题是“refine citations format and improve content presentation”。
- 影响范围：主要涉及 前端、后端。
- 改动规模：+515 / -185 行。
- 关键文件：backend/src/agents/lead_agent/prompt.py；backend/src/agents/middlewares/uploads_middleware.py；backend/src/gateway/routers/artifacts.py；frontend/package.json；frontend/pnpm-lock.yaml；frontend/src/components/workspace/artifacts/artifact-file-detail.tsx；frontend/src/components/workspace/messages/message-list-item.tsx；frontend/src/core/citations/utils.ts。

#### 50. feat: refine citations format and improve content presentation

- 提交：`[e8a8b5e](https://github.com/bytedance/deer-flow/commit/e8a8b5e56b13970c1a2c0c66875c1c4826aac69f)`
- 日期：2026-01-29
- 做了什么：新增或增强功能，主题是“refine citations format and improve content presentation”。
- 影响范围：主要涉及 前端、后端。
- 改动规模：+515 / -185 行。
- 关键文件：backend/src/agents/lead_agent/prompt.py；backend/src/agents/middlewares/uploads_middleware.py；backend/src/gateway/routers/artifacts.py；frontend/package.json；frontend/pnpm-lock.yaml；frontend/src/components/workspace/artifacts/artifact-file-detail.tsx；frontend/src/components/workspace/messages/message-list-item.tsx；frontend/src/core/citations/utils.ts。

#### 51. feat: add tooltips

- 提交：`[6b030d7](https://github.com/bytedance/deer-flow/commit/6b030d75897eda9b5a680851e2901780d3c59fe7)`
- 日期：2026-01-29
- 做了什么：新增或增强功能，主题是“add tooltips”。
- 影响范围：主要涉及 前端。
- 改动规模：+18 / -15 行。
- 关键文件：frontend/src/components/workspace/messages/message-group.tsx。

#### 52. feat: add tooltips

- 提交：`[e4d3735](https://github.com/bytedance/deer-flow/commit/e4d373541f9f6a0d800cbe960eb954405289735e)`
- 日期：2026-01-29
- 做了什么：新增或增强功能，主题是“add tooltips”。
- 影响范围：主要涉及 前端。
- 改动规模：+18 / -15 行。
- 关键文件：frontend/src/components/workspace/messages/message-group.tsx。

#### 53. feat: enhance search_image

- 提交：`[c700bd6](https://github.com/bytedance/deer-flow/commit/c700bd6841cdd74ae882e3870470dafa26a4786d)`
- 日期：2026-01-29
- 做了什么：新增或增强功能，主题是“enhance search_image”。
- 影响范围：主要涉及 前端。
- 改动规模：+23 / -8 行。
- 关键文件：frontend/src/components/workspace/messages/message-group.tsx。

#### 54. feat: enhance search_image

- 提交：`[f7ec116](https://github.com/bytedance/deer-flow/commit/f7ec116c263a905a66c9ad6dec7348b445bee486)`
- 日期：2026-01-29
- 做了什么：新增或增强功能，主题是“enhance search_image”。
- 影响范围：主要涉及 前端。
- 改动规模：+23 / -8 行。
- 关键文件：frontend/src/components/workspace/messages/message-group.tsx。

#### 55. feat: support image_search

- 提交：`[8359d84](https://github.com/bytedance/deer-flow/commit/8359d842b56d009a3d9db9bb0494ced41a25011e)`
- 日期：2026-01-29
- 做了什么：新增或增强功能，主题是“support image_search”。
- 影响范围：主要涉及 前端。
- 改动规模：+33 / -0 行。
- 关键文件：frontend/src/components/workspace/messages/message-group.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts；frontend/src/core/i18n/locales/zh-CN.ts。

#### 56. feat: support image_search

- 提交：`[d787b1c](https://github.com/bytedance/deer-flow/commit/d787b1ca5405fbb4360e494957bc1d131461eb8e)`
- 日期：2026-01-29
- 做了什么：新增或增强功能，主题是“support image_search”。
- 影响范围：主要涉及 前端。
- 改动规模：+33 / -0 行。
- 关键文件：frontend/src/components/workspace/messages/message-group.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts；frontend/src/core/i18n/locales/zh-CN.ts。

#### 57. feat: add image search builtin tool

- 提交：`[1926c58](https://github.com/bytedance/deer-flow/commit/1926c58cf28926c6b75ac76fe2c9acf3a2ef4e0a)`
- 日期：2026-01-29
- 做了什么：新增或增强功能，主题是“add image search builtin tool”。
- 影响范围：主要涉及 后端、配置、技能体系。
- 改动规模：+311 / -17 行。
- 关键文件：backend/pyproject.toml；backend/src/community/image_search/**init**.py；backend/src/community/image_search/tools.py；backend/src/config/sandbox_config.py；backend/src/gateway/routers/mcp.py；backend/src/models/patched_deepseek.py；backend/uv.lock；config.example.yaml。

#### 58. feat: add image search builtin tool

- 提交：`[5e62471](https://github.com/bytedance/deer-flow/commit/5e624713123f3ecdf64f423e1fd0597c08904cc5)`
- 日期：2026-01-29
- 做了什么：新增或增强功能，主题是“add image search builtin tool”。
- 影响范围：主要涉及 后端、配置、技能体系。
- 改动规模：+311 / -17 行。
- 关键文件：backend/pyproject.toml；backend/src/community/image_search/**init**.py；backend/src/community/image_search/tools.py；backend/src/config/sandbox_config.py；backend/src/gateway/routers/mcp.py；backend/src/models/patched_deepseek.py；backend/uv.lock；config.example.yaml。

#### 59. feat: modernize PPT styles and add deep-research skill

- 提交：`[248ffe6](https://github.com/bytedance/deer-flow/commit/248ffe61bcc74d5bc5f3e75ba75463efd62f160d)`
- 日期：2026-01-29
- 做了什么：新增或增强功能，主题是“modernize PPT styles and add deep-research skill”。
- 影响范围：主要涉及 技能体系。
- 改动规模：+361 / -80 行。
- 关键文件：skills/public/deep-research/SKILL.md；skills/public/ppt-generation/SKILL.md。

#### 60. feat: modernize PPT styles and add deep-research skill

- 提交：`[af18df4](https://github.com/bytedance/deer-flow/commit/af18df480b6eb015be404f19042b2d2bb5314507)`
- 日期：2026-01-29
- 做了什么：新增或增强功能，主题是“modernize PPT styles and add deep-research skill”。
- 影响范围：主要涉及 技能体系。
- 改动规模：+361 / -80 行。
- 关键文件：skills/public/deep-research/SKILL.md；skills/public/ppt-generation/SKILL.md。

#### 61. feat: display ask_clarification tool messages directly in frontend

- 提交：`[d4bfed2](https://github.com/bytedance/deer-flow/commit/d4bfed271b151fa9e65df1a6bdc55bd61fb4a3e1)`
- 日期：2026-01-29
- 做了什么：新增或增强功能，主题是“display ask_clarification tool messages directly in frontend”。
- 影响范围：主要涉及 前端、后端。
- 改动规模：+44 / -12 行。
- 关键文件：backend/src/agents/middlewares/clarification_middleware.py；frontend/src/components/workspace/messages/message-list.tsx；frontend/src/core/messages/utils.ts。

#### 62. feat: display ask_clarification tool messages directly in frontend

- 提交：`[73a1d32](https://github.com/bytedance/deer-flow/commit/73a1d32a5b43686d3ecbb0d75ba8af0246907710)`
- 日期：2026-01-29
- 做了什么：新增或增强功能，主题是“display ask_clarification tool messages directly in frontend”。
- 影响范围：主要涉及 前端、后端。
- 改动规模：+44 / -12 行。
- 关键文件：backend/src/agents/middlewares/clarification_middleware.py；frontend/src/components/workspace/messages/message-list.tsx；frontend/src/core/messages/utils.ts。

#### 63. feat: add inline citations and thread management features

- 提交：`[ad85b72](https://github.com/bytedance/deer-flow/commit/ad85b720644dd3e5bddac1abb671fdf1878cbc38)`
- 日期：2026-01-28
- 做了什么：新增或增强功能，主题是“add inline citations and thread management features”。
- 影响范围：主要涉及 前端、后端。
- 改动规模：+658 / -66 行。
- 关键文件：backend/src/agents/lead_agent/prompt.py；frontend/src/components/workspace/artifacts/artifact-file-detail.tsx；frontend/src/components/workspace/messages/message-list-item.tsx；frontend/src/components/workspace/recent-chat-list.tsx；frontend/src/core/citations/index.ts；frontend/src/core/citations/utils.ts；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts。

#### 64. feat: add inline citations and thread management features

- 提交：`[33c47e0](https://github.com/bytedance/deer-flow/commit/33c47e0c56e4e93b5d10e58383122886e80e314a)`
- 日期：2026-01-28
- 做了什么：新增或增强功能，主题是“add inline citations and thread management features”。
- 影响范围：主要涉及 前端、后端。
- 改动规模：+658 / -66 行。
- 关键文件：backend/src/agents/lead_agent/prompt.py；frontend/src/components/workspace/artifacts/artifact-file-detail.tsx；frontend/src/components/workspace/messages/message-list-item.tsx；frontend/src/components/workspace/recent-chat-list.tsx；frontend/src/core/citations/index.ts；frontend/src/core/citations/utils.ts；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts。

#### 65. feat: add inline citations and thread management features

- 提交：`[f8d2d88](https://github.com/bytedance/deer-flow/commit/f8d2d887272d68698e9558e7b49526723643f63d)`
- 日期：2026-01-28
- 做了什么：新增或增强功能，主题是“add inline citations and thread management features”。
- 影响范围：主要涉及 前端、后端。
- 改动规模：+658 / -66 行。
- 关键文件：backend/src/agents/lead_agent/prompt.py；frontend/src/components/workspace/artifacts/artifact-file-detail.tsx；frontend/src/components/workspace/messages/message-list-item.tsx；frontend/src/components/workspace/recent-chat-list.tsx；frontend/src/core/citations/index.ts；frontend/src/core/citations/utils.ts；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts。

#### 66. feat: update notes

- 提交：`[a010953](https://github.com/bytedance/deer-flow/commit/a010953880e97807c2282e4fb3d359325d62fad2)`
- 日期：2026-01-28
- 做了什么：新增或增强功能，主题是“update notes”。
- 影响范围：主要涉及 后端。
- 改动规模：+1 / -1 行。
- 关键文件：backend/src/tools/builtins/present_file_tool.py。

#### 67. feat: update notes

- 提交：`[453efa1](https://github.com/bytedance/deer-flow/commit/453efa1a1d513553869212defd2c96cde87eee23)`
- 日期：2026-01-28
- 做了什么：新增或增强功能，主题是“update notes”。
- 影响范围：主要涉及 后端。
- 改动规模：+1 / -1 行。
- 关键文件：backend/src/tools/builtins/present_file_tool.py。

#### 68. feat: update a new demo

- 提交：`[dd2c201](https://github.com/bytedance/deer-flow/commit/dd2c2011f153b953f95ac78f2f37cc4b61198eb8)`
- 日期：2026-01-28
- 做了什么：新增或增强功能，主题是“update a new demo”。
- 影响范围：主要涉及 前端。
- 改动规模：+1725 / -0 行。
- 关键文件：frontend/public/demo/threads/b83fbb2a-4e36-4d82-9de0-7b2a02c2092a/thread.json；frontend/public/demo/threads/b83fbb2a-4e36-4d82-9de0-7b2a02c2092a/user-data/outputs/caren-hero.jpg；frontend/public/demo/threads/b83fbb2a-4e36-4d82-9de0-7b2a02c2092a/user-data/outputs/caren-ingredients.jpg；frontend/public/demo/threads/b83fbb2a-4e36-4d82-9de0-7b2a02c2092a/user-data/outputs/caren-lifestyle.jpg；frontend/public/demo/threads/b83fbb2a-4e36-4d82-9de0-7b2a02c2092a/user-data/outputs/caren-products.jpg；frontend/public/demo/threads/b83fbb2a-4e36-4d82-9de0-7b2a02c2092a/user-data/outputs/index.html。

#### 69. feat: update a new demo

- 提交：`[c0980bf](https://github.com/bytedance/deer-flow/commit/c0980bfa82e443cd699752f6e0f3765ba0850afe)`
- 日期：2026-01-28
- 做了什么：新增或增强功能，主题是“update a new demo”。
- 影响范围：主要涉及 前端。
- 改动规模：+1725 / -0 行。
- 关键文件：frontend/public/demo/threads/b83fbb2a-4e36-4d82-9de0-7b2a02c2092a/thread.json；frontend/public/demo/threads/b83fbb2a-4e36-4d82-9de0-7b2a02c2092a/user-data/outputs/caren-hero.jpg；frontend/public/demo/threads/b83fbb2a-4e36-4d82-9de0-7b2a02c2092a/user-data/outputs/caren-ingredients.jpg；frontend/public/demo/threads/b83fbb2a-4e36-4d82-9de0-7b2a02c2092a/user-data/outputs/caren-lifestyle.jpg；frontend/public/demo/threads/b83fbb2a-4e36-4d82-9de0-7b2a02c2092a/user-data/outputs/caren-products.jpg；frontend/public/demo/threads/b83fbb2a-4e36-4d82-9de0-7b2a02c2092a/user-data/outputs/index.html。

#### 70. feat: modify the config example yaml

- 提交：`[49f6c00](https://github.com/bytedance/deer-flow/commit/49f6c001c3b39f7a04293c103df764740087ba48)`
- 日期：2026-01-28
- 做了什么：新增或增强功能，主题是“modify the config example yaml”。
- 影响范围：主要涉及 配置。
- 改动规模：+4 / -3 行。
- 关键文件：config.example.yaml。

#### 71. feat: modify the config example yaml

- 提交：`[055ab1f](https://github.com/bytedance/deer-flow/commit/055ab1fb040ee3643fbd92b8a3797bcce2949a17)`
- 日期：2026-01-28
- 做了什么：新增或增强功能，主题是“modify the config example yaml”。
- 影响范围：主要涉及 配置。
- 改动规模：+4 / -3 行。
- 关键文件：config.example.yaml。

#### 72. feat: add Leica demo

- 提交：`[d84a34b](https://github.com/bytedance/deer-flow/commit/d84a34b7cdfe6e37f6f00fee1107d8597e296c5f)`
- 日期：2026-01-28
- 做了什么：新增或增强功能，主题是“add Leica demo”。
- 影响范围：主要涉及 前端。
- 改动规模：+1195 / -0 行。
- 关键文件：frontend/public/demo/threads/7f9dc56c-e49c-4671-a3d2-c492ff4dce0c/thread.json；frontend/public/demo/threads/7f9dc56c-e49c-4671-a3d2-c492ff4dce0c/user-data/outputs/leica-master-photography-article.md；frontend/public/demo/threads/7f9dc56c-e49c-4671-a3d2-c492ff4dce0c/user-data/outputs/leica-nyc-candid.jpg；frontend/public/demo/threads/7f9dc56c-e49c-4671-a3d2-c492ff4dce0c/user-data/outputs/leica-paris-decisive-moment.jpg；frontend/public/demo/threads/7f9dc56c-e49c-4671-a3d2-c492ff4dce0c/user-data/outputs/leica-tokyo-night.jpg。

#### 73. feat: add Leica demo

- 提交：`[486a06d](https://github.com/bytedance/deer-flow/commit/486a06d772da2cf66d354c20c25c01c09d8bdf95)`
- 日期：2026-01-28
- 做了什么：新增或增强功能，主题是“add Leica demo”。
- 影响范围：主要涉及 前端。
- 改动规模：+1195 / -0 行。
- 关键文件：frontend/public/demo/threads/7f9dc56c-e49c-4671-a3d2-c492ff4dce0c/thread.json；frontend/public/demo/threads/7f9dc56c-e49c-4671-a3d2-c492ff4dce0c/user-data/outputs/leica-master-photography-article.md；frontend/public/demo/threads/7f9dc56c-e49c-4671-a3d2-c492ff4dce0c/user-data/outputs/leica-nyc-candid.jpg；frontend/public/demo/threads/7f9dc56c-e49c-4671-a3d2-c492ff4dce0c/user-data/outputs/leica-paris-decisive-moment.jpg；frontend/public/demo/threads/7f9dc56c-e49c-4671-a3d2-c492ff4dce0c/user-data/outputs/leica-tokyo-night.jpg。

#### 74. feat: fallback to error reporting

- 提交：`[d075e7a](https://github.com/bytedance/deer-flow/commit/d075e7a234345e3c5189ca928340a6e143c2dc90)`
- 日期：2026-01-28
- 做了什么：新增或增强功能，主题是“fallback to error reporting”。
- 影响范围：主要涉及 后端。
- 改动规模：+31 / -25 行。
- 关键文件：backend/src/community/firecrawl/tools.py。

#### 75. feat: fallback to error reporting

- 提交：`[5980bbd](https://github.com/bytedance/deer-flow/commit/5980bbde023062a35cdb8ac25917ed0dace76739)`
- 日期：2026-01-28
- 做了什么：新增或增强功能，主题是“fallback to error reporting”。
- 影响范围：主要涉及 后端。
- 改动规模：+31 / -25 行。
- 关键文件：backend/src/community/firecrawl/tools.py。

#### 76. feat: add another Kimi K2.5 demo

- 提交：`[a249b71](https://github.com/bytedance/deer-flow/commit/a249b7178a32eff9ff569ac27e9858a058e2a36f)`
- 日期：2026-01-28
- 做了什么：新增或增强功能，主题是“add another Kimi K2.5 demo”。
- 影响范围：主要涉及 前端。
- 改动规模：+1109 / -0 行。
- 关键文件：frontend/public/demo/threads/f4125791-0128-402a-8ca9-50e0947557e4/thread.json；frontend/public/demo/threads/f4125791-0128-402a-8ca9-50e0947557e4/user-data/outputs/index.html。

#### 77. feat: add another Kimi K2.5 demo

- 提交：`[5d5aec4](https://github.com/bytedance/deer-flow/commit/5d5aec43d31f9f3be7c7ba02749fd0abc5e3246b)`
- 日期：2026-01-28
- 做了什么：新增或增强功能，主题是“add another Kimi K2.5 demo”。
- 影响范围：主要涉及 前端。
- 改动规模：+1109 / -0 行。
- 关键文件：frontend/public/demo/threads/f4125791-0128-402a-8ca9-50e0947557e4/thread.json；frontend/public/demo/threads/f4125791-0128-402a-8ca9-50e0947557e4/user-data/outputs/index.html。

#### 78. feat: add kimi-k2.5 demo with vercel deployment

- 提交：`[e2bcc70](https://github.com/bytedance/deer-flow/commit/e2bcc70a8436eb9411999e2e32550d26ee522db8)`
- 日期：2026-01-28
- 做了什么：新增或增强功能，主题是“add kimi-k2.5 demo with vercel deployment”。
- 影响范围：主要涉及 前端。
- 改动规模：+2088 / -0 行。
- 关键文件：frontend/public/demo/threads/c02bb4d5-4202-490e-ae8f-ff4864fc0d2e/thread.json；frontend/public/demo/threads/c02bb4d5-4202-490e-ae8f-ff4864fc0d2e/user-data/outputs/index.html；frontend/public/demo/threads/c02bb4d5-4202-490e-ae8f-ff4864fc0d2e/user-data/outputs/script.js；frontend/public/demo/threads/c02bb4d5-4202-490e-ae8f-ff4864fc0d2e/user-data/outputs/styles.css。

#### 79. feat: add kimi-k2.5 demo with vercel deployment

- 提交：`[ade5426](https://github.com/bytedance/deer-flow/commit/ade5426d9e05cb59b867c2ad0766834668ed6fc4)`
- 日期：2026-01-28
- 做了什么：新增或增强功能，主题是“add kimi-k2.5 demo with vercel deployment”。
- 影响范围：主要涉及 前端。
- 改动规模：+2088 / -0 行。
- 关键文件：frontend/public/demo/threads/c02bb4d5-4202-490e-ae8f-ff4864fc0d2e/thread.json；frontend/public/demo/threads/c02bb4d5-4202-490e-ae8f-ff4864fc0d2e/user-data/outputs/index.html；frontend/public/demo/threads/c02bb4d5-4202-490e-ae8f-ff4864fc0d2e/user-data/outputs/script.js；frontend/public/demo/threads/c02bb4d5-4202-490e-ae8f-ff4864fc0d2e/user-data/outputs/styles.css。

#### 80. feat: fallback to textarea when loading

- 提交：`[dab4093](https://github.com/bytedance/deer-flow/commit/dab4093103aa4798670f263ab9588142b142cca0)`
- 日期：2026-01-28
- 做了什么：新增或增强功能，主题是“fallback to textarea when loading”。
- 影响范围：主要涉及 前端。
- 改动规模：+43 / -25 行。
- 关键文件：frontend/src/components/workspace/code-editor.tsx。

#### 81. feat: fallback to textarea when loading

- 提交：`[86c8f1a](https://github.com/bytedance/deer-flow/commit/86c8f1a25eccc9e6dd733a7ca75c1af4796c492c)`
- 日期：2026-01-28
- 做了什么：新增或增强功能，主题是“fallback to textarea when loading”。
- 影响范围：主要涉及 前端。
- 改动规模：+43 / -25 行。
- 关键文件：frontend/src/components/workspace/code-editor.tsx。

#### 82. feat: add scroll indicator

- 提交：`[28361ca](https://github.com/bytedance/deer-flow/commit/28361ca03cb7d732ddc1079df5959ff13a20cb22)`
- 日期：2026-01-27
- 做了什么：新增或增强功能，主题是“add scroll indicator”。
- 影响范围：主要涉及 前端。
- 改动规模：+5 / -5 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/ai-elements/conversation.tsx。

#### 83. feat: add scroll indicator

- 提交：`[7c42fa5](https://github.com/bytedance/deer-flow/commit/7c42fa516285fc4e764fb9d37ab6ed912f8e5613)`
- 日期：2026-01-27
- 做了什么：新增或增强功能，主题是“add scroll indicator”。
- 影响范围：主要涉及 前端。
- 改动规模：+5 / -5 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/ai-elements/conversation.tsx。

#### 84. feat: Generate a fallback report upon recursion limit hit (#838)

- 提交：`[ee02b9f](https://github.com/bytedance/deer-flow/commit/ee02b9f637aa859943b9ef45bb25e0b0f1bf0a0b)`
- 日期：2026-01-26
- 做了什么：新增或增强功能，主题是“Generate a fallback report upon recursion limit hit (#838)”。
- 影响范围：主要涉及 其他模块、文档。
- 改动规模：+895 / -12 行。
- 关键文件：docs/configuration_guide.md；src/config/configuration.py；src/graph/nodes.py；src/prompts/recursion_fallback.md；src/prompts/template.py；tests/integration/test_nodes.py；tests/unit/graph/test_nodes_recursion_limit.py。

#### 85. feat: add firecrawl community package with web_search and web_fetch tools

- 提交：`[b8c33e3](https://github.com/bytedance/deer-flow/commit/b8c33e342b08315237ef5e5cd42ea17dfe822292)`
- 日期：2026-01-26
- 做了什么：新增或增强功能，主题是“add firecrawl community package with web_search and web_fetch tools”。
- 影响范围：主要涉及 后端、其他模块。
- 改动规模：+571 / -0 行。
- 关键文件：.env.example；backend/pyproject.toml；backend/src/community/firecrawl/tools.py；backend/uv.lock。

#### 86. feat: add firecrawl community package with web_search and web_fetch tools

- 提交：`[ce7f725](https://github.com/bytedance/deer-flow/commit/ce7f7258ba119442161de46d5a2a44ea30bc78ec)`
- 日期：2026-01-26
- 做了什么：新增或增强功能，主题是“add firecrawl community package with web_search and web_fetch tools”。
- 影响范围：主要涉及 后端、其他模块。
- 改动规模：+571 / -0 行。
- 关键文件：.env.example；backend/pyproject.toml；backend/src/community/firecrawl/tools.py；backend/uv.lock。

#### 87. feat: add ppt-generation skill

- 提交：`[9215c9c](https://github.com/bytedance/deer-flow/commit/9215c9cce7a81e26b7750bfd8663f96cb023cdf7)`
- 日期：2026-01-26
- 做了什么：新增或增强功能，主题是“add ppt-generation skill”。
- 影响范围：主要涉及 技能体系。
- 改动规模：+511 / -0 行。
- 关键文件：skills/public/ppt-generation/SKILL.md；skills/public/ppt-generation/scripts/generate.py。

#### 88. feat: add ppt-generation skill

- 提交：`[0cc7cc0](https://github.com/bytedance/deer-flow/commit/0cc7cc08e91243b3f11a30f27fe5aab11c247f22)`
- 日期：2026-01-26
- 做了什么：新增或增强功能，主题是“add ppt-generation skill”。
- 影响范围：主要涉及 技能体系。
- 改动规模：+511 / -0 行。
- 关键文件：skills/public/ppt-generation/SKILL.md；skills/public/ppt-generation/scripts/generate.py。

#### 89. feat: auto select the first model as default model

- 提交：`[3ce4968](https://github.com/bytedance/deer-flow/commit/3ce4968e95cf0e0c8ace2ca0e6282a66fc7cd98f)`
- 日期：2026-01-26
- 做了什么：新增或增强功能，主题是“auto select the first model as default model”。
- 影响范围：主要涉及 前端。
- 改动规模：+17 / -8 行。
- 关键文件：frontend/src/components/workspace/input-box.tsx；frontend/src/core/models/hooks.ts；frontend/src/core/settings/local.ts；frontend/src/core/threads/types.ts。

#### 90. feat: auto select the first model as default model

- 提交：`[574dfd2](https://github.com/bytedance/deer-flow/commit/574dfd2b054c2d4854147f54cf181ed793ff5b2c)`
- 日期：2026-01-26
- 做了什么：新增或增强功能，主题是“auto select the first model as default model”。
- 影响范围：主要涉及 前端。
- 改动规模：+17 / -8 行。
- 关键文件：frontend/src/components/workspace/input-box.tsx；frontend/src/core/models/hooks.ts；frontend/src/core/settings/local.ts；frontend/src/core/threads/types.ts。

#### 91. feat: add podcast generation skill

- 提交：`[9f5658f](https://github.com/bytedance/deer-flow/commit/9f5658fa0e2f4ab0b017eb73d708c7bda60642f3)`
- 日期：2026-01-25
- 做了什么：新增或增强功能，主题是“add podcast generation skill”。
- 影响范围：主要涉及 技能体系、其他模块、后端。
- 改动规模：+542 / -1 行。
- 关键文件：.gitignore；backend/src/sandbox/local/local_sandbox.py；skills/public/podcast-generation/SKILL.md；skills/public/podcast-generation/scripts/generate.py；skills/public/podcast-generation/templates/tech-explainer.md。

#### 92. feat: add podcast generation skill

- 提交：`[3fa1646](https://github.com/bytedance/deer-flow/commit/3fa16467a25c690c8e5844ee93178e40efca15d5)`
- 日期：2026-01-25
- 做了什么：新增或增强功能，主题是“add podcast generation skill”。
- 影响范围：主要涉及 技能体系、其他模块、后端。
- 改动规模：+542 / -1 行。
- 关键文件：.gitignore；backend/src/sandbox/local/local_sandbox.py；skills/public/podcast-generation/SKILL.md；skills/public/podcast-generation/scripts/generate.py；skills/public/podcast-generation/templates/tech-explainer.md。

#### 93. feat: adjust button

- 提交：`[f629e13](https://github.com/bytedance/deer-flow/commit/f629e134d4e28a70dbdeb1d8e7a3326fb2ef9e9e)`
- 日期：2026-01-25
- 做了什么：新增或增强功能，主题是“adjust button”。
- 影响范围：主要涉及 前端。
- 改动规模：+17 / -13 行。
- 关键文件：frontend/src/components/landing/progressive-skills-animation.tsx。

#### 94. feat: adjust button

- 提交：`[044e38a](https://github.com/bytedance/deer-flow/commit/044e38aec65a9b67e59c6e11f9e398c7762ec66d)`
- 日期：2026-01-25
- 做了什么：新增或增强功能，主题是“adjust button”。
- 影响范围：主要涉及 前端。
- 改动规模：+17 / -13 行。
- 关键文件：frontend/src/components/landing/progressive-skills-animation.tsx。

#### 95. feat: add image and video generation skills

- 提交：`[ae0e7de](https://github.com/bytedance/deer-flow/commit/ae0e7de3b71f70e0754eeafd8353329a37837ddc)`
- 日期：2026-01-25
- 做了什么：新增或增强功能，主题是“add image and video generation skills”。
- 影响范围：主要涉及 技能体系。
- 改动规模：+630 / -169 行。
- 关键文件：skills/public/doraemon-comic-aigc/SKILL.md；skills/public/doraemon-comic-aigc/scripts/generate.py；skills/public/image-generation/SKILL.md；skills/public/image-generation/scripts/generate.py；skills/public/image-generation/templates/doraemon.md；skills/public/video-generation/SKILL.md；skills/public/video-generation/scripts/generate.py。

#### 96. feat: add image and video generation skills

- 提交：`[b53a2ea](https://github.com/bytedance/deer-flow/commit/b53a2ea5e1301fcf4e9a104db3724c6b09a66b27)`
- 日期：2026-01-25
- 做了什么：新增或增强功能，主题是“add image and video generation skills”。
- 影响范围：主要涉及 技能体系。
- 改动规模：+630 / -169 行。
- 关键文件：skills/public/doraemon-comic-aigc/SKILL.md；skills/public/doraemon-comic-aigc/scripts/generate.py；skills/public/image-generation/SKILL.md；skills/public/image-generation/scripts/generate.py；skills/public/image-generation/templates/doraemon.md；skills/public/video-generation/SKILL.md；skills/public/video-generation/scripts/generate.py。

#### 97. feat: update demo

- 提交：`[af4fc80](https://github.com/bytedance/deer-flow/commit/af4fc800ee540a7d93dbef059b6dd874b72f93f7)`
- 日期：2026-01-25
- 做了什么：新增或增强功能，主题是“update demo”。
- 影响范围：主要涉及 前端。
- 改动规模：+2043 / -1117 行。
- 关键文件：frontend/public/demo/threads/21cfea46-34bd-4aa6-9e1f-3009452fbeb9/thread.json；frontend/public/demo/threads/21cfea46-34bd-4aa6-9e1f-3009452fbeb9/user-data/outputs/doraemon-moe-comic.jpg；frontend/public/demo/threads/4f3e55ee-f853-43db-bfb3-7d1a411f03cb/thread.json；frontend/public/demo/threads/4f3e55ee-f853-43db-bfb3-7d1a411f03cb/user-data/outputs/darcy-proposal-reference.jpg；frontend/public/demo/threads/4f3e55ee-f853-43db-bfb3-7d1a411f03cb/user-data/outputs/darcy-proposal-video.mp4；frontend/public/demo/threads/85ee6ae5-bd68-4359-b17f-9f78c234d63c/thread.json；frontend/public/demo/threads/85ee6ae5-bd68-4359-b17f-9f78c234d63c/user-data/outputs/doraemon-moe.jpg；frontend/public/demo/threads/85ee6ae5-bd68-4359-b17f-9f78c234d63c/user-data/outputs/prompt.json。

#### 98. feat: update demo

- 提交：`[90c30c8](https://github.com/bytedance/deer-flow/commit/90c30c8485ae5f1477086347f3363314cff40876)`
- 日期：2026-01-25
- 做了什么：新增或增强功能，主题是“update demo”。
- 影响范围：主要涉及 前端。
- 改动规模：+2043 / -1117 行。
- 关键文件：frontend/public/demo/threads/21cfea46-34bd-4aa6-9e1f-3009452fbeb9/thread.json；frontend/public/demo/threads/21cfea46-34bd-4aa6-9e1f-3009452fbeb9/user-data/outputs/doraemon-moe-comic.jpg；frontend/public/demo/threads/4f3e55ee-f853-43db-bfb3-7d1a411f03cb/thread.json；frontend/public/demo/threads/4f3e55ee-f853-43db-bfb3-7d1a411f03cb/user-data/outputs/darcy-proposal-reference.jpg；frontend/public/demo/threads/4f3e55ee-f853-43db-bfb3-7d1a411f03cb/user-data/outputs/darcy-proposal-video.mp4；frontend/public/demo/threads/85ee6ae5-bd68-4359-b17f-9f78c234d63c/thread.json；frontend/public/demo/threads/85ee6ae5-bd68-4359-b17f-9f78c234d63c/user-data/outputs/doraemon-moe.jpg；frontend/public/demo/threads/85ee6ae5-bd68-4359-b17f-9f78c234d63c/user-data/outputs/prompt.json。

#### 99. feat: update translations

- 提交：`[87200d1](https://github.com/bytedance/deer-flow/commit/87200d1ad12bd1a7a5fc7278e65c2598e869cd35)`
- 日期：2026-01-25
- 做了什么：新增或增强功能，主题是“update translations”。
- 影响范围：主要涉及 前端。
- 改动规模：+9 / -8 行。
- 关键文件：frontend/src/components/landing/sections/skills-section.tsx；frontend/src/components/workspace/settings/skill-settings-page.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/zh-CN.ts。

#### 100. feat: update translations

- 提交：`[e6cac2c](https://github.com/bytedance/deer-flow/commit/e6cac2cae4eb0fe28c8fe5d5a2c092a27c5d0fb0)`
- 日期：2026-01-25
- 做了什么：新增或增强功能，主题是“update translations”。
- 影响范围：主要涉及 前端。
- 改动规模：+9 / -8 行。
- 关键文件：frontend/src/components/landing/sections/skills-section.tsx；frontend/src/components/workspace/settings/skill-settings-page.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/zh-CN.ts。

#### 101. feat: update demos

- 提交：`[74dd09b](https://github.com/bytedance/deer-flow/commit/74dd09b364a1e14074dc7ae480178d2b4f482308)`
- 日期：2026-01-25
- 做了什么：新增或增强功能，主题是“update demos”。
- 影响范围：主要涉及 前端。
- 改动规模：+2910 / -537 行。
- 关键文件：frontend/public/demo/threads/3823e443-4e2b-4679-b496-a9506eae462b/thread.json；frontend/public/demo/threads/3823e443-4e2b-4679-b496-a9506eae462b/user-data/outputs/fei-fei-li-podcast-timeline.md；frontend/public/demo/threads/d3e5adaf-084c-4dd5-9d29-94f1d6bccd98/thread.json；frontend/public/demo/threads/d3e5adaf-084c-4dd5-9d29-94f1d6bccd98/user-data/outputs/diana_hu_research.md；frontend/public/demo/threads/e05bea79-5b98-4e79-bc5f-c624be86ff7f/thread.json。

#### 102. feat: update demos

- 提交：`[e84fb70](https://github.com/bytedance/deer-flow/commit/e84fb705ce5d484b6f2ae6c5132c217a314ac947)`
- 日期：2026-01-25
- 做了什么：新增或增强功能，主题是“update demos”。
- 影响范围：主要涉及 前端。
- 改动规模：+2910 / -537 行。
- 关键文件：frontend/public/demo/threads/3823e443-4e2b-4679-b496-a9506eae462b/thread.json；frontend/public/demo/threads/3823e443-4e2b-4679-b496-a9506eae462b/user-data/outputs/fei-fei-li-podcast-timeline.md；frontend/public/demo/threads/d3e5adaf-084c-4dd5-9d29-94f1d6bccd98/thread.json；frontend/public/demo/threads/d3e5adaf-084c-4dd5-9d29-94f1d6bccd98/user-data/outputs/diana_hu_research.md；frontend/public/demo/threads/e05bea79-5b98-4e79-bc5f-c624be86ff7f/thread.json。

#### 103. feat: add Titanic ADA demo

- 提交：`[78bba47](https://github.com/bytedance/deer-flow/commit/78bba477698802afdddbc6df7ed8a606ab3d92a9)`
- 日期：2026-01-25
- 做了什么：新增或增强功能，主题是“add Titanic ADA demo”。
- 影响范围：主要涉及 前端。
- 改动规模：+1527 / -5 行。
- 关键文件：frontend/public/demo/threads/ad76c455-5bf9-4335-8517-fc03834ab828/thread.json；frontend/public/demo/threads/ad76c455-5bf9-4335-8517-fc03834ab828/user-data/outputs/titanic_summary.txt；frontend/public/demo/threads/ad76c455-5bf9-4335-8517-fc03834ab828/user-data/outputs/visualizations/class_gender_survival.png；frontend/public/demo/threads/ad76c455-5bf9-4335-8517-fc03834ab828/user-data/outputs/visualizations/correlation_heatmap.png；frontend/public/demo/threads/ad76c455-5bf9-4335-8517-fc03834ab828/user-data/outputs/visualizations/family_size_analysis.png；frontend/public/demo/threads/ad76c455-5bf9-4335-8517-fc03834ab828/user-data/outputs/visualizations/fare_analysis.png；frontend/public/demo/threads/ad76c455-5bf9-4335-8517-fc03834ab828/user-data/outputs/visualizations/survival_by_age.png；frontend/public/demo/threads/ad76c455-5bf9-4335-8517-fc03834ab828/user-data/outputs/visualizations/survival_by_class.png。

#### 104. feat: add Titanic ADA demo

- 提交：`[c6dbd9f](https://github.com/bytedance/deer-flow/commit/c6dbd9fbf42f04a47d316f95ff08adefbcb80aad)`
- 日期：2026-01-25
- 做了什么：新增或增强功能，主题是“add Titanic ADA demo”。
- 影响范围：主要涉及 前端。
- 改动规模：+1527 / -5 行。
- 关键文件：frontend/public/demo/threads/ad76c455-5bf9-4335-8517-fc03834ab828/thread.json；frontend/public/demo/threads/ad76c455-5bf9-4335-8517-fc03834ab828/user-data/outputs/titanic_summary.txt；frontend/public/demo/threads/ad76c455-5bf9-4335-8517-fc03834ab828/user-data/outputs/visualizations/class_gender_survival.png；frontend/public/demo/threads/ad76c455-5bf9-4335-8517-fc03834ab828/user-data/outputs/visualizations/correlation_heatmap.png；frontend/public/demo/threads/ad76c455-5bf9-4335-8517-fc03834ab828/user-data/outputs/visualizations/family_size_analysis.png；frontend/public/demo/threads/ad76c455-5bf9-4335-8517-fc03834ab828/user-data/outputs/visualizations/fare_analysis.png；frontend/public/demo/threads/ad76c455-5bf9-4335-8517-fc03834ab828/user-data/outputs/visualizations/survival_by_age.png；frontend/public/demo/threads/ad76c455-5bf9-4335-8517-fc03834ab828/user-data/outputs/visualizations/survival_by_class.png。

#### 105. feat: add new demo

- 提交：`[35f2aea](https://github.com/bytedance/deer-flow/commit/35f2aea510e05c13f0a4ad646ceebf3ff8c156a8)`
- 日期：2026-01-24
- 做了什么：新增或增强功能，主题是“add new demo”。
- 影响范围：主要涉及 前端。
- 改动规模：+3089 / -0 行。
- 关键文件：frontend/public/demo/threads/7cfa5f8f-a2f8-47ad-acbd-da7137baf990/thread.json；frontend/public/demo/threads/7cfa5f8f-a2f8-47ad-acbd-da7137baf990/user-data/outputs/index.html；frontend/public/demo/threads/7cfa5f8f-a2f8-47ad-acbd-da7137baf990/user-data/outputs/script.js；frontend/public/demo/threads/7cfa5f8f-a2f8-47ad-acbd-da7137baf990/user-data/outputs/style.css。

#### 106. feat: add new demo

- 提交：`[03311d4](https://github.com/bytedance/deer-flow/commit/03311d43dabbbbfd5e30b8aaf07816fbe5053de2)`
- 日期：2026-01-24
- 做了什么：新增或增强功能，主题是“add new demo”。
- 影响范围：主要涉及 前端。
- 改动规模：+3089 / -0 行。
- 关键文件：frontend/public/demo/threads/7cfa5f8f-a2f8-47ad-acbd-da7137baf990/thread.json；frontend/public/demo/threads/7cfa5f8f-a2f8-47ad-acbd-da7137baf990/user-data/outputs/index.html；frontend/public/demo/threads/7cfa5f8f-a2f8-47ad-acbd-da7137baf990/user-data/outputs/script.js；frontend/public/demo/threads/7cfa5f8f-a2f8-47ad-acbd-da7137baf990/user-data/outputs/style.css。

#### 107. feat: auto expand in demo mode

- 提交：`[a83e5e2](https://github.com/bytedance/deer-flow/commit/a83e5e238d84c49f07d572b6b877230d6182558a)`
- 日期：2026-01-24
- 做了什么：新增或增强功能，主题是“auto expand in demo mode”。
- 影响范围：主要涉及 前端。
- 改动规模：+34 / -5 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/workspace/artifacts/artifact-file-detail.tsx；frontend/src/components/workspace/artifacts/context.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts；frontend/src/core/i18n/locales/zh-CN.ts。

#### 108. feat: auto expand in demo mode

- 提交：`[099fb72](https://github.com/bytedance/deer-flow/commit/099fb727ccc04df964a208f8a89a8101e62ba9d0)`
- 日期：2026-01-24
- 做了什么：新增或增强功能，主题是“auto expand in demo mode”。
- 影响范围：主要涉及 前端。
- 改动规模：+34 / -5 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/workspace/artifacts/artifact-file-detail.tsx；frontend/src/components/workspace/artifacts/context.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts；frontend/src/core/i18n/locales/zh-CN.ts。

#### 109. feat: add environment variable injection for Docker sandbox

- 提交：`[6e147a7](https://github.com/bytedance/deer-flow/commit/6e147a772e8fc61c341a606b9637c60c1d40ced3)`
- 日期：2026-01-24
- 做了什么：新增或增强功能，主题是“add environment variable injection for Docker sandbox”。
- 影响范围：主要涉及 后端、前端、技能体系。
- 改动规模：+72 / -18 行。
- 关键文件：.env.example；backend/src/community/aio_sandbox/aio_sandbox_provider.py；backend/src/config/sandbox_config.py；config.example.yaml；frontend/src/core/mcp/api.ts；frontend/src/core/skills/api.ts；skills/public/doraemon-comic-aigc/SKILL.md；skills/public/doraemon-comic-aigc/scripts/generate.py。

#### 110. feat: add environment variable injection for Docker sandbox

- 提交：`[5671642](https://github.com/bytedance/deer-flow/commit/5671642dbe3d5ad343f19ed295f036b8a1fd1293)`
- 日期：2026-01-24
- 做了什么：新增或增强功能，主题是“add environment variable injection for Docker sandbox”。
- 影响范围：主要涉及 后端、前端、技能体系。
- 改动规模：+72 / -18 行。
- 关键文件：.env.example；backend/src/community/aio_sandbox/aio_sandbox_provider.py；backend/src/config/sandbox_config.py；config.example.yaml；frontend/src/core/mcp/api.ts；frontend/src/core/skills/api.ts；skills/public/doraemon-comic-aigc/SKILL.md；skills/public/doraemon-comic-aigc/scripts/generate.py。

#### 111. feat: add i18n

- 提交：`[869af57](https://github.com/bytedance/deer-flow/commit/869af570c93b0dbcae01fc73c4be8789b1cffcc4)`
- 日期：2026-01-24
- 做了什么：新增或增强功能，主题是“add i18n”。
- 影响范围：主要涉及 前端。
- 改动规模：+5 / -2 行。
- 关键文件：frontend/src/components/workspace/settings/skill-settings-page.tsx；frontend/src/components/workspace/settings/tool-settings-page.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts；frontend/src/core/i18n/locales/zh-CN.ts。

#### 112. feat: add i18n

- 提交：`[48b5428](https://github.com/bytedance/deer-flow/commit/48b5428000b36414e1c24452cf0b79b4600c04fd)`
- 日期：2026-01-24
- 做了什么：新增或增强功能，主题是“add i18n”。
- 影响范围：主要涉及 前端。
- 改动规模：+5 / -2 行。
- 关键文件：frontend/src/components/workspace/settings/skill-settings-page.tsx；frontend/src/components/workspace/settings/tool-settings-page.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts；frontend/src/core/i18n/locales/zh-CN.ts。

#### 113. feat: expand by default in demo mode

- 提交：`[5a27a3b](https://github.com/bytedance/deer-flow/commit/5a27a3beeba81876b560c4c6259303d2ab885950)`
- 日期：2026-01-24
- 做了什么：新增或增强功能，主题是“expand by default in demo mode”。
- 影响范围：主要涉及 前端。
- 改动规模：+7 / -2 行。
- 关键文件：frontend/src/components/workspace/messages/message-group.tsx。

#### 114. feat: expand by default in demo mode

- 提交：`[56b21e0](https://github.com/bytedance/deer-flow/commit/56b21e00bffbf69ff61f5fabef111ce7c2068e7a)`
- 日期：2026-01-24
- 做了什么：新增或增强功能，主题是“expand by default in demo mode”。
- 影响范围：主要涉及 前端。
- 改动规模：+7 / -2 行。
- 关键文件：frontend/src/components/workspace/messages/message-group.tsx。

#### 115. feat: adds docker-based dev environment (#18)

- 提交：`[3808130](https://github.com/bytedance/deer-flow/commit/38081306feec1d231a4211398b826ebf9d4453a0)`
- 日期：2026-01-24
- 做了什么：新增或增强功能，主题是“adds docker-based dev environment (#18)”。
- 影响范围：主要涉及 其他模块、容器部署、文档。
- 改动规模：+1074 / -285 行。
- 关键文件：.gitignore；CONTRIBUTING.md；Makefile；README.md；backend/Dockerfile；docker/docker-compose-dev.yaml；docker/nginx/nginx.conf；docker/nginx/nginx.local.conf。

#### 116. feat: adds docker-based dev environment (#18)

- 提交：`[400349c](https://github.com/bytedance/deer-flow/commit/400349c3e0e65c47e9cb8e0ac09721a09a2ace42)`
- 日期：2026-01-24
- 做了什么：新增或增强功能，主题是“adds docker-based dev environment (#18)”。
- 影响范围：主要涉及 其他模块、容器部署、文档。
- 改动规模：+1074 / -285 行。
- 关键文件：.gitignore；CONTRIBUTING.md；Makefile；README.md；backend/Dockerfile；docker/docker-compose-dev.yaml；docker/nginx/nginx.conf；docker/nginx/nginx.local.conf。

#### 117. feat: add Doraemon Skill

- 提交：`[c468381](https://github.com/bytedance/deer-flow/commit/c46838106442cb25c740e03995eaf269ac701e02)`
- 日期：2026-01-24
- 做了什么：新增或增强功能，主题是“add Doraemon Skill”。
- 影响范围：主要涉及 技能体系。
- 改动规模：+165 / -0 行。
- 关键文件：skills/public/doraemon-comic-aigc/SKILL.md；skills/public/doraemon-comic-aigc/scripts/generate.py。

#### 118. feat: add Doraemon Skill

- 提交：`[ee9950d](https://github.com/bytedance/deer-flow/commit/ee9950d6aa7ac72ab54cd668fda14d30d2e33743)`
- 日期：2026-01-24
- 做了什么：新增或增强功能，主题是“add Doraemon Skill”。
- 影响范围：主要涉及 技能体系。
- 改动规模：+165 / -0 行。
- 关键文件：skills/public/doraemon-comic-aigc/SKILL.md；skills/public/doraemon-comic-aigc/scripts/generate.py。

#### 119. feat: remove over-scroll

- 提交：`[cae7e67](https://github.com/bytedance/deer-flow/commit/cae7e67a1f36e5c34d728843bd92db527842f8af)`
- 日期：2026-01-24
- 做了什么：新增或增强功能，主题是“remove over-scroll”。
- 影响范围：主要涉及 前端。
- 改动规模：+0 / -1 行。
- 关键文件：frontend/src/app/workspace/layout.tsx。

#### 120. feat: remove over-scroll

- 提交：`[291b899](https://github.com/bytedance/deer-flow/commit/291b899486ba127645e0b727f6b2af05170ddb3b)`
- 日期：2026-01-24
- 做了什么：新增或增强功能，主题是“remove over-scroll”。
- 影响范围：主要涉及 前端。
- 改动规模：+0 / -1 行。
- 关键文件：frontend/src/app/workspace/layout.tsx。

#### 121. feat: add new demo

- 提交：`[72e0f3d](https://github.com/bytedance/deer-flow/commit/72e0f3d08196787f52e46f26d7301b7e15026c52)`
- 日期：2026-01-24
- 做了什么：新增或增强功能，主题是“add new demo”。
- 影响范围：主要涉及 前端。
- 改动规模：+1117 / -0 行。
- 关键文件：frontend/public/demo/threads/85ee6ae5-bd68-4359-b17f-9f78c234d63c/thread.json；frontend/public/demo/threads/85ee6ae5-bd68-4359-b17f-9f78c234d63c/user-data/outputs/doraemon-moe.jpg；frontend/public/demo/threads/85ee6ae5-bd68-4359-b17f-9f78c234d63c/user-data/outputs/prompt.json。

#### 122. feat: add new demo

- 提交：`[2c2a177](https://github.com/bytedance/deer-flow/commit/2c2a177186fc3c675e8545206155ba2cc1d43bcc)`
- 日期：2026-01-24
- 做了什么：新增或增强功能，主题是“add new demo”。
- 影响范围：主要涉及 前端。
- 改动规模：+1117 / -0 行。
- 关键文件：frontend/public/demo/threads/85ee6ae5-bd68-4359-b17f-9f78c234d63c/thread.json；frontend/public/demo/threads/85ee6ae5-bd68-4359-b17f-9f78c234d63c/user-data/outputs/doraemon-moe.jpg；frontend/public/demo/threads/85ee6ae5-bd68-4359-b17f-9f78c234d63c/user-data/outputs/prompt.json。

#### 123. feat: support absolute path as image src

- 提交：`[08f1af0](https://github.com/bytedance/deer-flow/commit/08f1af00b66b1333bf0bbd0eaef30a1adee978c1)`
- 日期：2026-01-24
- 做了什么：新增或增强功能，主题是“support absolute path as image src”。
- 影响范围：主要涉及 前端。
- 改动规模：+37 / -1 行。
- 关键文件：frontend/src/components/workspace/messages/message-list-item.tsx；frontend/src/core/artifacts/utils.ts。

#### 124. feat: support absolute path as image src

- 提交：`[4aef821](https://github.com/bytedance/deer-flow/commit/4aef8213441c5f3f214c781d554e19fda56db681)`
- 日期：2026-01-24
- 做了什么：新增或增强功能，主题是“support absolute path as image src”。
- 影响范围：主要涉及 前端。
- 改动规模：+37 / -1 行。
- 关键文件：frontend/src/components/workspace/messages/message-list-item.tsx；frontend/src/core/artifacts/utils.ts。

#### 125. chore: add new demo

- 提交：`[6485ed2](https://github.com/bytedance/deer-flow/commit/6485ed2a50254859cdf40412b3c5e282a3bafe6a)`
- 日期：2026-01-24
- 做了什么：新增或增强功能，主题是“add new demo”。
- 影响范围：主要涉及 前端。
- 改动规模：+5161 / -0 行。
- 关键文件：frontend/public/demo/threads/090898a7-1b1e-4937-ba03-764dbaafa27b/thread.json；frontend/public/demo/threads/090898a7-1b1e-4937-ba03-764dbaafa27b/user-data/outputs/nie-weiping-memorial/index.html；frontend/public/demo/threads/090898a7-1b1e-4937-ba03-764dbaafa27b/user-data/outputs/nie-weiping-memorial/script.js；frontend/public/demo/threads/090898a7-1b1e-4937-ba03-764dbaafa27b/user-data/outputs/nie-weiping-memorial/style.css。

#### 126. chore: add new demo

- 提交：`[cced422](https://github.com/bytedance/deer-flow/commit/cced422e9d404c3dfdc7f85563af82b5d2105712)`
- 日期：2026-01-24
- 做了什么：新增或增强功能，主题是“add new demo”。
- 影响范围：主要涉及 前端。
- 改动规模：+5161 / -0 行。
- 关键文件：frontend/public/demo/threads/090898a7-1b1e-4937-ba03-764dbaafa27b/thread.json；frontend/public/demo/threads/090898a7-1b1e-4937-ba03-764dbaafa27b/user-data/outputs/nie-weiping-memorial/index.html；frontend/public/demo/threads/090898a7-1b1e-4937-ba03-764dbaafa27b/user-data/outputs/nie-weiping-memorial/script.js；frontend/public/demo/threads/090898a7-1b1e-4937-ba03-764dbaafa27b/user-data/outputs/nie-weiping-memorial/style.css。

#### 127. feat: add new demo

- 提交：`[72e3ba9](https://github.com/bytedance/deer-flow/commit/72e3ba9b79c57e731b27dbd383d94870a4d4221e)`
- 日期：2026-01-24
- 做了什么：新增或增强功能，主题是“add new demo”。
- 影响范围：主要涉及 前端。
- 改动规模：+5119 / -0 行。
- 关键文件：frontend/public/demo/threads/090898a7-1b1e-4937-ba03-764dbaafa27b/thread.json；frontend/public/demo/threads/090898a7-1b1e-4937-ba03-764dbaafa27b/user-data/outputs/nie-weiping-memorial/index.html；frontend/public/demo/threads/090898a7-1b1e-4937-ba03-764dbaafa27b/user-data/outputs/nie-weiping-memorial/script.js；frontend/public/demo/threads/090898a7-1b1e-4937-ba03-764dbaafa27b/user-data/outputs/nie-weiping-memorial/style.css。

#### 128. feat: add new demo

- 提交：`[373fe0c](https://github.com/bytedance/deer-flow/commit/373fe0cd3c5496a119e5d7895d650f33191f54d9)`
- 日期：2026-01-24
- 做了什么：新增或增强功能，主题是“add new demo”。
- 影响范围：主要涉及 前端。
- 改动规模：+5119 / -0 行。
- 关键文件：frontend/public/demo/threads/090898a7-1b1e-4937-ba03-764dbaafa27b/thread.json；frontend/public/demo/threads/090898a7-1b1e-4937-ba03-764dbaafa27b/user-data/outputs/nie-weiping-memorial/index.html；frontend/public/demo/threads/090898a7-1b1e-4937-ba03-764dbaafa27b/user-data/outputs/nie-weiping-memorial/script.js；frontend/public/demo/threads/090898a7-1b1e-4937-ba03-764dbaafa27b/user-data/outputs/nie-weiping-memorial/style.css。

#### 129. feat: add uploads

- 提交：`[27df1b5](https://github.com/bytedance/deer-flow/commit/27df1b5f73d830574d1e60e5284c9a9dc4617056)`
- 日期：2026-01-24
- 做了什么：新增或增强功能，主题是“add uploads”。
- 影响范围：主要涉及 前端。
- 改动规模：+8 / -3 行。
- 关键文件：frontend/scripts/save-demo.js。

#### 130. feat: add uploads

- 提交：`[1f4591a](https://github.com/bytedance/deer-flow/commit/1f4591a4d145212b4781308456adeab406f4f2f1)`
- 日期：2026-01-24
- 做了什么：新增或增强功能，主题是“add uploads”。
- 影响范围：主要涉及 前端。
- 改动规模：+8 / -3 行。
- 关键文件：frontend/scripts/save-demo.js。

#### 131. chore: add new demo

- 提交：`[a3eb03b](https://github.com/bytedance/deer-flow/commit/a3eb03b1056c5638ed1eb0c9c896a2ba93a14762)`
- 日期：2026-01-24
- 做了什么：新增或增强功能，主题是“add new demo”。
- 影响范围：主要涉及 前端。
- 改动规模：+537 / -0 行。
- 关键文件：frontend/public/demo/threads/e05bea79-5b98-4e79-bc5f-c624be86ff7f/thread.json。

#### 132. chore: add new demo

- 提交：`[db27ca4](https://github.com/bytedance/deer-flow/commit/db27ca4ae093b59aaef2df2fab28c00ecc313466)`
- 日期：2026-01-24
- 做了什么：新增或增强功能，主题是“add new demo”。
- 影响范围：主要涉及 前端。
- 改动规模：+537 / -0 行。
- 关键文件：frontend/public/demo/threads/e05bea79-5b98-4e79-bc5f-c624be86ff7f/thread.json。

#### 133. feat: remove background

- 提交：`[930e6bd](https://github.com/bytedance/deer-flow/commit/930e6bd46fb0b0246fab4ccc335826ae263cfd5e)`
- 日期：2026-01-24
- 做了什么：新增或增强功能，主题是“remove background”。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -39 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/layout.tsx。

#### 134. feat: remove background

- 提交：`[0f1bfc3](https://github.com/bytedance/deer-flow/commit/0f1bfc3403ef5e4473e412cf73ee9d83d67aa76c)`
- 日期：2026-01-24
- 做了什么：新增或增强功能，主题是“remove background”。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -39 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/layout.tsx。

#### 135. feat: update save-demo

- 提交：`[6f24a71](https://github.com/bytedance/deer-flow/commit/6f24a71e1ec7d9c1fa6ea87fdda4ad9a97ea1312)`
- 日期：2026-01-24
- 做了什么：新增或增强功能，主题是“update save-demo”。
- 影响范围：主要涉及 前端。
- 改动规模：+7 / -4 行。
- 关键文件：frontend/scripts/save-demo.js。

#### 136. feat: update save-demo

- 提交：`[3ea1dca](https://github.com/bytedance/deer-flow/commit/3ea1dcac111966ac6cc3ad200e7477ad1374aded)`
- 日期：2026-01-24
- 做了什么：新增或增强功能，主题是“update save-demo”。
- 影响范围：主要涉及 前端。
- 改动规模：+7 / -4 行。
- 关键文件：frontend/scripts/save-demo.js。

#### 137. feat: add more links

- 提交：`[584c88f](https://github.com/bytedance/deer-flow/commit/584c88f0dd9a69710327926789bd15b5a733de2a)`
- 日期：2026-01-24
- 做了什么：新增或增强功能，主题是“add more links”。
- 影响范围：主要涉及 前端。
- 改动规模：+22 / -5 行。
- 关键文件：frontend/src/components/workspace/workspace-nav-menu.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts；frontend/src/core/i18n/locales/zh-CN.ts。

#### 138. feat: add more links

- 提交：`[3c40446](https://github.com/bytedance/deer-flow/commit/3c40446ade311fb8e7e13031ae93afc870b7345b)`
- 日期：2026-01-24
- 做了什么：新增或增强功能，主题是“add more links”。
- 影响范围：主要涉及 前端。
- 改动规模：+22 / -5 行。
- 关键文件：frontend/src/components/workspace/workspace-nav-menu.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts；frontend/src/core/i18n/locales/zh-CN.ts。

#### 139. feat: support static website

- 提交：`[cd63f41](https://github.com/bytedance/deer-flow/commit/cd63f41b4c7aa7c8c8440d3c6242ff9a2cb1655b)`
- 日期：2026-01-24
- 做了什么：新增或增强功能，主题是“support static website”。
- 影响范围：主要涉及 前端。
- 改动规模：+5535 / -738 行。
- 关键文件：frontend/package.json；frontend/pnpm-lock.yaml；frontend/public/demo/threads/5aa47db1-d0cb-4eb9-aea5-3dac1b371c5a/thread.json；frontend/public/demo/threads/5aa47db1-d0cb-4eb9-aea5-3dac1b371c5a/user-data/outputs/jiangsu-football/css/style.css；frontend/public/demo/threads/5aa47db1-d0cb-4eb9-aea5-3dac1b371c5a/user-data/outputs/jiangsu-football/favicon.html；frontend/public/demo/threads/5aa47db1-d0cb-4eb9-aea5-3dac1b371c5a/user-data/outputs/jiangsu-football/index.html；frontend/public/demo/threads/5aa47db1-d0cb-4eb9-aea5-3dac1b371c5a/user-data/outputs/jiangsu-football/js/data.js；frontend/public/demo/threads/5aa47db1-d0cb-4eb9-aea5-3dac1b371c5a/user-data/outputs/jiangsu-football/js/main.js。

#### 140. feat: support static website

- 提交：`[ebda30c](https://github.com/bytedance/deer-flow/commit/ebda30c7cf5ba61ba6885e0cab3b017bf7d6710d)`
- 日期：2026-01-24
- 做了什么：新增或增强功能，主题是“support static website”。
- 影响范围：主要涉及 前端。
- 改动规模：+5535 / -738 行。
- 关键文件：frontend/package.json；frontend/pnpm-lock.yaml；frontend/public/demo/threads/5aa47db1-d0cb-4eb9-aea5-3dac1b371c5a/thread.json；frontend/public/demo/threads/5aa47db1-d0cb-4eb9-aea5-3dac1b371c5a/user-data/outputs/jiangsu-football/css/style.css；frontend/public/demo/threads/5aa47db1-d0cb-4eb9-aea5-3dac1b371c5a/user-data/outputs/jiangsu-football/favicon.html；frontend/public/demo/threads/5aa47db1-d0cb-4eb9-aea5-3dac1b371c5a/user-data/outputs/jiangsu-football/index.html；frontend/public/demo/threads/5aa47db1-d0cb-4eb9-aea5-3dac1b371c5a/user-data/outputs/jiangsu-football/js/data.js；frontend/public/demo/threads/5aa47db1-d0cb-4eb9-aea5-3dac1b371c5a/user-data/outputs/jiangsu-football/js/main.js。

#### 141. feat: add citation support in research report block and markdown

- 提交：`[b7f0f54](https://github.com/bytedance/deer-flow/commit/b7f0f54aa0243e28563c160ab7eb3ebfbb11a339)`
- 日期：2026-01-24
- 做了什么：新增或增强功能，主题是“add citation support in research report block and markdown”。
- 影响范围：主要涉及 其他模块、配置。
- 改动规模：+2125 / -29 行。
- 关键文件：src/citations/**init**.py；src/citations/collector.py；src/citations/extractor.py；src/citations/formatter.py；src/citations/models.py；src/graph/nodes.py；src/graph/types.py；src/prompts/reporter.md。

#### 142. feat(server): add MCP server configuration validation (#830)

- 提交：`[612bddd](https://github.com/bytedance/deer-flow/commit/612bddd3fb14e8fdb51ac33f6709b707fc8934b4)`
- 日期：2026-01-24
- 做了什么：新增或增强功能，主题是“add MCP server configuration validation (#830)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+1072 / -19 行。
- 关键文件：src/server/mcp_request.py；src/server/mcp_utils.py；src/server/mcp_validators.py；tests/unit/server/test_app.py；tests/unit/server/test_chat_request.py；tests/unit/server/test_mcp_utils.py；tests/unit/server/test_mcp_validators.py。

#### 143. feat: implement file upload feature

- 提交：`[f6a20a6](https://github.com/bytedance/deer-flow/commit/f6a20a69e34e1802d5fed3319f351fc7c67f9f9a)`
- 日期：2026-01-23
- 做了什么：新增或增强功能，主题是“implement file upload feature”。
- 影响范围：主要涉及 后端、前端、其他模块。
- 改动规模：+1880 / -11 行。
- 关键文件：backend/docs/FILE_UPLOAD.md；backend/docs/PATH_EXAMPLES.md；backend/pyproject.toml；backend/src/agents/lead_agent/agent.py；backend/src/agents/lead_agent/prompt.py；backend/src/agents/middlewares/uploads_middleware.py；backend/src/agents/thread_state.py；backend/src/gateway/app.py。

#### 144. feat: implement file upload feature

- 提交：`[1fe37fd](https://github.com/bytedance/deer-flow/commit/1fe37fdb6c112aca5ed5fc7d51fa1f78bb5e14e6)`
- 日期：2026-01-23
- 做了什么：新增或增强功能，主题是“implement file upload feature”。
- 影响范围：主要涉及 后端、前端、其他模块。
- 改动规模：+1880 / -11 行。
- 关键文件：backend/docs/FILE_UPLOAD.md；backend/docs/PATH_EXAMPLES.md；backend/pyproject.toml；backend/src/agents/lead_agent/agent.py；backend/src/agents/lead_agent/prompt.py；backend/src/agents/middlewares/uploads_middleware.py；backend/src/agents/thread_state.py；backend/src/gateway/app.py。

#### 145. feat: implement the first version of landing page

- 提交：`[3f4bcd9](https://github.com/bytedance/deer-flow/commit/3f4bcd943396480d786cbcbc9812cf9d5b0ece94)`
- 日期：2026-01-23
- 做了什么：新增或增强功能，主题是“implement the first version of landing page”。
- 影响范围：主要涉及 前端。
- 改动规模：+2950 / -615 行。
- 关键文件：frontend/package.json；frontend/pnpm-lock.yaml；frontend/src/app/page.tsx；frontend/src/components/Galaxy.css；frontend/src/components/Galaxy.jsx；frontend/src/components/landing/components/progressive-skills-animation.tsx；frontend/src/components/landing/footer.tsx；frontend/src/components/landing/header.tsx。

#### 146. feat: implement the first version of landing page

- 提交：`[0908127](https://github.com/bytedance/deer-flow/commit/0908127bd774c878ddcea065f786f2c81540fab8)`
- 日期：2026-01-23
- 做了什么：新增或增强功能，主题是“implement the first version of landing page”。
- 影响范围：主要涉及 前端。
- 改动规模：+2950 / -615 行。
- 关键文件：frontend/package.json；frontend/pnpm-lock.yaml；frontend/src/app/page.tsx；frontend/src/components/Galaxy.css；frontend/src/components/Galaxy.jsx；frontend/src/components/landing/components/progressive-skills-animation.tsx；frontend/src/components/landing/footer.tsx；frontend/src/components/landing/header.tsx。

#### 147. feat(context): decrease token in web_search AIMessage (#827)

- 提交：`[c0849af](https://github.com/bytedance/deer-flow/commit/c0849af37eef547d2da1224e03d65ed70fa5c171)`
- 日期：2026-01-23
- 做了什么：新增或增强功能，主题是“decrease token in web_search AIMessage (#827)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+124 / -89 行。
- 关键文件：src/tools/crawl.py；src/tools/search.py；src/utils/context_manager.py；tests/unit/tools/test_search.py；tests/unit/utils/test_context_manager.py。

#### 148. feat: implement the first section of landing page

- 提交：`[307972f](https://github.com/bytedance/deer-flow/commit/307972f93ed05d5e8ddd9e1e8b3fbdc662614574)`
- 日期：2026-01-23
- 做了什么：新增或增强功能，主题是“implement the first section of landing page”。
- 影响范围：主要涉及 前端。
- 改动规模：+757 / -7 行。
- 关键文件：frontend/components.json；frontend/package.json；frontend/pnpm-lock.yaml；frontend/src/app/layout.tsx；frontend/src/app/page.tsx；frontend/src/components/Galaxy.css；frontend/src/components/Galaxy.jsx；frontend/src/components/landing/jumbotron.tsx。

#### 149. feat: implement the first section of landing page

- 提交：`[b69c13a](https://github.com/bytedance/deer-flow/commit/b69c13a3e5ad4ea87ccc539e8c88592c6db062f8)`
- 日期：2026-01-23
- 做了什么：新增或增强功能，主题是“implement the first section of landing page”。
- 影响范围：主要涉及 前端。
- 改动规模：+757 / -7 行。
- 关键文件：frontend/components.json；frontend/package.json；frontend/pnpm-lock.yaml；frontend/src/app/layout.tsx；frontend/src/app/page.tsx；frontend/src/components/Galaxy.css；frontend/src/components/Galaxy.jsx；frontend/src/components/landing/jumbotron.tsx。

#### 150. docs: add notes for v2.0 (#828)

- 提交：`[65cdc18](https://github.com/bytedance/deer-flow/commit/65cdc182d3a4aee84843705183186809f13f2644)`
- 日期：2026-01-22
- 做了什么：补充文档能力，主题是“add notes for v2.0 (#828)”。
- 影响范围：主要涉及 文档。
- 改动规模：+4 / -1 行。
- 关键文件：README.md。

#### 151. feat: adjust styles

- 提交：`[e9ab427](https://github.com/bytedance/deer-flow/commit/e9ab427326dc62bdb6ac549224ed2a241f14e2ab)`
- 日期：2026-01-22
- 做了什么：新增或增强功能，主题是“adjust styles”。
- 影响范围：主要涉及 前端。
- 改动规模：+7 / -1 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/ui/input-group.tsx；frontend/src/components/workspace/input-box.tsx。

#### 152. feat: adjust styles

- 提交：`[dc9d280](https://github.com/bytedance/deer-flow/commit/dc9d28018ce41198d5ad5f1e928a9fa1b2b1e94d)`
- 日期：2026-01-22
- 做了什么：新增或增强功能，主题是“adjust styles”。
- 影响范围：主要涉及 前端。
- 改动规模：+7 / -1 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/ui/input-group.tsx；frontend/src/components/workspace/input-box.tsx。

#### 153. feat: add main menu

- 提交：`[e0f491d](https://github.com/bytedance/deer-flow/commit/e0f491dcdb0ad97827b64a87a75ca627004af01d)`
- 日期：2026-01-22
- 做了什么：新增或增强功能，主题是“add main menu”。
- 影响范围：主要涉及 前端。
- 改动规模：+232 / -48 行。
- 关键文件：frontend/package.json；frontend/pnpm-lock.yaml；frontend/src/components/ui/avatar.tsx；frontend/src/components/workspace/workspace-nav-chat-list.tsx；frontend/src/components/workspace/workspace-nav-menu.tsx；frontend/src/components/workspace/workspace-sidebar.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts。

#### 154. feat: add main menu

- 提交：`[e137812](https://github.com/bytedance/deer-flow/commit/e1378123f5be00be9c2a9d4af261f9684d78312d)`
- 日期：2026-01-22
- 做了什么：新增或增强功能，主题是“add main menu”。
- 影响范围：主要涉及 前端。
- 改动规模：+232 / -48 行。
- 关键文件：frontend/package.json；frontend/pnpm-lock.yaml；frontend/src/components/ui/avatar.tsx；frontend/src/components/workspace/workspace-nav-chat-list.tsx；frontend/src/components/workspace/workspace-nav-menu.tsx；frontend/src/components/workspace/workspace-sidebar.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts。

#### 155. feat: update opacities

- 提交：`[80b07bc](https://github.com/bytedance/deer-flow/commit/80b07bcac04bc06532045ba2365f558fd593b456)`
- 日期：2026-01-22
- 做了什么：新增或增强功能，主题是“update opacities”。
- 影响范围：主要涉及 前端。
- 改动规模：+2 / -2 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/layout.tsx。

#### 156. feat: update opacities

- 提交：`[cb996f0](https://github.com/bytedance/deer-flow/commit/cb996f0858b7760ca6bc64490c6e31df98448c9a)`
- 日期：2026-01-22
- 做了什么：新增或增强功能，主题是“update opacities”。
- 影响范围：主要涉及 前端。
- 改动规模：+2 / -2 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/layout.tsx。

#### 157. feat: make `reasoning` mode as default

- 提交：`[8c99429](https://github.com/bytedance/deer-flow/commit/8c994293a82865e3fb66f87864a0df8fd27ff76e)`
- 日期：2026-01-22
- 做了什么：新增或增强功能，主题是“make `reasoning` mode as default”。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -1 行。
- 关键文件：frontend/src/core/settings/local.ts。

#### 158. feat: make `reasoning` mode as default

- 提交：`[99eb247](https://github.com/bytedance/deer-flow/commit/99eb2474b3882ceed82691191cf94965a841894c)`
- 日期：2026-01-22
- 做了什么：新增或增强功能，主题是“make `reasoning` mode as default”。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -1 行。
- 关键文件：frontend/src/core/settings/local.ts。

#### 159. feat: put all options into '+'

- 提交：`[7d4d706](https://github.com/bytedance/deer-flow/commit/7d4d70673811bebfa07b5e0ed884d2149d1024b1)`
- 日期：2026-01-22
- 做了什么：新增或增强功能，主题是“put all options into '+'”。
- 影响范围：主要涉及 前端。
- 改动规模：+197 / -141 行。
- 关键文件：frontend/src/app/layout.tsx；frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/ai-elements/prompt-input.tsx；frontend/src/components/workspace/input-box.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts；frontend/src/core/i18n/locales/zh-CN.ts。

#### 160. feat: put all options into '+'

- 提交：`[8ef89b3](https://github.com/bytedance/deer-flow/commit/8ef89b3004c454021aa7e4db9c4550f27227ac1a)`
- 日期：2026-01-22
- 做了什么：新增或增强功能，主题是“put all options into '+'”。
- 影响范围：主要涉及 前端。
- 改动规模：+197 / -141 行。
- 关键文件：frontend/src/app/layout.tsx；frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/ai-elements/prompt-input.tsx；frontend/src/components/workspace/input-box.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts；frontend/src/core/i18n/locales/zh-CN.ts。

#### 161. feat: add unified development environment with nginx proxy

- 提交：`[31bf499](https://github.com/bytedance/deer-flow/commit/31bf49917c63cf5340db0598e1672360079ceac9)`
- 日期：2026-01-22
- 做了什么：新增或增强功能，主题是“add unified development environment with nginx proxy”。
- 影响范围：主要涉及 其他模块、后端、前端。
- 改动规模：+376 / -69 行。
- 关键文件：.gitignore；Makefile；README.md；backend/CLAUDE.md；backend/Makefile；frontend/.env.example；frontend/src/core/config/index.ts；nginx.conf。

#### 162. feat: add unified development environment with nginx proxy

- 提交：`[2fac726](https://github.com/bytedance/deer-flow/commit/2fac72601eb638e2ed27de4a3cba18b00b51e4b4)`
- 日期：2026-01-22
- 做了什么：新增或增强功能，主题是“add unified development environment with nginx proxy”。
- 影响范围：主要涉及 其他模块、后端、前端。
- 改动规模：+376 / -69 行。
- 关键文件：.gitignore；Makefile；README.md；backend/CLAUDE.md；backend/Makefile；frontend/.env.example；frontend/src/core/config/index.ts；nginx.conf。

#### 163. feat: show `in-progress`

- 提交：`[16a4991](https://github.com/bytedance/deer-flow/commit/16a499190bcd8b174ea4cb4acee9614038be920f)`
- 日期：2026-01-22
- 做了什么：新增或增强功能，主题是“show `in-progress`”。
- 影响范围：主要涉及 前端。
- 改动规模：+12 / -2 行。
- 关键文件：frontend/src/components/workspace/todo-list.tsx。

#### 164. feat: show `in-progress`

- 提交：`[93f7089](https://github.com/bytedance/deer-flow/commit/93f70893fc8aa96675e3af74c5b9f205adeae1ae)`
- 日期：2026-01-22
- 做了什么：新增或增强功能，主题是“show `in-progress`”。
- 影响范围：主要涉及 前端。
- 改动规模：+12 / -2 行。
- 关键文件：frontend/src/components/workspace/todo-list.tsx。

#### 165. feat: adjust input background in light mode

- 提交：`[aa7436d](https://github.com/bytedance/deer-flow/commit/aa7436db2fa67f32643fd6fb0b105982e93d73f7)`
- 日期：2026-01-22
- 做了什么：新增或增强功能，主题是“adjust input background in light mode”。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -1 行。
- 关键文件：frontend/src/components/ui/input-group.tsx。

#### 166. feat: adjust input background in light mode

- 提交：`[4f71286](https://github.com/bytedance/deer-flow/commit/4f712861a31fa46d8cb00ac1a83b6eaec3ba021b)`
- 日期：2026-01-22
- 做了什么：新增或增强功能，主题是“adjust input background in light mode”。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -1 行。
- 关键文件：frontend/src/components/ui/input-group.tsx。

#### 167. feat: adjust styles

- 提交：`[93842e8](https://github.com/bytedance/deer-flow/commit/93842e81a4bfbad6e67833d31b957c900d6bcbed)`
- 日期：2026-01-22
- 做了什么：新增或增强功能，主题是“adjust styles”。
- 影响范围：主要涉及 前端。
- 改动规模：+13 / -6 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/workspace/todo-list.tsx。

#### 168. feat: adjust styles

- 提交：`[aed2f7c](https://github.com/bytedance/deer-flow/commit/aed2f7ce67211f5ca0078728753d19694ea30734)`
- 日期：2026-01-22
- 做了什么：新增或增强功能，主题是“adjust styles”。
- 影响范围：主要涉及 前端。
- 改动规模：+13 / -6 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/workspace/todo-list.tsx。

#### 169. feat: add animations

- 提交：`[e8e522c](https://github.com/bytedance/deer-flow/commit/e8e522c2fe4fd923913ce1edce2ca3937684030e)`
- 日期：2026-01-22
- 做了什么：新增或增强功能，主题是“add animations”。
- 影响范围：主要涉及 前端。
- 改动规模：+22 / -23 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/workspace/input-box.tsx；frontend/src/components/workspace/todo-list.tsx。

#### 170. feat: add animations

- 提交：`[9e72dc4](https://github.com/bytedance/deer-flow/commit/9e72dc4f6387d60c26b7da918657632bc1a6bce8)`
- 日期：2026-01-22
- 做了什么：新增或增强功能，主题是“add animations”。
- 影响范围：主要涉及 前端。
- 改动规模：+22 / -23 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/workspace/input-box.tsx；frontend/src/components/workspace/todo-list.tsx。

#### 171. feat: update skill settings

- 提交：`[37e2c3d](https://github.com/bytedance/deer-flow/commit/37e2c3d3c937cfbf7d980fa35c0d0a5251b2981f)`
- 日期：2026-01-22
- 做了什么：新增或增强功能，主题是“update skill settings”。
- 影响范围：主要涉及 前端。
- 改动规模：+75 / -25 行。
- 关键文件：frontend/TODO.md；frontend/src/components/workspace/input-box.tsx；frontend/src/components/workspace/settings/skill-settings-page.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts；frontend/src/core/i18n/locales/zh-CN.ts。

#### 172. feat: update skill settings

- 提交：`[b630e18](https://github.com/bytedance/deer-flow/commit/b630e1846a1bae16dd2ecfed0d75d2e1caa703b6)`
- 日期：2026-01-22
- 做了什么：新增或增强功能，主题是“update skill settings”。
- 影响范围：主要涉及 前端。
- 改动规模：+75 / -25 行。
- 关键文件：frontend/TODO.md；frontend/src/components/workspace/input-box.tsx；frontend/src/components/workspace/settings/skill-settings-page.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts；frontend/src/core/i18n/locales/zh-CN.ts。

#### 173. feat: add Todos

- 提交：`[1e4e51a](https://github.com/bytedance/deer-flow/commit/1e4e51a80cfa837a0983092e05cd3af4e37e012d)`
- 日期：2026-01-22
- 做了什么：新增或增强功能，主题是“add Todos”。
- 影响范围：主要涉及 前端。
- 改动规模：+230 / -70 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/layout.tsx；frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/ai-elements/prompt-input.tsx；frontend/src/components/workspace/artifacts/context.tsx；frontend/src/components/workspace/input-box.tsx；frontend/src/components/workspace/messages/message-group.tsx；frontend/src/components/workspace/messages/message-list.tsx；frontend/src/components/workspace/todo-list.tsx。

#### 174. feat: add Todos

- 提交：`[44850d9](https://github.com/bytedance/deer-flow/commit/44850d9a618f80e65236640ac2dd3b291649a679)`
- 日期：2026-01-22
- 做了什么：新增或增强功能，主题是“add Todos”。
- 影响范围：主要涉及 前端。
- 改动规模：+230 / -70 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/layout.tsx；frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/ai-elements/prompt-input.tsx；frontend/src/components/workspace/artifacts/context.tsx；frontend/src/components/workspace/input-box.tsx；frontend/src/components/workspace/messages/message-group.tsx；frontend/src/components/workspace/messages/message-list.tsx；frontend/src/components/workspace/todo-list.tsx。

#### 175. feat: add SSE and HTTP transport support for MCP servers

- 提交：`[5a45b9c](https://github.com/bytedance/deer-flow/commit/5a45b9c1311b2a934c281304fc6f36eb0344d9a0)`
- 日期：2026-01-21
- 做了什么：新增或增强功能，主题是“add SSE and HTTP transport support for MCP servers”。
- 影响范围：主要涉及 后端、其他模块、技能体系。
- 改动规模：+99 / -15 行。
- 关键文件：backend/debug.py；backend/src/agents/thread_state.py；backend/src/config/extensions_config.py；backend/src/gateway/routers/mcp.py；backend/src/mcp/client.py；backend/src/tools/tools.py；extensions_config.example.json；skills/public/frontend-design/SKILL.md。

#### 176. feat: add SSE and HTTP transport support for MCP servers

- 提交：`[87752ca](https://github.com/bytedance/deer-flow/commit/87752cafac610b14bf8e7db09ec23aaed381758a)`
- 日期：2026-01-21
- 做了什么：新增或增强功能，主题是“add SSE and HTTP transport support for MCP servers”。
- 影响范围：主要涉及 后端、其他模块、技能体系。
- 改动规模：+99 / -15 行。
- 关键文件：backend/debug.py；backend/src/agents/thread_state.py；backend/src/config/extensions_config.py；backend/src/gateway/routers/mcp.py；backend/src/mcp/client.py；backend/src/tools/tools.py；extensions_config.example.json；skills/public/frontend-design/SKILL.md。

#### 177. feat: use `resolvedTheme` instead of `systemTheme`

- 提交：`[fbe4d27](https://github.com/bytedance/deer-flow/commit/fbe4d27ddd76798975819d4cd57ea030ed42b3a0)`
- 日期：2026-01-21
- 做了什么：新增或增强功能，主题是“use `resolvedTheme` instead of `systemTheme`”。
- 影响范围：主要涉及 前端。
- 改动规模：+10 / -12 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/layout.tsx；frontend/src/components/workspace/settings/appearance-settings-page.tsx。

#### 178. feat: use `resolvedTheme` instead of `systemTheme`

- 提交：`[68b8083](https://github.com/bytedance/deer-flow/commit/68b80838260a4a1c4fb6905092de81e95d852ffa)`
- 日期：2026-01-21
- 做了什么：新增或增强功能，主题是“use `resolvedTheme` instead of `systemTheme`”。
- 影响范围：主要涉及 前端。
- 改动规模：+10 / -12 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/layout.tsx；frontend/src/components/workspace/settings/appearance-settings-page.tsx。

#### 179. feat: adjust colors

- 提交：`[e3d5b49](https://github.com/bytedance/deer-flow/commit/e3d5b4960f202289d475af1e84afb6c2b5265149)`
- 日期：2026-01-21
- 做了什么：新增或增强功能，主题是“adjust colors”。
- 影响范围：主要涉及 前端。
- 改动规模：+8 / -4 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/layout.tsx。

#### 180. feat: adjust colors

- 提交：`[ce4aa1e](https://github.com/bytedance/deer-flow/commit/ce4aa1e1548622e60746e40e7099e69fd5c1fb70)`
- 日期：2026-01-21
- 做了什么：新增或增强功能，主题是“adjust colors”。
- 影响范围：主要涉及 前端。
- 改动规模：+8 / -4 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/layout.tsx。

#### 181. feat: bring back the deer

- 提交：`[26587ee](https://github.com/bytedance/deer-flow/commit/26587ee970053c9ebc3ca0f2337edb5d877f1f73)`
- 日期：2026-01-21
- 做了什么：新增或增强功能，主题是“bring back the deer”。
- 影响范围：主要涉及 前端。
- 改动规模：+266 / -11 行。
- 关键文件：frontend/components.json；frontend/public/images/deer.svg；frontend/src/app/workspace/chats/[thread_id]/layout.tsx；frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/ui/flickering-grid.tsx；frontend/src/components/workspace/input-box.tsx。

#### 182. feat: bring back the deer

- 提交：`[1372dbe](https://github.com/bytedance/deer-flow/commit/1372dbefb27ca7ffb084b74f9fc88df74f9956e9)`
- 日期：2026-01-21
- 做了什么：新增或增强功能，主题是“bring back the deer”。
- 影响范围：主要涉及 前端。
- 改动规模：+266 / -11 行。
- 关键文件：frontend/components.json；frontend/public/images/deer.svg；frontend/src/app/workspace/chats/[thread_id]/layout.tsx；frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/ui/flickering-grid.tsx；frontend/src/components/workspace/input-box.tsx。

#### 183. feat: auto open artifact

- 提交：`[220fc1c](https://github.com/bytedance/deer-flow/commit/220fc1c48956b7e6a206f27bf33e5a38e2351368)`
- 日期：2026-01-21
- 做了什么：新增或增强功能，主题是“auto open artifact”。
- 影响范围：主要涉及 前端。
- 改动规模：+22 / -2 行。
- 关键文件：frontend/src/components/workspace/artifacts/context.tsx；frontend/src/components/workspace/messages/message-group.tsx。

#### 184. feat: auto open artifact

- 提交：`[4467b18](https://github.com/bytedance/deer-flow/commit/4467b1860f8ece2b4eebd7ad34a9634d2f21e617)`
- 日期：2026-01-21
- 做了什么：新增或增强功能，主题是“auto open artifact”。
- 影响范围：主要涉及 前端。
- 改动规模：+22 / -2 行。
- 关键文件：frontend/src/components/workspace/artifacts/context.tsx；frontend/src/components/workspace/messages/message-group.tsx。

#### 185. feat: add code editor

- 提交：`[48742d1](https://github.com/bytedance/deer-flow/commit/48742d1b59f5e7164a3f1ff82e931d764937b725)`
- 日期：2026-01-21
- 做了什么：新增或增强功能，主题是“add code editor”。
- 影响范围：主要涉及 前端。
- 改动规模：+759 / -3 行。
- 关键文件：frontend/package.json；frontend/pnpm-lock.yaml；frontend/src/components/ai-elements/code-editor.tsx；frontend/src/components/workspace/artifacts/artifact-file-detail.tsx。

#### 186. feat: add code editor

- 提交：`[6e024d6](https://github.com/bytedance/deer-flow/commit/6e024d6c8f716be47d79172e13f495f623087201)`
- 日期：2026-01-21
- 做了什么：新增或增强功能，主题是“add code editor”。
- 影响范围：主要涉及 前端。
- 改动规模：+759 / -3 行。
- 关键文件：frontend/package.json；frontend/pnpm-lock.yaml；frontend/src/components/ai-elements/code-editor.tsx；frontend/src/components/workspace/artifacts/artifact-file-detail.tsx。

#### 187. feat: enlarge shadow

- 提交：`[7c6eb4c](https://github.com/bytedance/deer-flow/commit/7c6eb4cc8b39dc27a062b3771a502f9df27fef37)`
- 日期：2026-01-21
- 做了什么：新增或增强功能，主题是“enlarge shadow”。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -1 行。
- 关键文件：frontend/src/components/ai-elements/artifact.tsx。

#### 188. feat: enlarge shadow

- 提交：`[4b7ee2b](https://github.com/bytedance/deer-flow/commit/4b7ee2bee2e8799a77f8f2f6f6abe5eb634b5fad)`
- 日期：2026-01-21
- 做了什么：新增或增强功能，主题是“enlarge shadow”。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -1 行。
- 关键文件：frontend/src/components/ai-elements/artifact.tsx。

#### 189. feat: make artifact "floating"

- 提交：`[d77b992](https://github.com/bytedance/deer-flow/commit/d77b9922a608ff5b554415e3b8f0af42b04b595c)`
- 日期：2026-01-21
- 做了什么：新增或增强功能，主题是“make artifact "floating"”。
- 影响范围：主要涉及 前端。
- 改动规模：+5 / -4 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/workspace/artifacts/artifact-file-detail.tsx。

#### 190. feat: make artifact "floating"

- 提交：`[28d724d](https://github.com/bytedance/deer-flow/commit/28d724d55ac75a7b45546608734f5369af877c6c)`
- 日期：2026-01-21
- 做了什么：新增或增强功能，主题是“make artifact "floating"”。
- 影响范围：主要涉及 前端。
- 改动规模：+5 / -4 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/workspace/artifacts/artifact-file-detail.tsx。

#### 191. feat: change color themes

- 提交：`[a2ca682](https://github.com/bytedance/deer-flow/commit/a2ca682b0c77b2440301071f01629f8c40d07370)`
- 日期：2026-01-21
- 做了什么：新增或增强功能，主题是“change color themes”。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -1 行。
- 关键文件：frontend/src/components/workspace/settings/settings-dialog.tsx。

#### 192. feat: change color themes

- 提交：`[adfce3c](https://github.com/bytedance/deer-flow/commit/adfce3c79c452cdba249dc09908c962f6cfa3e61)`
- 日期：2026-01-21
- 做了什么：新增或增强功能，主题是“change color themes”。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -1 行。
- 关键文件：frontend/src/components/workspace/settings/settings-dialog.tsx。

#### 193. feat: support settings

- 提交：`[10d253f](https://github.com/bytedance/deer-flow/commit/10d253f46105ee4026cedbba97c2431540fc6a4f)`
- 日期：2026-01-20
- 做了什么：新增或增强功能，主题是“support settings”。
- 影响范围：主要涉及 前端。
- 改动规模：+1355 / -217 行。
- 关键文件：frontend/package.json；frontend/pnpm-lock.yaml；frontend/src/components/ui/empty.tsx；frontend/src/components/ui/item.tsx；frontend/src/components/ui/switch.tsx；frontend/src/components/workspace/settings/acknowledge-page.tsx；frontend/src/components/workspace/settings/appearance-settings-page.tsx；frontend/src/components/workspace/settings/index.ts。

#### 194. feat: support settings

- 提交：`[1b70e00](https://github.com/bytedance/deer-flow/commit/1b70e0064209818612ff60bc67be733a3e4a7f0e)`
- 日期：2026-01-20
- 做了什么：新增或增强功能，主题是“support settings”。
- 影响范围：主要涉及 前端。
- 改动规模：+1355 / -217 行。
- 关键文件：frontend/package.json；frontend/pnpm-lock.yaml；frontend/src/components/ui/empty.tsx；frontend/src/components/ui/item.tsx；frontend/src/components/ui/switch.tsx；frontend/src/components/workspace/settings/acknowledge-page.tsx；frontend/src/components/workspace/settings/appearance-settings-page.tsx；frontend/src/components/workspace/settings/index.ts。

#### 195. feat: integrate todo middleware

- 提交：`[3191a38](https://github.com/bytedance/deer-flow/commit/3191a3845f21fbef0cadac807ef21d1fe7fe212c)`
- 日期：2026-01-20
- 做了什么：新增或增强功能，主题是“integrate todo middleware”。
- 影响范围：主要涉及 后端。
- 改动规模：+339 / -4 行。
- 关键文件：backend/docs/plan_mode_usage.md；backend/src/agents/lead_agent/agent.py。

#### 196. feat: integrate todo middleware

- 提交：`[7ead7c9](https://github.com/bytedance/deer-flow/commit/7ead7c93f8cfd90b6c2b77f77ee8b87ae477157e)`
- 日期：2026-01-20
- 做了什么：新增或增强功能，主题是“integrate todo middleware”。
- 影响范围：主要涉及 后端。
- 改动规模：+339 / -4 行。
- 关键文件：backend/docs/plan_mode_usage.md；backend/src/agents/lead_agent/agent.py。

#### 197. feat: enable public skills by default

- 提交：`[abc6c21](https://github.com/bytedance/deer-flow/commit/abc6c21b11bb49f709707def024226dbe90df0ec)`
- 日期：2026-01-20
- 做了什么：新增或增强功能，主题是“enable public skills by default”。
- 影响范围：主要涉及 后端、其他模块。
- 改动规模：+15 / -5 行。
- 关键文件：.gitignore；backend/Makefile；backend/src/config/extensions_config.py；backend/src/skills/loader.py。

#### 198. feat: enable public skills by default

- 提交：`[2d93110](https://github.com/bytedance/deer-flow/commit/2d931105d5bd1bc8161d6b164ec970b82690828d)`
- 日期：2026-01-20
- 做了什么：新增或增强功能，主题是“enable public skills by default”。
- 影响范围：主要涉及 后端、其他模块。
- 改动规模：+15 / -5 行。
- 关键文件：.gitignore；backend/Makefile；backend/src/config/extensions_config.py；backend/src/skills/loader.py。

#### 199. feat: save locale in cookies

- 提交：`[faba278](https://github.com/bytedance/deer-flow/commit/faba2784e1683ada212d5fda3088d1cf3018f888)`
- 日期：2026-01-20
- 做了什么：新增或增强功能，主题是“save locale in cookies”。
- 影响范围：主要涉及 前端。
- 改动规模：+131 / -38 行。
- 关键文件：frontend/src/app/layout.tsx；frontend/src/components/workspace/workspace-sidebar.tsx；frontend/src/core/i18n/context.tsx；frontend/src/core/i18n/cookies.ts；frontend/src/core/i18n/hooks.ts；frontend/src/core/i18n/index.ts；frontend/src/core/i18n/server.ts。

#### 200. feat: save locale in cookies

- 提交：`[dc8c1f4](https://github.com/bytedance/deer-flow/commit/dc8c1f4ed69e715485c1677630556c443663530f)`
- 日期：2026-01-20
- 做了什么：新增或增强功能，主题是“save locale in cookies”。
- 影响范围：主要涉及 前端。
- 改动规模：+131 / -38 行。
- 关键文件：frontend/src/app/layout.tsx；frontend/src/components/workspace/workspace-sidebar.tsx；frontend/src/core/i18n/context.tsx；frontend/src/core/i18n/cookies.ts；frontend/src/core/i18n/hooks.ts；frontend/src/core/i18n/index.ts；frontend/src/core/i18n/server.ts。

#### 201. feat: implement i18n

- 提交：`[32a45eb](https://github.com/bytedance/deer-flow/commit/32a45eb043e2f0023d2b18bf21a448e4a363dbe4)`
- 日期：2026-01-20
- 做了什么：新增或增强功能，主题是“implement i18n”。
- 影响范围：主要涉及 前端。
- 改动规模：+455 / -69 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/app/workspace/chats/page.tsx；frontend/src/components/workspace/artifacts/artifact-file-detail.tsx；frontend/src/components/workspace/artifacts/artifact-file-list.tsx；frontend/src/components/workspace/copy-button.tsx；frontend/src/components/workspace/input-box.tsx；frontend/src/components/workspace/messages/message-group.tsx；frontend/src/components/workspace/recent-chat-list.tsx。

#### 202. feat: implement i18n

- 提交：`[ac9ef30](https://github.com/bytedance/deer-flow/commit/ac9ef30780fb6819c40b231938d9f024ad2ffa32)`
- 日期：2026-01-20
- 做了什么：新增或增强功能，主题是“implement i18n”。
- 影响范围：主要涉及 前端。
- 改动规模：+455 / -69 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/app/workspace/chats/page.tsx；frontend/src/components/workspace/artifacts/artifact-file-detail.tsx；frontend/src/components/workspace/artifacts/artifact-file-list.tsx；frontend/src/components/workspace/copy-button.tsx；frontend/src/components/workspace/input-box.tsx；frontend/src/components/workspace/messages/message-group.tsx；frontend/src/components/workspace/recent-chat-list.tsx。

#### 203. feat: add skills api

- 提交：`[50810c8](https://github.com/bytedance/deer-flow/commit/50810c8212e122e3f5822ca23777e11747c3fa9d)`
- 日期：2026-01-20
- 做了什么：新增或增强功能，主题是“add skills api”。
- 影响范围：主要涉及 后端、其他模块、技能体系。
- 改动规模：+586 / -543 行。
- 关键文件：.gitignore；MCP_SETUP.md；backend/CLAUDE.md；backend/src/agents/lead_agent/prompt.py；backend/src/config/**init**.py；backend/src/config/app_config.py；backend/src/config/extensions_config.py；backend/src/config/mcp_config.py。

#### 204. feat: add skills api

- 提交：`[66df9b5](https://github.com/bytedance/deer-flow/commit/66df9b592771d40c908188a410df46bb6f6de814)`
- 日期：2026-01-20
- 做了什么：新增或增强功能，主题是“add skills api”。
- 影响范围：主要涉及 后端、其他模块、技能体系。
- 改动规模：+586 / -543 行。
- 关键文件：.gitignore；MCP_SETUP.md；backend/CLAUDE.md；backend/src/agents/lead_agent/prompt.py；backend/src/config/**init**.py；backend/src/config/app_config.py；backend/src/config/extensions_config.py；backend/src/config/mcp_config.py。

#### 205. feat: add MCP API endpoint and enhance API documentation

- 提交：`[8434cf4](https://github.com/bytedance/deer-flow/commit/8434cf4c605653d8149b766cd66d31952550af98)`
- 日期：2026-01-20
- 做了什么：新增或增强功能，主题是“add MCP API endpoint and enhance API documentation”。
- 影响范围：主要涉及 后端、其他模块。
- 改动规模：+307 / -11 行。
- 关键文件：backend/src/gateway/app.py；backend/src/gateway/routers/**init**.py；backend/src/gateway/routers/artifacts.py；backend/src/gateway/routers/mcp.py；backend/src/gateway/routers/models.py；nginx.conf。

#### 206. feat: add MCP API endpoint and enhance API documentation

- 提交：`[411d9d5](https://github.com/bytedance/deer-flow/commit/411d9d57c3024e4625b9fd89b3a210af5ed5807a)`
- 日期：2026-01-20
- 做了什么：新增或增强功能，主题是“add MCP API endpoint and enhance API documentation”。
- 影响范围：主要涉及 后端、其他模块。
- 改动规模：+307 / -11 行。
- 关键文件：backend/src/gateway/app.py；backend/src/gateway/routers/**init**.py；backend/src/gateway/routers/artifacts.py；backend/src/gateway/routers/mcp.py；backend/src/gateway/routers/models.py；nginx.conf。

#### 207. feat: add nginx reversed proxy (#15)

- 提交：`[513332b](https://github.com/bytedance/deer-flow/commit/513332b746bb1b356e947c6bcda6eb4803a084a8)`
- 日期：2026-01-19
- 做了什么：新增或增强功能，主题是“add nginx reversed proxy (#15)”。
- 影响范围：主要涉及 后端、文档、其他模块。
- 改动规模：+177 / -202 行。
- 关键文件：README.md；backend/Makefile；backend/src/gateway/app.py；backend/src/gateway/config.py；backend/src/gateway/routers/proxy.py；nginx.conf。

#### 208. feat: add nginx reversed proxy (#15)

- 提交：`[7978e05](https://github.com/bytedance/deer-flow/commit/7978e05dc1709ba28a82740799efc145b5925a9d)`
- 日期：2026-01-19
- 做了什么：新增或增强功能，主题是“add nginx reversed proxy (#15)”。
- 影响范围：主要涉及 后端、文档、其他模块。
- 改动规模：+177 / -202 行。
- 关键文件：README.md；backend/Makefile；backend/src/gateway/app.py；backend/src/gateway/config.py；backend/src/gateway/routers/proxy.py；nginx.conf。

#### 209. feat: use code block to display bash commands

- 提交：`[b8f9678](https://github.com/bytedance/deer-flow/commit/b8f9678d074fb382d308aa257a446f339dfaff8b)`
- 日期：2026-01-19
- 做了什么：新增或增强功能，主题是“use code block to display bash commands”。
- 影响范围：主要涉及 前端。
- 改动规模：+9 / -3 行。
- 关键文件：frontend/src/components/ai-elements/code-block.tsx；frontend/src/components/workspace/messages/message-group.tsx。

#### 210. feat: use code block to display bash commands

- 提交：`[5d6162d](https://github.com/bytedance/deer-flow/commit/5d6162d0061a9db93bea4a1e93753f23a6b822c8)`
- 日期：2026-01-19
- 做了什么：新增或增强功能，主题是“use code block to display bash commands”。
- 影响范围：主要涉及 前端。
- 改动规模：+9 / -3 行。
- 关键文件：frontend/src/components/ai-elements/code-block.tsx；frontend/src/components/workspace/messages/message-group.tsx。

#### 211. feat: support NEXT_PUBLIC_LANGGRAPH_BASE_URL

- 提交：`[fb265f2](https://github.com/bytedance/deer-flow/commit/fb265f2b1f970122883e538d0967a844462d336c)`
- 日期：2026-01-19
- 做了什么：新增或增强功能，主题是“support NEXT_PUBLIC_LANGGRAPH_BASE_URL”。
- 影响范围：主要涉及 前端。
- 改动规模：+12 / -2 行。
- 关键文件：frontend/src/core/api/api-client.ts；frontend/src/core/config/index.ts；frontend/src/env.js。

#### 212. feat: support NEXT_PUBLIC_LANGGRAPH_BASE_URL

- 提交：`[58b5c2f](https://github.com/bytedance/deer-flow/commit/58b5c2fcd553ab58f717d0abc8e605519b172172)`
- 日期：2026-01-19
- 做了什么：新增或增强功能，主题是“support NEXT_PUBLIC_LANGGRAPH_BASE_URL”。
- 影响范围：主要涉及 前端。
- 改动规模：+12 / -2 行。
- 关键文件：frontend/src/core/api/api-client.ts；frontend/src/core/config/index.ts；frontend/src/env.js。

#### 213. feat: add ToggleGroup

- 提交：`[d7dfffa](https://github.com/bytedance/deer-flow/commit/d7dfffad9044609900af7beb0fc2dd4bb6750a8d)`
- 日期：2026-01-19
- 做了什么：新增或增强功能，主题是“add ToggleGroup”。
- 影响范围：主要涉及 前端。
- 改动规模：+316 / -103 行。
- 关键文件：frontend/package.json；frontend/pnpm-lock.yaml；frontend/src/components/ui/toggle-group.tsx；frontend/src/components/ui/toggle.tsx；frontend/src/components/workspace/artifacts/artifact-file-detail.tsx；frontend/src/components/workspace/artifacts/file-viewer.tsx；frontend/src/core/artifacts/hooks.ts；frontend/src/core/artifacts/loader.ts。

#### 214. feat: add ToggleGroup

- 提交：`[24ca87d](https://github.com/bytedance/deer-flow/commit/24ca87d650073890a8a1b5759587e79b1dd9b913)`
- 日期：2026-01-19
- 做了什么：新增或增强功能，主题是“add ToggleGroup”。
- 影响范围：主要涉及 前端。
- 改动规模：+316 / -103 行。
- 关键文件：frontend/package.json；frontend/pnpm-lock.yaml；frontend/src/components/ui/toggle-group.tsx；frontend/src/components/ui/toggle.tsx；frontend/src/components/workspace/artifacts/artifact-file-detail.tsx；frontend/src/components/workspace/artifacts/file-viewer.tsx；frontend/src/core/artifacts/hooks.ts；frontend/src/core/artifacts/loader.ts。

#### 215. feat: add MCP (Model Context Protocol) support

- 提交：`[1171598](https://github.com/bytedance/deer-flow/commit/1171598b2f93a467d834dcebe1529c951c4c486a)`
- 日期：2026-01-19
- 做了什么：新增或增强功能，主题是“add MCP (Model Context Protocol) support”。
- 影响范围：主要涉及 后端、其他模块、文档。
- 改动规模：+1044 / -5 行。
- 关键文件：.gitignore；MCP_SETUP.md；README.md；backend/CLAUDE.md；backend/debug.py；backend/pyproject.toml；backend/src/agents/middlewares/clarification_middleware.py；backend/src/config/**init**.py。

#### 216. feat: add MCP (Model Context Protocol) support

- 提交：`[74d4a16](https://github.com/bytedance/deer-flow/commit/74d4a16492a6523f2b6eb47d2a98898f7b398e3e)`
- 日期：2026-01-19
- 做了什么：新增或增强功能，主题是“add MCP (Model Context Protocol) support”。
- 影响范围：主要涉及 后端、其他模块、文档。
- 改动规模：+1044 / -5 行。
- 关键文件：.gitignore；MCP_SETUP.md；README.md；backend/CLAUDE.md；backend/debug.py；backend/pyproject.toml；backend/src/agents/middlewares/clarification_middleware.py；backend/src/config/**init**.py。

#### 217. feat: support dynamic loading models

- 提交：`[541586d](https://github.com/bytedance/deer-flow/commit/541586dc66041a518f1af469bd4e28ffd7113f0f)`
- 日期：2026-01-19
- 做了什么：新增或增强功能，主题是“support dynamic loading models”。
- 影响范围：主要涉及 前端。
- 改动规模：+49 / -23 行。
- 关键文件：frontend/src/components/workspace/input-box.tsx；frontend/src/core/models/api.ts；frontend/src/core/models/hooks.ts；frontend/src/core/models/index.ts；frontend/src/core/models/types.ts。

#### 218. feat: support dynamic loading models

- 提交：`[21f35b1](https://github.com/bytedance/deer-flow/commit/21f35b1d3c4dd227a65a728f6fcb1b072b7adf96)`
- 日期：2026-01-19
- 做了什么：新增或增强功能，主题是“support dynamic loading models”。
- 影响范围：主要涉及 前端。
- 改动规模：+49 / -23 行。
- 关键文件：frontend/src/components/workspace/input-box.tsx；frontend/src/core/models/api.ts；frontend/src/core/models/hooks.ts；frontend/src/core/models/index.ts；frontend/src/core/models/types.ts。

#### 219. feat: implement summarization (#14)

- 提交：`[9a3eaea](https://github.com/bytedance/deer-flow/commit/9a3eaea54ef5e0d7c0c0b56e417b13a8ee5f7d89)`
- 日期：2026-01-19
- 做了什么：新增或增强功能，主题是“implement summarization (#14)”。
- 影响范围：主要涉及 后端、配置。
- 改动规模：+555 / -5 行。
- 关键文件：backend/CLAUDE.md；backend/docs/TODO.md；backend/docs/summarization.md；backend/src/agents/lead_agent/agent.py；backend/src/agents/lead_agent/prompt.py；backend/src/config/app_config.py；backend/src/config/summarization_config.py；config.example.yaml。

#### 220. feat: implement summarization (#14)

- 提交：`[f0a2381](https://github.com/bytedance/deer-flow/commit/f0a2381bd5f42972362ffe3f32349b6b78ef229b)`
- 日期：2026-01-19
- 做了什么：新增或增强功能，主题是“implement summarization (#14)”。
- 影响范围：主要涉及 后端、配置。
- 改动规模：+555 / -5 行。
- 关键文件：backend/CLAUDE.md；backend/docs/TODO.md；backend/docs/summarization.md；backend/src/agents/lead_agent/agent.py；backend/src/agents/lead_agent/prompt.py；backend/src/config/app_config.py；backend/src/config/summarization_config.py；config.example.yaml。

#### 221. feat: add NEXT_PUBLIC_BACKEND_BASE_URL

- 提交：`[f3f66ee](https://github.com/bytedance/deer-flow/commit/f3f66ee9248e832cc9e76fa12e70113731ca33f5)`
- 日期：2026-01-19
- 做了什么：新增或增强功能，主题是“add NEXT_PUBLIC_BACKEND_BASE_URL”。
- 影响范围：主要涉及 前端。
- 改动规模：+19 / -10 行。
- 关键文件：frontend/.env.example；frontend/src/core/api/api-client.ts；frontend/src/core/artifacts/utils.ts；frontend/src/core/config/index.ts；frontend/src/env.js。

#### 222. feat: add NEXT_PUBLIC_BACKEND_BASE_URL

- 提交：`[9d18e4e](https://github.com/bytedance/deer-flow/commit/9d18e4e12dd1c3762dfc3c0a28fd203b026892ed)`
- 日期：2026-01-19
- 做了什么：新增或增强功能，主题是“add NEXT_PUBLIC_BACKEND_BASE_URL”。
- 影响范围：主要涉及 前端。
- 改动规模：+19 / -10 行。
- 关键文件：frontend/.env.example；frontend/src/core/api/api-client.ts；frontend/src/core/artifacts/utils.ts；frontend/src/core/config/index.ts；frontend/src/env.js。

#### 223. feat: make `new chat` always on top

- 提交：`[d8391ca](https://github.com/bytedance/deer-flow/commit/d8391ca3ea0534698a3eec5c7e412f1e69edfaae)`
- 日期：2026-01-19
- 做了什么：新增或增强功能，主题是“make `new chat` always on top”。
- 影响范围：主要涉及 前端。
- 改动规模：+48 / -35 行。
- 关键文件：frontend/src/components/workspace/workspace-header.tsx；frontend/src/components/workspace/workspace-nav-menu.tsx。

#### 224. feat: make `new chat` always on top

- 提交：`[b431567](https://github.com/bytedance/deer-flow/commit/b4315676667b4ccbb81c06bd2e52e0fe7540aa43)`
- 日期：2026-01-19
- 做了什么：新增或增强功能，主题是“make `new chat` always on top”。
- 影响范围：主要涉及 前端。
- 改动规模：+48 / -35 行。
- 关键文件：frontend/src/components/workspace/workspace-header.tsx；frontend/src/components/workspace/workspace-nav-menu.tsx。

#### 225. feat: support clarification tool

- 提交：`[dc04042](https://github.com/bytedance/deer-flow/commit/dc04042b53aa104ffb990f6a03a00ba6cc45ac56)`
- 日期：2026-01-18
- 做了什么：新增或增强功能，主题是“support clarification tool”。
- 影响范围：主要涉及 前端。
- 改动规模：+11 / -1 行。
- 关键文件：frontend/src/components/workspace/messages/message-group.tsx。

#### 226. feat: support clarification tool

- 提交：`[5624b0c](https://github.com/bytedance/deer-flow/commit/5624b0cd382f391696f3534caba24a1030a29c10)`
- 日期：2026-01-18
- 做了什么：新增或增强功能，主题是“support clarification tool”。
- 影响范围：主要涉及 前端。
- 改动规模：+11 / -1 行。
- 关键文件：frontend/src/components/workspace/messages/message-group.tsx。

#### 227. feat: re-implement message group

- 提交：`[69b2250](https://github.com/bytedance/deer-flow/commit/69b225082b9c1490a826bd973df83f0aa7f383a6)`
- 日期：2026-01-18
- 做了什么：新增或增强功能，主题是“re-implement message group”。
- 影响范围：主要涉及 前端。
- 改动规模：+131 / -105 行。
- 关键文件：frontend/src/components/ai-elements/chain-of-thought.tsx；frontend/src/components/ai-elements/code-block.tsx；frontend/src/components/workspace/flip-display.tsx；frontend/src/components/workspace/messages/message-group.tsx。

#### 228. feat: re-implement message group

- 提交：`[aa44566](https://github.com/bytedance/deer-flow/commit/aa44566fefa5c267cec5c0c00a9daf6915211ee1)`
- 日期：2026-01-18
- 做了什么：新增或增强功能，主题是“re-implement message group”。
- 影响范围：主要涉及 前端。
- 改动规模：+131 / -105 行。
- 关键文件：frontend/src/components/ai-elements/chain-of-thought.tsx；frontend/src/components/ai-elements/code-block.tsx；frontend/src/components/workspace/flip-display.tsx；frontend/src/components/workspace/messages/message-group.tsx。

#### 229. feat: add clarification feature (#13)

- 提交：`[645923c](https://github.com/bytedance/deer-flow/commit/645923c3bcd01cbccd2e05ac70c1b862ec65f349)`
- 日期：2026-01-18
- 做了什么：新增或增强功能，主题是“add clarification feature (#13)”。
- 影响范围：主要涉及 后端。
- 改动规模：+416 / -9 行。
- 关键文件：backend/src/agents/lead_agent/agent.py；backend/src/agents/lead_agent/prompt.py；backend/src/agents/middlewares/clarification_middleware.py；backend/src/gateway/app.py；backend/src/sandbox/local/local_sandbox.py；backend/src/tools/builtins/**init**.py；backend/src/tools/builtins/clarification_tool.py；backend/src/tools/tools.py。

#### 230. feat: add clarification feature (#13)

- 提交：`[e1a8d54](https://github.com/bytedance/deer-flow/commit/e1a8d544b630430fbab852efb4f9ade63fc4af6f)`
- 日期：2026-01-18
- 做了什么：新增或增强功能，主题是“add clarification feature (#13)”。
- 影响范围：主要涉及 后端。
- 改动规模：+416 / -9 行。
- 关键文件：backend/src/agents/lead_agent/agent.py；backend/src/agents/lead_agent/prompt.py；backend/src/agents/middlewares/clarification_middleware.py；backend/src/gateway/app.py；backend/src/sandbox/local/local_sandbox.py；backend/src/tools/builtins/**init**.py；backend/src/tools/builtins/clarification_tool.py；backend/src/tools/tools.py。

#### 231. feat: support SSE write_file(0

- 提交：`[dd80348](https://github.com/bytedance/deer-flow/commit/dd80348b7640193ac87eb5b26757db52f4797239)`
- 日期：2026-01-18
- 做了什么：新增或增强功能，主题是“support SSE write_file(0”。
- 影响范围：主要涉及 前端。
- 改动规模：+293 / -178 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/app/workspace/layout.tsx；frontend/src/components/ai-elements/artifact.tsx；frontend/src/components/ai-elements/code-block.tsx；frontend/src/components/workspace/artifacts/artifact-file-detail.tsx；frontend/src/components/workspace/artifacts/file-viewer.tsx；frontend/src/components/workspace/messages/context.ts；frontend/src/components/workspace/messages/message-group.tsx。

#### 232. feat: support SSE write_file(0

- 提交：`[ec1964c](https://github.com/bytedance/deer-flow/commit/ec1964c82912d6e8166c0799910761fe78094eda)`
- 日期：2026-01-18
- 做了什么：新增或增强功能，主题是“support SSE write_file(0”。
- 影响范围：主要涉及 前端。
- 改动规模：+293 / -178 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/app/workspace/layout.tsx；frontend/src/components/ai-elements/artifact.tsx；frontend/src/components/ai-elements/code-block.tsx；frontend/src/components/workspace/artifacts/artifact-file-detail.tsx；frontend/src/components/workspace/artifacts/file-viewer.tsx；frontend/src/components/workspace/messages/context.ts；frontend/src/components/workspace/messages/message-group.tsx。

#### 233. feat: implement lazy sandbox and thread data initialization (#11)

- 提交：`[1397f30](https://github.com/bytedance/deer-flow/commit/1397f30f2499d136bbbd9e9d5c597b2dad8912f5)`
- 日期：2026-01-18
- 做了什么：新增或增强功能，主题是“implement lazy sandbox and thread data initialization (#11)”。
- 影响范围：主要涉及 后端。
- 改动规模：+104 / -13 行。
- 关键文件：backend/src/agents/middlewares/thread_data_middleware.py；backend/src/community/aio_sandbox/aio_sandbox_provider.py；backend/src/sandbox/middleware.py；backend/src/sandbox/tools.py。

#### 234. feat: implement lazy sandbox and thread data initialization (#11)

- 提交：`[5f4c58a](https://github.com/bytedance/deer-flow/commit/5f4c58aa8231aaf55cd32f141058f2670bb7bb13)`
- 日期：2026-01-18
- 做了什么：新增或增强功能，主题是“implement lazy sandbox and thread data initialization (#11)”。
- 影响范围：主要涉及 后端。
- 改动规模：+104 / -13 行。
- 关键文件：backend/src/agents/middlewares/thread_data_middleware.py；backend/src/community/aio_sandbox/aio_sandbox_provider.py；backend/src/sandbox/middleware.py；backend/src/sandbox/tools.py。

#### 235. feat: add recursion_limit

- 提交：`[8f0bd82](https://github.com/bytedance/deer-flow/commit/8f0bd828d5cc99d692e23de8d9441a74c65e362e)`
- 日期：2026-01-18
- 做了什么：新增或增强功能，主题是“add recursion_limit”。
- 影响范围：主要涉及 前端。
- 改动规模：+3 / -0 行。
- 关键文件：frontend/src/core/threads/hooks.ts。

#### 236. feat: add recursion_limit

- 提交：`[41a22fd](https://github.com/bytedance/deer-flow/commit/41a22fde9107c1ec263ebf48a95ccbcde15ca4ea)`
- 日期：2026-01-18
- 做了什么：新增或增强功能，主题是“add recursion_limit”。
- 影响范围：主要涉及 前端。
- 改动规模：+3 / -0 行。
- 关键文件：frontend/src/core/threads/hooks.ts。

#### 237. feat: enhance message display

- 提交：`[23dc64f](https://github.com/bytedance/deer-flow/commit/23dc64fab12c1b632c1608f684b013b88864d06e)`
- 日期：2026-01-18
- 做了什么：新增或增强功能，主题是“enhance message display”。
- 影响范围：主要涉及 前端。
- 改动规模：+115 / -66 行。
- 关键文件：frontend/src/components/workspace/messages/message-list-item.tsx；frontend/src/components/workspace/messages/message-list.tsx；frontend/src/core/messages/utils.ts。

#### 238. feat: enhance message display

- 提交：`[9605cec](https://github.com/bytedance/deer-flow/commit/9605cec6d379514feb42c7164ce1a730ddd58cbc)`
- 日期：2026-01-18
- 做了什么：新增或增强功能，主题是“enhance message display”。
- 影响范围：主要涉及 前端。
- 改动规模：+115 / -66 行。
- 关键文件：frontend/src/components/workspace/messages/message-list-item.tsx；frontend/src/components/workspace/messages/message-list.tsx；frontend/src/core/messages/utils.ts。

#### 239. feat: dim the placeholder

- 提交：`[59683fc](https://github.com/bytedance/deer-flow/commit/59683fc12e5dc408405cef7b278e31846f3efdc8)`
- 日期：2026-01-18
- 做了什么：新增或增强功能，主题是“dim the placeholder”。
- 影响范围：主要涉及 前端。
- 改动规模：+6 / -6 行。
- 关键文件：frontend/src/components/ui/textarea.tsx。

#### 240. feat: dim the placeholder

- 提交：`[f924272](https://github.com/bytedance/deer-flow/commit/f9242727c75360319d8e5c786de82a0ee79a057a)`
- 日期：2026-01-18
- 做了什么：新增或增强功能，主题是“dim the placeholder”。
- 影响范围：主要涉及 前端。
- 改动规模：+6 / -6 行。
- 关键文件：frontend/src/components/ui/textarea.tsx。

#### 241. feat: remove model icon

- 提交：`[92fc19a](https://github.com/bytedance/deer-flow/commit/92fc19a3aa50a9f31642e8a405e506de598886d4)`
- 日期：2026-01-18
- 做了什么：新增或增强功能，主题是“remove model icon”。
- 影响范围：主要涉及 前端。
- 改动规模：+8 / -9 行。
- 关键文件：frontend/src/components/ai-elements/model-selector.tsx；frontend/src/components/ai-elements/prompt-input.tsx；frontend/src/components/workspace/input-box.tsx。

#### 242. feat: remove model icon

- 提交：`[449f04f](https://github.com/bytedance/deer-flow/commit/449f04fc4404ab63ef084102f561b9a6dbddcdf0)`
- 日期：2026-01-18
- 做了什么：新增或增强功能，主题是“remove model icon”。
- 影响范围：主要涉及 前端。
- 改动规模：+8 / -9 行。
- 关键文件：frontend/src/components/ai-elements/model-selector.tsx；frontend/src/components/ai-elements/prompt-input.tsx；frontend/src/components/workspace/input-box.tsx。

#### 243. feat: fix todos (#9)

- 提交：`[aa03041](https://github.com/bytedance/deer-flow/commit/aa030410fc56ff55500fd69286fbb11c94e51eb9)`
- 日期：2026-01-17
- 做了什么：新增或增强功能，主题是“fix todos (#9)”。
- 影响范围：主要涉及 后端。
- 改动规模：+320 / -227 行。
- 关键文件：backend/SETUP.md；backend/TODO.md；backend/docs/BACKEND_TODO.md；backend/docs/SETUP.md；backend/docs/TODO.md；backend/src/config/app_config.py；backend/src/sandbox/exceptions.py；backend/src/sandbox/local/local_sandbox_provider.py。

#### 244. feat: fix todos (#9)

- 提交：`[3261273](https://github.com/bytedance/deer-flow/commit/3261273ee34550f2cc048cf0c9baf4169aa8b1aa)`
- 日期：2026-01-17
- 做了什么：新增或增强功能，主题是“fix todos (#9)”。
- 影响范围：主要涉及 后端。
- 改动规模：+320 / -227 行。
- 关键文件：backend/SETUP.md；backend/TODO.md；backend/docs/BACKEND_TODO.md；backend/docs/SETUP.md；backend/docs/TODO.md；backend/src/config/app_config.py；backend/src/sandbox/exceptions.py；backend/src/sandbox/local/local_sandbox_provider.py。

#### 245. feat: change back to 60px height

- 提交：`[3f1f6af](https://github.com/bytedance/deer-flow/commit/3f1f6af30c1d989f04b47e38dd189784cf8821f6)`
- 日期：2026-01-17
- 做了什么：新增或增强功能，主题是“change back to 60px height”。
- 影响范围：主要涉及 前端。
- 改动规模：+2 / -2 行。
- 关键文件：frontend/src/components/workspace/workspace-header.tsx。

#### 246. feat: change back to 60px height

- 提交：`[fa07e9e](https://github.com/bytedance/deer-flow/commit/fa07e9e903777cedc149820648caaef51e1af841)`
- 日期：2026-01-17
- 做了什么：新增或增强功能，主题是“change back to 60px height”。
- 影响范围：主要涉及 前端。
- 改动规模：+2 / -2 行。
- 关键文件：frontend/src/components/workspace/workspace-header.tsx。

#### 247. feat: use default sidebar width

- 提交：`[7ea7a78](https://github.com/bytedance/deer-flow/commit/7ea7a7864ec2099356d901017b4921a1583f6757)`
- 日期：2026-01-17
- 做了什么：新增或增强功能，主题是“use default sidebar width”。
- 影响范围：主要涉及 前端。
- 改动规模：+0 / -5 行。
- 关键文件：frontend/src/app/workspace/layout.tsx。

#### 248. feat: use default sidebar width

- 提交：`[d0988b3](https://github.com/bytedance/deer-flow/commit/d0988b3cf01f4a4bb1a3df3582e58f47cf4c61e7)`
- 日期：2026-01-17
- 做了什么：新增或增强功能，主题是“use default sidebar width”。
- 影响范围：主要涉及 前端。
- 改动规模：+0 / -5 行。
- 关键文件：frontend/src/app/workspace/layout.tsx。

#### 249. feat: refine theme

- 提交：`[5cda2b9](https://github.com/bytedance/deer-flow/commit/5cda2b90fcb5640d64d5513fd594b86ea716f4a3)`
- 日期：2026-01-17
- 做了什么：新增或增强功能，主题是“refine theme”。
- 影响范围：主要涉及 前端。
- 改动规模：+6 / -6 行。
- 关键文件：frontend/src/components/workspace/input-box.tsx；frontend/src/styles/globals.css。

#### 250. feat: refine theme

- 提交：`[36b7ac0](https://github.com/bytedance/deer-flow/commit/36b7ac0ce49f8cadf605fc93f36e548729d87933)`
- 日期：2026-01-17
- 做了什么：新增或增强功能，主题是“refine theme”。
- 影响范围：主要涉及 前端。
- 改动规模：+6 / -6 行。
- 关键文件：frontend/src/components/workspace/input-box.tsx；frontend/src/styles/globals.css。

#### 251. feat: adjust dark theme

- 提交：`[70cd664](https://github.com/bytedance/deer-flow/commit/70cd664d3fdeac4860b570a0be547dd0cf39fd04)`
- 日期：2026-01-17
- 做了什么：新增或增强功能，主题是“adjust dark theme”。
- 影响范围：主要涉及 前端。
- 改动规模：+3 / -3 行。
- 关键文件：frontend/src/styles/globals.css。

#### 252. feat: adjust dark theme

- 提交：`[00fc705](https://github.com/bytedance/deer-flow/commit/00fc70536ee9910f539ccc96d5d59fb522fe0c11)`
- 日期：2026-01-17
- 做了什么：新增或增强功能，主题是“adjust dark theme”。
- 影响范围：主要涉及 前端。
- 改动规模：+3 / -3 行。
- 关键文件：frontend/src/styles/globals.css。

#### 253. feat: the DeerFlow theme is back

- 提交：`[32a77cc](https://github.com/bytedance/deer-flow/commit/32a77cce8425cb79dcaf6a665eae7b0e2fd6dcbf)`
- 日期：2026-01-17
- 做了什么：新增或增强功能，主题是“the DeerFlow theme is back”。
- 影响范围：主要涉及 前端。
- 改动规模：+22 / -22 行。
- 关键文件：frontend/src/styles/globals.css。

#### 254. feat: the DeerFlow theme is back

- 提交：`[6c9b0f2](https://github.com/bytedance/deer-flow/commit/6c9b0f275b86f3fbd0549c7b708dbad515f9c126)`
- 日期：2026-01-17
- 做了什么：新增或增强功能，主题是“the DeerFlow theme is back”。
- 影响范围：主要涉及 前端。
- 改动规模：+22 / -22 行。
- 关键文件：frontend/src/styles/globals.css。

#### 255. feat: change light theme

- 提交：`[094553e](https://github.com/bytedance/deer-flow/commit/094553ea42dc18a807fcc248ef7008c2e964936c)`
- 日期：2026-01-17
- 做了什么：新增或增强功能，主题是“change light theme”。
- 影响范围：主要涉及 前端。
- 改动规模：+10 / -10 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/ui/input-group.tsx；frontend/src/components/ui/tooltip.tsx；frontend/src/components/workspace/artifacts/artifact-file-detail.tsx；frontend/src/styles/globals.css。

#### 256. feat: change light theme

- 提交：`[79d87de](https://github.com/bytedance/deer-flow/commit/79d87de5237c566288439260ec19375728eccd4e)`
- 日期：2026-01-17
- 做了什么：新增或增强功能，主题是“change light theme”。
- 影响范围：主要涉及 前端。
- 改动规模：+10 / -10 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/ui/input-group.tsx；frontend/src/components/ui/tooltip.tsx；frontend/src/components/workspace/artifacts/artifact-file-detail.tsx；frontend/src/styles/globals.css。

#### 257. feat: welcome, again

- 提交：`[2bc5f30](https://github.com/bytedance/deer-flow/commit/2bc5f30c4dbdf4412bf5a622cd3131cd5c242138)`
- 日期：2026-01-17
- 做了什么：新增或增强功能，主题是“welcome, again”。
- 影响范围：主要涉及 前端。
- 改动规模：+54 / -10 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/workspace/input-box.tsx；frontend/src/components/workspace/welcome.tsx。

#### 258. feat: welcome, again

- 提交：`[a6e5ebe](https://github.com/bytedance/deer-flow/commit/a6e5ebe8985f8e625e8c4cffb0766b5ada3056c8)`
- 日期：2026-01-17
- 做了什么：新增或增强功能，主题是“welcome, again”。
- 影响范围：主要涉及 前端。
- 改动规模：+54 / -10 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/workspace/input-box.tsx；frontend/src/components/workspace/welcome.tsx。

#### 259. feat: add reasoning check to message list item rendering

- 提交：`[06068dd](https://github.com/bytedance/deer-flow/commit/06068dd07b50408b8207386abec89e544deee36f)`
- 日期：2026-01-17
- 做了什么：新增或增强功能，主题是“add reasoning check to message list item rendering”。
- 影响范围：主要涉及 前端。
- 改动规模：+8 / -4 行。
- 关键文件：frontend/src/components/workspace/messages/message-list-item.tsx；frontend/src/core/messages/utils.ts。

#### 260. feat: add reasoning check to message list item rendering

- 提交：`[0ea448a](https://github.com/bytedance/deer-flow/commit/0ea448a220356f94da24a3e1acbc1603b42fa19c)`
- 日期：2026-01-17
- 做了什么：新增或增强功能，主题是“add reasoning check to message list item rendering”。
- 影响范围：主要涉及 前端。
- 改动规模：+8 / -4 行。
- 关键文件：frontend/src/components/workspace/messages/message-list-item.tsx；frontend/src/core/messages/utils.ts。

#### 261. feat: pull up the input box when creating new thread

- 提交：`[b705a44](https://github.com/bytedance/deer-flow/commit/b705a44f3c9f562c49d3887e04e8504471fa2757)`
- 日期：2026-01-17
- 做了什么：新增或增强功能，主题是“pull up the input box when creating new thread”。
- 影响范围：主要涉及 前端。
- 改动规模：+4 / -1 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx。

#### 262. feat: pull up the input box when creating new thread

- 提交：`[cb54b5d](https://github.com/bytedance/deer-flow/commit/cb54b5dffa70011822e23b64c4eeeddda0b73649)`
- 日期：2026-01-17
- 做了什么：新增或增强功能，主题是“pull up the input box when creating new thread”。
- 影响范围：主要涉及 前端。
- 改动规模：+4 / -1 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx。

#### 263. feat:enhance  focus status

- 提交：`[85d9baf](https://github.com/bytedance/deer-flow/commit/85d9baf2b14bf7452d79540ea24758442e66eed3)`
- 日期：2026-01-17
- 做了什么：新增或增强功能，主题是“enhance  focus status”。
- 影响范围：主要涉及 前端。
- 改动规模：+26 / -26 行。
- 关键文件：frontend/src/components/ui/input-group.tsx。

#### 264. feat:enhance  focus status

- 提交：`[9bfa49a](https://github.com/bytedance/deer-flow/commit/9bfa49ae0751865604726fd4e1e3e02dbb054a0b)`
- 日期：2026-01-17
- 做了什么：新增或增强功能，主题是“enhance  focus status”。
- 影响范围：主要涉及 前端。
- 改动规模：+26 / -26 行。
- 关键文件：frontend/src/components/ui/input-group.tsx。

#### 265. feat: redesign step counter

- 提交：`[a64b0d2](https://github.com/bytedance/deer-flow/commit/a64b0d226bab3e8c565df4df0c5db8f34508207d)`
- 日期：2026-01-17
- 做了什么：新增或增强功能，主题是“redesign step counter”。
- 影响范围：主要涉及 前端。
- 改动规模：+10 / -8 行。
- 关键文件：frontend/src/components/workspace/messages/message-group.tsx。

#### 266. feat: redesign step counter

- 提交：`[62921ec](https://github.com/bytedance/deer-flow/commit/62921ec96a20635f611e774ade74c9149dcd32e1)`
- 日期：2026-01-17
- 做了什么：新增或增强功能，主题是“redesign step counter”。
- 影响范围：主要涉及 前端。
- 改动规模：+10 / -8 行。
- 关键文件：frontend/src/components/workspace/messages/message-group.tsx。

#### 267. feat: extract ThreadTitle component

- 提交：`[d8f0f91](https://github.com/bytedance/deer-flow/commit/d8f0f912383eded63738a7e5c74b18f9b89019af)`
- 日期：2026-01-17
- 做了什么：新增或增强功能，主题是“extract ThreadTitle component”。
- 影响范围：主要涉及 前端。
- 改动规模：+15 / -7 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/workspace/thread-title.tsx。

#### 268. feat: extract ThreadTitle component

- 提交：`[7b33214](https://github.com/bytedance/deer-flow/commit/7b33214a0526152262a419f1249fa2910d4dd245)`
- 日期：2026-01-17
- 做了什么：新增或增强功能，主题是“extract ThreadTitle component”。
- 影响范围：主要涉及 前端。
- 改动规模：+15 / -7 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/workspace/thread-title.tsx。

#### 269. feat: integrated with artifacts in states

- 提交：`[f1c6991](https://github.com/bytedance/deer-flow/commit/f1c6991194ed9d89c1e2bc575bc0e3bf1a192e85)`
- 日期：2026-01-17
- 做了什么：新增或增强功能，主题是“integrated with artifacts in states”。
- 影响范围：主要涉及 前端。
- 改动规模：+118 / -70 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/ai-elements/artifact.tsx；frontend/src/components/ui/select.tsx；frontend/src/components/workspace/artifacts/artifact-file-detail.tsx；frontend/src/components/workspace/artifacts/artifact-file-list.tsx；frontend/src/components/workspace/artifacts/context.tsx；frontend/src/core/artifacts/utils.ts；frontend/src/core/threads/types.ts。

#### 270. feat: integrated with artifacts in states

- 提交：`[9a3f728](https://github.com/bytedance/deer-flow/commit/9a3f72869c31d598adad600b05486ebd50dd74c1)`
- 日期：2026-01-17
- 做了什么：新增或增强功能，主题是“integrated with artifacts in states”。
- 影响范围：主要涉及 前端。
- 改动规模：+118 / -70 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/ai-elements/artifact.tsx；frontend/src/components/ui/select.tsx；frontend/src/components/workspace/artifacts/artifact-file-detail.tsx；frontend/src/components/workspace/artifacts/artifact-file-list.tsx；frontend/src/components/workspace/artifacts/context.tsx；frontend/src/core/artifacts/utils.ts；frontend/src/core/threads/types.ts。

#### 271. feat: remove ring

- 提交：`[384353d](https://github.com/bytedance/deer-flow/commit/384353d613b2a9edc5657b50615f8d4951583747)`
- 日期：2026-01-17
- 做了什么：新增或增强功能，主题是“remove ring”。
- 影响范围：主要涉及 前端。
- 改动规模：+2 / -2 行。
- 关键文件：frontend/src/styles/globals.css。

#### 272. feat: remove ring

- 提交：`[ab65ab3](https://github.com/bytedance/deer-flow/commit/ab65ab3af28e6f8775de6ab3586e2985785a142f)`
- 日期：2026-01-17
- 做了什么：新增或增强功能，主题是“remove ring”。
- 影响范围：主要涉及 前端。
- 改动规模：+2 / -2 行。
- 关键文件：frontend/src/styles/globals.css。

#### 273. chore: add TODO for checking duplicate files in state.artifacts

- 提交：`[a66d515](https://github.com/bytedance/deer-flow/commit/a66d5152145b13e5559bb854e4135a2858c8dd06)`
- 日期：2026-01-17
- 做了什么：新增或增强功能，主题是“add TODO for checking duplicate files in state.artifacts”。
- 影响范围：主要涉及 后端。
- 改动规模：+1 / -0 行。
- 关键文件：backend/TODO.md。

#### 274. chore: add TODO for checking duplicate files in state.artifacts

- 提交：`[d603771](https://github.com/bytedance/deer-flow/commit/d6037712912d4e59cb7e095e0f2b975bfc484e43)`
- 日期：2026-01-17
- 做了什么：新增或增强功能，主题是“add TODO for checking duplicate files in state.artifacts”。
- 影响范围：主要涉及 后端。
- 改动规模：+1 / -0 行。
- 关键文件：backend/TODO.md。

#### 275. feat: merge the last thinking with the previous group

- 提交：`[a663bcc](https://github.com/bytedance/deer-flow/commit/a663bcc37be426408cec6269d2be9d5e4b2cfff1)`
- 日期：2026-01-17
- 做了什么：新增或增强功能，主题是“merge the last thinking with the previous group”。
- 影响范围：主要涉及 前端。
- 改动规模：+15 / -22 行。
- 关键文件：frontend/src/components/workspace/messages/message-list-item.tsx；frontend/src/core/messages/utils.ts。

#### 276. feat: merge the last thinking with the previous group

- 提交：`[1a3b70a](https://github.com/bytedance/deer-flow/commit/1a3b70ac43d2dec839f13b76d059b784fc9919cd)`
- 日期：2026-01-17
- 做了什么：新增或增强功能，主题是“merge the last thinking with the previous group”。
- 影响范围：主要涉及 前端。
- 改动规模：+15 / -22 行。
- 关键文件：frontend/src/components/workspace/messages/message-list-item.tsx；frontend/src/core/messages/utils.ts。

#### 277. feat: implement '/chats'

- 提交：`[56da1c9](https://github.com/bytedance/deer-flow/commit/56da1c990aad453481badf51e6d215a3834da081)`
- 日期：2026-01-17
- 做了什么：新增或增强功能，主题是“implement '/chats'”。
- 影响范围：主要涉及 前端。
- 改动规模：+48 / -1 行。
- 关键文件：frontend/src/app/workspace/chats/page.tsx。

#### 278. feat: implement '/chats'

- 提交：`[e2d0246](https://github.com/bytedance/deer-flow/commit/e2d02468272e2a14f72fc601bde6ea8bf6b50fef)`
- 日期：2026-01-17
- 做了什么：新增或增强功能，主题是“implement '/chats'”。
- 影响范围：主要涉及 前端。
- 改动规模：+48 / -1 行。
- 关键文件：frontend/src/app/workspace/chats/page.tsx。

#### 279. feat: add date time util

- 提交：`[228ec49](https://github.com/bytedance/deer-flow/commit/228ec49f70373b1c862ab6bd1c2053b9ef8caded)`
- 日期：2026-01-17
- 做了什么：新增或增强功能，主题是“add date time util”。
- 影响范围：主要涉及 前端。
- 改动规模：+16 / -0 行。
- 关键文件：frontend/package.json；frontend/pnpm-lock.yaml；frontend/src/core/utils/datetime.ts。

#### 280. feat: add date time util

- 提交：`[c38dfdf](https://github.com/bytedance/deer-flow/commit/c38dfdf0e0ef08be723fa2651f29a220362fd660)`
- 日期：2026-01-17
- 做了什么：新增或增强功能，主题是“add date time util”。
- 影响范围：主要涉及 前端。
- 改动规模：+16 / -0 行。
- 关键文件：frontend/package.json；frontend/pnpm-lock.yaml；frontend/src/core/utils/datetime.ts。

#### 281. feat: shrink card size

- 提交：`[0e8fdf6](https://github.com/bytedance/deer-flow/commit/0e8fdf6234c36b772ce2e01302f2a6257e38d407)`
- 日期：2026-01-17
- 做了什么：新增或增强功能，主题是“shrink card size”。
- 影响范围：主要涉及 前端。
- 改动规模：+3 / -3 行。
- 关键文件：frontend/src/components/workspace/artifacts/artifact-file-list.tsx。

#### 282. feat: shrink card size

- 提交：`[3151087](https://github.com/bytedance/deer-flow/commit/31510879f2617d3abcff70ff4891313fc3684b93)`
- 日期：2026-01-17
- 做了什么：新增或增强功能，主题是“shrink card size”。
- 影响范围：主要涉及 前端。
- 改动规模：+3 / -3 行。
- 关键文件：frontend/src/components/workspace/artifacts/artifact-file-list.tsx。

#### 283. feat: add `open in new window`

- 提交：`[5dc40a9](https://github.com/bytedance/deer-flow/commit/5dc40a9adeac285c8e954cb4d581471919b00989)`
- 日期：2026-01-17
- 做了什么：新增或增强功能，主题是“add `open in new window`”。
- 影响范围：主要涉及 前端。
- 改动规模：+13 / -1 行。
- 关键文件：frontend/src/components/workspace/artifacts/artifact-file-detail.tsx。

#### 284. feat: add `open in new window`

- 提交：`[aa2677e](https://github.com/bytedance/deer-flow/commit/aa2677e9fd9b046825d32426a771e016db6c4684)`
- 日期：2026-01-17
- 做了什么：新增或增强功能，主题是“add `open in new window`”。
- 影响范围：主要涉及 前端。
- 改动规模：+13 / -1 行。
- 关键文件：frontend/src/components/workspace/artifacts/artifact-file-detail.tsx。

#### 285. feat: support artifact preview

- 提交：`[962d8f0](https://github.com/bytedance/deer-flow/commit/962d8f04ec93cee36516dc9d9cb45199a8ba1e29)`
- 日期：2026-01-17
- 做了什么：新增或增强功能，主题是“support artifact preview”。
- 影响范围：主要涉及 前端、后端。
- 改动规模：+482 / -42 行。
- 关键文件：backend/src/gateway/app.py；backend/src/gateway/routers/artifacts.py；frontend/package.json；frontend/pnpm-lock.yaml；frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/app/workspace/layout.tsx；frontend/src/components/ui/sonner.tsx；frontend/src/components/workspace/artifacts/artifact-file-detail.tsx。

#### 286. feat: support artifact preview

- 提交：`[0c6f835](https://github.com/bytedance/deer-flow/commit/0c6f8353bf54b413cd1ef70bd3df97a0d163f781)`
- 日期：2026-01-17
- 做了什么：新增或增强功能，主题是“support artifact preview”。
- 影响范围：主要涉及 前端、后端。
- 改动规模：+482 / -42 行。
- 关键文件：backend/src/gateway/app.py；backend/src/gateway/routers/artifacts.py；frontend/package.json；frontend/pnpm-lock.yaml；frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/app/workspace/layout.tsx；frontend/src/components/ui/sonner.tsx；frontend/src/components/workspace/artifacts/artifact-file-detail.tsx。

#### 287. feat: set artifacts layout

- 提交：`[ec5bbf6](https://github.com/bytedance/deer-flow/commit/ec5bbf6b513fb573f07a2d9e23336c74054232bf)`
- 日期：2026-01-17
- 做了什么：新增或增强功能，主题是“set artifacts layout”。
- 影响范围：主要涉及 前端。
- 改动规模：+150 / -84 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/layout.tsx；frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/app/workspace/layout.tsx；frontend/src/components/workspace/artifacts/artifact-file-detail.tsx；frontend/src/components/workspace/artifacts/context.tsx；frontend/src/components/workspace/messages/message-list.tsx。

#### 288. feat: set artifacts layout

- 提交：`[80c928f](https://github.com/bytedance/deer-flow/commit/80c928fcf556d6b4c56e17312f63a8705a311b0e)`
- 日期：2026-01-17
- 做了什么：新增或增强功能，主题是“set artifacts layout”。
- 影响范围：主要涉及 前端。
- 改动规模：+150 / -84 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/layout.tsx；frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/app/workspace/layout.tsx；frontend/src/components/workspace/artifacts/artifact-file-detail.tsx；frontend/src/components/workspace/artifacts/context.tsx；frontend/src/components/workspace/messages/message-list.tsx。

#### 289. feat: make BETTER_AUTH_* optional

- 提交：`[4e7256a](https://github.com/bytedance/deer-flow/commit/4e7256a9d860209dd2153d0f355f9fdf3c440e59)`
- 日期：2026-01-17
- 做了什么：新增或增强功能，主题是“make BETTER_AUTH_* optional”。
- 影响范围：主要涉及 前端。
- 改动规模：+2 / -2 行。
- 关键文件：frontend/src/env.js。

#### 290. feat: make BETTER_AUTH_* optional

- 提交：`[9a4cb61](https://github.com/bytedance/deer-flow/commit/9a4cb616c9554800ab8499f29f248684417f6e1c)`
- 日期：2026-01-17
- 做了什么：新增或增强功能，主题是“make BETTER_AUTH_* optional”。
- 影响范围：主要涉及 前端。
- 改动规模：+2 / -2 行。
- 关键文件：frontend/src/env.js。

#### 291. feat: ignore components from 3rd parties

- 提交：`[bb92dec](https://github.com/bytedance/deer-flow/commit/bb92dec8d5751aef5260245d8373b26b28eaf456)`
- 日期：2026-01-17
- 做了什么：新增或增强功能，主题是“ignore components from 3rd parties”。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -1 行。
- 关键文件：frontend/eslint.config.js。

#### 292. feat: ignore components from 3rd parties

- 提交：`[1a99ae9](https://github.com/bytedance/deer-flow/commit/1a99ae9c36fc584d522b3707f76e32b7974152ef)`
- 日期：2026-01-17
- 做了什么：新增或增强功能，主题是“ignore components from 3rd parties”。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -1 行。
- 关键文件：frontend/eslint.config.js。

#### 293. feat: integrated with artifacts

- 提交：`[9d64c7e](https://github.com/bytedance/deer-flow/commit/9d64c7e076000f1c6e6d385a7dd400526bf4ec5b)`
- 日期：2026-01-17
- 做了什么：新增或增强功能，主题是“integrated with artifacts”。
- 影响范围：主要涉及 前端。
- 改动规模：+203 / -68 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/workspace/artifacts/artifact-file-detail.tsx；frontend/src/components/workspace/artifacts/artifact-file-list.tsx；frontend/src/components/workspace/artifacts/context.tsx；frontend/src/components/workspace/artifacts/index.ts；frontend/src/components/workspace/message-list/message-list.tsx；frontend/src/components/workspace/message-list/present-file-list.tsx。

#### 294. feat: integrated with artifacts

- 提交：`[e5050c6](https://github.com/bytedance/deer-flow/commit/e5050c6c1e5cd7fbd1218ac7421909cbe438a129)`
- 日期：2026-01-17
- 做了什么：新增或增强功能，主题是“integrated with artifacts”。
- 影响范围：主要涉及 前端。
- 改动规模：+203 / -68 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/workspace/artifacts/artifact-file-detail.tsx；frontend/src/components/workspace/artifacts/artifact-file-list.tsx；frontend/src/components/workspace/artifacts/context.tsx；frontend/src/components/workspace/artifacts/index.ts；frontend/src/components/workspace/message-list/message-list.tsx；frontend/src/components/workspace/message-list/present-file-list.tsx。

#### 295. feat: add artifacts logic (#8)

- 提交：`[facde64](https://github.com/bytedance/deer-flow/commit/facde645d7693234bb09fb01a72d29594d4107df)`
- 日期：2026-01-16
- 做了什么：新增或增强功能，主题是“add artifacts logic (#8)”。
- 影响范围：主要涉及 后端。
- 改动规模：+129 / -7 行。
- 关键文件：backend/src/agents/thread_state.py；backend/src/community/aio_sandbox/aio_sandbox_provider.py；backend/src/gateway/app.py；backend/src/gateway/routers/**init**.py；backend/src/gateway/routers/artifacts.py；backend/src/tools/builtins/present_file_tool.py。

#### 296. feat: add artifacts logic (#8)

- 提交：`[d5b3052](https://github.com/bytedance/deer-flow/commit/d5b3052cdad69b71aadb3a6b577d3dbe43c85553)`
- 日期：2026-01-16
- 做了什么：新增或增强功能，主题是“add artifacts logic (#8)”。
- 影响范围：主要涉及 后端。
- 改动规模：+129 / -7 行。
- 关键文件：backend/src/agents/thread_state.py；backend/src/community/aio_sandbox/aio_sandbox_provider.py；backend/src/gateway/app.py；backend/src/gateway/routers/**init**.py；backend/src/gateway/routers/artifacts.py；backend/src/tools/builtins/present_file_tool.py。

#### 297. feat: remember sidebar state

- 提交：`[6464a67](https://github.com/bytedance/deer-flow/commit/6464a6723018e8c44dd8019800ca9dd42012e05a)`
- 日期：2026-01-16
- 做了什么：新增或增强功能，主题是“remember sidebar state”。
- 影响范围：主要涉及 前端。
- 改动规模：+59 / -34 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/app/workspace/layout.tsx；frontend/src/core/settings/hooks.ts；frontend/src/core/settings/local.ts。

#### 298. feat: remember sidebar state

- 提交：`[0d11b21](https://github.com/bytedance/deer-flow/commit/0d11b21c84a7aaffcdd536374422971169ae12c9)`
- 日期：2026-01-16
- 做了什么：新增或增强功能，主题是“remember sidebar state”。
- 影响范围：主要涉及 前端。
- 改动规模：+59 / -34 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/app/workspace/layout.tsx；frontend/src/core/settings/hooks.ts；frontend/src/core/settings/local.ts。

#### 299. feat: support basic file presenting

- 提交：`[f9853f0](https://github.com/bytedance/deer-flow/commit/f9853f037c52c397d1fb394b5c47612dcb754110)`
- 日期：2026-01-16
- 做了什么：新增或增强功能，主题是“support basic file presenting”。
- 影响范围：主要涉及 前端。
- 改动规模：+102 / -4 行。
- 关键文件：frontend/src/components/workspace/message-list/message-list.tsx；frontend/src/components/workspace/message-list/present-file-list.tsx；frontend/src/core/messages/utils.ts；frontend/src/core/utils/files.ts。

#### 300. feat: support basic file presenting

- 提交：`[83f367b](https://github.com/bytedance/deer-flow/commit/83f367b98a74137bc8337531b6b814991b0d4b00)`
- 日期：2026-01-16
- 做了什么：新增或增强功能，主题是“support basic file presenting”。
- 影响范围：主要涉及 前端。
- 改动规模：+102 / -4 行。
- 关键文件：frontend/src/components/workspace/message-list/message-list.tsx；frontend/src/components/workspace/message-list/present-file-list.tsx；frontend/src/core/messages/utils.ts；frontend/src/core/utils/files.ts。

#### 301. feat: add thread-safety and graceful shutdown to AioSandboxProvider (#7)

- 提交：`[4b69aed](https://github.com/bytedance/deer-flow/commit/4b69aed47b3c0afb3f6469a4d42f368df208882d)`
- 日期：2026-01-16
- 做了什么：新增或增强功能，主题是“add thread-safety and graceful shutdown to AioSandboxProvider (#7)”。
- 影响范围：主要涉及 后端。
- 改动规模：+238 / -38 行。
- 关键文件：backend/src/community/aio_sandbox/aio_sandbox_provider.py；backend/src/utils/network.py。

#### 302. feat: add thread-safety and graceful shutdown to AioSandboxProvider (#7)

- 提交：`[50a1e40](https://github.com/bytedance/deer-flow/commit/50a1e407cfb00075e06ed7f91ea2cbc67ed18f67)`
- 日期：2026-01-16
- 做了什么：新增或增强功能，主题是“add thread-safety and graceful shutdown to AioSandboxProvider (#7)”。
- 影响范围：主要涉及 后端。
- 改动规模：+238 / -38 行。
- 关键文件：backend/src/community/aio_sandbox/aio_sandbox_provider.py；backend/src/utils/network.py。

#### 303. feat: integrated with artifact resizable

- 提交：`[93a231c](https://github.com/bytedance/deer-flow/commit/93a231cfb1aba3edefe114fb5d2f0a4d6b350750)`
- 日期：2026-01-16
- 做了什么：新增或增强功能，主题是“integrated with artifact resizable”。
- 影响范围：主要涉及 前端。
- 改动规模：+43 / -33 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/workspace/message-list/message-group.tsx；frontend/src/components/workspace/workspace-container.tsx。

#### 304. feat: integrated with artifact resizable

- 提交：`[ca70e2d](https://github.com/bytedance/deer-flow/commit/ca70e2dcf7c473062faef6eeac4c0147e0babf87)`
- 日期：2026-01-16
- 做了什么：新增或增强功能，主题是“integrated with artifact resizable”。
- 影响范围：主要涉及 前端。
- 改动规模：+43 / -33 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/workspace/message-list/message-group.tsx；frontend/src/components/workspace/workspace-container.tsx。

#### 305. chore: add resizable

- 提交：`[68fbf53](https://github.com/bytedance/deer-flow/commit/68fbf53fb2966fa3a1a6e3658e9f335d23a0482d)`
- 日期：2026-01-16
- 做了什么：新增或增强功能，主题是“add resizable”。
- 影响范围：主要涉及 前端。
- 改动规模：+103 / -0 行。
- 关键文件：frontend/package.json；frontend/pnpm-lock.yaml；frontend/src/components/ui/resizable.tsx。

#### 306. chore: add resizable

- 提交：`[e1ddb1e](https://github.com/bytedance/deer-flow/commit/e1ddb1ee422a8bb7b6e7144c622313444c30b8d0)`
- 日期：2026-01-16
- 做了什么：新增或增强功能，主题是“add resizable”。
- 影响范围：主要涉及 前端。
- 改动规模：+103 / -0 行。
- 关键文件：frontend/package.json；frontend/pnpm-lock.yaml；frontend/src/components/ui/resizable.tsx。

#### 307. feat: add present_file tool

- 提交：`[1517e86](https://github.com/bytedance/deer-flow/commit/1517e8675d5c876eb92b13bafaae3e4c71f55d08)`
- 日期：2026-01-16
- 做了什么：新增或增强功能，主题是“add present_file tool”。
- 影响范围：主要涉及 后端。
- 改动规模：+34 / -1 行。
- 关键文件：backend/src/tools/builtins/**init**.py；backend/src/tools/builtins/present_file_tool.py；backend/src/tools/tools.py。

#### 308. feat: add present_file tool

- 提交：`[56b26c0](https://github.com/bytedance/deer-flow/commit/56b26c060e27b0c12454cce9c3445a05cfe72a3c)`
- 日期：2026-01-16
- 做了什么：新增或增强功能，主题是“add present_file tool”。
- 影响范围：主要涉及 后端。
- 改动规模：+34 / -1 行。
- 关键文件：backend/src/tools/builtins/**init**.py；backend/src/tools/builtins/present_file_tool.py；backend/src/tools/tools.py。

#### 309. feat: add flip display effect

- 提交：`[91eff99](https://github.com/bytedance/deer-flow/commit/91eff99f01831c3dd1ed5d65e43a922647889a3e)`
- 日期：2026-01-16
- 做了什么：新增或增强功能，主题是“add flip display effect”。
- 影响范围：主要涉及 前端。
- 改动规模：+41 / -7 行。
- 关键文件：frontend/src/components/workspace/flip-display.tsx；frontend/src/components/workspace/message-list/message-group.tsx；frontend/src/components/workspace/message-list/message-list.tsx。

#### 310. feat: add flip display effect

- 提交：`[e37be40](https://github.com/bytedance/deer-flow/commit/e37be407732f328576ca4aed34b7e2cece1e7da4)`
- 日期：2026-01-16
- 做了什么：新增或增强功能，主题是“add flip display effect”。
- 影响范围：主要涉及 前端。
- 改动规模：+41 / -7 行。
- 关键文件：frontend/src/components/workspace/flip-display.tsx；frontend/src/components/workspace/message-list/message-group.tsx；frontend/src/components/workspace/message-list/message-list.tsx。

#### 311. feat: adjust layout

- 提交：`[c265734](https://github.com/bytedance/deer-flow/commit/c265734c6e9c76aaf5303418be9a3b3d3f6e1f91)`
- 日期：2026-01-16
- 做了什么：新增或增强功能，主题是“adjust layout”。
- 影响范围：主要涉及 前端。
- 改动规模：+5 / -4 行。
- 关键文件：frontend/src/components/workspace/message-list/message-list-item.tsx；frontend/src/components/workspace/message-list/message-list.tsx。

#### 312. feat: adjust layout

- 提交：`[6e5dab7](https://github.com/bytedance/deer-flow/commit/6e5dab76ccda4af0083b889f4ecad1d5505bd427)`
- 日期：2026-01-16
- 做了什么：新增或增强功能，主题是“adjust layout”。
- 影响范围：主要涉及 前端。
- 改动规模：+5 / -4 行。
- 关键文件：frontend/src/components/workspace/message-list/message-list-item.tsx；frontend/src/components/workspace/message-list/message-list.tsx。

#### 313. feat: adjust layout and style of tooltip

- 提交：`[7066a3b](https://github.com/bytedance/deer-flow/commit/7066a3b6910752a70a692389a78ca0e061bc39d1)`
- 日期：2026-01-16
- 做了什么：新增或增强功能，主题是“adjust layout and style of tooltip”。
- 影响范围：主要涉及 前端。
- 改动规模：+13 / -14 行。
- 关键文件：frontend/src/components/ui/tooltip.tsx；frontend/src/components/workspace/tooltip.tsx。

#### 314. feat: adjust layout and style of tooltip

- 提交：`[f6c20db](https://github.com/bytedance/deer-flow/commit/f6c20dbcfe2e34a0a353030c99aca061f36a9d4d)`
- 日期：2026-01-16
- 做了什么：新增或增强功能，主题是“adjust layout and style of tooltip”。
- 影响范围：主要涉及 前端。
- 改动规模：+13 / -14 行。
- 关键文件：frontend/src/components/ui/tooltip.tsx；frontend/src/components/workspace/tooltip.tsx。

#### 315. feat: add copy button

- 提交：`[df396fc](https://github.com/bytedance/deer-flow/commit/df396fc24651aa92d6c281879d365f5dc8818386)`
- 日期：2026-01-16
- 做了什么：新增或增强功能，主题是“add copy button”。
- 影响范围：主要涉及 前端。
- 改动规模：+37 / -0 行。
- 关键文件：frontend/src/components/workspace/copy-button.tsx。

#### 316. feat: add copy button

- 提交：`[574b7e5](https://github.com/bytedance/deer-flow/commit/574b7e59cef6f29e4e95dca443c3a81f65f7bf5a)`
- 日期：2026-01-16
- 做了什么：新增或增强功能，主题是“add copy button”。
- 影响范围：主要涉及 前端。
- 改动规模：+37 / -0 行。
- 关键文件：frontend/src/components/workspace/copy-button.tsx。

#### 317. feat: add skills system for specialized agent workflows (#6)

- 提交：`[9f755ec](https://github.com/bytedance/deer-flow/commit/9f755ecc30691fcdc713239dbf5c8d5ff3cb1355)`
- 日期：2026-01-16
- 做了什么：新增或增强功能，主题是“add skills system for specialized agent workflows (#6)”。
- 影响范围：主要涉及 后端、技能体系、文档。
- 改动规模：+2959 / -51 行。
- 关键文件：README.md；backend/CLAUDE.md；backend/SETUP.md；backend/docs/CONFIGURATION.md；backend/src/agents/lead_agent/prompt.py；backend/src/community/aio_sandbox/aio_sandbox_provider.py；backend/src/config/**init**.py；backend/src/config/app_config.py。

#### 318. feat: add skills system for specialized agent workflows (#6)

- 提交：`[cfa97f7](https://github.com/bytedance/deer-flow/commit/cfa97f7a960d6f05cc156c68f56062e36b17c2ae)`
- 日期：2026-01-16
- 做了什么：新增或增强功能，主题是“add skills system for specialized agent workflows (#6)”。
- 影响范围：主要涉及 后端、技能体系、文档。
- 改动规模：+2959 / -51 行。
- 关键文件：README.md；backend/CLAUDE.md；backend/SETUP.md；backend/docs/CONFIGURATION.md；backend/src/agents/lead_agent/prompt.py；backend/src/community/aio_sandbox/aio_sandbox_provider.py；backend/src/config/**init**.py；backend/src/config/app_config.py。

#### 319. feat: remove scroll button

- 提交：`[52b9d0c](https://github.com/bytedance/deer-flow/commit/52b9d0cffc8c5e64bca510a946e9521bfb253038)`
- 日期：2026-01-16
- 做了什么：新增或增强功能，主题是“remove scroll button”。
- 影响范围：主要涉及 前端。
- 改动规模：+0 / -2 行。
- 关键文件：frontend/src/components/workspace/message-list/message-list.tsx。

#### 320. feat: remove scroll button

- 提交：`[a589fb3](https://github.com/bytedance/deer-flow/commit/a589fb3daedd66f2616d49e2198c413e4e813804)`
- 日期：2026-01-16
- 做了什么：新增或增强功能，主题是“remove scroll button”。
- 影响范围：主要涉及 前端。
- 改动规模：+0 / -2 行。
- 关键文件：frontend/src/components/workspace/message-list/message-list.tsx。

#### 321. feat: rename 'model' to 'model_name'

- 提交：`[faf80bb](https://github.com/bytedance/deer-flow/commit/faf80bb4297198787167c3c440965581a93ccb17)`
- 日期：2026-01-16
- 做了什么：新增或增强功能，主题是“rename 'model' to 'model_name'”。
- 影响范围：主要涉及 前端。
- 改动规模：+163 / -105 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/ui/input.tsx；frontend/src/components/workspace/input-box.tsx；frontend/src/components/workspace/recent-chat-list.tsx；frontend/src/core/api/api-client.ts；frontend/src/core/api/client.ts；frontend/src/core/api/hooks.ts；frontend/src/core/api/index.ts。

#### 322. feat: rename 'model' to 'model_name'

- 提交：`[ac07547](https://github.com/bytedance/deer-flow/commit/ac075477a0b10f52cf71516db2252691b05e1bfa)`
- 日期：2026-01-16
- 做了什么：新增或增强功能，主题是“rename 'model' to 'model_name'”。
- 影响范围：主要涉及 前端。
- 改动规模：+163 / -105 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/ui/input.tsx；frontend/src/components/workspace/input-box.tsx；frontend/src/components/workspace/recent-chat-list.tsx；frontend/src/core/api/api-client.ts；frontend/src/core/api/client.ts；frontend/src/core/api/hooks.ts；frontend/src/core/api/index.ts。

#### 323. feat: add gateway module with FastAPI server (#5)

- 提交：`[7284eb1](https://github.com/bytedance/deer-flow/commit/7284eb15f1632ce417c1ec7c120cc3f932d0c82b)`
- 日期：2026-01-16
- 做了什么：新增或增强功能，主题是“add gateway module with FastAPI server (#5)”。
- 影响范围：主要涉及 后端、前端、其他模块。
- 改动规模：+1125 / -41 行。
- 关键文件：.gitignore；backend/Makefile；backend/pyproject.toml；backend/src/agents/lead_agent/agent.py；backend/src/gateway/**init**.py；backend/src/gateway/app.py；backend/src/gateway/config.py；backend/src/gateway/routers/**init**.py。

#### 324. feat: add gateway module with FastAPI server (#5)

- 提交：`[fb92a47](https://github.com/bytedance/deer-flow/commit/fb92a472e2b918532e32f383be2d4b11e5758e16)`
- 日期：2026-01-16
- 做了什么：新增或增强功能，主题是“add gateway module with FastAPI server (#5)”。
- 影响范围：主要涉及 后端、前端、其他模块。
- 改动规模：+1125 / -41 行。
- 关键文件：.gitignore；backend/Makefile；backend/pyproject.toml；backend/src/agents/lead_agent/agent.py；backend/src/gateway/**init**.py；backend/src/gateway/app.py；backend/src/gateway/config.py；backend/src/gateway/routers/**init**.py。

#### 325. feat: link to home page

- 提交：`[7c61896](https://github.com/bytedance/deer-flow/commit/7c6189668c38f0a211c78a60f4b8aa2e09a96588)`
- 日期：2026-01-16
- 做了什么：新增或增强功能，主题是“link to home page”。
- 影响范围：主要涉及 前端。
- 改动规模：+24 / -20 行。
- 关键文件：frontend/src/components/workspace/workspace-header.tsx。

#### 326. feat: link to home page

- 提交：`[5fa98bf](https://github.com/bytedance/deer-flow/commit/5fa98bf6cd9e1c36dbd54bb35afb7bb58c7f79d2)`
- 日期：2026-01-16
- 做了什么：新增或增强功能，主题是“link to home page”。
- 影响范围：主要涉及 前端。
- 改动规模：+24 / -20 行。
- 关键文件：frontend/src/components/workspace/workspace-header.tsx。

#### 327. feat: store the local settings

- 提交：`[028f402](https://github.com/bytedance/deer-flow/commit/028f402ff523924200a8949c40bf391f2e7f05a6)`
- 日期：2026-01-16
- 做了什么：新增或增强功能，主题是“store the local settings”。
- 影响范围：主要涉及 前端。
- 改动规模：+86 / -12 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/workspace/input-box.tsx；frontend/src/core/settings/hooks.ts；frontend/src/core/settings/index.ts；frontend/src/core/settings/local.ts。

#### 328. feat: store the local settings

- 提交：`[3a62deb](https://github.com/bytedance/deer-flow/commit/3a62deb3fd023d088f57fa668287a114725889c3)`
- 日期：2026-01-16
- 做了什么：新增或增强功能，主题是“store the local settings”。
- 影响范围：主要涉及 前端。
- 改动规模：+86 / -12 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/workspace/input-box.tsx；frontend/src/core/settings/hooks.ts；frontend/src/core/settings/index.ts；frontend/src/core/settings/local.ts。

#### 329. feat: enable edit context options

- 提交：`[3f2bfde](https://github.com/bytedance/deer-flow/commit/3f2bfded418368b3c08cf36f7fe58dc1e328c59a)`
- 日期：2026-01-16
- 做了什么：新增或增强功能，主题是“enable edit context options”。
- 影响范围：主要涉及 前端。
- 改动规模：+113 / -5 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/workspace/input-box.tsx。

#### 330. feat: enable edit context options

- 提交：`[cad1206](https://github.com/bytedance/deer-flow/commit/cad12068efa47a8056b0c0dcd1eaf71c71325fef)`
- 日期：2026-01-16
- 做了什么：新增或增强功能，主题是“enable edit context options”。
- 影响范围：主要涉及 前端。
- 改动规模：+113 / -5 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/workspace/input-box.tsx。

#### 331. feat: adjust message group layout

- 提交：`[6149962](https://github.com/bytedance/deer-flow/commit/61499624a09aceb014777c46c019266cfbc0fe39)`
- 日期：2026-01-15
- 做了什么：新增或增强功能，主题是“adjust message group layout”。
- 影响范围：主要涉及 前端。
- 改动规模：+4 / -4 行。
- 关键文件：frontend/src/components/ai-elements/chain-of-thought.tsx；frontend/src/components/workspace/message-list/message-group.tsx。

#### 332. feat: adjust message group layout

- 提交：`[7680a5a](https://github.com/bytedance/deer-flow/commit/7680a5adbaadb9e99ab6c36d04465513b6a73efa)`
- 日期：2026-01-15
- 做了什么：新增或增强功能，主题是“adjust message group layout”。
- 影响范围：主要涉及 前端。
- 改动规模：+4 / -4 行。
- 关键文件：frontend/src/components/ai-elements/chain-of-thought.tsx；frontend/src/components/workspace/message-list/message-group.tsx。

#### 333. feat: enhance label

- 提交：`[00ad420](https://github.com/bytedance/deer-flow/commit/00ad4206c4379dd9116e78a7a9dd66dfa430500e)`
- 日期：2026-01-15
- 做了什么：新增或增强功能，主题是“enhance label”。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -1 行。
- 关键文件：frontend/src/components/workspace/message-list/message-group.tsx。

#### 334. feat: enhance label

- 提交：`[f353831](https://github.com/bytedance/deer-flow/commit/f353831ac964b396af96a54d75e29b4fc674e64d)`
- 日期：2026-01-15
- 做了什么：新增或增强功能，主题是“enhance label”。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -1 行。
- 关键文件：frontend/src/components/workspace/message-list/message-group.tsx。

#### 335. feat: remove max-w-

- 提交：`[c3cb4c3](https://github.com/bytedance/deer-flow/commit/c3cb4c348de637ab5a7ea1866147d11c25fbc7fc)`
- 日期：2026-01-15
- 做了什么：新增或增强功能，主题是“remove max-w-”。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -4 行。
- 关键文件：frontend/src/components/ai-elements/chain-of-thought.tsx。

#### 336. feat: remove max-w-

- 提交：`[d45f48a](https://github.com/bytedance/deer-flow/commit/d45f48addef42f04625267523825d335ec73e4da)`
- 日期：2026-01-15
- 做了什么：新增或增强功能，主题是“remove max-w-”。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -4 行。
- 关键文件：frontend/src/components/ai-elements/chain-of-thought.tsx。

#### 337. feat: implement basic web app

- 提交：`[9f2b94e](https://github.com/bytedance/deer-flow/commit/9f2b94ed52c6771aba17cc662e12a465b24460e5)`
- 日期：2026-01-15
- 做了什么：新增或增强功能，主题是“implement basic web app”。
- 影响范围：主要涉及 前端。
- 改动规模：+4144 / -628 行。
- 关键文件：frontend/package.json；frontend/pnpm-lock.yaml；frontend/src/app/api/langgraph/[...path]/route.ts；frontend/src/app/layout.tsx；frontend/src/app/page.tsx；frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/app/workspace/chats/page.tsx；frontend/src/app/workspace/layout.tsx。

#### 338. feat: implement basic web app

- 提交：`[cecc684](https://github.com/bytedance/deer-flow/commit/cecc684de1a2bd9921152f4acc3929ac8beb5a9f)`
- 日期：2026-01-15
- 做了什么：新增或增强功能，主题是“implement basic web app”。
- 影响范围：主要涉及 前端。
- 改动规模：+4144 / -628 行。
- 关键文件：frontend/package.json；frontend/pnpm-lock.yaml；frontend/src/app/api/langgraph/[...path]/route.ts；frontend/src/app/layout.tsx；frontend/src/app/page.tsx；frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/app/workspace/chats/page.tsx；frontend/src/app/workspace/layout.tsx。

#### 339. feat: support function factory (#4)

- 提交：`[b44144d](https://github.com/bytedance/deer-flow/commit/b44144dd2c10dd1911c5fd86b4b3ff5cb246f357)`
- 日期：2026-01-15
- 做了什么：新增或增强功能，主题是“support function factory (#4)”。
- 影响范围：主要涉及 后端、其他模块。
- 改动规模：+133 / -22 行。
- 关键文件：backend/debug.py；backend/langgraph.json；backend/src/agents/**init**.py；backend/src/agents/lead_agent/**init**.py；backend/src/agents/lead_agent/agent.py；backend/src/agents/lead_agent/prompt.py；backend/src/agents/middlewares/thread_data_middleware.py；backend/src/sandbox/tools.py。

#### 340. feat: support function factory (#4)

- 提交：`[c7d68c6](https://github.com/bytedance/deer-flow/commit/c7d68c6d3f85b14f8c90735201049b340c9ac320)`
- 日期：2026-01-15
- 做了什么：新增或增强功能，主题是“support function factory (#4)”。
- 影响范围：主要涉及 后端、其他模块。
- 改动规模：+133 / -22 行。
- 关键文件：backend/debug.py；backend/langgraph.json；backend/src/agents/**init**.py；backend/src/agents/lead_agent/**init**.py；backend/src/agents/lead_agent/agent.py；backend/src/agents/lead_agent/prompt.py；backend/src/agents/middlewares/thread_data_middleware.py；backend/src/sandbox/tools.py。

#### 341. feat: add thread data middleware (#2)

- 提交：`[c92eedc](https://github.com/bytedance/deer-flow/commit/c92eedc57264fa566e6eb47a06dfc3b34798c6fb)`
- 日期：2026-01-15
- 做了什么：新增或增强功能，主题是“add thread data middleware (#2)”。
- 影响范围：主要涉及 后端、配置。
- 改动规模：+181 / -14 行。
- 关键文件：backend/src/agents/lead_agent/agent.py；backend/src/agents/middlewares/thread_data_middleware.py；backend/src/agents/thread_state.py；backend/src/community/aio_sandbox/aio_sandbox_provider.py；backend/src/sandbox/local/local_sandbox_provider.py；backend/src/sandbox/middleware.py；backend/src/sandbox/sandbox_provider.py；config.example.yaml。

#### 342. feat: add thread data middleware (#2)

- 提交：`[41442cc](https://github.com/bytedance/deer-flow/commit/41442ccc2f70422314c3c24843fb0e6f371807aa)`
- 日期：2026-01-15
- 做了什么：新增或增强功能，主题是“add thread data middleware (#2)”。
- 影响范围：主要涉及 后端、配置。
- 改动规模：+181 / -14 行。
- 关键文件：backend/src/agents/lead_agent/agent.py；backend/src/agents/middlewares/thread_data_middleware.py；backend/src/agents/thread_state.py；backend/src/community/aio_sandbox/aio_sandbox_provider.py；backend/src/sandbox/local/local_sandbox_provider.py；backend/src/sandbox/middleware.py；backend/src/sandbox/sandbox_provider.py；config.example.yaml。

#### 343. feat: add AIO sandbox provider and auto title generation (#1)

- 提交：`[ab42773](https://github.com/bytedance/deer-flow/commit/ab427731dc10549d2b00e606c2a0445af57b5af6)`
- 日期：2026-01-14
- 做了什么：新增或增强功能，主题是“add AIO sandbox provider and auto title generation (#1)”。
- 影响范围：主要涉及 后端。
- 改动规模：+1479 / -13 行。
- 关键文件：backend/.claude/settings.local.json；backend/AGENTS.md；backend/CLAUDE.md；backend/Makefile；backend/docs/AUTO_TITLE_GENERATION.md；backend/docs/BACKEND_TODO.md；backend/docs/TITLE_GENERATION_IMPLEMENTATION.md；backend/pyproject.toml。

#### 344. feat: add AIO sandbox provider and auto title generation (#1)

- 提交：`[b2abfec](https://github.com/bytedance/deer-flow/commit/b2abfecf675324e4d016004a92d589c50bd948b8)`
- 日期：2026-01-14
- 做了什么：新增或增强功能，主题是“add AIO sandbox provider and auto title generation (#1)”。
- 影响范围：主要涉及 后端。
- 改动规模：+1479 / -13 行。
- 关键文件：backend/.claude/settings.local.json；backend/AGENTS.md；backend/CLAUDE.md；backend/Makefile；backend/docs/AUTO_TITLE_GENERATION.md；backend/docs/BACKEND_TODO.md；backend/docs/TITLE_GENERATION_IMPLEMENTATION.md；backend/pyproject.toml。

#### 345. feat: integrated with sandbox

- 提交：`[de2d185](https://github.com/bytedance/deer-flow/commit/de2d18561adcb2bbab94246815bdca4dd151ebf8)`
- 日期：2026-01-14
- 做了什么：新增或增强功能，主题是“integrated with sandbox”。
- 影响范围：主要涉及 后端。
- 改动规模：+103 / -34 行。
- 关键文件：backend/src/agents/**init**.py；backend/src/agents/lead_agent/agent.py；backend/src/agents/thread_state.py；backend/src/config/app_config.py；backend/src/sandbox/local/local_sandbox_provider.py；backend/src/sandbox/middleware.py；backend/src/sandbox/sandbox_provider.py；backend/src/sandbox/tools.py。

#### 346. chore: add `lint` and `format`

- 提交：`[421488a](https://github.com/bytedance/deer-flow/commit/421488a991aee32bb60d3e6cc91ed17abfdc6d51)`
- 日期：2026-01-14
- 做了什么：新增或增强功能，主题是“add `lint` and `format`”。
- 影响范围：主要涉及 后端。
- 改动规模：+6 / -0 行。
- 关键文件：backend/Makefile。

#### 347. feat: add agents

- 提交：`[7dc063b](https://github.com/bytedance/deer-flow/commit/7dc063ba25b9be9ffcb23f6ffc944e591dbdeedf)`
- 日期：2026-01-14
- 做了什么：新增或增强功能，主题是“add agents”。
- 影响范围：主要涉及 后端。
- 改动规模：+93 / -0 行。
- 关键文件：backend/src/agents/**init**.py；backend/src/agents/lead_agent/**init**.py；backend/src/agents/lead_agent/agent.py；backend/src/agents/lead_agent/prompt.py。

#### 348. feat: add tools

- 提交：`[cbbbac0](https://github.com/bytedance/deer-flow/commit/cbbbac0c2b9f09ac7917df8b410ce7a4d28ce8b2)`
- 日期：2026-01-14
- 做了什么：新增或增强功能，主题是“add tools”。
- 影响范围：主要涉及 后端。
- 改动规模：+17 / -0 行。
- 关键文件：backend/src/tools/**init**.py；backend/src/tools/tools.py。

#### 349. feat: add sandbox and local impl

- 提交：`[57a02ac](https://github.com/bytedance/deer-flow/commit/57a02acb596566bb54d7b3b97151ceaef2b90eed)`
- 日期：2026-01-14
- 做了什么：新增或增强功能，主题是“add sandbox and local impl”。
- 影响范围：主要涉及 后端。
- 改动规模：+432 / -0 行。
- 关键文件：backend/src/sandbox/**init**.py；backend/src/sandbox/local/**init**.py；backend/src/sandbox/local/list_dir.py；backend/src/sandbox/local/local_sandbox.py；backend/src/sandbox/local/local_sandbox_provider.py；backend/src/sandbox/sandbox.py；backend/src/sandbox/sandbox_provider.py；backend/src/sandbox/tools.py。

#### 350. feat: integrated with Tavily and Jina AI

- 提交：`[4b5f529](https://github.com/bytedance/deer-flow/commit/4b5f5299037ffee397fcad67fc4bd27671cebe1d)`
- 日期：2026-01-14
- 做了什么：新增或增强功能，主题是“integrated with Tavily and Jina AI”。
- 影响范围：主要涉及 后端。
- 改动规模：+190 / -0 行。
- 关键文件：backend/src/community/jina_ai/jina_client.py；backend/src/community/jina_ai/tools.py；backend/src/community/tavily/tools.py；backend/src/utils/readability.py。

#### 351. feat: add model modules

- 提交：`[83bd7e4](https://github.com/bytedance/deer-flow/commit/83bd7e43096a50e842e50dd90fd3923910bdeb52)`
- 日期：2026-01-14
- 做了什么：新增或增强功能，主题是“add model modules”。
- 影响范围：主要涉及 后端。
- 改动规模：+46 / -0 行。
- 关键文件：backend/src/models/**init**.py；backend/src/models/factory.py。

#### 352. chore: add an empty **init**.py

- 提交：`[721b26a](https://github.com/bytedance/deer-flow/commit/721b26a32ff4d9c8dd749537a7942fbfa0ede7b0)`
- 日期：2026-01-14
- 做了什么：新增或增强功能，主题是“add an empty **init**.py”。
- 影响范围：主要涉及 后端。
- 改动规模：+0 / -0 行。
- 关键文件：backend/src/**init**.py。

#### 353. feat: add reflection modules

- 提交：`[86524a6](https://github.com/bytedance/deer-flow/commit/86524a65f6fa64bf9afc1ec9d248879eaab2ffe5)`
- 日期：2026-01-14
- 做了什么：新增或增强功能，主题是“add reflection modules”。
- 影响范围：主要涉及 后端。
- 改动规模：+84 / -0 行。
- 关键文件：backend/src/reflection/**init**.py；backend/src/reflection/resolvers.py。

#### 354. feat: add config modules

- 提交：`[88ed384](https://github.com/bytedance/deer-flow/commit/88ed3841c7f29b784bbaa9cbf3ce03098fbd521e)`
- 日期：2026-01-14
- 做了什么：新增或增强功能，主题是“add config modules”。
- 影响范围：主要涉及 后端。
- 改动规模：+202 / -0 行。
- 关键文件：backend/src/config/**init**.py；backend/src/config/app_config.py；backend/src/config/model_config.py；backend/src/config/sandbox_config.py；backend/src/config/tool_config.py。

#### 355. chore: add Python and LangGraph stuff

- 提交：`[c2a62a2](https://github.com/bytedance/deer-flow/commit/c2a62a2266e0756b5e69f7fc6054626f233da07c)`
- 日期：2026-01-14
- 做了什么：新增或增强功能，主题是“add Python and LangGraph stuff”。
- 影响范围：主要涉及 后端。
- 改动规模：+1239 / -0 行。
- 关键文件：backend/.python-version；backend/Makefile；backend/langgraph.json；backend/pyproject.toml；backend/uv.lock。

#### 356. chore: add .gitignore for Python project

- 提交：`[81bd4da](https://github.com/bytedance/deer-flow/commit/81bd4dafa84893e20005325d6d74f239adc4b2ac)`
- 日期：2026-01-14
- 做了什么：新增或增强功能，主题是“add .gitignore for Python project”。
- 影响范围：主要涉及 后端。
- 改动规模：+21 / -0 行。
- 关键文件：backend/.gitignore。

### Bug 修复

#### 1. fix: add translations

- 提交：`[f5b1412](https://github.com/bytedance/deer-flow/commit/f5b1412ac043d2b2aad1df6bc85c58cc9a696b2c)`
- 日期：2026-01-31
- 做了什么：修复缺陷或回归问题，主题是“add translations”。
- 影响范围：主要涉及 前端。
- 改动规模：+4 / -1 行。
- 关键文件：frontend/src/components/workspace/settings/skill-settings-page.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts；frontend/src/core/i18n/locales/zh-CN.ts。

#### 2. fix: add translations

- 提交：`[8a2fb35](https://github.com/bytedance/deer-flow/commit/8a2fb353c61e0b7bd14bd76e8092f1e596b8ad13)`
- 日期：2026-01-31
- 做了什么：修复缺陷或回归问题，主题是“add translations”。
- 影响范围：主要涉及 前端。
- 改动规模：+4 / -1 行。
- 关键文件：frontend/src/components/workspace/settings/skill-settings-page.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts；frontend/src/core/i18n/locales/zh-CN.ts。

#### 3. fix: add translations

- 提交：`[45fab66](https://github.com/bytedance/deer-flow/commit/45fab66a7d4abfa5a078b14ab938176e089ad788)`
- 日期：2026-01-31
- 做了什么：修复缺陷或回归问题，主题是“add translations”。
- 影响范围：主要涉及 前端。
- 改动规模：+4 / -1 行。
- 关键文件：frontend/src/components/workspace/settings/skill-settings-page.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts；frontend/src/core/i18n/locales/zh-CN.ts。

#### 4. fix: fix eslint errors and warnings

- 提交：`[d3ff5f9](https://github.com/bytedance/deer-flow/commit/d3ff5f9d3c3f8b6bfc0636c05d76ce93f80b24d3)`
- 日期：2026-01-31
- 做了什么：修复缺陷或回归问题，主题是“fix eslint errors and warnings”。
- 影响范围：主要涉及 前端。
- 改动规模：+20 / -80 行。
- 关键文件：frontend/eslint.config.js；frontend/package.json；frontend/src/components/workspace/code-editor.tsx；frontend/src/components/workspace/messages/message-list-item.tsx；frontend/src/core/uploads/api.ts。

#### 5. fix: fix eslint errors and warnings

- 提交：`[718bb94](https://github.com/bytedance/deer-flow/commit/718bb947d05a27a38bfd9e27a0716823ec05cfd4)`
- 日期：2026-01-31
- 做了什么：修复缺陷或回归问题，主题是“fix eslint errors and warnings”。
- 影响范围：主要涉及 前端。
- 改动规模：+20 / -80 行。
- 关键文件：frontend/eslint.config.js；frontend/package.json；frontend/src/components/workspace/code-editor.tsx；frontend/src/components/workspace/messages/message-list-item.tsx；frontend/src/core/uploads/api.ts。

#### 6. fix: fix eslint errors and warnings

- 提交：`[8ecb6b3](https://github.com/bytedance/deer-flow/commit/8ecb6b3d1ddcdc9bd145ff9f3dd8c5ec9af95202)`
- 日期：2026-01-31
- 做了什么：修复缺陷或回归问题，主题是“fix eslint errors and warnings”。
- 影响范围：主要涉及 前端。
- 改动规模：+20 / -80 行。
- 关键文件：frontend/eslint.config.js；frontend/package.json；frontend/src/components/workspace/code-editor.tsx；frontend/src/components/workspace/messages/message-list-item.tsx；frontend/src/core/uploads/api.ts。

#### 7. fix: fix eslint errors

- 提交：`[e858ef0](https://github.com/bytedance/deer-flow/commit/e858ef0250263dd54c0fb18298e7bfe5c6bed408)`
- 日期：2026-01-31
- 做了什么：修复缺陷或回归问题，主题是“fix eslint errors”。
- 影响范围：主要涉及 前端。
- 改动规模：+3 / -2 行。
- 关键文件：frontend/src/core/messages/utils.ts。

#### 8. fix: fix eslint errors

- 提交：`[b8281be](https://github.com/bytedance/deer-flow/commit/b8281be892da6309e4adf0a6999c3e1e45fd1232)`
- 日期：2026-01-31
- 做了什么：修复缺陷或回归问题，主题是“fix eslint errors”。
- 影响范围：主要涉及 前端。
- 改动规模：+3 / -2 行。
- 关键文件：frontend/src/core/messages/utils.ts。

#### 9. fix: fix eslint errors

- 提交：`[2ba687b](https://github.com/bytedance/deer-flow/commit/2ba687b239e183045e6a5ff915c777e440a10670)`
- 日期：2026-01-31
- 做了什么：修复缺陷或回归问题，主题是“fix eslint errors”。
- 影响范围：主要涉及 前端。
- 改动规模：+3 / -2 行。
- 关键文件：frontend/src/core/messages/utils.ts。

#### 10. fix: fix aio sandbox shutdown bug

- 提交：`[43ee8a2](https://github.com/bytedance/deer-flow/commit/43ee8a29683da20ed7a5a07fbc0f774fd7551042)`
- 日期：2026-01-30
- 做了什么：修复缺陷或回归问题，主题是“fix aio sandbox shutdown bug”。
- 影响范围：主要涉及 技能体系、后端、其他模块。
- 改动规模：+1271 / -4 行。
- 关键文件：Makefile；backend/src/community/aio_sandbox/aio_sandbox_provider.py；backend/src/config/extensions_config.py；backend/src/config/sandbox_config.py；skills/public/skill-creator/LICENSE.txt；skills/public/skill-creator/SKILL.md；skills/public/skill-creator/references/output-patterns.md；skills/public/skill-creator/references/workflows.md。

#### 11. fix: fix aio sandbox shutdown bug

- 提交：`[733c020](https://github.com/bytedance/deer-flow/commit/733c020c58528ff175a7e9cbb16cace23d8d43f1)`
- 日期：2026-01-30
- 做了什么：修复缺陷或回归问题，主题是“fix aio sandbox shutdown bug”。
- 影响范围：主要涉及 技能体系、后端、其他模块。
- 改动规模：+1271 / -4 行。
- 关键文件：Makefile；backend/src/community/aio_sandbox/aio_sandbox_provider.py；backend/src/config/extensions_config.py；backend/src/config/sandbox_config.py；skills/public/skill-creator/LICENSE.txt；skills/public/skill-creator/SKILL.md；skills/public/skill-creator/references/output-patterns.md；skills/public/skill-creator/references/workflows.md。

#### 12. fix: fix aio sandbox shutdown bug

- 提交：`[8182ed3](https://github.com/bytedance/deer-flow/commit/8182ed3737baa302b0ed8b35c2b289e241b88c4d)`
- 日期：2026-01-30
- 做了什么：修复缺陷或回归问题，主题是“fix aio sandbox shutdown bug”。
- 影响范围：主要涉及 技能体系、后端、其他模块。
- 改动规模：+1271 / -4 行。
- 关键文件：Makefile；backend/src/community/aio_sandbox/aio_sandbox_provider.py；backend/src/config/extensions_config.py；backend/src/config/sandbox_config.py；skills/public/skill-creator/LICENSE.txt；skills/public/skill-creator/SKILL.md；skills/public/skill-creator/references/output-patterns.md；skills/public/skill-creator/references/workflows.md。

#### 13. fix: fix condition of displaying artifacts

- 提交：`[c07c022](https://github.com/bytedance/deer-flow/commit/c07c0228f67613bd3046b009cfc76e7c572df54e)`
- 日期：2026-01-30
- 做了什么：修复缺陷或回归问题，主题是“fix condition of displaying artifacts”。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -1 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx。

#### 14. fix: fix condition of displaying artifacts

- 提交：`[697f094](https://github.com/bytedance/deer-flow/commit/697f094ba946326bc406335e3c61d78e9a291d6c)`
- 日期：2026-01-30
- 做了什么：修复缺陷或回归问题，主题是“fix condition of displaying artifacts”。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -1 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx。

#### 15. fix: fix condition of displaying artifacts

- 提交：`[21e12d9](https://github.com/bytedance/deer-flow/commit/21e12d91eb076bf2210e5c7822b68da57f85fbeb)`
- 日期：2026-01-30
- 做了什么：修复缺陷或回归问题，主题是“fix condition of displaying artifacts”。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -1 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx。

#### 16. fix: improve JSON repair handling for markdown code blocks (#841)

- 提交：`[3adb4e9](https://github.com/bytedance/deer-flow/commit/3adb4e90cbf14e8dd0b34ab72fcd02e3b550635f)`
- 日期：2026-01-30
- 做了什么：修复缺陷或回归问题，主题是“improve JSON repair handling for markdown code blocks (#841)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+394 / -6 行。
- 关键文件：src/graph/nodes.py；src/tools/crawl.py；src/utils/json_utils.py；tests/unit/utils/test_json_utils.py。

#### 17. fix: add max width

- 提交：`[a4f749f](https://github.com/bytedance/deer-flow/commit/a4f749f939b091ff5f8bfa8509ff8213a2b6f536)`
- 日期：2026-01-29
- 做了什么：修复缺陷或回归问题，主题是“add max width”。
- 影响范围：主要涉及 前端。
- 改动规模：+3 / -1 行。
- 关键文件：frontend/src/components/ai-elements/prompt-input.tsx。

#### 18. fix: add max width

- 提交：`[c265f54](https://github.com/bytedance/deer-flow/commit/c265f5410d623577db2b1f5846400c32bc6f181a)`
- 日期：2026-01-29
- 做了什么：修复缺陷或回归问题，主题是“add max width”。
- 影响范围：主要涉及 前端。
- 改动规模：+3 / -1 行。
- 关键文件：frontend/src/components/ai-elements/prompt-input.tsx。

#### 19. fix: add max width

- 提交：`[66deedf](https://github.com/bytedance/deer-flow/commit/66deedf3b25a2d38b46b2dc515e0433dc07ad4d3)`
- 日期：2026-01-29
- 做了什么：修复缺陷或回归问题，主题是“add max width”。
- 影响范围：主要涉及 前端。
- 改动规模：+3 / -1 行。
- 关键文件：frontend/src/components/ai-elements/prompt-input.tsx。

#### 20. fix: fix renaming

- 提交：`[4411af6](https://github.com/bytedance/deer-flow/commit/4411af68f5fd2da56c7e3844b4244da5bddfccd1)`
- 日期：2026-01-29
- 做了什么：修复缺陷或回归问题，主题是“fix renaming”。
- 影响范围：主要涉及 前端。
- 改动规模：+10 / -10 行。
- 关键文件：frontend/src/core/threads/hooks.ts。

#### 21. fix: fix renaming

- 提交：`[caf469d](https://github.com/bytedance/deer-flow/commit/caf469d2ab98164d4ebb425626142248ffa588d0)`
- 日期：2026-01-29
- 做了什么：修复缺陷或回归问题，主题是“fix renaming”。
- 影响范围：主要涉及 前端。
- 改动规模：+10 / -10 行。
- 关键文件：frontend/src/core/threads/hooks.ts。

#### 22. fix: fix renaming

- 提交：`[0ba82a9](https://github.com/bytedance/deer-flow/commit/0ba82a9fd793d0b30555fc5ac8d6ec2f1f7a98e1)`
- 日期：2026-01-29
- 做了什么：修复缺陷或回归问题，主题是“fix renaming”。
- 影响范围：主要涉及 前端。
- 改动规模：+10 / -10 行。
- 关键文件：frontend/src/core/threads/hooks.ts。

#### 23. fix: fix frontend bug

- 提交：`[75801d9](https://github.com/bytedance/deer-flow/commit/75801d9817ac19238855d5af766fad451ee86f15)`
- 日期：2026-01-29
- 做了什么：修复缺陷或回归问题，主题是“fix frontend bug”。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -1 行。
- 关键文件：frontend/src/app/layout.tsx；frontend/src/styles/globals.css。

#### 24. fix: fix frontend bug

- 提交：`[2c6dbbe](https://github.com/bytedance/deer-flow/commit/2c6dbbe065765d11eb6d6ac95b880b9984647e2f)`
- 日期：2026-01-29
- 做了什么：修复缺陷或回归问题，主题是“fix frontend bug”。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -1 行。
- 关键文件：frontend/src/app/layout.tsx；frontend/src/styles/globals.css。

#### 25. fix: fix frontend bug

- 提交：`[3cbf54b](https://github.com/bytedance/deer-flow/commit/3cbf54b2ebe752af51e6bb8890af3c73f267f81b)`
- 日期：2026-01-29
- 做了什么：修复缺陷或回归问题，主题是“fix frontend bug”。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -1 行。
- 关键文件：frontend/src/app/layout.tsx；frontend/src/styles/globals.css。

#### 26. fix: hide incomplete citations block during streaming

- 提交：`[e2e0fbf](https://github.com/bytedance/deer-flow/commit/e2e0fbf11442b9b5377e455fcddb499de77cce75)`
- 日期：2026-01-29
- 做了什么：修复缺陷或回归问题，主题是“hide incomplete citations block during streaming”。
- 影响范围：主要涉及 前端。
- 改动规模：+7 / -1 行。
- 关键文件：frontend/src/core/citations/utils.ts。

#### 27. fix: hide incomplete citations block during streaming

- 提交：`[6ae4868](https://github.com/bytedance/deer-flow/commit/6ae486878041e42b8ce5219a1d63db4f57cce349)`
- 日期：2026-01-29
- 做了什么：修复缺陷或回归问题，主题是“hide incomplete citations block during streaming”。
- 影响范围：主要涉及 前端。
- 改动规模：+7 / -1 行。
- 关键文件：frontend/src/core/citations/utils.ts。

#### 28. fix: hide incomplete citations block during streaming

- 提交：`[2ec506d](https://github.com/bytedance/deer-flow/commit/2ec506d5902a81772e5331d8a2e66c09401092d1)`
- 日期：2026-01-29
- 做了什么：修复缺陷或回归问题，主题是“hide incomplete citations block during streaming”。
- 影响范围：主要涉及 前端。
- 改动规模：+7 / -1 行。
- 关键文件：frontend/src/core/citations/utils.ts。

#### 29. fix: improve hasPresentFiles function to check for multiple tool calls

- 提交：`[7decdbc](https://github.com/bytedance/deer-flow/commit/7decdbcc835b0d8d6b09167331298e40b9cbbda4)`
- 日期：2026-01-29
- 做了什么：修复缺陷或回归问题，主题是“improve hasPresentFiles function to check for multiple tool calls”。
- 影响范围：主要涉及 前端。
- 改动规模：+2 / -1 行。
- 关键文件：frontend/src/core/messages/utils.ts。

#### 30. fix: improve hasPresentFiles function to check for multiple tool calls

- 提交：`[946031b](https://github.com/bytedance/deer-flow/commit/946031b79fdb2c3973a4e593e3211c2afe541049)`
- 日期：2026-01-29
- 做了什么：修复缺陷或回归问题，主题是“improve hasPresentFiles function to check for multiple tool calls”。
- 影响范围：主要涉及 前端。
- 改动规模：+2 / -1 行。
- 关键文件：frontend/src/core/messages/utils.ts。

#### 31. fix(mcp-tool): using the async invocation for MCP tools (#840)

- 提交：`[756421c](https://github.com/bytedance/deer-flow/commit/756421c3ac30fd9b8e7ce1bad3f63d5181de3e1e)`
- 日期：2026-01-28
- 做了什么：修复缺陷或回归问题，主题是“using the async invocation for MCP tools (#840)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+18 / -17 行。
- 关键文件：src/graph/nodes.py；tests/integration/test_nodes.py。

#### 32. fix: preserve reasoning_content in multi-turn conversations

- 提交：`[fa9fba3](https://github.com/bytedance/deer-flow/commit/fa9fba3f8e4d0fe9003bf6e4a275de5b335bb0d3)`
- 日期：2026-01-28
- 做了什么：修复缺陷或回归问题，主题是“preserve reasoning_content in multi-turn conversations”。
- 影响范围：主要涉及 后端、配置。
- 改动规模：+93 / -7 行。
- 关键文件：backend/debug.py；backend/src/agents/middlewares/uploads_middleware.py；backend/src/models/patched_deepseek.py；config.example.yaml。

#### 33. fix: preserve reasoning_content in multi-turn conversations

- 提交：`[9d0a0ea](https://github.com/bytedance/deer-flow/commit/9d0a0ea0221f84dc46b2bd879f6a595603a41b74)`
- 日期：2026-01-28
- 做了什么：修复缺陷或回归问题，主题是“preserve reasoning_content in multi-turn conversations”。
- 影响范围：主要涉及 后端、配置。
- 改动规模：+93 / -7 行。
- 关键文件：backend/debug.py；backend/src/agents/middlewares/uploads_middleware.py；backend/src/models/patched_deepseek.py；config.example.yaml。

#### 34. fix: hide chats when sidebar is not open

- 提交：`[ed31dc6](https://github.com/bytedance/deer-flow/commit/ed31dc6aab6fabf9325209a7b4436b5f9d667974)`
- 日期：2026-01-27
- 做了什么：修复缺陷或回归问题，主题是“hide chats when sidebar is not open”。
- 影响范围：主要涉及 前端。
- 改动规模：+3 / -1 行。
- 关键文件：frontend/src/components/workspace/workspace-sidebar.tsx。

#### 35. fix: hide chats when sidebar is not open

- 提交：`[ec31e61](https://github.com/bytedance/deer-flow/commit/ec31e61f95de94fbf90cbde88ac721b9602b3031)`
- 日期：2026-01-27
- 做了什么：修复缺陷或回归问题，主题是“hide chats when sidebar is not open”。
- 影响范围：主要涉及 前端。
- 改动规模：+3 / -1 行。
- 关键文件：frontend/src/components/workspace/workspace-sidebar.tsx。

#### 36. fix: eslint

- 提交：`[cc1fe4e](https://github.com/bytedance/deer-flow/commit/cc1fe4e50ecf8d83a217a879bf105e985a9efb3c)`
- 日期：2026-01-27
- 做了什么：修复缺陷或回归问题，主题是“eslint”。
- 影响范围：主要涉及 前端。
- 改动规模：+0 / -2 行。
- 关键文件：frontend/src/components/workspace/workspace-header.tsx。

#### 37. fix: eslint

- 提交：`[7928a6f](https://github.com/bytedance/deer-flow/commit/7928a6f2e10030e5200238263592f0804d8b47bd)`
- 日期：2026-01-27
- 做了什么：修复缺陷或回归问题，主题是“eslint”。
- 影响范围：主要涉及 前端。
- 改动规模：+0 / -2 行。
- 关键文件：frontend/src/components/workspace/workspace-header.tsx。

#### 38. fix: bugfix

- 提交：`[eca2b13](https://github.com/bytedance/deer-flow/commit/eca2b139cc0bb7a227dfbbeb68c920a3ffd3e4c9)`
- 日期：2026-01-27
- 做了什么：修复缺陷或回归问题，主题是“bugfix”。
- 影响范围：主要涉及 前端。
- 改动规模：+2 / -2 行。
- 关键文件：frontend/src/components/workspace/messages/message-group.tsx。

#### 39. fix: bugfix

- 提交：`[0bcbaeb](https://github.com/bytedance/deer-flow/commit/0bcbaebb7e857513233098321cfdf3f808e8e62d)`
- 日期：2026-01-27
- 做了什么：修复缺陷或回归问题，主题是“bugfix”。
- 影响范围：主要涉及 前端。
- 改动规模：+2 / -2 行。
- 关键文件：frontend/src/components/workspace/messages/message-group.tsx。

#### 40. fix: ensure MCP and skills config changes are immediately reflected

- 提交：`[1390632](https://github.com/bytedance/deer-flow/commit/139063283f53fa0a7fc7f9689b5b5479c4c60128)`
- 日期：2026-01-25
- 做了什么：修复缺陷或回归问题，主题是“ensure MCP and skills config changes are immediately reflected”。
- 影响范围：主要涉及 后端。
- 改动规模：+89 / -29 行。
- 关键文件：backend/src/gateway/app.py；backend/src/gateway/routers/mcp.py；backend/src/gateway/routers/skills.py；backend/src/mcp/cache.py；backend/src/mcp/tools.py；backend/src/skills/loader.py；backend/src/tools/tools.py。

#### 41. fix: ensure MCP and skills config changes are immediately reflected

- 提交：`[038f5d4](https://github.com/bytedance/deer-flow/commit/038f5d44f4c111f678508aaf4184f46bef775b2a)`
- 日期：2026-01-25
- 做了什么：修复缺陷或回归问题，主题是“ensure MCP and skills config changes are immediately reflected”。
- 影响范围：主要涉及 后端。
- 改动规模：+89 / -29 行。
- 关键文件：backend/src/gateway/app.py；backend/src/gateway/routers/mcp.py；backend/src/gateway/routers/skills.py；backend/src/mcp/cache.py；backend/src/mcp/tools.py；backend/src/skills/loader.py；backend/src/tools/tools.py。

#### 42. fix: many minor fixes

- 提交：`[598fed7](https://github.com/bytedance/deer-flow/commit/598fed797f24801769e581188696b66296717c4f)`
- 日期：2026-01-25
- 做了什么：修复缺陷或回归问题，主题是“many minor fixes”。
- 影响范围：主要涉及 前端。
- 改动规模：+83 / -38 行。
- 关键文件：frontend/src/app/mock/api/threads/[thread_id]/artifacts/[[...artifact_path]]/route.ts；frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/landing/sections/case-study-section.tsx；frontend/src/components/ui/spotlight-card.tsx。

#### 43. fix: many minor fixes

- 提交：`[756b396](https://github.com/bytedance/deer-flow/commit/756b396a642e5a006abf5186bbd9495197d2195d)`
- 日期：2026-01-25
- 做了什么：修复缺陷或回归问题，主题是“many minor fixes”。
- 影响范围：主要涉及 前端。
- 改动规模：+83 / -38 行。
- 关键文件：frontend/src/app/mock/api/threads/[thread_id]/artifacts/[[...artifact_path]]/route.ts；frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/landing/sections/case-study-section.tsx；frontend/src/components/ui/spotlight-card.tsx。

#### 44. fix: fix artifacts in demo mode

- 提交：`[c82f705](https://github.com/bytedance/deer-flow/commit/c82f7055414aa52c0c8d574cab20dfb8bd5d64f5)`
- 日期：2026-01-25
- 做了什么：修复缺陷或回归问题，主题是“fix artifacts in demo mode”。
- 影响范围：主要涉及 前端。
- 改动规模：+15 / -8 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/core/threads/hooks.ts。

#### 45. fix: fix artifacts in demo mode

- 提交：`[fecc5fa](https://github.com/bytedance/deer-flow/commit/fecc5faacf560237d59f9f3e0a84899b65a72a15)`
- 日期：2026-01-25
- 做了什么：修复缺陷或回归问题，主题是“fix artifacts in demo mode”。
- 影响范围：主要涉及 前端。
- 改动规模：+15 / -8 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/core/threads/hooks.ts。

#### 46. fix: remove tooltip

- 提交：`[3ac6e58](https://github.com/bytedance/deer-flow/commit/3ac6e58d4f5b4980661a22a94ad16160ebf934a6)`
- 日期：2026-01-25
- 做了什么：修复缺陷或回归问题，主题是“remove tooltip”。
- 影响范围：主要涉及 前端。
- 改动规模：+6 / -12 行。
- 关键文件：frontend/src/components/workspace/artifacts/artifact-file-detail.tsx。

#### 47. fix: remove tooltip

- 提交：`[9501ec5](https://github.com/bytedance/deer-flow/commit/9501ec5eed5359c208a11528104efe8ffb6035ef)`
- 日期：2026-01-25
- 做了什么：修复缺陷或回归问题，主题是“remove tooltip”。
- 影响范围：主要涉及 前端。
- 改动规模：+6 / -12 行。
- 关键文件：frontend/src/components/workspace/artifacts/artifact-file-detail.tsx。

#### 48. fix: fix auto select first artifact

- 提交：`[03b380c](https://github.com/bytedance/deer-flow/commit/03b380cb8b559d92fd96c659af3b4b92d309f0ce)`
- 日期：2026-01-24
- 做了什么：修复缺陷或回归问题，主题是“fix auto select first artifact”。
- 影响范围：主要涉及 前端。
- 改动规模：+12 / -2 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx。

#### 49. fix: fix auto select first artifact

- 提交：`[1e2855b](https://github.com/bytedance/deer-flow/commit/1e2855b5330e637e4ba73deac475268a4f92fa8a)`
- 日期：2026-01-24
- 做了什么：修复缺陷或回归问题，主题是“fix auto select first artifact”。
- 影响范围：主要涉及 前端。
- 改动规模：+12 / -2 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx。

#### 50. Merge pull request #17 from amszuidas/fix/tavily-api-key-config

- 提交：`[b1e7028](https://github.com/bytedance/deer-flow/commit/b1e7028ea023afa2c00d72d96e9dc895a566022e)`
- 日期：2026-01-24
- 做了什么：修复缺陷或回归问题，主题是“Merge pull request #17 from amszuidas/fix/tavily-api-key-config”。
- 影响范围：主要涉及 后端。
- 改动规模：+12 / -3 行。
- 关键文件：backend/src/community/tavily/tools.py。

#### 51. Merge pull request #17 from amszuidas/fix/tavily-api-key-config

- 提交：`[9498e78](https://github.com/bytedance/deer-flow/commit/9498e783f147c49bc16bade0861153ed8b9b2545)`
- 日期：2026-01-24
- 做了什么：修复缺陷或回归问题，主题是“Merge pull request #17 from amszuidas/fix/tavily-api-key-config”。
- 影响范围：主要涉及 后端。
- 改动规模：+12 / -3 行。
- 关键文件：backend/src/community/tavily/tools.py。

#### 52. fix: support loading tavily ak from config.yaml

- 提交：`[d6176e8](https://github.com/bytedance/deer-flow/commit/d6176e86d6d304159afba06e6f06d83b4b031d98)`
- 日期：2026-01-23
- 做了什么：修复缺陷或回归问题，主题是“support loading tavily ak from config.yaml”。
- 影响范围：主要涉及 后端。
- 改动规模：+12 / -3 行。
- 关键文件：backend/src/community/tavily/tools.py。

#### 53. fix: support loading tavily ak from config.yaml

- 提交：`[c1c8942](https://github.com/bytedance/deer-flow/commit/c1c894249143615054152fc82ddc1e9929953a52)`
- 日期：2026-01-23
- 做了什么：修复缺陷或回归问题，主题是“support loading tavily ak from config.yaml”。
- 影响范围：主要涉及 后端。
- 改动规模：+12 / -3 行。
- 关键文件：backend/src/community/tavily/tools.py。

#### 54. fix: use return value of resolve_env_variables in config loading

- 提交：`[3972485](https://github.com/bytedance/deer-flow/commit/3972485fe03cbbcdfc6b86049299712ac2e5fe06)`
- 日期：2026-01-23
- 做了什么：修复缺陷或回归问题，主题是“use return value of resolve_env_variables in config loading”。
- 影响范围：主要涉及 后端。
- 改动规模：+1 / -1 行。
- 关键文件：backend/src/config/app_config.py。

#### 55. fix: use return value of resolve_env_variables in config loading

- 提交：`[761cb6a](https://github.com/bytedance/deer-flow/commit/761cb6a7f52daee702091e3d71650247b73a8e77)`
- 日期：2026-01-23
- 做了什么：修复缺陷或回归问题，主题是“use return value of resolve_env_variables in config loading”。
- 影响范围：主要涉及 后端。
- 改动规模：+1 / -1 行。
- 关键文件：backend/src/config/app_config.py。

#### 56. fix: correct spelling

- 提交：`[eb80236](https://github.com/bytedance/deer-flow/commit/eb802361e1af2430ba825bb4deb4b2f05dfa3918)`
- 日期：2026-01-23
- 做了什么：修复缺陷或回归问题，主题是“correct spelling”。
- 影响范围：主要涉及 后端。
- 改动规模：+1 / -1 行。
- 关键文件：backend/src/sandbox/sandbox.py。

#### 57. fix: correct spelling

- 提交：`[2ef320f](https://github.com/bytedance/deer-flow/commit/2ef320f107de98dbf37f4a370695bd93dce894a0)`
- 日期：2026-01-23
- 做了什么：修复缺陷或回归问题，主题是“correct spelling”。
- 影响范围：主要涉及 后端。
- 改动规模：+1 / -1 行。
- 关键文件：backend/src/sandbox/sandbox.py。

#### 58. fix: robust environment variable resolution in config

- 提交：`[82a6ae8](https://github.com/bytedance/deer-flow/commit/82a6ae81bdf3259ebae90b8e00e22189f7f21a18)`
- 日期：2026-01-23
- 做了什么：修复缺陷或回归问题，主题是“robust environment variable resolution in config”。
- 影响范围：主要涉及 后端。
- 改动规模：+10 / -14 行。
- 关键文件：backend/src/config/app_config.py。

#### 59. fix: robust environment variable resolution in config

- 提交：`[303e025](https://github.com/bytedance/deer-flow/commit/303e0252ce1319b7c314e0f3897002003957eb38)`
- 日期：2026-01-23
- 做了什么：修复缺陷或回归问题，主题是“robust environment variable resolution in config”。
- 影响范围：主要涉及 后端。
- 改动规模：+10 / -14 行。
- 关键文件：backend/src/config/app_config.py。

#### 60. fix: fix menu item in side bar collapsed mode

- 提交：`[459d9d0](https://github.com/bytedance/deer-flow/commit/459d9d0287177280b266558d0d103902456afa73)`
- 日期：2026-01-22
- 做了什么：修复缺陷或回归问题，主题是“fix menu item in side bar collapsed mode”。
- 影响范围：主要涉及 前端。
- 改动规模：+11 / -5 行。
- 关键文件：frontend/src/components/workspace/workspace-nav-menu.tsx。

#### 61. fix: fix menu item in side bar collapsed mode

- 提交：`[6e1f63e](https://github.com/bytedance/deer-flow/commit/6e1f63e47f173ed4572dc5fe85911dbef9ae168a)`
- 日期：2026-01-22
- 做了什么：修复缺陷或回归问题，主题是“fix menu item in side bar collapsed mode”。
- 影响范围：主要涉及 前端。
- 改动规模：+11 / -5 行。
- 关键文件：frontend/src/components/workspace/workspace-nav-menu.tsx。

#### 62. fix: fix nginx conf

- 提交：`[c00f780](https://github.com/bytedance/deer-flow/commit/c00f780501a80bce25848528b3d5b714c4cb9c60)`
- 日期：2026-01-22
- 做了什么：修复缺陷或回归问题，主题是“fix nginx conf”。
- 影响范围：主要涉及 后端。
- 改动规模：+6 / -3 行。
- 关键文件：backend/Makefile。

#### 63. fix: fix nginx conf

- 提交：`[50c25f5](https://github.com/bytedance/deer-flow/commit/50c25f5c4d1bfaf6a48efdc71a6fdcb033b7e767)`
- 日期：2026-01-22
- 做了什么：修复缺陷或回归问题，主题是“fix nginx conf”。
- 影响范围：主要涉及 后端。
- 改动规模：+6 / -3 行。
- 关键文件：backend/Makefile。

#### 64. fix: update summarization configuration values

- 提交：`[11918b5](https://github.com/bytedance/deer-flow/commit/11918b52708dd639de224847ad368a81af1ad303)`
- 日期：2026-01-22
- 做了什么：修复缺陷或回归问题，主题是“update summarization configuration values”。
- 影响范围：主要涉及 配置。
- 改动规模：+5 / -5 行。
- 关键文件：config.example.yaml。

#### 65. fix: update summarization configuration values

- 提交：`[bd33f72](https://github.com/bytedance/deer-flow/commit/bd33f72017288764cf9fb8afcf5b8cc86fbe58d2)`
- 日期：2026-01-22
- 做了什么：修复缺陷或回归问题，主题是“update summarization configuration values”。
- 影响范围：主要涉及 配置。
- 改动规模：+5 / -5 行。
- 关键文件：config.example.yaml。

#### 66. Fixes(unit-test):  the unit tests error of recent change of #816 (#826)

- 提交：`[546e2e6](https://github.com/bytedance/deer-flow/commit/546e2e6234237eace252c7f17b9b92f1a98a2337)`
- 日期：2026-01-22
- 做了什么：修复缺陷或回归问题，主题是“Fixes(unit-test):  the unit tests error of recent change of #816 (#826)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+16 / -7 行。
- 关键文件：tests/unit/checkpoint/test_checkpoint.py。

#### 67. fix: handle false values correctly in (#823)

- 提交：`[6ec170c](https://github.com/bytedance/deer-flow/commit/6ec170cde5eaebef9108d0c8e2a8718e0e294aba)`
- 日期：2026-01-21
- 做了什么：修复缺陷或回归问题，主题是“handle false values correctly in (#823)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+52 / -7 行。
- 关键文件：src/config/configuration.py；tests/unit/config/test_configuration.py。

#### 68. fix: fix sandbox cp issue

- 提交：`[adbb03f](https://github.com/bytedance/deer-flow/commit/adbb03fc26933de6d8a8483796351efdd17a5b83)`
- 日期：2026-01-20
- 做了什么：修复缺陷或回归问题，主题是“fix sandbox cp issue”。
- 影响范围：主要涉及 后端。
- 改动规模：+42 / -0 行。
- 关键文件：backend/src/sandbox/tools.py。

#### 69. fix: fix sandbox cp issue

- 提交：`[c5a2771](https://github.com/bytedance/deer-flow/commit/c5a2771636cd2170d200ea214ca178751c582b0a)`
- 日期：2026-01-20
- 做了什么：修复缺陷或回归问题，主题是“fix sandbox cp issue”。
- 影响范围：主要涉及 后端。
- 改动规模：+42 / -0 行。
- 关键文件：backend/src/sandbox/tools.py。

#### 70. fix: fix skill md path

- 提交：`[5888a5b](https://github.com/bytedance/deer-flow/commit/5888a5ba16276e3ccbaf318cad9d520c5585208a)`
- 日期：2026-01-20
- 做了什么：修复缺陷或回归问题，主题是“fix skill md path”。
- 影响范围：主要涉及 后端、技能体系。
- 改动规模：+53 / -2 行。
- 关键文件：backend/src/agents/lead_agent/prompt.py；backend/src/skills/types.py；skills/public/web-design-guidelines/SKILL.md。

#### 71. fix: fix skill md path

- 提交：`[e58e5f1](https://github.com/bytedance/deer-flow/commit/e58e5f19043f4fbb9244299c5a981b07f723b163)`
- 日期：2026-01-20
- 做了什么：修复缺陷或回归问题，主题是“fix skill md path”。
- 影响范围：主要涉及 后端、技能体系。
- 改动规模：+53 / -2 行。
- 关键文件：backend/src/agents/lead_agent/prompt.py；backend/src/skills/types.py；skills/public/web-design-guidelines/SKILL.md。

#### 72. fix: fix config

- 提交：`[6ec023d](https://github.com/bytedance/deer-flow/commit/6ec023de8baec9d9e07126cbcd1b760fbb76a435)`
- 日期：2026-01-20
- 做了什么：修复缺陷或回归问题，主题是“fix config”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+2 / -5 行。
- 关键文件：extensions_config.example.json。

#### 73. fix: fix config

- 提交：`[33e6197](https://github.com/bytedance/deer-flow/commit/33e6197f65d46490e435a3f8a8a5c6c98571df98)`
- 日期：2026-01-20
- 做了什么：修复缺陷或回归问题，主题是“fix config”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+2 / -5 行。
- 关键文件：extensions_config.example.json。

#### 74. fix: fix backend

- 提交：`[d11763d](https://github.com/bytedance/deer-flow/commit/d11763dcc881a24df273e17614a23ddd2b46fa82)`
- 日期：2026-01-20
- 做了什么：修复缺陷或回归问题，主题是“fix backend”。
- 影响范围：主要涉及 后端。
- 改动规模：+2 / -2 行。
- 关键文件：backend/src/gateway/routers/**init**.py。

#### 75. fix: fix backend

- 提交：`[5c1bb67](https://github.com/bytedance/deer-flow/commit/5c1bb675ba60ef318f9b3b767c9f4fcb23baeb01)`
- 日期：2026-01-20
- 做了什么：修复缺陷或回归问题，主题是“fix backend”。
- 影响范围：主要涉及 后端。
- 改动规模：+2 / -2 行。
- 关键文件：backend/src/gateway/routers/**init**.py。

#### 76. fix: fix proxy

- 提交：`[d6c1e58](https://github.com/bytedance/deer-flow/commit/d6c1e5868d53397089b5e1746a62f80c21919ac6)`
- 日期：2026-01-19
- 做了什么：修复缺陷或回归问题，主题是“fix proxy”。
- 影响范围：主要涉及 后端。
- 改动规模：+22 / -21 行。
- 关键文件：backend/src/gateway/routers/proxy.py。

#### 77. fix: fix proxy

- 提交：`[a6fcdbf](https://github.com/bytedance/deer-flow/commit/a6fcdbf50a9a944fde1c886f9108a4822c2d7cd2)`
- 日期：2026-01-19
- 做了什么：修复缺陷或回归问题，主题是“fix proxy”。
- 影响范围：主要涉及 后端。
- 改动规模：+22 / -21 行。
- 关键文件：backend/src/gateway/routers/proxy.py。

#### 78. fix: use shared httpx client to prevent premature closure in SSE streaming

- 提交：`[1a7c853](https://github.com/bytedance/deer-flow/commit/1a7c853811443921b46c1419edd32159b3d70b42)`
- 日期：2026-01-19
- 做了什么：修复缺陷或回归问题，主题是“use shared httpx client to prevent premature closure in SSE streaming”。
- 影响范围：主要涉及 后端。
- 改动规模：+77 / -49 行。
- 关键文件：backend/src/gateway/app.py；backend/src/gateway/routers/proxy.py。

#### 79. fix: use shared httpx client to prevent premature closure in SSE streaming

- 提交：`[ffb9ed3](https://github.com/bytedance/deer-flow/commit/ffb9ed31986476d4e267fc7e02f87c2e80bfe062)`
- 日期：2026-01-19
- 做了什么：修复缺陷或回归问题，主题是“use shared httpx client to prevent premature closure in SSE streaming”。
- 影响范围：主要涉及 后端。
- 改动规模：+77 / -49 行。
- 关键文件：backend/src/gateway/app.py；backend/src/gateway/routers/proxy.py。

#### 80. fix: stop tracking .claude/settings.local.json

- 提交：`[8ea530e](https://github.com/bytedance/deer-flow/commit/8ea530e22188fa53a1676afc0ddf340ac1325d27)`
- 日期：2026-01-19
- 做了什么：修复缺陷或回归问题，主题是“stop tracking .claude/settings.local.json”。
- 影响范围：主要涉及 后端。
- 改动规模：+3 / -7 行。
- 关键文件：backend/.claude/settings.local.json；backend/.gitignore。

#### 81. fix: stop tracking .claude/settings.local.json

- 提交：`[3a4149c](https://github.com/bytedance/deer-flow/commit/3a4149c4374e1db39bfd1f1f6ac30254e0160530)`
- 日期：2026-01-19
- 做了什么：修复缺陷或回归问题，主题是“stop tracking .claude/settings.local.json”。
- 影响范围：主要涉及 后端。
- 改动规模：+3 / -7 行。
- 关键文件：backend/.claude/settings.local.json；backend/.gitignore。

#### 82. fix: fix getBackendBaseURL()

- 提交：`[1ef04c9](https://github.com/bytedance/deer-flow/commit/1ef04c94eeb86b1b81d81181faf93f75a35a130a)`
- 日期：2026-01-19
- 做了什么：修复缺陷或回归问题，主题是“fix getBackendBaseURL()”。
- 影响范围：主要涉及 前端。
- 改动规模：+6 / -5 行。
- 关键文件：frontend/src/core/config/index.ts；frontend/src/env.js。

#### 83. fix: fix getBackendBaseURL()

- 提交：`[1352b0e](https://github.com/bytedance/deer-flow/commit/1352b0e0ba8ca3ac2dbe9e6bb1334bc7555e9877)`
- 日期：2026-01-19
- 做了什么：修复缺陷或回归问题，主题是“fix getBackendBaseURL()”。
- 影响范围：主要涉及 前端。
- 改动规模：+6 / -5 行。
- 关键文件：frontend/src/core/config/index.ts；frontend/src/env.js。

#### 84. fix: decode URL

- 提交：`[63fa500](https://github.com/bytedance/deer-flow/commit/63fa500716e1a1c2380939b8969ddf52b5bcb4b7)`
- 日期：2026-01-18
- 做了什么：修复缺陷或回归问题，主题是“decode URL”。
- 影响范围：主要涉及 前端。
- 改动规模：+2 / -2 行。
- 关键文件：frontend/src/components/workspace/artifacts/artifact-file-detail.tsx；frontend/src/components/workspace/artifacts/file-viewer.tsx。

#### 85. fix: decode URL

- 提交：`[c321c92](https://github.com/bytedance/deer-flow/commit/c321c9293a8d0f960b9405d5f7844994c2e767fe)`
- 日期：2026-01-18
- 做了什么：修复缺陷或回归问题，主题是“decode URL”。
- 影响范围：主要涉及 前端。
- 改动规模：+2 / -2 行。
- 关键文件：frontend/src/components/workspace/artifacts/artifact-file-detail.tsx；frontend/src/components/workspace/artifacts/file-viewer.tsx。

#### 86. fix: Long thinking but with empty content (#12)

- 提交：`[c50540e](https://github.com/bytedance/deer-flow/commit/c50540e3fc610aa51a6087c8d4e0c8d251b2d0a0)`
- 日期：2026-01-18
- 做了什么：修复缺陷或回归问题，主题是“Long thinking but with empty content (#12)”。
- 影响范围：主要涉及 后端。
- 改动规模：+8 / -10 行。
- 关键文件：backend/debug.py；backend/docs/TODO.md；backend/src/agents/lead_agent/prompt.py。

#### 87. fix: Long thinking but with empty content (#12)

- 提交：`[6f97dde](https://github.com/bytedance/deer-flow/commit/6f97dde5d1654ea853417a2fca1a0da038f1a38a)`
- 日期：2026-01-18
- 做了什么：修复缺陷或回归问题，主题是“Long thinking but with empty content (#12)”。
- 影响范围：主要涉及 后端。
- 改动规模：+8 / -10 行。
- 关键文件：backend/debug.py；backend/docs/TODO.md；backend/src/agents/lead_agent/prompt.py。

#### 88. fix: fix message grouping issues

- 提交：`[6bf187c](https://github.com/bytedance/deer-flow/commit/6bf187c1c24b8191293beb6a2c01147f8848e867)`
- 日期：2026-01-18
- 做了什么：修复缺陷或回归问题，主题是“fix message grouping issues”。
- 影响范围：主要涉及 前端。
- 改动规模：+57 / -57 行。
- 关键文件：frontend/src/components/workspace/input-box.tsx；frontend/src/components/workspace/messages/message-list.tsx；frontend/src/core/messages/utils.ts。

#### 89. fix: fix message grouping issues

- 提交：`[71eadc9](https://github.com/bytedance/deer-flow/commit/71eadc942f80c9c2512286604caea0b46473d63a)`
- 日期：2026-01-18
- 做了什么：修复缺陷或回归问题，主题是“fix message grouping issues”。
- 影响范围：主要涉及 前端。
- 改动规模：+57 / -57 行。
- 关键文件：frontend/src/components/workspace/input-box.tsx；frontend/src/components/workspace/messages/message-list.tsx；frontend/src/core/messages/utils.ts。

#### 90. fix: fix backend python execution (#10)

- 提交：`[bfe8a24](https://github.com/bytedance/deer-flow/commit/bfe8a243504cf726edfdcf7f818f461df09736dd)`
- 日期：2026-01-18
- 做了什么：修复缺陷或回归问题，主题是“fix backend python execution (#10)”。
- 影响范围：主要涉及 后端。
- 改动规模：+4 / -4 行。
- 关键文件：backend/Makefile。

#### 91. fix: fix backend python execution (#10)

- 提交：`[5a0912d](https://github.com/bytedance/deer-flow/commit/5a0912d0fda136b6d7584a0e36c4ba7f6d42ccb7)`
- 日期：2026-01-18
- 做了什么：修复缺陷或回归问题，主题是“fix backend python execution (#10)”。
- 影响范围：主要涉及 后端。
- 改动规模：+4 / -4 行。
- 关键文件：backend/Makefile。

#### 92. fix(docker): nodejs  CVE-2025-59466 (#818)

- 提交：`[2ed0eeb](https://github.com/bytedance/deer-flow/commit/2ed0eeb10750fa67f05de2fc40992f7a7ab76760)`
- 日期：2026-01-17
- 做了什么：修复缺陷或回归问题，主题是“nodejs  CVE-2025-59466 (#818)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+2 / -2 行。
- 关键文件：web/Dockerfile。

#### 93. fix: fix z index

- 提交：`[caf761b](https://github.com/bytedance/deer-flow/commit/caf761be599edc47f8529ce75378f3fdcd1a7e57)`
- 日期：2026-01-17
- 做了什么：修复缺陷或回归问题，主题是“fix z index”。
- 影响范围：主要涉及 前端。
- 改动规模：+2 / -2 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx。

#### 94. fix: fix z index

- 提交：`[88eb341](https://github.com/bytedance/deer-flow/commit/88eb3411158785c0dd15ddc1624ff2929c5bc142)`
- 日期：2026-01-17
- 做了什么：修复缺陷或回归问题，主题是“fix z index”。
- 影响范围：主要涉及 前端。
- 改动规模：+2 / -2 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx。

#### 95. fix: remove unused imports

- 提交：`[df65010](https://github.com/bytedance/deer-flow/commit/df65010e5f0121e8e33c488ca2ac7c9b62537372)`
- 日期：2026-01-17
- 做了什么：修复缺陷或回归问题，主题是“remove unused imports”。
- 影响范围：主要涉及 前端。
- 改动规模：+0 / -2 行。
- 关键文件：frontend/src/components/workspace/input-box.tsx。

#### 96. fix: remove unused imports

- 提交：`[e418eb6](https://github.com/bytedance/deer-flow/commit/e418eb61100b639be9d4367f4e3567a415ffc114)`
- 日期：2026-01-17
- 做了什么：修复缺陷或回归问题，主题是“remove unused imports”。
- 影响范围：主要涉及 前端。
- 改动规模：+0 / -2 行。
- 关键文件：frontend/src/components/workspace/input-box.tsx。

#### 97. fix: remove unused imports

- 提交：`[97dbcc4](https://github.com/bytedance/deer-flow/commit/97dbcc4bd6160193159bb35bc358d7cfb2719d62)`
- 日期：2026-01-17
- 做了什么：修复缺陷或回归问题，主题是“remove unused imports”。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -5 行。
- 关键文件：frontend/src/components/workspace/messages/message-list-item.tsx。

#### 98. fix: remove unused imports

- 提交：`[63f3c9e](https://github.com/bytedance/deer-flow/commit/63f3c9e2bb1bdb8b44a5c33ff9a34f66ea85ea75)`
- 日期：2026-01-17
- 做了什么：修复缺陷或回归问题，主题是“remove unused imports”。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -5 行。
- 关键文件：frontend/src/components/workspace/messages/message-list-item.tsx。

#### 99. fix: do not display 'Untitled'

- 提交：`[584eed0](https://github.com/bytedance/deer-flow/commit/584eed01662562d8fe333f7414917568693ea064)`
- 日期：2026-01-17
- 做了什么：修复缺陷或回归问题，主题是“do not display 'Untitled'”。
- 影响范围：主要涉及 前端。
- 改动规模：+9 / -4 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx。

#### 100. fix: do not display 'Untitled'

- 提交：`[be1e016](https://github.com/bytedance/deer-flow/commit/be1e016ed476ea87a1886fd161c137be693e53c3)`
- 日期：2026-01-17
- 做了什么：修复缺陷或回归问题，主题是“do not display 'Untitled'”。
- 影响范围：主要涉及 前端。
- 改动规模：+9 / -4 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx。

#### 101. fix: fix broken when SSE

- 提交：`[34ca58e](https://github.com/bytedance/deer-flow/commit/34ca58ed1b6e4957cb39a5f08388fad98614e7b5)`
- 日期：2026-01-16
- 做了什么：修复缺陷或回归问题，主题是“fix broken when SSE”。
- 影响范围：主要涉及 前端。
- 改动规模：+16 / -16 行。
- 关键文件：frontend/src/components/workspace/message-list/message-group.tsx；frontend/src/components/workspace/message-list/present-file-list.tsx；frontend/src/core/messages/utils.ts。

#### 102. fix: fix broken when SSE

- 提交：`[16a5ed9](https://github.com/bytedance/deer-flow/commit/16a5ed9a739ef9c1073f88f49ebd73a36bae9252)`
- 日期：2026-01-16
- 做了什么：修复缺陷或回归问题，主题是“fix broken when SSE”。
- 影响范围：主要涉及 前端。
- 改动规模：+16 / -16 行。
- 关键文件：frontend/src/components/workspace/message-list/message-group.tsx；frontend/src/components/workspace/message-list/present-file-list.tsx；frontend/src/core/messages/utils.ts。

#### 103. fix: lastStep could be empty

- 提交：`[f19e3ae](https://github.com/bytedance/deer-flow/commit/f19e3ae8acde8c3a8abf45b25c444dee87ed3e5f)`
- 日期：2026-01-16
- 做了什么：修复缺陷或回归问题，主题是“lastStep could be empty”。
- 影响范围：主要涉及 前端。
- 改动规模：+5 / -2 行。
- 关键文件：frontend/src/components/workspace/message-list/message-group.tsx。

#### 104. fix: lastStep could be empty

- 提交：`[5ef3cb5](https://github.com/bytedance/deer-flow/commit/5ef3cb57ee66cd4acb8834cd382ccf9f1852bfbf)`
- 日期：2026-01-16
- 做了什么：修复缺陷或回归问题，主题是“lastStep could be empty”。
- 影响范围：主要涉及 前端。
- 改动规模：+5 / -2 行。
- 关键文件：frontend/src/components/workspace/message-list/message-group.tsx。

#### 105. fix: navigate to home only in open-mode

- 提交：`[1f03fb3](https://github.com/bytedance/deer-flow/commit/1f03fb3749f7a704bdad77558273742e39ee4524)`
- 日期：2026-01-16
- 做了什么：修复缺陷或回归问题，主题是“navigate to home only in open-mode”。
- 影响范围：主要涉及 前端。
- 改动规模：+21 / -21 行。
- 关键文件：frontend/src/components/workspace/workspace-header.tsx。

#### 106. fix: navigate to home only in open-mode

- 提交：`[5c94e6d](https://github.com/bytedance/deer-flow/commit/5c94e6d222795f2f4e114debecd211cff72de269)`
- 日期：2026-01-16
- 做了什么：修复缺陷或回归问题，主题是“navigate to home only in open-mode”。
- 影响范围：主要涉及 前端。
- 改动规模：+21 / -21 行。
- 关键文件：frontend/src/components/workspace/workspace-header.tsx。

#### 107. fix: fix local path for local sandbox (#3)

- 提交：`[a39f799](https://github.com/bytedance/deer-flow/commit/a39f799a7e740be121e1cffccbcea7e9f539d6b5)`
- 日期：2026-01-15
- 做了什么：修复缺陷或回归问题，主题是“fix local path for local sandbox (#3)”。
- 影响范围：主要涉及 后端、其他模块。
- 改动规模：+123 / -10 行。
- 关键文件：.gitignore；backend/src/agents/lead_agent/prompt.py；backend/src/sandbox/tools.py。

#### 108. fix: fix local path for local sandbox (#3)

- 提交：`[3b879e2](https://github.com/bytedance/deer-flow/commit/3b879e277eb7652b812c0952d6a4daca955c452a)`
- 日期：2026-01-15
- 做了什么：修复缺陷或回归问题，主题是“fix local path for local sandbox (#3)”。
- 影响范围：主要涉及 后端、其他模块。
- 改动规模：+123 / -10 行。
- 关键文件：.gitignore；backend/src/agents/lead_agent/prompt.py；backend/src/sandbox/tools.py。

#### 109. fix(config): Add support for MCP server configuration parameters (#812)

- 提交：`[6b73a53](https://github.com/bytedance/deer-flow/commit/6b73a5399951da8adbf579a86832a5251fe8f827)`
- 日期：2026-01-10
- 做了什么：修复缺陷或回归问题，主题是“Add support for MCP server configuration parameters (#812)”。
- 影响范围：主要涉及 其他模块、文档。
- 改动规模：+207 / -13 行。
- 关键文件：docs/mcp_integrations.md；src/server/app.py；src/server/mcp_request.py；src/server/mcp_utils.py；tests/unit/server/test_app.py；tests/unit/server/test_mcp_request.py；tests/unit/server/test_mcp_utils.py；web/src/core/mcp/schema.ts。

#### 110. fix(frontend):eliminating the empty divider issue on the frontend (#811)

- 提交：`[e52e69b](https://github.com/bytedance/deer-flow/commit/e52e69bdd4c0a41d83835d77eeaebfd627aebdce)`
- 日期：2026-01-09
- 做了什么：修复缺陷或回归问题，主题是“eliminating the empty divider issue on the frontend (#811)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+293 / -17 行。
- 关键文件：web/src/core/store/store.ts；web/tests/store.test.ts。

#### 111. fix(frontend): passing the MCP header and env setting to backend (#810)

- 提交：`[3360403](https://github.com/bytedance/deer-flow/commit/336040310c624f2b526f043d7e540657544f4fc8)`
- 日期：2026-01-09
- 做了什么：修复缺陷或回归问题，主题是“passing the MCP header and env setting to backend (#810)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+7 / -0 行。
- 关键文件：web/src/app/settings/dialogs/add-mcp-server-dialog.tsx；web/src/core/mcp/schema.ts。

#### 112. Fix message validation JSON import (#809)

- 提交：`[8c59f63](https://github.com/bytedance/deer-flow/commit/8c59f63d1b1b46bd2382d115a5e6eec70202295c)`
- 日期：2026-01-09
- 做了什么：修复缺陷或回归问题，主题是“Fix message validation JSON import (#809)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+3 / -1 行。
- 关键文件：src/utils/context_manager.py。

#### 113. fix: Add runtime parameter to compress_messages method(#803)

- 提交：`[a376b0c](https://github.com/bytedance/deer-flow/commit/a376b0cb4e28a4a17c2ba2b2baa38e55e36e3eb3)`
- 日期：2026-01-07
- 做了什么：修复缺陷或回归问题，主题是“Add runtime parameter to compress_messages method(#803)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+30 / -1 行。
- 关键文件：src/utils/context_manager.py；tests/unit/utils/test_context_manager.py。

#### 114. fix: migrate from deprecated create_react_agent to langchain.agents.create_agent (#802)

- 提交：`[d4ab77d](https://github.com/bytedance/deer-flow/commit/d4ab77de5c630855b13c735828c61dcc076294cd)`
- 日期：2026-01-07
- 做了什么：修复缺陷或回归问题，主题是“migrate from deprecated create_react_agent to langchain.agents.create_agent (#802)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+440 / -14 行。
- 关键文件：src/agents/agents.py；src/prompts/template.py；tests/integration/test_tool_interceptor_integration.py；tests/unit/agents/test_middleware.py；tests/unit/graph/test_agent_locale_restoration.py。

#### 115. fix(frontend):added the display of the 'analyst' message #800 (#801)

- 提交：`[1ced90b](https://github.com/bytedance/deer-flow/commit/1ced90b0553f44f68556eceb2385f6ddc1a27551)`
- 日期：2026-01-06
- 做了什么：修复缺陷或回归问题，主题是“added the display of the 'analyst' message #800 (#801)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+4 / -2 行。
- 关键文件：web/src/core/messages/types.ts；web/src/core/store/store.ts。

#### 116. fix(frontend): render all tool calls in the frontend #796 (#797)

- 提交：`[7ebbb53](https://github.com/bytedance/deer-flow/commit/7ebbb53b57ce2796feab37ab3543fad2b5e25dce)`
- 日期：2026-01-05
- 做了什么：修复缺陷或回归问题，主题是“render all tool calls in the frontend #796 (#797)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+18 / -15 行。
- 关键文件：web/src/app/chat/components/research-activities-block.tsx。

#### 117. fix(log): Enable the logging level  when enabling the DEBUG environment variable (#793)

- 提交：`[275aab9](https://github.com/bytedance/deer-flow/commit/275aab9d42dbffab36809932e8c8aa2823962809)`
- 日期：2026-01-01
- 做了什么：修复缺陷或回归问题，主题是“Enable the logging level  when enabling the DEBUG environment variable (#793)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+25 / -3 行。
- 关键文件：server.py；src/server/app.py；src/workflow.py。

## 2026-02

- 新功能/增强：226 条
- Bug 修复：100 条

### 新功能 / 增强

#### 1. test: add Gateway conformance tests for DeerFlowClient (#931)

- 提交：`[30d9487](https://github.com/bytedance/deer-flow/commit/30d948711fc55c37237cec83ae3348503177b3b3)`
- 日期：2026-02-28
- 做了什么：补充/增强测试体系，主题是“add Gateway conformance tests for DeerFlowClient (#931)”。
- 影响范围：主要涉及 后端、文档。
- 改动规模：+625 / -232 行。
- 关键文件：README.md；backend/CLAUDE.md；backend/src/client.py；backend/tests/test_client.py；backend/tests/test_client_live.py。

#### 2. feat: add DeerFlowClient for embedded programmatic access (#926)

- 提交：`[9d48c42](https://github.com/bytedance/deer-flow/commit/9d48c42a20c6e41e8132dcd67753d356b85a338c)`
- 日期：2026-02-28
- 做了什么：新增或增强功能，主题是“add DeerFlowClient for embedded programmatic access (#926)”。
- 影响范围：主要涉及 后端、其他模块、文档。
- 改动规模：+2450 / -2 行。
- 关键文件：.gitignore；README.md；backend/.gitignore；backend/CLAUDE.md；backend/src/client.py；backend/tests/test_client.py；backend/tests/test_client_live.py。

#### 3. feat: add Novita AI as optional LLM provider (#910)

- 提交：`[e62b3d4](https://github.com/bytedance/deer-flow/commit/e62b3d41679c5d6306d07220f9cb601c0b271a2c)`
- 日期：2026-02-27
- 做了什么：新增或增强功能，主题是“add Novita AI as optional LLM provider (#910)”。
- 影响范围：主要涉及 其他模块、文档、后端。
- 改动规模：+39 / -1 行。
- 关键文件：.env.example；README.md；backend/docs/CONFIGURATION.md；config.example.yaml。

#### 4. feat(subagents): make subagent timeout configurable via config.yaml (#897)

- 提交：`[faa4220](https://github.com/bytedance/deer-flow/commit/faa422072c0df116ad24d87ca6fcb6d7e5a276ca)`
- 日期：2026-02-25
- 做了什么：新增或增强功能，主题是“make subagent timeout configurable via config.yaml (#897)”。
- 影响范围：主要涉及 后端、CI/CD、配置。
- 改动规模：+554 / -40 行。
- 关键文件：.github/workflows/backend-unit-tests.yml；backend/CLAUDE.md；backend/Makefile；backend/src/agents/lead_agent/agent.py；backend/src/community/aio_sandbox/remote_backend.py；backend/src/config/app_config.py；backend/src/config/subagents_config.py；backend/src/config/tracing_config.py。

#### 5. feat: add LangSmith tracing integration (#878)

- 提交：`[85af540](https://github.com/bytedance/deer-flow/commit/85af540076922adb5a869013015837feed983d2c)`
- 日期：2026-02-21
- 做了什么：新增或增强功能，主题是“add LangSmith tracing integration (#878)”。
- 影响范围：主要涉及 后端。
- 改动规模：+84 / -1 行。
- 关键文件：backend/src/agents/lead_agent/agent.py；backend/src/config/**init**.py；backend/src/config/tracing_config.py；backend/src/models/factory.py。

#### 6. chore: add a Makefile command to create all required local configuration files (#883)

- 提交：`[0d7c082](https://github.com/bytedance/deer-flow/commit/0d7c0826f0226ccdec16c26ca78c2dcaa237c150)`
- 日期：2026-02-19
- 做了什么：新增或增强功能，主题是“add a Makefile command to create all required local configuration files (#883)”。
- 影响范围：主要涉及 其他模块、文档。
- 改动规模：+18 / -6 行。
- 关键文件：Makefile；README.md。

#### 7. docs: add videos and official website (#865)

- 提交：`[2d3a22a](https://github.com/bytedance/deer-flow/commit/2d3a22aeb09a1fa570656d724d8d22e9840fed2d)`
- 日期：2026-02-14
- 做了什么：补充文档能力，主题是“add videos and official website (#865)”。
- 影响范围：主要涉及 文档。
- 改动规模：+10 / -0 行。
- 关键文件：README.md。

#### 8. docs:Add security policy documentation (#864)

- 提交：`[d796c5a](https://github.com/bytedance/deer-flow/commit/d796c5a32829303b1a3ff9cfa0a6429b15524c83)`
- 日期：2026-02-14
- 做了什么：补充文档能力，主题是“Add security policy documentation (#864)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+12 / -0 行。
- 关键文件：SECURITY.md。

#### 9. feat(tool): Adding license header check and apply tool (#857)

- 提交：`[56b8c3a](https://github.com/bytedance/deer-flow/commit/56b8c3a496988dd095402d611cd9bca49dfd8487)`
- 日期：2026-02-13
- 做了什么：新增或增强功能，主题是“Adding license header check and apply tool (#857)”。
- 影响范围：主要涉及 其他模块、文档、脚本工具。
- 改动规模：+475 / -1 行。
- 关键文件：LICENSE_HEADER；LICENSE_HEADER_TS；Makefile；docs/LICENSE_HEADERS.md；pre-commit；scripts/license_header.py。

#### 10. feat: make max concurrent subagents configurable via runtime config

- 提交：`[770d92f](https://github.com/bytedance/deer-flow/commit/770d92fe364240d485b1db33730bf14908dc9580)`
- 日期：2026-02-11
- 做了什么：新增或增强功能，主题是“make max concurrent subagents configurable via runtime config”。
- 影响范围：主要涉及 后端。
- 改动规模：+75 / -52 行。
- 关键文件：backend/debug.py；backend/src/agents/lead_agent/agent.py；backend/src/agents/lead_agent/prompt.py；backend/src/agents/middlewares/subagent_limit_middleware.py；backend/src/subagents/executor.py。

#### 11. feat: enable skills support for subagents

- 提交：`[4a85c5d](https://github.com/bytedance/deer-flow/commit/4a85c5de7bccf30e21702c7889b7e49af8f0135d)`
- 日期：2026-02-11
- 做了什么：新增或增强功能，主题是“enable skills support for subagents”。
- 影响范围：主要涉及 后端。
- 改动规模：+61 / -42 行。
- 关键文件：backend/src/agents/lead_agent/prompt.py；backend/src/tools/builtins/task_tool.py。

#### 12. chore: add pnpm-workspace.yaml

- 提交：`[ebf4ec2](https://github.com/bytedance/deer-flow/commit/ebf4ec2786786d25cfdb817317dad4d34714447c)`
- 日期：2026-02-10
- 做了什么：新增或增强功能，主题是“add pnpm-workspace.yaml”。
- 影响范围：主要涉及 前端。
- 改动规模：+2 / -0 行。
- 关键文件：frontend/pnpm-workspace.yaml。

#### 13. chore: add .npmrc back

- 提交：`[eb287f0](https://github.com/bytedance/deer-flow/commit/eb287f095af421c1f82a283da48aac6ba9ce9fe7)`
- 日期：2026-02-10
- 做了什么：新增或增强功能，主题是“add .npmrc back”。
- 影响范围：主要涉及 前端。
- 改动规模：+2 / -0 行。
- 关键文件：frontend/.npmrc。

#### 14. feat: 改进设置页面UI和国际化支持 / Improve settings pages UI and i18n support

- 提交：`[f87d567](https://github.com/bytedance/deer-flow/commit/f87d5678f3bd000e1e4d16e14f52cfe1fbfb1eaa)`
- 日期：2026-02-10
- 做了什么：新增或增强功能，主题是“改进设置页面UI和国际化支持 / Improve settings pages UI and i18n support”。
- 影响范围：主要涉及 前端。
- 改动规模：+82 / -49 行。
- 关键文件：frontend/package.json；frontend/pnpm-lock.yaml；frontend/src/components/workspace/settings/memory-settings-page.tsx；frontend/src/components/workspace/settings/skill-settings-page.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts；frontend/src/core/i18n/locales/zh-CN.ts；frontend/src/core/streamdown/plugins.ts。

#### 15. Merge branch 'experimental' of github.com:hetaoBackend/deer-flow into feat/citations

- 提交：`[d51e6e2](https://github.com/bytedance/deer-flow/commit/d51e6e2f435fd3096e03aa045978060a018eb560)`
- 日期：2026-02-09
- 做了什么：新增或增强功能，主题是“Merge branch 'experimental' of github.com:hetaoBackend/deer-flow into feat/citations”。
- 影响范围：主要涉及 容器部署、后端、其他模块。
- 改动规模：+981 / -94 行。
- 关键文件：.dockerignore；CONTRIBUTING.md；Makefile；README.md；backend/Dockerfile；backend/langgraph.json；backend/pyproject.toml；backend/src/agents/lead_agent/agent.py。

#### 16. Merge branch 'experimental' of github.com:hetaoBackend/deer-flow into feat/citations

- 提交：`[1af14bf](https://github.com/bytedance/deer-flow/commit/1af14bf7e4e46d7fc45ebccd3ae69b30f28e445b)`
- 日期：2026-02-09
- 做了什么：新增或增强功能，主题是“Merge branch 'experimental' of github.com:hetaoBackend/deer-flow into feat/citations”。
- 影响范围：主要涉及 容器部署、后端、其他模块。
- 改动规模：+981 / -94 行。
- 关键文件：.dockerignore；CONTRIBUTING.md；Makefile；README.md；backend/Dockerfile；backend/langgraph.json；backend/pyproject.toml；backend/src/agents/lead_agent/agent.py。

#### 17. Add Kubernetes-based sandbox provider for multi-instance support (#19)

- 提交：`[7b7e32f](https://github.com/bytedance/deer-flow/commit/7b7e32f2625421392b8a95b4cad4cb765e52e481)`
- 日期：2026-02-09
- 做了什么：新增或增强功能，主题是“Add Kubernetes-based sandbox provider for multi-instance support (#19)”。
- 影响范围：主要涉及 容器部署、后端、其他模块。
- 改动规模：+981 / -94 行。
- 关键文件：.dockerignore；CONTRIBUTING.md；Makefile；README.md；backend/Dockerfile；backend/langgraph.json；backend/pyproject.toml；backend/src/agents/lead_agent/agent.py。

#### 18. Add Kubernetes-based sandbox provider for multi-instance support (#19)

- 提交：`[b6da3a2](https://github.com/bytedance/deer-flow/commit/b6da3a219e30c64682058e3440e4322644e3ff77)`
- 日期：2026-02-09
- 做了什么：新增或增强功能，主题是“Add Kubernetes-based sandbox provider for multi-instance support (#19)”。
- 影响范围：主要涉及 容器部署、后端、其他模块。
- 改动规模：+981 / -94 行。
- 关键文件：.dockerignore；CONTRIBUTING.md；Makefile；README.md；backend/Dockerfile；backend/langgraph.json；backend/pyproject.toml；backend/src/agents/lead_agent/agent.py。

#### 19. Merge upstream/experimental: resolve conflicts (keep feat/citations)

- 提交：`[c89bd9e](https://github.com/bytedance/deer-flow/commit/c89bd9edc9c4f8953a5b01304f8709eba1c073cc)`
- 日期：2026-02-09
- 做了什么：新增或增强功能，主题是“Merge upstream/experimental: resolve conflicts (keep feat/citations)”。
- 影响范围：主要涉及 前端。
- 改动规模：+78 / -32 行。
- 关键文件：frontend/src/components/workspace/artifacts/artifact-file-detail.tsx；frontend/src/components/workspace/messages/message-list-item.tsx；frontend/src/components/workspace/messages/subtask-card.tsx。

#### 20. Merge upstream/experimental: resolve conflicts (keep feat/citations)

- 提交：`[8a2cac7](https://github.com/bytedance/deer-flow/commit/8a2cac7b5a9a3cbdc2283b78d9deead85edea5ff)`
- 日期：2026-02-09
- 做了什么：新增或增强功能，主题是“Merge upstream/experimental: resolve conflicts (keep feat/citations)”。
- 影响范围：主要涉及 前端。
- 改动规模：+78 / -32 行。
- 关键文件：frontend/src/components/workspace/artifacts/artifact-file-detail.tsx；frontend/src/components/workspace/messages/message-list-item.tsx；frontend/src/components/workspace/messages/subtask-card.tsx。

#### 21. feat(citations): inline citation links with [citation:Title](URL)

- 提交：`[2f50e5d](https://github.com/bytedance/deer-flow/commit/2f50e5d96946859127a202d26b625ef3ba624487)`
- 日期：2026-02-09
- 做了什么：新增或增强功能，主题是“inline citation links with [citation:Title](URL)”。
- 影响范围：主要涉及 前端、后端。
- 改动规模：+133 / -27 行。
- 关键文件：backend/src/agents/lead_agent/prompt.py；backend/src/subagents/builtins/general_purpose.py；frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/workspace/artifacts/artifact-file-detail.tsx；frontend/src/components/workspace/citations/citation-link.tsx；frontend/src/components/workspace/messages/markdown-content.tsx；frontend/src/components/workspace/messages/message-group.tsx；frontend/src/components/workspace/messages/message-list-item.tsx。

#### 22. feat: basic implmenetation

- 提交：`[69c8b41](https://github.com/bytedance/deer-flow/commit/69c8b411866bdafd82b48caf7c9c3fb34ba454f6)`
- 日期：2026-02-09
- 做了什么：新增或增强功能，主题是“basic implmenetation”。
- 影响范围：主要涉及 前端。
- 改动规模：+110 / -34 行。
- 关键文件：frontend/src/components/workspace/messages/markdown-content.tsx；frontend/src/components/workspace/messages/message-list-item.tsx；frontend/src/components/workspace/messages/message-list.tsx。

#### 23. feat: basic implmenetation

- 提交：`[554ec7a](https://github.com/bytedance/deer-flow/commit/554ec7a91e56e454058baf8bb67fb8951fbb4e82)`
- 日期：2026-02-09
- 做了什么：新增或增强功能，主题是“basic implmenetation”。
- 影响范围：主要涉及 前端。
- 改动规模：+110 / -34 行。
- 关键文件：frontend/src/components/workspace/messages/markdown-content.tsx；frontend/src/components/workspace/messages/message-list-item.tsx；frontend/src/components/workspace/messages/message-list.tsx。

#### 24. feat(frontend): unify citation logic and prevent half-finished citations

- 提交：`[4f9d1d5](https://github.com/bytedance/deer-flow/commit/4f9d1d524ead47dae804fa34c7e14b420fc7ca7a)`
- 日期：2026-02-09
- 做了什么：新增或增强功能，主题是“unify citation logic and prevent half-finished citations”。
- 影响范围：主要涉及 前端。
- 改动规模：+310 / -162 行。
- 关键文件：frontend/src/components/ai-elements/inline-citation.tsx；frontend/src/components/workspace/artifacts/artifact-file-detail.tsx；frontend/src/components/workspace/messages/message-group.tsx；frontend/src/components/workspace/messages/message-list-item.tsx；frontend/src/components/workspace/messages/message-list.tsx；frontend/src/components/workspace/messages/safe-citation-content.tsx；frontend/src/components/workspace/messages/subtask-card.tsx；frontend/src/core/citations/index.ts。

#### 25. feat(frontend): unify citation logic and prevent half-finished citations

- 提交：`[a4268cb](https://github.com/bytedance/deer-flow/commit/a4268cb6d32a33e98568d723b96721bf67d8a46d)`
- 日期：2026-02-09
- 做了什么：新增或增强功能，主题是“unify citation logic and prevent half-finished citations”。
- 影响范围：主要涉及 前端。
- 改动规模：+310 / -162 行。
- 关键文件：frontend/src/components/ai-elements/inline-citation.tsx；frontend/src/components/workspace/artifacts/artifact-file-detail.tsx；frontend/src/components/workspace/messages/message-group.tsx；frontend/src/components/workspace/messages/message-list-item.tsx；frontend/src/components/workspace/messages/message-list.tsx；frontend/src/components/workspace/messages/safe-citation-content.tsx；frontend/src/components/workspace/messages/subtask-card.tsx；frontend/src/core/citations/index.ts。

#### 26. feat: update translations

- 提交：`[cbe0f3b](https://github.com/bytedance/deer-flow/commit/cbe0f3b32fed02386114365c5385f49451d8ebd6)`
- 日期：2026-02-09
- 做了什么：新增或增强功能，主题是“update translations”。
- 影响范围：主要涉及 前端。
- 改动规模：+2 / -2 行。
- 关键文件：frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/zh-CN.ts。

#### 27. feat: update translations

- 提交：`[738c509](https://github.com/bytedance/deer-flow/commit/738c509c7e256ea5ef2a5e3545fb9f32a2f57484)`
- 日期：2026-02-09
- 做了什么：新增或增强功能，主题是“update translations”。
- 影响范围：主要涉及 前端。
- 改动规模：+2 / -2 行。
- 关键文件：frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/zh-CN.ts。

#### 28. feat: enforce subagent concurrency limit of 3 per turn with batch execution

- 提交：`[f68b3c2](https://github.com/bytedance/deer-flow/commit/f68b3c26c35b677bef45d8ae20a034c130672182)`
- 日期：2026-02-09
- 做了什么：新增或增强功能，主题是“enforce subagent concurrency limit of 3 per turn with batch execution”。
- 影响范围：主要涉及 后端、前端。
- 改动规模：+1321 / -1894 行。
- 关键文件：backend/src/agents/lead_agent/prompt.py；frontend/pnpm-lock.yaml。

#### 29. feat: enforce subagent concurrency limit of 3 per turn with batch execution

- 提交：`[3aa45ff](https://github.com/bytedance/deer-flow/commit/3aa45ff035d7c1a8cc7722b12672a0534c90107a)`
- 日期：2026-02-09
- 做了什么：新增或增强功能，主题是“enforce subagent concurrency limit of 3 per turn with batch execution”。
- 影响范围：主要涉及 后端、前端。
- 改动规模：+1321 / -1894 行。
- 关键文件：backend/src/agents/lead_agent/prompt.py；frontend/pnpm-lock.yaml。

#### 30. chore: add pre-commit hook to reject *@bytedance.com author/committer email

- 提交：`[804d988](https://github.com/bytedance/deer-flow/commit/804d988002d6598399c997c62c902bd87a3e38ca)`
- 日期：2026-02-09
- 做了什么：新增或增强功能，主题是“add pre-commit hook to reject *@bytedance.com author/committer email”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+29 / -0 行。
- 关键文件：.githooks/pre-commit。

#### 31. chore: add pre-commit hook to reject *@bytedance.com author/committer email

- 提交：`[79c85d6](https://github.com/bytedance/deer-flow/commit/79c85d641054799c864a2d5cc3e0d34b6e7355b2)`
- 日期：2026-02-09
- 做了什么：新增或增强功能，主题是“add pre-commit hook to reject *@bytedance.com author/committer email”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+29 / -0 行。
- 关键文件：.githooks/pre-commit。

#### 32. feat: add DanglingToolCallMiddleware and SubagentLimitMiddleware

- 提交：`[caf12da](https://github.com/bytedance/deer-flow/commit/caf12da0f2062a8cd81a76df07585eba27d5077d)`
- 日期：2026-02-09
- 做了什么：新增或增强功能，主题是“add DanglingToolCallMiddleware and SubagentLimitMiddleware”。
- 影响范围：主要涉及 后端。
- 改动规模：+155 / -32 行。
- 关键文件：backend/CLAUDE.md；backend/src/agents/lead_agent/agent.py；backend/src/agents/middlewares/dangling_tool_call_middleware.py；backend/src/agents/middlewares/subagent_limit_middleware.py；backend/src/subagents/executor.py；backend/src/tools/builtins/task_tool.py。

#### 33. feat: add DanglingToolCallMiddleware and SubagentLimitMiddleware

- 提交：`[48e3039](https://github.com/bytedance/deer-flow/commit/48e303905567576ee9939ca02420688e8d532c91)`
- 日期：2026-02-09
- 做了什么：新增或增强功能，主题是“add DanglingToolCallMiddleware and SubagentLimitMiddleware”。
- 影响范围：主要涉及 后端。
- 改动规模：+155 / -32 行。
- 关键文件：backend/CLAUDE.md；backend/src/agents/lead_agent/agent.py；backend/src/agents/middlewares/dangling_tool_call_middleware.py；backend/src/agents/middlewares/subagent_limit_middleware.py；backend/src/subagents/executor.py；backend/src/tools/builtins/task_tool.py。

#### 34. feat: citations prompts, path_utils, and citation code cleanup

- 提交：`[2a39947](https://github.com/bytedance/deer-flow/commit/2a399478307bdd827632bdeddf5baf11c1412d22)`
- 日期：2026-02-09
- 做了什么：新增或增强功能，主题是“citations prompts, path_utils, and citation code cleanup”。
- 影响范围：主要涉及 后端、前端。
- 改动规模：+103 / -174 行。
- 关键文件：backend/src/agents/lead_agent/prompt.py；backend/src/gateway/path_utils.py；backend/src/gateway/routers/artifacts.py；backend/src/gateway/routers/skills.py；backend/src/subagents/builtins/general_purpose.py；frontend/src/core/citations/utils.ts。

#### 35. feat: citations prompts, path_utils, and citation code cleanup

- 提交：`[eb5782b](https://github.com/bytedance/deer-flow/commit/eb5782b93bc36a600c6b2e1713310f829c9b981d)`
- 日期：2026-02-09
- 做了什么：新增或增强功能，主题是“citations prompts, path_utils, and citation code cleanup”。
- 影响范围：主要涉及 后端、前端。
- 改动规模：+103 / -174 行。
- 关键文件：backend/src/agents/lead_agent/prompt.py；backend/src/gateway/path_utils.py；backend/src/gateway/routers/artifacts.py；backend/src/gateway/routers/skills.py；backend/src/subagents/builtins/general_purpose.py；frontend/src/core/citations/utils.ts。

#### 36. feat(frontend): add mode hover guide and adjust mode i18n

- 提交：`[d265bdb](https://github.com/bytedance/deer-flow/commit/d265bdb24519e313ee97d615b58fdb6fa7dc4e22)`
- 日期：2026-02-09
- 做了什么：新增或增强功能，主题是“add mode hover guide and adjust mode i18n”。
- 影响范围：主要涉及 前端。
- 改动规模：+101 / -29 行。
- 关键文件：frontend/src/components/workspace/input-box.tsx；frontend/src/components/workspace/mode-hover-guide.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/zh-CN.ts。

#### 37. feat(frontend): add mode hover guide and adjust mode i18n

- 提交：`[5e000f1](https://github.com/bytedance/deer-flow/commit/5e000f1a99128e9cf289ebd0e31bda1716252879)`
- 日期：2026-02-09
- 做了什么：新增或增强功能，主题是“add mode hover guide and adjust mode i18n”。
- 影响范围：主要涉及 前端。
- 改动规模：+101 / -29 行。
- 关键文件：frontend/src/components/workspace/input-box.tsx；frontend/src/components/workspace/mode-hover-guide.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/zh-CN.ts。

#### 38. feat: update workspace header to conditionally render title based on environment variable

- 提交：`[8b053a4](https://github.com/bytedance/deer-flow/commit/8b053a4415e8a9ac007e4769f62eb5d9da499175)`
- 日期：2026-02-09
- 做了什么：新增或增强功能，主题是“update workspace header to conditionally render title based on environment variable”。
- 影响范围：主要涉及 前端。
- 改动规模：+10 / -3 行。
- 关键文件：frontend/src/components/workspace/workspace-header.tsx。

#### 39. feat: update workspace header to conditionally render title based on environment variable

- 提交：`[fd4f6c6](https://github.com/bytedance/deer-flow/commit/fd4f6c679aeb384daf2f008d036ebf7579786b92)`
- 日期：2026-02-09
- 做了什么：新增或增强功能，主题是“update workspace header to conditionally render title based on environment variable”。
- 影响范围：主要涉及 前端。
- 改动规模：+10 / -3 行。
- 关键文件：frontend/src/components/workspace/workspace-header.tsx。

#### 40. feat: update workspace header to conditionally render title based on environment variable

- 提交：`[3ad2cd9](https://github.com/bytedance/deer-flow/commit/3ad2cd936fd0b47b310f9eddfe98ec5b1056b220)`
- 日期：2026-02-09
- 做了什么：新增或增强功能，主题是“update workspace header to conditionally render title based on environment variable”。
- 影响范围：主要涉及 前端。
- 改动规模：+10 / -3 行。
- 关键文件：frontend/src/components/workspace/workspace-header.tsx。

#### 41. feat: make it golden

- 提交：`[305e896](https://github.com/bytedance/deer-flow/commit/305e8969ef63cda3085221dc36ecae6cc72b571c)`
- 日期：2026-02-09
- 做了什么：新增或增强功能，主题是“make it golden”。
- 影响范围：主要涉及 前端。
- 改动规模：+3 / -1 行。
- 关键文件：frontend/src/components/ui/word-rotate.tsx。

#### 42. feat: make it golden

- 提交：`[189fcab](https://github.com/bytedance/deer-flow/commit/189fcab4c59b30c0b53a8f398bf2b324634e01ad)`
- 日期：2026-02-09
- 做了什么：新增或增强功能，主题是“make it golden”。
- 影响范围：主要涉及 前端。
- 改动规模：+3 / -1 行。
- 关键文件：frontend/src/components/ui/word-rotate.tsx。

#### 43. feat: make it golden

- 提交：`[e626146](https://github.com/bytedance/deer-flow/commit/e6261469efec11db8fd62159074d79a91f132e68)`
- 日期：2026-02-09
- 做了什么：新增或增强功能，主题是“make it golden”。
- 影响范围：主要涉及 前端。
- 改动规模：+3 / -1 行。
- 关键文件：frontend/src/components/ui/word-rotate.tsx。

#### 44. feat: make the title golden in Ultra mode

- 提交：`[ddbda4e](https://github.com/bytedance/deer-flow/commit/ddbda4e38f9d90c5e07ac24420ecec92c6debc40)`
- 日期：2026-02-09
- 做了什么：新增或增强功能，主题是“make the title golden in Ultra mode”。
- 影响范围：主要涉及 前端。
- 改动规模：+13 / -6 行。
- 关键文件：frontend/src/components/workspace/welcome.tsx；frontend/src/core/i18n/locales/zh-CN.ts。

#### 45. feat: make the title golden in Ultra mode

- 提交：`[db79ab2](https://github.com/bytedance/deer-flow/commit/db79ab27f4ba15a79aa89c8a6d833f5fb90ab623)`
- 日期：2026-02-09
- 做了什么：新增或增强功能，主题是“make the title golden in Ultra mode”。
- 影响范围：主要涉及 前端。
- 改动规模：+13 / -6 行。
- 关键文件：frontend/src/components/workspace/welcome.tsx；frontend/src/core/i18n/locales/zh-CN.ts。

#### 46. feat: make the title golden in Ultra mode

- 提交：`[76cdb0e](https://github.com/bytedance/deer-flow/commit/76cdb0e16eb5f0e242894b8e623218f3684bf2bd)`
- 日期：2026-02-09
- 做了什么：新增或增强功能，主题是“make the title golden in Ultra mode”。
- 影响范围：主要涉及 前端。
- 改动规模：+13 / -6 行。
- 关键文件：frontend/src/components/workspace/welcome.tsx；frontend/src/core/i18n/locales/zh-CN.ts。

#### 47. feat: add mode in welcome

- 提交：`[cebf259](https://github.com/bytedance/deer-flow/commit/cebf2599c9bd518c31c5762f84cc8b77f5fb7ec4)`
- 日期：2026-02-09
- 做了什么：新增或增强功能，主题是“add mode in welcome”。
- 影响范围：主要涉及 前端。
- 改动规模：+13 / -3 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/workspace/welcome.tsx。

#### 48. feat: add mode in welcome

- 提交：`[143f9f1](https://github.com/bytedance/deer-flow/commit/143f9f1f4dcd60d23755422140a7cd85dc96daea)`
- 日期：2026-02-09
- 做了什么：新增或增强功能，主题是“add mode in welcome”。
- 影响范围：主要涉及 前端。
- 改动规模：+13 / -3 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/workspace/welcome.tsx。

#### 49. feat: add mode in welcome

- 提交：`[d197ee8](https://github.com/bytedance/deer-flow/commit/d197ee8f288cf33e854aa90a4c201b49d6c23b63)`
- 日期：2026-02-09
- 做了什么：新增或增强功能，主题是“add mode in welcome”。
- 影响范围：主要涉及 前端。
- 改动规模：+13 / -3 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/workspace/welcome.tsx。

#### 50. feat: set golden color for ultra

- 提交：`[25b60e7](https://github.com/bytedance/deer-flow/commit/25b60e732f2a3c6a38f6fdcf91cc86f9f44e8c0b)`
- 日期：2026-02-09
- 做了什么：新增或增强功能，主题是“set golden color for ultra”。
- 影响范围：主要涉及 前端。
- 改动规模：+27 / -7 行。
- 关键文件：frontend/src/components/workspace/input-box.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/styles/globals.css。

#### 51. feat: set golden color for ultra

- 提交：`[9da3a1d](https://github.com/bytedance/deer-flow/commit/9da3a1dcb255b7dce2e99428d24960cbc32f80ce)`
- 日期：2026-02-09
- 做了什么：新增或增强功能，主题是“set golden color for ultra”。
- 影响范围：主要涉及 前端。
- 改动规模：+27 / -7 行。
- 关键文件：frontend/src/components/workspace/input-box.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/styles/globals.css。

#### 52. feat: set golden color for ultra

- 提交：`[d9b6077](https://github.com/bytedance/deer-flow/commit/d9b60778a95005f95ca255b6be72d97053c611ae)`
- 日期：2026-02-09
- 做了什么：新增或增强功能，主题是“set golden color for ultra”。
- 影响范围：主要涉及 前端。
- 改动规模：+27 / -7 行。
- 关键文件：frontend/src/components/workspace/input-box.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/styles/globals.css。

#### 53. feat: rewording

- 提交：`[f146e35](https://github.com/bytedance/deer-flow/commit/f146e35ee77b00cc33190624bafdb888b1b12f3d)`
- 日期：2026-02-08
- 做了什么：新增或增强功能，主题是“rewording”。
- 影响范围：主要涉及 前端。
- 改动规模：+12 / -13 行。
- 关键文件：frontend/src/components/workspace/messages/message-list.tsx；frontend/src/components/workspace/messages/subtask-card.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/zh-CN.ts。

#### 54. feat: rewording

- 提交：`[a4e1e1a](https://github.com/bytedance/deer-flow/commit/a4e1e1a95e6746e4671256dbed4db83a4aa11802)`
- 日期：2026-02-08
- 做了什么：新增或增强功能，主题是“rewording”。
- 影响范围：主要涉及 前端。
- 改动规模：+12 / -13 行。
- 关键文件：frontend/src/components/workspace/messages/message-list.tsx；frontend/src/components/workspace/messages/subtask-card.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/zh-CN.ts。

#### 55. feat: rewording

- 提交：`[eb9af00](https://github.com/bytedance/deer-flow/commit/eb9af00d1d9c0c9004a3b8450e023093d8770c7d)`
- 日期：2026-02-08
- 做了什么：新增或增强功能，主题是“rewording”。
- 影响范围：主要涉及 前端。
- 改动规模：+12 / -13 行。
- 关键文件：frontend/src/components/workspace/messages/message-list.tsx；frontend/src/components/workspace/messages/subtask-card.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/zh-CN.ts。

#### 56. feat: disallow present_files tool in subagents and add market-analysis skill

- 提交：`[6eb4cdd](https://github.com/bytedance/deer-flow/commit/6eb4cdd3ecf63f738e47f1b3edec5bb8d8df28b5)`
- 日期：2026-02-08
- 做了什么：新增或增强功能，主题是“disallow present_files tool in subagents and add market-analysis skill”。
- 影响范围：主要涉及 后端、技能体系。
- 改动规模：+210 / -2 行。
- 关键文件：backend/src/subagents/builtins/bash_agent.py；backend/src/subagents/builtins/general_purpose.py；skills/public/market-analysis/SKILL.md。

#### 57. feat: disallow present_files tool in subagents and add market-analysis skill

- 提交：`[f9b769b](https://github.com/bytedance/deer-flow/commit/f9b769b5c3d50b0f6fc2f56e316c04564de4f295)`
- 日期：2026-02-08
- 做了什么：新增或增强功能，主题是“disallow present_files tool in subagents and add market-analysis skill”。
- 影响范围：主要涉及 后端、技能体系。
- 改动规模：+210 / -2 行。
- 关键文件：backend/src/subagents/builtins/bash_agent.py；backend/src/subagents/builtins/general_purpose.py；skills/public/market-analysis/SKILL.md。

#### 58. feat: disallow present_files tool in subagents and add market-analysis skill

- 提交：`[54f2f1b](https://github.com/bytedance/deer-flow/commit/54f2f1bd3aed3ae98468e8d665481faad321ad95)`
- 日期：2026-02-08
- 做了什么：新增或增强功能，主题是“disallow present_files tool in subagents and add market-analysis skill”。
- 影响范围：主要涉及 后端、技能体系。
- 改动规模：+210 / -2 行。
- 关键文件：backend/src/subagents/builtins/bash_agent.py；backend/src/subagents/builtins/general_purpose.py；skills/public/market-analysis/SKILL.md。

#### 59. feat: add special effect for Ultra mode

- 提交：`[8a23515](https://github.com/bytedance/deer-flow/commit/8a2351593cd9609f0ef5177ffe18c62c1b838183)`
- 日期：2026-02-08
- 做了什么：新增或增强功能，主题是“add special effect for Ultra mode”。
- 影响范围：主要涉及 前端。
- 改动规模：+115 / -90 行。
- 关键文件：frontend/src/components/workspace/messages/subtask-card.tsx；frontend/src/styles/globals.css。

#### 60. feat: add special effect for Ultra mode

- 提交：`[d36fbcd](https://github.com/bytedance/deer-flow/commit/d36fbcdfc1d2710fd0e41ca0b9af210a34a77bd7)`
- 日期：2026-02-08
- 做了什么：新增或增强功能，主题是“add special effect for Ultra mode”。
- 影响范围：主要涉及 前端。
- 改动规模：+115 / -90 行。
- 关键文件：frontend/src/components/workspace/messages/subtask-card.tsx；frontend/src/styles/globals.css。

#### 61. feat: add special effect for Ultra mode

- 提交：`[0d55230](https://github.com/bytedance/deer-flow/commit/0d55230016476d536e03ed25a162224160b5f64f)`
- 日期：2026-02-08
- 做了什么：新增或增强功能，主题是“add special effect for Ultra mode”。
- 影响范围：主要涉及 前端。
- 改动规模：+115 / -90 行。
- 关键文件：frontend/src/components/workspace/messages/subtask-card.tsx；frontend/src/styles/globals.css。

#### 62. feat: add realtime subagent status report

- 提交：`[010aba1](https://github.com/bytedance/deer-flow/commit/010aba1e282c032a1b9f0257d7c79620021248b1)`
- 日期：2026-02-08
- 做了什么：新增或增强功能，主题是“add realtime subagent status report”。
- 影响范围：主要涉及 前端。
- 改动规模：+91 / -10 行。
- 关键文件：frontend/src/components/workspace/messages/subtask-card.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts；frontend/src/core/i18n/locales/zh-CN.ts；frontend/src/core/tasks/context.tsx；frontend/src/core/tasks/types.ts；frontend/src/core/threads/hooks.ts；frontend/src/core/tools/utils.ts。

#### 63. feat: add realtime subagent status report

- 提交：`[7ed1be3](https://github.com/bytedance/deer-flow/commit/7ed1be32fd86399ee198a817d24ff1515acd9ab8)`
- 日期：2026-02-08
- 做了什么：新增或增强功能，主题是“add realtime subagent status report”。
- 影响范围：主要涉及 前端。
- 改动规模：+91 / -10 行。
- 关键文件：frontend/src/components/workspace/messages/subtask-card.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts；frontend/src/core/i18n/locales/zh-CN.ts；frontend/src/core/tasks/context.tsx；frontend/src/core/tasks/types.ts；frontend/src/core/threads/hooks.ts；frontend/src/core/tools/utils.ts。

#### 64. feat: add realtime subagent status report

- 提交：`[7d4b5eb](https://github.com/bytedance/deer-flow/commit/7d4b5eb3cae5da2f3baadeb5f97d63adc741a8d4)`
- 日期：2026-02-08
- 做了什么：新增或增强功能，主题是“add realtime subagent status report”。
- 影响范围：主要涉及 前端。
- 改动规模：+91 / -10 行。
- 关键文件：frontend/src/components/workspace/messages/subtask-card.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts；frontend/src/core/i18n/locales/zh-CN.ts；frontend/src/core/tasks/context.tsx；frontend/src/core/tasks/types.ts；frontend/src/core/threads/hooks.ts；frontend/src/core/tools/utils.ts。

#### 65. feat: limit concurrent subagents to 3 per turn

- 提交：`[808e028](https://github.com/bytedance/deer-flow/commit/808e02833858a3494cc075d1a261806853fc5f85)`
- 日期：2026-02-08
- 做了什么：新增或增强功能，主题是“limit concurrent subagents to 3 per turn”。
- 影响范围：主要涉及 后端。
- 改动规模：+51 / -35 行。
- 关键文件：backend/src/agents/lead_agent/prompt.py；backend/src/subagents/executor.py；backend/src/tools/builtins/task_tool.py。

#### 66. feat: limit concurrent subagents to 3 per turn

- 提交：`[9e2b3f1](https://github.com/bytedance/deer-flow/commit/9e2b3f1f3973a6b64d3dcb5ce29d4250a1ae1f33)`
- 日期：2026-02-08
- 做了什么：新增或增强功能，主题是“limit concurrent subagents to 3 per turn”。
- 影响范围：主要涉及 后端。
- 改动规模：+51 / -35 行。
- 关键文件：backend/src/agents/lead_agent/prompt.py；backend/src/subagents/executor.py；backend/src/tools/builtins/task_tool.py。

#### 67. feat: limit concurrent subagents to 3 per turn

- 提交：`[faa327b](https://github.com/bytedance/deer-flow/commit/faa327b3cd04cc75f309e0c6987f9919133a2539)`
- 日期：2026-02-08
- 做了什么：新增或增强功能，主题是“limit concurrent subagents to 3 per turn”。
- 影响范围：主要涉及 后端。
- 改动规模：+51 / -35 行。
- 关键文件：backend/src/agents/lead_agent/prompt.py；backend/src/subagents/executor.py；backend/src/tools/builtins/task_tool.py。

#### 68. feat: add real-time streaming of subagent AI messages

- 提交：`[96bace7](https://github.com/bytedance/deer-flow/commit/96bace7ab6d68d148ebb58b85918edcd57790ee9)`
- 日期：2026-02-08
- 做了什么：新增或增强功能，主题是“add real-time streaming of subagent AI messages”。
- 影响范围：主要涉及 后端。
- 改动规模：+107 / -51 行。
- 关键文件：backend/src/subagents/executor.py；backend/src/tools/builtins/task_tool.py。

#### 69. feat: add real-time streaming of subagent AI messages

- 提交：`[0a27a75](https://github.com/bytedance/deer-flow/commit/0a27a7561af88783563b37945c1ce98f49fb4094)`
- 日期：2026-02-08
- 做了什么：新增或增强功能，主题是“add real-time streaming of subagent AI messages”。
- 影响范围：主要涉及 后端。
- 改动规模：+107 / -51 行。
- 关键文件：backend/src/subagents/executor.py；backend/src/tools/builtins/task_tool.py。

#### 70. feat: add real-time streaming of subagent AI messages

- 提交：`[5477294](https://github.com/bytedance/deer-flow/commit/54772947cbee69521fac263a26f705f6a8d906d6)`
- 日期：2026-02-08
- 做了什么：新增或增强功能，主题是“add real-time streaming of subagent AI messages”。
- 影响范围：主要涉及 后端。
- 改动规模：+107 / -51 行。
- 关键文件：backend/src/subagents/executor.py；backend/src/tools/builtins/task_tool.py。

#### 71. feat: rewording and add initial animation

- 提交：`[0355493](https://github.com/bytedance/deer-flow/commit/0355493a1604ad7df1b564ec3091986f351a8a1a)`
- 日期：2026-02-08
- 做了什么：新增或增强功能，主题是“rewording and add initial animation”。
- 影响范围：主要涉及 前端。
- 改动规模：+45 / -12 行。
- 关键文件：frontend/src/components/landing/hero.tsx；frontend/src/components/landing/sections/whats-new-section.tsx；frontend/src/components/workspace/welcome.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts；frontend/src/core/i18n/locales/zh-CN.ts；frontend/src/styles/globals.css。

#### 72. feat: rewording and add initial animation

- 提交：`[2b3dc96](https://github.com/bytedance/deer-flow/commit/2b3dc96e400607877b9bd878d5b3f83887de432d)`
- 日期：2026-02-08
- 做了什么：新增或增强功能，主题是“rewording and add initial animation”。
- 影响范围：主要涉及 前端。
- 改动规模：+45 / -12 行。
- 关键文件：frontend/src/components/landing/hero.tsx；frontend/src/components/landing/sections/whats-new-section.tsx；frontend/src/components/workspace/welcome.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts；frontend/src/core/i18n/locales/zh-CN.ts；frontend/src/styles/globals.css。

#### 73. feat: rewording and add initial animation

- 提交：`[ff7437f](https://github.com/bytedance/deer-flow/commit/ff7437f83015cf75d36c982fae2d2c95827731d6)`
- 日期：2026-02-08
- 做了什么：新增或增强功能，主题是“rewording and add initial animation”。
- 影响范围：主要涉及 前端。
- 改动规模：+45 / -12 行。
- 关键文件：frontend/src/components/landing/hero.tsx；frontend/src/components/landing/sections/whats-new-section.tsx；frontend/src/components/workspace/welcome.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts；frontend/src/core/i18n/locales/zh-CN.ts；frontend/src/styles/globals.css。

#### 74. feat: add ambilight

- 提交：`[de8ff9d](https://github.com/bytedance/deer-flow/commit/de8ff9d33675e4c90f38762611bde97a9687ad4e)`
- 日期：2026-02-07
- 做了什么：新增或增强功能，主题是“add ambilight”。
- 影响范围：主要涉及 前端。
- 改动规模：+44 / -0 行。
- 关键文件：frontend/src/styles/globals.css。

#### 75. feat: add ambilight

- 提交：`[01aa035](https://github.com/bytedance/deer-flow/commit/01aa0359056564f41470832740a91aae539ecebe)`
- 日期：2026-02-07
- 做了什么：新增或增强功能，主题是“add ambilight”。
- 影响范围：主要涉及 前端。
- 改动规模：+44 / -0 行。
- 关键文件：frontend/src/styles/globals.css。

#### 76. feat: add ambilight

- 提交：`[a4e89cc](https://github.com/bytedance/deer-flow/commit/a4e89cc96bf45d3f09aad45d7d3075f140fa1bc1)`
- 日期：2026-02-07
- 做了什么：新增或增强功能，主题是“add ambilight”。
- 影响范围：主要涉及 前端。
- 改动规模：+44 / -0 行。
- 关键文件：frontend/src/styles/globals.css。

#### 77. feat: add handling for task timeout and enhance Streamdown plugin for word animation

- 提交：`[d9a52f0](https://github.com/bytedance/deer-flow/commit/d9a52f07e7fd3a86bcc17b8bd8feafc9c23dafa7)`
- 日期：2026-02-07
- 做了什么：新增或增强功能，主题是“add handling for task timeout and enhance Streamdown plugin for word animation”。
- 影响范围：主要涉及 前端。
- 改动规模：+26 / -2 行。
- 关键文件：frontend/src/components/workspace/messages/message-list.tsx；frontend/src/components/workspace/messages/subtask-card.tsx；frontend/src/core/streamdown/plugins.ts。

#### 78. feat: add handling for task timeout and enhance Streamdown plugin for word animation

- 提交：`[99e8f22](https://github.com/bytedance/deer-flow/commit/99e8f22d1de1b97e679c7256e4e7cd13849b0f38)`
- 日期：2026-02-07
- 做了什么：新增或增强功能，主题是“add handling for task timeout and enhance Streamdown plugin for word animation”。
- 影响范围：主要涉及 前端。
- 改动规模：+26 / -2 行。
- 关键文件：frontend/src/components/workspace/messages/message-list.tsx；frontend/src/components/workspace/messages/subtask-card.tsx；frontend/src/core/streamdown/plugins.ts。

#### 79. feat: add handling for task timeout and enhance Streamdown plugin for word animation

- 提交：`[0810917](https://github.com/bytedance/deer-flow/commit/0810917b69834b96e7ba3f22d2da1ee18164c0d4)`
- 日期：2026-02-07
- 做了什么：新增或增强功能，主题是“add handling for task timeout and enhance Streamdown plugin for word animation”。
- 影响范围：主要涉及 前端。
- 改动规模：+26 / -2 行。
- 关键文件：frontend/src/components/workspace/messages/message-list.tsx；frontend/src/components/workspace/messages/subtask-card.tsx；frontend/src/core/streamdown/plugins.ts。

#### 80. feat: adjust position

- 提交：`[260953f](https://github.com/bytedance/deer-flow/commit/260953fb8120e606e8e9a00e377a1750af783730)`
- 日期：2026-02-07
- 做了什么：新增或增强功能，主题是“adjust position”。
- 影响范围：主要涉及 前端。
- 改动规模：+2 / -2 行。
- 关键文件：frontend/src/components/workspace/input-box.tsx。

#### 81. feat: adjust position

- 提交：`[dce82c1](https://github.com/bytedance/deer-flow/commit/dce82c1db434a4ffbcd069cc885bd32a1dd58deb)`
- 日期：2026-02-07
- 做了什么：新增或增强功能，主题是“adjust position”。
- 影响范围：主要涉及 前端。
- 改动规模：+2 / -2 行。
- 关键文件：frontend/src/components/workspace/input-box.tsx。

#### 82. feat: adjust position

- 提交：`[4dc3cda](https://github.com/bytedance/deer-flow/commit/4dc3cdac48e099db05c3386497df6c1785b45074)`
- 日期：2026-02-07
- 做了什么：新增或增强功能，主题是“adjust position”。
- 影响范围：主要涉及 前端。
- 改动规模：+2 / -2 行。
- 关键文件：frontend/src/components/workspace/input-box.tsx。

#### 83. refactor: optimize task tool parameter order and improve task tracking

- 提交：`[f41d9b3](https://github.com/bytedance/deer-flow/commit/f41d9b3be586174eb9b4efc06cd3f5f2635d4ffa)`
- 日期：2026-02-07
- 做了什么：新增或增强功能，主题是“optimize task tool parameter order and improve task tracking”。
- 影响范围：主要涉及 后端。
- 改动规模：+30 / -24 行。
- 关键文件：backend/src/agents/lead_agent/prompt.py；backend/src/subagents/executor.py；backend/src/tools/builtins/task_tool.py。

#### 84. refactor: optimize task tool parameter order and improve task tracking

- 提交：`[1425294](https://github.com/bytedance/deer-flow/commit/1425294f9b81eae47fb72cd927a44a9e8289b770)`
- 日期：2026-02-07
- 做了什么：新增或增强功能，主题是“optimize task tool parameter order and improve task tracking”。
- 影响范围：主要涉及 后端。
- 改动规模：+30 / -24 行。
- 关键文件：backend/src/agents/lead_agent/prompt.py；backend/src/subagents/executor.py；backend/src/tools/builtins/task_tool.py。

#### 85. refactor: optimize task tool parameter order and improve task tracking

- 提交：`[a6db74b](https://github.com/bytedance/deer-flow/commit/a6db74baba0c4cff77d312831eac5621260c7ae8)`
- 日期：2026-02-07
- 做了什么：新增或增强功能，主题是“optimize task tool parameter order and improve task tracking”。
- 影响范围：主要涉及 后端。
- 改动规模：+30 / -24 行。
- 关键文件：backend/src/agents/lead_agent/prompt.py；backend/src/subagents/executor.py；backend/src/tools/builtins/task_tool.py。

#### 86. feat: support subtasks

- 提交：`[3e2883e](https://github.com/bytedance/deer-flow/commit/3e2883e2a36fd0b81577df0dab18dcd6a7d966fd)`
- 日期：2026-02-07
- 做了什么：新增或增强功能，主题是“support subtasks”。
- 影响范围：主要涉及 前端。
- 改动规模：+433 / -109 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/layout.tsx；frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/ui/shine-border.tsx；frontend/src/components/workspace/artifacts/artifact-file-list.tsx；frontend/src/components/workspace/input-box.tsx；frontend/src/components/workspace/messages/message-group.tsx；frontend/src/components/workspace/messages/message-list.tsx；frontend/src/components/workspace/messages/subtask-card.tsx。

#### 87. feat: support subtasks

- 提交：`[a016332](https://github.com/bytedance/deer-flow/commit/a016332a37d72f273bffcef9791e16b557630f09)`
- 日期：2026-02-07
- 做了什么：新增或增强功能，主题是“support subtasks”。
- 影响范围：主要涉及 前端。
- 改动规模：+433 / -109 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/layout.tsx；frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/ui/shine-border.tsx；frontend/src/components/workspace/artifacts/artifact-file-list.tsx；frontend/src/components/workspace/input-box.tsx；frontend/src/components/workspace/messages/message-group.tsx；frontend/src/components/workspace/messages/message-list.tsx；frontend/src/components/workspace/messages/subtask-card.tsx。

#### 88. feat: support subtasks

- 提交：`[46798c0](https://github.com/bytedance/deer-flow/commit/46798c093195b0c37415de6cc5df955117a13add)`
- 日期：2026-02-07
- 做了什么：新增或增强功能，主题是“support subtasks”。
- 影响范围：主要涉及 前端。
- 改动规模：+433 / -109 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/layout.tsx；frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/ui/shine-border.tsx；frontend/src/components/workspace/artifacts/artifact-file-list.tsx；frontend/src/components/workspace/input-box.tsx；frontend/src/components/workspace/messages/message-group.tsx；frontend/src/components/workspace/messages/message-list.tsx；frontend/src/components/workspace/messages/subtask-card.tsx。

#### 89. Merge pull request #25 from LofiSu/feat/citations

- 提交：`[e4eb4a6](https://github.com/bytedance/deer-flow/commit/e4eb4a65cf1595bd71cc3b6ed3b9d3f69b1c7229)`
- 日期：2026-02-07
- 做了什么：新增或增强功能，主题是“Merge pull request #25 from LofiSu/feat/citations”。
- 影响范围：主要涉及 前端、后端。
- 改动规模：+580 / -501 行。
- 关键文件：backend/src/agents/lead_agent/prompt.py；backend/src/gateway/routers/artifacts.py；frontend/src/components/ai-elements/inline-citation.tsx；frontend/src/components/workspace/artifacts/artifact-file-detail.tsx；frontend/src/components/workspace/messages/message-group.tsx；frontend/src/components/workspace/messages/message-list-item.tsx；frontend/src/components/workspace/settings/memory-settings-page.tsx；frontend/src/core/citations/index.ts。

#### 90. Merge pull request #25 from LofiSu/feat/citations

- 提交：`[afb7a36](https://github.com/bytedance/deer-flow/commit/afb7a367391abaacd4735ba52613be7c21d82030)`
- 日期：2026-02-07
- 做了什么：新增或增强功能，主题是“Merge pull request #25 from LofiSu/feat/citations”。
- 影响范围：主要涉及 前端、后端。
- 改动规模：+580 / -501 行。
- 关键文件：backend/src/agents/lead_agent/prompt.py；backend/src/gateway/routers/artifacts.py；frontend/src/components/ai-elements/inline-citation.tsx；frontend/src/components/workspace/artifacts/artifact-file-detail.tsx；frontend/src/components/workspace/messages/message-group.tsx；frontend/src/components/workspace/messages/message-list-item.tsx；frontend/src/components/workspace/settings/memory-settings-page.tsx；frontend/src/core/citations/index.ts。

#### 91. Merge pull request #25 from LofiSu/feat/citations

- 提交：`[9f8d9e4](https://github.com/bytedance/deer-flow/commit/9f8d9e4da217975e77c56a4041cfb96f9f1b9d23)`
- 日期：2026-02-07
- 做了什么：新增或增强功能，主题是“Merge pull request #25 from LofiSu/feat/citations”。
- 影响范围：主要涉及 前端、后端。
- 改动规模：+580 / -501 行。
- 关键文件：backend/src/agents/lead_agent/prompt.py；backend/src/gateway/routers/artifacts.py；frontend/src/components/ai-elements/inline-citation.tsx；frontend/src/components/workspace/artifacts/artifact-file-detail.tsx；frontend/src/components/workspace/messages/message-group.tsx；frontend/src/components/workspace/messages/message-list-item.tsx；frontend/src/components/workspace/settings/memory-settings-page.tsx；frontend/src/core/citations/index.ts。

#### 92. feat: enhance workspace navigation menu with conditional rendering and mounted state

- 提交：`[91a05ac](https://github.com/bytedance/deer-flow/commit/91a05acdf8463ccc5e6a58829e10da5943a57619)`
- 日期：2026-02-07
- 做了什么：新增或增强功能，主题是“enhance workspace navigation menu with conditional rendering and mounted state”。
- 影响范围：主要涉及 前端。
- 改动规模：+101 / -79 行。
- 关键文件：frontend/src/components/workspace/workspace-nav-menu.tsx。

#### 93. feat: enhance workspace navigation menu with conditional rendering and mounted state

- 提交：`[4ac637a](https://github.com/bytedance/deer-flow/commit/4ac637a0eb8db54be78bb17abf5c1ebfe6bbc9c3)`
- 日期：2026-02-07
- 做了什么：新增或增强功能，主题是“enhance workspace navigation menu with conditional rendering and mounted state”。
- 影响范围：主要涉及 前端。
- 改动规模：+101 / -79 行。
- 关键文件：frontend/src/components/workspace/workspace-nav-menu.tsx。

#### 94. feat: enhance workspace navigation menu with conditional rendering and mounted state

- 提交：`[e7cd528](https://github.com/bytedance/deer-flow/commit/e7cd5287f1ee0aa42a5a2fb034e74cd028ea85cd)`
- 日期：2026-02-07
- 做了什么：新增或增强功能，主题是“enhance workspace navigation menu with conditional rendering and mounted state”。
- 影响范围：主要涉及 前端。
- 改动规模：+101 / -79 行。
- 关键文件：frontend/src/components/workspace/workspace-nav-menu.tsx。

#### 95. docs: update description for surprise-me skill to enhance clarity

- 提交：`[60be7ee](https://github.com/bytedance/deer-flow/commit/60be7ee20de3552aa04bdb5ebbbde092cfabf75f)`
- 日期：2026-02-07
- 做了什么：补充文档能力，主题是“update description for surprise-me skill to enhance clarity”。
- 影响范围：主要涉及 技能体系。
- 改动规模：+1 / -1 行。
- 关键文件：skills/public/surprise-me/SKILL.md。

#### 96. docs: update description for surprise-me skill to enhance clarity

- 提交：`[86ad92a](https://github.com/bytedance/deer-flow/commit/86ad92a1a6ec3f3d1b9ccb6b6b3e964c56286974)`
- 日期：2026-02-07
- 做了什么：补充文档能力，主题是“update description for surprise-me skill to enhance clarity”。
- 影响范围：主要涉及 技能体系。
- 改动规模：+1 / -1 行。
- 关键文件：skills/public/surprise-me/SKILL.md。

#### 97. docs: update description for surprise-me skill to enhance clarity

- 提交：`[85767c8](https://github.com/bytedance/deer-flow/commit/85767c8470178c08efc3a27d97c6ba7a507cf361)`
- 日期：2026-02-07
- 做了什么：补充文档能力，主题是“update description for surprise-me skill to enhance clarity”。
- 影响范围：主要涉及 技能体系。
- 改动规模：+1 / -1 行。
- 关键文件：skills/public/surprise-me/SKILL.md。

#### 98. feat: add animations

- 提交：`[a122f76](https://github.com/bytedance/deer-flow/commit/a122f76e3661f70c84c44747597342fbb7cb60fb)`
- 日期：2026-02-07
- 做了什么：新增或增强功能，主题是“add animations”。
- 影响范围：主要涉及 前端。
- 改动规模：+67 / -43 行。
- 关键文件：frontend/src/components/ai-elements/suggestion.tsx；frontend/src/styles/globals.css。

#### 99. feat: add animations

- 提交：`[a2af464](https://github.com/bytedance/deer-flow/commit/a2af464a6fdbdc798d0f9b81f1e73078d1b5caaa)`
- 日期：2026-02-07
- 做了什么：新增或增强功能，主题是“add animations”。
- 影响范围：主要涉及 前端。
- 改动规模：+67 / -43 行。
- 关键文件：frontend/src/components/ai-elements/suggestion.tsx；frontend/src/styles/globals.css。

#### 100. feat: add animations

- 提交：`[fc543a9](https://github.com/bytedance/deer-flow/commit/fc543a9b30acce8a305ca6bff693025e2eaae212)`
- 日期：2026-02-07
- 做了什么：新增或增强功能，主题是“add animations”。
- 影响范围：主要涉及 前端。
- 改动规模：+67 / -43 行。
- 关键文件：frontend/src/components/ai-elements/suggestion.tsx；frontend/src/styles/globals.css。

#### 101. Merge upstream/experimental into feat/citations

- 提交：`[f0075e0](https://github.com/bytedance/deer-flow/commit/f0075e0d64860040394a6f4fe3f8f90ed8a2077c)`
- 日期：2026-02-07
- 做了什么：新增或增强功能，主题是“Merge upstream/experimental into feat/citations”。
- 影响范围：主要涉及 前端、后端、技能体系。
- 改动规模：+3491 / -5322 行。
- 关键文件：Makefile；README.md；backend/CLAUDE.md；backend/debug.py；backend/docs/APPLE_CONTAINER.md；backend/docs/MEMORY_IMPROVEMENTS.md；backend/docs/MEMORY_IMPROVEMENTS_SUMMARY.md；backend/docs/SETUP.md。

#### 102. Merge upstream/experimental into feat/citations

- 提交：`[2331c67](https://github.com/bytedance/deer-flow/commit/2331c674468c626beb7553e8a5140441162bb54e)`
- 日期：2026-02-07
- 做了什么：新增或增强功能，主题是“Merge upstream/experimental into feat/citations”。
- 影响范围：主要涉及 前端、后端、技能体系。
- 改动规模：+3491 / -5322 行。
- 关键文件：Makefile；README.md；backend/CLAUDE.md；backend/debug.py；backend/docs/APPLE_CONTAINER.md；backend/docs/MEMORY_IMPROVEMENTS.md；backend/docs/MEMORY_IMPROVEMENTS_SUMMARY.md；backend/docs/SETUP.md。

#### 103. Merge upstream/experimental into feat/citations

- 提交：`[ea543ce](https://github.com/bytedance/deer-flow/commit/ea543ce1f437f31b0a870c8b7d8adc1d19b5d0af)`
- 日期：2026-02-07
- 做了什么：新增或增强功能，主题是“Merge upstream/experimental into feat/citations”。
- 影响范围：主要涉及 前端、后端、技能体系。
- 改动规模：+3491 / -5322 行。
- 关键文件：Makefile；README.md；backend/CLAUDE.md；backend/debug.py；backend/docs/APPLE_CONTAINER.md；backend/docs/MEMORY_IMPROVEMENTS.md；backend/docs/MEMORY_IMPROVEMENTS_SUMMARY.md；backend/docs/SETUP.md。

#### 104. feat: send custom event

- 提交：`[9bf3a12](https://github.com/bytedance/deer-flow/commit/9bf3a12c30abaea3e897f82c55116e7cc1d8b4db)`
- 日期：2026-02-06
- 做了什么：新增或增强功能，主题是“send custom event”。
- 影响范围：主要涉及 后端、前端、脚本工具。
- 改动规模：+80 / -127 行。
- 关键文件：backend/src/community/aio_sandbox/aio_sandbox_provider.py；backend/src/sandbox/tools.py；backend/src/subagents/executor.py；backend/src/tools/builtins/task_tool.py；frontend/src/components/workspace/subagent-card.tsx；frontend/src/core/threads/hooks.ts；scripts/cleanup-containers.sh。

#### 105. feat: send custom event

- 提交：`[1728137](https://github.com/bytedance/deer-flow/commit/172813720a02e5168c11da232064f16b578a6126)`
- 日期：2026-02-06
- 做了什么：新增或增强功能，主题是“send custom event”。
- 影响范围：主要涉及 后端、前端、脚本工具。
- 改动规模：+80 / -127 行。
- 关键文件：backend/src/community/aio_sandbox/aio_sandbox_provider.py；backend/src/sandbox/tools.py；backend/src/subagents/executor.py；backend/src/tools/builtins/task_tool.py；frontend/src/components/workspace/subagent-card.tsx；frontend/src/core/threads/hooks.ts；scripts/cleanup-containers.sh。

#### 106. feat: send custom event

- 提交：`[4f15670](https://github.com/bytedance/deer-flow/commit/4f156704557cc20f735d43cfb37d086028984cc6)`
- 日期：2026-02-06
- 做了什么：新增或增强功能，主题是“send custom event”。
- 影响范围：主要涉及 后端、前端、脚本工具。
- 改动规模：+80 / -127 行。
- 关键文件：backend/src/community/aio_sandbox/aio_sandbox_provider.py；backend/src/sandbox/tools.py；backend/src/subagents/executor.py；backend/src/tools/builtins/task_tool.py；frontend/src/components/workspace/subagent-card.tsx；frontend/src/core/threads/hooks.ts；scripts/cleanup-containers.sh。

#### 107. feat: fix task polling issue

- 提交：`[9f367b5](https://github.com/bytedance/deer-flow/commit/9f367b55638f833fe784529d7e705abb92177262)`
- 日期：2026-02-06
- 做了什么：新增或增强功能，主题是“fix task polling issue”。
- 影响范围：主要涉及 后端。
- 改动规模：+267 / -106 行。
- 关键文件：backend/docs/task_tool_improvements.md；backend/src/agents/lead_agent/prompt.py；backend/src/subagents/config.py；backend/src/subagents/executor.py；backend/src/tools/builtins/**init**.py；backend/src/tools/builtins/task_tool.py；backend/src/tools/tools.py。

#### 108. feat: fix task polling issue

- 提交：`[41d8d2f](https://github.com/bytedance/deer-flow/commit/41d8d2fd5c65fc8073c5d74b13727d0fa77587c0)`
- 日期：2026-02-06
- 做了什么：新增或增强功能，主题是“fix task polling issue”。
- 影响范围：主要涉及 后端。
- 改动规模：+267 / -106 行。
- 关键文件：backend/docs/task_tool_improvements.md；backend/src/agents/lead_agent/prompt.py；backend/src/subagents/config.py；backend/src/subagents/executor.py；backend/src/tools/builtins/**init**.py；backend/src/tools/builtins/task_tool.py；backend/src/tools/tools.py。

#### 109. feat: fix task polling issue

- 提交：`[498c8b3](https://github.com/bytedance/deer-flow/commit/498c8b3ec0df6f0c9c75ba4d8a0f0696c0f3397b)`
- 日期：2026-02-06
- 做了什么：新增或增强功能，主题是“fix task polling issue”。
- 影响范围：主要涉及 后端。
- 改动规模：+267 / -106 行。
- 关键文件：backend/docs/task_tool_improvements.md；backend/src/agents/lead_agent/prompt.py；backend/src/subagents/config.py；backend/src/subagents/executor.py；backend/src/tools/builtins/**init**.py；backend/src/tools/builtins/task_tool.py；backend/src/tools/tools.py。

#### 110. feat: add ultra mode

- 提交：`[449ffba](https://github.com/bytedance/deer-flow/commit/449ffbad7539b2341c6ae3e0ae6f95486ea0936f)`
- 日期：2026-02-06
- 做了什么：新增或增强功能，主题是“add ultra mode”。
- 影响范围：主要涉及 前端、后端、配置。
- 改动规模：+272 / -41 行。
- 关键文件：backend/src/agents/lead_agent/agent.py；backend/src/agents/lead_agent/prompt.py；backend/src/config/app_config.py；backend/src/config/subagents_config.py；backend/src/tools/builtins/task_tool.py；backend/src/tools/tools.py；config.example.yaml；frontend/src/app/workspace/chats/[thread_id]/page.tsx。

#### 111. feat: add ultra mode

- 提交：`[926c322](https://github.com/bytedance/deer-flow/commit/926c322c3693ccef3ad8a0a1d7dfece5fffb86df)`
- 日期：2026-02-06
- 做了什么：新增或增强功能，主题是“add ultra mode”。
- 影响范围：主要涉及 前端、后端、配置。
- 改动规模：+272 / -41 行。
- 关键文件：backend/src/agents/lead_agent/agent.py；backend/src/agents/lead_agent/prompt.py；backend/src/config/app_config.py；backend/src/config/subagents_config.py；backend/src/tools/builtins/task_tool.py；backend/src/tools/tools.py；config.example.yaml；frontend/src/app/workspace/chats/[thread_id]/page.tsx。

#### 112. feat: add ultra mode

- 提交：`[96baab1](https://github.com/bytedance/deer-flow/commit/96baab12a2a2174d0ecd9cd07ad4ef29eaf73e7e)`
- 日期：2026-02-06
- 做了什么：新增或增强功能，主题是“add ultra mode”。
- 影响范围：主要涉及 前端、后端、配置。
- 改动规模：+272 / -41 行。
- 关键文件：backend/src/agents/lead_agent/agent.py；backend/src/agents/lead_agent/prompt.py；backend/src/config/app_config.py；backend/src/config/subagents_config.py；backend/src/tools/builtins/task_tool.py；backend/src/tools/tools.py；config.example.yaml；frontend/src/app/workspace/chats/[thread_id]/page.tsx。

#### 113. feat: add 'about' page

- 提交：`[70989a9](https://github.com/bytedance/deer-flow/commit/70989a949e93d341bf2a87052d80003451bfbd8a)`
- 日期：2026-02-06
- 做了什么：新增或增强功能，主题是“add 'about' page”。
- 影响范围：主要涉及 前端。
- 改动规模：+675 / -22 行。
- 关键文件：frontend/next.config.js；frontend/package.json；frontend/pnpm-lock.yaml；frontend/src/components/workspace/settings/about-settings-page.tsx；frontend/src/components/workspace/settings/about.md；frontend/src/components/workspace/settings/acknowledge-page.tsx；frontend/src/components/workspace/settings/memory-settings-page.tsx；frontend/src/components/workspace/settings/settings-dialog.tsx。

#### 114. feat: add 'about' page

- 提交：`[44742c6](https://github.com/bytedance/deer-flow/commit/44742c63531a950ff83d650c1deda9a9c8bf7d9a)`
- 日期：2026-02-06
- 做了什么：新增或增强功能，主题是“add 'about' page”。
- 影响范围：主要涉及 前端。
- 改动规模：+675 / -22 行。
- 关键文件：frontend/next.config.js；frontend/package.json；frontend/pnpm-lock.yaml；frontend/src/components/workspace/settings/about-settings-page.tsx；frontend/src/components/workspace/settings/about.md；frontend/src/components/workspace/settings/acknowledge-page.tsx；frontend/src/components/workspace/settings/memory-settings-page.tsx；frontend/src/components/workspace/settings/settings-dialog.tsx。

#### 115. feat: add 'about' page

- 提交：`[f981167](https://github.com/bytedance/deer-flow/commit/f9811671d8a442ce777367170792cc0d42f3d37a)`
- 日期：2026-02-06
- 做了什么：新增或增强功能，主题是“add 'about' page”。
- 影响范围：主要涉及 前端。
- 改动规模：+675 / -22 行。
- 关键文件：frontend/next.config.js；frontend/package.json；frontend/pnpm-lock.yaml；frontend/src/components/workspace/settings/about-settings-page.tsx；frontend/src/components/workspace/settings/about.md；frontend/src/components/workspace/settings/acknowledge-page.tsx；frontend/src/components/workspace/settings/memory-settings-page.tsx；frontend/src/components/workspace/settings/settings-dialog.tsx。

#### 116. docs: add CLAUDE.md

- 提交：`[23c082f](https://github.com/bytedance/deer-flow/commit/23c082f05dad509aa8d01357f21416245807614d)`
- 日期：2026-02-06
- 做了什么：补充文档能力，主题是“add CLAUDE.md”。
- 影响范围：主要涉及 前端。
- 改动规模：+89 / -0 行。
- 关键文件：frontend/CLAUDE.md。

#### 117. docs: add CLAUDE.md

- 提交：`[a711c5f](https://github.com/bytedance/deer-flow/commit/a711c5f3104dfd4ab7e4058ac1a0ce42a50da0a5)`
- 日期：2026-02-06
- 做了什么：补充文档能力，主题是“add CLAUDE.md”。
- 影响范围：主要涉及 前端。
- 改动规模：+89 / -0 行。
- 关键文件：frontend/CLAUDE.md。

#### 118. docs: add CLAUDE.md

- 提交：`[8bd20ab](https://github.com/bytedance/deer-flow/commit/8bd20ab4e645e4aa5b0c908aa14955354516071e)`
- 日期：2026-02-06
- 做了什么：补充文档能力，主题是“add CLAUDE.md”。
- 影响范围：主要涉及 前端。
- 改动规模：+89 / -0 行。
- 关键文件：frontend/CLAUDE.md。

#### 119. docs: add AGENTS.md

- 提交：`[78b6164](https://github.com/bytedance/deer-flow/commit/78b6164770db512ad98cf45bed97a043cd3646da)`
- 日期：2026-02-06
- 做了什么：补充文档能力，主题是“add AGENTS.md”。
- 影响范围：主要涉及 前端。
- 改动规模：+100 / -0 行。
- 关键文件：frontend/AGENTS.md。

#### 120. docs: add AGENTS.md

- 提交：`[5b33a62](https://github.com/bytedance/deer-flow/commit/5b33a62f05c0297a9a163d6ef2e9f01145e45915)`
- 日期：2026-02-06
- 做了什么：补充文档能力，主题是“add AGENTS.md”。
- 影响范围：主要涉及 前端。
- 改动规模：+100 / -0 行。
- 关键文件：frontend/AGENTS.md。

#### 121. docs: add AGENTS.md

- 提交：`[30cd238](https://github.com/bytedance/deer-flow/commit/30cd2387f28df2b37ae02ef59bed664f68c73302)`
- 日期：2026-02-06
- 做了什么：补充文档能力，主题是“add AGENTS.md”。
- 影响范围：主要涉及 前端。
- 改动规模：+100 / -0 行。
- 关键文件：frontend/AGENTS.md。

#### 122. feat: update surprise-me functionality with localization support

- 提交：`[b74cf65](https://github.com/bytedance/deer-flow/commit/b74cf6527523c451001d7667f33ea077f3edb444)`
- 日期：2026-02-06
- 做了什么：新增或增强功能，主题是“update surprise-me functionality with localization support”。
- 影响范围：主要涉及 前端。
- 改动规模：+8 / -2 行。
- 关键文件：frontend/src/components/workspace/input-box.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts；frontend/src/core/i18n/locales/zh-CN.ts。

#### 123. feat: update surprise-me functionality with localization support

- 提交：`[765e35f](https://github.com/bytedance/deer-flow/commit/765e35fc70c7a6465e9bb575c4b88d24bbedb0bf)`
- 日期：2026-02-06
- 做了什么：新增或增强功能，主题是“update surprise-me functionality with localization support”。
- 影响范围：主要涉及 前端。
- 改动规模：+8 / -2 行。
- 关键文件：frontend/src/components/workspace/input-box.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts；frontend/src/core/i18n/locales/zh-CN.ts。

#### 124. feat: update surprise-me functionality with localization support

- 提交：`[bbb1a73](https://github.com/bytedance/deer-flow/commit/bbb1a731a530ef377c06cbe20c9ef894e39db6ce)`
- 日期：2026-02-06
- 做了什么：新增或增强功能，主题是“update surprise-me functionality with localization support”。
- 影响范围：主要涉及 前端。
- 改动规模：+8 / -2 行。
- 关键文件：frontend/src/components/workspace/input-box.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts；frontend/src/core/i18n/locales/zh-CN.ts。

#### 125. feat: add surprise-me

- 提交：`[22dea3f](https://github.com/bytedance/deer-flow/commit/22dea3fd433c7f1403cf0a3f372cfd7875452c0d)`
- 日期：2026-02-06
- 做了什么：新增或增强功能，主题是“add surprise-me”。
- 影响范围：主要涉及 前端、技能体系。
- 改动规模：+122 / -0 行。
- 关键文件：frontend/package.json；frontend/pnpm-lock.yaml；frontend/src/components/ui/confetti-button.tsx；frontend/src/components/workspace/input-box.tsx；skills/public/surprise-me/SKILL.md。

#### 126. feat: add surprise-me

- 提交：`[26e078d](https://github.com/bytedance/deer-flow/commit/26e078df7d6dd87a3fc02cd6ba685c3f6a1ff92c)`
- 日期：2026-02-06
- 做了什么：新增或增强功能，主题是“add surprise-me”。
- 影响范围：主要涉及 前端、技能体系。
- 改动规模：+122 / -0 行。
- 关键文件：frontend/package.json；frontend/pnpm-lock.yaml；frontend/src/components/ui/confetti-button.tsx；frontend/src/components/workspace/input-box.tsx；skills/public/surprise-me/SKILL.md。

#### 127. feat: add surprise-me

- 提交：`[697ea8e](https://github.com/bytedance/deer-flow/commit/697ea8e845a9ae27eb164c5a3ba1160c46298afd)`
- 日期：2026-02-06
- 做了什么：新增或增强功能，主题是“add surprise-me”。
- 影响范围：主要涉及 前端、技能体系。
- 改动规模：+122 / -0 行。
- 关键文件：frontend/package.json；frontend/pnpm-lock.yaml；frontend/src/components/ui/confetti-button.tsx；frontend/src/components/workspace/input-box.tsx；skills/public/surprise-me/SKILL.md。

#### 128. feat: adjust position

- 提交：`[f391060](https://github.com/bytedance/deer-flow/commit/f3910605737f56a5a2a664f9e844e8dfe79cb204)`
- 日期：2026-02-06
- 做了什么：新增或增强功能，主题是“adjust position”。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -1 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx。

#### 129. feat: adjust position

- 提交：`[254efe7](https://github.com/bytedance/deer-flow/commit/254efe739197448cb36c5a4edd61cce6fce46888)`
- 日期：2026-02-06
- 做了什么：新增或增强功能，主题是“adjust position”。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -1 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx。

#### 130. feat: adjust position

- 提交：`[dedfa1b](https://github.com/bytedance/deer-flow/commit/dedfa1bfb503f3b0c8259c6b128d3a550110e9d7)`
- 日期：2026-02-06
- 做了什么：新增或增强功能，主题是“adjust position”。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -1 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx。

#### 131. feat: add configuration to enable/disable subagents

- 提交：`[85128f5](https://github.com/bytedance/deer-flow/commit/85128f5f147ff09f6c1537abb21c177056684d2a)`
- 日期：2026-02-05
- 做了什么：新增或增强功能，主题是“add configuration to enable/disable subagents”。
- 影响范围：主要涉及 后端、配置。
- 改动规模：+105 / -63 行。
- 关键文件：backend/CLAUDE.md；backend/src/agents/lead_agent/prompt.py；backend/src/config/app_config.py；backend/src/config/subagents_config.py；backend/src/tools/tools.py；config.example.yaml。

#### 132. feat: add configuration to enable/disable subagents

- 提交：`[b7bf027](https://github.com/bytedance/deer-flow/commit/b7bf027aa5a463b08487c363516ff8340dda88d0)`
- 日期：2026-02-05
- 做了什么：新增或增强功能，主题是“add configuration to enable/disable subagents”。
- 影响范围：主要涉及 后端、配置。
- 改动规模：+105 / -63 行。
- 关键文件：backend/CLAUDE.md；backend/src/agents/lead_agent/prompt.py；backend/src/config/app_config.py；backend/src/config/subagents_config.py；backend/src/tools/tools.py；config.example.yaml。

#### 133. feat: add configuration to enable/disable subagents

- 提交：`[b7ba237](https://github.com/bytedance/deer-flow/commit/b7ba237c3656d8ddb2520fa3d7af4b26fca3ad77)`
- 日期：2026-02-05
- 做了什么：新增或增强功能，主题是“add configuration to enable/disable subagents”。
- 影响范围：主要涉及 后端、配置。
- 改动规模：+105 / -63 行。
- 关键文件：backend/CLAUDE.md；backend/src/agents/lead_agent/prompt.py；backend/src/config/app_config.py；backend/src/config/subagents_config.py；backend/src/tools/tools.py；config.example.yaml。

#### 134. feat: support sub agent mechanism

- 提交：`[ef379a3](https://github.com/bytedance/deer-flow/commit/ef379a310058f3e1771c89ff65e79e708b28ba35)`
- 日期：2026-02-05
- 做了什么：新增或增强功能，主题是“support sub agent mechanism”。
- 影响范围：主要涉及 后端、其他模块。
- 改动规模：+775 / -33 行。
- 关键文件：Makefile；backend/debug.py；backend/src/agents/lead_agent/prompt.py；backend/src/agents/memory/updater.py；backend/src/agents/middlewares/uploads_middleware.py；backend/src/community/aio_sandbox/aio_sandbox_provider.py；backend/src/config/extensions_config.py；backend/src/gateway/routers/artifacts.py。

#### 135. feat: support sub agent mechanism

- 提交：`[cbd2fe6](https://github.com/bytedance/deer-flow/commit/cbd2fe66dedee6335415dffdd97c111d6127b011)`
- 日期：2026-02-05
- 做了什么：新增或增强功能，主题是“support sub agent mechanism”。
- 影响范围：主要涉及 后端、其他模块。
- 改动规模：+775 / -33 行。
- 关键文件：Makefile；backend/debug.py；backend/src/agents/lead_agent/prompt.py；backend/src/agents/memory/updater.py；backend/src/agents/middlewares/uploads_middleware.py；backend/src/community/aio_sandbox/aio_sandbox_provider.py；backend/src/config/extensions_config.py；backend/src/gateway/routers/artifacts.py。

#### 136. feat: support sub agent mechanism

- 提交：`[6e3f43c](https://github.com/bytedance/deer-flow/commit/6e3f43c9431589a0aa652090db77c8b4218b8963)`
- 日期：2026-02-05
- 做了什么：新增或增强功能，主题是“support sub agent mechanism”。
- 影响范围：主要涉及 后端、其他模块。
- 改动规模：+775 / -33 行。
- 关键文件：Makefile；backend/debug.py；backend/src/agents/lead_agent/prompt.py；backend/src/agents/memory/updater.py；backend/src/agents/middlewares/uploads_middleware.py；backend/src/community/aio_sandbox/aio_sandbox_provider.py；backend/src/config/extensions_config.py；backend/src/gateway/routers/artifacts.py。

#### 137. feat: remove demo

- 提交：`[43ebce3](https://github.com/bytedance/deer-flow/commit/43ebce3b3744b2db38f97c57fad1ea169043c401)`
- 日期：2026-02-05
- 做了什么：新增或增强功能，主题是“remove demo”。
- 影响范围：主要涉及 前端。
- 改动规模：+7 / -5166 行。
- 关键文件：frontend/public/demo/threads/090898a7-1b1e-4937-ba03-764dbaafa27b/thread.json；frontend/public/demo/threads/090898a7-1b1e-4937-ba03-764dbaafa27b/user-data/outputs/nie-weiping-memorial/index.html；frontend/public/demo/threads/090898a7-1b1e-4937-ba03-764dbaafa27b/user-data/outputs/nie-weiping-memorial/script.js；frontend/public/demo/threads/090898a7-1b1e-4937-ba03-764dbaafa27b/user-data/outputs/nie-weiping-memorial/style.css；frontend/src/components/workspace/messages/message-group.tsx。

#### 138. feat: remove demo

- 提交：`[c31175d](https://github.com/bytedance/deer-flow/commit/c31175defdd1042865cfaf725429495a14d5e17c)`
- 日期：2026-02-05
- 做了什么：新增或增强功能，主题是“remove demo”。
- 影响范围：主要涉及 前端。
- 改动规模：+7 / -5166 行。
- 关键文件：frontend/public/demo/threads/090898a7-1b1e-4937-ba03-764dbaafa27b/thread.json；frontend/public/demo/threads/090898a7-1b1e-4937-ba03-764dbaafa27b/user-data/outputs/nie-weiping-memorial/index.html；frontend/public/demo/threads/090898a7-1b1e-4937-ba03-764dbaafa27b/user-data/outputs/nie-weiping-memorial/script.js；frontend/public/demo/threads/090898a7-1b1e-4937-ba03-764dbaafa27b/user-data/outputs/nie-weiping-memorial/style.css；frontend/src/components/workspace/messages/message-group.tsx。

#### 139. feat: remove demo

- 提交：`[118fc00](https://github.com/bytedance/deer-flow/commit/118fc0036850072f08f195064c47ac2a1839c378)`
- 日期：2026-02-05
- 做了什么：新增或增强功能，主题是“remove demo”。
- 影响范围：主要涉及 前端。
- 改动规模：+7 / -5166 行。
- 关键文件：frontend/public/demo/threads/090898a7-1b1e-4937-ba03-764dbaafa27b/thread.json；frontend/public/demo/threads/090898a7-1b1e-4937-ba03-764dbaafa27b/user-data/outputs/nie-weiping-memorial/index.html；frontend/public/demo/threads/090898a7-1b1e-4937-ba03-764dbaafa27b/user-data/outputs/nie-weiping-memorial/script.js；frontend/public/demo/threads/090898a7-1b1e-4937-ba03-764dbaafa27b/user-data/outputs/nie-weiping-memorial/style.css；frontend/src/components/workspace/messages/message-group.tsx。

#### 140. feat: enhance memory system with tiktoken and improved prompt guidelines

- 提交：`[db04611](https://github.com/bytedance/deer-flow/commit/db0461142ebed5f4555c6e59fda286cc68879559)`
- 日期：2026-02-04
- 做了什么：新增或增强功能，主题是“enhance memory system with tiktoken and improved prompt guidelines”。
- 影响范围：主要涉及 后端、技能体系。
- 改动规模：+659 / -50 行。
- 关键文件：backend/docs/MEMORY_IMPROVEMENTS.md；backend/docs/MEMORY_IMPROVEMENTS_SUMMARY.md；backend/pyproject.toml；backend/src/agents/memory/prompt.py；backend/uv.lock；skills/public/deep-research/SKILL.md。

#### 141. feat: enhance memory system with tiktoken and improved prompt guidelines

- 提交：`[0d245d6](https://github.com/bytedance/deer-flow/commit/0d245d6e31d9ebbc58365584e3b46eca68429356)`
- 日期：2026-02-04
- 做了什么：新增或增强功能，主题是“enhance memory system with tiktoken and improved prompt guidelines”。
- 影响范围：主要涉及 后端、技能体系。
- 改动规模：+659 / -50 行。
- 关键文件：backend/docs/MEMORY_IMPROVEMENTS.md；backend/docs/MEMORY_IMPROVEMENTS_SUMMARY.md；backend/pyproject.toml；backend/src/agents/memory/prompt.py；backend/uv.lock；skills/public/deep-research/SKILL.md。

#### 142. feat: enhance memory system with tiktoken and improved prompt guidelines

- 提交：`[df1191c](https://github.com/bytedance/deer-flow/commit/df1191c90ac886596c37c285d1bd97afed5e1790)`
- 日期：2026-02-04
- 做了什么：新增或增强功能，主题是“enhance memory system with tiktoken and improved prompt guidelines”。
- 影响范围：主要涉及 后端、技能体系。
- 改动规模：+659 / -50 行。
- 关键文件：backend/docs/MEMORY_IMPROVEMENTS.md；backend/docs/MEMORY_IMPROVEMENTS_SUMMARY.md；backend/pyproject.toml；backend/src/agents/memory/prompt.py；backend/uv.lock；skills/public/deep-research/SKILL.md。

#### 143. feat(citations): add shared citation components and optimize code

- 提交：`[644229f](https://github.com/bytedance/deer-flow/commit/644229f968dc824cb7c2ec5b6f3e07d971bdde3c)`
- 日期：2026-02-04
- 做了什么：新增或增强功能，主题是“add shared citation components and optimize code”。
- 影响范围：主要涉及 前端、后端。
- 改动规模：+519 / -465 行。
- 关键文件：backend/src/gateway/routers/artifacts.py；frontend/src/components/ai-elements/inline-citation.tsx；frontend/src/components/workspace/artifacts/artifact-file-detail.tsx；frontend/src/components/workspace/messages/message-group.tsx；frontend/src/components/workspace/messages/message-list-item.tsx；frontend/src/components/workspace/settings/memory-settings-page.tsx；frontend/src/core/citations/index.ts；frontend/src/core/citations/utils.ts。

#### 144. feat(citations): add shared citation components and optimize code

- 提交：`[c67f1af](https://github.com/bytedance/deer-flow/commit/c67f1af889b290b09c484a8ef3827134dfba115a)`
- 日期：2026-02-04
- 做了什么：新增或增强功能，主题是“add shared citation components and optimize code”。
- 影响范围：主要涉及 前端、后端。
- 改动规模：+519 / -465 行。
- 关键文件：backend/src/gateway/routers/artifacts.py；frontend/src/components/ai-elements/inline-citation.tsx；frontend/src/components/workspace/artifacts/artifact-file-detail.tsx；frontend/src/components/workspace/messages/message-group.tsx；frontend/src/components/workspace/messages/message-list-item.tsx；frontend/src/components/workspace/settings/memory-settings-page.tsx；frontend/src/core/citations/index.ts；frontend/src/core/citations/utils.ts。

#### 145. feat(citations): add shared citation components and optimize code

- 提交：`[1e2675b](https://github.com/bytedance/deer-flow/commit/1e2675beb35dab1f640b987118a5a6a6d9354596)`
- 日期：2026-02-04
- 做了什么：新增或增强功能，主题是“add shared citation components and optimize code”。
- 影响范围：主要涉及 前端、后端。
- 改动规模：+519 / -465 行。
- 关键文件：backend/src/gateway/routers/artifacts.py；frontend/src/components/ai-elements/inline-citation.tsx；frontend/src/components/workspace/artifacts/artifact-file-detail.tsx；frontend/src/components/workspace/messages/message-group.tsx；frontend/src/components/workspace/messages/message-list-item.tsx；frontend/src/components/workspace/settings/memory-settings-page.tsx；frontend/src/core/citations/index.ts；frontend/src/core/citations/utils.ts。

#### 146. feat: add Apple Container support with comprehensive documentation and dev tools

- 提交：`[5959ef8](https://github.com/bytedance/deer-flow/commit/5959ef87b8b06479f144560cb48cb8523f69de2d)`
- 日期：2026-02-03
- 做了什么：新增或增强功能，主题是“add Apple Container support with comprehensive documentation and dev tools”。
- 影响范围：主要涉及 后端、其他模块、文档。
- 改动规模：+556 / -30 行。
- 关键文件：Makefile；README.md；backend/CLAUDE.md；backend/docs/APPLE_CONTAINER.md；backend/docs/SETUP.md；backend/src/community/aio_sandbox/aio_sandbox_provider.py；config.example.yaml；scripts/cleanup-containers.sh。

#### 147. feat: add Apple Container support with comprehensive documentation and dev tools

- 提交：`[70a27b4](https://github.com/bytedance/deer-flow/commit/70a27b49c0d3e3306be6f53a283f08403e527de8)`
- 日期：2026-02-03
- 做了什么：新增或增强功能，主题是“add Apple Container support with comprehensive documentation and dev tools”。
- 影响范围：主要涉及 后端、其他模块、文档。
- 改动规模：+556 / -30 行。
- 关键文件：Makefile；README.md；backend/CLAUDE.md；backend/docs/APPLE_CONTAINER.md；backend/docs/SETUP.md；backend/src/community/aio_sandbox/aio_sandbox_provider.py；config.example.yaml；scripts/cleanup-containers.sh。

#### 148. feat: add Apple Container support with comprehensive documentation and dev tools

- 提交：`[ef10f3b](https://github.com/bytedance/deer-flow/commit/ef10f3ba413f926ced88ee2f44c4ecec91306817)`
- 日期：2026-02-03
- 做了什么：新增或增强功能，主题是“add Apple Container support with comprehensive documentation and dev tools”。
- 影响范围：主要涉及 后端、其他模块、文档。
- 改动规模：+556 / -30 行。
- 关键文件：Makefile；README.md；backend/CLAUDE.md；backend/docs/APPLE_CONTAINER.md；backend/docs/SETUP.md；backend/src/community/aio_sandbox/aio_sandbox_provider.py；config.example.yaml；scripts/cleanup-containers.sh。

#### 149. feat: add memory settings page

- 提交：`[6b53456](https://github.com/bytedance/deer-flow/commit/6b53456b3909bbe84507ec22b7be2e1e27c085ff)`
- 日期：2026-02-03
- 做了什么：新增或增强功能，主题是“add memory settings page”。
- 影响范围：主要涉及 前端、后端。
- 改动规模：+411 / -17 行。
- 关键文件：backend/README.md；frontend/src/components/landing/hero.tsx；frontend/src/components/landing/sections/whats-new-section.tsx；frontend/src/components/workspace/settings/memory-settings-page.tsx；frontend/src/components/workspace/settings/settings-dialog.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts；frontend/src/core/i18n/locales/zh-CN.ts。

#### 150. feat: add memory settings page

- 提交：`[94acb15](https://github.com/bytedance/deer-flow/commit/94acb15c0c7cd84c290ea73b429c6da4dc8526b8)`
- 日期：2026-02-03
- 做了什么：新增或增强功能，主题是“add memory settings page”。
- 影响范围：主要涉及 前端、后端。
- 改动规模：+411 / -17 行。
- 关键文件：backend/README.md；frontend/src/components/landing/hero.tsx；frontend/src/components/landing/sections/whats-new-section.tsx；frontend/src/components/workspace/settings/memory-settings-page.tsx；frontend/src/components/workspace/settings/settings-dialog.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts；frontend/src/core/i18n/locales/zh-CN.ts。

#### 151. feat: add memory settings page

- 提交：`[552d1c3](https://github.com/bytedance/deer-flow/commit/552d1c3a9aae49081347bd7f2ecd8820acb97f66)`
- 日期：2026-02-03
- 做了什么：新增或增强功能，主题是“add memory settings page”。
- 影响范围：主要涉及 前端、后端。
- 改动规模：+411 / -17 行。
- 关键文件：backend/README.md；frontend/src/components/landing/hero.tsx；frontend/src/components/landing/sections/whats-new-section.tsx；frontend/src/components/workspace/settings/memory-settings-page.tsx；frontend/src/components/workspace/settings/settings-dialog.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts；frontend/src/core/i18n/locales/zh-CN.ts。

#### 152. chore: add /api/memory

- 提交：`[4d650f3](https://github.com/bytedance/deer-flow/commit/4d650f35f8887fbc1c4c5142513376e6281b1840)`
- 日期：2026-02-03
- 做了什么：新增或增强功能，主题是“add /api/memory”。
- 影响范围：主要涉及 容器部署。
- 改动规模：+20 / -0 行。
- 关键文件：docker/nginx/nginx.conf；docker/nginx/nginx.local.conf。

#### 153. chore: add /api/memory

- 提交：`[b8c325e](https://github.com/bytedance/deer-flow/commit/b8c325eb3a7b44cd1450347a8d96d05844ee0e00)`
- 日期：2026-02-03
- 做了什么：新增或增强功能，主题是“add /api/memory”。
- 影响范围：主要涉及 容器部署。
- 改动规模：+20 / -0 行。
- 关键文件：docker/nginx/nginx.conf；docker/nginx/nginx.local.conf。

#### 154. chore: add /api/memory

- 提交：`[1cf0811](https://github.com/bytedance/deer-flow/commit/1cf081120e3f288448e211de685818ca43bc3cc9)`
- 日期：2026-02-03
- 做了什么：新增或增强功能，主题是“add /api/memory”。
- 影响范围：主要涉及 容器部署。
- 改动规模：+20 / -0 行。
- 关键文件：docker/nginx/nginx.conf；docker/nginx/nginx.local.conf。

#### 155. feat: add memory API and optimize memory middleware

- 提交：`[3b30913](https://github.com/bytedance/deer-flow/commit/3b30913e100c7411084feb76a78a3b68e376278e)`
- 日期：2026-02-03
- 做了什么：新增或增强功能，主题是“add memory API and optimize memory middleware”。
- 影响范围：主要涉及 后端、配置。
- 改动规模：+267 / -8 行。
- 关键文件：backend/src/agents/middlewares/memory_middleware.py；backend/src/gateway/app.py；backend/src/gateway/routers/memory.py；config.example.yaml。

#### 156. feat: add memory API and optimize memory middleware

- 提交：`[7b7a7ab](https://github.com/bytedance/deer-flow/commit/7b7a7abaf2faa4d0e6a3f136ee0d737ee3e6d646)`
- 日期：2026-02-03
- 做了什么：新增或增强功能，主题是“add memory API and optimize memory middleware”。
- 影响范围：主要涉及 后端、配置。
- 改动规模：+267 / -8 行。
- 关键文件：backend/src/agents/middlewares/memory_middleware.py；backend/src/gateway/app.py；backend/src/gateway/routers/memory.py；config.example.yaml。

#### 157. feat: add memory API and optimize memory middleware

- 提交：`[74d47ad](https://github.com/bytedance/deer-flow/commit/74d47ad87f1464f50d5956e5aff5e1b821b2c7c1)`
- 日期：2026-02-03
- 做了什么：新增或增强功能，主题是“add memory API and optimize memory middleware”。
- 影响范围：主要涉及 后端、配置。
- 改动规模：+267 / -8 行。
- 关键文件：backend/src/agents/middlewares/memory_middleware.py；backend/src/gateway/app.py；backend/src/gateway/routers/memory.py；config.example.yaml。

#### 158. feat: add global memory mechanism for personalized conversations

- 提交：`[0ea666e](https://github.com/bytedance/deer-flow/commit/0ea666e0cfe08aeadb7c66b88bcaca98c03b6466)`
- 日期：2026-02-03
- 做了什么：新增或增强功能，主题是“add global memory mechanism for personalized conversations”。
- 影响范围：主要涉及 后端。
- 改动规模：+929 / -3 行。
- 关键文件：backend/src/agents/lead_agent/agent.py；backend/src/agents/lead_agent/prompt.py；backend/src/agents/memory/**init**.py；backend/src/agents/memory/prompt.py；backend/src/agents/memory/queue.py；backend/src/agents/memory/updater.py；backend/src/agents/middlewares/memory_middleware.py；backend/src/config/**init**.py。

#### 159. feat: add global memory mechanism for personalized conversations

- 提交：`[18d85ab](https://github.com/bytedance/deer-flow/commit/18d85ab6e501df6a0f8110554a70ce8525a28eed)`
- 日期：2026-02-03
- 做了什么：新增或增强功能，主题是“add global memory mechanism for personalized conversations”。
- 影响范围：主要涉及 后端。
- 改动规模：+929 / -3 行。
- 关键文件：backend/src/agents/lead_agent/agent.py；backend/src/agents/lead_agent/prompt.py；backend/src/agents/memory/**init**.py；backend/src/agents/memory/prompt.py；backend/src/agents/memory/queue.py；backend/src/agents/memory/updater.py；backend/src/agents/middlewares/memory_middleware.py；backend/src/config/**init**.py。

#### 160. feat: add global memory mechanism for personalized conversations

- 提交：`[ffd07bb](https://github.com/bytedance/deer-flow/commit/ffd07bbafeef6e0424c56475c031edd91dc34b02)`
- 日期：2026-02-03
- 做了什么：新增或增强功能，主题是“add global memory mechanism for personalized conversations”。
- 影响范围：主要涉及 后端。
- 改动规模：+929 / -3 行。
- 关键文件：backend/src/agents/lead_agent/agent.py；backend/src/agents/lead_agent/prompt.py；backend/src/agents/memory/**init**.py；backend/src/agents/memory/prompt.py；backend/src/agents/memory/queue.py；backend/src/agents/memory/updater.py；backend/src/agents/middlewares/memory_middleware.py；backend/src/config/**init**.py。

#### 161. docs: add README.md

- 提交：`[8625551](https://github.com/bytedance/deer-flow/commit/86255511e1530702c46cf292cebffa5aa27fd196)`
- 日期：2026-02-02
- 做了什么：补充文档能力，主题是“add README.md”。
- 影响范围：主要涉及 前端。
- 改动规模：+131 / -8 行。
- 关键文件：frontend/.env.example；frontend/README.md。

#### 162. docs: add README.md

- 提交：`[0baa8a7](https://github.com/bytedance/deer-flow/commit/0baa8a733a77b17a6455d1a5ddc817ce4d847a6b)`
- 日期：2026-02-02
- 做了什么：补充文档能力，主题是“add README.md”。
- 影响范围：主要涉及 前端。
- 改动规模：+131 / -8 行。
- 关键文件：frontend/.env.example；frontend/README.md。

#### 163. docs: add README.md

- 提交：`[4fd9a2d](https://github.com/bytedance/deer-flow/commit/4fd9a2de8e797fe1e734b03ec3fad76a513144cb)`
- 日期：2026-02-02
- 做了什么：补充文档能力，主题是“add README.md”。
- 影响范围：主要涉及 前端。
- 改动规模：+131 / -8 行。
- 关键文件：frontend/.env.example；frontend/README.md。

#### 164. feat: enhance welcome component and input box with skill mode handling and localization updates

- 提交：`[f4f16bf](https://github.com/bytedance/deer-flow/commit/f4f16bfa5c3ced67e7c397b9cc776bc21d8a22fc)`
- 日期：2026-02-02
- 做了什么：新增或增强功能，主题是“enhance welcome component and input box with skill mode handling and localization updates”。
- 影响范围：主要涉及 前端。
- 改动规模：+33 / -9 行。
- 关键文件：frontend/src/components/workspace/input-box.tsx；frontend/src/components/workspace/welcome.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts；frontend/src/core/i18n/locales/zh-CN.ts。

#### 165. feat: enhance welcome component and input box with skill mode handling and localization updates

- 提交：`[010eade](https://github.com/bytedance/deer-flow/commit/010eadecca3568baa64de94a91dc3deace6978b5)`
- 日期：2026-02-02
- 做了什么：新增或增强功能，主题是“enhance welcome component and input box with skill mode handling and localization updates”。
- 影响范围：主要涉及 前端。
- 改动规模：+33 / -9 行。
- 关键文件：frontend/src/components/workspace/input-box.tsx；frontend/src/components/workspace/welcome.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts；frontend/src/core/i18n/locales/zh-CN.ts。

#### 166. feat: enhance welcome component and input box with skill mode handling and localization updates

- 提交：`[26acd6f](https://github.com/bytedance/deer-flow/commit/26acd6f3ad73cb06ad0f774d23476d3771869c8c)`
- 日期：2026-02-02
- 做了什么：新增或增强功能，主题是“enhance welcome component and input box with skill mode handling and localization updates”。
- 影响范围：主要涉及 前端。
- 改动规模：+33 / -9 行。
- 关键文件：frontend/src/components/workspace/input-box.tsx；frontend/src/components/workspace/welcome.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts；frontend/src/core/i18n/locales/zh-CN.ts。

#### 167. feat: update button in skill settings to include icon

- 提交：`[ccf2123](https://github.com/bytedance/deer-flow/commit/ccf21238afe33216a20dc95b25491ec2ad25e893)`
- 日期：2026-02-02
- 做了什么：新增或增强功能，主题是“update button in skill settings to include icon”。
- 影响范围：主要涉及 前端。
- 改动规模：+2 / -1 行。
- 关键文件：frontend/src/components/workspace/settings/skill-settings-page.tsx。

#### 168. feat: update button in skill settings to include icon

- 提交：`[67451df](https://github.com/bytedance/deer-flow/commit/67451df910f0978b040924b520a215388985f3e9)`
- 日期：2026-02-02
- 做了什么：新增或增强功能，主题是“update button in skill settings to include icon”。
- 影响范围：主要涉及 前端。
- 改动规模：+2 / -1 行。
- 关键文件：frontend/src/components/workspace/settings/skill-settings-page.tsx。

#### 169. feat: update button in skill settings to include icon

- 提交：`[9cc4113](https://github.com/bytedance/deer-flow/commit/9cc41139cbddef32df8ba95201e00875df004bc6)`
- 日期：2026-02-02
- 做了什么：新增或增强功能，主题是“update button in skill settings to include icon”。
- 影响范围：主要涉及 前端。
- 改动规模：+2 / -1 行。
- 关键文件：frontend/src/components/workspace/settings/skill-settings-page.tsx。

#### 170. feat: use list of links

- 提交：`[efd56fd](https://github.com/bytedance/deer-flow/commit/efd56fdf512667095a6ddeb737c7d953ef91bcf2)`
- 日期：2026-02-02
- 做了什么：新增或增强功能，主题是“use list of links”。
- 影响范围：主要涉及 技能体系。
- 改动规模：+2 / -2 行。
- 关键文件：skills/public/vercel-deploy-claimable/SKILL.md。

#### 171. feat: use list of links

- 提交：`[a5a0222](https://github.com/bytedance/deer-flow/commit/a5a02229633f0a48ab5c02d3301ed7d8964157ab)`
- 日期：2026-02-02
- 做了什么：新增或增强功能，主题是“use list of links”。
- 影响范围：主要涉及 技能体系。
- 改动规模：+2 / -2 行。
- 关键文件：skills/public/vercel-deploy-claimable/SKILL.md。

#### 172. feat: use list of links

- 提交：`[207cb2b](https://github.com/bytedance/deer-flow/commit/207cb2b98d31ce258335ef33d685e0cf0424a663)`
- 日期：2026-02-02
- 做了什么：新增或增强功能，主题是“use list of links”。
- 影响范围：主要涉及 技能体系。
- 改动规模：+2 / -2 行。
- 关键文件：skills/public/vercel-deploy-claimable/SKILL.md。

#### 173. feat: update button styling for artifacts tooltip

- 提交：`[b7c9bf5](https://github.com/bytedance/deer-flow/commit/b7c9bf557b19909f175a4fa1bf7480fe29eb01ed)`
- 日期：2026-02-02
- 做了什么：新增或增强功能，主题是“update button styling for artifacts tooltip”。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -0 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx。

#### 174. feat: update button styling for artifacts tooltip

- 提交：`[44daeaf](https://github.com/bytedance/deer-flow/commit/44daeaf37dbba05cff681aaa4011d8c6efffa52b)`
- 日期：2026-02-02
- 做了什么：新增或增强功能，主题是“update button styling for artifacts tooltip”。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -0 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx。

#### 175. feat: update button styling for artifacts tooltip

- 提交：`[b5e9eee](https://github.com/bytedance/deer-flow/commit/b5e9eeea9984d4248e161157c70c69a6c90c42d7)`
- 日期：2026-02-02
- 做了什么：新增或增强功能，主题是“update button styling for artifacts tooltip”。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -0 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx。

#### 176. feat: add suggestions

- 提交：`[3067f8d](https://github.com/bytedance/deer-flow/commit/3067f8dd03a102ad153ba5b3f664b36ed6722bd8)`
- 日期：2026-02-02
- 做了什么：新增或增强功能，主题是“add suggestions”。
- 影响范围：主要涉及 前端。
- 改动规模：+229 / -10 行。
- 关键文件：frontend/src/components/ai-elements/suggestion.tsx；frontend/src/components/workspace/input-box.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts；frontend/src/core/i18n/locales/zh-CN.ts。

#### 177. feat: add suggestions

- 提交：`[154fbb0](https://github.com/bytedance/deer-flow/commit/154fbb0ba364d756339c5273f11fcba417c3ed7e)`
- 日期：2026-02-02
- 做了什么：新增或增强功能，主题是“add suggestions”。
- 影响范围：主要涉及 前端。
- 改动规模：+229 / -10 行。
- 关键文件：frontend/src/components/ai-elements/suggestion.tsx；frontend/src/components/workspace/input-box.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts；frontend/src/core/i18n/locales/zh-CN.ts。

#### 178. feat: add suggestions

- 提交：`[e673405](https://github.com/bytedance/deer-flow/commit/e673405c00adf261c79ed48c4ae40c3debee64cc)`
- 日期：2026-02-02
- 做了什么：新增或增强功能，主题是“add suggestions”。
- 影响范围：主要涉及 前端。
- 改动规模：+229 / -10 行。
- 关键文件：frontend/src/components/ai-elements/suggestion.tsx；frontend/src/components/workspace/input-box.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts；frontend/src/core/i18n/locales/zh-CN.ts。

#### 179. feat: integrate PromptInputProvider into ChatLayout and utilize prompt input controller in ChatPage

- 提交：`[6c0e5ff](https://github.com/bytedance/deer-flow/commit/6c0e5fffd07997dfef80bbcd92fa235a3bfb56ec)`
- 日期：2026-02-02
- 做了什么：新增或增强功能，主题是“integrate PromptInputProvider into ChatLayout and utilize prompt input controller in ChatPage”。
- 影响范围：主要涉及 前端。
- 改动规模：+10 / -3 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/layout.tsx；frontend/src/app/workspace/chats/[thread_id]/page.tsx。

#### 180. feat: integrate PromptInputProvider into ChatLayout and utilize prompt input controller in ChatPage

- 提交：`[f287022](https://github.com/bytedance/deer-flow/commit/f287022ac053946176eec79ae92551bdd8c48b75)`
- 日期：2026-02-02
- 做了什么：新增或增强功能，主题是“integrate PromptInputProvider into ChatLayout and utilize prompt input controller in ChatPage”。
- 影响范围：主要涉及 前端。
- 改动规模：+10 / -3 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/layout.tsx；frontend/src/app/workspace/chats/[thread_id]/page.tsx。

#### 181. feat: integrate PromptInputProvider into ChatLayout and utilize prompt input controller in ChatPage

- 提交：`[b1227bb](https://github.com/bytedance/deer-flow/commit/b1227bb9117b53a440568657fedcbb590fead8ad)`
- 日期：2026-02-02
- 做了什么：新增或增强功能，主题是“integrate PromptInputProvider into ChatLayout and utilize prompt input controller in ChatPage”。
- 影响范围：主要涉及 前端。
- 改动规模：+10 / -3 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/layout.tsx；frontend/src/app/workspace/chats/[thread_id]/page.tsx。

#### 182. feat: add file icons

- 提交：`[867749d](https://github.com/bytedance/deer-flow/commit/867749d7a35896bbcd2670e9cd07615a90377024)`
- 日期：2026-02-02
- 做了什么：新增或增强功能，主题是“add file icons”。
- 影响范围：主要涉及 前端。
- 改动规模：+23 / -6 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/ai-elements/chain-of-thought.tsx；frontend/src/components/workspace/artifacts/artifact-file-list.tsx；frontend/src/components/workspace/artifacts/context.tsx；frontend/src/core/utils/files.tsx。

#### 183. feat: add file icons

- 提交：`[c587460](https://github.com/bytedance/deer-flow/commit/c587460dbcc6cf6d94d5f2581fa3710308b78e7f)`
- 日期：2026-02-02
- 做了什么：新增或增强功能，主题是“add file icons”。
- 影响范围：主要涉及 前端。
- 改动规模：+23 / -6 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/ai-elements/chain-of-thought.tsx；frontend/src/components/workspace/artifacts/artifact-file-list.tsx；frontend/src/components/workspace/artifacts/context.tsx；frontend/src/core/utils/files.tsx。

#### 184. feat: add file icons

- 提交：`[f1db301](https://github.com/bytedance/deer-flow/commit/f1db301d775e8295c65297cafca31595a1e2f351)`
- 日期：2026-02-02
- 做了什么：新增或增强功能，主题是“add file icons”。
- 影响范围：主要涉及 前端。
- 改动规模：+23 / -6 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/ai-elements/chain-of-thought.tsx；frontend/src/components/workspace/artifacts/artifact-file-list.tsx；frontend/src/components/workspace/artifacts/context.tsx；frontend/src/core/utils/files.tsx。

#### 185. feat: add file icon

- 提交：`[37dcee4](https://github.com/bytedance/deer-flow/commit/37dcee41c01a19942926bf11bd9632cdccbafc88)`
- 日期：2026-02-02
- 做了什么：新增或增强功能，主题是“add file icon”。
- 影响范围：主要涉及 前端。
- 改动规模：+236 / -186 行。
- 关键文件：frontend/src/components/workspace/artifacts/artifact-file-list.tsx；frontend/src/core/utils/files.ts；frontend/src/core/utils/files.tsx。

#### 186. feat: add file icon

- 提交：`[8bb4c35](https://github.com/bytedance/deer-flow/commit/8bb4c35416ba1d48b0d919171fb2fa95802cea2b)`
- 日期：2026-02-02
- 做了什么：新增或增强功能，主题是“add file icon”。
- 影响范围：主要涉及 前端。
- 改动规模：+236 / -186 行。
- 关键文件：frontend/src/components/workspace/artifacts/artifact-file-list.tsx；frontend/src/core/utils/files.ts；frontend/src/core/utils/files.tsx。

#### 187. feat: add file icon

- 提交：`[02400e0](https://github.com/bytedance/deer-flow/commit/02400e0e8c3049e87ad19895ecc39cdb2d376fd5)`
- 日期：2026-02-02
- 做了什么：新增或增强功能，主题是“add file icon”。
- 影响范围：主要涉及 前端。
- 改动规模：+236 / -186 行。
- 关键文件：frontend/src/components/workspace/artifacts/artifact-file-list.tsx；frontend/src/core/utils/files.ts；frontend/src/core/utils/files.tsx。

#### 188. feat: adjust tooltips

- 提交：`[51b4ed3](https://github.com/bytedance/deer-flow/commit/51b4ed3124dbdff29453074c9cf0d497791e8faf)`
- 日期：2026-02-02
- 做了什么：新增或增强功能，主题是“adjust tooltips”。
- 影响范围：主要涉及 前端。
- 改动规模：+16 / -3 行。
- 关键文件：frontend/src/components/ui/tooltip.tsx；frontend/src/components/workspace/messages/message-group.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts；frontend/src/core/i18n/locales/zh-CN.ts。

#### 189. feat: adjust tooltips

- 提交：`[7274f9a](https://github.com/bytedance/deer-flow/commit/7274f9a6ae06fe9f5e89998509ebb17d4ce8160c)`
- 日期：2026-02-02
- 做了什么：新增或增强功能，主题是“adjust tooltips”。
- 影响范围：主要涉及 前端。
- 改动规模：+16 / -3 行。
- 关键文件：frontend/src/components/ui/tooltip.tsx；frontend/src/components/workspace/messages/message-group.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts；frontend/src/core/i18n/locales/zh-CN.ts。

#### 190. feat: adjust tooltips

- 提交：`[0091da1](https://github.com/bytedance/deer-flow/commit/0091da1aeec6ca2109307e3998b330e17a048a92)`
- 日期：2026-02-02
- 做了什么：新增或增强功能，主题是“adjust tooltips”。
- 影响范围：主要涉及 前端。
- 改动规模：+16 / -3 行。
- 关键文件：frontend/src/components/ui/tooltip.tsx；frontend/src/components/workspace/messages/message-group.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts；frontend/src/core/i18n/locales/zh-CN.ts。

#### 191. feat: wrap path and command in Tooltip for enhanced user experience

- 提交：`[6d31c1c](https://github.com/bytedance/deer-flow/commit/6d31c1c5cf8bd87781fecbbe2685ff3047d919c2)`
- 日期：2026-02-02
- 做了什么：新增或增强功能，主题是“wrap path and command in Tooltip for enhanced user experience”。
- 影响范围：主要涉及 前端。
- 改动规模：+24 / -12 行。
- 关键文件：frontend/src/components/workspace/messages/message-group.tsx。

#### 192. feat: wrap path and command in Tooltip for enhanced user experience

- 提交：`[cb494fe](https://github.com/bytedance/deer-flow/commit/cb494fe4dfa19522f32af19c2bbdb99767793173)`
- 日期：2026-02-02
- 做了什么：新增或增强功能，主题是“wrap path and command in Tooltip for enhanced user experience”。
- 影响范围：主要涉及 前端。
- 改动规模：+24 / -12 行。
- 关键文件：frontend/src/components/workspace/messages/message-group.tsx。

#### 193. feat: wrap path and command in Tooltip for enhanced user experience

- 提交：`[076c1f0](https://github.com/bytedance/deer-flow/commit/076c1f0985b6d8e40024e534df208fa117ecba54)`
- 日期：2026-02-02
- 做了什么：新增或增强功能，主题是“wrap path and command in Tooltip for enhanced user experience”。
- 影响范围：主要涉及 前端。
- 改动规模：+24 / -12 行。
- 关键文件：frontend/src/components/workspace/messages/message-group.tsx。

#### 194. docs: add comments

- 提交：`[9010429](https://github.com/bytedance/deer-flow/commit/90104291ae14b3c12413e8e63b9ff715e1070bcf)`
- 日期：2026-02-02
- 做了什么：补充文档能力，主题是“add comments”。
- 影响范围：主要涉及 前端。
- 改动规模：+10 / -0 行。
- 关键文件：frontend/src/components/workspace/input-box.tsx。

#### 195. docs: add comments

- 提交：`[68df848](https://github.com/bytedance/deer-flow/commit/68df848b82442e79d5b616e65b164afc33a8f4ec)`
- 日期：2026-02-02
- 做了什么：补充文档能力，主题是“add comments”。
- 影响范围：主要涉及 前端。
- 改动规模：+10 / -0 行。
- 关键文件：frontend/src/components/workspace/input-box.tsx。

#### 196. docs: add comments

- 提交：`[ac16a73](https://github.com/bytedance/deer-flow/commit/ac16a73a474a578208905fe78cc14a26525a651e)`
- 日期：2026-02-02
- 做了什么：补充文档能力，主题是“add comments”。
- 影响范围：主要涉及 前端。
- 改动规模：+10 / -0 行。
- 关键文件：frontend/src/components/workspace/input-box.tsx。

#### 197. feat: add skeleton

- 提交：`[54277b9](https://github.com/bytedance/deer-flow/commit/54277b9d9ea6e21f2c1438e9dc08774d90b66cc2)`
- 日期：2026-02-02
- 做了什么：新增或增强功能，主题是“add skeleton”。
- 影响范围：主要涉及 前端。
- 改动规模：+89 / -2 行。
- 关键文件：frontend/src/components/workspace/messages/skeleton.tsx；frontend/src/styles/globals.css。

#### 198. feat: add skeleton

- 提交：`[b797ef8](https://github.com/bytedance/deer-flow/commit/b797ef816831c80023c2fb83f7b18c5aa62e739a)`
- 日期：2026-02-02
- 做了什么：新增或增强功能，主题是“add skeleton”。
- 影响范围：主要涉及 前端。
- 改动规模：+89 / -2 行。
- 关键文件：frontend/src/components/workspace/messages/skeleton.tsx；frontend/src/styles/globals.css。

#### 199. feat: add skeleton

- 提交：`[7da0a03](https://github.com/bytedance/deer-flow/commit/7da0a03dd0b200bcf1c6de599ca5a352efb15a52)`
- 日期：2026-02-02
- 做了什么：新增或增强功能，主题是“add skeleton”。
- 影响范围：主要涉及 前端。
- 改动规模：+89 / -2 行。
- 关键文件：frontend/src/components/workspace/messages/skeleton.tsx；frontend/src/styles/globals.css。

#### 200. feat: dynamic title

- 提交：`[a0a3a3f](https://github.com/bytedance/deer-flow/commit/a0a3a3fc0225aeae5d462cb4fe021783a82e80f7)`
- 日期：2026-02-02
- 做了什么：新增或增强功能，主题是“dynamic title”。
- 影响范围：主要涉及 前端。
- 改动规模：+51 / -2 行。
- 关键文件：frontend/src/app/layout.tsx；frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/app/workspace/chats/page.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts；frontend/src/core/i18n/locales/zh-CN.ts。

#### 201. feat: dynamic title

- 提交：`[be65130](https://github.com/bytedance/deer-flow/commit/be65130a062ab3eba98234a2574eaa5130fe0409)`
- 日期：2026-02-02
- 做了什么：新增或增强功能，主题是“dynamic title”。
- 影响范围：主要涉及 前端。
- 改动规模：+51 / -2 行。
- 关键文件：frontend/src/app/layout.tsx；frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/app/workspace/chats/page.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts；frontend/src/core/i18n/locales/zh-CN.ts。

#### 202. feat: dynamic title

- 提交：`[1eb4da6](https://github.com/bytedance/deer-flow/commit/1eb4da6c75d59d0e1162b2f289582a111676e5bc)`
- 日期：2026-02-02
- 做了什么：新增或增强功能，主题是“dynamic title”。
- 影响范围：主要涉及 前端。
- 改动规模：+51 / -2 行。
- 关键文件：frontend/src/app/layout.tsx；frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/app/workspace/chats/page.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts；frontend/src/core/i18n/locales/zh-CN.ts。

#### 203. feat: use `create skill` as title

- 提交：`[b540ad4](https://github.com/bytedance/deer-flow/commit/b540ad45052da2449482010095cdd8eebaf61fdd)`
- 日期：2026-02-02
- 做了什么：新增或增强功能，主题是“use `create skill` as title”。
- 影响范围：主要涉及 前端。
- 改动规模：+8 / -1 行。
- 关键文件：frontend/src/components/workspace/welcome.tsx。

#### 204. feat: use `create skill` as title

- 提交：`[dc1190b](https://github.com/bytedance/deer-flow/commit/dc1190b228e679ada786d20584fecb2fa31174d5)`
- 日期：2026-02-02
- 做了什么：新增或增强功能，主题是“use `create skill` as title”。
- 影响范围：主要涉及 前端。
- 改动规模：+8 / -1 行。
- 关键文件：frontend/src/components/workspace/welcome.tsx。

#### 205. feat: use `create skill` as title

- 提交：`[b50fbf8](https://github.com/bytedance/deer-flow/commit/b50fbf83d0b1570eae77c0e58531b9f177adf694)`
- 日期：2026-02-02
- 做了什么：新增或增强功能，主题是“use `create skill` as title”。
- 影响范围：主要涉及 前端。
- 改动规模：+8 / -1 行。
- 关键文件：frontend/src/components/workspace/welcome.tsx。

#### 206. feat: add find-skills skill for discovering agent skills

- 提交：`[f082ef3](https://github.com/bytedance/deer-flow/commit/f082ef3d87903ba078a36c7cc524d5a362a211ad)`
- 日期：2026-02-01
- 做了什么：新增或增强功能，主题是“add find-skills skill for discovering agent skills”。
- 影响范围：主要涉及 技能体系。
- 改动规模：+200 / -0 行。
- 关键文件：skills/public/find-skills/SKILL.md；skills/public/find-skills/scripts/install-skill.sh。

#### 207. feat: add find-skills skill for discovering agent skills

- 提交：`[e493921](https://github.com/bytedance/deer-flow/commit/e4939216fd8261d3773e6898276a5afc7c9cfac0)`
- 日期：2026-02-01
- 做了什么：新增或增强功能，主题是“add find-skills skill for discovering agent skills”。
- 影响范围：主要涉及 技能体系。
- 改动规模：+200 / -0 行。
- 关键文件：skills/public/find-skills/SKILL.md；skills/public/find-skills/scripts/install-skill.sh。

#### 208. feat: add find-skills skill for discovering agent skills

- 提交：`[7fd5ba2](https://github.com/bytedance/deer-flow/commit/7fd5ba258d0ce585da05aad8cd78ae15b962bc86)`
- 日期：2026-02-01
- 做了什么：新增或增强功能，主题是“add find-skills skill for discovering agent skills”。
- 影响范围：主要涉及 技能体系。
- 改动规模：+200 / -0 行。
- 关键文件：skills/public/find-skills/SKILL.md；skills/public/find-skills/scripts/install-skill.sh。

#### 209. docs: add comprehensive backend documentation

- 提交：`[9043c96](https://github.com/bytedance/deer-flow/commit/9043c964cac4267aaa2bf59c6f8779cfd4ab3d33)`
- 日期：2026-02-01
- 做了什么：补充文档能力，主题是“add comprehensive backend documentation”。
- 影响范围：主要涉及 后端。
- 改动规模：+1966 / -57 行。
- 关键文件：backend/CLAUDE.md；backend/CONTRIBUTING.md；backend/README.md；backend/docs/API.md；backend/docs/ARCHITECTURE.md；backend/docs/README.md；backend/docs/TODO.md；backend/pyproject.toml。

#### 210. docs: add comprehensive backend documentation

- 提交：`[68c3e33](https://github.com/bytedance/deer-flow/commit/68c3e3341a74f17d67efcf7d77b4938acf6d2c84)`
- 日期：2026-02-01
- 做了什么：补充文档能力，主题是“add comprehensive backend documentation”。
- 影响范围：主要涉及 后端。
- 改动规模：+1966 / -57 行。
- 关键文件：backend/CLAUDE.md；backend/CONTRIBUTING.md；backend/README.md；backend/docs/API.md；backend/docs/ARCHITECTURE.md；backend/docs/README.md；backend/docs/TODO.md；backend/pyproject.toml。

#### 211. docs: add comprehensive backend documentation

- 提交：`[4f4b7cd](https://github.com/bytedance/deer-flow/commit/4f4b7cde2e6efc5a2dc19227be0ec165eef0b1e7)`
- 日期：2026-02-01
- 做了什么：补充文档能力，主题是“add comprehensive backend documentation”。
- 影响范围：主要涉及 后端。
- 改动规模：+1966 / -57 行。
- 关键文件：backend/CLAUDE.md；backend/CONTRIBUTING.md；backend/README.md；backend/docs/API.md；backend/docs/ARCHITECTURE.md；backend/docs/README.md；backend/docs/TODO.md；backend/pyproject.toml。

#### 212. feat: update skills

- 提交：`[9b77070](https://github.com/bytedance/deer-flow/commit/9b770704067659ff5f615ef4ebb5b7105479ebda)`
- 日期：2026-02-01
- 做了什么：新增或增强功能，主题是“update skills”。
- 影响范围：主要涉及 前端。
- 改动规模：+35 / -19 行。
- 关键文件：frontend/src/app/mock/api/skills/route.ts。

#### 213. feat: update skills

- 提交：`[7e11f28](https://github.com/bytedance/deer-flow/commit/7e11f28d55eb6d0cdafcef55e2fb5975d62cae25)`
- 日期：2026-02-01
- 做了什么：新增或增强功能，主题是“update skills”。
- 影响范围：主要涉及 前端。
- 改动规模：+35 / -19 行。
- 关键文件：frontend/src/app/mock/api/skills/route.ts。

#### 214. feat: update skills

- 提交：`[890a837](https://github.com/bytedance/deer-flow/commit/890a8379ce4327d2974df554607f3419f9140e5f)`
- 日期：2026-02-01
- 做了什么：新增或增强功能，主题是“update skills”。
- 影响范围：主要涉及 前端。
- 改动规模：+35 / -19 行。
- 关键文件：frontend/src/app/mock/api/skills/route.ts。

#### 215. feat: add new demo

- 提交：`[22ef5fb](https://github.com/bytedance/deer-flow/commit/22ef5fb5ba069b96f6f23b3237ad057acd692e02)`
- 日期：2026-02-01
- 做了什么：新增或增强功能，主题是“add new demo”。
- 影响范围：主要涉及 前端。
- 改动规模：+3255 / -0 行。
- 关键文件：frontend/public/demo/threads/fe3f7974-1bcb-4a01-a950-79673baafefd/thread.json；frontend/public/demo/threads/fe3f7974-1bcb-4a01-a950-79673baafefd/user-data/outputs/index.html；frontend/public/demo/threads/fe3f7974-1bcb-4a01-a950-79673baafefd/user-data/outputs/research_deerflow_20260201.md。

#### 216. feat: add new demo

- 提交：`[d131a49](https://github.com/bytedance/deer-flow/commit/d131a497d70ae58bcc17d96e0db794c175d614f7)`
- 日期：2026-02-01
- 做了什么：新增或增强功能，主题是“add new demo”。
- 影响范围：主要涉及 前端。
- 改动规模：+3255 / -0 行。
- 关键文件：frontend/public/demo/threads/fe3f7974-1bcb-4a01-a950-79673baafefd/thread.json；frontend/public/demo/threads/fe3f7974-1bcb-4a01-a950-79673baafefd/user-data/outputs/index.html；frontend/public/demo/threads/fe3f7974-1bcb-4a01-a950-79673baafefd/user-data/outputs/research_deerflow_20260201.md。

#### 217. feat: add new demo

- 提交：`[88e1c7c](https://github.com/bytedance/deer-flow/commit/88e1c7c0b35fe985c16af54b8847b67127aad002)`
- 日期：2026-02-01
- 做了什么：新增或增强功能，主题是“add new demo”。
- 影响范围：主要涉及 前端。
- 改动规模：+3255 / -0 行。
- 关键文件：frontend/public/demo/threads/fe3f7974-1bcb-4a01-a950-79673baafefd/thread.json；frontend/public/demo/threads/fe3f7974-1bcb-4a01-a950-79673baafefd/user-data/outputs/index.html；frontend/public/demo/threads/fe3f7974-1bcb-4a01-a950-79673baafefd/user-data/outputs/research_deerflow_20260201.md。

#### 218. feat: update github-deep-research skill

- 提交：`[f206a57](https://github.com/bytedance/deer-flow/commit/f206a574c5bc3238919d698961ecb12dc0fcc793)`
- 日期：2026-02-01
- 做了什么：新增或增强功能，主题是“update github-deep-research skill”。
- 影响范围：主要涉及 技能体系。
- 改动规模：+39 / -39 行。
- 关键文件：skills/public/github-deep-research/SKILL.md；skills/public/github-deep-research/assets/report_template.md。

#### 219. feat: update github-deep-research skill

- 提交：`[8c37c9c](https://github.com/bytedance/deer-flow/commit/8c37c9c7554a565e11023646e6f7633dac509785)`
- 日期：2026-02-01
- 做了什么：新增或增强功能，主题是“update github-deep-research skill”。
- 影响范围：主要涉及 技能体系。
- 改动规模：+39 / -39 行。
- 关键文件：skills/public/github-deep-research/SKILL.md；skills/public/github-deep-research/assets/report_template.md。

#### 220. feat: update github-deep-research skill

- 提交：`[f656fd0](https://github.com/bytedance/deer-flow/commit/f656fd076893acb312e21dd45d834344f473d526)`
- 日期：2026-02-01
- 做了什么：新增或增强功能，主题是“update github-deep-research skill”。
- 影响范围：主要涉及 技能体系。
- 改动规模：+39 / -39 行。
- 关键文件：skills/public/github-deep-research/SKILL.md；skills/public/github-deep-research/assets/report_template.md。

#### 221. feat: add tooltip for installation

- 提交：`[e1ecf62](https://github.com/bytedance/deer-flow/commit/e1ecf62afa0b18120fae771fdc8a2e05da841019)`
- 日期：2026-02-01
- 做了什么：新增或增强功能，主题是“add tooltip for installation”。
- 影响范围：主要涉及 前端。
- 改动规模：+19 / -8 行。
- 关键文件：frontend/src/components/workspace/artifacts/artifact-file-detail.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts；frontend/src/core/i18n/locales/zh-CN.ts。

#### 222. feat: add tooltip for installation

- 提交：`[4721f1a](https://github.com/bytedance/deer-flow/commit/4721f1a890e24a1803079a41a287fb11d0ef6415)`
- 日期：2026-02-01
- 做了什么：新增或增强功能，主题是“add tooltip for installation”。
- 影响范围：主要涉及 前端。
- 改动规模：+19 / -8 行。
- 关键文件：frontend/src/components/workspace/artifacts/artifact-file-detail.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts；frontend/src/core/i18n/locales/zh-CN.ts。

#### 223. feat: add tooltip for installation

- 提交：`[a126787](https://github.com/bytedance/deer-flow/commit/a1267875fac97c8397794ac952b5b62faf1a31eb)`
- 日期：2026-02-01
- 做了什么：新增或增强功能，主题是“add tooltip for installation”。
- 影响范围：主要涉及 前端。
- 改动规模：+19 / -8 行。
- 关键文件：frontend/src/components/workspace/artifacts/artifact-file-detail.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts；frontend/src/core/i18n/locales/zh-CN.ts。

#### 224. feat: add github-deep-research skill

- 提交：`[46feff6](https://github.com/bytedance/deer-flow/commit/46feff6c16ecda1e4a0219ba5aac3b0fa59264af)`
- 日期：2026-02-01
- 做了什么：新增或增强功能，主题是“add github-deep-research skill”。
- 影响范围：主要涉及 技能体系。
- 改动规模：+666 / -0 行。
- 关键文件：skills/public/github-deep-research/SKILL.md；skills/public/github-deep-research/assets/report_template.md；skills/public/github-deep-research/scripts/github_api.py。

#### 225. feat: add github-deep-research skill

- 提交：`[16122dd](https://github.com/bytedance/deer-flow/commit/16122dd92d599b8077395ddc0724f74dd765a3c5)`
- 日期：2026-02-01
- 做了什么：新增或增强功能，主题是“add github-deep-research skill”。
- 影响范围：主要涉及 技能体系。
- 改动规模：+666 / -0 行。
- 关键文件：skills/public/github-deep-research/SKILL.md；skills/public/github-deep-research/assets/report_template.md；skills/public/github-deep-research/scripts/github_api.py。

#### 226. feat: add github-deep-research skill

- 提交：`[469e044](https://github.com/bytedance/deer-flow/commit/469e0449350c8c00408caf4cc26f127447ab6df3)`
- 日期：2026-02-01
- 做了什么：新增或增强功能，主题是“add github-deep-research skill”。
- 影响范围：主要涉及 技能体系。
- 改动规模：+666 / -0 行。
- 关键文件：skills/public/github-deep-research/SKILL.md；skills/public/github-deep-research/assets/report_template.md；skills/public/github-deep-research/scripts/github_api.py。

### Bug 修复

#### 1. fix(git):add .gitattributes to avoid 'bash\r' issue (#924)

- 提交：`[5ad8a65](https://github.com/bytedance/deer-flow/commit/5ad8a657f49fbbae296713d20a85fe5aadbf66d5)`
- 日期：2026-02-28
- 做了什么：修复缺陷或回归问题，主题是“add .gitattributes to avoid 'bash\r' issue (#924)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+43 / -0 行。
- 关键文件：.gitattributes。

#### 2. fix(i18n): normalize locale and prevent undefined translations (#914)

- 提交：`[e9adaab](https://github.com/bytedance/deer-flow/commit/e9adaab7a63482e62a288ed7fb72500aba7ccacb)`
- 日期：2026-02-27
- 做了什么：修复缺陷或回归问题，主题是“normalize locale and prevent undefined translations (#914)”。
- 影响范围：主要涉及 前端。
- 改动规模：+81 / -32 行。
- 关键文件：frontend/src/components/workspace/settings/appearance-settings-page.tsx；frontend/src/core/i18n/hooks.ts；frontend/src/core/i18n/index.ts；frontend/src/core/i18n/locale.ts；frontend/src/core/i18n/server.ts。

#### 3. fix: recover from stale model context when configured models change (#898)

- 提交：`[6a55860](https://github.com/bytedance/deer-flow/commit/6a55860a1588db4cb8f5ba463d278861ed73d65f)`
- 日期：2026-02-26
- 做了什么：修复缺陷或回归问题，主题是“recover from stale model context when configured models change (#898)”。
- 影响范围：主要涉及 后端、前端。
- 改动规模：+243 / -28 行。
- 关键文件：backend/src/agents/lead_agent/agent.py；backend/tests/test_lead_agent_model_resolution.py；frontend/src/components/workspace/input-box.tsx。

#### 4. fix(middleware): fix DanglingToolCallMiddleware inserting patches at wrong position (#904)

- 提交：`[d27a7a5](https://github.com/bytedance/deer-flow/commit/d27a7a5f54f01f4c96db517d57473bdd56261b13)`
- 日期：2026-02-25
- 做了什么：修复缺陷或回归问题，主题是“fix DanglingToolCallMiddleware inserting patches at wrong position (#904)”。
- 影响范围：主要涉及 后端。
- 改动规模：+62 / -26 行。
- 关键文件：backend/src/agents/middlewares/dangling_tool_call_middleware.py。

#### 5. fix(skill): enhance data authenticity protocols and clarify reporting guidelines (#905)

- 提交：`[33595f0](https://github.com/bytedance/deer-flow/commit/33595f0bac29df1c4ce20a28762504abd4dcb80d)`
- 日期：2026-02-25
- 做了什么：修复缺陷或回归问题，主题是“enhance data authenticity protocols and clarify reporting guidelines (#905)”。
- 影响范围：主要涉及 技能体系。
- 改动规模：+13 / -2 行。
- 关键文件：skills/public/consulting-analysis/SKILL.md。

#### 6. fix(docker): update nginx configuration and simplify docker script (#903)

- 提交：`[3a7251c](https://github.com/bytedance/deer-flow/commit/3a7251c95ea5bf97dfbb3db1b4959cd930ebd2a0)`
- 日期：2026-02-25
- 做了什么：修复缺陷或回归问题，主题是“update nginx configuration and simplify docker script (#903)”。
- 影响范围：主要涉及 容器部署、脚本工具。
- 改动规模：+6 / -10 行。
- 关键文件：docker/docker-compose-dev.yaml；docker/nginx/nginx.conf；scripts/docker.sh。

#### 7. fix(sandbox):deer-flow-provisioner container fails to start in local execution mode (#889)

- 提交：`[03705ac](https://github.com/bytedance/deer-flow/commit/03705acf3a116e24251d2d6a8a92d1fbd7d77ca7)`
- 日期：2026-02-24
- 做了什么：修复缺陷或回归问题，主题是“deer-flow-provisioner container fails to start in local execution mode (#889)”。
- 影响范围：主要涉及 后端、容器部署、其他模块。
- 改动规模：+452 / -52 行。
- 关键文件：.github/workflows/backend-unit-tests.yml；CONTRIBUTING.md；Makefile；README.md；backend/CLAUDE.md；backend/docs/CONFIGURATION.md；backend/tests/test_docker_sandbox_mode_detection.py；backend/tests/test_provisioner_kubeconfig.py。

#### 8. fix: HTML artifact preview renders blank in preview mode (#876)

- 提交：`[9f74589](https://github.com/bytedance/deer-flow/commit/9f74589d09f08aa29778f4eb46d18c0869558fc1)`
- 日期：2026-02-18
- 做了什么：修复缺陷或回归问题，主题是“HTML artifact preview renders blank in preview mode (#876)”。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -2 行。
- 关键文件：frontend/src/components/workspace/artifacts/artifact-file-detail.tsx。

#### 9. fix: use /tmp/nginx.pid to avoid permission denied errors (#877)

- 提交：`[67dbb10](https://github.com/bytedance/deer-flow/commit/67dbb10c2a4c2cc2fac22d7827f936f9148e8de0)`
- 日期：2026-02-18
- 做了什么：修复缺陷或回归问题，主题是“use /tmp/nginx.pid to avoid permission denied errors (#877)”。
- 影响范围：主要涉及 容器部署。
- 改动规模：+2 / -2 行。
- 关键文件：docker/nginx/nginx.conf；docker/nginx/nginx.local.conf。

#### 10. fix: move Key Citations to early position in reporter prompt to reduce URL hallucination (#859)

- 提交：`[13a2511](https://github.com/bytedance/deer-flow/commit/13a25112b1cb858aa56e2d77c385a28ff95f83ea)`
- 日期：2026-02-14
- 做了什么：修复缺陷或回归问题，主题是“move Key Citations to early position in reporter prompt to reduce URL hallucination (#859)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+31 / -17 行。
- 关键文件：src/graph/nodes.py；src/prompts/reporter.md。

#### 11. security: patch orjson DoS and harden container/frontend (#852)

- 提交：`[ba45c1a](https://github.com/bytedance/deer-flow/commit/ba45c1a3a9fb3ead7809bf08976d1305185b4fe6)`
- 日期：2026-02-13
- 做了什么：修复缺陷或回归问题，主题是“security: patch orjson DoS and harden container/frontend (#852)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+59 / -37 行。
- 关键文件：Dockerfile；pyproject.toml；uv.lock；web/src/components/deer-flow/message-input.tsx。

#### 12. fix: 修复新建技能后输入框无法编辑的问题

- 提交：`[b3a1f01](https://github.com/bytedance/deer-flow/commit/b3a1f018ab56626accb8d8f993f0d6087fe2faa8)`
- 日期：2026-02-10
- 做了什么：修复缺陷或回归问题，主题是“修复新建技能后输入框无法编辑的问题”。
- 影响范围：主要涉及 前端。
- 改动规模：+8 / -4 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx。

#### 13. fix:memory 为空时i18n字体显示

- 提交：`[cc88823](https://github.com/bytedance/deer-flow/commit/cc88823a64d74d063dcf4cbdf3861f4e31e0a255)`
- 日期：2026-02-10
- 做了什么：修复缺陷或回归问题，主题是“memory 为空时i18n字体显示”。
- 影响范围：主要涉及 前端。
- 改动规模：+2 / -2 行。
- 关键文件：frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/zh-CN.ts。

#### 14. fix: citations prompt

- 提交：`[6109216](https://github.com/bytedance/deer-flow/commit/6109216d54b7816556725f2e8e3564653fd15122)`
- 日期：2026-02-10
- 做了什么：修复缺陷或回归问题，主题是“citations prompt”。
- 影响范围：主要涉及 后端。
- 改动规模：+9 / -1 行。
- 关键文件：backend/src/agents/lead_agent/prompt.py。

#### 15. fix: eslint

- 提交：`[13b3032](https://github.com/bytedance/deer-flow/commit/13b3032d02a4071febde3248544f984247ea7fd0)`
- 日期：2026-02-09
- 做了什么：修复缺陷或回归问题，主题是“eslint”。
- 影响范围：主要涉及 前端。
- 改动规模：+2 / -1 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx。

#### 16. fix: eslint

- 提交：`[df3668e](https://github.com/bytedance/deer-flow/commit/df3668ecd50eacdd8f59d801522ab650608ab3f2)`
- 日期：2026-02-09
- 做了什么：修复缺陷或回归问题，主题是“eslint”。
- 影响范围：主要涉及 前端。
- 改动规模：+2 / -1 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx。

#### 17. fix: Add None check for db_uri in ChatStreamManager (#854)

- 提交：`[7607e14](https://github.com/bytedance/deer-flow/commit/7607e140884554f8dc3a3000035403f638033edd)`
- 日期：2026-02-09
- 做了什么：修复缺陷或回归问题，主题是“Add None check for db_uri in ChatStreamManager (#854)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+6 / -1 行。
- 关键文件：src/graph/checkpoint.py。

#### 18. fix(frontend): no half-finished citations, correct state when SSE ends

- 提交：`[d9a86c1](https://github.com/bytedance/deer-flow/commit/d9a86c10e88ef7f066aa2ba4c0c280274e53e9e8)`
- 日期：2026-02-09
- 做了什么：修复缺陷或回归问题，主题是“no half-finished citations, correct state when SSE ends”。
- 影响范围：主要涉及 前端、其他模块。
- 改动规模：+25 / -37 行。
- 关键文件：.githooks/pre-commit；.gitignore；frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/workspace/messages/message-list.tsx；frontend/src/core/citations/utils.ts。

#### 19. fix(frontend): no half-finished citations, correct state when SSE ends

- 提交：`[53509ea](https://github.com/bytedance/deer-flow/commit/53509eaeb1a728e330d07da5f62baa58982fcbda)`
- 日期：2026-02-09
- 做了什么：修复缺陷或回归问题，主题是“no half-finished citations, correct state when SSE ends”。
- 影响范围：主要涉及 前端、其他模块。
- 改动规模：+25 / -37 行。
- 关键文件：.githooks/pre-commit；.gitignore；frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/workspace/messages/message-list.tsx；frontend/src/core/citations/utils.ts。

#### 20. fix(frontend): citations display + refactor link/citation utils

- 提交：`[2d70aaa](https://github.com/bytedance/deer-flow/commit/2d70aaa969dc575d448911b4dd836387b2fc2588)`
- 日期：2026-02-09
- 做了什么：修复缺陷或回归问题，主题是“citations display + refactor link/citation utils”。
- 影响范围：主要涉及 前端。
- 改动规模：+69 / -19 行。
- 关键文件：frontend/src/components/workspace/artifacts/artifact-file-detail.tsx；frontend/src/components/workspace/messages/message-list-item.tsx；frontend/src/core/citations/index.ts；frontend/src/core/citations/utils.ts；frontend/src/lib/utils.ts。

#### 21. fix(frontend): citations display + refactor link/citation utils

- 提交：`[509ea87](https://github.com/bytedance/deer-flow/commit/509ea874f778d28092c518f3235ab5e858e0876d)`
- 日期：2026-02-09
- 做了什么：修复缺陷或回归问题，主题是“citations display + refactor link/citation utils”。
- 影响范围：主要涉及 前端。
- 改动规模：+69 / -19 行。
- 关键文件：frontend/src/components/workspace/artifacts/artifact-file-detail.tsx；frontend/src/components/workspace/messages/message-list-item.tsx；frontend/src/core/citations/index.ts；frontend/src/core/citations/utils.ts；frontend/src/lib/utils.ts。

#### 22. fix(frontend): build + remove hover tooltips in step links

- 提交：`[d72aad8](https://github.com/bytedance/deer-flow/commit/d72aad806347c501794faf3126fb6792278542df)`
- 日期：2026-02-09
- 做了什么：修复缺陷或回归问题，主题是“build + remove hover tooltips in step links”。
- 影响范围：主要涉及 前端。
- 改动规模：+82 / -53 行。
- 关键文件：frontend/next.config.js；frontend/package.json；frontend/src/components/workspace/messages/message-group.tsx；frontend/src/components/workspace/settings/about-content.ts；frontend/src/components/workspace/settings/about-settings-page.tsx。

#### 23. fix(frontend): build + remove hover tooltips in step links

- 提交：`[8cb14ad](https://github.com/bytedance/deer-flow/commit/8cb14ad4fb2dd71130b19c2a89b9e969d7e54609)`
- 日期：2026-02-09
- 做了什么：修复缺陷或回归问题，主题是“build + remove hover tooltips in step links”。
- 影响范围：主要涉及 前端。
- 改动规模：+82 / -53 行。
- 关键文件：frontend/next.config.js；frontend/package.json；frontend/src/components/workspace/messages/message-group.tsx；frontend/src/components/workspace/settings/about-content.ts；frontend/src/components/workspace/settings/about-settings-page.tsx。

#### 24. Revert "fix(frontend): Turbopack about page + remove hover on web search/citations"

- 提交：`[fe06be8](https://github.com/bytedance/deer-flow/commit/fe06be825801bf3f747fff0436c376e359a0b355)`
- 日期：2026-02-09
- 做了什么：修复缺陷或回归问题，主题是“Revert "fix(frontend): Turbopack about page + remove hover on web search/citations"”。
- 影响范围：主要涉及 前端。
- 改动规模：+51 / -79 行。
- 关键文件：frontend/src/components/ai-elements/inline-citation.tsx；frontend/src/components/workspace/messages/message-group.tsx；frontend/src/components/workspace/settings/about-content.ts；frontend/src/components/workspace/settings/about-settings-page.tsx。

#### 25. Revert "fix(frontend): Turbopack about page + remove hover on web search/citations"

- 提交：`[f577ff1](https://github.com/bytedance/deer-flow/commit/f577ff115bc3f2dbb84e2eeff9ab1f3b45103b2d)`
- 日期：2026-02-09
- 做了什么：修复缺陷或回归问题，主题是“Revert "fix(frontend): Turbopack about page + remove hover on web search/citations"”。
- 影响范围：主要涉及 前端。
- 改动规模：+51 / -79 行。
- 关键文件：frontend/src/components/ai-elements/inline-citation.tsx；frontend/src/components/workspace/messages/message-group.tsx；frontend/src/components/workspace/settings/about-content.ts；frontend/src/components/workspace/settings/about-settings-page.tsx。

#### 26. fix(frontend): Turbopack about page + remove hover on web search/citations

- 提交：`[842c4ec](https://github.com/bytedance/deer-flow/commit/842c4ecac0806359cba55fda80f22f926d905782)`
- 日期：2026-02-09
- 做了什么：修复缺陷或回归问题，主题是“Turbopack about page + remove hover on web search/citations”。
- 影响范围：主要涉及 前端。
- 改动规模：+79 / -51 行。
- 关键文件：frontend/src/components/ai-elements/inline-citation.tsx；frontend/src/components/workspace/messages/message-group.tsx；frontend/src/components/workspace/settings/about-content.ts；frontend/src/components/workspace/settings/about-settings-page.tsx。

#### 27. fix(frontend): Turbopack about page + remove hover on web search/citations

- 提交：`[77859d0](https://github.com/bytedance/deer-flow/commit/77859d01b824f08fd464d0b6cbab4ff2d79da6d9)`
- 日期：2026-02-09
- 做了什么：修复缺陷或回归问题，主题是“Turbopack about page + remove hover on web search/citations”。
- 影响范围：主要涉及 前端。
- 改动规模：+79 / -51 行。
- 关键文件：frontend/src/components/ai-elements/inline-citation.tsx；frontend/src/components/workspace/messages/message-group.tsx；frontend/src/components/workspace/settings/about-content.ts；frontend/src/components/workspace/settings/about-settings-page.tsx。

#### 28. fix: fix sub agent timeout

- 提交：`[17365e4](https://github.com/bytedance/deer-flow/commit/17365e40d53363815b2aa547120d831cea9e5e4f)`
- 日期：2026-02-08
- 做了什么：修复缺陷或回归问题，主题是“fix sub agent timeout”。
- 影响范围：主要涉及 后端。
- 改动规模：+15 / -8 行。
- 关键文件：backend/src/subagents/config.py；backend/src/subagents/executor.py；backend/src/tools/builtins/task_tool.py。

#### 29. fix: fix sub agent timeout

- 提交：`[19a1d03](https://github.com/bytedance/deer-flow/commit/19a1d03fc881afc4d78e2f45990bf52e79896e1a)`
- 日期：2026-02-08
- 做了什么：修复缺陷或回归问题，主题是“fix sub agent timeout”。
- 影响范围：主要涉及 后端。
- 改动规模：+15 / -8 行。
- 关键文件：backend/src/subagents/config.py；backend/src/subagents/executor.py；backend/src/tools/builtins/task_tool.py。

#### 30. fix: fix sub agent timeout

- 提交：`[f01c470](https://github.com/bytedance/deer-flow/commit/f01c470e64279b8fe5c6e30df3c937fa4d7774ba)`
- 日期：2026-02-08
- 做了什么：修复缺陷或回归问题，主题是“fix sub agent timeout”。
- 影响范围：主要涉及 后端。
- 改动规模：+15 / -8 行。
- 关键文件：backend/src/subagents/config.py；backend/src/subagents/executor.py；backend/src/tools/builtins/task_tool.py。

#### 31. docs: fix typo and grammar in readme (#851)

- 提交：`[5b29c9f](https://github.com/bytedance/deer-flow/commit/5b29c9f70a5d5e6c782412115e6b218784743f04)`
- 日期：2026-02-08
- 做了什么：修复缺陷或回归问题，主题是“fix typo and grammar in readme (#851)”。
- 影响范围：主要涉及 文档。
- 改动规模：+11 / -11 行。
- 关键文件：README.md。

#### 32. fix: adjust suggestion positioning and height for improved UI layout

- 提交：`[b135449](https://github.com/bytedance/deer-flow/commit/b135449c078d201974412e73ee51d79f6d7c8e12)`
- 日期：2026-02-07
- 做了什么：修复缺陷或回归问题，主题是“adjust suggestion positioning and height for improved UI layout”。
- 影响范围：主要涉及 前端。
- 改动规模：+3 / -3 行。
- 关键文件：frontend/src/components/ai-elements/suggestion.tsx；frontend/src/components/workspace/input-box.tsx。

#### 33. fix: adjust suggestion positioning and height for improved UI layout

- 提交：`[2510991](https://github.com/bytedance/deer-flow/commit/2510991698af7b66db4beb8f1d7bfa6de15684a2)`
- 日期：2026-02-07
- 做了什么：修复缺陷或回归问题，主题是“adjust suggestion positioning and height for improved UI layout”。
- 影响范围：主要涉及 前端。
- 改动规模：+3 / -3 行。
- 关键文件：frontend/src/components/ai-elements/suggestion.tsx；frontend/src/components/workspace/input-box.tsx。

#### 34. fix: adjust suggestion positioning and height for improved UI layout

- 提交：`[17b2630](https://github.com/bytedance/deer-flow/commit/17b2630b738bc4566d13abba7d493b623fc94036)`
- 日期：2026-02-07
- 做了什么：修复缺陷或回归问题，主题是“adjust suggestion positioning and height for improved UI layout”。
- 影响范围：主要涉及 前端。
- 改动规模：+3 / -3 行。
- 关键文件：frontend/src/components/ai-elements/suggestion.tsx；frontend/src/components/workspace/input-box.tsx。

#### 35. fix(server): graceful stream termination on cancellation (issue #847) (#850)

- 提交：`[f21bc6b](https://github.com/bytedance/deer-flow/commit/f21bc6b83f307a0e9aec04f3ce0f705d1fc22ecd)`
- 日期：2026-02-06
- 做了什么：修复缺陷或回归问题，主题是“graceful stream termination on cancellation (issue #847) (#850)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+91 / -9 行。
- 关键文件：src/server/app.py；tests/unit/server/test_app.py；web/src/core/api/chat.ts；web/src/core/api/types.ts；web/src/core/messages/merge-message.ts；web/src/core/store/store.ts。

#### 36. fix: fix markdown table

- 提交：`[5ed15d7](https://github.com/bytedance/deer-flow/commit/5ed15d79c980af550f350dfa661d7fd10518d8aa)`
- 日期：2026-02-06
- 做了什么：修复缺陷或回归问题，主题是“fix markdown table”。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -6 行。
- 关键文件：frontend/src/components/workspace/messages/message-list-item.tsx。

#### 37. fix: fix markdown table

- 提交：`[8f1a42a](https://github.com/bytedance/deer-flow/commit/8f1a42a8e000333e7486e2200cb4dd2e627e380d)`
- 日期：2026-02-06
- 做了什么：修复缺陷或回归问题，主题是“fix markdown table”。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -6 行。
- 关键文件：frontend/src/components/workspace/messages/message-list-item.tsx。

#### 38. fix: fix markdown table

- 提交：`[c3f9089](https://github.com/bytedance/deer-flow/commit/c3f9089e9547131485045b69ca7257776e717d21)`
- 日期：2026-02-06
- 做了什么：修复缺陷或回归问题，主题是“fix markdown table”。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -6 行。
- 关键文件：frontend/src/components/workspace/messages/message-list-item.tsx。

#### 39. Merge pull request #24 from LofiSu/fix/upload-files-alignment

- 提交：`[6b56e68](https://github.com/bytedance/deer-flow/commit/6b56e68ff2ebdf1a9d303ce55714f06ff4507426)`
- 日期：2026-02-06
- 做了什么：修复缺陷或回归问题，主题是“Merge pull request #24 from LofiSu/fix/upload-files-alignment”。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -1 行。
- 关键文件：frontend/src/components/workspace/messages/message-list-item.tsx。

#### 40. Merge pull request #24 from LofiSu/fix/upload-files-alignment

- 提交：`[537687c](https://github.com/bytedance/deer-flow/commit/537687c2c55ef9746210aa8f689a00ac5159c046)`
- 日期：2026-02-06
- 做了什么：修复缺陷或回归问题，主题是“Merge pull request #24 from LofiSu/fix/upload-files-alignment”。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -1 行。
- 关键文件：frontend/src/components/workspace/messages/message-list-item.tsx。

#### 41. Merge pull request #24 from LofiSu/fix/upload-files-alignment

- 提交：`[5016a5f](https://github.com/bytedance/deer-flow/commit/5016a5f7d9ecde3b35aed6955e8c15c69aca778b)`
- 日期：2026-02-06
- 做了什么：修复缺陷或回归问题，主题是“Merge pull request #24 from LofiSu/fix/upload-files-alignment”。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -1 行。
- 关键文件：frontend/src/components/workspace/messages/message-list-item.tsx。

#### 42. fix: fix subagent prompt

- 提交：`[9e4f251](https://github.com/bytedance/deer-flow/commit/9e4f2512f3e76fe806bd2686022496440f260374)`
- 日期：2026-02-06
- 做了什么：修复缺陷或回归问题，主题是“fix subagent prompt”。
- 影响范围：主要涉及 后端。
- 改动规模：+120 / -28 行。
- 关键文件：backend/src/agents/lead_agent/prompt.py。

#### 43. fix: fix subagent prompt

- 提交：`[a423dfb](https://github.com/bytedance/deer-flow/commit/a423dfb9fd5efc520f7233944cd3cd9a7cd64951)`
- 日期：2026-02-06
- 做了什么：修复缺陷或回归问题，主题是“fix subagent prompt”。
- 影响范围：主要涉及 后端。
- 改动规模：+120 / -28 行。
- 关键文件：backend/src/agents/lead_agent/prompt.py。

#### 44. fix: fix subagent prompt

- 提交：`[d1d275b](https://github.com/bytedance/deer-flow/commit/d1d275bb810dc6f39c2cacc175768f0da11d75cf)`
- 日期：2026-02-06
- 做了什么：修复缺陷或回归问题，主题是“fix subagent prompt”。
- 影响范围：主要涉及 后端。
- 改动规模：+120 / -28 行。
- 关键文件：backend/src/agents/lead_agent/prompt.py。

#### 45. fix(citations): hide citations block in reasoning/thinking content

- 提交：`[5484233](https://github.com/bytedance/deer-flow/commit/548423354847bcf9917bc924c949cd9e65a51abd)`
- 日期：2026-02-06
- 做了什么：修复缺陷或回归问题，主题是“hide citations block in reasoning/thinking content”。
- 影响范围：主要涉及 前端。
- 改动规模：+2 / -2 行。
- 关键文件：frontend/src/components/workspace/messages/message-group.tsx。

#### 46. fix(citations): hide citations block in reasoning/thinking content

- 提交：`[ca6bcaa](https://github.com/bytedance/deer-flow/commit/ca6bcaa31cd7fa1dc273c1495d297b3c25f76808)`
- 日期：2026-02-06
- 做了什么：修复缺陷或回归问题，主题是“hide citations block in reasoning/thinking content”。
- 影响范围：主要涉及 前端。
- 改动规模：+2 / -2 行。
- 关键文件：frontend/src/components/workspace/messages/message-group.tsx。

#### 47. fix(citations): hide citations block in reasoning/thinking content

- 提交：`[50ced32](https://github.com/bytedance/deer-flow/commit/50ced3272229abe56026615f5a7a3c5ba0ea3781)`
- 日期：2026-02-06
- 做了什么：修复缺陷或回归问题，主题是“hide citations block in reasoning/thinking content”。
- 影响范围：主要涉及 前端。
- 改动规模：+2 / -2 行。
- 关键文件：frontend/src/components/workspace/messages/message-group.tsx。

#### 48. fix(citations): only citation links in citationMap render as badges

- 提交：`[582bfae](https://github.com/bytedance/deer-flow/commit/582bfaee39d44d6bfa781b3a97127a27a77c0d83)`
- 日期：2026-02-06
- 做了什么：修复缺陷或回归问题，主题是“only citation links in citationMap render as badges”。
- 影响范围：主要涉及 前端。
- 改动规模：+7 / -26 行。
- 关键文件：frontend/src/components/workspace/messages/message-list-item.tsx。

#### 49. fix(citations): only citation links in citationMap render as badges

- 提交：`[666b747](https://github.com/bytedance/deer-flow/commit/666b747b8ad14bad771fb4755016267ae55215c2)`
- 日期：2026-02-06
- 做了什么：修复缺陷或回归问题，主题是“only citation links in citationMap render as badges”。
- 影响范围：主要涉及 前端。
- 改动规模：+7 / -26 行。
- 关键文件：frontend/src/components/workspace/messages/message-list-item.tsx。

#### 50. fix(citations): only citation links in citationMap render as badges

- 提交：`[e8ee198](https://github.com/bytedance/deer-flow/commit/e8ee19821d43c046251a69c7ac1751bc0078e8ea)`
- 日期：2026-02-06
- 做了什么：修复缺陷或回归问题，主题是“only citation links in citationMap render as badges”。
- 影响范围：主要涉及 前端。
- 改动规模：+7 / -26 行。
- 关键文件：frontend/src/components/workspace/messages/message-list-item.tsx。

#### 51. fix(citations): render external links as badges during streaming

- 提交：`[e7ea0fc](https://github.com/bytedance/deer-flow/commit/e7ea0fc551aef069d136589f11382bbcab6486a9)`
- 日期：2026-02-06
- 做了什么：修复缺陷或回归问题，主题是“render external links as badges during streaming”。
- 影响范围：主要涉及 前端。
- 改动规模：+26 / -8 行。
- 关键文件：frontend/src/components/workspace/messages/message-list-item.tsx。

#### 52. fix(citations): render external links as badges during streaming

- 提交：`[697c683](https://github.com/bytedance/deer-flow/commit/697c683dfaf4badbe0818e44e30889f9729c78a4)`
- 日期：2026-02-06
- 做了什么：修复缺陷或回归问题，主题是“render external links as badges during streaming”。
- 影响范围：主要涉及 前端。
- 改动规模：+26 / -8 行。
- 关键文件：frontend/src/components/workspace/messages/message-list-item.tsx。

#### 53. fix(citations): render external links as badges during streaming

- 提交：`[e444817](https://github.com/bytedance/deer-flow/commit/e444817c5dca4e65afaeabf03a0a47263b40565c)`
- 日期：2026-02-06
- 做了什么：修复缺陷或回归问题，主题是“render external links as badges during streaming”。
- 影响范围：主要涉及 前端。
- 改动规模：+26 / -8 行。
- 关键文件：frontend/src/components/workspace/messages/message-list-item.tsx。

#### 54. fix(citations): parse citations in reasoning content

- 提交：`[f1c3f90](https://github.com/bytedance/deer-flow/commit/f1c3f908c92fdbda6a5194354ef407db1bc730e7)`
- 日期：2026-02-06
- 做了什么：修复缺陷或回归问题，主题是“parse citations in reasoning content”。
- 影响范围：主要涉及 前端。
- 改动规模：+4 / -2 行。
- 关键文件：frontend/src/components/workspace/messages/message-list-item.tsx。

#### 55. fix(citations): parse citations in reasoning content

- 提交：`[579dccb](https://github.com/bytedance/deer-flow/commit/579dccbdcec13c5622deadeb90f938d1dca8be3f)`
- 日期：2026-02-06
- 做了什么：修复缺陷或回归问题，主题是“parse citations in reasoning content”。
- 影响范围：主要涉及 前端。
- 改动规模：+4 / -2 行。
- 关键文件：frontend/src/components/workspace/messages/message-list-item.tsx。

#### 56. fix(citations): parse citations in reasoning content

- 提交：`[e9648b1](https://github.com/bytedance/deer-flow/commit/e9648b11cdf8b9e02542e7625538d6fb09eac446)`
- 日期：2026-02-06
- 做了什么：修复缺陷或回归问题，主题是“parse citations in reasoning content”。
- 影响范围：主要涉及 前端。
- 改动规模：+4 / -2 行。
- 关键文件：frontend/src/components/workspace/messages/message-list-item.tsx。

#### 57. fix(artifacts): only render citation badges for links in citationMap

- 提交：`[7c21d8f](https://github.com/bytedance/deer-flow/commit/7c21d8f3a69066ac4ad49ff8e13cc41780ceb1ea)`
- 日期：2026-02-06
- 做了什么：修复缺陷或回归问题，主题是“only render citation badges for links in citationMap”。
- 影响范围：主要涉及 前端。
- 改动规模：+8 / -13 行。
- 关键文件：frontend/src/components/workspace/artifacts/artifact-file-detail.tsx。

#### 58. fix(artifacts): only render citation badges for links in citationMap

- 提交：`[365e3f4](https://github.com/bytedance/deer-flow/commit/365e3f430478d462fa8caa4bd3cad416ecdbb6f8)`
- 日期：2026-02-06
- 做了什么：修复缺陷或回归问题，主题是“only render citation badges for links in citationMap”。
- 影响范围：主要涉及 前端。
- 改动规模：+8 / -13 行。
- 关键文件：frontend/src/components/workspace/artifacts/artifact-file-detail.tsx。

#### 59. fix(artifacts): only render citation badges for links in citationMap

- 提交：`[0cf8ba8](https://github.com/bytedance/deer-flow/commit/0cf8ba86d121fe43d18584ca9aa99ca949a26319)`
- 日期：2026-02-06
- 做了什么：修复缺陷或回归问题，主题是“only render citation badges for links in citationMap”。
- 影响范围：主要涉及 前端。
- 改动规模：+8 / -13 行。
- 关键文件：frontend/src/components/workspace/artifacts/artifact-file-detail.tsx。

#### 60. fix(citations): only render citation badges for links in citationMap

- 提交：`[5d8c08d](https://github.com/bytedance/deer-flow/commit/5d8c08d3ba105c5624f73a37769b48235e895f14)`
- 日期：2026-02-06
- 做了什么：修复缺陷或回归问题，主题是“only render citation badges for links in citationMap”。
- 影响范围：主要涉及 前端。
- 改动规模：+8 / -22 行。
- 关键文件：frontend/src/components/workspace/messages/message-list-item.tsx。

#### 61. fix(citations): only render citation badges for links in citationMap

- 提交：`[1ce154f](https://github.com/bytedance/deer-flow/commit/1ce154fa71c1264f319eb1c571664f17f284b57a)`
- 日期：2026-02-06
- 做了什么：修复缺陷或回归问题，主题是“only render citation badges for links in citationMap”。
- 影响范围：主要涉及 前端。
- 改动规模：+8 / -22 行。
- 关键文件：frontend/src/components/workspace/messages/message-list-item.tsx。

#### 62. fix(citations): only render citation badges for links in citationMap

- 提交：`[7a3a5f5](https://github.com/bytedance/deer-flow/commit/7a3a5f5196f8a792bb037f88e4390870f34f602d)`
- 日期：2026-02-06
- 做了什么：修复缺陷或回归问题，主题是“only render citation badges for links in citationMap”。
- 影响范围：主要涉及 前端。
- 改动规模：+8 / -22 行。
- 关键文件：frontend/src/components/workspace/messages/message-list-item.tsx。

#### 63. fix(citations): use markdown link text as fallback for display

- 提交：`[49f7cf1](https://github.com/bytedance/deer-flow/commit/49f7cf16621b5586f46478111e3b198c488744a3)`
- 日期：2026-02-06
- 做了什么：修复缺陷或回归问题，主题是“use markdown link text as fallback for display”。
- 影响范围：主要涉及 前端。
- 改动规模：+8 / -4 行。
- 关键文件：frontend/src/components/ai-elements/inline-citation.tsx。

#### 64. fix(citations): use markdown link text as fallback for display

- 提交：`[acbf2fb](https://github.com/bytedance/deer-flow/commit/acbf2fb453f21f05badaacdfcb7a45f3d0a46ab2)`
- 日期：2026-02-06
- 做了什么：修复缺陷或回归问题，主题是“use markdown link text as fallback for display”。
- 影响范围：主要涉及 前端。
- 改动规模：+8 / -4 行。
- 关键文件：frontend/src/components/ai-elements/inline-citation.tsx。

#### 65. fix(citations): use markdown link text as fallback for display

- 提交：`[c87f176](https://github.com/bytedance/deer-flow/commit/c87f176fac5368ea14e67bf8217cb613d8652e1e)`
- 日期：2026-02-06
- 做了什么：修复缺陷或回归问题，主题是“use markdown link text as fallback for display”。
- 影响范围：主要涉及 前端。
- 改动规模：+8 / -4 行。
- 关键文件：frontend/src/components/ai-elements/inline-citation.tsx。

#### 66. fix(prompt): clarify citation link format must include URL

- 提交：`[a91302a](https://github.com/bytedance/deer-flow/commit/a91302ac72eebc87a1e365e089c81158f189a433)`
- 日期：2026-02-06
- 做了什么：修复缺陷或回归问题，主题是“clarify citation link format must include URL”。
- 影响范围：主要涉及 后端。
- 改动规模：+12 / -7 行。
- 关键文件：backend/src/agents/lead_agent/prompt.py。

#### 67. fix(prompt): clarify citation link format must include URL

- 提交：`[f43522b](https://github.com/bytedance/deer-flow/commit/f43522bd274579567004b312c28ccb4096d81b6d)`
- 日期：2026-02-06
- 做了什么：修复缺陷或回归问题，主题是“clarify citation link format must include URL”。
- 影响范围：主要涉及 后端。
- 改动规模：+12 / -7 行。
- 关键文件：backend/src/agents/lead_agent/prompt.py。

#### 68. fix(prompt): clarify citation link format must include URL

- 提交：`[b46a19e](https://github.com/bytedance/deer-flow/commit/b46a19e1165ff28acb97502ccae1565a29585ee4)`
- 日期：2026-02-06
- 做了什么：修复缺陷或回归问题，主题是“clarify citation link format must include URL”。
- 影响范围：主要涉及 后端。
- 改动规模：+12 / -7 行。
- 关键文件：backend/src/agents/lead_agent/prompt.py。

#### 69. fix(messages): prevent URL autolink bleeding into adjacent text

- 提交：`[738b71b](https://github.com/bytedance/deer-flow/commit/738b71be47ebb777542109fcb3af0c0db29caedc)`
- 日期：2026-02-06
- 做了什么：修复缺陷或回归问题，主题是“prevent URL autolink bleeding into adjacent text”。
- 影响范围：主要涉及 前端。
- 改动规模：+16 / -3 行。
- 关键文件：frontend/src/components/workspace/messages/message-list-item.tsx；frontend/src/core/streamdown/plugins.ts。

#### 70. fix(messages): prevent URL autolink bleeding into adjacent text

- 提交：`[c8c4d2f](https://github.com/bytedance/deer-flow/commit/c8c4d2fc953c634867e721698ce6fa1d0e1020fe)`
- 日期：2026-02-06
- 做了什么：修复缺陷或回归问题，主题是“prevent URL autolink bleeding into adjacent text”。
- 影响范围：主要涉及 前端。
- 改动规模：+16 / -3 行。
- 关键文件：frontend/src/components/workspace/messages/message-list-item.tsx；frontend/src/core/streamdown/plugins.ts。

#### 71. fix(messages): prevent URL autolink bleeding into adjacent text

- 提交：`[34a199c](https://github.com/bytedance/deer-flow/commit/34a199c6f3460dd15ed836690a9ab284e92b4cf4)`
- 日期：2026-02-06
- 做了什么：修复缺陷或回归问题，主题是“prevent URL autolink bleeding into adjacent text”。
- 影响范围：主要涉及 前端。
- 改动规模：+16 / -3 行。
- 关键文件：frontend/src/components/workspace/messages/message-list-item.tsx；frontend/src/core/streamdown/plugins.ts。

#### 72. fix(citations): only render CitationLink badges for AI messages

- 提交：`[6f96824](https://github.com/bytedance/deer-flow/commit/6f968242d64a3e0018a292511cdfdb3fa24e599f)`
- 日期：2026-02-06
- 做了什么：修复缺陷或回归问题，主题是“only render CitationLink badges for AI messages”。
- 影响范围：主要涉及 前端。
- 改动规模：+20 / -4 行。
- 关键文件：frontend/src/components/workspace/messages/message-list-item.tsx。

#### 73. fix(citations): only render CitationLink badges for AI messages

- 提交：`[1b0c016](https://github.com/bytedance/deer-flow/commit/1b0c0160939ae29198a169056064d9e96480c5d9)`
- 日期：2026-02-06
- 做了什么：修复缺陷或回归问题，主题是“only render CitationLink badges for AI messages”。
- 影响范围：主要涉及 前端。
- 改动规模：+20 / -4 行。
- 关键文件：frontend/src/components/workspace/messages/message-list-item.tsx。

#### 74. fix(citations): only render CitationLink badges for AI messages

- 提交：`[bcbbf9c](https://github.com/bytedance/deer-flow/commit/bcbbf9cf3fdb0626c978a994ec158eb785314ef9)`
- 日期：2026-02-06
- 做了什么：修复缺陷或回归问题，主题是“only render CitationLink badges for AI messages”。
- 影响范围：主要涉及 前端。
- 改动规模：+20 / -4 行。
- 关键文件：frontend/src/components/workspace/messages/message-list-item.tsx。

#### 75. fix(citations): improve citation link rendering and copy behavior

- 提交：`[2debcf4](https://github.com/bytedance/deer-flow/commit/2debcf421c1a7f2150f2c22462e09e6ee3e93770)`
- 日期：2026-02-04
- 做了什么：修复缺陷或回归问题，主题是“improve citation link rendering and copy behavior”。
- 影响范围：主要涉及 前端、后端。
- 改动规模：+26 / -26 行。
- 关键文件：backend/src/agents/lead_agent/prompt.py；frontend/src/components/ai-elements/inline-citation.tsx；frontend/src/components/workspace/messages/message-list-item.tsx。

#### 76. fix(citations): improve citation link rendering and copy behavior

- 提交：`[f6e625e](https://github.com/bytedance/deer-flow/commit/f6e625ec3b7ffc74fc9768cd273b067b6c584540)`
- 日期：2026-02-04
- 做了什么：修复缺陷或回归问题，主题是“improve citation link rendering and copy behavior”。
- 影响范围：主要涉及 前端、后端。
- 改动规模：+26 / -26 行。
- 关键文件：backend/src/agents/lead_agent/prompt.py；frontend/src/components/ai-elements/inline-citation.tsx；frontend/src/components/workspace/messages/message-list-item.tsx。

#### 77. fix(citations): improve citation link rendering and copy behavior

- 提交：`[0f9e3d5](https://github.com/bytedance/deer-flow/commit/0f9e3d508bde05e77ca64493d93bddbe2266d33e)`
- 日期：2026-02-04
- 做了什么：修复缺陷或回归问题，主题是“improve citation link rendering and copy behavior”。
- 影响范围：主要涉及 前端、后端。
- 改动规模：+26 / -26 行。
- 关键文件：backend/src/agents/lead_agent/prompt.py；frontend/src/components/ai-elements/inline-citation.tsx；frontend/src/components/workspace/messages/message-list-item.tsx。

#### 78. fix: fix frontend rendering issue

- 提交：`[b773bae](https://github.com/bytedance/deer-flow/commit/b773bae407fc186ff94a34c895edad76c85d8ec5)`
- 日期：2026-02-03
- 做了什么：修复缺陷或回归问题，主题是“fix frontend rendering issue”。
- 影响范围：主要涉及 前端。
- 改动规模：+4 / -1 行。
- 关键文件：frontend/next.config.js；frontend/src/app/workspace/layout.tsx。

#### 79. fix: fix frontend rendering issue

- 提交：`[d670cc0](https://github.com/bytedance/deer-flow/commit/d670cc0ab1cd0bf5177c85811a2a1745457a1b77)`
- 日期：2026-02-03
- 做了什么：修复缺陷或回归问题，主题是“fix frontend rendering issue”。
- 影响范围：主要涉及 前端。
- 改动规模：+4 / -1 行。
- 关键文件：frontend/next.config.js；frontend/src/app/workspace/layout.tsx。

#### 80. fix: fix frontend rendering issue

- 提交：`[8f8637c](https://github.com/bytedance/deer-flow/commit/8f8637c3c4a0de589d9d83605c6b4141d141abb5)`
- 日期：2026-02-03
- 做了什么：修复缺陷或回归问题，主题是“fix frontend rendering issue”。
- 影响范围：主要涉及 前端。
- 改动规模：+4 / -1 行。
- 关键文件：frontend/next.config.js；frontend/src/app/workspace/layout.tsx。

#### 81. fix: 修复用户消息中上传文件的右对齐显示

- 提交：`[3b411fe](https://github.com/bytedance/deer-flow/commit/3b411fe499c08ba530c377249095e301a8ae24b4)`
- 日期：2026-02-03
- 做了什么：修复缺陷或回归问题，主题是“修复用户消息中上传文件的右对齐显示”。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -1 行。
- 关键文件：frontend/src/components/workspace/messages/message-list-item.tsx。

#### 82. fix: 修复用户消息中上传文件的右对齐显示

- 提交：`[1fac83e](https://github.com/bytedance/deer-flow/commit/1fac83eafaad272eb9cc94720255a1949ed4683f)`
- 日期：2026-02-03
- 做了什么：修复缺陷或回归问题，主题是“修复用户消息中上传文件的右对齐显示”。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -1 行。
- 关键文件：frontend/src/components/workspace/messages/message-list-item.tsx。

#### 83. fix: 修复用户消息中上传文件的右对齐显示

- 提交：`[9017721](https://github.com/bytedance/deer-flow/commit/901772136eeda86b2356077a17faa5d4e57f0f43)`
- 日期：2026-02-03
- 做了什么：修复缺陷或回归问题，主题是“修复用户消息中上传文件的右对齐显示”。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -1 行。
- 关键文件：frontend/src/components/workspace/messages/message-list-item.tsx。

#### 84. fix: add file mtime-based cache invalidation for memory data

- 提交：`[2c32e8a](https://github.com/bytedance/deer-flow/commit/2c32e8a461ebbdc6b4de2c3bf3efb70a54fe4adb)`
- 日期：2026-02-03
- 做了什么：修复缺陷或回归问题，主题是“add file mtime-based cache invalidation for memory data”。
- 影响范围：主要涉及 后端。
- 改动规模：+38 / -8 行。
- 关键文件：backend/src/agents/memory/updater.py。

#### 85. fix: add file mtime-based cache invalidation for memory data

- 提交：`[9e15e60](https://github.com/bytedance/deer-flow/commit/9e15e609ec7918a7533a9687d1de2473d2167070)`
- 日期：2026-02-03
- 做了什么：修复缺陷或回归问题，主题是“add file mtime-based cache invalidation for memory data”。
- 影响范围：主要涉及 后端。
- 改动规模：+38 / -8 行。
- 关键文件：backend/src/agents/memory/updater.py。

#### 86. fix: add file mtime-based cache invalidation for memory data

- 提交：`[5682f7b](https://github.com/bytedance/deer-flow/commit/5682f7b67d5ffb5c47cbbb47240a851666e911ca)`
- 日期：2026-02-03
- 做了什么：修复缺陷或回归问题，主题是“add file mtime-based cache invalidation for memory data”。
- 影响范围：主要涉及 后端。
- 改动规模：+38 / -8 行。
- 关键文件：backend/src/agents/memory/updater.py。

#### 87. Fix a11y: add accessible name for icon button (#844)

- 提交：`[fab1d39](https://github.com/bytedance/deer-flow/commit/fab1d39323ec77179d77e1358c9e54b11ae77927)`
- 日期：2026-02-02
- 做了什么：修复缺陷或回归问题，主题是“Fix a11y: add accessible name for icon button (#844)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+13 / -2 行。
- 关键文件：web/src/app/landing/components/multi-agent-visualization.tsx。

#### 88. fix(node):deal with the plan_data content with multipmodal message (#846)

- 提交：`[e3e7a83](https://github.com/bytedance/deer-flow/commit/e3e7a83f40ac852e6b5befc93466d2d4b0cf3821)`
- 日期：2026-02-02
- 做了什么：修复缺陷或回归问题，主题是“deal with the plan_data content with multipmodal message (#846)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+177 / -1 行。
- 关键文件：src/graph/nodes.py；tests/integration/test_nodes.py。

#### 89. fix: fix position

- 提交：`[e847158](https://github.com/bytedance/deer-flow/commit/e84715831f8efb548d08a9a5e994d95cda303821)`
- 日期：2026-02-02
- 做了什么：修复缺陷或回归问题，主题是“fix position”。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -1 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx。

#### 90. fix: fix position

- 提交：`[03f84f2](https://github.com/bytedance/deer-flow/commit/03f84f2b76e87fc93b88ab5f65537d5acb9e2051)`
- 日期：2026-02-02
- 做了什么：修复缺陷或回归问题，主题是“fix position”。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -1 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx。

#### 91. fix: fix position

- 提交：`[268b7f9](https://github.com/bytedance/deer-flow/commit/268b7f911c4742c88f77fedc0797c88a2a6b4e10)`
- 日期：2026-02-02
- 做了什么：修复缺陷或回归问题，主题是“fix position”。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -1 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx。

#### 92. fix: set default state for todo list collapse to true

- 提交：`[018241c](https://github.com/bytedance/deer-flow/commit/018241c2034e2dafea7c7c5a4b61f68bb969c293)`
- 日期：2026-02-02
- 做了什么：修复缺陷或回归问题，主题是“set default state for todo list collapse to true”。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -1 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx。

#### 93. fix: set default state for todo list collapse to true

- 提交：`[35c5b6b](https://github.com/bytedance/deer-flow/commit/35c5b6ba6b1cca3829af7b431f5443b4a0646652)`
- 日期：2026-02-02
- 做了什么：修复缺陷或回归问题，主题是“set default state for todo list collapse to true”。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -1 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx。

#### 94. fix: set default state for todo list collapse to true

- 提交：`[8bc9d1b](https://github.com/bytedance/deer-flow/commit/8bc9d1b2262d3d938f1c3135921c0b4bc1f81e5b)`
- 日期：2026-02-02
- 做了什么：修复缺陷或回归问题，主题是“set default state for todo list collapse to true”。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -1 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx。

#### 95. fix: set default state for todo list collapse to false

- 提交：`[6f6d799](https://github.com/bytedance/deer-flow/commit/6f6d799051324b34407ac580aee1ed2951a14776)`
- 日期：2026-02-02
- 做了什么：修复缺陷或回归问题，主题是“set default state for todo list collapse to false”。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -3 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx。

#### 96. fix: set default state for todo list collapse to false

- 提交：`[a745b82](https://github.com/bytedance/deer-flow/commit/a745b824d5f4ebda7cfba87f510b1423e8a5faeb)`
- 日期：2026-02-02
- 做了什么：修复缺陷或回归问题，主题是“set default state for todo list collapse to false”。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -3 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx。

#### 97. fix: set default state for todo list collapse to false

- 提交：`[e01127e](https://github.com/bytedance/deer-flow/commit/e01127eec94b68f18aeb92d99fe6b2934cb7bd40)`
- 日期：2026-02-02
- 做了什么：修复缺陷或回归问题，主题是“set default state for todo list collapse to false”。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -3 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx。

#### 98. fix: update TooltipContent component to handle sideOffset correctly and add shadow styling

- 提交：`[a66f76f](https://github.com/bytedance/deer-flow/commit/a66f76f43d54f19d24d4eba8f3fb41e4a20a42cd)`
- 日期：2026-02-02
- 做了什么：修复缺陷或回归问题，主题是“update TooltipContent component to handle sideOffset correctly and add shadow styling”。
- 影响范围：主要涉及 前端。
- 改动规模：+3 / -3 行。
- 关键文件：frontend/src/components/ui/tooltip.tsx。

#### 99. fix: update TooltipContent component to handle sideOffset correctly and add shadow styling

- 提交：`[ccab249](https://github.com/bytedance/deer-flow/commit/ccab24983e6ba88c471fd197053bf3eeae79cee9)`
- 日期：2026-02-02
- 做了什么：修复缺陷或回归问题，主题是“update TooltipContent component to handle sideOffset correctly and add shadow styling”。
- 影响范围：主要涉及 前端。
- 改动规模：+3 / -3 行。
- 关键文件：frontend/src/components/ui/tooltip.tsx。

#### 100. fix: update TooltipContent component to handle sideOffset correctly and add shadow styling

- 提交：`[33e82a7](https://github.com/bytedance/deer-flow/commit/33e82a7abee13e201806a03353eb24e756f91aff)`
- 日期：2026-02-02
- 做了什么：修复缺陷或回归问题，主题是“update TooltipContent component to handle sideOffset correctly and add shadow styling”。
- 影响范围：主要涉及 前端。
- 改动规模：+3 / -3 行。
- 关键文件：frontend/src/components/ui/tooltip.tsx。

## 2026-03

- 新功能/增强：78 条
- Bug 修复：119 条

### 新功能 / 增强

#### 1. feat: support memory import and export (#1521)

- 提交：`[9a55775](https://github.com/bytedance/deer-flow/commit/9a557751d618bf3c5d2c30f80233e940837f0599)`
- 日期：2026-03-30
- 做了什么：新增或增强功能，主题是“support memory import and export (#1521)”。
- 影响范围：主要涉及 前端、后端。
- 改动规模：+604 / -27 行。
- 关键文件：backend/app/gateway/routers/memory.py；backend/packages/harness/deerflow/agents/memory/updater.py；backend/packages/harness/deerflow/client.py；backend/tests/test_client.py；backend/tests/test_memory_router.py；backend/tests/test_memory_updater.py；frontend/src/app/api/memory/[...path]/route.ts；frontend/src/app/api/memory/route.ts。

#### 2. feat(gateway): implement LangGraph Platform API in Gateway, replace langgraph-cli (#1403)

- 提交：`[34e835b](https://github.com/bytedance/deer-flow/commit/34e835bc33d6d2b6c235abf76577e4383f318b86)`
- 日期：2026-03-30
- 做了什么：新增或增强功能，主题是“implement LangGraph Platform API in Gateway, replace langgraph-cli (#1403)”。
- 影响范围：主要涉及 后端、容器部署、前端。
- 改动规模：+3492 / -66 行。
- 关键文件：backend/app/gateway/app.py；backend/app/gateway/deps.py；backend/app/gateway/routers/**init**.py；backend/app/gateway/routers/assistants_compat.py；backend/app/gateway/routers/runs.py；backend/app/gateway/routers/thread_runs.py；backend/app/gateway/routers/threads.py；backend/app/gateway/services.py。

#### 3. feat(feishu): add configurable domain for Lark international support (#1535)

- 提交：`[7db9592](https://github.com/bytedance/deer-flow/commit/7db95926b08626ab688400562977d2996078ae36)`
- 日期：2026-03-30
- 做了什么：新增或增强功能，主题是“add configurable domain for Lark international support (#1535)”。
- 影响范围：主要涉及 文档、后端、配置。
- 改动规模：+18 / -3 行。
- 关键文件：README.md；README_fr.md；README_ja.md；README_ru.md；README_zh.md；backend/app/channels/feishu.py；config.example.yaml。

#### 4. feat(sandbox): add SandboxAuditMiddleware for bash command security auditing (#1532)

- 提交：`[9aa3ff7](https://github.com/bytedance/deer-flow/commit/9aa3ff7c48434f84bafab8972bb517f4157ac042)`
- 日期：2026-03-30
- 做了什么：新增或增强功能，主题是“add SandboxAuditMiddleware for bash command security auditing (#1532)”。
- 影响范围：主要涉及 后端。
- 改动规模：+578 / -0 行。
- 关键文件：backend/packages/harness/deerflow/agents/middlewares/sandbox_audit_middleware.py；backend/packages/harness/deerflow/agents/middlewares/tool_error_handling_middleware.py；backend/tests/test_sandbox_audit_middleware.py。

#### 5. feat: support manual add and edit for memory facts (#1538)

- 提交：`[fc7de7f](https://github.com/bytedance/deer-flow/commit/fc7de7fffe3e9cd229d16dbfa4dd6a61251242ad)`
- 日期：2026-03-29
- 做了什么：新增或增强功能，主题是“support manual add and edit for memory facts (#1538)”。
- 影响范围：主要涉及 后端、前端。
- 改动规模：+978 / -53 行。
- 关键文件：backend/app/gateway/routers/memory.py；backend/docs/MEMORY_SETTINGS_REVIEW.md；backend/docs/memory-settings-sample.json；backend/packages/harness/deerflow/agents/memory/updater.py；backend/packages/harness/deerflow/client.py；backend/tests/test_client.py；backend/tests/test_memory_router.py；backend/tests/test_memory_updater.py。

#### 6. docs(config): add timeout and max_retries examples for model providers (#1549)

- 提交：`[6091ba8](https://github.com/bytedance/deer-flow/commit/6091ba83c45c47cb40e94fb2e4e5dc1a7b041126)`
- 日期：2026-03-29
- 做了什么：补充文档能力，主题是“add timeout and max_retries examples for model providers (#1549)”。
- 影响范围：主要涉及 配置。
- 改动规模：+28 / -0 行。
- 关键文件：config.example.yaml。

#### 7. docs: add format step to contributing workflow (#1552)

- 提交：`[70e9f2d](https://github.com/bytedance/deer-flow/commit/70e9f2dd2c1a429bba1277823d579d71e5da1976)`
- 日期：2026-03-29
- 做了什么：补充文档能力，主题是“add format step to contributing workflow (#1552)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+17 / -5 行。
- 关键文件：CONTRIBUTING.md。

#### 8. style: format unformatted files and add .omc/ to prettierignore (#1539)

- 提交：`[25df82c](https://github.com/bytedance/deer-flow/commit/25df82cbfdd521ef5fea7e4e6c7979a160856471)`
- 日期：2026-03-29
- 做了什么：新增或增强功能，主题是“style: format unformatted files and add .omc/ to prettierignore (#1539)”。
- 影响范围：主要涉及 后端、前端。
- 改动规模：+19 / -33 行。
- 关键文件：backend/packages/harness/deerflow/agents/factory.py；backend/tests/test_create_deerflow_agent.py；frontend/.prettierignore。

#### 9. feat: add create_deerflow_agent SDK entry point (Phase 1) (#1203)

- 提交：`[06a623f](https://github.com/bytedance/deer-flow/commit/06a623f9c82ee93e0dc69ba9fc4b98aeac132ae3)`
- 日期：2026-03-29
- 做了什么：新增或增强功能，主题是“add create_deerflow_agent SDK entry point (Phase 1) (#1203)”。
- 影响范围：主要涉及 后端。
- 改动规模：+2225 / -3 行。
- 关键文件：backend/docs/middleware-execution-flow.md；backend/docs/rfc-create-deerflow-agent.md；backend/packages/harness/deerflow/agents/**init**.py；backend/packages/harness/deerflow/agents/factory.py；backend/packages/harness/deerflow/agents/features.py；backend/packages/harness/deerflow/agents/middlewares/**init**.py；backend/tests/test_client_e2e.py；backend/tests/test_client_live.py。

#### 10. feat: add memory management actions and local filters in memory settings (#1467)

- 提交：`[7eb3a15](https://github.com/bytedance/deer-flow/commit/7eb3a150b5f3f3824515417685e49f00a6acd2fd)`
- 日期：2026-03-29
- 做了什么：新增或增强功能，主题是“add memory management actions and local filters in memory settings (#1467)”。
- 影响范围：主要涉及 后端、前端、文档。
- 改动规模：+1025 / -130 行。
- 关键文件：README.md；backend/app/gateway/routers/memory.py；backend/docs/MEMORY_SETTINGS_REVIEW.md；backend/docs/memory-settings-sample.json；backend/packages/harness/deerflow/agents/memory/**init**.py；backend/packages/harness/deerflow/agents/memory/updater.py；backend/packages/harness/deerflow/client.py；backend/tests/test_client.py。

#### 11. feat(client): support custom middleware injection (#1520)

- 提交：`[481494b](https://github.com/bytedance/deer-flow/commit/481494b9c0e679876c73f48dc834b8d3e8cb3dd9)`
- 日期：2026-03-29
- 做了什么：新增或增强功能，主题是“support custom middleware injection (#1520)”。
- 影响范围：主要涉及 后端。
- 改动规模：+56 / -5 行。
- 关键文件：backend/packages/harness/deerflow/agents/lead_agent/agent.py；backend/packages/harness/deerflow/client.py；backend/tests/test_client.py；backend/tests/test_lead_agent_model_resolution.py。

#### 12. docs(README): add missing cross-language README links (#1479)

- 提交：`[6bf23ba](https://github.com/bytedance/deer-flow/commit/6bf23ba0a310803a5b7b4bd905a1ed04c3aab73e)`
- 日期：2026-03-27
- 做了什么：补充文档能力，主题是“add missing cross-language README links (#1479)”。
- 影响范围：主要涉及 文档。
- 改动规模：+4 / -4 行。
- 关键文件：README_fr.md；README_ja.md；README_ru.md；README_zh.md。

#### 13. test: add unit tests for skill frontmatter validation (#1309)

- 提交：`[50f50d7](https://github.com/bytedance/deer-flow/commit/50f50d7654a030affbcd41b97e180db6d66a1782)`
- 日期：2026-03-27
- 做了什么：补充/增强测试体系，主题是“add unit tests for skill frontmatter validation (#1309)”。
- 影响范围：主要涉及 后端。
- 改动规模：+180 / -88 行。
- 关键文件：backend/tests/test_skills_router.py；backend/tests/test_skills_validation.py。

#### 14. feat(acp): add env field to ACPAgentConfig for subprocess env injection (#1447)

- 提交：`[8590249](https://github.com/bytedance/deer-flow/commit/8590249db41474c97de6eeb60190f006c962de6b)`
- 日期：2026-03-27
- 做了什么：新增或增强功能，主题是“add env field to ACPAgentConfig for subprocess env injection (#1447)”。
- 影响范围：主要涉及 后端、配置。
- 改动规模：+215 / -3 行。
- 关键文件：backend/packages/harness/deerflow/config/acp_config.py；backend/packages/harness/deerflow/tools/builtins/invoke_acp_agent_tool.py；backend/tests/test_acp_config.py；backend/tests/test_invoke_acp_agent_tool.py；config.example.yaml。

#### 15. docs: add LangSmith tracing configuration and documentation (#1414)

- 提交：`[a4e4bb2](https://github.com/bytedance/deer-flow/commit/a4e4bb21e3f0843a1de2e03ea00864379fa6bb8a)`
- 日期：2026-03-27
- 做了什么：补充文档能力，主题是“add LangSmith tracing configuration and documentation (#1414)”。
- 影响范围：主要涉及 文档、其他模块、后端。
- 改动规模：+111 / -4 行。
- 关键文件：.env.example；README.md；README_fr.md；README_ja.md；README_ru.md；README_zh.md；backend/README.md；docker/docker-compose.yaml。

#### 16. feat: Support gitHub PAT configuration for higher github API accessing rate. (#1374)

- 提交：`[6b13f5c](https://github.com/bytedance/deer-flow/commit/6b13f5c9fb052b2efee1e76edc5af91b9244a74d)`
- 日期：2026-03-27
- 做了什么：新增或增强功能，主题是“Support gitHub PAT configuration for higher github API accessing rate. (#1374)”。
- 影响范围：主要涉及 其他模块、后端、技能体系。
- 改动规模：+17 / -3 行。
- 关键文件：.env.example；backend/docs/CONFIGURATION.md；skills/public/github-deep-research/scripts/github_api.py。

#### 17. Implement DuckDuckGo search (#1432)

- 提交：`[c137933](https://github.com/bytedance/deer-flow/commit/c13793386fbf8c1bbccbdef1c8802daf40a58d0c)`
- 日期：2026-03-26
- 做了什么：新增或增强功能，主题是“Implement DuckDuckGo search (#1432)”。
- 影响范围：主要涉及 后端、配置。
- 改动规模：+107 / -3 行。
- 关键文件：backend/packages/harness/deerflow/community/ddg_search/**init**.py；backend/packages/harness/deerflow/community/ddg_search/tools.py；config.example.yaml。

#### 18. feat(memory): Introduce configurable memory storage abstraction (#1353)

- 提交：`[1c542ab](https://github.com/bytedance/deer-flow/commit/1c542ab7f1524f6248412e6ba004d985a549c10b)`
- 日期：2026-03-27
- 做了什么：新增或增强功能，主题是“Introduce configurable memory storage abstraction (#1353)”。
- 影响范围：主要涉及 后端。
- 改动规模：+442 / -177 行。
- 关键文件：backend/packages/harness/deerflow/agents/memory/**init**.py；backend/packages/harness/deerflow/agents/memory/storage.py；backend/packages/harness/deerflow/agents/memory/updater.py；backend/packages/harness/deerflow/config/memory_config.py；backend/tests/test_custom_agent.py；backend/tests/test_memory_storage.py；backend/tests/test_memory_updater.py。

#### 19. docs: add install.md agent setup guide (#1402)

- 提交：`[e1853df](https://github.com/bytedance/deer-flow/commit/e1853df06aa2aefb10750834802cce10af79b936)`
- 日期：2026-03-26
- 做了什么：补充文档能力，主题是“add install.md agent setup guide (#1402)”。
- 影响范围：主要涉及 文档、其他模块。
- 改动规模：+142 / -0 行。
- 关键文件：Install.md；README.md；README_fr.md；README_ja.md；README_ru.md；README_zh.md。

#### 20. Add security alerts to documents (#1413)

- 提交：`[f80d174](https://github.com/bytedance/deer-flow/commit/f80d1743ab035f5041a5a6e371853ae0de30cf1e)`
- 日期：2026-03-26
- 做了什么：新增或增强功能，主题是“Add security alerts to documents (#1413)”。
- 影响范围：主要涉及 文档。
- 改动规模：+95 / -0 行。
- 关键文件：README.md；README_fr.md；README_ja.md；README_ru.md；README_zh.md。

#### 21. feat: hide model ID for safety reason, only show the display_name (#1410)

- 提交：`[227967d](https://github.com/bytedance/deer-flow/commit/227967df3d048d93bc8576e099a405f9bc559533)`
- 日期：2026-03-26
- 做了什么：新增或增强功能，主题是“hide model ID for safety reason, only show the display_name (#1410)”。
- 影响范围：主要涉及 前端。
- 改动规模：+287 / -275 行。
- 关键文件：frontend/src/components/workspace/input-box.tsx。

#### 22. Add packages section to pnpm-workspace.yaml (#1382)

- 提交：`[c0a6b81](https://github.com/bytedance/deer-flow/commit/c0a6b81852b091d9f1187b5d035d58607b80b0b1)`
- 日期：2026-03-26
- 做了什么：新增或增强功能，主题是“Add packages section to pnpm-workspace.yaml (#1382)”。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -0 行。
- 关键文件：frontend/pnpm-workspace.yaml。

#### 23. feat(harness): integration ACP agent tool (#1344)

- 提交：`[d119214](https://github.com/bytedance/deer-flow/commit/d119214fee616408adbe1a1d42398aa5e1d1fe20)`
- 日期：2026-03-26
- 做了什么：新增或增强功能，主题是“integration ACP agent tool (#1344)”。
- 影响范围：主要涉及 后端、文档、配置。
- 改动规模：+1566 / -219 行。
- 关键文件：README.md；backend/CLAUDE.md；backend/app/channels/feishu.py；backend/app/gateway/routers/uploads.py；backend/packages/harness/deerflow/agents/lead_agent/prompt.py；backend/packages/harness/deerflow/agents/memory/prompt.py；backend/packages/harness/deerflow/agents/memory/updater.py；backend/packages/harness/deerflow/agents/middlewares/loop_detection_middleware.py。

#### 24. test: add unit tests for TodoMiddleware (#1307)

- 提交：`[ac97dc6](https://github.com/bytedance/deer-flow/commit/ac97dc6d426c92efeefa018cea4471c0bbd6834f)`
- 日期：2026-03-25
- 做了什么：补充/增强测试体系，主题是“add unit tests for TodoMiddleware (#1307)”。
- 影响范围：主要涉及 后端。
- 改动规模：+156 / -0 行。
- 关键文件：backend/tests/test_todo_middleware.py。

#### 25. test: add unit tests for DanglingToolCallMiddleware (#1305)

- 提交：`[1f0ae64](https://github.com/bytedance/deer-flow/commit/1f0ae64e0218f04f3f524e118718d9bb7fb2c7b3)`
- 日期：2026-03-25
- 做了什么：补充/增强测试体系，主题是“add unit tests for DanglingToolCallMiddleware (#1305)”。
- 影响范围：主要涉及 后端。
- 改动规模：+190 / -0 行。
- 关键文件：backend/tests/test_dangling_tool_call_middleware.py。

#### 26. Add user configuration template for China region (#1337)

- 提交：`[fdfe08d](https://github.com/bytedance/deer-flow/commit/fdfe08d4aad3d3da8d15ba1a5af4151c052acfa2)`
- 日期：2026-03-25
- 做了什么：新增或增强功能，主题是“Add user configuration template for China region (#1337)”。
- 影响范围：主要涉及 配置。
- 改动规模：+25 / -1 行。
- 关键文件：config.example.yaml。

#### 27. docs: add domestic link of coding plan (#1340)

- 提交：`[1287566](https://github.com/bytedance/deer-flow/commit/12875664f11058329bb71d6c05dbb5dc7a0cc989)`
- 日期：2026-03-25
- 做了什么：补充文档能力，主题是“add domestic link of coding plan (#1340)”。
- 影响范围：主要涉及 文档。
- 改动规模：+1 / -1 行。
- 关键文件：README_zh.md。

#### 28. test: add unit tests for SubagentLimitMiddleware (#1306)

- 提交：`[ec46ae0](https://github.com/bytedance/deer-flow/commit/ec46ae075d8f91fbff9b0d227f76180e3ab64e49)`
- 日期：2026-03-24
- 做了什么：补充/增强测试体系，主题是“add unit tests for SubagentLimitMiddleware (#1306)”。
- 影响范围：主要涉及 后端。
- 改动规模：+140 / -0 行。
- 关键文件：backend/tests/test_subagent_limit_middleware.py。

#### 29. test: add unit tests for skills parser (#1308)

- 提交：`[afb0f66](https://github.com/bytedance/deer-flow/commit/afb0f66c737d878add6c011ce383b59206097065)`
- 日期：2026-03-24
- 做了什么：补充/增强测试体系，主题是“add unit tests for skills parser (#1308)”。
- 影响范围：主要涉及 后端。
- 改动规模：+98 / -0 行。
- 关键文件：backend/tests/test_skills_parser.py。

#### 30. docs: add Russian README translation (#1311)

- 提交：`[f499f37](https://github.com/bytedance/deer-flow/commit/f499f37e94fee02e49e00d4e1e25239d6f05ab72)`
- 日期：2026-03-25
- 做了什么：补充文档能力，主题是“add Russian README translation (#1311)”。
- 影响范围：主要涉及 文档。
- 改动规模：+442 / -1 行。
- 关键文件：README.md；README_ru.md。

#### 31. docs: add French translation of README (#1303)

- 提交：`[21febe1](https://github.com/bytedance/deer-flow/commit/21febe1cc960d4346a6c14d516b828039832c887)`
- 日期：2026-03-25
- 做了什么：补充文档能力，主题是“add French translation of README (#1303)”。
- 影响范围：主要涉及 文档。
- 改动规模：+565 / -3 行。
- 关键文件：README.md；README_fr.md；README_ja.md；README_zh.md。

#### 32. feat: add configurable log level and token usage tracking (#1301)

- 提交：`[16ed797](https://github.com/bytedance/deer-flow/commit/16ed797e0efc537a2215b3c7c59f9839edf22d21)`
- 日期：2026-03-25
- 做了什么：新增或增强功能，主题是“add configurable log level and token usage tracking (#1301)”。
- 影响范围：主要涉及 后端、其他模块、配置。
- 改动规模：+74 / -3 行。
- 关键文件：.gitignore；backend/packages/harness/deerflow/agents/lead_agent/agent.py；backend/packages/harness/deerflow/agents/middlewares/token_usage_middleware.py；backend/packages/harness/deerflow/config/app_config.py；backend/packages/harness/deerflow/config/token_usage_config.py；config.example.yaml；scripts/serve.sh。

#### 33. feat(frontend): display token usage per conversation turn (#1229)

- 提交：`[b40b05f](https://github.com/bytedance/deer-flow/commit/b40b05f62347818aac71b064573e360ef644188d)`
- 日期：2026-03-23
- 做了什么：新增或增强功能，主题是“display token usage per conversation turn (#1229)”。
- 影响范围：主要涉及 前端。
- 改动规模：+159 / -1 行。
- 关键文件：frontend/src/app/workspace/agents/[agent_name]/chats/[thread_id]/page.tsx；frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/workspace/token-usage-indicator.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts；frontend/src/core/i18n/locales/zh-CN.ts；frontend/src/core/messages/usage.ts。

#### 34. feat(frontend): add Cmd+K command palette and keyboard shortcuts (#1230)

- 提交：`[48031e5](https://github.com/bytedance/deer-flow/commit/48031e506b1a6222b3b887347f379ab867c905d2)`
- 日期：2026-03-23
- 做了什么：新增或增强功能，主题是“add Cmd+K command palette and keyboard shortcuts (#1230)”。
- 影响范围：主要涉及 前端。
- 改动规模：+213 / -0 行。
- 关键文件：frontend/src/app/workspace/layout.tsx；frontend/src/components/workspace/command-palette.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts；frontend/src/core/i18n/locales/zh-CN.ts；frontend/src/hooks/use-global-shortcuts.ts。

#### 35. feat(guardrails): add pre-tool-call authorization middleware with pluggable providers (#1240)

- 提交：`[a29134d](https://github.com/bytedance/deer-flow/commit/a29134d7c9e704e2e1f960ec92417b65bf383b4f)`
- 日期：2026-03-23
- 做了什么：新增或增强功能，主题是“add pre-tool-call authorization middleware with pluggable providers (#1240)”。
- 影响范围：主要涉及 后端、配置。
- 改动规模：+1041 / -7 行。
- 关键文件：backend/CLAUDE.md；backend/docs/GUARDRAILS.md；backend/packages/harness/deerflow/agents/middlewares/tool_error_handling_middleware.py；backend/packages/harness/deerflow/config/app_config.py；backend/packages/harness/deerflow/config/guardrails_config.py；backend/packages/harness/deerflow/guardrails/**init**.py；backend/packages/harness/deerflow/guardrails/builtin.py；backend/packages/harness/deerflow/guardrails/middleware.py。

#### 36. feat(client): support agent_name injection to enable isolated memory and custom prompts (#1253)

- 提交：`[fe75cb3](https://github.com/bytedance/deer-flow/commit/fe75cb35caa428e7ef60205c59c44c88492ac7b4)`
- 日期：2026-03-23
- 做了什么：新增或增强功能，主题是“support agent_name injection to enable isolated memory and custom prompts (#1253)”。
- 影响范围：主要涉及 后端。
- 改动规模：+47 / -4 行。
- 关键文件：backend/packages/harness/deerflow/client.py；backend/tests/test_client.py。

#### 37. feat(web): add conversation export as Markdown and JSON (#1002)

- 提交：`[38ace61](https://github.com/bytedance/deer-flow/commit/38ace61617c9d2393a76ee4e2dd6404109d7ee32)`
- 日期：2026-03-23
- 做了什么：新增或增强功能，主题是“add conversation export as Markdown and JSON (#1002)”。
- 影响范围：主要涉及 前端。
- 改动规模：+308 / -2 行。
- 关键文件：frontend/src/app/workspace/agents/[agent_name]/chats/[thread_id]/page.tsx；frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/workspace/export-trigger.tsx；frontend/src/components/workspace/recent-chat-list.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts；frontend/src/core/i18n/locales/zh-CN.ts；frontend/src/core/threads/export.ts。

#### 38. feat: add Claude Code OAuth and Codex CLI as LLM providers (#1166)

- 提交：`[835ba04](https://github.com/bytedance/deer-flow/commit/835ba041f8e5eb7faa59aa7192a231a02f2a798e)`
- 日期：2026-03-22
- 做了什么：新增或增强功能，主题是“add Claude Code OAuth and Codex CLI as LLM providers (#1166)”。
- 影响范围：主要涉及 后端、文档、容器部署。
- 改动规模：+1546 / -0 行。
- 关键文件：README.md；backend/docs/CONFIGURATION.md；backend/packages/harness/deerflow/models/claude_provider.py；backend/packages/harness/deerflow/models/credential_loader.py；backend/packages/harness/deerflow/models/factory.py；backend/packages/harness/deerflow/models/openai_codex_provider.py；backend/tests/test_cli_auth_providers.py；backend/tests/test_credential_loader.py。

#### 39. feat(codex): support explicit OpenAI Responses API config (#1235)

- 提交：`[e119dc7](https://github.com/bytedance/deer-flow/commit/e119dc74ae869d2dfd2898301f71e9e5306c7d5a)`
- 日期：2026-03-22
- 做了什么：新增或增强功能，主题是“support explicit OpenAI Responses API config (#1235)”。
- 影响范围：主要涉及 后端、文档、配置。
- 改动规模：+113 / -1 行。
- 关键文件：README.md；backend/CLAUDE.md；backend/README.md；backend/docs/CONFIGURATION.md；backend/packages/harness/deerflow/config/model_config.py；backend/tests/test_model_config.py；backend/tests/test_model_factory.py；config.example.yaml。

#### 40. docs: add Japanese README (#1209)

- 提交：`[9dbcca5](https://github.com/bytedance/deer-flow/commit/9dbcca579dff84eaafac8d2629097e5f9bd739a2)`
- 日期：2026-03-21
- 做了什么：补充文档能力，主题是“add Japanese README (#1209)”。
- 影响范围：主要涉及 文档。
- 改动规模：+517 / -2 行。
- 关键文件：README.md；README_ja.md；README_zh.md。

#### 41. feat: track token usage per conversation turn (#1218)

- 提交：`[06cba21](https://github.com/bytedance/deer-flow/commit/06cba217c332b103e4bbe7edc031cfbc7455c168)`
- 日期：2026-03-21
- 做了什么：新增或增强功能，主题是“track token usage per conversation turn (#1218)”。
- 影响范围：主要涉及 后端。
- 改动规模：+327 / -6 行。
- 关键文件：backend/packages/harness/deerflow/client.py；backend/tests/test_token_usage.py。

#### 42. refactor: add channel-based streaming capability check (#1214)

- 提交：`[e69dc29](https://github.com/bytedance/deer-flow/commit/e69dc2961f4650d107234bf1b7a28654a02ec8fa)`
- 日期：2026-03-20
- 做了什么：新增或增强功能，主题是“add channel-based streaming capability check (#1214)”。
- 影响范围：主要涉及 后端。
- 改动规模：+11 / -1 行。
- 关键文件：backend/app/channels/manager.py。

#### 43. feat(manager): add bootstrap command to initialize soul.md in correct place (#1201)

- 提交：`[c037ed6](https://github.com/bytedance/deer-flow/commit/c037ed673923818c7059174da9334c8e125c6eea)`
- 日期：2026-03-20
- 做了什么：新增或增强功能，主题是“add bootstrap command to initialize soul.md in correct place (#1201)”。
- 影响范围：主要涉及 后端。
- 改动规模：+244 / -2 行。
- 关键文件：backend/app/channels/manager.py；backend/tests/test_channels.py。

#### 44. feat(tools): add tool_search for deferred MCP tool loading (#1176)

- 提交：`[0091d9f](https://github.com/bytedance/deer-flow/commit/0091d9f0714763eaad3c8450e5eadfd7555cba11)`
- 日期：2026-03-17
- 做了什么：新增或增强功能，主题是“add tool_search for deferred MCP tool loading (#1176)”。
- 影响范围：主要涉及 后端、配置。
- 改动规模：+718 / -23 行。
- 关键文件：backend/packages/harness/deerflow/agents/lead_agent/agent.py；backend/packages/harness/deerflow/agents/lead_agent/prompt.py；backend/packages/harness/deerflow/agents/middlewares/deferred_tool_filter_middleware.py；backend/packages/harness/deerflow/config/app_config.py；backend/packages/harness/deerflow/config/tool_search_config.py；backend/packages/harness/deerflow/mcp/tools.py；backend/packages/harness/deerflow/tools/builtins/tool_search.py；backend/packages/harness/deerflow/tools/tools.py。

#### 45. docs: add coding plan from ByteDance Volcengine (#1174)

- 提交：`[f29db80](https://github.com/bytedance/deer-flow/commit/f29db80be7516c13e33dab2e10279a91aebd17e1)`
- 日期：2026-03-17
- 做了什么：补充文档能力，主题是“add coding plan from ByteDance Volcengine (#1174)”。
- 影响范围：主要涉及 文档。
- 改动规模：+20 / -4 行。
- 关键文件：README.md；README_zh.md。

#### 46. docs: add README in Chinese (#1172)

- 提交：`[cb4cae4](https://github.com/bytedance/deer-flow/commit/cb4cae4064b90770681dc332874b0bb7bde3b3fb)`
- 日期：2026-03-17
- 做了什么：补充文档能力，主题是“add README in Chinese (#1172)”。
- 影响范围：主要涉及 文档。
- 改动规模：+499 / -2 行。
- 关键文件：README.md；README_zh.md。

#### 47. feat: add citation/reference support to deep research reports (#1143)

- 提交：`[9809af1](https://github.com/bytedance/deer-flow/commit/9809af1f26982f73532296ddeb35a0875836ab52)`
- 日期：2026-03-17
- 做了什么：新增或增强功能，主题是“add citation/reference support to deep research reports (#1143)”。
- 影响范围：主要涉及 前端、技能体系、后端。
- 改动规模：+128 / -10 行。
- 关键文件：backend/packages/harness/deerflow/agents/lead_agent/prompt.py；frontend/src/components/workspace/artifacts/artifact-file-detail.tsx；frontend/src/components/workspace/citations/artifact-link.tsx；frontend/src/components/workspace/messages/markdown-content.tsx；skills/public/github-deep-research/SKILL.md；skills/public/github-deep-research/assets/report_template.md。

#### 48. feat(feishu): stream updates on a single card (#1031)

- 提交：`[9b49a80](https://github.com/bytedance/deer-flow/commit/9b49a80ddafc0826e808f35677d153d9e310ff40)`
- 日期：2026-03-14
- 做了什么：新增或增强功能，主题是“stream updates on a single card (#1031)”。
- 影响范围：主要涉及 后端。
- 改动规模：+716 / -55 行。
- 关键文件：backend/CLAUDE.md；backend/README.md；backend/src/channels/feishu.py；backend/src/channels/manager.py；backend/src/channels/service.py；backend/tests/test_channels.py。

#### 49. feat: add LoopDetectionMiddleware to break repetitive tool call loops (#1056)

- 提交：`[d18a9ae](https://github.com/bytedance/deer-flow/commit/d18a9ae5aaf579d367b321f07130857faaf75214)`
- 日期：2026-03-14
- 做了什么：新增或增强功能，主题是“add LoopDetectionMiddleware to break repetitive tool call loops (#1056)”。
- 影响范围：主要涉及 后端。
- 改动规模：+462 / -0 行。
- 关键文件：backend/src/agents/lead_agent/agent.py；backend/src/agents/middlewares/loop_detection_middleware.py；backend/tests/test_loop_detection_middleware.py。

#### 50. Add MiniMax as an OpenAI-compatible model provider (#1120)

- 提交：`[bbd87df](https://github.com/bytedance/deer-flow/commit/bbd87df6ebccb74c010fce96456d5a3d3095359a)`
- 日期：2026-03-14
- 做了什么：新增或增强功能，主题是“Add MiniMax as an OpenAI-compatible model provider (#1120)”。
- 影响范围：主要涉及 后端、其他模块、配置。
- 改动规模：+131 / -0 行。
- 关键文件：.env.example；backend/docs/CONFIGURATION.md；backend/tests/test_model_factory.py；config.example.yaml。

#### 51. feat(sandbox): harden local file access and mask host paths (#983)

- 提交：`[253fe4d](https://github.com/bytedance/deer-flow/commit/253fe4d87fb8128c5e5633c3a7ee81f99fb32b71)`
- 日期：2026-03-13
- 做了什么：新增或增强功能，主题是“harden local file access and mask host paths (#983)”。
- 影响范围：主要涉及 后端。
- 改动规模：+282 / -39 行。
- 关键文件：backend/src/sandbox/tools.py；backend/tests/test_sandbox_tools_security.py。

#### 52. feat: enhance Docker support with production setup and deployment script (#1086)

- 提交：`[08ea9d3](https://github.com/bytedance/deer-flow/commit/08ea9d3038e2663fdb35555f733deb58bf2c7ae1)`
- 日期：2026-03-12
- 做了什么：新增或增强功能，主题是“enhance Docker support with production setup and deployment script (#1086)”。
- 影响范围：主要涉及 后端、其他模块、容器部署。
- 改动规模：+444 / -24 行。
- 关键文件：.gitignore；Makefile；README.md；backend/Dockerfile；backend/langgraph.json；backend/uv.lock；docker/docker-compose-dev.yaml；docker/docker-compose.yaml。

#### 53. feat: add dev-daemon target for background development mode (#1047)

- 提交：`[a0c38a5](https://github.com/bytedance/deer-flow/commit/a0c38a5cf307f4ae9c638770f67d13e2e314c954)`
- 日期：2026-03-11
- 做了什么：新增或增强功能，主题是“add dev-daemon target for background development mode (#1047)”。
- 影响范围：主要涉及 其他模块、脚本工具。
- 改动规模：+135 / -1 行。
- 关键文件：Makefile；scripts/start-daemon.sh。

#### 54. feat: add `make start` command for local previewing (#1078)

- 提交：`[2e7964d](https://github.com/bytedance/deer-flow/commit/2e7964d0aaa294cae69c53dcc70a254a287f35e6)`
- 日期：2026-03-11
- 做了什么：新增或增强功能，主题是“add `make start` command for local previewing (#1078)”。
- 影响范围：主要涉及 脚本工具、其他模块。
- 改动规模：+280 / -220 行。
- 关键文件：Makefile；scripts/check.sh；scripts/serve.sh；scripts/start.sh。

#### 55. chore(docker): Refactor sandbox state management and improve Docker integration (#1068)

- 提交：`[f836d8e](https://github.com/bytedance/deer-flow/commit/f836d8e17c83eb8610cb599925af5558e2138582)`
- 日期：2026-03-11
- 做了什么：新增或增强功能，主题是“Refactor sandbox state management and improve Docker integration (#1068)”。
- 影响范围：主要涉及 后端、脚本工具、配置。
- 改动规模：+454 / -383 行。
- 关键文件：backend/Dockerfile；backend/src/community/aio_sandbox/**init**.py；backend/src/community/aio_sandbox/aio_sandbox_provider.py；backend/src/community/aio_sandbox/file_state_store.py；backend/src/community/aio_sandbox/local_backend.py；backend/src/community/aio_sandbox/state_store.py；backend/src/config/extensions_config.py；backend/src/config/paths.py。

#### 56. feat(middleware): introduce TodoMiddleware for context-loss detection in todo management (#1041)

- 提交：`[f5bd691](https://github.com/bytedance/deer-flow/commit/f5bd691172ecd07dfe70af30fca5a123492a679c)`
- 日期：2026-03-10
- 做了什么：新增或增强功能，主题是“introduce TodoMiddleware for context-loss detection in todo management (#1041)”。
- 影响范围：主要涉及 后端、前端。
- 改动规模：+125 / -19 行。
- 关键文件：backend/src/agents/lead_agent/agent.py；backend/src/agents/middlewares/todo_middleware.py；backend/src/gateway/routers/suggestions.py；backend/src/models/factory.py；backend/src/sandbox/tools.py；frontend/src/components/workspace/chats/chat-box.tsx；frontend/src/core/messages/utils.ts；frontend/src/core/threads/hooks.ts。

#### 57. feat(channels): upload file attachments via IM channels (Slack, Telegram, Feishu) (#1040)

- 提交：`[33f086b](https://github.com/bytedance/deer-flow/commit/33f086b6120e265ba2f0190667d4c7afdc902375)`
- 日期：2026-03-10
- 做了什么：新增或增强功能，主题是“upload file attachments via IM channels (Slack, Telegram, Feishu) (#1040)”。
- 影响范围：主要涉及 后端、文档。
- 改动规模：+720 / -15 行。
- 关键文件：README.md；backend/src/channels/base.py；backend/src/channels/feishu.py；backend/src/channels/manager.py；backend/src/channels/message_bus.py；backend/src/channels/slack.py；backend/src/channels/telegram.py；backend/tests/test_channel_file_attachments.py。

#### 58. feat(dev): refactor service startup to use dedicated start script (#1042)

- 提交：`[f6508e0](https://github.com/bytedance/deer-flow/commit/f6508e06774799342717b237e08e76f583090f28)`
- 日期：2026-03-10
- 做了什么：新增或增强功能，主题是“refactor service startup to use dedicated start script (#1042)”。
- 影响范围：主要涉及 脚本工具、其他模块。
- 改动规模：+171 / -92 行。
- 关键文件：Makefile；scripts/start.sh；scripts/wait-for-port.sh。

#### 59. Revert "feat(threads): paginate full history via summaries endpoint (#1022)" (#1037)

- 提交：`[46918f0](https://github.com/bytedance/deer-flow/commit/46918f07864fc327e8e69e939a6496bdfe3881dd)`
- 日期：2026-03-09
- 做了什么：新增或增强功能，主题是“Revert "feat(threads): paginate full history via summaries endpoint (#1022)" (#1037)”。
- 影响范围：主要涉及 后端、前端。
- 改动规模：+24 / -361 行。
- 关键文件：backend/src/gateway/app.py；backend/src/gateway/routers/**init**.py；backend/src/gateway/routers/threads.py；backend/tests/test_threads_router.py；frontend/src/core/threads/hooks.ts；frontend/src/core/threads/types.ts；frontend/src/core/threads/utils.ts。

#### 60. feat(threads): paginate full history via summaries endpoint (#1022)

- 提交：`[2f47f1c](https://github.com/bytedance/deer-flow/commit/2f47f1ced216a257bc56fd06a2dec578be36e15d)`
- 日期：2026-03-09
- 做了什么：新增或增强功能，主题是“paginate full history via summaries endpoint (#1022)”。
- 影响范围：主要涉及 后端、前端。
- 改动规模：+361 / -24 行。
- 关键文件：backend/src/gateway/app.py；backend/src/gateway/routers/**init**.py；backend/src/gateway/routers/threads.py；backend/tests/test_threads_router.py；frontend/src/core/threads/hooks.ts；frontend/src/core/threads/types.ts；frontend/src/core/threads/utils.ts。

#### 61. feat(channels): make mobile session settings configurable by channel and user (#1021)

- 提交：`[ac1e191](https://github.com/bytedance/deer-flow/commit/ac1e1915efc098db27ff2b95a2a81a9be2d31904)`
- 日期：2026-03-08
- 做了什么：新增或增强功能，主题是“make mobile session settings configurable by channel and user (#1021)”。
- 影响范围：主要涉及 后端、文档、配置。
- 改动规模：+252 / -8 行。
- 关键文件：README.md；backend/src/channels/manager.py；backend/src/channels/service.py；backend/tests/test_channels.py；config.example.yaml。

#### 62. feat: add claude-to-deerflow skill for DeerFlow API integration (#1024)

- 提交：`[8871fca](https://github.com/bytedance/deer-flow/commit/8871fca5cbe2d4f9b68139d549b7c2b7f7313a63)`
- 日期：2026-03-08
- 做了什么：新增或增强功能，主题是“add claude-to-deerflow skill for DeerFlow API integration (#1024)”。
- 影响范围：主要涉及 技能体系、文档、后端。
- 改动规模：+597 / -3 行。
- 关键文件：README.md；backend/src/channels/telegram.py；skills/public/claude-to-deerflow/SKILL.md；skills/public/claude-to-deerflow/scripts/chat.sh；skills/public/claude-to-deerflow/scripts/status.sh。

#### 63. Update Nginx configuration for uploads and improve thread ID handling (#1023)

- 提交：`[3721c82](https://github.com/bytedance/deer-flow/commit/3721c82ba838d59c4e3ad70b4e2466293bb275af)`
- 日期：2026-03-08
- 做了什么：新增或增强功能，主题是“Update Nginx configuration for uploads and improve thread ID handling (#1023)”。
- 影响范围：主要涉及 容器部署、前端。
- 改动规模：+42 / -28 行。
- 关键文件：docker/nginx/nginx.conf；docker/nginx/nginx.local.conf；frontend/src/core/threads/hooks.ts。

#### 64. Enhance chat UI and compatible anthropic thinking messages (#1018)

- 提交：`[cf9af1f](https://github.com/bytedance/deer-flow/commit/cf9af1fe75fd1d3e216286afb57354486cded64a)`
- 日期：2026-03-08
- 做了什么：新增或增强功能，主题是“Enhance chat UI and compatible anthropic thinking messages (#1018)”。
- 影响范围：主要涉及 前端、后端。
- 改动规模：+213 / -129 行。
- 关键文件：backend/src/agents/middlewares/title_middleware.py；backend/src/sandbox/local/local_sandbox.py；backend/tests/test_title_middleware_core_logic.py；frontend/src/components/workspace/artifacts/context.tsx；frontend/src/components/workspace/chats/chat-box.tsx；frontend/src/components/workspace/messages/message-list.tsx；frontend/src/components/workspace/thread-title.tsx；frontend/src/core/messages/utils.ts。

#### 65. feat: add thinking settings to compatible anthropic api (#1017)

- 提交：`[3512279](https://github.com/bytedance/deer-flow/commit/3512279ce3be0d30d52160879dac21fef9c40bce)`
- 日期：2026-03-08
- 做了什么：新增或增强功能，主题是“add thinking settings to compatible anthropic api (#1017)”。
- 影响范围：主要涉及 后端、配置。
- 改动规模：+443 / -6 行。
- 关键文件：backend/src/config/model_config.py；backend/src/models/factory.py；backend/tests/test_model_factory.py；config.example.yaml。

#### 66. feat: add IM channels for Feishu, Slack, and Telegram (#1010)

- 提交：`[75b7302](https://github.com/bytedance/deer-flow/commit/75b7302000c066bf2ff1ba362ee6a6337d6bfc47)`
- 日期：2026-03-08
- 做了什么：新增或增强功能，主题是“add IM channels for Feishu, Slack, and Telegram (#1010)”。
- 影响范围：主要涉及 后端、技能体系、其他模块。
- 改动规模：+8326 / -339 行。
- 关键文件：.env.example；README.md；backend/CLAUDE.md；backend/docs/TODO.md；backend/pyproject.toml；backend/src/agents/memory/prompt.py；backend/src/agents/memory/updater.py；backend/src/agents/middlewares/memory_middleware.py。

#### 67. feat: may_ask (#981)

- 提交：`[9d2144d](https://github.com/bytedance/deer-flow/commit/9d2144d431a81960936fb9ae313a34f698c4d236)`
- 日期：2026-03-06
- 做了什么：新增或增强功能，主题是“may_ask (#981)”。
- 影响范围：主要涉及 前端、后端。
- 改动规模：+462 / -35 行。
- 关键文件：backend/src/gateway/app.py；backend/src/gateway/routers/**init**.py；backend/src/gateway/routers/suggestions.py；backend/tests/test_suggestions_router.py；frontend/src/app/workspace/agents/[agent_name]/chats/[thread_id]/page.tsx；frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/workspace/input-box.tsx；frontend/src/core/i18n/locales/en-US.ts。

#### 68. chore(ci):add copilot instructions file (#996)

- 提交：`[cfae751](https://github.com/bytedance/deer-flow/commit/cfae7519022e7e8958a990cd9d92876fa9e83b09)`
- 日期：2026-03-06
- 做了什么：新增或增强功能，主题是“add copilot instructions file (#996)”。
- 影响范围：主要涉及 CI/CD。
- 改动规模：+213 / -0 行。
- 关键文件：.github/copilot-instructions.md。

#### 69. Implement optimistic UI for file uploads and enhance message handling (#967)

- 提交：`[b17c087](https://github.com/bytedance/deer-flow/commit/b17c087174cc5999392fe6160ba2fe3692acefa1)`
- 日期：2026-03-05
- 做了什么：新增或增强功能，主题是“Implement optimistic UI for file uploads and enhance message handling (#967)”。
- 影响范围：主要涉及 前端、后端。
- 改动规模：+787 / -255 行。
- 关键文件：backend/src/agents/middlewares/uploads_middleware.py；backend/tests/test_uploads_middleware_core_logic.py；frontend/src/components/workspace/messages/message-list-item.tsx；frontend/src/components/workspace/thread-title.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts；frontend/src/core/i18n/locales/zh-CN.ts；frontend/src/core/messages/utils.ts。

#### 70. Add CORS_ORIGINS to .env.example for custom frontend port support (#969)

- 提交：`[7149f0c](https://github.com/bytedance/deer-flow/commit/7149f0c9b56b8de32e11a7606b4cdcd2ae93a818)`
- 日期：2026-03-04
- 做了什么：新增或增强功能，主题是“Add CORS_ORIGINS to .env.example for custom frontend port support (#969)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+3 / -0 行。
- 关键文件：.env.example。

#### 71. docs: add make install step before local dev (#955) (#963)

- 提交：`[4525952](https://github.com/bytedance/deer-flow/commit/452595255e99c7c62fe91b210920670cb533d606)`
- 日期：2026-03-04
- 做了什么：补充文档能力，主题是“add make install step before local dev (#955) (#963)”。
- 影响范围：主要涉及 文档。
- 改动规模：+8 / -3 行。
- 关键文件：README.md。

#### 72. Refactor hooks and improve error handling in chat functionality (#962)

- 提交：`[14d1e01](https://github.com/bytedance/deer-flow/commit/14d1e01149177ac4f15dc0c9c936f7ee8790ace3)`
- 日期：2026-03-04
- 做了什么：新增或增强功能，主题是“Refactor hooks and improve error handling in chat functionality (#962)”。
- 影响范围：主要涉及 前端、后端。
- 改动规模：+46 / -37 行。
- 关键文件：backend/src/agents/lead_agent/agent.py；frontend/src/app/workspace/agents/[agent_name]/chats/[thread_id]/page.tsx；frontend/src/app/workspace/agents/new/page.tsx；frontend/src/components/workspace/artifacts/artifact-trigger.tsx；frontend/src/components/workspace/chats/use-thread-chat.ts；frontend/src/core/threads/hooks.ts。

#### 73. feat(agent):Supports custom agent and chat experience with refactoring (#957)

- 提交：`[7de9439](https://github.com/bytedance/deer-flow/commit/7de94394d4295182701ffb47e938e7c39b963091)`
- 日期：2026-03-03
- 做了什么：新增或增强功能，主题是“Supports custom agent and chat experience with refactoring (#957)”。
- 影响范围：主要涉及 前端、后端、技能体系。
- 改动规模：+3001 / -502 行。
- 关键文件：Makefile；backend/src/agents/lead_agent/agent.py；backend/src/agents/lead_agent/prompt.py；backend/src/agents/memory/queue.py；backend/src/agents/memory/updater.py；backend/src/agents/middlewares/memory_middleware.py；backend/src/config/agents_config.py；backend/src/config/paths.py。

#### 74. feat(skills): support recursive nested skill loading (#950)

- 提交：`[7754c49](https://github.com/bytedance/deer-flow/commit/7754c49217bb111ab528e87f8570c6e6725dc05c)`
- 日期：2026-03-02
- 做了什么：新增或增强功能，主题是“support recursive nested skill loading (#950)”。
- 影响范围：主要涉及 后端。
- 改动规模：+79 / -13 行。
- 关键文件：backend/CLAUDE.md；backend/README.md；backend/src/skills/loader.py；backend/src/skills/parser.py；backend/src/skills/types.py；backend/tests/test_skills_loader.py。

#### 75. feat: add reasoning_effort configuration support for Doubao/GPT-5 models (#947)

- 提交：`[a138d53](https://github.com/bytedance/deer-flow/commit/a138d5388ab807b85d6f03c20d2ba59a764d84cf)`
- 日期：2026-03-02
- 做了什么：新增或增强功能，主题是“add reasoning_effort configuration support for Doubao/GPT-5 models (#947)”。
- 影响范围：主要涉及 后端、前端、其他模块。
- 改动规模：+212 / -33 行。
- 关键文件：.gitignore；backend/src/agents/lead_agent/agent.py；backend/src/client.py；backend/src/config/app_config.py；backend/src/config/extensions_config.py；backend/src/config/model_config.py；backend/src/gateway/routers/models.py；backend/src/models/factory.py。

#### 76. refactor(frontend): optimize network queries and improve code readability (#919)

- 提交：`[72df234](https://github.com/bytedance/deer-flow/commit/72df234636ed8199ab7169e01f435d4f0518124e)`
- 日期：2026-03-02
- 做了什么：新增或增强功能，主题是“optimize network queries and improve code readability (#919)”。
- 影响范围：主要涉及 前端。
- 改动规模：+15 / -29 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/core/models/api.ts；frontend/src/core/models/hooks.ts；frontend/src/core/threads/hooks.ts；frontend/src/core/threads/utils.ts。

#### 77. feat(mcp): add OAuth support for HTTP/SSE MCP servers (#908)

- 提交：`[a2f91c7](https://github.com/bytedance/deer-flow/commit/a2f91c75946a2e8eccb86127f89a34aa5fe4655d)`
- 日期：2026-03-01
- 做了什么：新增或增强功能，主题是“add OAuth support for HTTP/SSE MCP servers (#908)”。
- 影响范围：主要涉及 后端、文档、其他模块。
- 改动规模：+497 / -20 行。
- 关键文件：README.md；backend/CLAUDE.md；backend/README.md；backend/docs/API.md；backend/docs/MCP_SERVER.md；backend/src/config/extensions_config.py；backend/src/gateway/routers/mcp.py；backend/src/mcp/oauth.py。

#### 78. test(backend): add core logic unit tests for task/title/mcp (#936)

- 提交：`[3d3ea84](https://github.com/bytedance/deer-flow/commit/3d3ea84a5796c7c2558c1ada50cad60a8595a573)`
- 日期：2026-03-01
- 做了什么：补充/增强测试体系，主题是“add core logic unit tests for task/title/mcp (#936)”。
- 影响范围：主要涉及 后端。
- 改动规模：+460 / -6 行。
- 关键文件：backend/tests/test_client.py；backend/tests/test_client_live.py；backend/tests/test_mcp_client_config.py；backend/tests/test_task_tool_core_logic.py；backend/tests/test_title_middleware_core_logic.py。

### Bug 修复

#### 1. fix(sandbox): serialize concurrent exec_command calls in AioSandbox (#1435)

- 提交：`[a3bfea6](https://github.com/bytedance/deer-flow/commit/a3bfea631c2af0a3ef65e22abf0ed37bdca8123b)`
- 日期：2026-03-31
- 做了什么：修复缺陷或回归问题，主题是“serialize concurrent exec_command calls in AioSandbox (#1435)”。
- 影响范围：主要涉及 后端。
- 改动规模：+173 / -18 行。
- 关键文件：backend/packages/harness/deerflow/community/aio_sandbox/aio_sandbox.py；backend/tests/test_aio_sandbox.py。

#### 2. fix: surface configured sandbox mounts to agents (#1638)

- 提交：`[aae59a8](https://github.com/bytedance/deer-flow/commit/aae59a8ba894c74ee455891cd692f257baafdf8f)`
- 日期：2026-03-31
- 做了什么：修复缺陷或回归问题，主题是“surface configured sandbox mounts to agents (#1638)”。
- 影响范围：主要涉及 后端、配置。
- 改动规模：+93 / -2 行。
- 关键文件：backend/docs/CONFIGURATION.md；backend/packages/harness/deerflow/agents/lead_agent/prompt.py；backend/packages/harness/deerflow/runtime/runs/manager.py；backend/packages/harness/deerflow/subagents/builtins/bash_agent.py；backend/packages/harness/deerflow/subagents/builtins/general_purpose.py；backend/tests/test_lead_agent_prompt.py；backend/tests/test_run_manager.py；config.example.yaml。

#### 3. fix Windows Docker sandbox path mounting (#1634)

- 提交：`[3ff1542](https://github.com/bytedance/deer-flow/commit/3ff15423d651e98cc99791a85e3a20607ee2c75e)`
- 日期：2026-03-31
- 做了什么：修复缺陷或回归问题，主题是“fix Windows Docker sandbox path mounting (#1634)”。
- 影响范围：主要涉及 后端、容器部署。
- 改动规模：+158 / -27 行。
- 关键文件：backend/packages/harness/deerflow/community/aio_sandbox/aio_sandbox_provider.py；backend/packages/harness/deerflow/config/paths.py；backend/packages/harness/deerflow/runtime/runs/manager.py；backend/tests/test_aio_sandbox_provider.py；backend/tests/test_docker_sandbox_mode_detection.py；docker/provisioner/app.py。

#### 4. fix(tools): move sandbox.tools import in view_image_tool to break circular import (#1674)

- 提交：`[c2f7be3](https://github.com/bytedance/deer-flow/commit/c2f7be37b3104d3248b3203fc7d0fd920d128346)`
- 日期：2026-03-31
- 做了什么：修复缺陷或回归问题，主题是“move sandbox.tools import in view_image_tool to break circular import (#1674)”。
- 影响范围：主要涉及 后端。
- 改动规模：+2 / -1 行。
- 关键文件：backend/packages/harness/deerflow/tools/builtins/view_image_tool.py。

#### 5. fix: improve Windows compatibility in dependency check (#1550)

- 提交：`[09a9209](https://github.com/bytedance/deer-flow/commit/09a9209724c54edc09168fa6a1af563f7c3cf534)`
- 日期：2026-03-31
- 做了什么：修复缺陷或回归问题，主题是“improve Windows compatibility in dependency check (#1550)”。
- 影响范围：主要涉及 脚本工具。
- 改动规模：+15 / -2 行。
- 关键文件：scripts/check.py。

#### 6. fix(frontend): improve network error message for agent name check  (#1605)

- 提交：`[b356a13](https://github.com/bytedance/deer-flow/commit/b356a13da572848e8e31c74b7060510282c61299)`
- 日期：2026-03-31
- 做了什么：修复缺陷或回归问题，主题是“improve network error message for agent name check  (#1605)”。
- 影响范围：主要涉及 前端。
- 改动规模：+10 / -11 行。
- 关键文件：frontend/src/app/workspace/agents/new/page.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts；frontend/src/core/i18n/locales/zh-CN.ts。

#### 7. fix(langgraph): correct config.yaml mount path in docker-compose (#1679)

- 提交：`[ac9a6ee](https://github.com/bytedance/deer-flow/commit/ac9a6ee6a25da477f00a287a01922678fa405776)`
- 日期：2026-03-31
- 做了什么：修复缺陷或回归问题，主题是“correct config.yaml mount path in docker-compose (#1679)”。
- 影响范围：主要涉及 容器部署。
- 改动规模：+4 / -4 行。
- 关键文件：docker/docker-compose.yaml。

#### 8. fix: remove LANGSMITH_TRACING override that ignores .env value (#1640)

- 提交：`[64e0f53](https://github.com/bytedance/deer-flow/commit/64e0f5329a2a5f17a9b6cb13c6b6b116ecbbe24f)`
- 日期：2026-03-31
- 做了什么：修复缺陷或回归问题，主题是“remove LANGSMITH_TRACING override that ignores .env value (#1640)”。
- 影响范围：主要涉及 容器部署。
- 改动规模：+1 / -3 行。
- 关键文件：docker/docker-compose.yaml。

#### 9. fix(frontend): route agent checks to gateway (#1572)

- 提交：`[9e3d484](https://github.com/bytedance/deer-flow/commit/9e3d4848589f4dd266aeed82a9056ccac689c69c)`
- 日期：2026-03-30
- 做了什么：修复缺陷或回归问题，主题是“route agent checks to gateway (#1572)”。
- 影响范围：主要涉及 前端、容器部署。
- 改动规模：+97 / -9 行。
- 关键文件：docker/docker-compose-dev.yaml；docker/docker-compose.yaml；frontend/next.config.js；frontend/src/app/workspace/agents/new/page.tsx；frontend/src/core/agents/api.ts；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/zh-CN.ts。

#### 10. fix: run uv sync before dev services to keep venv up-to-date (#1626)

- 提交：`[b21792d](https://github.com/bytedance/deer-flow/commit/b21792d9bec26e32af70596ba10b49bb4b9784ec)`
- 日期：2026-03-30
- 做了什么：修复缺陷或回归问题，主题是“run uv sync before dev services to keep venv up-to-date (#1626)”。
- 影响范围：主要涉及 容器部署。
- 改动规模：+2 / -2 行。
- 关键文件：docker/docker-compose-dev.yaml。

#### 11. fix: add --n-jobs-per-worker 10 to langgraph dev command in Docker (#1623)

- 提交：`[0f1b023](https://github.com/bytedance/deer-flow/commit/0f1b023a2af71ab4ff25c3f5696c6beef016be4c)`
- 日期：2026-03-30
- 做了什么：修复缺陷或回归问题，主题是“add --n-jobs-per-worker 10 to langgraph dev command in Docker (#1623)”。
- 影响范围：主要涉及 容器部署。
- 改动规模：+2 / -2 行。
- 关键文件：docker/docker-compose-dev.yaml；docker/docker-compose.yaml。

#### 12. fix(config): update SSR fallback in getBaseOrigin function (#1617)

- 提交：`[2330c38](https://github.com/bytedance/deer-flow/commit/2330c382095182b3cb487a04c68ca2bfde75520e)`
- 日期：2026-03-30
- 做了什么：修复缺陷或回归问题，主题是“update SSR fallback in getBaseOrigin function (#1617)”。
- 影响范围：主要涉及 前端。
- 改动规模：+2 / -1 行。
- 关键文件：frontend/src/core/config/index.ts。

#### 13. fix: promote deferred tools after tool_search returns schema (#1570)

- 提交：`[9bcdba6](https://github.com/bytedance/deer-flow/commit/9bcdba6038425545a31cde800ae7bcd1dfd64efe)`
- 日期：2026-03-30
- 做了什么：修复缺陷或回归问题，主题是“promote deferred tools after tool_search returns schema (#1570)”。
- 影响范围：主要涉及 后端。
- 改动规模：+137 / -1 行。
- 关键文件：backend/packages/harness/deerflow/tools/builtins/tool_search.py；backend/tests/test_tool_search.py。

#### 14. fix(config): correct MiniMax M2.7 highspeed model name and add thinking support (#1596)

- 提交：`[ef58bb8](https://github.com/bytedance/deer-flow/commit/ef58bb8d3cb313de5002d3874f7f863bbe949693)`
- 日期：2026-03-30
- 做了什么：修复缺陷或回归问题，主题是“correct MiniMax M2.7 highspeed model name and add thinking support (#1596)”。
- 影响范围：主要涉及 配置。
- 改动规模：+7 / -3 行。
- 关键文件：config.example.yaml。

#### 15. fix(dev): exclude sandbox dirs from gateway hot-reload watcher (#1519)

- 提交：`[c5034c0](https://github.com/bytedance/deer-flow/commit/c5034c03c7802c289678d0c0b1763f370a2268ee)`
- 日期：2026-03-30
- 做了什么：修复缺陷或回归问题，主题是“exclude sandbox dirs from gateway hot-reload watcher (#1519)”。
- 影响范围：主要涉及 脚本工具。
- 改动规模：+1 / -1 行。
- 关键文件：scripts/serve.sh。

#### 16. fix(oauth): Harden Claude OAuth cache-control handling (#1583)

- 提交：`[5ceb19f](https://github.com/bytedance/deer-flow/commit/5ceb19f6f650c397569177fda5e5129768364f71)`
- 日期：2026-03-29
- 做了什么：修复缺陷或回归问题，主题是“Harden Claude OAuth cache-control handling (#1583)”。
- 影响范围：主要涉及 后端。
- 改动规模：+80 / -2 行。
- 关键文件：backend/packages/harness/deerflow/models/claude_provider.py；backend/tests/test_claude_provider_oauth_billing.py。

#### 17. fix(sandbox): anchor relative paths to thread workspace in local mode (#1522)

- 提交：`[cdb2a3a](https://github.com/bytedance/deer-flow/commit/cdb2a3a017f61a0cbb61def39a3949ee1bd9defe)`
- 日期：2026-03-29
- 做了什么：修复缺陷或回归问题，主题是“anchor relative paths to thread workspace in local mode (#1522)”。
- 影响范围：主要涉及 后端。
- 改动规模：+47 / -0 行。
- 关键文件：backend/packages/harness/deerflow/sandbox/tools.py；backend/tests/test_sandbox_tools_security.py。

#### 18. fix(frontend): prevent submit during IME composition (#1562)

- 提交：`[866cf4e](https://github.com/bytedance/deer-flow/commit/866cf4ef7338ab217b7421ae6035f338e4676346)`
- 日期：2026-03-29
- 做了什么：修复缺陷或回归问题，主题是“prevent submit during IME composition (#1562)”。
- 影响范围：主要涉及 前端。
- 改动规模：+17 / -3 行。
- 关键文件：frontend/src/app/workspace/agents/new/page.tsx；frontend/src/components/ai-elements/prompt-input.tsx；frontend/src/components/workspace/recent-chat-list.tsx；frontend/src/lib/ime.ts。

#### 19. docs: fix some broken links (#1567)

- 提交：`[d475de7](https://github.com/bytedance/deer-flow/commit/d475de799793a86d3737d7d0c387c4b72f02f165)`
- 日期：2026-03-29
- 做了什么：修复缺陷或回归问题，主题是“fix some broken links (#1567)”。
- 影响范围：主要涉及 后端、前端。
- 改动规模：+6 / -6 行。
- 关键文件：backend/docs/AUTO_TITLE_GENERATION.md；backend/docs/CONFIGURATION.md；backend/docs/TITLE_GENERATION_IMPLEMENTATION.md；frontend/public/demo/threads/7f9dc56c-e49c-4671-a3d2-c492ff4dce0c/user-data/outputs/leica-master-photography-article.md。

#### 20. fix(nginx): re-resolve upstream DNS in Docker (#1517)

- 提交：`[75c4757](https://github.com/bytedance/deer-flow/commit/75c4757f48409cd26edc805dcba7a0f008060233)`
- 日期：2026-03-29
- 做了什么：修复缺陷或回归问题，主题是“re-resolve upstream DNS in Docker (#1517)”。
- 影响范围：主要涉及 容器部署。
- 改动规模：+8 / -3 行。
- 关键文件：docker/nginx/nginx.conf。

#### 21. fix: use Git Bash for Windows local startup (#1551)

- 提交：`[580920e](https://github.com/bytedance/deer-flow/commit/580920ef63929ad60bea835bf043483f314db0dc)`
- 日期：2026-03-29
- 做了什么：修复缺陷或回归问题，主题是“use Git Bash for Windows local startup (#1551)”。
- 影响范围：主要涉及 其他模块、脚本工具。
- 改动规模：+22 / -4 行。
- 关键文件：Makefile；scripts/run-with-git-bash.cmd。

#### 22. fix: add Windows shell fallback for local sandbox (#1505)

- 提交：`[68c9e09](https://github.com/bytedance/deer-flow/commit/68c9e09a7aeaff10cbe1778a32c000e3abbdf1c5)`
- 日期：2026-03-29
- 做了什么：修复缺陷或回归问题，主题是“add Windows shell fallback for local sandbox (#1505)”。
- 影响范围：主要涉及 后端。
- 改动规模：+209 / -20 行。
- 关键文件：backend/packages/harness/deerflow/sandbox/local/local_sandbox.py；backend/tests/test_local_sandbox_encoding.py。

#### 23. fix(docs): Correct security usage recommendations in README_zh.md (#1548)

- 提交：`[8b6c333](https://github.com/bytedance/deer-flow/commit/8b6c333afc26d7b4dce5a624b5085a7f49c72103)`
- 日期：2026-03-29
- 做了什么：修复缺陷或回归问题，主题是“Correct security usage recommendations in README_zh.md (#1548)”。
- 影响范围：主要涉及 文档。
- 改动规模：+1 / -1 行。
- 关键文件：README_zh.md。

#### 24. fix(sandbox): fall back to config.configurable for thread_id in lazy sandbox init (#1529)

- 提交：`[118485a](https://github.com/bytedance/deer-flow/commit/118485a7cb0242623937600200957247b5383a87)`
- 日期：2026-03-29
- 做了什么：修复缺陷或回归问题，主题是“fall back to config.configurable for thread_id in lazy sandbox init (#1529)”。
- 影响范围：主要涉及 后端。
- 改动规模：+2 / -0 行。
- 关键文件：backend/packages/harness/deerflow/sandbox/tools.py。

#### 25. fix(sandbox): allow MCP filesystem server paths in local bash commands (#1527)

- 提交：`[9e5ba74](https://github.com/bytedance/deer-flow/commit/9e5ba74ecd88a2fccfd80c2ba75ca91bf6008e47)`
- 日期：2026-03-29
- 做了什么：修复缺陷或回归问题，主题是“allow MCP filesystem server paths in local bash commands (#1527)”。
- 影响范围：主要涉及 后端。
- 改动规模：+72 / -0 行。
- 关键文件：backend/packages/harness/deerflow/sandbox/tools.py；backend/tests/test_sandbox_tools_security.py。

#### 26. fix(channel): reject concurrent same-thread runs (#1465) (#1475)

- 提交：`[89183ae](https://github.com/bytedance/deer-flow/commit/89183ae76a6cac22567c006b10ab8e0f5003371c)`
- 日期：2026-03-29
- 做了什么：修复缺陷或回归问题，主题是“reject concurrent same-thread runs (#1465) (#1475)”。
- 影响范围：主要涉及 后端。
- 改动规模：+74 / -2 行。
- 关键文件：backend/app/channels/manager.py；backend/tests/test_channels.py。

#### 27. fix(middleware): fall back to configurable thread_id in MemoryMiddleware (#1425) (#1426)

- 提交：`[520c035](https://github.com/bytedance/deer-flow/commit/520c0352b55034f4b061e3b866f20ff77d341d8a)`
- 日期：2026-03-28
- 做了什么：修复缺陷或回归问题，主题是“fall back to configurable thread_id in MemoryMiddleware (#1425) (#1426)”。
- 影响范围：主要涉及 后端。
- 改动规模：+5 / -1 行。
- 关键文件：backend/packages/harness/deerflow/agents/middlewares/memory_middleware.py。

#### 28. fix(task_tool): fallback to configurable thread_id when context is mi… (#1343)

- 提交：`[690d80f](https://github.com/bytedance/deer-flow/commit/690d80f46f09c615fc9500b959cec8f9181360f9)`
- 日期：2026-03-28
- 做了什么：修复缺陷或回归问题，主题是“fallback to configurable thread_id when context is mi… (#1343)”。
- 影响范围：主要涉及 后端。
- 改动规模：+2 / -0 行。
- 关键文件：backend/packages/harness/deerflow/tools/builtins/task_tool.py。

#### 29. Fix IM channel backend URLs in Docker (#1497)

- 提交：`[c2dd893](https://github.com/bytedance/deer-flow/commit/c2dd8937ed4dc4bb3888d3b61ac9f139421c4fa3)`
- 日期：2026-03-28
- 做了什么：修复缺陷或回归问题，主题是“Fix IM channel backend URLs in Docker (#1497)”。
- 影响范围：主要涉及 后端、容器部署、文档。
- 改动规模：+58 / -3 行。
- 关键文件：README.md；backend/CLAUDE.md；backend/app/channels/service.py；backend/tests/test_channels.py；config.example.yaml；docker/docker-compose-dev.yaml；docker/docker-compose.yaml。

#### 30. fix(frontend): separate mock and default LangGraph clients (#1504)

- 提交：`[9caea02](https://github.com/bytedance/deer-flow/commit/9caea0266e3640179ef279b4a7367761fd6a442a)`
- 日期：2026-03-28
- 做了什么：修复缺陷或回归问题，主题是“separate mock and default LangGraph clients (#1504)”。
- 影响范围：主要涉及 前端。
- 改动规模：+10 / -3 行。
- 关键文件：frontend/src/core/api/api-client.ts。

#### 31. fix: prevent SpeechRecognition instance leaks on render (#1369)

- 提交：`[49f2e38](https://github.com/bytedance/deer-flow/commit/49f2e38fbf6ceed1a617c6c8eca99133baaa7cc0)`
- 日期：2026-03-28
- 做了什么：修复缺陷或回归问题，主题是“prevent SpeechRecognition instance leaks on render (#1369)”。
- 影响范围：主要涉及 前端。
- 改动规模：+9 / -4 行。
- 关键文件：frontend/src/components/ai-elements/prompt-input.tsx。

#### 32. fix: refactor to use getBaseOrigin for URL construction in backend and LangGraph base URL functions (#1494)

- 提交：`[d22cab8](https://github.com/bytedance/deer-flow/commit/d22cab8614352d54b33b94c0b3d476f304b873cf)`
- 日期：2026-03-28
- 做了什么：修复缺陷或回归问题，主题是“refactor to use getBaseOrigin for URL construction in backend and LangGraph base URL functions (#1494)”。
- 影响范围：主要涉及 前端。
- 改动规模：+10 / -2 行。
- 关键文件：frontend/src/core/config/index.ts。

#### 33. fix(oauth): inject billing header for Claude oAuth Models (#1442)

- 提交：`[43ef369](https://github.com/bytedance/deer-flow/commit/43ef3691a5ce98a574a8fc073bec886bdb94c2d6)`
- 日期：2026-03-28
- 做了什么：修复缺陷或回归问题，主题是“inject billing header for Claude oAuth Models (#1442)”。
- 影响范围：主要涉及 后端。
- 改动规模：+167 / -1 行。
- 关键文件：backend/packages/harness/deerflow/models/claude_provider.py；backend/tests/test_claude_provider_oauth_billing.py。

#### 34. fix: replace print() with logging across harness package (#1282)

- 提交：`[03b144f](https://github.com/bytedance/deer-flow/commit/03b144f9c900c90de250d4ef80b6eb829d8a8618)`
- 日期：2026-03-27
- 做了什么：修复缺陷或回归问题，主题是“replace print() with logging across harness package (#1282)”。
- 影响范围：主要涉及 后端。
- 改动规模：+40 / -16 行。
- 关键文件：backend/packages/harness/deerflow/agents/lead_agent/prompt.py；backend/packages/harness/deerflow/agents/memory/queue.py；backend/packages/harness/deerflow/agents/middlewares/clarification_middleware.py；backend/packages/harness/deerflow/agents/middlewares/memory_middleware.py；backend/packages/harness/deerflow/agents/middlewares/thread_data_middleware.py；backend/packages/harness/deerflow/agents/middlewares/view_image_middleware.py；backend/packages/harness/deerflow/skills/loader.py；backend/packages/harness/deerflow/skills/parser.py。

#### 35. docs(SETUP): correct setup documentation links (#1478)

- 提交：`[18b0794](https://github.com/bytedance/deer-flow/commit/18b07941253caa1a14bde0efb0a40bbbec322e3a)`
- 日期：2026-03-27
- 做了什么：修复缺陷或回归问题，主题是“correct setup documentation links (#1478)”。
- 影响范围：主要涉及 后端。
- 改动规模：+2 / -2 行。
- 关键文件：backend/docs/SETUP.md。

#### 36. fix(sandbox): Relax upload permissions for aio sandbox sync (#1409)

- 提交：`[40a4acb](https://github.com/bytedance/deer-flow/commit/40a4acbbeda09530060509c6d7002ef17b7e2444)`
- 日期：2026-03-27
- 做了什么：修复缺陷或回归问题，主题是“Relax upload permissions for aio sandbox sync (#1409)”。
- 影响范围：主要涉及 后端。
- 改动规模：+104 / -0 行。
- 关键文件：backend/app/gateway/routers/uploads.py；backend/tests/test_uploads_router.py。

#### 37. fix(middleware): return proper content format when no images viewed (#1454)

- 提交：`[4708700](https://github.com/bytedance/deer-flow/commit/47087007238bdc6ca88f801613e3279318dde732)`
- 日期：2026-03-27
- 做了什么：修复缺陷或回归问题，主题是“return proper content format when no images viewed (#1454)”。
- 影响范围：主要涉及 后端。
- 改动规模：+2 / -1 行。
- 关键文件：backend/packages/harness/deerflow/agents/middlewares/view_image_middleware.py。

#### 38. fix(task): avoid blocking in task tool polling (#1320)

- 提交：`[43a19f9](https://github.com/bytedance/deer-flow/commit/43a19f96274ea30211a48a520a4c93ffc4aa3037)`
- 日期：2026-03-27
- 做了什么：修复缺陷或回归问题，主题是“avoid blocking in task tool polling (#1320)”。
- 影响范围：主要涉及 后端。
- 改动规模：+248 / -83 行。
- 关键文件：backend/packages/harness/deerflow/tools/builtins/task_tool.py；backend/tests/test_task_tool_core_logic.py。

#### 39. fix(config): add Docker service name guidance for channel URLs (#1437)

- 提交：`[9996505](https://github.com/bytedance/deer-flow/commit/99965057c1fcd1ae7238edebf1a18ad7baad3fdd)`
- 日期：2026-03-26
- 做了什么：修复缺陷或回归问题，主题是“add Docker service name guidance for channel URLs (#1437)”。
- 影响范围：主要涉及 配置。
- 改动规模：+3 / -0 行。
- 关键文件：config.example.yaml。

#### 40. fix: add build-arg support for proxies and mirrors in Docker builds (#1346)

- 提交：`[8ae0235](https://github.com/bytedance/deer-flow/commit/8ae023574eb816e2b3b5355b88d794e3fa0c4790)`
- 日期：2026-03-27
- 做了什么：修复缺陷或回归问题，主题是“add build-arg support for proxies and mirrors in Docker builds (#1346)”。
- 影响范围：主要涉及 容器部署、后端、前端。
- 改动规模：+59 / -7 行。
- 关键文件：backend/Dockerfile；docker/docker-compose-dev.yaml；docker/docker-compose.yaml；docker/provisioner/Dockerfile；frontend/Dockerfile。

#### 41. fix: remove unused radix Icon import from suggestion (#1368)

- 提交：`[d7bdb1a](https://github.com/bytedance/deer-flow/commit/d7bdb1a4b93f5da3f171f8006ff75e90c707dc65)`
- 日期：2026-03-26
- 做了什么：修复缺陷或回归问题，主题是“remove unused radix Icon import from suggestion (#1368)”。
- 影响范围：主要涉及 前端。
- 改动规模：+0 / -1 行。
- 关键文件：frontend/src/components/ai-elements/suggestion.tsx。

#### 42. fix(gateway): enforce safe download for active artifact MIME types to mitigate stored XSS (#1389)

- 提交：`[0d3cefa](https://github.com/bytedance/deer-flow/commit/0d3cefaa5a57f9c0bbaeabd2c391d474b33a6757)`
- 日期：2026-03-26
- 做了什么：修复缺陷或回归问题，主题是“enforce safe download for active artifact MIME types to mitigate stored XSS (#1389)”。
- 影响范围：主要涉及 后端、文档。
- 改动规模：+119 / -18 行。
- 关键文件：README.md；backend/CLAUDE.md；backend/app/gateway/routers/artifacts.py；backend/tests/test_artifacts_router.py。

#### 43. Fix Windows backend test compatibility (#1384)

- 提交：`[b9583f7](https://github.com/bytedance/deer-flow/commit/b9583f7204b1cc9cc4f5dd57ebd3882f2a19b463)`
- 日期：2026-03-26
- 做了什么：修复缺陷或回归问题，主题是“Fix Windows backend test compatibility (#1384)”。
- 影响范围：主要涉及 后端。
- 改动规模：+141 / -27 行。
- 关键文件：backend/packages/harness/deerflow/community/aio_sandbox/aio_sandbox_provider.py；backend/packages/harness/deerflow/models/credential_loader.py；backend/packages/harness/deerflow/sandbox/tools.py；backend/packages/harness/deerflow/skills/installer.py；backend/tests/test_aio_sandbox_provider.py；backend/tests/test_client.py；backend/tests/test_docker_sandbox_mode_detection.py；backend/tests/test_skills_installer.py。

#### 44. fix(config): return full URLs for backend and LangGraph base URLs (#1392)

- 提交：`[4d1a69a](https://github.com/bytedance/deer-flow/commit/4d1a69a9387de64a79a5b6641e929830d843c134)`
- 日期：2026-03-26
- 做了什么：修复缺陷或回归问题，主题是“return full URLs for backend and LangGraph base URLs (#1392)”。
- 影响范围：主要涉及 前端。
- 改动规模：+8 / -2 行。
- 关键文件：frontend/src/core/config/index.ts。

#### 45. fix(LLM): fixing Gemini thinking + tool calls via OpenAI gateway (#1180) (#1205)

- 提交：`[a087fe7](https://github.com/bytedance/deer-flow/commit/a087fe7bccd62a090480971dc1ba11c3581ba2d7)`
- 日期：2026-03-26
- 做了什么：修复缺陷或回归问题，主题是“fixing Gemini thinking + tool calls via OpenAI gateway (#1180) (#1205)”。
- 影响范围：主要涉及 后端、配置。
- 改动规模：+360 / -1 行。
- 关键文件：backend/docs/CONFIGURATION.md；backend/packages/harness/deerflow/models/patched_openai.py；backend/tests/test_patched_openai.py；config.example.yaml。

#### 46. fix(config): fix summarization model alias resolution (#1378)

- 提交：`[080a03f](https://github.com/bytedance/deer-flow/commit/080a03f3bc1472838ef9ad8ae2a59f79d74dcd33)`
- 日期：2026-03-26
- 做了什么：修复缺陷或回归问题，主题是“fix summarization model alias resolution (#1378)”。
- 影响范围：主要涉及 后端。
- 改动规模：+28 / -1 行。
- 关键文件：backend/packages/harness/deerflow/agents/lead_agent/agent.py；backend/tests/test_lead_agent_model_resolution.py。

#### 47. fix: align config.example.yaml to use GEMINI_API_KEY (#1367)

- 提交：`[792c49e](https://github.com/bytedance/deer-flow/commit/792c49e6af017d44fb344bb3cb900a1ee7d77ce5)`
- 日期：2026-03-25
- 做了什么：修复缺陷或回归问题，主题是“align config.example.yaml to use GEMINI_API_KEY (#1367)”。
- 影响范围：主要涉及 配置。
- 改动规模：+1 / -1 行。
- 关键文件：config.example.yaml。

#### 48. Fix command syntax for container image pull (#1349)

- 提交：`[afe325d](https://github.com/bytedance/deer-flow/commit/afe325d34e7d2eb7c5d28a541d4cf042eb83b3b9)`
- 日期：2026-03-25
- 做了什么：修复缺陷或回归问题，主题是“Fix command syntax for container image pull (#1349)”。
- 影响范围：主要涉及 后端。
- 改动规模：+1 / -1 行。
- 关键文件：backend/docs/APPLE_CONTAINER.md。

#### 49. fix: add null checks for runtime.context and tighten langgraph constraint (#1326)

- 提交：`[d7e5107](https://github.com/bytedance/deer-flow/commit/d7e510763d83d6ed0cd9be6485212005caace07a)`
- 日期：2026-03-25
- 做了什么：修复缺陷或回归问题，主题是“add null checks for runtime.context and tighten langgraph constraint (#1326)”。
- 影响范围：主要涉及 后端。
- 改动规模：+6 / -4 行。
- 关键文件：backend/packages/harness/deerflow/agents/middlewares/uploads_middleware.py；backend/packages/harness/deerflow/sandbox/middleware.py；backend/packages/harness/pyproject.toml。

#### 50. fix(frontend): add stable ids for chat resizable panels (#1341)

- 提交：`[adc51e5](https://github.com/bytedance/deer-flow/commit/adc51e541c36d9ce4181a4ab40602f155df56414)`
- 日期：2026-03-25
- 做了什么：修复缺陷或回归问题，主题是“add stable ids for chat resizable panels (#1341)”。
- 影响范围：主要涉及 前端。
- 改动规模：+8 / -0 行。
- 关键文件：frontend/src/components/workspace/chats/chat-box.tsx。

#### 51. docs: fix typo and grammar issues in docs (#1315)

- 提交：`[97ad67d](https://github.com/bytedance/deer-flow/commit/97ad67db6b93cc5623318286d69fdeacd6fff84d)`
- 日期：2026-03-25
- 做了什么：修复缺陷或回归问题，主题是“fix typo and grammar issues in docs (#1315)”。
- 影响范围：主要涉及 其他模块、后端。
- 改动规模：+3 / -3 行。
- 关键文件：SECURITY.md；backend/AGENTS.md。

#### 52. fix: add null checks for runtime.context in middlewares and tools (#1269)

- 提交：`[2eca58b](https://github.com/bytedance/deer-flow/commit/2eca58bd86e861b694647f224634a6680361b9b7)`
- 日期：2026-03-25
- 做了什么：修复缺陷或回归问题，主题是“add null checks for runtime.context in middlewares and tools (#1269)”。
- 影响范围：主要涉及 后端、脚本工具。
- 改动规模：+15 / -8 行。
- 关键文件：backend/packages/harness/deerflow/agents/middlewares/loop_detection_middleware.py；backend/packages/harness/deerflow/agents/middlewares/memory_middleware.py；backend/packages/harness/deerflow/agents/middlewares/uploads_middleware.py；backend/packages/harness/deerflow/sandbox/middleware.py；backend/packages/harness/deerflow/sandbox/tools.py；backend/packages/harness/deerflow/tools/builtins/present_file_tool.py；backend/packages/harness/deerflow/tools/builtins/setup_agent_tool.py；backend/packages/harness/deerflow/tools/builtins/task_tool.py。

#### 53. fix(middleware): use HumanMessage in LoopDetectionMiddleware for Anthropic compat (#1300)

- 提交：`[77b8ef7](https://github.com/bytedance/deer-flow/commit/77b8ef79cad6d77f2a445a980e636981deca9684)`
- 日期：2026-03-25
- 做了什么：修复缺陷或回归问题，主题是“use HumanMessage in LoopDetectionMiddleware for Anthropic compat (#1300)”。
- 影响范围：主要涉及 后端。
- 改动规模：+10 / -5 行。
- 关键文件：backend/packages/harness/deerflow/agents/middlewares/loop_detection_middleware.py；backend/tests/test_loop_detection_middleware.py。

#### 54. fix: add Windows compatibility for make dev/start commands (#1297)

- 提交：`[067b19a](https://github.com/bytedance/deer-flow/commit/067b19af00b9a5a7895cecf6073a571cd91fcf33)`
- 日期：2026-03-24
- 做了什么：修复缺陷或回归问题，主题是“add Windows compatibility for make dev/start commands (#1297)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+16 / -0 行。
- 关键文件：Makefile。

#### 55. fix(mcp): implement sync invocation wrapper for async MCP tools (#1287)

- 提交：`[a9940c3](https://github.com/bytedance/deer-flow/commit/a9940c391c684e01f3d4b5d508611f2d04764527)`
- 日期：2026-03-24
- 做了什么：修复缺陷或回归问题，主题是“implement sync invocation wrapper for async MCP tools (#1287)”。
- 影响范围：主要涉及 后端。
- 改动规模：+128 / -0 行。
- 关键文件：backend/packages/harness/deerflow/mcp/tools.py；backend/tests/test_mcp_sync_wrapper.py。

#### 56. fix(skills): follow symlinks when scanning custom skills directory (#1292)

- 提交：`[6bf5267](https://github.com/bytedance/deer-flow/commit/6bf526748d7bfb32ff4899521899aac2f3eec02c)`
- 日期：2026-03-24
- 做了什么：修复缺陷或回归问题，主题是“follow symlinks when scanning custom skills directory (#1292)”。
- 影响范围：主要涉及 后端。
- 改动规模：+1 / -1 行。
- 关键文件：backend/packages/harness/deerflow/skills/loader.py。

#### 57. fix: use subprocess instead of os.system in analyze.py (#1289)

- 提交：`[14a3fa5](https://github.com/bytedance/deer-flow/commit/14a3fa5290d501af371b335eafa46b5e9f75367e)`
- 日期：2026-03-24
- 做了什么：修复缺陷或回归问题，主题是“use subprocess instead of os.system in analyze.py (#1289)”。
- 影响范围：主要涉及 脚本工具、技能体系。
- 改动规模：+4 / -3 行。
- 关键文件：scripts/check.py；skills/public/data-analysis/scripts/analyze.py。

#### 58. fix: repair frontend check command and docs (#1281)

- 提交：`[4b15f14](https://github.com/bytedance/deer-flow/commit/4b15f1464745339fdede86ff17420397a1237d9f)`
- 日期：2026-03-24
- 做了什么：修复缺陷或回归问题，主题是“repair frontend check command and docs (#1281)”。
- 影响范围：主要涉及 其他模块、文档、前端。
- 改动规模：+40 / -3 行。
- 关键文件：CONTRIBUTING.md；README.md；frontend/package.json。

#### 59. fix(frontend): fix the build error of i18n (#1274)

- 提交：`[48a1975](https://github.com/bytedance/deer-flow/commit/48a197555ba36e915e5450a5f2afba7157b6db76)`
- 日期：2026-03-24
- 做了什么：修复缺陷或回归问题，主题是“fix the build error of i18n (#1274)”。
- 影响范围：主要涉及 前端。
- 改动规模：+6 / -0 行。
- 关键文件：frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts；frontend/src/core/i18n/locales/zh-CN.ts。

#### 60. fix(frontend): filter task tool calls when rendering SubtaskCard (#1242)

- 提交：`[0431a67](https://github.com/bytedance/deer-flow/commit/0431a67b689cbc53154e46add4612c20a4cabfcd)`
- 日期：2026-03-24
- 做了什么：修复缺陷或回归问题，主题是“filter task tool calls when rendering SubtaskCard (#1242)”。
- 影响范围：主要涉及 前端。
- 改动规模：+3 / -3 行。
- 关键文件：frontend/src/components/workspace/messages/message-list.tsx。

#### 61. fix(threads): clean up local thread data after thread deletion (#1262)

- 提交：`[8b0f3fe](https://github.com/bytedance/deer-flow/commit/8b0f3fe2334b717f230d7f5b4a1d43dd06eb2a37)`
- 日期：2026-03-24
- 做了什么：修复缺陷或回归问题，主题是“clean up local thread data after thread deletion (#1262)”。
- 影响范围：主要涉及 后端、文档、前端。
- 改动规模：+240 / -9 行。
- 关键文件：README.md；backend/CLAUDE.md；backend/README.md；backend/app/gateway/app.py；backend/app/gateway/routers/**init**.py；backend/app/gateway/routers/threads.py；backend/docs/API.md；backend/docs/ARCHITECTURE.md。

#### 62. fix: add error handling for podcast generation failures (#1257)

- 提交：`[79acc39](https://github.com/bytedance/deer-flow/commit/79acc3939a684ce7680a47461182a918b4c056de)`
- 日期：2026-03-24
- 做了什么：修复缺陷或回归问题，主题是“add error handling for podcast generation failures (#1257)”。
- 影响范围：主要涉及 技能体系。
- 改动规模：+39 / -2 行。
- 关键文件：skills/public/podcast-generation/scripts/generate.py。

#### 63. fix(hotkey):support to open settings with hotkey (#1259)

- 提交：`[3be1d84](https://github.com/bytedance/deer-flow/commit/3be1d841aa0713230c29c2edb2ab69ef724a27af)`
- 日期：2026-03-23
- 做了什么：修复缺陷或回归问题，主题是“support to open settings with hotkey (#1259)”。
- 影响范围：主要涉及 前端。
- 改动规模：+6 / -2 行。
- 关键文件：frontend/src/components/workspace/command-palette.tsx。

#### 64. fix: add ~/.codex and ~/.claude bind mounts to docker-compose-dev.yaml (#1247)

- 提交：`[1c981ea](https://github.com/bytedance/deer-flow/commit/1c981ead2ae633e8a28e30c056b327de19c1fb13)`
- 日期：2026-03-23
- 做了什么：修复缺陷或回归问题，主题是“add ~/.codex and ~/.claude bind mounts to docker-compose-dev.yaml (#1247)”。
- 影响范围：主要涉及 容器部署。
- 改动规模：+26 / -0 行。
- 关键文件：docker/docker-compose-dev.yaml。

#### 65. fix(config): reload AppConfig when config path or mtime changes (#1239)

- 提交：`[644501a](https://github.com/bytedance/deer-flow/commit/644501ae07cdfa3e6003fe42d3f3bd8c6e83434e)`
- 日期：2026-03-22
- 做了什么：修复缺陷或回归问题，主题是“reload AppConfig when config path or mtime changes (#1239)”。
- 影响范围：主要涉及 后端、文档。
- 改动规模：+146 / -10 行。
- 关键文件：README.md；backend/CLAUDE.md；backend/packages/harness/deerflow/config/app_config.py；backend/tests/test_app_config_reload.py。

#### 66. fix(middleware): fallback to configurable thread_id in thread data middleware (#1237)

- 提交：`[e6c6770](https://github.com/bytedance/deer-flow/commit/e6c6770b701262b49cf4019e60df7a720666f951)`
- 日期：2026-03-22
- 做了什么：修复缺陷或回归问题，主题是“fallback to configurable thread_id in thread data middleware (#1237)”。
- 影响范围：主要涉及 后端。
- 改动规模：+62 / -2 行。
- 关键文件：backend/packages/harness/deerflow/agents/middlewares/thread_data_middleware.py；backend/tests/test_thread_data_middleware.py。

#### 67. fix(gateway): accept output_text suggestion blocks (#1238)

- 提交：`[894875a](https://github.com/bytedance/deer-flow/commit/894875ab1b1c232698c0ad32ae565f4b3cbbe1d1)`
- 日期：2026-03-22
- 做了什么：修复缺陷或回归问题，主题是“accept output_text suggestion blocks (#1238)”。
- 影响范围：主要涉及 后端。
- 改动规模：+19 / -1 行。
- 关键文件：backend/app/gateway/routers/suggestions.py；backend/tests/test_suggestions_router.py。

#### 68. fix(telegram): fix reply ordering race condition (#1231)

- 提交：`[7a90055](https://github.com/bytedance/deer-flow/commit/7a90055edeca554171ac4f5e0d045f09b630bd7d)`
- 日期：2026-03-22
- 做了什么：修复缺陷或回归问题，主题是“fix reply ordering race condition (#1231)”。
- 影响范围：主要涉及 后端。
- 改动规模：+53 / -7 行。
- 关键文件：backend/app/channels/telegram.py；backend/tests/test_channels.py。

#### 69. fix: normalize structured LLM content in serialization and memory updater (#1215)

- 提交：`[3af7090](https://github.com/bytedance/deer-flow/commit/3af709097eb77e7518d4d951b4a51802b70f895f)`
- 日期：2026-03-22
- 做了什么：修复缺陷或回归问题，主题是“normalize structured LLM content in serialization and memory updater (#1215)”。
- 影响范围：主要涉及 后端。
- 改动规模：+420 / -30 行。
- 关键文件：backend/packages/harness/deerflow/agents/checkpointer/provider.py；backend/packages/harness/deerflow/agents/memory/prompt.py；backend/packages/harness/deerflow/agents/memory/updater.py；backend/packages/harness/deerflow/client.py；backend/packages/harness/deerflow/subagents/executor.py；backend/tests/test_checkpointer.py；backend/tests/test_memory_updater.py；backend/tests/test_serialize_message_content.py。

#### 70. fix: improve MiniMax code plan integration (#1169)

- 提交：`[ceab7fa](https://github.com/bytedance/deer-flow/commit/ceab7fac14c3a8067670b85623697d4a42bd5fc1)`
- 日期：2026-03-20
- 做了什么：修复缺陷或回归问题，主题是“improve MiniMax code plan integration (#1169)”。
- 影响范围：主要涉及 前端、后端。
- 改动规模：+491 / -22 行。
- 关键文件：backend/app/gateway/routers/models.py；backend/packages/harness/deerflow/client.py；backend/packages/harness/deerflow/models/patched_minimax.py；backend/tests/test_client.py；backend/tests/test_patched_minimax.py；frontend/src/app/layout.tsx；frontend/src/app/mock/api/models/route.ts；frontend/src/app/workspace/agents/[agent_name]/chats/[thread_id]/page.tsx。

#### 71. fix(feishu): support @bot message in topic groups (#1206)

- 提交：`[3b235fd](https://github.com/bytedance/deer-flow/commit/3b235fd182684c806e93882909ac184db5ac4329)`
- 日期：2026-03-20
- 做了什么：修复缺陷或回归问题，主题是“support @bot message in topic groups (#1206)”。
- 影响范围：主要涉及 后端。
- 改动规模：+108 / -1 行。
- 关键文件：backend/app/channels/feishu.py；backend/tests/test_feishu_parser.py。

#### 72. fix: add sync after_model to TitleMiddleware (#1190)

- 提交：`[accf5b5](https://github.com/bytedance/deer-flow/commit/accf5b5f8ec0049eaf828cbeff80a03fee9b3f78)`
- 日期：2026-03-19
- 做了什么：修复缺陷或回归问题，主题是“add sync after_model to TitleMiddleware (#1190)”。
- 影响范围：主要涉及 后端。
- 改动规模：+120 / -35 行。
- 关键文件：backend/packages/harness/deerflow/agents/middlewares/title_middleware.py；backend/tests/test_title_middleware_core_logic.py。

#### 73. fix(harness): skip duplicate memory facts (#1193)

- 提交：`[f67c3d2](https://github.com/bytedance/deer-flow/commit/f67c3d2c9e236fb29e7a5622a9e4216809d60ff1)`
- 日期：2026-03-18
- 做了什么：修复缺陷或回归问题，主题是“skip duplicate memory facts (#1193)”。
- 影响范围：主要涉及 后端、文档。
- 改动规模：+169 / -3 行。
- 关键文件：README.md；backend/CLAUDE.md；backend/packages/harness/deerflow/agents/memory/updater.py；backend/tests/test_memory_updater.py。

#### 74. fix(scripts): handle docker-init failures gracefully for private registry (#1191)

- 提交：`[423ea59](https://github.com/bytedance/deer-flow/commit/423ea59491db1749316e9f6297efde8d2495de10)`
- 日期：2026-03-18
- 做了什么：修复缺陷或回归问题，主题是“handle docker-init failures gracefully for private registry (#1191)”。
- 影响范围：主要涉及 其他模块、脚本工具。
- 改动规模：+63 / -4 行。
- 关键文件：Makefile；scripts/docker.sh。

#### 75. fix(gateway): remove generated markdown on upload delete (#1170)

- 提交：`[4c78188](https://github.com/bytedance/deer-flow/commit/4c781888963b53130bc68cf8f712f73ed46d995e)`
- 日期：2026-03-18
- 做了什么：修复缺陷或回归问题，主题是“remove generated markdown on upload delete (#1170)”。
- 影响范围：主要涉及 后端。
- 改动规模：+18 / -1 行。
- 关键文件：backend/app/gateway/routers/uploads.py；backend/tests/test_uploads_router.py。

#### 76. fix(frontend): block duplicate sends during uploads (#1165)

- 提交：`[f737fbe](https://github.com/bytedance/deer-flow/commit/f737fbeae8a091d6ebf15ec97fb747293ec2c4b1)`
- 日期：2026-03-18
- 做了什么：修复缺陷或回归问题，主题是“block duplicate sends during uploads (#1165)”。
- 影响范围：主要涉及 前端。
- 改动规模：+22 / -3 行。
- 关键文件：frontend/AGENTS.md；frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/core/threads/hooks.ts。

#### 77. fix(harness): allow agent read access to /mnt/skills in local sandbox (#1178)

- 提交：`[feac03e](https://github.com/bytedance/deer-flow/commit/feac03ecbcac445bb514c411ec812e7f9ff74cb1)`
- 日期：2026-03-17
- 做了什么：修复缺陷或回归问题，主题是“allow agent read access to /mnt/skills in local sandbox (#1178)”。
- 影响范围：主要涉及 后端。
- 改动规模：+527 / -295 行。
- 关键文件：backend/packages/harness/deerflow/sandbox/local/local_sandbox.py；backend/packages/harness/deerflow/sandbox/local/local_sandbox_provider.py；backend/packages/harness/deerflow/sandbox/tools.py；backend/tests/test_sandbox_tools_security.py。

#### 78. fix(scripts): add next-server to serve.sh cleanup trap (#1162)

- 提交：`[75c9630](https://github.com/bytedance/deer-flow/commit/75c96300cfbd2ee28da2b1e813c2db77a618df86)`
- 日期：2026-03-17
- 做了什么：修复缺陷或回归问题，主题是“add next-server to serve.sh cleanup trap (#1162)”。
- 影响范围：主要涉及 脚本工具。
- 改动规模：+1 / -0 行。
- 关键文件：scripts/serve.sh。

#### 79. fix(harness): normalize structured content for titles (#1155)

- 提交：`[b1913a1](https://github.com/bytedance/deer-flow/commit/b1913a1902a73c1df6300393cf6418cc1a303fa1)`
- 日期：2026-03-17
- 做了什么：修复缺陷或回归问题，主题是“normalize structured content for titles (#1155)”。
- 影响范围：主要涉及 后端。
- 改动规模：+56 / -7 行。
- 关键文件：backend/CLAUDE.md；backend/docs/AUTO_TITLE_GENERATION.md；backend/packages/harness/deerflow/agents/middlewares/title_middleware.py；backend/tests/test_title_middleware_core_logic.py。

#### 80. fix(makefile): correct docker-init help description (#1163)

- 提交：`[ab0c10f](https://github.com/bytedance/deer-flow/commit/ab0c10f0021258dd6352082bb5128da5aff9b094)`
- 日期：2026-03-16
- 做了什么：修复缺陷或回归问题，主题是“correct docker-init help description (#1163)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+1 / -1 行。
- 关键文件：Makefile。

#### 81. fix(frontend): gracefully handle missing WebGL context (#1147)

- 提交：`[609ff58](https://github.com/bytedance/deer-flow/commit/609ff5849ff18af44e1926f5c4a5a5032fc399b1)`
- 日期：2026-03-16
- 做了什么：修复缺陷或回归问题，主题是“gracefully handle missing WebGL context (#1147)”。
- 影响范围：主要涉及 前端。
- 改动规模：+21 / -4 行。
- 关键文件：frontend/src/components/ui/galaxy.jsx。

#### 82. fix(scripts): correct Makefile target name in docker.sh restart message (#1161)

- 提交：`[3212c7c](https://github.com/bytedance/deer-flow/commit/3212c7c5a2c1117ab3a20fce2692072f2fa2e641)`
- 日期：2026-03-16
- 做了什么：修复缺陷或回归问题，主题是“correct Makefile target name in docker.sh restart message (#1161)”。
- 影响范围：主要涉及 脚本工具。
- 改动规模：+1 / -1 行。
- 关键文件：scripts/docker.sh。

#### 83. fix: issue 1138 windows encoding (#1139)

- 提交：`[191b60a](https://github.com/bytedance/deer-flow/commit/191b60a326f3031298d109dc4e8117ac40a00b23)`
- 日期：2026-03-16
- 做了什么：修复缺陷或回归问题，主题是“issue 1138 windows encoding (#1139)”。
- 影响范围：主要涉及 后端、技能体系。
- 改动规模：+116 / -24 行。
- 关键文件：backend/app/gateway/routers/artifacts.py；backend/app/gateway/routers/mcp.py；backend/app/gateway/routers/skills.py；backend/packages/harness/deerflow/community/aio_sandbox/aio_sandbox_provider.py；backend/packages/harness/deerflow/sandbox/local/local_sandbox.py；backend/packages/harness/deerflow/sandbox/tools.py；backend/packages/harness/deerflow/skills/validation.py；backend/tests/test_artifacts_router.py。

#### 84. fix: preserve conversation context in Telegram private chats (#1105)

- 提交：`[d197d50](https://github.com/bytedance/deer-flow/commit/d197d5014672ba319758019c1b14366a18dde818)`
- 日期：2026-03-14
- 做了什么：修复缺陷或回归问题，主题是“preserve conversation context in Telegram private chats (#1105)”。
- 影响范围：主要涉及 后端。
- 改动规模：+237 / -18 行。
- 关键文件：backend/src/channels/manager.py；backend/src/channels/telegram.py；backend/tests/test_channels.py。

#### 85. fix(frontend): surface upload API error details (#1113)

- 提交：`[5a84814](https://github.com/bytedance/deer-flow/commit/5a8481416f85d4828cef35bd45d779160258079d)`
- 日期：2026-03-13
- 做了什么：修复缺陷或回归问题，主题是“surface upload API error details (#1113)”。
- 影响范围：主要涉及 前端。
- 改动规模：+15 / -6 行。
- 关键文件：frontend/src/core/uploads/api.ts。

#### 86. fix: make check/config cross-platform for Windows (#1080) (#1093)

- 提交：`[a79d414](https://github.com/bytedance/deer-flow/commit/a79d4146956446e56d3db707f17d6d05f98fe527)`
- 日期：2026-03-13
- 做了什么：修复缺陷或回归问题，主题是“make check/config cross-platform for Windows (#1080) (#1093)”。
- 影响范围：主要涉及 脚本工具、其他模块。
- 改动规模：+194 / -8 行。
- 关键文件：Makefile；scripts/check.py；scripts/configure.py。

#### 87. fix(gateway): ignore archive metadata wrappers (#1108)

- 提交：`[b155923](https://github.com/bytedance/deer-flow/commit/b155923ab074673ca669a0028a3bfe025e1daead)`
- 日期：2026-03-13
- 做了什么：修复缺陷或回归问题，主题是“ignore archive metadata wrappers (#1108)”。
- 影响范围：主要涉及 后端。
- 改动规模：+134 / -14 行。
- 关键文件：backend/src/gateway/routers/skills.py；backend/tests/test_skills_archive_root.py。

#### 88. fix(gateway): allow standard skill frontmatter metadata (#1103)

- 提交：`[cda9fb7](https://github.com/bytedance/deer-flow/commit/cda9fb7bca6d86bde49bd0bc7edab76925bd4b54)`
- 日期：2026-03-13
- 做了什么：修复缺陷或回归问题，主题是“allow standard skill frontmatter metadata (#1103)”。
- 影响范围：主要涉及 后端、文档。
- 改动规模：+83 / -4 行。
- 关键文件：README.md；backend/CLAUDE.md；backend/src/gateway/routers/skills.py；backend/tests/test_skills_router.py。

#### 89. fix(gateway): normalize suggestion response content (#1098)

- 提交：`[03cafea](https://github.com/bytedance/deer-flow/commit/03cafea7158cb29c6dba999fb7049d5ec7d925e6)`
- 日期：2026-03-13
- 做了什么：修复缺陷或回归问题，主题是“normalize suggestion response content (#1098)”。
- 影响范围：主要涉及 后端、文档。
- 改动规模：+40 / -1 行。
- 关键文件：README.md；backend/CLAUDE.md；backend/src/gateway/routers/suggestions.py；backend/tests/test_suggestions_router.py。

#### 90. fix(memory): inject stored facts into system prompt memory context (#1083)

- 提交：`[b5fcb13](https://github.com/bytedance/deer-flow/commit/b5fcb1334ab1376b35568e4a80464bbf32c4218b)`
- 日期：2026-03-13
- 做了什么：修复缺陷或回归问题，主题是“inject stored facts into system prompt memory context (#1083)”。
- 影响范围：主要涉及 后端。
- 改动规模：+252 / -502 行。
- 关键文件：backend/docs/MEMORY_IMPROVEMENTS.md；backend/docs/MEMORY_IMPROVEMENTS_SUMMARY.md；backend/src/agents/memory/prompt.py；backend/tests/test_memory_prompt_injection.py。

#### 91. fix(middleware): degrade tool-call exceptions to error tool messages (#1110)

- 提交：`[3521cc2](https://github.com/bytedance/deer-flow/commit/3521cc266840d4e8edb4e377b74aa66282c44c48)`
- 日期：2026-03-13
- 做了什么：修复缺陷或回归问题，主题是“degrade tool-call exceptions to error tool messages (#1110)”。
- 影响范围：主要涉及 后端、脚本工具。
- 改动规模：+436 / -14 行。
- 关键文件：backend/src/agents/lead_agent/agent.py；backend/src/agents/middlewares/tool_error_handling_middleware.py；backend/src/subagents/executor.py；backend/tests/test_tool_error_handling_middleware.py；scripts/tool-error-degradation-detection.sh。

#### 92. fix(chat): update navigation method to prevent state loss during thread remount (#1107)

- 提交：`[fdacb1c](https://github.com/bytedance/deer-flow/commit/fdacb1c3a5734a023319be19e9dfaeca54b5b8f7)`
- 日期：2026-03-12
- 做了什么：修复缺陷或回归问题，主题是“update navigation method to prevent state loss during thread remount (#1107)”。
- 影响范围：主要涉及 前端。
- 改动规模：+4 / -27 行。
- 关键文件：frontend/src/app/workspace/agents/[agent_name]/chats/[thread_id]/page.tsx；frontend/src/app/workspace/chats/[thread_id]/layout.tsx；frontend/src/app/workspace/chats/[thread_id]/page.tsx。

#### 93. fix(makefile):quick fix of the makefile formate error (#1085)

- 提交：`[e5a21b9](https://github.com/bytedance/deer-flow/commit/e5a21b9ba0316891af682b327cd5fba02c2bc383)`
- 日期：2026-03-11
- 做了什么：修复缺陷或回归问题，主题是“quick fix of the makefile formate error (#1085)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+2 / -2 行。
- 关键文件：Makefile。

#### 94. fix(client): Harden upload validation and conversion flow (#989)

- 提交：`[4bae3c7](https://github.com/bytedance/deer-flow/commit/4bae3c724ce2f6fbe6baaddc19c16e848e93539c)`
- 日期：2026-03-11
- 做了什么：修复缺陷或回归问题，主题是“Harden upload validation and conversion flow (#989)”。
- 影响范围：主要涉及 后端。
- 改动规模：+174 / -49 行。
- 关键文件：backend/CLAUDE.md；backend/README.md；backend/src/client.py；backend/tests/test_client.py。

#### 95. fix(frontend): fix new-chat navigation stale state issue (#1077)

- 提交：`[5d4fd9c](https://github.com/bytedance/deer-flow/commit/5d4fd9cf72604a48fea2a97c79b7a0956d7c0d47)`
- 日期：2026-03-11
- 做了什么：修复缺陷或回归问题，主题是“fix new-chat navigation stale state issue (#1077)”。
- 影响范围：主要涉及 前端。
- 改动规模：+27 / -2 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/layout.tsx；frontend/src/app/workspace/chats/[thread_id]/page.tsx。

#### 96. fix(tracing): support LANGCHAIN_* env fallback for LangSmith config (#1065)

- 提交：`[96dbee0](https://github.com/bytedance/deer-flow/commit/96dbee00e37942af7deb42f2899f4262cd3de423)`
- 日期：2026-03-11
- 做了什么：修复缺陷或回归问题，主题是“support LANGCHAIN_* env fallback for LangSmith config (#1065)”。
- 影响范围：主要涉及 后端。
- 改动规模：+116 / -4 行。
- 关键文件：backend/src/config/tracing_config.py；backend/tests/test_tracing_config.py。

#### 97. fix: load all thread pages in thread lists (#1044)

- 提交：`[6ae7f0c](https://github.com/bytedance/deer-flow/commit/6ae7f0c0eeeb0a694c6fc3e728c562975be57f16)`
- 日期：2026-03-10
- 做了什么：修复缺陷或回归问题，主题是“load all thread pages in thread lists (#1044)”。
- 影响范围：主要涉及 前端。
- 改动规模：+116 / -12 行。
- 关键文件：frontend/src/app/mock/api/threads/search/route.ts；frontend/src/core/threads/hooks.ts。

#### 98. fix(frontend): sanitize unsupported langgraph stream modes (#1050)

- 提交：`[d5135ab](https://github.com/bytedance/deer-flow/commit/d5135ab7578dc7a6d8431375a26a094fb6936dce)`
- 日期：2026-03-10
- 做了什么：修复缺陷或回归问题，主题是“sanitize unsupported langgraph stream modes (#1050)”。
- 影响范围：主要涉及 前端。
- 改动规模：+138 / -4 行。
- 关键文件：frontend/src/core/api/api-client.ts；frontend/src/core/api/stream-mode.test.ts；frontend/src/core/api/stream-mode.ts；frontend/src/core/threads/hooks.ts。

#### 99. fix: improve port detection in WSL (#1061)

- 提交：`[19604e7](https://github.com/bytedance/deer-flow/commit/19604e7f4716bede04ae51ed67abba51cef502cb)`
- 日期：2026-03-10
- 做了什么：修复缺陷或回归问题，主题是“improve port detection in WSL (#1061)”。
- 影响范围：主要涉及 脚本工具。
- 改动规模：+28 / -1 行。
- 关键文件：scripts/wait-for-port.sh。

#### 100. docs: fix stream_mode examples for runs stream (#1033) (#1039)

- 提交：`[cf1c4a6](https://github.com/bytedance/deer-flow/commit/cf1c4a68ea370a0055e858f8c2c1a0cfa10d90c7)`
- 日期：2026-03-10
- 做了什么：修复缺陷或回归问题，主题是“fix stream_mode examples for runs stream (#1033) (#1039)”。
- 影响范围：主要涉及 后端。
- 改动规模：+6 / -2 行。
- 关键文件：backend/docs/API.md。

#### 101. fix(subagents): cleanup background tasks after completion to prevent memory leak (#1030)

- 提交：`[0409f8c](https://github.com/bytedance/deer-flow/commit/0409f8cefd7864fa34f9fbef30b7bbd97156c64b)`
- 日期：2026-03-10
- 做了什么：修复缺陷或回归问题，主题是“cleanup background tasks after completion to prevent memory leak (#1030)”。
- 影响范围：主要涉及 后端。
- 改动规模：+361 / -1 行。
- 关键文件：backend/src/subagents/executor.py；backend/src/tools/builtins/task_tool.py；backend/tests/test_subagent_executor.py；backend/tests/test_task_tool_core_logic.py。

#### 102. fix(checkpointer): return InMemorySaver instead of None when not configured (#1016) (#1019)

- 提交：`[959b4f2](https://github.com/bytedance/deer-flow/commit/959b4f2b0989365717b3aa7e386e690a424a45e7)`
- 日期：2026-03-09
- 做了什么：修复缺陷或回归问题，主题是“return InMemorySaver instead of None when not configured (#1016) (#1019)”。
- 影响范围：主要涉及 后端。
- 改动规模：+95 / -12 行。
- 关键文件：backend/src/agents/checkpointer/async_provider.py；backend/src/agents/checkpointer/provider.py；backend/tests/test_checkpointer.py；backend/tests/test_checkpointer_none_fix.py。

#### 103. fix(frontend): enable HTML preview for generated artifacts using srcDoc (#1001)

- 提交：`[4f0a8da](https://github.com/bytedance/deer-flow/commit/4f0a8da2eed7ccfcd12f4322b30ded56edf7ed37)`
- 日期：2026-03-09
- 做了什么：修复缺陷或回归问题，主题是“enable HTML preview for generated artifacts using srcDoc (#1001)”。
- 影响范围：主要涉及 前端。
- 改动规模：+5 / -10 行。
- 关键文件：frontend/src/components/workspace/artifacts/artifact-file-detail.tsx。

#### 104. fix(dev): improve gateway startup diagnostics for config errors (#1020)

- 提交：`[6b5c4fe](https://github.com/bytedance/deer-flow/commit/6b5c4fe6dd11f8032aa7f92aa497d5ae09548ffa)`
- 日期：2026-03-08
- 做了什么：修复缺陷或回归问题，主题是“improve gateway startup diagnostics for config errors (#1020)”。
- 影响范围：主要涉及 后端、其他模块、文档。
- 改动规模：+26 / -5 行。
- 关键文件：Makefile；README.md；backend/CLAUDE.md；backend/src/gateway/app.py。

#### 105. fix(docker): remove cache_from to prevent missing cache warnings (#1013)

- 提交：`[511e9ea](https://github.com/bytedance/deer-flow/commit/511e9eaf5eb3c26f6b530002978e6cd477a90db7)`
- 日期：2026-03-08
- 做了什么：修复缺陷或回归问题，主题是“remove cache_from to prevent missing cache warnings (#1013)”。
- 影响范围：主要涉及 容器部署。
- 改动规模：+2 / -4 行。
- 关键文件：docker/docker-compose-dev.yaml。

#### 106. fix: normalize presented artifact paths (#998)

- 提交：`[09325ca](https://github.com/bytedance/deer-flow/commit/09325ca28f99cd9eed55d6bc96969432279d2c39)`
- 日期：2026-03-06
- 做了什么：修复缺陷或回归问题，主题是“normalize presented artifact paths (#998)”。
- 影响范围：主要涉及 后端。
- 改动规模：+145 / -1 行。
- 关键文件：backend/src/tools/builtins/present_file_tool.py；backend/tests/test_present_file_tool_core_logic.py。

#### 107. fix(subagent): support async MCP tools in subagent executor (#917)

- 提交：`[3e4a24f](https://github.com/bytedance/deer-flow/commit/3e4a24f48bd6bc869805e9351e5599c7bf662764)`
- 日期：2026-03-06
- 做了什么：修复缺陷或回归问题，主题是“support async MCP tools in subagent executor (#917)”。
- 影响范围：主要涉及 后端。
- 改动规模：+674 / -6 行。
- 关键文件：backend/src/subagents/executor.py；backend/tests/test_subagent_executor.py。

#### 108. fix(backend): upgrade langgraph-api to 0.7 and stabilize memory path tests (#984)

- 提交：`[3a5e0b9](https://github.com/bytedance/deer-flow/commit/3a5e0b935d2f1b0a5519f3d0eb93e24bf1cd1761)`
- 日期：2026-03-06
- 做了什么：修复缺陷或回归问题，主题是“upgrade langgraph-api to 0.7 and stabilize memory path tests (#984)”。
- 影响范围：主要涉及 后端。
- 改动规模：+135 / -101 行。
- 关键文件：backend/pyproject.toml；backend/tests/test_custom_agent.py；backend/uv.lock。

#### 109. fix(nginx): use cross-platform local paths for pid and logs (#977)

- 提交：`[0c7c96d](https://github.com/bytedance/deer-flow/commit/0c7c96d75e286c7513ea1d0cb9625afe6617dd21)`
- 日期：2026-03-05
- 做了什么：修复缺陷或回归问题，主题是“use cross-platform local paths for pid and logs (#977)”。
- 影响范围：主要涉及 容器部署。
- 改动规模：+3 / -3 行。
- 关键文件：docker/nginx/nginx.local.conf。

#### 110. fix(chat): handle empty uploaded files case and improve artifact selection logic (#979)

- 提交：`[1b3939c](https://github.com/bytedance/deer-flow/commit/1b3939cb78b58ad45ae8eb8b3485a78465e54c2a)`
- 日期：2026-03-05
- 做了什么：修复缺陷或回归问题，主题是“handle empty uploaded files case and improve artifact selection logic (#979)”。
- 影响范围：主要涉及 前端、后端。
- 改动规模：+51 / -18 行。
- 关键文件：backend/src/agents/middlewares/uploads_middleware.py；backend/tests/test_uploads_middleware_core_logic.py；frontend/src/components/workspace/artifacts/context.tsx；frontend/src/components/workspace/chats/chat-box.tsx；frontend/src/core/messages/utils.ts。

#### 111. fix(memory): prevent file upload events from persisting in long-term memory (#971)

- 提交：`[3ada4f9](https://github.com/bytedance/deer-flow/commit/3ada4f98b1c63f138dbb90fffbf5ea51d086c63f)`
- 日期：2026-03-05
- 做了什么：修复缺陷或回归问题，主题是“prevent file upload events from persisting in long-term memory (#971)”。
- 影响范围：主要涉及 后端。
- 改动规模：+336 / -5 行。
- 关键文件：backend/src/agents/memory/prompt.py；backend/src/agents/memory/updater.py；backend/src/agents/middlewares/memory_middleware.py；backend/tests/test_memory_upload_filtering.py。

#### 112. fix(readme): correct typo Offiical to Official (#972)

- 提交：`[6ac0042](https://github.com/bytedance/deer-flow/commit/6ac0042cfee14ca395681d96c2e7b1393f4cb528)`
- 日期：2026-03-05
- 做了什么：修复缺陷或回归问题，主题是“correct typo Offiical to Official (#972)”。
- 影响范围：主要涉及 文档。
- 改动规模：+1 / -1 行。
- 关键文件：README.md。

#### 113. fix(make):added make config command in make file (#964)

- 提交：`[a3c8efb](https://github.com/bytedance/deer-flow/commit/a3c8efb00b2c7281e25c0ca6330bed13d99b15df)`
- 日期：2026-03-04
- 做了什么：修复缺陷或回归问题，主题是“added make config command in make file (#964)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+6 / -1 行。
- 关键文件：Makefile。

#### 114. fix(models): handle google provider import errors and add dependency (#952)

- 提交：`[8342e88](https://github.com/bytedance/deer-flow/commit/8342e88534b78390221c0ff5bfc9b37759fc26f5)`
- 日期：2026-03-03
- 做了什么：修复缺陷或回归问题，主题是“handle google provider import errors and add dependency (#952)”。
- 影响范围：主要涉及 后端、配置。
- 改动规模：+191 / -1 行。
- 关键文件：backend/CLAUDE.md；backend/README.md；backend/pyproject.toml；backend/src/reflection/resolvers.py；backend/tests/test_reflection_resolvers.py；backend/uv.lock；config.example.yaml。

#### 115. Fix line numbering (#954)

- 提交：`[e399d09](https://github.com/bytedance/deer-flow/commit/e399d09e8f493ba5e2cd23008d17a582fe9b6f7c)`
- 日期：2026-03-02
- 做了什么：修复缺陷或回归问题，主题是“Fix line numbering (#954)”。
- 影响范围：主要涉及 前端。
- 改动规模：+2 / -1 行。
- 关键文件：frontend/src/components/ai-elements/message.tsx。

#### 116. fix(backend): Fix readability extraction crash when Node parser fails (#937)

- 提交：`[80316c1](https://github.com/bytedance/deer-flow/commit/80316c131e90d4938bd3fec9d6da0f3c1c730016)`
- 日期：2026-03-01
- 做了什么：修复缺陷或回归问题，主题是“Fix readability extraction crash when Node parser fails (#937)”。
- 影响范围：主要涉及 后端。
- 改动规模：+73 / -1 行。
- 关键文件：backend/src/utils/readability.py；backend/tests/test_readability.py。

#### 117. fix: use shell fallback instead of hardcoded /bin/zsh in LocalSandbox (#939)

- 提交：`[d728bb2](https://github.com/bytedance/deer-flow/commit/d728bb26d59bb2e97396c2a4921787ca3b0360a0)`
- 日期：2026-03-01
- 做了什么：修复缺陷或回归问题，主题是“use shell fallback instead of hardcoded /bin/zsh in LocalSandbox (#939)”。
- 影响范围：主要涉及 后端。
- 改动规模：+21 / -1 行。
- 关键文件：backend/src/sandbox/local/local_sandbox.py。

#### 118. fix(uploads): persist thread uploads canonically and fail fast on upload errors (#943)

- 提交：`[8c6dd9e](https://github.com/bytedance/deer-flow/commit/8c6dd9e264e3a1189a3f0e5964b95bf9067c73e5)`
- 日期：2026-03-01
- 做了什么：修复缺陷或回归问题，主题是“persist thread uploads canonically and fail fast on upload errors (#943)”。
- 影响范围：主要涉及 后端、前端。
- 改动规模：+143 / -12 行。
- 关键文件：backend/docs/FILE_UPLOAD.md；backend/src/gateway/routers/uploads.py；backend/tests/test_uploads_router.py；frontend/src/core/threads/hooks.ts。

#### 119. Fix typo: Offiical to Official (#942)

- 提交：`[5a1ac62](https://github.com/bytedance/deer-flow/commit/5a1ac6287ed0cea3c14e9460fe456c5bb876ce48)`
- 日期：2026-03-01
- 做了什么：修复缺陷或回归问题，主题是“Fix typo: Offiical to Official (#942)”。
- 影响范围：主要涉及 文档。
- 改动规模：+1 / -1 行。
- 关键文件：README.md。

## 2026-04

- 新功能/增强：64 条
- Bug 修复：169 条

### 新功能 / 增强

#### 1. feat(channels): add DingTalk channel integration (#2628)

- 提交：`[08afdcb](https://github.com/bytedance/deer-flow/commit/08afdcb907f149312f31827aa1a96eeaa67b85f9)`
- 日期：2026-04-30
- 做了什么：新增或增强功能，主题是“add DingTalk channel integration (#2628)”。
- 影响范围：主要涉及 后端、文档、其他模块。
- 改动规模：+2544 / -7 行。
- 关键文件：.env.example；README.md；README_fr.md；README_ja.md；README_ru.md；README_zh.md；backend/CLAUDE.md；backend/app/channels/base.py。

#### 2. chore(adpator):Adapt MindIE engine model and improve testing and fixes (#2523)

- 提交：`[395c143](https://github.com/bytedance/deer-flow/commit/395c14357b60926a63af2142ac96bbb670ecb768)`
- 日期：2026-04-28
- 做了什么：新增或增强功能，主题是“Adapt MindIE engine model and improve testing and fixes (#2523)”。
- 影响范围：主要涉及 后端。
- 改动规模：+100 / -7 行。
- 关键文件：backend/packages/harness/deerflow/models/mindie_provider.py；backend/tests/test_mindie_provider.py。

#### 3. feat: implement process-local internal authentication for Gateway and enhance CSRF handling

- 提交：`[da174df](https://github.com/bytedance/deer-flow/commit/da174dfd4d65bb23613d1185c61ddf3e8846a91d)`
- 日期：2026-04-26
- 做了什么：新增或增强功能，主题是“implement process-local internal authentication for Gateway and enhance CSRF handling”。
- 影响范围：主要涉及 后端、文档。
- 改动规模：+134 / -26 行。
- 关键文件：README.md；backend/CLAUDE.md；backend/app/channels/manager.py；backend/app/gateway/app.py；backend/app/gateway/auth_middleware.py；backend/app/gateway/internal_auth.py；backend/packages/harness/deerflow/agents/memory/queue.py；backend/packages/harness/deerflow/agents/memory/storage.py。

#### 4. feat: add default database configuration for AppConfig and update example config

- 提交：`[35ef8b7](https://github.com/bytedance/deer-flow/commit/35ef8b7c136a61d47a300e2413800f257217feca)`
- 日期：2026-04-26
- 做了什么：新增或增强功能，主题是“add default database configuration for AppConfig and update example config”。
- 影响范围：主要涉及 后端、配置。
- 改动规模：+61 / -2 行。
- 关键文件：backend/packages/harness/deerflow/config/app_config.py；backend/tests/test_app_config_reload.py；config.example.yaml。

#### 5. feat: add request parameter to generate_suggestions endpoint for enhanced context

- 提交：`[3b71e2d](https://github.com/bytedance/deer-flow/commit/3b71e2d37793233862b3701d99bb579da2407c82)`
- 日期：2026-04-26
- 做了什么：新增或增强功能，主题是“add request parameter to generate_suggestions endpoint for enhanced context”。
- 影响范围：主要涉及 后端。
- 改动规模：+1 / -1 行。
- 关键文件：backend/app/gateway/routers/suggestions.py。

#### 6. feat: enhance chat history loading with new hooks and UI components (#2338)

- 提交：`[db5ad86](https://github.com/bytedance/deer-flow/commit/db5ad86381159d7d7f57de499b01515dba350803)`
- 日期：2026-04-19
- 做了什么：新增或增强功能，主题是“enhance chat history loading with new hooks and UI components (#2338)”。
- 影响范围：主要涉及 前端、后端。
- 改动规模：+746 / -1438 行。
- 关键文件：backend/app/gateway/deps.py；backend/app/gateway/routers/runs.py；backend/app/gateway/routers/thread_runs.py；backend/app/gateway/routers/uploads.py；backend/app/gateway/services.py；backend/packages/harness/deerflow/agents/middlewares/loop_detection_middleware.py；backend/packages/harness/deerflow/agents/middlewares/summarization_middleware.py；backend/packages/harness/deerflow/agents/middlewares/thread_data_middleware.py。

#### 7. feat(persistence): per-user filesystem isolation, run-scoped APIs, and state/history simplification (#2153)

- 提交：`[2e05f38](https://github.com/bytedance/deer-flow/commit/2e05f380c4c01398f0077923b1d792dcd9b4d3b3)`
- 日期：2026-04-12
- 做了什么：新增或增强功能，主题是“per-user filesystem isolation, run-scoped APIs, and state/history simplification (#2153)”。
- 影响范围：主要涉及 后端。
- 改动规模：+1630 / -783 行。
- 关键文件：backend/CLAUDE.md；backend/app/channels/feishu.py；backend/app/channels/manager.py；backend/app/gateway/path_utils.py；backend/app/gateway/routers/memory.py；backend/app/gateway/routers/runs.py；backend/app/gateway/routers/thread_runs.py；backend/app/gateway/routers/threads.py。

#### 8. feat: Add metadata and descriptions to various documentation pages in Chinese

- 提交：`[44d9953](https://github.com/bytedance/deer-flow/commit/44d9953e2e2f4f2993660ecb191be86ed89e608a)`
- 日期：2026-04-12
- 做了什么：新增或增强功能，主题是“Add metadata and descriptions to various documentation pages in Chinese”。
- 影响范围：主要涉及 前端、其他模块。
- 改动规模：+516 / -1015 行。
- 关键文件：deer-flow.code-workspace；frontend/src/app/[lang]/docs/layout.tsx；frontend/src/components/landing/footer.tsx；frontend/src/content/en/_meta.ts；frontend/src/content/en/application/agents-and-threads.mdx；frontend/src/content/en/application/configuration.mdx；frontend/src/content/en/application/deployment-guide.mdx；frontend/src/content/en/application/index.mdx。

#### 9. feat(persistence):Unified persistence layer with event store, feedback, and rebase cleanup (#2134)

- 提交：`[56d5fa3](https://github.com/bytedance/deer-flow/commit/56d5fa3337cb6ecf54620c2fe09379aedffaa5e7)`
- 日期：2026-04-12
- 做了什么：新增或增强功能，主题是“Unified persistence layer with event store, feedback, and rebase cleanup (#2134)”。
- 影响范围：主要涉及 后端、前端、文档。
- 改动规模：+3036 / -799 行。
- 关键文件：backend/app/gateway/app.py；backend/app/gateway/authz.py；backend/app/gateway/deps.py；backend/app/gateway/langgraph_auth.py；backend/app/gateway/routers/feedback.py；backend/app/gateway/routers/thread_runs.py；backend/app/gateway/routers/threads.py；backend/app/gateway/services.py。

#### 10. docs: fill all TBD documentation pages and add new harness module pages

- 提交：`[88f822a](https://github.com/bytedance/deer-flow/commit/88f822a8b3150d845395c3fa10adf74ee5cc9b73)`
- 日期：2026-04-11
- 做了什么：补充文档能力，主题是“fill all TBD documentation pages and add new harness module pages”。
- 影响范围：主要涉及 前端。
- 改动规模：+2449 / -17 行。
- 关键文件：frontend/src/content/en/application/agents-and-threads.mdx；frontend/src/content/en/application/configuration.mdx；frontend/src/content/en/application/deployment-guide.mdx；frontend/src/content/en/application/index.mdx；frontend/src/content/en/application/operations-and-troubleshooting.mdx；frontend/src/content/en/application/quick-start.mdx；frontend/src/content/en/application/workspace-usage.mdx；frontend/src/content/en/harness/_meta.ts。

#### 11. feat(dependencies): add langchain-ollama and ollama packages with optional dependencies

- 提交：`[7ff9077](https://github.com/bytedance/deer-flow/commit/7ff90770749132219b729095466da194f9f61371)`
- 日期：2026-04-11
- 做了什么：新增或增强功能，主题是“add langchain-ollama and ollama packages with optional dependencies”。
- 影响范围：主要涉及 后端。
- 改动规模：+7 / -0 行。
- 关键文件：backend/uv.lock。

#### 12. feat: replace auto-admin creation with secure interactive first-boot setup (#2063)

- 提交：`[848ace9](https://github.com/bytedance/deer-flow/commit/848ace98cb0ca54735f6003b711d0bbb21eecab8)`
- 日期：2026-04-11
- 做了什么：新增或增强功能，主题是“replace auto-admin creation with secure interactive first-boot setup (#2063)”。
- 影响范围：主要涉及 后端、前端。
- 改动规模：+793 / -205 行。
- 关键文件：backend/app/gateway/app.py；backend/app/gateway/auth/errors.py；backend/app/gateway/auth/local_provider.py；backend/app/gateway/auth/repositories/base.py；backend/app/gateway/auth/repositories/sqlite.py；backend/app/gateway/auth_middleware.py；backend/app/gateway/csrf_middleware.py；backend/app/gateway/routers/auth.py。

#### 13. feat(auth): release-validation pass for 2.0-rc — 12 blockers + simplify follow-ups (#2008)

- 提交：`[94eee95](https://github.com/bytedance/deer-flow/commit/94eee95fe0a10f3b46eaff4860ff388a058d7582)`
- 日期：2026-04-09
- 做了什么：新增或增强功能，主题是“release-validation pass for 2.0-rc — 12 blockers + simplify follow-ups (#2008)”。
- 影响范围：主要涉及 后端、前端、容器部署。
- 改动规模：+9144 / -431 行。
- 关键文件：backend/app/gateway/app.py；backend/app/gateway/auth/**init**.py；backend/app/gateway/auth/config.py；backend/app/gateway/auth/credential_file.py；backend/app/gateway/auth/errors.py；backend/app/gateway/auth/jwt.py；backend/app/gateway/auth/local_provider.py；backend/app/gateway/auth/models.py。

#### 14. feat(persistence): add unified persistence layer with event store, token tracking, and feedback (#1930)

- 提交：`[d8ecaf4](https://github.com/bytedance/deer-flow/commit/d8ecaf46c977513c1b6f51954ffffea631966df8)`
- 日期：2026-04-07
- 做了什么：新增或增强功能，主题是“add unified persistence layer with event store, token tracking, and feedback (#1930)”。
- 影响范围：主要涉及 后端、其他模块、配置。
- 改动规模：+6451 / -463 行。
- 关键文件：.env.example；backend/Dockerfile；backend/app/gateway/app.py；backend/app/gateway/deps.py；backend/app/gateway/routers/feedback.py；backend/app/gateway/routers/thread_runs.py；backend/app/gateway/routers/threads.py；backend/app/gateway/services.py。

#### 15. feat(dev): add pre-commit hooks for ruff, eslint, and prettier (#2525)

- 提交：`[8a04414](https://github.com/bytedance/deer-flow/commit/8a044142cbf86ffa6bd445db7d129f9ac051d608)`
- 日期：2026-04-26
- 做了什么：新增或增强功能，主题是“add pre-commit hooks for ruff, eslint, and prettier (#2525)”。
- 影响范围：主要涉及 其他模块、配置、文档。
- 改动规模：+38 / -3 行。
- 关键文件：.pre-commit-config.yaml；CONTRIBUTING.md；Makefile；README.md。

#### 16. feat(mcp): support custom tool interceptors via extensions_config.json (#2451)

- 提交：`[f394c0d](https://github.com/bytedance/deer-flow/commit/f394c0d8c8de8821ac6a5becc73f5a9587a03e42)`
- 日期：2026-04-25
- 做了什么：新增或增强功能，主题是“support custom tool interceptors via extensions_config.json (#2451)”。
- 影响范围：主要涉及 后端、其他模块。
- 改动规模：+334 / -0 行。
- 关键文件：backend/docs/MCP_SERVER.md；backend/packages/harness/deerflow/mcp/tools.py；backend/tests/test_mcp_custom_interceptors.py；extensions_config.example.json。

#### 17. feat(models): Provider for MindIE model engine (#2483)

- 提交：`[2bb1a2d](https://github.com/bytedance/deer-flow/commit/2bb1a2dfa28fb79a308b5f980fabd44693bcd0f7)`
- 日期：2026-04-25
- 做了什么：新增或增强功能，主题是“Provider for MindIE model engine (#2483)”。
- 影响范围：主要涉及 后端、配置。
- 改动规模：+682 / -1 行。
- 关键文件：backend/packages/harness/deerflow/models/factory.py；backend/packages/harness/deerflow/models/mindie_provider.py；backend/pyproject.toml；backend/tests/test_mindie_provider.py；backend/uv.lock；config.example.yaml。

#### 18. feat(trace):Add run_name to the trace info for system agents. (#2492)

- 提交：`[11f557a](https://github.com/bytedance/deer-flow/commit/11f557a2c691bf77be76e5b1d914c1ddb55fde05)`
- 日期：2026-04-24
- 做了什么：新增或增强功能，主题是“Add run_name to the trace info for system agents. (#2492)”。
- 影响范围：主要涉及 后端。
- 改动规模：+34 / -4 行。
- 关键文件：backend/app/gateway/routers/suggestions.py；backend/packages/harness/deerflow/agents/memory/updater.py；backend/packages/harness/deerflow/agents/middlewares/title_middleware.py；backend/packages/harness/deerflow/skills/security_scanner.py；backend/tests/test_memory_updater.py；backend/tests/test_security_scanner.py；backend/tests/test_suggestions_router.py；backend/tests/test_title_middleware_core_logic.py。

#### 19. feat(subagents): support per-subagent skill loading and custom subagent types (#2253)

- 提交：`[30d619d](https://github.com/bytedance/deer-flow/commit/30d619de08291fe5657559c00bf0a389c9ea74a6)`
- 日期：2026-04-23
- 做了什么：新增或增强功能，主题是“support per-subagent skill loading and custom subagent types (#2253)”。
- 影响范围：主要涉及 后端、前端、配置。
- 改动规模：+962 / -72 行。
- 关键文件：backend/app/gateway/routers/agents.py；backend/packages/harness/deerflow/agents/lead_agent/prompt.py；backend/packages/harness/deerflow/config/subagents_config.py；backend/packages/harness/deerflow/subagents/config.py；backend/packages/harness/deerflow/subagents/executor.py；backend/packages/harness/deerflow/subagents/registry.py；backend/packages/harness/deerflow/tools/builtins/setup_agent_tool.py；backend/packages/harness/deerflow/tools/builtins/task_tool.py。

#### 20. feat: add optional prompt-toolkit support to debug.py (#2461)

- 提交：`[c42ae3a](https://github.com/bytedance/deer-flow/commit/c42ae3af79430c7637277118838dbf6cfd3ae881)`
- 日期：2026-04-23
- 做了什么：新增或增强功能，主题是“add optional prompt-toolkit support to debug.py (#2461)”。
- 影响范围：主要涉及 后端。
- 改动规模：+19 / -4 行。
- 关键文件：backend/debug.py；backend/pyproject.toml。

#### 21. feat(frontend): add Playwright E2E tests with CI workflow (#2279)

- 提交：`[c6b0423](https://github.com/bytedance/deer-flow/commit/c6b0423558cafb603b01148bbc999a0b883b315e)`
- 日期：2026-04-18
- 做了什么：新增或增强功能，主题是“add Playwright E2E tests with CI workflow (#2279)”。
- 影响范围：主要涉及 前端、其他模块、CI/CD。
- 改动规模：+671 / -14 行。
- 关键文件：.github/workflows/e2e-tests.yml；.gitignore；CONTRIBUTING.md；frontend/AGENTS.md；frontend/CLAUDE.md；frontend/Makefile；frontend/README.md；frontend/package.json。

#### 22. feat: show token usage per assistant response (#2270)

- 提交：`[105db00](https://github.com/bytedance/deer-flow/commit/105db0098784ed3c44158420938052c51b1691f3)`
- 日期：2026-04-16
- 做了什么：新增或增强功能，主题是“show token usage per assistant response (#2270)”。
- 影响范围：主要涉及 前端、后端、配置。
- 改动规模：+271 / -50 行。
- 关键文件：backend/app/gateway/routers/models.py；backend/packages/harness/deerflow/client.py；backend/tests/test_client.py；config.example.yaml；frontend/src/app/workspace/agents/[agent_name]/chats/[thread_id]/page.tsx；frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/workspace/messages/message-list-item.tsx；frontend/src/components/workspace/messages/message-list.tsx。

#### 23. test: add unit tests for ViewImageMiddleware (#2256)

- 提交：`[8e35913](https://github.com/bytedance/deer-flow/commit/8e3591312afcbda911881c2fa1b932aa0295b531)`
- 日期：2026-04-15
- 做了什么：补充/增强测试体系，主题是“add unit tests for ViewImageMiddleware (#2256)”。
- 影响范围：主要涉及 后端。
- 改动规模：+398 / -0 行。
- 关键文件：backend/tests/test_view_image_middleware.py。

#### 24. feat: flush memory before summarization (#2176)

- 提交：`[4ba3167](https://github.com/bytedance/deer-flow/commit/4ba3167f48b212605203c35cb5883e5520e53fa6)`
- 日期：2026-04-14
- 做了什么：新增或增强功能，主题是“flush memory before summarization (#2176)”。
- 影响范围：主要涉及 后端。
- 改动规模：+666 / -188 行。
- 关键文件：backend/packages/harness/deerflow/agents/lead_agent/agent.py；backend/packages/harness/deerflow/agents/memory/message_processing.py；backend/packages/harness/deerflow/agents/memory/queue.py；backend/packages/harness/deerflow/agents/memory/summarization_hook.py；backend/packages/harness/deerflow/agents/middlewares/memory_middleware.py；backend/packages/harness/deerflow/agents/middlewares/summarization_middleware.py；backend/tests/test_lead_agent_model_resolution.py；backend/tests/test_memory_queue.py。

#### 25.  feat: switch memory updater to async LLM calls (#2138)

- 提交：`[07fc25d](https://github.com/bytedance/deer-flow/commit/07fc25d2857ea25b46dc635c9059eba8f8ce6dfe)`
- 日期：2026-04-14
- 做了什么：新增或增强功能，主题是“switch memory updater to async LLM calls (#2138)”。
- 影响范围：主要涉及 后端。
- 改动规模：+278 / -82 行。
- 关键文件：backend/docs/TODO.md；backend/packages/harness/deerflow/agents/memory/updater.py；backend/tests/test_memory_updater.py。

#### 26. feat(frontend): set up Vitest frontend testing infrastructure with CI workflow (#2147)

- 提交：`[4efc8d4](https://github.com/bytedance/deer-flow/commit/4efc8d404fad850664e7f74657303b0ea409d6ee)`
- 日期：2026-04-12
- 做了什么：新增或增强功能，主题是“set up Vitest frontend testing infrastructure with CI workflow (#2147)”。
- 影响范围：主要涉及 前端、CI/CD、其他模块。
- 改动规模：+632 / -336 行。
- 关键文件：.github/workflows/frontend-unit-tests.yml；CONTRIBUTING.md；frontend/AGENTS.md；frontend/CLAUDE.md；frontend/Makefile；frontend/README.md；frontend/package.json；frontend/pnpm-lock.yaml。

#### 27. feat(llm): introduce lightweight circuit breaker to prevent rate-limit bans and resource exhaustion (#2095)

- 提交：`[4d4ddb3](https://github.com/bytedance/deer-flow/commit/4d4ddb3d3f396a4cd605e3c85800eb889844e7df)`
- 日期：2026-04-12
- 做了什么：新增或增强功能，主题是“introduce lightweight circuit breaker to prevent rate-limit bans and resource exhaustion (#2095)”。
- 影响范围：主要涉及 后端、配置。
- 改动规模：+356 / -2 行。
- 关键文件：backend/packages/harness/deerflow/agents/middlewares/llm_error_handling_middleware.py；backend/packages/harness/deerflow/config/app_config.py；backend/tests/test_llm_error_handling_middleware.py；config.example.yaml。

#### 28. feat(subagents): allow model override per subagent in config.yaml (#2064)

- 提交：`[ac04f27](https://github.com/bytedance/deer-flow/commit/ac04f2704f933dcb1b22369ea7ee2b4f89740caa)`
- 日期：2026-04-12
- 做了什么：新增或增强功能，主题是“allow model override per subagent in config.yaml (#2064)”。
- 影响范围：主要涉及 后端、配置。
- 改动规模：+196 / -2 行。
- 关键文件：backend/packages/harness/deerflow/config/subagents_config.py；backend/packages/harness/deerflow/subagents/registry.py；backend/tests/test_subagent_timeout_config.py；config.example.yaml。

#### 29. feat(channels): add Discord channel integration (#1806)

- 提交：`[c4d273a](https://github.com/bytedance/deer-flow/commit/c4d273a68a6b72bf2dec75c0b230f3fba68bc212)`
- 日期：2026-04-11
- 做了什么：新增或增强功能，主题是“add Discord channel integration (#1806)”。
- 影响范围：主要涉及 后端、其他模块。
- 改动规模：+299 / -0 行。
- 关键文件：.env.example；backend/app/channels/discord.py；backend/app/channels/manager.py；backend/app/channels/service.py；backend/tests/test_discord_channel.py。

#### 30. Add Contributor Covenant Code of Conduct

- 提交：`[679ca65](https://github.com/bytedance/deer-flow/commit/679ca657ee09af1e09d32ab06f3ef27ddf75d8bb)`
- 日期：2026-04-10
- 做了什么：新增或增强功能，主题是“Add Contributor Covenant Code of Conduct”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+128 / -0 行。
- 关键文件：CODE_OF_CONDUCT.md。

#### 31. feat: add WeChat channel integration (#1869)

- 提交：`[fa96acd](https://github.com/bytedance/deer-flow/commit/fa96acdf4b20e45229c25974a00fe397c5f46c89)`
- 日期：2026-04-10
- 做了什么：新增或增强功能，主题是“add WeChat channel integration (#1869)”。
- 影响范围：主要涉及 后端、文档、配置。
- 改动规模：+2699 / -0 行。
- 关键文件：README.md；backend/app/channels/manager.py；backend/app/channels/service.py；backend/app/channels/wechat.py；backend/tests/test_wechat_channel.py；config.example.yaml。

#### 32. feat(provisioner): add optional PVC support for sandbox volumes  (#2020)

- 提交：`[90299e2](https://github.com/bytedance/deer-flow/commit/90299e2710bf82079e6db5c88e227f75e75913fb)`
- 日期：2026-04-10
- 做了什么：新增或增强功能，主题是“add optional PVC support for sandbox volumes  (#2020)”。
- 影响范围：主要涉及 后端、容器部署。
- 改动规模：+255 / -55 行。
- 关键文件：backend/tests/conftest.py；backend/tests/test_provisioner_kubeconfig.py；backend/tests/test_provisioner_pvc_volumes.py；docker/docker-compose-dev.yaml；docker/provisioner/README.md；docker/provisioner/app.py。

#### 33. feat(blog): implement blog structure with post listing, tagging, and layout enhancements (#1962)

- 提交：`[7dc0c7d](https://github.com/bytedance/deer-flow/commit/7dc0c7d01f3719dc40ca1f7ebdd4cc9f16ca83e8)`
- 日期：2026-04-10
- 做了什么：新增或增强功能，主题是“implement blog structure with post listing, tagging, and layout enhancements (#1962)”。
- 影响范围：主要涉及 前端。
- 改动规模：+868 / -11 行。
- 关键文件：frontend/src/app/[lang]/docs/layout.tsx；frontend/src/app/blog/[[...mdxPath]]/page.tsx；frontend/src/app/blog/layout.tsx；frontend/src/app/blog/posts/page.tsx；frontend/src/app/blog/tags/[tag]/page.tsx；frontend/src/components/landing/header.tsx；frontend/src/components/landing/post-list.tsx；frontend/src/content/en/_meta.ts。

#### 34. Add TypeScript SDK path to code-workspace settings (#2052)

- 提交：`[809b341](https://github.com/bytedance/deer-flow/commit/809b341350f493bb20e59be3bd96fb72ba35615c)`
- 日期：2026-04-10
- 做了什么：新增或增强功能，主题是“Add TypeScript SDK path to code-workspace settings (#2052)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+1 / -0 行。
- 关键文件：deer-flow.code-workspace。

#### 35. test(skills): add evaluation + trigger analysis for systematic-literature-review (#2061)

- 提交：`[654354c](https://github.com/bytedance/deer-flow/commit/654354c624bfc84ecbb60f1394ca4806590bcbdf)`
- 日期：2026-04-10
- 做了什么：补充/增强测试体系，主题是“add evaluation + trigger analysis for systematic-literature-review (#2061)”。
- 影响范围：主要涉及 技能体系。
- 改动规模：+182 / -1 行。
- 关键文件：skills/public/systematic-literature-review/SKILL.md；skills/public/systematic-literature-review/evals/evals.json；skills/public/systematic-literature-review/evals/trigger_eval_set.json。

#### 36. feat(dx): Setup Wizard + doctor command — closes #2030 (#2034)

- 提交：`[eef0a6e](https://github.com/bytedance/deer-flow/commit/eef0a6e2dadefd360a74ffbc19c5fb6d0bb7d426)`
- 日期：2026-04-10
- 做了什么：新增或增强功能，主题是“Setup Wizard + doctor command — closes #2030 (#2034)”。
- 影响范围：主要涉及 脚本工具、后端、其他模块。
- 改动规模：+2809 / -68 行。
- 关键文件：Makefile；README.md；backend/docs/CONFIGURATION.md；backend/packages/harness/deerflow/agents/lead_agent/agent.py；backend/packages/harness/deerflow/community/firecrawl/tools.py；backend/tests/conftest.py；backend/tests/test_doctor.py；backend/tests/test_firecrawl_tools.py。

#### 37. feat(skills): add systematic-literature-review skill for multi-paper SLR workflows (#2032)

- 提交：`[16aa51c](https://github.com/bytedance/deer-flow/commit/16aa51c9b33f14163582ddfae468b97c6c1c2c4a)`
- 日期：2026-04-10
- 做了什么：新增或增强功能，主题是“add systematic-literature-review skill for multi-paper SLR workflows (#2032)”。
- 影响范围：主要涉及 技能体系。
- 改动规模：+949 / -0 行。
- 关键文件：skills/public/systematic-literature-review/SKILL.md；skills/public/systematic-literature-review/scripts/arxiv_search.py；skills/public/systematic-literature-review/templates/apa.md；skills/public/systematic-literature-review/templates/bibtex.md；skills/public/systematic-literature-review/templates/ieee.md。

#### 38. feat(models): add langchain-ollama for native Ollama thinking support (#2062)

- 提交：`[133ffe7](https://github.com/bytedance/deer-flow/commit/133ffe7174182814e16d20a69bc98b5d47d744b3)`
- 日期：2026-04-10
- 做了什么：新增或增强功能，主题是“add langchain-ollama for native Ollama thinking support (#2062)”。
- 影响范围：主要涉及 后端、配置。
- 改动规模：+36 / -0 行。
- 关键文件：backend/packages/harness/pyproject.toml；config.example.yaml。

#### 39. feat(smoke-test): add smoke test skill (#1947)

- 提交：`[6572fa5](https://github.com/bytedance/deer-flow/commit/6572fa5b75e96a15aa0a0bfc601346b8d4cf22d4)`
- 日期：2026-04-09
- 做了什么：补充/增强测试体系，主题是“add smoke test skill (#1947)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+2155 / -0 行。
- 关键文件：.agent/skills/smoke-test/SKILL.md；.agent/skills/smoke-test/references/SOP.md；.agent/skills/smoke-test/references/troubleshooting.md；.agent/skills/smoke-test/scripts/check_docker.sh；.agent/skills/smoke-test/scripts/check_local_env.sh；.agent/skills/smoke-test/scripts/deploy_docker.sh；.agent/skills/smoke-test/scripts/deploy_local.sh；.agent/skills/smoke-test/scripts/frontend_check.sh。

#### 40. feat(config): add when_thinking_disabled support for model configs (#1970)

- 提交：`[194bab4](https://github.com/bytedance/deer-flow/commit/194bab469143f5dc370513144800705d3c4467ab)`
- 日期：2026-04-09
- 做了什么：新增或增强功能，主题是“add when_thinking_disabled support for model configs (#1970)”。
- 影响范围：主要涉及 后端、配置。
- 改动规模：+168 / -5 行。
- 关键文件：backend/packages/harness/deerflow/config/model_config.py；backend/packages/harness/deerflow/models/factory.py；backend/tests/test_model_factory.py；config.example.yaml。

#### 41. feat: implement full checkpoint rollback on user cancellation (#1867)

- 提交：`[35f141f](https://github.com/bytedance/deer-flow/commit/35f141fc48ff0ae70ebfb97d8c8ccd9565187b52)`
- 日期：2026-04-09
- 做了什么：新增或增强功能，主题是“implement full checkpoint rollback on user cancellation (#1867)”。
- 影响范围：主要涉及 后端。
- 改动规模：+356 / -19 行。
- 关键文件：backend/packages/harness/deerflow/runtime/runs/worker.py；backend/tests/test_run_worker_rollback.py。

#### 42. feat(client): add thread query methods `list_threads` and `get_thread` (#1609)

- 提交：`[31a3c9a](https://github.com/bytedance/deer-flow/commit/31a3c9a3dec4e855b9054a3db02d6edf6fd11d7e)`
- 日期：2026-04-09
- 做了什么：新增或增强功能，主题是“add thread query methods `list_threads` and `get_thread` (#1609)”。
- 影响范围：主要涉及 后端。
- 改动规模：+243 / -0 行。
- 关键文件：backend/packages/harness/deerflow/client.py；backend/tests/test_client.py。

#### 43. feat(community): add Exa search as community tool provider (#1357)

- 提交：`[5350b2f](https://github.com/bytedance/deer-flow/commit/5350b2fb24b3bdb98729cc20b4544658fb8dfaa9)`
- 日期：2026-04-08
- 做了什么：新增或增强功能，主题是“add Exa search as community tool provider (#1357)”。
- 影响范围：主要涉及 后端、配置。
- 改动规模：+377 / -0 行。
- 关键文件：backend/packages/harness/deerflow/community/exa/tools.py；backend/packages/harness/pyproject.toml；backend/tests/test_exa_tools.py；backend/uv.lock；config.example.yaml。

#### 44. feat(sandbox): strengthen bash command auditing with compound splitting and expanded patterns (#1881)

- 提交：`[3b3e8e1](https://github.com/bytedance/deer-flow/commit/3b3e8e1b0ba1831008e8cefdf115215c8b10731c)`
- 日期：2026-04-07
- 做了什么：新增或增强功能，主题是“strengthen bash command auditing with compound splitting and expanded patterns (#1881)”。
- 影响范围：主要涉及 后端。
- 改动规模：+327 / -9 行。
- 关键文件：backend/packages/harness/deerflow/agents/middlewares/sandbox_audit_middleware.py；backend/tests/test_sandbox_audit_middleware.py。

#### 45. feat: add BytePlus logo (#1948)

- 提交：`[f467e61](https://github.com/bytedance/deer-flow/commit/f467e613b6173253bc2d217f15bb434c8113d52f)`
- 日期：2026-04-07
- 做了什么：新增或增强功能，主题是“add BytePlus logo (#1948)”。
- 影响范围：主要涉及 前端。
- 改动规模：+59 / -0 行。
- 关键文件：frontend/src/components/landing/hero.tsx。

#### 46. Feature/feishu receive file (#1608)

- 提交：`[88e5352](https://github.com/bytedance/deer-flow/commit/88e535269ec1b4ec06ee3ad7f6143ddea27305ab)`
- 日期：2026-04-06
- 做了什么：新增或增强功能，主题是“Feature/feishu receive file (#1608)”。
- 影响范围：主要涉及 后端。
- 改动规模：+331 / -5 行。
- 关键文件：backend/app/channels/base.py；backend/app/channels/feishu.py；backend/app/channels/manager.py；backend/app/channels/service.py；backend/tests/test_channel_file_attachments.py；backend/tests/test_channels.py；backend/tests/test_feishu_parser.py。

#### 47. Implement skill self-evolution and skill_manage flow (#1874)

- 提交：`[888f7bf](https://github.com/bytedance/deer-flow/commit/888f7bfb9d1d2eb4570d51aec4dfe62ddac15e05)`
- 日期：2026-04-06
- 做了什么：新增或增强功能，主题是“Implement skill self-evolution and skill_manage flow (#1874)”。
- 影响范围：主要涉及 后端、文档、其他模块。
- 改动规模：+1163 / -58 行。
- 关键文件：.gitignore；backend/app/gateway/routers/skills.py；backend/packages/harness/deerflow/agents/lead_agent/prompt.py；backend/packages/harness/deerflow/config/**init**.py；backend/packages/harness/deerflow/config/app_config.py；backend/packages/harness/deerflow/config/skill_evolution_config.py；backend/packages/harness/deerflow/skills/loader.py；backend/packages/harness/deerflow/skills/manager.py。

#### 48. feat(models): add vLLM provider support (#1860)

- 提交：`[dd30e60](https://github.com/bytedance/deer-flow/commit/dd30e609f7b50fa1398c6fa3654b9c0be3fb7c7c)`
- 日期：2026-04-06
- 做了什么：新增或增强功能，主题是“add vLLM provider support (#1860)”。
- 影响范围：主要涉及 后端、其他模块、文档。
- 改动规模：+534 / -5 行。
- 关键文件：.env.example；README.md；backend/CLAUDE.md；backend/packages/harness/deerflow/models/factory.py；backend/packages/harness/deerflow/models/vllm_provider.py；backend/tests/test_model_factory.py；backend/tests/test_vllm_provider.py；config.example.yaml。

#### 49. feat: unified serve.sh with gateway mode support (#1847)

- 提交：`[ca2fb95](https://github.com/bytedance/deer-flow/commit/ca2fb95ee6bae08073ad058ecaecbf180c32a50c)`
- 日期：2026-04-05
- 做了什么：新增或增强功能，主题是“unified serve.sh with gateway mode support (#1847)”。
- 影响范围：主要涉及 容器部署、脚本工具、其他模块。
- 改动规模：+551 / -376 行。
- 关键文件：Makefile；README.md；backend/CLAUDE.md；docker/docker-compose-dev.yaml；docker/docker-compose.yaml；docker/nginx/nginx.conf；docker/provisioner/Dockerfile；scripts/deploy.sh。

#### 50. feat(skills): add academic-paper-review, code-documentation, and newsletter-generation skills (#1861)

- 提交：`[8bb14fa](https://github.com/bytedance/deer-flow/commit/8bb14fa1a7bf7e6ee0631db4db9168962edbc31f)`
- 日期：2026-04-05
- 做了什么：新增或增强功能，主题是“add academic-paper-review, code-documentation, and newsletter-generation skills (#1861)”。
- 影响范围：主要涉及 技能体系。
- 改动规模：+1047 / -0 行。
- 关键文件：skills/public/academic-paper-review/SKILL.md；skills/public/code-documentation/SKILL.md；skills/public/newsletter-generation/SKILL.md。

#### 51. feat: support wecom channel (#1390)

- 提交：`[1980980](https://github.com/bytedance/deer-flow/commit/19809800f14f1869dd2b01f521d9312b7cde940d)`
- 日期：2026-04-04
- 做了什么：新增或增强功能，主题是“support wecom channel (#1390)”。
- 影响范围：主要涉及 后端、文档、其他模块。
- 改动规模：+771 / -3 行。
- 关键文件：.env.example；README.md；README_zh.md；backend/app/channels/manager.py；backend/app/channels/service.py；backend/app/channels/wecom.py；backend/pyproject.toml；backend/tests/test_channels.py。

#### 52. feat(uploads): guide agent using agentic search for uploaded documents (#1816)

- 提交：`[bbd0866](https://github.com/bytedance/deer-flow/commit/bbd0866374332c01889b5c597674b9a3efc50364)`
- 日期：2026-04-04
- 做了什么：新增或增强功能，主题是“guide agent using agentic search for uploaded documents (#1816)”。
- 影响范围：主要涉及 后端。
- 改动规模：+7 / -1 行。
- 关键文件：backend/packages/harness/deerflow/agents/middlewares/uploads_middleware.py。

#### 53. feat(uploads): add pymupdf4llm PDF converter with auto-fallback and async offload (#1727)

- 提交：`[ddfc988](https://github.com/bytedance/deer-flow/commit/ddfc988bef96456a87103d2cb0bef785d552e281)`
- 日期：2026-04-03
- 做了什么：新增或增强功能，主题是“add pymupdf4llm PDF converter with auto-fallback and async offload (#1727)”。
- 影响范围：主要涉及 后端、配置。
- 改动规模：+461 / -14 行。
- 关键文件：backend/packages/harness/deerflow/config/app_config.py；backend/packages/harness/deerflow/utils/file_conversion.py；backend/packages/harness/pyproject.toml；backend/tests/test_file_conversion.py；config.example.yaml。

#### 54. feat(uploads): inject document outline into agent context for converted files (#1738)

- 提交：`[5ff230e](https://github.com/bytedance/deer-flow/commit/5ff230eafd29fd6dad8dd3ece58b3f3aba478ff9)`
- 日期：2026-04-03
- 做了什么：新增或增强功能，主题是“inject document outline into agent context for converted files (#1738)”。
- 影响范围：主要涉及 后端。
- 改动规模：+354 / -10 行。
- 关键文件：backend/packages/harness/deerflow/agents/middlewares/uploads_middleware.py；backend/packages/harness/deerflow/utils/file_conversion.py；backend/tests/test_file_conversion.py；backend/tests/test_uploads_middleware_core_logic.py。

#### 55. Add explicit save action for agent creation (#1798)

- 提交：`[3d4f9a8](https://github.com/bytedance/deer-flow/commit/3d4f9a88feaff07b14fcaba69c3c727390eee993)`
- 日期：2026-04-03
- 做了什么：新增或增强功能，主题是“Add explicit save action for agent creation (#1798)”。
- 影响范围：主要涉及 前端。
- 改动规模：+219 / -52 行。
- 关键文件：frontend/src/app/workspace/agents/new/page.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts；frontend/src/core/i18n/locales/zh-CN.ts；frontend/src/core/messages/utils.ts；frontend/src/core/threads/hooks.ts。

#### 56. feat(sandbox): add read-only support for local sandbox path mappings (#1808)

- 提交：`[1694c61](https://github.com/bytedance/deer-flow/commit/1694c616ef3e48be10862f5ce66ece1bd224dfaf)`
- 日期：2026-04-03
- 做了什么：新增或增强功能，主题是“add read-only support for local sandbox path mappings (#1808)”。
- 影响范围：主要涉及 后端、配置。
- 改动规模：+768 / -33 行。
- 关键文件：backend/packages/harness/deerflow/sandbox/local/local_sandbox.py；backend/packages/harness/deerflow/sandbox/local/local_sandbox_provider.py；backend/packages/harness/deerflow/sandbox/tools.py；backend/tests/test_local_sandbox_provider_mounts.py；backend/tests/test_sandbox_tools_security.py；config.example.yaml。

#### 57. feat(sandbox): add built-in grep and glob tools (#1784)

- 提交：`[c6cdf20](https://github.com/bytedance/deer-flow/commit/c6cdf200ceae043d9c14982d1da1549fc3fb806b)`
- 日期：2026-04-03
- 做了什么：新增或增强功能，主题是“add built-in grep and glob tools (#1784)”。
- 影响范围：主要涉及 后端、其他模块、配置。
- 改动规模：+1388 / -69 行。
- 关键文件：.gitignore；backend/docs/rfc-grep-glob-tools.md；backend/packages/harness/deerflow/community/aio_sandbox/aio_sandbox.py；backend/packages/harness/deerflow/sandbox/local/list_dir.py；backend/packages/harness/deerflow/sandbox/local/local_sandbox.py；backend/packages/harness/deerflow/sandbox/sandbox.py；backend/packages/harness/deerflow/sandbox/search.py；backend/packages/harness/deerflow/sandbox/tools.py。

#### 58. feat(client): add `available_skills` parameter to DeerFlowClient (#1779)

- 提交：`[76fad8b](https://github.com/bytedance/deer-flow/commit/76fad8b08de23c41ab1799e54b26bc59273d5ab9)`
- 日期：2026-04-03
- 做了什么：新增或增强功能，主题是“add `available_skills` parameter to DeerFlowClient (#1779)”。
- 影响范围：主要涉及 后端。
- 改动规模：+17 / -2 行。
- 关键文件：backend/packages/harness/deerflow/client.py；backend/tests/test_client.py。

#### 59. Improve Python reliability in channel retries and thread typing (#1776)

- 提交：`[6de9c7b](https://github.com/bytedance/deer-flow/commit/6de9c7b43f5802ce7b84f87719a9402cd495f41b)`
- 日期：2026-04-03
- 做了什么：新增或增强功能，主题是“Improve Python reliability in channel retries and thread typing (#1776)”。
- 影响范围：主要涉及 后端。
- 改动规模：+60 / -7 行。
- 关键文件：backend/app/channels/feishu.py；backend/app/channels/slack.py；backend/app/channels/telegram.py；backend/app/gateway/routers/threads.py；backend/tests/test_channels.py。

#### 60. Add documents site (#1767)

- 提交：`[c1366cf](https://github.com/bytedance/deer-flow/commit/c1366cf559b7edd2831a727effda5d701a0b0440)`
- 日期：2026-04-03
- 做了什么：新增或增强功能，主题是“Add documents site (#1767)”。
- 影响范围：主要涉及 前端、其他模块、容器部署。
- 改动规模：+2249 / -33 行。
- 关键文件：.gitignore；docker/nginx/nginx.local.conf；frontend/next.config.js；frontend/package.json；frontend/pnpm-lock.yaml；frontend/src/app/[lang]/docs/[[...mdxPath]]/page.tsx；frontend/src/app/[lang]/docs/layout.tsx；frontend/src/components/landing/header.tsx。

#### 61. feat/per agent skill filter (#1650)

- 提交：`[f8fb8d6](https://github.com/bytedance/deer-flow/commit/f8fb8d6fb129a38049e0e86dd099093a45498a37)`
- 日期：2026-04-02
- 做了什么：新增或增强功能，主题是“feat/per agent skill filter (#1650)”。
- 影响范围：主要涉及 后端、配置。
- 改动规模：+142 / -1 行。
- 关键文件：backend/docs/CONFIGURATION.md；backend/packages/harness/deerflow/agents/lead_agent/agent.py；backend/packages/harness/deerflow/agents/lead_agent/prompt.py；backend/packages/harness/deerflow/config/agents_config.py；backend/tests/test_custom_agent.py；backend/tests/test_lead_agent_skills.py；config.example.yaml。

#### 62. feat(tracing): add optional Langfuse support (#1717)

- 提交：`[2d1f90d](https://github.com/bytedance/deer-flow/commit/2d1f90d5dc0b0c992cb421428d33b431be5a5a17)`
- 日期：2026-04-02
- 做了什么：新增或增强功能，主题是“add optional Langfuse support (#1717)”。
- 影响范围：主要涉及 后端、文档。
- 改动规模：+667 / -67 行。
- 关键文件：README.md；backend/README.md；backend/packages/harness/deerflow/config/**init**.py；backend/packages/harness/deerflow/config/tracing_config.py；backend/packages/harness/deerflow/models/factory.py；backend/packages/harness/deerflow/tracing/**init**.py；backend/packages/harness/deerflow/tracing/factory.py；backend/packages/harness/pyproject.toml。

#### 63. feat(sandbox): truncate oversized bash and read_file tool outputs (#1677)

- 提交：`[df5339b](https://github.com/bytedance/deer-flow/commit/df5339b5d076fc71dd4e54d3f69c396fc2d63944)`
- 日期：2026-04-02
- 做了什么：新增或增强功能，主题是“truncate oversized bash and read_file tool outputs (#1677)”。
- 影响范围：主要涉及 后端、配置。
- 改动规模：+257 / -4 行。
- 关键文件：backend/packages/harness/deerflow/config/sandbox_config.py；backend/packages/harness/deerflow/sandbox/tools.py；backend/tests/test_tool_output_truncation.py；config.example.yaml。

#### 64. feat(memory): structured reflection + correction detection in MemoryMiddleware (#1620) (#1668)

- 提交：`[0cdecf7](https://github.com/bytedance/deer-flow/commit/0cdecf7b30bf5d369f4b6b24ab6fba4093955ee2)`
- 日期：2026-04-01
- 做了什么：新增或增强功能，主题是“structured reflection + correction detection in MemoryMiddleware (#1620) (#1668)”。
- 影响范围：主要涉及 后端。
- 改动规模：+436 / -21 行。
- 关键文件：backend/app/gateway/routers/memory.py；backend/packages/harness/deerflow/agents/memory/prompt.py；backend/packages/harness/deerflow/agents/memory/queue.py；backend/packages/harness/deerflow/agents/memory/updater.py；backend/packages/harness/deerflow/agents/middlewares/memory_middleware.py；backend/tests/test_memory_prompt_injection.py；backend/tests/test_memory_queue.py；backend/tests/test_memory_router.py。

### Bug 修复

#### 1. fix(config): unify log_level from config.yaml across Gateway and debug entry points (#2601)

- 提交：`[eba3b9e](https://github.com/bytedance/deer-flow/commit/eba3b9e18d797dfc42b9cc8610781fa941755731)`
- 日期：2026-04-30
- 做了什么：修复缺陷或回归问题，主题是“unify log_level from config.yaml across Gateway and debug entry points (#2601)”。
- 影响范围：主要涉及 后端。
- 改动规模：+137 / -28 行。
- 关键文件：backend/app/gateway/app.py；backend/debug.py；backend/packages/harness/deerflow/config/app_config.py；backend/tests/test_logging_level_from_config.py。

#### 2. fix(memory): replace short-lived asyncio.run() with persistent event loop (#2627)

- 提交：`[c0da278](https://github.com/bytedance/deer-flow/commit/c0da2782695168a19e34e2c11d8a188f02884128)`
- 日期：2026-04-30
- 做了什么：修复缺陷或回归问题，主题是“replace short-lived asyncio.run() with persistent event loop (#2627)”。
- 影响范围：主要涉及 后端。
- 改动规模：+240 / -88 行。
- 关键文件：backend/packages/harness/deerflow/agents/memory/updater.py；backend/tests/test_memory_updater.py。

#### 3. fix: avoid temporary event loops in async subagent execution (#2414)

- 提交：`[7dea166](https://github.com/bytedance/deer-flow/commit/7dea1666ce665905e684af4dac2b300f6d6884f4)`
- 日期：2026-04-30
- 做了什么：修复缺陷或回归问题，主题是“avoid temporary event loops in async subagent execution (#2414)”。
- 影响范围：主要涉及 后端。
- 改动规模：+236 / -75 行。
- 关键文件：backend/packages/harness/deerflow/subagents/executor.py；backend/tests/test_subagent_executor.py。

#### 4. fix(nginx): add catch-all /api/ location for auth routes (#2657)

- 提交：`[88d47f6](https://github.com/bytedance/deer-flow/commit/88d47f677f41bbce4fbc87fcc15ca2d1a7c0c3ec)`
- 日期：2026-04-30
- 做了什么：修复缺陷或回归问题，主题是“add catch-all /api/ location for auth routes (#2657)”。
- 影响范围：主要涉及 容器部署。
- 改动规模：+11 / -0 行。
- 关键文件：docker/nginx/nginx.conf。

#### 5. [security] fix(sandbox): bind local Docker ports to loopback (#2633)

- 提交：`[74081a8](https://github.com/bytedance/deer-flow/commit/74081a85a6827b013b4f41ca6a7f9e4d9b62069e)`
- 日期：2026-04-30
- 做了什么：修复缺陷或回归问题，主题是“[security] fix(sandbox): bind local Docker ports to loopback (#2633)”。
- 影响范围：主要涉及 后端。
- 改动规模：+169 / -2 行。
- 关键文件：backend/docs/CONFIGURATION.md；backend/packages/harness/deerflow/community/aio_sandbox/local_backend.py；backend/tests/test_aio_sandbox_local_backend.py。

#### 6. fix: avoid duplicate call to extractReasoningContentFromMessage (#2661)

- 提交：`[24a5a00](https://github.com/bytedance/deer-flow/commit/24a5a00679a99886387612ff991afbbd8c6be52d)`
- 日期：2026-04-30
- 做了什么：修复缺陷或回归问题，主题是“avoid duplicate call to extractReasoningContentFromMessage (#2661)”。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -1 行。
- 关键文件：frontend/src/components/workspace/messages/message-group.tsx。

#### 7. fix(security): allow disabling API docs in production via GATEWAY_ENABLE_DOCS (#2651)

- 提交：`[0691c4d](https://github.com/bytedance/deer-flow/commit/0691c4dda383561659f03c55927951a5be66b548)`
- 日期：2026-04-30
- 做了什么：修复缺陷或回归问题，主题是“allow disabling API docs in production via GATEWAY_ENABLE_DOCS (#2651)”。
- 影响范围：主要涉及 后端、其他模块。
- 改动规模：+134 / -4 行。
- 关键文件：.env.example；backend/CLAUDE.md；backend/app/gateway/app.py；backend/app/gateway/config.py；backend/docs/CONFIGURATION.md；backend/tests/test_gateway_docs_toggle.py。

#### 8. fix(frontend): create thread on first submit in new-agent page (#2656)

- 提交：`[f7b10d4](https://github.com/bytedance/deer-flow/commit/f7b10d42e484b308b3883e9c311baa7fa7960c30)`
- 日期：2026-04-30
- 做了什么：修复缺陷或回归问题，主题是“create thread on first submit in new-agent page (#2656)”。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -1 行。
- 关键文件：frontend/src/app/workspace/agents/new/page.tsx。

#### 9. Fix the log Injection error of skills.py

- 提交：`[11afd32](https://github.com/bytedance/deer-flow/commit/11afd32459cbbeb4a0c86fe9d2a07244af82f6f0)`
- 日期：2026-04-28
- 做了什么：修复缺陷或回归问题，主题是“Fix the log Injection error of skills.py”。
- 影响范围：主要涉及 后端。
- 改动规模：+7 / -2 行。
- 关键文件：backend/app/gateway/routers/skills.py。

#### 10. fixed the CI build errors

- 提交：`[64f4dc1](https://github.com/bytedance/deer-flow/commit/64f4dc163910895b1fd5df1d569fac6ffce8309e)`
- 日期：2026-04-28
- 做了什么：修复缺陷或回归问题，主题是“fixed the CI build errors”。
- 影响范围：主要涉及 后端。
- 改动规模：+4 / -3 行。
- 关键文件：backend/app/gateway/routers/skills.py；backend/tests/test_skills_custom_router.py。

#### 11. fix(sandbox): block host bash traversal escapes (#2560)

- 提交：`[6bd88fe](https://github.com/bytedance/deer-flow/commit/6bd88fe14cfe4d4b83199047326d4455bd656d55)`
- 日期：2026-04-28
- 做了什么：修复缺陷或回归问题，主题是“block host bash traversal escapes (#2560)”。
- 影响范围：主要涉及 后端。
- 改动规模：+373 / -25 行。
- 关键文件：backend/packages/harness/deerflow/sandbox/tools.py；backend/tests/test_sandbox_tools_security.py。

#### 12. fix(sandbox): prevent local custom mount symlink escapes (#2558)

- 提交：`[39c5da9](https://github.com/bytedance/deer-flow/commit/39c5da94f3b723b9062fdf00522cc69cdc837640)`
- 日期：2026-04-28
- 做了什么：修复缺陷或回归问题，主题是“prevent local custom mount symlink escapes (#2558)”。
- 影响范围：主要涉及 后端。
- 改动规模：+242 / -23 行。
- 关键文件：backend/packages/harness/deerflow/sandbox/local/list_dir.py；backend/packages/harness/deerflow/sandbox/local/local_sandbox.py；backend/tests/test_local_sandbox_provider_mounts.py。

#### 13. fix(skills): scan skill archives before install (#2561)

- 提交：`[707ed32](https://github.com/bytedance/deer-flow/commit/707ed328dd3b3364c304fac8ea0409bc86c2e1a6)`
- 日期：2026-04-28
- 做了什么：修复缺陷或回归问题，主题是“scan skill archives before install (#2561)”。
- 影响范围：主要涉及 后端。
- 改动规模：+400 / -9 行。
- 关键文件：backend/app/gateway/routers/skills.py；backend/packages/harness/deerflow/skills/**init**.py；backend/packages/harness/deerflow/skills/installer.py；backend/tests/test_client.py；backend/tests/test_client_e2e.py；backend/tests/test_skills_custom_router.py；backend/tests/test_skills_installer.py。

#### 14. fix(aio-sandbox): redact env values in container logs (#2562)

- 提交：`[f7dfb88](https://github.com/bytedance/deer-flow/commit/f7dfb88a306615ce6ec90a9bf7fabba86113f529)`
- 日期：2026-04-28
- 做了什么：修复缺陷或回归问题，主题是“redact env values in container logs (#2562)”。
- 影响范围：主要涉及 后端。
- 改动规模：+134 / -2 行。
- 关键文件：backend/packages/harness/deerflow/community/aio_sandbox/local_backend.py；backend/tests/test_aio_sandbox_local_backend.py。

#### 15. Fix the issues when reviewing 2566 persistant part (#2604)

- 提交：`[69649d8](https://github.com/bytedance/deer-flow/commit/69649d8aaef890e443bf5b5aef353fc664a920c4)`
- 日期：2026-04-28
- 做了什么：修复缺陷或回归问题，主题是“Fix the issues when reviewing 2566 persistant part (#2604)”。
- 影响范围：主要涉及 后端。
- 改动规模：+82 / -19 行。
- 关键文件：backend/packages/harness/deerflow/runtime/converters.py；backend/packages/harness/deerflow/runtime/journal.py；backend/tests/test_run_journal.py。

#### 16.  fix(security): harden auth system and fix run journal logic bug (#2593)

- 提交：`[4e4e4f9](https://github.com/bytedance/deer-flow/commit/4e4e4f92a060e90963157b99f1a425ba0f4c469d)`
- 日期：2026-04-28
- 做了什么：修复缺陷或回归问题，主题是“harden auth system and fix run journal logic bug (#2593)”。
- 影响范围：主要涉及 后端。
- 改动规模：+245 / -22 行。
- 关键文件：backend/app/gateway/auth/config.py；backend/app/gateway/auth/local_provider.py；backend/app/gateway/auth/password.py；backend/app/gateway/authz.py；backend/app/gateway/langgraph_auth.py；backend/app/gateway/routers/auth.py；backend/packages/harness/deerflow/runtime/journal.py；backend/tests/test_auth.py。

#### 17. fix(harness): constrain view_image to thread data paths (#2557)

- 提交：`[af8c0cf](https://github.com/bytedance/deer-flow/commit/af8c0cfb7830c885765fca8d5d023d6cfca045a5)`
- 日期：2026-04-28
- 做了什么：修复缺陷或回归问题，主题是“constrain view_image to thread data paths (#2557)”。
- 影响范围：主要涉及 后端。
- 改动规模：+282 / -32 行。
- 关键文件：backend/packages/harness/deerflow/agents/factory.py；backend/packages/harness/deerflow/sandbox/tools.py；backend/packages/harness/deerflow/tools/builtins/view_image_tool.py；backend/tests/test_create_deerflow_agent.py；backend/tests/test_view_image_tool.py。

#### 18. fix(frontend): add missing mock routes for runs-list, models, and suggestions (#2578)

- 提交：`[748429e](https://github.com/bytedance/deer-flow/commit/748429ef0d6a466e04549f7aee4466170727a705)`
- 日期：2026-04-26
- 做了什么：修复缺陷或回归问题，主题是“add missing mock routes for runs-list, models, and suggestions (#2578)”。
- 影响范围：主要涉及 前端。
- 改动规模：+41 / -0 行。
- 关键文件：frontend/tests/e2e/utils/mock-api.ts。

#### 19. fix: enforce 'request' parameter requirement in require_auth decorator

- 提交：`[ed9ebfa](https://github.com/bytedance/deer-flow/commit/ed9ebfac4d95cffeb0ac7604f1c8b68b821676bb)`
- 日期：2026-04-26
- 做了什么：修复缺陷或回归问题，主题是“enforce 'request' parameter requirement in require_auth decorator”。
- 影响范围：主要涉及 后端。
- 改动规模：+1 / -1 行。
- 关键文件：backend/app/gateway/authz.py。

#### 20. fix the lint error of backend

- 提交：`[897dae5](https://github.com/bytedance/deer-flow/commit/897dae5475cefdaf857c9dff3b0143b1a4b90c02)`
- 日期：2026-04-26
- 做了什么：修复缺陷或回归问题，主题是“fix the lint error of backend”。
- 影响范围：主要涉及 后端。
- 改动规模：+1 / -0 行。
- 关键文件：backend/packages/harness/deerflow/persistence/migrations/env.py。

#### 21. fix unit tests of test_upload_files and test_shutdown

- 提交：`[eba6c0e](https://github.com/bytedance/deer-flow/commit/eba6c0eab20d5381d77180b2fc2f6854d0ba1ab7)`
- 日期：2026-04-26
- 做了什么：修复缺陷或回归问题，主题是“fix unit tests of test_upload_files and test_shutdown”。
- 影响范围：主要涉及 后端。
- 改动规模：+40 / -3 行。
- 关键文件：backend/app/gateway/app.py；backend/app/gateway/authz.py。

#### 22. fix the unit tests error of agent provider

- 提交：`[60754f0](https://github.com/bytedance/deer-flow/commit/60754f0c502ce2ec03899173252fe8bd1aa71819)`
- 日期：2026-04-26
- 做了什么：修复缺陷或回归问题，主题是“fix the unit tests error of agent provider”。
- 影响范围：主要涉及 后端。
- 改动规模：+8 / -8 行。
- 关键文件：backend/tests/test_checkpointer.py；backend/tests/test_lead_agent_prompt.py。

#### 23. Potential fix for pull request finding 'Unused import'

- 提交：`[16aedf4](https://github.com/bytedance/deer-flow/commit/16aedf459a0e7ce36cf73a3973ec6f1a468da395)`
- 日期：2026-04-26
- 做了什么：修复缺陷或回归问题，主题是“Potential fix for pull request finding 'Unused import'”。
- 影响范围：主要涉及 后端。
- 改动规模：+2 / -1 行。
- 关键文件：backend/packages/harness/deerflow/persistence/migrations/env.py。

#### 24. fix: resolve make dev and test-e2e errors (#2570)

- 提交：`[c5d57b4](https://github.com/bytedance/deer-flow/commit/c5d57b453382d794174f16ab354b930d1a246ca5)`
- 日期：2026-04-26
- 做了什么：修复缺陷或回归问题，主题是“resolve make dev and test-e2e errors (#2570)”。
- 影响范围：主要涉及 后端、前端。
- 改动规模：+15 / -2 行。
- 关键文件：backend/docs/HARNESS_APP_SPLIT.md；backend/langgraph.json；frontend/playwright.config.ts；frontend/src/core/auth/server.ts。

#### 25. Fixed the warning message of uv

- 提交：`[e4ff444](https://github.com/bytedance/deer-flow/commit/e4ff444a71cd5d1fc387c036e50af24b4fbe2b3d)`
- 日期：2026-04-26
- 做了什么：修复缺陷或回归问题，主题是“Fixed the warning message of uv”。
- 影响范围：主要涉及 后端。
- 改动规模：+4 / -1 行。
- 关键文件：backend/pyproject.toml；backend/uv.toml。

#### 26. fix the lint error by updating the .prettierignore

- 提交：`[64a43bc](https://github.com/bytedance/deer-flow/commit/64a43bc4486ae2de09eafc969efb81df8ab3f401)`
- 日期：2026-04-26
- 做了什么：修复缺陷或回归问题，主题是“fix the lint error by updating the .prettierignore”。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -0 行。
- 关键文件：frontend/.prettierignore。

#### 27. try to fix the frontend e2e test errors

- 提交：`[3f88045](https://github.com/bytedance/deer-flow/commit/3f88045b98dc01730ce61cb8c2e9c80f0ba05f6e)`
- 日期：2026-04-26
- 做了什么：修复缺陷或回归问题，主题是“try to fix the frontend e2e test errors”。
- 影响范围：主要涉及 前端。
- 改动规模：+34 / -16 行。
- 关键文件：frontend/src/app/workspace/agents/new/page.tsx；frontend/src/content/en/harness/tools.mdx；frontend/src/content/zh/harness/tools.mdx。

#### 28. fix the lint errors in the frontend

- 提交：`[9eca429](https://github.com/bytedance/deer-flow/commit/9eca429a291e406929a522ecb7594ebd81a01f70)`
- 日期：2026-04-26
- 做了什么：修复缺陷或回归问题，主题是“fix the lint errors in the frontend”。
- 影响范围：主要涉及 前端。
- 改动规模：+6 / -4 行。
- 关键文件：frontend/src/app/workspace/agents/new/page.tsx；frontend/src/core/threads/hooks.ts。

#### 29. fix the lint errors in frontend

- 提交：`[28381e1](https://github.com/bytedance/deer-flow/commit/28381e1383cdd1a4ec57a659e965c46c1cd7cf6d)`
- 日期：2026-04-26
- 做了什么：修复缺陷或回归问题，主题是“fix the lint errors in frontend”。
- 影响范围：主要涉及 前端。
- 改动规模：+456 / -357 行。
- 关键文件：frontend/src/content/en/application/configuration.mdx；frontend/src/content/en/application/deployment-guide.mdx；frontend/src/content/en/application/index.mdx；frontend/src/content/en/application/operations-and-troubleshooting.mdx；frontend/src/content/en/application/quick-start.mdx；frontend/src/content/en/application/workspace-usage.mdx；frontend/src/content/en/harness/configuration.mdx；frontend/src/content/en/harness/customization.mdx。

#### 30. fix the lint error in backend

- 提交：`[829e82a](https://github.com/bytedance/deer-flow/commit/829e82a9afa404750494b658bb9c208386aec9e4)`
- 日期：2026-04-26
- 做了什么：修复缺陷或回归问题，主题是“fix the lint error in backend”。
- 影响范围：主要涉及 后端。
- 改动规模：+76 / -49 行。
- 关键文件：backend/app/gateway/routers/threads.py；backend/app/gateway/services.py；backend/packages/harness/deerflow/persistence/feedback/model.py；backend/scripts/migrate_user_isolation.py；backend/tests/_router_auth_helpers.py；backend/tests/test_memory_queue_user_isolation.py；backend/tests/test_memory_storage_user_isolation.py；backend/tests/test_memory_updater_user_isolation.py。

#### 31. fix: resolve merge conflict in pnpm-lock.yaml and clean up better-auth dependencies

- 提交：`[98a5b34](https://github.com/bytedance/deer-flow/commit/98a5b34f76ea3b0a4803f70ba3bd74451f564825)`
- 日期：2026-04-26
- 做了什么：修复缺陷或回归问题，主题是“resolve merge conflict in pnpm-lock.yaml and clean up better-auth dependencies”。
- 影响范围：主要涉及 后端、前端。
- 改动规模：+1362 / -1351 行。
- 关键文件：backend/packages/harness/deerflow/agents/memory/queue.py；backend/packages/harness/pyproject.toml；backend/uv.lock；frontend/pnpm-lock.yaml。

#### 32. docs: fix review feedback - source-map paths, memory API routes, supports_thinking, checkpointer callout

- 提交：`[716cae2](https://github.com/bytedance/deer-flow/commit/716cae20c6e63dd0f3227b83ebddb913bf3dc0e3)`
- 日期：2026-04-11
- 做了什么：修复缺陷或回归问题，主题是“fix review feedback - source-map paths, memory API routes, supports_thinking, checkpointer callout”。
- 影响范围：主要涉及 前端。
- 改动规模：+448 / -5 行。
- 关键文件：frontend/src/content/en/application/agents-and-threads.mdx；frontend/src/content/en/reference/api-gateway-reference.mdx；frontend/src/content/en/reference/configuration-reference.mdx；frontend/src/content/en/reference/runtime-flags-and-modes.mdx；frontend/src/content/en/reference/source-map.mdx。

#### 33. fix(channles):update the logger for the channel config (#2524)

- 提交：`[9dc2598](https://github.com/bytedance/deer-flow/commit/9dc25987e05e71ae87db0da22a63b4290c5e9747)`
- 日期：2026-04-26
- 做了什么：修复缺陷或回归问题，主题是“update the logger for the channel config (#2524)”。
- 影响范围：主要涉及 后端。
- 改动规模：+79 / -1 行。
- 关键文件：backend/app/channels/service.py；backend/tests/test_channels.py。

#### 34. fix(channels): accept single slack allowed user (#2481)

- 提交：`[410f0c4](https://github.com/bytedance/deer-flow/commit/410f0c48b54d5b38f8baf834baf3956eba1f8679)`
- 日期：2026-04-25
- 做了什么：修复缺陷或回归问题，主题是“accept single slack allowed user (#2481)”。
- 影响范围：主要涉及 后端、配置。
- 改动规模：+95 / -8 行。
- 关键文件：backend/app/channels/slack.py；backend/tests/test_channels.py；config.example.yaml。

#### 35. fix: cap prompt caching breakpoints at 4 to prevent API 400 errors (#2449)

- 提交：`[1f59e94](https://github.com/bytedance/deer-flow/commit/1f59e945af4a04824deda90cd41ca318670858c5)`
- 日期：2026-04-25
- 做了什么：修复缺陷或回归问题，主题是“cap prompt caching breakpoints at 4 to prevent API 400 errors (#2449)”。
- 影响范围：主要涉及 后端。
- 改动规模：+282 / -22 行。
- 关键文件：backend/packages/harness/deerflow/models/claude_provider.py；backend/tests/test_claude_provider_prompt_caching.py。

#### 36. fix: use subprocess instead of os.system in local_backend.py (#2494)

- 提交：`[950821c](https://github.com/bytedance/deer-flow/commit/950821cb9bb7fba773ba88e14cd8ade9f9151b8b)`
- 日期：2026-04-25
- 做了什么：修复缺陷或回归问题，主题是“use subprocess instead of os.system in local_backend.py (#2494)”。
- 影响范围：主要涉及 后端。
- 改动规模：+6 / -4 行。
- 关键文件：backend/packages/harness/deerflow/sandbox/local/local_sandbox.py；backend/tests/test_local_sandbox_provider_mounts.py。

#### 37. fix: read lead agent options from context (#2515)

- 提交：`[b970993](https://github.com/bytedance/deer-flow/commit/b9709934255b2f7f951fd4b2300543ef764e1473)`
- 日期：2026-04-24
- 做了什么：修复缺陷或回归问题，主题是“read lead agent options from context (#2515)”。
- 影响范围：主要涉及 后端。
- 改动规模：+139 / -19 行。
- 关键文件：backend/app/gateway/services.py；backend/packages/harness/deerflow/agents/lead_agent/agent.py；backend/tests/test_gateway_services.py；backend/tests/test_lead_agent_model_resolution.py。

#### 38. fix: gate deferred MCP tool execution (#2513)

- 提交：`[ec8a8ca](https://github.com/bytedance/deer-flow/commit/ec8a8cae38456ece2b0f9a6b32c42382127c5f0e)`
- 日期：2026-04-24
- 做了什么：修复缺陷或回归问题，主题是“gate deferred MCP tool execution (#2513)”。
- 影响范围：主要涉及 后端。
- 改动规模：+155 / -1 行。
- 关键文件：backend/packages/harness/deerflow/agents/middlewares/deferred_tool_filter_middleware.py；backend/packages/harness/deerflow/tools/builtins/tool_search.py；backend/tests/test_tool_search.py。

#### 39. fix: inherit subagent skill allowlists (#2514)

- 提交：`[d78ed5c](https://github.com/bytedance/deer-flow/commit/d78ed5c8f2673da21f1855c74341d7bda15776aa)`
- 日期：2026-04-24
- 做了什么：修复缺陷或回归问题，主题是“inherit subagent skill allowlists (#2514)”。
- 影响范围：主要涉及 后端。
- 改动规模：+103 / -3 行。
- 关键文件：backend/packages/harness/deerflow/agents/lead_agent/agent.py；backend/packages/harness/deerflow/tools/builtins/task_tool.py；backend/tests/test_task_tool_core_logic.py。

#### 40. fix(middleware): avoid rescuing non-skill tool outputs during summarization (#2458)

- 提交：`[f9ff3a6](https://github.com/bytedance/deer-flow/commit/f9ff3a698ddc64dc8dbc7404e0a2f7ef886ef0f8)`
- 日期：2026-04-24
- 做了什么：修复缺陷或回归问题，主题是“avoid rescuing non-skill tool outputs during summarization (#2458)”。
- 影响范围：主要涉及 后端、配置。
- 改动规模：+629 / -9 行。
- 关键文件：backend/docs/summarization.md；backend/packages/harness/deerflow/agents/lead_agent/agent.py；backend/packages/harness/deerflow/agents/middlewares/summarization_middleware.py；backend/packages/harness/deerflow/config/summarization_config.py；backend/tests/test_lead_agent_model_resolution.py；backend/tests/test_summarization_middleware.py；config.example.yaml。

#### 41. fix memory settings layout overflow (#2420)

- 提交：`[c2332bb](https://github.com/bytedance/deer-flow/commit/c2332bb7908e5774763c49cfb77a229832f4f57b)`
- 日期：2026-04-24
- 做了什么：修复缺陷或回归问题，主题是“fix memory settings layout overflow (#2420)”。
- 影响范围：主要涉及 前端。
- 改动规模：+11 / -11 行。
- 关键文件：frontend/src/components/workspace/settings/memory-settings-page.tsx；frontend/src/components/workspace/settings/settings-dialog.tsx。

#### 42. fix: keep debug.py interactive terminal free from background log noise (#2466)

- 提交：`[3a61126](https://github.com/bytedance/deer-flow/commit/3a61126824e9542b630d4181bac50fd101f55010)`
- 日期：2026-04-24
- 做了什么：修复缺陷或回归问题，主题是“keep debug.py interactive terminal free from background log noise (#2466)”。
- 影响范围：主要涉及 其他模块、后端。
- 改动规模：+58 / -11 行。
- 关键文件：.gitignore；backend/debug.py。

#### 43. fix(jina): log transient failures at WARNING without traceback (#2484) (#2485)

- 提交：`[e8572b9](https://github.com/bytedance/deer-flow/commit/e8572b9d0c39fbfcf6b20fdf3d5871912345593a)`
- 日期：2026-04-24
- 做了什么：修复缺陷或回归问题，主题是“log transient failures at WARNING without traceback (#2484) (#2485)”。
- 影响范围：主要涉及 后端。
- 改动规模：+24 / -2 行。
- 关键文件：backend/packages/harness/deerflow/community/jina_ai/jina_client.py；backend/tests/test_jina_client.py。

#### 44. fix(backend): fix the unit test error in backend

- 提交：`[80a7446](https://github.com/bytedance/deer-flow/commit/80a7446fd68651df4ea70cd5d0cb6f86008a26f9)`
- 日期：2026-04-24
- 做了什么：修复缺陷或回归问题，主题是“fix the unit test error in backend”。
- 影响范围：主要涉及 后端。
- 改动规模：+0 / -3 行。
- 关键文件：backend/tests/test_task_tool_core_logic.py。

#### 45. fix(backend): Updated the uv.lock with new added dependency

- 提交：`[cd12821](https://github.com/bytedance/deer-flow/commit/cd12821134f39f06c3ecf0a3598351dc303dbd65)`
- 日期：2026-04-24
- 做了什么：修复缺陷或回归问题，主题是“Updated the uv.lock with new added dependency”。
- 影响范围：主要涉及 后端。
- 改动规模：+23 / -0 行。
- 关键文件：backend/uv.lock。

#### 46. fix(gateway): bound lifespan shutdown hooks to prevent worker hang under uvicorn reload (#2331)

- 提交：`[4e72410](https://github.com/bytedance/deer-flow/commit/4e72410154ebb2c1e055d21b52211ae56c79c3d2)`
- 日期：2026-04-23
- 做了什么：修复缺陷或回归问题，主题是“bound lifespan shutdown hooks to prevent worker hang under uvicorn reload (#2331)”。
- 影响范围：主要涉及 后端。
- 改动规模：+84 / -2 行。
- 关键文件：backend/app/gateway/app.py；backend/tests/test_gateway_lifespan_shutdown.py。

#### 47. fix(skills): validate bundled SKILL.md front-matter in CI (fixes #2443) (#2457)

- 提交：`[b90f219](https://github.com/bytedance/deer-flow/commit/b90f219bd179766227a02f8e33cfa57ba5086d66)`
- 日期：2026-04-23
- 做了什么：修复缺陷或回归问题，主题是“validate bundled SKILL.md front-matter in CI (fixes #2443) (#2457)”。
- 影响范围：主要涉及 技能体系、后端。
- 改动规模：+39 / -2 行。
- 关键文件：backend/tests/test_skills_bundled.py；skills/public/bootstrap/SKILL.md；skills/public/chart-visualization/SKILL.md。

#### 48. fix: remove mismatched context param in debug.py to suppress Pydantic warning (#2446)

- 提交：`[c43c803](https://github.com/bytedance/deer-flow/commit/c43c803f66f595d16fb8227fea241d887a0f30dc)`
- 日期：2026-04-23
- 做了什么：修复缺陷或回归问题，主题是“remove mismatched context param in debug.py to suppress Pydantic warning (#2446)”。
- 影响范围：主要涉及 后端。
- 改动规模：+5 / -1 行。
- 关键文件：backend/debug.py。

#### 49. fix: rename present_file to present_files in docs and prompts (#2393)

- 提交：`[5ba1dac](https://github.com/bytedance/deer-flow/commit/5ba1dacf25085d038db09bf27c5120821f61a777)`
- 日期：2026-04-21
- 做了什么：修复缺陷或回归问题，主题是“rename present_file to present_files in docs and prompts (#2393)”。
- 影响范围：主要涉及 后端。
- 改动规模：+4 / -4 行。
- 关键文件：backend/docs/ARCHITECTURE.md；backend/docs/GUARDRAILS.md；backend/packages/harness/deerflow/agents/lead_agent/prompt.py。

#### 50. fix: remove unnecessary f-string prefixes and unused import (#2352)

- 提交：`[085c13e](https://github.com/bytedance/deer-flow/commit/085c13edc7c2b913fd432422c726fce0f2f81d66)`
- 日期：2026-04-20
- 做了什么：修复缺陷或回归问题，主题是“remove unnecessary f-string prefixes and unused import (#2352)”。
- 影响范围：主要涉及 技能体系。
- 改动规模：+8 / -9 行。
- 关键文件：skills/public/data-analysis/scripts/analyze.py；skills/public/skill-creator/eval-viewer/generate_review.py；skills/public/skill-creator/scripts/aggregate_benchmark.py；skills/public/skill-creator/scripts/quick_validate.py；skills/public/skill-creator/scripts/run_loop.py。

#### 51. Fix invalid HTML nesting in reasoning trigger during complex task rendering (#2382)

- 提交：`[ef04174](https://github.com/bytedance/deer-flow/commit/ef04174194629aa833bb56a4c5326fae860b7113)`
- 日期：2026-04-21
- 做了什么：修复缺陷或回归问题，主题是“Fix invalid HTML nesting in reasoning trigger during complex task rendering (#2382)”。
- 影响范围：主要涉及 前端。
- 改动规模：+30 / -2 行。
- 关键文件：frontend/src/components/ai-elements/reasoning.tsx；frontend/tests/unit/core/reasoning-trigger.test.ts。

#### 52. fix: resolve tool duplication and skill parser YAML inconsistencies (#1803) (#2107)

- 提交：`[6dce26a](https://github.com/bytedance/deer-flow/commit/6dce26a52e1e4c2118b6222c3308fceddf254c37)`
- 日期：2026-04-20
- 做了什么：修复缺陷或回归问题，主题是“resolve tool duplication and skill parser YAML inconsistencies (#1803) (#2107)”。
- 影响范围：主要涉及 后端。
- 改动规模：+297 / -193 行。
- 关键文件：backend/packages/harness/deerflow/skills/parser.py；backend/packages/harness/deerflow/tools/tools.py；backend/tests/test_skills_parser.py；backend/tests/test_tool_deduplication.py。

#### 53. fix(setup-agent): prevent data loss when setup fails on existing agen… (#2254)

- 提交：`[fc94e90](https://github.com/bytedance/deer-flow/commit/fc94e90f6caed2a0198af9836314dc79111c9548)`
- 日期：2026-04-20
- 做了什么：修复缺陷或回归问题，主题是“prevent data loss when setup fails on existing agen… (#2254)”。
- 影响范围：主要涉及 后端。
- 改动规模：+91 / -2 行。
- 关键文件：backend/packages/harness/deerflow/tools/builtins/setup_agent_tool.py；backend/tests/test_setup_agent_tool.py。

#### 54. fix command palette hydration mismatch (#2301)

- 提交：`[f2013f4](https://github.com/bytedance/deer-flow/commit/f2013f47aaf01d6b976fbc17af1473306334888b)`
- 日期：2026-04-20
- 做了什么：修复缺陷或回归问题，主题是“fix command palette hydration mismatch (#2301)”。
- 影响范围：主要涉及 前端。
- 改动规模：+2 / -5 行。
- 关键文件：frontend/src/components/ui/command.tsx。

#### 55. fix: use Apple Container image pull syntax (#2366)

- 提交：`[4be857f](https://github.com/bytedance/deer-flow/commit/4be857f64bf713cf52a8944fb2882aa5126f2c54)`
- 日期：2026-04-20
- 做了什么：修复缺陷或回归问题，主题是“use Apple Container image pull syntax (#2366)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+1 / -1 行。
- 关键文件：Makefile。

#### 56. fix(token-usage): enable stream usage for openai-compatible models (#2217)

- 提交：`[c99865f](https://github.com/bytedance/deer-flow/commit/c99865f53dc7d82a888a326463b146625d128ae2)`
- 日期：2026-04-19
- 做了什么：修复缺陷或回归问题，主题是“enable stream usage for openai-compatible models (#2217)”。
- 影响范围：主要涉及 后端。
- 改动规模：+111 / -0 行。
- 关键文件：backend/packages/harness/deerflow/models/factory.py；backend/tests/test_model_factory.py。

#### 57. fix(script): use portable locale for langgraph log pipeline on macOS (#2361)

- 提交：`[05f1da0](https://github.com/bytedance/deer-flow/commit/05f1da03e5a5eaa7033f98bc02f28fb62930f7f7)`
- 日期：2026-04-19
- 做了什么：修复缺陷或回归问题，主题是“use portable locale for langgraph log pipeline on macOS (#2361)”。
- 影响范围：主要涉及 脚本工具。
- 改动规模：+1 / -1 行。
- 关键文件：scripts/serve.sh。

#### 58. fix: Catch httpx.ReadError in the error handling (#2309)

- 提交：`[a62ca5d](https://github.com/bytedance/deer-flow/commit/a62ca5dd47e3bc9b3a98be699133c9c96e20bf27)`
- 日期：2026-04-19
- 做了什么：修复缺陷或回归问题，主题是“Catch httpx.ReadError in the error handling (#2309)”。
- 影响范围：主要涉及 后端。
- 改动规模：+78 / -0 行。
- 关键文件：backend/packages/harness/deerflow/agents/middlewares/llm_error_handling_middleware.py；backend/tests/test_llm_error_handling_middleware.py。

#### 59. fix(backend): make clarification messages idempotent (#2350) (#2351)

- 提交：`[f514e35](https://github.com/bytedance/deer-flow/commit/f514e35a36f30e3608719e59a0272682df5f1f44)`
- 日期：2026-04-19
- 做了什么：修复缺陷或回归问题，主题是“make clarification messages idempotent (#2350) (#2351)”。
- 影响范围：主要涉及 后端。
- 改动规模：+68 / -0 行。
- 关键文件：backend/packages/harness/deerflow/agents/middlewares/clarification_middleware.py；backend/tests/test_clarification_middleware.py。

#### 60. fix(reasoning): prevent LLM-hallucinated HTML tags from rendering as DOM elements (#2321)

- 提交：`[7c87dc5](https://github.com/bytedance/deer-flow/commit/7c87dc5bcaddefb9bad7448cb8580da303115cdd)`
- 日期：2026-04-19
- 做了什么：修复缺陷或回归问题，主题是“prevent LLM-hallucinated HTML tags from rendering as DOM elements (#2321)”。
- 影响范围：主要涉及 前端。
- 改动规模：+24 / -1 行。
- 关键文件：frontend/src/components/ai-elements/reasoning.tsx；frontend/src/core/streamdown/plugins.ts；frontend/tests/unit/core/streamdown/plugins.test.ts。

#### 61. [security] fix(uploads): require explicit opt-in for host-side document conversion (#2332)

- 提交：`[80e210f](https://github.com/bytedance/deer-flow/commit/80e210f5bb2f346d8e8136aef4694d9dadea48b0)`
- 日期：2026-04-18
- 做了什么：修复缺陷或回归问题，主题是“[security] fix(uploads): require explicit opt-in for host-side document conversion (#2332)”。
- 影响范围：主要涉及 后端、配置。
- 改动规模：+144 / -18 行。
- 关键文件：backend/app/gateway/routers/uploads.py；backend/docs/FILE_UPLOAD.md；backend/packages/harness/deerflow/utils/file_conversion.py；backend/tests/test_file_conversion.py；backend/tests/test_uploads_router.py；config.example.yaml。

#### 62. fix(subagent): inherit parent agent's tool_groups in task_tool (#2305)

- 提交：`[5547401](https://github.com/bytedance/deer-flow/commit/55474011c9fd4e7aac176df0ce580bcf749a596d)`
- 日期：2026-04-18
- 做了什么：修复缺陷或回归问题，主题是“inherit parent agent's tool_groups in task_tool (#2305)”。
- 影响范围：主要涉及 后端。
- 改动规模：+134 / -3 行。
- 关键文件：backend/packages/harness/deerflow/agents/lead_agent/agent.py；backend/packages/harness/deerflow/tools/builtins/task_tool.py；backend/tests/test_task_tool_core_logic.py。

#### 63. fix(mcp): prevent RuntimeError from escaping except block in get_cach… (#2252)

- 提交：`[24fe5fb](https://github.com/bytedance/deer-flow/commit/24fe5fbd8cea7319366495c21b57509c69414d77)`
- 日期：2026-04-18
- 做了什么：修复缺陷或回归问题，主题是“prevent RuntimeError from escaping except block in get_cach… (#2252)”。
- 影响范围：主要涉及 后端。
- 改动规模：+7 / -3 行。
- 关键文件：backend/packages/harness/deerflow/mcp/cache.py。

#### 64. fix(scripts): Cloud Provider Reports Security Issue（aliyun could） (#2323)

- 提交：`[1221448](https://github.com/bytedance/deer-flow/commit/1221448029be6b0cd3553e48a18982baaefad29d)`
- 日期：2026-04-18
- 做了什么：修复缺陷或回归问题，主题是“Cloud Provider Reports Security Issue（aliyun could） (#2323)”。
- 影响范围：主要涉及 脚本工具。
- 改动规模：+0 / -5 行。
- 关键文件：scripts/wait-for-port.sh。

#### 65. fix(frontend): add catch-all API rewrite for gateway routes (#2335)

- 提交：`[3b91df2](https://github.com/bytedance/deer-flow/commit/3b91df2b185678d469375cb8a69b5eeda36b8911)`
- 日期：2026-04-18
- 做了什么：修复缺陷或回归问题，主题是“add catch-all API rewrite for gateway routes (#2335)”。
- 影响范围：主要涉及 前端。
- 改动规模：+12 / -0 行。
- 关键文件：frontend/next.config.js。

#### 66. fix(sandbox): add missing path masking in ls_tool output (#2317)

- 提交：`[ca1b7d5](https://github.com/bytedance/deer-flow/commit/ca1b7d5f48bf46db80898af21d20f1da23ccdf69)`
- 日期：2026-04-18
- 做了什么：修复缺陷或回归问题，主题是“add missing path masking in ls_tool output (#2317)”。
- 影响范围：主要涉及 后端。
- 改动规模：+72 / -1 行。
- 关键文件：backend/packages/harness/deerflow/sandbox/tools.py；backend/tests/test_sandbox_search_tools.py。

#### 67. fix: Memory update system has cache corruption, data loss, and thread-safety bugs (#2251)

- 提交：`[898f4e8](https://github.com/bytedance/deer-flow/commit/898f4e8ac26e44286b1965443fe9fded0ed71b94)`
- 日期：2026-04-17
- 做了什么：修复缺陷或回归问题，主题是“Memory update system has cache corruption, data loss, and thread-safety bugs (#2251)”。
- 影响范围：主要涉及 后端。
- 改动规模：+159 / -9 行。
- 关键文件：backend/packages/harness/deerflow/agents/memory/storage.py；backend/packages/harness/deerflow/agents/memory/updater.py；backend/tests/test_memory_storage.py；backend/tests/test_memory_updater.py。

#### 68. fix(checkpointer): create parent directory before opening SQLite in sync provider (#2272)

- 提交：`[a664d2f](https://github.com/bytedance/deer-flow/commit/a664d2f5c4b2cbeb683e67e8bc48e2654d59695e)`
- 日期：2026-04-16
- 做了什么：修复缺陷或回归问题，主题是“create parent directory before opening SQLite in sync provider (#2272)”。
- 影响范围：主要涉及 后端。
- 改动规模：+75 / -1 行。
- 关键文件：backend/packages/harness/deerflow/agents/checkpointer/provider.py；backend/tests/test_checkpointer.py。

#### 69. fix(frontend): make Suggestion button opaque in dark mode (#2276)

- 提交：`[0e16a7f](https://github.com/bytedance/deer-flow/commit/0e16a7fe55a971f2ec69b9289d97f12e3293e5fd)`
- 日期：2026-04-16
- 做了什么：修复缺陷或回归问题，主题是“make Suggestion button opaque in dark mode (#2276)”。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -1 行。
- 关键文件：frontend/src/components/ai-elements/suggestion.tsx。

#### 70. fix(frontend): stop artifact panel from auto-opening on rehydrated write_file (#2278)

- 提交：`[4d3038a](https://github.com/bytedance/deer-flow/commit/4d3038a7b6c71e5871cf41a7fcbd901df0d7e1ba)`
- 日期：2026-04-16
- 做了什么：修复缺陷或回归问题，主题是“stop artifact panel from auto-opening on rehydrated write_file (#2278)”。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -1 行。
- 关键文件：frontend/src/components/workspace/messages/message-group.tsx。

#### 71. fix: validate bootstrap agent names before filesystem writes (#2274)

- 提交：`[2176b2b](https://github.com/bytedance/deer-flow/commit/2176b2bbfccfce25ceee08318813f96d843a13fd)`
- 日期：2026-04-16
- 做了什么：修复缺陷或回归问题，主题是“validate bootstrap agent names before filesystem writes (#2274)”。
- 影响范围：主要涉及 后端。
- 改动规模：+78 / -5 行。
- 关键文件：backend/packages/harness/deerflow/agents/lead_agent/agent.py；backend/packages/harness/deerflow/config/agents_config.py；backend/packages/harness/deerflow/tools/builtins/setup_agent_tool.py；backend/tests/test_lead_agent_model_resolution.py；backend/tests/test_setup_agent_tool.py。

#### 72. fix(frontend):lint error of message-list-item.tsx

- 提交：`[242c654](https://github.com/bytedance/deer-flow/commit/242c6540752395b2642dd8445df022c4abdf2cec)`
- 日期：2026-04-15
- 做了什么：修复缺陷或回归问题，主题是“lint error of message-list-item.tsx”。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -1 行。
- 关键文件：frontend/src/components/workspace/messages/message-list-item.tsx。

#### 73. fix(frontend): lint error of frontend

- 提交：`[0c21cbf](https://github.com/bytedance/deer-flow/commit/0c21cbf01f096f42fe68f21fecad01ce3a9b1fe8)`
- 日期：2026-04-15
- 做了什么：修复缺陷或回归问题，主题是“lint error of frontend”。
- 影响范围：主要涉及 前端。
- 改动规模：+14 / -2 行。
- 关键文件：frontend/src/components/workspace/messages/message-list-item.tsx。

#### 74. fix(frontend): add skills API rewrite rule to prevent HTML fallback (#2241)

- 提交：`[772538d](https://github.com/bytedance/deer-flow/commit/772538ddbac67c888daccc261532e0006753a4bb)`
- 日期：2026-04-15
- 做了什么：修复缺陷或回归问题，主题是“add skills API rewrite rule to prevent HTML fallback (#2241)”。
- 影响范围：主要涉及 前端。
- 改动规模：+8 / -0 行。
- 关键文件：frontend/next.config.js。

#### 75. fix(frontend): resolve /mnt/ links in markdown to artifact API URLs (#2243)

- 提交：`[35fb3dd](https://github.com/bytedance/deer-flow/commit/35fb3dd65a452c0290f516778e1cea75a9fcbc9c)`
- 日期：2026-04-15
- 做了什么：修复缺陷或回归问题，主题是“resolve /mnt/ links in markdown to artifact API URLs (#2243)”。
- 影响范围：主要涉及 前端。
- 改动规模：+8 / -1 行。
- 关键文件：frontend/src/components/workspace/messages/message-list-item.tsx。

#### 76. fix(gateway): forward agent_name and is_bootstrap from context to configurable (#2242)

- 提交：`[692f794](https://github.com/bytedance/deer-flow/commit/692f79452d56fd14c4aece225abe9784af5c0812)`
- 日期：2026-04-15
- 做了什么：修复缺陷或回归问题，主题是“forward agent_name and is_bootstrap from context to configurable (#2242)”。
- 影响范围：主要涉及 后端。
- 改动规模：+2 / -0 行。
- 关键文件：backend/app/gateway/services.py。

#### 77. fix(memory): use asyncio.to_thread for blocking file I/O in aupdate_memory (#2220)

- 提交：`[8760937](https://github.com/bytedance/deer-flow/commit/8760937439e2722203f7d759414b667f20bbb285)`
- 日期：2026-04-14
- 做了什么：修复缺陷或回归问题，主题是“use asyncio.to_thread for blocking file I/O in aupdate_memory (#2220)”。
- 影响范围：主要涉及 后端。
- 改动规模：+6 / -3 行。
- 关键文件：backend/packages/harness/deerflow/agents/memory/storage.py；backend/packages/harness/deerflow/agents/memory/updater.py。

#### 78. fix(todo-middleware): prevent premature agent exit with incomplete todos (#2135)

- 提交：`[e4f896e](https://github.com/bytedance/deer-flow/commit/e4f896e90d6be14358f64dd2e47af00f6fc82d99)`
- 日期：2026-04-14
- 做了什么：修复缺陷或回归问题，主题是“prevent premature agent exit with incomplete todos (#2135)”。
- 影响范围：主要涉及 后端。
- 改动规模：+227 / -2 行。
- 关键文件：backend/packages/harness/deerflow/agents/middlewares/todo_middleware.py；backend/tests/test_todo_middleware.py。

#### 79. fix(backend): fix uploads for mounted sandbox providers (#2199)

- 提交：`[55bc09a](https://github.com/bytedance/deer-flow/commit/55bc09ac33df555494371ab55d07fdd640feb8ff)`
- 日期：2026-04-14
- 做了什么：修复缺陷或回归问题，主题是“fix uploads for mounted sandbox providers (#2199)”。
- 影响范围：主要涉及 后端。
- 改动规模：+51 / -5 行。
- 关键文件：backend/app/gateway/routers/uploads.py；backend/packages/harness/deerflow/community/aio_sandbox/aio_sandbox_provider.py；backend/packages/harness/deerflow/sandbox/local/local_sandbox_provider.py；backend/packages/harness/deerflow/sandbox/sandbox_provider.py；backend/tests/test_uploads_router.py。

#### 80. fix(check): windows pnpm version detection in check script (#2189)

- 提交：`[9cf7153](https://github.com/bytedance/deer-flow/commit/9cf7153b1d912e4706e86359b3d640a0f9b01f31)`
- 日期：2026-04-14
- 做了什么：修复缺陷或回归问题，主题是“windows pnpm version detection in check script (#2189)”。
- 影响范围：主要涉及 后端、脚本工具。
- 改动规模：+72 / -8 行。
- 关键文件：backend/tests/test_check_script.py；scripts/check.py。

#### 81. fix(title): strip  tags from title model responses and assistant context (#1927)

- 提交：`[c91785d](https://github.com/bytedance/deer-flow/commit/c91785dd68e907eda621ae42b83a4c4b00ff15ee)`
- 日期：2026-04-14
- 做了什么：修复缺陷或回归问题，主题是“strip  tags from title model responses and assistant context (#1927)”。
- 影响范围：主要涉及 后端。
- 改动规模：+54 / -1 行。
- 关键文件：backend/packages/harness/deerflow/agents/middlewares/title_middleware.py；backend/tests/test_title_middleware_core_logic.py。

#### 82. fix(skills): avoid blocking custom skill deletion on readonly history writes (#2197)

- 提交：`[053e18e](https://github.com/bytedance/deer-flow/commit/053e18e1a6909f92140bf706cc182409c61ceb64)`
- 日期：2026-04-14
- 做了什么：修复缺陷或回归问题，主题是“avoid blocking custom skill deletion on readonly history writes (#2197)”。
- 影响范围：主要涉及 后端。
- 改动规模：+87 / -12 行。
- 关键文件：backend/app/gateway/routers/skills.py；backend/tests/test_skills_custom_router.py。

#### 83. fix: disable custom-agent management API by default (#2161)

- 提交：`[a7e7c6d](https://github.com/bytedance/deer-flow/commit/a7e7c6d667daecbade1c3e6ace992457e9f13f84)`
- 日期：2026-04-14
- 做了什么：修复缺陷或回归问题，主题是“disable custom-agent management API by default (#2161)”。
- 影响范围：主要涉及 后端、配置。
- 改动规模：+194 / -6 行。
- 关键文件：backend/app/gateway/routers/agents.py；backend/packages/harness/deerflow/config/agents_api_config.py；backend/packages/harness/deerflow/config/app_config.py；backend/tests/test_app_config_reload.py；backend/tests/test_custom_agent.py；config.example.yaml。

#### 84. fix(middleware): fix present_files thread id fallback (#2181)

- 提交：`[f4c17c6](https://github.com/bytedance/deer-flow/commit/f4c17c66ce6d49ca6332393ad5c7ae07c7257abf)`
- 日期：2026-04-13
- 做了什么：修复缺陷或回归问题，主题是“fix present_files thread id fallback (#2181)”。
- 影响范围：主要涉及 后端。
- 改动规模：+49 / -2 行。
- 关键文件：backend/packages/harness/deerflow/tools/builtins/present_file_tool.py；backend/tests/test_present_file_tool_core_logic.py。

#### 85. fix: wrap blocking readability call with asyncio.to_thread in web_fetch (#2157)

- 提交：`[1df389b](https://github.com/bytedance/deer-flow/commit/1df389b9d04d41caa56a73a0ad748f439d8b7a80)`
- 日期：2026-04-13
- 做了什么：修复缺陷或回归问题，主题是“wrap blocking readability call with asyncio.to_thread in web_fetch (#2157)”。
- 影响范围：主要涉及 后端。
- 改动规模：+30 / -1 行。
- 关键文件：backend/packages/harness/deerflow/community/jina_ai/tools.py；backend/tests/test_jina_client.py。

#### 86. fix(middleware): repair dangling tool-call history after loop interru… (#2035)

- 提交：`[5db71cb](https://github.com/bytedance/deer-flow/commit/5db71cb68ce58bbcb221493ee6008adffc286c55)`
- 日期：2026-04-12
- 做了什么：修复缺陷或回归问题，主题是“repair dangling tool-call history after loop interru… (#2035)”。
- 影响范围：主要涉及 后端、文档。
- 改动规模：+146 / -18 行。
- 关键文件：README.md；backend/CLAUDE.md；backend/packages/harness/deerflow/agents/middlewares/dangling_tool_call_middleware.py；backend/packages/harness/deerflow/agents/middlewares/loop_detection_middleware.py；backend/tests/test_dangling_tool_call_middleware.py；backend/tests/test_loop_detection_middleware.py。

#### 87. fix(sandbox): resolve paths in read_file/write_file content for LocalSandbox (#1935)

- 提交：`[dc50a7f](https://github.com/bytedance/deer-flow/commit/dc50a7fdfb1f280b8b54af05719518967eaf5c82)`
- 日期：2026-04-11
- 做了什么：修复缺陷或回归问题，主题是“resolve paths in read_file/write_file content for LocalSandbox (#1935)”。
- 影响范围：主要涉及 后端。
- 改动规模：+144 / -2 行。
- 关键文件：backend/packages/harness/deerflow/sandbox/local/local_sandbox.py；backend/tests/test_local_sandbox_provider_mounts.py。

#### 88. fix(middleware): add per-tool-type frequency detection to LoopDetectionMiddleware (#1988)

- 提交：`[5b63344](https://github.com/bytedance/deer-flow/commit/5b633449f8cfcce4117ce467f8fa778274669d2c)`
- 日期：2026-04-11
- 做了什么：修复缺陷或回归问题，主题是“add per-tool-type frequency detection to LoopDetectionMiddleware (#1988)”。
- 影响范围：主要涉及 后端。
- 改动规模：+256 / -3 行。
- 关键文件：backend/packages/harness/deerflow/agents/middlewares/loop_detection_middleware.py；backend/tests/test_loop_detection_middleware.py。

#### 89. fix(sandbox): improve sandbox security and preserve multimodal content (#2114)

- 提交：`[0256913](https://github.com/bytedance/deer-flow/commit/02569136df23006a89b34222e132b975e124a8c2)`
- 日期：2026-04-11
- 做了什么：修复缺陷或回归问题，主题是“improve sandbox security and preserve multimodal content (#2114)”。
- 影响范围：主要涉及 后端。
- 改动规模：+25 / -13 行。
- 关键文件：backend/packages/harness/deerflow/agents/middlewares/uploads_middleware.py；backend/packages/harness/deerflow/sandbox/security.py；backend/tests/test_local_bash_tool_loading.py；backend/tests/test_uploads_middleware_core_logic.py。

#### 90. fix(makefile): route Windows shell-script targets through Git Bash (#2060)

- 提交：`[092bf13](https://github.com/bytedance/deer-flow/commit/092bf13f5e1b3f9f76c08a332051b4bb76257107)`
- 日期：2026-04-11
- 做了什么：修复缺陷或回归问题，主题是“route Windows shell-script targets through Git Bash (#2060)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+23 / -52 行。
- 关键文件：Makefile。

#### 91. fix(sandbox): prevent memory leak in file operation locks using WeakValueDictionary (#2096)

- 提交：`[718dddd](https://github.com/bytedance/deer-flow/commit/718dddde75c00541e079dab9c1892c44b7a65e6b)`
- 日期：2026-04-10
- 做了什么：修复缺陷或回归问题，主题是“prevent memory leak in file operation locks using WeakValueDictionary (#2096)”。
- 影响范围：主要涉及 后端。
- 改动规模：+41 / -1 行。
- 关键文件：backend/packages/harness/deerflow/sandbox/file_operation_lock.py；backend/tests/test_sandbox_tools_security.py。

#### 92. fix(backend): stream DeerFlowClient AI text as token deltas (#1969) (#1974)

- 提交：`[b1aabe8](https://github.com/bytedance/deer-flow/commit/b1aabe88b8cb3de3b60325d968bacf39777e34c8)`
- 日期：2026-04-10
- 做了什么：修复缺陷或回归问题，主题是“stream DeerFlowClient AI text as token deltas (#1969) (#1974)”。
- 影响范围：主要涉及 后端。
- 改动规模：+917 / -56 行。
- 关键文件：backend/CLAUDE.md；backend/docs/README.md；backend/docs/STREAMING.md；backend/packages/harness/deerflow/client.py；backend/tests/test_client.py。

#### 93. fix(frontend): replace invalid "context" select field with "metadata" in threads.search (#2053)

- 提交：`[f889709](https://github.com/bytedance/deer-flow/commit/f88970985a6732f54ee5835ef67bca6fd2d057fe)`
- 日期：2026-04-10
- 做了什么：修复缺陷或回归问题，主题是“replace invalid "context" select field with "metadata" in threads.search (#2053)”。
- 影响范围：主要涉及 前端。
- 改动规模：+42 / -6 行。
- 关键文件：frontend/src/core/threads/hooks.ts；frontend/src/core/threads/utils.test.ts；frontend/src/core/threads/utils.ts。

#### 94. fix(sandbox): add startup reconciliation to prevent orphaned container leaks (#1976)

- 提交：`[0b6fa8b](https://github.com/bytedance/deer-flow/commit/0b6fa8b9e16ddc1c028b5738f4245585a38fc82f)`
- 日期：2026-04-09
- 做了什么：修复缺陷或回归问题，主题是“add startup reconciliation to prevent orphaned container leaks (#1976)”。
- 影响范围：主要涉及 后端。
- 改动规模：+1020 / -4 行。
- 关键文件：backend/packages/harness/deerflow/community/aio_sandbox/aio_sandbox_provider.py；backend/packages/harness/deerflow/community/aio_sandbox/backend.py；backend/packages/harness/deerflow/community/aio_sandbox/local_backend.py；backend/tests/test_sandbox_orphan_reconciliation.py；backend/tests/test_sandbox_orphan_reconciliation_e2e.py。

#### 95. Fix abnormal preview of HTML files (#1986)

- 提交：`[140907c](https://github.com/bytedance/deer-flow/commit/140907ce1d5ab4b8317f350deeed35e1579c0d1e)`
- 日期：2026-04-09
- 做了什么：修复缺陷或回归问题，主题是“Fix abnormal preview of HTML files (#1986)”。
- 影响范围：主要涉及 其他模块、前端。
- 改动规模：+26 / -10 行。
- 关键文件：frontend/src/components/workspace/artifacts/artifact-file-detail.tsx；pr-build/issue1955-after.png；pr-build/issue1955-before.png。

#### 96. fix(frontend): disable incomplete markdown parsing for human messages (#2014)

- 提交：`[52718b0](https://github.com/bytedance/deer-flow/commit/52718b0f23d527240eaa301024614ad9b7bd3852)`
- 日期：2026-04-09
- 做了什么：修复缺陷或回归问题，主题是“disable incomplete markdown parsing for human messages (#2014)”。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -0 行。
- 关键文件：frontend/src/components/workspace/messages/message-list-item.tsx。

#### 97. fix(agent): file-io path guidance in agent prompts (#2019)

- 提交：`[563383c](https://github.com/bytedance/deer-flow/commit/563383c60fa709b8a44490ac85f8cef5133cee7e)`
- 日期：2026-04-09
- 做了什么：修复缺陷或回归问题，主题是“file-io path guidance in agent prompts (#2019)”。
- 影响范围：主要涉及 后端。
- 改动规模：+41 / -1 行。
- 关键文件：backend/packages/harness/deerflow/agents/lead_agent/prompt.py；backend/packages/harness/deerflow/subagents/builtins/bash_agent.py；backend/packages/harness/deerflow/subagents/builtins/general_purpose.py；backend/tests/test_lead_agent_prompt.py；backend/tests/test_subagent_prompt_security.py。

#### 98. fix: resolve missing serialized kwargs in PatchedChatDeepSeek (#2025)

- 提交：`[1b74d84](https://github.com/bytedance/deer-flow/commit/1b74d8459092c95be1f8613817f47187847722ce)`
- 日期：2026-04-09
- 做了什么：修复缺陷或回归问题，主题是“resolve missing serialized kwargs in PatchedChatDeepSeek (#2025)”。
- 影响范围：主要涉及 后端。
- 改动规模：+444 / -0 行。
- 关键文件：backend/packages/harness/deerflow/models/openai_codex_provider.py；backend/packages/harness/deerflow/models/patched_deepseek.py；backend/tests/test_codex_provider.py；backend/tests/test_patched_deepseek.py。

#### 99. fix(docker): dev uv cache mounts on macOS (#2036)

- 提交：`[823f3af](https://github.com/bytedance/deer-flow/commit/823f3af98c018ff0da66673509ee6d33ab4dca61)`
- 日期：2026-04-09
- 做了什么：修复缺陷或回归问题，主题是“dev uv cache mounts on macOS (#2036)”。
- 影响范围：主要涉及 容器部署。
- 改动规模：+10 / -4 行。
- 关键文件：docker/docker-compose-dev.yaml。

#### 100. fix(docker): nginx fails to start on hosts without IPv6 (#2027)

- 提交：`[13664e9](https://github.com/bytedance/deer-flow/commit/13664e99e7dae7a7eca88f548ff4d00a8716f37a)`
- 日期：2026-04-09
- 做了什么：修复缺陷或回归问题，主题是“nginx fails to start on hosts without IPv6 (#2027)”。
- 影响范围：主要涉及 容器部署。
- 改动规模：+9 / -4 行。
- 关键文件：docker/docker-compose-dev.yaml。

#### 101. fix(frontend): preserve agent context in thread history routes (#1771)

- 提交：`[60e0abf](https://github.com/bytedance/deer-flow/commit/60e0abfdb8cdb7ee8f50722296b22c9a56e296d6)`
- 日期：2026-04-09
- 做了什么：修复缺陷或回归问题，主题是“preserve agent context in thread history routes (#1771)”。
- 影响范围：主要涉及 前端。
- 改动规模：+78 / -21 行。
- 关键文件：frontend/src/app/workspace/chats/page.tsx；frontend/src/components/workspace/recent-chat-list.tsx；frontend/src/core/threads/hooks.ts；frontend/src/core/threads/types.ts；frontend/src/core/threads/utils.test.ts；frontend/src/core/threads/utils.ts。

#### 102. fix(models): resolve duplicate keyword argument error when reasoning_effort appears in both config and kwargs (#2017)

- 提交：`[616caa9](https://github.com/bytedance/deer-flow/commit/616caa92b126c36eb7ad55b86f51578cbeb97d89)`
- 日期：2026-04-09
- 做了什么：修复缺陷或回归问题，主题是“resolve duplicate keyword argument error when reasoning_effort appears in both config and kwargs (#2017)”。
- 影响范围：主要涉及 后端。
- 改动规模：+42 / -1 行。
- 关键文件：backend/packages/harness/deerflow/models/factory.py；backend/tests/test_model_factory.py。

#### 103. fix(middleware): handle string-serialized options in ClarificationMiddleware (#1997)

- 提交：`[ad6d934](https://github.com/bytedance/deer-flow/commit/ad6d934a5fd0bf37ee937e126eb5ade1a6aec7fe)`
- 日期：2026-04-08
- 做了什么：修复缺陷或回归问题，主题是“handle string-serialized options in ClarificationMiddleware (#1997)”。
- 影响范围：主要涉及 后端。
- 改动规模：+135 / -0 行。
- 关键文件：backend/packages/harness/deerflow/agents/middlewares/clarification_middleware.py；backend/tests/test_clarification_middleware.py。

#### 104. fix(backend): use timezone-aware UTC in memory modules (fix pytest DeprecationWarnings) (#1992)

- 提交：`[29817c3](https://github.com/bytedance/deer-flow/commit/29817c3b342b4277b86ec41f0187860112af8035)`
- 日期：2026-04-08
- 做了什么：修复缺陷或回归问题，主题是“use timezone-aware UTC in memory modules (fix pytest DeprecationWarnings) (#1992)”。
- 影响范围：主要涉及 后端。
- 改动规模：+17 / -9 行。
- 关键文件：backend/packages/harness/deerflow/agents/memory/queue.py；backend/packages/harness/deerflow/agents/memory/storage.py；backend/packages/harness/deerflow/agents/memory/updater.py。

#### 105. Fix(subagent): Event loop conflict in SubagentExecutor.execute() (#1965)

- 提交：`[e5b1490](https://github.com/bytedance/deer-flow/commit/e5b149068cc34f2deeaf68a882b36889671ff05e)`
- 日期：2026-04-08
- 做了什么：修复缺陷或回归问题，主题是“Event loop conflict in SubagentExecutor.execute() (#1965)”。
- 影响范围：主要涉及 后端。
- 改动规模：+93 / -9 行。
- 关键文件：backend/packages/harness/deerflow/subagents/executor.py；backend/tests/test_subagent_executor.py。

#### 106. fix(frontend): avoid using route new as thread id (#1967)

- 提交：`[85b7ed3](https://github.com/bytedance/deer-flow/commit/85b7ed3cecc21639d0f05bb3d8cf24ebffef5cff)`
- 日期：2026-04-08
- 做了什么：修复缺陷或回归问题，主题是“avoid using route new as thread id (#1967)”。
- 影响范围：主要涉及 前端。
- 改动规模：+10 / -6 行。
- 关键文件：frontend/src/components/workspace/messages/message-list-item.tsx；frontend/src/components/workspace/messages/message-list.tsx。

#### 107. fix(frontend): prevent stale 'new' thread ID from triggering 422 history requests (#1960)

- 提交：`[2480520](https://github.com/bytedance/deer-flow/commit/24805200f0c8ba8db4a3d3317b2835f7739cf9a7)`
- 日期：2026-04-08
- 做了什么：修复缺陷或回归问题，主题是“prevent stale 'new' thread ID from triggering 422 history requests (#1960)”。
- 影响范围：主要涉及 前端。
- 改动规模：+8 / -0 行。
- 关键文件：frontend/src/components/workspace/chats/use-thread-chat.ts。

#### 108. fix(frontend): UI polish - fix CSS typo, dark mode border, and hardcoded colors (#1942)

- 提交：`[d1baf72](https://github.com/bytedance/deer-flow/commit/d1baf7212bf1616b627c5906c931c3b29ce3f90d)`
- 日期：2026-04-08
- 做了什么：修复缺陷或回归问题，主题是“UI polish - fix CSS typo, dark mode border, and hardcoded colors (#1942)”。
- 影响范围：主要涉及 前端。
- 改动规模：+10 / -11 行。
- 关键文件：frontend/src/components/landing/hero.tsx；frontend/src/components/landing/sections/case-study-section.tsx；frontend/src/components/workspace/messages/message-list.tsx；frontend/src/components/workspace/streaming-indicator.tsx；frontend/src/components/workspace/welcome.tsx；frontend/src/styles/globals.css。

#### 109. fix(provider): preserve streamed Codex output when response.completed.output is empty (#1928)

- 提交：`[0948c7a](https://github.com/bytedance/deer-flow/commit/0948c7a4e1db52ea49072c116a3de65fc7496c71)`
- 日期：2026-04-07
- 做了什么：修复缺陷或回归问题，主题是“preserve streamed Codex output when response.completed.output is empty (#1928)”。
- 影响范围：主要涉及 后端。
- 改动规模：+153 / -1 行。
- 关键文件：backend/packages/harness/deerflow/models/openai_codex_provider.py；backend/tests/test_cli_auth_providers.py。

#### 110. fix(backend): make loop detection hash tool calls by stable keys (#1911)

- 提交：`[c3170f2](https://github.com/bytedance/deer-flow/commit/c3170f22dac766b114d6ec3a962752623b71a4b0)`
- 日期：2026-04-07
- 做了什么：修复缺陷或回归问题，主题是“make loop detection hash tool calls by stable keys (#1911)”。
- 影响范围：主要涉及 后端。
- 改动规模：+144 / -18 行。
- 关键文件：backend/packages/harness/deerflow/agents/middlewares/loop_detection_middleware.py；backend/tests/test_loop_detection_middleware.py。

#### 111. fix(frontend): unify local settings runtime state and remove sidebar layout from LocalSettings (#1879)

- 提交：`[1193ac6](https://github.com/bytedance/deer-flow/commit/1193ac64dcba30febd68b89eec5260dcc0abeba8)`
- 日期：2026-04-07
- 做了什么：修复缺陷或回归问题，主题是“unify local settings runtime state and remove sidebar layout from LocalSettings (#1879)”。
- 影响范围：主要涉及 前端。
- 改动规模：+235 / -105 行。
- 关键文件：frontend/src/app/workspace/layout.tsx；frontend/src/components/query-client-provider.tsx；frontend/src/core/settings/hooks.ts；frontend/src/core/settings/index.ts；frontend/src/core/settings/local.ts；frontend/src/core/settings/store.ts。

#### 112. fix(frontend):keep DeerFlow chat thread ids in sync (#1931)

- 提交：`[ab41de2](https://github.com/bytedance/deer-flow/commit/ab41de2961968873449b25321cd0f0d36a188185)`
- 日期：2026-04-07
- 做了什么：修复缺陷或回归问题，主题是“keep DeerFlow chat thread ids in sync (#1931)”。
- 影响范围：主要涉及 前端。
- 改动规模：+34 / -10 行。
- 关键文件：frontend/src/app/workspace/agents/[agent_name]/chats/[thread_id]/page.tsx；frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/workspace/chats/use-thread-chat.ts；frontend/src/core/threads/hooks.ts。

#### 113. Fix agent gallery after bootstrap creation 修复新建智能体后菜单仍为空的问题 (#1934)

- 提交：`[4004fb8](https://github.com/bytedance/deer-flow/commit/4004fb849f4def372e9e6d9fa0d1a5951a8a48d1)`
- 日期：2026-04-07
- 做了什么：修复缺陷或回归问题，主题是“Fix agent gallery after bootstrap creation 修复新建智能体后菜单仍为空的问题 (#1934)”。
- 影响范围：主要涉及 前端。
- 改动规模：+48 / -3 行。
- 关键文件：frontend/src/app/workspace/agents/new/page.tsx。

#### 114. fix(subagents): add cooperative cancellation for subagent threads (#1873)

- 提交：`[f0dd8cb](https://github.com/bytedance/deer-flow/commit/f0dd8cb0d22bd49cdb6c7efa35ca765403d143da)`
- 日期：2026-04-07
- 做了什么：修复缺陷或回归问题，主题是“add cooperative cancellation for subagent threads (#1873)”。
- 影响范围：主要涉及 后端。
- 改动规模：+397 / -7 行。
- 关键文件：backend/packages/harness/deerflow/subagents/executor.py；backend/packages/harness/deerflow/tools/builtins/task_tool.py；backend/tests/test_subagent_executor.py；backend/tests/test_task_tool_core_logic.py。

#### 115. fix(skill): make skill prompt cache refresh nonblocking (#1924)

- 提交：`[7643a46](https://github.com/bytedance/deer-flow/commit/7643a46fcacccf6160250e1cc635989eba924fc1)`
- 日期：2026-04-07
- 做了什么：修复缺陷或回归问题，主题是“make skill prompt cache refresh nonblocking (#1924)”。
- 影响范围：主要涉及 后端。
- 改动规模：+346 / -29 行。
- 关键文件：backend/app/gateway/routers/skills.py；backend/packages/harness/deerflow/agents/**init**.py；backend/packages/harness/deerflow/agents/lead_agent/prompt.py；backend/packages/harness/deerflow/tools/skill_manage_tool.py；backend/tests/test_lead_agent_prompt.py；backend/tests/test_lead_agent_skills.py；backend/tests/test_skill_manage_tool.py；backend/tests/test_skills_custom_router.py。

#### 116. fix(frontend): resolve invalid HTML nesting and tabnabbing vulnerabilities (#1904)

- 提交：`[3acdf79](https://github.com/bytedance/deer-flow/commit/3acdf79beb5a54c9f23e2a35dee1aa27d242020d)`
- 日期：2026-04-07
- 做了什么：修复缺陷或回归问题，主题是“resolve invalid HTML nesting and tabnabbing vulnerabilities (#1904)”。
- 影响范围：主要涉及 前端。
- 改动规模：+45 / -40 行。
- 关键文件：frontend/src/components/workspace/artifacts/artifact-file-detail.tsx；frontend/src/components/workspace/artifacts/artifact-file-list.tsx；frontend/src/components/workspace/messages/message-group.tsx。

#### 117. fix(docker): restore gateway env vars and fix langgraph empty arg issue (#1915)

- 提交：`[2d068cc](https://github.com/bytedance/deer-flow/commit/2d068cc0750d5c15aa3985cb107aeb247e998785)`
- 日期：2026-04-07
- 做了什么：修复缺陷或回归问题，主题是“restore gateway env vars and fix langgraph empty arg issue (#1915)”。
- 影响范围：主要涉及 容器部署。
- 改动规模：+3 / -1 行。
- 关键文件：docker/docker-compose.yaml。

#### 118. fix(sandbox): add input sanitisation guard to SandboxAuditMiddleware (#1872)

- 提交：`[055e4df](https://github.com/bytedance/deer-flow/commit/055e4df0490dbd1bca9ffc8f6b2330668933223b)`
- 日期：2026-04-06
- 做了什么：修复缺陷或回归问题，主题是“add input sanitisation guard to SandboxAuditMiddleware (#1872)”。
- 影响范围：主要涉及 后端。
- 改动规模：+198 / -12 行。
- 关键文件：backend/packages/harness/deerflow/agents/middlewares/sandbox_audit_middleware.py；backend/tests/test_sandbox_audit_middleware.py。

#### 119. fix(backend): preserve viewed image reducer metadata (#1900)

- 提交：`[1ced6e9](https://github.com/bytedance/deer-flow/commit/1ced6e977c3d5ce7ce999b310d016da98f231736)`
- 日期：2026-04-06
- 做了什么：修复缺陷或回归问题，主题是“preserve viewed image reducer metadata (#1900)”。
- 影响范围：主要涉及 后端。
- 改动规模：+14 / -7 行。
- 关键文件：backend/packages/harness/deerflow/agents/middlewares/view_image_middleware.py；backend/tests/test_create_deerflow_agent.py。

#### 120. fix(frontend): artifact download action bounds and lint errors (#1899)

- 提交：`[f5088ed](https://github.com/bytedance/deer-flow/commit/f5088ed70d9208d4273b8b7e2ed36da5979395ee)`
- 日期：2026-04-06
- 做了什么：修复缺陷或回归问题，主题是“artifact download action bounds and lint errors (#1899)”。
- 影响范围：主要涉及 前端。
- 改动规模：+5 / -5 行。
- 关键文件：frontend/src/components/workspace/artifacts/artifact-file-list.tsx。

#### 121. fix: wrap suggestion chips without overlapping input (#1895)

- 提交：`[55e78de](https://github.com/bytedance/deer-flow/commit/55e78de6fc0e64efc0c7607be4134ffa2a073d35)`
- 日期：2026-04-06
- 做了什么：修复缺陷或回归问题，主题是“wrap suggestion chips without overlapping input (#1895)”。
- 影响范围：主要涉及 前端。
- 改动规模：+46 / -42 行。
- 关键文件：frontend/src/components/ai-elements/suggestion.tsx；frontend/src/components/workspace/input-box.tsx。

#### 122. fix: add output truncation to ls_tool to prevent context window overflow (#1896)

- 提交：`[5fd2c58](https://github.com/bytedance/deer-flow/commit/5fd2c581f6b775d693f01f88ddb68694c56921d9)`
- 日期：2026-04-06
- 做了什么：修复缺陷或回归问题，主题是“add output truncation to ls_tool to prevent context window overflow (#1896)”。
- 影响范围：主要涉及 后端、配置。
- 改动规模：+109 / -3 行。
- 关键文件：backend/packages/harness/deerflow/config/sandbox_config.py；backend/packages/harness/deerflow/sandbox/tools.py；backend/tests/test_tool_output_truncation.py；config.example.yaml。

#### 123. fix(docker): command syntax for LANGGRAPH_ALLOW_BLOCKING (#1891)

- 提交：`[d7a3eff](https://github.com/bytedance/deer-flow/commit/d7a3eff23ea62980eea210560c24f86581d0ad80)`
- 日期：2026-04-06
- 做了什么：修复缺陷或回归问题，主题是“command syntax for LANGGRAPH_ALLOW_BLOCKING (#1891)”。
- 影响范围：主要涉及 容器部署。
- 改动规模：+1 / -1 行。
- 关键文件：docker/docker-compose.yaml。

#### 124. fix(frontend): Update route.ts default backend port(#1892)

- 提交：`[ee06440](https://github.com/bytedance/deer-flow/commit/ee064402055794385877d0e6c5f24641b9eb88f5)`
- 日期：2026-04-06
- 做了什么：修复缺陷或回归问题，主题是“Update route.ts default backend port(#1892)”。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -1 行。
- 关键文件：frontend/src/app/api/memory/route.ts。

#### 125. Fix(#1702): stream resume run (#1858)

- 提交：`[7c68dd4](https://github.com/bytedance/deer-flow/commit/7c68dd4ad40119f0c210cf68abc72f83e2a8cefe)`
- 日期：2026-04-06
- 做了什么：修复缺陷或回归问题，主题是“stream resume run (#1858)”。
- 影响范围：主要涉及 后端、前端。
- 改动规模：+288 / -198 行。
- 关键文件：backend/app/gateway/routers/runs.py；backend/app/gateway/routers/thread_runs.py；backend/app/gateway/services.py；backend/packages/harness/deerflow/runtime/stream_bridge/memory.py；backend/tests/test_stream_bridge.py；frontend/src/core/threads/hooks.ts。

#### 126. fix: expose custom events from DeerFlowClient.stream() (#1827)

- 提交：`[29575c3](https://github.com/bytedance/deer-flow/commit/29575c32f9a3aa0c98bf1c7107ec1c3ef97884b3)`
- 日期：2026-04-06
- 做了什么：修复缺陷或回归问题，主题是“expose custom events from DeerFlowClient.stream() (#1827)”。
- 影响范围：主要涉及 后端。
- 改动规模：+72 / -1 行。
- 关键文件：backend/packages/harness/deerflow/client.py；backend/tests/test_client.py。

#### 127. fix(docker): recover invalid .venv to prevent startup restart loops (#1871)

- 提交：`[ed90a2e](https://github.com/bytedance/deer-flow/commit/ed90a2ee9d9a972824cece2ffe3a6af658425486)`
- 日期：2026-04-06
- 做了什么：修复缺陷或回归问题，主题是“recover invalid .venv to prevent startup restart loops (#1871)”。
- 影响范围：主要涉及 容器部署。
- 改动规模：+2 / -2 行。
- 关键文件：docker/docker-compose-dev.yaml。

#### 128. fix: escape shell variables in production langgraph command (#1877) (#1880)

- 提交：`[993fb0f](https://github.com/bytedance/deer-flow/commit/993fb0ff9db46f9b2636b4c1d42a8e3fb5b3460b)`
- 日期：2026-04-06
- 做了什么：修复缺陷或回归问题，主题是“escape shell variables in production langgraph command (#1877) (#1880)”。
- 影响范围：主要涉及 容器部署。
- 改动规模：+1 / -1 行。
- 关键文件：docker/docker-compose.yaml。

#### 129. fix(channels): normalize slack allowed user ids (#1802)

- 提交：`[117fa9b](https://github.com/bytedance/deer-flow/commit/117fa9b05d7061cb7733c04e24c7fe190ab21510)`
- 日期：2026-04-05
- 做了什么：修复缺陷或回归问题，主题是“normalize slack allowed user ids (#1802)”。
- 影响范围：主要涉及 后端。
- 改动规模：+43 / -2 行。
- 关键文件：backend/app/channels/slack.py；backend/tests/test_channels.py。

#### 130. fix: avoid command palette hydration mismatch on macOS (#1563)

- 提交：`[28474c4](https://github.com/bytedance/deer-flow/commit/28474c47cbea8db2fcd62a651996eb875bde710c)`
- 日期：2026-04-05
- 做了什么：修复缺陷或回归问题，主题是“avoid command palette hydration mismatch on macOS (#1563)”。
- 影响范围：主要涉及 前端。
- 改动规模：+4 / -10 行。
- 关键文件：frontend/src/components/workspace/command-palette.tsx。

#### 131. fix(memory): case-insensitive fact deduplication and positive reinforcement detection (#1804)

- 提交：`[8049785](https://github.com/bytedance/deer-flow/commit/8049785de666ddeb143693df21e15d76582acba8)`
- 日期：2026-04-05
- 做了什么：修复缺陷或回归问题，主题是“case-insensitive fact deduplication and positive reinforcement detection (#1804)”。
- 影响范围：主要涉及 后端。
- 改动规模：+326 / -3 行。
- 关键文件：backend/packages/harness/deerflow/agents/memory/queue.py；backend/packages/harness/deerflow/agents/memory/updater.py；backend/packages/harness/deerflow/agents/middlewares/memory_middleware.py；backend/tests/test_memory_queue.py；backend/tests/test_memory_updater.py；backend/tests/test_memory_upload_filtering.py。

#### 132. fix: preserve virtual path separator style (#1828)

- 提交：`[9ca68ff](https://github.com/bytedance/deer-flow/commit/9ca68ffaaa00e53784c84cc9c6cd18144e33efc4)`
- 日期：2026-04-05
- 做了什么：修复缺陷或回归问题，主题是“preserve virtual path separator style (#1828)”。
- 影响范围：主要涉及 后端。
- 改动规模：+75 / -4 行。
- 关键文件：backend/packages/harness/deerflow/sandbox/tools.py；backend/tests/test_sandbox_tools_security.py。

#### 133. docs: fix some broken links (#1864)

- 提交：`[d3b59a7](https://github.com/bytedance/deer-flow/commit/d3b59a7931e7fd8bd2ef88b590935de50bd77276)`
- 日期：2026-04-05
- 做了什么：修复缺陷或回归问题，主题是“fix some broken links (#1864)”。
- 影响范围：主要涉及 后端、其他模块。
- 改动规模：+4 / -4 行。
- 关键文件：CONTRIBUTING.md；backend/docs/AUTO_TITLE_GENERATION.md；backend/docs/TITLE_GENERATION_IMPLEMENTATION.md。

#### 134. fix(docker): use multi-stage build to remove build-essential from runtime image (#1846)

- 提交：`[e5416b5](https://github.com/bytedance/deer-flow/commit/e5416b539ae9bb2921e4bf58ed2375a4650e20bf)`
- 日期：2026-04-05
- 做了什么：修复缺陷或回归问题，主题是“use multi-stage build to remove build-essential from runtime image (#1846)”。
- 影响范围：主要涉及 后端、容器部署。
- 改动规模：+44 / -7 行。
- 关键文件：backend/Dockerfile；docker/docker-compose-dev.yaml。

#### 135. fix(sandbox): guard against None runtime.context in sandbox tool helpers (#1853)

- 提交：`[72d4347](https://github.com/bytedance/deer-flow/commit/72d4347adb269f0c9eb9fcb120d7fb5550a6a103)`
- 日期：2026-04-05
- 做了什么：修复缺陷或回归问题，主题是“guard against None runtime.context in sandbox tool helpers (#1853)”。
- 影响范围：主要涉及 后端。
- 改动规模：+6 / -3 行。
- 关键文件：backend/packages/harness/deerflow/sandbox/tools.py。

#### 136. fix: include soul field in GET /api/agents list response (fixes #1819) (#1863)

- 提交：`[a283d4a](https://github.com/bytedance/deer-flow/commit/a283d4a02d701ef9dc514727738646210fd82992)`
- 日期：2026-04-04
- 做了什么：修复缺陷或回归问题，主题是“include soul field in GET /api/agents list response (fixes #1819) (#1863)”。
- 影响范围：主要涉及 后端。
- 改动规模：+13 / -4 行。
- 关键文件：backend/app/gateway/routers/agents.py；backend/tests/test_custom_agent.py。

#### 137. fix: unblock concurrent threads and workspace hydration (#1839)

- 提交：`[2a150f5](https://github.com/bytedance/deer-flow/commit/2a150f5d4ab6c0e9fff504ed59faf521a94aef58)`
- 日期：2026-04-04
- 做了什么：修复缺陷或回归问题，主题是“unblock concurrent threads and workspace hydration (#1839)”。
- 影响范围：主要涉及 后端、容器部署、前端。
- 改动规模：+213 / -199 行。
- 关键文件：backend/Makefile；backend/app/gateway/routers/suggestions.py；backend/packages/harness/deerflow/agents/lead_agent/prompt.py；backend/packages/harness/deerflow/agents/middlewares/title_middleware.py；backend/packages/harness/deerflow/config/app_config.py；backend/packages/harness/deerflow/config/extensions_config.py；backend/packages/harness/deerflow/config/paths.py；backend/packages/harness/deerflow/config/skills_config.py。

#### 138. fix(frontend): keep prompt attachments from breaking before upload (#1833)

- 提交：`[1c0051c](https://github.com/bytedance/deer-flow/commit/1c0051c1db23d9075cadc7ed47f678fd52bf847b)`
- 日期：2026-04-04
- 做了什么：修复缺陷或回归问题，主题是“keep prompt attachments from breaking before upload (#1833)”。
- 影响范围：主要涉及 前端。
- 改动规模：+225 / -33 行。
- 关键文件：frontend/src/components/ai-elements/prompt-input.tsx；frontend/src/core/threads/hooks.ts；frontend/src/core/uploads/index.ts；frontend/src/core/uploads/prompt-input-files.test.mjs；frontend/src/core/uploads/prompt-input-files.ts。

#### 139. fix(frontend): block unsupported .app uploads (#1834)

- 提交：`[144c9b2](https://github.com/bytedance/deer-flow/commit/144c9b2464427d2f388815eff792e864f105d57a)`
- 日期：2026-04-04
- 做了什么：修复缺陷或回归问题，主题是“block unsupported .app uploads (#1834)”。
- 影响范围：主要涉及 前端。
- 改动规模：+137 / -9 行。
- 关键文件：frontend/src/components/ai-elements/prompt-input.tsx；frontend/src/core/uploads/file-validation.test.mjs；frontend/src/core/uploads/file-validation.ts；frontend/src/core/uploads/index.ts。

#### 140. fix(uploads): handle split-bold headings and ** ** artefacts in extract_outline (#1838)

- 提交：`[163121d](https://github.com/bytedance/deer-flow/commit/163121d327560469c508ca1cb324c428fa660700)`
- 日期：2026-04-04
- 做了什么：修复缺陷或回归问题，主题是“handle split-bold headings and ** ** artefacts in extract_outline (#1838)”。
- 影响范围：主要涉及 后端。
- 改动规模：+177 / -19 行。
- 关键文件：backend/packages/harness/deerflow/agents/middlewares/uploads_middleware.py；backend/packages/harness/deerflow/utils/file_conversion.py；backend/tests/test_file_conversion.py；backend/tests/test_uploads_middleware_core_logic.py。

#### 141. fix(frontend): resolve button hydration mismatch with undefined variant/size (#1506)

- 提交：`[6473d38](https://github.com/bytedance/deer-flow/commit/6473d389178465746a3b353e7a534e6e42a5b88c)`
- 日期：2026-04-04
- 做了什么：修复缺陷或回归问题，主题是“resolve button hydration mismatch with undefined variant/size (#1506)”。
- 影响范围：主要涉及 前端。
- 改动规模：+2 / -2 行。
- 关键文件：frontend/src/components/ui/button.tsx。

#### 142. fix: use webpack for local frontend dev in serve.sh (#1832)

- 提交：`[4ceb18c](https://github.com/bytedance/deer-flow/commit/4ceb18c6e4fe5c241ab94446516d2414a7b1b689)`
- 日期：2026-04-04
- 做了什么：修复缺陷或回归问题，主题是“use webpack for local frontend dev in serve.sh (#1832)”。
- 影响范围：主要涉及 脚本工具。
- 改动规模：+3 / -1 行。
- 关键文件：scripts/serve.sh。

#### 143. fix: remove nginx Plus-only zone/resolve directives from nginx.conf (#1837)

- 提交：`[fd31058](https://github.com/bytedance/deer-flow/commit/fd310582bd78ed90534b90058bab9910b78412fc)`
- 日期：2026-04-03
- 做了什么：修复缺陷或回归问题，主题是“remove nginx Plus-only zone/resolve directives from nginx.conf (#1837)”。
- 影响范围：主要涉及 容器部署。
- 改动规模：+7 / -8 行。
- 关键文件：docker/nginx/nginx.conf。

#### 144. fix: add missing DEER_FLOW_CONFIG_PATH and DEER_FLOW_EXTENSIONS_CONFIG_PATH env vars to gateway service (fixes #1829) (#1836)

- 提交：`[fb2d99f](https://github.com/bytedance/deer-flow/commit/fb2d99fd86eeaa997090c830b4f3908d5d78b051)`
- 日期：2026-04-03
- 做了什么：修复缺陷或回归问题，主题是“add missing DEER_FLOW_CONFIG_PATH and DEER_FLOW_EXTENSIONS_CONFIG_PATH env vars to gateway service (fixes #1829) (#1836)”。
- 影响范围：主要涉及 容器部署。
- 改动规模：+2 / -0 行。
- 关键文件：docker/docker-compose.yaml。

#### 145. fix(middleware): handle list-type AIMessage.content in LoopDetectionMiddleware (#1823)

- 提交：`[db82b59](https://github.com/bytedance/deer-flow/commit/db82b5925498f2855cffbf5f52b47164b81de638)`
- 日期：2026-04-04
- 做了什么：修复缺陷或回归问题，主题是“handle list-type AIMessage.content in LoopDetectionMiddleware (#1823)”。
- 影响范围：主要涉及 后端。
- 改动规模：+137 / -3 行。
- 关键文件：backend/packages/harness/deerflow/agents/middlewares/loop_detection_middleware.py；backend/tests/test_loop_detection_middleware.py。

#### 146. fix(uploads): fall back to configurable.thread_id when runtime.context lacks thread_id (#1814)

- 提交：`[46d0c32](https://github.com/bytedance/deer-flow/commit/46d0c329c1b9c975b877aeeb85c864e0baf273c1)`
- 日期：2026-04-03
- 做了什么：修复缺陷或回归问题，主题是“fall back to configurable.thread_id when runtime.context lacks thread_id (#1814)”。
- 影响范围：主要涉及 后端。
- 改动规模：+7 / -0 行。
- 关键文件：backend/packages/harness/deerflow/agents/middlewares/uploads_middleware.py。

#### 147. fix: replace the offline link in the lead_agent prompt (#1800)

- 提交：`[a2aba23](https://github.com/bytedance/deer-flow/commit/a2aba23962528377e5beb763498055ab5c3ce95b)`
- 日期：2026-04-03
- 做了什么：修复缺陷或回归问题，主题是“replace the offline link in the lead_agent prompt (#1800)”。
- 影响范围：主要涉及 后端。
- 改动规模：+4 / -4 行。
- 关键文件：backend/packages/harness/deerflow/agents/lead_agent/prompt.py。

#### 148. fix: guarantee END sentinel delivery when stream bridge queue is full (#1695)

- 提交：`[6dbdd46](https://github.com/bytedance/deer-flow/commit/6dbdd4674f25bc5c7d51fc863ba25ecee7de7b18)`
- 日期：2026-04-03
- 做了什么：修复缺陷或回归问题，主题是“guarantee END sentinel delivery when stream bridge queue is full (#1695)”。
- 影响范围：主要涉及 后端。
- 改动规模：+232 / -5 行。
- 关键文件：backend/packages/harness/deerflow/runtime/stream_bridge/memory.py；backend/tests/test_stream_bridge.py。

#### 149. fix: use SystemMessage+HumanMessage for follow-up question generation (#1751)

- 提交：`[83039fa](https://github.com/bytedance/deer-flow/commit/83039fa22ca3ec8beeda8cf3b788cb6d350ab154)`
- 日期：2026-04-03
- 做了什么：修复缺陷或回归问题，主题是“use SystemMessage+HumanMessage for follow-up question generation (#1751)”。
- 影响范围：主要涉及 后端。
- 改动规模：+30 / -5 行。
- 关键文件：backend/app/gateway/routers/suggestions.py；backend/tests/test_suggestions_router.py。

#### 150. fix(ui): avoid follow-up suggestion overlap (#1777)

- 提交：`[9735d73](https://github.com/bytedance/deer-flow/commit/9735d73b836b60bcfdf547bfccd7b2beaa601317)`
- 日期：2026-04-03
- 做了什么：修复缺陷或回归问题，主题是“avoid follow-up suggestion overlap (#1777)”。
- 影响范围：主要涉及 前端。
- 改动规模：+111 / -39 行。
- 关键文件：frontend/src/app/workspace/agents/[agent_name]/chats/[thread_id]/page.tsx；frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/workspace/input-box.tsx；frontend/src/components/workspace/messages/message-list.tsx。

#### 151. fix ACP mcpServers payload (#1735)

- 提交：`[4856566](https://github.com/bytedance/deer-flow/commit/48565664e06760efecaf19489ec4746eec470406)`
- 日期：2026-04-03
- 做了什么：修复缺陷或回归问题，主题是“fix ACP mcpServers payload (#1735)”。
- 影响范围：主要涉及 后端。
- 改动规模：+180 / -4 行。
- 关键文件：backend/packages/harness/deerflow/tools/builtins/invoke_acp_agent_tool.py；backend/tests/test_invoke_acp_agent_tool.py。

#### 152. fix: inject longTermBackground into memory prompt (#1734)

- 提交：`[5664b9d](https://github.com/bytedance/deer-flow/commit/5664b9d413bf3419ba7ea8031a0b808f069f75ff)`
- 日期：2026-04-03
- 做了什么：修复缺陷或回归问题，主题是“inject longTermBackground into memory prompt (#1734)”。
- 影响范围：主要涉及 后端。
- 改动规模：+23 / -0 行。
- 关键文件：backend/packages/harness/deerflow/agents/memory/prompt.py；backend/tests/test_memory_prompt_injection.py。

#### 153. fix(ui): avoid over-segmenting cjk messages (#1726)

- 提交：`[952059e](https://github.com/bytedance/deer-flow/commit/952059eb51dec40c205ea60c60063d42bc7f02d8)`
- 日期：2026-04-02
- 做了什么：修复缺陷或回归问题，主题是“avoid over-segmenting cjk messages (#1726)”。
- 影响范围：主要涉及 前端。
- 改动规模：+7 / -0 行。
- 关键文件：frontend/src/core/rehype/index.ts。

#### 154. fix: enable DanglingToolCallMiddleware for subagents (#1766)

- 提交：`[8128a3b](https://github.com/bytedance/deer-flow/commit/8128a3bc57f06582b4d899d667a5ee9451b9e9de)`
- 日期：2026-04-02
- 做了什么：修复缺陷或回归问题，主题是“enable DanglingToolCallMiddleware for subagents (#1766)”。
- 影响范围：主要涉及 后端。
- 改动规模：+1 / -1 行。
- 关键文件：backend/packages/harness/deerflow/agents/middlewares/tool_error_handling_middleware.py。

#### 155. fix(frontend): add missing rel="noopener noreferrer" to target="_blank" links (#1741)

- 提交：`[636053f](https://github.com/bytedance/deer-flow/commit/636053fb6da8a61681ab2290ef25e32d9e3f4916)`
- 日期：2026-04-02
- 做了什么：修复缺陷或回归问题，主题是“add missing rel="noopener noreferrer" to target="_blank" links (#1741)”。
- 影响范围：主要涉及 前端。
- 改动规模：+33 / -14 行。
- 关键文件：frontend/src/components/ai-elements/open-in-chat.tsx；frontend/src/components/ai-elements/sources.tsx；frontend/src/components/landing/header.tsx；frontend/src/components/landing/sections/case-study-section.tsx；frontend/src/components/landing/sections/community-section.tsx；frontend/src/components/workspace/artifacts/artifact-file-detail.tsx；frontend/src/components/workspace/artifacts/artifact-file-list.tsx；frontend/src/components/workspace/messages/message-group.tsx。

#### 156. fix(sandbox): exclude URL paths from absolute path validation (#1385) (#1419)

- 提交：`[f56d0b4](https://github.com/bytedance/deer-flow/commit/f56d0b4869722111fb4d8ae8ed79e59699acb9e2)`
- 日期：2026-04-02
- 做了什么：修复缺陷或回归问题，主题是“exclude URL paths from absolute path validation (#1385) (#1419)”。
- 影响范围：主要涉及 后端。
- 改动规模：+57 / -1 行。
- 关键文件：backend/packages/harness/deerflow/sandbox/tools.py；backend/tests/test_sandbox_tools_security.py。

#### 157. fix: prevent concurrent subagent file write conflicts in sandbox tools (#1714)

- 提交：`[a2cb38f](https://github.com/bytedance/deer-flow/commit/a2cb38f62bbd1b6d018a3368acd4bfeeff9e2fd2)`
- 日期：2026-04-02
- 做了什么：修复缺陷或回归问题，主题是“prevent concurrent subagent file write conflicts in sandbox tools (#1714)”。
- 影响范围：主要涉及 后端。
- 改动规模：+327 / -28 行。
- 关键文件：backend/CLAUDE.md；backend/README.md；backend/packages/harness/deerflow/community/aio_sandbox/aio_sandbox.py；backend/packages/harness/deerflow/sandbox/file_operation_lock.py；backend/packages/harness/deerflow/sandbox/tools.py；backend/tests/test_aio_sandbox.py；backend/tests/test_sandbox_tools_security.py。

#### 158. Fix/1681 llm call retry handling (#1683)

- 提交：`[3a672b3](https://github.com/bytedance/deer-flow/commit/3a672b39c798604abc5911371c56745260186324)`
- 日期：2026-04-02
- 做了什么：修复缺陷或回归问题，主题是“Fix/1681 llm call retry handling (#1683)”。
- 影响范围：主要涉及 后端、前端。
- 改动规模：+428 / -0 行。
- 关键文件：backend/packages/harness/deerflow/agents/middlewares/llm_error_handling_middleware.py；backend/packages/harness/deerflow/agents/middlewares/tool_error_handling_middleware.py；backend/tests/test_llm_error_handling_middleware.py；frontend/src/core/threads/hooks.ts。

#### 159. fix(frontend): persist model selection per thread (#1553)

- 提交：`[0eb6550](https://github.com/bytedance/deer-flow/commit/0eb6550cf4c3b853056de404f96937bc121f4ae9)`
- 日期：2026-04-01
- 做了什么：修复缺陷或回归问题，主题是“persist model selection per thread (#1553)”。
- 影响范围：主要涉及 前端。
- 改动规模：+133 / -44 行。
- 关键文件：frontend/src/app/workspace/agents/[agent_name]/chats/[thread_id]/page.tsx；frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/core/settings/hooks.ts；frontend/src/core/settings/local.ts。

#### 160. fix: avoid treating Feishu file paths as commands (#1654)

- 提交：`[0a37960](https://github.com/bytedance/deer-flow/commit/0a379602b80b45a1f91f5815e7171fa5d465fe63)`
- 日期：2026-04-01
- 做了什么：修复缺陷或回归问题，主题是“avoid treating Feishu file paths as commands (#1654)”。
- 影响范围：主要涉及 后端。
- 改动规模：+88 / -3 行。
- 关键文件：backend/app/channels/commands.py；backend/app/channels/feishu.py；backend/app/channels/manager.py；backend/tests/test_feishu_parser.py。

#### 161. fix(gateway): prevent 400 error when client sends context with configurable (#1660)

- 提交：`[1fb5ace](https://github.com/bytedance/deer-flow/commit/1fb5acee3956338f4844f51afb6e30a79219a14f)`
- 日期：2026-04-01
- 做了什么：修复缺陷或回归问题，主题是“prevent 400 error when client sends context with configurable (#1660)”。
- 影响范围：主要涉及 后端。
- 改动规模：+103 / -30 行。
- 关键文件：backend/app/gateway/services.py；backend/packages/harness/deerflow/runtime/runs/worker.py；backend/tests/test_gateway_services.py。

#### 162. Fix Windows startup and dependency checks (#1709)

- 提交：`[82c3dbb](https://github.com/bytedance/deer-flow/commit/82c3dbbc6bb6c7a8e5349144ffd77125d22618b2)`
- 日期：2026-04-01
- 做了什么：修复缺陷或回归问题，主题是“Fix Windows startup and dependency checks (#1709)”。
- 影响范围：主要涉及 脚本工具、文档、其他模块。
- 改动规模：+76 / -29 行。
- 关键文件：Makefile；README.md；README_zh.md；scripts/check.py；scripts/config-upgrade.sh；scripts/serve.sh；scripts/start-daemon.sh。

#### 163. fix(skills): support parsing multiline YAML strings in SKILL.md frontmatter (#1703)

- 提交：`[e97c8c9](https://github.com/bytedance/deer-flow/commit/e97c8c99431ab4f71fe0dde4fd427b14deb1c545)`
- 日期：2026-04-01
- 做了什么：修复缺陷或回归问题，主题是“support parsing multiline YAML strings in SKILL.md frontmatter (#1703)”。
- 影响范围：主要涉及 后端。
- 改动规模：+83 / -5 行。
- 关键文件：backend/packages/harness/deerflow/skills/parser.py；backend/tests/test_skills_parser.py。

#### 164. fix: share .deer-flow in docker-compose-dev for uploads (#1718)

- 提交：`[68d44f6](https://github.com/bytedance/deer-flow/commit/68d44f6755b94047177311c29ad6da0e0ee8ca9d)`
- 日期：2026-04-01
- 做了什么：修复缺陷或回归问题，主题是“share .deer-flow in docker-compose-dev for uploads (#1718)”。
- 影响范围：主要涉及 容器部署。
- 改动规模：+2 / -0 行。
- 关键文件：docker/docker-compose-dev.yaml。

#### 165. fix(gateway): merge context field into configurable for langgraph-compat runs (#1699) (#1707)

- 提交：`[c2ff59a](https://github.com/bytedance/deer-flow/commit/c2ff59a5b172049202a6d4fadd5d4e911c108334)`
- 日期：2026-04-01
- 做了什么：修复缺陷或回归问题，主题是“merge context field into configurable for langgraph-compat runs (#1699) (#1707)”。
- 影响范围：主要涉及 后端。
- 改动规模：+146 / -0 行。
- 关键文件：backend/app/gateway/routers/thread_runs.py；backend/app/gateway/services.py；backend/tests/test_gateway_services.py。

#### 166. fix: add --n-jobs-per-worker 10 to local dev Makefile (#1694)

- 提交：`[52c8c06](https://github.com/bytedance/deer-flow/commit/52c8c06cf27406b91e888d35b27c0f091d004660)`
- 日期：2026-04-01
- 做了什么：修复缺陷或回归问题，主题是“add --n-jobs-per-worker 10 to local dev Makefile (#1694)”。
- 影响范围：主要涉及 后端。
- 改动规模：+1 / -1 行。
- 关键文件：backend/Makefile。

#### 167. fix: use safe docker bind mount syntax for sandbox mounts (#1655)

- 提交：`[3e461d9](https://github.com/bytedance/deer-flow/commit/3e461d9d0896f3395408e9128f809d8744f9b4cf)`
- 日期：2026-04-01
- 做了什么：修复缺陷或回归问题，主题是“use safe docker bind mount syntax for sandbox mounts (#1655)”。
- 影响范围：主要涉及 后端。
- 改动规模：+64 / -8 行。
- 关键文件：backend/packages/harness/deerflow/community/aio_sandbox/local_backend.py；backend/tests/test_aio_sandbox_local_backend.py。

#### 168. fix(artifact): enhance artifact content loading to include URL for non-write files (#1678)

- 提交：`[cf43584](https://github.com/bytedance/deer-flow/commit/cf43584d241f96f2429b656ab95aab49c5227112)`
- 日期：2026-04-01
- 做了什么：修复缺陷或回归问题，主题是“enhance artifact content loading to include URL for non-write files (#1678)”。
- 影响范围：主要涉及 前端。
- 改动规模：+15 / -4 行。
- 关键文件：frontend/src/components/workspace/artifacts/artifact-file-detail.tsx；frontend/src/core/artifacts/hooks.ts；frontend/src/core/artifacts/loader.ts。

#### 169. fix(gateway): forward assistant_id as agent_name in build_run_config (#1667)

- 提交：`[6ff60f2](https://github.com/bytedance/deer-flow/commit/6ff60f2af1a10478329843920c7e8f6937dcbcff)`
- 日期：2026-04-01
- 做了什么：修复缺陷或回归问题，主题是“forward assistant_id as agent_name in build_run_config (#1667)”。
- 影响范围：主要涉及 后端。
- 改动规模：+104 / -7 行。
- 关键文件：backend/app/gateway/services.py；backend/tests/test_gateway_services.py。

## 2026-05

- 新功能/增强：4 条
- Bug 修复：20 条

### 新功能 / 增强

#### 1. feat(agent): add custom-agent self-updates with user isolation (#2713)

- 提交：`[59c4a3f](https://github.com/bytedance/deer-flow/commit/59c4a3f0a48904d1eada5b1934ca32a9c7d6dea7)`
- 日期：2026-05-05
- 做了什么：新增或增强功能，主题是“add custom-agent self-updates with user isolation (#2713)”。
- 影响范围：主要涉及 后端、前端。
- 改动规模：+956 / -61 行。
- 关键文件：backend/CLAUDE.md；backend/app/gateway/routers/agents.py；backend/packages/harness/deerflow/agents/lead_agent/agent.py；backend/packages/harness/deerflow/agents/lead_agent/prompt.py；backend/packages/harness/deerflow/config/agents_config.py；backend/packages/harness/deerflow/config/paths.py；backend/packages/harness/deerflow/tools/builtins/**init**.py；backend/packages/harness/deerflow/tools/builtins/setup_agent_tool.py。

#### 2. feat(github): Added container push workflow (#2709)

- 提交：`[b10eb7b](https://github.com/bytedance/deer-flow/commit/b10eb7bafcf0e95023fc1c8b2a563bf6c8e03860)`
- 日期：2026-05-04
- 做了什么：新增或增强功能，主题是“Added container push workflow (#2709)”。
- 影响范围：主要涉及 CI/CD。
- 改动规模：+101 / -0 行。
- 关键文件：.github/workflows/container.yaml。

#### 3. feat: refine token usage display modes (#2329)

- 提交：`[d02f762](https://github.com/bytedance/deer-flow/commit/d02f762ab031da715273fc742f2e00d114ae5325)`
- 日期：2026-05-04
- 做了什么：新增或增强功能，主题是“refine token usage display modes (#2329)”。
- 影响范围：主要涉及 前端、后端。
- 改动规模：+2346 / -222 行。
- 关键文件：backend/packages/harness/deerflow/agents/middlewares/token_usage_middleware.py；backend/packages/harness/deerflow/client.py；backend/tests/test_client.py；backend/tests/test_client_message_serialization.py；backend/tests/test_token_usage_middleware.py；frontend/src/app/workspace/agents/[agent_name]/chats/[thread_id]/page.tsx；frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/workspace/messages/message-group.tsx。

#### 4. feat(community): add Serper web search provider (#2630)

- 提交：`[44ab21f](https://github.com/bytedance/deer-flow/commit/44ab21fc44981eb2de9e4c0bccd2039c5195715c)`
- 日期：2026-05-02
- 做了什么：新增或增强功能，主题是“add Serper web search provider (#2630)”。
- 影响范围：主要涉及 后端、其他模块、配置。
- 改动规模：+419 / -0 行。
- 关键文件：.env.example；backend/packages/harness/deerflow/community/serper/**init**.py；backend/packages/harness/deerflow/community/serper/tools.py；backend/tests/test_serper_tools.py；config.example.yaml。

### Bug 修复

#### 1. fix(config): reset config-backed singletons on hot reload (#2588)

- 提交：`[4ead2c6](https://github.com/bytedance/deer-flow/commit/4ead2c6b197bcfa863b8381b3e30484060e41e0c)`
- 日期：2026-05-06
- 做了什么：修复缺陷或回归问题，主题是“reset config-backed singletons on hot reload (#2588)”。
- 影响范围：主要涉及 后端。
- 改动规模：+259 / -48 行。
- 关键文件：backend/packages/harness/deerflow/config/app_config.py；backend/packages/harness/deerflow/config/checkpointer_config.py；backend/packages/harness/deerflow/config/stream_bridge_config.py；backend/packages/harness/deerflow/config/subagents_config.py；backend/tests/test_app_config_reload.py。

#### 2. fix(loop-detection): keep tool-call pairing on warn injection (#2724) (#2725)

- 提交：`[e8675f2](https://github.com/bytedance/deer-flow/commit/e8675f266ddfdaa67edd9c13134bfdf8315d7751)`
- 日期：2026-05-05
- 做了什么：修复缺陷或回归问题，主题是“keep tool-call pairing on warn injection (#2724) (#2725)”。
- 影响范围：主要涉及 后端。
- 改动规模：+106 / -13 行。
- 关键文件：backend/app/channels/manager.py；backend/packages/harness/deerflow/agents/middlewares/loop_detection_middleware.py；backend/tests/test_channels.py；backend/tests/test_loop_detection_middleware.py。

#### 3. fix: Supplement list_running in RemoteSandboxBackend (#2716)

- 提交：`[680187d](https://github.com/bytedance/deer-flow/commit/680187ddc26fd94850425b33bd3dd6d414b7631e)`
- 日期：2026-05-05
- 做了什么：修复缺陷或回归问题，主题是“Supplement list_running in RemoteSandboxBackend (#2716)”。
- 影响范围：主要涉及 后端。
- 改动规模：+337 / -0 行。
- 关键文件：backend/packages/harness/deerflow/community/aio_sandbox/remote_backend.py；backend/tests/test_remote_sandbox_backend.py。

#### 4. fix(frontend): restore localhost fallback for getGatewayConfig in prod mode (#2705) (#2718)

- 提交：`[aded753](https://github.com/bytedance/deer-flow/commit/aded753de3981ecda82145439e92e2a5d0db758b)`
- 日期：2026-05-05
- 做了什么：修复缺陷或回归问题，主题是“restore localhost fallback for getGatewayConfig in prod mode (#2705) (#2718)”。
- 影响范围：主要涉及 前端、其他模块。
- 改动规模：+131 / -7 行。
- 关键文件：.env.example；frontend/.env.example；frontend/src/core/auth/gateway-config.ts；frontend/tests/unit/core/auth/gateway-config.test.ts。

#### 5. fix(docker):force ngix to resolve upstream names at request time (#2717)

- 提交：`[028493b](https://github.com/bytedance/deer-flow/commit/028493bfd888a4672b8f36af5b82be36cac98c66)`
- 日期：2026-05-05
- 做了什么：修复缺陷或回归问题，主题是“force ngix to resolve upstream names at request time (#2717)”。
- 影响范围：主要涉及 后端、容器部署。
- 改动规模：+20 / -28 行。
- 关键文件：backend/tests/test_gateway_runtime_cleanup.py；docker/nginx/nginx.conf。

#### 6. fix(channels): preserve clarification conversation history across follow-up turns (#2444)

- 提交：`[8e48b7e](https://github.com/bytedance/deer-flow/commit/8e48b7e85c47625d44c51600b6a496ee5e3c1906)`
- 日期：2026-05-04
- 做了什么：修复缺陷或回归问题，主题是“preserve clarification conversation history across follow-up turns (#2444)”。
- 影响范围：主要涉及 后端。
- 改动规模：+138 / -0 行。
- 关键文件：backend/app/channels/manager.py；backend/tests/test_channels.py。

#### 7. fix(i18n): add Chinese translations for account settings page (#2712)

- 提交：`[af6e48c](https://github.com/bytedance/deer-flow/commit/af6e48ccaaf816cc0990439820b13d59a4499bda)`
- 日期：2026-05-04
- 做了什么：修复缺陷或回归问题，主题是“add Chinese translations for account settings page (#2712)”。
- 影响范围：主要涉及 前端。
- 改动规模：+73 / -14 行。
- 关键文件：frontend/src/components/workspace/settings/account-settings-page.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts；frontend/src/core/i18n/locales/zh-CN.ts。

#### 8. fix(docker): set UTF-8 locale to prevent ASCII encoding errors in minimal containers (#2707)

- 提交：`[82e7936](https://github.com/bytedance/deer-flow/commit/82e7936d36d603a33e3d3d8d785e180ea6d074f6)`
- 日期：2026-05-04
- 做了什么：修复缺陷或回归问题，主题是“set UTF-8 locale to prevent ASCII encoding errors in minimal containers (#2707)”。
- 影响范围：主要涉及 后端。
- 改动规模：+10 / -0 行。
- 关键文件：backend/Dockerfile。

#### 9. fix(frontend): avoid misleading error message when agent api is disable (#2697) (#2698)

- 提交：`[222a777](https://github.com/bytedance/deer-flow/commit/222a7773cbb6abfd44ca127508c277bbbc39c842)`
- 日期：2026-05-04
- 做了什么：修复缺陷或回归问题，主题是“avoid misleading error message when agent api is disable (#2697) (#2698)”。
- 影响范围：主要涉及 前端。
- 改动规模：+31 / -1 行。
- 关键文件：frontend/src/app/workspace/agents/new/page.tsx；frontend/src/core/agents/api.ts；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts；frontend/src/core/i18n/locales/zh-CN.ts。

#### 10. fix(harness): restore legacy skills path fallback (#2694) (#2696)

- 提交：`[f80ac96](https://github.com/bytedance/deer-flow/commit/f80ac961ec8cf12dec41b36d47c794e25da6b0e4)`
- 日期：2026-05-03
- 做了什么：修复缺陷或回归问题，主题是“restore legacy skills path fallback (#2694) (#2696)”。
- 影响范围：主要涉及 后端。
- 改动规模：+63 / -4 行。
- 关键文件：backend/packages/harness/deerflow/config/skills_config.py；backend/tests/test_runtime_paths.py；backend/tests/test_skills_loader.py。

#### 11. [security] fix(upload): reject symlinked upload destinations (#2623)

- 提交：`[e543bbf](https://github.com/bytedance/deer-flow/commit/e543bbf5d6b657be05e90ca4264c98cc2c3add70)`
- 日期：2026-05-02
- 做了什么：修复缺陷或回归问题，主题是“[security] fix(upload): reject symlinked upload destinations (#2623)”。
- 影响范围：主要涉及 后端。
- 改动规模：+369 / -16 行。
- 关键文件：backend/app/channels/manager.py；backend/app/gateway/routers/uploads.py；backend/packages/harness/deerflow/uploads/manager.py；backend/tests/test_channel_file_attachments.py；backend/tests/test_uploads_manager.py；backend/tests/test_uploads_router.py。

#### 12. fix(gateway): return ISO 8601 timestamps from threads endpoints (#2599)

- 提交：`[ca3332f](https://github.com/bytedance/deer-flow/commit/ca3332f8bf17d848b82cc85863ca955ed5b9adb8)`
- 日期：2026-05-02
- 做了什么：修复缺陷或回归问题，主题是“return ISO 8601 timestamps from threads endpoints (#2599)”。
- 影响范围：主要涉及 后端。
- 改动规模：+494 / -32 行。
- 关键文件：backend/app/gateway/routers/threads.py；backend/packages/harness/deerflow/persistence/thread_meta/memory.py；backend/packages/harness/deerflow/runtime/runs/manager.py；backend/packages/harness/deerflow/utils/time.py；backend/tests/test_threads_router.py；backend/tests/test_utils_time.py。

#### 13. fix(runtime): make rollback restore checkpoint supersede newer checkpoints (#2582)

- 提交：`[17447fc](https://github.com/bytedance/deer-flow/commit/17447fccbe91aa685f5363d85ee2b5c0afa323ce)`
- 日期：2026-05-02
- 做了什么：修复缺陷或回归问题，主题是“make rollback restore checkpoint supersede newer checkpoints (#2582)”。
- 影响范围：主要涉及 后端。
- 改动规模：+75 / -19 行。
- 关键文件：backend/app/gateway/routers/threads.py；backend/packages/harness/deerflow/runtime/runs/worker.py；backend/pyproject.toml；backend/tests/test_run_worker_rollback.py。

#### 14. fix(sandbox): pass no_change_timeout to exec_command to prevent 120s premature termination (#2685)

- 提交：`[189b824](https://github.com/bytedance/deer-flow/commit/189b82405c2b5e65652fe474ad9e1b334277a606)`
- 日期：2026-05-01
- 做了什么：修复缺陷或回归问题，主题是“pass no_change_timeout to exec_command to prevent 120s premature termination (#2685)”。
- 影响范围：主要涉及 后端。
- 改动规模：+61 / -3 行。
- 关键文件：backend/packages/harness/deerflow/community/aio_sandbox/aio_sandbox.py；backend/tests/test_aio_sandbox.py。

#### 15. fix(subagents): use model override for tools and middleware (#2641)

- 提交：`[487c1d9](https://github.com/bytedance/deer-flow/commit/487c1d939fb150d107bf41f9b8a6508e06454610)`
- 日期：2026-05-01
- 做了什么：修复缺陷或回归问题，主题是“use model override for tools and middleware (#2641)”。
- 影响范围：主要涉及 后端。
- 改动规模：+219 / -39 行。
- 关键文件：backend/packages/harness/deerflow/agents/middlewares/tool_error_handling_middleware.py；backend/packages/harness/deerflow/subagents/config.py；backend/packages/harness/deerflow/subagents/executor.py；backend/packages/harness/deerflow/tools/builtins/task_tool.py；backend/tests/test_subagent_executor.py；backend/tests/test_task_tool_core_logic.py；backend/tests/test_tool_error_handling_middleware.py。

#### 16. fix(harness): resolve runtime paths from project root (#2642)

- 提交：`[c09c334](https://github.com/bytedance/deer-flow/commit/c09c33454458f2d6b7dc1c1352a440ba49746072)`
- 日期：2026-05-01
- 做了什么：修复缺陷或回归问题，主题是“resolve runtime paths from project root (#2642)”。
- 影响范围：主要涉及 后端、文档、容器部署。
- 改动规模：+284 / -55 行。
- 关键文件：README.md；README_zh.md；backend/docs/CONFIGURATION.md；backend/docs/SETUP.md；backend/packages/harness/deerflow/config/app_config.py；backend/packages/harness/deerflow/config/extensions_config.py；backend/packages/harness/deerflow/config/paths.py；backend/packages/harness/deerflow/config/runtime_paths.py。

#### 17. fix(uploads): enforce streaming upload limits in gateway (#2589)

- 提交：`[8939cca](https://github.com/bytedance/deer-flow/commit/8939ccaed2f03ba831b16c83605d09b80f36e632)`
- 日期：2026-05-01
- 做了什么：修复缺陷或回归问题，主题是“enforce streaming upload limits in gateway (#2589)”。
- 影响范围：主要涉及 后端、配置。
- 改动规模：+393 / -14 行。
- 关键文件：backend/app/gateway/routers/uploads.py；backend/docs/FILE_UPLOAD.md；backend/tests/test_uploads_router.py；config.example.yaml。

#### 18. fix(subagents): propagate user context across threaded execution (#2676)

- 提交：`[83938cf](https://github.com/bytedance/deer-flow/commit/83938cf35ad3c764378e92efc643ef5feb964f23)`
- 日期：2026-05-01
- 做了什么：修复缺陷或回归问题，主题是“propagate user context across threaded execution (#2676)”。
- 影响范围：主要涉及 后端。
- 改动规模：+88 / -10 行。
- 关键文件：backend/packages/harness/deerflow/subagents/executor.py；backend/tests/test_subagent_executor.py。

#### 19. fix(agents): propagate agent_name into ToolRuntime.context for setup_agent (#2679)

- 提交：`[78633c6](https://github.com/bytedance/deer-flow/commit/78633c69acd20f609c9caf42bcc7854a8cbcdac3)`
- 日期：2026-05-01
- 做了什么：修复缺陷或回归问题，主题是“propagate agent_name into ToolRuntime.context for setup_agent (#2679)”。
- 影响范围：主要涉及 后端。
- 改动规模：+133 / -25 行。
- 关键文件：backend/app/gateway/services.py；backend/packages/harness/deerflow/runtime/runs/worker.py；backend/tests/test_gateway_services.py；backend/tests/test_run_worker_rollback.py。

#### 20. fix: keep lead agent graph factory signature compatible (#2678)

- 提交：`[8b61c94](https://github.com/bytedance/deer-flow/commit/8b61c94e1ddce6d2c0dd7b5d234b3c3987935054)`
- 日期：2026-05-01
- 做了什么：修复缺陷或回归问题，主题是“keep lead agent graph factory signature compatible (#2678)”。
- 影响范围：主要涉及 后端。
- 改动规模：+46 / -2 行。
- 关键文件：backend/packages/harness/deerflow/agents/lead_agent/agent.py；backend/tests/test_lead_agent_model_resolution.py。

