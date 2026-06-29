## Why

嵌入 ui-ehm 的 DeerFlow 工作台需要呈现为更通用的 AI 工作台入口。当前侧边栏品牌区显示 `EHM AI 工作台`，并带有 `E` 方块标识，与嵌套场景下的产品命名不一致。

## What Changes

- 将工作台侧边栏品牌标题改为 `AI工作台`
- 移除工作台侧边栏品牌区的 `E` 方块标识
- 更新相关组件测试，确保展开和折叠状态都不再依赖 `E` 标识

## Capabilities

### Modified Capabilities

- `industrial-navigation-hierarchy`: 工作台导航品牌区展示新的 AI 工作台命名，并去除旧的 EHM 图标标识

## Impact

- `frontend/src/components/workspace/workspace-header.tsx`
- `frontend/tests/unit/components/workspace/workspace-header.test.ts`
- `openspec/specs/industrial-navigation-hierarchy/spec.md`
