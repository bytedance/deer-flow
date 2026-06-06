# Claude Agent SDK 烟雾测试与 `cli_path` 验证

> 日期：2026/06/06
> 适用：deer-flow `m2` 分支
> 相关：`config.example.yaml:739` `@agentclientprotocol/claude-agent-acp`、`feat(gateway): bake 32 CLI/debug tools into image for offline LAN use`（commit `6d89ced5`）

---

## 一、目的

验证两件事：

1. `claude-agent-sdk`（Python SDK）在 deer-flow `backend/.venv` 里能跑通，能 spawn `claude` CLI 子进程并收到流式响应。
2. `ClaudeAgentOptions(cli_path=...)` 是否真的能让 SDK 复用**外部 CLI**（指定路径）而不是用 wheel 内置的那份。

第二点是关键 —— 决定了 gateway 离线镜像要不要 baked `claude-agent-sdk` 自身的内置 CLI。

---

## 二、测试代码

见同级文件 `claude-agent-sdk-smoke-test.py`。核心三行：

```python
async for message in query(
    prompt="What is 2 + 2?",
    options=ClaudeAgentOptions(cli_path=CLAUDE_PATH),
):
    print(message)
```

`CLAUDE_PATH` 指向 `/Users/raidery/.nvm/versions/node/v24.14.1/bin/claude`（系统全局 npm 包 `@anthropic-ai/claude-code@2.1.139`，node v24.14.1）。

---

## 三、两次运行对比

| 维度 | 默认（wheel 内置 CLI 2.1.150） | `cli_path` 指定（系统 CLI 2.1.139） |
|---|---|---|
| `claude_code_version`（SystemMessage 报告） | `2.1.150` | **`2.1.139`** ✅ |
| 耗时 | 11.08 s | 6.35 s（**快 43 %**） |
| 成本 | $0.172 | $0.162（少 6 %） |
| 输入 tokens | 31 989 | 31 909（持平） |
| 输出 tokens | 458 | 112（**少 76 %**） |
| 回答内容 | `2 + 2 = **4**`（带 markdown） | `4`（极简） |
| 工具集 | 含 `TaskCreate / TaskGet / TaskList / TaskUpdate` | 含 `TodoWrite`（老 API） |
| `session_id` | `aa25517d-…` | `0c54f32e-…` |

### 关键结论

- **`cli_path` 真的生效**：第二次运行 `SystemMessage` 报的 `claude_code_version` 从 `2.1.150` 变成 `2.1.139`，与系统 `claude -v` 完全一致。证明 SDK 这次 spawn 的是 `cli_path` 指向的二进制，而不是 wheel 自带的 `claude.exe`。
- **两个 CLI 版本行为有差异**：2.1.150 用新的 `Task*` 系列工具，2.1.139 用老的 `TodoWrite`；2.1.150 的回答带 markdown 加粗，2.1.139 极简。SDK 透传由 CLI 决定的 schema 和行为。
- **性能差 43 %**：版本更老的 2.1.139 在这个简单任务上反而更快更便宜，主要因为输出 tokens 少（不写 markdown 包装）。这跟"更新 = 更好"的直觉相反，需要 case by case 看。

---

## 四、SDK 收到的消息流（按顺序）

1. `HookEventMessage` × 2 — `SessionStart:startup` 钩子被触发。`output.additionalContext` 包含 superpowers 插件的 `using-superpowers` skill 全文。这是 CLI 启动时自动加载的（`~/.claude/plugins/cache/superpowers-marketplace/...`），与 SDK 无关。
2. `SystemMessage`（`subtype='init'`）— 握手，data 字段含 `cwd`、`session_id`、`tools`、`mcp_servers`、`model`、`claude_code_version`、`apiKeySource: ANTHROPIC_API_KEY` 等。
3. `AssistantMessage`（`content=[ThinkingBlock(...)]`）— 模型内部思考。
4. `AssistantMessage`（`content=[TextBlock(text='4')]`）— 最终回答。
5. `ResultMessage`（`subtype='success'`）— 结束，含 `duration_ms`、`total_cost_usd`、`usage`、`model_usage`、`stop_reason='end_turn'`。

完整 schema 见 `backend/.venv/lib/python3.12/site-packages/claude_agent_sdk/types.py`。

---

## 五、对集成方案的修正

| 之前的判断 | 修正后 |
|---|---|
| "镜像需要 baked `claude-agent-sdk` 自带的 CLI" | **不需要**。只要镜像里有任意 `claude` 二进制，指定 `cli_path` 即可。`claude-agent-sdk` wheel 只贡献 Python 绑定层，其内置 CLI 在 `cli_path` 被设置时**不会被使用**。 |
| "镜像需要同时 baked `claude` CLI 和 `claude-agent-sdk` wheel CLI 两份" | **不需要**。`uv sync` 装 `claude-agent-sdk` 时即使下载了内置 CLI，也不会被 `query()` 实际 spawn。 |
| "`npx -y @agentclientprotocol/claude-agent-acp` 是走 Node 路线，跟 Python SDK 互斥" | **仍然成立**。这两条路径在 gateway 里是二选一：要么用 ACP 适配器（Node 进程 + JSON-RPC），要么用 Python SDK 嵌入（`query()` / `ClaudeSDKClient`）。目前 `config.example.yaml:739` 走的是 ACP 路线。 |

### 简化后的 gateway 镜像最小需求（Python SDK 路线）

```
- python:3.12
- pip install claude-agent-sdk         # Python 绑定层（内置 CLI 不重要）
- npm install -g @anthropic-ai/claude-code@<version>  # 真实使用的 CLI
- ANTHROPIC_API_KEY (env)
```

构建时 `cli_path` 写绝对路径到镜像里的 `claude` 位置（例如 `/usr/local/bin/claude`）。

---

## 六、相关源码位置

- `claude_agent_sdk` SDK：`backend/.venv/lib/python3.12/site-packages/claude_agent_sdk/`
  - `types.py:1702` — `ClaudeAgentOptions.cli_path` 定义
  - `_internal/transport/subprocess_cli.py:63-64` — `cli_path` 注入到 transport 层
  - `_internal/transport/subprocess_cli.py:225` — 实际 spawn 命令：`[self._cli_path, "--output-format", "stream-json", "--verbose"]`
- 系统 `claude` 二进制：`/Users/raidery/.nvm/versions/node/v24.14.1/bin/claude` → `../lib/node_modules/@anthropic-ai/claude-code/bin/claude.exe`（macOS 上 `.exe` 是 `@yao-pkg/pkg` 打包 Node 运行时的产物，命名是合法的）
- 同系列相关文档：
  - `docx/integration/deerflow-claude-code-offline-install-guide.md` — 离线安装 `claude` CLI 2.1.139 的 vendor 流程
  - `docx/integration/backend-dockerfile-apt-cache-plan.md` — backend Dockerfile 的 apt cache 规划
