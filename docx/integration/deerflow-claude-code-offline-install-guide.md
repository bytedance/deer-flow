# DeerFlow 内网离线环境安装 Claude Code 2.1.139 指南

> 目标：将 `claude` CLI v2.1.139 烘焙到 `deer-flow-gateway` 容器镜像中，供 gateway 通过 `import anthropic` 模式（`backend/packages/harness/deerflow/models/claude_provider.py`）调用 Claude 时，按需生成/刷新 OAuth 凭据。
> 适用版本：DeerFlow `m2` 分支，`backend/Dockerfile`（多阶段：builder / dev / runtime）
> 日期：2026/06/05
> 版本：2.0

---

## 一、背景与目标

### 1.1 现状

- DeerFlow gateway 通过 `claude_provider:ClaudeChatModel`（继承 `ChatAnthropic`）直接调 Anthropic API。
- 代码路径使用 `import anthropic`（Anthropic Python SDK）+ `from langchain_anthropic import ChatAnthropic`，**不再走 ACP 协议**。
- `claude` CLI（`@anthropic-ai/claude-code`）在容器内仅用于**生成/刷新 OAuth 凭据**（`claude login` → 写 `~/.claude/.credentials.json`），运行时不调它。

### 1.2 问题

在**纯内网、无法访问 npm registry** 的环境：

- `npm install -g @anthropic-ai/claude-code@2.1.139` 拉不到包，容器内没有 `claude` 二进制；
- Python 依赖（`anthropic` / `langchain_anthropic` 等）已通过其他途径（私有 pypi 镜像 / wheel vendor / 系统包）安装完毕，不在本文档讨论范围内。

### 1.3 目标

把以下组件烘焙进 `deer-flow-gateway` 镜像：

| 编号 | 组件 | 版本 | 用途 |
|---|---|---|---|
| ① | `claude` CLI | **2.1.139** | 容器内 `claude login` 生成 OAuth 凭据（**非热路径**） |
| ② | `claude` CLI 的全部 npm 依赖 | 随 ① 自动解析 | 离线安装时**必须一并 vendor**，否则 `npm install` 拉不到 |
| ③ | Node.js | 22.x（已有） | `claude` CLI 的运行时 |

使 `docker exec deer-flow-gateway claude --version` 输出 `2.1.139`，且 gateway 通过 `claude_provider.py` 调 Anthropic API 时能正确读到凭据（OAuth 模式）或环境变量（API key 模式）。

> **关于 vendor 方式**：`npm pack` 出来的 tarball **只含 package 自身文件**（`package.json` + `lib/` + `bin/`），**不含** `node_modules/` 里的 transitive 依赖。离线环境 `npm install` 会去 registry 拉 deps 失败。所以本文档用 `npm install --prefix <staging>` 把整个 staging prefix（含 `bin/` 和 `lib/node_modules/` 全量依赖）打成 tar 一次性带入镜像。

---

## 二、DeerFlow 项目内的"Claude Code"三重含义

| 名字 | 是什么 | 路径 / 安装位置 | 是否必须 |
|---|---|---|---|
| **① `claude` CLI** | Anthropic 官方命令行工具（`@anthropic-ai/claude-code`） | `/usr/local/bin/claude`（系统级安装）| **可选**（仅用于生成/刷新 OAuth 凭据）|
| **② `claude_provider.py`** | Python SDK 包装（继承 `ChatAnthropic`）| `backend/packages/harness/deerflow/models/claude_provider.py` | **gateway 实际调用** |
| **③ Claude 凭据** | OAuth token（`~/.claude/.credentials.json`）或 `$ANTHROPIC_API_KEY` | docker-compose 挂载 `/root/.claude` 或环境变量 | 必须 |

> 关键点：v2.0 之后**不再需要** `@zed-industries/claude-agent-acp`、**不再需要** ACP 适配器、**不再需要** `invoke_acp_agent` 工具的 Claude 相关配置。`claude` CLI 在容器里只承担「一次性登录拿 token」的职责，热路径完全由 Python SDK 直连 Anthropic。

### 调用链

```
DeerFlow gateway 进程
  └─ claude_provider:ClaudeChatModel.__init__
        └─ credential_loader.load_claude_code_credential()
              ├─ 读 $ANTHROPIC_API_KEY（API key 模式）
              └─ 或读 /root/.claude/.credentials.json（OAuth 模式）
                    └─ → Anthropic Python SDK → api.anthropic.com
```

---

## 三、整体方案

### 3.1 总体策略

完全离线安装 `claude` CLI 的标准三步：

```
① 在能上网的机器上 npm pack @anthropic-ai/claude-code@2.1.139 打成 tarball
   ↓
② 把 tarball 拷到内网项目目录
   ↓
③ Dockerfile runtime 阶段 npm install -g 离线装
```

### 3.2 目录结构（最终态）

```
deer-flow/
├── backend/Dockerfile                              ← 改 runtime 阶段尾部加一段
├── offline-claude/                                 ← 新增：本地 vendor 目录
│   └── claude-code-bundled-2.1.139.tar.gz          ← 整个 npm staging 目录打包（含 bin/ + lib/node_modules/ 全量依赖）
└── config.yaml                                     ← 加 models: 段注册 ClaudeChatModel
```

### 3.3 总体流程

| 步骤 | 在哪做 | 是否要网 | 产物 |
|---|---|---|---|
| 1. `npm install --prefix staging` + `tar` 整个 staging | 在线 | ✅ | `offline-claude/claude-code-bundled-2.1.139.tar.gz`（~100-150 MB） |
| 2. `offline-claude/` 目录随项目带到内网 | 任意 | ❌ | 镜像构建可访问的 vendor 包 |
| 3. 改 `backend/Dockerfile`（runtime 阶段加 install 段） | 内网 | ❌ | 新镜像 |
| 4. 改 `config.yaml` 在 `models:` 段注册 `ClaudeChatModel` | 内网 | ❌ | gateway 可用 Claude 模型 |
| 5. `docker build` 或 `docker load` | 内网 | ❌ | 离线镜像 |
| 6. 拿 OAuth token（任选：host `claude login` / 容器内 `claude login` / 改用 `ANTHROPIC_API_KEY`） | 内网 host 或容器 | ✅（一次性，需通 anthropic.com）| `~/.claude/.credentials.json` 或环境变量 |
| 7. `docker compose up -d` + 验证 | 内网 | ❌ | 服务可用 |

---

## 四、详细步骤

### 4.1 步骤 1：在线机器准备 Claude Code CLI 离线包（含全部依赖）

`npm pack` 只能把 package 自身打成 tarball（~5 MB），**不包含** `node_modules/` 里的 transitive 依赖。离线环境 `npm install` 会去 registry 拉 deps 失败。

正确做法：用 `npm install --prefix <staging>` 把 `claude-code` 及其**全部 npm 依赖**装到一个临时 staging prefix，再把整个 staging 目录打成 tar。

新增 `scripts/bundle-claude-code.sh`：

```bash
#!/bin/bash
# 在有网的环境跑一次，把 @anthropic-ai/claude-code 2.1.139 及其全部 npm 依赖
# 装到临时 staging prefix，再把整个 staging 打成 tar 一次性 vendor 进镜像。
#
# 产物：offline-claude/claude-code-bundled-2.1.139.tar.gz  (~100-150 MB)
#
# 用法：./scripts/bundle-claude-code.sh [版本号]
# 默认版本：2.1.139
set -euo pipefail

VERSION="${1:-2.1.139}"
OUT_DIR="$(cd "$(dirname "$0")/.." && pwd)/offline-claude"
STAGING="$(mktemp -d)"

mkdir -p "$OUT_DIR"

echo "==> Installing @anthropic-ai/claude-code@${VERSION} into staging prefix..."
# --prefix + -g 让 npm 把全局布局（bin/ + lib/node_modules/）装到 STAGING
# 这会把 claude-code 的所有 transitive deps 解析并下载到 STAGING/lib/node_modules/
npm install --prefix "$STAGING" -g @anthropic-ai/claude-code@"${VERSION}" 2>&1 | tail -20

echo "==> Verifying claude binary in staging..."
"$STAGING/bin/claude" --version
echo "    (requested: ${VERSION})"

echo "==> Bundling staging directory..."
# 整个 staging 目录打包，含：
#   STAGING/bin/claude                       — 启动脚本
#   STAGING/lib/node_modules/@anthropic-ai/claude-code/  — package 自身
#   STAGING/lib/node_modules/<dep1>/ ...     — 所有 npm deps
#   STAGING/lib/node_modules/<depN>/ ...
#   STAGING/etc/, include/, share/           — npm prefix 元数据（无害）
tar -czf "$OUT_DIR/claude-code-bundled-${VERSION}.tar.gz" -C "$STAGING" .

echo "==> Cleaning up..."
rm -rf "$STAGING"

echo ""
echo "Done!"
ls -lh "$OUT_DIR/claude-code-bundled-${VERSION}.tar.gz"

# 顺便打印一下 deps 数量，方便人肉核对
echo ""
echo "Top-level deps in bundled tarball:"
tar -tzf "$OUT_DIR/claude-code-bundled-${VERSION}.tar.gz" \
  | grep -E '^[^/]+/lib/node_modules/[^/]+/?$' \
  | sed 's|^[^/]*/lib/node_modules/||' \
  | sort -u
```

跑一次：

```bash
chmod +x scripts/bundle-claude-code.sh
./scripts/bundle-claude-code.sh
# 产物：./offline-claude/claude-code-bundled-2.1.139.tar.gz
# 体积：~100-150 MB（远大于 npm pack 的 ~5 MB，因为它含全部 deps）
```

**为什么不用 `npm pack`**：对比两种方案产物体积：

| 方案 | 产物 | 体积 | 离线安装时 |
|---|---|---|---|
| `npm pack @anthropic-ai/claude-code@2.1.139` | `anthropic-ai-claude-code-2.1.139.tgz` | ~5 MB | `npm install -g` 需要拉 deps → ❌ 失败 |
| `npm install --prefix staging` + `tar -czf` | `claude-code-bundled-2.1.139.tar.gz` | ~100-150 MB | `tar -xzf -C /usr/local` 直接用 → ✅ 成功 |

### 4.2 步骤 2：拷贝 vendor 目录到内网项目

把整个 `offline-claude/` 目录随项目带到内网机器。目录结构：

```
deer-flow/
└── offline-claude/
    └── claude-code-bundled-2.1.139.tar.gz
```

### 4.3 步骤 3：改 `backend/Dockerfile`

在 **runtime 阶段**（line 122-144 工具清单段）**之后**追加：

```dockerfile
# ── Install Claude Code 2.1.139 (offline bundled) ─────────────────────────────
# 离线环境：把 npm install --prefix 装好的整个 staging 目录
# （含 bin/ + lib/node_modules/ 全量依赖）一次性解压到 /usr/local
# gateway 通过 claude_provider.py (import anthropic) 调 Anthropic API，
# claude CLI 仅用于容器内 claude login 生成 OAuth 凭据。
ARG CLAUDE_CODE_VERSION=2.1.139
COPY offline-claude/claude-code-bundled-${CLAUDE_CODE_VERSION}.tar.gz /tmp/claude-bundle.tar.gz
RUN tar -xzf /tmp/claude-bundle.tar.gz -C /usr/local \
    && rm /tmp/claude-bundle.tar.gz \
    && claude --version
```

> **关于 Node.js 兼容性**：runtime 阶段已经装好 Node 22，`claude` CLI 自身用 Node 22 运行，无冲突。
> **关于解压目标**：`/usr/local` 是 npm 在 Linux 上的默认全局 prefix，解压后 `/usr/local/bin/claude` 就在 PATH 中；同时 `/usr/local/lib/node_modules/@anthropic-ai/claude-code/` 和所有 deps 也都到位。

### 4.4 步骤 4：改 `config.yaml`

在 `models:` 段加一个 Claude 模型条目：

```yaml
# config.yaml — models 段新增
models:
  # ... 原有模型（MiniMax / DeepSeek / Qwen 等）...

  - name: claude-sonnet-4-6
    display_name: Claude Sonnet 4.6
    use: deerflow.models.claude_provider:ClaudeChatModel
    model: claude-sonnet-4-6
    max_tokens: 16384
    enable_prompt_caching: true
    supports_thinking: true
    # 鉴权优先级（在 claude_provider.py + credential_loader.py 中实现）：
    #   1. $ANTHROPIC_API_KEY
    #   2. $CLAUDE_CODE_OAUTH_TOKEN / $ANTHROPIC_AUTH_TOKEN
    #   3. $CLAUDE_CODE_CREDENTIALS_PATH 指向的 .credentials.json
    #   4. 默认 ~/.claude/.credentials.json
```

如需让 `claude-sonnet-4-6` 成为默认模型，把 `models:` 数组里它的位置挪到第一位即可（`factory.create_chat_model()` 在 `name=None` 时取第一个）。

### 4.5 步骤 5：构建 / 加载镜像

按 `docx/offline-docker/...` 现有流程：

```bash
# 在线机器构建并导出
docker compose -f docker/docker-compose.yaml build gateway
docker save deer-flow-gateway:latest -o ~/deer-flow-offline/deer-flow-gateway.tar

# 传送到内网机器
scp ~/deer-flow-offline/deer-flow-gateway.tar user@内网机:/opt/deer-flow/

# 内网机器加载
ssh user@内网机 "docker load -i /opt/deer-flow/deer-flow-gateway.tar"
```

### 4.6 步骤 6：拿 OAuth token

容器**不需要**执行 `claude login`——`docker-compose.yaml` 已经把 host 的 `~/.claude` 整个挂载进容器：

```yaml
- type: bind
  source: ${HOME:?HOME must be set}/.claude
  target: /root/.claude
  read_only: true
```

凭据生成方式三选一：

**方式 A：在内网 host 跑 `claude login`**（推荐）

1. host 上先装 `claude`（任意方式，外网/包管理器都行）
2. `claude login` 按提示走 OAuth 浏览器流程
3. `~/.claude/.credentials.json` 自动生成
4. 容器启动时挂载好，gateway 直接读

**方式 B：容器内 `claude login`**

1. `docker exec -it deer-flow-gateway claude login`
2. 需要 host 能访问 anthropic.com（一次性）

**方式 C：直接用 `ANTHROPIC_API_KEY`**（完全跳过 `claude` CLI 登录）

```bash
# 加到 gateway 环境变量（docker-compose.yaml 的 environment 段）
export ANTHROPIC_API_KEY=sk-ant-...
docker compose up -d
```

- `claude_provider.py` 优先读 `$ANTHROPIC_API_KEY`，跳过 OAuth 路径
- `claude` CLI 在容器里仍装着，但不被使用

如果内网 host **也无法访问 anthropic.com**，走项目已提供的 `scripts/export_claude_code_oauth.py` 在**外网机器**登录后导出 token 再传过来：

```bash
# 在能访问 anthropic.com 的机器上
./scripts/export_claude_code_oauth.py --output ~/claude-creds.json

# 传到内网 host
scp ~/claude-creds.json user@内网机:~/.claude/.credentials.json
```

### 4.7 步骤 7：启动并验证

```bash
# 启动
ssh user@内网机 "/opt/deer-flow/start.sh start"

# 关键验证 1：claude CLI 版本
ssh user@内网机 "docker exec deer-flow-gateway claude --version"
# 预期：2.1.139

# 关键验证 2：claude 能读凭据（如果走 OAuth）
ssh user@内网机 'docker exec deer-flow-gateway bash -c "
  ls -la /root/.claude/.credentials.json
  cat /root/.claude/.credentials.json | head -c 200
"'

# 关键验证 3：Python anthropic SDK 装载
ssh user@内网机 "docker exec deer-flow-gateway python -c 'import anthropic; print(anthropic.__version__)'"
# 预期：一个版本号，例如 0.40.0

# 关键验证 4：doctor 跑一遍
ssh user@内网机 "cd /opt/deer-flow && docker exec deer-flow-gateway python /app/backend/scripts/doctor.py 2>&1 | head -30"
# 预期：Claude auth available (model: claude-sonnet-4-6) - ok

# 关键验证 5：实际创建 ClaudeChatModel 实例
ssh user@内网机 "docker exec deer-flow-gateway python -c '
from backend.packages.harness.deerflow.models import create_chat_model
m = create_chat_model(\"claude-sonnet-4-6\")
print(type(m).__name__, m.model)
'"
# 预期：ClaudeChatModel claude-sonnet-4-6
```

---

## 五、验证清单

| 阶段 | 验证项 | 命令 | 预期结果 |
|---|---|---|---|
| 构建后（在线）| `claude` 二进制可执行 | `docker run --rm deer-flow-gateway:latest claude --version` | `2.1.139` |
| 构建后（在线）| `claude` 依赖齐全 | `docker run --rm deer-flow-gateway:latest ls /usr/local/lib/node_modules/` | 包含 `@anthropic-ai/` 及多个 deps |
| 构建后（在线）| Node.js 仍在 | `docker run --rm deer-flow-gateway:latest node --version` | `v22.x.x` |
| 加载后（内网）| `claude` 版本 | `docker exec deer-flow-gateway claude --version` | `2.1.139` |
| 加载后（内网）| `claude` 凭据可读 | `docker exec deer-flow-gateway ls -la /root/.claude/.credentials.json` | 文件存在 |
| 加载后（内网）| Python SDK 装载 | `docker exec deer-flow-gateway python -c "import anthropic"` | 无报错 |
| 端到端 | doctor 通过 | `python /app/backend/scripts/doctor.py` | "Claude auth available" ok |
| 端到端 | 模型可创建 | `python -c "from deerflow.models import create_chat_model; create_chat_model('claude-sonnet-4-6')"` | `ClaudeChatModel` 实例 |

---

## 六、风险点与应对

### 6.1 已知风险

| 风险 | 影响 | 应对 |
|---|---|---|
| Claude Code bundled Node 与镜像自带 Node 22 冲突 | 极少数情况下 `which node` 找到错的 Node | 把 `/usr/local/bin` 放到 PATH 最前；用 `claude --print-system-info` 验证 |
| 内网 host 也无法访问 anthropic.com | `claude login` 走不通 | 改用 `ANTHROPIC_API_KEY` 环境变量（走 API key 模式）|
| 离线 npm bundle tarball ~100-150 MB（含全部 deps） | 镜像变大 | 接受这个代价；`claude` CLI 仅作 OAuth 凭据生成，非热路径 |
| Claude Code 升级到 3.x 改了 npm 包布局 | 当前安装脚本失效 | 升级时重跑 `scripts/bundle-claude-code.sh` 重新打 tarball |
| Python `anthropic` SDK 与 `langchain_anthropic` 版本不匹配 | `claude_provider.py` 加载失败 | 在 `pyproject.toml` 锁版本；升级时在测试环境验证 |

### 6.2 备选方案：完全跳过 `claude` CLI

如果不需要 OAuth 凭据（只用 `ANTHROPIC_API_KEY` 走 API key 模式），`claude` CLI 实际上**不被使用**，可以跳过整个 npm install 步骤：

- **不需要** `offline-claude/npm-vendor/` 目录
- **不需要** Dockerfile 里加 npm install 段
- **不需要** 内网 `claude login`
- 直接在 `docker-compose.yaml` 的 gateway 环境变量里加 `ANTHROPIC_API_KEY=sk-ant-...`

代价：失去 OAuth 凭据自动刷新能力（OAuth token 过期后需要重新 `claude login`）；代价微小，因为 API key 模式更简单稳定。

---

## 七、附录

### 7.1 完整 Dockerfile diff（runtime 阶段尾部）

```diff
 # Copy Node.js runtime from builder (provides npx for MCP servers)
 COPY --from=builder /usr/local/bin/node /usr/local/bin/node
+
+# ── Install Claude Code 2.1.139 (offline bundled) ─────────────────────────────
+ARG CLAUDE_CODE_VERSION=2.1.139
+COPY offline-claude/claude-code-bundled-${CLAUDE_CODE_VERSION}.tar.gz /tmp/claude-bundle.tar.gz
+RUN tar -xzf /tmp/claude-bundle.tar.gz -C /usr/local \
+    && rm /tmp/claude-bundle.tar.gz \
+    && claude --version
```

### 7.2 完整 config.yaml diff

```diff
 models:
   - name: MiniMax-M3
     display_name: MiniMax-M3
     ...
+
+  - name: claude-sonnet-4-6
+    display_name: Claude Sonnet 4.6
+    use: deerflow.models.claude_provider:ClaudeChatModel
+    model: claude-sonnet-4-6
+    max_tokens: 16384
+    enable_prompt_caching: true
+    supports_thinking: true
```

（同时按需调整 `models:` 数组顺序，让 `claude-sonnet-4-6` 成为默认模型）

### 7.3 关键文件位置速查

| 用途 | 路径 |
|---|---|
| `claude` CLI binary | `/usr/local/bin/claude` |
| `claude` CLI 安装目录 | `/usr/local/lib/node_modules/@anthropic-ai/claude-code/` |
| `claude` CLI 全部 npm 依赖 | `/usr/local/lib/node_modules/<dep>/`（约 10-30 个包）|
| `claude_provider.py`（gateway 实际调用）| `backend/packages/harness/deerflow/models/claude_provider.py` |
| `credential_loader.py`（凭据加载）| `backend/packages/harness/deerflow/models/credential_loader.py` |
| `factory.py`（模型工厂）| `backend/packages/harness/deerflow/models/factory.py` |
| Anthropic Python SDK | `/usr/local/lib/python3.11/site-packages/anthropic/` |
| OAuth 凭据（host 挂载）| `/root/.claude/.credentials.json` |
| Node.js | `/usr/local/bin/node`（来自 builder 阶段，v22.x）|
| 项目 config | `config.yaml`（`models:` 段）|
| 在线打包脚本 | `scripts/bundle-claude-code.sh`（在新加的 vendor 流程）|
| 离线 bundle 包 | `offline-claude/claude-code-bundled-2.1.139.tar.gz` |
| Doctor 脚本 | `scripts/doctor.py`（`python scripts/doctor.py` 跑）|
| OAuth 导出脚本 | `scripts/export_claude_code_oauth.py`（跨机迁移凭据用）|

### 7.4 相关引用

- 项目现有离线部署指南：[`docx/offline-docker/deer-flow-offline-linux-docker-deployment-guide.md`](../offline-docker/deer-flow-offline-linux-docker-deployment-guide.md)
- Claude 鉴权 + OAuth 处理（核心调用路径）：[`backend/packages/harness/deerflow/models/claude_provider.py`](../../backend/packages/harness/deerflow/models/claude_provider.py)
- 凭据加载（优先 `$ANTHROPIC_API_KEY` → `~/.claude/.credentials.json`）：[`backend/packages/harness/deerflow/models/credential_loader.py`](../../backend/packages/harness/deerflow/models/credential_loader.py)
- 模型工厂（注册/创建模型实例）：[`backend/packages/harness/deerflow/models/factory.py`](../../backend/packages/harness/deerflow/models/factory.py)

---

## 八、变更记录

| 日期 | 版本 | 变更 |
|---|---|---|
| 2026/06/05 | 1.0 | 初稿，Claude Code 2.1.139 离线安装方案（ACP 路线） |
| 2026/06/05 | 2.0 | **重写**：移除 ACP 路线（`@zed-industries/claude-agent-acp`、`invoke_acp_agent`、`acp_agents` 配置段），改用 `import anthropic` + `claude_provider:ClaudeChatModel` 直连 Anthropic API；安装方式从官方 `install.sh` + tar 打包改为 `npm install -g`（offline vendor） |
| 2026/06/05 | 2.1 | **修正离线 vendor 方式**：`npm pack` 出来的 tarball 只含 package 自身（~5 MB），不含 `node_modules/` 里的 transitive 依赖。改用 `npm install --prefix <staging> -g` + `tar -czf` 整个 staging 目录（含 `bin/` + `lib/node_modules/` 全量依赖，~100-150 MB）；Dockerfile 端从 `npm install -g` 改为 `tar -xzf -C /usr/local`。新增 `scripts/bundle-claude-code.sh`。 |
