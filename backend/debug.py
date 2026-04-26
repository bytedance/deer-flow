#!/usr/bin/env python
"""
Lead Agent 调试脚本

===================
设计思路说明
===================

**为什么需要这个脚本**：
1. **本地调试**：提供在 VS Code 中设置断点调试 agent 执行流程的能力
2. **快速迭代**：无需启动完整的 LangGraph Server 和 Gateway API
3. **交互式测试**：通过终端直接与 agent 交互，验证功能

**核心设计模式**：
- **独立运行**：直接使用 `uv run` 执行，绕过 HTTP 层
- **最小依赖**：只依赖 deerflow-harness 包，不涉及 FastAPI
- **交互式循环**：提供类似 REPL 的交互体验

**为什么这样设计**：
- **PYTHONPATH=.**：确保 uv 工作区正确解析 deerflow-harness 和 app 包
- **异步主函数**：Agent 执行需要异步环境
- **MCP 初始化**：在启动时初始化 MCP 工具，确保工具可用
- **错误处理**：捕获并显示异常，便于调试

**使用场景**：
- 调试 agent 执行流程
- 测试新工具或中间件
- 验证 prompt 模板
- 分析 agent 响应生成过程

**运行要求**：
    从 backend/ 目录使用 `uv run` 运行，以便 uv 工作区
    正确解析 deerflow-harness 和 app 包：

        cd backend && PYTHONPATH=. uv run python debug.py

**使用方法**：
    1. 在 agent.py 或其他文件中设置断点
    2. 按 F5 或使用"运行和调试"面板
    3. 在终端中输入消息与 agent 交互
"""

import asyncio
import logging

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage

from deerflow.agents import make_lead_agent

# 加载 .env 文件中的环境变量
# 为什么需要：API keys 等敏感信息不应硬编码在代码中
load_dotenv()

# 配置日志系统
# 为什么这样配置：
# - level=INFO：显示足够的调试信息，但不至于过于冗长
# - 包含时间戳：便于追踪执行顺序
# - 标准格式：易于阅读和解析
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


async def main():
    """
    调试脚本的主函数

    ===================
    设计思路说明
    ===================

    **核心职责**：
    初始化 agent 并提供交互式命令行界面。

    **执行流程**：
    1. 初始化 MCP 工具（如果可用）
    2. 创建 agent 实例
    3. 进入交互式循环，读取用户输入并调用 agent
    4. 显示 agent 响应

    **为什么这样设计**：
    - **MCP 初始化容错**：MCP 工具可能不可用，失败时只显示警告
    - **固定 thread_id**：使用固定的调试线程 ID，便于追踪状态
    - **交互式循环**：持续运行直到用户输入 quit/exit
    - **错误捕获**：显示完整错误堆栈，便于调试
    """

    # 步骤 1：在启动时初始化 MCP 工具
    # 为什么在启动时初始化：
    # - MCP 工具需要异步初始化
    # - 避免首次调用时的延迟
    # - 提前发现配置错误
    try:
        from deerflow.mcp import initialize_mcp_tools

        await initialize_mcp_tools()
    except Exception as e:
        # MCP 工具初始化失败不应阻止调试
        # 显示警告并继续执行
        print(f"Warning: Failed to initialize MCP tools: {e}")

    # 步骤 2：创建 agent 配置
    # 为什么使用 configurable 字典：
    # - LangGraph 的标准配置方式
    # - 支持运行时配置
    # - 可以覆盖默认配置
    config = {
        "configurable": {
            "thread_id": "debug-thread-001",  # 固定的调试线程 ID
            "thinking_enabled": True,         # 启用扩展思考
            "is_plan_mode": True,             # 启用计划模式
            # 取消注释以使用特定模型
            # "model_name": "kimi-k2.5",
        }
    }

    # 步骤 3：创建 lead agent 实例
    # make_lead_agent 返回一个 LangGraph 编译的 Runnable
    agent = make_lead_agent(config)

    # 显示欢迎信息
    print("=" * 50)
    print("Lead Agent Debug Mode")
    print("Type 'quit' or 'exit' to stop")
    print("=" * 50)

    # 步骤 4：进入交互式循环
    while True:
        try:
            # 读取用户输入
            user_input = input("\nYou: ").strip()

            # 跳过空输入
            if not user_input:
                continue

            # 检查退出命令
            if user_input.lower() in ("quit", "exit"):
                print("Goodbye!")
                break

            # 调用 agent
            # 为什么使用 HumanMessage：
            # - LangChain 的标准消息格式
            # - 表示来自人类的输入
            state = {"messages": [HumanMessage(content=user_input)]}
            result = await agent.ainvoke(state, config=config, context={"thread_id": "debug-thread-001"})

            # 显示 agent 响应
            # 为什么只显示最后一条消息：
            # - agent 可能返回多条消息（工具调用等）
            # - 最后一条通常是 AI 的最终响应
            if result.get("messages"):
                last_message = result["messages"][-1]
                print(f"\nAgent: {last_message.content}")

        except KeyboardInterrupt:
            # 用户按下 Ctrl+C
            print("\nInterrupted. Goodbye!")
            break
        except Exception as e:
            # 捕获并显示其他异常
            print(f"\nError: {e}")
            import traceback

            traceback.print_exc()


# 程序入口点
# 为什么使用 asyncio.run：
# - main 是异步函数
# - asyncio.run 创建新的事件循环并运行 main
# - 确保正确的异步生命周期管理
if __name__ == "__main__":
    asyncio.run(main())
