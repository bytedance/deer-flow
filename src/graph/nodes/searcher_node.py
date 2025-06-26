from .base_node import BaseNode
from src.config.agents import AgentConfiguration
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import Command
from typing import Literal, Dict, Any, List, Tuple
import os
import re
import json
import uuid
import aiohttp
from src.config.configuration import Configuration
from src.prompts.template import apply_prompt_template
from src.llms.llm import get_llm_by_type

class SearcherNode(BaseNode):
    def __init__(self, toolmanager):
        super().__init__("searcher", AgentConfiguration.NODE_CONFIGS["searcher"], toolmanager)
        self.call_supervisor = {
            "name": "display_result",
            "description": "This function used to display your result to Supervisor.",
            "parameters": {
                "type": "object",
                "properties": {
                    "queries": {
                        "type": "array",
                        "items": {
                            "type": "string"
                        },
                        "description": "The list of search queries that were used to gather the information being summarized."
                    },
                    "result": {
                        "type": "string",
                        "description": "A comprehensive markdown-formatted summary of the search results, including key findings, structured information, and relevant details organized in a readable format."
                    }
                },
                "required": [
                    "queries",
                    "result"
                ]
            }
        }

        self.webSearchTool = {
            "name": "web_search",
            "description": "This function acts as a search engine to retrieve a wide range of information from the web. It is capable of processing queries related to various topics and returning relevant results.This search tool's performance is limited and it only returns summary information. Therefore, it's necessary to narrow down the search scope as much as possible. For example, avoid searching for specific time periods. Note: Except for proper nouns, abbreviations, and terms, it is recommended to use Chinese for search keywords to obtain better search results.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query used to retrieve information from the internet. Rewrite and optimize the query based on conversation history for best search quality.The keywords should not exceed four."
                    }
                },
                "required": [
                    "query"
                ]
            }
        }

    async def execute(self, state: Dict[str, Any], config: RunnableConfig) -> Command[Literal["supervisor"]]:
        
        configurable = Configuration.from_runnable_config(config)
        supervisor_iterate_time = state["supervisor_iterate_time"]

        messages = apply_prompt_template(self.name, state, configurable)
        # 准备委托工具
        tools = [self.call_supervisor, self.webSearchTool]
        self.log_input_message(messages)
        llm = get_llm_by_type( self.config.llm_type).bind_tools(tools)
        response = llm.invoke(messages)

        node_res_summary = ""

        max_toolcall_iterate_times = configurable.max_toolcall_iterate_times
        iterate_times = state.get("tool_call_iterate_time", 0)
        if hasattr(response, 'tool_calls') and response.tool_calls \
            and iterate_times < max_toolcall_iterate_times:
            iterate_times += 1
            self.log_tool_call(response, iterate_times)

            for tool_call in response.tool_calls:
                # 返回给supervisor
                if tool_call["name"] == "display_result":
                    node_res_summary += f"\n{tool_call['args']['result']}"
                    return Command(
                        update={
                            "messages": [HumanMessage(content=node_res_summary, name="writer")],
                            "supervisor_iterate_time": supervisor_iterate_time + 1,
                            "tool_call_iterate_time" : 0
                        },
                        goto="supervisor"
                    )
                elif tool_call["name"] == "web_search":
                    from src.tools.search import get_web_search_tool, filter_garbled_text

                    background_summary = "相关背景信息收集:\n"
                    search_engine = get_web_search_tool(configurable.max_search_results)
                    try:
                        
                        searched_content = search_engine.invoke(tool_call["args"])
                        for elem in searched_content:
                            background_summary += f"- 题目：{ elem["title"]}\n- 内容：{elem["content"]}\n"
                        
                    except Exception as e:
                        self.log_execution(f"Background research failed: {e}")
                    background_summary = filter_garbled_text(background_summary)
                    return Command(
                        update={
                            "messages": [ToolMessage(content=background_summary, tool_call_id=tool_call["id"])],
                            "tool_call_iterate_time" : iterate_times
                        },
                        goto="searcher"
                    )
                else:
                    pass
        return Command(
            update={
                "messages": response,
                "supervisor_iterate_time": supervisor_iterate_time + 1
            },
            goto="supervisor"
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
                    self.log_execution_warning(f"Failed to download {url}: {e}")
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