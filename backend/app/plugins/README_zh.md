# app.plugins 设计说明

本文基于当前代码实现，说明 `backend/app/plugins` 的定位、插件设计契约、依赖边界，以及当前 `auth` 插件是如何在尽量少侵入宿主应用的前提下提供服务的。

## 1. 总体定位

`app.plugins` 是应用侧插件边界。它的目标不是做一个通用插件市场，而是在 `app` 这一层给可拆分的业务能力预留清晰边界，使某一类能力可以：

1. 在插件内部自带领域模型、运行时状态和适配器
2. 只通过有限的接缝与宿主应用交互
3. 在未来保持“可替换、可裁剪、可扩展”

当前目录下实际落地的插件是 [`auth`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/app/plugins/auth)。

从当前实现看，`app.plugins` 的方向不是“所有逻辑都塞进 app”，而是：

1. 宿主应用负责统一启动、共享基础设施和总路由装配
2. 插件负责自己的业务契约、持久化定义、运行时状态和外部适配器

## 2. 插件设计契约

### 2.1 插件内部要自带完整能力

当前代码体现出的首要契约是：

插件自己的 ORM、runtime、domain、adapter，原则上都应由插件内部实现，不要把核心业务依赖散落到外部模块。

以 `auth` 插件为例，它内部已经自带了完整分层：

1. `domain`
   - 配置、错误、JWT、密码、领域模型、服务
2. `storage`
   - 插件自己的 ORM 模型、仓储契约和仓储实现
3. `runtime`
   - 插件自己的运行时配置状态
4. `api`
   - 插件自己的 HTTP router 和 schema
5. `security`
   - 插件自己的 middleware、dependency、csrf、LangGraph 适配
6. `authorization`
   - 插件自己的权限模型、policy 解析和 hook
7. `injection`
   - 插件自己的路由策略注册、注入和校验逻辑

换句话说，插件不是一组零散 helper，而应该是一个自闭合的功能模块。

### 2.2 宿主应用只提供共享基础设施，不承接插件内部逻辑

当前约束不是“插件完全独立进程”，而是：

1. 插件可以复用应用共享的 `engine`、`session_factory`、FastAPI app、路由树
2. 但插件自己的表结构、仓储、运行时配置、鉴权逻辑，仍然应由插件自己拥有

这一点在 [`auth/plugin.toml`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/app/plugins/auth/plugin.toml) 里写得很明确：

1. `storage.mode = "shared_infrastructure"`
2. 说明插件拥有自己的 storage definitions 和 repositories
3. 但复用应用共享的 persistence infrastructure

所以这里的契约不是“禁止复用基础设施”，而是“不要把插件内部业务实现外包给 app 其他模块”。

### 2.3 依赖方向要单向

按当前实现，比较理想的依赖方向是：

```text
gateway / app bootstrap
  -> plugin public adapters
     -> plugin domain / storage / runtime
```

而不是：

```text
plugin domain
  -> 依赖 app 里的业务模块
```

插件可以使用：

1. 共享持久化基础设施
2. 宿主应用提供的 `app.state`
3. FastAPI / Starlette 等通用框架能力

但不应该把自己的核心业务规则建立在别的业务模块之上，否则后续无法热插拔。

## 3. 当前 auth 插件的实际结构

当前 `auth` 插件可以概括为一套“自带模型、自带服务、自带适配器”的认证授权包。

### 3.1 domain

[`auth/domain`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/app/plugins/auth/domain) 负责：

1. `config.py`
   - 认证相关配置定义与加载
2. `errors.py`
   - 错误码和错误响应契约
3. `jwt.py`
   - token 编解码
4. `password.py`
   - 密码哈希和校验
5. `models.py`
   - auth 域模型
6. `service.py`
   - `AuthService`，作为核心业务服务

`AuthService` 本身只依赖插件内部的 `DbUserRepository` 和共享 session factory，没有把认证逻辑散到 `gateway`。

### 3.2 storage

[`auth/storage`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/app/plugins/auth/storage) 明确体现了“ORM 由插件自己内部实现”的契约：

1. [`models.py`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/app/plugins/auth/storage/models.py)
   - 定义插件自己的 `users` 表模型
2. [`contracts.py`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/app/plugins/auth/storage/contracts.py)
   - 定义 `User`、`UserCreate` 和 `UserRepositoryProtocol`
3. [`repositories.py`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/app/plugins/auth/storage/repositories.py)
   - 实现 `DbUserRepository`

这里的关键点是：

1. 插件自己定义 ORM model
2. 插件自己定义 repository protocol
3. 插件自己实现 repository
4. 外部只需要给它 session / session_factory

这就是插件边界应该保持的最小共享面。

### 3.3 runtime

[`auth/runtime/config_state.py`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/app/plugins/auth/runtime/config_state.py) 维护插件自己的 runtime config state：

1. `get_auth_config()`
2. `set_auth_config()`
3. `reset_auth_config()`

这说明运行时配置状态也属于插件内部，而不是由外部模块代持。后续如果别的插件需要自己的缓存、状态机、feature flag，也应沿这个模式内聚在插件内部。

### 3.4 adapters

`auth` 插件对外暴露能力主要通过四类 adapter：

1. `api/router.py`
   - HTTP 接口
2. `security/*`
   - middleware、dependency、request user 解析、actor context bridge
3. `authorization/*`
   - capability、policy evaluator、auth hooks
4. `injection/*`
   - route policy registry、guard 注入、启动校验

这类 adapter 的共同特征是：

1. 入口能力在插件内定义
2. 宿主应用只负责调用和装配

## 4. 插件如何与宿主应用交互

### 4.1 总路由只 include，不重写插件逻辑

[`app/gateway/router.py`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/app/gateway/router.py) 只是：

1. 引入 `app.plugins.auth.api.router`
2. `include_router(auth_router)`

这说明宿主应用对 auth HTTP 能力的接入是装配式的，而不是在 `gateway` 里重写一套登录/注册逻辑。

### 4.2 registrar 负责启动装配，不负责接管插件实现

[`app/gateway/registrar.py`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/app/gateway/registrar.py) 里，宿主应用做的事情主要是：

1. `app.state.authz_hooks = build_authz_hooks()`
2. 加载并校验 route policy registry
3. `install_route_guards(app)`
4. `app.add_middleware(CSRFMiddleware)`
5. `app.add_middleware(AuthMiddleware)`

也就是说，宿主应用只负责把插件接进来：

1. 注册 middleware
2. 安装 route guard
3. 把 hooks 和 registry 放到 `app.state`

真正的鉴权逻辑、认证逻辑、路由策略语义仍然在插件内部。

### 4.3 共享会话工厂，但业务仓储仍归插件

在 [`auth/security/dependencies.py`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/app/plugins/auth/security/dependencies.py) 中：

1. 插件从 `request.app.state.persistence.session_factory` 取得共享 session factory
2. 然后自己构造 `DbUserRepository`
3. 再自己构造 `AuthService`

这就是一个很典型的低侵入接缝：

1. 外部只提供共享基础设施句柄
2. 插件自己决定如何实例化内部依赖

## 5. 热插拔与低侵入原则

### 5.1 如果要向其他模块提供服务，应尽量减少入侵

插件给其他模块提供服务时，优先选下面这些方式：

1. 暴露 router
2. 暴露 middleware / dependency
3. 暴露 hook 或 protocol
4. 通过 `app.state` 注入少量共享对象
5. 使用配置驱动的 route policy / capability，而不是把判断逻辑硬编码进业务路由

不推荐的方式是：

1. 在 `gateway` 大量写插件特定分支
2. 让别的业务模块直接 import 插件内部 ORM 细节后自行拼逻辑
3. 把插件状态散落到全局多个模块中共同维护

### 5.2 当前 auth 插件已经体现出的低侵入点

当前 `auth` 插件的低侵入接入点主要有四个：

1. 路由接入
   - `gateway.router` 只 `include_router`
2. 中间件接入
   - `registrar` 只注册 `AuthMiddleware` / `CSRFMiddleware`
3. 策略注入
   - `install_route_guards(app)` 给路由统一追加 `Depends(enforce_route_policy)`
4. hook 接缝
   - `authz_hooks` 通过 `app.state` 暴露，策略构建和权限提供器可以替换

这套结构的好处是：

1. 宿主应用改动面集中在装配层
2. 插件核心实现集中在插件目录内部
3. 替换实现时，不需要在业务路由里逐个修改

### 5.3 route policy 是低侵入的关键机制

[`auth/injection/registry_loader.py`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/app/plugins/auth/injection/registry_loader.py)、[`validation.py`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/app/plugins/auth/injection/validation.py) 和 [`route_injector.py`](/Users/rayhpeng/workspace/open-source/deer-flow/backend/app/plugins/auth/injection/route_injector.py) 共同形成了一套很关键的契约：

1. 路由策略写在插件自己的 `route_policies.yaml`
2. 启动时会校验策略表和真实路由是否一致
3. guard 通过统一注入附着到路由，而不是每个 endpoint 手写一遍

这使得插件能够：

1. 用配置描述“哪些路由公开、需要哪些 capability、需要哪些 owner policy”
2. 避免对宿主路由层做大规模侵入
3. 在未来更容易替换或裁剪某个插件

## 6. 关于“ORM、runtime 都由自己内部实现”的具体说明

这条契约建议明确理解为以下三点：

1. 数据模型归插件
   - 插件自己的表、Pydantic contract、repository protocol、repository implementation 都放在插件目录内
2. 运行时状态归插件
   - 插件自己的配置缓存、上下文桥、插件级 hooks 都在插件内部维护
3. 外部只暴露基础设施，不接管插件语义
   - 例如共享 `session_factory`、FastAPI app、`app.state`

拿 `auth` 举例：

1. `users` 表在插件里定义，不在 `app.infra` 定义
2. `AuthService` 在插件里实现，不在 `gateway` 实现
3. `get_auth_config()` 在插件里维护，不由别的模块缓存
4. `AuthMiddleware`、`route_guard`、`AuthzHooks` 都由插件自己提供

这是后续做插件化时最重要的结构前提。

## 7. 当前作用范围与非目标

就当前实现而言，`app.plugins` 的作用范围主要是：

1. 为应用侧可拆分能力建立模块边界
2. 让插件拥有自己的 domain/storage/runtime/adapter
3. 通过装配式接缝接入宿主应用

当前非目标也很明确：

1. 还不是一个完整的通用插件发现/安装系统
2. 还没有做到运行时动态启停插件
3. 也不是把共享基础设施完全复制进每个插件

所以“热插拔”在当前阶段更准确的含义是：

1. 插件边界尽量独立
2. 接入点尽量集中在装配层
3. 替换或移除时，改动尽量局限在 `registrar`、`router include`、`app.state` hooks 这些少数位置

## 8. 后续演进建议

如果后续要继续把 `app.plugins` 做成更稳定的插件边界，建议保持这些规则：

1. 每个插件目录内部都保持 `domain` / `storage` / `runtime` / `adapter` 分层
2. 插件自己的 ORM 与 repository 不要下沉到共享业务目录
3. 插件向外提供服务时优先暴露 protocol、hook、router、middleware，而不是要求外部 import 内部实现细节
4. 插件与宿主应用的接缝尽量限制在：
   - `router.include_router(...)`
   - `app.add_middleware(...)`
   - `app.state.*`
   - 生命周期装配
5. 配置驱动优先于散落的硬编码接入
6. 启动期校验优先于运行时隐式失败

## 9. 设计总结

可以把当前 `app.plugins` 的契约总结为一句话：

插件内部拥有自己的业务实现、ORM 和 runtime；宿主应用只提供共享基础设施和装配接缝；对外服务时尽量通过低侵入、可替换的方式接入，以便后续做到真正的热插拔和边界演进。
