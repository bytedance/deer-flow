## MODIFIED Requirements

### Requirement: 工作台用户菜单入口保持简洁

工作台侧边栏底部的用户菜单 SHALL 仅展示“设置”入口，不再展示单独的“关于本系统”入口。

#### Scenario: 用户打开侧边栏底部用户菜单

- **WHEN** 用户点击侧边栏底部的用户信息
- **THEN** 弹出的菜单 SHALL 展示“设置”
- **AND** SHALL NOT 展示“关于本系统”

### Requirement: 工作台公司名称展示一致

工作台前端 SHALL 使用“深圳因思科技有限公司”作为版权与运营主体名称。

#### Scenario: 用户查看关于、页脚、隐私或条款内容

- **WHEN** 页面展示公司名称
- **THEN** 文案 SHALL 使用“深圳因思科技有限公司”
- **AND** SHALL NOT 使用旧公司名称
