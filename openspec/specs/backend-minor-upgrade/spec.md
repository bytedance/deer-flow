## Purpose

后端 minor 版本实际升级与 lint 工具升级，确保运行版本与锁文件一致。

## Requirements

### Requirement: 后端 minor 落后包实际升级

系统 SHALL 升级 uvicorn、langgraph-sdk、langfuse、exa-py 等 minor 落后包到最新兼容版本。详见 `backend-constraint-tighten`。

### Requirement: ruff lint 工具升级

系统 SHALL 将 ruff 从 0.14.11 升级到 0.15.17，修复 643 个 lint 违规（616 自动 + 27 手动）。

#### Scenario: ruff 升级后 lint 通过

- **WHEN** 执行 `make lint`
- **THEN** ruff 检查通过，无新增违规
