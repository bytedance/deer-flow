#!/usr/bin/env python3
"""
Google Drive 集成 - 更新文件
"""
import os
import sys
import argparse

# 添加脚本目录到路径，以便导入 utils
script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, script_dir)

from utils import get_credentials, build_drive_service, get_mime_type
from googleapiclient.http import MediaFileUpload

def rename_file(service, file_id, new_name):
    """
    重命名文件
    
    Args:
        service: Drive 服务对象
        file_id: 文件 ID
        new_name: 新名称
    
    Returns:
        更新后的文件信息
    """
    file_metadata = {'name': new_name}
    updated_file = service.files().update(
        fileId=file_id,
        body=file_metadata,
        fields='id, name'
    ).execute()
    return updated_file

def move_file(service, file_id, new_folder_id):
    """
    移动文件到新文件夹
    
    Args:
        service: Drive 服务对象
        file_id: 文件 ID
        new_folder_id: 新文件夹 ID
    
    Returns:
        更新后的文件信息
    """
    # 获取当前父文件夹
    file = service.files().get(fileId=file_id, fields='parents').execute()
    previous_parents = ",".join(file.get('parents', []))
    
    # 移动文件
    updated_file = service.files().update(
        fileId=file_id,
        addParents=new_folder_id,
        removeParents=previous_parents,
        fields='id, name, parents'
    ).execute()
    return updated_file

def update_file_content(service, file_id, file_path):
    """
    更新文件内容
    
    Args:
        service: Drive 服务对象
        file_id: 文件 ID
        file_path: 本地文件路径
    
    Returns:
        更新后的文件信息
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"文件不存在: {file_path}")
    
    mime_type = get_mime_type(file_path)
    media = MediaFileUpload(file_path, mimetype=mime_type, resumable=True)
    
    updated_file = service.files().update(
        fileId=file_id,
        media_body=media,
        fields='id, name, size, modifiedTime'
    ).execute()
    return updated_file

def main():
    parser = argparse.ArgumentParser(description='更新 Google Drive 文件')
    parser.add_argument('--credentials', 
                       default='credentials.json',
                       help='OAuth 凭证文件路径')
    parser.add_argument('--token',
                       default='token.json',
                       help='Token 文件路径')
    parser.add_argument('file_id', help='文件 ID')
    
    # 子命令
    subparsers = parser.add_subparsers(dest='command', help='操作类型')
    
    # 重命名
    rename_parser = subparsers.add_parser('rename', help='重命名文件')
    rename_parser.add_argument('new_name', help='新文件名')
    
    # 移动
    move_parser = subparsers.add_parser('move', help='移动文件')
    move_parser.add_argument('folder_id', help='目标文件夹 ID')
    
    # 更新内容
    update_parser = subparsers.add_parser('content', help='更新文件内容')
    update_parser.add_argument('file', help='本地文件路径')
    
    args = parser.parse_args()
    
    if not args.command:
        print("❌ 错误: 必须指定操作类型")
        parser.print_help()
        return 1
    
    try:
        # 获取凭证并构建服务
        creds = get_credentials(args.credentials, args.token)
        service = build_drive_service(creds)
        
        # 获取原文件信息
        original_file = service.files().get(fileId=args.file_id, fields='name').execute()
        
        print("=" * 80)
        
        if args.command == 'rename':
            print(f"重命名文件: {original_file['name']} -> {args.new_name}")
            result = rename_file(service, args.file_id, args.new_name)
            print(f"✅ 文件重命名成功！")
            print(f"新名称: {result['name']}")
        
        elif args.command == 'move':
            print(f"移动文件: {original_file['name']}")
            result = move_file(service, args.file_id, args.folder_id)
            print(f"✅ 文件移动成功！")
            print(f"新父文件夹: {result.get('parents', [])}")
        
        elif args.command == 'content':
            print(f"更新文件内容: {original_file['name']}")
            result = update_file_content(service, args.file_id, args.file)
            print(f"✅ 文件内容更新成功！")
            print(f"大小: {result.get('size', 'N/A')} 字节")
            print(f"修改时间: {result.get('modifiedTime', 'N/A')}")
        
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
