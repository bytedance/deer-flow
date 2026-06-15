## Purpose

前端依赖全链路升级：minor/patch 批量更新、废弃包清理、TypeScript 5 → 6、Zod 3 → 4、ESLint 配置现代化（ESLint 10 推迟）。

## Requirements

### Requirement: 前端小版本和补丁批量更新

系统 SHALL 通过 `pnpm update` 更新 ~48 个 minor/patch 落后的依赖，包括 react 19.2.4→19.2.7、next 16.1.7→16.2.9、tailwindcss 4.1.18→4.3.1 等。

#### Scenario: 更新后前端构建成功

- **WHEN** 执行 `pnpm build`
- **THEN** 构建成功，无编译错误

#### Scenario: 更新后前端测试通过

- **WHEN** 执行 `pnpm test`
- **THEN** 所有测试通过

### Requirement: 废弃/未使用包清理

系统 SHALL 移除 `@types/gsap`（gsap 3.x 自带类型）、`nuxt-og-image`（Nuxt 包零引用）、`@hookform/resolvers`（零引用）等废弃包。

hast 迁移到 @types/hast 不可行（TypeScript 禁止直接导入 @types/* 包），hast 保留。

#### Scenario: 移除废弃包后构建正常

- **WHEN** 删除废弃包并执行 `pnpm build`
- **THEN** 无类型错误、无 import 解析错误

### Requirement: TypeScript 5 → 6 升级

系统 SHALL 升级 typescript 到 6.0.3，修复 24 个编译错误（全在测试文件），零新增 lint 问题。

#### Scenario: TypeScript 6 编译通过

- **WHEN** 执行 `pnpm exec tsc --noEmit`
- **THEN** 零错误

#### Scenario: ESLint 检查通过

- **WHEN** 执行 `pnpm exec eslint .`
- **THEN** 无新增错误

### Requirement: Zod 3 → 4 升级

系统 SHALL 升级 zod 到 4.4.3，同步升级 @t3-oss/env-nextjs 到 0.13.11，适配 `z.record(value)` → `z.record(z.string(), value)` 语法变更（5 处）。

#### Scenario: 生态兼容性确认

- **WHEN** 检查 @t3-oss/env-nextjs 的 peerDependencies
- **THEN** 最新稳定版声明支持 zod 4 且兼容 TypeScript 6

#### Scenario: 环境变量解析正常

- **WHEN** 前端启动加载环境变量
- **THEN** @t3-oss/env-nextjs 使用 zod 4 正确解析

### Requirement: ESLint 配置现代化（ESLint 10 推迟）

ESLint 10 因插件生态不兼容推迟。系统 SHALL 升级 eslint-config-next 到 16.2.9，重构 `eslint.config.js` 移除 `FlatCompat`/`@eslint/eslintrc`，直接使用 flat config。

#### Scenario: ESLint 9 检查通过

- **WHEN** 执行 `pnpm exec eslint .`
- **THEN** 无新增错误（预存在问题不阻塞）
