# nodes/reader_node.py
"""阅读器节点"""

from .base_node import BaseNode
from src.config.agents import AgentConfiguration
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import Command
from typing import Literal, Dict, Any
import base64
import io
import os
import uuid
import logging
from PIL import Image

logger = logging.getLogger(__name__)

class ReaderNode(BaseNode):
    """阅读器节点 - 处理图像理解任务"""
    
    def __init__(self, toolmanager):
        super().__init__("reader", AgentConfiguration.NODE_CONFIGS["reader"], toolmanager)
    
    async def execute(self, state: Dict[str, Any], config: RunnableConfig) -> Command[Literal["supervisor"]]:
        """执行阅读器逻辑"""
        self.log_execution("Starting image reading task")
        
        # 导入必要的模块
        from src.config.configuration import Configuration
        from src.prompts.template import apply_prompt_template
        from src.llms.llm import get_llm_by_type
        from src.tools.image_rotate import rotate_image
        from src.graph.types import Resource
        from tools.delegation_tools import call_rotate_tool
        
        try:
            configurable = Configuration.from_runnable_config(config)
            
            # 推进到下一步
            current_step_index = self.get_next_step_index(state)
            current_plan = state.get("current_plan")
            
            if not current_plan or current_step_index >= len(current_plan.steps):
                return Command(goto="reporter")
            
            current_step = current_plan.steps[current_step_index]
            self.log_execution(f"Working on step {current_step_index}: {current_step.title}")
            
            # 获取图像路径
            session_dir = state.get("session_dir", "")
            image_paths = state.get("file_info", "")
            
            if not image_paths:
                self.log_execution("No image paths provided")
                return Command(goto="reporter")
            
            # 构建reader输入
            reader_input = {
                "messages": [self._create_message_with_base64_image(
                    text=f"""# Current Task

## Title
{current_step.title}

## Description
{current_step.description}

## Previous Message
{state.get('messages', [])[-1].content if state.get('messages') else 'No previous message'}

#Reading Image paths (The order of image paths corresponds to the order in which images are read):
{image_paths}

## Locale
{state.get('locale', 'en-US')}""", 
                    image_paths=image_paths
                )],
                "locale": state.get("locale", "en-US"),
                "resources": state.get("resources", [])
            }
            
            messages = apply_prompt_template("reader", reader_input, configurable)
            
            # 使用vision模型处理文档和图片
            delegation_tools = [call_rotate_tool]
            llm = get_llm_by_type(self.config.llm_type).bind_tools(delegation_tools)
            response = llm.invoke(messages)
            
            self.log_execution(f"Reader initial response received")
            
            # 处理工具调用
            response = await self._handle_tool_calls(
                response, messages, llm, configurable, state, session_dir
            )
            
            current_step.execution_res = response.content
            
            # 确定下一个节点
            next_node = self.determine_next_node(state)
            
            return Command(
                update={
                    "messages": [AIMessage(content=response.content, name="reader")],
                    "current_plan": current_plan,
                    "current_step_index": current_step_index
                },
                goto=next_node
            )
            
        except Exception as e:
            self.log_execution(f"Error in reader execution: {e}")
            return Command(
                update={
                    "messages": [AIMessage(content=f"Error in reading: {str(e)}", name="reader")]
                },
                goto="reporter"
            )
    
    def _create_message_with_base64_image(self, text: str, image_paths: str) -> HumanMessage:
        """使用base64编码传递图像, 都转为jpg再转为base64传输"""
        
        # image_paths: path1,path2,path3
        image_paths_list = image_paths.split(",")
        base64_image_list = []
        
        for image_path in image_paths_list:
            try:
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
            except Exception as e:
                self.log_execution(f"Error processing image {image_path}: {e}")
                continue
        
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
    
    async def _handle_tool_calls(self, response, messages, llm, configurable, state, session_dir):
        """处理工具调用"""
        from src.tools.image_rotate import rotate_image
        from src.graph.types import Resource
        
        max_toolcall_iterate_times = configurable.max_toolcall_iterate_times
        iterate_times = 0
        
        while hasattr(response, 'tool_calls') and response.tool_calls and iterate_times < max_toolcall_iterate_times:
            iterate_times += 1
            self.log_execution(f"Reader tool call iteration: {iterate_times}")
            
            for tool_call in response.tool_calls:
                if tool_call["name"] == "call_rotate_tool":
                    image_path = tool_call["args"]["file_info"]
                    rotate_request = tool_call["args"]["rotate_request"]
                    
                    # 生成新的文件路径
                    base_name = os.path.splitext(os.path.basename(image_path))[0]
                    extension = os.path.splitext(image_path)[1]
                    
                    # 使用UUID确保文件名唯一性
                    unique_id = str(uuid.uuid4())[:8]
                    new_filename = f"{base_name}_rotated_{unique_id}{extension}"
                    new_file_path = os.path.join(session_dir, new_filename)
                    
                    try:
                        # 旋转并保存图像
                        rotation_desc = rotate_image(image_path, new_file_path, rotate_request)
                        
                        # 更新资源列表
                        if 'resources' not in state:
                            state['resources'] = []
                            
                        state['resources'].append(Resource(
                            uri=new_file_path,
                            title=f"{base_name} ({rotation_desc})",
                            description=f"从 {image_path} {rotation_desc}后生成的图像"
                        ))
                        
                        self.log_execution(f"图像已成功{rotation_desc}并保存到: {new_file_path}")
                        
                        current_resources = f"""##Rotated image is: 
uri: {new_file_path}
title: {rotation_desc}
description: 从 {image_path} {rotation_desc}后生成的图像"""
                        
                        # 将结果返回给reader
                        mcp_summary = f"Rotate success! Tools Results:\n{current_resources}"
                        
                        # 第二次LLM调用：基于结果分析
                        messages = messages + [
                            AIMessage(content=response.content, tool_calls=response.tool_calls),
                            ToolMessage(content=mcp_summary, tool_call_id=response.tool_calls[0]["id"]),
                            self._create_message_with_base64_image(
                                text=f"Based on results, Continue to complete your task\n## Locale\n{state.get('locale', 'en-US')}",
                                image_paths=new_file_path
                            )
                        ]
                        
                        response = llm.invoke(messages)
                        
                    except Exception as e:
                        self.log_execution(f"Error rotating image: {e}")
                        # 继续处理，不中断流程
                        break
        
        return response