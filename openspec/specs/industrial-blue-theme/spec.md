# industrial-blue-theme Specification

## Purpose
定义工业蓝深色主题的 CSS 设计令牌和视觉行为，为 EHM 工作台提供第三种工业风主题选项。

## Requirements

### Requirement: Industrial Blue CSS Theme
系统 SHALL 提供名为 `industrial-blue` 的 CSS 主题，通过 `.industrial-blue` 类选择器覆盖 shadcn/ui 设计令牌。所有颜色值 SHALL 使用 oklch 色彩空间定义。

底色背景 (--background) SHALL 带有蓝色底调（oklch chroma > 0.01），以区别于 industrial-dark 的中性灰 (chroma = 0)。主色 (--primary) hue SHALL 锚定在 250°-255° 区间。

#### Scenario: 用户切换到工业蓝主题
- **WHEN** 用户在外观设置中选择"工业蓝"主题
- **THEN** `<html>` 元素获得 `industrial-blue` 类
- **AND** 所有页面元素使用蓝色底调的深色配色渲染

#### Scenario: 深色 variant 兼容
- **WHEN** 页面处于 industrial-blue 主题
- **THEN** Tailwind `dark:` variant 的工具类生效（与 industrial-dark 行为一致）

#### Scenario: Alarm 语义色一致性
- **WHEN** 页面处于 industrial-blue 主题
- **THEN** alarm 优先级颜色（critical/high/medium/low/journal）与 industrial-dark 主题一致

### Requirement: Industrial Blue Theme Preview Card
系统 SHALL 在外观设置页面提供工业蓝主题的预览卡片，展示主题名称、图标和色彩预览色条。

#### Scenario: 外观设置显示工业蓝
- **WHEN** 用户打开外观设置页面
- **THEN** 页面上显示"工业蓝"主题卡片，附带蓝色系预览色条和工业图标
