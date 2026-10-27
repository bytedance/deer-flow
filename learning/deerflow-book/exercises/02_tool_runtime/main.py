"""D04 练习：工具的业务参数与框架注入的运行上下文。

函数签名已验证；当前继续实现函数体。
后续在已安装 DeerFlow 依赖的后端环境中验证，不直接使用宿主机 Python。
"""

from langchain.tools import tool

from deerflow.tools.types import Runtime
from deerflow.sandbox.tools import read_current_file_content


# 签名已通过检查：模型只看得到 path，runtime 由框架注入。
# TODO：导入 deerflow.sandbox.tools 中的 read_current_file_content。
# TODO：用 read_current_file_content(runtime, path) 取得原始文本。
# TODO：按 splitlines() 的规则返回行数；空文件返回 0。
@tool
def count_file_lines(path: str, runtime:Runtime) -> int:
    """统计当前用户会话中的文本文件行数。"""
    text = read_current_file_content(runtime,path)
    return len(text.splitlines())