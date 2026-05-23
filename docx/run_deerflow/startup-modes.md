# DeerFlow 启动模式对比

## 一句话总结

| 模式 | 适合场景 | 进程管理 |
|------|----------|----------|
| **Local** | 本地开发，热重载 | 直接运行在宿主机 |
| **Docker Dev** | 隔离环境开发，跨团队一致 | Docker 容器 |
| **Docker Prod** | 生产部署 | Docker 容器 |

---

## Local 模式（开发推荐）

直接在你电脑上跑 4 个服务：

```
nginx(2026) → Gateway(8001) + LangGraph Server(2024) + Frontend(3000)
```

### Dev vs Prod

| | Dev | Prod |
|--|-----|------|
| 前端 | `pnpm run dev`（热重载） | `pnpm run preview`（预编译） |
| 后端 | `--reload` 热重载 | 无重载，纯优化运行 |
| 日志 | 直接输出终端 | 输出到日志文件 |

### Foreground vs Daemon

- **Foreground**（前台）：日志刷刷刷往终端滚，按 `Ctrl+C` 停止
- **Daemon**（后台）：`nohup` 跑在后台，进程分离出去，不影响你干别的

```
./scripts/serve.sh --dev              # Dev 前台 ← 日常开发用这个
./scripts/serve.sh --dev --daemon     # Dev 后台
./scripts/serve.sh --prod             # Prod 前台
./scripts/serve.sh --stop             # 停止
```

---

## Docker Dev 模式

用 `docker.sh` 把服务跑在容器里，**隔离性好，和环境解耦**。

```
./scripts/docker.sh init   # 可选：预拉沙箱镜像，加速首次启动
./scripts/docker.sh start  # 启动（自动检测沙箱模式）
./scripts/docker.sh logs   # 看日志
./scripts/docker.sh stop   # 停止
```

**三个沙箱模式（自动检测，无需手动配置）：**

| 沙箱模式 | 配置 | 说明 |
|----------|------|------|
| `local` | `LocalSandboxProvider` | 不需要容器镜像，最轻量 |
| `aio` | `AioSandboxProvider` | 使用 AIO 沙箱容器 |
| `provisioner` | `AioSandboxProvider` + `provisioner_url` | Kubernetes 模式，额外启动 provisioner |

启动后访问：**http://localhost:2026**

---

## Docker Prod 模式

生产级部署，**镜像预编译，服务更稳定**。

```bash
./scripts/deploy.sh        # 构建镜像 + 启动
./scripts/deploy.sh build  # 仅构建镜像
./scripts/deploy.sh start  # 从已有镜像启动
./scripts/deploy.sh down   # 停止并清理容器
```

---

## 横向对比

| | Local Dev | Local Prod | Docker Dev | Docker Prod |
|--|-----------|------------|------------|-------------|
| 进程位置 | 宿主机 | 宿主机 | Docker 容器 | Docker 容器 |
| 前端热重载 | ✅ | ❌ | ✅（volume 挂载源码） | ❌（预编译） |
| 启动速度 | 快 | 快 | 首次慢，之后快 | 取决于镜像 |
| 隔离性 | 低 | 低 | 高 | 高 |
| 适用场景 | 日常开发 | 快速验证 | 团队协作 / 环境一致 | 生产环境 |

---

## 选哪个？

**日常开发** → `make dev` 或 `./scripts/serve.sh --dev`

- 修改代码实时生效，前端后端都能热重载

**临时测试 / 不污染本地环境** → `make docker-start` 或 `./scripts/docker.sh start`

- 容器隔离，stop 就干净了，不留残留进程

**生产部署** → `make up` 或 `./scripts/deploy.sh`

- 预编译镜像，稳定可靠，可复现

---

## 常用命令速查

```bash
# Local 开发
make dev              # Dev 模式前台启动
make dev-daemon       # Dev 模式后台启动
make stop             # 停止

# Docker 开发
make docker-start     # 启动 Docker Dev
make docker-stop      # 停止
make docker-logs      # 看日志

# Docker 生产
make up               # 构建 + 启动
make down             # 停止 + 清理
```