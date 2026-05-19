# Nacos 服务发现

## 目的

通过 Nacos 实现 DeerFlow 网关实例的服务注册、心跳维持和优雅注销，支持可配置的连接参数和启动容错。

## 新增需求

### 需求：启动时服务注册

系统必须在 FastAPI 应用启动时将 DeerFlow 网关实例注册到 Nacos，提供服务名称、IP、端口和元数据。

#### 场景：注册成功
- **当** 网关应用完成启动
- **则** 服务实例注册到 Nacos，并每 5 秒发送一次心跳

#### 场景：关闭时优雅注销
- **当** 网关应用关闭
- **则** 在进程退出前从 Nacos 注销服务实例

#### 场景：启动时 Nacos 不可用
- **当** 注册期间 Nacos 不可达
- **则** 网关正常启动，记录警告，并通过指数退避重试注册

### 需求：服务心跳

系统必须定期向 Nacos 发送心跳请求，以维持服务实例的健康状态。

#### 场景：心跳保持实例存活
- **当** 服务已注册且正在运行
- **则** 按配置的间隔（默认 5 秒）向 Nacos 发送心跳

#### 场景：心跳丢失导致过期
- **当** 网关进程崩溃或被非优雅终止
- **则** Nacos 在配置的超时后将实例标记为不健康，并最终移除

### 需求：Nacos 配置

系统必须通过 `config.yaml` 中的 `nacos` 段支持 Nacos 连接参数。当 `nacos` 为 `null` 或不存在时，整个 Nacos 服务发现功能处于禁用状态，不影响系统正常启动和运行。

#### 场景：包含所有参数的配置
- **当** `config.yaml` 的 `nacos` 段包含 `server_addr`、`namespace`、`group`、`service.name`、`service.ip`、`service.port`、`service.weight`、`service.metadata`、`heartbeat.interval`、`heartbeat.timeout`、`retry.max_attempts`、`retry.base_delay`、`retry.max_delay`
- **则** 所有参数均用于 Nacos 服务注册

#### 场景：使用默认值的最小配置
- **当** `config.yaml` 只包含 `nacos.server_addr` 和 `nacos.namespace`
- **则** 应用默认值：group=`DEFAULT_GROUP`，service_name=`deer-flow-gateway`，service_ip=自动检测，service_port=8001，weight=1.0，heartbeat_interval=5s，heartbeat_timeout=15s，retry 使用指数退避

#### 场景：未配置 Nacos 时禁用
- **当** `config.yaml` 中 `nacos` 字段为 `null` 或不存在
- **则** Nacos 服务发现功能静默禁用，网关正常启动，不尝试注册，不发送心跳

### 需求：Nacos 配置模型

系统必须通过 Pydantic 模型管理 Nacos 配置，遵循项目现有的单例配置模式（与 `MemoryConfig` 一致），并由 `AppConfig` 统一加载。

#### 场景：Pydantic 模型校验
- **当** `nacos` 配置中包含无效值（如 `heartbeat.interval` 超出 1-30 范围）
- **则** `AppConfig.from_file()` 启动时抛出 `ValidationError`，明确提示错误字段

#### 场景：配置热重载
- **当** `config.yaml` 文件在运行中被修改
- **则** 下一次 `get_app_config()` 调用自动检测 mtime 变化并重新加载 Nacos 配置，无需重启进程

#### 场景：环境变量替换
- **当** `nacos.server_addr` 的值以 `$` 开头（如 `$NACOS_SERVER_ADDR`）
- **则** 系统自动从环境变量中解析实际值，与项目中 `$OPENAI_API_KEY` 的行为一致
