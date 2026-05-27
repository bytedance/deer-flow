## 1. 基础架构 — InsProvider 与配置

- [ ] 1.1 创建 `backend/packages/harness/deerflow/community/ins/` 模块目录结构（`__init__.py`, `provider.py`, `tools.py`, `config.py`）
- [ ] 1.2 实现 `InsProvider` 类：封装 INS REST API 调用逻辑，基于 `HttpConnectorConfig` 构建，绑定 `tenant_id` 和认证信息
- [ ] 1.3 实现 Provider 的数据格式化层：将 INS 原始 JSON 响应转换为 Agent 友好的文本（Markdown 表格、摘要统计）
- [ ] 1.4 实现 `get_ins_provider()` 工厂函数：从 `http_connectors` 配置中获取当前租户的 INS 连接器，创建 Provider 实例
- [ ] 1.5 在 `config.example.yaml` 中添加 INS 连接器的配置示例（`http_connectors` 段）
- [ ] 1.6 编写 `InsProvider` 的单元测试：覆盖初始化、认证、租户隔离、错误处理场景

## 2. 核心工具 — 5 个 INS 工具实现

- [ ] 2.1 实现 `ins_get_device_detail` 工具：接收 `device_id`，返回设备名称、型号、测点列表、阈值
- [ ] 2.2 实现 `ins_get_measurement_trend` 工具：接收 `point_id` + `time_range`，返回趋势摘要（最大/最小/平均/标准差/异常点）
- [ ] 2.3 实现 `ins_get_vibration_spectrum` 工具：接收 `device_id` + 可选 `timestamp`，返回 Top 5 频率分量 + 总振值 + 是否超标
- [ ] 2.4 实现 `ins_get_alarm_history` 工具：接收 `device_id` + 可选 `limit`，返回报警记录列表
- [ ] 2.5 实现 `ins_get_peer_comparison` 工具：接收 `device_id`，返回同类设备对标数据
- [ ] 2.6 为每个工具添加输入参数验证（`device_id` 非空、`time_range` 枚举值、`limit` 范围）
- [ ] 2.7 为每个工具实现错误处理：超时返回友好信息、API 不可达返回降级提示、非 JSON 响应返回警告
- [ ] 2.8 编写 5 个工具的单元测试：覆盖正常返回、设备不存在、参数无效、API 超时、认证失败场景

## 3. 工具注册与集成

- [ ] 3.1 在 `tools/tools.py` 的 `BUILTIN_TOOLS` 或配置加载流程中注册 INS 工具（仅当 INS 连接器已配置时注册）
- [ ] 3.2 验证 INS 工具与 `http_connector_tool`、MCP 工具在 `get_available_tools()` 中正常共存
- [ ] 3.3 验证工具名去重逻辑：INS 工具名不与其他工具冲突
- [ ] 3.4 验证租户隔离：不同租户使用各自的 INS 连接器配置
- [ ] 3.5 编写集成测试：模拟完整的 Agent 工具调用链路（工具注册 → Agent 调用 → Provider 调用 INS → 格式化返回）

## 4. Skill 增强 — 诊断工作流声明

- [ ] 4.1 更新 `device-diagnosis` Skill 的 SOUL.md：声明标准诊断流程（确认设备 → 获取详情 → 查历史报警 → 获取频谱 → 综合分析）
- [ ] 4.2 更新 `monitoring-analysis` Skill 的 SOUL.md：声明监测流程（设备状态查询 → 趋势分析 → 同类对标）
- [ ] 4.3 更新 `trend-report` Skill 的 SOUL.md：声明报告生成流程（获取趋势数据 → 获取报警统计 → 同类对标 → 生成报告）
- [ ] 4.4 在所有工业 Skill 的 SOUL.md 中添加 INS 工具不可用时的降级策略说明
- [ ] 4.5 在 SOUL.md 中使用标准化工具引用格式 `<tool>ins_get_device_detail</tool>` 声明工具依赖
- [ ] 4.6 验证自定义 Skill 可以引用 INS 工具（无需额外配置）

## 5. 模板集成 — DSL 扩展与运行时注入

- [ ] 5.1 在报告模板 DSL schema 中添加可选的 `ins_data_requirements` 字段定义
- [ ] 5.2 实现 `ins_data_requirements` 解析器：解析 `tool`、`bind_from`、`params`、`fetch_timing` 字段
- [ ] 5.3 实现 `bind_from` 字段路径解析：从表单步骤输出中提取指定字段值
- [ ] 5.4 实现运行时数据注入逻辑：表单提交后按声明调用 INS 工具，将结果以 `<ins_data>` 标签注入 Agent 上下文
- [ ] 5.5 实现数据获取时机控制：支持 `on_submit`（默认）和 `before_generation` 两种模式
- [ ] 5.6 实现部分失败处理：成功的数据注入，失败的返回错误信息，不阻断报告生成
- [ ] 5.7 实现数据获取去重：相同工具 + 相同参数的调用只执行一次
- [ ] 5.8 编写模板集成的单元测试：覆盖 DSL 解析、bind_from 解析、数据注入、部分失败、去重场景

## 6. 模板编辑器 — INS 数据字段配置 UI

- [ ] 6.1 在模板编辑器面板中添加"添加 INS 数据源"按钮和工具选择列表
- [ ] 6.2 实现 INS 数据需求配置表单：工具选择、参数绑定（从表单步骤字段中选择）、静态参数输入
- [ ] 6.3 实现 `bind_from` 验证：引用的表单步骤必须存在，否则显示验证错误
- [ ] 6.4 实现编辑器 UI 与 DSL `ins_data_requirements` 的双向同步
- [ ] 6.5 在 YAML 编辑器中支持 `ins_data_requirements` 段的显示和编辑
- [ ] 6.6 验证编辑器与 `useTemplateDSL` hook 的集成

## 7. 配置与部署

- [ ] 7.1 在 `config.yaml` 中添加生产环境的 INS 连接器配置（URL、认证方式、超时、缓存 TTL）
- [ ] 7.2 在 `.env` 中添加 INS API 认证 token 的环境变量（`INS_API_TOKEN`）
- [ ] 7.3 编写 INS 工具的配置文档（`backend/docs/INS_TOOLS.md`）：配置步骤、工具列表、参数说明、排障指南
- [ ] 7.4 验证 Docker 部署场景下 INS 工具的网络连通性（容器内访问 INS API）
- [ ] 7.5 验证 `make doctor` 命令能检测 INS 连接器配置的有效性

## 8. 端到端验证

- [ ] 8.1 端到端测试：用户在对话中描述设备问题 → Agent 自动调用 INS 工具 → 输出数据驱动的诊断结论
- [ ] 8.2 端到端测试：用户通过报告模板生成日报 → 模板自动获取 INS 数据 → 报告包含实时设备数据
- [ ] 8.3 端到端测试：INS API 不可用时 → Agent 降级为用户手动提供数据的模式
- [ ] 8.4 端到端测试：多租户场景下 → 租户 A 和租户 B 的 Agent 各自使用自己的 INS 连接器配置
