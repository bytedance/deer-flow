# Docker Dev 环境启动指南

面向 `make docker-start`（容器版开发环境）的启动手册，重点讲清**数据库接线**：
容器内 `localhost` 不是宿主机，postgres 模式必须改用 `host.docker.internal`。
本文保留用户 fork `0aee7096` 的数据库接线说明，并按当前原生 Gateway 拓扑更新。
历史 macOS + Docker Desktop 实测发生于 2026-09-11；本次 Task6A 没有重跑开发栈或连接用户数据库。

## 1. 服务拓扑

`make docker-start` → `scripts/docker.sh start` → Compose 项目 `deer-flow-dev`
（编排文件 `docker/docker-compose-dev.yaml`）：

| 服务 | 端口 | 说明 |
|---|---|---|
| nginx | **2026（对外唯一入口）** | 反代前端 + API，默认只绑 127.0.0.1 |
| gateway | 8001（容器内部） | FastAPI 后端 + agent 运行时 |
| frontend | 3000（容器内部） | Next.js dev server |
| provisioner | 8002（按需） | 仅当 `config.yaml` 配置 provisioner 沙箱模式时启动 |
| redis | 6379（容器内部） | 跨 worker SSE stream bridge |

浏览器访问 `http://localhost:2026`。

**编排里没有 postgres 容器** —— 数据库由你自己提供（本机安装或远程），
通过根目录 `.env` 的 `DATABASE_URL` 注入 gateway 容器（`env_file: ../.env`）。
Kubernetes/Helm 部署（`make up` 之外的生产路径）才捆绑 postgres StatefulSet。

## 2. 快速启动

前置：Docker Desktop / Engine 运行中；**Docker Compose ≥ 2.24**（`docker compose
version` 检查，旧版无法解析编排文件里的 optional `env_file` 长语法）。

```bash
make config         # 首次：从 example 生成 config.yaml / extensions_config.json（已存在则跳过）
make docker-init    # 拉取沙箱镜像（首次或镜像更新时）
make docker-start   # 启动（自动按 config.yaml 探测沙箱模式）
make docker-logs    # 看日志（另有 docker-logs-gateway / -frontend / -redis）
make docker-stop    # 停止
```

脚本行为要点：

- `config.yaml` 不存在时会从 `config.example.yaml` 复制并提示去填 API key。
- 国内网络可先 `export UV_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple`
  和 `NPM_REGISTRY=https://registry.npmmirror.com` 加速构建。
- AIO 沙箱镜像建议**固定版本 tag**（如 `...all-in-one-sandbox:1.11.0`），
  不要用 `:latest`（见 issue #3921：镜像源上 `latest` 被冻结在旧版本，
  会导致依赖 required-secrets 的 skill 失败）。在 `docker-compose-dev.yaml`
  的 `SANDBOX_IMAGE` 处修改。
- 手动 compose 命令必须带项目名和相对路径，且**不要在 `docker/` 目录内执行**：
  ```bash
  docker compose -p deer-flow-dev -f docker/docker-compose-dev.yaml ps
  ```

## 3. 数据库接线（重点）

### 3.1 三种 backend

`config.yaml` 的 `database.backend` 三选一（定义于
`backend/packages/harness/deerflow/config/database_config.py`）：

| backend | 用途 | 持久化 |
|---|---|---|
| `memory`（代码默认） | 临时开发 | ❌ 重启即失 |
| `sqlite` | 单机档 | ✅ 落在 `sqlite_dir`（默认 `backend/.deer-flow/data/deerflow.db`） |
| `postgres` | 多副本 / 生产档 | ✅ 需 `DATABASE_URL` |

只有 `postgres` 模式才需要 `.env` 里的 `DATABASE_URL`。

### 3.2 容器内 `localhost` 不是你的宿主机（实测复现的坑）

gateway 容器读到的 `DATABASE_URL` 是在**容器内**解析的。`.env` 里写成
`localhost:5432` 时，容器连的是它自己 → `Connection refused`。实测记录
（本机 postgres 仅监听 `127.0.0.1`/`::1`，pgvector:pg16 镜像作客户端）：

```text
# .env 原样（localhost）→ 容器内执行：
psql: error: connection to server at "localhost" (::1), port 5432 failed: Connection refused

# 宿主机改写为 host.docker.internal 后：
 container->host.docker.internal OK
```

使用 `/health/ready` 和 Gateway 日志确认连接状态；不要打印完整 DATABASE_URL 或容器环境。

### 3.3 正确配置：按运行方式切换主机名

`.env` 中**同时保留两行、按需切换注释**（`.env` 是 `make dev` 和 docker 共用的）：

```bash
# 本机直跑（make dev / make start）用这个：
DATABASE_URL=postgresql://USER:PASSWORD@localhost:5432/DBNAME
# Docker 容器跑（make docker-start）改用这个：
# DATABASE_URL=postgresql://USER:PASSWORD@host.docker.internal:5432/DBNAME
```

平台差异：

- **macOS / Windows（Docker Desktop）**：开箱即用。编排里 gateway 和
  provisioner 服务都已声明 `extra_hosts: "host.docker.internal:host-gateway"`，
  且 Desktop 的代理从宿主机侧回连，**宿主机 postgres 即使只监听 loopback
  也能连通**（已实测）。
- **Linux（原生 Docker Engine）**：`host-gateway` 会解析成 docker 网桥 IP
  （如 `172.17.0.1`），流量不再走宿主机 loopback —— 需要额外放开 postgres
  监听与访问控制：`postgresql.conf` 设 `listen_addresses = '*'`（或至少加上
  网桥网段），`pg_hba.conf` 允许该网段（如 `host all all 172.16.0.0/12 scram-sha-256`），
  然后 `systemctl reload postgresql`。同时确认宿主机防火墙放行 5432。

> 安全提示：`listen_addresses = '*'` + 宽网段 `pg_hba` 只建议在受信任的
> 内网/单机开发环境使用；生产库请走独立网络与最小权限账号。

### 3.4 改完 `.env` 怎么生效

Compose 的 `restart` **不会**重新读取 `env_file`。修改 `.env` 后必须重建容器：

```bash
make docker-stop && make docker-start
# 或只重建 gateway：
docker compose -p deer-flow-dev -f docker/docker-compose-dev.yaml up -d gateway
```

## 4. 常见问题排查

| 现象 | 原因 | 处理 |
|---|---|---|
| gateway 反复重启 / 启动即挂，日志见 `Connection refused ... :5432` | `.env` 用了 `localhost` | 改 `host.docker.internal` 后重建（§3.3/§3.4） |
| 改了 `.env` 但容器行为没变 | `restart` 不重读 `env_file` | `make docker-stop && make docker-start`（§3.4） |
| `database.backend: memory` 时数据重启消失 | 这是该模式的定义 | 切 `postgres`（推荐）或 `sqlite` |
| compose 报 env_file 长语法解析错误 | Compose < 2.24 | 升级 Docker Desktop / compose 插件 |
| 沙箱 skill 报缺 secrets | AIO 镜像 `:latest` 被冻结在旧版 | 固定镜像 tag ≥ 1.11.0（§2） |
| 想确认数据库连接 | 连接串属于私有配置 | 检查 `/health/ready` 的 database 状态；不要输出环境变量 |

日志入口：`make docker-logs`（全部）、`make docker-logs-gateway`（后端 trace
back 在这里）、`make docker-logs-frontend`（前端编译错误）。

## 5. 与本地模式的对照

| | `make dev`（本地进程） | `make docker-start`（容器） |
|---|---|---|
| DATABASE_URL 主机名 | `localhost` | `host.docker.internal` |
| 入口 | nginx :2026（本地起 nginx） | nginx :2026（容器） |
| 热重载 | uvicorn `--reload`（排除 `.deer-flow/`） | 源码 bind mount + dev-entrypoint |
| 数据落点 | `backend/.deer-flow/` | 同目录 bind mount 进容器（`/app/backend/.deer-flow`） |

`DEER_FLOW_HOME`（默认 `backend/.deer-flow`）在两种模式下指向同一个宿主机
目录，因此 **sqlite 模式切模式不丢数据**；postgres 模式则与运行方式完全无关。


## 6. 原生 ECS 的数据库边界

原生多实例 Gateway、checkpoint、run events、MCP tasks 和 schedules 使用原生应用 PostgreSQL。
私有 `ecs_executor` 的三个 ledger 表使用**另一个独立数据库**，由自己的 Alembic chain 管理，
不能把 executor URL 指向 Gateway 数据库。原生 worker 只有出站控制通道，不开放额外入站端口。
普通 Docker dev 命令不会启用 ECS，也不会自动转换旧 Fleet execution 数据；
含旧 intent 的数据库会被原生 Gateway 隔离，参见 [兼容和切换步骤](ecs-native-fork-integration.md)。
