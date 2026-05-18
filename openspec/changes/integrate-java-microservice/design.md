## 背景

DeerFlow 是一个独立运行的 Python FastAPI 应用。现有 Java 微服务体系使用 Nacos 进行服务发现，使用 Dubbo（或类似的 RPC 框架）进行服务间通信。DeerFlow Python 后端需要：

1. **被外部发现**：向 Nacos 注册中心注册自身，使 Java 服务能够将请求路由到它
2. **调用 Java 服务**：调用 Java 微服务 RPC 接口以访问共享业务逻辑

Python 后端运行在 8001 端口（网关）。Nacos 服务器地址、命名空间和分组随环境而异。Java 服务对外暴露接口——DeerFlow 需要使用带类型的参数调用这些接口上的特定方法。

## 目标 / 非目标

**目标：**
- 在启动时自动向 Nacos 注册 DeerFlow 网关，发送心跳，并在关闭时注销
- 提供通用的 RPC 客户端层，用于调用通过 Nacos 发现到的 Java 服务
- 支持基于 JSON 的 RPC 调用序列化（Python/Java 之间兼容性最好）
- 与现有 `config.yaml` 配置系统集成

**非目标：**
- 双向 Dubbo 协议支持（Python 侧原生 Dubbo 协议）——不在初期集成范围内；使用 HTTP/JSON-RPC 作为桥接
- 服务网格 / Sidecar 代理（如 Envoy）——保持在应用层面
- Java 服务通过 Dubbo 调用 Python——Python 服务通过 Nacos REST API 注册；Java 服务通过标准 Nacos 发现来找到它

## 决策

### 决策 1：采用 HTTP + JSON-RPC 而非原生 Dubbo 协议

**理由**：Dubbo 原生二进制协议的 Python 客户端支持有限。HTTP/JSON-RPC 通用性好，易于调试，足以满足 AI 智能体典型的请求/响应模式（非高吞吐流式场景）。Java 服务可以通过 Spring Cloud Gateway 或 Dubbo 的 REST 协议暴露 HTTP 端点。

**已考虑的替代方案**：
- *Dubbo Python SDK (dubbo-python)*：生态不成熟，文档有限，序列化复杂
- *gRPC*：需要 Python 和 Java 团队共享 proto 定义；对于初期集成来说过于繁琐

### 决策 2：使用 Nacos Open API 进行服务注册（不使用 SDK）

**理由**：Nacos 提供了简洁的 REST API 用于服务注册（`/nacos/v1/ns/instance`）。直接使用 HTTP API 避免了对特定 Nacos Python SDK 的依赖，SDK 可能滞后于服务器版本。注册格式文档完善且稳定。

**已考虑的替代方案**：
- *nacos-sdk-python*：增加了版本耦合风险的依赖；REST API 已经足够简洁

### 决策 3：配置驱动的服务定义

**理由**：要调用的 Java 服务声明式地定义在 `config.yaml` 的新 `rpc.services` 段中。每个条目指定：服务名称（用于 Nacos 查找）、base URL 或发现方式，以及接口方法及其路径和 HTTP 方法。

这与 `config.yaml` 中 `http_connectors` 的现有模式相一致。

### 决策 4：遵循项目现有配置单例模式

**理由**：Nacos 和 RPC 配置与项目中 `MemoryConfig`、`AuthConfig` 等模块采用完全一致的模式——Pydantic `BaseModel` + 模块级单例 + `load_*_config_from_dict()` + `AppConfig` 统一加载。当 `nacos` 为 `null` 时整个功能静默禁用。

**具体结构**：

`config.yaml` 示例：
```yaml
# Nacos 服务发现（设为 null 或不配置则禁用）
nacos:
  server_addr: "127.0.0.1:8848"   # 必填，支持 $NACOS_SERVER_ADDR
  namespace: ""                    # 命名空间ID，空=public
  group: "DEFAULT_GROUP"
  service:
    name: "deer-flow-gateway"
    ip: ""                         # 留空自动检测
    port: 8001
    weight: 1.0
    metadata:
      version: "1.0"
  heartbeat:
    interval: 5                    # 秒
    timeout: 15                    # 秒，Nacos 实例过期时间
  retry:
    max_attempts: 10
    base_delay: 1.0
    max_delay: 60.0

# Java RPC 客户端（设为 null 或不配置则禁用）
rpc:
  default_timeout: 30.0
  default_retry:
    max_attempts: 3
    backoff_factor: 0.5
  services:
    - name: "user-service"
      discovery: "user-service"    # Nacos 服务名
      endpoints:
        - method: "getUserById"
          path: "/api/user/{id}"
          http_method: "GET"
```

Pydantic 模型层次：
```
AppConfig
├── nacos: NacosConfig | None     # None = 禁用
│   ├── server_addr: str
│   ├── namespace: str
│   ├── group: str
│   ├── service: NacosServiceConfig
│   │   ├── name: str
│   │   ├── ip: str
│   │   ├── port: int
│   │   ├── weight: float
│   │   └── metadata: dict
│   ├── heartbeat: NacosHeartbeatConfig
│   │   ├── interval: int (1-30)
│   │   └── timeout: int (5-60)
│   └── retry: NacosRetryConfig
│       ├── max_attempts: int (0-100)
│       ├── base_delay: float
│       └── max_delay: float
└── rpc: RpcConfig | None          # None = 禁用
    ├── default_timeout: float
    ├── default_retry: RpcRetryConfig
    └── services: list[RpcServiceConfig]
        ├── name: str
        ├── discovery: str | None
        ├── base_url: str | None
        ├── timeout: float | None
        └── endpoints: list[RpcEndpointConfig]
            ├── method: str
            ├── path: str
            └── http_method: str (GET|POST|PUT|DELETE)
```

**集成点**：在 `AppConfig._apply_singleton_configs()` 中注册：
```python
if config.nacos is not None:
    load_nacos_config_from_dict(config.nacos.model_dump())
if config.rpc is not None:
    load_rpc_config_from_dict(config.rpc.model_dump())
```

## 风险 / 权衡

- **启动时 Nacos 不可用**：DeerFlow 网关应在 Nacos 不可达时仍能正常启动，记录警告并在后台重试注册。→ 使用 `tenacity` 实现指数退避重试。
- **序列化不匹配**：Java 和 Python 具有不同的类型系统。JSON 作为公共语言，但复杂类型（Date、BigDecimal）需要约定。→ 文档化预期的 JSON 格式；添加类型转换工具。
- **额外的网络跳转**：每次调用 Java 服务都会增加延迟。→ 使用连接池（httpx with keep-alive）和可选的响应缓存。
