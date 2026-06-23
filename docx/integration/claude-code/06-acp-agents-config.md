# ACP Agents 配置参考

> 日期：2026/06/18
> 适用：deer-flow `m2` 分支
> 状态：参考文档 — 镜像 `config.yaml` 的 `acp_agents` 段
> 相关：
> - `config.example.yaml:937-975` ACP Agents 段
> - `config.yaml:182-199` 本地生效配置
> - `deerflow-claude-code-offline-install-guide.md` 离线 `claude` CLI 安装流程
> - `offline-claude/bundle-pi-acp.sh` / `bundle-pi-coding-agent.sh` Pi 离线 vendor 脚本

---

## 一、定位

`acp_agents` 段是 DeerFlow 给 lead agent 注册**外部 ACP 子代理**的入口：lead agent 通过 `invoke_acp_agent(agent="<name>", prompt="...")` 工具把编码任务委派给一个**独立子进程**跑的 ACP 兼容 agent，跑完把结果整段回传。

每个 agent 一个独立 YAML 块，字段定义见 `backend/packages/harness/deerflow/config/acp_config.py::ACPAgentConfig`：

| 字段 | 必填 | 默认 | 说明 |
|---|---|---|---|
| `command` | ✅ | — | 启动子进程的二进制 / 命令 |
| `args` | ❌ | `[]` | 传给 command 的 CLI 参数 |
| `description` | ✅ | — | 描述，写进 lead agent 的工具 schema |
| `model` | ❌ | `null` | 模型提示，`null` = 子 agent 自己的默认 |
| `auto_approve_permissions` | ❌ | `false` | **ACP 模式必须 `true`**，否则 lead agent 会卡在权限弹窗 |
| `env` | ❌ | `{}` | 注入到子进程的环境变量，`$VAR` 自动从宿主环境解析 |

---

## 二、生产配置（`config.yaml` 实际生效段）

`config.yaml:182-199`：

```yaml
acp_agents:
  claude_code:
    command: /usr/local/bin/claude-agent-acp
    args: []
    description: Claude Code for implementation, refactoring, and debugging
    model: null
    auto_approve_permissions: true
    env:
      CLAUDE_CODE_EXECUTABLE: /usr/local/bin/claude
      #ANTHROPIC_API_KEY: $ANTHROPIC_API_KEY
  pi:
    command: pi-acp
    args: []
    description: Pi coding agent — light, fast for small code-generation tasks (single-file
      edits, bug fixes, small refactors)
    model: minimax/MiniMax-M3
    env:
      MINIMAX_API_KEY: $MINIMAX_API_KEY
```

---

## 三、关键字段解释

### 3.1 `claude_code.command`

`/usr/local/bin/claude-agent-acp` 是 vendored 的 ACP 适配器，来自 `offline-claude/claude-agent-acp-bundled-0.42.0-linux-x64.tar.gz`。安装方式：

```bash
tar -xzf offline-claude/claude-agent-acp-bundled-0.42.0-linux-x64.tar.gz -C /usr/local/
# 产出：
#   /usr/local/bin/claude-agent-acp
#   /usr/local/lib/node_modules/@agentclientprotocol/claude-agent-acp/
```

在线场景可改用 `npx` 拉取：

```yaml
claude_code:
  command: npx
  args: ["-y", "@agentclientprotocol/claude-agent-acp"]
```

### 3.2 `claude_code.env.CLAUDE_CODE_EXECUTABLE`（关键）

`claude-agent-acp` 启动后会**自己 spawn** `claude` CLI 子进程来跑实际任务。它通过读环境变量 `CLAUDE_CODE_EXECUTABLE` 决定 `claude` 二进制位置（见 vendored 源码 `dist/acp-agent.js` 第 9-13 行）：

```js
export async function claudeCliPath() {
    if (process.env.CLAUDE_CODE_EXECUTABLE) {
        return process.env.CLAUDE_CODE_EXECUTABLE;
    }
    // 否则从 @anthropic-ai/claude-agent-sdk 的 native binary 找
}
```

所以 `/usr/local/bin/claude` 的路径**只能走 env，不能走 args**。该二进制来自 `offline-claude/claude-code-bundled-2.1.139-linux-x64.tar.gz`（`@anthropic-ai/claude-code@2.1.139` 全局安装产物）。

### 3.3 `auto_approve_permissions: true`（必须）

ACP 模式下，`claude-agent-acp` 子 agent 会向 lead agent 发 "Allow once / Allow always" 权限弹窗。如果不开自动授权，lead agent 的 `invoke_acp_agent` 工具调用会**无限 hang 住**——它不知道该如何回应弹窗（DeerFlow 没有实现 ACP 权限弹窗的转发逻辑）。

**生产配置务必设为 `true`**，等权限模型完善后再考虑暴露给用户。

### 3.4 `pi.model: minimax/MiniMax-M3`

Pi 走的是 MiniMax-M3 后端（`MINIMAX_API_KEY` 已在 env 里注入），不消耗 Anthropic token。`pi-acp` 本身就是 npm 包，无 native binary，所以 `command: pi-acp` + `args: []` 即可，无需 `CLAUDE_CODE_EXECUTABLE` 这类环境变量。

---

## 四、为什么 Pi 用空 args 而 Claude Code 走 env

| 维度 | Pi (`pi-acp`) | Claude Code (`claude-agent-acp`) |
|---|---|---|
| ACP adapter 是否自带编码能力 | ✅ 是，`pi-acp` 内部完成所有编码逻辑 | ❌ 否，只是协议适配器，必须 spawn `claude` CLI |
| 是否需要外部二进制 | ❌ 不需要 | ✅ 需要 `@anthropic-ai/claude-code` CLI |
| 路径如何传 | N/A | 环境变量 `CLAUDE_CODE_EXECUTABLE` |
| args 含义 | 留空 | 留空（vendor binary 已包含全部参数） |
| 离线 vendor 包 | `offline-claude/pi-acp-bundled-*.tar.gz` | `offline-claude/claude-agent-acp-bundled-*.tar.gz` + `offline-claude/claude-code-bundled-*.tar.gz` |

---

## 五、模板 `config.example.yaml` 同步段

`config.example.yaml:942-957` 同步记录：

```yaml
# acp_agents:
#   claude_code:
#     # Vendored ACP adapter (from offline-claude/claude-agent-acp-bundled-*.tar.gz).
#     # For online use, replace `command` + `args` with:
#     #   command: npx
#     #   args: ["-y", "@agentclientprotocol/claude-agent-acp"]
#     command: /usr/local/bin/claude-agent-acp
#     args: []
#     description: Claude Code for implementation, refactoring, and debugging
#     model: null
#     # auto_approve_permissions: false  # Set to true to auto-approve ACP permission requests
#     env:
#       # Point the adapter at the vendored `claude` CLI binary (from offline-claude/claude-code-bundled-*.tar.gz)
#       CLAUDE_CODE_EXECUTABLE: /usr/local/bin/claude
#       ANTHROPIC_API_KEY: $ANTHROPIC_API_KEY  # $VAR resolves from host environment
#
#   codex:
#     ...
#   pi:
#     ...
```

---

## 六、验证清单（新增 / 改动 `acp_agents` 段后必跑）

| 检查 | 命令 |
|---|---|
| YAML 语法 | `python3 -c "import yaml; yaml.safe_load(open('config.yaml'))"` |
| 单测（schema + reload）| `cd backend && PYTHONPATH=. uv run pytest tests/test_acp_config.py tests/test_app_config_reload.py` |
| 工具调用路径 | `cd backend && PYTHONPATH=. uv run pytest tests/test_invoke_acp_agent_tool.py` |
| 二进制就位 | `ls -l /usr/local/bin/claude-agent-acp /usr/local/bin/claude /usr/local/bin/pi-acp` |
| 端到端冒烟 | 启 lead agent，下达"用 claude_code 改一个文件"指令，观察子进程是否正常 spawn + 回写 |

---

## 七、相关引用

- ACP 工具实现：`backend/packages/harness/deerflow/tools/builtins/invoke_acp_agent_tool.py`
- 配置 schema：`backend/packages/harness/deerflow/config/acp_config.py`
- AppConfig 集成：`backend/packages/harness/deerflow/config/app_config.py`（`acp_agents` 段解析）
- 离线 vendor 脚本：`offline-claude/bundle-pi-acp.sh` / `bundle-pi-coding-agent.sh`
- Claude Code 离线安装：`docx/integration/deerflow-claude-code-offline-install-guide.md`
- Claude Code 集成设计：`docx/integration/claude-code/03-integration-design.md`（ACP 路径 vs SDK 路径取舍）