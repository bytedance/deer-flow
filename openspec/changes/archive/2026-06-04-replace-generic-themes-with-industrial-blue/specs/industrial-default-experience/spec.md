# industrial-default-experience Specification

## ADDED Requirements

### Requirement: Industrial-only theme options
系统 SHALL 仅提供工业风主题选项供用户切换。外观设置中 SHALL NOT 显示 next-themes 通用的 "light" 和 "dark" 主题。可用主题 SHALL 限定为：工业蓝 (industrial-blue)、工业深色 (industrial-dark)、工业浅色 (industrial-light)。

#### Scenario: 外观主题列表
- **WHEN** 用户打开外观设置页面
- **THEN** 仅显示三张主题预览卡片：工业蓝、工业深色、工业浅色
- **AND** 不显示"浅色" (light) 和"深色" (dark) 选项

#### Scenario: 遗留主题值回退
- **WHEN** 用户的 localStorage 中存储了 light 或 dark 作为主题偏好值
- **THEN** next-themes 自动回退到默认主题 industrial-dark
- **AND** 用户不会看到白屏或样式缺失

## REMOVED Requirements

### Requirement: Shadcn default themes as user options
**Reason**: "Light" 和 "Dark" 通用主题与产品的工业工程定位不匹配。系统定位为石油石化行业设备管理平台，通用消费级主题不符合品牌调性。
**Migration**: 受影响的用户自动回退到 industrial-dark 主题，无需手动迁移。外观设置页面的主题列表已更新为工业三主题。
