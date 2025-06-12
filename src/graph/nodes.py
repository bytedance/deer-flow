# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import base64
import io
import json
import logging
import os
from typing import Annotated, Literal
from PIL import Image
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool
from langgraph.types import Command, interrupt
from langchain_mcp_adapters.client import MultiServerMCPClient
from src.mcp_client.mcp_client import MultiServerMCPClient_wFileUpload
from src.agents import create_agent
from src.tools.search import LoggedTavilySearch
from src.tools import (
    crawl_tool,
    get_web_search_tool,
    get_retriever_tool,
    python_repl_tool,
)

from src.config.configuration import Configuration
from src.llms.llm import get_llm_by_type
from src.prompts.planner_model import Plan, StepType, Step
from src.prompts.template import apply_prompt_template
from src.utils.json_utils import repair_json_output

from src.graph.types import State
from src.config import SELECTED_SEARCH_ENGINE, SearchEngine

from src.utils.file_descriptors import file2resource

logger = logging.getLogger(__name__)

# Define available LLM types
LLMType = Literal["basic", "reasoning", "vision"]

# Define agent-LLM mapping
AGENT_LLM_MAP: dict[str, LLMType] = {
    "coordinator": "basic",
    "planner": "basic", 
    "router": "basic",
    "analyzer": "basic",
    "coder": "basic",
    "researcher": "basic",
    "reader": "vision",
    "thinker": "reasoning",
    "reporter": "basic",
}

@tool
def handoff_to_planner(
    task_title: Annotated[str, "The title of the task to be handed off."],
    locale: Annotated[str, "The user's detected language locale (e.g., en-US, zh-CN)."],
):
    """Handoff to planner agent to do plan."""
    return

@tool
def call_coder_agent(
    analysis_request: Annotated[str, "Specific coding request for the coder"]
):
    """
    Delegate task to coder agent For coding tasks. 
    Parameters:
        analysis_request: str, Specific code task description, if there are files to be processed, concatenate the file URI at the end of the task description, for example: file_path={URI}
    Returns:
        str, The result of code execution after achieving task objectives through code execution
        """

    return f"Will delegate to coder: {analysis_request}"

@tool
def call_researcher_agent(
    research_request: Annotated[str, "Specific research request for the researcher"]
):
    """
    Delegate task to researcher agent For research and web searching. 
    Parameters:
        research_request: str, Specific research task description, Clearly state the scope of the field you want to research.
    Returns:
        str, The result of research
    """

    return f"Will delegate to researcher: {research_request}"

@tool
def call_reader_agent(
    reader_request: Annotated[str, "Specific image reading process"],
    file_info: Annotated[str, "Image file path to read"],
):
    """
    Delegate task to reader agent For image understanding and vision question answering. 
    Parameters:
        reader_request: str, Specific image readerode task description
        file_info: Image file path need reading, If multiple images need to be read, input them in the following format: file_path1,file_path2,file_path3
    Returns:
        str, The result of image reading
        """
    return f"Will delegate to reader: {reader_request}\nfile_info: {file_info}"

def _create_delegation_step(target_agent: str, request_content: str, current_step_index: int, need_search=False) -> Step:
    """创建委托步骤"""
    step_titles = {
        "coder": "Code Analysis Task",
        "researcher": "Research Task", 
        "reader": "Image Reading Task"
    }
    
    return Step(
        need_search=need_search,
        title=step_titles.get(target_agent, f"{target_agent} Task"),
        description=request_content,
        step_type=target_agent,
        execution_res=None
    )


def coordinator_node(
    state: State, config: RunnableConfig
) -> Command[Literal["planner", "__end__"]]:
    """协调器节点 - 过滤无意义问题"""
    logger.info("Coordinator node is running.")
    configurable = Configuration.from_runnable_config(config)
    messages = apply_prompt_template("coordinator", state, configurable)
    print(State)
    response = (
        get_llm_by_type(AGENT_LLM_MAP["coordinator"])
        .bind_tools([handoff_to_planner])
        .invoke(messages)
    )
    
    logger.debug(f"Coordinator response: {response}")
    
    goto = "__end__"
    locale = state.get("locale", "en-US")
    
    if len(response.tool_calls) > 0:
        goto = "planner"
        try:
            for tool_call in response.tool_calls:
                if tool_call.get("name", "") != "handoff_to_planner":
                    continue
                if tool_locale := tool_call.get("args", {}).get("locale"):
                    locale = tool_locale
                    break
        except Exception as e:
            logger.error(f"Error processing tool calls: {e}")
    else:
        logger.warning("Coordinator response contains no tool calls. Terminating workflow.")
    
    return Command(
        update={
            "locale": locale, 
            "resources": state["resources"],
            "messages": [AIMessage(content=response.content, name="coordinator")],
            "current_step_index": -1  # 初始化步骤索引
        },
        goto=goto,
    )

def planner_node(
    state: State, config: RunnableConfig
) -> Command[Literal["router", "__end__"]]:
    """规划器节点 - 计划 → router"""
    logger.info("Planner node is generating execution plan.")
    configurable = Configuration.from_runnable_config(config)
    
    messages = apply_prompt_template("planner", state, configurable)
    
    # 背景调研
    if state.get("enable_background_investigation", True):
        query = state["messages"][-1].content
        if SELECTED_SEARCH_ENGINE == SearchEngine.TAVILY.value:
            searched_content = LoggedTavilySearch(
                max_results=configurable.max_search_results
            ).invoke(query)
            if isinstance(searched_content, list):
                background_results = [
                    {"title": elem["title"], "content": elem["content"]}
                    for elem in searched_content
                ]
                messages.append({
                    "role": "user",
                    "content": f"Background investigation results:\n{json.dumps(background_results, ensure_ascii=False)}"
                })
    
    llm = get_llm_by_type(AGENT_LLM_MAP["planner"]).with_structured_output(
        Plan, method="json_mode"
    )
    
    response = llm.invoke(messages)
    plan_content = response.model_dump_json(indent=4, exclude_none=True)
    
    logger.info(f"Generated plan: {plan_content}")
    
    try:
        plan_dict = json.loads(plan_content)
        new_plan = Plan.model_validate(plan_dict)
        
        return Command(
            update={
                "current_plan": new_plan,
                "messages": [AIMessage(content=plan_content, name="planner")],
                "current_step_index": -1  # 重置步骤索引
            },
            goto="router"
        )
    except json.JSONDecodeError:
        logger.error("Failed to parse plan JSON")
        return Command(goto="__end__")

def router_node(
    state: State
) -> Command[Literal["analyzer", "coder", "researcher", "reader", "thinker", "planner", "reporter"]]:
    """路由节点 - 根据planner执行step（按逻辑中转，无LLM）"""
    logger.info("Router node is dispatching tasks.")
    # print(f"router state: {state}")
    current_plan = state.get("current_plan")
    if not current_plan or not current_plan.steps:
        logger.warning("No plan or steps available, routing to planner")
        return Command(goto="planner")
    
    current_step_index = state.get("current_step_index", -1)
    next_step_index = current_step_index + 1
    
    # 检查是否所有步骤都已完成
    if next_step_index >= len(current_plan.steps):
        logger.info("All steps completed, routing to reporter")
        return Command(goto="reporter")
    
    current_step = current_plan.steps[next_step_index]

    # 根据步骤类型路由到相应的agent
    step_type = current_step.step_type.lower()
    
    logger.info(f"Current step index: {current_step_index}, Next step index: {next_step_index}")
    logger.info(f"Total steps: {len(current_plan.steps)}")
    logger.info(f"Routing to {step_type} for step {next_step_index}: {current_step.title}")

    # 更新当前步骤索引
    update_data = {"current_step_index": next_step_index}
    
    logger.info(f"Routing to {step_type} for step {next_step_index}: {current_step.title}")
    
    if step_type == "analyzer":
        return Command(update=update_data, goto="analyzer")
    elif step_type == "coder":
        return Command(update=update_data, goto="coder")
    elif step_type == "researcher":
        return Command(update=update_data, goto="researcher")
    elif step_type == "reader":
        return Command(update=update_data, goto="reader")
    elif step_type == "thinker":
        return Command(update=update_data, goto="thinker")
    else:
        # 默认路由到analyzer
        logger.info(f"Default routing to analyzer for step: {current_step.title}")
        return Command(update=update_data, goto="analyzer")


async def analyzer_node(
    state: State, config: RunnableConfig
) -> Command[Literal["router"]]:
    """分析器节点 - 可以通过插入step委托其他agent"""

    # def test_direct_tool_call():
    #     from langchain_core.tools import tool
    #     print("=== 直接工具调用测试 ===")
    #     llm = get_llm_by_type(AGENT_LLM_MAP["analyzer"])
        
    #     @tool
    #     def call_reader_agent(reader_request: str):
    #         """reader_agent"""
    #         return f"Will delegate to reader: {reader_request}"
        
    #     llm_with_tools = llm.bind_tools([call_reader_agent])
        
    #     # 测试简单英文prompt
    #     response = llm_with_tools.invoke([
    #         HumanMessage(content="Call call_reader_agent with reader_request='analyze image content'")
    #     ])
        
    #     print(f"直接测试结果: {hasattr(response, 'tool_calls') and bool(response.tool_calls)}")
    #     if hasattr(response, 'tool_calls') and response.tool_calls:
    #         print(f"Tool calls: {response.tool_calls}")
    #     else:
    #         print(f"Response content: {response.content}")
        
    #     return response

    # # 运行测试
    # test_result = test_direct_tool_call()

    
    configurable = Configuration.from_runnable_config(config)
    # print(state)
    current_plan = state.get("current_plan")
    current_step_index = state.get("current_step_index", 0)
    current_step = current_plan.steps[current_step_index]

    logger.info(f"Analyzer node working: current_step:{current_step}")
    # 构建analyzer输入（只使用前一个agent传递的message）
    analyzer_input = {
        "messages": [
            HumanMessage(
                content=f"# Current Task\n\n## Title\n{current_step.title}\n\n## Description\n{current_step.description}\n\n## Previous Message\n{state.get('messages', [])[-1].content if state.get('messages') else 'No previous message'}\n\n## Locale\n{state.get('locale', 'en-US')}"
            )
        ],
        "locale": state.get("locale", "en-US"),
        "resources": state.get("resources", [])
    }
    
    messages = apply_prompt_template("analyzer", analyzer_input, configurable)
    # print(f"analyzer{current_step_index}: \n{messages[1].content}")
    # 准备委托工具

    delegation_tools = [call_coder_agent, call_researcher_agent, call_reader_agent]
    delegation_tool_names = {tool.name for tool in delegation_tools}

    # 处理MCP服务器配置
    mcp_servers = {}
    if configurable.mcp_settings:
        for server_name, server_config in configurable.mcp_settings["servers"].items():
            if (
                server_config.get("enabled_tools")
                and "analyzer" in server_config.get("add_to_agents", [])
            ):
                mcp_servers[server_name] = {
                    k: v for k, v in server_config.items()
                    if k in ("transport", "command", "args", "url", "env")
                }

    mcp_tools = []
    # 创建mcp agent
    assert mcp_servers
    
    async with MultiServerMCPClient_wFileUpload(mcp_servers, state=state) as client:
        for tool in client.get_tools():
            mcp_tools.append(tool)
        # print(f"mcp_tools: {mcp_tools}")
            
        all_tools = delegation_tools + mcp_tools
        llm = get_llm_by_type(AGENT_LLM_MAP["analyzer"]).bind_tools(all_tools)
        response = llm.invoke(messages)
        logger.info(response.content)
      
        # 检查tool call
        max_toolcall_iterater_times = configurable.max_toolcall_iterater_times
        iterater_times = 0
        while hasattr(response, 'tool_calls') and response.tool_calls and iterater_times < max_toolcall_iterater_times:
            iterater_times += 1
            logger.info(f"analyzer tool call times: {iterater_times}")
            delegation_calls = []
            mcp_calls = []

            # 判断是mcp还是agent， 如果是mcp需要再将结果返回再跑一遍
            for tool_call in response.tool_calls:
                if tool_call["name"] in delegation_tool_names:
                    delegation_calls.append(tool_call)
                else:
                    mcp_calls.append(tool_call)
            
            # 执行MCP，获取结果, 目前只执行一次mcp
            if mcp_calls:
                mcp_results = []
                for tool_call in mcp_calls:
                    # 找到并执行MCP工具
                    for tool in mcp_tools:
                        if tool.name == tool_call["name"]:
                            result = await tool.coroutine(**tool_call["args"])
                            print(f"tool result: {result}")
                            tool_response_list = json.loads(result[0])
                            result_text = "response text: "
                            for res in tool_response_list:
                                if res["type"] == "text":
                                    result_text = result_text + res["text"] + " | " 
                                elif res["type"] == "uri":
                                    result_text = result_text + "toolcall output file_path: " + res["uri"]
                                else:
                                    raise ValueError
                            mcp_results.append(f"**{tool_call['name']}**\n {result_text}")
                            break
                
                # 将MCP结果返回给analyzer
                mcp_summary = "MCP Tools Results:\n" + "\n".join(mcp_results)
                
                # 第二次LLM调用：基于MCP结果分析
                messages = messages + [
                    AIMessage(content=response.content, tool_calls=response.tool_calls),
                    HumanMessage(content=f"{mcp_summary}\n\nBased on the MCP results, provide your analysis or delegate to appropriate agents.\n## Locale\n{state.get('locale', 'en-US')}")
                ]
                print(messages)
                response = llm.invoke(messages)

            if delegation_calls:
                
                if tool_call["name"] == "call_coder_agent":
                    # 插入coder步骤
                    coder_step = _create_delegation_step("coder", tool_call["args"]["analysis_request"], current_step_index)
                    current_plan.steps.insert(current_step_index + 1, coder_step)
                    
                    # 完成当前步骤
                    current_step.execution_res = f"Delegated to coder: {tool_call['args']['analysis_request']}"
                    # Task delegated to coder
                    return Command(
                        update={
                            "messages": [AIMessage(content=f"{tool_call['args']['analysis_request']}", name="analyzer")],
                            "current_plan": current_plan
                        },
                        goto="router"
                    )
                elif tool_call["name"] == "call_researcher_agent":
                    # 插入researcher步骤
                    researcher_step = _create_delegation_step("researcher", tool_call["args"]["research_request"], current_step_index, need_search=True)
                    current_plan.steps.insert(current_step_index + 1, researcher_step)
                    
                    # 完成当前步骤
                    current_step.execution_res = f"Delegated to researcher: {tool_call['args']['research_request']}"
                    # Task delegated to researcher
                    return Command(
                        update={
                            "messages": [AIMessage(content=f"{tool_call['args']['research_request']}", name="analyzer")],
                            "current_plan": current_plan
                        },
                        goto="router"
                    )
                elif tool_call["name"] == "call_reader_agent":
                    # print(tool_call)
                    # 插入reader步骤
                    reader_request = tool_call['args']['reader_request']
                    file_info = tool_call['args']['file_info']

                    reader_step = _create_delegation_step("reader", reader_request, current_step_index)
                    current_plan.steps.insert(current_step_index + 1, reader_step)
                    
                    # 完成当前步骤
                    current_step.execution_res = f"Delegated to reader: {reader_request}"
                    # Task delegated to reader
                    return Command(
                        update={
                            "messages": [AIMessage(content=f"{reader_request}", name="analyzer")],
                            "current_plan": current_plan,
                            "file_info": file_info
                        },
                        goto="router"
                    )
    
    current_step.execution_res = response.content
    
    return Command(
        update={
            "messages": [AIMessage(content=response.content, name="analyzer")],
            "current_plan": current_plan
        },
        goto="router"
    )

async def coder_node(
    state: State, config: RunnableConfig
) -> Command[Literal["router"]]:
    """编程节点 - 处理编程任务"""
    
    configurable = Configuration.from_runnable_config(config)
    
    current_plan = state.get("current_plan")
    current_step_index = state.get("current_step_index", 0)
    current_step = current_plan.steps[current_step_index]
    logger.info(f"Coder node is executing coding task. current_step: {current_step}")

    # 构建coder输入（只使用前一个agent传递的message）
    coder_input = {
        "messages": [
            HumanMessage(
                content=f"# Current Task\n\n## Title\n{current_step.title}\n\n## Description\n{current_step.description}\n\n## Previous Message\n{state.get('messages', [])[-1].content if state.get('messages') else 'No previous message'}\n\n## Locale\n{state.get('locale', 'en-US')}"
            )
        ],
        "locale": state.get("locale", "en-US"),
        "resources": state.get("resources", [])
    }
    
    messages = apply_prompt_template("coder", coder_input, configurable)
    # print(f"code: \n{messages}")
    # 创建coder agent
    coder_agent = create_agent("coder", "coder", [python_repl_tool], "coder")
    
    # 执行agent
    recursion_limit = int(os.getenv("AGENT_RECURSION_LIMIT", "30"))
    result = await coder_agent.ainvoke(
        input={"messages": messages},
        config={"recursion_limit": recursion_limit}
    )
    
    execution_result = result["messages"][-1].content
    current_step.execution_res = execution_result
    
    return Command(
        update={
            "messages": [AIMessage(content=execution_result, name="coder")],
            "current_plan": current_plan
        },
        goto="router"
    )

async def researcher_node(
    state: State, config: RunnableConfig
) -> Command[Literal["router"]]:
    """研究员节点 - 处理研究任务"""
    configurable = Configuration.from_runnable_config(config)
    
    current_plan = state.get("current_plan")
    current_step_index = state.get("current_step_index", 0)
    current_step = current_plan.steps[current_step_index]
    logger.info(f"Researcher node is executing research task. current_step: {current_step}")

    # 构建researcher输入（只使用前一个agent传递的message）
    researcher_input = {
        "messages": [
            HumanMessage(
                content=f"# Current Task\n\n## Title\n{current_step.title}\n\n## Description\n{current_step.description}\n\n## Previous Message\n{state.get('messages', [])[-1].content if state.get('messages') else 'No previous message'}\n\n## Locale\n{state.get('locale', 'en-US')}"
            )
        ],
        "locale": state.get("locale", "en-US"),
        "resources": state.get("resources", [])
    }
    
    messages = apply_prompt_template("researcher", researcher_input, configurable)
    # print(f"research: \n{messages}")
    # 准备研究工具
    tools = [get_web_search_tool(configurable.max_search_results), crawl_tool]
    retriever_tool = get_retriever_tool(state.get("resources", []))
    if retriever_tool:
        tools.insert(0, retriever_tool)
    
    # 处理MCP服务器配置
    mcp_servers = {}
    if configurable.mcp_settings:
        for server_name, server_config in configurable.mcp_settings["servers"].items():
            if (
                server_config.get("enabled_tools")
                and "researcher" in server_config.get("add_to_agents", [])
            ):
                mcp_servers[server_name] = {
                    k: v for k, v in server_config.items()
                    if k in ("transport", "command", "args", "url", "env")
                }
    
    # 创建并执行agent
    if mcp_servers:
        async with MultiServerMCPClient_wFileUpload(mcp_servers, state) as client:
            loaded_tools = tools[:]
            for tool in client.get_tools():
                loaded_tools.append(tool)
            agent = create_agent("researcher", "researcher", loaded_tools, "researcher")
    else:
        agent = create_agent("researcher", "researcher", tools, "researcher")
    
    recursion_limit = int(os.getenv("AGENT_RECURSION_LIMIT", "25"))
    result = await agent.ainvoke(
        input={"messages": messages}, 
        config={"recursion_limit": recursion_limit}
    )
    
    execution_result = result["messages"][-1].content
    current_step.execution_res = execution_result
    
    return Command(
        update={
            "messages": [AIMessage(content=execution_result, name="researcher")],
            "current_plan": current_plan
        },
        goto="router"
    )

def create_message_with_base64_image(text: str, image_paths: str) -> HumanMessage:
    """使用base64编码传递图像, 都转为jpg再转为base64传输"""

    # image_paths: path1,path2,path3
    image_paths_list = image_paths.split(",")
    base64_image_list = []
    for image_path in image_paths_list:
        with Image.open(image_path) as img:
            # 转换为RGB模式（去除透明通道）
            if img.mode in ('RGBA', 'LA', 'P'):
                img = img.convert('RGB')
            
            # 保存为JPEG格式到内存
            buffer = io.BytesIO()
            img.save(buffer, format='JPEG', quality=85)
            buffer.seek(0)
            # 编码为base64
            base64_image = base64.b64encode(buffer.getvalue()).decode('utf-8')
            base64_image_list.append(base64_image)

    image_messages = [
        {
            "type": "image_url",
            "image_url": {
                "url": f"data:image/jpeg;base64,{i}"
            }
        }
        for i in base64_image_list
    ]
    # 创建多模态content
    content = [
        {
            "type": "text",
            "text": text
        }
    ]
    content.extend(image_messages)
    
    return HumanMessage(content=content)

async def reader_node(
    state: State, config: RunnableConfig
) -> Command[Literal["router"]]:
    """读取器节点 - 处理文档读取任务"""
    
    configurable = Configuration.from_runnable_config(config)
    
    current_plan = state.get("current_plan")
    current_step_index = state.get("current_step_index", 0)
    current_step = current_plan.steps[current_step_index]
    logger.info(f"Reader node is reading image. current_step: {current_step}")
    # 构建reader输入（只使用前一个agent传递的message）
    reader_input = {
        "messages": [create_message_with_base64_image(
                text=f"# Current Task\n\n## Title\n{current_step.title}\n\n## Description\n{current_step.description}\n\n## Previous Message\n{state.get('messages', [])[-1].content if state.get('messages') else 'No previous message'}\n\n## Locale\n{state.get('locale', 'en-US')}", 
                image_paths=state.get("file_info", "")
            )],
        "locale": state.get("locale", "en-US"),
        "resources": state.get("resources", [])
    }
    
    messages = apply_prompt_template("reader", reader_input, configurable)
    # print(f"reader: \n{messages}")
    # 使用vision模型处理文档和图片
    llm = get_llm_by_type(AGENT_LLM_MAP["reader"])
    response = llm.invoke(messages)
    
    current_step.execution_res = response.content
    
    return Command(
        update={
            "messages": [AIMessage(content=response.content, name="reader")],
            "current_plan": current_plan
        },
        goto="router"
    )

def thinker_node(
    state: State, config: RunnableConfig
) -> Command[Literal["router"]]:
    """思考器节点 - 使用推理模型，能够深度思考问题"""
    
    configurable = Configuration.from_runnable_config(config)
    
    current_plan = state.get("current_plan")
    current_step_index = state.get("current_step_index", 0)
    current_step = current_plan.steps[current_step_index]
    logger.info(f"Thinker node is processing complex reasoning task. current_step: {current_step}")

    # 构建thinker输入（只使用前一个agent传递的message）
    thinker_input = {
        "messages": [
            HumanMessage(
                content=f"# Current Task\n\n## Title\n{current_step.title}\n\n## Description\n{current_step.description}\n\n## Previous Message\n{state.get('messages', [])[-1].content if state.get('messages') else 'No previous message'}\n\n## Locale\n{state.get('locale', 'en-US')}"
            )
        ],
        "locale": state.get("locale", "en-US"),
        "resources": state.get("resources", [])
    }
    
    messages = apply_prompt_template("thinker", thinker_input, configurable)
    # print(f"thinker: \n{messages}")
    # 使用推理模型
    response = get_llm_by_type(AGENT_LLM_MAP["thinker"]).invoke(messages)
    
    current_step.execution_res = response.content
    # logger.info(f"Thinker response: {response.content}")
    return Command(
        update={
            "messages": [AIMessage(content=response.content, name="thinker")],
            "current_plan": current_plan
        },
        goto="router"
    )

def reporter_node(state: State, config: RunnableConfig) -> dict:
    """报告生成节点 - 综合所有步骤结果生成最终报告"""
    logger.info("Reporter node is generating final report.")
    configurable = Configuration.from_runnable_config(config)
    
    current_plan = state.get("current_plan")
    current_step_index = state.get("current_step_index", 0)
    current_step = current_plan.steps[current_step_index]

    logger.info(f"Reporter node is generating final report. current_step_index: {current_step_index}")
    # 构建综合报告输入
    comprehensive_context = f"""
# Task Overview

## Original Task
{current_plan.title if current_plan else "Unknown Task"}

## Task Description
{current_plan.thought if current_plan else "No description available"}

# Step Execution Results

"""
    
    # 添加所有步骤的执行结果
    if current_plan and current_plan.steps:
        for i, step in enumerate(current_plan.steps, 1):
            comprehensive_context += f"## Step {i}: {step.title}\n\n"
            comprehensive_context += f"**Description:** {step.description}\n\n"
            comprehensive_context += f"**Result:** {step.execution_res or 'Not executed'}\n\n"
            comprehensive_context += "---\n\n"
    
    # 构建reporter输入
    reporter_input = {
        "messages": [
            HumanMessage(
                content=f"{comprehensive_context}\n\n# Reporter Task\n\nPlease create a comprehensive final report that synthesizes all the above information. The report should be well-structured, clear, and actionable."
            )
        ],
        "locale": state.get("locale", "en-US"),
    }
    
    # 应用reporter模板
    invoke_messages = apply_prompt_template("reporter", reporter_input, configurable)
    # print(f"reporter: \n{invoke_messages}")
    # 生成最终报告
    response = get_llm_by_type(AGENT_LLM_MAP["reporter"]).invoke(invoke_messages)
    logger.info("Final report generated successfully.")
    logger.info(response.content)
    # print(response.content)
    return {"final_report": response.content}