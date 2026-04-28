from langchain.tools import tool
import re


@tool("ai_trace_detector")
def ai_trace_detector(file_path: str) -> str:
    """AI痕迹检测工具，检测正文中是否存在AI生成痕迹。

    Args:
        file_path: 正文文件路径

    Returns:
        检测报告
    """
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        return f"文件读取失败: {e}"

    issues = []
    paragraphs = [p.strip() for p in content.split("\n\n") if p.strip()]

    # 1. 段落等长检测
    if len(paragraphs) >= 5:
        lengths = [len(p) for p in paragraphs]
        avg_len = sum(lengths) / len(lengths)
        variance = sum((l - avg_len) ** 2 for l in lengths) / len(lengths)
        if variance < 500:
            issues.append("警告：段落长度过于均匀，疑似AI生成")

    # 2. 套话词密度
    filler_words = ["似乎", "可能", "或许", "大概", "仿佛", "好像", "一定程度上"]
    filler_count = sum(content.count(w) for w in filler_words)
    if filler_count > 5:
        issues.append(f"警告：套话词密度过高（发现{filler_count}个）")

    # 3. 公式化转折
    transition_words = ["然而", "不过", "与此同时", "尽管如此", "总而言之", "综上所述"]
    transition_count = sum(content.count(w) for w in transition_words)
    if transition_count > 3:
        issues.append(f"警告：公式化转折过多（发现{transition_count}个）")

    # 4. AI痕迹词
    ai_words = ["仿佛", "不禁", "宛如", "一丝", "抹去", "吞噬", "呢喃", "不由",
                "下意识", "微微", "陡然", "猛然", "骤然"]
    found_ai_words = [(w, content.count(w)) for w in ai_words if content.count(w) > 0]
    if found_ai_words:
        words_str = ", ".join(f"{w}({c})" for w, c in found_ai_words)
        issues.append(f"警告：发现AI痕迹词：{words_str}")

    # 5. 列表式结构检测
    list_patterns = [
        r"(?:首先|其次|再次|最后|第一|第二|第三|第四|第五)[，、：]",
        r"(?:一是|二是|三是|四是|五是)[，、：]",
    ]
    for pattern in list_patterns:
        matches = re.findall(pattern, content)
        if len(matches) > 2:
            issues.append("警告：检测到列表式结构（首先/其次/最后等）")
            break

    if issues:
        return "AI痕迹检测报告（发现问题）：\n" + "\n".join(f"- {issue}" for issue in issues)
    else:
        return "AI痕迹检测报告：未检测到明显AI痕迹。"
