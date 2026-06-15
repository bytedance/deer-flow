## Context

项目依赖版本检查（2026-06-13）发现两类问题。

**后端**：`uv.lock` 已将几乎所有"主版本落后"的包解析到最新版（redis 8.0.0、bcrypt 5.0.0、langchain-text-splitters 1.1.2 等）。`pyproject.toml` 中的 `>=` 最低约束仅作为文档/安全网，实际运行版本已是最新。仅 5 个包存在真实的 minor 差距（uvicorn 0.46→0.49、langgraph-sdk 0.3→0.4 等）。

**前端**：`pnpm-lock.yaml` 锁定了具体版本，56 个包落后于最新稳定版。8 个主版本落后（typescript 5→6、zod 3→4、eslint 9→10 等），需要源码适配。

关键约束：
- 后端 Harness / App 分层规则不变
- TDD 强制：升级后必须通过现有测试套件
- 前端 typescript 5→6 和 zod 3→4 是破坏性变更，需源码适配

## Goals / Non-Goals

**Goals:**
- 后端：收紧 15 个包的最低约束使其与 uv.lock 已解析版本对齐；实际升级 5 个 minor 落后包并验证兼容性
- 前端：批量更新 48 个小版本/补丁包；升级 typescript 6、zod 4、eslint 10 并适配源码
- 清理废弃包（@types/gsap、hast）
- 验证 langchain 生态版本耦合无冲突

**Non-Goals:**
- 不改变任何功能行为
- 不引入新依赖
- 不升级 Node.js 运行时版本
- 不处理 nuxt-og-image（若未使用则从 package.json 删除）

## Decisions

### 决策 1：后端以"约束收紧"为主，不做大规模代码变更

**选择**: 后端升级分为两步：
1. 将 15 个包的 `>=` 最低约束提升到 `uv.lock` 已解析版本（纯 pyproject.toml 修改，零代码变更）
2. 对 5 个真正 minor 落后的包执行 `uv lock --upgrade` 并跑全量测试

**理由**: 实际安装版本已是最新，代码已在这些版本上运行。收紧约束只是"把已验证的事实写成文档"，风险极低。

**替代方案**: 按原计划分 3 批升级后端所有主版本。否决原因：审计报告的"主版本落后"是约束最低值的差距，不是实际安装的差距，按原计划做会造成大量不必要的工作。

### 决策 2：前端分 2 批，小版本先行，主版本独立

**选择**:
- **批次 A（低风险）**: ~48 个 minor/patch 包更新 + 废弃包清理。一个 PR。
- **批次 B（高风险，3 个独立 PR）**: typescript 6、zod 4、eslint 10 各自独立 PR，按依赖顺序：TS 6 → Zod 4 → ESLint 10。

**理由**: 小版本更新向后兼容，可批量处理。主版本有 breaking changes，需独立 PR 便于回滚和回归定位。TS 6 先行是因为 Zod 4 的代码适配需要 TS 6 编译。

### 决策 3：升级前先做 langchain 生态耦合验证

**选择**: 在后端升级前，先执行 `uv lock --dry-run` 验证所有 langchain-* 包的版本解析是否一致。如果 langchain-text-splitters 1.1.2 与当前 langchain-core 版本有冲突，需同步升级。

**理由**: langchain 系列包之间有严格的版本耦合关系。虽然锁文件当前正常，但收紧约束后重新解析可能暴露冲突。

### 决策 4：Zod 4 升级前先验证生态兼容性

**选择**: 在开始 Zod 4 适配前，先检查 `@t3-oss/env-nextjs` 的最新版本是否声明支持 Zod 4 且兼容 TypeScript 6。如果不兼容，推迟 Zod 4 升级。`react-hook-form` 和 `@hookform/resolvers` 在项目中零引用，已在 Phase 2 作为死依赖移除，不构成 Zod 4 升级阻碍。

**理由**: Zod 4 于 2025 年底发布，生态支持可能不完善。`@t3-oss/env-nextjs` 是前端唯一仍在使用的 zod 下游包（用于 `src/env.js` 环境变量验证），经实测其 0.13.11 已声明 `zod: "^3.24.0 || ^4.0.0"` 且 `typescript: ">=5.0.0"`，兼容性已确认。

## Risks / Trade-offs

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| 后端约束收紧后 `uv lock` 解析冲突 | 依赖解析失败 | 先用 `uv lock --dry-run` 验证，有冲突则回退约束 |
| uvicorn 0.46→0.49 有 breaking changes | Gateway 启动失败 | 先在测试环境验证，保留回退分支 |
| typescript 5→6 引入新 strict 规则 | 前端编译失败 | 逐个修复编译错误，不跳过 |
| zod 3→4 API 不兼容 | 表单验证/环境变量失效 | 先验证生态兼容性，不兼容则推迟 |
| langchain 生态版本耦合 | langchain-text-splitters 与 langchain-core 不兼容 | 升级前 `uv lock --dry-run` 验证 |
| eslint 10 与 eslint-config-next 不兼容 | lint 检查失败 | 确认 eslint-config-next 16.x 支持 ESLint 10 |

## Migration Plan

### 部署步骤

1. **后端约束收紧 + minor 升级**（1 个 PR）
   - 收紧 15 个包的最低约束
   - `uv lock --upgrade` 升级 5 个 minor 落后包
   - `uv lock --dry-run` 验证 langchain 生态耦合
   - `make test` 全量验证
   - 提交 PR

2. **前端小版本批量更新**（1 个 PR）
   - `pnpm update` 更新 ~48 个包
   - 删除 @types/gsap、hast
   - `pnpm build` + `pnpm test`
   - 提交 PR

3. **前端 TypeScript 6**（1 个 PR）
   - 升级 typescript 5→6
   - 修复编译错误
   - `pnpm check` + `pnpm build` + `pnpm test`
   - 提交 PR

4. **前端 Zod 4**（1 个 PR）
   - 验证生态兼容性
   - 升级 zod 3→4 + @hookform/resolvers + @t3-oss/env-nextjs
   - 适配 schema 语法
   - 提交 PR

5. **前端 ESLint 10**（1 个 PR）
   - 升级 eslint 9→10 + eslint-config-next 16
   - 适配配置格式
   - 提交 PR

### 回滚策略

- 每批 PR 独立，回滚只需 revert 单个 PR
- 锁文件与代码一起回滚
- 无数据库 schema 变更

**PR 回滚独立性：**

| PR | 可独立回滚 | 说明 |
| --- | --- | --- |
| Phase 1 (后端约束) | ✅ 完全独立 | 无前端依赖 |
| Phase 2 (前端小版本) | ✅ 完全独立 | 无后端依赖 |
| Phase 3 (TS 6) | ✅ 完全独立 | 后续 PR 基于此，但回滚 TS 6 只需同时回滚 Phase 4/5 |
| Phase 4 (Zod 4) | ⚠️ 依赖 Phase 3 | 基于 TS 6 编译，回滚 Zod 4 不影响 Phase 3/5 |
| Phase 5 (ESLint 10) | ⚠️ 依赖 Phase 3 | 基于 TS 6 + typescript-eslint 升级，回滚 ESLint 10 不影响 Phase 3/4 |

Phase 3/4/5 是顺序依赖链（TS 6 → Zod 4 → ESLint 10）。如果 Phase 3 需要回滚，Phase 4 和 5 也必须回滚（它们的代码适配基于 TS 6 编译）。反过来，回滚 Phase 4 或 5 不会影响 Phase 3。
