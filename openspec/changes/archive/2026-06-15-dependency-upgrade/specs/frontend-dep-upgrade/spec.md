## ADDED Requirements

### Requirement: 前端小版本和补丁批量更新

系统 SHALL 通过 `pnpm update` 更新 ~48 个 minor/patch 落后的依赖，包括：

| 包 | 当前 | 目标 |
| --- | --- | --- |
| react / react-dom | 19.2.4 | 19.2.7 |
| next | 16.1.7 | 16.2.9 |
| tailwindcss | 4.1.18 | 4.3.1 |
| @tanstack/react-query | 5.90.20 | 5.101.0 |
| motion | 12.34.0 | 12.40.0 |
| ai | 6.0.78 | 6.0.204 |
| echarts | 6.0.0 | 6.1.0 |
| date-fns | 4.1.0 | 4.4.0 |
| zustand | 5.0.13 | 5.0.14 |

#### Scenario: 更新后前端构建成功

- **WHEN** 执行 `pnpm build`
- **THEN** 构建成功，无编译错误

#### Scenario: 更新后前端测试通过

- **WHEN** 执行 `pnpm test`
- **THEN** 所有测试通过

### Requirement: 废弃/未使用包清理

系统 SHALL 移除以下废弃、多余及未使用的 npm 包：

| 包 | 处理方式 | 原因 |
| --- | --- | --- |
| @types/gsap | 直接删除 | gsap 3.x 自带类型定义 |
| nuxt-og-image | 直接删除 | Nuxt 包，在 Next.js 项目中确认零引用 |
| hast | 先迁移 import 再删除 | 先将 `src/core/rehype/index.ts` 中 `import type { ... } from "hast"` 改为 `from "@types/hast"`，验证编译通过后删除（`@types/hast` 保留） |
| react-hook-form | 直接删除 | 全项目搜索 `useForm`/`useController`/`react-hook-form` 零匹配，未使用 |
| @hookform/resolvers | 直接删除 | 依赖 react-hook-form，一并移除 |

#### Scenario: 移除 @types/gsap 后构建正常

- **WHEN** 删除 `@types/gsap` 并执行 `pnpm build`
- **THEN** gsap 类型从 gsap 包自身解析，无类型错误

#### Scenario: 移除 hast 后构建正常

- **WHEN** 将 hast 类型 import 迁移到 `@types/hast`，删除 `hast` 包，执行 `pnpm build`
- **THEN** 无类型错误、无 import 解析错误

#### Scenario: 移除 nuxt-og-image 后构建正常

- **WHEN** 删除 `nuxt-og-image` 并执行 `pnpm build`
- **THEN** 无 import 错误

#### Scenario: 移除 react-hook-form + @hookform/resolvers 后构建正常

- **WHEN** 删除 `react-hook-form` 和 `@hookform/resolvers` 并执行 `pnpm build`
- **THEN** 无类型错误、无 import 错误（两者在项目中零引用）

### Requirement: TypeScript 5 → 6 升级

系统 SHALL 升级 typescript 到 6.x，修复所有编译错误，同步升级 typescript-eslint 到兼容版本。

#### Scenario: TypeScript 6 编译通过

- **WHEN** 执行 `pnpm exec tsc --noEmit`
- **THEN** 零错误

#### Scenario: ESLint 检查通过

- **WHEN** 执行 `pnpm exec eslint .`
- **THEN** 无错误

### Requirement: Zod 3 → 4 升级

系统 SHALL 在确认生态兼容性后升级 zod 到 4.x，同步升级 @t3-oss/env-nextjs，适配所有 schema 语法变更。

若 @t3-oss/env-nextjs 最新稳定版不支持 zod 4，SHALL 推迟此升级。

#### Scenario: 生态兼容性确认

- **WHEN** 检查 @t3-oss/env-nextjs 的 peerDependencies
- **THEN** 最新稳定版声明支持 zod 4 且兼容 TypeScript 6

#### Scenario: 环境变量解析正常

- **WHEN** 前端启动加载环境变量
- **THEN** @t3-oss/env-nextjs 使用 zod 4 正确解析

### Requirement: ESLint 9 → 10 升级

系统 SHALL 升级 eslint 到 10.x，同步升级 eslint-config-next 到 16.x，适配配置格式变更。

#### Scenario: ESLint 10 检查通过

- **WHEN** 执行 `pnpm exec eslint .`
- **THEN** 无错误，配置兼容 ESLint 10
