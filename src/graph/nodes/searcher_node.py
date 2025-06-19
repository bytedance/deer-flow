# nodes/searcher_node.py
"""研究员节点"""

from .base_node import BaseNode
from src.config.agents import AgentConfiguration
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import Command
from typing import Literal, Dict, Any, List, Tuple
import os
import re
import json
import uuid
import aiohttp
import logging

logger = logging.getLogger(__name__)

class SearcherNode(BaseNode):
    """研究员节点 - 处理研究任务"""
    
    def __init__(self, toolmanager):
        super().__init__("searcher", AgentConfiguration.NODE_CONFIGS["searcher"], toolmanager)
    
    async def execute(self, state: Dict[str, Any], config: RunnableConfig) -> Command[Literal["supervisor"]]:
        """执行研究逻辑"""
        self.log_execution("Starting research task")
        
        # 导入必要的模块
        from src.config.configuration import Configuration
        from src.prompts.template import apply_prompt_template
        from src.agents import create_agent
        from src.tools import get_web_search_tool, get_retriever_tool
        from src.mcp_client.mcp_client import MultiServerMCPClient_wFileUpload
        from src.graph.types import Resource
        
        try:
            configurable = Configuration.from_runnable_config(config)
            
            # 推进到下一步
            current_step_index = self.get_next_step_index(state)
            current_plan = state.get("current_plan")
            
            if not current_plan or current_step_index >= len(current_plan.steps):
                return Command(goto="reporter")
            
            current_step = current_plan.steps[current_step_index]
            self.log_execution(f"Working on step {current_step_index}: {current_step.title}")
            
            # 构建searcher输入
            searcher_input = {
                "messages": [
                    HumanMessage(
                        content=f"""# Current Task

## Title
{current_step.title}

## Description
{current_step.description}

## Previous Message
{state.get('messages', [])[-1].content if state.get('messages') else 'No previous message'}

## Locale
{state.get('locale', 'en-US')}"""
                    )
                ],
                "locale": state.get("locale", "en-US"),
                "resources": state.get("resources", [])
            }
            
            messages = apply_prompt_template("searcher", searcher_input, configurable)
            
            # 准备研究工具
            tools = [get_web_search_tool(configurable.max_search_results)]
            
            # 添加检索工具
            retriever_tool = get_retriever_tool(state.get("resources", []))
            if retriever_tool:
                tools.insert(0, retriever_tool)
            
            # 处理MCP服务器配置
            mcp_servers = {}
            if configurable.mcp_settings:
                for server_name, server_config in configurable.mcp_settings["servers"].items():
                    if (
                        server_config.get("enabled_tools")
                        and "searcher" in server_config.get("add_to_agents", [])
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
                    agent = create_agent("searcher", "searcher", loaded_tools, "searcher")
                    
                    recursion_limit = int(os.getenv("AGENT_RECURSION_LIMIT", "25"))
                    result = await agent.ainvoke(
                        input={"messages": messages}, 
                        config={"recursion_limit": recursion_limit}
                    )
            else:
                agent = create_agent("searcher", "searcher", tools, "searcher")
                recursion_limit = int(os.getenv("AGENT_RECURSION_LIMIT", "25"))
                result = await agent.ainvoke(
                    input={"messages": messages}, 
                    config={"recursion_limit": recursion_limit}
                )
            
            research_content = result["messages"][-1].content
            self.log_execution(f"Research completed. Content length: {len(research_content)}")
            
            # 处理图像下载
            need_image = state.get("need_image", "true")
            if need_image.lower() == "true":
                research_content = await self._process_images(research_content, state)
            
            execution_result = research_content
            current_step.execution_res = execution_result
            
            # 确定下一个节点
            next_node = self.determine_next_node(state)
            
            return Command(
                update={
                    "messages": [AIMessage(content=execution_result, name="searcher")],
                    "current_plan": current_plan,
                    "current_step_index": current_step_index
                },
                goto=next_node
            )
            
        except Exception as e:
            self.log_execution(f"Error in searcher execution: {e}")
            return Command(
                update={
                    "messages": [AIMessage(content=f"Error in research: {str(e)}", name="searcher")]
                },
                goto="reporter"
            )
    
    def _extract_markdown_images(self, text: str) -> List[Tuple[str, str]]:
        """提取 Markdown 格式图像的描述和 URL"""
        if not text:
            return []
        
        # 匹配 ![description](url) 格式
        pattern = r'!\[([^\]]*)\]\(([^)]+)\)'
        matches = re.findall(pattern, text)
        
        # 过滤并返回有效的 HTTP(S) URL 和对应的描述
        result = []
        for description, url in matches:
            url = url.strip()
            if url.startswith(('http://', 'https://')):
                result.append((description, url))
        
        return result
    
    async def _download_images_batch(
        self, 
        image_infos: List[Tuple[str, str]], 
        session_dir: str,
        max_images: int = 5,
        timeout: int = 10
    ) -> List[Dict[str, Any]]:
        """简化的批量下载"""
        
        os.makedirs(session_dir, exist_ok=True)
        downloaded_images = []
        
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as session:
            for i, (image_desc, url) in enumerate(image_infos[:max_images]):
                try:
                    async with session.get(url) as response:
                        if response.status == 200:
                            content = await response.read()
                            
                            # 简单的文件扩展名检测
                            if 'image/png' in response.headers.get('Content-Type', ''):
                                ext = '.png'
                            elif 'image/gif' in response.headers.get('Content-Type', ''):
                                ext = '.gif'
                            else:
                                ext = '.jpg'
                            
                            filename = f"research_img_{i+1}_{uuid.uuid4().hex[:8]}{ext}"
                            local_path = os.path.join(session_dir, filename)
                            
                            with open(local_path, 'wb') as f:
                                f.write(content)
                            
                            downloaded_images.append({
                                'original_url': url,
                                'local_path': local_path,
                                'image_desc': image_desc,
                                'mime_type': response.headers.get('Content-Type', 'image/jpeg'),
                                'size': len(content)
                            })
                            
                except Exception as e:
                    logger.warning(f"Failed to download {url}: {e}")
                    continue
        
        return downloaded_images
    
    async def _process_images(self, research_content: str, state: Dict[str, Any]) -> str:
        """处理图像下载和资源添加"""
        from src.graph.types import Resource
        
        # 提取图像URL
        image_listtuple = self._extract_markdown_images(research_content)
        
        if image_listtuple:
            self.log_execution(f"Found {len(image_listtuple)} images, downloading...")
            
            downloaded_images = await self._download_images_batch(
                image_listtuple[:5],  # 限制最多5张图
                session_dir=state.get('session_dir', './sessions/default'),
                max_images=5
            )
            
            new_images_info = []
            # 添加到resources
            for image_info in downloaded_images:
                new_images_info.append({
                    'uri': image_info['local_path'],
                    'title': image_info['image_desc'],
                    'description': image_info['image_desc'],
                })
                
                # 添加到state的resources中
                if 'resources' not in state:
                    state['resources'] = []
                    
                state['resources'].append(
                    Resource(
                        uri=image_info['local_path'],
                        title=image_info['image_desc'],
                        description=image_info['image_desc'],
                    )
                )
            
            self.log_execution(f"Downloaded {len(downloaded_images)} images")
            
            # 将图像信息添加到研究结果中
            research_content += f"\n##related images\n{json.dumps(new_images_info, indent=2, ensure_ascii=False)}"
        
        return research_content