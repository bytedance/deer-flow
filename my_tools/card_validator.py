from langchain.tools import tool
import json
import os
from typing import Optional


@tool("card_validator")
def card_validator(
    card_path: str,
    fix: bool = True,
    auto_create: bool = False,
    book_name: str = "",
    genre: str = "",
    concept: str = "",
    platform: str = "",
) -> str:
    """验证并规范化 card.json 文件格式。

    Args:
        card_path: card.json 文件路径
        fix: 是否自动修复格式问题（默认True）
        auto_create: 如果文件不存在是否自动创建（默认False）
        book_name: 自动创建时的书名
        genre: 自动创建时的类型
        concept: 自动创建时的一句话概念
        platform: 自动创建时的平台

    Returns:
        验证结果报告（包含是否通过、问题列表、修复后的内容）
    """
    card_path = card_path.replace("\\", "/")
    
    # 定义必填字段和类型
    REQUIRED_FIELDS = {
        "book_name": str,
        "genre": str,
        "concept": str,
        "platform": str,
        "status": str,
        "current_chapter": int,
        "target_chapters": int,
    }
    
    STATUS_VALUES = ["planning", "writing", "completed", "paused"]
    
    result = {
        "valid": True,
        "issues": [],
        "fixed": False,
        "content": None,
    }
    
    # 检查文件是否存在
    if not os.path.exists(card_path):
        if auto_create and book_name:
            card_data = {
                "book_name": book_name,
                "genre": genre or "未知",
                "concept": concept or "",
                "platform": platform or "",
                "status": "planning",
                "current_chapter": 0,
                "target_chapters": 0,
            }
            os.makedirs(os.path.dirname(card_path), exist_ok=True)
            with open(card_path, "w", encoding="utf-8") as f:
                json.dump(card_data, f, ensure_ascii=False, indent=2)
            result["fixed"] = True
            result["content"] = card_data
            return f"[OK] card.json 已创建：{card_path}\n\n内容：\n{json.dumps(card_data, ensure_ascii=False, indent=2)}"
        else:
            return f"[FAIL] 文件不存在：{card_path}\n提示：设置 auto_create=True 和 book_name 参数可自动创建"
    
    # 读取文件
    try:
        with open(card_path, "r", encoding="utf-8") as f:
            raw_content = f.read()
    except Exception as e:
        return f"[FAIL] 读取文件失败：{str(e)}"
    
    # 尝试解析 JSON
    try:
        card_data = json.loads(raw_content)
    except json.JSONDecodeError as e:
        result["valid"] = False
        result["issues"].append(f"JSON 解析失败：{str(e)}")
        if fix:
            # 尝试修复：移除注释
            cleaned = raw_content.replace("# ", "// ")
            try:
                card_data = json.loads(cleaned)
                result["issues"].append("已自动修复：移除注释")
                result["fixed"] = True
            except:
                return f"[FAIL] JSON 格式错误，无法解析：{str(e)}\n建议：手动修复 JSON 格式"
        else:
            return f"[FAIL] JSON 格式错误：{str(e)}"
    
    # 验证字段
    for field, field_type in REQUIRED_FIELDS.items():
        if field not in card_data:
            result["valid"] = False
            result["issues"].append(f"缺少必填字段：{field}")
        elif not isinstance(card_data[field], field_type):
            result["valid"] = False
            result["issues"].append(
                f"字段类型错误：{field} 应为 {field_type.__name__}，实际为 {type(card_data[field]).__name__}"
            )
            if fix:
                try:
                    if field_type == int:
                        card_data[field] = int(card_data[field])
                        result["fixed"] = True
                    elif field_type == str:
                        card_data[field] = str(card_data[field])
                        result["fixed"] = True
                except:
                    result["issues"].append(f"无法自动修复字段：{field}")
    
    # 验证 status 值
    if "status" in card_data and card_data["status"] not in STATUS_VALUES:
        result["valid"] = False
        result["issues"].append(
            f"status 值无效：{card_data['status']}，应为 {STATUS_VALUES} 之一"
        )
        if fix:
            card_data["status"] = "planning"
            result["fixed"] = True
    
    # 验证数字范围
    if "current_chapter" in card_data and card_data["current_chapter"] < 0:
        result["valid"] = False
        result["issues"].append("current_chapter 不能为负数")
        if fix:
            card_data["current_chapter"] = 0
            result["fixed"] = True
    
    if "target_chapters" in card_data and card_data["target_chapters"] < 0:
        result["valid"] = False
        result["issues"].append("target_chapters 不能为负数")
        if fix:
            card_data["target_chapters"] = 0
            result["fixed"] = True
    
    # 写入修复后的文件
    if fix and result["fixed"]:
        with open(card_path, "w", encoding="utf-8") as f:
            json.dump(card_data, f, ensure_ascii=False, indent=2)
        result["content"] = card_data
    
    # 生成报告
    if result["valid"] and not result["fixed"]:
        report = f"[OK] card.json 验证通过\n\n路径：{card_path}\n\n内容：\n{json.dumps(card_data, ensure_ascii=False, indent=2)}"
    elif result["fixed"]:
        report = f"[FIXED] card.json 已修复\n\n路径：{card_path}\n\n问题：\n" + "\n".join(
            f"- {issue}" for issue in result["issues"]
        ) + f"\n\n修复后内容：\n{json.dumps(card_data, ensure_ascii=False, indent=2)}"
    else:
        report = f"[FAIL] card.json 验证失败\n\n路径：{card_path}\n\n问题：\n" + "\n".join(
            f"- {issue}" for issue in result["issues"]
        ) + "\n\n建议：设置 fix=True 可自动修复"
    
    return report
