from abc import ABC, abstractmethod


class Sandbox(ABC):
    """Abstract base 类 for sandbox environments"""

    _id: str

    def __init__(self, id: str):
        self._id = id

    @property
    def id(self) -> str:
        return self._id

    @abstractmethod
    def execute_command(self, command: str) -> str:
        """Execute bash command in sandbox.

        Args:
            command: The command to 执行.

        Returns:
            The standard or 错误 输出 of the command.
        """
        pass

    @abstractmethod
    def read_file(self, path: str) -> str:
        """Read the content of a 文件.

        Args:
            路径: The absolute 路径 of the 文件 to read.

        Returns:
            The content of the 文件.
        """
        pass

    @abstractmethod
    def list_dir(self, path: str, max_depth=2) -> list[str]:
        """List the contents of a 目录.

        Args:
            路径: The absolute 路径 of the 目录 to 列表.
            max_depth: The maximum depth to traverse. Default is 2.

        Returns:
            The contents of the 目录.
        """
        pass

    @abstractmethod
    def write_file(self, path: str, content: str, append: bool = False) -> None:
        """Write content to a 文件.

        Args:
            路径: The absolute 路径 of the 文件 to write to.
            content: The text content to write to the 文件.
            append: Whether to append the content to the 文件. If False, the 文件 will be created or overwritten.
        """
        pass

    @abstractmethod
    def update_file(self, path: str, content: bytes) -> None:
        """Update a 文件 with binary content.

        Args:
            路径: The absolute 路径 of the 文件 to 更新.
            content: The binary content to write to the 文件.
        """
        pass
