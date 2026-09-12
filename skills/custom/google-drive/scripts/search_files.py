#!/usr/bin/env python3
"""
Google Drive 集成 - 搜索文件
"""
import os
import sys
import argparse

# 添加脚本目录到路径，以便导入 utils
script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, script_dir)

from utils import get_credentials, build_drive_service, print_file_list

def build_search_query(keywords=None, folder_id=None, mime_type=None, 
                      modified_after=None, modified_before=None,
                      created_after=None, created_before=None,
                      name_contains=None, trashed=False):
    """
    构建搜索查询字符串
    
    Args:
        keywords: 全文搜索关键词
        folder_id: 限定在特定文件夹中搜索
        mime_type: 限定文件类型
        modified_after: 修改时间晚于 (RFC3339 格式)
        modified_before: 修改时间早于
        created_after: 创建时间晚于
        created_before: 创建时间早于
        name_contains: 文件名包含
        trashed: 是否包含已删除文件
    
    Returns:
        查询字符串
    """
    conditions = []
    
    if not trashed:
        conditions.append("trashed = false")
    
    if keywords:
        conditions.append(f"fullText contains '{keywords}'")
    
    if folder_id:
        conditions.append(f"'{folder_id}' in parents")
    
    if mime_type:
        if mime_type == 'folder':
            conditions.append("mimeType = 'application/vnd.google-apps.folder'")
        elif mime_type == 'doc':
            conditions.append("mimeType = 'application/vnd.google-apps.document'")
        elif mime_type == 'sheet':
            conditions.append("mimeType = 'application/vnd.google-apps.spreadsheet'")
        elif mime_type == 'slide':
            conditions.append("mimeType = 'application/vnd.google-apps.presentation'")
        elif mime_type == 'image':
            conditions.append("mimeType contains 'image/'")
        elif mime_type == 'video':
            conditions.append("mimeType contains 'video/'")
        elif mime_type == 'pdf':
            conditions.append("mimeType = 'application/pdf'")
        else:
            conditions.append(f"mimeType = '{mime_type}'")
    
    if modified_after:
        conditions.append(f"modifiedTime > '{modified_after}'")
    
    if modified_before:
        conditions.append(f"modifiedTime < '{modified_before}'")
    
    if created_after:
        conditions.append(f"createdTime > '{created_after}'")
    
    if created_before:
        conditions.append(f"createdTime < '{created_before}'")
    
    if name_contains:
        conditions.append(f"name contains '{name_contains}'")
    
    return " and ".join(conditions) if conditions else ""

def search_files(service, query, page_size=20, order_by='modifiedTime desc'):
    """
    搜索文件
    
    Args:
        service: Drive 服务对象
        query: 查询字符串
        page_size: 结果数量限制
        order_by: 排序方式
    
    Returns:
        文件列表
    """
    results = service.files().list(
        q=query,
        pageSize=page_size,
        orderBy=order_by,
        fields="files(id, name, mimeType, size, modifiedTime, createdTime)"
    ).execute()
    
    return results.get('files', [])

def main():
    parser = argparse.ArgumentParser(description='搜索 Google Drive 文件')
    parser.add_argument('--credentials', 
                       default='credentials.json',
                       help='OAuth 凭证文件路径')
    parser.add_argument('--token',
                       default='token.json',
                       help='Token 文件路径')
    
    # 搜索条件
    parser.add_argument('--query', '-q', help='全文搜索关键词')
    parser.add_argument('--folder-id', help='限定在特定文件夹中搜索')
    parser.add_argument('--type', '-t', 
                       choices=['folder', 'doc', 'sheet', 'slide', 'image', 'video', 'pdf'],
                       help='限定文件类型')
    parser.add_argument('--name', help='文件名包含')
    parser.add_argument('--modified-after', help='修改时间晚于 (RFC3339 格式)')
    parser.add_argument('--modified-before', help='修改时间早于')
    parser.add_argument('--created-after', help='创建时间晚于')
    parser.add_argument('--created-before', help='创建时间早于')
    parser.add_argument('--trashed', action='store_true', help='包含已删除文件')
    
    # 结果选项
    parser.add_argument('--limit', '-l', type=int, default=30, help='结果数量限制')
    parser.add_argument('--order-by',
                       choices=['name', 'modifiedTime', 'createdTime', 'size'],
                       default='modifiedTime',
                       help='排序方式')
    parser.add_argument('--asc', action='store_true', help='升序排列')
    
    args = parser.parse_args()
    
    # 构建排序字符串
    order_by = args.order_by
    order_by += " asc" if args.asc else " desc"
    
    try:
        # 获取凭证并构建服务
        creds = get_credentials(args.credentials, args.token)
        service = build_drive_service(creds)
        
        # 构建查询
        query = build_search_query(
            keywords=args.query,
            folder_id=args.folder_id,
            mime_type=args.type,
            modified_after=args.modified_after,
            modified_before=args.modified_before,
            created_after=args.created_after,
            created_before=args.created_before,
            name_contains=args.name,
            trashed=args.trashed
        )
        
        print("=" * 80)
        print("Google Drive 搜索")
        if query:
            print(f"查询条件: {query}")
        else:
            print("查询条件: (无限制，返回最近修改的文件)")
        print("=" * 80)
        print()
        
        # 执行搜索
        files = search_files(service, query, args.limit, order_by)
        
        if files:
            print_file_list(files)
            print()
            print(f"共找到 {len(files)} 个结果")
        else:
            print("未找到匹配的文件。")
        
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
