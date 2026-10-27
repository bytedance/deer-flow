"""实作 01：导入类、创建实例、调用方法。

两个教学类都在 sandbox_examples.py 中。
本文件的 read_with_tool 是模拟工具上层调用的普通 Python 函数。

运行：python learning/deerflow-book/exercises/01_sandbox_dispatch/main.py
"""

# TODO 1：从 sandbox_examples 模块导入 LocalSandboxDemo 类。
from sandbox_examples import LocalSandboxDemo,ContainerSandboxDemo

def read_with_tool(sandbox, path: str) -> str:
    """这段调用代码在后续切换实例时保持不变。"""
    return sandbox.read_file(path)

def main():
    sandbox_local = LocalSandboxDemo()
    result_local = read_with_tool(sandbox= sandbox_local,path="report.txt")
    sandbox_con = ContainerSandboxDemo()
    result_con = read_with_tool(sandbox= sandbox_con , path="report02.txt")
    print (result_con)

if __name__ == "__main__":
    main()