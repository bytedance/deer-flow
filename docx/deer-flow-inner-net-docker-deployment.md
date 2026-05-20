# DeerFlow 内网 Docker 部署指南

> 基于 vLLM (Qwen 3.5 27B) + PostgreSQL + 局域网环境
> 容器名称：pgvector-db (PostgreSQL)
> 日期：2026/05/18

---

## 一、网络架构

```
┌─────────────────────────────────────────────────────────────┐
│                    局域网 (192.168.x.0/24)                   │
│                                                             │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐   │
│  │  vLLM        │    │ pgvector-db │    │  DeerFlow    │   │
│  │ <VLLM_IP>    │    │  (Docker)   │    │  (Docker)    │   │
│  │   :8000      │    │   :5432     │    │   :2026      │   │
│  └──────────────┘    └──────────────┘    └──────┬───────┘   │
│                                                  │          │
│                                           ┌──────┴───────┐  │
│                                           │   Nginx      │  │
│                                           │   :2026      │  │
│                                           └──────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

---

## 二、需要修改的配置文件

### 文件 1：`.env`（项目根目录）

```bash
# ==================== 必须配置 ====================

# 数据库连接 - Docker 网络内使用容器名 pgvector-db
DATABASE_URL=postgresql://pgsql:Pass%401234@pgvector-db:5432/deerflow

# PostgreSQL 驱动必须（使用 postgres backend 时）
UV_EXTRAS=postgres

# vLLM API Key（内网通常无需认证，可留空）
VLLM_API_KEY=your-vllm-api-key

# 前端认证密钥 - 生成方式：openssl rand -base64 32
BETTER_AUTH_SECRET=请运行: openssl rand -base64 32

# ==================== 可选配置 ====================
# LANGSMITH_TRACING=false
```

### 文件 2：`config.yaml`（项目根目录）

```yaml
# ==================== 数据库配置 ====================
database:
  backend: postgres
  postgres_url: $DATABASE_URL

# ==================== 日志配置 ====================
log_level: info
token_usage:
  enabled: true

# ==================== 模型配置 ====================
models:
  # vLLM Qwen 3.5 27B - 请修改 <VLLM_IP> 为实际 IP
  - name: qwen3-27b-vllm
    display_name: Qwen3 27B (vLLM)
    use: deerflow.models.vllm_provider:VllmChatModel
    model: Qwen/Qwen3-27B-Instruct   # 根据 vLLM 部署的实际模型名修改
    api_key: $VLLM_API_KEY
    base_url: http://<VLLM_IP>:8000/v1
    request_timeout: 600.0
    max_retries: 2
    max_tokens: 8192
    supports_thinking: false
    supports_vision: false

# ==================== 工具配置 ====================
tools:
  - name: web_search
    group: web
    use: deerflow.community.ddg_search.tools:web_search_tool
    max_results: 5

  - name: web_fetch
    group: web
    use: deerflow.community.jina_ai.tools:web_fetch_tool
    timeout: 10

  - name: ls
    group: file:read
    use: deerflow.sandbox.tools:ls_tool

  - name: read_file
    group: file:read
    use: deerflow.sandbox.tools:read_file_tool

  - name: glob
    group: file:read
    use: deerflow.sandbox.tools:glob_tool
    max_results: 200

  - name: grep
    group: file:read
    use: deerflow.sandbox.tools:grep_tool
    max_results: 100

  - name: write_file
    group: file:write
    use: deerflow.sandbox.tools:write_file_tool

  - name: str_replace
    group: file:write
    use: deerflow.sandbox.tools:str_replace_tool

  - name: bash
    group: bash
    use: deerflow.sandbox.tools:bash_tool

# ==================== 沙箱配置 ====================
sandbox:
  use: deerflow.sandbox.local:LocalSandboxProvider
  allow_host_bash: false

# ==================== 记忆配置 ====================
memory:
  enabled: true
  storage_path: memory.json
  debounce_seconds: 30
  max_facts: 100
  injection_enabled: true
  max_injection_tokens: 2000

# ==================== 其他配置 ====================
title:
  enabled: true
  max_words: 6

summarization:
  enabled: true

run_events:
  backend: memory
```

---

## 三、部署步骤

### 步骤 1：修改 `.env`

```bash
# 在项目根目录下创建/修改 .env
cat >> .env << 'EOF'
DATABASE_URL=postgresql://pgsql:Pass%401234@pgvector-db:5432/deerflow
UV_EXTRAS=postgres
VLLM_API_KEY=your-vllm-api-key
BETTER_AUTH_SECRET=$(openssl rand -base64 32)
EOF
```

### 步骤 2：修改 `config.yaml`

将 `<VLLM_IP>` 替换为 vLLM 服务器的实际 IP：

```yaml
models:
  - name: qwen3-27b-vllm
    base_url: http://192.168.x.x:8000/v1  # 替换为实际 IP
```

### 步骤 3：确保 PostgreSQL 数据库存在

如果 `pgvector-db` 容器内还没有 `deerflow` 数据库：

```bash
# 进入 pgvector-db 容器
docker exec -it pgvector-db psql -U pgsql -d postgres

# 在 psql 内执行
CREATE DATABASE deerflow;
\q
```

### 步骤 4：构建并启动

```bash
# 进入 docker 目录
cd docker

# 构建镜像（带上 postgres extra）
UV_EXTRAS=postgres docker compose build

# 启动服务
docker compose up -d

# 查看状态
docker compose ps
```

---

## 四、初始化

### 创建管理员账户

访问 `http://<本机IP>:2026`，首次访问会显示初始化页面，点击 "Initialize Admin" 创建管理员。

或通过 API：

```bash
curl -X POST http://localhost:2026/api/v1/auth/initialize \
  -H "Content-Type: application/json" \
  -d '{"email": "admin@your-company.com", "password": "YourPassword123"}'
```

### 创建普通用户

```bash
curl -X POST http://localhost:2026/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email": "user@your-company.com", "password": "UserPassword123"}'
```

---

## 五、验证

### 健康检查

```bash
# Nginx
curl -I http://localhost:2026/health

# Gateway
curl http://localhost:8001/health

# 模型列表
curl http://localhost:2026/api/v1/models
```

### 测试消息发送

登录后发送一条测试消息，确认：
1. vLLM 模型被调用
2. 响应正常返回
3. 多用户记忆隔离正常

---

## 六、日常运维

```bash
# 查看日志
docker compose logs -f gateway

# 重启服务
docker compose restart

# 停止服务
docker compose down

# 进入 gateway 容器
docker exec -it deer-flow-gateway sh
```

---

## 七、快速检查清单

- [ ] `.env` 中 `DATABASE_URL` 已修改为 `pgvector-db:5432`
- [ ] `.env` 中 `UV_EXTRAS=postgres` 已设置
- [ ] `config.yaml` 中 `base_url` 已设置为 vLLM 实际 IP
- [ ] `BETTER_AUTH_SECRET` 已生成并配置
- [ ] PostgreSQL 中 `deerflow` 数据库已创建
- [ ] Docker 服务已启动 (nginx, frontend, gateway)
- [ ] 管理员账户已创建
- [ ] 浏览器可访问 `http://<本机IP>:2026`
- [ ] 发送消息测试成功

---

## 八、关键配置速查

| 配置项 | 值 |
|--------|-----|
| vLLM 地址 | `http://<VLLM_IP>:8000/v1` |
| PostgreSQL | `pgvector-db:5432` |
| 数据库名 | `deerflow` |
| 数据库用户 | `pgsql` |
| 数据库密码 | `Pass@1234` |
| DeerFlow 端口 | `2026` |
| Docker 网络 | `deer-flow` (bridge) |
| UV_EXTRAS | `postgres` |

---

## 九、已知限制

1. **vLLM IP 需要用户手动填写** - 文档中用 `<VLLM_IP>` 占位，需替换为实际 IP
2. **内网无 API Key 认证** - 需要确认 vLLM 服务是否开启了 API Key 验证
3. **模型名需要确认** - `Qwen/Qwen3-27B-Instruct` 是示例名称，需根据实际部署修改