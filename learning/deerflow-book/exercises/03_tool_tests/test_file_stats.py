"""D05：为 count_file_lines 编写自动化测试。

先在练习目录完成，再将通过验收的测试整理到 backend/tests/。
普通三行文本、空文件和缺失文件三个测试已通过。
"""

from unittest.mock import patch

from deerflow.tools.file_stats import count_file_lines
import pytest

def test_count_file_lines_normal():
    path = "/mnt/user-data/uploads/sample.txt"
    runtime = object()  # 测试占位对象；这里的模拟读取不会访问真实运行上下文。

    # 临时让读取函数返回指定文本；离开 with 后自动恢复。
    with patch(
        "deerflow.tools.file_stats.read_current_file_content",
        return_value="alpha\nbeta\ngamma\n",
    )as mock_read:
        # @tool 包装后的对象用 .func 访问原来的 Python 函数。
        result = count_file_lines.func(path=path, runtime=runtime)
        mock_read.assert_called_once_with(runtime, path)
    assert result == 3


# 空文件：模拟读取成功但返回空字符串，检查工具返回 0。
def test_count_file_lines_empty():
    path = "/mnt/user-data/uploads/sample.txt"
    runtime = object()  # 测试占位对象；这里的模拟读取不会访问真实运行上下文。

    with patch(
        "deerflow.tools.file_stats.read_current_file_content",
        return_value="",
    ):
        result = count_file_lines.func(path=path,runtime=runtime)
    assert result == 0


# 缺失文件：模拟读取时抛出 FileNotFoundError，检查工具保留该异常。
def test_count_file_lines_missing():
    path = "/mnt/user-data/uploads/sample.txt"
    runtime = object()  # 测试占位对象；这里的模拟读取不会访问真实运行上下文。 
    with patch(
        "deerflow.tools.file_stats.read_current_file_content",
        side_effect=FileNotFoundError("文件不存在")
    ):
        with pytest.raises(FileNotFoundError):
            count_file_lines.func(path=path,runtime=runtime)
def test_count_file_lines_no_trailing_newline():
    path = "/mnt/user-data/uploads/sample.txt"
    runtime = object()  # 测试占位对象；这里的模拟读取不会访问真实运行上下文。

    with patch(
        "deerflow.tools.file_stats.read_current_file_content",
        return_value="alpha\nbeta",
    )as mock_read:
        result = count_file_lines.func(path=path,runtime=runtime)
        mock_read.assert_called_once_with(runtime,path)
    assert result == 2
def test_count_file_lines_blank_line():
    path = "/mnt/user-data/uploads/sample.txt"
    runtime = object()  # 测试占位对象；这里的模拟读取不会访问真实运行上下文。

    with patch(
        "deerflow.tools.file_stats.read_current_file_content",
        return_value="alpha\n\nbeta\n",
    )as mock_read:
        result = count_file_lines.func(path=path,runtime=runtime)
        mock_read.assert_called_once_with(runtime,path)
    assert result == 3
def test_count_file_lines_newline_only():
    path = "/mnt/user-data/uploads/sample.txt"
    runtime = object()  # 测试占位对象；这里的模拟读取不会访问真实运行上下文。

    with patch(
        "deerflow.tools.file_stats.read_current_file_content",
        return_value="\n",
    )as mock_read:
        result = count_file_lines.func(path=path,runtime=runtime)
        mock_read.assert_called_once_with(runtime,path)
    assert result == 1
def test_count_file_lines_model_parameters():
    schema = count_file_lines.tool_call_schema.model_json_schema()
    assert set(schema["properties"]) == {"path"}
    # TODO：断言 properties 的键只有 path
    # TODO：断言 required 列表只有 path
    assert schema["required"] == ["path"]