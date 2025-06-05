import os
import re
import json

from markitdown import MarkItDown


# Initialize FastMCP server for MarkItDown (SSE)

def extract_base64_images(input_string):
    """
    提取字符串中所有的base64图片信息
    
    Args:
        input_string (str): 输入的字符串
    
    Returns:
        tuple: (提取的图片信息列表, 删除匹配内容后的字符串)
    """
    # 正则表达式匹配 f"\n![{alt_text}](data:{content_type};base64,{b64_string})\n"
    pattern = r'\n?!\[([^\]]*)\]\(data:([^;]+);base64,([^)]+)\)\n?'

    # 找到所有匹配项
    matches = re.findall(pattern, input_string)

    # 构建结果列表
    result_list = []
    for match in matches:
        alt_text, content_type, b64_string = match
        image_info = {
            'type': 'uri',
            'alt_text': alt_text,
            'content_type': content_type,
            'uri': b64_string
        }
        result_list.append(image_info)

    # 删除所有匹配的字符串
    cleaned_string = re.sub(pattern, '', input_string)
    result_list.append(dict(
        type='text',
        text=cleaned_string
    ))

    return result_list

async def convert_to_markdown(uri: str) -> str:
    """Convert a resource described by an http:, https:, file: or data: URI to markdown"""
    return MarkItDown(enable_plugins=check_plugins_enabled()).convert_uri(uri).markdown


def check_plugins_enabled() -> bool:
    return os.getenv("MARKITDOWN_ENABLE_PLUGINS", "false").strip().lower() in (
        "true",
        "1",
        "yes",
    )

async def markitdown_parsing_doc(uri: str) -> str:
    """Convert a resource described by an http:, https:, file: or data: URI to markdown
    supported file types: [.doc, .docx, .ppt, .pptx, .xls, .xlsx]
    Parameters:
        uri: str, The uri of the resource to convert
    Returns:
        str, a json list of markdown content
    """
    # 支持word/PPT的图片, 不支持excel/pdf的图片
    md = MarkItDown(enable_plugins=False)
    result = md.convert(uri, keep_data_uris=True)           # attribute: title/markdown
    result = extract_base64_images(result.markdown)
    result = json.dumps(result, ensure_ascii=False)
    return result