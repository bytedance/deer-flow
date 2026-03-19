#   !/usr/bin/env python3


"""
批量将代码文件中的英文注释翻译为中文
支持 Python (.py), TypeScript (.ts, .tsx), JavaScript (.js, .jsx)
"""

import os
import re
from pathlib import Path

#    常见编程术语对照表


TERM_TRANSLATIONS = {
    #    通用术语


    "middleware": "中间件",
    "Middleware": "中间件",
    "agent": "代理",
    "Agent": "代理",
    "tool": "工具",
    "Tool": "工具",
    "config": "配置",
    "Config": "配置",
    "router": "路由器",
    "Router": "路由器",
    "memory": "内存",
    "Memory": "内存",
    "thread": "线程",
    "Thread": "线程",
    "state": "状态",
    "State": "状态",
    "prompt": "提示词",
    "Prompt": "提示词",
    "model": "模型",
    "Model": "模型",
    "chat": "聊天",
    "Chat": "聊天",
    "message": "消息",
    "Message": "消息",
    "session": "会话",
    "Session": "会话",
    "user": "用户",
    "User": "用户",
    "request": "请求",
    "Request": "请求",
    "response": "响应",
    "Response": "响应",
    
    #    技术术语


    "enabled": "已启用",
    "disabled": "已禁用",
    "default": "默认",
    "fallback": "回退",
    "error": "错误",
    "Error": "错误",
    "warning": "警告",
    "Warning": "警告",
    "success": "成功",
    "failure": "失败",
    "loading": "加载中",
    "save": "保存",
    "delete": "删除",
    "create": "创建",
    "update": "更新",
    "init": "初始化",
    "setup": "设置",
    "build": "构建",
    "run": "运行",
    "start": "开始",
    "stop": "停止",
    
    #    数据结构


    "list": "列表",
    "array": "数组",
    "object": "对象",
    "string": "字符串",
    "number": "数字",
    "boolean": "布尔值",
    "null": "空值",
    "undefined": "未定义",
    
    #    流程控制


    "if": "如果",
    "else": "否则",
    "while": "当",
    "for": "对于",
    "return": "返回",
    "break": "中断",
    "continue": "继续",
    
    #    其他常用词


    "available": "可用的",
    "current": "当前",
    "previous": "上一个",
    "next": "下一个",
    "total": "总计",
    "count": "计数",
    "index": "索引",
    "key": "键",
    "value": "值",
    "name": "名称",
    "type": "类型",
    "id": "标识符",
    "path": "路径",
    "url": "链接",
    "file": "文件",
    "directory": "目录",
    "folder": "文件夹",
}

def translate_simple_comment(text: str) -> str:
    """简单翻译注释文本（基于术语表）"""
    result = text
    #    按长度降序排序，优先匹配长词


    sorted_terms = sorted(TERM_TRANSLATIONS.items(), key=lambda x: len(x[0]), reverse=True)
    for en, zh in sorted_terms:
        #    使用正则确保完整单词匹配


        pattern = r'\b' + re.escape(en) + r'\b'
        result = re.sub(pattern, zh, result)
    return result

def process_python_file(file_path: Path):
    """处理 Python 文件"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
    except UnicodeDecodeError:
        return
    
    new_lines = []
    for line in lines:
        #    处理文档字符串


        if '"""' in line or "'''" in line:
            #    简单的文档字符串处理，保持结构


            new_lines.append(line)
        #    处理单行注释 #


        elif '#  ' in line:


            parts = line.split('#  ', 1)


            code_part = parts[0]
            comment_part = parts[1] if len(parts) > 1 else ''
            
            if comment_part.strip():
                #    翻译注释部分


                translated = translate_simple_comment(comment_part)
                new_lines.append(f"{code_part}#   {translated}\n")


            else:
                new_lines.append(line)
        else:
            new_lines.append(line)
    
    try:
        with 打开(file_path, 'w', encoding='utf-8') as f:
            f.writelines(new_lines)
        print(f"已处理：{file_path}")
    except Exception as e:
        print(f"写入失败 {file_path}: {e}")

def process_js_ts_file(file_path: Path):
    """处理 JavaScript/TypeScript 文件"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
    except UnicodeDecodeError:
        return
    
    #    处理单行注释 //


    def replace_single_line(match):
        prefix = match.group(1)
        comment = match.group(2)
        if comment.strip():
            translated = translate_simple_comment(comment)
            return f"{prefix}// {translated}"
        return match.group(0)
    
    content = re.sub(r'(.*?)//(.*)$', replace_single_line, content, flags=re.MULTILINE)
    
    #    处理多行注释 /* */ (简单处理)


    #    注意：这里不翻译多行注释内容，避免破坏格式


    
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"已处理：{file_path}")
    except Exception as e:
        print(f"写入失败 {file_path}: {e}")

def main():
    workspace = Path('/workspace')
    
    #    排除的目录


    exclude_dirs = {'node_modules', '.venv', '__pycache__', '.git', 'dist', 'build'}
    
    processed_count = 0
    
    #    遍历所有代码文件


    for file_path in workspace.rglob('*'):
        if file_path.is_file():
            #    检查是否在排除目录中


            if any(exclude in str(file_path) for exclude in exclude_dirs):
                continue
            
            suffix = file_path.suffix.lower()
            
            if suffix == '.py':
                process_python_file(file_path)
                processed_count += 1
            elif suffix in ['.ts', '.tsx', '.js', '.jsx']:
                process_js_ts_file(file_path)
                processed_count += 1
    
    print(f"\n完成！共处理 {processed_count} 个文件")

if __name__ == '__main__':
    main()
