"""
Google Drive 与 LangGraph 集成示例
展示如何将 Google Drive 操作集成到 LangGraph 工作流中
"""
from typing import TypedDict, Annotated, List, Optional
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode
from langchain_core.tools import tool
import os
import sys

# 添加脚本目录到路径
script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
scripts_path = os.path.join(script_dir, 'scripts')
sys.path.insert(0, scripts_path)

from utils import get_credentials, build_drive_service

# ========== 状态定义 ==========

class DriveState(TypedDict):
    """Google Drive 操作状态"""
    query: str
    operation: str  # 'search', 'list', 'read', 'create'
    file_id: Optional[str]
    file_name: Optional[str]
    results: List[dict]
    content: Optional[str]
    error: Optional[str]

# ========== Google Drive 工具定义 ==========

@tool
def search_drive(query: str, limit: int = 10) -> List[dict]:
    """
    搜索 Google Drive 文件
    
    Args:
        query: 搜索关键词
        limit: 结果数量限制
    
    Returns:
        文件信息列表
    """
    creds = get_credentials()
    service = build_drive_service(creds)
    
    from googleapiclient.errors import HttpError
    
    try:
        results = service.files().list(
            q=f"fullText contains '{query}' and trashed = false",
            pageSize=limit,
            fields="files(id, name, mimeType, modifiedTime)"
        ).execute()
        
        files = results.get('files', [])
        return files
    except HttpError as e:
        return [{"error": str(e)}]

@tool
def list_drive_files(folder_id: str = None, limit: int = 20) -> List[dict]:
    """
    列出 Google Drive 文件
    
    Args:
        folder_id: 文件夹 ID（可选，None 表示根目录）
        limit: 结果数量限制
    
    Returns:
        文件信息列表
    """
    creds = get_credentials()
    service = build_drive_service(creds)
    
    query = "trashed = false"
    if folder_id:
        query += f" and '{folder_id}' in parents"
    else:
        query += " and 'root' in parents"
    
    results = service.files().list(
        q=query,
        pageSize=limit,
        orderBy="modifiedTime desc",
        fields="files(id, name, mimeType, modifiedTime)"
    ).execute()
    
    return results.get('files', [])

@tool
def read_drive_file(file_id: str) -> str:
    """
    读取 Google Drive 文件内容
    
    Args:
        file_id: 文件 ID
    
    Returns:
        文件内容
    """
    creds = get_credentials()
    service = build_drive_service(creds)
    
    import io
    from googleapiclient.http import MediaIoBaseDownload
    
    # 获取文件信息
    file = service.files().get(fileId=file_id, fields='name, mimeType').execute()
    mime_type = file.get('mimeType', '')
    
    if 'vnd.google-apps' in mime_type:
        # Google Workspace 文件需要导出
        if 'document' in mime_type:
            export_mime = 'text/plain'
        elif 'spreadsheet' in mime_type:
            export_mime = 'text/csv'
        else:
            export_mime = 'text/plain'
        
        request = service.files().export_media(fileId=file_id, mimeType=export_mime)
    else:
        request = service.files().get_media(fileId=file_id)
    
    file_content = io.BytesIO()
    downloader = MediaIoBaseDownload(file_content, request)
    
    done = False
    while done is False:
        status, done = downloader.next_chunk()
    
    return file_content.getvalue().decode('utf-8', errors='ignore')

# ========== 节点定义 ==========

def decide_operation(state: DriveState) -> DriveState:
    """决定执行哪种操作"""
    operation = state.get('operation', 'list')
    
    if operation == 'search' and not state.get('query'):
        return {"error": "搜索操作需要提供查询关键词"}
    
    if operation in ['read'] and not state.get('file_id'):
        return {"error": "读取操作需要提供文件 ID"}
    
    return state

def execute_operation(state: DriveState) -> DriveState:
    """执行 Google Drive 操作"""
    operation = state.get('operation', 'list')
    
    try:
        if operation == 'search':
            results = search_drive.invoke({"query": state['query'], "limit": 10})
            return {"results": results}
        
        elif operation == 'list':
            results = list_drive_files.invoke({"folder_id": state.get('file_id'), "limit": 20})
            return {"results": results}
        
        elif operation == 'read':
            content = read_drive_file.invoke({"file_id": state['file_id']})
            return {"content": content, "results": [{"file_id": state['file_id']}]}
        
        else:
            return {"error": f"未知操作: {operation}"}
    
    except Exception as e:
        return {"error": str(e)}

def format_results(state: DriveState) -> DriveState:
    """格式化结果"""
    if state.get('error'):
        return state
    
    results = state.get('results', [])
    formatted = []
    
    for file in results:
        if 'error' in file:
            formatted.append(f"错误: {file['error']}")
        else:
            formatted.append(
                f"- {file.get('name', 'Unknown')} "
                f"(ID: {file.get('id', 'N/A')})"
            )
    
    return {"results": results, "formatted_output": "\n".join(formatted)}

# ========== 构建图 ==========

def build_drive_graph():
    """构建 Google Drive 操作图"""
    workflow = StateGraph(DriveState)
    
    # 添加节点
    workflow.add_node("decide", decide_operation)
    workflow.add_node("execute", execute_operation)
    workflow.add_node("format", format_results)
    
    # 设置边
    workflow.set_entry_point("decide")
    workflow.add_edge("decide", "execute")
    workflow.add_edge("execute", "format")
    workflow.add_edge("format", END)
    
    return workflow.compile()

# ========== 使用示例 ==========

if __name__ == "__main__":
    # 检查是否已认证
    if not os.path.exists('token.json'):
        print("请先运行 `python scripts/auth_setup.py` 完成认证")
        sys.exit(1)
    
    # 构建图
    graph = build_drive_graph()
    
    print("=== Google Drive LangGraph 集成示例 ===\n")
    
    # 示例 1: 列出文件
    print("示例 1: 列出最近修改的文件")
    print("-" * 50)
    result = graph.invoke({
        "operation": "list"
    })
    
    if result.get('error'):
        print(f"错误: {result['error']}")
    else:
        print(result.get('formatted_output', '无结果'))
    print()
    
    # 示例 2: 搜索文件
    print("示例 2: 搜索文件 (关键词: '报告')")
    print("-" * 50)
    result = graph.invoke({
        "operation": "search",
        "query": "报告"
    })
    
    if result.get('error'):
        print(f"错误: {result['error']}")
    else:
        print(result.get('formatted_output', '无结果'))
    print()
    
    print("✅ 示例完成！")
