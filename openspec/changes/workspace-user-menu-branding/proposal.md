## Why

工作台用户菜单当前在点击用户后展示“设置”和“关于本系统”两个入口。产品期望该弹出内容更简洁，只保留“设置”。同时系统内仍存在旧版权与运营主体文案，需要统一更新为“深圳因思科技有限公司”。

## What Changes

- 用户菜单弹出层仅保留“设置”入口
- 移除用户菜单中的“关于本系统”入口，不影响设置弹窗内部的“关于”页面
- 将前端所有旧公司名称文案统一替换为“深圳因思科技有限公司”

## Capabilities

### Modified Capabilities

- `industrial-navigation-hierarchy`: 工作台用户菜单仅保留设置入口，并统一展示新的公司名称

## Impact

- `frontend/src/components/workspace/workspace-nav-menu.tsx`
- `frontend/src/components/workspace/settings/about-content.ts`
- `frontend/src/components/workspace/settings/about.md`
- `frontend/src/components/landing/footer.tsx`
- `frontend/src/app/privacy/page.tsx`
- `frontend/src/app/terms/page.tsx`
- `openspec/specs/industrial-navigation-hierarchy/spec.md`
