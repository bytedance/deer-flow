from langchain.tools import tool
import re


@tool("post_write_validator")
def post_write_validator(file_path: str) -> str:
    """后写验证工具，检查正文格式是否符合规范。

    Args:
        file_path: 正文文件路径

    Returns:
        验证报告
    """
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        return f"文件读取失败: {e}"

    issues = []

    if re.search(r"^#{1,6}\s", content, re.MULTILINE):
        issues.append("错误：正文包含Markdown标题（#、##等）")

    if re.search(r"^\s*[-*+]\s", content, re.MULTILINE):
        issues.append("错误：正文包含列表项（-、*、+）")

    if re.search(r"^\s*\d+\.\s", content, re.MULTILINE):
        issues.append("错误：正文包含编号列表（1.、2.等）")

    if re.search(r"\*\*.*?\*\*", content):
        issues.append("错误：正文包含加粗标记（**）")

    if re.search(r"UPDATED_STATE|STATE_UPDATE|状态更新", content, re.IGNORECASE):
        issues.append("错误：正文包含状态更新标记")

    if '"' in content or "'" in content:
        issues.append('错误：正文包含英文引号，应使用中文引号\u201c\u201d')

    chinese_chars = len(re.findall(r"[\u4e00-\u9fff]", content))
    if chinese_chars < 1600:
        issues.append(f"警告：字数不足，当前{chinese_chars}字，要求1600字以上")

    if issues:
        return "验证未通过：\n" + "\n".join(f"- {issue}" for issue in issues)
    else:
        return f"验证通过。字数：{chinese_chars}字。"
