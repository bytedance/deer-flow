## 1. CSS 主题定义

- [x] 1.1 在 `globals.css` 新增 `.industrial-blue` 规则块，定义完整的 shadcn CSS 变量（background/foreground/card/primary/secondary/muted/accent/destructive/border/input/ring/sidebar 系列/chart 系列）
- [x] 1.2 保持 alarm 和 status 语义色与 industrial-dark 一致
- [x] 1.3 修改 `@custom-variant dark` 选择器，添加 `.industrial-blue *` 使其享受 `dark:` variant 覆盖

## 2. 外观设置页面

- [x] 2.1 从 `THEME_OPTIONS` 数组中移除 light 和 dark 选项
- [x] 2.2 新增 industrial-blue 主题项，提供蓝色系预览色条和图标
- [x] 2.3 确保 i18n key 更新（如 `theme.industrialBlue`）或直接使用中文文案

## 3. ThemeProvider 配置

- [x] 3.1 在 `layout.tsx` 中更新 ThemeProvider 的 `themes` 属性为 `["industrial-dark", "industrial-light", "industrial-blue"]`
- [x] 3.2 确认默认主题 `defaultTheme="industrial-dark"` 保持不变

## 4. 验证

- [x] 4.1 搜索项目中是否存在 `light:` Tailwind variant 依赖（确认移除 light 主题不影响现有样式）
- [x] 4.2 TypeScript 类型检查通过（appearance-settings 和 layout 无错误）
- [x] 4.3 验证 localStorage 中遗留 light/dark 值时自动回退到 industrial-dark（next-themes 机制保证）
