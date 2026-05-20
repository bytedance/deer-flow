# DeerFlow Docker x86 平台构建指南

## 背景

Mac (Apple Silicon) 默认构建 ARM 架构镜像。如果需要在 x86 服务器上运行镜像，或在 x86 机器上构建兼容镜像，需要在构建时指定目标平台为 `linux/amd64`。

## 环境变量

```bash
export DOCKER_BUILDKIT=1                          # 启用 BuildKit 构建缓存（加速后续构建）
export DOCKER_DEFAULT_PLATFORM=linux/amd64        # 指定 x86 架构
export DEER_FLOW_ROOT=/Users/raidery/bench/harness/raidery/deer-flow
export UV_IMAGE=ghcr.io/astral-sh/uv:0.7.20
export NPM_REGISTRY=https://registry.npmmirror.com    # npm 国内镜像
export UV_INDEX_URL=https://mirrors.cloud.tencent.com/pypi/simple  # PyPI 国内腾讯镜像
export PIP_INDEX_URL=https://mirrors.cloud.tencent.com/pypi/simple
```

## 开发环境构建（docker-compose-dev.yaml）

```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
docker-compose -f docker/docker-compose-dev.yaml build
docker-compose -f docker/docker-compose-dev.yaml up -d
```

## 生产环境构建（docker-compose.yaml）

```bash
cd /Users/raidery/bench/harness/raidery/deer-flow
docker-compose -f docker/docker-compose.yaml build
docker-compose -f docker/docker-compose.yaml up -d
```

## 常用命令

```bash
# 查看容器状态
docker-compose -f docker/docker-compose-dev.yaml ps

# 查看全部日志
docker-compose -f docker/docker-compose-dev.yaml logs -f

# 仅看 gateway 日志
docker-compose -f docker/docker-compose-dev.yaml logs -f gateway

# 仅看 frontend 日志
docker-compose -f docker/docker-compose-dev.yaml logs -f frontend

# 停止所有容器
docker-compose -f docker/docker-compose-dev.yaml down
```

## 访问地址

- 开发环境：http://localhost:2026
- nginx 代理：`/api/langgraph/*` → Gateway，`/api/*` → REST API，`/` → Frontend

## BuildKit 缓存说明

`DOCKER_BUILDKIT=1` 启用后，Dockerfile 中的 `--mount=type=cache` 会持久化到本地文件系统。

前端 `pnpm install` 的缓存（1077 个文件）会在首次构建后缓存，后续构建不再重复下载。

首次构建较慢（约 5-10 分钟），之后增量构建通常在 1 分钟内完成。

## 常见问题

### extensions_config.json 是目录而非文件

gateway 启动失败，报 `Is a directory: '/app/extensions_config.json'`。

**解决**：

```bash
rm -rf extensions_config.json
cp extensions_config.example.json extensions_config.json
docker-compose -f docker/docker-compose-dev.yaml restart gateway
```

### gateway 启动失败，报 asyncpg 未安装

`config.yaml` 中 `database.backend: postgres`，但未安装 asyncpg。

**解决**：将 `config.yaml` 中的 `database.backend` 改为 `sqlite`：

```bash
sed -i '' 's/backend: postgres/backend: sqlite/' config.yaml
docker-compose -f docker/docker-compose-dev.yaml restart gateway
```

### pnpm install 每次都重新下载

需要在 `frontend/Dockerfile` 中为 cache mount 添加固定 `id`：

```dockerfile
# 原来
RUN --mount=type=cache,target=/root/.local/share/pnpm/store \
    cd /app/frontend && pnpm install --frozen-lockfile

# 改为（加 id=pnpm-store）
RUN --mount=type=cache,id=pnpm-store,target=/root/.local/share/pnpm/store,mode=0755 \
    cd /app/frontend && pnpm install --frozen-lockfile
```

然后配合 `export DOCKER_BUILDKIT=1` 即可复用缓存。

### 孤儿容器警告

```bash
docker-compose -f docker/docker-compose-dev.yaml up --remove-orphans
```

### JWT SECRET 警告

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
# 将生成的密钥加入 .env：AUTH_JWT_SECRET=生成的密钥
```

## 开发模式 vs 生产模式

| | docker-compose-dev.yaml | docker-compose.yaml |
|---|---|---|
| 用途 | 开发（热重载、源码挂载） | 生产（预编译、不可变镜像） |
| Frontend target | `dev` | `prod` |
| 源码挂载 | 有（src/ 目录挂载） | 无 |
| pnpm store | 挂载宿主机 store | BuildKit cache |
| 网络名 | `deer-flow-dev` | `deer-flow` |

## docker-compose-dev.yaml 与 docker-compose.yaml 的区别

- **`docker-compose-dev.yaml`**：开发用，修改代码自动生效（源码挂载），前台日志可见
- **`docker-compose.yaml`**：生产用，一次构建到处运行，改代码需重新 `build`

'''
  http://localhost:2026

  你看到的 http://localhost:2026/setup 提示 "System already initialized" 是因为系统已经设置过了。

  解决方式

  1. 访问登录页：http://localhost:2026 或 http://localhost:2026/login
  2. 如果需要重置系统（清除初始化状态重新配置）：
  # 停止服务
  make stop

  # 清除数据
  make clean

  # 重新启动
  make dev
  3. 或者直接访问：http://localhost:2026/workspace

  你现在能在 2026 端口看到登录页面吗？
'''