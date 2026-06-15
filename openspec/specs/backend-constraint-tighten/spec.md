## Purpose

后端依赖最低约束收紧至 uv.lock 已解析版本 + minor 落后包实际升级 + ruff lint 工具升级。确保声明的版本约束与实际使用的版本一致，防止未来依赖解析漂移。

## Requirements

### Requirement: 后端最低约束收紧至 uv.lock 已解析版本

系统 SHALL 将 `backend/pyproject.toml`（App 层）和 `backend/packages/harness/pyproject.toml`（Harness 层）中依赖的最低约束提升到 uv.lock 已解析的实际版本。

App 层 7 个包: fastapi, uvicorn, sse-starlette, langgraph-sdk, python-telegram-bot, wecom-aibot-python-sdk, bcrypt。

Harness 层 9 个包: langfuse, langchain-text-splitters, firecrawl-py, markitdown, exa-py, langgraph-sdk, redis [optional], langchain-ollama [optional], pymupdf4llm [optional]。

#### Scenario: 约束收紧后 uv lock 解析一致

- **WHEN** 开发者执行 `uv lock`
- **THEN** 锁文件与收紧后的约束一致，无版本降级

#### Scenario: 约束收紧后测试通过

- **WHEN** 执行 `make test`
- **THEN** 所有后端测试通过（因为实际运行版本未变）

### Requirement: 后端 minor 落后包实际升级

系统 SHALL 升级 uvicorn、langgraph-sdk、langfuse、exa-py 到最新 minor 版本（sse-starlette 受 langgraph-api 约束保持 3.3.4），并验证兼容性。

同时升级 langgraph-api 0.8.1 → 0.10.0（EOL 修复），联动升级 langgraph-cli、langgraph-runtime-inmem、starlette。

#### Scenario: 升级后 uv lock 成功

- **WHEN** 执行 `uv lock --upgrade-package <packages>`
- **THEN** 锁文件成功更新到目标版本

#### Scenario: 升级后全量测试通过

- **WHEN** 执行 `make test`
- **THEN** 所有后端测试通过

#### Scenario: Gateway 正常启动

- **WHEN** 执行 `make gateway`
- **THEN** Gateway 在端口 8001 正常启动，/health 返回 200

### Requirement: langchain 生态耦合验证

系统 SHALL 在后端升级前验证 langchain 生态包的版本耦合关系无冲突。

#### Scenario: 依赖解析无冲突

- **WHEN** 执行 `uv lock --dry-run`
- **THEN** 所有 langchain-* 包解析成功，无版本冲突

### Requirement: ruff lint 工具升级

系统 SHALL 将 ruff 从 0.14.11 升级到 0.15.17，修复新规则报告的违规。

#### Scenario: ruff 升级后 lint 通过

- **WHEN** 执行 `make lint`
- **THEN** ruff 检查通过，无新增违规

### Requirement: postgres 可选依赖安装修复

`config.yaml` 默认 `backend: postgres` 时系统 SHALL 确保 postgres 可选依赖被安装。

#### Scenario: Postgres checkpointer 正常启动

- **WHEN** `config.yaml` 使用 `database.backend: postgres`
- **THEN** postgres 可选依赖已安装，checkpointer 连接成功
