# DeerFlow Docker 启动指南

## 快速启动

```bash
# 初始化 — 预拉取沙箱镜像（可选，加速首次启动）
./scripts/docker.sh init

# 启动 Docker 开发环境
./scripts/docker.sh start
```

启动后访问：**http://localhost:2026**

## 命令详解

| 命令 | 说明 |
|------|------|
| `./scripts/docker.sh init` | 预拉取沙箱镜像 |
| `./scripts/docker.sh start` | 启动全部服务（frontend + gateway + nginx） |
| `./scripts/docker.sh restart` | 重启所有运行中的服务 |
| `./scripts/docker.sh logs` | 查看全部日志 |
| `./scripts/docker.sh logs --frontend` | 仅前端日志 |
| `./scripts/docker.sh logs --gateway` | 仅网关日志 |
| `./scripts/docker.sh logs --nginx` | 仅 nginx 日志 |
| `./scripts/docker.sh stop` | 停止 Docker 服务 |
| `./scripts/docker.sh help` | 显示帮助 |

## 沙箱模式

脚本自动从 `config.yaml` 检测沙箱模式：

| 模式 | 配置 | 说明 |
|------|------|------|
| `local` | `LocalSandboxProvider` | 不需要 Docker 镜像 |
| `aio` | `AioSandboxProvider` 无 `provisioner_url` | 使用 AIO 沙箱 |
| `provisioner` | `AioSandboxProvider` + `provisioner_url` | Kubernetes 模式，额外启动 provisioner 服务 |

启动的服务：

- **标准模式**（local / aio）：`frontend` + `gateway` + `nginx`
- **Provisioner 模式**：`frontend` + `gateway` + `provisioner` + `nginx`

## 常见问题

**Q: 启动前需要配置什么？**

确保 `config.yaml` 存在且配置了 API keys。如不存在，脚本会自动从 `config.example.yaml` 复制一份。

**Q: 如何查看日志？**

```bash
./scripts/docker.sh logs --gateway   # 网关日志
./scripts/docker.sh logs --frontend  # 前端日志
```

**Q: 如何停止？**

```bash
./scripts/docker.sh stop
```