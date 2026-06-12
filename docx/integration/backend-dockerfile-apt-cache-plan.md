# backend/Dockerfile `apt install` 缓存化方案

> 状态：**待实现 (Pending)** — 仅方案评审与对比，等后续落地。
> 关联文件：`backend/Dockerfile`（两处 `apt-get install`）
> 创建日期：2026-06-05

---

## 1. 背景与根因

`backend/Dockerfile` 是多阶段构建（builder / dev / runtime 三阶段），但 `apt-get install` 出现在两个独立的 stage：

| 位置 | Stage | 基础镜像 | 用途 |
|------|-------|---------|------|
| L26–L58 | Stage 1 `builder` | `python:3.12-slim-bookworm` | 编译 Python 原生扩展 |
| L137–L168 | Stage 3 `runtime` | `python:3.12-slim-bookworm`（**全新拉取**） | 干净的生产镜像 |
| — | Stage 2 `dev` | `FROM builder` | 继承 builder，无额外 apt install |

**关键事实**：Stage 3 与 Stage 1 **没有派生关系**（Stage 2 才是 `FROM builder`）。`COPY --from` 只能搬文件，搬不了 apt 的 dpkg 数据库，因此两处都必须重装。

两份列表的差异：

- **Builder** 额外有 `curl`（安装 Node.js 需要）和 `build-essential`（编译 `asyncpg` / `psycopg` / `pymupdf` 等 C 扩展需要）。
- **Runtime** 额外有 `libpq5`（`asyncpg` / `psycopg[binary]` 运行时链接），**不**装 `build-essential`（注释明确说明：减少 ~200 MB 镜像体积与攻击面）。

## 2. 三个候选方案

### 方案 A：BuildKit `--mount=type=cache`（推荐 / 改动最小）

给两处 `apt-get install` 都加上 BuildKit cache mount：

```dockerfile
RUN --mount=type=cache,target=/var/lib/apt,sharing=locked \
    --mount=type=cache,target=/var/cache/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends --fix-missing \
    curl \
    build-essential \
    ca-certificates \
    gnupg \
    git \
    tini \
    # ... (完整列表见 backend/Dockerfile L26-L58)
    && rm -rf /var/lib/apt/lists/*
```

> Stage 3 同理，target 和 sharing 参数不变。

**契合现有架构**：第 77 行已经使用 `--mount=type=cache,target=/root/.cache/uv,uid=0` 处理 uv 缓存，模板直接复用，BuildKit 已被项目隐式启用。

| 优点 | 缺点 |
|------|------|
| 改动最小（2 个 RUN 各加 1 行 mount） | 缓存只在**当前构建主机**生效，CI 多机之间不共享 |
| 二次构建显著加速（apt 仓库元数据 + 包文件复用） | `apt-get update` 仍需执行（要读 sources.list） |
| 不改镜像内容（mount 不进 layer） | 需要 `DOCKER_BUILDKIT=1`（新 Docker 默认开启） |
| 零引入成本 | — |

### 方案 B：BuildKit cache + Registry 缓存（CI 阶段）

方案 A 的超集，叠加 `--cache-to / --cache-from type=registry`：

```bash
docker buildx build \
  --cache-from type=registry,ref=swr.cn-north-4.myhuaweicloud.com/ddn-k8s/deerflow/cache:main \
  --cache-to   type=registry,ref=swr.cn-north-4.myhuaweicloud.com/ddn-k8s/deerflow/cache:main,mode=max \
  -f backend/Dockerfile .
```

| 优点 | 缺点 |
|------|------|
| 跨机器 / 跨 CI 任务共享缓存 | 需要内部镜像仓库（项目已在用 `swr.cn-north-4`） |
| `mode=max` 把所有中间层（含 apt cache）都缓存 | cache 镜像本身会膨胀 |
| Dockerfile 改动同 A，外加 CI flag | 首次推送有成本 |

### 方案 C：预烤 Base 镜像（包列表稳定后）

新增一个独立的基础镜像 `deerflow-backend-base:apt-v1`，把**两阶段共需**的包全部预装好，两个 stage 都基于它：

```dockerfile
# docker/backend-base.Dockerfile（新增）
FROM swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/library/python:3.12-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    gnupg \
    git \
    tini \
    jq \
    yq \
    wget \
    unzip \
    zip \
    xz-utils \
    p7zip-full \
    less \
    vim-tiny \
    nano \
    tree \
    file \
    xxd \
    procps \
    htop \
    lsof \
    psmisc \
    strace \
    iputils-ping \
    iproute2 \
    dnsutils \
    net-tools \
    traceroute \
    tcpdump \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*
```

`backend/Dockerfile` 改写为：

```dockerfile
ARG BASE_IMAGE=swr.cn-north-4.myhuaweicloud.com/ddn-k8s/deerflow-backend-base:apt-v1
FROM ${BASE_IMAGE} AS builder
RUN apt-get update && apt-get install -y --no-install-recommends build-essential curl \
    && rm -rf /var/lib/apt/lists/*
# ... builder 剩余逻辑不变

FROM ${BASE_IMAGE} AS runtime
# 啥也不用装，直接用 base
```

| 优点 | 缺点 |
|------|------|
| **彻底**消除重复下载；后续 build 几乎不联网 | 多维护一个 Dockerfile + 镜像 tag |
| 阶段镜像变小（apt cache 不会进入 base 的下游镜像） | 包列表变更需重烤 base |
| Builder 阶段只需装 2 个包（`build-essential` + `curl`） | 第一版要打通 base 镜像的发布流程 |
| 包版本完全可控、可锁定 | base 镜像本身也要定期更新 |
| 完全离线友好 | — |

> 注：Builder 阶段仍要 `apt-get install build-essential`，但因 base 已下载 apt 索引和大部分元数据，实际新增下载量很小（`build-essential` 自身约 200 MB 是编译工具链必须成本）。

### 方案 D：单 Dockerfile 内 "common" 阶段（**已否决**）

```dockerfile
FROM python:3.12-slim-bookworm AS common
RUN apt-get update && apt-get install -y --no-install-recommends ... libpq5

FROM common AS builder
RUN apt-get install -y build-essential curl

FROM common AS runtime
```

**评估**：本质是方案 C 的"内部版本"，但 base 没有 tag 可复用，且**第一次构建**仍要下载全部包。解决的痛点和方案 C 一样，收益更小。**不推荐。**

## 3. 对比矩阵

| 维度 | 方案 A (BuildKit cache) | 方案 B (+ Registry) | 方案 C (Base 镜像) |
|------|-------------------------|---------------------|---------------------|
| 改动量 | 小 | 中 | 中-大 |
| 本地二次构建加速 | ✅✅ | ✅✅ | ✅✅✅ |
| 跨机 / CI 共享 | ❌ | ✅ | ✅ |
| 镜像体积优化 | — | — | ✅（省 1 个 apt 层） |
| 离线 / 受限网络友好 | ✅（包文件复用） | ✅ | ✅✅（根本不联网） |
| 维护成本 | 低 | 低 | 中 |
| 适用阶段 | 现在 | CI 跑通后 | 包列表稳定后 |

## 4. 推荐落地路径（分阶段）

1. **现在** → 实施方案 A。改 2 行 Dockerfile，立刻见效，零风险；第 77 行 `uv` 的 mount 已是同模式，照抄即可。
2. **CI 起来后** → 加方案 B。复用 `swr.cn-north-4`，`--cache-to mode=max` 缓存所有层。构建时间由"每 PR 全量"→"几乎增量"。
3. **包列表收敛稳定后** → 评估方案 C。把 base 镜像作为独立 artifact 版本化，绑到 apt 源更新节奏（如每月重烤一次）。最彻底，但要先确认包的变动频率是否值得每次重烤。

## 5. 待确认事项

落地前需先回答：

1. **主要部署场景**：本地 build / CI build / 内部 Harbor 拉取镜像？决定 B/C 优先级。
2. `apt-get install` 列表**是否频繁变动**？决定 C 是否值得。
3. CI 用什么 runner（自建 / GitHub Actions / 阿里云）？决定 B 的 cache 后端。
4. 是否有镜像仓库可放 cache / base？（`swr.cn-north-4` 已在用，应有。）

## 6. 参考

- `backend/Dockerfile` L26–L58（builder apt install）
- `backend/Dockerfile` L77（已有 BuildKit cache mount 范式）
- `backend/Dockerfile` L137–L168（runtime apt install）
- Docker BuildKit 文档：[--mount=type=cache](https://docs.docker.com/build/cache/optimize/#use-cache-mounts)
