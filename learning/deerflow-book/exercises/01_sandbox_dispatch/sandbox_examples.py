"""教学用的两个类：通过返回文字模拟不同环境的读取行为。

它们是普通 Python 类，不是 DeerFlow 的真实 Sandbox 实现。
"""


class LocalSandboxDemo:
    def read_file(self, path: str) -> str:
        return f"本地实现：读取 {path}"


class ContainerSandboxDemo:
    def read_file(self, path: str) -> str:
        return f"容器实现：读取 {path}"
