# Deer-Flow 近一年按月 Commit 中文逐条分析（Bug 修复）

> 数据源：`origin/main` 最近12个月。

> 说明：仅纳入“Bug 修复”相关提交；每条包含做了什么、影响模块、改动规模、关键文件。

> 包含：缺陷修复、回归修复、稳定性修复（按 commit message 关键词自动识别）。

GitHub 提交页：<https://github.com/bytedance/deer-flow/commits/main/>

## 2025-06

- 提交数：18 条

#### 1. fix: next server fetch error (#374)
- 提交：[`52dfdd8`](https://github.com/bytedance/deer-flow/commit/52dfdd83aea8f0ba554d535f6a90aa3313e05be1)
- 日期：2025-06-27
- 做了什么：修复缺陷或回归问题，主题是“next server fetch error (#374)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+37 / -45 行。
- 关键文件：web/src/app/chat/components/input-box.tsx；web/src/app/layout.tsx；web/src/components/deer-flow/message-input.tsx；web/src/core/api/config.ts；web/src/core/api/hooks.ts。

#### 2. fix: the lint error of llm.py (#369)
- 提交：[`f27c96e`](https://github.com/bytedance/deer-flow/commit/f27c96e692ac9a8ebf6379a5d1ecb6f32fbcc3db)
- 日期：2025-06-26
- 做了什么：修复缺陷或回归问题，主题是“the lint error of llm.py (#369)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+1 / -2 行。
- 关键文件：src/llms/llm.py。

#### 3. fix: replace json before js fence (#344)
- 提交：[`aa06cd6`](https://github.com/bytedance/deer-flow/commit/aa06cd6fb64c63d47d8c7033e13689f0491cbf33)
- 日期：2025-06-26
- 做了什么：修复缺陷或回归问题，主题是“replace json before js fence (#344)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+1 / -1 行。
- 关键文件：web/src/core/utils/json.ts。

#### 4. fix: settings tab display name (#250)
- 提交：[`82e1b65`](https://github.com/bytedance/deer-flow/commit/82e1b65792c5a663b61c2b94a417824a893ea8fb)
- 日期：2025-06-19
- 做了什么：修复缺陷或回归问题，主题是“settings tab display name (#250)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+1 / -0 行。
- 关键文件：web/src/app/settings/tabs/mcp-tab.tsx。

#### 5. Fix: the test errors of test_nodes (#345)
- 提交：[`89f3d73`](https://github.com/bytedance/deer-flow/commit/89f3d731c94e7e8618573c5328bf65e1885c9874)
- 日期：2025-06-18
- 做了什么：修复缺陷或回归问题，主题是“the test errors of test_nodes (#345)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+3 / -2 行。
- 关键文件：tests/integration/test_nodes.py。

#### 6. fix: update several links related to volcengine in Readme (#333)
- 提交：[`30a189c`](https://github.com/bytedance/deer-flow/commit/30a189cf26836f87574b3efdcc9b3265a91946ea)
- 日期：2025-06-17
- 做了什么：修复缺陷或回归问题，主题是“update several links related to volcengine in Readme (#333)”。
- 影响范围：主要涉及 文档。
- 改动规模：+3 / -9 行。
- 关键文件：README.md；README_zh.md。

#### 7. fix: add line breaks to mcp edit dialog (#313)
- 提交：[`8823ffd`](https://github.com/bytedance/deer-flow/commit/8823ffdb6ab33572708ff5924c889fda96428e43)
- 日期：2025-06-17
- 做了什么：修复缺陷或回归问题，主题是“add line breaks to mcp edit dialog (#313)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+1 / -1 行。
- 关键文件：web/src/app/settings/dialogs/add-mcp-server-dialog.tsx。

#### 8. fix(web): priority displayName for settings name error (#336)
- 提交：[`4fe4315`](https://github.com/bytedance/deer-flow/commit/4fe43153b147069cc47c9c99299c879002f99974)
- 日期：2025-06-17
- 做了什么：修复缺陷或回归问题，主题是“priority displayName for settings name error (#336)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+4 / -2 行。
- 关键文件：web/src/app/settings/tabs/about-tab.tsx；web/src/app/settings/tabs/general-tab.tsx；web/src/app/settings/tabs/index.tsx；web/src/app/settings/tabs/mcp-tab.tsx。

#### 9. Revert "fix: solves the malformed json output and pydantic validation error p…" (#325)
- 提交：[`4fb053b`](https://github.com/bytedance/deer-flow/commit/4fb053b6d22f3960dc79141f05dc3220f6d2afd9)
- 日期：2025-06-14
- 做了什么：修复缺陷或回归问题，主题是“Revert "fix: solves the malformed json output and pydantic validation error p…" (#325)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+1 / -2 行。
- 关键文件：src/graph/nodes.py。

#### 10. fix: solves the malformed json output and pydantic validation error produced by the 'planner' node by forcing the llm response to strictly comply with the pydantic 'Plan' model (#322)
- 提交：[`a7315b4`](https://github.com/bytedance/deer-flow/commit/a7315b46df1ecf7a59b1b8c80dd7cf2adc8552ad)
- 日期：2025-06-13
- 做了什么：修复缺陷或回归问题，主题是“solves the malformed json output and pydantic validation error produced by the 'planner' node by forcing the llm response to strictly comply with the pydantic 'Plan' model (#322)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+2 / -1 行。
- 关键文件：src/graph/nodes.py。

#### 11. fix: mcp config styles (#320)
- 提交：[`03e6a1a`](https://github.com/bytedance/deer-flow/commit/03e6a1a6e799ad20a25b8dc741541d5015ebcfb3)
- 日期：2025-06-13
- 做了什么：修复缺陷或回归问题，主题是“mcp config styles (#320)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+3 / -1 行。
- 关键文件：web/src/app/settings/dialogs/add-mcp-server-dialog.tsx；web/src/components/deer-flow/link.tsx。

#### 12. fix: input text not clear when click submit button (#303)
- 提交：[`397ac57`](https://github.com/bytedance/deer-flow/commit/397ac572358fce6ec65d343a855b1bd34350e435)
- 日期：2025-06-11
- 做了什么：修复缺陷或回归问题，主题是“input text not clear when click submit button (#303)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+1 / -0 行。
- 关键文件：web/src/components/deer-flow/message-input.tsx。

#### 13. fix: enable proxy support in aiohttp by adding trust_env=True (#289)
- 提交：[`cda3870`](https://github.com/bytedance/deer-flow/commit/cda3870adddfdc77a379bf553dc33222996a7cc2)
- 日期：2025-06-07
- 做了什么：修复缺陷或回归问题，主题是“enable proxy support in aiohttp by adding trust_env=True (#289)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+1 / -1 行。
- 关键文件：src/tools/tavily_search/tavily_search_api_wrapper.py。

#### 14. fix: web start with dotenv (#282)
- 提交：[`73ac8ae`](https://github.com/bytedance/deer-flow/commit/73ac8ae45a2f0a5caf35b45d601d080af6abf91f)
- 日期：2025-06-05
- 做了什么：修复缺陷或回归问题，主题是“web start with dotenv (#282)”。
- 影响范围：主要涉及 其他模块、配置。
- 改动规模：+29 / -2 行。
- 关键文件：web/package.json；web/pnpm-lock.yaml。

#### 15. fix: correct placeholder for API key in configuration guide (#278)
- 提交：[`91648c4`](https://github.com/bytedance/deer-flow/commit/91648c42102fb2dcddebf0fabbdd2d76312b03a6)
- 日期：2025-06-05
- 做了什么：修复缺陷或回归问题，主题是“correct placeholder for API key in configuration guide (#278)”。
- 影响范围：主要涉及 文档。
- 改动规模：+1 / -1 行。
- 关键文件：docs/configuration_guide.md。

#### 16. fix: do not return the server side exception to client (#277)
- 提交：[`9525780`](https://github.com/bytedance/deer-flow/commit/95257800d204eae24379c976760f5cc6dc24dbc8)
- 日期：2025-06-05
- 做了什么：修复缺陷或回归问题，主题是“do not return the server side exception to client (#277)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+7 / -5 行。
- 关键文件：src/server/app.py。

#### 17. fix:added sanitizing check on the log message (#272)
- 提交：[`45568ca`](https://github.com/bytedance/deer-flow/commit/45568ca95b33717d85a7a967a462430a094720aa)
- 日期：2025-06-03
- 做了什么：修复缺陷或回归问题，主题是“added sanitizing check on the log message (#272)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+4 / -2 行。
- 关键文件：src/server/app.py；src/tools/tts.py。

#### 18. fix: added permissions setting in the workflow (#273)
- 提交：[`db3e746`](https://github.com/bytedance/deer-flow/commit/db3e74629f52003ceb0cc029c01db5a400abc491)
- 日期：2025-06-03
- 做了什么：修复缺陷或回归问题，主题是“added permissions setting in the workflow (#273)”。
- 影响范围：主要涉及 CI/CD、其他模块。
- 改动规模：+9 / -1 行。
- 关键文件：.github/workflows/lint.yaml；.github/workflows/unittest.yaml；src/tools/retriever.py。

## 2025-07

- 提交数：30 条

#### 1. fix: build of the web (#492)
- 提交：[`ba7509d`](https://github.com/bytedance/deer-flow/commit/ba7509d9ae10158a6e241fc15b154a29788fe467)
- 日期：2025-07-31
- 做了什么：修复缺陷或回归问题，主题是“build of the web (#492)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+6 / -5 行。
- 关键文件：web/src/core/mcp/types.ts；web/src/core/store/settings-store.ts。

#### 2. fix:try to fix the docker build of front-end (#487)
- 提交：[`aca9dcf`](https://github.com/bytedance/deer-flow/commit/aca9dcf643c49bc970a404d519ff3260d6086753)
- 日期：2025-07-30
- 做了什么：修复缺陷或回归问题，主题是“try to fix the docker build of front-end (#487)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+3 / -3 行。
- 关键文件：web/src/core/store/settings-store.ts。

#### 3. fix: docker build with uv.lock updated (#486)
- 提交：[`98ef913`](https://github.com/bytedance/deer-flow/commit/98ef913b881c2fc172c51017802d2911f979ae6c)
- 日期：2025-07-29
- 做了什么：修复缺陷或回归问题，主题是“docker build with uv.lock updated (#486)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+40 / -11 行。
- 关键文件：uv.lock。

#### 4. fix: Add streamable MCP server support (#468)
- 提交：[`e178483`](https://github.com/bytedance/deer-flow/commit/e178483971a7c98c6c1b782df973a5d0d25adf9a)
- 日期：2025-07-29
- 做了什么：修复缺陷或回归问题，主题是“Add streamable MCP server support (#468)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+27 / -6 行。
- 关键文件：pyproject.toml；src/server/mcp_utils.py；tests/unit/server/test_mcp_utils.py；web/src/app/settings/dialogs/add-mcp-server-dialog.tsx；web/src/core/mcp/schema.ts；web/src/core/mcp/types.ts。

#### 5. fix: dotenv flags error (#472)
- 提交：[`89c1b68`](https://github.com/bytedance/deer-flow/commit/89c1b689dce49fe9854e46175bdcd277093fe82a)
- 日期：2025-07-24
- 做了什么：修复缺陷或回归问题，主题是“dotenv flags error (#472)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+2 / -2 行。
- 关键文件：web/package.json。

#### 6. fix:env AGENT_RECURSION_LIMIT not work (#453)
- 提交：[`32d8e51`](https://github.com/bytedance/deer-flow/commit/32d8e514e1ed17d6dd3fd977d2816a898bdb0a89)
- 日期：2025-07-22
- 做了什么：修复缺陷或回归问题，主题是“env AGENT_RECURSION_LIMIT not work (#453)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+84 / -1 行。
- 关键文件：src/config/configuration.py；src/server/app.py；src/workflow.py；tests/unit/config/test_configuration.py。

#### 7. Fix empty tuple agent (#458)
- 提交：[`b197b0f`](https://github.com/bytedance/deer-flow/commit/b197b0f4cb46adcf5e1bc26355d3d1aafac37178)
- 日期：2025-07-22
- 做了什么：修复缺陷或回归问题，主题是“Fix empty tuple agent (#458)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+1 / -1 行。
- 关键文件：src/server/app.py。

#### 8. fix: JSON parse error in link.tsx (#448)
- 提交：[`e6ba1fc`](https://github.com/bytedance/deer-flow/commit/e6ba1fcd82d67f6deaa42f2e870df04bb694fa65)
- 日期：2025-07-20
- 做了什么：修复缺陷或回归问题，主题是“JSON parse error in link.tsx (#448)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+2 / -1 行。
- 关键文件：web/src/components/deer-flow/link.tsx。

#### 9. fix: keep applying quick fix for #446 (#450)
- 提交：[`4d65d20`](https://github.com/bytedance/deer-flow/commit/4d65d20f011f20cfa4376b8251aa533917c0ae75)
- 日期：2025-07-20
- 做了什么：修复缺陷或回归问题，主题是“keep applying quick fix for #446 (#450)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+3 / -5 行。
- 关键文件：.env.example；src/server/app.py。

#### 10. fix: the Backend returns 400 error (#449)
- 提交：[`ff67366`](https://github.com/bytedance/deer-flow/commit/ff67366c5c508e8c0be2ada8d40f3544cd86dcfe)
- 日期：2025-07-20
- 做了什么：修复缺陷或回归问题，主题是“the Backend returns 400 error (#449)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+8 / -4 行。
- 关键文件：.env.example；src/server/app.py。

#### 11. fix: fix the bug introduced by coordinator messages update (#445)
- 提交：[`dbb24d7`](https://github.com/bytedance/deer-flow/commit/dbb24d7d146470613227ab99519a1e3c2905433d)
- 日期：2025-07-18
- 做了什么：修复缺陷或回归问题，主题是“fix the bug introduced by coordinator messages update (#445)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+4 / -8 行。
- 关键文件：src/graph/nodes.py。

#### 12. fix:planner AttributeError 'list' object has no attribute 'get' (#436)
- 提交：[`f17b06f`](https://github.com/bytedance/deer-flow/commit/f17b06f2060f2ca371a9c016516a603173e62f2a)
- 日期：2025-07-18
- 做了什么：修复缺陷或回归问题，主题是“planner AttributeError 'list' object has no attribute 'get' (#436)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+1 / -1 行。
- 关键文件：src/graph/nodes.py。

#### 13. fix:The console UI directly throws an error when user input is empty (#438)
- 提交：[`c14c548`](https://github.com/bytedance/deer-flow/commit/c14c548e0c28b25d02aa42b731788546d691b093)
- 日期：2025-07-17
- 做了什么：修复缺陷或回归问题，主题是“The console UI directly throws an error when user input is empty (#438)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+5 / -1 行。
- 关键文件：main.py。

#### 14. fix: fix the coordinator's forgetting of its own messages. (#433)
- 提交：[`c89b358`](https://github.com/bytedance/deer-flow/commit/c89b35805d01555b6a150bc09155cfa49f78a511)
- 日期：2025-07-17
- 做了什么：修复缺陷或回归问题，主题是“fix the coordinator's forgetting of its own messages. (#433)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+8 / -1 行。
- 关键文件：src/graph/nodes.py。

#### 15. fix: fix unit test cases for prompt enhancer (#431)
- 提交：[`774473c`](https://github.com/bytedance/deer-flow/commit/774473cc184fde0971b76dd67985674e4752eff8)
- 日期：2025-07-16
- 做了什么：修复缺陷或回归问题，主题是“fix unit test cases for prompt enhancer (#431)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+307 / -1 行。
- 关键文件：tests/unit/prompt_enhancer/graph/test_enhancer_node.py。

#### 16. fix: handle empty agent tuple in streaming workflow (#427)
- 提交：[`b04225b`](https://github.com/bytedance/deer-flow/commit/b04225b7c83e5635f91f17d691b34d6244a90b1e)
- 日期：2025-07-16
- 做了什么：修复缺陷或回归问题，主题是“handle empty agent tuple in streaming workflow (#427)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+5 / -1 行。
- 关键文件：src/server/app.py。

#### 17. fix: clean up the builder code (#417)
- 提交：[`0f118fd`](https://github.com/bytedance/deer-flow/commit/0f118fda924a09ea6059da3a764307329b29eb1c)
- 日期：2025-07-15
- 做了什么：修复缺陷或回归问题，主题是“clean up the builder code (#417)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+22 / -2 行。
- 关键文件：src/graph/builder.py；tests/unit/graph/test_builder.py。

#### 18. fix: missing i18n message (#410)
- 提交：[`8bdc6bf`](https://github.com/bytedance/deer-flow/commit/8bdc6bfa2d4fd00c99808ddadb035c42401a09b5)
- 日期：2025-07-14
- 做了什么：修复缺陷或回归问题，主题是“missing i18n message (#410)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+1 / -1 行。
- 关键文件：web/messages/en.json。

#### 19. fix: add missing translation for chat.page (#409)
- 提交：[`afbcdd6`](https://github.com/bytedance/deer-flow/commit/afbcdd68d8c455d84e6a7fe8be0023f451511818)
- 日期：2025-07-14
- 做了什么：修复缺陷或回归问题，主题是“add missing translation for chat.page (#409)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+5 / -0 行。
- 关键文件：web/messages/en.json。

#### 20. fix: main build fix for the merge #237 (#407)
- 提交：[`bf3bcee`](https://github.com/bytedance/deer-flow/commit/bf3bcee8e3010c83575ec38e215f7c159d95d53a)
- 日期：2025-07-13
- 做了什么：修复缺陷或回归问题，主题是“main build fix for the merge #237 (#407)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+3 / -5 行。
- 关键文件：src/llms/llm.py。

#### 21. fix: update the reasoning model url in conf.yaml.example (#406)
- 提交：[`86a89ac`](https://github.com/bytedance/deer-flow/commit/86a89acac3c39e3860a0448d839cbece383b3bff)
- 日期：2025-07-13
- 做了什么：修复缺陷或回归问题，主题是“update the reasoning model url in conf.yaml.example (#406)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+1 / -1 行。
- 关键文件：conf.yaml.example。

#### 22. fix:catch toolCalls doesn't return validate json (#405)
- 提交：[`2121510`](https://github.com/bytedance/deer-flow/commit/2121510f63365e4a0f6089759cb95dd2e6ba11c8)
- 日期：2025-07-12
- 做了什么：修复缺陷或回归问题，主题是“catch toolCalls doesn't return validate json (#405)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+14 / -6 行。
- 关键文件：web/src/components/deer-flow/link.tsx。

#### 23. fix: repair_json_output cannot process msgs that do not starts with {, [ or ``` (#384)
- 提交：[`0dc6c16`](https://github.com/bytedance/deer-flow/commit/0dc6c16c423c1774f7122ef5472ccbb4c2a13b74)
- 日期：2025-07-12
- 做了什么：修复缺陷或回归问题，主题是“repair_json_output cannot process msgs that do not starts with {, [ or ``` (#384)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+13 / -17 行。
- 关键文件：src/utils/json_utils.py。

#### 24. fix: correctly remove outermost code block markers in model responses (fix markdown rendering issue) (#386)
- 提交：[`5abf8c1`](https://github.com/bytedance/deer-flow/commit/5abf8c1f5ed7b2ebe4c1757606067ae1d73e7712)
- 日期：2025-07-12
- 做了什么：修复缺陷或回归问题，主题是“correctly remove outermost code block markers in model responses (fix markdown rendering issue) (#386)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+44 / -8 行。
- 关键文件：web/src/components/deer-flow/markdown.tsx。

#### 25. fix:upgrade uv version to avoid the big change of uv.lock (#402)
- 提交：[`136f7ea`](https://github.com/bytedance/deer-flow/commit/136f7eaa4ea289d8dcf2145156a49b6682b39a79)
- 日期：2025-07-12
- 做了什么：修复缺陷或回归问题，主题是“upgrade uv version to avoid the big change of uv.lock (#402)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+3 / -0 行。
- 关键文件：pyproject.toml。

#### 26. fix: fix the lint check errors of the main branch (#403)
- 提交：[`3c46201`](https://github.com/bytedance/deer-flow/commit/3c46201ff0f74e3df9403c1a3edb77cced67e7c4)
- 日期：2025-07-12
- 做了什么：修复缺陷或回归问题，主题是“fix the lint check errors of the main branch (#403)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+21 / -128 行。
- 关键文件：src/config/__init__.py；src/crawler/crawler.py；src/llms/llm.py；src/prompt_enhancer/graph/enhancer_node.py；src/rag/vikingdb_knowledge_base.py；src/tools/search.py；tests/integration/test_nodes.py；tests/test_state.py。

#### 27. fix: some lint fix using tools (#98)
- 提交：[`2363b21`](https://github.com/bytedance/deer-flow/commit/2363b21447869d758b361909493eb9d1e24a51a8)
- 日期：2025-07-12
- 做了什么：修复缺陷或回归问题，主题是“some lint fix using tools (#98)”。
- 影响范围：主要涉及 其他模块、文档。
- 改动规模：+206 / -137 行。
- 关键文件：CONTRIBUTING；Makefile；README.md；README_de.md；README_es.md；README_ja.md；README_pt.md；README_ru.md。

#### 28. fix: the typo of setup-uv action (#393)
- 提交：[`d801680`](https://github.com/bytedance/deer-flow/commit/d8016809b279b43f2c22b99ade26b12b3c218ea0)
- 日期：2025-07-07
- 做了什么：修复缺陷或回归问题，主题是“the typo of setup-uv action (#393)”。
- 影响范围：主要涉及 CI/CD。
- 改动规模：+2 / -2 行。
- 关键文件：.github/workflows/lint.yaml；.github/workflows/unittest.yaml。

#### 29. fix: spine the github hash on the third party actions (#392)
- 提交：[`6c254c0`](https://github.com/bytedance/deer-flow/commit/6c254c0783111894652b2e92866a00cb94881a18)
- 日期：2025-07-07
- 做了什么：修复缺陷或回归问题，主题是“spine the github hash on the third party actions (#392)”。
- 影响范围：主要涉及 CI/CD。
- 改动规模：+5 / -5 行。
- 关键文件：.github/workflows/container.yaml；.github/workflows/lint.yaml；.github/workflows/unittest.yaml。

#### 30. fix: docker build (#385)
- 提交：[`d4fbc86`](https://github.com/bytedance/deer-flow/commit/d4fbc86b285205f0d0793461a4e7d5a4fa46e545)
- 日期：2025-07-05
- 做了什么：修复缺陷或回归问题，主题是“docker build (#385)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+1 / -1 行。
- 关键文件：Dockerfile。

## 2025-08

- 提交数：11 条

#### 1. Fix: build of font end of #466 (#530)
- 提交：[`0a02843`](https://github.com/bytedance/deer-flow/commit/0a02843666d8f795ef60b8235163ea4bccb07656)
- 日期：2025-08-21
- 做了什么：修复缺陷或回归问题，主题是“build of font end of #466 (#530)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+17 / -1 行。
- 关键文件：web/src/app/chat/components/message-list-view.tsx。

#### 2. FIX/Adapt message box to handle long text in frontend (#466)
- 提交：[`f17e5bd`](https://github.com/bytedance/deer-flow/commit/f17e5bd6c84acb3781430af6dc61bf1d8d6d6ed0)
- 日期：2025-08-21
- 做了什么：修复缺陷或回归问题，主题是“FIX/Adapt message box to handle long text in frontend (#466)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+53 / -24 行。
- 关键文件：web/src/app/chat/components/message-list-view.tsx；web/src/components/deer-flow/message-input.tsx；web/src/styles/prosemirror.css。

#### 3. fix: update TavilySearchWithImages to inherit from TavilySearchResults (#522)
- 提交：[`db6c1bf`](https://github.com/bytedance/deer-flow/commit/db6c1bf7cb18d65f08109551ae0a026ab02907c4)
- 日期：2025-08-21
- 做了什么：修复缺陷或回归问题，主题是“update TavilySearchWithImages to inherit from TavilySearchResults (#522)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+4 / -2 行。
- 关键文件：src/tools/tavily_search/tavily_search_results_with_images.py。

#### 4. fix: env parameters exception when configuring SSE or HTTP MCP server (#513)
- 提交：[`270d8c3`](https://github.com/bytedance/deer-flow/commit/270d8c3712aa7933fb0b41d88bb7dbf5994a344e)
- 日期：2025-08-20
- 做了什么：修复缺陷或回归问题，主题是“env parameters exception when configuring SSE or HTTP MCP server (#513)”。
- 影响范围：主要涉及 其他模块、文档。
- 改动规模：+54 / -16 行。
- 关键文件：docs/mcp_integrations.md；src/graph/nodes.py；src/server/app.py；src/server/mcp_request.py；src/server/mcp_utils.py；tests/unit/server/test_mcp_utils.py；web/src/core/mcp/types.ts；web/src/core/store/settings-store.ts。

#### 5. fix: GitHub workflow action version warning  (#520)
- 提交：[`b08e9ad`](https://github.com/bytedance/deer-flow/commit/b08e9ad3ac12ad60b2c8488f1796da49224a6828)
- 日期：2025-08-20
- 做了什么：修复缺陷或回归问题，主题是“GitHub workflow action version warning  (#520)”。
- 影响范围：主要涉及 CI/CD。
- 改动规模：+1 / -1 行。
- 关键文件：.github/workflows/unittest.yaml。

#### 6. fix: using commit hash as the action version (#519)
- 提交：[`c6d152a`](https://github.com/bytedance/deer-flow/commit/c6d152a07438eee83e29349108dd7e3ba9c6ba16)
- 日期：2025-08-20
- 做了什么：修复缺陷或回归问题，主题是“using commit hash as the action version (#519)”。
- 影响范围：主要涉及 CI/CD。
- 改动规模：+4 / -4 行。
- 关键文件：.github/workflows/container.yaml；.github/workflows/lint.yaml。

#### 7. fix: polish the makefile to provide help command (#518)
- 提交：[`44d328f`](https://github.com/bytedance/deer-flow/commit/44d328f6966a5081ecb1d66cd2e111ef26fb85bd)
- 日期：2025-08-20
- 做了什么：修复缺陷或回归问题，主题是“polish the makefile to provide help command (#518)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+17 / -9 行。
- 关键文件：.gitignore；Makefile。

#### 8. fix: backend server docker instance only listen to localhost (#508)
- 提交：[`ea17e82`](https://github.com/bytedance/deer-flow/commit/ea17e82514a82e12df31db0a4397ce2a7cbfdaa8)
- 日期：2025-08-11
- 做了什么：修复缺陷或回归问题，主题是“backend server docker instance only listen to localhost (#508)”。
- 影响范围：主要涉及 文档、配置。
- 改动规模：+15 / -9 行。
- 关键文件：README.md；README_de.md；README_es.md；README_ja.md；README_pt.md；README_ru.md；README_zh.md；docker-compose.yml。

#### 9. fix: tool name mismatch issue (#506)
- 提交：[`a4d6171`](https://github.com/bytedance/deer-flow/commit/a4d6171c17e5a87403d3ded409a02fa056f49cfb)
- 日期：2025-08-08
- 做了什么：修复缺陷或回归问题，主题是“tool name mismatch issue (#506)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+2 / -2 行。
- 关键文件：src/prompts/researcher.md。

#### 10. fix: added configuration of python_repl (#503)
- 提交：[`9e691ec`](https://github.com/bytedance/deer-flow/commit/9e691ecf204221fc534d79ae232cf12565298c88)
- 日期：2025-08-06
- 做了什么：修复缺陷或回归问题，主题是“added configuration of python_repl (#503)”。
- 影响范围：主要涉及 文档、其他模块。
- 改动规模：+194 / -77 行。
- 关键文件：.env.example；README.md；README_de.md；README_es.md；README_ja.md；README_pt.md；README_ru.md；README_zh.md。

#### 11. fix: langchain-mcp-adapters version conflict (#500)
- 提交：[`4218cdd`](https://github.com/bytedance/deer-flow/commit/4218cddab5e4995434b44b209625a1224394850d)
- 日期：2025-08-04
- 做了什么：修复缺陷或回归问题，主题是“langchain-mcp-adapters version conflict (#500)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+13 / -12 行。
- 关键文件：src/graph/nodes.py；tests/integration/test_nodes.py。

## 2025-09

- 提交数：10 条

#### 1. fix: support local models by making thought field optional in Plan model (#601)
- 提交：[`24f6905`](https://github.com/bytedance/deer-flow/commit/24f6905c18d3d154d88bcd34d32a3726ea518110)
- 日期：2025-09-27
- 做了什么：修复缺陷或回归问题，主题是“support local models by making thought field optional in Plan model (#601)”。
- 影响范围：主要涉及 其他模块、文档。
- 改动规模：+43 / -2 行。
- 关键文件：README.md；conf.yaml.example；docs/configuration_guide.md；src/prompts/planner.md；src/prompts/planner_model.py。

#### 2. fix: don't expose internal application error to client (#585)
- 提交：[`ea0fe62`](https://github.com/bytedance/deer-flow/commit/ea0fe62971d5ce317514669e28ee3a3a3e3b2351)
- 日期：2025-09-16
- 做了什么：修复缺陷或回归问题，主题是“don't expose internal application error to client (#585)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+1 / -1 行。
- 关键文件：src/server/app.py。

#### 3. fix: log the exception of graph execution (#577)
- 提交：[`79ab736`](https://github.com/bytedance/deer-flow/commit/79ab7365c06cf1c14279155092334109a56b1d20)
- 日期：2025-09-14
- 做了什么：修复缺陷或回归问题，主题是“log the exception of graph execution (#577)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+29 / -18 行。
- 关键文件：src/server/app.py。

#### 4. fix: frontend supports chinese for listing datasets in RAG (#582)
- 提交：[`26a587c`](https://github.com/bytedance/deer-flow/commit/26a587c24e1f33f84eada25d878273609645026f)
- 日期：2025-09-14
- 做了什么：修复缺陷或回归问题，主题是“frontend supports chinese for listing datasets in RAG (#582)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+34 / -13 行。
- 关键文件：web/src/components/deer-flow/message-input.tsx；web/src/components/deer-flow/resource-suggestion.tsx。

#### 5. fix: Remove duplicate assignment operations for the tool_call_chunks field (#575)
- 提交：[`6d1d7f2`](https://github.com/bytedance/deer-flow/commit/6d1d7f2d9e21d950dc1144e31557aa5fef9a0656)
- 日期：2025-09-12
- 做了什么：修复缺陷或回归问题，主题是“Remove duplicate assignment operations for the tool_call_chunks field (#575)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+0 / -1 行。
- 关键文件：src/server/app.py。

#### 6. fix: the stdio and sse mcp server loading issue (#566)
- 提交：[`317acdf`](https://github.com/bytedance/deer-flow/commit/317acdffadbaf99ccb644bdad38e44aa4e09c31f)
- 日期：2025-09-09
- 做了什么：修复缺陷或回归问题，主题是“the stdio and sse mcp server loading issue (#566)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+6 / -1 行。
- 关键文件：src/server/mcp_utils.py。

#### 7. fix: correct typo in MongoDB connection string within .env.example (#560)
- 提交：[`38ff2f7`](https://github.com/bytedance/deer-flow/commit/38ff2f7276d0330b76bbb4bec023fcb0761d8c15)
- 日期：2025-09-08
- 做了什么：修复缺陷或回归问题，主题是“correct typo in MongoDB connection string within .env.example (#560)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+2 / -2 行。
- 关键文件：.env.example。

#### 8. fix: the search content return tuple issue (#555)
- 提交：[`a41ced1`](https://github.com/bytedance/deer-flow/commit/a41ced13459d67122604ccdb170779f50fc841a8)
- 日期：2025-09-04
- 做了什么：修复缺陷或回归问题，主题是“the search content return tuple issue (#555)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+3 / -0 行。
- 关键文件：src/graph/nodes.py。

#### 9. Fixed the deepseek v3 planning issue #545 (#554)
- 提交：[`8f127df`](https://github.com/bytedance/deer-flow/commit/8f127df9489272d7069bf6f247cb3242fb1b3160)
- 日期：2025-09-04
- 做了什么：修复缺陷或回归问题，主题是“Fixed the deepseek v3 planning issue #545 (#554)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+1 / -1 行。
- 关键文件：src/graph/nodes.py。

#### 10. fix deer-flow/src/prompts/prose/prose_zap.md (#553)
- 提交：[`5f1981a`](https://github.com/bytedance/deer-flow/commit/5f1981ac9b361936844997503087756d12e19fe1)
- 日期：2025-09-03
- 做了什么：修复缺陷或回归问题，主题是“fix deer-flow/src/prompts/prose/prose_zap.md (#553)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+1 / -1 行。
- 关键文件：src/prompts/prose/prose_zap.md。

## 2025-10

- 提交数：34 条

#### 1. fix: prevent DOM error when removing temporary download link (#675) (#676)
- 提交：[`fea585a`](https://github.com/bytedance/deer-flow/commit/fea585ae3dbb4e4e6bcc43cab6e6018edfeb6272)
- 日期：2025-10-31
- 做了什么：修复缺陷或回归问题，主题是“prevent DOM error when removing temporary download link (#675) (#676)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+7 / -2 行。
- 关键文件：web/src/app/chat/components/research-block.tsx。

#### 2. fix: remove the unnessary conditional edge. (#671)
- 提交：[`6ae4bc5`](https://github.com/bytedance/deer-flow/commit/6ae4bc588a0022d067c61da21f16d50980519d4a)
- 日期：2025-10-29
- 做了什么：修复缺陷或回归问题，主题是“remove the unnessary conditional edge. (#671)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+2 / -8 行。
- 关键文件：src/graph/builder.py；tests/unit/graph/test_builder.py。

#### 3. fix: presever the local setting between frontend and backend (#670)
- 提交：[`0415f62`](https://github.com/bytedance/deer-flow/commit/0415f622da4ab010c140d6a9630b5df5d5fa8b7e)
- 日期：2025-10-28
- 做了什么：修复缺陷或回归问题，主题是“presever the local setting between frontend and backend (#670)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+994 / -21 行。
- 关键文件：src/graph/nodes.py；src/server/app.py；tests/integration/test_nodes.py；tests/unit/graph/test_agent_locale_restoration.py；tests/unit/graph/test_human_feedback_locale_fix.py；tests/unit/graph/test_state_preservation.py。

#### 4. fix: pass the locale through the frontend chat (#668)
- 提交：[`eb4c3b8`](https://github.com/bytedance/deer-flow/commit/eb4c3b8ef60378b6db667fc7a201d36fceb5ded6)
- 日期：2025-10-28
- 做了什么：修复缺陷或回归问题，主题是“pass the locale through the frontend chat (#668)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+27 / -0 行。
- 关键文件：web/src/core/api/chat.ts。

#### 5. fix: make SSE buffer size configurable to prevent overflow during multi-round searches (#664) (#665)
- 提交：[`ccd7535`](https://github.com/bytedance/deer-flow/commit/ccd75350720ad8c5163d2df3364b90bdd422da8c)
- 日期：2025-10-27
- 做了什么：修复缺陷或回归问题，主题是“make SSE buffer size configurable to prevent overflow during multi-round searches (#664) (#665)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+25 / -2 行。
- 关键文件：web/.env.example；web/src/core/sse/fetch-stream.ts；web/src/env.js。

#### 6. fix: handle escaped curly braces in LaTeX formulas (#608) (#660)
- 提交：[`6ded818`](https://github.com/bytedance/deer-flow/commit/6ded818f62fb198516688cef383ec9dd586debe1)
- 日期：2025-10-26
- 做了什么：修复缺陷或回归问题，主题是“handle escaped curly braces in LaTeX formulas (#608) (#660)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+32 / -0 行。
- 关键文件：web/src/core/utils/markdown.ts；web/tests/markdown-math-editor.test.ts。

#### 7. fix: improve config loading resilience for non-localhost access (#510) (#658)
- 提交：[`0441038`](https://github.com/bytedance/deer-flow/commit/04410386722276244e0be729439e5915433efe90)
- 日期：2025-10-26
- 做了什么：修复缺陷或回归问题，主题是“improve config loading resilience for non-localhost access (#510) (#658)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+80 / -16 行。
- 关键文件：web/.env.example；web/src/app/chat/components/input-box.tsx；web/src/core/api/hooks.ts。

#### 8. fix: parsed json with extra tokens issue (#656)
- 提交：[`c7a82b8`](https://github.com/bytedance/deer-flow/commit/c7a82b82b4e28e0bd0af237088a64cf69812a536)
- 日期：2025-10-26
- 做了什么：修复缺陷或回归问题，主题是“parsed json with extra tokens issue (#656)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+779 / -7 行。
- 关键文件：src/graph/nodes.py；src/utils/context_manager.py；src/utils/json_utils.py；tests/unit/utils/test_json_utils.py；web/src/app/chat/components/research-activities-block.tsx；web/src/core/utils/json.ts；web/tests/json.test.ts。

#### 9. fix: handle [ACCEPTED] feedback gracefully without TypeError in plan review  (#657)
- 提交：[`fd5a9ae`](https://github.com/bytedance/deer-flow/commit/fd5a9aeae46c627764912b826af283f15dfbc255)
- 日期：2025-10-25
- 做了什么：修复缺陷或回归问题，主题是“handle [ACCEPTED] feedback gracefully without TypeError in plan review  (#657)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+41 / -6 行。
- 关键文件：src/graph/nodes.py；tests/integration/test_nodes.py。

#### 10. fix: react key warnings from duplicate message IDs + establish jest testing framework (#655)
- 提交：[`1d71f89`](https://github.com/bytedance/deer-flow/commit/1d71f8910e35a3c19d66fcca8fe53e1ce071ad49)
- 日期：2025-10-25
- 做了什么：修复缺陷或回归问题，主题是“react key warnings from duplicate message IDs + establish jest testing framework (#655)”。
- 影响范围：主要涉及 其他模块、CI/CD、配置。
- 改动规模：+4127 / -151 行。
- 关键文件：.github/workflows/lint.yaml；Makefile；web/jest.config.mjs；web/jest.setup.js；web/package.json；web/pnpm-lock.yaml；web/src/app/chat/components/message-list-view.tsx；web/src/core/store/store.ts。

#### 11. fix: prevent tool name concatenation in consecutive tool calls to fix #523 (#654)
- 提交：[`f2be4d6`](https://github.com/bytedance/deer-flow/commit/f2be4d6af16ba63196fbfd238151c7dfee71cee3)
- 日期：2025-10-24
- 做了什么：修复缺陷或回归问题，主题是“prevent tool name concatenation in consecutive tool calls to fix #523 (#654)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+470 / -10 行。
- 关键文件：src/server/app.py；tests/unit/server/test_tool_call_chunks.py。

#### 12. fix: repair missing step_type fields in Plan validation (#653)
- 提交：[`36bf5c9`](https://github.com/bytedance/deer-flow/commit/36bf5c9ccda0d4a742700044b212133424a57129)
- 日期：2025-10-24
- 做了什么：修复缺陷或回归问题，主题是“repair missing step_type fields in Plan validation (#653)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+794 / -6 行。
- 关键文件：src/graph/nodes.py；src/prompts/planner.md；src/prompts/planner.zh_CN.md；tests/integration/test_nodes.py；tests/unit/graph/test_plan_validation.py。

#### 13. fix: resolve issue #651 - crawl error with None content handling (#652)
- 提交：[`975b344`](https://github.com/bytedance/deer-flow/commit/975b344ca7f894765c6644d6b60bda47cab1e4ec)
- 日期：2025-10-24
- 做了什么：修复缺陷或回归问题，主题是“resolve issue #651 - crawl error with None content handling (#652)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+329 / -10 行。
- 关键文件：src/crawler/article.py；src/crawler/crawler.py；src/crawler/jina_client.py；src/crawler/readability_extractor.py；tests/unit/crawler/test_article.py；tests/unit/crawler/test_jina_client.py；tests/unit/crawler/test_readability_extractor.py；tests/unit/tools/test_crawl.py。

#### 14. Fix: clarification bugs - max rounds, locale passing, and over-clarification (#647)
- 提交：[`2001a7c`](https://github.com/bytedance/deer-flow/commit/2001a7c223886eef6177a6c5177ecef7846289dc)
- 日期：2025-10-24
- 做了什么：修复缺陷或回归问题，主题是“clarification bugs - max rounds, locale passing, and over-clarification (#647)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+119 / -40 行。
- 关键文件：src/graph/nodes.py；src/graph/types.py；src/prompts/coordinator.md；src/tools/search.py；tests/integration/test_nodes.py；tests/unit/tools/test_search.py。

#### 15. fix: resolve issue #467 - message content validation and Tavily search error handling (#645)
- 提交：[`052490b`](https://github.com/bytedance/deer-flow/commit/052490b116b5e916509378b12de5ade07fa62655)
- 日期：2025-10-23
- 做了什么：修复缺陷或回归问题，主题是“resolve issue #467 - message content validation and Tavily search error handling (#645)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+114 / -14 行。
- 关键文件：src/graph/nodes.py；src/tools/tavily_search/tavily_search_results_with_images.py；src/utils/context_manager.py；tests/integration/test_nodes.py；tests/unit/tools/test_tavily_search_results_with_images.py。

#### 16. fix: Optimize the performance of stream data processing and add anti-… (#642)
- 提交：[`829cb39`](https://github.com/bytedance/deer-flow/commit/829cb39b251078725555d5116ef6f763f38dac6e)
- 日期：2025-10-22
- 做了什么：修复缺陷或回归问题，主题是“Optimize the performance of stream data processing and add anti-… (#642)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+81 / -17 行。
- 关键文件：web/src/components/editor/generative/ai-selector.tsx；web/src/core/sse/fetch-stream.ts；web/src/core/store/store.ts。

#### 17. fix: support additional Tavily search parameters via configuration to fix #548 (#643)
- 提交：[`9ece3fd`](https://github.com/bytedance/deer-flow/commit/9ece3fd9c31ce3f983c9cf465b0b1e26c1c49579)
- 日期：2025-10-22
- 做了什么：修复缺陷或回归问题，主题是“support additional Tavily search parameters via configuration to fix #548 (#643)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+245 / -5 行。
- 关键文件：conf.yaml.example；src/tools/search.py；tests/unit/tools/test_search.py。

#### 18. fix: Refine clarification workflow state handling (#641)
- 提交：[`003f081`](https://github.com/bytedance/deer-flow/commit/003f081a7b2d2c35a9de0ba3f1672017989ef60a)
- 日期：2025-10-22
- 做了什么：修复缺陷或回归问题，主题是“Refine clarification workflow state handling (#641)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+615 / -117 行。
- 关键文件：src/config/configuration.py；src/graph/nodes.py；src/graph/types.py；src/graph/utils.py；src/server/app.py；src/tools/search_postprocessor.py；src/workflow.py；tests/integration/test_nodes.py。

#### 19. fix: ensure web search is performed for research plans to fix #535 (#640)
- 提交：[`add0a70`](https://github.com/bytedance/deer-flow/commit/add0a701f46050bcc0133d26a4a26ec7e12189b0)
- 日期：2025-10-22
- 做了什么：修复缺陷或回归问题，主题是“ensure web search is performed for research plans to fix #535 (#640)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+95 / -8 行。
- 关键文件：src/config/configuration.py；src/graph/nodes.py；src/prompts/coordinator.md；src/prompts/planner.md；tests/integration/test_nodes.py。

#### 20. fix: unescape markdown-escaped characters in math formulas to fix #608 (#637)
- 提交：[`1a16677`](https://github.com/bytedance/deer-flow/commit/1a16677d1a9540752a25bdeaf2d25ce135c088a2)
- 日期：2025-10-21
- 做了什么：修复缺陷或回归问题，主题是“unescape markdown-escaped characters in math formulas to fix #608 (#637)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+127 / -3 行。
- 关键文件：web/src/components/editor/index.tsx；web/src/core/utils/markdown.ts；web/tests/markdown-math-editor.test.ts。

#### 21. fix: convert crawl_tool dict return to JSON string for type consistency (#636)
- 提交：[`d30c4d0`](https://github.com/bytedance/deer-flow/commit/d30c4d00d3bef0e85fd2e92d1deb0ac4c696d6c5)
- 日期：2025-10-21
- 做了什么：修复缺陷或回归问题，主题是“convert crawl_tool dict return to JSON string for type consistency (#636)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+10 / -6 行。
- 关键文件：src/tools/crawl.py；tests/unit/tools/test_crawl.py。

#### 22. fix: correct image result format for OpenAI compatibility to fix #632 (#634)
- 提交：[`e2ff765`](https://github.com/bytedance/deer-flow/commit/e2ff765460164c8bfd659c2512fc02d5935b3c8c)
- 日期：2025-10-20
- 做了什么：修复缺陷或回归问题，主题是“correct image result format for OpenAI compatibility to fix #632 (#634)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+12 / -5 行。
- 关键文件：src/tools/search_postprocessor.py；src/tools/tavily_search/tavily_search_api_wrapper.py；tests/unit/tools/test_tavily_search_api_wrapper.py。

#### 23. fix: handle non-string tool results to fix #631 (#633)
- 提交：[`3689bc0`](https://github.com/bytedance/deer-flow/commit/3689bc0e69dc6fd6404863ec208f362d2acbb689)
- 日期：2025-10-20
- 做了什么：修复缺陷或回归问题，主题是“handle non-string tool results to fix #631 (#633)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+6 / -2 行。
- 关键文件：src/server/app.py；web/src/app/chat/components/research-activities-block.tsx。

#### 24. fix: optimize animations to prevent browser freeze with many research steps (#630)
- 提交：[`984aa69`](https://github.com/bytedance/deer-flow/commit/984aa69acfb81b8cf51a700d31e02208d2f473b6)
- 日期：2025-10-19
- 做了什么：修复缺陷或回归问题，主题是“optimize animations to prevent browser freeze with many research steps (#630)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+92 / -65 行。
- 关键文件：web/src/app/chat/components/research-activities-block.tsx。

#### 25. fix: add missing RunnableConfig parameter to human_feedback_node (#629)
- 提交：[`5af036f`](https://github.com/bytedance/deer-flow/commit/5af036f19fe3712546e5ca94f449dd01bf23d357)
- 日期：2025-10-19
- 做了什么：修复缺陷或回归问题，主题是“add missing RunnableConfig parameter to human_feedback_node (#629)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+15 / -15 行。
- 关键文件：src/graph/nodes.py；tests/integration/test_nodes.py。

#### 26. fix: improve error handling in researcher and coder nodes (#596)
- 提交：[`57c9c2d`](https://github.com/bytedance/deer-flow/commit/57c9c2dcd52c82a78d7a212de897698019f110df)
- 日期：2025-10-19
- 做了什么：修复缺陷或回归问题，主题是“improve error handling in researcher and coder nodes (#596)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+26 / -3 行。
- 关键文件：src/graph/nodes.py。

#### 27. fix:the formual display error after report editing (#627)
- 提交：[`497a2a3`](https://github.com/bytedance/deer-flow/commit/497a2a39cf02a6be9a2b60c7a332f9a7542882b1)
- 日期：2025-10-17
- 做了什么：修复缺陷或回归问题，主题是“the formual display error after report editing (#627)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+46 / -0 行。
- 关键文件：web/src/core/utils/markdown.ts；web/tests/markdown-math-editor.test.ts。

#### 28. fix: prevent repeated content animation during thinking streaming (#614) (#623)
- 提交：[`c6348e7`](https://github.com/bytedance/deer-flow/commit/c6348e70c6745f9d6f94d88059474c2494773fcf)
- 日期：2025-10-16
- 做了什么：修复缺陷或回归问题，主题是“prevent repeated content animation during thinking streaming (#614) (#623)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+46 / -13 行。
- 关键文件：web/src/app/chat/components/message-list-view.tsx。

#### 29. fix: add unique key prop to conversation starter list items (#619)
- 提交：[`025ea6b`](https://github.com/bytedance/deer-flow/commit/025ea6b94e742c4f5ae98bd9b5ee5d7cd3130c5e)
- 日期：2025-10-16
- 做了什么：修复缺陷或回归问题，主题是“add unique key prop to conversation starter list items (#619)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+1 / -1 行。
- 关键文件：web/src/app/chat/components/conversation-starter.tsx。

#### 30. fix: configure Windows event loop policy for PostgreSQL async compatibility (#618)
- 提交：[`120fcfb`](https://github.com/bytedance/deer-flow/commit/120fcfb316bdba35e0382e1e9170c89ba7ae0928)
- 日期：2025-10-16
- 做了什么：修复缺陷或回归问题，主题是“configure Windows event loop policy for PostgreSQL async compatibility (#618)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+7 / -0 行。
- 关键文件：src/server/app.py。

#### 31. fix: exclude test files from TypeScript type checking
- 提交：[`779de40`](https://github.com/bytedance/deer-flow/commit/779de40f106e9e2042ee47b1b7e9d481d35759d5)
- 日期：2025-10-15
- 做了什么：修复缺陷或回归问题，主题是“exclude test files from TypeScript type checking”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+1 / -1 行。
- 关键文件：web/tsconfig.json。

#### 32. fix: resolve math formula display abnormal after editing report
- 提交：[`58c1743`](https://github.com/bytedance/deer-flow/commit/58c1743ed59dfd87a9542ec2ab84caed601f18dd)
- 日期：2025-10-15
- 做了什么：修复缺陷或回归问题，主题是“resolve math formula display abnormal after editing report”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+208 / -19 行。
- 关键文件：web/src/components/deer-flow/markdown.tsx；web/src/components/editor/extensions.tsx；web/src/components/editor/index.tsx；web/src/components/editor/math-serializer.ts；web/src/core/utils/markdown.ts；web/tests/markdown-katex.test.ts；web/tests/markdown-math-editor.test.ts。

#### 33. fix: add max_clarification_rounds parameter passing from frontend to backend (#616)
- 提交：[`24e2d86`](https://github.com/bytedance/deer-flow/commit/24e2d86f7b1eaf05af0ba6aeb88d6a458fc2786b)
- 日期：2025-10-14
- 做了什么：修复缺陷或回归问题，主题是“add max_clarification_rounds parameter passing from frontend to backend (#616)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+2 / -0 行。
- 关键文件：web/src/core/api/chat.ts；web/src/core/store/store.ts。

#### 34. chore: fix incorrect filename in conf.yaml.example comments (#609)
- 提交：[`f80af8e`](https://github.com/bytedance/deer-flow/commit/f80af8e1320c58d944ebdd50b8054baae48ed00b)
- 日期：2025-10-11
- 做了什么：修复缺陷或回归问题，主题是“fix incorrect filename in conf.yaml.example comments (#609)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+1 / -1 行。
- 关键文件：conf.yaml.example。

## 2025-11

- 提交数：10 条

#### 1. fix(web): handle incomplete JSON in MCP tool call arguments (#528) (#727)
- 提交：[`e179fb1`](https://github.com/bytedance/deer-flow/commit/e179fb163274d0cace4ce14044f091d4bbf643eb)
- 日期：2025-11-29
- 做了什么：修复缺陷或回归问题，主题是“handle incomplete JSON in MCP tool call arguments (#528) (#727)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+364 / -1 行。
- 关键文件：web/src/core/messages/merge-message.ts；web/tests/merge-message.test.ts。

#### 2. fix(llm): filter unexpected config keys to prevent LangChain warnings (#411) (#726)
- 提交：[`4a78cfe`](https://github.com/bytedance/deer-flow/commit/4a78cfe12a6efa37524317e43cfb36a0f709cea3)
- 日期：2025-11-29
- 做了什么：修复缺陷或回归问题，主题是“filter unexpected config keys to prevent LangChain warnings (#411) (#726)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+101 / -0 行。
- 关键文件：src/llms/llm.py；tests/unit/llms/test_llm.py。

#### 3. fix: apply context compression to prevent token overflow (Issue #721) (#722)
- 提交：[`b24f4d3`](https://github.com/bytedance/deer-flow/commit/b24f4d3f38d45403b7525537de3ba7112c0a8835)
- 日期：2025-11-28
- 做了什么：修复缺陷或回归问题，主题是“apply context compression to prevent token overflow (Issue #721) (#722)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+110 / -8 行。
- 关键文件：conf.yaml.example；src/graph/nodes.py；src/llms/llm.py；src/utils/context_manager.py。

#### 4. fix: the frontend error when cancle the research plan (#719)
- 提交：[`223ec57`](https://github.com/bytedance/deer-flow/commit/223ec57fe4d9039836b6259458cd207d9994a262)
- 日期：2025-11-28
- 做了什么：修复缺陷或回归问题，主题是“the frontend error when cancle the research plan (#719)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+5 / -0 行。
- 关键文件：src/server/app.py。

#### 5. fix: revert the part of patch of issue-710 to extract the content from the plan (#718)
- 提交：[`4559197`](https://github.com/bytedance/deer-flow/commit/4559197505cede4c5fee5f8c41129052b44b5589)
- 日期：2025-11-27
- 做了什么：修复缺陷或回归问题，主题是“revert the part of patch of issue-710 to extract the content from the plan (#718)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+10 / -176 行。
- 关键文件：src/graph/nodes.py；tests/unit/graph/test_plan_validation.py。

#### 6. fix: multiple web_search ToolMessages only showing last result (#717)
- 提交：[`ca4ada5`](https://github.com/bytedance/deer-flow/commit/ca4ada5aa774fdecbe674791a4b8dd6a6d0fc30b)
- 日期：2025-11-27
- 做了什么：修复缺陷或回归问题，主题是“multiple web_search ToolMessages only showing last result (#717)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+275 / -6 行。
- 关键文件：src/graph/nodes.py；tests/integration/test_nodes.py。

#### 7. fix: the exception of plan validation (#714)
- 提交：[`6679169`](https://github.com/bytedance/deer-flow/commit/667916959b0a8a611d20b03175836c1a3f4154bd)
- 日期：2025-11-27
- 做了什么：修复缺陷或回归问题，主题是“the exception of plan validation (#714)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+228 / -12 行。
- 关键文件：src/graph/nodes.py；tests/integration/test_nodes.py；tests/unit/graph/test_plan_validation.py。

#### 8. fix: the crawling error when encountering PDF URLs (#707)
- 提交：[`bec97f0`](https://github.com/bytedance/deer-flow/commit/bec97f02ae596fc84e02e02d913fc5872a181eab)
- 日期：2025-11-25
- 做了什么：修复缺陷或回归问题，主题是“the crawling error when encountering PDF URLs (#707)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+484 / -3 行。
- 关键文件：src/crawler/crawler.py；src/tools/crawl.py；tests/unit/crawler/test_crawler_class.py；tests/unit/tools/test_crawl.py。

#### 9. fix: the validation Error with qwen-max-latest Model (#706)
- 提交：[`da51433`](https://github.com/bytedance/deer-flow/commit/da514337da8e57398870f223c81cab6964e7497a)
- 日期：2025-11-24
- 做了什么：修复缺陷或回归问题，主题是“the validation Error with qwen-max-latest Model (#706)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+187 / -4 行。
- 关键文件：src/graph/nodes.py；tests/integration/test_nodes.py。

#### 10. fix: ensure researcher agent uses web search tool instead of generating URLs (#702) (#704)
- 提交：[`478291d`](https://github.com/bytedance/deer-flow/commit/478291df0781b7fe60a05abade18808bc27e4f7d)
- 日期：2025-11-24
- 做了什么：修复缺陷或回归问题，主题是“ensure researcher agent uses web search tool instead of generating URLs (#702) (#704)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+84 / -11 行。
- 关键文件：src/config/configuration.py；src/graph/nodes.py；src/prompts/researcher.md；src/prompts/researcher.zh_CN.md；src/rag/qdrant.py；tests/integration/test_nodes.py。

## 2025-12

- 提交数：14 条

#### 1. fix(main): Passing the local parameter from the main interactive mode (#791)
- 提交：[`a71b6bc`](https://github.com/bytedance/deer-flow/commit/a71b6bc41fd80667381a9a790ecdcc99197c29cf)
- 日期：2025-12-30
- 做了什么：修复缺陷或回归问题，主题是“Passing the local parameter from the main interactive mode (#791)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+13 / -0 行。
- 关键文件：main.py；src/workflow.py。

#### 2. fix(workflow): resolve locale hardcoding in src/workflow.py for interactive mode (#789)
- 提交：[`893ff82`](https://github.com/bytedance/deer-flow/commit/893ff82a7f818aa6a35a4e43b153d2c90f556c0e)
- 日期：2025-12-30
- 做了什么：修复缺陷或回归问题，主题是“resolve locale hardcoding in src/workflow.py for interactive mode (#789)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+6 / -8 行。
- 关键文件：src/workflow.py。

#### 3. fix(deps): update langchain-core to 1.2.5 to resolve CVE-2025-68664 (#787)
- 提交：[`5087d50`](https://github.com/bytedance/deer-flow/commit/5087d5012f60aee82b8c722a26afbe04092973e0)
- 日期：2025-12-27
- 做了什么：修复缺陷或回归问题，主题是“update langchain-core to 1.2.5 to resolve CVE-2025-68664 (#787)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+28 / -5 行。
- 关键文件：pyproject.toml；uv.lock。

#### 4. fix(podcast): add fallback for models without json_object support (#747) (#785)
- 提交：[`bab60e6`](https://github.com/bytedance/deer-flow/commit/bab60e6e3d166a166b5b4f3bf33c1995d025697e)
- 日期：2025-12-26
- 做了什么：修复缺陷或回归问题，主题是“add fallback for models without json_object support (#747) (#785)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+254 / -10 行。
- 关键文件：src/podcast/graph/script_writer_node.py；tests/unit/podcast/__init__.py；tests/unit/podcast/test_script_writer_node.py。

#### 5. fix(metrics): update the polynomial regular expression used on uncontrolled data (#784)
- 提交：[`5a79f89`](https://github.com/bytedance/deer-flow/commit/5a79f896c4aeb5ff981619188dc59038dee760aa)
- 日期：2025-12-26
- 做了什么：修复缺陷或回归问题，主题是“update the polynomial regular expression used on uncontrolled data (#784)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+2 / -2 行。
- 关键文件：src/eval/metrics.py。

#### 6. fix(web): enable runtime API URL detection for cross-machine access (#777) (#783)
- 提交：[`cd5c487`](https://github.com/bytedance/deer-flow/commit/cd5c4877f34d001742db17f4a87bd815dbee4e16)
- 日期：2025-12-25
- 做了什么：修复缺陷或回归问题，主题是“enable runtime API URL detection for cross-machine access (#777) (#783)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+18 / -1 行。
- 关键文件：web/src/core/api/resolve-service-url.ts。

#### 7. Fix typo in vulnerability reporting instructions (#772)
- 提交：[`1f403a9`](https://github.com/bytedance/deer-flow/commit/1f403a9f797c0b37d382bd56e3a7050800739388)
- 日期：2025-12-21
- 做了什么：修复缺陷或回归问题，主题是“Fix typo in vulnerability reporting instructions (#772)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+1 / -1 行。
- 关键文件：SECURITY.md。

#### 8. fix: display direct_response message in frontend (#763) (#764)
- 提交：[`b85130b`](https://github.com/bytedance/deer-flow/commit/b85130b8490b0057f9407f95f204e7a6090f7a4b)
- 日期：2025-12-17
- 做了什么：修复缺陷或回归问题，主题是“display direct_response message in frontend (#763) (#764)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+5 / -0 行。
- 关键文件：web/src/core/messages/merge-message.ts。

#### 9. fix: handle greetings without triggering research workflow (#755)
- 提交：[`c686ab7`](https://github.com/bytedance/deer-flow/commit/c686ab70162a87de28f673357751d121a9b5f00e)
- 日期：2025-12-13
- 做了什么：修复缺陷或回归问题，主题是“handle greetings without triggering research workflow (#755)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+64 / -36 行。
- 关键文件：src/graph/nodes.py；src/prompts/coordinator.md；src/prompts/coordinator.zh_CN.md；tests/integration/test_nodes.py。

#### 10. fix(agents): patch _run in ToolInterceptor to ensure interrupt triggering (#753)
- 提交：[`ec99338`](https://github.com/bytedance/deer-flow/commit/ec99338c9a164c168b735a89a197fc189350783e)
- 日期：2025-12-10
- 做了什么：修复缺陷或回归问题，主题是“patch _run in ToolInterceptor to ensure interrupt triggering (#753)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+76 / -0 行。
- 关键文件：src/agents/tool_interceptor.py；tests/unit/agents/test_tool_interceptor_fix.py。

#### 11. fix(checkpoint): clear in-memory store after successful persistence (#751)
- 提交：[`84c449c`](https://github.com/bytedance/deer-flow/commit/84c449cf7945b27d82f41a80013691b682c29dc3)
- 日期：2025-12-09
- 做了什么：修复缺陷或回归问题，主题是“clear in-memory store after successful persistence (#751)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+60 / -2 行。
- 关键文件：src/graph/checkpoint.py；tests/unit/checkpoint/test_memory_leak.py。

#### 12. fix: setup WindowsSelectorEventLoopPolicy in the first place #741 (#742)
- 提交：[`3bf4e1d`](https://github.com/bytedance/deer-flow/commit/3bf4e1defb88373c5020b7ac10991ae69f77b5c4)
- 日期：2025-12-06
- 做了什么：修复缺陷或回归问题，主题是“setup WindowsSelectorEventLoopPolicy in the first place #741 (#742)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+9 / -0 行。
- 关键文件：src/__init__.py。

#### 13. fix: passing the locale to create_react_agent (#745)
- 提交：[`3191e81`](https://github.com/bytedance/deer-flow/commit/3191e819397a56a4827692535fd6ac8cd7a7ffba)
- 日期：2025-12-06
- 做了什么：修复缺陷或回归问题，主题是“passing the locale to create_react_agent (#745)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+14 / -3 行。
- 关键文件：src/agents/agents.py；src/graph/nodes.py。

#### 14. fix: update Interrupt object attribute access for LangGraph 1.0+ (#730) (#731)
- 提交：[`c36ab39`](https://github.com/bytedance/deer-flow/commit/c36ab393f1d1a878dcce0ef16fbeecd31f8ccaad)
- 日期：2025-12-02
- 做了什么：修复缺陷或回归问题，主题是“update Interrupt object attribute access for LangGraph 1.0+ (#730) (#731)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+105 / -6 行。
- 关键文件：src/server/app.py；tests/unit/server/test_app.py。

## 2026-01

- 提交数：117 条

#### 1. fix: add translations
- 提交：[`f5b1412`](https://github.com/bytedance/deer-flow/commit/f5b1412ac043d2b2aad1df6bc85c58cc9a696b2c)
- 日期：2026-01-31
- 做了什么：修复缺陷或回归问题，主题是“add translations”。
- 影响范围：主要涉及 前端。
- 改动规模：+4 / -1 行。
- 关键文件：frontend/src/components/workspace/settings/skill-settings-page.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts；frontend/src/core/i18n/locales/zh-CN.ts。

#### 2. fix: add translations
- 提交：[`8a2fb35`](https://github.com/bytedance/deer-flow/commit/8a2fb353c61e0b7bd14bd76e8092f1e596b8ad13)
- 日期：2026-01-31
- 做了什么：修复缺陷或回归问题，主题是“add translations”。
- 影响范围：主要涉及 前端。
- 改动规模：+4 / -1 行。
- 关键文件：frontend/src/components/workspace/settings/skill-settings-page.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts；frontend/src/core/i18n/locales/zh-CN.ts。

#### 3. fix: add translations
- 提交：[`45fab66`](https://github.com/bytedance/deer-flow/commit/45fab66a7d4abfa5a078b14ab938176e089ad788)
- 日期：2026-01-31
- 做了什么：修复缺陷或回归问题，主题是“add translations”。
- 影响范围：主要涉及 前端。
- 改动规模：+4 / -1 行。
- 关键文件：frontend/src/components/workspace/settings/skill-settings-page.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts；frontend/src/core/i18n/locales/zh-CN.ts。

#### 4. fix: fix eslint errors and warnings
- 提交：[`d3ff5f9`](https://github.com/bytedance/deer-flow/commit/d3ff5f9d3c3f8b6bfc0636c05d76ce93f80b24d3)
- 日期：2026-01-31
- 做了什么：修复缺陷或回归问题，主题是“fix eslint errors and warnings”。
- 影响范围：主要涉及 前端。
- 改动规模：+20 / -80 行。
- 关键文件：frontend/eslint.config.js；frontend/package.json；frontend/src/components/workspace/code-editor.tsx；frontend/src/components/workspace/messages/message-list-item.tsx；frontend/src/core/uploads/api.ts。

#### 5. fix: fix eslint errors and warnings
- 提交：[`718bb94`](https://github.com/bytedance/deer-flow/commit/718bb947d05a27a38bfd9e27a0716823ec05cfd4)
- 日期：2026-01-31
- 做了什么：修复缺陷或回归问题，主题是“fix eslint errors and warnings”。
- 影响范围：主要涉及 前端。
- 改动规模：+20 / -80 行。
- 关键文件：frontend/eslint.config.js；frontend/package.json；frontend/src/components/workspace/code-editor.tsx；frontend/src/components/workspace/messages/message-list-item.tsx；frontend/src/core/uploads/api.ts。

#### 6. fix: fix eslint errors and warnings
- 提交：[`8ecb6b3`](https://github.com/bytedance/deer-flow/commit/8ecb6b3d1ddcdc9bd145ff9f3dd8c5ec9af95202)
- 日期：2026-01-31
- 做了什么：修复缺陷或回归问题，主题是“fix eslint errors and warnings”。
- 影响范围：主要涉及 前端。
- 改动规模：+20 / -80 行。
- 关键文件：frontend/eslint.config.js；frontend/package.json；frontend/src/components/workspace/code-editor.tsx；frontend/src/components/workspace/messages/message-list-item.tsx；frontend/src/core/uploads/api.ts。

#### 7. fix: fix eslint errors
- 提交：[`e858ef0`](https://github.com/bytedance/deer-flow/commit/e858ef0250263dd54c0fb18298e7bfe5c6bed408)
- 日期：2026-01-31
- 做了什么：修复缺陷或回归问题，主题是“fix eslint errors”。
- 影响范围：主要涉及 前端。
- 改动规模：+3 / -2 行。
- 关键文件：frontend/src/core/messages/utils.ts。

#### 8. fix: fix eslint errors
- 提交：[`b8281be`](https://github.com/bytedance/deer-flow/commit/b8281be892da6309e4adf0a6999c3e1e45fd1232)
- 日期：2026-01-31
- 做了什么：修复缺陷或回归问题，主题是“fix eslint errors”。
- 影响范围：主要涉及 前端。
- 改动规模：+3 / -2 行。
- 关键文件：frontend/src/core/messages/utils.ts。

#### 9. fix: fix eslint errors
- 提交：[`2ba687b`](https://github.com/bytedance/deer-flow/commit/2ba687b239e183045e6a5ff915c777e440a10670)
- 日期：2026-01-31
- 做了什么：修复缺陷或回归问题，主题是“fix eslint errors”。
- 影响范围：主要涉及 前端。
- 改动规模：+3 / -2 行。
- 关键文件：frontend/src/core/messages/utils.ts。

#### 10. fix: fix aio sandbox shutdown bug
- 提交：[`43ee8a2`](https://github.com/bytedance/deer-flow/commit/43ee8a29683da20ed7a5a07fbc0f774fd7551042)
- 日期：2026-01-30
- 做了什么：修复缺陷或回归问题，主题是“fix aio sandbox shutdown bug”。
- 影响范围：主要涉及 技能体系、后端、其他模块。
- 改动规模：+1271 / -4 行。
- 关键文件：Makefile；backend/src/community/aio_sandbox/aio_sandbox_provider.py；backend/src/config/extensions_config.py；backend/src/config/sandbox_config.py；skills/public/skill-creator/LICENSE.txt；skills/public/skill-creator/SKILL.md；skills/public/skill-creator/references/output-patterns.md；skills/public/skill-creator/references/workflows.md。

#### 11. fix: fix aio sandbox shutdown bug
- 提交：[`733c020`](https://github.com/bytedance/deer-flow/commit/733c020c58528ff175a7e9cbb16cace23d8d43f1)
- 日期：2026-01-30
- 做了什么：修复缺陷或回归问题，主题是“fix aio sandbox shutdown bug”。
- 影响范围：主要涉及 技能体系、后端、其他模块。
- 改动规模：+1271 / -4 行。
- 关键文件：Makefile；backend/src/community/aio_sandbox/aio_sandbox_provider.py；backend/src/config/extensions_config.py；backend/src/config/sandbox_config.py；skills/public/skill-creator/LICENSE.txt；skills/public/skill-creator/SKILL.md；skills/public/skill-creator/references/output-patterns.md；skills/public/skill-creator/references/workflows.md。

#### 12. fix: fix aio sandbox shutdown bug
- 提交：[`8182ed3`](https://github.com/bytedance/deer-flow/commit/8182ed3737baa302b0ed8b35c2b289e241b88c4d)
- 日期：2026-01-30
- 做了什么：修复缺陷或回归问题，主题是“fix aio sandbox shutdown bug”。
- 影响范围：主要涉及 技能体系、后端、其他模块。
- 改动规模：+1271 / -4 行。
- 关键文件：Makefile；backend/src/community/aio_sandbox/aio_sandbox_provider.py；backend/src/config/extensions_config.py；backend/src/config/sandbox_config.py；skills/public/skill-creator/LICENSE.txt；skills/public/skill-creator/SKILL.md；skills/public/skill-creator/references/output-patterns.md；skills/public/skill-creator/references/workflows.md。

#### 13. fix: fix condition of displaying artifacts
- 提交：[`c07c022`](https://github.com/bytedance/deer-flow/commit/c07c0228f67613bd3046b009cfc76e7c572df54e)
- 日期：2026-01-30
- 做了什么：修复缺陷或回归问题，主题是“fix condition of displaying artifacts”。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -1 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx。

#### 14. fix: fix condition of displaying artifacts
- 提交：[`697f094`](https://github.com/bytedance/deer-flow/commit/697f094ba946326bc406335e3c61d78e9a291d6c)
- 日期：2026-01-30
- 做了什么：修复缺陷或回归问题，主题是“fix condition of displaying artifacts”。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -1 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx。

#### 15. fix: fix condition of displaying artifacts
- 提交：[`21e12d9`](https://github.com/bytedance/deer-flow/commit/21e12d91eb076bf2210e5c7822b68da57f85fbeb)
- 日期：2026-01-30
- 做了什么：修复缺陷或回归问题，主题是“fix condition of displaying artifacts”。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -1 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx。

#### 16. fix: improve JSON repair handling for markdown code blocks (#841)
- 提交：[`3adb4e9`](https://github.com/bytedance/deer-flow/commit/3adb4e90cbf14e8dd0b34ab72fcd02e3b550635f)
- 日期：2026-01-30
- 做了什么：修复缺陷或回归问题，主题是“improve JSON repair handling for markdown code blocks (#841)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+394 / -6 行。
- 关键文件：src/graph/nodes.py；src/tools/crawl.py；src/utils/json_utils.py；tests/unit/utils/test_json_utils.py。

#### 17. fix: add max width
- 提交：[`a4f749f`](https://github.com/bytedance/deer-flow/commit/a4f749f939b091ff5f8bfa8509ff8213a2b6f536)
- 日期：2026-01-29
- 做了什么：修复缺陷或回归问题，主题是“add max width”。
- 影响范围：主要涉及 前端。
- 改动规模：+3 / -1 行。
- 关键文件：frontend/src/components/ai-elements/prompt-input.tsx。

#### 18. fix: add max width
- 提交：[`c265f54`](https://github.com/bytedance/deer-flow/commit/c265f5410d623577db2b1f5846400c32bc6f181a)
- 日期：2026-01-29
- 做了什么：修复缺陷或回归问题，主题是“add max width”。
- 影响范围：主要涉及 前端。
- 改动规模：+3 / -1 行。
- 关键文件：frontend/src/components/ai-elements/prompt-input.tsx。

#### 19. fix: add max width
- 提交：[`66deedf`](https://github.com/bytedance/deer-flow/commit/66deedf3b25a2d38b46b2dc515e0433dc07ad4d3)
- 日期：2026-01-29
- 做了什么：修复缺陷或回归问题，主题是“add max width”。
- 影响范围：主要涉及 前端。
- 改动规模：+3 / -1 行。
- 关键文件：frontend/src/components/ai-elements/prompt-input.tsx。

#### 20. fix: fix renaming
- 提交：[`4411af6`](https://github.com/bytedance/deer-flow/commit/4411af68f5fd2da56c7e3844b4244da5bddfccd1)
- 日期：2026-01-29
- 做了什么：修复缺陷或回归问题，主题是“fix renaming”。
- 影响范围：主要涉及 前端。
- 改动规模：+10 / -10 行。
- 关键文件：frontend/src/core/threads/hooks.ts。

#### 21. fix: fix renaming
- 提交：[`caf469d`](https://github.com/bytedance/deer-flow/commit/caf469d2ab98164d4ebb425626142248ffa588d0)
- 日期：2026-01-29
- 做了什么：修复缺陷或回归问题，主题是“fix renaming”。
- 影响范围：主要涉及 前端。
- 改动规模：+10 / -10 行。
- 关键文件：frontend/src/core/threads/hooks.ts。

#### 22. fix: fix renaming
- 提交：[`0ba82a9`](https://github.com/bytedance/deer-flow/commit/0ba82a9fd793d0b30555fc5ac8d6ec2f1f7a98e1)
- 日期：2026-01-29
- 做了什么：修复缺陷或回归问题，主题是“fix renaming”。
- 影响范围：主要涉及 前端。
- 改动规模：+10 / -10 行。
- 关键文件：frontend/src/core/threads/hooks.ts。

#### 23. fix: fix frontend bug
- 提交：[`75801d9`](https://github.com/bytedance/deer-flow/commit/75801d9817ac19238855d5af766fad451ee86f15)
- 日期：2026-01-29
- 做了什么：修复缺陷或回归问题，主题是“fix frontend bug”。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -1 行。
- 关键文件：frontend/src/app/layout.tsx；frontend/src/styles/globals.css。

#### 24. fix: fix frontend bug
- 提交：[`2c6dbbe`](https://github.com/bytedance/deer-flow/commit/2c6dbbe065765d11eb6d6ac95b880b9984647e2f)
- 日期：2026-01-29
- 做了什么：修复缺陷或回归问题，主题是“fix frontend bug”。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -1 行。
- 关键文件：frontend/src/app/layout.tsx；frontend/src/styles/globals.css。

#### 25. fix: fix frontend bug
- 提交：[`3cbf54b`](https://github.com/bytedance/deer-flow/commit/3cbf54b2ebe752af51e6bb8890af3c73f267f81b)
- 日期：2026-01-29
- 做了什么：修复缺陷或回归问题，主题是“fix frontend bug”。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -1 行。
- 关键文件：frontend/src/app/layout.tsx；frontend/src/styles/globals.css。

#### 26. fix: hide incomplete citations block during streaming
- 提交：[`e2e0fbf`](https://github.com/bytedance/deer-flow/commit/e2e0fbf11442b9b5377e455fcddb499de77cce75)
- 日期：2026-01-29
- 做了什么：修复缺陷或回归问题，主题是“hide incomplete citations block during streaming”。
- 影响范围：主要涉及 前端。
- 改动规模：+7 / -1 行。
- 关键文件：frontend/src/core/citations/utils.ts。

#### 27. fix: hide incomplete citations block during streaming
- 提交：[`6ae4868`](https://github.com/bytedance/deer-flow/commit/6ae486878041e42b8ce5219a1d63db4f57cce349)
- 日期：2026-01-29
- 做了什么：修复缺陷或回归问题，主题是“hide incomplete citations block during streaming”。
- 影响范围：主要涉及 前端。
- 改动规模：+7 / -1 行。
- 关键文件：frontend/src/core/citations/utils.ts。

#### 28. fix: hide incomplete citations block during streaming
- 提交：[`2ec506d`](https://github.com/bytedance/deer-flow/commit/2ec506d5902a81772e5331d8a2e66c09401092d1)
- 日期：2026-01-29
- 做了什么：修复缺陷或回归问题，主题是“hide incomplete citations block during streaming”。
- 影响范围：主要涉及 前端。
- 改动规模：+7 / -1 行。
- 关键文件：frontend/src/core/citations/utils.ts。

#### 29. fix: improve hasPresentFiles function to check for multiple tool calls
- 提交：[`7decdbc`](https://github.com/bytedance/deer-flow/commit/7decdbcc835b0d8d6b09167331298e40b9cbbda4)
- 日期：2026-01-29
- 做了什么：修复缺陷或回归问题，主题是“improve hasPresentFiles function to check for multiple tool calls”。
- 影响范围：主要涉及 前端。
- 改动规模：+2 / -1 行。
- 关键文件：frontend/src/core/messages/utils.ts。

#### 30. fix: improve hasPresentFiles function to check for multiple tool calls
- 提交：[`946031b`](https://github.com/bytedance/deer-flow/commit/946031b79fdb2c3973a4e593e3211c2afe541049)
- 日期：2026-01-29
- 做了什么：修复缺陷或回归问题，主题是“improve hasPresentFiles function to check for multiple tool calls”。
- 影响范围：主要涉及 前端。
- 改动规模：+2 / -1 行。
- 关键文件：frontend/src/core/messages/utils.ts。

#### 31. fix(mcp-tool): using the async invocation for MCP tools (#840)
- 提交：[`756421c`](https://github.com/bytedance/deer-flow/commit/756421c3ac30fd9b8e7ce1bad3f63d5181de3e1e)
- 日期：2026-01-28
- 做了什么：修复缺陷或回归问题，主题是“using the async invocation for MCP tools (#840)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+18 / -17 行。
- 关键文件：src/graph/nodes.py；tests/integration/test_nodes.py。

#### 32. fix: preserve reasoning_content in multi-turn conversations
- 提交：[`fa9fba3`](https://github.com/bytedance/deer-flow/commit/fa9fba3f8e4d0fe9003bf6e4a275de5b335bb0d3)
- 日期：2026-01-28
- 做了什么：修复缺陷或回归问题，主题是“preserve reasoning_content in multi-turn conversations”。
- 影响范围：主要涉及 后端、配置。
- 改动规模：+93 / -7 行。
- 关键文件：backend/debug.py；backend/src/agents/middlewares/uploads_middleware.py；backend/src/models/patched_deepseek.py；config.example.yaml。

#### 33. fix: preserve reasoning_content in multi-turn conversations
- 提交：[`9d0a0ea`](https://github.com/bytedance/deer-flow/commit/9d0a0ea0221f84dc46b2bd879f6a595603a41b74)
- 日期：2026-01-28
- 做了什么：修复缺陷或回归问题，主题是“preserve reasoning_content in multi-turn conversations”。
- 影响范围：主要涉及 后端、配置。
- 改动规模：+93 / -7 行。
- 关键文件：backend/debug.py；backend/src/agents/middlewares/uploads_middleware.py；backend/src/models/patched_deepseek.py；config.example.yaml。

#### 34. fix: hide chats when sidebar is not open
- 提交：[`ed31dc6`](https://github.com/bytedance/deer-flow/commit/ed31dc6aab6fabf9325209a7b4436b5f9d667974)
- 日期：2026-01-27
- 做了什么：修复缺陷或回归问题，主题是“hide chats when sidebar is not open”。
- 影响范围：主要涉及 前端。
- 改动规模：+3 / -1 行。
- 关键文件：frontend/src/components/workspace/workspace-sidebar.tsx。

#### 35. fix: hide chats when sidebar is not open
- 提交：[`ec31e61`](https://github.com/bytedance/deer-flow/commit/ec31e61f95de94fbf90cbde88ac721b9602b3031)
- 日期：2026-01-27
- 做了什么：修复缺陷或回归问题，主题是“hide chats when sidebar is not open”。
- 影响范围：主要涉及 前端。
- 改动规模：+3 / -1 行。
- 关键文件：frontend/src/components/workspace/workspace-sidebar.tsx。

#### 36. fix: eslint
- 提交：[`cc1fe4e`](https://github.com/bytedance/deer-flow/commit/cc1fe4e50ecf8d83a217a879bf105e985a9efb3c)
- 日期：2026-01-27
- 做了什么：修复缺陷或回归问题，主题是“eslint”。
- 影响范围：主要涉及 前端。
- 改动规模：+0 / -2 行。
- 关键文件：frontend/src/components/workspace/workspace-header.tsx。

#### 37. fix: eslint
- 提交：[`7928a6f`](https://github.com/bytedance/deer-flow/commit/7928a6f2e10030e5200238263592f0804d8b47bd)
- 日期：2026-01-27
- 做了什么：修复缺陷或回归问题，主题是“eslint”。
- 影响范围：主要涉及 前端。
- 改动规模：+0 / -2 行。
- 关键文件：frontend/src/components/workspace/workspace-header.tsx。

#### 38. fix: bugfix
- 提交：[`eca2b13`](https://github.com/bytedance/deer-flow/commit/eca2b139cc0bb7a227dfbbeb68c920a3ffd3e4c9)
- 日期：2026-01-27
- 做了什么：修复缺陷或回归问题，主题是“bugfix”。
- 影响范围：主要涉及 前端。
- 改动规模：+2 / -2 行。
- 关键文件：frontend/src/components/workspace/messages/message-group.tsx。

#### 39. fix: bugfix
- 提交：[`0bcbaeb`](https://github.com/bytedance/deer-flow/commit/0bcbaebb7e857513233098321cfdf3f808e8e62d)
- 日期：2026-01-27
- 做了什么：修复缺陷或回归问题，主题是“bugfix”。
- 影响范围：主要涉及 前端。
- 改动规模：+2 / -2 行。
- 关键文件：frontend/src/components/workspace/messages/message-group.tsx。

#### 40. fix: ensure MCP and skills config changes are immediately reflected
- 提交：[`1390632`](https://github.com/bytedance/deer-flow/commit/139063283f53fa0a7fc7f9689b5b5479c4c60128)
- 日期：2026-01-25
- 做了什么：修复缺陷或回归问题，主题是“ensure MCP and skills config changes are immediately reflected”。
- 影响范围：主要涉及 后端。
- 改动规模：+89 / -29 行。
- 关键文件：backend/src/gateway/app.py；backend/src/gateway/routers/mcp.py；backend/src/gateway/routers/skills.py；backend/src/mcp/cache.py；backend/src/mcp/tools.py；backend/src/skills/loader.py；backend/src/tools/tools.py。

#### 41. fix: ensure MCP and skills config changes are immediately reflected
- 提交：[`038f5d4`](https://github.com/bytedance/deer-flow/commit/038f5d44f4c111f678508aaf4184f46bef775b2a)
- 日期：2026-01-25
- 做了什么：修复缺陷或回归问题，主题是“ensure MCP and skills config changes are immediately reflected”。
- 影响范围：主要涉及 后端。
- 改动规模：+89 / -29 行。
- 关键文件：backend/src/gateway/app.py；backend/src/gateway/routers/mcp.py；backend/src/gateway/routers/skills.py；backend/src/mcp/cache.py；backend/src/mcp/tools.py；backend/src/skills/loader.py；backend/src/tools/tools.py。

#### 42. fix: many minor fixes
- 提交：[`598fed7`](https://github.com/bytedance/deer-flow/commit/598fed797f24801769e581188696b66296717c4f)
- 日期：2026-01-25
- 做了什么：修复缺陷或回归问题，主题是“many minor fixes”。
- 影响范围：主要涉及 前端。
- 改动规模：+83 / -38 行。
- 关键文件：frontend/src/app/mock/api/threads/[thread_id]/artifacts/[[...artifact_path]]/route.ts；frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/landing/sections/case-study-section.tsx；frontend/src/components/ui/spotlight-card.tsx。

#### 43. fix: many minor fixes
- 提交：[`756b396`](https://github.com/bytedance/deer-flow/commit/756b396a642e5a006abf5186bbd9495197d2195d)
- 日期：2026-01-25
- 做了什么：修复缺陷或回归问题，主题是“many minor fixes”。
- 影响范围：主要涉及 前端。
- 改动规模：+83 / -38 行。
- 关键文件：frontend/src/app/mock/api/threads/[thread_id]/artifacts/[[...artifact_path]]/route.ts；frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/landing/sections/case-study-section.tsx；frontend/src/components/ui/spotlight-card.tsx。

#### 44. fix: fix artifacts in demo mode
- 提交：[`c82f705`](https://github.com/bytedance/deer-flow/commit/c82f7055414aa52c0c8d574cab20dfb8bd5d64f5)
- 日期：2026-01-25
- 做了什么：修复缺陷或回归问题，主题是“fix artifacts in demo mode”。
- 影响范围：主要涉及 前端。
- 改动规模：+15 / -8 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/core/threads/hooks.ts。

#### 45. fix: fix artifacts in demo mode
- 提交：[`fecc5fa`](https://github.com/bytedance/deer-flow/commit/fecc5faacf560237d59f9f3e0a84899b65a72a15)
- 日期：2026-01-25
- 做了什么：修复缺陷或回归问题，主题是“fix artifacts in demo mode”。
- 影响范围：主要涉及 前端。
- 改动规模：+15 / -8 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/core/threads/hooks.ts。

#### 46. fix: remove tooltip
- 提交：[`3ac6e58`](https://github.com/bytedance/deer-flow/commit/3ac6e58d4f5b4980661a22a94ad16160ebf934a6)
- 日期：2026-01-25
- 做了什么：修复缺陷或回归问题，主题是“remove tooltip”。
- 影响范围：主要涉及 前端。
- 改动规模：+6 / -12 行。
- 关键文件：frontend/src/components/workspace/artifacts/artifact-file-detail.tsx。

#### 47. fix: remove tooltip
- 提交：[`9501ec5`](https://github.com/bytedance/deer-flow/commit/9501ec5eed5359c208a11528104efe8ffb6035ef)
- 日期：2026-01-25
- 做了什么：修复缺陷或回归问题，主题是“remove tooltip”。
- 影响范围：主要涉及 前端。
- 改动规模：+6 / -12 行。
- 关键文件：frontend/src/components/workspace/artifacts/artifact-file-detail.tsx。

#### 48. fix: fix auto select first artifact
- 提交：[`03b380c`](https://github.com/bytedance/deer-flow/commit/03b380cb8b559d92fd96c659af3b4b92d309f0ce)
- 日期：2026-01-24
- 做了什么：修复缺陷或回归问题，主题是“fix auto select first artifact”。
- 影响范围：主要涉及 前端。
- 改动规模：+12 / -2 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx。

#### 49. fix: fix auto select first artifact
- 提交：[`1e2855b`](https://github.com/bytedance/deer-flow/commit/1e2855b5330e637e4ba73deac475268a4f92fa8a)
- 日期：2026-01-24
- 做了什么：修复缺陷或回归问题，主题是“fix auto select first artifact”。
- 影响范围：主要涉及 前端。
- 改动规模：+12 / -2 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx。

#### 50. Merge pull request #17 from amszuidas/fix/tavily-api-key-config
- 提交：[`b1e7028`](https://github.com/bytedance/deer-flow/commit/b1e7028ea023afa2c00d72d96e9dc895a566022e)
- 日期：2026-01-24
- 做了什么：修复缺陷或回归问题，主题是“Merge pull request #17 from amszuidas/fix/tavily-api-key-config”。
- 影响范围：主要涉及 后端。
- 改动规模：+12 / -3 行。
- 关键文件：backend/src/community/tavily/tools.py。

#### 51. Merge pull request #17 from amszuidas/fix/tavily-api-key-config
- 提交：[`9498e78`](https://github.com/bytedance/deer-flow/commit/9498e783f147c49bc16bade0861153ed8b9b2545)
- 日期：2026-01-24
- 做了什么：修复缺陷或回归问题，主题是“Merge pull request #17 from amszuidas/fix/tavily-api-key-config”。
- 影响范围：主要涉及 后端。
- 改动规模：+12 / -3 行。
- 关键文件：backend/src/community/tavily/tools.py。

#### 52. fix: support loading tavily ak from config.yaml
- 提交：[`d6176e8`](https://github.com/bytedance/deer-flow/commit/d6176e86d6d304159afba06e6f06d83b4b031d98)
- 日期：2026-01-23
- 做了什么：修复缺陷或回归问题，主题是“support loading tavily ak from config.yaml”。
- 影响范围：主要涉及 后端。
- 改动规模：+12 / -3 行。
- 关键文件：backend/src/community/tavily/tools.py。

#### 53. fix: support loading tavily ak from config.yaml
- 提交：[`c1c8942`](https://github.com/bytedance/deer-flow/commit/c1c894249143615054152fc82ddc1e9929953a52)
- 日期：2026-01-23
- 做了什么：修复缺陷或回归问题，主题是“support loading tavily ak from config.yaml”。
- 影响范围：主要涉及 后端。
- 改动规模：+12 / -3 行。
- 关键文件：backend/src/community/tavily/tools.py。

#### 54. fix: use return value of resolve_env_variables in config loading
- 提交：[`3972485`](https://github.com/bytedance/deer-flow/commit/3972485fe03cbbcdfc6b86049299712ac2e5fe06)
- 日期：2026-01-23
- 做了什么：修复缺陷或回归问题，主题是“use return value of resolve_env_variables in config loading”。
- 影响范围：主要涉及 后端。
- 改动规模：+1 / -1 行。
- 关键文件：backend/src/config/app_config.py。

#### 55. fix: use return value of resolve_env_variables in config loading
- 提交：[`761cb6a`](https://github.com/bytedance/deer-flow/commit/761cb6a7f52daee702091e3d71650247b73a8e77)
- 日期：2026-01-23
- 做了什么：修复缺陷或回归问题，主题是“use return value of resolve_env_variables in config loading”。
- 影响范围：主要涉及 后端。
- 改动规模：+1 / -1 行。
- 关键文件：backend/src/config/app_config.py。

#### 56. fix: correct spelling
- 提交：[`eb80236`](https://github.com/bytedance/deer-flow/commit/eb802361e1af2430ba825bb4deb4b2f05dfa3918)
- 日期：2026-01-23
- 做了什么：修复缺陷或回归问题，主题是“correct spelling”。
- 影响范围：主要涉及 后端。
- 改动规模：+1 / -1 行。
- 关键文件：backend/src/sandbox/sandbox.py。

#### 57. fix: correct spelling
- 提交：[`2ef320f`](https://github.com/bytedance/deer-flow/commit/2ef320f107de98dbf37f4a370695bd93dce894a0)
- 日期：2026-01-23
- 做了什么：修复缺陷或回归问题，主题是“correct spelling”。
- 影响范围：主要涉及 后端。
- 改动规模：+1 / -1 行。
- 关键文件：backend/src/sandbox/sandbox.py。

#### 58. fix: robust environment variable resolution in config
- 提交：[`82a6ae8`](https://github.com/bytedance/deer-flow/commit/82a6ae81bdf3259ebae90b8e00e22189f7f21a18)
- 日期：2026-01-23
- 做了什么：修复缺陷或回归问题，主题是“robust environment variable resolution in config”。
- 影响范围：主要涉及 后端。
- 改动规模：+10 / -14 行。
- 关键文件：backend/src/config/app_config.py。

#### 59. fix: robust environment variable resolution in config
- 提交：[`303e025`](https://github.com/bytedance/deer-flow/commit/303e0252ce1319b7c314e0f3897002003957eb38)
- 日期：2026-01-23
- 做了什么：修复缺陷或回归问题，主题是“robust environment variable resolution in config”。
- 影响范围：主要涉及 后端。
- 改动规模：+10 / -14 行。
- 关键文件：backend/src/config/app_config.py。

#### 60. fix: fix menu item in side bar collapsed mode
- 提交：[`459d9d0`](https://github.com/bytedance/deer-flow/commit/459d9d0287177280b266558d0d103902456afa73)
- 日期：2026-01-22
- 做了什么：修复缺陷或回归问题，主题是“fix menu item in side bar collapsed mode”。
- 影响范围：主要涉及 前端。
- 改动规模：+11 / -5 行。
- 关键文件：frontend/src/components/workspace/workspace-nav-menu.tsx。

#### 61. fix: fix menu item in side bar collapsed mode
- 提交：[`6e1f63e`](https://github.com/bytedance/deer-flow/commit/6e1f63e47f173ed4572dc5fe85911dbef9ae168a)
- 日期：2026-01-22
- 做了什么：修复缺陷或回归问题，主题是“fix menu item in side bar collapsed mode”。
- 影响范围：主要涉及 前端。
- 改动规模：+11 / -5 行。
- 关键文件：frontend/src/components/workspace/workspace-nav-menu.tsx。

#### 62. fix: fix nginx conf
- 提交：[`c00f780`](https://github.com/bytedance/deer-flow/commit/c00f780501a80bce25848528b3d5b714c4cb9c60)
- 日期：2026-01-22
- 做了什么：修复缺陷或回归问题，主题是“fix nginx conf”。
- 影响范围：主要涉及 后端。
- 改动规模：+6 / -3 行。
- 关键文件：backend/Makefile。

#### 63. fix: fix nginx conf
- 提交：[`50c25f5`](https://github.com/bytedance/deer-flow/commit/50c25f5c4d1bfaf6a48efdc71a6fdcb033b7e767)
- 日期：2026-01-22
- 做了什么：修复缺陷或回归问题，主题是“fix nginx conf”。
- 影响范围：主要涉及 后端。
- 改动规模：+6 / -3 行。
- 关键文件：backend/Makefile。

#### 64. fix: update summarization configuration values
- 提交：[`11918b5`](https://github.com/bytedance/deer-flow/commit/11918b52708dd639de224847ad368a81af1ad303)
- 日期：2026-01-22
- 做了什么：修复缺陷或回归问题，主题是“update summarization configuration values”。
- 影响范围：主要涉及 配置。
- 改动规模：+5 / -5 行。
- 关键文件：config.example.yaml。

#### 65. fix: update summarization configuration values
- 提交：[`bd33f72`](https://github.com/bytedance/deer-flow/commit/bd33f72017288764cf9fb8afcf5b8cc86fbe58d2)
- 日期：2026-01-22
- 做了什么：修复缺陷或回归问题，主题是“update summarization configuration values”。
- 影响范围：主要涉及 配置。
- 改动规模：+5 / -5 行。
- 关键文件：config.example.yaml。

#### 66. Fixes(unit-test):  the unit tests error of recent change of #816 (#826)
- 提交：[`546e2e6`](https://github.com/bytedance/deer-flow/commit/546e2e6234237eace252c7f17b9b92f1a98a2337)
- 日期：2026-01-22
- 做了什么：修复缺陷或回归问题，主题是“Fixes(unit-test):  the unit tests error of recent change of #816 (#826)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+16 / -7 行。
- 关键文件：tests/unit/checkpoint/test_checkpoint.py。

#### 67. fix: handle false values correctly in (#823)
- 提交：[`6ec170c`](https://github.com/bytedance/deer-flow/commit/6ec170cde5eaebef9108d0c8e2a8718e0e294aba)
- 日期：2026-01-21
- 做了什么：修复缺陷或回归问题，主题是“handle false values correctly in (#823)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+52 / -7 行。
- 关键文件：src/config/configuration.py；tests/unit/config/test_configuration.py。

#### 68. fix: fix sandbox cp issue
- 提交：[`adbb03f`](https://github.com/bytedance/deer-flow/commit/adbb03fc26933de6d8a8483796351efdd17a5b83)
- 日期：2026-01-20
- 做了什么：修复缺陷或回归问题，主题是“fix sandbox cp issue”。
- 影响范围：主要涉及 后端。
- 改动规模：+42 / -0 行。
- 关键文件：backend/src/sandbox/tools.py。

#### 69. fix: fix sandbox cp issue
- 提交：[`c5a2771`](https://github.com/bytedance/deer-flow/commit/c5a2771636cd2170d200ea214ca178751c582b0a)
- 日期：2026-01-20
- 做了什么：修复缺陷或回归问题，主题是“fix sandbox cp issue”。
- 影响范围：主要涉及 后端。
- 改动规模：+42 / -0 行。
- 关键文件：backend/src/sandbox/tools.py。

#### 70. fix: fix skill md path
- 提交：[`5888a5b`](https://github.com/bytedance/deer-flow/commit/5888a5ba16276e3ccbaf318cad9d520c5585208a)
- 日期：2026-01-20
- 做了什么：修复缺陷或回归问题，主题是“fix skill md path”。
- 影响范围：主要涉及 后端、技能体系。
- 改动规模：+53 / -2 行。
- 关键文件：backend/src/agents/lead_agent/prompt.py；backend/src/skills/types.py；skills/public/web-design-guidelines/SKILL.md。

#### 71. fix: fix skill md path
- 提交：[`e58e5f1`](https://github.com/bytedance/deer-flow/commit/e58e5f19043f4fbb9244299c5a981b07f723b163)
- 日期：2026-01-20
- 做了什么：修复缺陷或回归问题，主题是“fix skill md path”。
- 影响范围：主要涉及 后端、技能体系。
- 改动规模：+53 / -2 行。
- 关键文件：backend/src/agents/lead_agent/prompt.py；backend/src/skills/types.py；skills/public/web-design-guidelines/SKILL.md。

#### 72. fix: fix config
- 提交：[`6ec023d`](https://github.com/bytedance/deer-flow/commit/6ec023de8baec9d9e07126cbcd1b760fbb76a435)
- 日期：2026-01-20
- 做了什么：修复缺陷或回归问题，主题是“fix config”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+2 / -5 行。
- 关键文件：extensions_config.example.json。

#### 73. fix: fix config
- 提交：[`33e6197`](https://github.com/bytedance/deer-flow/commit/33e6197f65d46490e435a3f8a8a5c6c98571df98)
- 日期：2026-01-20
- 做了什么：修复缺陷或回归问题，主题是“fix config”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+2 / -5 行。
- 关键文件：extensions_config.example.json。

#### 74. fix: fix backend
- 提交：[`d11763d`](https://github.com/bytedance/deer-flow/commit/d11763dcc881a24df273e17614a23ddd2b46fa82)
- 日期：2026-01-20
- 做了什么：修复缺陷或回归问题，主题是“fix backend”。
- 影响范围：主要涉及 后端。
- 改动规模：+2 / -2 行。
- 关键文件：backend/src/gateway/routers/__init__.py。

#### 75. fix: fix backend
- 提交：[`5c1bb67`](https://github.com/bytedance/deer-flow/commit/5c1bb675ba60ef318f9b3b767c9f4fcb23baeb01)
- 日期：2026-01-20
- 做了什么：修复缺陷或回归问题，主题是“fix backend”。
- 影响范围：主要涉及 后端。
- 改动规模：+2 / -2 行。
- 关键文件：backend/src/gateway/routers/__init__.py。

#### 76. fix: fix proxy
- 提交：[`d6c1e58`](https://github.com/bytedance/deer-flow/commit/d6c1e5868d53397089b5e1746a62f80c21919ac6)
- 日期：2026-01-19
- 做了什么：修复缺陷或回归问题，主题是“fix proxy”。
- 影响范围：主要涉及 后端。
- 改动规模：+22 / -21 行。
- 关键文件：backend/src/gateway/routers/proxy.py。

#### 77. fix: fix proxy
- 提交：[`a6fcdbf`](https://github.com/bytedance/deer-flow/commit/a6fcdbf50a9a944fde1c886f9108a4822c2d7cd2)
- 日期：2026-01-19
- 做了什么：修复缺陷或回归问题，主题是“fix proxy”。
- 影响范围：主要涉及 后端。
- 改动规模：+22 / -21 行。
- 关键文件：backend/src/gateway/routers/proxy.py。

#### 78. fix: use shared httpx client to prevent premature closure in SSE streaming
- 提交：[`1a7c853`](https://github.com/bytedance/deer-flow/commit/1a7c853811443921b46c1419edd32159b3d70b42)
- 日期：2026-01-19
- 做了什么：修复缺陷或回归问题，主题是“use shared httpx client to prevent premature closure in SSE streaming”。
- 影响范围：主要涉及 后端。
- 改动规模：+77 / -49 行。
- 关键文件：backend/src/gateway/app.py；backend/src/gateway/routers/proxy.py。

#### 79. fix: use shared httpx client to prevent premature closure in SSE streaming
- 提交：[`ffb9ed3`](https://github.com/bytedance/deer-flow/commit/ffb9ed31986476d4e267fc7e02f87c2e80bfe062)
- 日期：2026-01-19
- 做了什么：修复缺陷或回归问题，主题是“use shared httpx client to prevent premature closure in SSE streaming”。
- 影响范围：主要涉及 后端。
- 改动规模：+77 / -49 行。
- 关键文件：backend/src/gateway/app.py；backend/src/gateway/routers/proxy.py。

#### 80. fix: stop tracking .claude/settings.local.json
- 提交：[`8ea530e`](https://github.com/bytedance/deer-flow/commit/8ea530e22188fa53a1676afc0ddf340ac1325d27)
- 日期：2026-01-19
- 做了什么：修复缺陷或回归问题，主题是“stop tracking .claude/settings.local.json”。
- 影响范围：主要涉及 后端。
- 改动规模：+3 / -7 行。
- 关键文件：backend/.claude/settings.local.json；backend/.gitignore。

#### 81. fix: stop tracking .claude/settings.local.json
- 提交：[`3a4149c`](https://github.com/bytedance/deer-flow/commit/3a4149c4374e1db39bfd1f1f6ac30254e0160530)
- 日期：2026-01-19
- 做了什么：修复缺陷或回归问题，主题是“stop tracking .claude/settings.local.json”。
- 影响范围：主要涉及 后端。
- 改动规模：+3 / -7 行。
- 关键文件：backend/.claude/settings.local.json；backend/.gitignore。

#### 82. fix: fix getBackendBaseURL()
- 提交：[`1ef04c9`](https://github.com/bytedance/deer-flow/commit/1ef04c94eeb86b1b81d81181faf93f75a35a130a)
- 日期：2026-01-19
- 做了什么：修复缺陷或回归问题，主题是“fix getBackendBaseURL()”。
- 影响范围：主要涉及 前端。
- 改动规模：+6 / -5 行。
- 关键文件：frontend/src/core/config/index.ts；frontend/src/env.js。

#### 83. fix: fix getBackendBaseURL()
- 提交：[`1352b0e`](https://github.com/bytedance/deer-flow/commit/1352b0e0ba8ca3ac2dbe9e6bb1334bc7555e9877)
- 日期：2026-01-19
- 做了什么：修复缺陷或回归问题，主题是“fix getBackendBaseURL()”。
- 影响范围：主要涉及 前端。
- 改动规模：+6 / -5 行。
- 关键文件：frontend/src/core/config/index.ts；frontend/src/env.js。

#### 84. fix: decode URL
- 提交：[`63fa500`](https://github.com/bytedance/deer-flow/commit/63fa500716e1a1c2380939b8969ddf52b5bcb4b7)
- 日期：2026-01-18
- 做了什么：修复缺陷或回归问题，主题是“decode URL”。
- 影响范围：主要涉及 前端。
- 改动规模：+2 / -2 行。
- 关键文件：frontend/src/components/workspace/artifacts/artifact-file-detail.tsx；frontend/src/components/workspace/artifacts/file-viewer.tsx。

#### 85. fix: decode URL
- 提交：[`c321c92`](https://github.com/bytedance/deer-flow/commit/c321c9293a8d0f960b9405d5f7844994c2e767fe)
- 日期：2026-01-18
- 做了什么：修复缺陷或回归问题，主题是“decode URL”。
- 影响范围：主要涉及 前端。
- 改动规模：+2 / -2 行。
- 关键文件：frontend/src/components/workspace/artifacts/artifact-file-detail.tsx；frontend/src/components/workspace/artifacts/file-viewer.tsx。

#### 86. fix: Long thinking but with empty content (#12)
- 提交：[`c50540e`](https://github.com/bytedance/deer-flow/commit/c50540e3fc610aa51a6087c8d4e0c8d251b2d0a0)
- 日期：2026-01-18
- 做了什么：修复缺陷或回归问题，主题是“Long thinking but with empty content (#12)”。
- 影响范围：主要涉及 后端。
- 改动规模：+8 / -10 行。
- 关键文件：backend/debug.py；backend/docs/TODO.md；backend/src/agents/lead_agent/prompt.py。

#### 87. fix: Long thinking but with empty content (#12)
- 提交：[`6f97dde`](https://github.com/bytedance/deer-flow/commit/6f97dde5d1654ea853417a2fca1a0da038f1a38a)
- 日期：2026-01-18
- 做了什么：修复缺陷或回归问题，主题是“Long thinking but with empty content (#12)”。
- 影响范围：主要涉及 后端。
- 改动规模：+8 / -10 行。
- 关键文件：backend/debug.py；backend/docs/TODO.md；backend/src/agents/lead_agent/prompt.py。

#### 88. fix: fix message grouping issues
- 提交：[`6bf187c`](https://github.com/bytedance/deer-flow/commit/6bf187c1c24b8191293beb6a2c01147f8848e867)
- 日期：2026-01-18
- 做了什么：修复缺陷或回归问题，主题是“fix message grouping issues”。
- 影响范围：主要涉及 前端。
- 改动规模：+57 / -57 行。
- 关键文件：frontend/src/components/workspace/input-box.tsx；frontend/src/components/workspace/messages/message-list.tsx；frontend/src/core/messages/utils.ts。

#### 89. fix: fix message grouping issues
- 提交：[`71eadc9`](https://github.com/bytedance/deer-flow/commit/71eadc942f80c9c2512286604caea0b46473d63a)
- 日期：2026-01-18
- 做了什么：修复缺陷或回归问题，主题是“fix message grouping issues”。
- 影响范围：主要涉及 前端。
- 改动规模：+57 / -57 行。
- 关键文件：frontend/src/components/workspace/input-box.tsx；frontend/src/components/workspace/messages/message-list.tsx；frontend/src/core/messages/utils.ts。

#### 90. fix: fix backend python execution (#10)
- 提交：[`bfe8a24`](https://github.com/bytedance/deer-flow/commit/bfe8a243504cf726edfdcf7f818f461df09736dd)
- 日期：2026-01-18
- 做了什么：修复缺陷或回归问题，主题是“fix backend python execution (#10)”。
- 影响范围：主要涉及 后端。
- 改动规模：+4 / -4 行。
- 关键文件：backend/Makefile。

#### 91. fix: fix backend python execution (#10)
- 提交：[`5a0912d`](https://github.com/bytedance/deer-flow/commit/5a0912d0fda136b6d7584a0e36c4ba7f6d42ccb7)
- 日期：2026-01-18
- 做了什么：修复缺陷或回归问题，主题是“fix backend python execution (#10)”。
- 影响范围：主要涉及 后端。
- 改动规模：+4 / -4 行。
- 关键文件：backend/Makefile。

#### 92. fix(docker): nodejs  CVE-2025-59466 (#818)
- 提交：[`2ed0eeb`](https://github.com/bytedance/deer-flow/commit/2ed0eeb10750fa67f05de2fc40992f7a7ab76760)
- 日期：2026-01-17
- 做了什么：修复缺陷或回归问题，主题是“nodejs  CVE-2025-59466 (#818)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+2 / -2 行。
- 关键文件：web/Dockerfile。

#### 93. fix: fix z index
- 提交：[`caf761b`](https://github.com/bytedance/deer-flow/commit/caf761be599edc47f8529ce75378f3fdcd1a7e57)
- 日期：2026-01-17
- 做了什么：修复缺陷或回归问题，主题是“fix z index”。
- 影响范围：主要涉及 前端。
- 改动规模：+2 / -2 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx。

#### 94. fix: fix z index
- 提交：[`88eb341`](https://github.com/bytedance/deer-flow/commit/88eb3411158785c0dd15ddc1624ff2929c5bc142)
- 日期：2026-01-17
- 做了什么：修复缺陷或回归问题，主题是“fix z index”。
- 影响范围：主要涉及 前端。
- 改动规模：+2 / -2 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx。

#### 95. fix: remove unused imports
- 提交：[`df65010`](https://github.com/bytedance/deer-flow/commit/df65010e5f0121e8e33c488ca2ac7c9b62537372)
- 日期：2026-01-17
- 做了什么：修复缺陷或回归问题，主题是“remove unused imports”。
- 影响范围：主要涉及 前端。
- 改动规模：+0 / -2 行。
- 关键文件：frontend/src/components/workspace/input-box.tsx。

#### 96. fix: remove unused imports
- 提交：[`e418eb6`](https://github.com/bytedance/deer-flow/commit/e418eb61100b639be9d4367f4e3567a415ffc114)
- 日期：2026-01-17
- 做了什么：修复缺陷或回归问题，主题是“remove unused imports”。
- 影响范围：主要涉及 前端。
- 改动规模：+0 / -2 行。
- 关键文件：frontend/src/components/workspace/input-box.tsx。

#### 97. fix: remove unused imports
- 提交：[`97dbcc4`](https://github.com/bytedance/deer-flow/commit/97dbcc4bd6160193159bb35bc358d7cfb2719d62)
- 日期：2026-01-17
- 做了什么：修复缺陷或回归问题，主题是“remove unused imports”。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -5 行。
- 关键文件：frontend/src/components/workspace/messages/message-list-item.tsx。

#### 98. fix: remove unused imports
- 提交：[`63f3c9e`](https://github.com/bytedance/deer-flow/commit/63f3c9e2bb1bdb8b44a5c33ff9a34f66ea85ea75)
- 日期：2026-01-17
- 做了什么：修复缺陷或回归问题，主题是“remove unused imports”。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -5 行。
- 关键文件：frontend/src/components/workspace/messages/message-list-item.tsx。

#### 99. fix: do not display 'Untitled'
- 提交：[`584eed0`](https://github.com/bytedance/deer-flow/commit/584eed01662562d8fe333f7414917568693ea064)
- 日期：2026-01-17
- 做了什么：修复缺陷或回归问题，主题是“do not display 'Untitled'”。
- 影响范围：主要涉及 前端。
- 改动规模：+9 / -4 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx。

#### 100. fix: do not display 'Untitled'
- 提交：[`be1e016`](https://github.com/bytedance/deer-flow/commit/be1e016ed476ea87a1886fd161c137be693e53c3)
- 日期：2026-01-17
- 做了什么：修复缺陷或回归问题，主题是“do not display 'Untitled'”。
- 影响范围：主要涉及 前端。
- 改动规模：+9 / -4 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx。

#### 101. fix: fix broken when SSE
- 提交：[`34ca58e`](https://github.com/bytedance/deer-flow/commit/34ca58ed1b6e4957cb39a5f08388fad98614e7b5)
- 日期：2026-01-16
- 做了什么：修复缺陷或回归问题，主题是“fix broken when SSE”。
- 影响范围：主要涉及 前端。
- 改动规模：+16 / -16 行。
- 关键文件：frontend/src/components/workspace/message-list/message-group.tsx；frontend/src/components/workspace/message-list/present-file-list.tsx；frontend/src/core/messages/utils.ts。

#### 102. fix: fix broken when SSE
- 提交：[`16a5ed9`](https://github.com/bytedance/deer-flow/commit/16a5ed9a739ef9c1073f88f49ebd73a36bae9252)
- 日期：2026-01-16
- 做了什么：修复缺陷或回归问题，主题是“fix broken when SSE”。
- 影响范围：主要涉及 前端。
- 改动规模：+16 / -16 行。
- 关键文件：frontend/src/components/workspace/message-list/message-group.tsx；frontend/src/components/workspace/message-list/present-file-list.tsx；frontend/src/core/messages/utils.ts。

#### 103. fix: lastStep could be empty
- 提交：[`f19e3ae`](https://github.com/bytedance/deer-flow/commit/f19e3ae8acde8c3a8abf45b25c444dee87ed3e5f)
- 日期：2026-01-16
- 做了什么：修复缺陷或回归问题，主题是“lastStep could be empty”。
- 影响范围：主要涉及 前端。
- 改动规模：+5 / -2 行。
- 关键文件：frontend/src/components/workspace/message-list/message-group.tsx。

#### 104. fix: lastStep could be empty
- 提交：[`5ef3cb5`](https://github.com/bytedance/deer-flow/commit/5ef3cb57ee66cd4acb8834cd382ccf9f1852bfbf)
- 日期：2026-01-16
- 做了什么：修复缺陷或回归问题，主题是“lastStep could be empty”。
- 影响范围：主要涉及 前端。
- 改动规模：+5 / -2 行。
- 关键文件：frontend/src/components/workspace/message-list/message-group.tsx。

#### 105. fix: navigate to home only in open-mode
- 提交：[`1f03fb3`](https://github.com/bytedance/deer-flow/commit/1f03fb3749f7a704bdad77558273742e39ee4524)
- 日期：2026-01-16
- 做了什么：修复缺陷或回归问题，主题是“navigate to home only in open-mode”。
- 影响范围：主要涉及 前端。
- 改动规模：+21 / -21 行。
- 关键文件：frontend/src/components/workspace/workspace-header.tsx。

#### 106. fix: navigate to home only in open-mode
- 提交：[`5c94e6d`](https://github.com/bytedance/deer-flow/commit/5c94e6d222795f2f4e114debecd211cff72de269)
- 日期：2026-01-16
- 做了什么：修复缺陷或回归问题，主题是“navigate to home only in open-mode”。
- 影响范围：主要涉及 前端。
- 改动规模：+21 / -21 行。
- 关键文件：frontend/src/components/workspace/workspace-header.tsx。

#### 107. fix: fix local path for local sandbox (#3)
- 提交：[`a39f799`](https://github.com/bytedance/deer-flow/commit/a39f799a7e740be121e1cffccbcea7e9f539d6b5)
- 日期：2026-01-15
- 做了什么：修复缺陷或回归问题，主题是“fix local path for local sandbox (#3)”。
- 影响范围：主要涉及 后端、其他模块。
- 改动规模：+123 / -10 行。
- 关键文件：.gitignore；backend/src/agents/lead_agent/prompt.py；backend/src/sandbox/tools.py。

#### 108. fix: fix local path for local sandbox (#3)
- 提交：[`3b879e2`](https://github.com/bytedance/deer-flow/commit/3b879e277eb7652b812c0952d6a4daca955c452a)
- 日期：2026-01-15
- 做了什么：修复缺陷或回归问题，主题是“fix local path for local sandbox (#3)”。
- 影响范围：主要涉及 后端、其他模块。
- 改动规模：+123 / -10 行。
- 关键文件：.gitignore；backend/src/agents/lead_agent/prompt.py；backend/src/sandbox/tools.py。

#### 109. fix(config): Add support for MCP server configuration parameters (#812)
- 提交：[`6b73a53`](https://github.com/bytedance/deer-flow/commit/6b73a5399951da8adbf579a86832a5251fe8f827)
- 日期：2026-01-10
- 做了什么：修复缺陷或回归问题，主题是“Add support for MCP server configuration parameters (#812)”。
- 影响范围：主要涉及 其他模块、文档。
- 改动规模：+207 / -13 行。
- 关键文件：docs/mcp_integrations.md；src/server/app.py；src/server/mcp_request.py；src/server/mcp_utils.py；tests/unit/server/test_app.py；tests/unit/server/test_mcp_request.py；tests/unit/server/test_mcp_utils.py；web/src/core/mcp/schema.ts。

#### 110. fix(frontend):eliminating the empty divider issue on the frontend (#811)
- 提交：[`e52e69b`](https://github.com/bytedance/deer-flow/commit/e52e69bdd4c0a41d83835d77eeaebfd627aebdce)
- 日期：2026-01-09
- 做了什么：修复缺陷或回归问题，主题是“eliminating the empty divider issue on the frontend (#811)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+293 / -17 行。
- 关键文件：web/src/core/store/store.ts；web/tests/store.test.ts。

#### 111. fix(frontend): passing the MCP header and env setting to backend (#810)
- 提交：[`3360403`](https://github.com/bytedance/deer-flow/commit/336040310c624f2b526f043d7e540657544f4fc8)
- 日期：2026-01-09
- 做了什么：修复缺陷或回归问题，主题是“passing the MCP header and env setting to backend (#810)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+7 / -0 行。
- 关键文件：web/src/app/settings/dialogs/add-mcp-server-dialog.tsx；web/src/core/mcp/schema.ts。

#### 112. Fix message validation JSON import (#809)
- 提交：[`8c59f63`](https://github.com/bytedance/deer-flow/commit/8c59f63d1b1b46bd2382d115a5e6eec70202295c)
- 日期：2026-01-09
- 做了什么：修复缺陷或回归问题，主题是“Fix message validation JSON import (#809)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+3 / -1 行。
- 关键文件：src/utils/context_manager.py。

#### 113. fix: Add runtime parameter to compress_messages method(#803)
- 提交：[`a376b0c`](https://github.com/bytedance/deer-flow/commit/a376b0cb4e28a4a17c2ba2b2baa38e55e36e3eb3)
- 日期：2026-01-07
- 做了什么：修复缺陷或回归问题，主题是“Add runtime parameter to compress_messages method(#803)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+30 / -1 行。
- 关键文件：src/utils/context_manager.py；tests/unit/utils/test_context_manager.py。

#### 114. fix: migrate from deprecated create_react_agent to langchain.agents.create_agent (#802)
- 提交：[`d4ab77d`](https://github.com/bytedance/deer-flow/commit/d4ab77de5c630855b13c735828c61dcc076294cd)
- 日期：2026-01-07
- 做了什么：修复缺陷或回归问题，主题是“migrate from deprecated create_react_agent to langchain.agents.create_agent (#802)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+440 / -14 行。
- 关键文件：src/agents/agents.py；src/prompts/template.py；tests/integration/test_tool_interceptor_integration.py；tests/unit/agents/test_middleware.py；tests/unit/graph/test_agent_locale_restoration.py。

#### 115. fix(frontend):added the display of the 'analyst' message #800 (#801)
- 提交：[`1ced90b`](https://github.com/bytedance/deer-flow/commit/1ced90b0553f44f68556eceb2385f6ddc1a27551)
- 日期：2026-01-06
- 做了什么：修复缺陷或回归问题，主题是“added the display of the 'analyst' message #800 (#801)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+4 / -2 行。
- 关键文件：web/src/core/messages/types.ts；web/src/core/store/store.ts。

#### 116. fix(frontend): render all tool calls in the frontend #796 (#797)
- 提交：[`7ebbb53`](https://github.com/bytedance/deer-flow/commit/7ebbb53b57ce2796feab37ab3543fad2b5e25dce)
- 日期：2026-01-05
- 做了什么：修复缺陷或回归问题，主题是“render all tool calls in the frontend #796 (#797)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+18 / -15 行。
- 关键文件：web/src/app/chat/components/research-activities-block.tsx。

#### 117. fix(log): Enable the logging level  when enabling the DEBUG environment variable (#793)
- 提交：[`275aab9`](https://github.com/bytedance/deer-flow/commit/275aab9d42dbffab36809932e8c8aa2823962809)
- 日期：2026-01-01
- 做了什么：修复缺陷或回归问题，主题是“Enable the logging level  when enabling the DEBUG environment variable (#793)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+25 / -3 行。
- 关键文件：server.py；src/server/app.py；src/workflow.py。

## 2026-02

- 提交数：100 条

#### 1. fix(git):add .gitattributes to avoid 'bash\r' issue (#924)
- 提交：[`5ad8a65`](https://github.com/bytedance/deer-flow/commit/5ad8a657f49fbbae296713d20a85fe5aadbf66d5)
- 日期：2026-02-28
- 做了什么：修复缺陷或回归问题，主题是“add .gitattributes to avoid 'bash\r' issue (#924)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+43 / -0 行。
- 关键文件：.gitattributes。

#### 2. fix(i18n): normalize locale and prevent undefined translations (#914)
- 提交：[`e9adaab`](https://github.com/bytedance/deer-flow/commit/e9adaab7a63482e62a288ed7fb72500aba7ccacb)
- 日期：2026-02-27
- 做了什么：修复缺陷或回归问题，主题是“normalize locale and prevent undefined translations (#914)”。
- 影响范围：主要涉及 前端。
- 改动规模：+81 / -32 行。
- 关键文件：frontend/src/components/workspace/settings/appearance-settings-page.tsx；frontend/src/core/i18n/hooks.ts；frontend/src/core/i18n/index.ts；frontend/src/core/i18n/locale.ts；frontend/src/core/i18n/server.ts。

#### 3. fix: recover from stale model context when configured models change (#898)
- 提交：[`6a55860`](https://github.com/bytedance/deer-flow/commit/6a55860a1588db4cb8f5ba463d278861ed73d65f)
- 日期：2026-02-26
- 做了什么：修复缺陷或回归问题，主题是“recover from stale model context when configured models change (#898)”。
- 影响范围：主要涉及 后端、前端。
- 改动规模：+243 / -28 行。
- 关键文件：backend/src/agents/lead_agent/agent.py；backend/tests/test_lead_agent_model_resolution.py；frontend/src/components/workspace/input-box.tsx。

#### 4. fix(middleware): fix DanglingToolCallMiddleware inserting patches at wrong position (#904)
- 提交：[`d27a7a5`](https://github.com/bytedance/deer-flow/commit/d27a7a5f54f01f4c96db517d57473bdd56261b13)
- 日期：2026-02-25
- 做了什么：修复缺陷或回归问题，主题是“fix DanglingToolCallMiddleware inserting patches at wrong position (#904)”。
- 影响范围：主要涉及 后端。
- 改动规模：+62 / -26 行。
- 关键文件：backend/src/agents/middlewares/dangling_tool_call_middleware.py。

#### 5. fix(skill): enhance data authenticity protocols and clarify reporting guidelines (#905)
- 提交：[`33595f0`](https://github.com/bytedance/deer-flow/commit/33595f0bac29df1c4ce20a28762504abd4dcb80d)
- 日期：2026-02-25
- 做了什么：修复缺陷或回归问题，主题是“enhance data authenticity protocols and clarify reporting guidelines (#905)”。
- 影响范围：主要涉及 技能体系。
- 改动规模：+13 / -2 行。
- 关键文件：skills/public/consulting-analysis/SKILL.md。

#### 6. fix(docker): update nginx configuration and simplify docker script (#903)
- 提交：[`3a7251c`](https://github.com/bytedance/deer-flow/commit/3a7251c95ea5bf97dfbb3db1b4959cd930ebd2a0)
- 日期：2026-02-25
- 做了什么：修复缺陷或回归问题，主题是“update nginx configuration and simplify docker script (#903)”。
- 影响范围：主要涉及 容器部署、脚本工具。
- 改动规模：+6 / -10 行。
- 关键文件：docker/docker-compose-dev.yaml；docker/nginx/nginx.conf；scripts/docker.sh。

#### 7. fix(sandbox):deer-flow-provisioner container fails to start in local execution mode (#889)
- 提交：[`03705ac`](https://github.com/bytedance/deer-flow/commit/03705acf3a116e24251d2d6a8a92d1fbd7d77ca7)
- 日期：2026-02-24
- 做了什么：修复缺陷或回归问题，主题是“deer-flow-provisioner container fails to start in local execution mode (#889)”。
- 影响范围：主要涉及 后端、容器部署、其他模块。
- 改动规模：+452 / -52 行。
- 关键文件：.github/workflows/backend-unit-tests.yml；CONTRIBUTING.md；Makefile；README.md；backend/CLAUDE.md；backend/docs/CONFIGURATION.md；backend/tests/test_docker_sandbox_mode_detection.py；backend/tests/test_provisioner_kubeconfig.py。

#### 8. fix: HTML artifact preview renders blank in preview mode (#876)
- 提交：[`9f74589`](https://github.com/bytedance/deer-flow/commit/9f74589d09f08aa29778f4eb46d18c0869558fc1)
- 日期：2026-02-18
- 做了什么：修复缺陷或回归问题，主题是“HTML artifact preview renders blank in preview mode (#876)”。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -2 行。
- 关键文件：frontend/src/components/workspace/artifacts/artifact-file-detail.tsx。

#### 9. fix: use /tmp/nginx.pid to avoid permission denied errors (#877)
- 提交：[`67dbb10`](https://github.com/bytedance/deer-flow/commit/67dbb10c2a4c2cc2fac22d7827f936f9148e8de0)
- 日期：2026-02-18
- 做了什么：修复缺陷或回归问题，主题是“use /tmp/nginx.pid to avoid permission denied errors (#877)”。
- 影响范围：主要涉及 容器部署。
- 改动规模：+2 / -2 行。
- 关键文件：docker/nginx/nginx.conf；docker/nginx/nginx.local.conf。

#### 10. fix: move Key Citations to early position in reporter prompt to reduce URL hallucination (#859)
- 提交：[`13a2511`](https://github.com/bytedance/deer-flow/commit/13a25112b1cb858aa56e2d77c385a28ff95f83ea)
- 日期：2026-02-14
- 做了什么：修复缺陷或回归问题，主题是“move Key Citations to early position in reporter prompt to reduce URL hallucination (#859)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+31 / -17 行。
- 关键文件：src/graph/nodes.py；src/prompts/reporter.md。

#### 11. security: patch orjson DoS and harden container/frontend (#852)
- 提交：[`ba45c1a`](https://github.com/bytedance/deer-flow/commit/ba45c1a3a9fb3ead7809bf08976d1305185b4fe6)
- 日期：2026-02-13
- 做了什么：修复缺陷或回归问题，主题是“security: patch orjson DoS and harden container/frontend (#852)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+59 / -37 行。
- 关键文件：Dockerfile；pyproject.toml；uv.lock；web/src/components/deer-flow/message-input.tsx。

#### 12. fix: 修复新建技能后输入框无法编辑的问题
- 提交：[`b3a1f01`](https://github.com/bytedance/deer-flow/commit/b3a1f018ab56626accb8d8f993f0d6087fe2faa8)
- 日期：2026-02-10
- 做了什么：修复缺陷或回归问题，主题是“修复新建技能后输入框无法编辑的问题”。
- 影响范围：主要涉及 前端。
- 改动规模：+8 / -4 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx。

#### 13. fix:memory 为空时i18n字体显示
- 提交：[`cc88823`](https://github.com/bytedance/deer-flow/commit/cc88823a64d74d063dcf4cbdf3861f4e31e0a255)
- 日期：2026-02-10
- 做了什么：修复缺陷或回归问题，主题是“memory 为空时i18n字体显示”。
- 影响范围：主要涉及 前端。
- 改动规模：+2 / -2 行。
- 关键文件：frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/zh-CN.ts。

#### 14. fix: citations prompt
- 提交：[`6109216`](https://github.com/bytedance/deer-flow/commit/6109216d54b7816556725f2e8e3564653fd15122)
- 日期：2026-02-10
- 做了什么：修复缺陷或回归问题，主题是“citations prompt”。
- 影响范围：主要涉及 后端。
- 改动规模：+9 / -1 行。
- 关键文件：backend/src/agents/lead_agent/prompt.py。

#### 15. fix: eslint
- 提交：[`13b3032`](https://github.com/bytedance/deer-flow/commit/13b3032d02a4071febde3248544f984247ea7fd0)
- 日期：2026-02-09
- 做了什么：修复缺陷或回归问题，主题是“eslint”。
- 影响范围：主要涉及 前端。
- 改动规模：+2 / -1 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx。

#### 16. fix: eslint
- 提交：[`df3668e`](https://github.com/bytedance/deer-flow/commit/df3668ecd50eacdd8f59d801522ab650608ab3f2)
- 日期：2026-02-09
- 做了什么：修复缺陷或回归问题，主题是“eslint”。
- 影响范围：主要涉及 前端。
- 改动规模：+2 / -1 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx。

#### 17. fix: Add None check for db_uri in ChatStreamManager (#854)
- 提交：[`7607e14`](https://github.com/bytedance/deer-flow/commit/7607e140884554f8dc3a3000035403f638033edd)
- 日期：2026-02-09
- 做了什么：修复缺陷或回归问题，主题是“Add None check for db_uri in ChatStreamManager (#854)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+6 / -1 行。
- 关键文件：src/graph/checkpoint.py。

#### 18. fix(frontend): no half-finished citations, correct state when SSE ends
- 提交：[`d9a86c1`](https://github.com/bytedance/deer-flow/commit/d9a86c10e88ef7f066aa2ba4c0c280274e53e9e8)
- 日期：2026-02-09
- 做了什么：修复缺陷或回归问题，主题是“no half-finished citations, correct state when SSE ends”。
- 影响范围：主要涉及 前端、其他模块。
- 改动规模：+25 / -37 行。
- 关键文件：.githooks/pre-commit；.gitignore；frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/workspace/messages/message-list.tsx；frontend/src/core/citations/utils.ts。

#### 19. fix(frontend): no half-finished citations, correct state when SSE ends
- 提交：[`53509ea`](https://github.com/bytedance/deer-flow/commit/53509eaeb1a728e330d07da5f62baa58982fcbda)
- 日期：2026-02-09
- 做了什么：修复缺陷或回归问题，主题是“no half-finished citations, correct state when SSE ends”。
- 影响范围：主要涉及 前端、其他模块。
- 改动规模：+25 / -37 行。
- 关键文件：.githooks/pre-commit；.gitignore；frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/workspace/messages/message-list.tsx；frontend/src/core/citations/utils.ts。

#### 20. fix(frontend): citations display + refactor link/citation utils
- 提交：[`2d70aaa`](https://github.com/bytedance/deer-flow/commit/2d70aaa969dc575d448911b4dd836387b2fc2588)
- 日期：2026-02-09
- 做了什么：修复缺陷或回归问题，主题是“citations display + refactor link/citation utils”。
- 影响范围：主要涉及 前端。
- 改动规模：+69 / -19 行。
- 关键文件：frontend/src/components/workspace/artifacts/artifact-file-detail.tsx；frontend/src/components/workspace/messages/message-list-item.tsx；frontend/src/core/citations/index.ts；frontend/src/core/citations/utils.ts；frontend/src/lib/utils.ts。

#### 21. fix(frontend): citations display + refactor link/citation utils
- 提交：[`509ea87`](https://github.com/bytedance/deer-flow/commit/509ea874f778d28092c518f3235ab5e858e0876d)
- 日期：2026-02-09
- 做了什么：修复缺陷或回归问题，主题是“citations display + refactor link/citation utils”。
- 影响范围：主要涉及 前端。
- 改动规模：+69 / -19 行。
- 关键文件：frontend/src/components/workspace/artifacts/artifact-file-detail.tsx；frontend/src/components/workspace/messages/message-list-item.tsx；frontend/src/core/citations/index.ts；frontend/src/core/citations/utils.ts；frontend/src/lib/utils.ts。

#### 22. fix(frontend): build + remove hover tooltips in step links
- 提交：[`d72aad8`](https://github.com/bytedance/deer-flow/commit/d72aad806347c501794faf3126fb6792278542df)
- 日期：2026-02-09
- 做了什么：修复缺陷或回归问题，主题是“build + remove hover tooltips in step links”。
- 影响范围：主要涉及 前端。
- 改动规模：+82 / -53 行。
- 关键文件：frontend/next.config.js；frontend/package.json；frontend/src/components/workspace/messages/message-group.tsx；frontend/src/components/workspace/settings/about-content.ts；frontend/src/components/workspace/settings/about-settings-page.tsx。

#### 23. fix(frontend): build + remove hover tooltips in step links
- 提交：[`8cb14ad`](https://github.com/bytedance/deer-flow/commit/8cb14ad4fb2dd71130b19c2a89b9e969d7e54609)
- 日期：2026-02-09
- 做了什么：修复缺陷或回归问题，主题是“build + remove hover tooltips in step links”。
- 影响范围：主要涉及 前端。
- 改动规模：+82 / -53 行。
- 关键文件：frontend/next.config.js；frontend/package.json；frontend/src/components/workspace/messages/message-group.tsx；frontend/src/components/workspace/settings/about-content.ts；frontend/src/components/workspace/settings/about-settings-page.tsx。

#### 24. Revert "fix(frontend): Turbopack about page + remove hover on web search/citations"
- 提交：[`fe06be8`](https://github.com/bytedance/deer-flow/commit/fe06be825801bf3f747fff0436c376e359a0b355)
- 日期：2026-02-09
- 做了什么：修复缺陷或回归问题，主题是“Revert "fix(frontend): Turbopack about page + remove hover on web search/citations"”。
- 影响范围：主要涉及 前端。
- 改动规模：+51 / -79 行。
- 关键文件：frontend/src/components/ai-elements/inline-citation.tsx；frontend/src/components/workspace/messages/message-group.tsx；frontend/src/components/workspace/settings/about-content.ts；frontend/src/components/workspace/settings/about-settings-page.tsx。

#### 25. Revert "fix(frontend): Turbopack about page + remove hover on web search/citations"
- 提交：[`f577ff1`](https://github.com/bytedance/deer-flow/commit/f577ff115bc3f2dbb84e2eeff9ab1f3b45103b2d)
- 日期：2026-02-09
- 做了什么：修复缺陷或回归问题，主题是“Revert "fix(frontend): Turbopack about page + remove hover on web search/citations"”。
- 影响范围：主要涉及 前端。
- 改动规模：+51 / -79 行。
- 关键文件：frontend/src/components/ai-elements/inline-citation.tsx；frontend/src/components/workspace/messages/message-group.tsx；frontend/src/components/workspace/settings/about-content.ts；frontend/src/components/workspace/settings/about-settings-page.tsx。

#### 26. fix(frontend): Turbopack about page + remove hover on web search/citations
- 提交：[`842c4ec`](https://github.com/bytedance/deer-flow/commit/842c4ecac0806359cba55fda80f22f926d905782)
- 日期：2026-02-09
- 做了什么：修复缺陷或回归问题，主题是“Turbopack about page + remove hover on web search/citations”。
- 影响范围：主要涉及 前端。
- 改动规模：+79 / -51 行。
- 关键文件：frontend/src/components/ai-elements/inline-citation.tsx；frontend/src/components/workspace/messages/message-group.tsx；frontend/src/components/workspace/settings/about-content.ts；frontend/src/components/workspace/settings/about-settings-page.tsx。

#### 27. fix(frontend): Turbopack about page + remove hover on web search/citations
- 提交：[`77859d0`](https://github.com/bytedance/deer-flow/commit/77859d01b824f08fd464d0b6cbab4ff2d79da6d9)
- 日期：2026-02-09
- 做了什么：修复缺陷或回归问题，主题是“Turbopack about page + remove hover on web search/citations”。
- 影响范围：主要涉及 前端。
- 改动规模：+79 / -51 行。
- 关键文件：frontend/src/components/ai-elements/inline-citation.tsx；frontend/src/components/workspace/messages/message-group.tsx；frontend/src/components/workspace/settings/about-content.ts；frontend/src/components/workspace/settings/about-settings-page.tsx。

#### 28. fix: fix sub agent timeout
- 提交：[`17365e4`](https://github.com/bytedance/deer-flow/commit/17365e40d53363815b2aa547120d831cea9e5e4f)
- 日期：2026-02-08
- 做了什么：修复缺陷或回归问题，主题是“fix sub agent timeout”。
- 影响范围：主要涉及 后端。
- 改动规模：+15 / -8 行。
- 关键文件：backend/src/subagents/config.py；backend/src/subagents/executor.py；backend/src/tools/builtins/task_tool.py。

#### 29. fix: fix sub agent timeout
- 提交：[`19a1d03`](https://github.com/bytedance/deer-flow/commit/19a1d03fc881afc4d78e2f45990bf52e79896e1a)
- 日期：2026-02-08
- 做了什么：修复缺陷或回归问题，主题是“fix sub agent timeout”。
- 影响范围：主要涉及 后端。
- 改动规模：+15 / -8 行。
- 关键文件：backend/src/subagents/config.py；backend/src/subagents/executor.py；backend/src/tools/builtins/task_tool.py。

#### 30. fix: fix sub agent timeout
- 提交：[`f01c470`](https://github.com/bytedance/deer-flow/commit/f01c470e64279b8fe5c6e30df3c937fa4d7774ba)
- 日期：2026-02-08
- 做了什么：修复缺陷或回归问题，主题是“fix sub agent timeout”。
- 影响范围：主要涉及 后端。
- 改动规模：+15 / -8 行。
- 关键文件：backend/src/subagents/config.py；backend/src/subagents/executor.py；backend/src/tools/builtins/task_tool.py。

#### 31. docs: fix typo and grammar in readme (#851)
- 提交：[`5b29c9f`](https://github.com/bytedance/deer-flow/commit/5b29c9f70a5d5e6c782412115e6b218784743f04)
- 日期：2026-02-08
- 做了什么：修复缺陷或回归问题，主题是“fix typo and grammar in readme (#851)”。
- 影响范围：主要涉及 文档。
- 改动规模：+11 / -11 行。
- 关键文件：README.md。

#### 32. fix: adjust suggestion positioning and height for improved UI layout
- 提交：[`b135449`](https://github.com/bytedance/deer-flow/commit/b135449c078d201974412e73ee51d79f6d7c8e12)
- 日期：2026-02-07
- 做了什么：修复缺陷或回归问题，主题是“adjust suggestion positioning and height for improved UI layout”。
- 影响范围：主要涉及 前端。
- 改动规模：+3 / -3 行。
- 关键文件：frontend/src/components/ai-elements/suggestion.tsx；frontend/src/components/workspace/input-box.tsx。

#### 33. fix: adjust suggestion positioning and height for improved UI layout
- 提交：[`2510991`](https://github.com/bytedance/deer-flow/commit/2510991698af7b66db4beb8f1d7bfa6de15684a2)
- 日期：2026-02-07
- 做了什么：修复缺陷或回归问题，主题是“adjust suggestion positioning and height for improved UI layout”。
- 影响范围：主要涉及 前端。
- 改动规模：+3 / -3 行。
- 关键文件：frontend/src/components/ai-elements/suggestion.tsx；frontend/src/components/workspace/input-box.tsx。

#### 34. fix: adjust suggestion positioning and height for improved UI layout
- 提交：[`17b2630`](https://github.com/bytedance/deer-flow/commit/17b2630b738bc4566d13abba7d493b623fc94036)
- 日期：2026-02-07
- 做了什么：修复缺陷或回归问题，主题是“adjust suggestion positioning and height for improved UI layout”。
- 影响范围：主要涉及 前端。
- 改动规模：+3 / -3 行。
- 关键文件：frontend/src/components/ai-elements/suggestion.tsx；frontend/src/components/workspace/input-box.tsx。

#### 35. fix(server): graceful stream termination on cancellation (issue #847) (#850)
- 提交：[`f21bc6b`](https://github.com/bytedance/deer-flow/commit/f21bc6b83f307a0e9aec04f3ce0f705d1fc22ecd)
- 日期：2026-02-06
- 做了什么：修复缺陷或回归问题，主题是“graceful stream termination on cancellation (issue #847) (#850)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+91 / -9 行。
- 关键文件：src/server/app.py；tests/unit/server/test_app.py；web/src/core/api/chat.ts；web/src/core/api/types.ts；web/src/core/messages/merge-message.ts；web/src/core/store/store.ts。

#### 36. fix: fix markdown table
- 提交：[`5ed15d7`](https://github.com/bytedance/deer-flow/commit/5ed15d79c980af550f350dfa661d7fd10518d8aa)
- 日期：2026-02-06
- 做了什么：修复缺陷或回归问题，主题是“fix markdown table”。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -6 行。
- 关键文件：frontend/src/components/workspace/messages/message-list-item.tsx。

#### 37. fix: fix markdown table
- 提交：[`8f1a42a`](https://github.com/bytedance/deer-flow/commit/8f1a42a8e000333e7486e2200cb4dd2e627e380d)
- 日期：2026-02-06
- 做了什么：修复缺陷或回归问题，主题是“fix markdown table”。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -6 行。
- 关键文件：frontend/src/components/workspace/messages/message-list-item.tsx。

#### 38. fix: fix markdown table
- 提交：[`c3f9089`](https://github.com/bytedance/deer-flow/commit/c3f9089e9547131485045b69ca7257776e717d21)
- 日期：2026-02-06
- 做了什么：修复缺陷或回归问题，主题是“fix markdown table”。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -6 行。
- 关键文件：frontend/src/components/workspace/messages/message-list-item.tsx。

#### 39. Merge pull request #24 from LofiSu/fix/upload-files-alignment
- 提交：[`6b56e68`](https://github.com/bytedance/deer-flow/commit/6b56e68ff2ebdf1a9d303ce55714f06ff4507426)
- 日期：2026-02-06
- 做了什么：修复缺陷或回归问题，主题是“Merge pull request #24 from LofiSu/fix/upload-files-alignment”。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -1 行。
- 关键文件：frontend/src/components/workspace/messages/message-list-item.tsx。

#### 40. Merge pull request #24 from LofiSu/fix/upload-files-alignment
- 提交：[`537687c`](https://github.com/bytedance/deer-flow/commit/537687c2c55ef9746210aa8f689a00ac5159c046)
- 日期：2026-02-06
- 做了什么：修复缺陷或回归问题，主题是“Merge pull request #24 from LofiSu/fix/upload-files-alignment”。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -1 行。
- 关键文件：frontend/src/components/workspace/messages/message-list-item.tsx。

#### 41. Merge pull request #24 from LofiSu/fix/upload-files-alignment
- 提交：[`5016a5f`](https://github.com/bytedance/deer-flow/commit/5016a5f7d9ecde3b35aed6955e8c15c69aca778b)
- 日期：2026-02-06
- 做了什么：修复缺陷或回归问题，主题是“Merge pull request #24 from LofiSu/fix/upload-files-alignment”。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -1 行。
- 关键文件：frontend/src/components/workspace/messages/message-list-item.tsx。

#### 42. fix: fix subagent prompt
- 提交：[`9e4f251`](https://github.com/bytedance/deer-flow/commit/9e4f2512f3e76fe806bd2686022496440f260374)
- 日期：2026-02-06
- 做了什么：修复缺陷或回归问题，主题是“fix subagent prompt”。
- 影响范围：主要涉及 后端。
- 改动规模：+120 / -28 行。
- 关键文件：backend/src/agents/lead_agent/prompt.py。

#### 43. fix: fix subagent prompt
- 提交：[`a423dfb`](https://github.com/bytedance/deer-flow/commit/a423dfb9fd5efc520f7233944cd3cd9a7cd64951)
- 日期：2026-02-06
- 做了什么：修复缺陷或回归问题，主题是“fix subagent prompt”。
- 影响范围：主要涉及 后端。
- 改动规模：+120 / -28 行。
- 关键文件：backend/src/agents/lead_agent/prompt.py。

#### 44. fix: fix subagent prompt
- 提交：[`d1d275b`](https://github.com/bytedance/deer-flow/commit/d1d275bb810dc6f39c2cacc175768f0da11d75cf)
- 日期：2026-02-06
- 做了什么：修复缺陷或回归问题，主题是“fix subagent prompt”。
- 影响范围：主要涉及 后端。
- 改动规模：+120 / -28 行。
- 关键文件：backend/src/agents/lead_agent/prompt.py。

#### 45. fix(citations): hide citations block in reasoning/thinking content
- 提交：[`5484233`](https://github.com/bytedance/deer-flow/commit/548423354847bcf9917bc924c949cd9e65a51abd)
- 日期：2026-02-06
- 做了什么：修复缺陷或回归问题，主题是“hide citations block in reasoning/thinking content”。
- 影响范围：主要涉及 前端。
- 改动规模：+2 / -2 行。
- 关键文件：frontend/src/components/workspace/messages/message-group.tsx。

#### 46. fix(citations): hide citations block in reasoning/thinking content
- 提交：[`ca6bcaa`](https://github.com/bytedance/deer-flow/commit/ca6bcaa31cd7fa1dc273c1495d297b3c25f76808)
- 日期：2026-02-06
- 做了什么：修复缺陷或回归问题，主题是“hide citations block in reasoning/thinking content”。
- 影响范围：主要涉及 前端。
- 改动规模：+2 / -2 行。
- 关键文件：frontend/src/components/workspace/messages/message-group.tsx。

#### 47. fix(citations): hide citations block in reasoning/thinking content
- 提交：[`50ced32`](https://github.com/bytedance/deer-flow/commit/50ced3272229abe56026615f5a7a3c5ba0ea3781)
- 日期：2026-02-06
- 做了什么：修复缺陷或回归问题，主题是“hide citations block in reasoning/thinking content”。
- 影响范围：主要涉及 前端。
- 改动规模：+2 / -2 行。
- 关键文件：frontend/src/components/workspace/messages/message-group.tsx。

#### 48. fix(citations): only citation links in citationMap render as badges
- 提交：[`582bfae`](https://github.com/bytedance/deer-flow/commit/582bfaee39d44d6bfa781b3a97127a27a77c0d83)
- 日期：2026-02-06
- 做了什么：修复缺陷或回归问题，主题是“only citation links in citationMap render as badges”。
- 影响范围：主要涉及 前端。
- 改动规模：+7 / -26 行。
- 关键文件：frontend/src/components/workspace/messages/message-list-item.tsx。

#### 49. fix(citations): only citation links in citationMap render as badges
- 提交：[`666b747`](https://github.com/bytedance/deer-flow/commit/666b747b8ad14bad771fb4755016267ae55215c2)
- 日期：2026-02-06
- 做了什么：修复缺陷或回归问题，主题是“only citation links in citationMap render as badges”。
- 影响范围：主要涉及 前端。
- 改动规模：+7 / -26 行。
- 关键文件：frontend/src/components/workspace/messages/message-list-item.tsx。

#### 50. fix(citations): only citation links in citationMap render as badges
- 提交：[`e8ee198`](https://github.com/bytedance/deer-flow/commit/e8ee19821d43c046251a69c7ac1751bc0078e8ea)
- 日期：2026-02-06
- 做了什么：修复缺陷或回归问题，主题是“only citation links in citationMap render as badges”。
- 影响范围：主要涉及 前端。
- 改动规模：+7 / -26 行。
- 关键文件：frontend/src/components/workspace/messages/message-list-item.tsx。

#### 51. fix(citations): render external links as badges during streaming
- 提交：[`e7ea0fc`](https://github.com/bytedance/deer-flow/commit/e7ea0fc551aef069d136589f11382bbcab6486a9)
- 日期：2026-02-06
- 做了什么：修复缺陷或回归问题，主题是“render external links as badges during streaming”。
- 影响范围：主要涉及 前端。
- 改动规模：+26 / -8 行。
- 关键文件：frontend/src/components/workspace/messages/message-list-item.tsx。

#### 52. fix(citations): render external links as badges during streaming
- 提交：[`697c683`](https://github.com/bytedance/deer-flow/commit/697c683dfaf4badbe0818e44e30889f9729c78a4)
- 日期：2026-02-06
- 做了什么：修复缺陷或回归问题，主题是“render external links as badges during streaming”。
- 影响范围：主要涉及 前端。
- 改动规模：+26 / -8 行。
- 关键文件：frontend/src/components/workspace/messages/message-list-item.tsx。

#### 53. fix(citations): render external links as badges during streaming
- 提交：[`e444817`](https://github.com/bytedance/deer-flow/commit/e444817c5dca4e65afaeabf03a0a47263b40565c)
- 日期：2026-02-06
- 做了什么：修复缺陷或回归问题，主题是“render external links as badges during streaming”。
- 影响范围：主要涉及 前端。
- 改动规模：+26 / -8 行。
- 关键文件：frontend/src/components/workspace/messages/message-list-item.tsx。

#### 54. fix(citations): parse citations in reasoning content
- 提交：[`f1c3f90`](https://github.com/bytedance/deer-flow/commit/f1c3f908c92fdbda6a5194354ef407db1bc730e7)
- 日期：2026-02-06
- 做了什么：修复缺陷或回归问题，主题是“parse citations in reasoning content”。
- 影响范围：主要涉及 前端。
- 改动规模：+4 / -2 行。
- 关键文件：frontend/src/components/workspace/messages/message-list-item.tsx。

#### 55. fix(citations): parse citations in reasoning content
- 提交：[`579dccb`](https://github.com/bytedance/deer-flow/commit/579dccbdcec13c5622deadeb90f938d1dca8be3f)
- 日期：2026-02-06
- 做了什么：修复缺陷或回归问题，主题是“parse citations in reasoning content”。
- 影响范围：主要涉及 前端。
- 改动规模：+4 / -2 行。
- 关键文件：frontend/src/components/workspace/messages/message-list-item.tsx。

#### 56. fix(citations): parse citations in reasoning content
- 提交：[`e9648b1`](https://github.com/bytedance/deer-flow/commit/e9648b11cdf8b9e02542e7625538d6fb09eac446)
- 日期：2026-02-06
- 做了什么：修复缺陷或回归问题，主题是“parse citations in reasoning content”。
- 影响范围：主要涉及 前端。
- 改动规模：+4 / -2 行。
- 关键文件：frontend/src/components/workspace/messages/message-list-item.tsx。

#### 57. fix(artifacts): only render citation badges for links in citationMap
- 提交：[`7c21d8f`](https://github.com/bytedance/deer-flow/commit/7c21d8f3a69066ac4ad49ff8e13cc41780ceb1ea)
- 日期：2026-02-06
- 做了什么：修复缺陷或回归问题，主题是“only render citation badges for links in citationMap”。
- 影响范围：主要涉及 前端。
- 改动规模：+8 / -13 行。
- 关键文件：frontend/src/components/workspace/artifacts/artifact-file-detail.tsx。

#### 58. fix(artifacts): only render citation badges for links in citationMap
- 提交：[`365e3f4`](https://github.com/bytedance/deer-flow/commit/365e3f430478d462fa8caa4bd3cad416ecdbb6f8)
- 日期：2026-02-06
- 做了什么：修复缺陷或回归问题，主题是“only render citation badges for links in citationMap”。
- 影响范围：主要涉及 前端。
- 改动规模：+8 / -13 行。
- 关键文件：frontend/src/components/workspace/artifacts/artifact-file-detail.tsx。

#### 59. fix(artifacts): only render citation badges for links in citationMap
- 提交：[`0cf8ba8`](https://github.com/bytedance/deer-flow/commit/0cf8ba86d121fe43d18584ca9aa99ca949a26319)
- 日期：2026-02-06
- 做了什么：修复缺陷或回归问题，主题是“only render citation badges for links in citationMap”。
- 影响范围：主要涉及 前端。
- 改动规模：+8 / -13 行。
- 关键文件：frontend/src/components/workspace/artifacts/artifact-file-detail.tsx。

#### 60. fix(citations): only render citation badges for links in citationMap
- 提交：[`5d8c08d`](https://github.com/bytedance/deer-flow/commit/5d8c08d3ba105c5624f73a37769b48235e895f14)
- 日期：2026-02-06
- 做了什么：修复缺陷或回归问题，主题是“only render citation badges for links in citationMap”。
- 影响范围：主要涉及 前端。
- 改动规模：+8 / -22 行。
- 关键文件：frontend/src/components/workspace/messages/message-list-item.tsx。

#### 61. fix(citations): only render citation badges for links in citationMap
- 提交：[`1ce154f`](https://github.com/bytedance/deer-flow/commit/1ce154fa71c1264f319eb1c571664f17f284b57a)
- 日期：2026-02-06
- 做了什么：修复缺陷或回归问题，主题是“only render citation badges for links in citationMap”。
- 影响范围：主要涉及 前端。
- 改动规模：+8 / -22 行。
- 关键文件：frontend/src/components/workspace/messages/message-list-item.tsx。

#### 62. fix(citations): only render citation badges for links in citationMap
- 提交：[`7a3a5f5`](https://github.com/bytedance/deer-flow/commit/7a3a5f5196f8a792bb037f88e4390870f34f602d)
- 日期：2026-02-06
- 做了什么：修复缺陷或回归问题，主题是“only render citation badges for links in citationMap”。
- 影响范围：主要涉及 前端。
- 改动规模：+8 / -22 行。
- 关键文件：frontend/src/components/workspace/messages/message-list-item.tsx。

#### 63. fix(citations): use markdown link text as fallback for display
- 提交：[`49f7cf1`](https://github.com/bytedance/deer-flow/commit/49f7cf16621b5586f46478111e3b198c488744a3)
- 日期：2026-02-06
- 做了什么：修复缺陷或回归问题，主题是“use markdown link text as fallback for display”。
- 影响范围：主要涉及 前端。
- 改动规模：+8 / -4 行。
- 关键文件：frontend/src/components/ai-elements/inline-citation.tsx。

#### 64. fix(citations): use markdown link text as fallback for display
- 提交：[`acbf2fb`](https://github.com/bytedance/deer-flow/commit/acbf2fb453f21f05badaacdfcb7a45f3d0a46ab2)
- 日期：2026-02-06
- 做了什么：修复缺陷或回归问题，主题是“use markdown link text as fallback for display”。
- 影响范围：主要涉及 前端。
- 改动规模：+8 / -4 行。
- 关键文件：frontend/src/components/ai-elements/inline-citation.tsx。

#### 65. fix(citations): use markdown link text as fallback for display
- 提交：[`c87f176`](https://github.com/bytedance/deer-flow/commit/c87f176fac5368ea14e67bf8217cb613d8652e1e)
- 日期：2026-02-06
- 做了什么：修复缺陷或回归问题，主题是“use markdown link text as fallback for display”。
- 影响范围：主要涉及 前端。
- 改动规模：+8 / -4 行。
- 关键文件：frontend/src/components/ai-elements/inline-citation.tsx。

#### 66. fix(prompt): clarify citation link format must include URL
- 提交：[`a91302a`](https://github.com/bytedance/deer-flow/commit/a91302ac72eebc87a1e365e089c81158f189a433)
- 日期：2026-02-06
- 做了什么：修复缺陷或回归问题，主题是“clarify citation link format must include URL”。
- 影响范围：主要涉及 后端。
- 改动规模：+12 / -7 行。
- 关键文件：backend/src/agents/lead_agent/prompt.py。

#### 67. fix(prompt): clarify citation link format must include URL
- 提交：[`f43522b`](https://github.com/bytedance/deer-flow/commit/f43522bd274579567004b312c28ccb4096d81b6d)
- 日期：2026-02-06
- 做了什么：修复缺陷或回归问题，主题是“clarify citation link format must include URL”。
- 影响范围：主要涉及 后端。
- 改动规模：+12 / -7 行。
- 关键文件：backend/src/agents/lead_agent/prompt.py。

#### 68. fix(prompt): clarify citation link format must include URL
- 提交：[`b46a19e`](https://github.com/bytedance/deer-flow/commit/b46a19e1165ff28acb97502ccae1565a29585ee4)
- 日期：2026-02-06
- 做了什么：修复缺陷或回归问题，主题是“clarify citation link format must include URL”。
- 影响范围：主要涉及 后端。
- 改动规模：+12 / -7 行。
- 关键文件：backend/src/agents/lead_agent/prompt.py。

#### 69. fix(messages): prevent URL autolink bleeding into adjacent text
- 提交：[`738b71b`](https://github.com/bytedance/deer-flow/commit/738b71be47ebb777542109fcb3af0c0db29caedc)
- 日期：2026-02-06
- 做了什么：修复缺陷或回归问题，主题是“prevent URL autolink bleeding into adjacent text”。
- 影响范围：主要涉及 前端。
- 改动规模：+16 / -3 行。
- 关键文件：frontend/src/components/workspace/messages/message-list-item.tsx；frontend/src/core/streamdown/plugins.ts。

#### 70. fix(messages): prevent URL autolink bleeding into adjacent text
- 提交：[`c8c4d2f`](https://github.com/bytedance/deer-flow/commit/c8c4d2fc953c634867e721698ce6fa1d0e1020fe)
- 日期：2026-02-06
- 做了什么：修复缺陷或回归问题，主题是“prevent URL autolink bleeding into adjacent text”。
- 影响范围：主要涉及 前端。
- 改动规模：+16 / -3 行。
- 关键文件：frontend/src/components/workspace/messages/message-list-item.tsx；frontend/src/core/streamdown/plugins.ts。

#### 71. fix(messages): prevent URL autolink bleeding into adjacent text
- 提交：[`34a199c`](https://github.com/bytedance/deer-flow/commit/34a199c6f3460dd15ed836690a9ab284e92b4cf4)
- 日期：2026-02-06
- 做了什么：修复缺陷或回归问题，主题是“prevent URL autolink bleeding into adjacent text”。
- 影响范围：主要涉及 前端。
- 改动规模：+16 / -3 行。
- 关键文件：frontend/src/components/workspace/messages/message-list-item.tsx；frontend/src/core/streamdown/plugins.ts。

#### 72. fix(citations): only render CitationLink badges for AI messages
- 提交：[`6f96824`](https://github.com/bytedance/deer-flow/commit/6f968242d64a3e0018a292511cdfdb3fa24e599f)
- 日期：2026-02-06
- 做了什么：修复缺陷或回归问题，主题是“only render CitationLink badges for AI messages”。
- 影响范围：主要涉及 前端。
- 改动规模：+20 / -4 行。
- 关键文件：frontend/src/components/workspace/messages/message-list-item.tsx。

#### 73. fix(citations): only render CitationLink badges for AI messages
- 提交：[`1b0c016`](https://github.com/bytedance/deer-flow/commit/1b0c0160939ae29198a169056064d9e96480c5d9)
- 日期：2026-02-06
- 做了什么：修复缺陷或回归问题，主题是“only render CitationLink badges for AI messages”。
- 影响范围：主要涉及 前端。
- 改动规模：+20 / -4 行。
- 关键文件：frontend/src/components/workspace/messages/message-list-item.tsx。

#### 74. fix(citations): only render CitationLink badges for AI messages
- 提交：[`bcbbf9c`](https://github.com/bytedance/deer-flow/commit/bcbbf9cf3fdb0626c978a994ec158eb785314ef9)
- 日期：2026-02-06
- 做了什么：修复缺陷或回归问题，主题是“only render CitationLink badges for AI messages”。
- 影响范围：主要涉及 前端。
- 改动规模：+20 / -4 行。
- 关键文件：frontend/src/components/workspace/messages/message-list-item.tsx。

#### 75. fix(citations): improve citation link rendering and copy behavior
- 提交：[`2debcf4`](https://github.com/bytedance/deer-flow/commit/2debcf421c1a7f2150f2c22462e09e6ee3e93770)
- 日期：2026-02-04
- 做了什么：修复缺陷或回归问题，主题是“improve citation link rendering and copy behavior”。
- 影响范围：主要涉及 前端、后端。
- 改动规模：+26 / -26 行。
- 关键文件：backend/src/agents/lead_agent/prompt.py；frontend/src/components/ai-elements/inline-citation.tsx；frontend/src/components/workspace/messages/message-list-item.tsx。

#### 76. fix(citations): improve citation link rendering and copy behavior
- 提交：[`f6e625e`](https://github.com/bytedance/deer-flow/commit/f6e625ec3b7ffc74fc9768cd273b067b6c584540)
- 日期：2026-02-04
- 做了什么：修复缺陷或回归问题，主题是“improve citation link rendering and copy behavior”。
- 影响范围：主要涉及 前端、后端。
- 改动规模：+26 / -26 行。
- 关键文件：backend/src/agents/lead_agent/prompt.py；frontend/src/components/ai-elements/inline-citation.tsx；frontend/src/components/workspace/messages/message-list-item.tsx。

#### 77. fix(citations): improve citation link rendering and copy behavior
- 提交：[`0f9e3d5`](https://github.com/bytedance/deer-flow/commit/0f9e3d508bde05e77ca64493d93bddbe2266d33e)
- 日期：2026-02-04
- 做了什么：修复缺陷或回归问题，主题是“improve citation link rendering and copy behavior”。
- 影响范围：主要涉及 前端、后端。
- 改动规模：+26 / -26 行。
- 关键文件：backend/src/agents/lead_agent/prompt.py；frontend/src/components/ai-elements/inline-citation.tsx；frontend/src/components/workspace/messages/message-list-item.tsx。

#### 78. fix: fix frontend rendering issue
- 提交：[`b773bae`](https://github.com/bytedance/deer-flow/commit/b773bae407fc186ff94a34c895edad76c85d8ec5)
- 日期：2026-02-03
- 做了什么：修复缺陷或回归问题，主题是“fix frontend rendering issue”。
- 影响范围：主要涉及 前端。
- 改动规模：+4 / -1 行。
- 关键文件：frontend/next.config.js；frontend/src/app/workspace/layout.tsx。

#### 79. fix: fix frontend rendering issue
- 提交：[`d670cc0`](https://github.com/bytedance/deer-flow/commit/d670cc0ab1cd0bf5177c85811a2a1745457a1b77)
- 日期：2026-02-03
- 做了什么：修复缺陷或回归问题，主题是“fix frontend rendering issue”。
- 影响范围：主要涉及 前端。
- 改动规模：+4 / -1 行。
- 关键文件：frontend/next.config.js；frontend/src/app/workspace/layout.tsx。

#### 80. fix: fix frontend rendering issue
- 提交：[`8f8637c`](https://github.com/bytedance/deer-flow/commit/8f8637c3c4a0de589d9d83605c6b4141d141abb5)
- 日期：2026-02-03
- 做了什么：修复缺陷或回归问题，主题是“fix frontend rendering issue”。
- 影响范围：主要涉及 前端。
- 改动规模：+4 / -1 行。
- 关键文件：frontend/next.config.js；frontend/src/app/workspace/layout.tsx。

#### 81. fix: 修复用户消息中上传文件的右对齐显示
- 提交：[`3b411fe`](https://github.com/bytedance/deer-flow/commit/3b411fe499c08ba530c377249095e301a8ae24b4)
- 日期：2026-02-03
- 做了什么：修复缺陷或回归问题，主题是“修复用户消息中上传文件的右对齐显示”。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -1 行。
- 关键文件：frontend/src/components/workspace/messages/message-list-item.tsx。

#### 82. fix: 修复用户消息中上传文件的右对齐显示
- 提交：[`1fac83e`](https://github.com/bytedance/deer-flow/commit/1fac83eafaad272eb9cc94720255a1949ed4683f)
- 日期：2026-02-03
- 做了什么：修复缺陷或回归问题，主题是“修复用户消息中上传文件的右对齐显示”。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -1 行。
- 关键文件：frontend/src/components/workspace/messages/message-list-item.tsx。

#### 83. fix: 修复用户消息中上传文件的右对齐显示
- 提交：[`9017721`](https://github.com/bytedance/deer-flow/commit/901772136eeda86b2356077a17faa5d4e57f0f43)
- 日期：2026-02-03
- 做了什么：修复缺陷或回归问题，主题是“修复用户消息中上传文件的右对齐显示”。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -1 行。
- 关键文件：frontend/src/components/workspace/messages/message-list-item.tsx。

#### 84. fix: add file mtime-based cache invalidation for memory data
- 提交：[`2c32e8a`](https://github.com/bytedance/deer-flow/commit/2c32e8a461ebbdc6b4de2c3bf3efb70a54fe4adb)
- 日期：2026-02-03
- 做了什么：修复缺陷或回归问题，主题是“add file mtime-based cache invalidation for memory data”。
- 影响范围：主要涉及 后端。
- 改动规模：+38 / -8 行。
- 关键文件：backend/src/agents/memory/updater.py。

#### 85. fix: add file mtime-based cache invalidation for memory data
- 提交：[`9e15e60`](https://github.com/bytedance/deer-flow/commit/9e15e609ec7918a7533a9687d1de2473d2167070)
- 日期：2026-02-03
- 做了什么：修复缺陷或回归问题，主题是“add file mtime-based cache invalidation for memory data”。
- 影响范围：主要涉及 后端。
- 改动规模：+38 / -8 行。
- 关键文件：backend/src/agents/memory/updater.py。

#### 86. fix: add file mtime-based cache invalidation for memory data
- 提交：[`5682f7b`](https://github.com/bytedance/deer-flow/commit/5682f7b67d5ffb5c47cbbb47240a851666e911ca)
- 日期：2026-02-03
- 做了什么：修复缺陷或回归问题，主题是“add file mtime-based cache invalidation for memory data”。
- 影响范围：主要涉及 后端。
- 改动规模：+38 / -8 行。
- 关键文件：backend/src/agents/memory/updater.py。

#### 87. Fix a11y: add accessible name for icon button (#844)
- 提交：[`fab1d39`](https://github.com/bytedance/deer-flow/commit/fab1d39323ec77179d77e1358c9e54b11ae77927)
- 日期：2026-02-02
- 做了什么：修复缺陷或回归问题，主题是“Fix a11y: add accessible name for icon button (#844)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+13 / -2 行。
- 关键文件：web/src/app/landing/components/multi-agent-visualization.tsx。

#### 88. fix(node):deal with the plan_data content with multipmodal message (#846)
- 提交：[`e3e7a83`](https://github.com/bytedance/deer-flow/commit/e3e7a83f40ac852e6b5befc93466d2d4b0cf3821)
- 日期：2026-02-02
- 做了什么：修复缺陷或回归问题，主题是“deal with the plan_data content with multipmodal message (#846)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+177 / -1 行。
- 关键文件：src/graph/nodes.py；tests/integration/test_nodes.py。

#### 89. fix: fix position
- 提交：[`e847158`](https://github.com/bytedance/deer-flow/commit/e84715831f8efb548d08a9a5e994d95cda303821)
- 日期：2026-02-02
- 做了什么：修复缺陷或回归问题，主题是“fix position”。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -1 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx。

#### 90. fix: fix position
- 提交：[`03f84f2`](https://github.com/bytedance/deer-flow/commit/03f84f2b76e87fc93b88ab5f65537d5acb9e2051)
- 日期：2026-02-02
- 做了什么：修复缺陷或回归问题，主题是“fix position”。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -1 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx。

#### 91. fix: fix position
- 提交：[`268b7f9`](https://github.com/bytedance/deer-flow/commit/268b7f911c4742c88f77fedc0797c88a2a6b4e10)
- 日期：2026-02-02
- 做了什么：修复缺陷或回归问题，主题是“fix position”。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -1 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx。

#### 92. fix: set default state for todo list collapse to true
- 提交：[`018241c`](https://github.com/bytedance/deer-flow/commit/018241c2034e2dafea7c7c5a4b61f68bb969c293)
- 日期：2026-02-02
- 做了什么：修复缺陷或回归问题，主题是“set default state for todo list collapse to true”。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -1 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx。

#### 93. fix: set default state for todo list collapse to true
- 提交：[`35c5b6b`](https://github.com/bytedance/deer-flow/commit/35c5b6ba6b1cca3829af7b431f5443b4a0646652)
- 日期：2026-02-02
- 做了什么：修复缺陷或回归问题，主题是“set default state for todo list collapse to true”。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -1 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx。

#### 94. fix: set default state for todo list collapse to true
- 提交：[`8bc9d1b`](https://github.com/bytedance/deer-flow/commit/8bc9d1b2262d3d938f1c3135921c0b4bc1f81e5b)
- 日期：2026-02-02
- 做了什么：修复缺陷或回归问题，主题是“set default state for todo list collapse to true”。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -1 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx。

#### 95. fix: set default state for todo list collapse to false
- 提交：[`6f6d799`](https://github.com/bytedance/deer-flow/commit/6f6d799051324b34407ac580aee1ed2951a14776)
- 日期：2026-02-02
- 做了什么：修复缺陷或回归问题，主题是“set default state for todo list collapse to false”。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -3 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx。

#### 96. fix: set default state for todo list collapse to false
- 提交：[`a745b82`](https://github.com/bytedance/deer-flow/commit/a745b824d5f4ebda7cfba87f510b1423e8a5faeb)
- 日期：2026-02-02
- 做了什么：修复缺陷或回归问题，主题是“set default state for todo list collapse to false”。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -3 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx。

#### 97. fix: set default state for todo list collapse to false
- 提交：[`e01127e`](https://github.com/bytedance/deer-flow/commit/e01127eec94b68f18aeb92d99fe6b2934cb7bd40)
- 日期：2026-02-02
- 做了什么：修复缺陷或回归问题，主题是“set default state for todo list collapse to false”。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -3 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/page.tsx。

#### 98. fix: update TooltipContent component to handle sideOffset correctly and add shadow styling
- 提交：[`a66f76f`](https://github.com/bytedance/deer-flow/commit/a66f76f43d54f19d24d4eba8f3fb41e4a20a42cd)
- 日期：2026-02-02
- 做了什么：修复缺陷或回归问题，主题是“update TooltipContent component to handle sideOffset correctly and add shadow styling”。
- 影响范围：主要涉及 前端。
- 改动规模：+3 / -3 行。
- 关键文件：frontend/src/components/ui/tooltip.tsx。

#### 99. fix: update TooltipContent component to handle sideOffset correctly and add shadow styling
- 提交：[`ccab249`](https://github.com/bytedance/deer-flow/commit/ccab24983e6ba88c471fd197053bf3eeae79cee9)
- 日期：2026-02-02
- 做了什么：修复缺陷或回归问题，主题是“update TooltipContent component to handle sideOffset correctly and add shadow styling”。
- 影响范围：主要涉及 前端。
- 改动规模：+3 / -3 行。
- 关键文件：frontend/src/components/ui/tooltip.tsx。

#### 100. fix: update TooltipContent component to handle sideOffset correctly and add shadow styling
- 提交：[`33e82a7`](https://github.com/bytedance/deer-flow/commit/33e82a7abee13e201806a03353eb24e756f91aff)
- 日期：2026-02-02
- 做了什么：修复缺陷或回归问题，主题是“update TooltipContent component to handle sideOffset correctly and add shadow styling”。
- 影响范围：主要涉及 前端。
- 改动规模：+3 / -3 行。
- 关键文件：frontend/src/components/ui/tooltip.tsx。

## 2026-03

- 提交数：119 条

#### 1. fix(sandbox): serialize concurrent exec_command calls in AioSandbox (#1435)
- 提交：[`a3bfea6`](https://github.com/bytedance/deer-flow/commit/a3bfea631c2af0a3ef65e22abf0ed37bdca8123b)
- 日期：2026-03-31
- 做了什么：修复缺陷或回归问题，主题是“serialize concurrent exec_command calls in AioSandbox (#1435)”。
- 影响范围：主要涉及 后端。
- 改动规模：+173 / -18 行。
- 关键文件：backend/packages/harness/deerflow/community/aio_sandbox/aio_sandbox.py；backend/tests/test_aio_sandbox.py。

#### 2. fix: surface configured sandbox mounts to agents (#1638)
- 提交：[`aae59a8`](https://github.com/bytedance/deer-flow/commit/aae59a8ba894c74ee455891cd692f257baafdf8f)
- 日期：2026-03-31
- 做了什么：修复缺陷或回归问题，主题是“surface configured sandbox mounts to agents (#1638)”。
- 影响范围：主要涉及 后端、配置。
- 改动规模：+93 / -2 行。
- 关键文件：backend/docs/CONFIGURATION.md；backend/packages/harness/deerflow/agents/lead_agent/prompt.py；backend/packages/harness/deerflow/runtime/runs/manager.py；backend/packages/harness/deerflow/subagents/builtins/bash_agent.py；backend/packages/harness/deerflow/subagents/builtins/general_purpose.py；backend/tests/test_lead_agent_prompt.py；backend/tests/test_run_manager.py；config.example.yaml。

#### 3. fix Windows Docker sandbox path mounting (#1634)
- 提交：[`3ff1542`](https://github.com/bytedance/deer-flow/commit/3ff15423d651e98cc99791a85e3a20607ee2c75e)
- 日期：2026-03-31
- 做了什么：修复缺陷或回归问题，主题是“fix Windows Docker sandbox path mounting (#1634)”。
- 影响范围：主要涉及 后端、容器部署。
- 改动规模：+158 / -27 行。
- 关键文件：backend/packages/harness/deerflow/community/aio_sandbox/aio_sandbox_provider.py；backend/packages/harness/deerflow/config/paths.py；backend/packages/harness/deerflow/runtime/runs/manager.py；backend/tests/test_aio_sandbox_provider.py；backend/tests/test_docker_sandbox_mode_detection.py；docker/provisioner/app.py。

#### 4. fix(tools): move sandbox.tools import in view_image_tool to break circular import (#1674)
- 提交：[`c2f7be3`](https://github.com/bytedance/deer-flow/commit/c2f7be37b3104d3248b3203fc7d0fd920d128346)
- 日期：2026-03-31
- 做了什么：修复缺陷或回归问题，主题是“move sandbox.tools import in view_image_tool to break circular import (#1674)”。
- 影响范围：主要涉及 后端。
- 改动规模：+2 / -1 行。
- 关键文件：backend/packages/harness/deerflow/tools/builtins/view_image_tool.py。

#### 5. fix: improve Windows compatibility in dependency check (#1550)
- 提交：[`09a9209`](https://github.com/bytedance/deer-flow/commit/09a9209724c54edc09168fa6a1af563f7c3cf534)
- 日期：2026-03-31
- 做了什么：修复缺陷或回归问题，主题是“improve Windows compatibility in dependency check (#1550)”。
- 影响范围：主要涉及 脚本工具。
- 改动规模：+15 / -2 行。
- 关键文件：scripts/check.py。

#### 6. fix(frontend): improve network error message for agent name check  (#1605)
- 提交：[`b356a13`](https://github.com/bytedance/deer-flow/commit/b356a13da572848e8e31c74b7060510282c61299)
- 日期：2026-03-31
- 做了什么：修复缺陷或回归问题，主题是“improve network error message for agent name check  (#1605)”。
- 影响范围：主要涉及 前端。
- 改动规模：+10 / -11 行。
- 关键文件：frontend/src/app/workspace/agents/new/page.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts；frontend/src/core/i18n/locales/zh-CN.ts。

#### 7. fix(langgraph): correct config.yaml mount path in docker-compose (#1679)
- 提交：[`ac9a6ee`](https://github.com/bytedance/deer-flow/commit/ac9a6ee6a25da477f00a287a01922678fa405776)
- 日期：2026-03-31
- 做了什么：修复缺陷或回归问题，主题是“correct config.yaml mount path in docker-compose (#1679)”。
- 影响范围：主要涉及 容器部署。
- 改动规模：+4 / -4 行。
- 关键文件：docker/docker-compose.yaml。

#### 8. fix: remove LANGSMITH_TRACING override that ignores .env value (#1640)
- 提交：[`64e0f53`](https://github.com/bytedance/deer-flow/commit/64e0f5329a2a5f17a9b6cb13c6b6b116ecbbe24f)
- 日期：2026-03-31
- 做了什么：修复缺陷或回归问题，主题是“remove LANGSMITH_TRACING override that ignores .env value (#1640)”。
- 影响范围：主要涉及 容器部署。
- 改动规模：+1 / -3 行。
- 关键文件：docker/docker-compose.yaml。

#### 9. fix(frontend): route agent checks to gateway (#1572)
- 提交：[`9e3d484`](https://github.com/bytedance/deer-flow/commit/9e3d4848589f4dd266aeed82a9056ccac689c69c)
- 日期：2026-03-30
- 做了什么：修复缺陷或回归问题，主题是“route agent checks to gateway (#1572)”。
- 影响范围：主要涉及 前端、容器部署。
- 改动规模：+97 / -9 行。
- 关键文件：docker/docker-compose-dev.yaml；docker/docker-compose.yaml；frontend/next.config.js；frontend/src/app/workspace/agents/new/page.tsx；frontend/src/core/agents/api.ts；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/zh-CN.ts。

#### 10. fix: run uv sync before dev services to keep venv up-to-date (#1626)
- 提交：[`b21792d`](https://github.com/bytedance/deer-flow/commit/b21792d9bec26e32af70596ba10b49bb4b9784ec)
- 日期：2026-03-30
- 做了什么：修复缺陷或回归问题，主题是“run uv sync before dev services to keep venv up-to-date (#1626)”。
- 影响范围：主要涉及 容器部署。
- 改动规模：+2 / -2 行。
- 关键文件：docker/docker-compose-dev.yaml。

#### 11. fix: add --n-jobs-per-worker 10 to langgraph dev command in Docker (#1623)
- 提交：[`0f1b023`](https://github.com/bytedance/deer-flow/commit/0f1b023a2af71ab4ff25c3f5696c6beef016be4c)
- 日期：2026-03-30
- 做了什么：修复缺陷或回归问题，主题是“add --n-jobs-per-worker 10 to langgraph dev command in Docker (#1623)”。
- 影响范围：主要涉及 容器部署。
- 改动规模：+2 / -2 行。
- 关键文件：docker/docker-compose-dev.yaml；docker/docker-compose.yaml。

#### 12. fix(config): update SSR fallback in getBaseOrigin function (#1617)
- 提交：[`2330c38`](https://github.com/bytedance/deer-flow/commit/2330c382095182b3cb487a04c68ca2bfde75520e)
- 日期：2026-03-30
- 做了什么：修复缺陷或回归问题，主题是“update SSR fallback in getBaseOrigin function (#1617)”。
- 影响范围：主要涉及 前端。
- 改动规模：+2 / -1 行。
- 关键文件：frontend/src/core/config/index.ts。

#### 13. fix: promote deferred tools after tool_search returns schema (#1570)
- 提交：[`9bcdba6`](https://github.com/bytedance/deer-flow/commit/9bcdba6038425545a31cde800ae7bcd1dfd64efe)
- 日期：2026-03-30
- 做了什么：修复缺陷或回归问题，主题是“promote deferred tools after tool_search returns schema (#1570)”。
- 影响范围：主要涉及 后端。
- 改动规模：+137 / -1 行。
- 关键文件：backend/packages/harness/deerflow/tools/builtins/tool_search.py；backend/tests/test_tool_search.py。

#### 14. fix(config): correct MiniMax M2.7 highspeed model name and add thinking support (#1596)
- 提交：[`ef58bb8`](https://github.com/bytedance/deer-flow/commit/ef58bb8d3cb313de5002d3874f7f863bbe949693)
- 日期：2026-03-30
- 做了什么：修复缺陷或回归问题，主题是“correct MiniMax M2.7 highspeed model name and add thinking support (#1596)”。
- 影响范围：主要涉及 配置。
- 改动规模：+7 / -3 行。
- 关键文件：config.example.yaml。

#### 15. fix(dev): exclude sandbox dirs from gateway hot-reload watcher (#1519)
- 提交：[`c5034c0`](https://github.com/bytedance/deer-flow/commit/c5034c03c7802c289678d0c0b1763f370a2268ee)
- 日期：2026-03-30
- 做了什么：修复缺陷或回归问题，主题是“exclude sandbox dirs from gateway hot-reload watcher (#1519)”。
- 影响范围：主要涉及 脚本工具。
- 改动规模：+1 / -1 行。
- 关键文件：scripts/serve.sh。

#### 16. fix(oauth): Harden Claude OAuth cache-control handling (#1583)
- 提交：[`5ceb19f`](https://github.com/bytedance/deer-flow/commit/5ceb19f6f650c397569177fda5e5129768364f71)
- 日期：2026-03-29
- 做了什么：修复缺陷或回归问题，主题是“Harden Claude OAuth cache-control handling (#1583)”。
- 影响范围：主要涉及 后端。
- 改动规模：+80 / -2 行。
- 关键文件：backend/packages/harness/deerflow/models/claude_provider.py；backend/tests/test_claude_provider_oauth_billing.py。

#### 17. fix(sandbox): anchor relative paths to thread workspace in local mode (#1522)
- 提交：[`cdb2a3a`](https://github.com/bytedance/deer-flow/commit/cdb2a3a017f61a0cbb61def39a3949ee1bd9defe)
- 日期：2026-03-29
- 做了什么：修复缺陷或回归问题，主题是“anchor relative paths to thread workspace in local mode (#1522)”。
- 影响范围：主要涉及 后端。
- 改动规模：+47 / -0 行。
- 关键文件：backend/packages/harness/deerflow/sandbox/tools.py；backend/tests/test_sandbox_tools_security.py。

#### 18. fix(frontend): prevent submit during IME composition (#1562)
- 提交：[`866cf4e`](https://github.com/bytedance/deer-flow/commit/866cf4ef7338ab217b7421ae6035f338e4676346)
- 日期：2026-03-29
- 做了什么：修复缺陷或回归问题，主题是“prevent submit during IME composition (#1562)”。
- 影响范围：主要涉及 前端。
- 改动规模：+17 / -3 行。
- 关键文件：frontend/src/app/workspace/agents/new/page.tsx；frontend/src/components/ai-elements/prompt-input.tsx；frontend/src/components/workspace/recent-chat-list.tsx；frontend/src/lib/ime.ts。

#### 19. docs: fix some broken links (#1567)
- 提交：[`d475de7`](https://github.com/bytedance/deer-flow/commit/d475de799793a86d3737d7d0c387c4b72f02f165)
- 日期：2026-03-29
- 做了什么：修复缺陷或回归问题，主题是“fix some broken links (#1567)”。
- 影响范围：主要涉及 后端、前端。
- 改动规模：+6 / -6 行。
- 关键文件：backend/docs/AUTO_TITLE_GENERATION.md；backend/docs/CONFIGURATION.md；backend/docs/TITLE_GENERATION_IMPLEMENTATION.md；frontend/public/demo/threads/7f9dc56c-e49c-4671-a3d2-c492ff4dce0c/user-data/outputs/leica-master-photography-article.md。

#### 20. fix(nginx): re-resolve upstream DNS in Docker (#1517)
- 提交：[`75c4757`](https://github.com/bytedance/deer-flow/commit/75c4757f48409cd26edc805dcba7a0f008060233)
- 日期：2026-03-29
- 做了什么：修复缺陷或回归问题，主题是“re-resolve upstream DNS in Docker (#1517)”。
- 影响范围：主要涉及 容器部署。
- 改动规模：+8 / -3 行。
- 关键文件：docker/nginx/nginx.conf。

#### 21. fix: use Git Bash for Windows local startup (#1551)
- 提交：[`580920e`](https://github.com/bytedance/deer-flow/commit/580920ef63929ad60bea835bf043483f314db0dc)
- 日期：2026-03-29
- 做了什么：修复缺陷或回归问题，主题是“use Git Bash for Windows local startup (#1551)”。
- 影响范围：主要涉及 其他模块、脚本工具。
- 改动规模：+22 / -4 行。
- 关键文件：Makefile；scripts/run-with-git-bash.cmd。

#### 22. fix: add Windows shell fallback for local sandbox (#1505)
- 提交：[`68c9e09`](https://github.com/bytedance/deer-flow/commit/68c9e09a7aeaff10cbe1778a32c000e3abbdf1c5)
- 日期：2026-03-29
- 做了什么：修复缺陷或回归问题，主题是“add Windows shell fallback for local sandbox (#1505)”。
- 影响范围：主要涉及 后端。
- 改动规模：+209 / -20 行。
- 关键文件：backend/packages/harness/deerflow/sandbox/local/local_sandbox.py；backend/tests/test_local_sandbox_encoding.py。

#### 23. fix(docs): Correct security usage recommendations in README_zh.md (#1548)
- 提交：[`8b6c333`](https://github.com/bytedance/deer-flow/commit/8b6c333afc26d7b4dce5a624b5085a7f49c72103)
- 日期：2026-03-29
- 做了什么：修复缺陷或回归问题，主题是“Correct security usage recommendations in README_zh.md (#1548)”。
- 影响范围：主要涉及 文档。
- 改动规模：+1 / -1 行。
- 关键文件：README_zh.md。

#### 24. fix(sandbox): fall back to config.configurable for thread_id in lazy sandbox init (#1529)
- 提交：[`118485a`](https://github.com/bytedance/deer-flow/commit/118485a7cb0242623937600200957247b5383a87)
- 日期：2026-03-29
- 做了什么：修复缺陷或回归问题，主题是“fall back to config.configurable for thread_id in lazy sandbox init (#1529)”。
- 影响范围：主要涉及 后端。
- 改动规模：+2 / -0 行。
- 关键文件：backend/packages/harness/deerflow/sandbox/tools.py。

#### 25. fix(sandbox): allow MCP filesystem server paths in local bash commands (#1527)
- 提交：[`9e5ba74`](https://github.com/bytedance/deer-flow/commit/9e5ba74ecd88a2fccfd80c2ba75ca91bf6008e47)
- 日期：2026-03-29
- 做了什么：修复缺陷或回归问题，主题是“allow MCP filesystem server paths in local bash commands (#1527)”。
- 影响范围：主要涉及 后端。
- 改动规模：+72 / -0 行。
- 关键文件：backend/packages/harness/deerflow/sandbox/tools.py；backend/tests/test_sandbox_tools_security.py。

#### 26. fix(channel): reject concurrent same-thread runs (#1465) (#1475)
- 提交：[`89183ae`](https://github.com/bytedance/deer-flow/commit/89183ae76a6cac22567c006b10ab8e0f5003371c)
- 日期：2026-03-29
- 做了什么：修复缺陷或回归问题，主题是“reject concurrent same-thread runs (#1465) (#1475)”。
- 影响范围：主要涉及 后端。
- 改动规模：+74 / -2 行。
- 关键文件：backend/app/channels/manager.py；backend/tests/test_channels.py。

#### 27. fix(middleware): fall back to configurable thread_id in MemoryMiddleware (#1425) (#1426)
- 提交：[`520c035`](https://github.com/bytedance/deer-flow/commit/520c0352b55034f4b061e3b866f20ff77d341d8a)
- 日期：2026-03-28
- 做了什么：修复缺陷或回归问题，主题是“fall back to configurable thread_id in MemoryMiddleware (#1425) (#1426)”。
- 影响范围：主要涉及 后端。
- 改动规模：+5 / -1 行。
- 关键文件：backend/packages/harness/deerflow/agents/middlewares/memory_middleware.py。

#### 28. fix(task_tool): fallback to configurable thread_id when context is mi… (#1343)
- 提交：[`690d80f`](https://github.com/bytedance/deer-flow/commit/690d80f46f09c615fc9500b959cec8f9181360f9)
- 日期：2026-03-28
- 做了什么：修复缺陷或回归问题，主题是“fallback to configurable thread_id when context is mi… (#1343)”。
- 影响范围：主要涉及 后端。
- 改动规模：+2 / -0 行。
- 关键文件：backend/packages/harness/deerflow/tools/builtins/task_tool.py。

#### 29. Fix IM channel backend URLs in Docker (#1497)
- 提交：[`c2dd893`](https://github.com/bytedance/deer-flow/commit/c2dd8937ed4dc4bb3888d3b61ac9f139421c4fa3)
- 日期：2026-03-28
- 做了什么：修复缺陷或回归问题，主题是“Fix IM channel backend URLs in Docker (#1497)”。
- 影响范围：主要涉及 后端、容器部署、文档。
- 改动规模：+58 / -3 行。
- 关键文件：README.md；backend/CLAUDE.md；backend/app/channels/service.py；backend/tests/test_channels.py；config.example.yaml；docker/docker-compose-dev.yaml；docker/docker-compose.yaml。

#### 30. fix(frontend): separate mock and default LangGraph clients (#1504)
- 提交：[`9caea02`](https://github.com/bytedance/deer-flow/commit/9caea0266e3640179ef279b4a7367761fd6a442a)
- 日期：2026-03-28
- 做了什么：修复缺陷或回归问题，主题是“separate mock and default LangGraph clients (#1504)”。
- 影响范围：主要涉及 前端。
- 改动规模：+10 / -3 行。
- 关键文件：frontend/src/core/api/api-client.ts。

#### 31. fix: prevent SpeechRecognition instance leaks on render (#1369)
- 提交：[`49f2e38`](https://github.com/bytedance/deer-flow/commit/49f2e38fbf6ceed1a617c6c8eca99133baaa7cc0)
- 日期：2026-03-28
- 做了什么：修复缺陷或回归问题，主题是“prevent SpeechRecognition instance leaks on render (#1369)”。
- 影响范围：主要涉及 前端。
- 改动规模：+9 / -4 行。
- 关键文件：frontend/src/components/ai-elements/prompt-input.tsx。

#### 32. fix: refactor to use getBaseOrigin for URL construction in backend and LangGraph base URL functions (#1494)
- 提交：[`d22cab8`](https://github.com/bytedance/deer-flow/commit/d22cab8614352d54b33b94c0b3d476f304b873cf)
- 日期：2026-03-28
- 做了什么：修复缺陷或回归问题，主题是“refactor to use getBaseOrigin for URL construction in backend and LangGraph base URL functions (#1494)”。
- 影响范围：主要涉及 前端。
- 改动规模：+10 / -2 行。
- 关键文件：frontend/src/core/config/index.ts。

#### 33. fix(oauth): inject billing header for Claude oAuth Models (#1442)
- 提交：[`43ef369`](https://github.com/bytedance/deer-flow/commit/43ef3691a5ce98a574a8fc073bec886bdb94c2d6)
- 日期：2026-03-28
- 做了什么：修复缺陷或回归问题，主题是“inject billing header for Claude oAuth Models (#1442)”。
- 影响范围：主要涉及 后端。
- 改动规模：+167 / -1 行。
- 关键文件：backend/packages/harness/deerflow/models/claude_provider.py；backend/tests/test_claude_provider_oauth_billing.py。

#### 34. fix: replace print() with logging across harness package (#1282)
- 提交：[`03b144f`](https://github.com/bytedance/deer-flow/commit/03b144f9c900c90de250d4ef80b6eb829d8a8618)
- 日期：2026-03-27
- 做了什么：修复缺陷或回归问题，主题是“replace print() with logging across harness package (#1282)”。
- 影响范围：主要涉及 后端。
- 改动规模：+40 / -16 行。
- 关键文件：backend/packages/harness/deerflow/agents/lead_agent/prompt.py；backend/packages/harness/deerflow/agents/memory/queue.py；backend/packages/harness/deerflow/agents/middlewares/clarification_middleware.py；backend/packages/harness/deerflow/agents/middlewares/memory_middleware.py；backend/packages/harness/deerflow/agents/middlewares/thread_data_middleware.py；backend/packages/harness/deerflow/agents/middlewares/view_image_middleware.py；backend/packages/harness/deerflow/skills/loader.py；backend/packages/harness/deerflow/skills/parser.py。

#### 35. docs(SETUP): correct setup documentation links (#1478)
- 提交：[`18b0794`](https://github.com/bytedance/deer-flow/commit/18b07941253caa1a14bde0efb0a40bbbec322e3a)
- 日期：2026-03-27
- 做了什么：修复缺陷或回归问题，主题是“correct setup documentation links (#1478)”。
- 影响范围：主要涉及 后端。
- 改动规模：+2 / -2 行。
- 关键文件：backend/docs/SETUP.md。

#### 36. fix(sandbox): Relax upload permissions for aio sandbox sync (#1409)
- 提交：[`40a4acb`](https://github.com/bytedance/deer-flow/commit/40a4acbbeda09530060509c6d7002ef17b7e2444)
- 日期：2026-03-27
- 做了什么：修复缺陷或回归问题，主题是“Relax upload permissions for aio sandbox sync (#1409)”。
- 影响范围：主要涉及 后端。
- 改动规模：+104 / -0 行。
- 关键文件：backend/app/gateway/routers/uploads.py；backend/tests/test_uploads_router.py。

#### 37. fix(middleware): return proper content format when no images viewed (#1454)
- 提交：[`4708700`](https://github.com/bytedance/deer-flow/commit/47087007238bdc6ca88f801613e3279318dde732)
- 日期：2026-03-27
- 做了什么：修复缺陷或回归问题，主题是“return proper content format when no images viewed (#1454)”。
- 影响范围：主要涉及 后端。
- 改动规模：+2 / -1 行。
- 关键文件：backend/packages/harness/deerflow/agents/middlewares/view_image_middleware.py。

#### 38. fix(task): avoid blocking in task tool polling (#1320)
- 提交：[`43a19f9`](https://github.com/bytedance/deer-flow/commit/43a19f96274ea30211a48a520a4c93ffc4aa3037)
- 日期：2026-03-27
- 做了什么：修复缺陷或回归问题，主题是“avoid blocking in task tool polling (#1320)”。
- 影响范围：主要涉及 后端。
- 改动规模：+248 / -83 行。
- 关键文件：backend/packages/harness/deerflow/tools/builtins/task_tool.py；backend/tests/test_task_tool_core_logic.py。

#### 39. fix(config): add Docker service name guidance for channel URLs (#1437)
- 提交：[`9996505`](https://github.com/bytedance/deer-flow/commit/99965057c1fcd1ae7238edebf1a18ad7baad3fdd)
- 日期：2026-03-26
- 做了什么：修复缺陷或回归问题，主题是“add Docker service name guidance for channel URLs (#1437)”。
- 影响范围：主要涉及 配置。
- 改动规模：+3 / -0 行。
- 关键文件：config.example.yaml。

#### 40. fix: add build-arg support for proxies and mirrors in Docker builds (#1346)
- 提交：[`8ae0235`](https://github.com/bytedance/deer-flow/commit/8ae023574eb816e2b3b5355b88d794e3fa0c4790)
- 日期：2026-03-27
- 做了什么：修复缺陷或回归问题，主题是“add build-arg support for proxies and mirrors in Docker builds (#1346)”。
- 影响范围：主要涉及 容器部署、后端、前端。
- 改动规模：+59 / -7 行。
- 关键文件：backend/Dockerfile；docker/docker-compose-dev.yaml；docker/docker-compose.yaml；docker/provisioner/Dockerfile；frontend/Dockerfile。

#### 41. fix: remove unused radix Icon import from suggestion (#1368)
- 提交：[`d7bdb1a`](https://github.com/bytedance/deer-flow/commit/d7bdb1a4b93f5da3f171f8006ff75e90c707dc65)
- 日期：2026-03-26
- 做了什么：修复缺陷或回归问题，主题是“remove unused radix Icon import from suggestion (#1368)”。
- 影响范围：主要涉及 前端。
- 改动规模：+0 / -1 行。
- 关键文件：frontend/src/components/ai-elements/suggestion.tsx。

#### 42. fix(gateway): enforce safe download for active artifact MIME types to mitigate stored XSS (#1389)
- 提交：[`0d3cefa`](https://github.com/bytedance/deer-flow/commit/0d3cefaa5a57f9c0bbaeabd2c391d474b33a6757)
- 日期：2026-03-26
- 做了什么：修复缺陷或回归问题，主题是“enforce safe download for active artifact MIME types to mitigate stored XSS (#1389)”。
- 影响范围：主要涉及 后端、文档。
- 改动规模：+119 / -18 行。
- 关键文件：README.md；backend/CLAUDE.md；backend/app/gateway/routers/artifacts.py；backend/tests/test_artifacts_router.py。

#### 43. Fix Windows backend test compatibility (#1384)
- 提交：[`b9583f7`](https://github.com/bytedance/deer-flow/commit/b9583f7204b1cc9cc4f5dd57ebd3882f2a19b463)
- 日期：2026-03-26
- 做了什么：修复缺陷或回归问题，主题是“Fix Windows backend test compatibility (#1384)”。
- 影响范围：主要涉及 后端。
- 改动规模：+141 / -27 行。
- 关键文件：backend/packages/harness/deerflow/community/aio_sandbox/aio_sandbox_provider.py；backend/packages/harness/deerflow/models/credential_loader.py；backend/packages/harness/deerflow/sandbox/tools.py；backend/packages/harness/deerflow/skills/installer.py；backend/tests/test_aio_sandbox_provider.py；backend/tests/test_client.py；backend/tests/test_docker_sandbox_mode_detection.py；backend/tests/test_skills_installer.py。

#### 44. fix(config): return full URLs for backend and LangGraph base URLs (#1392)
- 提交：[`4d1a69a`](https://github.com/bytedance/deer-flow/commit/4d1a69a9387de64a79a5b6641e929830d843c134)
- 日期：2026-03-26
- 做了什么：修复缺陷或回归问题，主题是“return full URLs for backend and LangGraph base URLs (#1392)”。
- 影响范围：主要涉及 前端。
- 改动规模：+8 / -2 行。
- 关键文件：frontend/src/core/config/index.ts。

#### 45. fix(LLM): fixing Gemini thinking + tool calls via OpenAI gateway (#1180) (#1205)
- 提交：[`a087fe7`](https://github.com/bytedance/deer-flow/commit/a087fe7bccd62a090480971dc1ba11c3581ba2d7)
- 日期：2026-03-26
- 做了什么：修复缺陷或回归问题，主题是“fixing Gemini thinking + tool calls via OpenAI gateway (#1180) (#1205)”。
- 影响范围：主要涉及 后端、配置。
- 改动规模：+360 / -1 行。
- 关键文件：backend/docs/CONFIGURATION.md；backend/packages/harness/deerflow/models/patched_openai.py；backend/tests/test_patched_openai.py；config.example.yaml。

#### 46. fix(config): fix summarization model alias resolution (#1378)
- 提交：[`080a03f`](https://github.com/bytedance/deer-flow/commit/080a03f3bc1472838ef9ad8ae2a59f79d74dcd33)
- 日期：2026-03-26
- 做了什么：修复缺陷或回归问题，主题是“fix summarization model alias resolution (#1378)”。
- 影响范围：主要涉及 后端。
- 改动规模：+28 / -1 行。
- 关键文件：backend/packages/harness/deerflow/agents/lead_agent/agent.py；backend/tests/test_lead_agent_model_resolution.py。

#### 47. fix: align config.example.yaml to use GEMINI_API_KEY (#1367)
- 提交：[`792c49e`](https://github.com/bytedance/deer-flow/commit/792c49e6af017d44fb344bb3cb900a1ee7d77ce5)
- 日期：2026-03-25
- 做了什么：修复缺陷或回归问题，主题是“align config.example.yaml to use GEMINI_API_KEY (#1367)”。
- 影响范围：主要涉及 配置。
- 改动规模：+1 / -1 行。
- 关键文件：config.example.yaml。

#### 48. Fix command syntax for container image pull (#1349)
- 提交：[`afe325d`](https://github.com/bytedance/deer-flow/commit/afe325d34e7d2eb7c5d28a541d4cf042eb83b3b9)
- 日期：2026-03-25
- 做了什么：修复缺陷或回归问题，主题是“Fix command syntax for container image pull (#1349)”。
- 影响范围：主要涉及 后端。
- 改动规模：+1 / -1 行。
- 关键文件：backend/docs/APPLE_CONTAINER.md。

#### 49. fix: add null checks for runtime.context and tighten langgraph constraint (#1326)
- 提交：[`d7e5107`](https://github.com/bytedance/deer-flow/commit/d7e510763d83d6ed0cd9be6485212005caace07a)
- 日期：2026-03-25
- 做了什么：修复缺陷或回归问题，主题是“add null checks for runtime.context and tighten langgraph constraint (#1326)”。
- 影响范围：主要涉及 后端。
- 改动规模：+6 / -4 行。
- 关键文件：backend/packages/harness/deerflow/agents/middlewares/uploads_middleware.py；backend/packages/harness/deerflow/sandbox/middleware.py；backend/packages/harness/pyproject.toml。

#### 50. fix(frontend): add stable ids for chat resizable panels (#1341)
- 提交：[`adc51e5`](https://github.com/bytedance/deer-flow/commit/adc51e541c36d9ce4181a4ab40602f155df56414)
- 日期：2026-03-25
- 做了什么：修复缺陷或回归问题，主题是“add stable ids for chat resizable panels (#1341)”。
- 影响范围：主要涉及 前端。
- 改动规模：+8 / -0 行。
- 关键文件：frontend/src/components/workspace/chats/chat-box.tsx。

#### 51. docs: fix typo and grammar issues in docs (#1315)
- 提交：[`97ad67d`](https://github.com/bytedance/deer-flow/commit/97ad67db6b93cc5623318286d69fdeacd6fff84d)
- 日期：2026-03-25
- 做了什么：修复缺陷或回归问题，主题是“fix typo and grammar issues in docs (#1315)”。
- 影响范围：主要涉及 其他模块、后端。
- 改动规模：+3 / -3 行。
- 关键文件：SECURITY.md；backend/AGENTS.md。

#### 52. fix: add null checks for runtime.context in middlewares and tools (#1269)
- 提交：[`2eca58b`](https://github.com/bytedance/deer-flow/commit/2eca58bd86e861b694647f224634a6680361b9b7)
- 日期：2026-03-25
- 做了什么：修复缺陷或回归问题，主题是“add null checks for runtime.context in middlewares and tools (#1269)”。
- 影响范围：主要涉及 后端、脚本工具。
- 改动规模：+15 / -8 行。
- 关键文件：backend/packages/harness/deerflow/agents/middlewares/loop_detection_middleware.py；backend/packages/harness/deerflow/agents/middlewares/memory_middleware.py；backend/packages/harness/deerflow/agents/middlewares/uploads_middleware.py；backend/packages/harness/deerflow/sandbox/middleware.py；backend/packages/harness/deerflow/sandbox/tools.py；backend/packages/harness/deerflow/tools/builtins/present_file_tool.py；backend/packages/harness/deerflow/tools/builtins/setup_agent_tool.py；backend/packages/harness/deerflow/tools/builtins/task_tool.py。

#### 53. fix(middleware): use HumanMessage in LoopDetectionMiddleware for Anthropic compat (#1300)
- 提交：[`77b8ef7`](https://github.com/bytedance/deer-flow/commit/77b8ef79cad6d77f2a445a980e636981deca9684)
- 日期：2026-03-25
- 做了什么：修复缺陷或回归问题，主题是“use HumanMessage in LoopDetectionMiddleware for Anthropic compat (#1300)”。
- 影响范围：主要涉及 后端。
- 改动规模：+10 / -5 行。
- 关键文件：backend/packages/harness/deerflow/agents/middlewares/loop_detection_middleware.py；backend/tests/test_loop_detection_middleware.py。

#### 54. fix: add Windows compatibility for make dev/start commands (#1297)
- 提交：[`067b19a`](https://github.com/bytedance/deer-flow/commit/067b19af00b9a5a7895cecf6073a571cd91fcf33)
- 日期：2026-03-24
- 做了什么：修复缺陷或回归问题，主题是“add Windows compatibility for make dev/start commands (#1297)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+16 / -0 行。
- 关键文件：Makefile。

#### 55. fix(mcp): implement sync invocation wrapper for async MCP tools (#1287)
- 提交：[`a9940c3`](https://github.com/bytedance/deer-flow/commit/a9940c391c684e01f3d4b5d508611f2d04764527)
- 日期：2026-03-24
- 做了什么：修复缺陷或回归问题，主题是“implement sync invocation wrapper for async MCP tools (#1287)”。
- 影响范围：主要涉及 后端。
- 改动规模：+128 / -0 行。
- 关键文件：backend/packages/harness/deerflow/mcp/tools.py；backend/tests/test_mcp_sync_wrapper.py。

#### 56. fix(skills): follow symlinks when scanning custom skills directory (#1292)
- 提交：[`6bf5267`](https://github.com/bytedance/deer-flow/commit/6bf526748d7bfb32ff4899521899aac2f3eec02c)
- 日期：2026-03-24
- 做了什么：修复缺陷或回归问题，主题是“follow symlinks when scanning custom skills directory (#1292)”。
- 影响范围：主要涉及 后端。
- 改动规模：+1 / -1 行。
- 关键文件：backend/packages/harness/deerflow/skills/loader.py。

#### 57. fix: use subprocess instead of os.system in analyze.py (#1289)
- 提交：[`14a3fa5`](https://github.com/bytedance/deer-flow/commit/14a3fa5290d501af371b335eafa46b5e9f75367e)
- 日期：2026-03-24
- 做了什么：修复缺陷或回归问题，主题是“use subprocess instead of os.system in analyze.py (#1289)”。
- 影响范围：主要涉及 脚本工具、技能体系。
- 改动规模：+4 / -3 行。
- 关键文件：scripts/check.py；skills/public/data-analysis/scripts/analyze.py。

#### 58. fix: repair frontend check command and docs (#1281)
- 提交：[`4b15f14`](https://github.com/bytedance/deer-flow/commit/4b15f1464745339fdede86ff17420397a1237d9f)
- 日期：2026-03-24
- 做了什么：修复缺陷或回归问题，主题是“repair frontend check command and docs (#1281)”。
- 影响范围：主要涉及 其他模块、文档、前端。
- 改动规模：+40 / -3 行。
- 关键文件：CONTRIBUTING.md；README.md；frontend/package.json。

#### 59. fix(frontend): fix the build error of i18n (#1274)
- 提交：[`48a1975`](https://github.com/bytedance/deer-flow/commit/48a197555ba36e915e5450a5f2afba7157b6db76)
- 日期：2026-03-24
- 做了什么：修复缺陷或回归问题，主题是“fix the build error of i18n (#1274)”。
- 影响范围：主要涉及 前端。
- 改动规模：+6 / -0 行。
- 关键文件：frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts；frontend/src/core/i18n/locales/zh-CN.ts。

#### 60. fix(frontend): filter task tool calls when rendering SubtaskCard (#1242)
- 提交：[`0431a67`](https://github.com/bytedance/deer-flow/commit/0431a67b689cbc53154e46add4612c20a4cabfcd)
- 日期：2026-03-24
- 做了什么：修复缺陷或回归问题，主题是“filter task tool calls when rendering SubtaskCard (#1242)”。
- 影响范围：主要涉及 前端。
- 改动规模：+3 / -3 行。
- 关键文件：frontend/src/components/workspace/messages/message-list.tsx。

#### 61. fix(threads): clean up local thread data after thread deletion (#1262)
- 提交：[`8b0f3fe`](https://github.com/bytedance/deer-flow/commit/8b0f3fe2334b717f230d7f5b4a1d43dd06eb2a37)
- 日期：2026-03-24
- 做了什么：修复缺陷或回归问题，主题是“clean up local thread data after thread deletion (#1262)”。
- 影响范围：主要涉及 后端、文档、前端。
- 改动规模：+240 / -9 行。
- 关键文件：README.md；backend/CLAUDE.md；backend/README.md；backend/app/gateway/app.py；backend/app/gateway/routers/__init__.py；backend/app/gateway/routers/threads.py；backend/docs/API.md；backend/docs/ARCHITECTURE.md。

#### 62. fix: add error handling for podcast generation failures (#1257)
- 提交：[`79acc39`](https://github.com/bytedance/deer-flow/commit/79acc3939a684ce7680a47461182a918b4c056de)
- 日期：2026-03-24
- 做了什么：修复缺陷或回归问题，主题是“add error handling for podcast generation failures (#1257)”。
- 影响范围：主要涉及 技能体系。
- 改动规模：+39 / -2 行。
- 关键文件：skills/public/podcast-generation/scripts/generate.py。

#### 63. fix(hotkey):support to open settings with hotkey (#1259)
- 提交：[`3be1d84`](https://github.com/bytedance/deer-flow/commit/3be1d841aa0713230c29c2edb2ab69ef724a27af)
- 日期：2026-03-23
- 做了什么：修复缺陷或回归问题，主题是“support to open settings with hotkey (#1259)”。
- 影响范围：主要涉及 前端。
- 改动规模：+6 / -2 行。
- 关键文件：frontend/src/components/workspace/command-palette.tsx。

#### 64. fix: add ~/.codex and ~/.claude bind mounts to docker-compose-dev.yaml (#1247)
- 提交：[`1c981ea`](https://github.com/bytedance/deer-flow/commit/1c981ead2ae633e8a28e30c056b327de19c1fb13)
- 日期：2026-03-23
- 做了什么：修复缺陷或回归问题，主题是“add ~/.codex and ~/.claude bind mounts to docker-compose-dev.yaml (#1247)”。
- 影响范围：主要涉及 容器部署。
- 改动规模：+26 / -0 行。
- 关键文件：docker/docker-compose-dev.yaml。

#### 65. fix(config): reload AppConfig when config path or mtime changes (#1239)
- 提交：[`644501a`](https://github.com/bytedance/deer-flow/commit/644501ae07cdfa3e6003fe42d3f3bd8c6e83434e)
- 日期：2026-03-22
- 做了什么：修复缺陷或回归问题，主题是“reload AppConfig when config path or mtime changes (#1239)”。
- 影响范围：主要涉及 后端、文档。
- 改动规模：+146 / -10 行。
- 关键文件：README.md；backend/CLAUDE.md；backend/packages/harness/deerflow/config/app_config.py；backend/tests/test_app_config_reload.py。

#### 66. fix(middleware): fallback to configurable thread_id in thread data middleware (#1237)
- 提交：[`e6c6770`](https://github.com/bytedance/deer-flow/commit/e6c6770b701262b49cf4019e60df7a720666f951)
- 日期：2026-03-22
- 做了什么：修复缺陷或回归问题，主题是“fallback to configurable thread_id in thread data middleware (#1237)”。
- 影响范围：主要涉及 后端。
- 改动规模：+62 / -2 行。
- 关键文件：backend/packages/harness/deerflow/agents/middlewares/thread_data_middleware.py；backend/tests/test_thread_data_middleware.py。

#### 67. fix(gateway): accept output_text suggestion blocks (#1238)
- 提交：[`894875a`](https://github.com/bytedance/deer-flow/commit/894875ab1b1c232698c0ad32ae565f4b3cbbe1d1)
- 日期：2026-03-22
- 做了什么：修复缺陷或回归问题，主题是“accept output_text suggestion blocks (#1238)”。
- 影响范围：主要涉及 后端。
- 改动规模：+19 / -1 行。
- 关键文件：backend/app/gateway/routers/suggestions.py；backend/tests/test_suggestions_router.py。

#### 68. fix(telegram): fix reply ordering race condition (#1231)
- 提交：[`7a90055`](https://github.com/bytedance/deer-flow/commit/7a90055edeca554171ac4f5e0d045f09b630bd7d)
- 日期：2026-03-22
- 做了什么：修复缺陷或回归问题，主题是“fix reply ordering race condition (#1231)”。
- 影响范围：主要涉及 后端。
- 改动规模：+53 / -7 行。
- 关键文件：backend/app/channels/telegram.py；backend/tests/test_channels.py。

#### 69. fix: normalize structured LLM content in serialization and memory updater (#1215)
- 提交：[`3af7090`](https://github.com/bytedance/deer-flow/commit/3af709097eb77e7518d4d951b4a51802b70f895f)
- 日期：2026-03-22
- 做了什么：修复缺陷或回归问题，主题是“normalize structured LLM content in serialization and memory updater (#1215)”。
- 影响范围：主要涉及 后端。
- 改动规模：+420 / -30 行。
- 关键文件：backend/packages/harness/deerflow/agents/checkpointer/provider.py；backend/packages/harness/deerflow/agents/memory/prompt.py；backend/packages/harness/deerflow/agents/memory/updater.py；backend/packages/harness/deerflow/client.py；backend/packages/harness/deerflow/subagents/executor.py；backend/tests/test_checkpointer.py；backend/tests/test_memory_updater.py；backend/tests/test_serialize_message_content.py。

#### 70. fix: improve MiniMax code plan integration (#1169)
- 提交：[`ceab7fa`](https://github.com/bytedance/deer-flow/commit/ceab7fac14c3a8067670b85623697d4a42bd5fc1)
- 日期：2026-03-20
- 做了什么：修复缺陷或回归问题，主题是“improve MiniMax code plan integration (#1169)”。
- 影响范围：主要涉及 前端、后端。
- 改动规模：+491 / -22 行。
- 关键文件：backend/app/gateway/routers/models.py；backend/packages/harness/deerflow/client.py；backend/packages/harness/deerflow/models/patched_minimax.py；backend/tests/test_client.py；backend/tests/test_patched_minimax.py；frontend/src/app/layout.tsx；frontend/src/app/mock/api/models/route.ts；frontend/src/app/workspace/agents/[agent_name]/chats/[thread_id]/page.tsx。

#### 71. fix(feishu): support @bot message in topic groups (#1206)
- 提交：[`3b235fd`](https://github.com/bytedance/deer-flow/commit/3b235fd182684c806e93882909ac184db5ac4329)
- 日期：2026-03-20
- 做了什么：修复缺陷或回归问题，主题是“support @bot message in topic groups (#1206)”。
- 影响范围：主要涉及 后端。
- 改动规模：+108 / -1 行。
- 关键文件：backend/app/channels/feishu.py；backend/tests/test_feishu_parser.py。

#### 72. fix: add sync after_model to TitleMiddleware (#1190)
- 提交：[`accf5b5`](https://github.com/bytedance/deer-flow/commit/accf5b5f8ec0049eaf828cbeff80a03fee9b3f78)
- 日期：2026-03-19
- 做了什么：修复缺陷或回归问题，主题是“add sync after_model to TitleMiddleware (#1190)”。
- 影响范围：主要涉及 后端。
- 改动规模：+120 / -35 行。
- 关键文件：backend/packages/harness/deerflow/agents/middlewares/title_middleware.py；backend/tests/test_title_middleware_core_logic.py。

#### 73. fix(harness): skip duplicate memory facts (#1193)
- 提交：[`f67c3d2`](https://github.com/bytedance/deer-flow/commit/f67c3d2c9e236fb29e7a5622a9e4216809d60ff1)
- 日期：2026-03-18
- 做了什么：修复缺陷或回归问题，主题是“skip duplicate memory facts (#1193)”。
- 影响范围：主要涉及 后端、文档。
- 改动规模：+169 / -3 行。
- 关键文件：README.md；backend/CLAUDE.md；backend/packages/harness/deerflow/agents/memory/updater.py；backend/tests/test_memory_updater.py。

#### 74. fix(scripts): handle docker-init failures gracefully for private registry (#1191)
- 提交：[`423ea59`](https://github.com/bytedance/deer-flow/commit/423ea59491db1749316e9f6297efde8d2495de10)
- 日期：2026-03-18
- 做了什么：修复缺陷或回归问题，主题是“handle docker-init failures gracefully for private registry (#1191)”。
- 影响范围：主要涉及 其他模块、脚本工具。
- 改动规模：+63 / -4 行。
- 关键文件：Makefile；scripts/docker.sh。

#### 75. fix(gateway): remove generated markdown on upload delete (#1170)
- 提交：[`4c78188`](https://github.com/bytedance/deer-flow/commit/4c781888963b53130bc68cf8f712f73ed46d995e)
- 日期：2026-03-18
- 做了什么：修复缺陷或回归问题，主题是“remove generated markdown on upload delete (#1170)”。
- 影响范围：主要涉及 后端。
- 改动规模：+18 / -1 行。
- 关键文件：backend/app/gateway/routers/uploads.py；backend/tests/test_uploads_router.py。

#### 76. fix(frontend): block duplicate sends during uploads (#1165)
- 提交：[`f737fbe`](https://github.com/bytedance/deer-flow/commit/f737fbeae8a091d6ebf15ec97fb747293ec2c4b1)
- 日期：2026-03-18
- 做了什么：修复缺陷或回归问题，主题是“block duplicate sends during uploads (#1165)”。
- 影响范围：主要涉及 前端。
- 改动规模：+22 / -3 行。
- 关键文件：frontend/AGENTS.md；frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/core/threads/hooks.ts。

#### 77. fix(harness): allow agent read access to /mnt/skills in local sandbox (#1178)
- 提交：[`feac03e`](https://github.com/bytedance/deer-flow/commit/feac03ecbcac445bb514c411ec812e7f9ff74cb1)
- 日期：2026-03-17
- 做了什么：修复缺陷或回归问题，主题是“allow agent read access to /mnt/skills in local sandbox (#1178)”。
- 影响范围：主要涉及 后端。
- 改动规模：+527 / -295 行。
- 关键文件：backend/packages/harness/deerflow/sandbox/local/local_sandbox.py；backend/packages/harness/deerflow/sandbox/local/local_sandbox_provider.py；backend/packages/harness/deerflow/sandbox/tools.py；backend/tests/test_sandbox_tools_security.py。

#### 78. fix(scripts): add next-server to serve.sh cleanup trap (#1162)
- 提交：[`75c9630`](https://github.com/bytedance/deer-flow/commit/75c96300cfbd2ee28da2b1e813c2db77a618df86)
- 日期：2026-03-17
- 做了什么：修复缺陷或回归问题，主题是“add next-server to serve.sh cleanup trap (#1162)”。
- 影响范围：主要涉及 脚本工具。
- 改动规模：+1 / -0 行。
- 关键文件：scripts/serve.sh。

#### 79. fix(harness): normalize structured content for titles (#1155)
- 提交：[`b1913a1`](https://github.com/bytedance/deer-flow/commit/b1913a1902a73c1df6300393cf6418cc1a303fa1)
- 日期：2026-03-17
- 做了什么：修复缺陷或回归问题，主题是“normalize structured content for titles (#1155)”。
- 影响范围：主要涉及 后端。
- 改动规模：+56 / -7 行。
- 关键文件：backend/CLAUDE.md；backend/docs/AUTO_TITLE_GENERATION.md；backend/packages/harness/deerflow/agents/middlewares/title_middleware.py；backend/tests/test_title_middleware_core_logic.py。

#### 80. fix(makefile): correct docker-init help description (#1163)
- 提交：[`ab0c10f`](https://github.com/bytedance/deer-flow/commit/ab0c10f0021258dd6352082bb5128da5aff9b094)
- 日期：2026-03-16
- 做了什么：修复缺陷或回归问题，主题是“correct docker-init help description (#1163)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+1 / -1 行。
- 关键文件：Makefile。

#### 81. fix(frontend): gracefully handle missing WebGL context (#1147)
- 提交：[`609ff58`](https://github.com/bytedance/deer-flow/commit/609ff5849ff18af44e1926f5c4a5a5032fc399b1)
- 日期：2026-03-16
- 做了什么：修复缺陷或回归问题，主题是“gracefully handle missing WebGL context (#1147)”。
- 影响范围：主要涉及 前端。
- 改动规模：+21 / -4 行。
- 关键文件：frontend/src/components/ui/galaxy.jsx。

#### 82. fix(scripts): correct Makefile target name in docker.sh restart message (#1161)
- 提交：[`3212c7c`](https://github.com/bytedance/deer-flow/commit/3212c7c5a2c1117ab3a20fce2692072f2fa2e641)
- 日期：2026-03-16
- 做了什么：修复缺陷或回归问题，主题是“correct Makefile target name in docker.sh restart message (#1161)”。
- 影响范围：主要涉及 脚本工具。
- 改动规模：+1 / -1 行。
- 关键文件：scripts/docker.sh。

#### 83. fix: issue 1138 windows encoding (#1139)
- 提交：[`191b60a`](https://github.com/bytedance/deer-flow/commit/191b60a326f3031298d109dc4e8117ac40a00b23)
- 日期：2026-03-16
- 做了什么：修复缺陷或回归问题，主题是“issue 1138 windows encoding (#1139)”。
- 影响范围：主要涉及 后端、技能体系。
- 改动规模：+116 / -24 行。
- 关键文件：backend/app/gateway/routers/artifacts.py；backend/app/gateway/routers/mcp.py；backend/app/gateway/routers/skills.py；backend/packages/harness/deerflow/community/aio_sandbox/aio_sandbox_provider.py；backend/packages/harness/deerflow/sandbox/local/local_sandbox.py；backend/packages/harness/deerflow/sandbox/tools.py；backend/packages/harness/deerflow/skills/validation.py；backend/tests/test_artifacts_router.py。

#### 84. fix: preserve conversation context in Telegram private chats (#1105)
- 提交：[`d197d50`](https://github.com/bytedance/deer-flow/commit/d197d5014672ba319758019c1b14366a18dde818)
- 日期：2026-03-14
- 做了什么：修复缺陷或回归问题，主题是“preserve conversation context in Telegram private chats (#1105)”。
- 影响范围：主要涉及 后端。
- 改动规模：+237 / -18 行。
- 关键文件：backend/src/channels/manager.py；backend/src/channels/telegram.py；backend/tests/test_channels.py。

#### 85. fix(frontend): surface upload API error details (#1113)
- 提交：[`5a84814`](https://github.com/bytedance/deer-flow/commit/5a8481416f85d4828cef35bd45d779160258079d)
- 日期：2026-03-13
- 做了什么：修复缺陷或回归问题，主题是“surface upload API error details (#1113)”。
- 影响范围：主要涉及 前端。
- 改动规模：+15 / -6 行。
- 关键文件：frontend/src/core/uploads/api.ts。

#### 86. fix: make check/config cross-platform for Windows (#1080) (#1093)
- 提交：[`a79d414`](https://github.com/bytedance/deer-flow/commit/a79d4146956446e56d3db707f17d6d05f98fe527)
- 日期：2026-03-13
- 做了什么：修复缺陷或回归问题，主题是“make check/config cross-platform for Windows (#1080) (#1093)”。
- 影响范围：主要涉及 脚本工具、其他模块。
- 改动规模：+194 / -8 行。
- 关键文件：Makefile；scripts/check.py；scripts/configure.py。

#### 87. fix(gateway): ignore archive metadata wrappers (#1108)
- 提交：[`b155923`](https://github.com/bytedance/deer-flow/commit/b155923ab074673ca669a0028a3bfe025e1daead)
- 日期：2026-03-13
- 做了什么：修复缺陷或回归问题，主题是“ignore archive metadata wrappers (#1108)”。
- 影响范围：主要涉及 后端。
- 改动规模：+134 / -14 行。
- 关键文件：backend/src/gateway/routers/skills.py；backend/tests/test_skills_archive_root.py。

#### 88. fix(gateway): allow standard skill frontmatter metadata (#1103)
- 提交：[`cda9fb7`](https://github.com/bytedance/deer-flow/commit/cda9fb7bca6d86bde49bd0bc7edab76925bd4b54)
- 日期：2026-03-13
- 做了什么：修复缺陷或回归问题，主题是“allow standard skill frontmatter metadata (#1103)”。
- 影响范围：主要涉及 后端、文档。
- 改动规模：+83 / -4 行。
- 关键文件：README.md；backend/CLAUDE.md；backend/src/gateway/routers/skills.py；backend/tests/test_skills_router.py。

#### 89. fix(gateway): normalize suggestion response content (#1098)
- 提交：[`03cafea`](https://github.com/bytedance/deer-flow/commit/03cafea7158cb29c6dba999fb7049d5ec7d925e6)
- 日期：2026-03-13
- 做了什么：修复缺陷或回归问题，主题是“normalize suggestion response content (#1098)”。
- 影响范围：主要涉及 后端、文档。
- 改动规模：+40 / -1 行。
- 关键文件：README.md；backend/CLAUDE.md；backend/src/gateway/routers/suggestions.py；backend/tests/test_suggestions_router.py。

#### 90. fix(memory): inject stored facts into system prompt memory context (#1083)
- 提交：[`b5fcb13`](https://github.com/bytedance/deer-flow/commit/b5fcb1334ab1376b35568e4a80464bbf32c4218b)
- 日期：2026-03-13
- 做了什么：修复缺陷或回归问题，主题是“inject stored facts into system prompt memory context (#1083)”。
- 影响范围：主要涉及 后端。
- 改动规模：+252 / -502 行。
- 关键文件：backend/docs/MEMORY_IMPROVEMENTS.md；backend/docs/MEMORY_IMPROVEMENTS_SUMMARY.md；backend/src/agents/memory/prompt.py；backend/tests/test_memory_prompt_injection.py。

#### 91. fix(middleware): degrade tool-call exceptions to error tool messages (#1110)
- 提交：[`3521cc2`](https://github.com/bytedance/deer-flow/commit/3521cc266840d4e8edb4e377b74aa66282c44c48)
- 日期：2026-03-13
- 做了什么：修复缺陷或回归问题，主题是“degrade tool-call exceptions to error tool messages (#1110)”。
- 影响范围：主要涉及 后端、脚本工具。
- 改动规模：+436 / -14 行。
- 关键文件：backend/src/agents/lead_agent/agent.py；backend/src/agents/middlewares/tool_error_handling_middleware.py；backend/src/subagents/executor.py；backend/tests/test_tool_error_handling_middleware.py；scripts/tool-error-degradation-detection.sh。

#### 92. fix(chat): update navigation method to prevent state loss during thread remount (#1107)
- 提交：[`fdacb1c`](https://github.com/bytedance/deer-flow/commit/fdacb1c3a5734a023319be19e9dfaeca54b5b8f7)
- 日期：2026-03-12
- 做了什么：修复缺陷或回归问题，主题是“update navigation method to prevent state loss during thread remount (#1107)”。
- 影响范围：主要涉及 前端。
- 改动规模：+4 / -27 行。
- 关键文件：frontend/src/app/workspace/agents/[agent_name]/chats/[thread_id]/page.tsx；frontend/src/app/workspace/chats/[thread_id]/layout.tsx；frontend/src/app/workspace/chats/[thread_id]/page.tsx。

#### 93. fix(makefile):quick fix of the makefile formate error (#1085)
- 提交：[`e5a21b9`](https://github.com/bytedance/deer-flow/commit/e5a21b9ba0316891af682b327cd5fba02c2bc383)
- 日期：2026-03-11
- 做了什么：修复缺陷或回归问题，主题是“quick fix of the makefile formate error (#1085)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+2 / -2 行。
- 关键文件：Makefile。

#### 94. fix(client): Harden upload validation and conversion flow (#989)
- 提交：[`4bae3c7`](https://github.com/bytedance/deer-flow/commit/4bae3c724ce2f6fbe6baaddc19c16e848e93539c)
- 日期：2026-03-11
- 做了什么：修复缺陷或回归问题，主题是“Harden upload validation and conversion flow (#989)”。
- 影响范围：主要涉及 后端。
- 改动规模：+174 / -49 行。
- 关键文件：backend/CLAUDE.md；backend/README.md；backend/src/client.py；backend/tests/test_client.py。

#### 95. fix(frontend): fix new-chat navigation stale state issue (#1077)
- 提交：[`5d4fd9c`](https://github.com/bytedance/deer-flow/commit/5d4fd9cf72604a48fea2a97c79b7a0956d7c0d47)
- 日期：2026-03-11
- 做了什么：修复缺陷或回归问题，主题是“fix new-chat navigation stale state issue (#1077)”。
- 影响范围：主要涉及 前端。
- 改动规模：+27 / -2 行。
- 关键文件：frontend/src/app/workspace/chats/[thread_id]/layout.tsx；frontend/src/app/workspace/chats/[thread_id]/page.tsx。

#### 96. fix(tracing): support LANGCHAIN_* env fallback for LangSmith config (#1065)
- 提交：[`96dbee0`](https://github.com/bytedance/deer-flow/commit/96dbee00e37942af7deb42f2899f4262cd3de423)
- 日期：2026-03-11
- 做了什么：修复缺陷或回归问题，主题是“support LANGCHAIN_* env fallback for LangSmith config (#1065)”。
- 影响范围：主要涉及 后端。
- 改动规模：+116 / -4 行。
- 关键文件：backend/src/config/tracing_config.py；backend/tests/test_tracing_config.py。

#### 97. fix: load all thread pages in thread lists (#1044)
- 提交：[`6ae7f0c`](https://github.com/bytedance/deer-flow/commit/6ae7f0c0eeeb0a694c6fc3e728c562975be57f16)
- 日期：2026-03-10
- 做了什么：修复缺陷或回归问题，主题是“load all thread pages in thread lists (#1044)”。
- 影响范围：主要涉及 前端。
- 改动规模：+116 / -12 行。
- 关键文件：frontend/src/app/mock/api/threads/search/route.ts；frontend/src/core/threads/hooks.ts。

#### 98. fix(frontend): sanitize unsupported langgraph stream modes (#1050)
- 提交：[`d5135ab`](https://github.com/bytedance/deer-flow/commit/d5135ab7578dc7a6d8431375a26a094fb6936dce)
- 日期：2026-03-10
- 做了什么：修复缺陷或回归问题，主题是“sanitize unsupported langgraph stream modes (#1050)”。
- 影响范围：主要涉及 前端。
- 改动规模：+138 / -4 行。
- 关键文件：frontend/src/core/api/api-client.ts；frontend/src/core/api/stream-mode.test.ts；frontend/src/core/api/stream-mode.ts；frontend/src/core/threads/hooks.ts。

#### 99. fix: improve port detection in WSL (#1061)
- 提交：[`19604e7`](https://github.com/bytedance/deer-flow/commit/19604e7f4716bede04ae51ed67abba51cef502cb)
- 日期：2026-03-10
- 做了什么：修复缺陷或回归问题，主题是“improve port detection in WSL (#1061)”。
- 影响范围：主要涉及 脚本工具。
- 改动规模：+28 / -1 行。
- 关键文件：scripts/wait-for-port.sh。

#### 100. docs: fix stream_mode examples for runs stream (#1033) (#1039)
- 提交：[`cf1c4a6`](https://github.com/bytedance/deer-flow/commit/cf1c4a68ea370a0055e858f8c2c1a0cfa10d90c7)
- 日期：2026-03-10
- 做了什么：修复缺陷或回归问题，主题是“fix stream_mode examples for runs stream (#1033) (#1039)”。
- 影响范围：主要涉及 后端。
- 改动规模：+6 / -2 行。
- 关键文件：backend/docs/API.md。

#### 101. fix(subagents): cleanup background tasks after completion to prevent memory leak (#1030)
- 提交：[`0409f8c`](https://github.com/bytedance/deer-flow/commit/0409f8cefd7864fa34f9fbef30b7bbd97156c64b)
- 日期：2026-03-10
- 做了什么：修复缺陷或回归问题，主题是“cleanup background tasks after completion to prevent memory leak (#1030)”。
- 影响范围：主要涉及 后端。
- 改动规模：+361 / -1 行。
- 关键文件：backend/src/subagents/executor.py；backend/src/tools/builtins/task_tool.py；backend/tests/test_subagent_executor.py；backend/tests/test_task_tool_core_logic.py。

#### 102. fix(checkpointer): return InMemorySaver instead of None when not configured (#1016) (#1019)
- 提交：[`959b4f2`](https://github.com/bytedance/deer-flow/commit/959b4f2b0989365717b3aa7e386e690a424a45e7)
- 日期：2026-03-09
- 做了什么：修复缺陷或回归问题，主题是“return InMemorySaver instead of None when not configured (#1016) (#1019)”。
- 影响范围：主要涉及 后端。
- 改动规模：+95 / -12 行。
- 关键文件：backend/src/agents/checkpointer/async_provider.py；backend/src/agents/checkpointer/provider.py；backend/tests/test_checkpointer.py；backend/tests/test_checkpointer_none_fix.py。

#### 103. fix(frontend): enable HTML preview for generated artifacts using srcDoc (#1001)
- 提交：[`4f0a8da`](https://github.com/bytedance/deer-flow/commit/4f0a8da2eed7ccfcd12f4322b30ded56edf7ed37)
- 日期：2026-03-09
- 做了什么：修复缺陷或回归问题，主题是“enable HTML preview for generated artifacts using srcDoc (#1001)”。
- 影响范围：主要涉及 前端。
- 改动规模：+5 / -10 行。
- 关键文件：frontend/src/components/workspace/artifacts/artifact-file-detail.tsx。

#### 104. fix(dev): improve gateway startup diagnostics for config errors (#1020)
- 提交：[`6b5c4fe`](https://github.com/bytedance/deer-flow/commit/6b5c4fe6dd11f8032aa7f92aa497d5ae09548ffa)
- 日期：2026-03-08
- 做了什么：修复缺陷或回归问题，主题是“improve gateway startup diagnostics for config errors (#1020)”。
- 影响范围：主要涉及 后端、其他模块、文档。
- 改动规模：+26 / -5 行。
- 关键文件：Makefile；README.md；backend/CLAUDE.md；backend/src/gateway/app.py。

#### 105. fix(docker): remove cache_from to prevent missing cache warnings (#1013)
- 提交：[`511e9ea`](https://github.com/bytedance/deer-flow/commit/511e9eaf5eb3c26f6b530002978e6cd477a90db7)
- 日期：2026-03-08
- 做了什么：修复缺陷或回归问题，主题是“remove cache_from to prevent missing cache warnings (#1013)”。
- 影响范围：主要涉及 容器部署。
- 改动规模：+2 / -4 行。
- 关键文件：docker/docker-compose-dev.yaml。

#### 106. fix: normalize presented artifact paths (#998)
- 提交：[`09325ca`](https://github.com/bytedance/deer-flow/commit/09325ca28f99cd9eed55d6bc96969432279d2c39)
- 日期：2026-03-06
- 做了什么：修复缺陷或回归问题，主题是“normalize presented artifact paths (#998)”。
- 影响范围：主要涉及 后端。
- 改动规模：+145 / -1 行。
- 关键文件：backend/src/tools/builtins/present_file_tool.py；backend/tests/test_present_file_tool_core_logic.py。

#### 107. fix(subagent): support async MCP tools in subagent executor (#917)
- 提交：[`3e4a24f`](https://github.com/bytedance/deer-flow/commit/3e4a24f48bd6bc869805e9351e5599c7bf662764)
- 日期：2026-03-06
- 做了什么：修复缺陷或回归问题，主题是“support async MCP tools in subagent executor (#917)”。
- 影响范围：主要涉及 后端。
- 改动规模：+674 / -6 行。
- 关键文件：backend/src/subagents/executor.py；backend/tests/test_subagent_executor.py。

#### 108. fix(backend): upgrade langgraph-api to 0.7 and stabilize memory path tests (#984)
- 提交：[`3a5e0b9`](https://github.com/bytedance/deer-flow/commit/3a5e0b935d2f1b0a5519f3d0eb93e24bf1cd1761)
- 日期：2026-03-06
- 做了什么：修复缺陷或回归问题，主题是“upgrade langgraph-api to 0.7 and stabilize memory path tests (#984)”。
- 影响范围：主要涉及 后端。
- 改动规模：+135 / -101 行。
- 关键文件：backend/pyproject.toml；backend/tests/test_custom_agent.py；backend/uv.lock。

#### 109. fix(nginx): use cross-platform local paths for pid and logs (#977)
- 提交：[`0c7c96d`](https://github.com/bytedance/deer-flow/commit/0c7c96d75e286c7513ea1d0cb9625afe6617dd21)
- 日期：2026-03-05
- 做了什么：修复缺陷或回归问题，主题是“use cross-platform local paths for pid and logs (#977)”。
- 影响范围：主要涉及 容器部署。
- 改动规模：+3 / -3 行。
- 关键文件：docker/nginx/nginx.local.conf。

#### 110. fix(chat): handle empty uploaded files case and improve artifact selection logic (#979)
- 提交：[`1b3939c`](https://github.com/bytedance/deer-flow/commit/1b3939cb78b58ad45ae8eb8b3485a78465e54c2a)
- 日期：2026-03-05
- 做了什么：修复缺陷或回归问题，主题是“handle empty uploaded files case and improve artifact selection logic (#979)”。
- 影响范围：主要涉及 前端、后端。
- 改动规模：+51 / -18 行。
- 关键文件：backend/src/agents/middlewares/uploads_middleware.py；backend/tests/test_uploads_middleware_core_logic.py；frontend/src/components/workspace/artifacts/context.tsx；frontend/src/components/workspace/chats/chat-box.tsx；frontend/src/core/messages/utils.ts。

#### 111. fix(memory): prevent file upload events from persisting in long-term memory (#971)
- 提交：[`3ada4f9`](https://github.com/bytedance/deer-flow/commit/3ada4f98b1c63f138dbb90fffbf5ea51d086c63f)
- 日期：2026-03-05
- 做了什么：修复缺陷或回归问题，主题是“prevent file upload events from persisting in long-term memory (#971)”。
- 影响范围：主要涉及 后端。
- 改动规模：+336 / -5 行。
- 关键文件：backend/src/agents/memory/prompt.py；backend/src/agents/memory/updater.py；backend/src/agents/middlewares/memory_middleware.py；backend/tests/test_memory_upload_filtering.py。

#### 112. fix(readme): correct typo Offiical to Official (#972)
- 提交：[`6ac0042`](https://github.com/bytedance/deer-flow/commit/6ac0042cfee14ca395681d96c2e7b1393f4cb528)
- 日期：2026-03-05
- 做了什么：修复缺陷或回归问题，主题是“correct typo Offiical to Official (#972)”。
- 影响范围：主要涉及 文档。
- 改动规模：+1 / -1 行。
- 关键文件：README.md。

#### 113. fix(make):added make config command in make file (#964)
- 提交：[`a3c8efb`](https://github.com/bytedance/deer-flow/commit/a3c8efb00b2c7281e25c0ca6330bed13d99b15df)
- 日期：2026-03-04
- 做了什么：修复缺陷或回归问题，主题是“added make config command in make file (#964)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+6 / -1 行。
- 关键文件：Makefile。

#### 114. fix(models): handle google provider import errors and add dependency (#952)
- 提交：[`8342e88`](https://github.com/bytedance/deer-flow/commit/8342e88534b78390221c0ff5bfc9b37759fc26f5)
- 日期：2026-03-03
- 做了什么：修复缺陷或回归问题，主题是“handle google provider import errors and add dependency (#952)”。
- 影响范围：主要涉及 后端、配置。
- 改动规模：+191 / -1 行。
- 关键文件：backend/CLAUDE.md；backend/README.md；backend/pyproject.toml；backend/src/reflection/resolvers.py；backend/tests/test_reflection_resolvers.py；backend/uv.lock；config.example.yaml。

#### 115. Fix line numbering (#954)
- 提交：[`e399d09`](https://github.com/bytedance/deer-flow/commit/e399d09e8f493ba5e2cd23008d17a582fe9b6f7c)
- 日期：2026-03-02
- 做了什么：修复缺陷或回归问题，主题是“Fix line numbering (#954)”。
- 影响范围：主要涉及 前端。
- 改动规模：+2 / -1 行。
- 关键文件：frontend/src/components/ai-elements/message.tsx。

#### 116. fix(backend): Fix readability extraction crash when Node parser fails (#937)
- 提交：[`80316c1`](https://github.com/bytedance/deer-flow/commit/80316c131e90d4938bd3fec9d6da0f3c1c730016)
- 日期：2026-03-01
- 做了什么：修复缺陷或回归问题，主题是“Fix readability extraction crash when Node parser fails (#937)”。
- 影响范围：主要涉及 后端。
- 改动规模：+73 / -1 行。
- 关键文件：backend/src/utils/readability.py；backend/tests/test_readability.py。

#### 117. fix: use shell fallback instead of hardcoded /bin/zsh in LocalSandbox (#939)
- 提交：[`d728bb2`](https://github.com/bytedance/deer-flow/commit/d728bb26d59bb2e97396c2a4921787ca3b0360a0)
- 日期：2026-03-01
- 做了什么：修复缺陷或回归问题，主题是“use shell fallback instead of hardcoded /bin/zsh in LocalSandbox (#939)”。
- 影响范围：主要涉及 后端。
- 改动规模：+21 / -1 行。
- 关键文件：backend/src/sandbox/local/local_sandbox.py。

#### 118. fix(uploads): persist thread uploads canonically and fail fast on upload errors (#943)
- 提交：[`8c6dd9e`](https://github.com/bytedance/deer-flow/commit/8c6dd9e264e3a1189a3f0e5964b95bf9067c73e5)
- 日期：2026-03-01
- 做了什么：修复缺陷或回归问题，主题是“persist thread uploads canonically and fail fast on upload errors (#943)”。
- 影响范围：主要涉及 后端、前端。
- 改动规模：+143 / -12 行。
- 关键文件：backend/docs/FILE_UPLOAD.md；backend/src/gateway/routers/uploads.py；backend/tests/test_uploads_router.py；frontend/src/core/threads/hooks.ts。

#### 119. Fix typo: Offiical to Official (#942)
- 提交：[`5a1ac62`](https://github.com/bytedance/deer-flow/commit/5a1ac6287ed0cea3c14e9460fe456c5bb876ce48)
- 日期：2026-03-01
- 做了什么：修复缺陷或回归问题，主题是“Fix typo: Offiical to Official (#942)”。
- 影响范围：主要涉及 文档。
- 改动规模：+1 / -1 行。
- 关键文件：README.md。

## 2026-04

- 提交数：169 条

#### 1. fix(config): unify log_level from config.yaml across Gateway and debug entry points (#2601)
- 提交：[`eba3b9e`](https://github.com/bytedance/deer-flow/commit/eba3b9e18d797dfc42b9cc8610781fa941755731)
- 日期：2026-04-30
- 做了什么：修复缺陷或回归问题，主题是“unify log_level from config.yaml across Gateway and debug entry points (#2601)”。
- 影响范围：主要涉及 后端。
- 改动规模：+137 / -28 行。
- 关键文件：backend/app/gateway/app.py；backend/debug.py；backend/packages/harness/deerflow/config/app_config.py；backend/tests/test_logging_level_from_config.py。

#### 2. fix(memory): replace short-lived asyncio.run() with persistent event loop (#2627)
- 提交：[`c0da278`](https://github.com/bytedance/deer-flow/commit/c0da2782695168a19e34e2c11d8a188f02884128)
- 日期：2026-04-30
- 做了什么：修复缺陷或回归问题，主题是“replace short-lived asyncio.run() with persistent event loop (#2627)”。
- 影响范围：主要涉及 后端。
- 改动规模：+240 / -88 行。
- 关键文件：backend/packages/harness/deerflow/agents/memory/updater.py；backend/tests/test_memory_updater.py。

#### 3. fix: avoid temporary event loops in async subagent execution (#2414)
- 提交：[`7dea166`](https://github.com/bytedance/deer-flow/commit/7dea1666ce665905e684af4dac2b300f6d6884f4)
- 日期：2026-04-30
- 做了什么：修复缺陷或回归问题，主题是“avoid temporary event loops in async subagent execution (#2414)”。
- 影响范围：主要涉及 后端。
- 改动规模：+236 / -75 行。
- 关键文件：backend/packages/harness/deerflow/subagents/executor.py；backend/tests/test_subagent_executor.py。

#### 4. fix(nginx): add catch-all /api/ location for auth routes (#2657)
- 提交：[`88d47f6`](https://github.com/bytedance/deer-flow/commit/88d47f677f41bbce4fbc87fcc15ca2d1a7c0c3ec)
- 日期：2026-04-30
- 做了什么：修复缺陷或回归问题，主题是“add catch-all /api/ location for auth routes (#2657)”。
- 影响范围：主要涉及 容器部署。
- 改动规模：+11 / -0 行。
- 关键文件：docker/nginx/nginx.conf。

#### 5. [security] fix(sandbox): bind local Docker ports to loopback (#2633)
- 提交：[`74081a8`](https://github.com/bytedance/deer-flow/commit/74081a85a6827b013b4f41ca6a7f9e4d9b62069e)
- 日期：2026-04-30
- 做了什么：修复缺陷或回归问题，主题是“[security] fix(sandbox): bind local Docker ports to loopback (#2633)”。
- 影响范围：主要涉及 后端。
- 改动规模：+169 / -2 行。
- 关键文件：backend/docs/CONFIGURATION.md；backend/packages/harness/deerflow/community/aio_sandbox/local_backend.py；backend/tests/test_aio_sandbox_local_backend.py。

#### 6. fix: avoid duplicate call to extractReasoningContentFromMessage (#2661)
- 提交：[`24a5a00`](https://github.com/bytedance/deer-flow/commit/24a5a00679a99886387612ff991afbbd8c6be52d)
- 日期：2026-04-30
- 做了什么：修复缺陷或回归问题，主题是“avoid duplicate call to extractReasoningContentFromMessage (#2661)”。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -1 行。
- 关键文件：frontend/src/components/workspace/messages/message-group.tsx。

#### 7. fix(security): allow disabling API docs in production via GATEWAY_ENABLE_DOCS (#2651)
- 提交：[`0691c4d`](https://github.com/bytedance/deer-flow/commit/0691c4dda383561659f03c55927951a5be66b548)
- 日期：2026-04-30
- 做了什么：修复缺陷或回归问题，主题是“allow disabling API docs in production via GATEWAY_ENABLE_DOCS (#2651)”。
- 影响范围：主要涉及 后端、其他模块。
- 改动规模：+134 / -4 行。
- 关键文件：.env.example；backend/CLAUDE.md；backend/app/gateway/app.py；backend/app/gateway/config.py；backend/docs/CONFIGURATION.md；backend/tests/test_gateway_docs_toggle.py。

#### 8. fix(frontend): create thread on first submit in new-agent page (#2656)
- 提交：[`f7b10d4`](https://github.com/bytedance/deer-flow/commit/f7b10d42e484b308b3883e9c311baa7fa7960c30)
- 日期：2026-04-30
- 做了什么：修复缺陷或回归问题，主题是“create thread on first submit in new-agent page (#2656)”。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -1 行。
- 关键文件：frontend/src/app/workspace/agents/new/page.tsx。

#### 9. Fix the log Injection error of skills.py
- 提交：[`11afd32`](https://github.com/bytedance/deer-flow/commit/11afd32459cbbeb4a0c86fe9d2a07244af82f6f0)
- 日期：2026-04-28
- 做了什么：修复缺陷或回归问题，主题是“Fix the log Injection error of skills.py”。
- 影响范围：主要涉及 后端。
- 改动规模：+7 / -2 行。
- 关键文件：backend/app/gateway/routers/skills.py。

#### 10. fixed the CI build errors
- 提交：[`64f4dc1`](https://github.com/bytedance/deer-flow/commit/64f4dc163910895b1fd5df1d569fac6ffce8309e)
- 日期：2026-04-28
- 做了什么：修复缺陷或回归问题，主题是“fixed the CI build errors”。
- 影响范围：主要涉及 后端。
- 改动规模：+4 / -3 行。
- 关键文件：backend/app/gateway/routers/skills.py；backend/tests/test_skills_custom_router.py。

#### 11. fix(sandbox): block host bash traversal escapes (#2560)
- 提交：[`6bd88fe`](https://github.com/bytedance/deer-flow/commit/6bd88fe14cfe4d4b83199047326d4455bd656d55)
- 日期：2026-04-28
- 做了什么：修复缺陷或回归问题，主题是“block host bash traversal escapes (#2560)”。
- 影响范围：主要涉及 后端。
- 改动规模：+373 / -25 行。
- 关键文件：backend/packages/harness/deerflow/sandbox/tools.py；backend/tests/test_sandbox_tools_security.py。

#### 12. fix(sandbox): prevent local custom mount symlink escapes (#2558)
- 提交：[`39c5da9`](https://github.com/bytedance/deer-flow/commit/39c5da94f3b723b9062fdf00522cc69cdc837640)
- 日期：2026-04-28
- 做了什么：修复缺陷或回归问题，主题是“prevent local custom mount symlink escapes (#2558)”。
- 影响范围：主要涉及 后端。
- 改动规模：+242 / -23 行。
- 关键文件：backend/packages/harness/deerflow/sandbox/local/list_dir.py；backend/packages/harness/deerflow/sandbox/local/local_sandbox.py；backend/tests/test_local_sandbox_provider_mounts.py。

#### 13. fix(skills): scan skill archives before install (#2561)
- 提交：[`707ed32`](https://github.com/bytedance/deer-flow/commit/707ed328dd3b3364c304fac8ea0409bc86c2e1a6)
- 日期：2026-04-28
- 做了什么：修复缺陷或回归问题，主题是“scan skill archives before install (#2561)”。
- 影响范围：主要涉及 后端。
- 改动规模：+400 / -9 行。
- 关键文件：backend/app/gateway/routers/skills.py；backend/packages/harness/deerflow/skills/__init__.py；backend/packages/harness/deerflow/skills/installer.py；backend/tests/test_client.py；backend/tests/test_client_e2e.py；backend/tests/test_skills_custom_router.py；backend/tests/test_skills_installer.py。

#### 14. fix(aio-sandbox): redact env values in container logs (#2562)
- 提交：[`f7dfb88`](https://github.com/bytedance/deer-flow/commit/f7dfb88a306615ce6ec90a9bf7fabba86113f529)
- 日期：2026-04-28
- 做了什么：修复缺陷或回归问题，主题是“redact env values in container logs (#2562)”。
- 影响范围：主要涉及 后端。
- 改动规模：+134 / -2 行。
- 关键文件：backend/packages/harness/deerflow/community/aio_sandbox/local_backend.py；backend/tests/test_aio_sandbox_local_backend.py。

#### 15. Fix the issues when reviewing 2566 persistant part (#2604)
- 提交：[`69649d8`](https://github.com/bytedance/deer-flow/commit/69649d8aaef890e443bf5b5aef353fc664a920c4)
- 日期：2026-04-28
- 做了什么：修复缺陷或回归问题，主题是“Fix the issues when reviewing 2566 persistant part (#2604)”。
- 影响范围：主要涉及 后端。
- 改动规模：+82 / -19 行。
- 关键文件：backend/packages/harness/deerflow/runtime/converters.py；backend/packages/harness/deerflow/runtime/journal.py；backend/tests/test_run_journal.py。

#### 16.  fix(security): harden auth system and fix run journal logic bug (#2593)
- 提交：[`4e4e4f9`](https://github.com/bytedance/deer-flow/commit/4e4e4f92a060e90963157b99f1a425ba0f4c469d)
- 日期：2026-04-28
- 做了什么：修复缺陷或回归问题，主题是“harden auth system and fix run journal logic bug (#2593)”。
- 影响范围：主要涉及 后端。
- 改动规模：+245 / -22 行。
- 关键文件：backend/app/gateway/auth/config.py；backend/app/gateway/auth/local_provider.py；backend/app/gateway/auth/password.py；backend/app/gateway/authz.py；backend/app/gateway/langgraph_auth.py；backend/app/gateway/routers/auth.py；backend/packages/harness/deerflow/runtime/journal.py；backend/tests/test_auth.py。

#### 17. fix(harness): constrain view_image to thread data paths (#2557)
- 提交：[`af8c0cf`](https://github.com/bytedance/deer-flow/commit/af8c0cfb7830c885765fca8d5d023d6cfca045a5)
- 日期：2026-04-28
- 做了什么：修复缺陷或回归问题，主题是“constrain view_image to thread data paths (#2557)”。
- 影响范围：主要涉及 后端。
- 改动规模：+282 / -32 行。
- 关键文件：backend/packages/harness/deerflow/agents/factory.py；backend/packages/harness/deerflow/sandbox/tools.py；backend/packages/harness/deerflow/tools/builtins/view_image_tool.py；backend/tests/test_create_deerflow_agent.py；backend/tests/test_view_image_tool.py。

#### 18. fix(frontend): add missing mock routes for runs-list, models, and suggestions (#2578)
- 提交：[`748429e`](https://github.com/bytedance/deer-flow/commit/748429ef0d6a466e04549f7aee4466170727a705)
- 日期：2026-04-26
- 做了什么：修复缺陷或回归问题，主题是“add missing mock routes for runs-list, models, and suggestions (#2578)”。
- 影响范围：主要涉及 前端。
- 改动规模：+41 / -0 行。
- 关键文件：frontend/tests/e2e/utils/mock-api.ts。

#### 19. fix: enforce 'request' parameter requirement in require_auth decorator
- 提交：[`ed9ebfa`](https://github.com/bytedance/deer-flow/commit/ed9ebfac4d95cffeb0ac7604f1c8b68b821676bb)
- 日期：2026-04-26
- 做了什么：修复缺陷或回归问题，主题是“enforce 'request' parameter requirement in require_auth decorator”。
- 影响范围：主要涉及 后端。
- 改动规模：+1 / -1 行。
- 关键文件：backend/app/gateway/authz.py。

#### 20. fix the lint error of backend
- 提交：[`897dae5`](https://github.com/bytedance/deer-flow/commit/897dae5475cefdaf857c9dff3b0143b1a4b90c02)
- 日期：2026-04-26
- 做了什么：修复缺陷或回归问题，主题是“fix the lint error of backend”。
- 影响范围：主要涉及 后端。
- 改动规模：+1 / -0 行。
- 关键文件：backend/packages/harness/deerflow/persistence/migrations/env.py。

#### 21. fix unit tests of test_upload_files and test_shutdown
- 提交：[`eba6c0e`](https://github.com/bytedance/deer-flow/commit/eba6c0eab20d5381d77180b2fc2f6854d0ba1ab7)
- 日期：2026-04-26
- 做了什么：修复缺陷或回归问题，主题是“fix unit tests of test_upload_files and test_shutdown”。
- 影响范围：主要涉及 后端。
- 改动规模：+40 / -3 行。
- 关键文件：backend/app/gateway/app.py；backend/app/gateway/authz.py。

#### 22. fix the unit tests error of agent provider
- 提交：[`60754f0`](https://github.com/bytedance/deer-flow/commit/60754f0c502ce2ec03899173252fe8bd1aa71819)
- 日期：2026-04-26
- 做了什么：修复缺陷或回归问题，主题是“fix the unit tests error of agent provider”。
- 影响范围：主要涉及 后端。
- 改动规模：+8 / -8 行。
- 关键文件：backend/tests/test_checkpointer.py；backend/tests/test_lead_agent_prompt.py。

#### 23. Potential fix for pull request finding 'Unused import'
- 提交：[`16aedf4`](https://github.com/bytedance/deer-flow/commit/16aedf459a0e7ce36cf73a3973ec6f1a468da395)
- 日期：2026-04-26
- 做了什么：修复缺陷或回归问题，主题是“Potential fix for pull request finding 'Unused import'”。
- 影响范围：主要涉及 后端。
- 改动规模：+2 / -1 行。
- 关键文件：backend/packages/harness/deerflow/persistence/migrations/env.py。

#### 24. fix: resolve make dev and test-e2e errors (#2570)
- 提交：[`c5d57b4`](https://github.com/bytedance/deer-flow/commit/c5d57b453382d794174f16ab354b930d1a246ca5)
- 日期：2026-04-26
- 做了什么：修复缺陷或回归问题，主题是“resolve make dev and test-e2e errors (#2570)”。
- 影响范围：主要涉及 后端、前端。
- 改动规模：+15 / -2 行。
- 关键文件：backend/docs/HARNESS_APP_SPLIT.md；backend/langgraph.json；frontend/playwright.config.ts；frontend/src/core/auth/server.ts。

#### 25. Fixed the warning message of uv
- 提交：[`e4ff444`](https://github.com/bytedance/deer-flow/commit/e4ff444a71cd5d1fc387c036e50af24b4fbe2b3d)
- 日期：2026-04-26
- 做了什么：修复缺陷或回归问题，主题是“Fixed the warning message of uv”。
- 影响范围：主要涉及 后端。
- 改动规模：+4 / -1 行。
- 关键文件：backend/pyproject.toml；backend/uv.toml。

#### 26. fix the lint error by updating the .prettierignore
- 提交：[`64a43bc`](https://github.com/bytedance/deer-flow/commit/64a43bc4486ae2de09eafc969efb81df8ab3f401)
- 日期：2026-04-26
- 做了什么：修复缺陷或回归问题，主题是“fix the lint error by updating the .prettierignore”。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -0 行。
- 关键文件：frontend/.prettierignore。

#### 27. try to fix the frontend e2e test errors
- 提交：[`3f88045`](https://github.com/bytedance/deer-flow/commit/3f88045b98dc01730ce61cb8c2e9c80f0ba05f6e)
- 日期：2026-04-26
- 做了什么：修复缺陷或回归问题，主题是“try to fix the frontend e2e test errors”。
- 影响范围：主要涉及 前端。
- 改动规模：+34 / -16 行。
- 关键文件：frontend/src/app/workspace/agents/new/page.tsx；frontend/src/content/en/harness/tools.mdx；frontend/src/content/zh/harness/tools.mdx。

#### 28. fix the lint errors in the frontend
- 提交：[`9eca429`](https://github.com/bytedance/deer-flow/commit/9eca429a291e406929a522ecb7594ebd81a01f70)
- 日期：2026-04-26
- 做了什么：修复缺陷或回归问题，主题是“fix the lint errors in the frontend”。
- 影响范围：主要涉及 前端。
- 改动规模：+6 / -4 行。
- 关键文件：frontend/src/app/workspace/agents/new/page.tsx；frontend/src/core/threads/hooks.ts。

#### 29. fix the lint errors in frontend
- 提交：[`28381e1`](https://github.com/bytedance/deer-flow/commit/28381e1383cdd1a4ec57a659e965c46c1cd7cf6d)
- 日期：2026-04-26
- 做了什么：修复缺陷或回归问题，主题是“fix the lint errors in frontend”。
- 影响范围：主要涉及 前端。
- 改动规模：+456 / -357 行。
- 关键文件：frontend/src/content/en/application/configuration.mdx；frontend/src/content/en/application/deployment-guide.mdx；frontend/src/content/en/application/index.mdx；frontend/src/content/en/application/operations-and-troubleshooting.mdx；frontend/src/content/en/application/quick-start.mdx；frontend/src/content/en/application/workspace-usage.mdx；frontend/src/content/en/harness/configuration.mdx；frontend/src/content/en/harness/customization.mdx。

#### 30. fix the lint error in backend
- 提交：[`829e82a`](https://github.com/bytedance/deer-flow/commit/829e82a9afa404750494b658bb9c208386aec9e4)
- 日期：2026-04-26
- 做了什么：修复缺陷或回归问题，主题是“fix the lint error in backend”。
- 影响范围：主要涉及 后端。
- 改动规模：+76 / -49 行。
- 关键文件：backend/app/gateway/routers/threads.py；backend/app/gateway/services.py；backend/packages/harness/deerflow/persistence/feedback/model.py；backend/scripts/migrate_user_isolation.py；backend/tests/_router_auth_helpers.py；backend/tests/test_memory_queue_user_isolation.py；backend/tests/test_memory_storage_user_isolation.py；backend/tests/test_memory_updater_user_isolation.py。

#### 31. fix: resolve merge conflict in pnpm-lock.yaml and clean up better-auth dependencies
- 提交：[`98a5b34`](https://github.com/bytedance/deer-flow/commit/98a5b34f76ea3b0a4803f70ba3bd74451f564825)
- 日期：2026-04-26
- 做了什么：修复缺陷或回归问题，主题是“resolve merge conflict in pnpm-lock.yaml and clean up better-auth dependencies”。
- 影响范围：主要涉及 后端、前端。
- 改动规模：+1362 / -1351 行。
- 关键文件：backend/packages/harness/deerflow/agents/memory/queue.py；backend/packages/harness/pyproject.toml；backend/uv.lock；frontend/pnpm-lock.yaml。

#### 32. docs: fix review feedback - source-map paths, memory API routes, supports_thinking, checkpointer callout
- 提交：[`716cae2`](https://github.com/bytedance/deer-flow/commit/716cae20c6e63dd0f3227b83ebddb913bf3dc0e3)
- 日期：2026-04-11
- 做了什么：修复缺陷或回归问题，主题是“fix review feedback - source-map paths, memory API routes, supports_thinking, checkpointer callout”。
- 影响范围：主要涉及 前端。
- 改动规模：+448 / -5 行。
- 关键文件：frontend/src/content/en/application/agents-and-threads.mdx；frontend/src/content/en/reference/api-gateway-reference.mdx；frontend/src/content/en/reference/configuration-reference.mdx；frontend/src/content/en/reference/runtime-flags-and-modes.mdx；frontend/src/content/en/reference/source-map.mdx。

#### 33. fix(channles):update the logger for the channel config (#2524)
- 提交：[`9dc2598`](https://github.com/bytedance/deer-flow/commit/9dc25987e05e71ae87db0da22a63b4290c5e9747)
- 日期：2026-04-26
- 做了什么：修复缺陷或回归问题，主题是“update the logger for the channel config (#2524)”。
- 影响范围：主要涉及 后端。
- 改动规模：+79 / -1 行。
- 关键文件：backend/app/channels/service.py；backend/tests/test_channels.py。

#### 34. fix(channels): accept single slack allowed user (#2481)
- 提交：[`410f0c4`](https://github.com/bytedance/deer-flow/commit/410f0c48b54d5b38f8baf834baf3956eba1f8679)
- 日期：2026-04-25
- 做了什么：修复缺陷或回归问题，主题是“accept single slack allowed user (#2481)”。
- 影响范围：主要涉及 后端、配置。
- 改动规模：+95 / -8 行。
- 关键文件：backend/app/channels/slack.py；backend/tests/test_channels.py；config.example.yaml。

#### 35. fix: cap prompt caching breakpoints at 4 to prevent API 400 errors (#2449)
- 提交：[`1f59e94`](https://github.com/bytedance/deer-flow/commit/1f59e945af4a04824deda90cd41ca318670858c5)
- 日期：2026-04-25
- 做了什么：修复缺陷或回归问题，主题是“cap prompt caching breakpoints at 4 to prevent API 400 errors (#2449)”。
- 影响范围：主要涉及 后端。
- 改动规模：+282 / -22 行。
- 关键文件：backend/packages/harness/deerflow/models/claude_provider.py；backend/tests/test_claude_provider_prompt_caching.py。

#### 36. fix: use subprocess instead of os.system in local_backend.py (#2494)
- 提交：[`950821c`](https://github.com/bytedance/deer-flow/commit/950821cb9bb7fba773ba88e14cd8ade9f9151b8b)
- 日期：2026-04-25
- 做了什么：修复缺陷或回归问题，主题是“use subprocess instead of os.system in local_backend.py (#2494)”。
- 影响范围：主要涉及 后端。
- 改动规模：+6 / -4 行。
- 关键文件：backend/packages/harness/deerflow/sandbox/local/local_sandbox.py；backend/tests/test_local_sandbox_provider_mounts.py。

#### 37. fix: read lead agent options from context (#2515)
- 提交：[`b970993`](https://github.com/bytedance/deer-flow/commit/b9709934255b2f7f951fd4b2300543ef764e1473)
- 日期：2026-04-24
- 做了什么：修复缺陷或回归问题，主题是“read lead agent options from context (#2515)”。
- 影响范围：主要涉及 后端。
- 改动规模：+139 / -19 行。
- 关键文件：backend/app/gateway/services.py；backend/packages/harness/deerflow/agents/lead_agent/agent.py；backend/tests/test_gateway_services.py；backend/tests/test_lead_agent_model_resolution.py。

#### 38. fix: gate deferred MCP tool execution (#2513)
- 提交：[`ec8a8ca`](https://github.com/bytedance/deer-flow/commit/ec8a8cae38456ece2b0f9a6b32c42382127c5f0e)
- 日期：2026-04-24
- 做了什么：修复缺陷或回归问题，主题是“gate deferred MCP tool execution (#2513)”。
- 影响范围：主要涉及 后端。
- 改动规模：+155 / -1 行。
- 关键文件：backend/packages/harness/deerflow/agents/middlewares/deferred_tool_filter_middleware.py；backend/packages/harness/deerflow/tools/builtins/tool_search.py；backend/tests/test_tool_search.py。

#### 39. fix: inherit subagent skill allowlists (#2514)
- 提交：[`d78ed5c`](https://github.com/bytedance/deer-flow/commit/d78ed5c8f2673da21f1855c74341d7bda15776aa)
- 日期：2026-04-24
- 做了什么：修复缺陷或回归问题，主题是“inherit subagent skill allowlists (#2514)”。
- 影响范围：主要涉及 后端。
- 改动规模：+103 / -3 行。
- 关键文件：backend/packages/harness/deerflow/agents/lead_agent/agent.py；backend/packages/harness/deerflow/tools/builtins/task_tool.py；backend/tests/test_task_tool_core_logic.py。

#### 40. fix(middleware): avoid rescuing non-skill tool outputs during summarization (#2458)
- 提交：[`f9ff3a6`](https://github.com/bytedance/deer-flow/commit/f9ff3a698ddc64dc8dbc7404e0a2f7ef886ef0f8)
- 日期：2026-04-24
- 做了什么：修复缺陷或回归问题，主题是“avoid rescuing non-skill tool outputs during summarization (#2458)”。
- 影响范围：主要涉及 后端、配置。
- 改动规模：+629 / -9 行。
- 关键文件：backend/docs/summarization.md；backend/packages/harness/deerflow/agents/lead_agent/agent.py；backend/packages/harness/deerflow/agents/middlewares/summarization_middleware.py；backend/packages/harness/deerflow/config/summarization_config.py；backend/tests/test_lead_agent_model_resolution.py；backend/tests/test_summarization_middleware.py；config.example.yaml。

#### 41. fix memory settings layout overflow (#2420)
- 提交：[`c2332bb`](https://github.com/bytedance/deer-flow/commit/c2332bb7908e5774763c49cfb77a229832f4f57b)
- 日期：2026-04-24
- 做了什么：修复缺陷或回归问题，主题是“fix memory settings layout overflow (#2420)”。
- 影响范围：主要涉及 前端。
- 改动规模：+11 / -11 行。
- 关键文件：frontend/src/components/workspace/settings/memory-settings-page.tsx；frontend/src/components/workspace/settings/settings-dialog.tsx。

#### 42. fix: keep debug.py interactive terminal free from background log noise (#2466)
- 提交：[`3a61126`](https://github.com/bytedance/deer-flow/commit/3a61126824e9542b630d4181bac50fd101f55010)
- 日期：2026-04-24
- 做了什么：修复缺陷或回归问题，主题是“keep debug.py interactive terminal free from background log noise (#2466)”。
- 影响范围：主要涉及 其他模块、后端。
- 改动规模：+58 / -11 行。
- 关键文件：.gitignore；backend/debug.py。

#### 43. fix(jina): log transient failures at WARNING without traceback (#2484) (#2485)
- 提交：[`e8572b9`](https://github.com/bytedance/deer-flow/commit/e8572b9d0c39fbfcf6b20fdf3d5871912345593a)
- 日期：2026-04-24
- 做了什么：修复缺陷或回归问题，主题是“log transient failures at WARNING without traceback (#2484) (#2485)”。
- 影响范围：主要涉及 后端。
- 改动规模：+24 / -2 行。
- 关键文件：backend/packages/harness/deerflow/community/jina_ai/jina_client.py；backend/tests/test_jina_client.py。

#### 44. fix(backend): fix the unit test error in backend
- 提交：[`80a7446`](https://github.com/bytedance/deer-flow/commit/80a7446fd68651df4ea70cd5d0cb6f86008a26f9)
- 日期：2026-04-24
- 做了什么：修复缺陷或回归问题，主题是“fix the unit test error in backend”。
- 影响范围：主要涉及 后端。
- 改动规模：+0 / -3 行。
- 关键文件：backend/tests/test_task_tool_core_logic.py。

#### 45. fix(backend): Updated the uv.lock with new added dependency
- 提交：[`cd12821`](https://github.com/bytedance/deer-flow/commit/cd12821134f39f06c3ecf0a3598351dc303dbd65)
- 日期：2026-04-24
- 做了什么：修复缺陷或回归问题，主题是“Updated the uv.lock with new added dependency”。
- 影响范围：主要涉及 后端。
- 改动规模：+23 / -0 行。
- 关键文件：backend/uv.lock。

#### 46. fix(gateway): bound lifespan shutdown hooks to prevent worker hang under uvicorn reload (#2331)
- 提交：[`4e72410`](https://github.com/bytedance/deer-flow/commit/4e72410154ebb2c1e055d21b52211ae56c79c3d2)
- 日期：2026-04-23
- 做了什么：修复缺陷或回归问题，主题是“bound lifespan shutdown hooks to prevent worker hang under uvicorn reload (#2331)”。
- 影响范围：主要涉及 后端。
- 改动规模：+84 / -2 行。
- 关键文件：backend/app/gateway/app.py；backend/tests/test_gateway_lifespan_shutdown.py。

#### 47. fix(skills): validate bundled SKILL.md front-matter in CI (fixes #2443) (#2457)
- 提交：[`b90f219`](https://github.com/bytedance/deer-flow/commit/b90f219bd179766227a02f8e33cfa57ba5086d66)
- 日期：2026-04-23
- 做了什么：修复缺陷或回归问题，主题是“validate bundled SKILL.md front-matter in CI (fixes #2443) (#2457)”。
- 影响范围：主要涉及 技能体系、后端。
- 改动规模：+39 / -2 行。
- 关键文件：backend/tests/test_skills_bundled.py；skills/public/bootstrap/SKILL.md；skills/public/chart-visualization/SKILL.md。

#### 48. fix: remove mismatched context param in debug.py to suppress Pydantic warning (#2446)
- 提交：[`c43c803`](https://github.com/bytedance/deer-flow/commit/c43c803f66f595d16fb8227fea241d887a0f30dc)
- 日期：2026-04-23
- 做了什么：修复缺陷或回归问题，主题是“remove mismatched context param in debug.py to suppress Pydantic warning (#2446)”。
- 影响范围：主要涉及 后端。
- 改动规模：+5 / -1 行。
- 关键文件：backend/debug.py。

#### 49. fix: rename present_file to present_files in docs and prompts (#2393)
- 提交：[`5ba1dac`](https://github.com/bytedance/deer-flow/commit/5ba1dacf25085d038db09bf27c5120821f61a777)
- 日期：2026-04-21
- 做了什么：修复缺陷或回归问题，主题是“rename present_file to present_files in docs and prompts (#2393)”。
- 影响范围：主要涉及 后端。
- 改动规模：+4 / -4 行。
- 关键文件：backend/docs/ARCHITECTURE.md；backend/docs/GUARDRAILS.md；backend/packages/harness/deerflow/agents/lead_agent/prompt.py。

#### 50. fix: remove unnecessary f-string prefixes and unused import (#2352)
- 提交：[`085c13e`](https://github.com/bytedance/deer-flow/commit/085c13edc7c2b913fd432422c726fce0f2f81d66)
- 日期：2026-04-20
- 做了什么：修复缺陷或回归问题，主题是“remove unnecessary f-string prefixes and unused import (#2352)”。
- 影响范围：主要涉及 技能体系。
- 改动规模：+8 / -9 行。
- 关键文件：skills/public/data-analysis/scripts/analyze.py；skills/public/skill-creator/eval-viewer/generate_review.py；skills/public/skill-creator/scripts/aggregate_benchmark.py；skills/public/skill-creator/scripts/quick_validate.py；skills/public/skill-creator/scripts/run_loop.py。

#### 51. Fix invalid HTML nesting in reasoning trigger during complex task rendering (#2382)
- 提交：[`ef04174`](https://github.com/bytedance/deer-flow/commit/ef04174194629aa833bb56a4c5326fae860b7113)
- 日期：2026-04-21
- 做了什么：修复缺陷或回归问题，主题是“Fix invalid HTML nesting in reasoning trigger during complex task rendering (#2382)”。
- 影响范围：主要涉及 前端。
- 改动规模：+30 / -2 行。
- 关键文件：frontend/src/components/ai-elements/reasoning.tsx；frontend/tests/unit/core/reasoning-trigger.test.ts。

#### 52. fix: resolve tool duplication and skill parser YAML inconsistencies (#1803) (#2107)
- 提交：[`6dce26a`](https://github.com/bytedance/deer-flow/commit/6dce26a52e1e4c2118b6222c3308fceddf254c37)
- 日期：2026-04-20
- 做了什么：修复缺陷或回归问题，主题是“resolve tool duplication and skill parser YAML inconsistencies (#1803) (#2107)”。
- 影响范围：主要涉及 后端。
- 改动规模：+297 / -193 行。
- 关键文件：backend/packages/harness/deerflow/skills/parser.py；backend/packages/harness/deerflow/tools/tools.py；backend/tests/test_skills_parser.py；backend/tests/test_tool_deduplication.py。

#### 53. fix(setup-agent): prevent data loss when setup fails on existing agen… (#2254)
- 提交：[`fc94e90`](https://github.com/bytedance/deer-flow/commit/fc94e90f6caed2a0198af9836314dc79111c9548)
- 日期：2026-04-20
- 做了什么：修复缺陷或回归问题，主题是“prevent data loss when setup fails on existing agen… (#2254)”。
- 影响范围：主要涉及 后端。
- 改动规模：+91 / -2 行。
- 关键文件：backend/packages/harness/deerflow/tools/builtins/setup_agent_tool.py；backend/tests/test_setup_agent_tool.py。

#### 54. fix command palette hydration mismatch (#2301)
- 提交：[`f2013f4`](https://github.com/bytedance/deer-flow/commit/f2013f47aaf01d6b976fbc17af1473306334888b)
- 日期：2026-04-20
- 做了什么：修复缺陷或回归问题，主题是“fix command palette hydration mismatch (#2301)”。
- 影响范围：主要涉及 前端。
- 改动规模：+2 / -5 行。
- 关键文件：frontend/src/components/ui/command.tsx。

#### 55. fix: use Apple Container image pull syntax (#2366)
- 提交：[`4be857f`](https://github.com/bytedance/deer-flow/commit/4be857f64bf713cf52a8944fb2882aa5126f2c54)
- 日期：2026-04-20
- 做了什么：修复缺陷或回归问题，主题是“use Apple Container image pull syntax (#2366)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+1 / -1 行。
- 关键文件：Makefile。

#### 56. fix(token-usage): enable stream usage for openai-compatible models (#2217)
- 提交：[`c99865f`](https://github.com/bytedance/deer-flow/commit/c99865f53dc7d82a888a326463b146625d128ae2)
- 日期：2026-04-19
- 做了什么：修复缺陷或回归问题，主题是“enable stream usage for openai-compatible models (#2217)”。
- 影响范围：主要涉及 后端。
- 改动规模：+111 / -0 行。
- 关键文件：backend/packages/harness/deerflow/models/factory.py；backend/tests/test_model_factory.py。

#### 57. fix(script): use portable locale for langgraph log pipeline on macOS (#2361)
- 提交：[`05f1da0`](https://github.com/bytedance/deer-flow/commit/05f1da03e5a5eaa7033f98bc02f28fb62930f7f7)
- 日期：2026-04-19
- 做了什么：修复缺陷或回归问题，主题是“use portable locale for langgraph log pipeline on macOS (#2361)”。
- 影响范围：主要涉及 脚本工具。
- 改动规模：+1 / -1 行。
- 关键文件：scripts/serve.sh。

#### 58. fix: Catch httpx.ReadError in the error handling (#2309)
- 提交：[`a62ca5d`](https://github.com/bytedance/deer-flow/commit/a62ca5dd47e3bc9b3a98be699133c9c96e20bf27)
- 日期：2026-04-19
- 做了什么：修复缺陷或回归问题，主题是“Catch httpx.ReadError in the error handling (#2309)”。
- 影响范围：主要涉及 后端。
- 改动规模：+78 / -0 行。
- 关键文件：backend/packages/harness/deerflow/agents/middlewares/llm_error_handling_middleware.py；backend/tests/test_llm_error_handling_middleware.py。

#### 59. fix(backend): make clarification messages idempotent (#2350) (#2351)
- 提交：[`f514e35`](https://github.com/bytedance/deer-flow/commit/f514e35a36f30e3608719e59a0272682df5f1f44)
- 日期：2026-04-19
- 做了什么：修复缺陷或回归问题，主题是“make clarification messages idempotent (#2350) (#2351)”。
- 影响范围：主要涉及 后端。
- 改动规模：+68 / -0 行。
- 关键文件：backend/packages/harness/deerflow/agents/middlewares/clarification_middleware.py；backend/tests/test_clarification_middleware.py。

#### 60. fix(reasoning): prevent LLM-hallucinated HTML tags from rendering as DOM elements (#2321)
- 提交：[`7c87dc5`](https://github.com/bytedance/deer-flow/commit/7c87dc5bcaddefb9bad7448cb8580da303115cdd)
- 日期：2026-04-19
- 做了什么：修复缺陷或回归问题，主题是“prevent LLM-hallucinated HTML tags from rendering as DOM elements (#2321)”。
- 影响范围：主要涉及 前端。
- 改动规模：+24 / -1 行。
- 关键文件：frontend/src/components/ai-elements/reasoning.tsx；frontend/src/core/streamdown/plugins.ts；frontend/tests/unit/core/streamdown/plugins.test.ts。

#### 61. [security] fix(uploads): require explicit opt-in for host-side document conversion (#2332)
- 提交：[`80e210f`](https://github.com/bytedance/deer-flow/commit/80e210f5bb2f346d8e8136aef4694d9dadea48b0)
- 日期：2026-04-18
- 做了什么：修复缺陷或回归问题，主题是“[security] fix(uploads): require explicit opt-in for host-side document conversion (#2332)”。
- 影响范围：主要涉及 后端、配置。
- 改动规模：+144 / -18 行。
- 关键文件：backend/app/gateway/routers/uploads.py；backend/docs/FILE_UPLOAD.md；backend/packages/harness/deerflow/utils/file_conversion.py；backend/tests/test_file_conversion.py；backend/tests/test_uploads_router.py；config.example.yaml。

#### 62. fix(subagent): inherit parent agent's tool_groups in task_tool (#2305)
- 提交：[`5547401`](https://github.com/bytedance/deer-flow/commit/55474011c9fd4e7aac176df0ce580bcf749a596d)
- 日期：2026-04-18
- 做了什么：修复缺陷或回归问题，主题是“inherit parent agent's tool_groups in task_tool (#2305)”。
- 影响范围：主要涉及 后端。
- 改动规模：+134 / -3 行。
- 关键文件：backend/packages/harness/deerflow/agents/lead_agent/agent.py；backend/packages/harness/deerflow/tools/builtins/task_tool.py；backend/tests/test_task_tool_core_logic.py。

#### 63. fix(mcp): prevent RuntimeError from escaping except block in get_cach… (#2252)
- 提交：[`24fe5fb`](https://github.com/bytedance/deer-flow/commit/24fe5fbd8cea7319366495c21b57509c69414d77)
- 日期：2026-04-18
- 做了什么：修复缺陷或回归问题，主题是“prevent RuntimeError from escaping except block in get_cach… (#2252)”。
- 影响范围：主要涉及 后端。
- 改动规模：+7 / -3 行。
- 关键文件：backend/packages/harness/deerflow/mcp/cache.py。

#### 64. fix(scripts): Cloud Provider Reports Security Issue（aliyun could） (#2323)
- 提交：[`1221448`](https://github.com/bytedance/deer-flow/commit/1221448029be6b0cd3553e48a18982baaefad29d)
- 日期：2026-04-18
- 做了什么：修复缺陷或回归问题，主题是“Cloud Provider Reports Security Issue（aliyun could） (#2323)”。
- 影响范围：主要涉及 脚本工具。
- 改动规模：+0 / -5 行。
- 关键文件：scripts/wait-for-port.sh。

#### 65. fix(frontend): add catch-all API rewrite for gateway routes (#2335)
- 提交：[`3b91df2`](https://github.com/bytedance/deer-flow/commit/3b91df2b185678d469375cb8a69b5eeda36b8911)
- 日期：2026-04-18
- 做了什么：修复缺陷或回归问题，主题是“add catch-all API rewrite for gateway routes (#2335)”。
- 影响范围：主要涉及 前端。
- 改动规模：+12 / -0 行。
- 关键文件：frontend/next.config.js。

#### 66. fix(sandbox): add missing path masking in ls_tool output (#2317)
- 提交：[`ca1b7d5`](https://github.com/bytedance/deer-flow/commit/ca1b7d5f48bf46db80898af21d20f1da23ccdf69)
- 日期：2026-04-18
- 做了什么：修复缺陷或回归问题，主题是“add missing path masking in ls_tool output (#2317)”。
- 影响范围：主要涉及 后端。
- 改动规模：+72 / -1 行。
- 关键文件：backend/packages/harness/deerflow/sandbox/tools.py；backend/tests/test_sandbox_search_tools.py。

#### 67. fix: Memory update system has cache corruption, data loss, and thread-safety bugs (#2251)
- 提交：[`898f4e8`](https://github.com/bytedance/deer-flow/commit/898f4e8ac26e44286b1965443fe9fded0ed71b94)
- 日期：2026-04-17
- 做了什么：修复缺陷或回归问题，主题是“Memory update system has cache corruption, data loss, and thread-safety bugs (#2251)”。
- 影响范围：主要涉及 后端。
- 改动规模：+159 / -9 行。
- 关键文件：backend/packages/harness/deerflow/agents/memory/storage.py；backend/packages/harness/deerflow/agents/memory/updater.py；backend/tests/test_memory_storage.py；backend/tests/test_memory_updater.py。

#### 68. fix(checkpointer): create parent directory before opening SQLite in sync provider (#2272)
- 提交：[`a664d2f`](https://github.com/bytedance/deer-flow/commit/a664d2f5c4b2cbeb683e67e8bc48e2654d59695e)
- 日期：2026-04-16
- 做了什么：修复缺陷或回归问题，主题是“create parent directory before opening SQLite in sync provider (#2272)”。
- 影响范围：主要涉及 后端。
- 改动规模：+75 / -1 行。
- 关键文件：backend/packages/harness/deerflow/agents/checkpointer/provider.py；backend/tests/test_checkpointer.py。

#### 69. fix(frontend): make Suggestion button opaque in dark mode (#2276)
- 提交：[`0e16a7f`](https://github.com/bytedance/deer-flow/commit/0e16a7fe55a971f2ec69b9289d97f12e3293e5fd)
- 日期：2026-04-16
- 做了什么：修复缺陷或回归问题，主题是“make Suggestion button opaque in dark mode (#2276)”。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -1 行。
- 关键文件：frontend/src/components/ai-elements/suggestion.tsx。

#### 70. fix(frontend): stop artifact panel from auto-opening on rehydrated write_file (#2278)
- 提交：[`4d3038a`](https://github.com/bytedance/deer-flow/commit/4d3038a7b6c71e5871cf41a7fcbd901df0d7e1ba)
- 日期：2026-04-16
- 做了什么：修复缺陷或回归问题，主题是“stop artifact panel from auto-opening on rehydrated write_file (#2278)”。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -1 行。
- 关键文件：frontend/src/components/workspace/messages/message-group.tsx。

#### 71. fix: validate bootstrap agent names before filesystem writes (#2274)
- 提交：[`2176b2b`](https://github.com/bytedance/deer-flow/commit/2176b2bbfccfce25ceee08318813f96d843a13fd)
- 日期：2026-04-16
- 做了什么：修复缺陷或回归问题，主题是“validate bootstrap agent names before filesystem writes (#2274)”。
- 影响范围：主要涉及 后端。
- 改动规模：+78 / -5 行。
- 关键文件：backend/packages/harness/deerflow/agents/lead_agent/agent.py；backend/packages/harness/deerflow/config/agents_config.py；backend/packages/harness/deerflow/tools/builtins/setup_agent_tool.py；backend/tests/test_lead_agent_model_resolution.py；backend/tests/test_setup_agent_tool.py。

#### 72. fix(frontend):lint error of message-list-item.tsx
- 提交：[`242c654`](https://github.com/bytedance/deer-flow/commit/242c6540752395b2642dd8445df022c4abdf2cec)
- 日期：2026-04-15
- 做了什么：修复缺陷或回归问题，主题是“lint error of message-list-item.tsx”。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -1 行。
- 关键文件：frontend/src/components/workspace/messages/message-list-item.tsx。

#### 73. fix(frontend): lint error of frontend
- 提交：[`0c21cbf`](https://github.com/bytedance/deer-flow/commit/0c21cbf01f096f42fe68f21fecad01ce3a9b1fe8)
- 日期：2026-04-15
- 做了什么：修复缺陷或回归问题，主题是“lint error of frontend”。
- 影响范围：主要涉及 前端。
- 改动规模：+14 / -2 行。
- 关键文件：frontend/src/components/workspace/messages/message-list-item.tsx。

#### 74. fix(frontend): add skills API rewrite rule to prevent HTML fallback (#2241)
- 提交：[`772538d`](https://github.com/bytedance/deer-flow/commit/772538ddbac67c888daccc261532e0006753a4bb)
- 日期：2026-04-15
- 做了什么：修复缺陷或回归问题，主题是“add skills API rewrite rule to prevent HTML fallback (#2241)”。
- 影响范围：主要涉及 前端。
- 改动规模：+8 / -0 行。
- 关键文件：frontend/next.config.js。

#### 75. fix(frontend): resolve /mnt/ links in markdown to artifact API URLs (#2243)
- 提交：[`35fb3dd`](https://github.com/bytedance/deer-flow/commit/35fb3dd65a452c0290f516778e1cea75a9fcbc9c)
- 日期：2026-04-15
- 做了什么：修复缺陷或回归问题，主题是“resolve /mnt/ links in markdown to artifact API URLs (#2243)”。
- 影响范围：主要涉及 前端。
- 改动规模：+8 / -1 行。
- 关键文件：frontend/src/components/workspace/messages/message-list-item.tsx。

#### 76. fix(gateway): forward agent_name and is_bootstrap from context to configurable (#2242)
- 提交：[`692f794`](https://github.com/bytedance/deer-flow/commit/692f79452d56fd14c4aece225abe9784af5c0812)
- 日期：2026-04-15
- 做了什么：修复缺陷或回归问题，主题是“forward agent_name and is_bootstrap from context to configurable (#2242)”。
- 影响范围：主要涉及 后端。
- 改动规模：+2 / -0 行。
- 关键文件：backend/app/gateway/services.py。

#### 77. fix(memory): use asyncio.to_thread for blocking file I/O in aupdate_memory (#2220)
- 提交：[`8760937`](https://github.com/bytedance/deer-flow/commit/8760937439e2722203f7d759414b667f20bbb285)
- 日期：2026-04-14
- 做了什么：修复缺陷或回归问题，主题是“use asyncio.to_thread for blocking file I/O in aupdate_memory (#2220)”。
- 影响范围：主要涉及 后端。
- 改动规模：+6 / -3 行。
- 关键文件：backend/packages/harness/deerflow/agents/memory/storage.py；backend/packages/harness/deerflow/agents/memory/updater.py。

#### 78. fix(todo-middleware): prevent premature agent exit with incomplete todos (#2135)
- 提交：[`e4f896e`](https://github.com/bytedance/deer-flow/commit/e4f896e90d6be14358f64dd2e47af00f6fc82d99)
- 日期：2026-04-14
- 做了什么：修复缺陷或回归问题，主题是“prevent premature agent exit with incomplete todos (#2135)”。
- 影响范围：主要涉及 后端。
- 改动规模：+227 / -2 行。
- 关键文件：backend/packages/harness/deerflow/agents/middlewares/todo_middleware.py；backend/tests/test_todo_middleware.py。

#### 79. fix(backend): fix uploads for mounted sandbox providers (#2199)
- 提交：[`55bc09a`](https://github.com/bytedance/deer-flow/commit/55bc09ac33df555494371ab55d07fdd640feb8ff)
- 日期：2026-04-14
- 做了什么：修复缺陷或回归问题，主题是“fix uploads for mounted sandbox providers (#2199)”。
- 影响范围：主要涉及 后端。
- 改动规模：+51 / -5 行。
- 关键文件：backend/app/gateway/routers/uploads.py；backend/packages/harness/deerflow/community/aio_sandbox/aio_sandbox_provider.py；backend/packages/harness/deerflow/sandbox/local/local_sandbox_provider.py；backend/packages/harness/deerflow/sandbox/sandbox_provider.py；backend/tests/test_uploads_router.py。

#### 80. fix(check): windows pnpm version detection in check script (#2189)
- 提交：[`9cf7153`](https://github.com/bytedance/deer-flow/commit/9cf7153b1d912e4706e86359b3d640a0f9b01f31)
- 日期：2026-04-14
- 做了什么：修复缺陷或回归问题，主题是“windows pnpm version detection in check script (#2189)”。
- 影响范围：主要涉及 后端、脚本工具。
- 改动规模：+72 / -8 行。
- 关键文件：backend/tests/test_check_script.py；scripts/check.py。

#### 81. fix(title): strip <think> tags from title model responses and assistant context (#1927)
- 提交：[`c91785d`](https://github.com/bytedance/deer-flow/commit/c91785dd68e907eda621ae42b83a4c4b00ff15ee)
- 日期：2026-04-14
- 做了什么：修复缺陷或回归问题，主题是“strip <think> tags from title model responses and assistant context (#1927)”。
- 影响范围：主要涉及 后端。
- 改动规模：+54 / -1 行。
- 关键文件：backend/packages/harness/deerflow/agents/middlewares/title_middleware.py；backend/tests/test_title_middleware_core_logic.py。

#### 82. fix(skills): avoid blocking custom skill deletion on readonly history writes (#2197)
- 提交：[`053e18e`](https://github.com/bytedance/deer-flow/commit/053e18e1a6909f92140bf706cc182409c61ceb64)
- 日期：2026-04-14
- 做了什么：修复缺陷或回归问题，主题是“avoid blocking custom skill deletion on readonly history writes (#2197)”。
- 影响范围：主要涉及 后端。
- 改动规模：+87 / -12 行。
- 关键文件：backend/app/gateway/routers/skills.py；backend/tests/test_skills_custom_router.py。

#### 83. fix: disable custom-agent management API by default (#2161)
- 提交：[`a7e7c6d`](https://github.com/bytedance/deer-flow/commit/a7e7c6d667daecbade1c3e6ace992457e9f13f84)
- 日期：2026-04-14
- 做了什么：修复缺陷或回归问题，主题是“disable custom-agent management API by default (#2161)”。
- 影响范围：主要涉及 后端、配置。
- 改动规模：+194 / -6 行。
- 关键文件：backend/app/gateway/routers/agents.py；backend/packages/harness/deerflow/config/agents_api_config.py；backend/packages/harness/deerflow/config/app_config.py；backend/tests/test_app_config_reload.py；backend/tests/test_custom_agent.py；config.example.yaml。

#### 84. fix(middleware): fix present_files thread id fallback (#2181)
- 提交：[`f4c17c6`](https://github.com/bytedance/deer-flow/commit/f4c17c66ce6d49ca6332393ad5c7ae07c7257abf)
- 日期：2026-04-13
- 做了什么：修复缺陷或回归问题，主题是“fix present_files thread id fallback (#2181)”。
- 影响范围：主要涉及 后端。
- 改动规模：+49 / -2 行。
- 关键文件：backend/packages/harness/deerflow/tools/builtins/present_file_tool.py；backend/tests/test_present_file_tool_core_logic.py。

#### 85. fix: wrap blocking readability call with asyncio.to_thread in web_fetch (#2157)
- 提交：[`1df389b`](https://github.com/bytedance/deer-flow/commit/1df389b9d04d41caa56a73a0ad748f439d8b7a80)
- 日期：2026-04-13
- 做了什么：修复缺陷或回归问题，主题是“wrap blocking readability call with asyncio.to_thread in web_fetch (#2157)”。
- 影响范围：主要涉及 后端。
- 改动规模：+30 / -1 行。
- 关键文件：backend/packages/harness/deerflow/community/jina_ai/tools.py；backend/tests/test_jina_client.py。

#### 86. fix(middleware): repair dangling tool-call history after loop interru… (#2035)
- 提交：[`5db71cb`](https://github.com/bytedance/deer-flow/commit/5db71cb68ce58bbcb221493ee6008adffc286c55)
- 日期：2026-04-12
- 做了什么：修复缺陷或回归问题，主题是“repair dangling tool-call history after loop interru… (#2035)”。
- 影响范围：主要涉及 后端、文档。
- 改动规模：+146 / -18 行。
- 关键文件：README.md；backend/CLAUDE.md；backend/packages/harness/deerflow/agents/middlewares/dangling_tool_call_middleware.py；backend/packages/harness/deerflow/agents/middlewares/loop_detection_middleware.py；backend/tests/test_dangling_tool_call_middleware.py；backend/tests/test_loop_detection_middleware.py。

#### 87. fix(sandbox): resolve paths in read_file/write_file content for LocalSandbox (#1935)
- 提交：[`dc50a7f`](https://github.com/bytedance/deer-flow/commit/dc50a7fdfb1f280b8b54af05719518967eaf5c82)
- 日期：2026-04-11
- 做了什么：修复缺陷或回归问题，主题是“resolve paths in read_file/write_file content for LocalSandbox (#1935)”。
- 影响范围：主要涉及 后端。
- 改动规模：+144 / -2 行。
- 关键文件：backend/packages/harness/deerflow/sandbox/local/local_sandbox.py；backend/tests/test_local_sandbox_provider_mounts.py。

#### 88. fix(middleware): add per-tool-type frequency detection to LoopDetectionMiddleware (#1988)
- 提交：[`5b63344`](https://github.com/bytedance/deer-flow/commit/5b633449f8cfcce4117ce467f8fa778274669d2c)
- 日期：2026-04-11
- 做了什么：修复缺陷或回归问题，主题是“add per-tool-type frequency detection to LoopDetectionMiddleware (#1988)”。
- 影响范围：主要涉及 后端。
- 改动规模：+256 / -3 行。
- 关键文件：backend/packages/harness/deerflow/agents/middlewares/loop_detection_middleware.py；backend/tests/test_loop_detection_middleware.py。

#### 89. fix(sandbox): improve sandbox security and preserve multimodal content (#2114)
- 提交：[`0256913`](https://github.com/bytedance/deer-flow/commit/02569136df23006a89b34222e132b975e124a8c2)
- 日期：2026-04-11
- 做了什么：修复缺陷或回归问题，主题是“improve sandbox security and preserve multimodal content (#2114)”。
- 影响范围：主要涉及 后端。
- 改动规模：+25 / -13 行。
- 关键文件：backend/packages/harness/deerflow/agents/middlewares/uploads_middleware.py；backend/packages/harness/deerflow/sandbox/security.py；backend/tests/test_local_bash_tool_loading.py；backend/tests/test_uploads_middleware_core_logic.py。

#### 90. fix(makefile): route Windows shell-script targets through Git Bash (#2060)
- 提交：[`092bf13`](https://github.com/bytedance/deer-flow/commit/092bf13f5e1b3f9f76c08a332051b4bb76257107)
- 日期：2026-04-11
- 做了什么：修复缺陷或回归问题，主题是“route Windows shell-script targets through Git Bash (#2060)”。
- 影响范围：主要涉及 其他模块。
- 改动规模：+23 / -52 行。
- 关键文件：Makefile。

#### 91. fix(sandbox): prevent memory leak in file operation locks using WeakValueDictionary (#2096)
- 提交：[`718dddd`](https://github.com/bytedance/deer-flow/commit/718dddde75c00541e079dab9c1892c44b7a65e6b)
- 日期：2026-04-10
- 做了什么：修复缺陷或回归问题，主题是“prevent memory leak in file operation locks using WeakValueDictionary (#2096)”。
- 影响范围：主要涉及 后端。
- 改动规模：+41 / -1 行。
- 关键文件：backend/packages/harness/deerflow/sandbox/file_operation_lock.py；backend/tests/test_sandbox_tools_security.py。

#### 92. fix(backend): stream DeerFlowClient AI text as token deltas (#1969) (#1974)
- 提交：[`b1aabe8`](https://github.com/bytedance/deer-flow/commit/b1aabe88b8cb3de3b60325d968bacf39777e34c8)
- 日期：2026-04-10
- 做了什么：修复缺陷或回归问题，主题是“stream DeerFlowClient AI text as token deltas (#1969) (#1974)”。
- 影响范围：主要涉及 后端。
- 改动规模：+917 / -56 行。
- 关键文件：backend/CLAUDE.md；backend/docs/README.md；backend/docs/STREAMING.md；backend/packages/harness/deerflow/client.py；backend/tests/test_client.py。

#### 93. fix(frontend): replace invalid "context" select field with "metadata" in threads.search (#2053)
- 提交：[`f889709`](https://github.com/bytedance/deer-flow/commit/f88970985a6732f54ee5835ef67bca6fd2d057fe)
- 日期：2026-04-10
- 做了什么：修复缺陷或回归问题，主题是“replace invalid "context" select field with "metadata" in threads.search (#2053)”。
- 影响范围：主要涉及 前端。
- 改动规模：+42 / -6 行。
- 关键文件：frontend/src/core/threads/hooks.ts；frontend/src/core/threads/utils.test.ts；frontend/src/core/threads/utils.ts。

#### 94. fix(sandbox): add startup reconciliation to prevent orphaned container leaks (#1976)
- 提交：[`0b6fa8b`](https://github.com/bytedance/deer-flow/commit/0b6fa8b9e16ddc1c028b5738f4245585a38fc82f)
- 日期：2026-04-09
- 做了什么：修复缺陷或回归问题，主题是“add startup reconciliation to prevent orphaned container leaks (#1976)”。
- 影响范围：主要涉及 后端。
- 改动规模：+1020 / -4 行。
- 关键文件：backend/packages/harness/deerflow/community/aio_sandbox/aio_sandbox_provider.py；backend/packages/harness/deerflow/community/aio_sandbox/backend.py；backend/packages/harness/deerflow/community/aio_sandbox/local_backend.py；backend/tests/test_sandbox_orphan_reconciliation.py；backend/tests/test_sandbox_orphan_reconciliation_e2e.py。

#### 95. Fix abnormal preview of HTML files (#1986)
- 提交：[`140907c`](https://github.com/bytedance/deer-flow/commit/140907ce1d5ab4b8317f350deeed35e1579c0d1e)
- 日期：2026-04-09
- 做了什么：修复缺陷或回归问题，主题是“Fix abnormal preview of HTML files (#1986)”。
- 影响范围：主要涉及 其他模块、前端。
- 改动规模：+26 / -10 行。
- 关键文件：frontend/src/components/workspace/artifacts/artifact-file-detail.tsx；pr-build/issue1955-after.png；pr-build/issue1955-before.png。

#### 96. fix(frontend): disable incomplete markdown parsing for human messages (#2014)
- 提交：[`52718b0`](https://github.com/bytedance/deer-flow/commit/52718b0f23d527240eaa301024614ad9b7bd3852)
- 日期：2026-04-09
- 做了什么：修复缺陷或回归问题，主题是“disable incomplete markdown parsing for human messages (#2014)”。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -0 行。
- 关键文件：frontend/src/components/workspace/messages/message-list-item.tsx。

#### 97. fix(agent): file-io path guidance in agent prompts (#2019)
- 提交：[`563383c`](https://github.com/bytedance/deer-flow/commit/563383c60fa709b8a44490ac85f8cef5133cee7e)
- 日期：2026-04-09
- 做了什么：修复缺陷或回归问题，主题是“file-io path guidance in agent prompts (#2019)”。
- 影响范围：主要涉及 后端。
- 改动规模：+41 / -1 行。
- 关键文件：backend/packages/harness/deerflow/agents/lead_agent/prompt.py；backend/packages/harness/deerflow/subagents/builtins/bash_agent.py；backend/packages/harness/deerflow/subagents/builtins/general_purpose.py；backend/tests/test_lead_agent_prompt.py；backend/tests/test_subagent_prompt_security.py。

#### 98. fix: resolve missing serialized kwargs in PatchedChatDeepSeek (#2025)
- 提交：[`1b74d84`](https://github.com/bytedance/deer-flow/commit/1b74d8459092c95be1f8613817f47187847722ce)
- 日期：2026-04-09
- 做了什么：修复缺陷或回归问题，主题是“resolve missing serialized kwargs in PatchedChatDeepSeek (#2025)”。
- 影响范围：主要涉及 后端。
- 改动规模：+444 / -0 行。
- 关键文件：backend/packages/harness/deerflow/models/openai_codex_provider.py；backend/packages/harness/deerflow/models/patched_deepseek.py；backend/tests/test_codex_provider.py；backend/tests/test_patched_deepseek.py。

#### 99. fix(docker): dev uv cache mounts on macOS (#2036)
- 提交：[`823f3af`](https://github.com/bytedance/deer-flow/commit/823f3af98c018ff0da66673509ee6d33ab4dca61)
- 日期：2026-04-09
- 做了什么：修复缺陷或回归问题，主题是“dev uv cache mounts on macOS (#2036)”。
- 影响范围：主要涉及 容器部署。
- 改动规模：+10 / -4 行。
- 关键文件：docker/docker-compose-dev.yaml。

#### 100. fix(docker): nginx fails to start on hosts without IPv6 (#2027)
- 提交：[`13664e9`](https://github.com/bytedance/deer-flow/commit/13664e99e7dae7a7eca88f548ff4d00a8716f37a)
- 日期：2026-04-09
- 做了什么：修复缺陷或回归问题，主题是“nginx fails to start on hosts without IPv6 (#2027)”。
- 影响范围：主要涉及 容器部署。
- 改动规模：+9 / -4 行。
- 关键文件：docker/docker-compose-dev.yaml。

#### 101. fix(frontend): preserve agent context in thread history routes (#1771)
- 提交：[`60e0abf`](https://github.com/bytedance/deer-flow/commit/60e0abfdb8cdb7ee8f50722296b22c9a56e296d6)
- 日期：2026-04-09
- 做了什么：修复缺陷或回归问题，主题是“preserve agent context in thread history routes (#1771)”。
- 影响范围：主要涉及 前端。
- 改动规模：+78 / -21 行。
- 关键文件：frontend/src/app/workspace/chats/page.tsx；frontend/src/components/workspace/recent-chat-list.tsx；frontend/src/core/threads/hooks.ts；frontend/src/core/threads/types.ts；frontend/src/core/threads/utils.test.ts；frontend/src/core/threads/utils.ts。

#### 102. fix(models): resolve duplicate keyword argument error when reasoning_effort appears in both config and kwargs (#2017)
- 提交：[`616caa9`](https://github.com/bytedance/deer-flow/commit/616caa92b126c36eb7ad55b86f51578cbeb97d89)
- 日期：2026-04-09
- 做了什么：修复缺陷或回归问题，主题是“resolve duplicate keyword argument error when reasoning_effort appears in both config and kwargs (#2017)”。
- 影响范围：主要涉及 后端。
- 改动规模：+42 / -1 行。
- 关键文件：backend/packages/harness/deerflow/models/factory.py；backend/tests/test_model_factory.py。

#### 103. fix(middleware): handle string-serialized options in ClarificationMiddleware (#1997)
- 提交：[`ad6d934`](https://github.com/bytedance/deer-flow/commit/ad6d934a5fd0bf37ee937e126eb5ade1a6aec7fe)
- 日期：2026-04-08
- 做了什么：修复缺陷或回归问题，主题是“handle string-serialized options in ClarificationMiddleware (#1997)”。
- 影响范围：主要涉及 后端。
- 改动规模：+135 / -0 行。
- 关键文件：backend/packages/harness/deerflow/agents/middlewares/clarification_middleware.py；backend/tests/test_clarification_middleware.py。

#### 104. fix(backend): use timezone-aware UTC in memory modules (fix pytest DeprecationWarnings) (#1992)
- 提交：[`29817c3`](https://github.com/bytedance/deer-flow/commit/29817c3b342b4277b86ec41f0187860112af8035)
- 日期：2026-04-08
- 做了什么：修复缺陷或回归问题，主题是“use timezone-aware UTC in memory modules (fix pytest DeprecationWarnings) (#1992)”。
- 影响范围：主要涉及 后端。
- 改动规模：+17 / -9 行。
- 关键文件：backend/packages/harness/deerflow/agents/memory/queue.py；backend/packages/harness/deerflow/agents/memory/storage.py；backend/packages/harness/deerflow/agents/memory/updater.py。

#### 105. Fix(subagent): Event loop conflict in SubagentExecutor.execute() (#1965)
- 提交：[`e5b1490`](https://github.com/bytedance/deer-flow/commit/e5b149068cc34f2deeaf68a882b36889671ff05e)
- 日期：2026-04-08
- 做了什么：修复缺陷或回归问题，主题是“Event loop conflict in SubagentExecutor.execute() (#1965)”。
- 影响范围：主要涉及 后端。
- 改动规模：+93 / -9 行。
- 关键文件：backend/packages/harness/deerflow/subagents/executor.py；backend/tests/test_subagent_executor.py。

#### 106. fix(frontend): avoid using route new as thread id (#1967)
- 提交：[`85b7ed3`](https://github.com/bytedance/deer-flow/commit/85b7ed3cecc21639d0f05bb3d8cf24ebffef5cff)
- 日期：2026-04-08
- 做了什么：修复缺陷或回归问题，主题是“avoid using route new as thread id (#1967)”。
- 影响范围：主要涉及 前端。
- 改动规模：+10 / -6 行。
- 关键文件：frontend/src/components/workspace/messages/message-list-item.tsx；frontend/src/components/workspace/messages/message-list.tsx。

#### 107. fix(frontend): prevent stale 'new' thread ID from triggering 422 history requests (#1960)
- 提交：[`2480520`](https://github.com/bytedance/deer-flow/commit/24805200f0c8ba8db4a3d3317b2835f7739cf9a7)
- 日期：2026-04-08
- 做了什么：修复缺陷或回归问题，主题是“prevent stale 'new' thread ID from triggering 422 history requests (#1960)”。
- 影响范围：主要涉及 前端。
- 改动规模：+8 / -0 行。
- 关键文件：frontend/src/components/workspace/chats/use-thread-chat.ts。

#### 108. fix(frontend): UI polish - fix CSS typo, dark mode border, and hardcoded colors (#1942)
- 提交：[`d1baf72`](https://github.com/bytedance/deer-flow/commit/d1baf7212bf1616b627c5906c931c3b29ce3f90d)
- 日期：2026-04-08
- 做了什么：修复缺陷或回归问题，主题是“UI polish - fix CSS typo, dark mode border, and hardcoded colors (#1942)”。
- 影响范围：主要涉及 前端。
- 改动规模：+10 / -11 行。
- 关键文件：frontend/src/components/landing/hero.tsx；frontend/src/components/landing/sections/case-study-section.tsx；frontend/src/components/workspace/messages/message-list.tsx；frontend/src/components/workspace/streaming-indicator.tsx；frontend/src/components/workspace/welcome.tsx；frontend/src/styles/globals.css。

#### 109. fix(provider): preserve streamed Codex output when response.completed.output is empty (#1928)
- 提交：[`0948c7a`](https://github.com/bytedance/deer-flow/commit/0948c7a4e1db52ea49072c116a3de65fc7496c71)
- 日期：2026-04-07
- 做了什么：修复缺陷或回归问题，主题是“preserve streamed Codex output when response.completed.output is empty (#1928)”。
- 影响范围：主要涉及 后端。
- 改动规模：+153 / -1 行。
- 关键文件：backend/packages/harness/deerflow/models/openai_codex_provider.py；backend/tests/test_cli_auth_providers.py。

#### 110. fix(backend): make loop detection hash tool calls by stable keys (#1911)
- 提交：[`c3170f2`](https://github.com/bytedance/deer-flow/commit/c3170f22dac766b114d6ec3a962752623b71a4b0)
- 日期：2026-04-07
- 做了什么：修复缺陷或回归问题，主题是“make loop detection hash tool calls by stable keys (#1911)”。
- 影响范围：主要涉及 后端。
- 改动规模：+144 / -18 行。
- 关键文件：backend/packages/harness/deerflow/agents/middlewares/loop_detection_middleware.py；backend/tests/test_loop_detection_middleware.py。

#### 111. fix(frontend): unify local settings runtime state and remove sidebar layout from LocalSettings (#1879)
- 提交：[`1193ac6`](https://github.com/bytedance/deer-flow/commit/1193ac64dcba30febd68b89eec5260dcc0abeba8)
- 日期：2026-04-07
- 做了什么：修复缺陷或回归问题，主题是“unify local settings runtime state and remove sidebar layout from LocalSettings (#1879)”。
- 影响范围：主要涉及 前端。
- 改动规模：+235 / -105 行。
- 关键文件：frontend/src/app/workspace/layout.tsx；frontend/src/components/query-client-provider.tsx；frontend/src/core/settings/hooks.ts；frontend/src/core/settings/index.ts；frontend/src/core/settings/local.ts；frontend/src/core/settings/store.ts。

#### 112. fix(frontend):keep DeerFlow chat thread ids in sync (#1931)
- 提交：[`ab41de2`](https://github.com/bytedance/deer-flow/commit/ab41de2961968873449b25321cd0f0d36a188185)
- 日期：2026-04-07
- 做了什么：修复缺陷或回归问题，主题是“keep DeerFlow chat thread ids in sync (#1931)”。
- 影响范围：主要涉及 前端。
- 改动规模：+34 / -10 行。
- 关键文件：frontend/src/app/workspace/agents/[agent_name]/chats/[thread_id]/page.tsx；frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/workspace/chats/use-thread-chat.ts；frontend/src/core/threads/hooks.ts。

#### 113. Fix agent gallery after bootstrap creation 修复新建智能体后菜单仍为空的问题 (#1934)
- 提交：[`4004fb8`](https://github.com/bytedance/deer-flow/commit/4004fb849f4def372e9e6d9fa0d1a5951a8a48d1)
- 日期：2026-04-07
- 做了什么：修复缺陷或回归问题，主题是“Fix agent gallery after bootstrap creation 修复新建智能体后菜单仍为空的问题 (#1934)”。
- 影响范围：主要涉及 前端。
- 改动规模：+48 / -3 行。
- 关键文件：frontend/src/app/workspace/agents/new/page.tsx。

#### 114. fix(subagents): add cooperative cancellation for subagent threads (#1873)
- 提交：[`f0dd8cb`](https://github.com/bytedance/deer-flow/commit/f0dd8cb0d22bd49cdb6c7efa35ca765403d143da)
- 日期：2026-04-07
- 做了什么：修复缺陷或回归问题，主题是“add cooperative cancellation for subagent threads (#1873)”。
- 影响范围：主要涉及 后端。
- 改动规模：+397 / -7 行。
- 关键文件：backend/packages/harness/deerflow/subagents/executor.py；backend/packages/harness/deerflow/tools/builtins/task_tool.py；backend/tests/test_subagent_executor.py；backend/tests/test_task_tool_core_logic.py。

#### 115. fix(skill): make skill prompt cache refresh nonblocking (#1924)
- 提交：[`7643a46`](https://github.com/bytedance/deer-flow/commit/7643a46fcacccf6160250e1cc635989eba924fc1)
- 日期：2026-04-07
- 做了什么：修复缺陷或回归问题，主题是“make skill prompt cache refresh nonblocking (#1924)”。
- 影响范围：主要涉及 后端。
- 改动规模：+346 / -29 行。
- 关键文件：backend/app/gateway/routers/skills.py；backend/packages/harness/deerflow/agents/__init__.py；backend/packages/harness/deerflow/agents/lead_agent/prompt.py；backend/packages/harness/deerflow/tools/skill_manage_tool.py；backend/tests/test_lead_agent_prompt.py；backend/tests/test_lead_agent_skills.py；backend/tests/test_skill_manage_tool.py；backend/tests/test_skills_custom_router.py。

#### 116. fix(frontend): resolve invalid HTML nesting and tabnabbing vulnerabilities (#1904)
- 提交：[`3acdf79`](https://github.com/bytedance/deer-flow/commit/3acdf79beb5a54c9f23e2a35dee1aa27d242020d)
- 日期：2026-04-07
- 做了什么：修复缺陷或回归问题，主题是“resolve invalid HTML nesting and tabnabbing vulnerabilities (#1904)”。
- 影响范围：主要涉及 前端。
- 改动规模：+45 / -40 行。
- 关键文件：frontend/src/components/workspace/artifacts/artifact-file-detail.tsx；frontend/src/components/workspace/artifacts/artifact-file-list.tsx；frontend/src/components/workspace/messages/message-group.tsx。

#### 117. fix(docker): restore gateway env vars and fix langgraph empty arg issue (#1915)
- 提交：[`2d068cc`](https://github.com/bytedance/deer-flow/commit/2d068cc0750d5c15aa3985cb107aeb247e998785)
- 日期：2026-04-07
- 做了什么：修复缺陷或回归问题，主题是“restore gateway env vars and fix langgraph empty arg issue (#1915)”。
- 影响范围：主要涉及 容器部署。
- 改动规模：+3 / -1 行。
- 关键文件：docker/docker-compose.yaml。

#### 118. fix(sandbox): add input sanitisation guard to SandboxAuditMiddleware (#1872)
- 提交：[`055e4df`](https://github.com/bytedance/deer-flow/commit/055e4df0490dbd1bca9ffc8f6b2330668933223b)
- 日期：2026-04-06
- 做了什么：修复缺陷或回归问题，主题是“add input sanitisation guard to SandboxAuditMiddleware (#1872)”。
- 影响范围：主要涉及 后端。
- 改动规模：+198 / -12 行。
- 关键文件：backend/packages/harness/deerflow/agents/middlewares/sandbox_audit_middleware.py；backend/tests/test_sandbox_audit_middleware.py。

#### 119. fix(backend): preserve viewed image reducer metadata (#1900)
- 提交：[`1ced6e9`](https://github.com/bytedance/deer-flow/commit/1ced6e977c3d5ce7ce999b310d016da98f231736)
- 日期：2026-04-06
- 做了什么：修复缺陷或回归问题，主题是“preserve viewed image reducer metadata (#1900)”。
- 影响范围：主要涉及 后端。
- 改动规模：+14 / -7 行。
- 关键文件：backend/packages/harness/deerflow/agents/middlewares/view_image_middleware.py；backend/tests/test_create_deerflow_agent.py。

#### 120. fix(frontend): artifact download action bounds and lint errors (#1899)
- 提交：[`f5088ed`](https://github.com/bytedance/deer-flow/commit/f5088ed70d9208d4273b8b7e2ed36da5979395ee)
- 日期：2026-04-06
- 做了什么：修复缺陷或回归问题，主题是“artifact download action bounds and lint errors (#1899)”。
- 影响范围：主要涉及 前端。
- 改动规模：+5 / -5 行。
- 关键文件：frontend/src/components/workspace/artifacts/artifact-file-list.tsx。

#### 121. fix: wrap suggestion chips without overlapping input (#1895)
- 提交：[`55e78de`](https://github.com/bytedance/deer-flow/commit/55e78de6fc0e64efc0c7607be4134ffa2a073d35)
- 日期：2026-04-06
- 做了什么：修复缺陷或回归问题，主题是“wrap suggestion chips without overlapping input (#1895)”。
- 影响范围：主要涉及 前端。
- 改动规模：+46 / -42 行。
- 关键文件：frontend/src/components/ai-elements/suggestion.tsx；frontend/src/components/workspace/input-box.tsx。

#### 122. fix: add output truncation to ls_tool to prevent context window overflow (#1896)
- 提交：[`5fd2c58`](https://github.com/bytedance/deer-flow/commit/5fd2c581f6b775d693f01f88ddb68694c56921d9)
- 日期：2026-04-06
- 做了什么：修复缺陷或回归问题，主题是“add output truncation to ls_tool to prevent context window overflow (#1896)”。
- 影响范围：主要涉及 后端、配置。
- 改动规模：+109 / -3 行。
- 关键文件：backend/packages/harness/deerflow/config/sandbox_config.py；backend/packages/harness/deerflow/sandbox/tools.py；backend/tests/test_tool_output_truncation.py；config.example.yaml。

#### 123. fix(docker): command syntax for LANGGRAPH_ALLOW_BLOCKING (#1891)
- 提交：[`d7a3eff`](https://github.com/bytedance/deer-flow/commit/d7a3eff23ea62980eea210560c24f86581d0ad80)
- 日期：2026-04-06
- 做了什么：修复缺陷或回归问题，主题是“command syntax for LANGGRAPH_ALLOW_BLOCKING (#1891)”。
- 影响范围：主要涉及 容器部署。
- 改动规模：+1 / -1 行。
- 关键文件：docker/docker-compose.yaml。

#### 124. fix(frontend): Update route.ts default backend port(#1892)
- 提交：[`ee06440`](https://github.com/bytedance/deer-flow/commit/ee064402055794385877d0e6c5f24641b9eb88f5)
- 日期：2026-04-06
- 做了什么：修复缺陷或回归问题，主题是“Update route.ts default backend port(#1892)”。
- 影响范围：主要涉及 前端。
- 改动规模：+1 / -1 行。
- 关键文件：frontend/src/app/api/memory/route.ts。

#### 125. Fix(#1702): stream resume run (#1858)
- 提交：[`7c68dd4`](https://github.com/bytedance/deer-flow/commit/7c68dd4ad40119f0c210cf68abc72f83e2a8cefe)
- 日期：2026-04-06
- 做了什么：修复缺陷或回归问题，主题是“stream resume run (#1858)”。
- 影响范围：主要涉及 后端、前端。
- 改动规模：+288 / -198 行。
- 关键文件：backend/app/gateway/routers/runs.py；backend/app/gateway/routers/thread_runs.py；backend/app/gateway/services.py；backend/packages/harness/deerflow/runtime/stream_bridge/memory.py；backend/tests/test_stream_bridge.py；frontend/src/core/threads/hooks.ts。

#### 126. fix: expose custom events from DeerFlowClient.stream() (#1827)
- 提交：[`29575c3`](https://github.com/bytedance/deer-flow/commit/29575c32f9a3aa0c98bf1c7107ec1c3ef97884b3)
- 日期：2026-04-06
- 做了什么：修复缺陷或回归问题，主题是“expose custom events from DeerFlowClient.stream() (#1827)”。
- 影响范围：主要涉及 后端。
- 改动规模：+72 / -1 行。
- 关键文件：backend/packages/harness/deerflow/client.py；backend/tests/test_client.py。

#### 127. fix(docker): recover invalid .venv to prevent startup restart loops (#1871)
- 提交：[`ed90a2e`](https://github.com/bytedance/deer-flow/commit/ed90a2ee9d9a972824cece2ffe3a6af658425486)
- 日期：2026-04-06
- 做了什么：修复缺陷或回归问题，主题是“recover invalid .venv to prevent startup restart loops (#1871)”。
- 影响范围：主要涉及 容器部署。
- 改动规模：+2 / -2 行。
- 关键文件：docker/docker-compose-dev.yaml。

#### 128. fix: escape shell variables in production langgraph command (#1877) (#1880)
- 提交：[`993fb0f`](https://github.com/bytedance/deer-flow/commit/993fb0ff9db46f9b2636b4c1d42a8e3fb5b3460b)
- 日期：2026-04-06
- 做了什么：修复缺陷或回归问题，主题是“escape shell variables in production langgraph command (#1877) (#1880)”。
- 影响范围：主要涉及 容器部署。
- 改动规模：+1 / -1 行。
- 关键文件：docker/docker-compose.yaml。

#### 129. fix(channels): normalize slack allowed user ids (#1802)
- 提交：[`117fa9b`](https://github.com/bytedance/deer-flow/commit/117fa9b05d7061cb7733c04e24c7fe190ab21510)
- 日期：2026-04-05
- 做了什么：修复缺陷或回归问题，主题是“normalize slack allowed user ids (#1802)”。
- 影响范围：主要涉及 后端。
- 改动规模：+43 / -2 行。
- 关键文件：backend/app/channels/slack.py；backend/tests/test_channels.py。

#### 130. fix: avoid command palette hydration mismatch on macOS (#1563)
- 提交：[`28474c4`](https://github.com/bytedance/deer-flow/commit/28474c47cbea8db2fcd62a651996eb875bde710c)
- 日期：2026-04-05
- 做了什么：修复缺陷或回归问题，主题是“avoid command palette hydration mismatch on macOS (#1563)”。
- 影响范围：主要涉及 前端。
- 改动规模：+4 / -10 行。
- 关键文件：frontend/src/components/workspace/command-palette.tsx。

#### 131. fix(memory): case-insensitive fact deduplication and positive reinforcement detection (#1804)
- 提交：[`8049785`](https://github.com/bytedance/deer-flow/commit/8049785de666ddeb143693df21e15d76582acba8)
- 日期：2026-04-05
- 做了什么：修复缺陷或回归问题，主题是“case-insensitive fact deduplication and positive reinforcement detection (#1804)”。
- 影响范围：主要涉及 后端。
- 改动规模：+326 / -3 行。
- 关键文件：backend/packages/harness/deerflow/agents/memory/queue.py；backend/packages/harness/deerflow/agents/memory/updater.py；backend/packages/harness/deerflow/agents/middlewares/memory_middleware.py；backend/tests/test_memory_queue.py；backend/tests/test_memory_updater.py；backend/tests/test_memory_upload_filtering.py。

#### 132. fix: preserve virtual path separator style (#1828)
- 提交：[`9ca68ff`](https://github.com/bytedance/deer-flow/commit/9ca68ffaaa00e53784c84cc9c6cd18144e33efc4)
- 日期：2026-04-05
- 做了什么：修复缺陷或回归问题，主题是“preserve virtual path separator style (#1828)”。
- 影响范围：主要涉及 后端。
- 改动规模：+75 / -4 行。
- 关键文件：backend/packages/harness/deerflow/sandbox/tools.py；backend/tests/test_sandbox_tools_security.py。

#### 133. docs: fix some broken links (#1864)
- 提交：[`d3b59a7`](https://github.com/bytedance/deer-flow/commit/d3b59a7931e7fd8bd2ef88b590935de50bd77276)
- 日期：2026-04-05
- 做了什么：修复缺陷或回归问题，主题是“fix some broken links (#1864)”。
- 影响范围：主要涉及 后端、其他模块。
- 改动规模：+4 / -4 行。
- 关键文件：CONTRIBUTING.md；backend/docs/AUTO_TITLE_GENERATION.md；backend/docs/TITLE_GENERATION_IMPLEMENTATION.md。

#### 134. fix(docker): use multi-stage build to remove build-essential from runtime image (#1846)
- 提交：[`e5416b5`](https://github.com/bytedance/deer-flow/commit/e5416b539ae9bb2921e4bf58ed2375a4650e20bf)
- 日期：2026-04-05
- 做了什么：修复缺陷或回归问题，主题是“use multi-stage build to remove build-essential from runtime image (#1846)”。
- 影响范围：主要涉及 后端、容器部署。
- 改动规模：+44 / -7 行。
- 关键文件：backend/Dockerfile；docker/docker-compose-dev.yaml。

#### 135. fix(sandbox): guard against None runtime.context in sandbox tool helpers (#1853)
- 提交：[`72d4347`](https://github.com/bytedance/deer-flow/commit/72d4347adb269f0c9eb9fcb120d7fb5550a6a103)
- 日期：2026-04-05
- 做了什么：修复缺陷或回归问题，主题是“guard against None runtime.context in sandbox tool helpers (#1853)”。
- 影响范围：主要涉及 后端。
- 改动规模：+6 / -3 行。
- 关键文件：backend/packages/harness/deerflow/sandbox/tools.py。

#### 136. fix: include soul field in GET /api/agents list response (fixes #1819) (#1863)
- 提交：[`a283d4a`](https://github.com/bytedance/deer-flow/commit/a283d4a02d701ef9dc514727738646210fd82992)
- 日期：2026-04-04
- 做了什么：修复缺陷或回归问题，主题是“include soul field in GET /api/agents list response (fixes #1819) (#1863)”。
- 影响范围：主要涉及 后端。
- 改动规模：+13 / -4 行。
- 关键文件：backend/app/gateway/routers/agents.py；backend/tests/test_custom_agent.py。

#### 137. fix: unblock concurrent threads and workspace hydration (#1839)
- 提交：[`2a150f5`](https://github.com/bytedance/deer-flow/commit/2a150f5d4ab6c0e9fff504ed59faf521a94aef58)
- 日期：2026-04-04
- 做了什么：修复缺陷或回归问题，主题是“unblock concurrent threads and workspace hydration (#1839)”。
- 影响范围：主要涉及 后端、容器部署、前端。
- 改动规模：+213 / -199 行。
- 关键文件：backend/Makefile；backend/app/gateway/routers/suggestions.py；backend/packages/harness/deerflow/agents/lead_agent/prompt.py；backend/packages/harness/deerflow/agents/middlewares/title_middleware.py；backend/packages/harness/deerflow/config/app_config.py；backend/packages/harness/deerflow/config/extensions_config.py；backend/packages/harness/deerflow/config/paths.py；backend/packages/harness/deerflow/config/skills_config.py。

#### 138. fix(frontend): keep prompt attachments from breaking before upload (#1833)
- 提交：[`1c0051c`](https://github.com/bytedance/deer-flow/commit/1c0051c1db23d9075cadc7ed47f678fd52bf847b)
- 日期：2026-04-04
- 做了什么：修复缺陷或回归问题，主题是“keep prompt attachments from breaking before upload (#1833)”。
- 影响范围：主要涉及 前端。
- 改动规模：+225 / -33 行。
- 关键文件：frontend/src/components/ai-elements/prompt-input.tsx；frontend/src/core/threads/hooks.ts；frontend/src/core/uploads/index.ts；frontend/src/core/uploads/prompt-input-files.test.mjs；frontend/src/core/uploads/prompt-input-files.ts。

#### 139. fix(frontend): block unsupported .app uploads (#1834)
- 提交：[`144c9b2`](https://github.com/bytedance/deer-flow/commit/144c9b2464427d2f388815eff792e864f105d57a)
- 日期：2026-04-04
- 做了什么：修复缺陷或回归问题，主题是“block unsupported .app uploads (#1834)”。
- 影响范围：主要涉及 前端。
- 改动规模：+137 / -9 行。
- 关键文件：frontend/src/components/ai-elements/prompt-input.tsx；frontend/src/core/uploads/file-validation.test.mjs；frontend/src/core/uploads/file-validation.ts；frontend/src/core/uploads/index.ts。

#### 140. fix(uploads): handle split-bold headings and ** ** artefacts in extract_outline (#1838)
- 提交：[`163121d`](https://github.com/bytedance/deer-flow/commit/163121d327560469c508ca1cb324c428fa660700)
- 日期：2026-04-04
- 做了什么：修复缺陷或回归问题，主题是“handle split-bold headings and ** ** artefacts in extract_outline (#1838)”。
- 影响范围：主要涉及 后端。
- 改动规模：+177 / -19 行。
- 关键文件：backend/packages/harness/deerflow/agents/middlewares/uploads_middleware.py；backend/packages/harness/deerflow/utils/file_conversion.py；backend/tests/test_file_conversion.py；backend/tests/test_uploads_middleware_core_logic.py。

#### 141. fix(frontend): resolve button hydration mismatch with undefined variant/size (#1506)
- 提交：[`6473d38`](https://github.com/bytedance/deer-flow/commit/6473d389178465746a3b353e7a534e6e42a5b88c)
- 日期：2026-04-04
- 做了什么：修复缺陷或回归问题，主题是“resolve button hydration mismatch with undefined variant/size (#1506)”。
- 影响范围：主要涉及 前端。
- 改动规模：+2 / -2 行。
- 关键文件：frontend/src/components/ui/button.tsx。

#### 142. fix: use webpack for local frontend dev in serve.sh (#1832)
- 提交：[`4ceb18c`](https://github.com/bytedance/deer-flow/commit/4ceb18c6e4fe5c241ab94446516d2414a7b1b689)
- 日期：2026-04-04
- 做了什么：修复缺陷或回归问题，主题是“use webpack for local frontend dev in serve.sh (#1832)”。
- 影响范围：主要涉及 脚本工具。
- 改动规模：+3 / -1 行。
- 关键文件：scripts/serve.sh。

#### 143. fix: remove nginx Plus-only zone/resolve directives from nginx.conf (#1837)
- 提交：[`fd31058`](https://github.com/bytedance/deer-flow/commit/fd310582bd78ed90534b90058bab9910b78412fc)
- 日期：2026-04-03
- 做了什么：修复缺陷或回归问题，主题是“remove nginx Plus-only zone/resolve directives from nginx.conf (#1837)”。
- 影响范围：主要涉及 容器部署。
- 改动规模：+7 / -8 行。
- 关键文件：docker/nginx/nginx.conf。

#### 144. fix: add missing DEER_FLOW_CONFIG_PATH and DEER_FLOW_EXTENSIONS_CONFIG_PATH env vars to gateway service (fixes #1829) (#1836)
- 提交：[`fb2d99f`](https://github.com/bytedance/deer-flow/commit/fb2d99fd86eeaa997090c830b4f3908d5d78b051)
- 日期：2026-04-03
- 做了什么：修复缺陷或回归问题，主题是“add missing DEER_FLOW_CONFIG_PATH and DEER_FLOW_EXTENSIONS_CONFIG_PATH env vars to gateway service (fixes #1829) (#1836)”。
- 影响范围：主要涉及 容器部署。
- 改动规模：+2 / -0 行。
- 关键文件：docker/docker-compose.yaml。

#### 145. fix(middleware): handle list-type AIMessage.content in LoopDetectionMiddleware (#1823)
- 提交：[`db82b59`](https://github.com/bytedance/deer-flow/commit/db82b5925498f2855cffbf5f52b47164b81de638)
- 日期：2026-04-04
- 做了什么：修复缺陷或回归问题，主题是“handle list-type AIMessage.content in LoopDetectionMiddleware (#1823)”。
- 影响范围：主要涉及 后端。
- 改动规模：+137 / -3 行。
- 关键文件：backend/packages/harness/deerflow/agents/middlewares/loop_detection_middleware.py；backend/tests/test_loop_detection_middleware.py。

#### 146. fix(uploads): fall back to configurable.thread_id when runtime.context lacks thread_id (#1814)
- 提交：[`46d0c32`](https://github.com/bytedance/deer-flow/commit/46d0c329c1b9c975b877aeeb85c864e0baf273c1)
- 日期：2026-04-03
- 做了什么：修复缺陷或回归问题，主题是“fall back to configurable.thread_id when runtime.context lacks thread_id (#1814)”。
- 影响范围：主要涉及 后端。
- 改动规模：+7 / -0 行。
- 关键文件：backend/packages/harness/deerflow/agents/middlewares/uploads_middleware.py。

#### 147. fix: replace the offline link in the lead_agent prompt (#1800)
- 提交：[`a2aba23`](https://github.com/bytedance/deer-flow/commit/a2aba23962528377e5beb763498055ab5c3ce95b)
- 日期：2026-04-03
- 做了什么：修复缺陷或回归问题，主题是“replace the offline link in the lead_agent prompt (#1800)”。
- 影响范围：主要涉及 后端。
- 改动规模：+4 / -4 行。
- 关键文件：backend/packages/harness/deerflow/agents/lead_agent/prompt.py。

#### 148. fix: guarantee END sentinel delivery when stream bridge queue is full (#1695)
- 提交：[`6dbdd46`](https://github.com/bytedance/deer-flow/commit/6dbdd4674f25bc5c7d51fc863ba25ecee7de7b18)
- 日期：2026-04-03
- 做了什么：修复缺陷或回归问题，主题是“guarantee END sentinel delivery when stream bridge queue is full (#1695)”。
- 影响范围：主要涉及 后端。
- 改动规模：+232 / -5 行。
- 关键文件：backend/packages/harness/deerflow/runtime/stream_bridge/memory.py；backend/tests/test_stream_bridge.py。

#### 149. fix: use SystemMessage+HumanMessage for follow-up question generation (#1751)
- 提交：[`83039fa`](https://github.com/bytedance/deer-flow/commit/83039fa22ca3ec8beeda8cf3b788cb6d350ab154)
- 日期：2026-04-03
- 做了什么：修复缺陷或回归问题，主题是“use SystemMessage+HumanMessage for follow-up question generation (#1751)”。
- 影响范围：主要涉及 后端。
- 改动规模：+30 / -5 行。
- 关键文件：backend/app/gateway/routers/suggestions.py；backend/tests/test_suggestions_router.py。

#### 150. fix(ui): avoid follow-up suggestion overlap (#1777)
- 提交：[`9735d73`](https://github.com/bytedance/deer-flow/commit/9735d73b836b60bcfdf547bfccd7b2beaa601317)
- 日期：2026-04-03
- 做了什么：修复缺陷或回归问题，主题是“avoid follow-up suggestion overlap (#1777)”。
- 影响范围：主要涉及 前端。
- 改动规模：+111 / -39 行。
- 关键文件：frontend/src/app/workspace/agents/[agent_name]/chats/[thread_id]/page.tsx；frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/components/workspace/input-box.tsx；frontend/src/components/workspace/messages/message-list.tsx。

#### 151. fix ACP mcpServers payload (#1735)
- 提交：[`4856566`](https://github.com/bytedance/deer-flow/commit/48565664e06760efecaf19489ec4746eec470406)
- 日期：2026-04-03
- 做了什么：修复缺陷或回归问题，主题是“fix ACP mcpServers payload (#1735)”。
- 影响范围：主要涉及 后端。
- 改动规模：+180 / -4 行。
- 关键文件：backend/packages/harness/deerflow/tools/builtins/invoke_acp_agent_tool.py；backend/tests/test_invoke_acp_agent_tool.py。

#### 152. fix: inject longTermBackground into memory prompt (#1734)
- 提交：[`5664b9d`](https://github.com/bytedance/deer-flow/commit/5664b9d413bf3419ba7ea8031a0b808f069f75ff)
- 日期：2026-04-03
- 做了什么：修复缺陷或回归问题，主题是“inject longTermBackground into memory prompt (#1734)”。
- 影响范围：主要涉及 后端。
- 改动规模：+23 / -0 行。
- 关键文件：backend/packages/harness/deerflow/agents/memory/prompt.py；backend/tests/test_memory_prompt_injection.py。

#### 153. fix(ui): avoid over-segmenting cjk messages (#1726)
- 提交：[`952059e`](https://github.com/bytedance/deer-flow/commit/952059eb51dec40c205ea60c60063d42bc7f02d8)
- 日期：2026-04-02
- 做了什么：修复缺陷或回归问题，主题是“avoid over-segmenting cjk messages (#1726)”。
- 影响范围：主要涉及 前端。
- 改动规模：+7 / -0 行。
- 关键文件：frontend/src/core/rehype/index.ts。

#### 154. fix: enable DanglingToolCallMiddleware for subagents (#1766)
- 提交：[`8128a3b`](https://github.com/bytedance/deer-flow/commit/8128a3bc57f06582b4d899d667a5ee9451b9e9de)
- 日期：2026-04-02
- 做了什么：修复缺陷或回归问题，主题是“enable DanglingToolCallMiddleware for subagents (#1766)”。
- 影响范围：主要涉及 后端。
- 改动规模：+1 / -1 行。
- 关键文件：backend/packages/harness/deerflow/agents/middlewares/tool_error_handling_middleware.py。

#### 155. fix(frontend): add missing rel="noopener noreferrer" to target="_blank" links (#1741)
- 提交：[`636053f`](https://github.com/bytedance/deer-flow/commit/636053fb6da8a61681ab2290ef25e32d9e3f4916)
- 日期：2026-04-02
- 做了什么：修复缺陷或回归问题，主题是“add missing rel="noopener noreferrer" to target="_blank" links (#1741)”。
- 影响范围：主要涉及 前端。
- 改动规模：+33 / -14 行。
- 关键文件：frontend/src/components/ai-elements/open-in-chat.tsx；frontend/src/components/ai-elements/sources.tsx；frontend/src/components/landing/header.tsx；frontend/src/components/landing/sections/case-study-section.tsx；frontend/src/components/landing/sections/community-section.tsx；frontend/src/components/workspace/artifacts/artifact-file-detail.tsx；frontend/src/components/workspace/artifacts/artifact-file-list.tsx；frontend/src/components/workspace/messages/message-group.tsx。

#### 156. fix(sandbox): exclude URL paths from absolute path validation (#1385) (#1419)
- 提交：[`f56d0b4`](https://github.com/bytedance/deer-flow/commit/f56d0b4869722111fb4d8ae8ed79e59699acb9e2)
- 日期：2026-04-02
- 做了什么：修复缺陷或回归问题，主题是“exclude URL paths from absolute path validation (#1385) (#1419)”。
- 影响范围：主要涉及 后端。
- 改动规模：+57 / -1 行。
- 关键文件：backend/packages/harness/deerflow/sandbox/tools.py；backend/tests/test_sandbox_tools_security.py。

#### 157. fix: prevent concurrent subagent file write conflicts in sandbox tools (#1714)
- 提交：[`a2cb38f`](https://github.com/bytedance/deer-flow/commit/a2cb38f62bbd1b6d018a3368acd4bfeeff9e2fd2)
- 日期：2026-04-02
- 做了什么：修复缺陷或回归问题，主题是“prevent concurrent subagent file write conflicts in sandbox tools (#1714)”。
- 影响范围：主要涉及 后端。
- 改动规模：+327 / -28 行。
- 关键文件：backend/CLAUDE.md；backend/README.md；backend/packages/harness/deerflow/community/aio_sandbox/aio_sandbox.py；backend/packages/harness/deerflow/sandbox/file_operation_lock.py；backend/packages/harness/deerflow/sandbox/tools.py；backend/tests/test_aio_sandbox.py；backend/tests/test_sandbox_tools_security.py。

#### 158. Fix/1681 llm call retry handling (#1683)
- 提交：[`3a672b3`](https://github.com/bytedance/deer-flow/commit/3a672b39c798604abc5911371c56745260186324)
- 日期：2026-04-02
- 做了什么：修复缺陷或回归问题，主题是“Fix/1681 llm call retry handling (#1683)”。
- 影响范围：主要涉及 后端、前端。
- 改动规模：+428 / -0 行。
- 关键文件：backend/packages/harness/deerflow/agents/middlewares/llm_error_handling_middleware.py；backend/packages/harness/deerflow/agents/middlewares/tool_error_handling_middleware.py；backend/tests/test_llm_error_handling_middleware.py；frontend/src/core/threads/hooks.ts。

#### 159. fix(frontend): persist model selection per thread (#1553)
- 提交：[`0eb6550`](https://github.com/bytedance/deer-flow/commit/0eb6550cf4c3b853056de404f96937bc121f4ae9)
- 日期：2026-04-01
- 做了什么：修复缺陷或回归问题，主题是“persist model selection per thread (#1553)”。
- 影响范围：主要涉及 前端。
- 改动规模：+133 / -44 行。
- 关键文件：frontend/src/app/workspace/agents/[agent_name]/chats/[thread_id]/page.tsx；frontend/src/app/workspace/chats/[thread_id]/page.tsx；frontend/src/core/settings/hooks.ts；frontend/src/core/settings/local.ts。

#### 160. fix: avoid treating Feishu file paths as commands (#1654)
- 提交：[`0a37960`](https://github.com/bytedance/deer-flow/commit/0a379602b80b45a1f91f5815e7171fa5d465fe63)
- 日期：2026-04-01
- 做了什么：修复缺陷或回归问题，主题是“avoid treating Feishu file paths as commands (#1654)”。
- 影响范围：主要涉及 后端。
- 改动规模：+88 / -3 行。
- 关键文件：backend/app/channels/commands.py；backend/app/channels/feishu.py；backend/app/channels/manager.py；backend/tests/test_feishu_parser.py。

#### 161. fix(gateway): prevent 400 error when client sends context with configurable (#1660)
- 提交：[`1fb5ace`](https://github.com/bytedance/deer-flow/commit/1fb5acee3956338f4844f51afb6e30a79219a14f)
- 日期：2026-04-01
- 做了什么：修复缺陷或回归问题，主题是“prevent 400 error when client sends context with configurable (#1660)”。
- 影响范围：主要涉及 后端。
- 改动规模：+103 / -30 行。
- 关键文件：backend/app/gateway/services.py；backend/packages/harness/deerflow/runtime/runs/worker.py；backend/tests/test_gateway_services.py。

#### 162. Fix Windows startup and dependency checks (#1709)
- 提交：[`82c3dbb`](https://github.com/bytedance/deer-flow/commit/82c3dbbc6bb6c7a8e5349144ffd77125d22618b2)
- 日期：2026-04-01
- 做了什么：修复缺陷或回归问题，主题是“Fix Windows startup and dependency checks (#1709)”。
- 影响范围：主要涉及 脚本工具、文档、其他模块。
- 改动规模：+76 / -29 行。
- 关键文件：Makefile；README.md；README_zh.md；scripts/check.py；scripts/config-upgrade.sh；scripts/serve.sh；scripts/start-daemon.sh。

#### 163. fix(skills): support parsing multiline YAML strings in SKILL.md frontmatter (#1703)
- 提交：[`e97c8c9`](https://github.com/bytedance/deer-flow/commit/e97c8c99431ab4f71fe0dde4fd427b14deb1c545)
- 日期：2026-04-01
- 做了什么：修复缺陷或回归问题，主题是“support parsing multiline YAML strings in SKILL.md frontmatter (#1703)”。
- 影响范围：主要涉及 后端。
- 改动规模：+83 / -5 行。
- 关键文件：backend/packages/harness/deerflow/skills/parser.py；backend/tests/test_skills_parser.py。

#### 164. fix: share .deer-flow in docker-compose-dev for uploads (#1718)
- 提交：[`68d44f6`](https://github.com/bytedance/deer-flow/commit/68d44f6755b94047177311c29ad6da0e0ee8ca9d)
- 日期：2026-04-01
- 做了什么：修复缺陷或回归问题，主题是“share .deer-flow in docker-compose-dev for uploads (#1718)”。
- 影响范围：主要涉及 容器部署。
- 改动规模：+2 / -0 行。
- 关键文件：docker/docker-compose-dev.yaml。

#### 165. fix(gateway): merge context field into configurable for langgraph-compat runs (#1699) (#1707)
- 提交：[`c2ff59a`](https://github.com/bytedance/deer-flow/commit/c2ff59a5b172049202a6d4fadd5d4e911c108334)
- 日期：2026-04-01
- 做了什么：修复缺陷或回归问题，主题是“merge context field into configurable for langgraph-compat runs (#1699) (#1707)”。
- 影响范围：主要涉及 后端。
- 改动规模：+146 / -0 行。
- 关键文件：backend/app/gateway/routers/thread_runs.py；backend/app/gateway/services.py；backend/tests/test_gateway_services.py。

#### 166. fix: add --n-jobs-per-worker 10 to local dev Makefile (#1694)
- 提交：[`52c8c06`](https://github.com/bytedance/deer-flow/commit/52c8c06cf27406b91e888d35b27c0f091d004660)
- 日期：2026-04-01
- 做了什么：修复缺陷或回归问题，主题是“add --n-jobs-per-worker 10 to local dev Makefile (#1694)”。
- 影响范围：主要涉及 后端。
- 改动规模：+1 / -1 行。
- 关键文件：backend/Makefile。

#### 167. fix: use safe docker bind mount syntax for sandbox mounts (#1655)
- 提交：[`3e461d9`](https://github.com/bytedance/deer-flow/commit/3e461d9d0896f3395408e9128f809d8744f9b4cf)
- 日期：2026-04-01
- 做了什么：修复缺陷或回归问题，主题是“use safe docker bind mount syntax for sandbox mounts (#1655)”。
- 影响范围：主要涉及 后端。
- 改动规模：+64 / -8 行。
- 关键文件：backend/packages/harness/deerflow/community/aio_sandbox/local_backend.py；backend/tests/test_aio_sandbox_local_backend.py。

#### 168. fix(artifact): enhance artifact content loading to include URL for non-write files (#1678)
- 提交：[`cf43584`](https://github.com/bytedance/deer-flow/commit/cf43584d241f96f2429b656ab95aab49c5227112)
- 日期：2026-04-01
- 做了什么：修复缺陷或回归问题，主题是“enhance artifact content loading to include URL for non-write files (#1678)”。
- 影响范围：主要涉及 前端。
- 改动规模：+15 / -4 行。
- 关键文件：frontend/src/components/workspace/artifacts/artifact-file-detail.tsx；frontend/src/core/artifacts/hooks.ts；frontend/src/core/artifacts/loader.ts。

#### 169. fix(gateway): forward assistant_id as agent_name in build_run_config (#1667)
- 提交：[`6ff60f2`](https://github.com/bytedance/deer-flow/commit/6ff60f2af1a10478329843920c7e8f6937dcbcff)
- 日期：2026-04-01
- 做了什么：修复缺陷或回归问题，主题是“forward assistant_id as agent_name in build_run_config (#1667)”。
- 影响范围：主要涉及 后端。
- 改动规模：+104 / -7 行。
- 关键文件：backend/app/gateway/services.py；backend/tests/test_gateway_services.py。

## 2026-05

- 提交数：20 条

#### 1. fix(config): reset config-backed singletons on hot reload (#2588)
- 提交：[`4ead2c6`](https://github.com/bytedance/deer-flow/commit/4ead2c6b197bcfa863b8381b3e30484060e41e0c)
- 日期：2026-05-06
- 做了什么：修复缺陷或回归问题，主题是“reset config-backed singletons on hot reload (#2588)”。
- 影响范围：主要涉及 后端。
- 改动规模：+259 / -48 行。
- 关键文件：backend/packages/harness/deerflow/config/app_config.py；backend/packages/harness/deerflow/config/checkpointer_config.py；backend/packages/harness/deerflow/config/stream_bridge_config.py；backend/packages/harness/deerflow/config/subagents_config.py；backend/tests/test_app_config_reload.py。

#### 2. fix(loop-detection): keep tool-call pairing on warn injection (#2724) (#2725)
- 提交：[`e8675f2`](https://github.com/bytedance/deer-flow/commit/e8675f266ddfdaa67edd9c13134bfdf8315d7751)
- 日期：2026-05-05
- 做了什么：修复缺陷或回归问题，主题是“keep tool-call pairing on warn injection (#2724) (#2725)”。
- 影响范围：主要涉及 后端。
- 改动规模：+106 / -13 行。
- 关键文件：backend/app/channels/manager.py；backend/packages/harness/deerflow/agents/middlewares/loop_detection_middleware.py；backend/tests/test_channels.py；backend/tests/test_loop_detection_middleware.py。

#### 3. fix: Supplement list_running in RemoteSandboxBackend (#2716)
- 提交：[`680187d`](https://github.com/bytedance/deer-flow/commit/680187ddc26fd94850425b33bd3dd6d414b7631e)
- 日期：2026-05-05
- 做了什么：修复缺陷或回归问题，主题是“Supplement list_running in RemoteSandboxBackend (#2716)”。
- 影响范围：主要涉及 后端。
- 改动规模：+337 / -0 行。
- 关键文件：backend/packages/harness/deerflow/community/aio_sandbox/remote_backend.py；backend/tests/test_remote_sandbox_backend.py。

#### 4. fix(frontend): restore localhost fallback for getGatewayConfig in prod mode (#2705) (#2718)
- 提交：[`aded753`](https://github.com/bytedance/deer-flow/commit/aded753de3981ecda82145439e92e2a5d0db758b)
- 日期：2026-05-05
- 做了什么：修复缺陷或回归问题，主题是“restore localhost fallback for getGatewayConfig in prod mode (#2705) (#2718)”。
- 影响范围：主要涉及 前端、其他模块。
- 改动规模：+131 / -7 行。
- 关键文件：.env.example；frontend/.env.example；frontend/src/core/auth/gateway-config.ts；frontend/tests/unit/core/auth/gateway-config.test.ts。

#### 5. fix(docker):force ngix to resolve upstream names at request time (#2717)
- 提交：[`028493b`](https://github.com/bytedance/deer-flow/commit/028493bfd888a4672b8f36af5b82be36cac98c66)
- 日期：2026-05-05
- 做了什么：修复缺陷或回归问题，主题是“force ngix to resolve upstream names at request time (#2717)”。
- 影响范围：主要涉及 后端、容器部署。
- 改动规模：+20 / -28 行。
- 关键文件：backend/tests/test_gateway_runtime_cleanup.py；docker/nginx/nginx.conf。

#### 6. fix(channels): preserve clarification conversation history across follow-up turns (#2444)
- 提交：[`8e48b7e`](https://github.com/bytedance/deer-flow/commit/8e48b7e85c47625d44c51600b6a496ee5e3c1906)
- 日期：2026-05-04
- 做了什么：修复缺陷或回归问题，主题是“preserve clarification conversation history across follow-up turns (#2444)”。
- 影响范围：主要涉及 后端。
- 改动规模：+138 / -0 行。
- 关键文件：backend/app/channels/manager.py；backend/tests/test_channels.py。

#### 7. fix(i18n): add Chinese translations for account settings page (#2712)
- 提交：[`af6e48c`](https://github.com/bytedance/deer-flow/commit/af6e48ccaaf816cc0990439820b13d59a4499bda)
- 日期：2026-05-04
- 做了什么：修复缺陷或回归问题，主题是“add Chinese translations for account settings page (#2712)”。
- 影响范围：主要涉及 前端。
- 改动规模：+73 / -14 行。
- 关键文件：frontend/src/components/workspace/settings/account-settings-page.tsx；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts；frontend/src/core/i18n/locales/zh-CN.ts。

#### 8. fix(docker): set UTF-8 locale to prevent ASCII encoding errors in minimal containers (#2707)
- 提交：[`82e7936`](https://github.com/bytedance/deer-flow/commit/82e7936d36d603a33e3d3d8d785e180ea6d074f6)
- 日期：2026-05-04
- 做了什么：修复缺陷或回归问题，主题是“set UTF-8 locale to prevent ASCII encoding errors in minimal containers (#2707)”。
- 影响范围：主要涉及 后端。
- 改动规模：+10 / -0 行。
- 关键文件：backend/Dockerfile。

#### 9. fix(frontend): avoid misleading error message when agent api is disable (#2697) (#2698)
- 提交：[`222a777`](https://github.com/bytedance/deer-flow/commit/222a7773cbb6abfd44ca127508c277bbbc39c842)
- 日期：2026-05-04
- 做了什么：修复缺陷或回归问题，主题是“avoid misleading error message when agent api is disable (#2697) (#2698)”。
- 影响范围：主要涉及 前端。
- 改动规模：+31 / -1 行。
- 关键文件：frontend/src/app/workspace/agents/new/page.tsx；frontend/src/core/agents/api.ts；frontend/src/core/i18n/locales/en-US.ts；frontend/src/core/i18n/locales/types.ts；frontend/src/core/i18n/locales/zh-CN.ts。

#### 10. fix(harness): restore legacy skills path fallback (#2694) (#2696)
- 提交：[`f80ac96`](https://github.com/bytedance/deer-flow/commit/f80ac961ec8cf12dec41b36d47c794e25da6b0e4)
- 日期：2026-05-03
- 做了什么：修复缺陷或回归问题，主题是“restore legacy skills path fallback (#2694) (#2696)”。
- 影响范围：主要涉及 后端。
- 改动规模：+63 / -4 行。
- 关键文件：backend/packages/harness/deerflow/config/skills_config.py；backend/tests/test_runtime_paths.py；backend/tests/test_skills_loader.py。

#### 11. [security] fix(upload): reject symlinked upload destinations (#2623)
- 提交：[`e543bbf`](https://github.com/bytedance/deer-flow/commit/e543bbf5d6b657be05e90ca4264c98cc2c3add70)
- 日期：2026-05-02
- 做了什么：修复缺陷或回归问题，主题是“[security] fix(upload): reject symlinked upload destinations (#2623)”。
- 影响范围：主要涉及 后端。
- 改动规模：+369 / -16 行。
- 关键文件：backend/app/channels/manager.py；backend/app/gateway/routers/uploads.py；backend/packages/harness/deerflow/uploads/manager.py；backend/tests/test_channel_file_attachments.py；backend/tests/test_uploads_manager.py；backend/tests/test_uploads_router.py。

#### 12. fix(gateway): return ISO 8601 timestamps from threads endpoints (#2599)
- 提交：[`ca3332f`](https://github.com/bytedance/deer-flow/commit/ca3332f8bf17d848b82cc85863ca955ed5b9adb8)
- 日期：2026-05-02
- 做了什么：修复缺陷或回归问题，主题是“return ISO 8601 timestamps from threads endpoints (#2599)”。
- 影响范围：主要涉及 后端。
- 改动规模：+494 / -32 行。
- 关键文件：backend/app/gateway/routers/threads.py；backend/packages/harness/deerflow/persistence/thread_meta/memory.py；backend/packages/harness/deerflow/runtime/runs/manager.py；backend/packages/harness/deerflow/utils/time.py；backend/tests/test_threads_router.py；backend/tests/test_utils_time.py。

#### 13. fix(runtime): make rollback restore checkpoint supersede newer checkpoints (#2582)
- 提交：[`17447fc`](https://github.com/bytedance/deer-flow/commit/17447fccbe91aa685f5363d85ee2b5c0afa323ce)
- 日期：2026-05-02
- 做了什么：修复缺陷或回归问题，主题是“make rollback restore checkpoint supersede newer checkpoints (#2582)”。
- 影响范围：主要涉及 后端。
- 改动规模：+75 / -19 行。
- 关键文件：backend/app/gateway/routers/threads.py；backend/packages/harness/deerflow/runtime/runs/worker.py；backend/pyproject.toml；backend/tests/test_run_worker_rollback.py。

#### 14. fix(sandbox): pass no_change_timeout to exec_command to prevent 120s premature termination (#2685)
- 提交：[`189b824`](https://github.com/bytedance/deer-flow/commit/189b82405c2b5e65652fe474ad9e1b334277a606)
- 日期：2026-05-01
- 做了什么：修复缺陷或回归问题，主题是“pass no_change_timeout to exec_command to prevent 120s premature termination (#2685)”。
- 影响范围：主要涉及 后端。
- 改动规模：+61 / -3 行。
- 关键文件：backend/packages/harness/deerflow/community/aio_sandbox/aio_sandbox.py；backend/tests/test_aio_sandbox.py。

#### 15. fix(subagents): use model override for tools and middleware (#2641)
- 提交：[`487c1d9`](https://github.com/bytedance/deer-flow/commit/487c1d939fb150d107bf41f9b8a6508e06454610)
- 日期：2026-05-01
- 做了什么：修复缺陷或回归问题，主题是“use model override for tools and middleware (#2641)”。
- 影响范围：主要涉及 后端。
- 改动规模：+219 / -39 行。
- 关键文件：backend/packages/harness/deerflow/agents/middlewares/tool_error_handling_middleware.py；backend/packages/harness/deerflow/subagents/config.py；backend/packages/harness/deerflow/subagents/executor.py；backend/packages/harness/deerflow/tools/builtins/task_tool.py；backend/tests/test_subagent_executor.py；backend/tests/test_task_tool_core_logic.py；backend/tests/test_tool_error_handling_middleware.py。

#### 16. fix(harness): resolve runtime paths from project root (#2642)
- 提交：[`c09c334`](https://github.com/bytedance/deer-flow/commit/c09c33454458f2d6b7dc1c1352a440ba49746072)
- 日期：2026-05-01
- 做了什么：修复缺陷或回归问题，主题是“resolve runtime paths from project root (#2642)”。
- 影响范围：主要涉及 后端、文档、容器部署。
- 改动规模：+284 / -55 行。
- 关键文件：README.md；README_zh.md；backend/docs/CONFIGURATION.md；backend/docs/SETUP.md；backend/packages/harness/deerflow/config/app_config.py；backend/packages/harness/deerflow/config/extensions_config.py；backend/packages/harness/deerflow/config/paths.py；backend/packages/harness/deerflow/config/runtime_paths.py。

#### 17. fix(uploads): enforce streaming upload limits in gateway (#2589)
- 提交：[`8939cca`](https://github.com/bytedance/deer-flow/commit/8939ccaed2f03ba831b16c83605d09b80f36e632)
- 日期：2026-05-01
- 做了什么：修复缺陷或回归问题，主题是“enforce streaming upload limits in gateway (#2589)”。
- 影响范围：主要涉及 后端、配置。
- 改动规模：+393 / -14 行。
- 关键文件：backend/app/gateway/routers/uploads.py；backend/docs/FILE_UPLOAD.md；backend/tests/test_uploads_router.py；config.example.yaml。

#### 18. fix(subagents): propagate user context across threaded execution (#2676)
- 提交：[`83938cf`](https://github.com/bytedance/deer-flow/commit/83938cf35ad3c764378e92efc643ef5feb964f23)
- 日期：2026-05-01
- 做了什么：修复缺陷或回归问题，主题是“propagate user context across threaded execution (#2676)”。
- 影响范围：主要涉及 后端。
- 改动规模：+88 / -10 行。
- 关键文件：backend/packages/harness/deerflow/subagents/executor.py；backend/tests/test_subagent_executor.py。

#### 19. fix(agents): propagate agent_name into ToolRuntime.context for setup_agent (#2679)
- 提交：[`78633c6`](https://github.com/bytedance/deer-flow/commit/78633c69acd20f609c9caf42bcc7854a8cbcdac3)
- 日期：2026-05-01
- 做了什么：修复缺陷或回归问题，主题是“propagate agent_name into ToolRuntime.context for setup_agent (#2679)”。
- 影响范围：主要涉及 后端。
- 改动规模：+133 / -25 行。
- 关键文件：backend/app/gateway/services.py；backend/packages/harness/deerflow/runtime/runs/worker.py；backend/tests/test_gateway_services.py；backend/tests/test_run_worker_rollback.py。

#### 20. fix: keep lead agent graph factory signature compatible (#2678)
- 提交：[`8b61c94`](https://github.com/bytedance/deer-flow/commit/8b61c94e1ddce6d2c0dd7b5d234b3c3987935054)
- 日期：2026-05-01
- 做了什么：修复缺陷或回归问题，主题是“keep lead agent graph factory signature compatible (#2678)”。
- 影响范围：主要涉及 后端。
- 改动规模：+46 / -2 行。
- 关键文件：backend/packages/harness/deerflow/agents/lead_agent/agent.py；backend/tests/test_lead_agent_model_resolution.py。
