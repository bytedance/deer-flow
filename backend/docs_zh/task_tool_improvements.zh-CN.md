# Task 工具改进

## 概述

Task 工具已完成改进，用于消除低效的 LLM 轮询。此前使用后台任务时，LLM 需要反复调用 `task_status` 轮询完成状态，导致不必要的 API 请求。

## 已完成改动

### 1. 移除 `run_in_background` 参数

`task` 工具已移除 `run_in_background` 参数。现在所有 subagent 任务默认异步运行，但工具会自动处理完成流程。

**之前：**
```python
# LLM 需要自行管理轮询
task_id = task(
    subagent_type="bash",
    prompt="Run tests",
    description="Run tests",
    run_in_background=True
)
# 然后 LLM 需要反复轮询：
while True:
    status = task_status(task_id)
    if completed:
        break
```

**之后：**
```python
# 工具会阻塞直到完成，轮询在后端执行
result = task(
    subagent_type="bash",
    prompt="Run tests",
    description="Run tests"
)
# 调用返回后可立即拿到结果
```

### 2. 后端轮询

`task_tool` 现在会：
- 异步启动 subagent 任务
- 在后端轮询完成状态（每 2 秒）
- 阻塞当前工具调用直到任务完成
- 直接返回最终结果

这意味着：
- ✅ LLM 只需发起一次工具调用
- ✅ 不再有浪费性的 LLM 轮询请求
- ✅ 状态检查由后端统一处理
- ✅ 具备超时保护（最长 5 分钟）

### 3. 对 LLM 隐藏 `task_status`

`task_status_tool` 不再暴露给 LLM。它仍保留在代码库中供潜在内部/调试用途，但 LLM 无法直接调用。

### 4. 更新文档

- 更新 `prompt.py` 中的 `SUBAGENT_SECTION`，移除所有后台任务与轮询相关描述
- 简化使用示例
- 明确说明该工具会自动等待任务完成

## 实现细节

### 轮询逻辑

位于 `packages/harness/deerflow/tools/builtins/task_tool.py`：

```python
# 启动后台执行
task_id = executor.execute_async(prompt)

# 在后端轮询任务状态
while True:
    result = get_background_task_result(task_id)

    # 检查任务是否完成或失败
    if result.status == SubagentStatus.COMPLETED:
        return f"[Subagent: {subagent_type}]\n\n{result.result}"
    elif result.status == SubagentStatus.FAILED:
        return f"[Subagent: {subagent_type}] Task failed: {result.error}"

    # 下一轮轮询前等待
    time.sleep(2)

    # 超时保护（5 分钟）
    if poll_count > 150:
        return "Task timed out after 5 minutes"
```

### 执行超时

除轮询超时外，subagent 执行本身也有内置超时机制：

**配置**（`packages/harness/deerflow/subagents/config.py`）：
```python
@dataclass
class SubagentConfig:
    # ...
    timeout_seconds: int = 300  # 默认 5 分钟
```

**线程池架构：**

为避免嵌套线程池和资源浪费，系统采用两个专用线程池：

1. **调度线程池**（`_scheduler_pool`）：
   - 最大 worker：4
   - 用途：编排后台任务执行
   - 执行 `run_task()`，负责任务生命周期管理

2. **执行线程池**（`_execution_pool`）：
   - 最大 worker：8（更大以避免阻塞）
   - 用途：实际执行 subagent，并支持超时控制
   - 执行 `execute()` 方法以调用 agent

**工作方式：**
```python
# 在 execute_async() 中：
_scheduler_pool.submit(run_task)  # 提交编排任务

# 在 run_task() 中：
future = _execution_pool.submit(self.execute, task)  # 提交执行任务
exec_result = future.result(timeout=timeout_seconds)  # 按超时等待
```

**收益：**
- ✅ 关注点清晰分离（调度 vs 执行）
- ✅ 无嵌套线程池
- ✅ 在正确层级执行超时控制
- ✅ 更好的资源利用率

**两层超时保护：**
1. **执行超时**：subagent 执行本身有 5 分钟超时（`SubagentConfig` 可配置）
2. **轮询超时**：工具轮询有 5 分钟超时（30 次轮询 × 10 秒）

即使 subagent 执行发生卡死，系统也不会无限等待。

### 价值

1. **降低 API 成本**：不再有重复的 LLM 轮询请求
2. **更简单的使用体验**：LLM 无需管理轮询逻辑
3. **更高可靠性**：后端统一处理状态检查
4. **超时保护**：双层超时机制防止无限等待（执行 + 轮询）

## 测试

验证改动是否生效：

1. 启动一个持续几秒的 subagent 任务
2. 验证工具调用会阻塞直到完成
3. 验证结果会被直接返回
4. 验证不会出现 `task_status` 调用

示例测试场景：
```python
# 该调用应阻塞约 10 秒后返回结果
result = task(
    subagent_type="bash",
    prompt="sleep 10 && echo 'Done'",
    description="Test task"
)
# result 应包含 "Done"
```

## 迁移说明

对于此前使用 `run_in_background=True` 的用户/代码：
- 直接移除该参数
- 删除任何手写轮询逻辑
- 工具会自动等待直到任务完成

除去移除参数这一点外，不需要其他改动——API 整体行为保持兼容。
