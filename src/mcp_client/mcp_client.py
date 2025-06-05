import asyncio
from langchain_mcp_adapters.client import MultiServerMCPClient
from mcp import ClientSession
from langchain_mcp_adapters.tools import load_mcp_tools
from langchain_core.tools import BaseTool
from langchain_mcp_adapters.tools import NonTextContent
from src.graph.types import State, Resource
from typing import Any
import os.path as osp
import uuid
import json
import re
import base64
import filetype
import logging
import traceback
logger = logging.getLogger(__name__)

def file_to_data_uri(file_path):
    """读取一个文件并将其转换成base64编码利用filetype库,在前面加上mime信息,返回data:uri格式"""
    with open(file_path, 'rb') as file:
        file_content = file.read()
    
    kind = filetype.guess(file_content)
    if kind is None:
        mime_type = 'application/octet-stream'
    else:
        mime_type = kind.mime
    base64_content = base64.b64encode(file_content).decode('utf-8')
    mime_base64 = f"data:{mime_type};base64,{base64_content}"
    return mime_base64


def base64_to_bytes(base64_str: str) -> bytes:
    """
    将Base64编码的字符串（可能带有data:前缀）转换为bytes对象
    参数: base64_str: Base64编码的字符串，可能带有类似"data:image/png;base64,"的前缀
    返回: 解码后的bytes对象
    """
    # 检查是否包含"base64,"前缀，并提取Base64部分
    if "base64," in base64_str:
        # 使用 split 提取 base64, 后面的部分
        try:
            base64_data = base64_str.split("base64,")[1]
        except IndexError:
            raise ValueError("无效的Base64 data URI格式")
    else:
        base64_data = base64_str
    
    # 移除可能的空白字符（如换行符、空格）
    base64_data = base64_data.strip()
    
    try:
        return base64.b64decode(base64_data)
    except base64.binascii.Error as e:
        raise ValueError("无效的Base64编码") from e



class MultiServerMCPClient_wFileUpload(MultiServerMCPClient):
    def __init__(self, connections, state: State):
        super().__init__(connections)
        self.state = state

    async def _initialize_session_and_load_tools(
        self, server_name: str, session: ClientSession
    ) -> None:
        """Initialize a session and load tools from it.

        Args:
            server_name: Name to identify this server connection
            session: The ClientSession to initialize
        """
        # Initialize the session
        await session.initialize()
        self.sessions[server_name] = session

        # Load tools from this server
        print("++mcp add fileload")
        server_tools = await load_mcp_tools(session)
        server_tools = [self._add_file_upload_in_tool(tool) for tool in server_tools]
        self.server_name_to_tools[server_name] = server_tools
    
    def _add_file_upload_in_tool(self, tool: BaseTool):
        print(tool.name)
        delegation_tools = ['call_researcher_agent', 'call_reader_agent', 'call_coder_agent']
        if tool.name in delegation_tools:
            print(f"{tool.name} 没包装")
            return tool  # 直接返回，不包装
        
        old_coroutine = tool.coroutine

        def _replace_base64_with_path(out):
            # todo: 有潜在bug，如果模型输出内容就是有base64编码的内容，则会被替换为文件路径
            # 需要针对特定返回格式的json string进行处理
            # todo: 如果返回内容中有两个相同的文件？
            if isinstance(out, str):
                # 用正则表达式匹配out中的base64编码的uri，并替换为文件路径
                pattern = r'data:[^;]+;base64,[A-Za-z0-9+/=]+'
                matches = re.findall(pattern, out)
                for match in matches:
                    b64_string = match
                    # 使用filetype库猜测文件类型，并使用uuid生成文件名
                    data_bytes = base64_to_bytes(b64_string)
                    file_name = f"{uuid.uuid4().hex[:8]}.{filetype.guess(data_bytes).extension}"
                    file_path = osp.join(self.state['session_dir'], file_name)
                    with open(file_path, 'wb') as file:
                        file.write(data_bytes)
                    self.state['resources'].append(Resource(
                        uri=file_path,
                        title=file_path,
                        description=file_path))
                    out = out.replace(b64_string, file_path)
                return out
            elif isinstance(out, dict):
                for k, v in out.items():
                    out[k] = _replace_base64_with_path(v)
                return out
            elif isinstance(out, list):
                return [_replace_base64_with_path(item) for item in out]
            elif isinstance(out, tuple):
                return tuple([_replace_base64_with_path(item) for item in out])
            elif out is None:
                return out
            else:
                logger.error(f"recursive_replace_uri_with_file error, {type(out)}")
                raise ValueError(f"recursive_replace_uri_with_file error, {type(out)}")
        
        async def wrapped_call_tool(
            **arguments: dict[str, Any],
        ) -> tuple[str | list[str], list[NonTextContent] | None]:
            for k in list(arguments.keys()):
                if 'uri' == k.lower() and osp.exists(arguments[k]):
                    arguments[k] = file_to_data_uri(arguments[k])
            out = await old_coroutine(**arguments)
            try:
                out = _replace_base64_with_path(out)
            except Exception as e:
                logger.error(f"recursive_replace_uri_with_file error, {e}")
                logger.error(traceback.format_exc())
                raise e
            logger.info(f"wrapped_call_tool out: {out}")
            return out
        
        tool.coroutine = wrapped_call_tool
        return tool

async def test():
    from langchain_openai import ChatOpenAI
    from langgraph.prebuilt import create_react_agent

    llm = ChatOpenAI(base_url="https://ark.cn-beijing.volces.com/api/v3",
                 model="doubao-1-5-pro-32k-250115",
                 api_key="a4be7a02-ff35-4f53-af52-25ed6e1b3c3b")
    
    async with MultiServerMCPClient_wFileUpload( {
            "doc_parse": {
                "url": "http://0.0.0.0:8010/sse",
                "transport": "sse",
            }
        }
    ) as client:
            tools = client.get_tools()
            agent = create_react_agent(
                name="doubao",
                model=llm,
                tools=tools,
            )
            response = await agent.ainvoke({"messages": "看文件中2025-04-01的加班时长: /mnt/afs/yaotiankuo/agents/deer-dev/tests/加班清单.xlsx? use doc parse function"})
    print(response)

if __name__ == "__main__":
     
    asyncio.run(test())
