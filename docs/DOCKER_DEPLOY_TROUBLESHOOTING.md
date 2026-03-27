# 🦌 DeerFlow 2.0 本地化部署与排坑实战指南

**文档维护：** Hical
**适用环境：** Windows + Docker Desktop (企业内网管控环境)

## 📌 项目简介
DeerFlow 是一个强大的多智能体（Multi-Agent）协作框架，专为长时间运行的复杂自主任务设计（如自动化编码、深度调研、排障分析）。底层基于 LangGraph，支持沙盒（Sandbox）隔离执行。

---

## 🛠️ 部署前置准备

由于公司终端管控策略（如 IP-Guard 等防泄密软件）可能会禁用系统 WSL (Windows Subsystem for Linux) 或拦截 C 盘挂载，建议 Docker Desktop 配置如下：
1. **禁用 WSL**：若启动 Docker 报错，修改 `%APPDATA%\Docker\settings.json`，将 `"wslEngineEnabled"` 改为 `false`，强制使用 Hyper-V 引擎。
2. **准备代码**：
   
```bash
   git clone https://github.com/bytedance/deer-flow.git
   cd deer-flow
   
```

## ⚙️ 核心配置修改 (避坑指南)
为了防止在启动和编译过程中出现各种“水土不服”的报错，在执行启动命令前，请务必完成以下 5 步修改：

1. **配置根目录 .env**：复制 .env.example 重命名为 .env，并在末尾追加以下关键变量：
```env
# 大模型 Token
ANTHROPIC_API_KEY=XXXXXX

# 必须配置 Auth 组件的 Base URL，否则前端 SSR 渲染会报 500 错误！(端口固定为 2026)
BETTER_AUTH_BASE_URL=http://localhost:2026
BETTER_AUTH_SECRET=glacier_network_super_secret_key_2026

```
2. **配置大模型 config.yaml**：复制 config.example.yaml 重命名为 config.yaml，配置内网模型：
models:
  - name: claude-sonnet-4-6
    display_name: Claude Sonnet 4.6 (Claude Code OAuth)
    use: langchain_anthropic:ChatAnthropic
    model: claude-4.5-sonnet
    api_key: $ANTHROPIC_API_KEY
    max_tokens: 8192

# 记得把系统默认的模型指向刚才配置好的这个内网模型
default_model: claude-sonnet-4-6

3. **切除敏感挂载卷 (防 Docker 崩溃)**：打开 docker/docker-compose.yml，搜索 .claude。将这部分挂载代码整块注释掉或删除，防止安全软件拦截对 C 盘敏感目录的访问导致 Docker 引擎闪退：

```yaml
# - type: bind
#   source: ${HOME:?HOME must be set}/.claude
#   target: /root/.claude
#   ...

```

4. **修复前端编译“总闸” (防 Next.js 语法报错)**：开源代码存在部分 TypeScript 类型缺失。为防止构建失败，打开 frontend/next.config.js，注入忽略报错配置：

```javascript
import "./src/env.js";

/** @type {import("next").NextConfig} */
const config = {
  devIndicators: false,
  typescript: { ignoreBuildErrors: true }, // 强制忽略 TS 报错
  eslint: { ignoreDuringBuilds: true },    // 强制忽略格式报错
};

export default config;

```

5. **补齐致命的“空洞文件 (防前端白屏 500 错误)**：这一步极其重要，否则页面渲染会报 Cannot read properties of undefined (reading 'sections')：

# 新建前端环境变量：在 frontend/ 目录下新建 .env 文件，填入：
```env
   NEXT_PUBLIC_API_URL=http://localhost:2026/api
   BETTER_AUTH_URL=http://localhost:2026
   BETTER_AUTH_SECRET=glacier_network_super_secret_key_2026
   
```
# 初始化扩展配置：在项目根目录下新建或修改 extensions_config.json 文件，填入空数组，绝不能留空 {}：
```json

{
  "sections": []
}

```

6. **其他语法错误修复**：
#  frontend/src/core/i18n/locales/types.ts ：在 tokenUsage 的 total: string; 后添加了 }; 闭合括号，让 shortcuts 和 settings 恢复为顶层属性。

#  frontend/src/core/i18n/locales/en-US.ts ：在 tokenUsage 的 total: "Total", 后添加了 }, 并移除了末尾多余的 }。

# frontend/src/core/i18n/locales/zh-CN.ts：在 tokenUsage 的 total: "总计", 后添加了 }, 并将末尾的 }} 改为 }。


7. **启动集群**：
# 进入 docker 目录，执行终极启动指令（首次拉取可能较慢，建议配置阿里云 Docker 镜像源）：

```bash

cd docker
docker compose --env-file ../.env up -d --build

```
# 注意：(如果中途构建失败，或者修改了环境变量，可使用 docker compose --env-file ../.env build --no-cache frontend 强制清除缓存重新打包。)

8. **验收与使用**：
# 当执行 docker compose ps 看到 nginx、frontend、langgraph、postgres 等容器均处于 Up 状态时，部署完成！
# 打开浏览器，访问 Nginx 统一网关地址：👉 http://localhost:2026
# 点击首屏进入 Workspace。
# 在底部对话框输入复杂的排障指令，体验多智能体在隔离沙盒中的自动编码与分析能力！

9. **后续启动踩坑补充**：
# DeerFlow Docker 部署问题排查总结

## 问题背景

在 Windows 环境下通过 `docker compose --env-file ../.env up -d` 启动 DeerFlow 时，持续报错：

```
Error response from daemon: {"message":"No such image: nginx:alpine"}
Error response from daemon: {"message":"No such image: deer-flow-gateway"}
```

---

## 根本原因

`docker compose up` 在构建镜像时默认调用 **BuildKit**（`docker buildx`）。
BuildKit 构建完成后，会额外执行 `resolving provenance` 步骤，将镜像打包成 **OCI manifest list（多平台清单索引）**，存储在 BuildKit 自己的 cache 存储中，**而不是写入 Docker daemon 的标准 image store**。

所以：
- `docker compose build` 显示 `Service xxx Built` ✅ — 构建日志正常
- `docker compose up` 报 `No such image: xxx` ❌ — daemon 里实际没有该镜像
- `docker images` 显示镜像存在 ❌ — 显示的是 BuildKit cache 中的幻象，并非 daemon 里的真实镜像

---

## 完整排查流程

### 第一阶段：镜像拉取失败

**报错：**
```
Error response from daemon: No such image: nginx:alpine
```

**原因：** 国内网络无法直接访问 Docker Hub。

**解决：** 配置 Docker Desktop 镜像加速。

打开 Docker Desktop → Settings → Docker Engine，添加以下配置：

```json
{
  "registry-mirrors": [
    "https://docker.1ms.run",
    "https://docker.xuanyuan.me",
    "https://dockerpull.org"
  ]
}
```

Apply & Restart 后重新拉取：

```powershell
docker pull nginx:alpine
```

---

### 第二阶段：Context 隔离问题

`docker pull nginx:alpine` 成功，但 compose 仍然找不到镜像。

**原因：** Docker Desktop 在 Windows 上存在两个 context：

```
NAME            DOCKER ENDPOINT
default         npipe:////./pipe/docker_engine          # Windows Docker engine
desktop-linux * npipe:////./pipe/dockerDesktopLinuxEngine  # Docker Desktop Linux engine
```

pull 和 compose 使用了不同的 context，镜像存在于不同的 daemon 中。

**解决：** 确保 pull 和 compose 在同一个 context 下执行：

```powershell
# 切换到 Docker Desktop 的 Linux engine
docker context use desktop-linux

# 重新拉取
docker pull nginx:alpine
```

---

### 第三阶段：BuildKit manifest list 问题（根本原因）

构建服务镜像（`frontend` / `gateway` / `langgraph`）每次 build 完都报：

```
Error response from daemon: No such image: deer-flow-gateway
```

**排查过程：**

| 尝试方案                                                            | 结果                                                               |
| ------------------------------------------------------------------- | ------------------------------------------------------------------ |
| `--pull never` 跳过 nginx pull                                      | 构建镜像仍写不进 daemon                                            |
| `BUILDX_NO_DEFAULT_ATTESTATIONS=1`                                  | 无效，provenance 步骤仍执行                                        |
| `DOCKER_BUILDKIT=0` 禁用 BuildKit                                   | 失败，Dockerfile 中 `RUN --mount=type=cache` 语法必须依赖 BuildKit |
| 关闭 Docker Desktop "Use containerd for pulling and storing images" | 不是根本原因，无效                                                 |
| `docker buildx build --provenance=false --output type=docker`       | `docker inspect` 报找不到，BuildKit cache 混淆                     |
| `docker compose` yaml 中添加 `provenance: false`                    | compose v2.31 不支持该字段，报 schema 校验错误                     |

**根本原因确认：** BuildKit 即使使用 `docker` driver，v0.17.3 版本的 provenance attestation 仍会将最终产物封装为 OCI index，导致 Docker daemon 无法直接运行。

---

## 最终解决方案

绕过 BuildKit，使用标准 `docker build` 手动构建镜像，然后 compose 用 `--pull never` 跳过自动 pull。

### Step 1：手动构建三个服务镜像

```powershell
cd d:\hical\deer-flow

# 构建 frontend
docker build -t deer-flow-frontend -f frontend/Dockerfile --target prod .

# 构建 gateway
docker build -t deer-flow-gateway -f backend/Dockerfile .

# 构建 langgraph（与 gateway 使用同一个 Dockerfile）
docker build -t deer-flow-langgraph -f backend/Dockerfile .
```

### Step 2：验证镜像写入 daemon

```powershell
docker inspect deer-flow-frontend --format "{{.Id}}"
docker inspect deer-flow-gateway --format "{{.Id}}"
docker inspect deer-flow-langgraph --format "{{.Id}}"
```

三个命令都返回 `sha256:...` ID 即表示成功。

### Step 3：启动服务

```powershell
cd d:\hical\deer-flow\docker
docker compose -p deer-flow --env-file ../.env up -d --pull never
```

### Step 4：验证所有容器正常运行

```powershell
docker compose -p deer-flow ps
```

期望输出（4 个容器均为 `Up` 状态）：

```
NAME                  IMAGE                 STATUS
deer-flow-frontend    deer-flow-frontend    Up
deer-flow-gateway     deer-flow-gateway     Up
deer-flow-langgraph   deer-flow-langgraph   Up
deer-flow-nginx       nginx:alpine          Up    0.0.0.0:2026->2026/tcp
```

访问 http://localhost:2026 验证服务是否正常。

---

## 关键结论

| 知识点                                 | 说明                                                                                          |
| -------------------------------------- | --------------------------------------------------------------------------------------------- |
| `docker compose build` 默认用 BuildKit | BuildKit 构建产物是 OCI manifest list，存在自己的 cache 里，`docker run/compose` 无法直接使用 |
| `docker build`（非 buildx）            | 直接写入 Docker daemon image store，`docker run/compose` 可正常使用                           |
| `--pull never`                         | 防止 compose 对已有镜像（如 nginx）尝试重新拉取而报错                                         |
| `-p deer-flow`                         | 指定项目名，确保镜像名为 `deer-flow-*` 而非目录名 `docker-*`                                  |
| Docker Desktop context                 | Windows 上有 `default` 和 `desktop-linux` 两个 context，需保持一致                            |

---

## 重新部署流程（快速参考）

下次重新部署时，直接执行以下命令：

```powershell
# 1. 确认使用 desktop-linux context
docker context use desktop-linux

# 2. 进入项目根目录，构建三个服务镜像
cd d:\hical\deer-flow
docker build -t deer-flow-frontend -f frontend/Dockerfile --target prod .
docker build -t deer-flow-gateway -f backend/Dockerfile .
docker build -t deer-flow-langgraph -f backend/Dockerfile .

# 3. 启动服务
cd docker
docker compose -p deer-flow --env-file ../.env up -d --pull never

# 4. 查看状态
docker compose -p deer-flow ps
```

---

## 停止服务

```powershell
cd d:\hical\deer-flow\docker
docker compose -p deer-flow down
```

---

## 附：502 Bad Gateway — gateway 启动失败排查

### 现象

服务启动后访问 `http://localhost:2026` 下载报告等页面时显示：

```
502 Bad Gateway
nginx/1.29.7
```

所有容器状态均为 `Up`，但功能不可用。

### 排查过程

**Step 1：确认容器状态**

```powershell
docker compose -p deer-flow ps
```

4 个容器均 `Up`，排除容器崩溃。

**Step 2：查看 gateway 启动日志**

```powershell
docker logs deer-flow-gateway --tail 30
```

发现关键报错：

```
RuntimeError: Failed to load configuration during gateway startup:
Config file specified by environment variable `DEER_FLOW_CONFIG_PATH`
not found at D:\hical\deer-flow\config.yaml
```

**Step 3：定位根本原因**

检查 `.env` 文件：

```env
DEER_FLOW_CONFIG_PATH=D:\hical\deer-flow\config.yaml
DEER_FLOW_EXTENSIONS_CONFIG_PATH=D:\hical\deer-flow\extensions_config.json
```

`docker-compose.yaml` 通过 `env_file: ../.env` 将 `.env` 所有变量注入容器。容器是 Linux 环境，无法识别 Windows 路径 `D:\...`，导致 gateway 进程启动失败，nginx 因上游无响应返回 502。

### 根本原因

`.env` 里的路径变量同时承担两个角色：
- **volume mount 的宿主机路径**（由 Docker Desktop 解析，支持 `D:/...` 格式）
- **容器内环境变量**（由容器内 Linux 进程读取，不支持 Windows 路径）

`docker-compose.yaml` 的 `env_file` 会将所有 `.env` 变量透传进容器，但 gateway 服务的 `environment` 块没有用容器内路径覆盖这两个变量，导致 Windows 路径泄露进容器。

### 解决方案

在 `docker/docker-compose.yaml` 的 gateway `environment` 块中显式覆盖为容器内路径（`environment` 优先级高于 `env_file`）：

```yaml
# gateway 服务的 environment 块
environment:
  - CI=true
  - DEER_FLOW_HOME=/app/backend/.deer-flow
  - DEER_FLOW_CONFIG_PATH=/app/backend/config.yaml            # 覆盖 .env 中的 Windows 路径
  - DEER_FLOW_EXTENSIONS_CONFIG_PATH=/app/backend/extensions_config.json  # 覆盖 .env 中的 Windows 路径
  - DEER_FLOW_HOST_BASE_DIR=${DEER_FLOW_HOME}
  - DEER_FLOW_HOST_SKILLS_PATH=${DEER_FLOW_REPO_ROOT}/skills
  - DEER_FLOW_SANDBOX_HOST=host.docker.internal
env_file:
  - ../.env
```

> langgraph 服务原本已有 `DEER_FLOW_CONFIG_PATH=/app/config.yaml` 和 `DEER_FLOW_EXTENSIONS_CONFIG_PATH=/app/extensions_config.json` 覆盖，无需修改。

修改后重启容器：

```powershell
cd d:\hical\deer-flow\docker
docker compose -p deer-flow --env-file ../.env up -d --pull never
```

验证 gateway 正常启动：

```powershell
docker logs deer-flow-gateway --tail 5
# 期望看到：INFO: Application startup complete.

curl http://localhost:2026/health
# 期望返回：{"status":"healthy","service":"deer-flow-gateway"}
```

### 关键结论

| 知识点 | 说明 |
|-------|------|
| `env_file` 透传所有变量 | `.env` 里的 Windows 路径会原样注入容器，Linux 进程无法识别 |
| `environment` 优先级更高 | 在 compose 的 `environment` 块中覆盖同名变量，可防止 `env_file` 的值污染容器 |
| volume mount 路径 vs 容器内路径 | 宿主机路径用于 `volumes` 挂载（Docker Desktop 自动转换），容器内路径用于程序运行时读取 |

