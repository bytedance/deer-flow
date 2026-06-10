# 记忆系统 (Memory System)

基于 LLM 的长期记忆系统，支持每用户隔离、事实提取、防抖队列。

## 组件

| 模块 | 职责 |
|------|------|
| `updater.py` | LLM 记忆更新，事实提取，空白规范化事实去重，原子文件 I/O |
| `queue.py` | 防抖更新队列（每线程去重，可配置等待时间）；在入队时捕获 `user_id` 以在 `threading.Timer` 边界后保留 |
| `prompt.py` | 记忆更新提示模板 |
| `storage.py` | 基于文件的存储，每用户隔离；缓存键为 `(user_id, agent_name)` 元组 |

## 每用户隔离

### 存储路径

| 类型 | 路径 |
|------|------|
| 每用户记忆 | `{base_dir}/users/{user_id}/memory.json` |
| 每 Agent 每用户记忆 | `{base_dir}/users/{user_id}/agents/{agent_name}/memory.json` |
| 自定义 Agent 定义 | `{base_dir}/users/{user_id}/agents/{agent_name}/` (SOUL.md + config.yaml) |

### user_id 解析

- 通过 `get_effective_user_id()` 从 `deerflow.runtime.user_context` 解析
- 无认证模式: `user_id` 默认为 `"default"` (常量 `DEFAULT_USER_ID`)
- 配置中的绝对 `storage_path` 选择不参与每用户隔离

### 遗留布局回退

遗留共享布局 `{base_dir}/agents/{agent_name}/` 保留为未迁移安装的只读回退。

### 迁移

运行迁移脚本:

```bash
PYTHONPATH=. python scripts/migrate_user_isolation.py
```

选项:
- `--dry-run` - 预览更改
- `--user-id USER_ID` - 分配无主遗留数据给用户（默认 `default`）

## 数据结构

存储在 `{base_dir}/users/{user_id}/memory.json`:

```json
{
  "userContext": {
    "workContext": "工作上下文摘要",
    "personalContext": "个人上下文摘要",
    "topOfMind": "当前关注点（1-3 句）"
  },
  "history": {
    "recentMonths": "最近月份上下文",
    "earlierContext": "早期上下文",
    "longTermBackground": "长期背景"
  },
  "facts": [
    {
      "id": "fact-uuid",
      "content": "事实内容",
      "category": "preference|knowledge|context|behavior|goal",
      "confidence": 0.85,
      "createdAt": "2026-01-01T00:00:00Z",
      "source": "conversation|feedback_loop"
    }
  ]
}
```

### 事实类别

| 类别 | 说明 | 示例 |
|------|------|------|
| `preference` | 用户偏好 | "喜欢简洁的代码风格" |
| `knowledge` | 用户知识 | "熟悉 Python 和 TypeScript" |
| `context` | 当前上下文 | "正在开发 DeerFlow 项目" |
| `behavior` | 行为模式 | "倾向于先测试后实现" |
| `goal` | 目标 | "学习 LangGraph" |

## 工作流

```
┌─────────────────────────────────────────────────────────────────┐
│  1. MemoryMiddleware 过滤消息（用户输入 + 最终 AI 响应）            │
│     捕获 user_id 并通过捕获的 user_id 排队对话                    │
└─────────────────────────┬───────────────────────────────────────┘
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│  2. 队列防抖（默认 30 秒），批量更新，每线程去重                    │
└─────────────────────────┬───────────────────────────────────────┘
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│  3. 后台线程调用 LLM 提取上下文更新和事实                          │
│     使用存储的 user_id（非 contextvar，定时器线程不可用）            │
└─────────────────────────┬───────────────────────────────────────┘
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│  4. 原子应用更新（临时文件 + 重命名），缓存失效                    │
│     在追加前跳过重复事实内容                                       │
└─────────────────────────┬───────────────────────────────────────┘
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│  5. 下次交互时，注入前 15 个事实 + 上下文到系统提示的 <memory> 标签  │
└─────────────────────────────────────────────────────────────────┘
```

## 配置选项

`config.yaml` → `memory`:

| 选项 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `enabled` | bool | true | 主开关 |
| `injection_enabled` | bool | true | 是否注入到系统提示 |
| `storage_path` | str | null | 记忆文件路径（绝对路径选择不参与每用户隔离） |
| `debounce_seconds` | int | 30 | 处理前等待时间 |
| `model_name` | str | null | 更新用 LLM（null = 默认模型） |
| `max_facts` | int | 100 | 最大事实数 |
| `fact_confidence_threshold` | float | 0.7 | 事实置信度阈值 |
| `max_injection_tokens` | int | 2000 | 提示注入的 token 限制 |

### 配置示例

```yaml
memory:
  enabled: true
  injection_enabled: true
  debounce_seconds: 30
  model_name: null
  max_facts: 100
  fact_confidence_threshold: 0.7
  max_injection_tokens: 2000
```

## 去重机制

### 事实去重

- 空白规范化: 比较前修剪前导/尾随空白
- 内容匹配: 相同内容的事实不重复追加
- 置信度过滤: 低于 `fact_confidence_threshold` 的事实不存储

### 线程去重

- 每线程在防抖窗口内只处理一次
- 防止同一对话的重复更新

## 缓存策略

- 缓存键: `(user_id, agent_name)` 元组
- 文件 mtime 变更时自动失效
- 原子写入后显式失效

## 最佳实践

### 事实提取提示

LLM 被指示提取:
- 明确的偏好陈述
- 重复的行为模式
- 重要的上下文信息
- 长期目标

### 记忆注入

系统提示中的 `<memory>` 标签包含:
- 用户上下文摘要
- 前 15 个最相关事实
- 按置信度和相关性排序

### 调试记忆

查看记忆内容:
```bash
cat backend/.deer-flow/users/{user_id}/memory.json | jq
```

强制重新加载:
```bash
POST /api/memory/reload
```

查看状态:
```bash
GET /api/memory/status
```
