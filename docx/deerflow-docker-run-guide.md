# DeerFlow 镜像导出与迁移指南

## 概述

本文档描述如何将当前机器上的 DeerFlow Docker 镜像导出，并在另一台机器上运行。

---

## 第一步：导出镜像

在当前运行 DeerFlow 的机器上执行：

```bash
docker save -o deerflow.tar \
  deer-flow-dev-frontend \
  deer-flow-dev-gateway \
  nginx:alpine
```

或者一次性保存所有镜像：

```bash
docker save -o deerflow.tar $(docker images --format '{{.Repository}}:{{.Tag}}' | grep -E "deer-flow|nginx")
```

确认导出成功：

```bash
ls -lh deerflow.tar
```

---

## 第二步：传输文件到目标机器

```bash
# 通过 scp 复制镜像包
scp deerflow.tar user@target-machine:/home/user/deer-flow/

# 通过 rsync 复制配置文件和目录
rsync -av docker/ user@target:/home/user/deer-flow/docker/
rsync -av config.yaml user@target:/home/user/deer-flow/
rsync -av skills/ user@target:/home/user/deer-flow/
rsync -av frontend/.env user@target:/home/user/deer-flow/frontend/ 2>/dev/null || true
rsync -av backend/.env user@target:/home/user/deer-flow/backend/ 2>/dev/null || true
```

### 需要拷贝的关键文件列表

| 文件/目录 | 说明 |
|-----------|------|
| `docker/` | docker-compose-dev.yaml、nginx.conf、dev-entrypoint.sh 等 |
| `config.yaml` | 主配置文件 |
| `skills/` | 技能目录 |
| `frontend/.env` | 前端环境变量（如果存在） |
| `backend/.env` | 后端环境变量（如果存在） |

---

## 第三步：目标机器配置

### 3.1 导入镜像

```bash
cd /home/user/deer-flow
docker load -i deerflow.tar
```

确认导入成功：

```bash
docker images | grep -E "deer-flow|nginx"
```

### 3.2 配置环境变量

目标机器的 `.env` 文件需要重新配置，特别是：

| 变量 | 说明 |
|------|------|
| `DEER_FLOW_CHANNELS_LANGGRAPH_URL` | Gateway API 地址 |
| `DEER_FLOW_CHANNELS_GATEWAY_URL` | Gateway URL |
| `DEER_FLOW_ROOT` | 项目根目录 |
| API Keys | 根据 config.yaml 中配置的模型填写 |

### 3.3 检查端口

确保目标机器以下端口未被占用：

| 端口 | 服务 |
|------|------|
| 2026 | nginx（统一入口） |
| 3000 | frontend（Next.js） |
| 8001 | gateway（Backend API） |

---

## 第四步：启动服务

### 启动命令

```bash
cd /home/user/deer-flow/docker

# 启动所有服务（local 模式不需要 provisioner）
docker compose -p deer-flow-dev -f docker-compose-dev.yaml up -d frontend gateway nginx
```

### 常用操作

```bash
# 查看服务状态
docker compose -p deer-flow-dev -f docker-compose-dev.yaml ps

# 查看日志
docker compose -p deer-flow-dev -f docker-compose-dev.yaml logs -f

# 查看指定服务日志
docker compose -p deer-flow-dev -f docker-compose-dev.yaml logs -f gateway

# 停止服务
docker compose -p deer-flow-dev -f docker-compose-dev.yaml down
```

---

## 访问

启动成功后访问：

```
http://目标机器IP:2026
```

---

## 架构说明

```
浏览器 → nginx (2026) → frontend (3000) + gateway (8001)
```

| 容器名 | 说明 |
|--------|------|
| deer-flow-nginx | 反向代理，统一入口 |
| deer-flow-frontend | Next.js 前端开发服务器 |
| deer-flow-gateway | Python FastAPI 后端 + Agent 运行时 |

---

## 注意事项

### 1. Docker Socket

gateway 容器需要访问宿主机的 `/var/run/docker.sock` 来运行沙箱（DoD 模式）：

```yaml
- /var/run/docker.sock:/var/run/docker.sock
```

### 2. sandbox 模式

当前使用的是 `LocalSandboxProvider`（local 模式），不需要：
- 沙箱镜像（all-in-one-sandbox）
- provisioner 容器

### 3. 环境变量 DEER_FLOW_ROOT

docker-compose-dev.yaml 中使用了 `DEER_FLOW_ROOT` 环境变量，确保在启动前设置：

```bash
export DEER_FLOW_ROOT=/home/user/deer-flow
```

或者在 `.env` 文件中配置：

```env
DEER_FLOW_ROOT=/home/user/deer-flow
```

### 4. 网络

docker-compose-dev.yaml 创建了 `deer-flow-dev` 桥接网络，子网 `192.168.200.0/24`。如果与其他网络冲突，需要修改 `docker-compose-dev.yaml` 中的网络配置。

---

## 故障排查

### 容器启动失败

```bash
# 查看所有容器状态
docker ps -a | grep deer-flow

# 查看 gateway 日志
docker compose -p deer-flow-dev -f docker-compose-dev.yaml logs gateway

# 进入 gateway 容器调试
docker exec -it deer-flow-dev-gateway bash
```

### 端口冲突

```bash
# 检查端口占用
ss -tlnp | grep -E "2026|3000|8001"

# 或者
netstat -tlnp | grep -E "2026|3000|8001"
```

### 清理后重新启动

```bash
docker compose -p deer-flow-dev -f docker-compose-dev.yaml down -v
docker compose -p deer-flow-dev -f docker-compose-dev.yaml up -d --build frontend gateway nginx
```

```
──────────────┬────────────────────────────┬────────────────────────────────┐
  │              │          make up           │       make docker-start        │
  ├──────────────┼────────────────────────────┼────────────────────────────────┤
  │ 脚本         │ ./scripts/deploy.sh        │ ./scripts/docker.sh start      │
  ├──────────────┼────────────────────────────┼────────────────────────────────┤
  │ Compose 文件 │ docker/docker-compose.yaml │ docker/docker-compose-dev.yaml │
  ├──────────────┼────────────────────────────┼────────────────────────────────┤
  │ 项目名       │ deer-flow                  │ deer-flow-dev                  │
  ├──────────────┼────────────────────────────┼────────────────────────────────┤
  │ 用途         │ 生产环境                   │ 开发环境                       │
  └──────────────┴────────────────────────────┴────────────────────────────────┘

  实际运行的命令：

  # make up（生产）
  docker compose -p deer-flow -f docker/docker-compose.yaml up --build -d --remove-orphans frontend gateway nginx

  # make docker-start（开发）
  docker compose -p deer-flow-dev -f docker/docker-compose-dev.yaml up --build -d --remove-orphans frontend gateway nginx

  共同点：
  - 都会自动检测 sandbox 模式（local/aio/provisioner）
  - 都会自动设置 DEER_FLOW_ROOT 环境变量
  - 都会在 config.yaml 不存在时从 example 复制

  选择建议：
  - 本地开发 → make docker-start（项目名 deer-flow-dev）
  - 生产部署 → make up（项目名 deer-flow）
  - 查看日志 → make docker-logs-gateway

  ```