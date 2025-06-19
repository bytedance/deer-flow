# tools/delegation_tools.py
"""委托工具"""

from typing import Annotated
from langchain_core.tools import tool

@tool
def handoff_to_planner(
    task_title: Annotated[str, "The title of the task to be handed off."],
    locale: Annotated[str, "The user's detected language locale (e.g., en-US, zh-CN)."],
):
    """Handoff to planner agent to do plan."""
    return {
        "action": "handoff", 
        "target": "planner", 
        "task_title": task_title, 
        "locale": locale
    }

@tool
def call_coder_agent(
    analysis_request: Annotated[str, "Specific coding request for the coder"]
):
    """
    Delegate task to coder agent for coding tasks. 
    Parameters:
        analysis_request: str, Specific code task description, if there are files to be processed, concatenate the file URI at the end of the task description, for example: file_path={URI}
    Returns:
        dict, Delegation information for the coder agent
    """
    return {
        "action": "delegate", 
        "target": "coder", 
        "request": analysis_request
    }

@tool
def call_researcher_agent(
    research_request: Annotated[str, "Specific research request for the researcher"],
    need_image: Annotated[str, "whether the search needs to return images"],
):
    """
    Delegate task to researcher agent for research and web searching. 
    Parameters:
        research_request: str, Specific research task description, clearly state the scope of the field you want to research.
        need_image: str, input true or false. true for return images
    Returns:
        dict, Delegation information for the researcher agent
    """
    return {
        "action": "delegate", 
        "target": "researcher", 
        "request": research_request, 
        "need_image": need_image
    }

@tool
def call_reader_agent(
    reader_request: Annotated[str, "Specific image reading process"],
    file_info: Annotated[str, "Image file path to read"],
):
    """
    Delegate task to reader agent for image understanding and vision question answering. 
    Parameters:
        reader_request: str, Specific image reader task description
        file_info: Image file path need reading, If multiple images need to be read, input them in the following format: file_path1,file_path2,file_path3
    Returns:
        dict, Delegation information for the reader agent
    """
    return {
        "action": "delegate", 
        "target": "reader", 
        "request": reader_request, 
        "file_info": file_info
    }

@tool
def call_rotate_tool(
    rotate_request: Annotated[str, "Specific image rotate angle."],
    file_info: Annotated[str, "Image file path to rotate"],
):
    """
    Rotate images that are difficult to read and require rotation, only support one image a time, but you can call this tool multiple times in one call.
    Parameters:
        rotate_request: Only support 3 angles: 90, -90, 180
            -90: counterclockwise rotation by 90 degrees
            90: clockwise rotation by 90 degrees
            180: clockwise rotation by 180 degrees
        file_info: Image file path to rotate
    Returns:
        dict, Rotation information
    """
    return {
        "action": "rotate", 
        "angle": rotate_request, 
        "file": file_info
    }