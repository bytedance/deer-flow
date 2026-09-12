"""
Google Drive 集成 - 通用工具函数
"""
import os
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
import io

# Get the directory of the current script
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(SCRIPT_DIR)

# 如果修改这些范围，删除 token.json 文件
SCOPES = [
    'https://www.googleapis.com/auth/drive',
    'https://www.googleapis.com/auth/drive.file',
    'https://www.googleapis.com/auth/drive.readonly'
]

def get_credentials(credentials_path=None, token_path=None):
    """
    获取或刷新 Google Drive API 凭证
    
    Args:
        credentials_path: OAuth 凭证文件路径 (default: skills/custom/google-drive/credentials.json)
        token_path: 保存的 token 文件路径 (default: skills/custom/google-drive/token.json)
    
    Returns:
        Credentials 对象
    """
    # Use default paths relative to the skill directory if not provided
    if credentials_path is None:
        credentials_path = os.path.join(SKILL_DIR, 'credentials.json')
    if token_path is None:
        # Check environment variable first for token path (for Docker)
        token_path = os.environ.get('GOOGLE_DRIVE_TOKEN_PATH', os.path.join(SKILL_DIR, 'token.json'))
    
    creds = None
    
    # 检查是否有已保存的 token
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)
    
    # 如果没有有效凭证，让用户登录
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(credentials_path):
                raise FileNotFoundError(
                    f"未找到凭证文件: {credentials_path}\n"
                    "请从 Google Cloud Console 下载 OAuth 凭证文件。"
                )
            
            flow = InstalledAppFlow.from_client_secrets_file(
                credentials_path, SCOPES)
            creds = flow.run_local_server(port=0)
        
        # 保存凭证供下次使用
        with open(token_path, 'w') as token:
            token.write(creds.to_json())
    
    return creds

def build_drive_service(creds):
    """
    构建 Google Drive 服务对象
    
    Args:
        creds: Credentials 对象
    
    Returns:
        Drive 服务对象
    """
    return build('drive', 'v3', credentials=creds)

def format_file_size(size_bytes):
    """
    格式化文件大小为人类可读格式
    
    Args:
        size_bytes: 文件大小（字节）
    
    Returns:
        格式化后的文件大小字符串
    """
    if size_bytes is None:
        return "N/A"
    
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024.0
    
    return f"{size_bytes:.2f} PB"

def get_mime_type(file_path):
    """
    根据文件扩展名获取 MIME 类型
    
    Args:
        file_path: 文件路径
    
    Returns:
        MIME 类型字符串
    """
    import mimetypes
    mime_type, _ = mimetypes.guess_type(file_path)
    
    if mime_type is None:
        # 默认 MIME 类型
        ext = os.path.splitext(file_path)[1].lower()
        mime_map = {
            '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            '.pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
            '.txt': 'text/plain',
            '.md': 'text/markdown',
            '.json': 'application/json',
            '.csv': 'text/csv',
        }
        mime_type = mime_map.get(ext, 'application/octet-stream')
    
    return mime_type

def get_google_mime_type(file_type):
    """
    获取 Google Workspace 文档的 MIME 类型
    
    Args:
        file_type: 文档类型 ('doc', 'sheet', 'slide')
    
    Returns:
        Google Workspace MIME 类型
    """
    mime_map = {
        'doc': 'application/vnd.google-apps.document',
        'sheet': 'application/vnd.google-apps.spreadsheet',
        'slide': 'application/vnd.google-apps.presentation',
        'folder': 'application/vnd.google-apps.folder',
    }
    return mime_map.get(file_type, 'application/octet-stream')

def get_export_mime_type(file_type):
    """
    获取导出 Google Workspace 文档时使用的 MIME 类型
    
    Args:
        file_type: 文档类型 ('doc', 'sheet', 'slide')
    
    Returns:
        导出 MIME 类型
    """
    mime_map = {
        'doc': 'text/plain',
        'sheet': 'text/csv',
        'slide': 'text/plain',
    }
    return mime_map.get(file_type, 'text/plain')

def print_file_list(files):
    """
    美观地打印文件列表
    
    Args:
        files: 文件信息列表
    """
    if not files:
        print("未找到文件。")
        return
    
    print(f"{'名称':<50} {'类型':<20} {'大小':<12} {'修改时间':<20}")
    print("-" * 100)
    
    for file in files:
        name = file.get('name', 'N/A')[:47] + '...' if len(file.get('name', '')) > 50 else file.get('name', 'N/A')
        mime_type = file.get('mimeType', 'N/A').split('.')[-1][:18]
        size = format_file_size(file.get('size'))
        modified_time = file.get('modifiedTime', 'N/A')[:10]
        
        print(f"{name:<50} {mime_type:<20} {size:<12} {modified_time:<20}")