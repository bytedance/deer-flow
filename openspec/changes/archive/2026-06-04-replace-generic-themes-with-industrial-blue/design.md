## Context

EHM 工作台当前有 4 个主题：通用的 light/dark（shadcn/ui 默认配色），以及两套工业定制主题 industrial-dark 和 industrial-light。所有主题通过 next-themes 管理，CSS 变量在 `globals.css` 中定义，Tailwind 通过 `@custom-variant dark` 处理深色主题选择器。

工业蓝作为第三个工业主题，需要与现有架构一致：纯 CSS 变量覆盖，不引入额外的 JS 运行时逻辑。

## Goals / Non-Goals

**Goals:**
- 移除 light/dark 通用主题，用户只能在工业主题间切换
- 新增 industrial-blue 主题，底色带蓝色底调的深色方案
- 工业蓝主题继承 industrial-dark 的 alarm/status 语义色
- 现有 industrial-dark/industrial-light 颜色值不变

**Non-Goals:**
- 不创建"工业蓝浅色版"——本变更仅新增一个深色基调主题
- 不修改 next-themes 的持久化或切换机制
- 不影响 landing page 的 forcedTheme="industrial-dark" 行为
- 不修改其他组件对 `dark:` Tailwind variant 的依赖

## Decisions

### 1. industrial-blue 放在 `.industrial-blue` 类选择器中

**选择**: 与 industrial-dark/industrial-light 一致，使用独立的 CSS 类 `.industrial-blue` 覆盖变量。

**备选**: 使用 `data-theme="industrial-blue"` 属性选择器。但现有主题统一用类选择器，保持一致性。

### 2. Tailwind dark variant 扩展

**选择**: 将 `@custom-variant dark` 从 `&:is(.dark *, .industrial-dark *)` 扩展为 `&:is(.dark *, .industrial-dark *, .industrial-blue *)`。

**理由**: 工业蓝是深色基调主题，依赖 `dark:` 前缀的工具类来处理 Muted、Accent 等面板颜色。不扩展则 `dark:bg-muted` 等类在工业蓝下不生效。

### 3. 工业蓝色相锚定 252°

**选择**: Hue 252°（cobalt-steel blue），primary chroma 0.18，surface chroma 0.022。

**备选方案 A**: Hue 240°（纯蓝）。更蓝但偏紫，在低饱和度表面显得"脏"。
**备选方案 B**: Hue 265°（indigo）。偏紫，与现有品牌蓝差异太大。

**理由**: 252° 在纯蓝和靛蓝之间，低 chroma 表面保持"冷钢蓝"质感，不会偏紫也不会偏青。

### 4. 不改变 ThemeProvider 逻辑

**选择**: ThemeProvider 的 `forcedTheme`（仅 landing page 强制 industrial-dark）和 `themes` 属性由 layout.tsx 管理，不在 provider 中添加硬编码逻辑。

**理由**: 主题列表是配置而非逻辑，应在使用侧（layout.tsx）声明。

## Risks / Trade-offs

- **[低风险] industrial-blue 的 `muted` 和 `muted-foreground` 对比度不足** → 上线前在真机上验证 WCAG AA 对比度（4.5:1）。必要时将 muted-foreground 的 lightness 从 0.63 提升到 0.68。
- **[低风险] 现有用户 localStorage 中可能有 light/dark 主题残留** → next-themes 的 `themes` 属性限制可选值后，非法值会回退到默认主题（industrial-dark）。无需迁移脚本。
- **[无风险] 移除 light/dark 后，依赖 `light:` variant 的 Tailwind 类失效** → 搜索确认项目中无 `light:` variant 使用。
