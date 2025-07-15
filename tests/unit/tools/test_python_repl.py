# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import pytest
from unittest.mock import patch
from src.tools.python_repl import python_repl_tool


class TestPythonReplTool:

    @patch("src.tools.python_repl.repl")
    @patch("src.tools.python_repl.logger")
    def test_successful_code_execution(self, mock_logger, mock_repl):
        # Arrange
        code = "print('Hello, World!')"
        expected_output = "Hello, World!\n"
        mock_repl.run.return_value = expected_output

        # Act
        result = python_repl_tool(code)

        # Assert
        mock_repl.run.assert_called_once_with(code)
        mock_logger.info.assert_called_with("Code execution successful")
        assert "Successfully executed:" in result
        assert code in result
        assert expected_output in result

    @patch("src.tools.python_repl.repl")
    @patch("src.tools.python_repl.logger")
    def test_invalid_input_type(self, mock_logger, mock_repl):
        # Arrange
        invalid_code = 123

        # Act & Assert - expect ValidationError from LangChain
        with pytest.raises(Exception) as exc_info:
            python_repl_tool(invalid_code)

        # Verify that it's a validation error
        assert "ValidationError" in str(
            type(exc_info.value)
        ) or "validation error" in str(exc_info.value)

        # The REPL should not be called since validation fails first
        mock_repl.run.assert_not_called()

    @patch("src.tools.python_repl.repl")
    @patch("src.tools.python_repl.logger")
    def test_code_execution_with_error_in_result(self, mock_logger, mock_repl):
        # Arrange
        code = "invalid_function()"
        error_result = "NameError: name 'invalid_function' is not defined"
        mock_repl.run.return_value = error_result

        # Act
        result = python_repl_tool(code)

        # Assert
        mock_repl.run.assert_called_once_with(code)
        mock_logger.error.assert_called_with(error_result)
        assert "Error executing code:" in result
        assert code in result
        assert error_result in result

    @patch("src.tools.python_repl.repl")
    @patch("src.tools.python_repl.logger")
    def test_code_execution_with_exception_in_result(self, mock_logger, mock_repl):
        # Arrange
        code = "1/0"
        exception_result = "ZeroDivisionError: division by zero"
        mock_repl.run.return_value = exception_result

        # Act
        result = python_repl_tool(code)

        # Assert
        mock_repl.run.assert_called_once_with(code)
        mock_logger.error.assert_called_with(exception_result)
        assert "Error executing code:" in result
        assert code in result
        assert exception_result in result

    @patch("src.tools.python_repl.repl")
    @patch("src.tools.python_repl.logger")
    def test_code_execution_raises_exception(self, mock_logger, mock_repl):
        # Arrange
        code = "print('test')"
        exception = RuntimeError("REPL failed")
        mock_repl.run.side_effect = exception

        # Act
        result = python_repl_tool(code)

        # Assert
        mock_repl.run.assert_called_once_with(code)
        mock_logger.error.assert_called_with(repr(exception))
        assert "Error executing code:" in result
        assert code in result
        assert repr(exception) in result

    @patch("src.tools.python_repl.repl")
    @patch("src.tools.python_repl.logger")
    def test_successful_execution_with_calculation(self, mock_logger, mock_repl):
        # Arrange
        code = "result = 2 + 3\nprint(result)"
        expected_output = "5\n"
        mock_repl.run.return_value = expected_output

        # Act
        result = python_repl_tool(code)

        # Assert
        mock_repl.run.assert_called_once_with(code)
        mock_logger.info.assert_any_call("Executing Python code")
        mock_logger.info.assert_any_call("Code execution successful")
        assert "Successfully executed:" in result
        assert code in result
        assert expected_output in result

    @patch("src.tools.python_repl.repl")
    @patch("src.tools.python_repl.logger")
    def test_empty_string_code(self, mock_logger, mock_repl):
        # Arrange
        code = ""
        mock_repl.run.return_value = ""

        # Act
        result = python_repl_tool(code)

        # Assert
        mock_repl.run.assert_called_once_with(code)
        mock_logger.info.assert_called_with("Code execution successful")
        assert "Successfully executed:" in result

    @patch("src.tools.python_repl.repl")
    @patch("src.tools.python_repl.logger")
    def test_logging_calls(self, mock_logger, mock_repl):
        # Arrange
        code = "x = 1"
        mock_repl.run.return_value = ""

        # Act
        python_repl_tool(code)

        # Assert
        mock_logger.info.assert_any_call("Executing Python code")
        mock_logger.info.assert_any_call("Code execution successful")
