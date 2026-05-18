## 1. 依赖与配置

- [ ] 1.1 向 `pyproject.toml` 添加 Python 依赖（`httpx`、`tenacity`）
- [ ] 1.2 在 `deerflow/config/nacos_config.py` 中创建 `NacosConfig`、`NacosServiceConfig`、`NacosHeartbeatConfig`、`NacosRetryConfig` Pydantic 模型，包含字段约束和默认值，并按项目惯例添加模块级单例和 `load_nacos_config_from_dict()`
- [ ] 1.3 在 `deerflow/config/rpc_config.py` 中创建 `RpcConfig`、`RpcServiceConfig`、`RpcEndpointConfig`、`RpcRetryConfig` Pydantic 模型，并按项目惯例添加模块级单例和 `load_rpc_config_from_dict()`
- [ ] 1.4 在 `deerflow/config/app_config.py` 的 `AppConfig` 中添加 `nacos: NacosConfig | None` 和 `rpc: RpcConfig | None` 字段，并在 `_apply_singleton_configs()` 中注册加载调用

## 2. Nacos 服务发现模块

- [ ] 2.1 创建 `deerflow/rpc/__init__.py` 模块目录
- [ ] 2.2 实现 `NacosRegistry` 类，包含 `register()`、`deregister()`、`send_heartbeat()` 方法
- [ ] 2.3 实现 `discover_service(name)` 方法，用于从 Nacos 查询健康实例
- [ ] 2.4 实现后台心跳任务，支持可配置的间隔时间
- [ ] 2.5 实现启动时 Nacos 不可达的指数退避重试

## 3. Java RPC 客户端模块

- [ ] 3.1 实现 `RpcClient` 类，通过 `httpx.AsyncClient` 支持连接池
- [ ] 3.2 实现服务解析：Nacos 发现查找 vs 直接 `base_url`
- [ ] 3.3 实现 `call(service_name, method, params)` 方法，支持 JSON 序列化
- [ ] 3.4 实现超时处理和退避重试
- [ ] 3.5 实现错误转换：将 4xx/5xx 响应和网络错误转换为 Python 异常

## 4. 网关集成

- [ ] 4.1 在 `app/gateway/app.py` 的网关生命周期中添加 Nacos 注册和心跳启动
- [ ] 4.2 在生命周期中添加网关关闭时的 Nacos 注销
- [ ] 4.3 将 `rpc_client` 添加为 FastAPI 依赖或在路由中可访问的单例
- [ ] 4.4 更新 `config.example.yaml` 和 `config.yaml`，添加 `nacos` 和 `rpc` 配置段

## 5. 测试

- [ ] 5.1 编写 `NacosConfig` 和 `RpcConfig` 模型验证的单元测试
- [ ] 5.2 编写 `NacosRegistry` 的单元测试（使用 mock HTTP 响应）
- [ ] 5.3 编写 `RpcClient` 的单元测试（使用 mock HTTP 响应）
- [ ] 5.4 编写网关生命周期钩子的集成测试（mock Nacos 服务器）
