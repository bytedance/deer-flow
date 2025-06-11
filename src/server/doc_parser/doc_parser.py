
import json
from mcp.server.fastmcp import FastMCP
import argparse


import requests
import json

import base64
from mimetypes import guess_type
from utils_textin import base64_to_bytes, textin_parsing_doc
from utils_markitdown import markitdown_parsing_doc
import filetype



async def parse_doc(uri: str) -> str:
    """Convert a resource described by an http:, https:, file: or data: URI to markdown
    supported file types: [.pdf, .doc, .docx, .ppt, .pptx, .xls, .xlsx]
    Parameters:
        uri: str, The uri of the resource to convert
    Returns:
        str, a json list of markdown content
    """
    input_bytes = base64_to_bytes(uri)
    kind = filetype.guess(input_bytes)
    # https://github.com/h2non/filetype.py
    markitdwon_type_list = [
        'application/msword', # .doc
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document', # .docx
        'application/vnd.ms-excel', # .xls
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', # .xlsx
        'application/vnd.ms-powerpoint', # .ppt
        'application/vnd.openxmlformats-officedocument.presentationml.presentation', # .pptx
    ]
    if kind.mime == 'application/pdf':
        return await textin_parsing_doc(uri)
    elif kind.mime in markitdwon_type_list:
        return await markitdown_parsing_doc(uri)
    else:
        raise ValueError(f"Unsupported file type: {kind.mime}")



if __name__ == "__main__":
    # Initialize and run the server
    import sys
    parser = argparse.ArgumentParser(description='Run MCP SSE-based server')
    parser.add_argument('--host', default='0.0.0.0', help='Host to bind to')
    parser.add_argument('--port', type=int, default=8010, help='Port to listen on')
    args = parser.parse_args()
    
    settings = dict(host=args.host, port=args.port)
    mcp = FastMCP("Document parsing", **settings)
    mcp.add_tool(parse_doc)
    mcp.run(transport='sse')