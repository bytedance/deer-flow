# DeerFlow 持久化机制分析

本文档分析 DeerFlow 系统中可用于保存 MD 文件并供 Agent 使用的持久化机制。

## 1. Skills 系统（最推荐）

**位置**：`skills/custom/` 目录（已 gitignore，不会提交到代码库）

每个 skill 是一个子目录，包含一个 `SKILL.md` 文件：

```
skills/custom/
└── my-knowledge/
    └── SKILL.md
```

`SKILL.md` 格式（YAML frontmatter + 正文）：

```markdown
---
name: my-knowledge
description: 当需要XXX时使用此 skill（Agent 根据 description 判断是否加载）
---

# 正文内容
...你的 MD 文件内容...
```

**Agent 使用方式**：启用后，skill 路径会注入到 Agent 的 system prompt 中，Agent 在需要时主动加载读取其内容。

**启用方式**：
- Web UI 的 Skills 设置页面
- Gateway API：`GET/PUT /api/skills`

**安装方式**：
- 直接在 `skills/custom/` 下创建目录和 `SKILL.md`
- 或将目录打包为 `.skill`（ZIP），通过 `POST /api/skills/install` 安装

---

## 2. 虚拟文件系统（适合运行时读取）

Agent 在沙箱内可访问以下虚拟路径：

| 虚拟路径 | 物理路径 | 用途 |
|---|---|---|
| `/mnt/skills/` | `skills/` | 只读，skills 目录 |
| `/mnt/user-data/workspace/` | `backend/.deer-flow/threads/{id}/user-data/workspace/` | Agent 工作目录，按 thread 隔离 |
| `/mnt/user-data/uploads/` | `backend/.deer-flow/threads/{id}/user-data/uploads/` | 用户上传文件 |
| `/mnt/user-data/outputs/` | `backend/.deer-flow/threads/{id}/user-data/outputs/` | Agent 输出文件 |

把 MD 文件放到 `skills/public/` 或 `skills/custom/` 下后，Agent 可以直接通过 `read_file` 工具读取：

```
read_file /mnt/skills/custom/<skill-name>/<file>.md
```

---

## 3. Memory 系统（不适合原始文档）

存储位置：`backend/.deer-flow/memory.json`

内容是从对话中自动提取的结构化事实和用户偏好（workContext、facts 等），由 LLM 自动维护。**不适合**保存原始 MD 文件，适合存储简短的用户偏好、习惯和背景知识点。

---

## 推荐做法

将 MD 文件放到 `skills/custom/<skill-name>/SKILL.md`，在 frontmatter 的 `description` 字段中清晰描述"何时应该使用此 skill"，然后在 Web UI 中启用。Agent 会在判断合适时自动加载并遵循其中的内容。
