## ADDED Requirements

### Requirement: 后端 minor 落后包实际升级

（已在 backend-constraint-tighten/spec.md 中定义）

### Requirement: ruff lint 工具升级

系统 SHALL 将 ruff 从 >=0.14.11 升级到最新 minor 版本。ruff 新版本可能引入新 lint 规则，需要在升级后修复新规则报告的违规。

#### Scenario: ruff 升级后 lint 通过

- **WHEN** 执行 `make lint`
- **THEN** ruff 检查通过，无新增违规
