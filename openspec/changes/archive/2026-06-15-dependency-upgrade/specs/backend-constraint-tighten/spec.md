## ADDED Requirements

### Requirement: 后端最低约束收紧至 uv.lock 已解析版本

系统 SHALL 将以下 15 个包的 pyproject.toml 最低约束提升到 uv.lock 已解析的实际版本。这是纯文档工作——锁文件已在使用这些版本，代码已兼容。

约束分两个文件更新：

**`backend/pyproject.toml`（App 层，7 个包）：**

| 包 | 当前约束 | 新约束（= uv.lock 已解析版本） |
| --- | --- | --- |
| fastapi | >=0.115.0 | >=0.136.1 |
| uvicorn | >=0.34.0 | >=0.46.0 |
| sse-starlette | >=2.1.0 | >=3.3.4 |
| langgraph-sdk | >=0.1.51 | >=0.3.13 |
| python-telegram-bot | >=21.0 | >=22.7 |
| wecom-aibot-python-sdk | >=0.1.6 | >=1.0.2 |
| bcrypt | >=4.0.0 | >=5.0.0 |

**`backend/packages/harness/pyproject.toml`（Harness 层，8 个包）：**

| 包 | 当前约束 | 新约束（= uv.lock 已解析版本） | 位置 |
| --- | --- | --- | --- |
| langfuse | >=3.4.1 | >=4.5.1 | dependencies |
| langchain-text-splitters | >=0.3.0 | >=1.1.2 | dependencies |
| firecrawl-py | >=1.15.0 | >=4.23.0 | dependencies |
| markitdown | >=0.0.1a2 | >=0.1.5 | dependencies |
| exa-py | >=1.0.0 | >=2.12.1 | dependencies |
| langgraph-sdk | >=0.1.51 | >=0.3.13 | dependencies |
| redis | >=5.0.0 | >=8.0.0 | [optional] redis |
| langchain-ollama | >=0.3.0 | >=1.1.0 | [optional] ollama |
| pymupdf4llm | >=0.0.17 | >=1.27.2.3 | [optional] pymupdf |

#### Scenario: 约束收紧后 uv lock 解析一致

- **WHEN** 开发者执行 `uv lock`
- **THEN** 锁文件与收紧后的约束一致，无版本降级

#### Scenario: 约束收紧后测试通过

- **WHEN** 执行 `make test`
- **THEN** 所有后端测试通过（因为实际运行版本未变）

### Requirement: 后端 5 个 minor 落后包实际升级

系统 SHALL 升级以下 5 个真正 minor 落后的包到最新版本，并验证兼容性：

| 包 | uv.lock 当前 | 目标最新 |
| --- | --- | --- |
| uvicorn | 0.46.0 | 0.49.0 |
| langgraph-sdk | 0.3.13 | 0.4.2 |
| langfuse | 4.5.1 | 4.7.1 |
| exa-py | 2.12.1 | 2.13.2 |
| sse-starlette | 3.3.4 | 3.4.4 |

#### Scenario: 升级后 uv lock 成功

- **WHEN** 执行 `uv lock --upgrade-package uvicorn --upgrade-package langgraph-sdk --upgrade-package langfuse --upgrade-package exa-py --upgrade-package sse-starlette`
- **THEN** 锁文件成功更新，5 个包升级到目标版本

#### Scenario: 升级后全量测试通过

- **WHEN** 执行 `make test`
- **THEN** 所有后端测试通过

#### Scenario: Gateway 正常启动

- **WHEN** 执行 `make gateway`
- **THEN** Gateway 在端口 8001 正常启动，/health 返回 200

### Requirement: langchain 生态耦合验证

系统 SHALL 在后端升级前验证 langchain 生态包的版本耦合关系：

- langchain-text-splitters 1.1.2 与 langchain-core 版本兼容
- langchain-ollama 1.1.0 与 langchain-core 版本兼容
- langchain-mcp-adapters 与 langchain-core 版本兼容

#### Scenario: 依赖解析无冲突

- **WHEN** 执行 `uv lock --dry-run`
- **THEN** 所有 langchain-* 包解析成功，无版本冲突
