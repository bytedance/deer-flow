#!/usr/bin/env python3
"""
合并多次搜索结果
功能：去重、重新编号、生成统计信息
"""

import argparse
import json
import sys
from pathlib import Path
from typing import List, Dict


def merge_results(result_files: List[str]) -> Dict:
    """
    合并多个搜索结果文件
    
    Args:
        result_files: 搜索结果文件路径列表
        
    Returns:
        合并后的结果字典
    """
    all_articles = []
    seen_titles = set()
    duplicates_count = 0
    regions_searched = []
    
    for file_path in result_files:
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception as e:
            print(f"警告: 无法读取文件 {file_path}: {e}", file=sys.stderr)
            continue
        
        # 检查是否是清洗后的格式
        if data.get("cleaned") and "articles" in data:
            articles = data["articles"]
        elif "content" in data and "data" in data.get("content", {}):
            articles = data["content"]["data"].get("检索文章", [])
        else:
            print(f"警告: 文件 {file_path} 格式不识别", file=sys.stderr)
            continue
        
        # 记录搜索的地域（从文件名推断）
        if "gd" in file_path.lower() or "guangdong" in file_path.lower():
            regions_searched.append("广东省")
        elif "bj" in file_path.lower() or "beijing" in file_path.lower():
            regions_searched.append("北京市")
        elif "sh" in file_path.lower() or "shanghai" in file_path.lower():
            regions_searched.append("上海市")
        else:
            regions_searched.append("未知地区")
        
        # 去重合并
        for article in articles:
            title = article.get("文章标题", "")
            if title in seen_titles:
                duplicates_count += 1
                continue
            
            seen_titles.add(title)
            all_articles.append(article)
    
    # 重新编号段落
    global_id = 1
    total_paragraphs = 0
    for article in all_articles:
        paragraphs = article.get("段落", [])
        for p in paragraphs:
            p["id"] = global_id
            global_id += 1
            total_paragraphs += 1
    
    # 返回合并结果
    return {
        "cleaned": True,
        "articles": all_articles,
        "search_summary": {
            "total_searches": len(result_files),
            "regions": list(set(regions_searched)),
            "total_articles": len(all_articles),
            "total_paragraphs": total_paragraphs,
            "duplicates_removed": duplicates_count
        }
    }


def main():
    parser = argparse.ArgumentParser(
        description="合并多次搜索结果（去重+重新编号）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s result_gd.json result_bj.json result_sh.json
  %(prog)s result_gd.json result_bj.json --output merged.json
        """
    )
    parser.add_argument("files", nargs="+", help="搜索结果文件路径")
    parser.add_argument("--output", "-o", help="输出文件路径（可选，默认输出到标准输出）")
    
    args = parser.parse_args()
    
    # 合并结果
    merged = merge_results(args.files)
    
    # 输出
    output_json = json.dumps(merged, ensure_ascii=False, indent=2)
    
    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            f.write(output_json)
        print(f"✅ 已合并 {merged['search_summary']['total_searches']} 次搜索结果")
        print(f"   - 文章数: {merged['search_summary']['total_articles']}")
        print(f"   - 段落数: {merged['search_summary']['total_paragraphs']}")
        print(f"   - 去重: {merged['search_summary']['duplicates_removed']} 篇")
        print(f"   - 输出: {args.output}")
    else:
        print(output_json)


if __name__ == "__main__":
    main()
