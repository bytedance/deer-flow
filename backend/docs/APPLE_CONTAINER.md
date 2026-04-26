# Apple Container支持

===================
设计思路说明
===================

**为什么支持Apple Container**：
DeerFlow现在支持Apple Container作为macOS上的首选容器运行时，并自动回退到Docker。

**设计决策**：
- **自动检测**：无需手动配置，系统自动选择最佳运行时
- **优先使用Apple Container**：在Apple Silicon Mac上提供原生性能
- **自动回退到Docker**：确保跨平台兼容性

**架构优势**：
- **性能优化**：Apple Container在Apple Silicon上提供更好的性能
- **资源节约**：比Docker Desktop更轻量
- **无缝集成**：使用macOS Virtualization.framework
- **零配置**：用户无需修改任何配置文件

## 概述

从该版本开始，DeerFlow在macOS上自动检测并使用Apple Container（如果可用），在以下情况下回退到Docker：
- Apple Container未安装
- 运行在非macOS平台上

这为Apple Silicon Mac提供了更好的性能，同时保持所有平台的兼容性。

## 优势

### 在带有Apple Container的Apple Silicon Mac上：
- **更好的性能**：无需Rosetta 2翻译的原生ARM64执行
- **更低的资源使用**：比Docker Desktop更轻量
- **原生集成**：使用macOS Virtualization.framework

### 回退到Docker：
- 完全的向后兼容性
- 在所有平台上工作（macOS、Linux、Windows）
- 无需配置更改

## 要求

### 对于Apple Container（仅macOS）：
- macOS 15.0或更高版本
- Apple Silicon (M1/M2/M3/M4)
- 已安装Apple Container CLI

### 安装：
```bash
# 从GitHub发布版本下载
# https://github.com/apple/container/releases

# 验证安装
container --version

# 启动服务
container system start
```

### 对于Docker（所有平台）：
- Docker Desktop或Docker Engine

## 工作原理

### 自动检测

`AioSandboxProvider`自动检测可用的容器运行时：

1. 在macOS上：尝试`container --version`
   - 成功 → 使用Apple Container
   - 失败 → 回退到Docker

2. 在其他平台上：直接使用Docker

### 运行时差异

两种运行时使用几乎相同的命令语法：

**容器启动：**
```bash
# Apple Container
container run --rm -d -p 8080:8080 -v /host:/container -e KEY=value image

# Docker
docker run --rm -d -p 8080:8080 -v /host:/container -e KEY=value image
```

**容器清理：**
```bash
# Apple Container（使用--rm标志）
container stop <id>  # 由于--rm而自动删除

# Docker（使用--rm标志）
docker stop <id>     # 由于--rm而自动删除
```

### 实现细节

实现在`backend/packages/harness/deerflow/community/aio_sandbox/aio_sandbox_provider.py`中：

- `_detect_container_runtime()`: 启动时检测可用运行时
- `_start_container()`: 使用检测到的运行时，为Apple Container跳过Docker特定选项
- `_stop_container()`: 为运行时使用适当的停止命令

## 配置

无需配置更改！系统自动工作。

但是，您可以通过检查日志来验证正在使用的运行时：

```
INFO:deerflow.community.aio_sandbox.aio_sandbox_provider:Detected Apple Container: container version 0.1.0
INFO:deerflow.community.aio_sandbox.aio_sandbox_provider:Starting sandbox container using container: ...
```

或者对于Docker：
```
INFO:deerflow.community.aio_sandbox.aio_sandbox_provider:Apple Container not available, falling back to Docker
INFO:deerflow.community.aio_sandbox.aio_sandbox_provider:Starting sandbox container using docker: ...
```

## 容器镜像

两种运行时都使用OCI兼容的镜像。默认镜像适用于两者：

```yaml
sandbox:
  use: deerflow.community.aio_sandbox:AioSandboxProvider
  image: enterprise-public-cn-beijing.cr.volces.com/vefaas-public/all-in-one-sandbox:latest  # 默认镜像
```

确保您的镜像适用于相应的架构：
- ARM64用于Apple Silicon上的Apple Container
- AMD64用于Intel Mac上的Docker
- 多架构镜像适用于两者

### 预拉取镜像（推荐）

**重要**：容器镜像通常很大（500MB+），在首次使用时拉取，可能导致长时间等待且没有明确的反馈。

**最佳实践**：在设置期间预拉取镜像：

```bash
# 从项目根目录
make setup-sandbox
```

此命令将：
1. 从`config.yaml`读取配置的镜像（或使用默认值）
2. 检测可用运行时（Apple Container或Docker）
3. 拉取镜像并显示进度
4. 验证镜像已准备就绪

**手动预拉取**：

```bash
# 使用Apple Container
container image pull enterprise-public-cn-beijing.cr.volces.com/vefaas-public/all-in-one-sandbox:latest

# 使用Docker
docker pull enterprise-public-cn-beijing.cr.volces.com/vefaas-public/all-in-one-sandbox:latest
```

如果您跳过预拉取，镜像将在首次代理执行时自动拉取，根据您的网络速度可能需要几分钟。

## 清理脚本

项目包括一个统一的清理脚本，可处理两种运行时：

**脚本：** `scripts/cleanup-containers.sh`

**用法：**
```bash
# 清理所有DeerFlow沙箱容器
./scripts/cleanup-containers.sh deer-flow-sandbox

# 自定义前缀
./scripts/cleanup-containers.sh my-prefix
```

**Makefile集成：**

`Makefile`中的所有清理命令自动处理两种运行时：
```bash
make stop   # 停止所有服务并清理容器
make clean  # 完整清理，包括日志
```

## 测试

测试容器运行时检测：

```bash
cd backend
python test_container_runtime.py
```

这将：
1. 检测可用运行时
2. 可选地启动测试容器
3. 验证连接
4. 清理

## 故障排除

### 在macOS上未检测到Apple Container

1. 检查是否已安装：
   ```bash
   which container
   container --version
   ```

2. 检查服务是否正在运行：
   ```bash
   container system start
   ```

3. 检查日志中的检测信息：
   ```bash
   # 在应用程序日志中查找检测消息
   grep "container runtime" logs/*.log
   ```

### 容器未清理

1. 手动检查运行中的容器：
   ```bash
   # Apple Container
   container list

   # Docker
   docker ps
   ```

2. 手动运行清理脚本：
   ```bash
   ./scripts/cleanup-containers.sh deer-flow-sandbox
   ```

### 性能问题

- Apple Container在Apple Silicon上应该更快
- 如果遇到问题，可以通过临时重命名`container`命令来强制使用Docker：
   ```bash
   # 临时解决方案 - 不建议永久使用
   sudo mv /opt/homebrew/bin/container /opt/homebrew/bin/container.bak
   ```

## 参考资料

- [Apple Container GitHub](https://github.com/apple/container)
- [Apple Container文档](https://github.com/apple/container/blob/main/docs/)
- [OCI镜像规范](https://github.com/opencontainers/image-spec)
