## 背景

DeerFlow 是一个基于 Python 的 AI 智能体系统，需要在现有 Java 微服务体系内运行。目前，Python 后端处于孤立运行状态——既无法被 Java 服务通过 Nacos 发现，也无法调用 Java 微服务的 RPC 接口。这使得 DeerFlow 无法参与更广泛的服务网格，也限制了其利用现有 Java 服务进行数据访问和业务逻辑处理的能力。

## 变更内容

- 添加 Nacos 服务注册，使 Python 网关服务可被其他 Java 微服务发现
- 添加 RPC 客户端层，使 Python 后端能够调用 Java 微服务接口
- 在 `config.yaml` 中添加 Nacos 连接参数和 Java 服务端点的配置支持
- 提供结构化的方式来定义可被 DeerFlow 工具和智能体使用的 Java 服务代理

## 能力

### 新增能力

- `nacos-service-discovery`：将 DeerFlow 网关服务注册到 Nacos（含心跳、元数据、健康状态），使 Java 微服务能够发现并路由请求到 Python 后端。
- `java-rpc-client`：提供 RPC 客户端，使 Python 后端能够调用 Java 微服务接口——包括服务方法调用、序列化、超时/重试处理，以及跨已注册实例的负载均衡。

### 修改的能力

<!-- 无——这是新的集成，不涉及现有规格变更。 -->

## 影响

- **代码**：在 `deerflow/rpc/` 下新增 Python 模块（Nacos 注册 + RPC 客户端），以及在 `deerflow/config/` 下新增相关配置
- **依赖**：新增 Python 依赖——Nacos Python 客户端和 RPC 框架适配器（如 Dubbo Python 客户端或 gRPC）
- **配置**：在 `config.yaml` 中新增 Nacos 服务器地址/命名空间/分组以及 RPC 服务定义的配置段
- **网关**：网关生命周期钩子将在启动/关闭时向 Nacos 注册/注销
