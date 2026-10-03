#!/usr/bin/env python3
"""
Google Drive 集成 - 读取文件内容
"""
import os
import sys
import argparse

# 添加脚本目录到路径，以便导入 utils
script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, script_dir)

from utils import (
    get_credentials, build_drive_service, 
    get_export_mime_type, get_mime_type
)
from googleapiclient.http import MediaIoBaseDownload
import io

def get_file_by_name(service, file_name):
    """
    根据文件名搜索文件
    
    Args:
        service: Drive 服务对象
        file_name: 文件名
    
    Returns:
        文件信息或 None
    """
    query = f"name = '{file_name}' and trashed = false"
    
    results = service.files().list(
        q=query,
        pageSize=5,
        fields="files(id, name, mimeType, size)"
    ).execute()
    
    files = results.get('files', [])
    
    if files:
        if len(files) > 1:
            print(f"⚠️ 找到 {len(files)} 个同名文件，使用第一个：")
            for i, f in enumerate(files, 1):
                print(f"  {i}. {f['name']} (ID: {f['id']})")
            print()
        return files[0]
    
    return None

def read_google_workspace_file(service, file_id, mime_type):
    """
    读取 Google Workspace 文档内容（Docs, Sheets, Slides）
    
    Args:
        service: Drive 服务对象
        file_id: 文件 ID
        mime_type: 文件 MIME 类型
    
    Returns:
        文件内容字符串
    """
    # 确定导出格式
    if 'document' in mime_type:
        export_mime = 'text/plain'
    elif 'spreadsheet' in mime_type:
        export_mime = 'text/csv'
    elif 'presentation' in mime_type:
        export_mime = 'text/plain'
    else:
        export_mime = 'text/plain'
    
    # 导出文件
    request = service.files().export_media(fileId=file_id, mimeType=export_mime)
    file_content = io.BytesIO()
    downloader = MediaIoBaseDownload(file_content, request)
    
    done = False
    while done is False:
        status, done = downloader.next_chunk()
        if status:
            print(f"下载进度: {int(status.progress() * 100)}%")
    
    return file_content.getvalue().decode('utf-8')

def read_regular_file(service, file_id):
    """
    读取常规文件内容
    
    Args:
        service: Drive 服务对象
        file_id: 文件 ID
    
    Returns:
        文件内容字节
    """
    request = service.files().get_media(fileId=file_id)
    file_content = io.BytesIO()
    downloader = MediaIoBaseDownload(file_content, request)
    
    done = False
    while done is False:
        status, done = downloader.next_chunk()
        if status:
            print(f"下载进度: {int(status.progress() * 100)}%")
    
    return file_content.getvalue()

def download_file(service, file_id, output_path):
    """
    下载文件到本地
    
    Args:
        service: Drive 服务对象
        file_id: 文件 ID
        output_path: 输出文件路径
    """
    # 获取文件信息
    file = service.files().get(fileId=file_id, fields='name, mimeType').execute()
    mime_type = file.get('mimeType', '')
    
    if 'vnd.google-apps' in mime_type:
        # Google Workspace 文件需要导出
        content = read_google_workspace_file(service, file_id, mime_type)
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(content)
    else:
        # 常规文件直接下载
        content = read_regular_file(service, file_id)
        with open(output_path, 'wb') as f:
            f.write(content)

def main():
    parser = argparse.ArgumentParser(description='读取 Google Drive 文件内容')
    parser.add_argument('--credentials', 
                       default='credentials.json',
                       help='OAuth 凭证文件路径')
    parser.add_argument('--token',
                       default='token.json',
                       help='Token 文件路径')
    parser.add_argument('--file-id',
                       help='文件 ID')
    parser.add_argument('--file-name',
                       help='文件名（会搜索匹配的文件）')
    parser.add_argument('--download',
                       help='下载到指定路径')
    parser.add_argument('--preview',
                       action='store_true',
                       help='预览前 500 个字符')
    
    args = parser.parse_args()
    
    if not args.file_id and not args.file_name:
        print("❌ 错误: 必须指定 --file-id 或 --file-name")
        parser.print_help()
        return 1
    
    try:
        # 获取凭证并构建服务
        creds = get_credentials(args.credentials, args.token)
        service = build_drive_service(creds)
        
        # 获取文件
        if args.file_name:
            file = get_file_by_name(service, args.file_name)
            if not file:
                print(f"❌ 未找到文件: {args.file_name}")
                return 1
            file_id = file['id']
            file_name = file['name']
            mime_type = file['mimeType']
        else:
            file_id = args.file_id
            # 获取文件信息
            file = service.files().get(fileId=file_id, fields='name, mimeType').execute()
            file_name = file.get('name', 'Unknown')
            mime_type = file.get('mimeType', '')
        
        print("=" * 80)
        print(f"读取文件: {file_name}")
        print(f"文件 ID: {file_id}")
        print(f"MIME 类型: {mime_type}")
        print("=" * 80)
        print()
        
        # 读取文件内容
        if 'vnd.google-apps' in mime_type:
            content = read_google_workspace_file(service, file_id, mime_type)
        else:
            content_bytes = read_regular_file(service, file_id)
            # 尝试解码为文本
            try:
                content = content_bytes.decode('utf-8')
            except UnicodeDecodeError:
                content = f"[二进制文件，大小: {len(content_bytes)} 字节]"
        
        # 处理输出
        if args.download:
            download_file(service, file_id, args.download)
            print(f"✅ 文件已下载到: {args.download}")
        elif args.preview:
            print("内容预览（前 500 字符）:")
            print("-" * 80)
            print(content[:500])
            if len(content) > 500:
                print("... (更多内容)")
            print("-" * 80)
        else:
            print("文件内容:")
            print("-" * 80)
            print(content)
            print("-" * 80)
        
        print()
        return 0
        
    except FileNotFoundError as e:
        print(f"❌ 错误: {e}")
        print()
        print("请先运行 `python auth_setup.py` 完成认证设置。")
        return 1
    except Exception as e:
        print(f"❌ 发生错误: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == '__main__':
    sys.exit(main())
