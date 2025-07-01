import json
from copy import deepcopy
import logging
import os
import uuid

from src.llms.llm import get_llm_by_type
from src.utils.image_utils import create_message_with_base64_image

logger = logging.getLogger(__name__)

def file_to_text(file_path):

    from markitdown import MarkItDown

    md = MarkItDown(enable_plugins=False) # Set to True to enable plugins
    result = md.convert(file_path)

    return result

def image_to_caption(img_path):
    caption_input = [create_message_with_base64_image(
                text="请详细描述图片信息", 
                image_paths=img_path
            )]

    llm = get_llm_by_type("vision")
        
    response = llm.invoke(caption_input)
    return response


def file2resource(file: str) -> dict:
    """Convert a file to a resource dict.
    
    Args:
        file: The file to convert
    Returns:
        The resource
    """
    # todo
    logger.warning(f'file title and description not implemented, use filename as title and description')
    return {
        'uri': file,
        'title': os.path.basename(file),
        'description': file
    }

def resources2user_input(resources: list[dict]) -> str:
    """Convert a list of resources to a user input string.
    
    Args:
        resources: The list of resources
    Returns:
        The user input string
    """
    resources = deepcopy(resources)
    # [{
    #     'uri': file,
    #     'title': os.path.basename(file),
    #     'description': file
    # }]
    # res_str = json.dumps(resources, indent=2, ensure_ascii=False)

    res_str = "\nReference:\n"
    for idx, resource in enumerate(resources):
        file_extension = resource["uri"].split(".")[-1].lower()  # 获取文件扩展名并转为小写

        # 判断文件类型
        if file_extension in ["jpg", "jpeg", "png", "gif", "bmp", "webp"]:  # 图片文件类型
            file_content = image_to_caption(resource["uri"])
        elif file_extension in ["pdf", "docx", "pptx", "xlsx"]:
            file_content = file_to_text(resource["uri"]) 
        else:
            raise ValueError("未知文件类型")

        res_str += f"<file><id>{idx}</id><name>{resource["uri"]}</name><content>{file_content}\n</content></file>\n"

    return res_str
