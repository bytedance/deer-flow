# 任务工具改进

===================
设计思路说明
===================

**为什么需要改进任务工具**：
1. **消除浪费性轮询**：之前LLM需要反复调用`task_status`来检查完成状态
2. **降低API成本**：减少不必要的LLM请求
3. **简化使用体验**：让工具自动处理等待逻辑
4. **提高可靠性**：由后端统一管理状态检查

**核心改进目标**：
- 从LLM管理的轮询改为后端自动轮询
- 保持异步执行的优势，但隐藏复杂性
- 提供超时保护，防止无限等待
- 简化API，减少参数和步骤

## 功能概述

任务工具已得到改进，消除了浪费性的LLM轮询。以前，使用后台任务时，LLM必须反复调用`task_status`来轮询完成状态，导致不必要的API请求。

**为什么之前的设计有问题**：
- **LLM负担**：让LLM管理轮询逻辑是浪费其能力
- **成本高昂**：每次轮询都是一次完整的LLM API调用
- **延迟累积**：轮询间隔加上网络延迟增加总等待时间
- **复杂性高**：需要LLM理解并正确实现轮询模式

## 实施的变更

### 1. 移除`run_in_background`参数

从`task`工具中移除了`run_in_background`参数。所有子代理任务现在默认异步运行，但工具会自动处理完成等待。

**为什么移除这个参数**：
- **默认异步**：所有任务都应该异步执行以提高效率
- **自动等待**：工具应该自动等待完成，而不是让调用者管理
- **简化API**：减少参数数量，降低使用复杂度
- **行为一致**：无论是否后台运行，都使用相同的代码路径

**改进前的使用方式**：
```python
# LLM had to manage polling
task_id = task(
    subagent_type="bash",
    prompt="Run tests",
    description="Run tests",
    run_in_background=True
)
# Then LLM had to poll repeatedly:
while True:
    status = task_status(task_id)
    if completed:
        break
```

**After:**
```python
# Tool blocks until complete, polling happens in backend
result = task(
    subagent_type="bash",
    prompt="Run tests",
    description="Run tests"
)
# Result is available immediately after the call returns
```

### 2. 后端轮询机制

`task_tool`现在：
- 异步启动子代理任务
- 在后端轮询完成状态（每2秒）
- 阻塞工具调用直到完成
- 直接返回最终结果

**这意味着**：
- ✅ LLM只进行一次工具调用
- ✅ 没有浪费性的LLM轮询请求
- ✅ 后端处理所有状态检查
- ✅ 超时保护（最多5分钟）

**为什么使用后端轮询**：
- **成本优化**：后端轮询是简单的HTTP请求，成本远低于LLM API调用
- **可靠性**：后端轮询不受LLM输出格式影响
- **一致性**：统一的轮询逻辑，不会因为LLM理解不同而有差异
- **可观测性**：后端轮询更容易添加日志和监控

### 3. Removed `task_status` from LLM Tools

The `task_status_tool` is no longer exposed to the LLM. It's kept in the codebase for potential internal/debugging use, but the LLM cannot call it.

### 4. Updated Documentation

- Updated `SUBAGENT_SECTION` in `prompt.py` to remove all references to background tasks and polling
- Simplified usage examples
- Made it clear that the tool automatically waits for completion

## 实现细节

### 轮询逻辑

Located in `packages/harness/deerflow/tools/builtins/task_tool.py`:

```python
# Start background execution
task_id = executor.execute_async(prompt)

# Poll for task completion in backend
while True:
    result = get_background_task_result(task_id)

    # Check if task completed or failed
    if result.status == SubagentStatus.COMPLETED:
        return f"[Subagent: {subagent_type}]\n\n{result.result}"
    elif result.status == SubagentStatus.FAILED:
        return f"[Subagent: {subagent_type}] Task failed: {result.error}"

    # Wait before next poll
    time.sleep(2)

    # Timeout protection (5 minutes)
    if poll_count > 150:
        return "Task timed out after 5 minutes"
```

### 执行超时机制

除了轮询超时外，子代理执行现在还具有内置超时机制：

**配置位置**（`packages/harness/deerflow/subagents/config.py`）：
```python
@dataclass
class SubagentConfig:
    # ...
    timeout_seconds: int = 300  # 默认5分钟
```

**为什么需要执行超时**：
- **防止挂起**：子代理可能因为代码错误或外部依赖而挂起
- **资源保护**：限制单个任务的最大执行时间
- **用户体验**：避免用户无限等待
- **可配置性**：不同场景可能需要不同的超时时间

**线程池架构设计**：

为了避免嵌套线程池和资源浪费，我们使用两个专用的线程池：

1. **调度器池**（`_scheduler_pool`）：
   - 最大工作线程：4
   - 用途：协调后台任务执行
   - 运行管理任务生命周期的`run_task()`函数

2. **执行池**（`_execution_pool`）：
   - 最大工作线程：8（更大以避免阻塞）
   - 用途：实际的子代理执行，支持超时
   - 运行调用代理的`execute()`方法

**为什么使用两个线程池**：
- **关注点分离**：调度和执行是不同的职责
- **避免嵌套**：防止线程池嵌套导致的资源问题
- **灵活配置**：调度和执行可以有不同的线程数
- **超时控制**：在正确的层级实现超时机制

**工作原理**：
```python
# In execute_async():
_scheduler_pool.submit(run_task)  # Submit orchestration task

# In run_task():
future = _execution_pool.submit(self.execute, task)  # Submit execution
exec_result = future.result(timeout=timeout_seconds)  # Wait with timeout
```

**架构优势**：
- ✅ 关注点清晰分离（调度 vs 执行）
- ✅ 没有嵌套线程池
- ✅ 在正确的层级强制超时
- ✅ 更好的资源利用率

**两层超时保护**：
1. **执行超时**：子代理执行本身有5分钟超时（在SubagentConfig中可配置）
2. **轮询超时**：工具轮询有5分钟超时（30次轮询 × 10秒）

**为什么需要两层超时**：
- **执行超时**：防止子代理任务本身挂起
- **轮询超时**：防止工具调用无限等待
- **双重保险**：即使一层失败，另一层也能保护系统
- **不同粒度**：执行超时控制任务，轮询超时控制等待

### 改进收益

1. **降低API成本**：不再有重复的LLM轮询请求
2. **更简单的用户体验**：LLM不需要管理轮询逻辑
3. **更好的可靠性**：后端一致地处理所有状态检查
4. **超时保护**：两层超时防止无限等待（执行 + 轮询）

**为什么这些收益很重要**：
- **成本节约**：LLM API调用昂贵，减少轮询直接降低成本
- **用户体验**：减少等待时间和复杂性
- **系统稳定性**：超时保护防止资源耗尽
- **可维护性**：简化的代码更容易理解和维护

## Testing

To verify the changes work correctly:

1. Start a subagent task that takes a few seconds
2. Verify the tool call blocks until completion
3. Verify the result is returned directly
4. Verify no `task_status` calls are made

Example test scenario:
```python
# This should block for ~10 seconds then return result
result = task(
    subagent_type="bash",
    prompt="sleep 10 && echo 'Done'",
    description="Test task"
)
# result should contain "Done"
```

## Migration Notes

For users/code that previously used `run_in_background=True`:
- Simply remove the parameter
- Remove any polling logic
- The tool will automatically wait for completion

No other changes needed - the API is backward compatible (minus the removed parameter).
