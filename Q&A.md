# Q&A

## 1. 什么时候会到 `reporter_node`？

### 简短结论

`reporter_node` 是最终写报告的节点。当 Planner 认为“资料已经足够”，或者研究/规划流程已经不能继续、达到最大规划轮数时，工作流就会跳到 `reporter_node`，生成最终报告，然后结束。

### 图结构中的位置

在 `src/graph/builder.py` 中，`reporter` 节点被注册到图里，并且它执行完成后直接进入 `END`：

```python
builder.add_node("reporter", reporter_node)
builder.add_edge("reporter", END)
```

但图里没有显式写 `planner -> reporter` 的普通边。真正进入 `reporter_node`，主要是节点函数返回 `Command(goto="reporter")` 触发的动态跳转。

### 主要触发场景

#### 1. 规划轮数达到上限

在 `planner_node` 中，如果当前 `plan_iterations` 已经达到配置里的 `max_plan_iterations`，会直接跳到 `reporter`：

```python
if plan_iterations >= configurable.max_plan_iterations:
    return Command(
        update=preserve_state_meta_fields(state),
        goto="reporter"
    )
```

这是一种兜底机制，避免 Planner 无限循环规划。

#### 2. Planner 判断上下文已经足够

如果 Planner 生成的计划里 `has_enough_context` 为真，说明模型认为已有信息足够写最终报告，不需要再派发研究任务：

```python
if isinstance(curr_plan, dict) and curr_plan.get("has_enough_context"):
    new_plan = Plan.model_validate(curr_plan)
    return Command(
        update={
            "messages": [AIMessage(content=full_response, name="planner")],
            "current_plan": new_plan,
            **preserve_state_meta_fields(state),
        },
        goto="reporter",
    )
```

#### 3. 研究任务全部完成后回到 Planner，再由 Planner 决定是否进入 Reporter

`research_team` 节点之后有条件边，会检查当前计划里的步骤是否已经执行完成：

```python
if all(step.execution_res for step in current_plan.steps):
    return "planner"
```

也就是说，研究团队不是直接去 `reporter`，而是先回到 `planner`。Planner 会基于已经收集到的观察结果和当前计划，判断是否继续规划，还是进入最终报告阶段。

#### 4. Planner 输出解析失败，但已经至少跑过一轮

如果 Planner 的输出不是合法 JSON，或者计划解析失败，代码里也有兜底逻辑：

- 第一次规划失败：可能直接结束。
- 已经有过规划/执行轮次后失败：跳到 `reporter`，尽量基于已有信息生成报告。

### 常见执行链路

一个典型流程大致是：

```text
START
  -> coordinator
  -> planner
  -> human_feedback
  -> research_team
  -> researcher / analyst / coder
  -> research_team
  -> planner
  -> reporter
  -> END
```

其中 `researcher`、`analyst`、`coder` 负责执行不同类型的计划步骤；执行完以后回到 `research_team`，再由 `research_team` 判断下一步是继续跑未完成步骤，还是回到 `planner`。

### 一句话理解

`reporter_node` 不是研究流程中的普通中间节点，而是最终收口节点。只要系统判断“可以写最终答案了”，就会进入它。

## 2. `checkpoint` 有什么用？

### 简短结论

`checkpoint` 可以理解为 Agent 工作流的“存档点”。它保存 LangGraph 当前线程的状态，让系统支持多轮对话、人工确认、中断恢复，以及服务重启后的状态恢复。

### 在图构建里的作用

`src/graph/builder.py` 里有两个构建函数：

```python
def build_graph_with_memory():
    memory = MemorySaver()
    builder = _build_base_graph()
    return builder.compile(checkpointer=memory)


def build_graph():
    builder = _build_base_graph()
    return builder.compile()
```

区别是：

- `build_graph()`：没有 checkpointer，图执行状态不会被保存。
- `build_graph_with_memory()`：使用 `MemorySaver`，把状态保存在进程内存里。

服务端默认使用的是 `build_graph_with_memory()`：

```python
graph = build_graph_with_memory()
```

### 它保存什么状态？

Checkpoint 保存的是 LangGraph 线程状态，比如：

- 当前执行到哪个节点。
- `messages` 对话历史。
- `current_plan` 当前计划。
- `observations` 研究观察结果。
- `plan_iterations` 规划轮数。
- 是否在 `human_feedback_node` 被 `interrupt()` 暂停。
- 后续 resume 时需要恢复的上下文。

没有 checkpoint 的话，每次请求更像是一次全新的运行，很难恢复之前停下来的节点。

### 为什么人工反馈需要 checkpoint？

在 `human_feedback_node` 中，如果计划不是自动接受，会调用：

```python
feedback = interrupt("Please Review the Plan.")
```

这会让图暂停，等待用户反馈。之后用户点击接受或编辑计划时，系统需要知道：

- 之前停在哪个节点。
- 当时的 `current_plan` 是什么。
- 之前有哪些消息和状态。

这些都依赖 checkpoint 保存。

### 默认内存 checkpoint 与数据库 checkpoint

默认的 `MemorySaver` 只保存在当前 Python 进程内：

- 优点：简单、开发方便。
- 缺点：服务重启后状态丢失。

如果配置了环境变量：

```bash
LANGGRAPH_CHECKPOINT_SAVER=true
LANGGRAPH_CHECKPOINT_DB_URL=postgresql://...
```

或者：

```bash
LANGGRAPH_CHECKPOINT_DB_URL=mongodb://...
```

服务端会使用 PostgreSQL 或 MongoDB 版本的 checkpointer：

```python
graph.checkpointer = _pg_checkpointer
```

或：

```python
graph.checkpointer = _mongo_checkpointer
```

这样 checkpoint 就会持久化到数据库里，服务重启后仍然有机会恢复线程状态。

### `src/graph/checkpoint.py` 的额外作用

这个文件里还有一个 `ChatStreamManager`，它和 LangGraph 的状态 checkpoint 不是完全同一件事。

它主要负责把 SSE 流式输出片段按 `thread_id` 暂存在内存中，并在流结束时写入 MongoDB 或 PostgreSQL：

```python
def process_stream_message(
    self, thread_id: str, message: str, finish_reason: str
) -> bool:
    ...
```

当 `finish_reason` 是 `stop` 或 `interrupt` 时，会把这一轮完整的流式消息持久化：

```python
if finish_reason in ("stop", "interrupt"):
    return self._persist_complete_conversation(
        thread_id, store_namespace, current_index
    )
```

所以这里有两层含义：

- LangGraph checkpointer：保存工作流状态。
- `ChatStreamManager`：保存流式聊天事件内容。

### 一句话理解

`checkpoint` 解决的是“工作流跑到一半如何记住现场”的问题；没有它，复杂 Agent 的中断、续跑、人工反馈、多轮线程状态都会变得不可靠。

## human-feedback

### 1. 目前有哪些地方会出现 human-feedback？

这个分支里和 human-feedback 相关的机制主要有三类：

#### 1. 显式的 `human_feedback_node`

图构建时注册了一个名为 `human_feedback` 的节点：

```python
builder.add_node("human_feedback", human_feedback_node)
```

Planner 在生成计划后，如果没有直接判断 `has_enough_context=true`，就会把流程交给 `human_feedback`：

```python
return Command(
    update={
        "messages": [AIMessage(content=full_response, name="planner")],
        "current_plan": full_response,
        **preserve_state_meta_fields(state),
    },
    goto="human_feedback",
)
```

这是最核心的人工反馈位置：让用户审阅 Planner 生成的研究计划。

#### `has_enough_context` 是怎么判断的？

这里不是后端代码用固定规则去计算 `has_enough_context`，而是 **Planner LLM 根据 `src/prompts/planner.md` 的提示词规则自己判断，并在输出 JSON 里填写这个字段**。

Planner 的输出必须符合 `Plan` 模型：

```python
class Plan(BaseModel):
    locale: str
    has_enough_context: bool
    thought: str = Field(default="", description="Thinking process for the plan")
    title: str
    steps: List[Step] = Field(
        default_factory=list,
        description="Research & Processing steps to get more context",
    )
```

提示词里对“上下文是否足够”给了很严格的标准。只有同时满足这些条件，Planner 才应该把 `has_enough_context` 设为 `true`：

- 当前信息能用具体细节完整回答用户问题的所有方面。
- 信息是全面、最新、可靠来源支撑的。
- 不存在明显信息缺口、歧义或矛盾。
- 关键数据点有可信证据或来源支撑。
- 信息既覆盖事实数据，也覆盖必要背景。
- 信息量足够支撑一份完整报告。

提示词还明确要求：**即使 90% 确定信息足够，也要倾向继续收集更多信息**。所以默认策略是保守的，除非非常确定上下文足够，否则应该输出：

```json
{
  "has_enough_context": false,
  "steps": [...]
}
```

代码层面的判断发生在 `planner_node` 中。Planner 先调用 LLM 得到 `full_response`，然后清理、解析 JSON：

```python
cleaned_response = repair_json_output(full_response)
curr_plan = json.loads(cleaned_response)
curr_plan_content = extract_plan_content(curr_plan)
curr_plan = json.loads(repair_json_output(curr_plan_content))
```

随后只检查解析结果里的字段：

```python
if isinstance(curr_plan, dict) and curr_plan.get("has_enough_context"):
    new_plan = Plan.model_validate(curr_plan)
    return Command(
        update={
            "messages": [AIMessage(content=full_response, name="planner")],
            "current_plan": new_plan,
            **preserve_state_meta_fields(state),
        },
        goto="reporter",
    )
```

如果 `has_enough_context` 为 `true`，说明 Planner 认为不需要继续研究，也不需要用户审阅计划，直接进入 `reporter` 写最终报告。

如果 `has_enough_context` 为 `false`，或者字段缺失/为假值，就走下面这个默认分支：

```python
return Command(
    update={
        "messages": [AIMessage(content=full_response, name="planner")],
        "current_plan": full_response,
        **preserve_state_meta_fields(state),
    },
    goto="human_feedback",
)
```

因此，`human_feedback` 出现的本质原因是：Planner 认为当前上下文还不足以直接回答，需要先把研究计划交给用户确认，然后再执行研究步骤。

#### 2. `human_feedback_node` 内部的 LangGraph `interrupt()`

在 `src/graph/nodes.py` 中，如果没有开启自动接受计划，节点会调用：

```python
feedback = interrupt("Please Review the Plan.")
```

这里会暂停图执行，并把一个 interrupt 事件交给服务端流式输出。用户可以选择接受计划，或者要求编辑计划。

#### 3. 工具执行前的人工确认

`src/agents/tool_interceptor.py` 里还有一个工具级别的 interrupt 机制：

```python
feedback = interrupt(
    f"About to execute tool: '{tool_name}'\n\nInput:\n{tool_input_repr}\n\nApprove execution?"
)
```

它不是 `human_feedback_node`，但也是人类反馈机制的一部分。只要请求配置了 `interrupt_before_tools`，对应工具在执行前就会先暂停，等待用户批准。

相关入口在 `ChatRequest` 中：

```python
interrupt_before_tools: List[str] = Field(
    default_factory=list,
    description="List of tool names to interrupt before execution (e.g., ['db_tool', 'api_tool'])",
)
```

然后执行 agent 时会把这些工具包装起来：

```python
processed_tools = wrap_tools_with_interceptor(tools, interrupt_before_tools)
```

#### 4. Clarification 里的类 interrupt 事件

`coordinator_node` 在澄清模式下，也会通过状态更新放入 `__interrupt__`：

```python
"__interrupt__": [("coordinator", response.content)]
```

这和 `human_feedback_node` 里的 LangGraph `interrupt()` 不是同一种写法，更像是项目自己借用了 `__interrupt__` 事件形态来把澄清问题推给前端。理解代码时要区分：计划审阅和工具确认是 LangGraph `interrupt()`，澄清问题是 coordinator 侧构造的类 interrupt 状态。

### 2. human-feedback 是怎么等待用户请求的？底层线程运行时怎么样？

关键点：**它不是让一个 Python 线程一直阻塞等待用户点击。**

在 `human_feedback_node` 中调用 `interrupt(...)` 后，LangGraph 会中断当前图运行，把中断信息写入当前线程的 checkpoint，并通过 `astream` 产出包含 `__interrupt__` 的事件。

服务端在 `_stream_graph_events()` 里识别这个事件：

```python
if "__interrupt__" in event_data:
    yield _create_interrupt_event(thread_id, event_data)
```

然后 `_create_interrupt_event()` 会把它转换成前端能理解的 SSE 事件：

```python
return _make_event(
    "interrupt",
    {
        "thread_id": thread_id,
        "id": interrupt_id,
        "role": "assistant",
        "content": interrupt.value,
        "finish_reason": "interrupt",
        "options": [
            {"text": "Edit plan", "value": "edit_plan"},
            {"text": "Start research", "value": "accepted"},
        ],
    },
)
```

所以运行时大概是：

```text
graph.astream()
  -> 执行到 human_feedback_node
  -> interrupt("Please Review the Plan.")
  -> LangGraph 保存 checkpoint
  -> astream 产出 __interrupt__ update
  -> FastAPI 转成 SSE interrupt 事件
  -> 当前 HTTP 流结束或暂停在客户端交互边界
  -> 用户下一次请求携带 interrupt_feedback
  -> 后端用 Command(resume=...) 恢复
```

这里的“等待”是协议层和 checkpoint 层的等待，而不是服务端工作线程一直占住不放。后端把“当前执行到哪里、当时状态是什么”保存起来，等下一次请求再恢复。

这也是为什么 checkpoint 很重要：没有 checkpoint，resume 时就不知道之前停在 `human_feedback_node` 的哪个 `interrupt()` 调用点，也不知道当时的 `current_plan` 和上下文。

### 3. human-feedback 之后的状态流转和可能链路是什么？

`human_feedback_node` 的核心输入是：

- `current_plan`：Planner 生成的计划。
- `auto_accepted_plan`：是否跳过人工审阅。
- `plan_iterations`：已经规划/执行过几轮。

主要链路如下。

#### 1. 自动接受计划

如果请求里 `auto_accepted_plan=True`，就不会调用 `interrupt()`，直接解析计划并进入研究团队：

```text
planner
  -> human_feedback
  -> research_team
```

代码里表现为跳过：

```python
if not auto_accepted_plan:
    feedback = interrupt("Please Review the Plan.")
```

后面解析计划成功后：

```python
return Command(
    update=update_dict,
    goto="research_team",
)
```

#### 2. 用户接受计划

用户选择 `Start research` 后，前端会把反馈值作为 `interrupt_feedback` 传回来。服务端拼成：

```python
resume_msg = f"[{interrupt_feedback}]"
```

如果是 `accepted`，恢复到节点后会被识别为：

```python
elif feedback_normalized.startswith("[ACCEPTED]"):
    logger.info("Plan is accepted by user.")
```

然后进入计划解析、`Plan.model_validate()`，成功后：

```text
human_feedback
  -> research_team
  -> researcher / analyst / coder
  -> research_team
  -> planner
  -> reporter 或 human_feedback
```

#### 3. 用户要求编辑计划

用户选择 `Edit plan` 后，恢复值会变成类似：

```text
[edit_plan] 用户补充意见
```

节点里会识别：

```python
if feedback_normalized.startswith("[EDIT_PLAN]"):
    return Command(
        update={
            "messages": [
                HumanMessage(content=feedback, name="feedback"),
            ],
            **preserve_state_meta_fields(state),
        },
        goto="planner",
    )
```

这条链路是：

```text
human_feedback
  -> planner
  -> human_feedback
```

也就是说，用户的编辑意见会作为 `HumanMessage(name="feedback")` 加入消息历史，让 Planner 基于反馈重新生成计划。

#### 4. 空反馈、无效反馈

如果恢复值为空、`None`，或者不是 `[ACCEPTED]` / `[EDIT_PLAN]` 开头，都会回到 `planner`：

```text
human_feedback
  -> planner
```

这是容错逻辑，避免用户反馈格式异常导致整个流程崩掉。

#### 5. 计划解析失败

用户接受后，`human_feedback_node` 会把 `current_plan` 解析成 `Plan` 模型。如果解析失败：

- 如果还没超过最大规划轮数：回到 `planner` 重新规划。
- 如果已经跑过多轮：跳到 `reporter`，尽量用已有信息生成报告。
- 如果第一次就失败且无法恢复：可能进入 `__end__`。

对应链路：

```text
human_feedback
  -> planner
```

或：

```text
human_feedback
  -> reporter
  -> END
```

或：

```text
human_feedback
  -> END
```

### 4. human-feedback 之后的恢复怎么做？

恢复发生在服务端 `_astream_workflow_generator()`。

正常第一次请求时，后端构造完整的初始状态：

```python
workflow_input = {
    "messages": messages,
    "plan_iterations": 0,
    "final_report": "",
    "current_plan": None,
    "observations": [],
    "auto_accepted_plan": auto_accepted_plan,
    ...
}
```

但如果这是一次人工反馈后的请求，也就是：

```python
if not auto_accepted_plan and interrupt_feedback:
```

后端不会再传完整初始状态，而是构造 LangGraph 的 resume 命令：

```python
resume_msg = f"[{interrupt_feedback}]"
if messages:
    resume_msg += f" {messages[-1]['content']}"
workflow_input = Command(resume=resume_msg)
```

之后仍然用同一个 `thread_id` 运行：

```python
async for event in _stream_graph_events(
    graph, workflow_input, workflow_config, thread_id
):
    yield event
```

LangGraph 会根据 `thread_id` 找到之前 interrupt 时保存的 checkpoint，把 `Command(resume=...)` 的值作为 `interrupt()` 的返回值交回给节点代码。

所以从节点视角看，恢复后的代码就像普通函数调用返回了一样：

```python
feedback = interrupt("Please Review the Plan.")
```

第一次执行时，它在这里暂停；恢复执行时，`feedback` 会得到类似：

```text
[accepted] ...
```

或：

```text
[edit_plan] ...
```

然后继续执行下面的分支判断。

### 5. 这个机制的关键不变量

- 必须使用同一个 `thread_id`，否则 LangGraph 找不到之前的 checkpoint。
- 必须有 checkpointer。当前服务默认 `build_graph_with_memory()` 使用 `MemorySaver`，只在进程内有效；如果服务重启，需要 PostgreSQL / MongoDB checkpointer 才能跨进程恢复。
- `interrupt_feedback` 的值会被包装成方括号格式，比如 `accepted` 变成 `[accepted]`，以便 `human_feedback_node` 用 `startswith("[ACCEPTED]")` 或 `startswith("[EDIT_PLAN]")` 判断。
- `auto_accepted_plan=True` 会绕过人工审阅，不会进入等待用户反馈的 `interrupt()`。
- 工具级 interrupt 和计划级 human feedback 共享 LangGraph interrupt/resume 思路，但判断逻辑不同：工具级反馈只要包含 `approved`、`yes`、`continue`、`ok`、`accepted` 等关键词就视为同意。

### 6. 一句话理解

这个框架的 human-feedback 本质是 **LangGraph interrupt + checkpoint + Command(resume=...)**：第一次运行到人工确认点时保存现场并把问题发给前端；用户下一次请求带回反馈后，系统从同一个 checkpoint 恢复，把反馈作为 `interrupt()` 的返回值继续执行。
