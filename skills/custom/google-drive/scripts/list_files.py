#!/usr/bin/env python3
"""
Google Drive 集成 - 列出文件和文件夹
"""
import os
import sys
import argparse

# 添加脚本目录到路径，以便导入 utils
script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, script_dir)

from utils import get_credentials, build_drive_service, print_file_list

def list_files(service, folder_id=None, page_size=10, order_by='modifiedTime desc'):
    """
    列出 Google Drive 中的文件
    
    Args:
        service: Drive 服务对象
        folder_id: 文件夹 ID（可选，None 表示根目录）
        page_size: 每页结果数量
        order_by: 排序方式
    
    Returns:
        文件信息列表
    """
    query = ""
    
    if folder_id:
        query = f"'{folder_id}' in parents"
    else:
        # 只显示根目录的文件，不显示垃圾和已删除文件
        query = "'root' in parents"
    
    # 排除已删除的文件
    query += " and trashed = false"
    
    results = service.files().list(
        q=query,
        pageSize=page_size,
        orderBy=order_by,
        fields="nextPageToken, files(id, name, mimeType, size, modifiedTime, createdTime, parents)"
    ).execute()
    
    files = results.get('files', [])
    
    # 处理分页（如果有更多结果）
    next_page_token = results.get('nextPageToken')
    while next_page_token and len(files) < page_size:
        results = service.files().list(
            q=query,
            pageSize=page_size - len(files),
            orderBy=order_by,
            fields="nextPageToken, files(id, name, mimeType, size, modifiedTime, createdTime, parents)",
            pageToken=next_page_token
        ).execute()
        files.extend(results.get('files', []))
        next_page_token = results.get('nextPageToken')
    
    return files

def list_folders(service):
    """
    列出所有文件夹
    
    Args:
        service: Drive 服务对象
    
    Returns:
        文件夹列表
    """
    query = "mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    
    results = service.files().list(
        q=query,
        pageSize=100,
        fields="files(id, name, modifiedTime)"
    ).execute()
    
    return results.get('files', [])

def main():
    parser = argparse.ArgumentParser(description='列出 Google Drive 文件和文件夹')
    parser.add_argument('--credentials', 
                       default='credentials.json',
                       help='OAuth 凭证文件路径')
    parser.add_argument('--token',
                       default='token.json',
                       help='Token 文件路径')
    parser.add_argument('--folder-id',
                       help='文件夹 ID（不指定则列出根目录）')
    parser.add_argument('--limit',
                       type=int,
                       default=20,
                       help='列出文件数量限制 (默认: 20)')
    parser.add_argument('--order-by',
                       choices=['name', 'modifiedTime', 'createdTime', 'size'],
                       default='modifiedTime',
                       help='排序方式 (默认: 修改时间)')
    parser.add_argument('--desc',
                       action='store_true',
                       default=True,
                       help='降序排列 (默认)')
    parser.add_argument('--asc',
                       action='store_true',
                       help='升序排列')
    parser.add_argument('--folders-only',
                       action='store_true',
                       help='只列出文件夹')
    
    args = parser.parse_args()
    
    # 构建排序字符串
    order_by = args.order_by
    if args.asc:
        order_by += " asc"
    else:
        order_by += " desc"
    
    try:
        # 获取凭证并构建服务
        creds = get_credentials(args.credentials, args.token)
        service = build_drive_service(creds)
        
        print("=" * 80)
        if args.folders_only:
            print("Google Drive - 文件夹列表")
            files = list_folders(service)
        else:
            location = f"文件夹 '{args.folder_id}'" if args.folder_id else "根目录"
            print(f"Google Drive - {location} 文件列表")
            files = list_files(service, args.folder_id, args.limit, order_by)
        
        print("=" * 80)
        print()
        
        if files:
            print_file_list(files)
            print()
            print(f"共找到 {len(files)} 个文件/文件夹")
        else:
            print("未找到文件。")
        
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
