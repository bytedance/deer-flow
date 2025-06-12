# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""
Entry point script for the DeerFlow project.
"""

import argparse
import asyncio
import os

from InquirerPy import inquirer

from src.config.questions import BUILT_IN_QUESTIONS, BUILT_IN_QUESTIONS_ZH_CN
from src.workflow import run_agent_workflow_async

def get_all_file_paths(folder_path):
    file_paths = []
    for entry in os.listdir(folder_path):  # 遍历文件夹中的所有条目
        full_path = os.path.join(folder_path, entry)  # 获取完整路径
        if os.path.isfile(full_path):  # 判断是否为文件
            file_paths.append(full_path)
    return file_paths

def ask(
    question,
    files,
    debug=False,
    max_plan_iterations=1,
    max_step_num=3,
    enable_background_investigation=True,
):
    """Run the agent workflow with the given question.

    Args:
        question: The user's query or request
        debug: If True, enables debug level logging
        max_plan_iterations: Maximum number of plan iterations
        max_step_num: Maximum number of steps in a plan
        enable_background_investigation: If True, performs web search before planning to enhance context
    """
    if files:
        # get all file path from folder
        if len(files)==1 and os.path.isdir(files[0]):
            files = get_all_file_paths(files[0])

        user_input = [
            {'type': 'text', 'text': question}
        ]
        for f in files:
            user_input.append({'type': "file_url", 'file_url': {'url': f}})
    else:
        user_input = question
    asyncio.run(
        run_agent_workflow_async(
            user_input=user_input,
            debug=debug,
            max_plan_iterations=max_plan_iterations,
            max_step_num=max_step_num,
            enable_background_investigation=enable_background_investigation,
        )
    )


def main(
    debug=False,
    max_plan_iterations=1,
    max_step_num=3,
    enable_background_investigation=True,
):
    """Interactive mode with built-in questions.

    Args:
        enable_background_investigation: If True, performs web search before planning to enhance context
        debug: If True, enables debug level logging
        max_plan_iterations: Maximum number of plan iterations
        max_step_num: Maximum number of steps in a plan
    """
    # First select language
    language = inquirer.select(
        message="Select language / 选择语言:",
        choices=["English", "中文"],
    ).execute()

    # Choose questions based on language
    questions = (
        BUILT_IN_QUESTIONS if language == "English" else BUILT_IN_QUESTIONS_ZH_CN
    )
    ask_own_option = (
        "[Ask my own question]" if language == "English" else "[自定义问题]"
    )

    # Select a question
    initial_question = inquirer.select(
        message=(
            "What do you want to know?" if language == "English" else "您想了解什么?"
        ),
        choices=[ask_own_option] + questions,
    ).execute()

    if initial_question == ask_own_option:
        initial_question = inquirer.text(
            message=(
                "What do you want to know?"
                if language == "English"
                else "您想了解什么?"
            ),
        ).execute()
        files = inquirer.text(
            message=(
                "input files?"
                if language == "English"
                else "输入文件?"
            ),
        ).execute()
        files = files.split(';')
    # Pass all parameters to ask function
    ask(
        question=initial_question,
        files=files,
        debug=debug,
        max_plan_iterations=max_plan_iterations,
        max_step_num=max_step_num,
        enable_background_investigation=enable_background_investigation,
    )


if __name__ == "__main__":
    # Set up argument parser
    parser = argparse.ArgumentParser(description="Run the Deer")
    parser.add_argument("--query", nargs="*", help="The query to process")
    parser.add_argument("--file", nargs="*", help="upload files, you can upload multiple files seperated by space or upload a folder path")
    parser.add_argument(
        "--interactive",
        action="store_true",
        help="Run in interactive mode with built-in questions",
    )
    parser.add_argument(
        "--max_plan_iterations",
        type=int,
        default=1,
        help="Maximum number of plan iterations (default: 1)",
    )
    parser.add_argument(
        "--max_step_num",
        type=int,
        default=3,
        help="Maximum number of steps in a plan (default: 3)",
    )
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    parser.add_argument(
        "--no-background-investigation",
        action="store_false",
        dest="enable_background_investigation",
        help="Disable background investigation before planning",
    )

    args = parser.parse_args()

    if args.interactive:
        # Pass command line arguments to main function
        main(
            debug=args.debug,
            max_plan_iterations=args.max_plan_iterations,
            max_step_num=args.max_step_num,
            enable_background_investigation=args.enable_background_investigation,
        )
    else:
        # Parse user input from command line arguments or user input
        if args.query:
            user_query = " ".join(args.query)
        else:
            user_query = input("Enter your query: ")

        # Run the agent workflow with the provided parameters
        ask(
            question=user_query,
            files=args.file,
            debug=args.debug,
            max_plan_iterations=args.max_plan_iterations,
            max_step_num=args.max_step_num,
            enable_background_investigation=args.enable_background_investigation,
        )

# uv run main.py --query "使用analyzer中的docparse工具看文件中张国战的所有加班时长, plan只需要一个step" --file /mnt/afs/yaotiankuo/agents/deer-dev/tests/加班清单.xlsx
# uv run main.py --query "看文件中张国战的所有加班时长, plan只需要一个step" --file /mnt/afs/yaotiankuo/agents/deer-dev/tests/加班清单.xlsx
# main.py --query "看文件中张国战的所有加班时长, 使用analyzer调用mcp服务查看,不使用coder" --file /mnt/afs/yaotiankuo/agents/deer-dev/tests/加班清单.xlsx
# main.py --query 分析目前agent的最新研究，给一个详细的报告
# main.py --query "图中画着什么东西" --file /mnt/afs/yaotiankuo/agents/deer-dev/tests/ts.png
# main.py --query "看看他是哪个学校毕业的" --file /mnt/afs/yaotiankuo/agents/deer-main-dev/tests/test_cases/cv.pdf
# main.py --query "从图中能获取哪些现象和推论？" --file /mnt/afs/yaotiankuo/agents/deer-dev/tests/report.jpg

# main.py --query "有哪些同学严重偏科, 不使用coder和search，只使用doc_parse" --file /mnt/afs/yaotiankuo/agents/deer-dev/tests/成绩单.xlsx
# main.py --query " 图中中国玩具的的线上销售渠道有哪些？" --file /mnt/afs/yaotiankuo/agents/deer-dev/tests/sell.jpg

# main.py --query "Q1: 这些材料体现了什么交通事故，责任如何认定？ Q2: 涉及事故的白色小汽车在哪些位置发生明显损坏，如果维修的话需要多少费用？请结合图片和必要的搜索材料回答该问题" --file /mnt/afs/yaotiankuo/agents/deer-dev/tests/multi_images/car1.jpg /mnt/afs/yaotiankuo/agents/deer-dev/tests/multi_images/car2.jpg /mnt/afs/yaotiankuo/agents/deer-dev/tests/multi_images/car3.jpg

# main.py --query "微博评论中统计积极/消极占比，并尝试解读其原因, 不使用coder" --file /mnt/afs/yaotiankuo/agents/deer-main-dev/tests/test_cases/multi_files

# main.py --query "这些是商业医疗保险理赔材料，准确识别所有表格并整理成md输出" --file /mnt/afs/yaotiankuo/agents/deer-main-dev/tests/test_cases/rotate_img

# main.py --query "将第二个图转正，整理成md输出" --file /mnt/afs/yaotiankuo/agents/deer-main-dev/tests/test_cases/rotate_img


# main.py --query "搜索一下 attention block的结构图，再帮我讲解一下"