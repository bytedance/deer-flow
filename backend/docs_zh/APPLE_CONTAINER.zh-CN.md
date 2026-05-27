# Apple Container 支持

DeerFlow 现已支持在 macOS 上优先使用 Apple Container 作为容器运行时，并在不可用时自动回退到 Docker。

## 概述

从此版本开始，DeerFlow 会在 macOS 上自动检测并优先使用 Apple Container；在以下情况下会回退到 Docker：
- 未安装 Apple Container
- 运行在非 macOS 平台

这在保证全平台兼容性的同时，为 Apple Silicon Mac 提供更好的性能。

## 优势

### 在 Apple Silicon Mac 且使用 Apple Container 时：
- **更高性能**：原生 ARM64 执行，无需 Rosetta 2 转译
- **更低资源占用**：比 Docker Desktop 更轻量
- **原生集成**：基于 macOS Virtualization.framework

### 回退到 Docker 时：
- 完整向后兼容
- 可在所有平台运行（macOS、Linux、Windows）
- 无需修改配置

## 要求

### 使用 Apple Container（仅 macOS）：
- macOS 15.0 或更高版本
- Apple Silicon（M1/M2/M3/M4）
- 已安装 Apple Container CLI

### 安装：
```bash
# 从 GitHub Releases 下载
# https://github.com/apple/container/releases

# 验证安装
container --version

# 启动服务
container system start
```

### 使用 Docker（全平台）：
- Docker Desktop 或 Docker Engine

## 工作原理

### 自动检测

`AioSandboxProvider` 会自动检测可用容器运行时：

1. 在 macOS 上：尝试执行 `container --version`
   - 成功 → 使用 Apple Container
   - 失败 → 回退到 Docker

2. 在其他平台：直接使用 Docker

### 运行时差异

两种运行时的命令语法几乎一致：

**容器启动：**
```bash
# Apple Container
container run --rm -d -p 8080:8080 -v /host:/container -e KEY=value image

# Docker
docker run --rm -d -p 8080:8080 -v /host:/container -e KEY=value image
```

**容器清理：**
```bash
# Apple Container（带 --rm 参数）
container stop <id>  # 因 --rm 自动删除

# Docker（带 --rm 参数）
docker stop <id>     # 因 --rm 自动删除
```

### 实现细节

实现位于 `backend/packages/harness/deerflow/community/aio_sandbox/aio_sandbox_provider.py`：

- `_detect_container_runtime()`：启动时检测可用运行时
- `_start_container()`：使用检测到的运行时；对 Apple Container 跳过 Docker 专有选项
- `_stop_container()`：根据运行时使用对应停止命令

## 配置

无需修改任何配置，系统会自动生效。

不过你可以通过日志确认当前使用的运行时：

```
INFO:deerflow.community.aio_sandbox.aio_sandbox_provider:Detected Apple Container: container version 0.1.0
INFO:deerflow.community.aio_sandbox.aio_sandbox_provider:Starting sandbox container using container: ...
```

或者（Docker）：
```
INFO:deerflow.community.aio_sandbox.aio_sandbox_provider:Apple Container not available, falling back to Docker
INFO:deerflow.community.aio_sandbox.aio_sandbox_provider:Starting sandbox container using docker: ...
```

## 容器镜像

两种运行时都使用 OCI 兼容镜像。默认镜像可同时适配二者：

```yaml
sandbox:
  use: deerflow.community.aio_sandbox:AioSandboxProvider
  image: enterprise-public-cn-beijing.cr.volces.com/vefaas-public/all-in-one-sandbox:latest  # 默认镜像
```

请确保镜像支持对应架构：
- Apple Silicon 上的 Apple Container：ARM64
- Intel Mac 上的 Docker：AMD64
- 多架构镜像：两者都可用

### 预拉取镜像（推荐）

**重要**：容器镜像通常较大（500MB+），首次使用时拉取可能耗时较长，且反馈不明显。

**最佳实践**：在初始化阶段先预拉取镜像：

```bash
# 在项目根目录执行
make setup-sandbox
```

此命令会：
1. 从 `config.yaml` 读取已配置镜像（或使用默认值）
2. 检测可用运行时（Apple Container 或 Docker）
3. 显示进度并拉取镜像
4. 验证镜像可用性

**手动预拉取**：

```bash
# 使用 Apple Container
container image pull enterprise-public-cn-beijing.cr.volces.com/vefaas-public/all-in-one-sandbox:latest

# 使用 Docker
docker pull enterprise-public-cn-beijing.cr.volces.com/vefaas-public/all-in-one-sandbox:latest
```

如果跳过预拉取，首次执行 agent 时会自动拉取镜像；根据网络速度，可能需要几分钟。

## 清理脚本

项目提供了统一清理脚本，可同时处理两种运行时：

**脚本：** `scripts/cleanup-containers.sh`

**用法：**
```bash
# 清理所有 DeerFlow 沙箱容器
./scripts/cleanup-containers.sh deer-flow-sandbox

# 自定义前缀
./scripts/cleanup-containers.sh my-prefix
```

**Makefile 集成：**

`Makefile` 中所有清理命令都可自动兼容两种运行时：
```bash
make stop   # 停止所有服务并清理容器
make clean  # 完整清理（含日志）
```

## 测试

测试容器运行时检测：

```bash
cd backend
python test_container_runtime.py
```

此测试会：
1. 检测可用运行时
2. 可选地启动测试容器
3. 验证连通性
4. 执行清理

## 故障排查

### macOS 上未检测到 Apple Container

1. 检查是否安装：
   ```bash
   which container
   container --version
   ```

2. 检查服务是否运行：
   ```bash
   container system start
   ```

3. 查看检测日志：
   ```bash
   # 在应用日志中查找检测信息
   grep "container runtime" logs/*.log
   ```

### 容器未被清理

1. 手动查看正在运行的容器：
   ```bash
   # Apple Container
   container list

   # Docker
   docker ps
   ```

2. 手动执行清理脚本：
   ```bash
   ./scripts/cleanup-containers.sh deer-flow-sandbox
   ```

### 性能问题

- 在 Apple Silicon 上，Apple Container 理应更快
- 如遇问题，可通过临时重命名 `container` 命令来强制使用 Docker：
   ```bash
   # 临时方案，不建议长期使用
   sudo mv /opt/homebrew/bin/container /opt/homebrew/bin/container.bak
   ```

## 参考资料

- [Apple Container GitHub](https://github.com/apple/container)
- [Apple Container Documentation](https://github.com/apple/container/blob/main/docs/)
- [OCI Image Spec](https://github.com/opencontainers/image-spec)
