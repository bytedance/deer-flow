# DeerFlow 离线 Linux Docker 部署指南

> macOS 构建 x86 镜像 → 离线迁移到 Linux → 运行
> 日期：2026/05/21

---

## 一、已知镜像信息（已验证）

| 镜像 | Tag | 大小 | 架构 |
|------|-----|------|------|
| `deer-flow-frontend` | latest | 1.4GB | linux/amd64 |
| `deer-flow-gateway` | latest | 1.16GB | linux/amd64 |
| `nginx` | alpine | 62.4MB | linux/amd64 |

---

## 二、macOS 端操作（导出镜像和文件）

### 2.1 导出 3 个 Docker 镜像

```bash
# 创建临时目录
mkdir -p ~/deer-flow-offline

# 导出镜像（分开保存，方便管理）
docker save deer-flow-frontend:latest -o ~/deer-flow-offline/deer-flow-frontend.tar
docker save deer-flow-gateway:latest -o ~/deer-flow-offline/deer-flow-gateway.tar
docker save nginx:alpine -o ~/deer-flow-offline/nginx-alpine.tar

# 验证文件
ls -lh ~/deer-flow-offline/
```

**预期输出：**
```
deer-flow-frontend.tar   1.4GB
deer-flow-gateway.tar    1.16GB
nginx-alpine.tar         ~62MB
```

### 2.2 准备部署文件包（简化版）

**推荐：直接使用预修改的 docker-compose.yaml，不手动修改。**

预修改的文件已保存在 `docx/offline-docker/docker-compose.yaml`，跳过手动修改步骤，直接执行步骤 3。

如果需要手动修改原文件，可参考以下命令（仅作参考，无需执行）：

```bash
# 以下命令仅作参考，请跳过，直接使用 docx/offline-docker/docker-compose.yaml
DEER_FLOW_ROOT=/Users/raidery/bench/harness/raidery/deer-flow
cd "$DEER_FLOW_ROOT"

# 创建部署目录
mkdir -p ~/deer-flow-offline/deploy-files

# ── 1. 复制预修改的 docker-compose.yaml（已改 build → image）─
cp docx/offline-docker/docker-compose.yaml ~/deer-flow-offline/deploy-files/docker-compose.yaml

# ── 2. 复制 nginx.conf（注意路径：docker/nginx/nginx.conf → deploy-files/nginx.conf）─
cp docker/nginx/nginx.conf ~/deer-flow-offline/deploy-files/nginx.conf

# ── 3. 复制配置文件（包含敏感密钥）──────────────────
# 注意：.env 包含 TAVILY_API_KEY、MINIMAX_API_KEY、AUTH_JWT_SECRET 等敏感信息
cp config.yaml ~/deer-flow-offline/deploy-files/config.yaml
cp extensions_config.json ~/deer-flow-offline/deploy-files/extensions_config.json
cp .env ~/deer-flow-offline/deploy-files/.env

# ── 4. 复制 frontend.env（如果存在）───────────────────
cp frontend/.env ~/deer-flow-offline/deploy-files/frontend.env 2>/dev/null || touch ~/deer-flow-offline/deploy-files/frontend.env

# ── 5. 复制 skills 目录（可选）────────────────────────
cp -r skills ~/deer-flow-offline/deploy-files/skills 2>/dev/null || echo "# skills not copied" > ~/deer-flow-offline/deploy-files/skills/README
```

### 2.3 验证部署文件

```bash
ls -lh ~/deer-flow-offline/deploy-files/
```

**预期文件清单：**
```
docker-compose.yaml   # 已修改，build → image
nginx.conf            # nginx 配置
config.yaml           # 主配置
extensions_config.json
.env                  # 环境变量
frontend.env          # 前端环境变量
skills/               # 技能目录（可选）
```

---

## 三、传输文件到 Linux

### 方式 A：scp（文件大，建议分批压缩）

```bash
# macOS 上打包（压缩减少传输时间）
cd ~
tar -czvf deer-flow-images.tar.gz deer-flow-offline/

# 传输镜像 tar 包
scp deer-flow-offline/deer-flow-frontend.tar user@linux-host:/tmp/
scp deer-flow-offline/deer-flow-gateway.tar user@linux-host:/tmp/
scp deer-flow-offline/nginx-alpine.tar user@linux-host:/tmp/

# 传输部署文件包
scp -r deer-flow-offline/deploy-files user@linux-host:/opt/deer-flow/
```

### 方式 B：rsync（增量、显示进度）

```bash
# macOS 上
rsync -avP ~/deer-flow-offline/deer-flow-*.tar user@linux-host:/tmp/
rsync -avP ~/deer-flow-offline/deploy-files/ user@linux-host:/opt/deer-flow/

# Linux 端确认文件完整性
ls -lh /tmp/deer-flow-*.tar
ls -lh /opt/deer-flow/
```

---

## 四、Linux 端操作（加载镜像和启动）

### 4.1 加载 Docker 镜像

```bash
# SSH 登录 Linux 后执行
cd /tmp

# 加载 3 个镜像
docker load -i deer-flow-frontend.tar
docker load -i deer-flow-gateway.tar
docker load -i nginx-alpine.tar

# 验证镜像已加载
docker images | grep -E "deer-flow|nginx"
```

**预期输出：**
```
deer-flow-frontend    latest    <IMAGE_ID>    1.4GB
deer-flow-gateway      latest    <IMAGE_ID>    1.16GB
nginx                  alpine    <IMAGE_ID>    62.4MB
```

### 4.2 检查部署目录

```bash
ls -lh /opt/deer-flow/
```

**预期内容：**
```
deploy-files/
  docker-compose.yaml
  nginx.conf
  config.yaml
  extensions_config.json
  .env
  frontend.env
  skills/
```

### 4.3 组织目录结构

```bash
# 创建标准目录结构
cd /opt/deer-flow
mkdir -p docker
mkdir -p .deer-flow
mkdir -p skills

# 移动配置文件到正确位置
mv deploy-files/docker-compose.yaml docker/
mv deploy-files/nginx.conf docker/
mv deploy-files/config.yaml .
mv deploy-files/extensions_config.json .
mv deploy-files/.env .
mv deploy-files/frontend.env .
[ -d deploy-files/skills ] && mv deploy-files/skills/* skills/ 2>/dev/null || true

# 清理临时目录
rm -rf deploy-files
```

**最终目录结构：**
```
/opt/deer-flow/
├── docker/
│   ├── docker-compose.yaml   # 已修改，build → image
│   └── nginx.conf
├── config.yaml
├── extensions_config.json
├── .env
├── frontend.env
├── skills/
└── .deer-flow/                # 运行时数据目录（自动创建）
```

---

## 五、修改配置文件

### 5.1 设置 BETTER_AUTH_SECRET

如果 `.env` 中没有设置，需要生成：

```bash
cd /opt/deer-flow

# 生成认证密钥
BETTER_AUTH_SECRET=$(openssl rand -hex 32 2>/dev/null || python3 -c "import secrets; print(secrets.token_hex(32))")

# 如果 .env 为空或不存在，创建它
cat > .env << EOF
BETTER_AUTH_SECRET=$BETTER_AUTH_SECRET
EOF

# 如果 .env 已存在但不完整，追加
echo "BETTER_AUTH_SECRET=$BETTER_AUTH_SECRET" >> .env

cat .env
```

### 5.2 修改 config.yaml（如需要）

确认 `config.yaml` 中的 API 密钥、模型配置、数据库连接等正确。参考 `docx/deerflow-docker-run-guide.md` 中的配置示例。

### 5.3 设置 skills 目录（如需要）

```bash
# 如果 skills 目录为空但部署文件未复制，手动复制
# 从 macOS rsync 或 scp 传输
rsync -av user@mac-host:/Users/raidery/bench/harness/raidery/deer-flow/skills/ /opt/deer-flow/skills/
```

---

## 六、启动 DeerFlow

### 6.1 创建 Docker 网络

```bash
cd /opt/deer-flow

# 删除旧网络（如存在）
docker network rm deer-flow 2>/dev/null || true

# 创建新网络
docker network create deer-flow
```

### 6.2 设置环境变量

```bash
cd /opt/deer-flow

# 设置所有必要环境变量
export DEER_FLOW_HOME="/opt/deer-flow/.deer-flow"
export DEER_FLOW_CONFIG_PATH="/opt/deer-flow/config.yaml"
export DEER_FLOW_EXTENSIONS_CONFIG_PATH="/opt/deer-flow/extensions_config.json"
export DEER_FLOW_DOCKER_SOCKET="/var/run/docker.sock"
export DEER_FLOW_REPO_ROOT="/opt/deer-flow"
export HOME=$(eval echo ~)
export BETTER_AUTH_SECRET=$(grep BETTER_AUTH_SECRET .env | cut -d= -f2)

# 创建运行时目录
mkdir -p "$DEER_FLOW_HOME"
```

### 6.3 启动服务（使用预加载镜像，不 rebuild）

```bash
cd /opt/deer-flow/docker

# 启动 3 个服务（nginx, frontend, gateway），不 rebuild
docker compose up -d --remove-orphans

# 查看状态
docker compose ps
```

**预期输出：**
```
NAME                    IMAGE                     STATUS
deer-flow-nginx         nginx:alpine              Up
deer-flow-frontend      deer-flow-frontend:latest Up
deer-flow-gateway       deer-flow-gateway:latest  Up
```

---

## 七、验证部署

### 7.1 健康检查

```bash
# 测试 nginx（外部入口）
curl -I http://localhost:2026/health

# 预期：HTTP 200

# 测试 gateway API
curl http://localhost:2026/api/models

# 预期：返回 JSON 格式的模型列表

# 测试 frontend
curl -I http://localhost:2026/

# 预期：HTTP 200，指向 Next.js
```

### 7.2 查看日志

```bash
# 查看所有服务日志
docker compose -f /opt/deer-flow/docker/docker-compose.yaml logs -f

# 只看 gateway
docker compose -f /opt/deer-flow/docker/docker-compose.yaml logs -f gateway

# 只看 frontend
docker compose -f /opt/deer-flow/docker/docker-compose.yaml logs -f frontend
```

---

## 八、日常运维命令

```bash
cd /opt/deer-flow/docker

# 停止服务
docker compose down

# 重启服务
docker compose restart

# 查看容器
docker compose ps

# 查看资源使用
docker stats

# 进入 gateway 容器（调试）
docker exec -it deer-flow-gateway sh

# 完全清理（包括数据卷）
docker compose down -v
```

---

## 九、部署检查清单

| 步骤 | 操作 | 验证 |
|------|------|------|
| 1 | macOS 导出镜像 | `docker save` 成功，3 个 tar 文件存在 |
| 2 | 传输镜像到 Linux | `ls -lh /tmp/deer-flow-*.tar` 确认大小 |
| 3 | Linux 加载镜像 | `docker images` 看到 3 个镜像 |
| 4 | 传输配置文件 | `/opt/deer-flow/` 目录结构完整 |
| 5 | 修改 docker-compose.yaml | `build:` 已改为 `image:` |
| 6 | 生成 BETTER_AUTH_SECRET | `.env` 中已设置 |
| 7 | 创建 Docker 网络 | `docker network ls` 看到 deer-flow |
| 8 | 启动服务 | `docker compose ps` 显示 3 个 Up |
| 9 | 健康检查 | `curl http://localhost:2026/health` 返回 200 |

---

## 十、常见问题排查

### 问题 1：容器启动失败

```bash
# 查看具体日志
docker compose logs gateway

# 常见原因：config.yaml 配置错误、端口冲突、权限问题

# 检查端口占用
ss -tlnp | grep -E "2026|3000|8001"
```

### 问题 2：nginx 启动失败

```bash
# 检查 nginx.conf 路径
docker compose logs nginx

# 确认 nginx.conf 在 docker/ 目录下
ls -lh /opt/deer-flow/docker/nginx.conf
```

### 问题 3：frontend 连接不到 gateway

```bash
# 检查网络
docker network inspect deer-flow

# 检查 gateway 是否正常运行
docker compose ps gateway

# 测试容器内连通性
docker exec -it deer-flow-frontend ping gateway
```

### 问题 4：Permission denied（.deer-flow 目录）

```bash
# 修改权限
sudo chown -R $(id -u):$(id -g) /opt/deer-flow/.deer-flow
```

---

## 十一、完整一键部署脚本（Linux 用）

保存到 `/opt/deer-flow/start.sh`，执行 `chmod +x start.sh && ./start.sh`

```bash
#!/bin/bash
#
# DeerFlow 离线部署启动脚本
# 用法：./start.sh
#

set -e

DEPLOY_DIR="/opt/deer-flow"
PORT="${PORT:-2026}"
COMPOSE_FILE="$DEPLOY_DIR/docker/docker-compose.yaml"

echo "=========================================="
echo "  DeerFlow 离线部署"
echo "=========================================="

# 检查镜像是否已加载
echo "==> 检查 Docker 镜像..."
IMAGES=$(docker images --format '{{.Repository}}:{{.Tag}}' | grep -E "^deer-flow-frontend:|^deer-flow-gateway:|^nginx:alpine$" | wc -l)
if [ "$IMAGES" -lt 3 ]; then
    echo "✗ 镜像未完全加载，请先执行 docker load -i *.tar"
    echo "  当前镜像："
    docker images | grep -E "deer-flow|nginx"
    exit 1
fi
echo "✓ 3 个镜像已加载"

# 检查配置文件
echo "==> 检查配置文件..."
for f in "$DEPLOY_DIR/config.yaml" "$DEPLOY_DIR/extensions_config.json" "$COMPOSE_FILE" "$DEPLOY_DIR/docker/nginx.conf"; do
    if [ ! -f "$f" ]; then
        echo "✗ 缺少文件: $f"
        exit 1
    fi
done
echo "✓ 配置文件完整"

# 创建目录
echo "==> 创建运行时目录..."
mkdir -p "$DEPLOY_DIR/.deer-flow"
mkdir -p "$DEPLOY_DIR/skills"

# 创建网络
echo "==> 创建 Docker 网络..."
docker network rm deer-flow 2>/dev/null || true
docker network create deer-flow 2>/dev/null || true

# 设置环境变量
export DEER_FLOW_HOME="$DEPLOY_DIR/.deer-flow"
export DEER_FLOW_CONFIG_PATH="$DEPLOY_DIR/config.yaml"
export DEER_FLOW_EXTENSIONS_CONFIG_PATH="$DEPLOY_DIR/extensions_config.json"
export DEER_FLOW_DOCKER_SOCKET="/var/run/docker.sock"
export DEER_FLOW_REPO_ROOT="$DEPLOY_DIR"
export HOME=$(eval echo ~)

# 生成 BETTER_AUTH_SECRET（如需要）
if ! grep -q "BETTER_AUTH_SECRET" "$DEPLOY_DIR/.env" 2>/dev/null || [ ! -s "$DEPLOY_DIR/.env" ]; then
    echo "==> 生成 BETTER_AUTH_SECRET..."
    SECRET=$(openssl rand -hex 32 2>/dev/null || python3 -c "import secrets; print(secrets.token_hex(32))")
    echo "BETTER_AUTH_SECRET=$SECRET" >> "$DEPLOY_DIR/.env"
    export BETTER_AUTH_SECRET="$SECRET"
fi

export BETTER_AUTH_SECRET=$(grep BETTER_AUTH_SECRET "$DEPLOY_DIR/.env" | cut -d= -f2)
echo "✓ BETTER_AUTH_SECRET 已设置"

# 启动服务
echo "==> 启动 DeerFlow 服务..."
cd "$DEPLOY_DIR/docker"
docker compose up -d --remove-orphans

echo ""
echo "==> 容器状态..."
docker compose ps

echo ""
echo "=========================================="
echo "  DeerFlow 已启动"
echo "  🌐 访问地址: http://localhost:$PORT"
echo "=========================================="
echo ""
echo "  日志查看: docker compose -f $COMPOSE_FILE logs -f"
echo "  停止服务: docker compose -f $COMPOSE_FILE down"
echo ""
```

---

## 十二、关键文件路径速查

| 文件/目录 | macOS 源路径 | Linux 目标路径 |
|-----------|-------------|---------------|
| 镜像包（前端） | `~/deer-flow-offline/deer-flow-frontend.tar` | `/tmp/deer-flow-frontend.tar` |
| 镜像包（网关） | `~/deer-flow-offline/deer-flow-gateway.tar` | `/tmp/deer-flow-gateway.tar` |
| 镜像包（nginx） | `~/deer-flow-offline/nginx-alpine.tar` | `/tmp/nginx-alpine.tar` |
| docker-compose | `docker/docker-compose.yaml` | `/opt/deer-flow/docker/docker-compose.yaml` |
| nginx.conf | `docker/nginx/nginx.conf` | `/opt/deer-flow/docker/nginx.conf` |
| config.yaml | `config.yaml` | `/opt/deer-flow/config.yaml` |
| extensions_config.json | `extensions_config.json` | `/opt/deer-flow/extensions_config.json` |
| .env | `.env` | `/opt/deer-flow/.env` |
| frontend.env | `frontend/.env` | `/opt/deer-flow/frontend.env` |
| skills/ | `skills/` | `/opt/deer-flow/skills/` |

---

## 十三、依赖关系图

```
macOS 构建 → save → tar 文件
                    ↓
           scp/rsync → Linux /tmp/
                    ↓
           docker load → 本地镜像
                    ↓
           配置文件 → /opt/deer-flow/
                    ↓
           docker network create
                    ↓
           docker compose up -d
                    ↓
                运行中 ← http://localhost:2026
```

---

## 十四、注意事项

1. **架构一致**：镜像已在 macOS 上以 `--platform linux/amd64` 构建，Linux 直接加载即可运行，无需重新 build。

2. **不要修改 nginx.conf 路径**：原文件在 `docker/nginx/nginx.conf`，部署到 Linux 后放在 `docker/nginx.conf`（注意少了 `nginx/` 子目录），docker-compose.yaml 中的 volume 挂载已对应调整。

3. **docker-compose.yaml 已修改**：frontend 和 gateway 的 `build:` 已改为 `image:`，在 Linux 上启动时不会触发 rebuild，直接使用预加载镜像。

4. **skills 目录可选**：如果不使用 agent skills，可以跳过 skills 的传输。但建议传输，因为 gateway 启动时会检查 skills 目录。

5. **BETTER_AUTH_SECRET 必须设置**：这是 Next.js 认证必需的，不设置会导致 frontend 无法正常工作。