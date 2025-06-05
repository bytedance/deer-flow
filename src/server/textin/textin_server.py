
import json
from mcp.server.fastmcp import FastMCP
import argparse


import requests
import json

import base64
from mimetypes import guess_type
from filetype import guess


def get_file_content(filePath):
    with open(filePath, 'rb') as fp:
        return fp.read()

import base64

def base64_to_bytes(base64_str: str) -> bytes:
    """
    将Base64编码的字符串（可能带有data:前缀）转换为bytes对象
    参数: base64_str: Base64编码的字符串，可能带有类似"data:image/png;base64,"的前缀
    返回: 解码后的bytes对象
    """
    # 检查是否包含"base64,"前缀，并提取Base64部分
    if "base64," in base64_str:
        # 使用 split 提取 base64, 后面的部分
        try:
            base64_data = base64_str.split("base64,")[1]
        except IndexError:
            raise ValueError("无效的Base64 data URI格式")
    else:
        base64_data = base64_str
    
    # 移除可能的空白字符（如换行符、空格）
    base64_data = base64_data.strip()
    
    try:
        return base64.b64decode(base64_data)
    except base64.binascii.Error as e:
        raise ValueError("无效的Base64编码") from e

def format_data_uri(base64_str: str) -> str:
    """为Base64字符串添加正确的前缀（如 data:image/jpeg;base64,）
    使其成为标准的DataURI格式
    参数:  base64_str: 原始Base64编码字符串
    返回:  带正确前缀的完整Base64字符串
    """
    try:
        # 解码Base64获取二进制数据
        decoded_data = base64.b64decode(base64_str)
        
        # 方法1：使用filetype检测实际文件类型（更准确）
        file_type = guess(decoded_data)
        if file_type:
            mime = file_type.mime
        else:
            mime = 'application/octet-stream'
        
        # 构造完整前缀
        return f"data:{mime};base64,{base64_str}"
    
    except Exception as e:
        raise ValueError(f"Base64处理失败: {str(e)}")


class TextinOcr(object):
    def __init__(self, app_id, app_secret):
        self._app_id = app_id
        self._app_secret = app_secret
        self.host = 'https://api.textin.com'

    def recognize_pdf2md(self, input_bytes, options):
        """
        pdf to markdown
        :param options: request params
        :param input_bytes: bytes
        :param is_url: bool
        :return: response

        options = {
            'pdf_pwd': None,
            'dpi': 144,  # 设置dpi为144
            'page_start': 0,
            'page_count': 1000,  # 设置解析的页数为1000页
            'apply_document_tree': 0,
            'markdown_details': 1,
            'page_details': 0,  # 不包含页面细节信息
            'table_flavor': 'md',
            'get_image': 'none',
            'parse_mode': 'scan',  # 解析模式设为scan
        }
        """
        url = self.host + '/ai/service/v1/pdf_to_markdown'
        headers = {
            'x-ti-app-id': self._app_id,
            'x-ti-secret-code': self._app_secret
        }
        headers['Content-Type'] = 'application/octet-stream'

        respond = requests.post(url, data=input_bytes, headers=headers, params=options)
        print("request time: ", respond.elapsed.total_seconds())
        return json.loads(respond.text)

async def pdf_to_markdown(uri: str) -> str:
    """Parse a pdf file to markdown
    supported file types: [.pdf]
    Parameters:
        uri: str, The uri of the pdf file to parse
    Returns:
        str, a json list of pdf content
    """
    input_bytes = base64_to_bytes(uri)
    
    textin = TextinOcr('de83773ea32ff8271f05922c0e057ac7', '57864d9c5f89ccf3d048e8019e1ba3c6')

    # option 文档 https://www.textin.com/document/pdf_to_markdown
    result = textin.recognize_pdf2md(input_bytes, {
        'page_start': 0,
        'page_count': 1000,  # 设置解析页数为1000页
        'page_details': True,
        'table_flavor': 'html', # [md, html]
        'image_output_type': 'base64str',
        'get_image': 'objects',
        'parse_mode': 'auto',  # 设置解析模式 [scan, auto]
        'page_details': 0,  # 不包含页面细节
        'markdown_details': 1,
        'apply_document_tree': 1,
        'dpi': 216  # 分辨率设置为 [72, 144, 216] dpi
    })

    # 获取detail字段内容
    details = result['result']['detail']

    # 存储转换后的结果
    converted_results = []

    # 遍历并转换每个元素
    for item in details:
        item_type = item['type']
        
        if item_type == 'image':
            # 处理图片类型
            converted_results.append({
                'type': 'file_base64',
                'file_base64': format_data_uri(item['base64str'])
            })
        elif item_type in ['paragraph', 'table']:
            # 处理段落和表格类型
            converted_results.append({
                'type': 'text',
                'text': item['text']
            })
    return json.dumps(converted_results, ensure_ascii=False)



if __name__ == "__main__":
    # Initialize and run the server
    import sys
    parser = argparse.ArgumentParser(description='Run MCP SSE-based server')
    parser.add_argument('--host', default='0.0.0.0', help='Host to bind to')
    parser.add_argument('--port', type=int, default=8009, help='Port to listen on')
    args = parser.parse_args()
    
    settings = dict(host=args.host, port=args.port)
    mcp = FastMCP("textin", **settings)
    mcp.add_tool(pdf_to_markdown)
    mcp.run(transport='sse')