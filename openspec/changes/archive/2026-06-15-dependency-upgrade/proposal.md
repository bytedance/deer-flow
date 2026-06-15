# 依赖升级

## Why

项目依赖版本检查发现两类问题：

1. **后端约束最低值过旧**：`pyproject.toml` 中的 `>=` 最低约束与 `uv.lock` 实际解析版本差距悬殊（如 redis 约束 >=5.0.0 但锁文件已解析到 8.0.0）。虽然 `uv lock` 已能获取最新版，但最低约束过旧意味着：新开发者首次 `uv lock` 时若不加 `--upgrade` 可能解析到老版本、依赖解析冲突时回退空间过大、安全审计工具误报"版本落后"。

2. **前端锁文件版本过时**：`pnpm-lock.yaml` 锁定了具体版本，56 个包明确落后于最新稳定版，其中 8 个落后于主版本（typescript 5→6、zod 3→4、eslint 9→10 等），需要实际的代码适配工作。

## What Changes

- **后端约束收紧**: 将 15 个包的最低约束提升到当前 `uv.lock` 已解析的版本（纯文档工作，无代码变更）
- **后端少量 minor 升级**: uvicorn 0.46→0.49、langgraph-sdk 0.3→0.4、langfuse 4.5→4.7、exa-py 2.12→2.13、sse-starlette 3.3→3.4 等约 5 个包需实际升级并验证兼容性
- **后端废弃检查**: 确认 langchain 生态版本耦合无冲突
- **前端小版本批量更新**: ~48 个包的 minor/patch 升级 + 5 个废弃/未使用包清理（@types/gsap、hast、nuxt-og-image、react-hook-form、@hookform/resolvers）
- **前端主版本升级**: typescript 5→6、zod 3→4、eslint 9→10（需源码适配）

## Capabilities

### New Capabilities

- `backend-constraint-tighten`: 后端 pyproject.toml 最低约束收紧，使其与 uv.lock 已解析版本对齐
- `backend-minor-upgrade`: 后端 5 个实际 minor 版本落后包的升级与兼容性验证
- `frontend-dep-upgrade`: 前端依赖批量更新（小版本 + 主版本 + 废弃包清理）

### Modified Capabilities

（无现有 spec 需要修改）

## Impact

- **后端代码**: `backend/pyproject.toml`、`backend/packages/harness/pyproject.toml`、`uv.lock`（约束收紧后需 `uv lock` 重新生成）
- **前端代码**: `frontend/package.json`、`pnpm-lock.yaml`、部分源码（TS 6 / Zod 4 适配）
- **CI/CD**: 锁文件变更后 CI 缓存自动失效重建
- **风险**: 后端实际风险很低（锁文件已是最新版）；前端主版本升级是主要风险点
