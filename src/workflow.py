# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import asyncio
import logging
import os
import os.path as osp
import datetime
from src.graph import build_graph
from src.utils.file_descriptors import file2resource, resources2user_input
import uuid
import shutil
# Configure logging
logging.basicConfig(
    level=logging.INFO,  # Default level is INFO
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)


def enable_debug_logging():
    """Enable debug level logging for more detailed execution information."""
    logging.getLogger("src").setLevel(logging.DEBUG)


logger = logging.getLogger(__name__)

# Create the graph
graph = build_graph()


def get_init_state(
        user_input: str | list[dict], 
        enable_background_investigation: bool) -> str | list[dict]:
    """
    1. 对用户输入进行预处理以初始化状态。
    2. 创建会话目录
    3. 将用户输入文件转换为资源列表。
    参数：
        user_input：用户的查询或请求，类型为字符串或字典列表
        enable_background_investigation：若为 True，则在规划前进行网络搜索以增强上下文信息
    返回值：
        经过预处理的用户输入
        用户输入可以是字符串，也可以是字典列表，每个字典包含一个 'type' 键以及 'text' 或 'file_url' 键。
    """
    
    session_id = datetime.datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + str(uuid.uuid4().hex[:8])
    session_dir = osp.join(os.environ.get('SESSION_DIR', './sessions'), session_id)
    if not osp.exists(session_dir):
        os.makedirs(session_dir)

    if isinstance(user_input, str):
        user_input_text = user_input
        resources = []
    elif isinstance(user_input, list):
        if len(user_input) == 0:
            raise ValueError("User input cannot be empty")
        
        user_input_text = '\n\n'.join([f['text'] for f in user_input if f['type'] == 'text'])
        
        for content in user_input:
            # copy file from file_url and save to session_dir
            if content['type'] == 'file_url':
                file_url = content['file_url']['url']
                file_name = osp.basename(file_url)
                file_path = osp.join(session_dir, file_name)
                if osp.exists(file_path):
                    # 在文件名stem上增加一个后缀, ...
                    file_name_stem = osp.splitext(file_name)[0]
                    file_name = file_name_stem + '_' + str(uuid.uuid4().hex[:8]) + osp.splitext(file_name)[1]
                    file_path = osp.join(session_dir, file_name)
                shutil.copy(file_url, file_path)
                content['file_url']['url'] = file_path
                    
        files = [f for f in user_input if f['type'] == 'file_url']
        resources = [file2resource(f['file_url']['url']) for f in files]
        
        for res_i, resource in enumerate(resources):
            resources[res_i]['resource_id'] = res_i
        user_input_text = user_input_text + "\n\n" + resources2user_input(resources)

    else:
        raise ValueError("Invalid user input type")
    
    return {
        "messages": [{"role": "user", "content": user_input_text}],
        "resources": resources,
        "auto_accepted_plan": True,
        "enable_background_investigation": enable_background_investigation,
        "session_id": session_id,
        "session_dir": session_dir,
    }


async def run_agent_workflow_async(
    user_input: str | list[dict],
    debug: bool = False,
    max_plan_iterations: int = 1,
    max_step_num: int = 3,
    enable_background_investigation: bool = True,
):
    """Run the agent workflow asynchronously with the given user input.

    Args:
        user_input: The user's query or request
        debug: If True, enables debug level logging
        max_plan_iterations: Maximum number of plan iterations
        max_step_num: Maximum number of steps in a plan
        enable_background_investigation: If True, performs web search before planning to enhance context

    Returns:
        The final state after the workflow completes
    """
    if not user_input:
        raise ValueError("Input could not be empty")

    if debug:
        enable_debug_logging()

    logger.info(f"Starting async workflow with user input: {user_input}")
    initial_state = get_init_state(user_input, enable_background_investigation)


    config = {
        "configurable": {
            "thread_id": "default",
            "max_plan_iterations": max_plan_iterations,
            "max_step_num": max_step_num,
            "max_search_results": 5,
            "mcp_settings": {
                "servers": {
                    "doc_parser": {
                        "transport": "sse",
                        "url": "http://127.0.0.1:8010/sse",
                        "enabled_tools": ["parse_doc"],
                        "add_to_agents": ["analyzer"]
                    }
                }
            },
        },
        "recursion_limit": 100,
    }
    last_message_cnt = 0
    async for s in graph.astream(
        input=initial_state, config=config, stream_mode="values"
    ):
        try:
            if isinstance(s, dict) and "messages" in s:
                if len(s["messages"]) <= last_message_cnt:
                    continue
                last_message_cnt = len(s["messages"])
                message = s["messages"][-1]
                if isinstance(message, tuple):
                    print(message)
                else:
                    message.pretty_print()
            else:
                # For any other output format
                print(f"Output: {s}")
        except Exception as e:
            logger.error(f"Error processing stream output: {e}")
            print(f"Error processing output: {str(e)}")

    logger.info("Async workflow completed successfully")


if __name__ == "__main__":
    print(graph.get_graph(xray=True).draw_mermaid())
