# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

"""
Entry point script for the DeerFlow project.
"""

import argparse
import asyncio
from src.fvg.common import  make_object_from_config
import json
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
    agent,
    question,
    files,
    config,
    debug=False,
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
            agent,
            user_input=user_input,
            debug=debug,
            enable_background_investigation=enable_background_investigation,
            stream_config=config["stream_config"]
        )
    )


def main(
    agent,
    config,
    debug=False,
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
        agent,
        question=initial_question,
        files=files,
        config=config,
        debug=debug,
        enable_background_investigation=enable_background_investigation,
    )

if __name__ == "__main__":
    # Set up argument parser
    parser = argparse.ArgumentParser(description="Run the Deer")
    parser.add_argument("-c", "--config-path", default="main.json", help="The path to the config file.")
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

    with open(args.config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    agent = make_object_from_config(config["agent"])

    os.makedirs("logs", exist_ok=True)
    if args.interactive:
        # Pass command line arguments to main function
        main(
            agent,
            config,
            debug=args.debug,
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
            agent,
            question=user_query,
            files=args.file,
            config=config,
            debug=args.debug,
            enable_background_investigation=args.enable_background_investigation,
        )
