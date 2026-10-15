# DeerFlow multi-agent starter

这是基于 `agent-swarm-dev-team.md` 改造的 **本地可跑版**。

当前机器已经具备：
- `tmux`
- `codex`
- `claude`
- `git worktree`
- `gh`（已安装，但还未登录）

当前仍缺：
- GitHub remote
- `gh auth login`
- CI / PR 流水线接入

所以这套脚手架先解决第一阶段：**多 agent 并行开发**。

## 目录

- `active-tasks.json`：任务注册表
- `swarm.config.json`：项目级角色与默认配置
- `templates/`：不同 agent 的 prompt 模板
- `run-agent.sh`：创建 worktree、启动 tmux、运行 codex/claude
- `check-agents.sh`：确定性检查脚本（tmux / worktree / git / gh）

## 建议角色拆分（适合 DeerFlow）

1. `backend-python`
   - 负责 `backend/`
   - 适合：FastAPI / LangGraph / harness / tests

2. `frontend-nextjs`
   - 负责 `frontend/`
   - 适合：Next.js / React / UI / hooks / typecheck

3. `docs-sync`
   - 负责 README / CLAUDE / AGENTS / docs/
   - DeerFlow 明确要求代码变更后同步文档

4. `reviewer`
   - 不直接开发
   - 负责 diff review / 风险审查 / DoD 检查

## 最小试跑建议

先不要一上来开 4 个 agent。
建议先试这两类组合：

### 组合 A：前后端并行

- Agent 1：`frontend-nextjs`
- Agent 2：`backend-python`

### 组合 B：开发 + 审查

- Agent 1：`backend-python` 或 `frontend-nextjs`
- Agent 2：`reviewer`

## 使用方式

### 1. 启动一个后端 agent

```bash
cd deer-flow
./.clawdbot/run-agent.sh \
  --task backend-thread-cleanup \
  --agent codex \
  --role backend-python \
  --branch feat/backend-thread-cleanup \
  --prompt-file ./.clawdbot/templates/backend-python.md
```

### 2. 启动一个前端 agent

```bash
./.clawdbot/run-agent.sh \
  --task frontend-compose-polish \
  --agent claude \
  --role frontend-nextjs \
  --branch feat/frontend-compose-polish \
  --prompt-file ./.clawdbot/templates/frontend-nextjs.md
```

### 3. 查看状态

```bash
./.clawdbot/check-agents.sh
```

### 4. 进入 tmux 查看某个 agent

```bash
tmux attach -t claw-backend-thread-cleanup
```

### 5. 中途纠偏

```bash
tmux send-keys -t claw-backend-thread-cleanup "Stop. Fix tests first, then refactor." Enter
```

## 第二阶段（已补前置）

我已经把下面这些前置补上了：

1. 已添加 `upstream = https://github.com/bytedance/deer-flow.git`
2. 新增 `github-bootstrap.sh` 检查 GitHub 接入状态
3. 新增 `create-pr.sh` 用于 push 当前分支并创建 PR
4. `check-agents.sh` 现在会显示 `upstream / origin / gh auth` 状态

当前还需要你完成的只有两件事：

1. `gh auth login`
2. 配置你自己的 fork 为 `origin`

完成后，就可以进入自动 PR / CI 闭环。

## 注意

- 当前脚手架默认基于本地 `master` 创建 worktree；因为仓库现在没有 remote。
- `gh` 已可用，但在登录前不会执行任何 PR 操作。
- DeerFlow 后端文档要求：**代码改动后同步 README / CLAUDE / AGENTS / docs**。这点已写进模板。
