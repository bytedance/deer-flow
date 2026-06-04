## Why

EHM AI 工作台定位为石油石化行业的工业设备智能诊断平台，但外观设置中仍保留了 next-themes 通用的"浅色"和"深色"选项。这两个通用主题与产品的工业工程定位不匹配——它们使用 shadcn/ui 默认的中性灰色系，缺乏工业场景所需的冷峻、专业视觉质感。同时，现有的 industrial-dark/industrial-light 双主题选择偏少，缺少一个带蓝色底调的中间选项来丰富工业主题矩阵。

## What Changes

- **移除**"浅色"(light) 和"深色"(dark) 通用主题选项，从外观设置中彻底隐藏
- **新增** industrial-blue 工业蓝主题，底色带蓝色底调 (oklch chroma 0.022-0.18)，区别于 industrial-dark 的纯灰 (chroma=0)
- Tailwind dark variant 扩展以覆盖 `.industrial-blue` 选择器
- next-themes `themes` 配置更新，移除 light/dark，增加 industrial-blue
- 不改变现有 industrial-dark/industrial-light 的任何颜色值

## Capabilities

### New Capabilities
- `industrial-blue-theme`: 工业蓝 CSS 主题，提供完整的 shadcn/ui 设计令牌集合（background/foreground/card/primary/secondary/muted/accent/destructive/border/input/ring/sidebar 系列/chart 系列），以 oklch 色彩空间定义，锚定 hue 252°（cobalt-steel blue 区间）

### Modified Capabilities
- `industrial-default-experience`: 外观主题选项从 4 项（浅色/深色/工业深色/工业浅色）缩减为 3 项（工业蓝/工业深色/工业浅色），通用 light/dark 主题不再对外暴露

## Impact

- `frontend/src/styles/globals.css` — 新增 `.industrial-blue` CSS 规则块 + 修改 `@custom-variant dark` 选择器
- `frontend/src/components/workspace/settings/appearance-settings-page.tsx` — THEME_OPTIONS 增删改
- `frontend/src/components/theme-provider.tsx` — 确认兼容（无需改动，next-themes 的 forcedTheme 仅用于 landing page）
- `frontend/src/app/layout.tsx` — ThemeProvider 的 `themes` 属性需更新
