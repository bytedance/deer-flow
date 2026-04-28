from langchain.tools import tool
import os
import re


@tool("context_assembler")
def context_assembler(
    book_name: str,
    chapter_group: str,
    target_chapter: int,
    task_dir: str = "",
) -> str:
    """将各整理Agent的输出组装为写作任务汇总MD。

    Args:
        book_name: 小说名称
        chapter_group: 章节组范围，如"第01-05章"
        target_chapter: 当前要写的章节号
        task_dir: 任务目录路径（可选，默认使用标准路径）

    Returns:
        组装后的写作任务汇总文件路径
    """
    if not task_dir:
        task_dir = f"book/{book_name}/02-正文/{chapter_group}/_task"

    task_dir = task_dir.replace("\\", "/")
    book_path = f"book/{book_name}"

    def read_file(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception:
            return ""

    # 读取各参考文件
    world_ref = read_file(f"{task_dir}/世界观参考.md")
    char_ref = read_file(f"{task_dir}/人物参考.md")
    item_ref = read_file(f"{task_dir}/道具参考.md")
    story_ref = read_file(f"{task_dir}/故事线参考.md")
    user_req = read_file(f"{task_dir}/用户要求.md")

    # 读取整组细纲
    outline_file = f"{book_path}/01-规划/chapters/{chapter_group}-细纲.md"
    outline_content = read_file(outline_file)

    # 读取规则
    rules = read_file(f"{book_path}/01-规划/book-rules.json")

    # 读取当前状态
    current_state = read_file(f"{book_path}/03-状态/current-state.md")

    # 读取伏笔
    hooks = read_file(f"{book_path}/03-状态/pending-hooks.md")

    # 读取前情提要（最近3章摘要）
    summaries = read_file(f"{book_path}/03-状态/chapter-summaries.md")
    # 提取最近3章摘要
    recent_summaries = ""
    if summaries:
        chapter_sections = re.findall(r"## 第\d+章 摘要.*?\n(?:[^#].*?\n)*", summaries, re.DOTALL)
        recent_summaries = "\n".join(chapter_sections[-3:])

    # 组装写作任务汇总
    output = f"""# 第{target_chapter}章 写作任务

## 当前章节
第{target_chapter}章（本组{chapter_group}）

## 用户要求
{user_req if user_req else "（无特殊要求，按细纲写作）"}

## 本组细纲（{chapter_group}）
{outline_content if outline_content else "（细纲未找到）"}

## 本书规则
{rules if rules else "（无特殊规则）"}

## 世界观参考
{world_ref if world_ref else "（无）"}

## 人物参考
{char_ref if char_ref else "（无）"}

## 道具参考
{item_ref if item_ref else "（无）"}

## 故事线参考
{story_ref if story_ref else "（无）"}

## 当前状态
{current_state if current_state else "（无）"}

## 伏笔提醒
{hooks if hooks else "（无）"}

## 前情提要
{recent_summaries if recent_summaries else "（无前情）"}
"""

    output_path = f"{task_dir}/写作任务汇总.md"
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(output)

    return output_path
