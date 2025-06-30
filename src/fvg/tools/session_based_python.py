import contextlib
import fvg.common
import io
from langchain_core.tools import BaseTool
from pydantic import Field
import re


def sanitize_input(query: str) -> str:
    """Sanitize input to the python REPL.

    Remove whitespace, backtick & python (if llm mistakes python console as terminal)

    Args:
        query: The query to sanitize

    Returns:
        str: The sanitized query
    """

    # Removes `, whitespace & python from start
    query = re.sub(r"^(\s|`)*(?i:python)?\s*", "", query)
    # Removes whitespace & ` from end
    query = re.sub(r"(\s|`)*$", "", query)
    return query


class PythonREPLTool(BaseTool):
    """Tool for running python code in a REPL."""

    name: str = "Python_REPL"
    description: str = (
        "A Python shell. Use this to execute python commands. "
        "Input should be a valid python command. "
        "If you want to see the output of a value, you should print it out "
        "with `print(...)`."
    )
    sanitize_input: bool = True
    session_locals: dict = Field(default_factory=dict)

    def _run(self, query: str, run_manager=None):
        if self.sanitize_input:
            query = sanitize_input(query)

        exec_out = io.StringIO()
        try:
            with contextlib.redirect_stdout(exec_out):
                exec(
                    query, {},
                    fvg.common.get_session_local(
                        self.session_locals, run_manager)
                )
                return exec_out.getvalue()
        except Exception as e:
            return repr(e)
