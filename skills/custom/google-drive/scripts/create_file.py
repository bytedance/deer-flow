#!/usr/bin/env python3
"""
Google Drive 集成 - 创建文件
"""
import os
import sys
import argparse

# 添加脚本目录到路径，以便导入 utils
script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, script_dir)

from utils import (
    get_credentials, build_drive_service,
    get_mime_type, get_google_mime_type
)
from googleapiclient.http import MediaFileUpload

def create_folder(service, folder_name, parent_folder_id=None):
    """
    创建新文件夹
    
    Args:
        service: Drive 服务对象
        folder_name: 文件夹名称
        parent_folder_id: 父文件夹 ID（可选）
    
    Returns:
        创建的文件夹信息
    """
    file_metadata = {
        'name': folder_name,
        'mimeType': 'application/vnd.google-apps.folder'
    }
    
    if parent_folder_id:
        file_metadata['parents'] = [parent_folder_id]
    
    folder = service.files().create(body=file_metadata, fields='id, name').execute()
    return folder

def create_google_document(service, doc_type, name, parent_folder_id=None, content=None):
    """
    创建 Google Workspace 文档
    
    Args:
        service: Drive 服务对象
        doc_type: 文档类型 ('doc', 'sheet', 'slide')
        name: 文档名称
        parent_folder_id: 父文件夹 ID（可选）
        content: 初始内容（可选）
    
    Returns:
        创建的文档信息
    """
    mime_type = get_google_mime_type(doc_type)
    
    file_metadata = {
        'name': name,
        'mimeType': mime_type
    }
    
    if parent_folder_id:
        file_metadata['parents'] = [parent_folder_id]
    
    file = service.files().create(body=file_metadata, fields='id, name, webViewLink').execute()
    
    # TODO: 如果提供了内容，需要使用相应的 API 来添加内容
    # 这需要使用 Docs API, Sheets API 或 Slides API
    
    return file

def upload_file(service, file_path, name=None, parent_folder_id=None):
    """
    上传本地文件到 Google Drive
    
    Args:
        service: Drive 服务对象
        file_path: 本地文件路径
        name: 文件名称（可选，默认使用原文件名）
        parent_folder_id: 父文件夹 ID（可选）
    
    Returns:
        上传的文件信息
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"文件不存在: {file_path}")
    
    file_name = name or os.path.basename(file_path)
    mime_type = get_mime_type(file_path)
    
    file_metadata = {
        'name': file_name
    }
    
    if parent_folder_id:
        file_metadata['parents'] = [parent_folder_id]
    
    media = MediaFileUpload(file_path, mimetype=mime_type, resumable=True)
    
    file = service.files().create(
        body=file_metadata,
        media_body=media,
        fields='id, name, size, webViewLink'
    ).execute()
    
    return file

def main():
    parser = argparse.ArgumentParser(description='在 Google Drive 中创建文件')
    parser.add_argument('--credentials', 
                       default='credentials.json',
                       help='OAuth 凭证文件路径')
    parser.add_argument('--token',
                       default='token.json',
                       help='Token 文件路径')
    parser.add_argument('--folder-id',
                       help='父文件夹 ID（可选）')
    
    # 子命令
    subparsers = parser.add_subparsers(dest='command', help='操作类型')
    
    # 创建文件夹
    folder_parser = subparsers.add_parser('folder', help='创建文件夹')
    folder_parser.add_argument('name', help='文件夹名称')
    
    # 创建 Google 文档
    doc_parser = subparsers.add_parser('doc', help='创建 Google 文档')
    doc_parser.add_argument('type', choices=['doc', 'sheet', 'slide'], help='文档类型')
    doc_parser.add_argument('name', help='文档名称')
    
    # 上传文件
    upload_parser = subparsers.add_parser('upload', help='上传本地文件')
    upload_parser.add_argument('file', help='本地文件路径')
    upload_parser.add_argument('--name', help='文件名称（可选）')
    
    args = parser.parse_args()
    
    if not args.command:
        print("❌ 错误: 必须指定操作类型")
        parser.print_help()
        return 1
    
    try:
        # 获取凭证并构建服务
        creds = get_credentials(args.credentials, args.token)
        service = build_drive_service(creds)
        
        print("=" * 80)
        
        if args.command == 'folder':
            print(f"创建文件夹: {args.name}")
            result = create_folder(service, args.name, args.folder_id)
            print(f"✅ 文件夹创建成功！")
            print(f"文件夹名称: {result['name']}")
            print(f"文件夹 ID: {result['id']}")
        
        elif args.command == 'doc':
            type_names = {'doc': '文档', 'sheet': '表格', 'slide': '演示文稿'}
            print(f"创建 Google {type_names[args.type]}: {args.name}")
            result = create_google_document(service, args.type, args.name, args.folder_id)
            print(f"✅ {type_names[args.type]}创建成功！")
            print(f"名称: {result['name']}")
            print(f"ID: {result['id']}")
            print(f"链接: {result.get('webViewLink', 'N/A')}")
        
        elif args.command == 'upload':
            file_name = args.name or os.path.basename(args.file)
            print(f"上传文件: {file_name}")
            result = upload_file(service, args.file, args.name, args.folder_id)
            print(f"✅ 文件上传成功！")
            print(f"名称: {result['name']}")
            print(f"ID: {result['id']}")
            print(f"大小: {result.get('size', 'N/A')} 字节")
            print(f"链接: {result.get('webViewLink', 'N/A')}")
        
        print("=" * 80)
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
