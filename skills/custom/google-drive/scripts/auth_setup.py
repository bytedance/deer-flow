#!/usr/bin/env python3
"""
Google Drive 集成 - 认证设置工具
用于初始化 OAuth 认证并获取访问凭证
"""
import os
import sys
import argparse

# 添加脚本目录到路径，以便导入 utils
script_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, script_dir)

from utils import get_credentials

def main():
    parser = argparse.ArgumentParser(description='Google Drive 认证设置工具')
    parser.add_argument('--credentials', 
                       default='credentials.json',
                       help='OAuth 凭证文件路径 (默认: credentials.json)')
    parser.add_argument('--token',
                       default='token.json',
                       help='Token 文件保存路径 (默认: token.json)')
    
    args = parser.parse_args()
    
    print("=" * 60)
    print("Google Drive 集成 - 认证设置工具")
    print("=" * 60)
    print()
    
    # 检查凭证文件是否存在
    if not os.path.exists(args.credentials):
        print(f"❌ 未找到凭证文件: {args.credentials}")
        print()
        print("请按照以下步骤获取凭证文件：")
        print()
        print("1. 访问 Google Cloud Console: https://console.cloud.google.com/")
        print("2. 创建新项目或选择现有项目")
        print("3. 搜索并启用 'Google Drive API'")
        print("4. 前往 'API 和服务' > '凭据'")
        print("5. 点击 '创建凭据' > 'OAuth 客户端 ID'")
        print("6. 选择应用类型为 '桌面应用'")
        print("7. 输入名称并点击 '创建'")
        print("8. 下载 JSON 凭证文件并保存为", args.credentials)
        print()
        return 1
    
    print(f"✅ 找到凭证文件: {args.credentials}")
    print()
    print("正在启动 OAuth 认证流程...")
    print("浏览器将会打开，请完成授权。")
    print()
    
    try:
        # 尝试获取凭证（这将触发 OAuth 流程）
        creds = get_credentials(args.credentials, args.token)
        
        print("=" * 60)
        print("✅ 认证成功！")
        print("=" * 60)
        print()
        print(f"Token 文件已保存到: {os.path.abspath(args.token)}")
        print()
        print("现在您可以使用其他 Google Drive 脚本了！")
        print()
        print("测试一下：运行 `python list_files.py` 来列出您的文件")
        print()
        
        return 0
        
    except Exception as e:
        print("=" * 60)
        print(f"❌ 认证失败: {e}")
        print("=" * 60)
        print()
        print("请检查：")
        print("1. 凭证文件是否正确")
        print("2. 您是否在浏览器中完成了授权")
        print("3. 网络连接是否正常")
        print()
        return 1

if __name__ == '__main__':
    sys.exit(main())
