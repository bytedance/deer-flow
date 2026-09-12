#!/usr/bin/env python3
"""
DKAG 素材召回接口脚本
用于根据查询关键词召回相关公文素材

使用深知可信搜索接口：/dependable/search/
"""

import argparse
import html
import json
import re
import sys
from pathlib import Path
from typing import Optional

import requests

# ========== DKAG 搜索限制配置 ==========
# 本 skill 专门处理公文写作场景

# 查询关键词长度限制
MAX_QUERY_LENGTH = 500          # 最大查询字符数
MIN_QUERY_LENGTH = 2            # 最小查询字符数

# 错误提示
QUERY_TOO_LONG_ERROR = f"错误：查询关键词过长，超过限制（最大 {MAX_QUERY_LENGTH} 字符）"
QUERY_TOO_SHORT_ERROR = f"错误：查询关键词过短，最少需要 {MIN_QUERY_LENGTH} 个字符"
# ==========================================

# 默认配置文件路径
CONFIG_FILE = Path(__file__).parent.parent / "config.ini"
# 固定基础 URL（新接口格式）
FIXED_BASE_URL = "https://open.dknowc.cn/dependable/search/"


def load_config(config_path: Optional[Path] = None) -> str:
    """
    从配置文件加载 API Key

    配置文件格式 (config.ini):
    [dkag]
    api_key=your_api_key_here
    """
    config_path = config_path or CONFIG_FILE

    if not config_path.exists():
        raise FileNotFoundError(
            f"配置文件不存在: {config_path}\n"
            f"请创建配置文件并添加你的 API Key:\n"
            f"  [dkag]\n"
            f"  api_key=your_api_key_here"
        )

    api_key = ''
    try:
        import configparser
        config = configparser.ConfigParser()
        config.read(config_path, encoding='utf-8')
        api_key = config.get('dkag', 'api_key', fallback='')
    except Exception:
        # 简单的文件读取方式（兼容无 configparser 的情况）
        with open(config_path, 'r', encoding='utf-8') as f:
            for line in f:
                if line.startswith('api_key='):
                    api_key = line.split('=', 1)[1].strip()

    if not api_key:
        raise ValueError("API Key 为空，请在配置文件中设置有效的 api_key")
    
    return api_key


def clean_dkag_response(api_response: dict) -> dict:
    """
    清洗 DKAG API 返回的数据

    清洗逻辑：
    1. 处理 HTML 转义字符（如 &nbsp; 等）
    2. 移除网页干扰词（如 "首页 > 打印"）
    3. 统一换行符并合并多余换行
    4. 合并多余的空格和制表符
    5. 为每个段落分配唯一 ID

    Args:
        api_response: DKAG API 原始返回的 JSON

    Returns:
        清洗后的结果字典
    """
    try:
        # 按照新接口路径定位文章列表
        # 新接口格式：content -> data -> 检索文章
        inner_content = api_response.get("content", {})
        
        # 兼容新接口的嵌套结构
        if "data" in inner_content:
            real_data = inner_content.get("data", {})
        else:
            real_data = inner_content
            
        articles = real_data.get("检索文章", [])
        
        # 提取 knowledgeBase 链接
        knowledge_base_url = inner_content.get("knowledgeBase", "")

        if not articles:
            return {
                "cleaned": True,
                "articles": [],
                "message": "未检索到相关参考文章",
                "knowledgeBase": knowledge_base_url
            }

        cleaned_articles = []
        global_id_counter = 1

        for art in articles:
            cleaned_art = {
                "文章标题": art.get("文章标题", "无标题"),
                "发布日期": art.get("发布日期", ""),
                "数据源": art.get("数据源", "未知来源"),
                "段落": []
            }

            # 遍历段落并清洗
            paragraphs = art.get("段落", [])
            for p in paragraphs:
                # 提取标题和内容
                p_title = p.get("标题", "").strip()
                p_content = p.get("内容", "").strip()

                # 合并标题和内容
                full_text = f"{p_title}\n{p_content}" if p_title else p_content

                # --- 清洗逻辑 ---
                # 1. 处理 HTML 转义字符 (如 &nbsp; 等)
                content = html.unescape(full_text)

                # 2. 移除特定的网页干扰词
                content = re.sub(r'首页\s*>\s*.*?\s*打印\s*\]', '', content, flags=re.DOTALL)
                content = re.sub(r'点击\s*\d+.*?次', '', content)
                content = re.sub(r'分享\s*到.*?$', '', content, flags=re.MULTILINE)

                # 3. 统一换行符并合并多余换行
                content = content.replace('\r', '\n')
                content = re.sub(r'\n+', '\n', content)

                # 4. 合并多余的空格和制表符
                content = re.sub(r'[ \t]+', ' ', content)
                content = content.strip()

                if content:
                    # 分配全局唯一的自增 ID
                    cleaned_art["段落"].append({
                        "id": global_id_counter,
                        "内容": content
                    })
                    global_id_counter += 1

            # 只有当文章清洗后仍有有效段落时才添加
            if cleaned_art["段落"]:
                cleaned_articles.append(cleaned_art)

        # 如果没有有效结果
        if not cleaned_articles:
            return {
                "cleaned": True,
                "articles": [],
                "message": "素材内容经过清洗后为空"
            }

        # 提取规范性文件清单（policyFiles）
        policy_files = real_data.get("policyFiles", [])

        # 返回清洗后结果
        return {
            "cleaned": True,
            "articles": cleaned_articles,
            "total_articles": len(cleaned_articles),
            "total_paragraphs": global_id_counter - 1,
            "knowledgeBase": knowledge_base_url,
            "policyFiles": policy_files
        }

    except Exception as e:
        # 返回报错信息方便排查
        return {
            "cleaned": False,
            "error": True,
            "message": f"数据清洗报错: {type(e).__name__} - {str(e)}"
        }


def dkag_search(
    query: str,
    area: Optional[str] = None,
    time: Optional[str] = None,
    api_key: Optional[str] = None,
    config_path: Optional[Path] = None,
    clean: bool = False,
    policy: bool = False,
    full: bool = False
) -> dict:
    """
    调用深知可信搜索接口召回素材

    API 文档：
    - 请求路径: https://open.dknowc.cn/dependable/search/
    - 请求方式: POST
    - Content-Type: application/json
    - 认证方式: api-key 请求头

    Args:
        query: 搜索关键词（必填，支持完整句子）
        area: 用户所属地域（可选，默认"中国"），如"广东省"、"北京市"
        time: 生效日期范围（可选），如"2026年"、"2025年08月"、"2025年08月15日"
        api_key: API 密钥（可选，如不传则从配置文件读取）
        config_path: 配置文件路径（可选）
        clean: 是否对返回结果进行数据清洗（默认 False）
        policy: 是否返回规范性文件清单policyFiles（默认 False）
        full: 是否返回文章全文（return_full_content，默认 False）

    Returns:
        搜索结果字典
    """
    # 验证查询关键词
    if len(query) > MAX_QUERY_LENGTH:
        return {
            "error": True,
            "message": QUERY_TOO_LONG_ERROR,
            "query_length": len(query),
            "max_length": MAX_QUERY_LENGTH
        }

    if len(query) < MIN_QUERY_LENGTH:
        return {
            "error": True,
            "message": QUERY_TOO_SHORT_ERROR,
            "query_length": len(query),
            "min_length": MIN_QUERY_LENGTH
        }

    # 获取 API Key
    if not api_key:
        api_key = load_config(config_path)

    # 构建完整 URL
    url = FIXED_BASE_URL

    # 构建请求体（新接口格式）
    payload = {
        "query": query,
        "eff_time": [time] if time else [""],
        "service_area": [area] if area else [""],
        "knowBase": True,
        "policy": policy,
        "return_full_content": full
    }

    # 构建请求头
    headers = {
        "Content-Type": "application/json",
        "api-key": api_key
    }

    # 发送请求
    try:
        response = requests.post(url, data=json.dumps(payload), headers=headers, timeout=30)
        response.raise_for_status()
        result = response.json()
        
        # 新接口返回结构：content.检索文章
        # 需要转换成旧接口的格式以保持兼容
        if "content" in result and "检索文章" in result.get("content", {}):
            # 包装成旧格式
            result = {
                "content": {
                    "data": result["content"]
                }
            }

        # 如果需要清洗数据
        if clean:
            return clean_dkag_response(result)
        return result
    except requests.exceptions.RequestException as e:
        return {
            "error": True,
            "message": f"请求失败: {str(e)}",
            "payload": payload,
            "url": url,
            "status_code": getattr(e.response, 'status_code', None) if hasattr(e, 'response') else None
        }


def main():
    """命令行入口"""
    parser = argparse.ArgumentParser(
        description="DKAG 素材召回接口（V2新接口）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s "在北京申请就业见习单位认定需要哪些材料"
  %(prog)s "留学人才来粤服务政策" --area 广东省
  %(prog)s "北京社保政策" --area 北京市 --json
        """
    )
    parser.add_argument("query", help="搜索关键词（支持完整句子）")
    parser.add_argument("--area", help="用户所属地域（默认: 中国），如: 广东省、北京市")
    parser.add_argument("--time", help="生效日期范围，如: 2026年、2025年08月、2025年08月15日")
    parser.add_argument("--api-key", help="API 密钥（可选，默认从配置文件读取）")
    parser.add_argument("--config", help=f"配置文件路径（默认: {CONFIG_FILE}）")
    parser.add_argument("--json", action="store_true", help="以 JSON 格式输出")
    parser.add_argument("--clean", action="store_true", help="对返回结果进行数据清洗（去除HTML转义、网页干扰词等）")
    parser.add_argument("--policy", action="store_true", help="返回规范性文件清单（policyFiles）")
    parser.add_argument("--full", action="store_true", help="返回文章全文（return_full_content）")

    args = parser.parse_args()

    # 调用搜索
    result = dkag_search(
        query=args.query,
        area=args.area,
        time=args.time,
        api_key=args.api_key,
        config_path=Path(args.config) if args.config else None,
        clean=args.clean,
        policy=args.policy,
        full=args.full
    )

    # 输出结果
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
