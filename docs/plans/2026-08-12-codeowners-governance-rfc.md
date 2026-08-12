# RFC：关键代码领域 CODEOWNERS 治理

**状态：** Draft
**日期：** 2026-08-12

## 背景

deer-flow 已按 PR 变更范围添加 area、size 和 risk 标签，但关键模块仍依赖维护者手工分配 reviewer。随着模块和 AI 辅助改动增加，高风险 PR 可能缺少熟悉上下文的评审者，评审也容易集中到少数维护者。

本 RFC 建议新增 `.github/CODEOWNERS`，按关键领域自动请求 GitHub Team 评审。

## 目标

- Gateway、Agent Runtime、Sandbox、MCP、持久化、外部集成和前端核心状态等关键代码自动匹配领域 reviewer。
- 每个领域 Team 至少有两名活跃维护者，避免单点。
- CODEOWNERS 和 CI、Docker、依赖配置等治理文件由专门负责人审核。
- 默认分支要求至少一名匹配的 Code Owner 批准后才能合并。

## 非目标

- 本 RFC PR 只提交设计文档，不直接新增 `.github/CODEOWNERS`。
- 不在本 PR 中启用 GitHub ruleset 或修改分支保护。
- 不创建或调整 GitHub Team；Team 名称需在实施 PR 前确认。
- 不改变现有 `area:*`、`size/*`、`risk:*` 自动 label 规则。

## 代码改动

新增 `.github/CODEOWNERS`：

```text
# Gateway / Auth
/backend/app/gateway/                                      @bytedance/deer-flow-gateway
/backend/packages/harness/deerflow/authz/                  @bytedance/deer-flow-gateway

# Agent Runtime
/backend/packages/harness/deerflow/agents/                 @bytedance/deer-flow-runtime
/backend/packages/harness/deerflow/runtime/                @bytedance/deer-flow-runtime
/backend/packages/harness/deerflow/subagents/              @bytedance/deer-flow-runtime

# Sandbox / MCP
/backend/packages/harness/deerflow/sandbox/                @bytedance/deer-flow-sandbox
/backend/packages/harness/deerflow/mcp/                    @bytedance/deer-flow-sandbox
/backend/packages/harness/deerflow/community/aio_sandbox/  @bytedance/deer-flow-sandbox
/backend/packages/harness/deerflow/community/e2b_sandbox/  @bytedance/deer-flow-sandbox

# Persistence
/backend/packages/harness/deerflow/persistence/            @bytedance/deer-flow-data

# Channels / Integrations
/backend/app/channels/                                     @bytedance/deer-flow-integrations
/backend/packages/harness/deerflow/integrations/           @bytedance/deer-flow-integrations

# Frontend thread and message state
/frontend/src/core/threads/                                @bytedance/deer-flow-frontend-core
/frontend/src/core/messages/                               @bytedance/deer-flow-frontend-core
/frontend/src/components/workspace/chats/                  @bytedance/deer-flow-frontend-core
/frontend/src/components/workspace/messages/               @bytedance/deer-flow-frontend-core

# CI / Docker / dependency configuration
/.github/                                                  @bytedance/deer-flow-infra @bytedance/deer-flow-maintainers
/docker/                                                   @bytedance/deer-flow-infra
/scripts/                                                  @bytedance/deer-flow-infra
/Makefile                                                  @bytedance/deer-flow-infra
/backend/Makefile                                          @bytedance/deer-flow-infra
/backend/pyproject.toml                                    @bytedance/deer-flow-infra
/backend/packages/harness/pyproject.toml                   @bytedance/deer-flow-infra
/backend/packages/extension-api/pyproject.toml             @bytedance/deer-flow-infra
/backend/uv.lock                                           @bytedance/deer-flow-infra
/frontend/Makefile                                         @bytedance/deer-flow-infra
/frontend/package.json                                     @bytedance/deer-flow-infra
/frontend/pnpm-lock.yaml                                   @bytedance/deer-flow-infra

# Protect CODEOWNERS itself. Keep this rule after /.github/.
/.github/CODEOWNERS                                        @bytedance/deer-flow-maintainers
```

以上 Team 名为草案。合并前需要替换为实际存在、可见且拥有仓库 write 权限的 GitHub Team；每个 Team 至少包含两名活跃成员。

CODEOWNERS 使用最后一个匹配规则，因此 `/.github/CODEOWNERS` 必须位于 `/.github/` 之后。多个 owner 必须写在同一行。

## 合并规则

在默认分支的 GitHub ruleset 中启用：

- Require a pull request before merging。
- Require review from Code Owners。
- Require approval of the most recent reviewable push。
- Require conversation resolution 和现有 required status checks。

普通 PR 需要至少一名匹配的 Code Owner 批准。同时修改多个关键领域时，作者应请求每个领域 Team 评审；`size/XL` 且 `risk:high` 的 PR 还需一名 maintainer 批准。

GitHub 原生 CODEOWNERS 只保证任意一个匹配 owner 的批准，不保证多个领域分别批准。第一阶段由合并者检查跨领域审批，后续若持续出现漏审，再增加自动检查。

## 验证

- CODEOWNERS 中的所有路径均能匹配现有目录或文件。
- 所有 Team 均存在、可见、拥有 write 权限，并至少有两名活跃成员。
- 修改每个关键领域的测试 PR 能自动请求正确 Team。
- 修改 `.github/CODEOWNERS` 时只请求 maintainer Team。
- 启用 ruleset 后，缺少 Code Owner approval 的 PR 无法合并。

## 参考

- [GitHub：About code owners](https://docs.github.com/en/enterprise-cloud@latest/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/about-code-owners)
- [GitHub：Available rules for rulesets](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets)
