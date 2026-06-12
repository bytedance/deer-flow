# 用户级 Custom Agent 部署

## 路径

```
<base_dir>/users/<user_id>/agents/<agent_name>/
```

- `<base_dir>` 解析链：`$DEER_FLOW_HOME` → `$DEER_FLOW_PROJECT_ROOT/.deer-flow` → `Path.cwd()/.deer-flow`
- `<user_id>` 当前登录用户 UUID（启用 better-auth 时**不是** `default`）

**本机实例**（`make dev` 从项目根启动，cwd=`backend/`，user_id=f37e34d9-...）：

```
backend/.deer-flow/users/f37e34d9-cbf4-4a20-b514-94738b626f9b/agents/<agent_name>/
```

## 目录结构

```
<agent_name>/
├── SOUL.md       # system prompt / 人格
└── config.yaml   # name + 配置
```

**目录名必须等于 `config.yaml` 里的 `name:` 字段**。

## config.yaml 最小骨架

```yaml
name: <agent_name>             # 跟目录名一致
description: 一句话描述
model: <model_name>            # 必须在主 config.yaml 的 models[] 里注册
skills:                        # 引用 skills/public/ 下的目录名
  - data-analysis
  - markitdown
tool_groups: []                # 留空 = 不开放外接工具
```

## SOUL.md 写法

Markdown，按章节组织：Identity / Core Traits / Hard Limits / Communication / Risk & Audit / Growth / Lessons Learned。

参考例子：`docs/superpowers/deployment/农信AI助手-SOUL.md`

## 部署步骤

1. 建目录：`mkdir -p <完整路径>/<agent_name>/`
2. 写 `SOUL.md` 和 `config.yaml`
3. **重启 DeerFlow**（agent 配置仅启动时加载，改完不重启不生效）

## 常见坑

- ❌ **不要用 legacy 路径** `<base_dir>/agents/<name>/` —— 没有 user 隔离，read-only fallback，多用户下不生效
- ❌ `model:` 字段名字拼错 → agent 启动失败
- ❌ `skills:` 列表里写的名字必须在 `skills/public/<name>/SKILL.md` 真实存在
- ❌ 改完文件没重启 → 看不到效果

## 部署现成例子（农信AI助手）

```bash
SRC=/Users/raidery/bench/harness/raidery/deer-flow/docs/superpowers/deployment
DST=/Users/raidery/bench/harness/raidery/deer-flow/backend/.deer-flow/users/f37e34d9-cbf4-4a20-b514-94738b626f9b/agents/农信AI助手

mkdir -p "$DST"
cp "$SRC/农信AI助手-SOUL.md"    "$DST/SOUL.md"
cp "$SRC/农信AI助手-config.yaml" "$DST/config.yaml"
```

> ⚠️ 例子里的 `model: gpt-4` 需先确认主 `config.yaml` 的 `models[]` 里有这个名字。

---

## 补充

### config.yaml 相关开关

- `agents_api.enabled: false` 只关 Gateway HTTP `/api/agents` routers，**不影响** `setup_agent` 工具，UI 引导仍可用
- `skill_evolution.enabled: true`（您的配置）—— agent 可自动演化 skill

### Web UI 名字限制

`<base_dir>/agents/new` 第一步的 regex：`^[A-Za-z0-9-]+$`（**不能含中文**，`农信AI助手` 这种会被 reject）。

### 三种创建方式

| 方式 | 路径 | 适用 |
|---|---|---|
| **A. Web UI 引导** | `/workspace/agents/new` → 起名 + 跟 bootstrap agent 4 阶段对话（Hello / You / Personality / Depth） | 第一次创建 / 不熟引导流程 |
| **B. 手动写文件** | `mkdir -p <dst>` + 写两个文件 + `make restart` | 已有模板 / 批量创建 |
| **C. API + setup_agent 工具** | run config 里塞 `is_bootstrap=True`，agent 内部调 `setup_agent(soul, description, skills)` 落盘 | 脚本化 / 自动化 |

方法 A 示例 URL：`http://localhost:2026/workspace/agents/new`

方法 C 示例：
```bash
curl -X POST http://localhost:8001/api/threads/<thread_id>/runs/stream \
  -H "Content-Type: application/json" \
  -d '{"assistant_id":"lead-agent","config":{"configurable":{"is_bootstrap":true}},"input":{"messages":[{"role":"user","content":"create agent..."}]}}'
```

### 之后迭代：update_agent

已存在的 agent 在自己聊天里可调 `update_agent` 工具，自更新 SOUL.md / config.yaml（原子写）。

**前提**：
- `is_bootstrap=False`
- runtime 有 `agent_name`（即在 custom agent 的上下文中）

### 常见坑（补充）

- ❌ 名字带中文/空格 → Web UI 方法 A 第一步 reject
- ❌ `model:` 拼错 → agent 启动失败
- ❌ `skills:` 列表里写的名字必须在 `skills/public/<name>/SKILL.md` 真实存在
- ❌ 改完文件没 `make restart` → 看不到效果
- ❌ 落到 legacy 路径 `<base_dir>/agents/<name>/` → 多用户下被忽略
